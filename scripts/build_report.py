#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests"]
# ///
"""
build_report.py — run the whole mechanical report chain in one allowlisted call.

The point: after the in-chat Playwright GPX sweep (+ ingest_gpx) and scaffold,
EVERYTHING mechanical happens inside this one script — so the per-step `mkdir` /
`cp` / individual-script prompts disappear. The LLM only writes the narrative
prose between the two phases.

Two phases:

  # PHASE 1 (data + maps): waypoints, your CalTopo cross-ref, combo stats,
  # drive time, overview PNG, new CalTopo research map, regional-map sync.
  scripts/build_report.py --slug star_peak_group --title "Star Peak Group" --climber kyle
      → prints caltopo_id, regional_id, PNG path, combo stats, drive-time line.
      (LLM then writes docs/peaks/<slug>.md using those values.)

  # PHASE 2 (finalize): inject other-climber status, regen index, run QA gates.
  scripts/build_report.py --slug star_peak_group --finalize

Re-running phase 1 with --caltopo-id <ID> appends to the existing research map
instead of creating a duplicate.

Prereqs for phase 1: gpx/<slug>/peaks.yml (scaffold_report.py) + the swept
track GPX already in gpx/<slug>/ (ingest_gpx.py). peak_db + CalTopo creds local.
"""
from __future__ import annotations
import argparse, re, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")

RANGE_TO_REGIONAL = {
    "Sangre de Cristo": "VKGB00L", "Sawatch": "L5VH4BU", "San Juan": "06AR6BF",
    "Elk": "1G2G7DM", "Gore": "6E4GJV2", "Mosquito": "LECF68J",
    "Tenmile": "7QE01UK", "Front": "DLES5CC", "Weminuche": "7AQN6TS",
    "Eastern White Mountains": "UDK6ETR", "Western White Mountains": "UDK6ETR",
    "Carter-Moriah Range": "UDK6ETR", "Presidential Range": "UDK6ETR",
}


def run(cmd, **kw):
    print(f"\n$ {' '.join(str(c) for c in cmd)}")
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode != 0 and r.stderr:
        print(r.stderr.rstrip())
    return r


def regional_for(slug: str) -> tuple[str | None, str | None]:
    from peak_db_client import peaks
    cfg = yaml.safe_load((ROOT / "gpx" / slug / "peaks.yml").read_text())
    oid = cfg["objective_ids"][0]
    rng = next((p["range"] for p in peaks() if p["id"] == oid), None)
    return rng, RANGE_TO_REGIONAL.get(rng)


def primary_th(slug: str):
    cfg = yaml.safe_load((ROOT / "gpx" / slug / "peaks.yml").read_text())
    for lm in cfg.get("landmarks", []):
        if lm.get("kind", "trailhead") == "trailhead":
            return lm
    return (cfg.get("landmarks") or [None])[0]


