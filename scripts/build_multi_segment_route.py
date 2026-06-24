#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "caltopo_python"]
# ///
"""
build_multi_segment_route.py — compose a recommended route from SEVERAL recorded tracks as
SEPARATE <trk> segments, for objectives that no single track links and that have no recorded
connector between them (runbook: "make them individual climbs, each its own <trkseg>" — never
invent a straight-line connector). --legs refuses to split a disconnected leg; this is the
tool for that case.

Each --tracks entry is a recorded-track filename substring, built VERBATIM (via
build_recommended_route --from-track) and emitted as its own <trk> so the per-segment
fidelity gate measures each on its own (no phantom connector across the gap). Distance is
summed from the segments; gain is summed from each segment's DEM measurement.

Then fans the change out exactly like propagate_route: GPS Tracks export, overview PNG,
frontmatter dist/gain, and the CalTopo route line.

    scripts/build_multi_segment_route.py grizzly_jenkins_group \
        --tracks trio_14ers_1,lakefork_14ers_6
"""
from __future__ import annotations
import argparse, logging, re, subprocess, sys
import xml.etree.ElementTree as ET
from pathlib import Path

logging.basicConfig(level=logging.ERROR)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import propagate_route as pr   # update_frontmatter, replace_caltopo_route, caltopo_id

GPX = ROOT / "gpx"
SCRIPTS = ROOT / "scripts"
NS = "{http://www.topografix.com/GPX/1/1}"


def run(cmd):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True)


def seg_points(path: Path):
    root = ET.parse(path).getroot()
    return [(p.get("lat"), p.get("lon")) for p in root.iter(NS + "trkpt")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--tracks", required=True, help="comma-separated recorded-track substrings, in route order")
    ap.add_argument("--no-caltopo", action="store_true")
    args = ap.parse_args()

    tracks = [t.strip() for t in args.tracks.split(",") if t.strip()]
    print(f"== multi-segment route {args.slug} : {len(tracks)} segment(s) ==")
    segs, tot_d, tot_g = [], 0.0, 0
    for i, trk in enumerate(tracks):
        tmp = GPX / args.slug / f".seg_{i}.gpx"
        r = run([SCRIPTS / "build_recommended_route.py", args.slug, "--from-track", trk, "--out", tmp])
        if r.returncode != 0:
            print(r.stdout[-400:], r.stderr[-300:]); sys.exit(f"segment {trk} failed")
        m = re.search(r"Recommended route:\s*([\d.]+)\s*mi\s*·\s*~?([\d,]+)\s*ft", r.stdout or "")
        d, g = (float(m.group(1)), int(m.group(2).replace(",", ""))) if m else (0.0, 0)
        pts = seg_points(tmp)
        if len(pts) < 2:
            sys.exit(f"segment {trk}: no points")
        segs.append((trk, pts)); tot_d += d; tot_g += g
        print(f"  seg {i}: {trk:28s} {d:5.1f} mi / {g:,} ft / {len(pts)} pts")
        tmp.unlink()

    out = GPX / args.slug / f"{args.slug}_recommended.gpx"
    with out.open("w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<gpx version="1.1" creator="build_multi_segment_route" '
                'xmlns="http://www.topografix.com/GPX/1/1">\n')
        for trk, pts in segs:
            f.write(f'  <trk><name>{args.slug} recommended route — {trk} '
                    f'(segment)</name><trkseg>\n')
            for lat, lon in pts:
                f.write(f'    <trkpt lat="{lat}" lon="{lon}"></trkpt>\n')
            f.write('  </trkseg></trk>\n')
        f.write('</gpx>\n')
    print(f"  wrote {out.name}: {len(segs)} segments, {tot_d:.1f} mi / {tot_g:,} ft total")

    if run([SCRIPTS / "export_to_gps_tracks.py", args.slug]).returncode != 0:
        print("  (GPS Tracks export warned)")
    if run([SCRIPTS / "make_overview_map.py", args.slug]).returncode != 0:
        sys.exit("make_overview_map failed")
    print("  PNG refreshed")
    pr.update_frontmatter(args.slug, tot_d, tot_g)
    print(f"  frontmatter dist/gain → {tot_d:.1f} mi / {tot_g:,} ft")
    mid = pr.caltopo_id(args.slug)
    if mid and not args.no_caltopo:
        pr.replace_caltopo_route(args.slug, mid)
    print(f"  ✓ {args.slug} multi-segment route built + propagated")


if __name__ == "__main__":
    main()
