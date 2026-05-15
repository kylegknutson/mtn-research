#!/usr/bin/env python3
"""
Convert LineString shapes (and optionally Markers) from a dumped CalTopo
map JSON into individual .gpx files.

Usage:
    python caltopo_to_gpx.py --map CVV0 --out-dir ../gpx/dolores_peak
    python caltopo_to_gpx.py --map CVV0 --out-dir ../gpx/dolores_peak --prefix dolores

Each LineString becomes one .gpx <trk>.
All Markers become <wpt> entries inside a single waypoints.gpx.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CALTOPO_DIR = SCRIPT_DIR.parent / "caltopo"

GPX_NS = "http://www.topografix.com/GPX/1/1"


def slugify(s: str) -> str:
    s = (s or "untitled").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "untitled"


def make_gpx_root() -> ET.Element:
    root = ET.Element("gpx", {
        "version": "1.1",
        "creator": "caltopo_to_gpx.py",
        "xmlns": GPX_NS,
    })
    return root


def write_gpx(root: ET.Element, path: Path) -> None:
    # Simple ElementTree XML output. Add a tiny prolog manually.
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with path.open("wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)


def coord_pair(c) -> tuple[float, float, float | None]:
    """Return (lat, lon, elev) from CalTopo coord [lon, lat] or [lon, lat, elev]."""
    lon = float(c[0])
    lat = float(c[1])
    elev = float(c[2]) if len(c) >= 3 and c[2] is not None else None
    return lat, lon, elev


def linestring_to_gpx(name: str, desc: str | None, coords: list, out_path: Path) -> int:
    root = make_gpx_root()
    trk = ET.SubElement(root, "trk")
    ET.SubElement(trk, "name").text = name
    if desc:
        ET.SubElement(trk, "desc").text = desc
    seg = ET.SubElement(trk, "trkseg")
    n = 0
    for c in coords:
        if not isinstance(c, (list, tuple)) or len(c) < 2:
            continue
        lat, lon, elev = coord_pair(c)
        pt = ET.SubElement(seg, "trkpt", {"lat": f"{lat:.7f}", "lon": f"{lon:.7f}"})
        if elev is not None:
            ET.SubElement(pt, "ele").text = f"{elev:.1f}"
        n += 1
    write_gpx(root, out_path)
    return n


def markers_to_waypoints_gpx(markers: list, out_path: Path) -> int:
    root = make_gpx_root()
    n = 0
    for m in markers:
        props = m.get("properties") or {}
        geom = m.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        lat, lon, elev = coord_pair(coords)
        wpt = ET.SubElement(root, "wpt", {"lat": f"{lat:.7f}", "lon": f"{lon:.7f}"})
        if elev is not None:
            ET.SubElement(wpt, "ele").text = f"{elev:.1f}"
        ET.SubElement(wpt, "name").text = props.get("title") or "(untitled)"
        if props.get("description"):
            ET.SubElement(wpt, "desc").text = props["description"]
        n += 1
    if n:
        write_gpx(root, out_path)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="CalTopo map ID (must already be dumped to caltopo/<id>.json)")
    ap.add_argument("--out-dir", required=True, help="Output directory for GPX files")
    ap.add_argument("--prefix", default="", help="Optional filename prefix (e.g. 'dolores')")
    args = ap.parse_args()

    src = CALTOPO_DIR / f"{args.map}.json"
    if not src.exists():
        sys.exit(f"Not found: {src}. Run fetch_caltopo.py --map {args.map} first.")

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(src.read_text())
    feats = (data.get("state") or {}).get("features", []) or []

    line_features = []
    point_features = []
    for f in feats:
        if not isinstance(f, dict):
            continue
        g = f.get("geometry") or {}
        gt = g.get("type")
        if gt == "LineString":
            line_features.append(f)
        elif gt == "Point":
            point_features.append(f)
        # MultiLineString could be split into multiple, but CalTopo rarely uses.

    prefix = (args.prefix + "_") if args.prefix else ""
    written = []

    for f in line_features:
        props = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates", [])
        title = props.get("title") or "untitled"
        slug = slugify(title)
        out = out_dir / f"{prefix}{slug}_caltopo_{args.map}.gpx"
        n = linestring_to_gpx(title, props.get("description"), coords, out)
        print(f"  track : {out.name}  ({n} pts)")
        written.append(out)

    if point_features:
        out = out_dir / f"{prefix}waypoints_caltopo_{args.map}.gpx"
        n = markers_to_waypoints_gpx(point_features, out)
        print(f"  waypts: {out.name}  ({n} pts)")
        written.append(out)

    print(f"\nWrote {len(written)} file(s) to {out_dir}")


if __name__ == "__main__":
    main()
