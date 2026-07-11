#!/usr/bin/env python3
"""
check_map_extents.py — every recommended line must lie fully inside its PNG's frame.

Rewritten 2026-07-10 (Kyle: "the approach magenta track isn't on there — how did that
make it past the gates?"). The old version REPLICATED make_overview_map's bbox logic
and so agreed with its bugs — when the summit-scope filter silently dropped the
pack-in leg from the Needleton map, both sides considered it "out of scope" and the
gate passed. Now make_overview_map writes the rendered extent to a sidecar
(docs/maps/<slug>.extent.json) and this gate validates the ARTIFACT:

  every trackpoint of every gpx/<slug>/*recommended*.gpx must fall inside the
  sidecar extent (small tolerance). A leg off the frame — dropped or cropped — FAILs.

Slugs without a sidecar yet FAIL with a regen hint (regenerate the PNG).

Usage:
    scripts/check_map_extents.py                    # all slugs with a PNG
    scripts/check_map_extents.py carter_dome_group  # one slug
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX_DIR = ROOT / "gpx"
MAPS_DIR = ROOT / "docs" / "maps"
NS = "{http://www.topografix.com/GPX/1/1}"
TOL = 0.0005   # ~50 m of slack for edge-kissing points


def track_points(path: Path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    fails = checked = 0
    for png in sorted(MAPS_DIR.glob("*.png")):
        slug = png.stem
        if only and slug != only:
            continue
        if not (GPX_DIR / slug).is_dir():
            continue
        routes = sorted((GPX_DIR / slug).glob("*recommended*.gpx"))
        if not routes:
            continue
        checked += 1
        sidecar = png.with_suffix(".extent.json")
        if not sidecar.exists():
            fails += 1
            print(f"FAIL  {slug:26s} no {sidecar.name} — regenerate the PNG "
                  f"(scripts/make_overview_map.py {slug})")
            continue
        ext = json.loads(sidecar.read_text())
        slug_ok = True
        for f in routes:
            pts = track_points(f)
            if not pts:
                continue
            out = sum(1 for la, lo in pts
                      if not (ext["lat_min"] - TOL <= la <= ext["lat_max"] + TOL
                              and ext["lon_min"] - TOL <= lo <= ext["lon_max"] + TOL))
            if out:
                fails += 1
                slug_ok = False
                print(f"FAIL  {slug:26s} {f.name}: {out}/{len(pts)} points outside the "
                      f"rendered frame — a recommended line is off the PNG")
        if slug_ok:
            print(f"OK    {slug}")

    print(f"\n{checked} slug(s) checked — {fails} extent failure(s).")
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
