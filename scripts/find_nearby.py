#!/usr/bin/env python3
"""
Find CalTopo features (markers, tracks, shapes, folders) whose geometry falls
inside a bounding box. Walks every JSON dump in ../caltopo/.

Usage:
    # Bounding box (south, west, north, east):
    python find_nearby.py --bbox 37.78,-108.08,37.86,-107.98

    # Single point with radius (km):
    python find_nearby.py --center 37.82,-108.04 --radius-km 5

    # Multiple centers (each with the same radius):
    python find_nearby.py --center 37.8217,-108.0436 --center 37.8094,-108.0231 --radius-km 3

Output: one line per matched feature with map title, feature class, title, and sample coord.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CALTOPO_DIR = SCRIPT_DIR.parent / "caltopo"


def iter_coords(geom):
    """Recursively yield (lon, lat) pairs from a GeoJSON-like geometry."""
    if not geom:
        return
    if isinstance(geom, dict):
        coords = geom.get("coordinates")
        if coords is not None:
            yield from iter_coords(coords)
        return
    if isinstance(geom, (list, tuple)):
        # Leaf coord pair?
        if (
            len(geom) >= 2
            and all(isinstance(x, (int, float)) for x in geom[:2])
        ):
            yield (geom[0], geom[1])  # lon, lat
            return
        for item in geom:
            yield from iter_coords(item)


def in_bbox(lon: float, lat: float, bbox: tuple[float, float, float, float]) -> bool:
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e


def km_between(lat1, lon1, lat2, lon2):
    """Haversine distance in km."""
    R = 6371.0
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def bbox_for_centers(centers: list[tuple[float, float]], radius_km: float) -> tuple[float, float, float, float]:
    """Build a single bbox covering all (lat, lon) centers padded by radius_km."""
    deg_lat = radius_km / 111.0
    s = min(c[0] for c in centers) - deg_lat
    n = max(c[0] for c in centers) + deg_lat
    # Longitude degrees-per-km depends on latitude; use the most equatorward (largest cos)
    avg_lat = sum(c[0] for c in centers) / len(centers)
    deg_lon = radius_km / (111.0 * max(0.01, math.cos(math.radians(avg_lat))))
    w = min(c[1] for c in centers) - deg_lon
    e = max(c[1] for c in centers) + deg_lon
    return (s, w, n, e)


def parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("--bbox must be S,W,N,E (4 floats)")
    return tuple(parts)  # type: ignore[return-value]


def parse_center(s: str) -> tuple[float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("--center must be LAT,LON")
    return (parts[0], parts[1])


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bbox", type=parse_bbox, help="S,W,N,E (e.g. 37.78,-108.08,37.86,-107.98)")
    g.add_argument("--center", type=parse_center, action="append",
                   help="LAT,LON; can repeat for multiple centers")
    ap.add_argument("--radius-km", type=float, default=3.0,
                    help="Radius in km (with --center); default 3")
    ap.add_argument("--show-coord", action="store_true",
                    help="Print a sample matching coord per feature")
    args = ap.parse_args()

    if args.bbox:
        bbox = args.bbox
        centers = []
    else:
        centers = args.center
        bbox = bbox_for_centers(centers, args.radius_km)

    print(f"Searching bbox S={bbox[0]:.4f} W={bbox[1]:.4f} N={bbox[2]:.4f} E={bbox[3]:.4f}")
    if centers:
        for c in centers:
            print(f"  center: lat={c[0]} lon={c[1]} radius={args.radius_km}km")
    print()

    files = sorted(CALTOPO_DIR.glob("*.json"))
    if not files:
        sys.exit(f"No JSON dumps in {CALTOPO_DIR}. Run fetch_caltopo.py --all first.")

    total_matches = 0
    for path in files:
        try:
            data = json.loads(path.read_text())
        except Exception as e:
            print(f"[skip {path.name}] {e}")
            continue

        features = (data.get("state") or {}).get("features", []) or []
        # Map title — pull from any feature with class=CollaborativeMap, else use file name.
        map_title = path.stem
        for f in features:
            p = (f or {}).get("properties") or {}
            if p.get("class") == "CollaborativeMap":
                map_title = p.get("title") or map_title
                break

        match_rows = []
        for f in features:
            if not isinstance(f, dict):
                continue
            geom = f.get("geometry")
            if not geom:
                continue
            sample = None
            for lon, lat in iter_coords(geom):
                if in_bbox(lon, lat, bbox):
                    sample = (lat, lon)
                    break
            if sample is None:
                continue
            props = f.get("properties") or {}
            cls = props.get("class", "?")
            title = props.get("title") or props.get("description") or "(untitled)"
            match_rows.append((cls, title, sample, props.get("folderId")))

        if match_rows:
            print(f"=== {path.name}  ({map_title}) — {len(match_rows)} match(es) ===")
            for cls, title, (lat, lon), fid in match_rows:
                line = f"  [{cls:14}] {title}"
                if args.show_coord:
                    line += f"   @ {lat:.5f},{lon:.5f}"
                print(line)
            total_matches += len(match_rows)

    print()
    print(f"Total matches across {len(files)} map(s): {total_matches}")


if __name__ == "__main__":
    main()
