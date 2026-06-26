#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
list_source_tracks.py — for a slug, size up every recorded source track: total length
(mi), how far its start is from the trailhead landmark, and how many of the report's
objective summits it passes (within 250 m). Helps pick a from_track recipe / spot a
recommended route that doesn't actually start at the TH or reach a summit.

    scripts/list_source_tracks.py homestake_peak
"""
from __future__ import annotations
import math, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
COVER_M = 250.0
SKIP = ("_recommended", "_landmarks", "_peaks_only")


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def pts(p):
    return [(float(t.get("lat")), float(t.get("lon"))) for t in ET.parse(p).getroot().iter(NS+"trkpt")]


def main():
    slug = sys.argv[1]
    d = GPX / slug
    cfg = yaml.safe_load((d / "peaks.yml").read_text()) or {}
    th = next((lm for lm in cfg.get("landmarks", []) if lm.get("kind") == "trailhead"), None)

    objs = []
    pk = d / f"{slug}_peaks_only.gpx"
    if pk.exists():
        for w in ET.parse(pk).getroot().iter(NS+"wpt"):
            nm = w.find(NS+"name")
            objs.append(((float(w.get("lat")), float(w.get("lon"))), (nm.text if nm is not None else "").split(" (")[0]))

    print(f"{slug}: {len(objs)} objective(s)" + (f", TH {th['name']}" if th else ", no TH landmark"))
    rows = []
    for f in sorted(d.glob("*.gpx")):
        if any(s in f.name for s in SKIP):
            continue
        tp = pts(f)
        if not tp:
            continue
        miles = sum(hav(*tp[i], *tp[i+1]) for i in range(len(tp)-1)) / 1609.344
        samp = tp[::8] or tp
        covered = sum(1 for (la, lo), _ in objs if min(hav(la, lo, p[0], p[1]) for p in samp) <= COVER_M)
        th_ft = hav(tp[0][0], tp[0][1], th["lat"], th["lon"]) * 3.28084 if th else float("nan")
        rows.append((miles, covered, th_ft, f.name))
    rows.sort(reverse=True)
    for miles, covered, th_ft, name in rows:
        flag = "✓all" if objs and covered == len(objs) else f"{covered}/{len(objs)}"
        print(f"  {miles:5.1f} mi  cover {flag:>5}  start {th_ft:6.0f} ft from TH   {name}")


if __name__ == "__main__":
    main()
