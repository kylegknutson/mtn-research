#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests"]
# ///
"""
research_peak.py — assemble the mechanical 80% of a report into a data-filled
skeleton, so the LLM only writes the narrative + judgment.

**Auth model:** the authenticated TR/GPX sweep stays an in-chat step driven by
the Playwright-MCP browser (already logged into all 3 sources — no second login,
ever). Run that first so `gpx/<slug>/` holds the track files; then this script
does everything else mechanically:

  • regenerate waypoint GPX (build_peak_gpx)
  • cluster analysis from peak_db (nearby unclimbed ranked, same-drainage)
  • combo stats (distance/gain range) from the swept tracks
  • drive-time Maps URL from the climber's home to the primary trailhead
  • emit docs/peaks/<slug>.md skeleton: frontmatter + Quick Stats + map embed
    + stats + cluster + TR-table placeholder + Sources-checked footer, with the
    judgment sections left as <!-- TODO --> blocks
  • print the map-build commands (CalTopo + regional + PNG) to run next

Idempotent: writes to <slug>.skeleton.md by default (won't clobber a real report).

Usage:
    # 1. (in chat) sweep GPX from all 3 sources → gpx/<slug>/
    # 2.
    scripts/research_peak.py --slug crestolita_broken_hand
    scripts/research_peak.py --slug <slug> --climber kyle --out docs/peaks/<slug>.md
"""
from __future__ import annotations
import argparse, math, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
sys.path.insert(0, str(ROOT / "scripts"))
from peak_db_client import peaks, peak_lists  # noqa: E402
from climber import climbed_ids  # noqa: E402

LIST_ID = "co_13_14ers"
RANGE_TO_REGIONAL = {
    "Sangre de Cristo": "VKGB00L", "Sawatch": "L5VH4BU", "San Juan": "06AR6BF",
    "Elk": "1G2G7DM", "Gore": "6E4GJV2", "Mosquito": "LECF68J",
    "Tenmile": "7QE01UK", "Front": "DLES5CC", "Weminuche": "7AQN6TS",
}


