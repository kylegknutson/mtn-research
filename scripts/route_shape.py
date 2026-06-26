#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
route_shape.py — quick geometry summary of a report's recommended route: start/end
coords, straight-line span, whether it's a LOOP (start≈end) or POINT-TO-POINT, and
each endpoint's distance from the slug's trailhead landmark(s). Used to keep the
prose's "loop" vs "traverse" framing honest after a route is rebuilt from a track.

    scripts/route_shape.py williams_mountains
"""
from __future__ import annotations
import math, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
NS = "{http://www.topografix.com/GPX/1/1}"
LOOP_M = 400.0   # start within this of end → call it a loop


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def main():
    slug = sys.argv[1]
    d = ROOT / "gpx" / slug
    rt = next((f for f in d.glob("*recommended*.gpx")), None)
    if not rt:
        sys.exit(f"no recommended route in {d}")
    pts = [(float(t.get("lat")), float(t.get("lon"))) for t in ET.parse(rt).getroot().iter(NS+"trkpt")]
    if not pts:
        sys.exit("route has no track points")
    s, e = pts[0], pts[-1]
    gap = hav(s[0], s[1], e[0], e[1])
    shape = "LOOP" if gap <= LOOP_M else "POINT-TO-POINT"
    print(f"{slug}: {len(pts)} pts · {shape} (start↔end {gap*3.28084:.0f} ft apart)")
    print(f"  start {s[0]:.5f},{s[1]:.5f}")
    print(f"  end   {e[0]:.5f},{e[1]:.5f}")

    cfg = yaml.safe_load((d / "peaks.yml").read_text()) or {}
    for lm in cfg.get("landmarks", []):
        if lm.get("kind") == "trailhead":
            ds = hav(s[0], s[1], lm["lat"], lm["lon"]) * 3.28084
            de = hav(e[0], e[1], lm["lat"], lm["lon"]) * 3.28084
            print(f"  TH '{lm['name']}': start {ds:.0f} ft, end {de:.0f} ft away")


if __name__ == "__main__":
    main()