def data_phase(args):
    slug = args.slug
    gdir = ROOT / "gpx" / slug
    if not (gdir / "peaks.yml").exists():
        sys.exit(f"no {gdir}/peaks.yml — run scaffold_report.py first")

    rng, regional = regional_for(slug)
    title = args.title or slug.replace("_", " ").title()

    run([SCRIPTS / "build_peak_gpx.py", "--slug", slug])

    # Multi-day trip: draw the road between camps on the PNG (≥2 trailheads).
    cfg = yaml.safe_load((gdir / "peaks.yml").read_text())
    n_th = sum(1 for lm in cfg.get("landmarks", []) if lm.get("kind", "trailhead") == "trailhead")
    if n_th >= 2:
        run([SCRIPTS / "build_drive_route.py", "--slug", slug])

    if regional:
        run([SCRIPTS / "caltopo_mytracks.py", "--slug", slug, "--maps", regional,
             "--margin-mi", str(args.mytracks_margin)])
    run([SCRIPTS / "combo_stats.py", "--slug", slug])

    th = primary_th(slug)
    if th:
        run([SCRIPTS / "drive_time.py", "--to", f'{th["lat"]},{th["lon"]}',
             "--climber", args.climber, "--label", th.get("name", "")])

    run([SCRIPTS / "make_overview_map.py", slug, "--title", title])

    # CalTopo research map: new, or append to an existing one
    if args.caltopo_id:
        ct = run([SCRIPTS / "gpx_to_caltopo.py", "--gpx-dir", str(gdir),
                  "--map-id", args.caltopo_id, "--sharing", "URL"])
        caltopo_id = args.caltopo_id
    else:
        ct = run([SCRIPTS / "gpx_to_caltopo.py", "--gpx-dir", str(gdir),
                  "--new-map", f"Research: {title}", "--sharing", "URL"])
        m = re.search(r"caltopo\.com/m/(\w+)", ct.stdout or "")
        caltopo_id = m.group(1) if m else None

    # Summit markers: gpx_to_caltopo dedupes markers account-wide, so the per-
    # report map's summit markers get SKIPPED when they already exist in the
    # regional map. Add them explicitly as peak/#39FF14 (--no-dedupe) so the
    # research map always shows its objectives.
    if caltopo_id:
        run([SCRIPTS / "gpx_to_caltopo.py", "--gpx", str(gdir / f"{slug}_peaks_only.gpx"),
             "--map-id", caltopo_id, "--marker-symbol", "peak", "--color", "#39FF14", "--no-dedupe"])

    if regional:
        run([SCRIPTS / "sync_to_regional.py", "--slug", slug, "--map-id", regional])

    print("\n" + "=" * 60)
    print("BUILD SUMMARY — paste these into the report frontmatter/body:")
    print(f"  slug:            {slug}")
    print(f"  range:           {rng}")
    print(f"  caltopo_id:      {caltopo_id or '??? (parse from output above)'}")
    print(f"  regional_map_id: {regional}")
    print(f"  image:           maps/{slug}.png")
    print("  (combo stats + drive-time line printed above)")
    print("Next: write docs/peaks/%s.md, then run --finalize." % slug)
    print("=" * 60)


def finalize_phase(args):
    print("== finalize: inject climber status, regen index + peak map, run QA gates ==")
    run([SCRIPTS / "climber_status.py"])
    run([SCRIPTS / "gen_index.py"])
    run([SCRIPTS / "gen_peak_map.py"])
    fails = []
    # Pixel gates (track present / basemap / clipping) + report source-check +
    # ROUTE-GEOMETRY gates: check_route_geometry catches recommended-route
    # teleports (a straight-line jump the pixel gates can't see — Kyle caught one
    # by eye 2026-06-15), check_route_stats catches optimistic headline mileage.
    gates = [
        ["check_reports.py"],
        ["check_maps.py"],
        ["check_map_extents.py"],
        ["check_route_geometry.py"],
        ["check_route_stats.py", "--strict"],
        ["check_class.py", "--strict"],   # SAFETY: class >= hardest objective's summit class
    ]
    for chk in gates:
        r = run([SCRIPTS / chk[0], *chk[1:]])
        if r.returncode != 0:
            fails.append(chk[0])
    print("\n" + "=" * 60)
    print("FINALIZE: " + ("ALL GATES PASS ✓" if not fails else "FAILED: " + ", ".join(fails)))
    print("Next: review the report + PNG, then `git add` / commit / push.")
    print("=" * 60)
    sys.exit(1 if fails else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--climber", default="kyle")
    ap.add_argument("--caltopo-id", help="append to this existing CalTopo map instead of creating a new one")
    ap.add_argument("--mytracks-margin", type=float, default=1.0,
                    help="bbox margin (mi) for caltopo_mytracks cross-ref (default 1.0, tighter to avoid off-objective tracks)")
    ap.add_argument("--finalize", action="store_true")
    args = ap.parse_args()
    if args.finalize:
        finalize_phase(args)
    else:
        data_phase(args)


if __name__ == "__main__":
    main()