def hav_mi(la1, lo1, la2, lo2):
    R = 3958.8; p = math.pi / 180
    a = (math.sin((la2-la1)*p/2)**2 + math.cos(la1*p)*math.cos(la2*p)*math.sin((lo2-lo1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--climber", default="kyle")
    ap.add_argument("--out", help="Output path (default docs/peaks/<slug>.skeleton.md)")
    args = ap.parse_args()

    gdir = ROOT / "gpx" / args.slug
    cfg_path = gdir / "peaks.yml"
    if not cfg_path.exists():
        sys.exit(f"No {cfg_path}. Create it first (see build_peak_gpx.py).")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    obj_ids = cfg.get("objective_ids") or []

    by_id = {p["id"]: p for p in peaks()}
    climbed = climbed_ids(args.climber)   # climber-agnostic (peak_db or 14ers checklist)
    in_list = {r["peak_id"] for r in peak_lists() if r["list_id"] == LIST_ID}
    objs = [by_id[i] for i in obj_ids if i in by_id]
    if not objs:
        sys.exit("No objective peaks resolved from peaks.yml objective_ids.")

    # 1. waypoint GPX
    print("• regenerating waypoint GPX…")
    print(run([str(SCRIPTS / "build_peak_gpx.py"), "--slug", args.slug]).strip())

    # 2. combo stats over swept track files
    track_files = [f for f in sorted(gdir.glob("*.gpx"))
                   if "peaks_only" not in f.name and "landmarks" not in f.name]
    stats_line = "_no track files yet — run the in-chat GPX sweep first_"
    if track_files:
        out = run([str(SCRIPTS / "combo_stats.py"), "--slug", args.slug])
        for ln in out.splitlines():
            if "STATS_LINE:" in ln:
                stats_line = ln.split("STATS_LINE:", 1)[1].strip()

    # 3. cluster analysis
    rng = (objs[0].get("range") or "").strip()
    radius = float((cfg.get("nearby") or {}).get("radius_mi", 8))
    nearby = []
    for p in by_id.values():
        if p["id"] in obj_ids or p.get("state") != "CO" or not p.get("lat"): continue
        if p["id"] not in in_list or not p.get("ranked") or p.get("elevation_ft", 0) < 13000: continue
        if p["id"] in climbed: continue
        d = min(hav_mi(o["lat"], o["lon"], p["lat"], p["lon"]) for o in objs)
        if d <= radius:
            nearby.append((d, p))
    nearby.sort()

    # 4. drive time URL to primary trailhead
    th = next((lm for lm in (cfg.get("landmarks") or []) if lm.get("kind") == "trailhead"),
              (cfg.get("landmarks") or [None])[0])
    drive_url = drive_row = ""
    if th:
        out = run([str(SCRIPTS / "drive_time.py"), "--to", f'{th["lat"]},{th["lon"]}',
                   "--climber", args.climber, "--label", th["name"]])
        for ln in out.splitlines():
            if ln.startswith("| Drive"):
                drive_row = ln.strip()
            if "maps/dir" in ln and "http" in ln and not ln.startswith("|"):
                drive_url = ln.strip()

    regional = RANGE_TO_REGIONAL.get(rng, "_TBD_")

    # 5. emit skeleton
    def q(s): return s.strip('"')
    title = " + ".join(q(o["display_name"]) for o in objs)
    fm = ["---",
          f"image: maps/{args.slug}.png",
          f"range: {rng}",
          'drive_time: "TODO"',
          f'yds_class: "{objs[0].get("yds_class","TODO")}"',
          f'gain: "{stats_line if track_files else "TODO"}"',
          "status: unclimbed",
          f"regional_map_id: {regional}",
          "---", ""]

    qs = ["## Quick stats", "", "| | " + " | ".join(q(o["display_name"]) for o in objs) + " |",
          "|---|" + "---|" * len(objs)]
    def row(label, fn): return f"| {label} | " + " | ".join(fn(o) for o in objs) + " |"
    qs.append(row("Elevation (LiDAR)", lambda o: f"{o['elevation_ft']}'"))
    qs.append(row("Lat / Lon", lambda o: f"{o['lat']}, {o['lon']}"))
    qs.append(row("Weather", lambda o: f"[NOAA](https://forecast.weather.gov/MapClick.php?lat={o['lat']}&lon={o['lon']})"))
    qs.append(row("Class (standard)", lambda o: str(o.get("yds_class") or "TODO")))
    qs.append(row("Range", lambda o: o.get("range") or ""))
    qs.append(row("peak_db id", lambda o: str(o["id"])))

    cluster = ["## Cluster status", ""]
    if nearby:
        cluster.append(f"Nearby unclimbed ranked 13er+ within {radius:.0f} mi "
                       "(verify same-drainage vs different-drive before adding to the map):")
        for d, p in nearby[:15]:
            cluster.append(f"- {q(p['display_name'])} ({p['elevation_ft']}', {d:.1f} mi)")
    else:
        cluster.append(f"No unclimbed ranked 13er+ neighbors within {radius:.0f} mi — standalone objective.")

    body = [
        f"# {title}",
        "",
        "**Researched:** TODO   ·   **Report type:** TODO (single / day-trip / multi-day)",
        f"**CalTopo research map:** TODO   ·   **Regional map:** [{rng}](https://caltopo.com/m/{regional})",
        "**Status in DB:** " + ("all unclimbed" if all(o["id"] not in climbed for o in objs) else "mixed"),
        "",
        f"![Overview map](../maps/{args.slug}.png)",
        f"*[Interactive CalTopo map](TODO)*",
        "",
        "---", "",
        *qs, "",
        f"**Combo stats (from swept tracks):** {stats_line}",
        "", "---", "",
        *cluster,
        "", "---", "",
        "## Drive + approach", "",
        (drive_row or "| Drive from <home> | **TODO** |"),
        "", "---", "",
        "<!-- TODO: recommended route narrative (synthesize from the TRs; verify the",
        "     standard line vs technical variants — don't conflate them) -->",
        "", "## Conditions / season", "<!-- TODO -->",
        "", "## Permits / access", "<!-- TODO -->",
        "", "## Cell coverage", "<!-- TODO: query 14ers cell DB + geographic reasoning -->",
        "", "---", "",
        "## Trip reports & GPX (all three sources)",
        "<!-- TODO: fill TR tables per source from the in-chat sweep -->",
        "",
        f"**Sources checked:** 14ers.com · listsofjohn.com · peakbagger.com",
        "", "---", "",
        "## TL;DR", "<!-- TODO -->", "",
    ]

    out_path = Path(args.out) if args.out else (ROOT / "docs" / "peaks" / f"{args.slug}.skeleton.md")
    out_path.write_text("\n".join(fm + body) + "\n")
    print(f"\n✓ skeleton → {out_path.relative_to(ROOT)}")
    print(f"  objective peaks: {len(objs)} · nearby ranked unclimbed: {len(nearby)} · track files: {len(track_files)}")

    print("\nNext — build the maps (side-effectful; run once):")
    print(f"  scripts/gpx_to_caltopo.py --gpx-dir gpx/{args.slug} --new-map \"Research: {title}\" --no-dedupe")
    print(f"  scripts/sync_to_regional.py --slug {args.slug} --map-id {regional}")
    print(f"  scripts/make_overview_map.py {args.slug}")
    print("Then: wire the map ID into the report, fill the TODO narrative, rename off .skeleton.md, commit.")


if __name__ == "__main__":
    main()
