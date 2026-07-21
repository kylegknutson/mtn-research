#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_route_starts.py — a single-day report's recommended route must BEGIN at its
declared trailhead.

The gap this closes (Kyle, 2026-07-12, "cuba"): a recommended route can get rebuilt
from a recorded track that starts on the WRONG side of the peaks — miles from the
trailhead the report describes — and every existing gate still passes (the recipe
reproduces the file, the route summits the objectives, the map frames it). Nothing
checked "does the line actually start where the report says you park." Cuba's route
began 3 mi from its declared TH (and the TH itself was mislabeled). This flags that.

Multi-day trips (peaks.yml has `days:` or `legs:`) are already covered by
check_trip_continuity, which anchors every day/leg start+end to a TH or camp — so
they're skipped here to avoid double-counting camp-anchored day routes.

    scripts/check_route_starts.py                 # audit every single-day report
    scripts/check_route_starts.py cuba_gulch_trio # one slug
    scripts/check_route_starts.py --strict        # exit 1 if any route starts far from its TH

Threshold: 0.3 mi (matches check_trip_continuity's anchor tolerance).
"""
from __future__ import annotations
import argparse, math, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
THRESH_MI = 0.3


def hav_mi(a, b, c, d):
    R = 3958.8
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def first_last(gpx: Path):
    pts = [(float(t.get("lat")), float(t.get("lon")))
           for t in ET.parse(gpx).getroot().iter(NS+"trkpt")]
    return (pts[0], pts[-1]) if pts else (None, None)


def anchors(cfg):
    """Trailhead/camp landmarks a route may legitimately start from."""
    out = []
    for lm in cfg.get("landmarks", []) or []:
        kind = (lm.get("kind") or "").lower()
        nm = (lm.get("name") or "").lower()
        if kind in ("trailhead", "camp") or "camp" in nm or "trailhead" in nm or nm.endswith(" th"):
            if lm.get("lat") is not None:
                out.append((lm["lat"], lm["lon"], lm.get("name", "?")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    slugs = [args.slug] if args.slug else sorted(
        d.name for d in GPX.iterdir() if d.is_dir() and (d / "peaks.yml").exists())

    flagged, skipped_trips, no_th = [], [], []
    for slug in slugs:
        d = GPX / slug
        try:
            cfg = yaml.safe_load((d / "peaks.yml").read_text()) or {}
        except Exception:
            continue
        if cfg.get("days") or cfg.get("legs"):
            skipped_trips.append(slug)   # covered by check_trip_continuity
            continue
        routes = sorted(f for f in d.glob("*recommended*.gpx"))
        if not routes:
            continue
        anc = anchors(cfg)
        if not anc:
            no_th.append(slug)
            continue
        for r in routes:
            start, _ = first_last(r)
            if start is None:
                continue
            dist = min(hav_mi(start[0], start[1], a[0], a[1]) for a in anc)
            near = min(anc, key=lambda a: hav_mi(start[0], start[1], a[0], a[1]))
            if dist > THRESH_MI:
                flagged.append((dist, slug, r.name, near[2]))

    flagged.sort(reverse=True)
    print(f"Checked {len(slugs) - len(skipped_trips)} single-day report(s) "
          f"({len(skipped_trips)} trips skipped — covered by check_trip_continuity).\n")
    if flagged:
        print("ROUTE STARTS FAR FROM DECLARED TRAILHEAD:")
        for dist, slug, fn, thname in flagged:
            print(f"  {dist:5.1f} mi  {slug:26} {fn}  (nearest TH: {thname})")
    else:
        print("✓ every single-day recommended route starts within "
              f"{THRESH_MI} mi of its trailhead.")
    if no_th:
        print(f"\n(no trailhead landmark to check: {', '.join(no_th)})")
    if args.strict and flagged:
        sys.exit(1)


if __name__ == "__main__":
    main()
