#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
analyze_tracks.py — for a report's source GPX, list each track's distance and
which objective peaks it actually summits.

Use it to pick the recommended-route source when the composed graph route comes
out implausibly long: find the recorded track that hits ALL objectives in the
fewest miles (often a single clean party track beats a stitched composite).

Summit = track passes within --tol-ft of the objective (default 250 ft).

Usage:
    scripts/analyze_tracks.py cuba_gulch_trio
    scripts/analyze_tracks.py cuba_gulch_trio --all-only   # only tracks hitting every objective
"""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path
import xml.etree.ElementTree as ET
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX_ROOT = ROOT / "gpx"
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
NS = "{http://www.topografix.com/GPX/1/1}"
HELPER = ("recommended", "peaks_only", "landmark", "_drive", "drive_in", "summit", "waypoint")


def hav_mi(a, b):
    R = 3958.8
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))


def track_pts(path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]


def objectives(slug):
    cfg = yaml.safe_load((GPX_ROOT / slug / "peaks.yml").read_text())
    ids = cfg.get("objective_ids") or []
    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    P = {p["id"]: p for p in peaks()}
    return [(i, P[i]["display_name"], (P[i]["lat"], P[i]["lon"])) for i in ids if i in P]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--tol-ft", type=float, default=250)
    ap.add_argument("--all-only", action="store_true", help="only tracks summiting every objective")
    args = ap.parse_args()

    objs = objectives(args.slug)
    tol_mi = args.tol_ft / 5280.0
    d = GPX_ROOT / args.slug
    files = [f for f in sorted(d.glob("*.gpx")) if not any(h in f.name.lower() for h in HELPER)]

    # trailhead (first landmark marked kind: trailhead) — to flag higher-start tracks
    th = None
    cfg = yaml.safe_load((d / "peaks.yml").read_text()) or {}
    for l in (cfg.get("landmarks") or []):
        if l.get("kind") == "trailhead" and l.get("lat") is not None:
            th = (l["lat"], l["lon"]); break

    print(f"objectives: " + ", ".join(n for _, n, _ in objs) + (f"  | TH @ {th}" if th else ""))
    print(f"{'track':48} {'mi':>6} {'st→TH':>6}  hits")
    rows = []
    for f in files:
        pts = track_pts(f)
        if len(pts) < 2:
            continue
        dist = sum(hav_mi(pts[i], pts[i+1]) for i in range(len(pts)-1))
        hits = [n for _, n, c in objs if min(hav_mi(p, c) for p in pts) <= tol_mi]
        st_th = min(hav_mi(pts[0], th), hav_mi(pts[-1], th)) if th else None
        rows.append((len(hits), dist, f.name, hits, st_th))
    for nhits, dist, name, hits, st_th in sorted(rows, key=lambda r: (-r[0], r[1])):
        if args.all_only and nhits < len(objs):
            continue
        mark = "  ALL" if nhits == len(objs) else ""
        sth = f"{st_th:5.1f}" if st_th is not None else "    —"
        print(f"{name[:48]:48} {dist:6.1f} {sth}  {nhits}/{len(objs)}{mark}  {', '.join(hits)}")


if __name__ == "__main__":
    main()
