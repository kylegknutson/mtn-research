#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
caltopo_features.py — list the features on a CalTopo map from its local dump.

Quick diagnostic for "what's actually on this map?" — prints every LineString
(track) and Point (marker) with title, stroke color, and point count. Run
`scripts/fetch_caltopo.py --map <ID>` first to refresh caltopo/<ID>.json.

Usage:
    scripts/fetch_caltopo.py --map 55M4430
    scripts/caltopo_features.py 55M4430
    scripts/caltopo_features.py 55M4430 --kind line   # tracks only
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP_DIR = ROOT / "caltopo"


def find_features(obj):
    """Locate the features list wherever it's nested (top-level or under 'state')."""
    if isinstance(obj, dict):
        if isinstance(obj.get("features"), list):
            return obj["features"]
        for v in obj.values():
            r = find_features(v)
            if r is not None:
                return r
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("map_id")
    ap.add_argument("--kind", choices=["line", "point", "all"], default="all")
    ap.add_argument("--ids", action="store_true", help="show feature ids (for deletion)")
    args = ap.parse_args()

    dump = DUMP_DIR / f"{args.map_id}.json"
    if not dump.exists():
        sys.exit(f"No dump at {dump} — run: scripts/fetch_caltopo.py --map {args.map_id}")

    feats = find_features(json.loads(dump.read_text())) or []
    lines, points, other = [], [], 0
    for f in feats:
        g = f.get("geometry") or {}
        t = g.get("type")
        p = f.get("properties", {})
        title = (p.get("title") or "(untitled)").strip()
        stroke = p.get("stroke") or p.get("fill") or "—"
        coords = g.get("coordinates") or []
        npts = len(coords) if t in ("LineString", "MultiLineString") else 0
        fid = f.get("id", "?")
        if t in ("LineString", "MultiLineString"):
            lines.append((title, stroke, npts, fid))
        elif t == "Point":
            points.append((title, stroke, fid))
        else:
            other += 1

    if args.kind in ("line", "all"):
        print(f"\nTracks ({len(lines)}):")
        for title, stroke, npts, fid in sorted(lines):
            print(f"  {stroke:9} {npts:6d} pts  {title}" + (f"   [{fid}]" if args.ids else ""))
    if args.kind in ("point", "all"):
        print(f"\nMarkers ({len(points)}):")
        for title, stroke, fid in sorted(points):
            print(f"  {stroke:9}  {title}" + (f"   [{fid}]" if args.ids else ""))
    print(f"\n{len(feats)} features total ({len(lines)} tracks, {len(points)} markers, {other} other).")


if __name__ == "__main__":
    main()
