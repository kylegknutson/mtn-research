#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
build_trip_day_routes.py — one composed recommended route PER DAY for a multi-day trip.

A single-day report has one recommended route; a multi-day Trip must have one route
PER DAY (the day clusters can be miles apart, with no track between them — there is
no single composed line). This reads per-day objective assignments from the trip's
gpx/<slug>/peaks.yml `days:` block, and for each day:
  1. writes a per-day objectives file (subset of <slug>_peaks_only.gpx),
  2. picks that day's trailhead (nearest landmark TH to the day's peaks),
  3. calls build_recommended_route.py --peaks-only <subset> --start <th> --out
     gpx/<slug>/day_<label>_recommended.gpx
so make_overview_map / gen_peak_map (which glob *recommended*.gpx) draw every day.

peaks.yml must define `days:` — each entry has `label` and `objective_ids` (a subset
of the trip's objective_ids), e.g.:

    objective_ids: [607, 633, 488, 796, 654]
    days:
      - {label: "Bennett",     objective_ids: [607]}
      - {label: "Summit trio", objective_ids: [488, 796, 654]}
      - {label: "Conejos",     objective_ids: [633]}

The day's <slug>_peaks_only.gpx waypoints are aligned to objective_ids by ORDER
(build_peak_gpx emits them in objective_ids order), so a day's objective_ids select
its waypoints by index.

Usage:
    scripts/build_trip_day_routes.py south_san_juans_3day
    scripts/build_trip_day_routes.py south_san_juans_3day --no-dem   # faster smoke test
"""
from __future__ import annotations
import argparse, math, re, subprocess, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
SCRIPTS = ROOT / "scripts"
NS = "{http://www.topografix.com/GPX/1/1}"


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def parse_waypoints(path: Path):
    root = ET.parse(path).getroot()
    out = []
    for w in root.iter(NS + "wpt"):
        n = w.find(NS + "name"); e = w.find(NS + "ele"); s = w.find(NS + "sym")
        out.append({"lat": float(w.get("lat")), "lon": float(w.get("lon")),
                    "name": n.text if n is not None else "",
                    "ele": e.text if e is not None and e.text else None,
                    "sym": s.text if s is not None and s.text else "peak"})
    return out


def write_peaks_only(path: Path, wpts: list[dict]):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="build_trip_day_routes.py" '
             'xmlns="http://www.topografix.com/GPX/1/1">']
    for w in wpts:
        ele = f"<ele>{w['ele']}</ele>" if w.get("ele") else ""
        lines.append(f'<wpt lat="{w["lat"]:.5f}" lon="{w["lon"]:.5f}">{ele}'
                     f'<name>{w["name"]}</name><sym>{w.get("sym","peak")}</sym></wpt>')
    lines.append("</gpx>")
    path.write_text("\n".join(lines) + "\n")


def slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def trailheads(cfg: dict, d: Path):
    """(lat, lon, name) trailheads from peaks.yml landmarks (kind: trailhead),
    falling back to all landmark waypoints."""
    ths = [(l["lat"], l["lon"], l.get("name", "TH"))
           for l in (cfg.get("landmarks") or [])
           if l.get("kind") == "trailhead" and l.get("lat") is not None]
    if not ths:
        lm = next(d.glob("*landmark*.gpx"), None)
        if lm:
            ths = [(w["lat"], w["lon"], w["name"]) for w in parse_waypoints(lm)]
    return ths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--no-dem", action="store_true", help="pass through (noisy gain; faster)")
    ap.add_argument("--keep-subsets", action="store_true", help="don't delete the per-day objective files")
    args = ap.parse_args()

    d = GPX / args.slug
    yml = d / "peaks.yml"
    if not yml.exists():
        sys.exit(f"ERROR: {yml} not found")
    cfg = yaml.safe_load(yml.read_text()) or {}
    days = cfg.get("days")
    if not days:
        sys.exit(f"ERROR: {yml} has no `days:` block — add per-day objective_ids "
                 f"(see this script's docstring). Single-day reports use build_recommended_route.py.")
    full_ids = cfg.get("objective_ids") or []
    pk = next(d.glob("*peaks_only*.gpx"), None)
    if not pk:
        sys.exit("ERROR: no *_peaks_only.gpx")
    wpts = parse_waypoints(pk)
    if len(wpts) != len(full_ids):
        sys.exit(f"ERROR: {pk.name} has {len(wpts)} waypoints but peaks.yml has "
                 f"{len(full_ids)} objective_ids — can't align by index.")
    id_to_wpt = dict(zip(full_ids, wpts))
    ths = trailheads(cfg, d)

    built = []
    for day in days:
        label = day["label"]; ids = day["objective_ids"]
        sub = [id_to_wpt[i] for i in ids if i in id_to_wpt]
        if not sub:
            print(f"  WARN: day {label!r} — no matching objectives, skipped"); continue
        clat = sum(w["lat"] for w in sub) / len(sub)
        clon = sum(w["lon"] for w in sub) / len(sub)
        if not ths:
            sys.exit(f"ERROR: no trailheads to start day {label!r} from")
        th = min(ths, key=lambda t: hav(clat, clon, t[0], t[1]))
        slug_label = slugify(label)
        subset_f = d / f"day_{slug_label}_peaks_only.gpx"   # 'peaks_only' → excluded as a source track
        out_f = d / f"day_{slug_label}_recommended.gpx"
        write_peaks_only(subset_f, sub)
        cmd = [str(SCRIPTS / "build_recommended_route.py"), args.slug,
               "--peaks-only", str(subset_f), "--start", f"{th[0]},{th[1]}",
               "--out", str(out_f)]
        if args.no_dem:
            cmd.append("--no-dem")
        print(f"\n=== day: {label} → {', '.join(w['name'].split(' (')[0] for w in sub)} "
              f"| start {th[2]} ===")
        r = subprocess.run(cmd)
        if not args.keep_subsets:
            subset_f.unlink(missing_ok=True)
        if r.returncode != 0:
            sys.exit(f"build_recommended_route failed for day {label!r}")
        built.append(out_f.name)

    print(f"\nBuilt {len(built)} day route(s): " + ", ".join(built))


if __name__ == "__main__":
    main()
