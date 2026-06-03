#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
caltopo_mytracks.py — pull Kyle's OWN CalTopo tracks that fall within a report's
area into the report's gpx/ collection.

A research report's map must include not just the three web sources, but Kyle's
own recorded/collected tracks from his CalTopo account (his "All" archive map +
the range's regional map). This scans the local caltopo/*.json dumps for
LineStrings inside the report's bounding box and writes the new ones (deduped
against what's already collected) as gpx/<slug>/<slug>_caltopo_<mapid>_<n>.gpx.

Refresh the dumps first so the data is current:
    scripts/fetch_caltopo.py --map C105AEV      # the big "All" archive
    scripts/fetch_caltopo.py --map <REGIONAL>   # e.g. VKGB00L for Sangres

Then:
    scripts/caltopo_mytracks.py --slug lakes_of_clouds_loop
    scripts/caltopo_mytracks.py --slug <slug> --margin-mi 3

Bounding box is computed from gpx/<slug>/<slug>_peaks_only.gpx + a margin.
"""
from __future__ import annotations
import argparse, glob, hashlib, math, re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALTOPO = ROOT / "caltopo"
NS = "{http://www.topografix.com/GPX/1/1}"


def gpx_track_points(path: Path):
    try: root = ET.parse(path).getroot()
    except ET.ParseError: return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(f"{NS}trkpt")]


def gpx_wpts(path: Path):
    try: root = ET.parse(path).getroot()
    except ET.ParseError: return []
    return [(float(w.get("lat")), float(w.get("lon"))) for w in root.iter(f"{NS}wpt")]


def sig(pts):
    """Geometry signature for dedupe: rounded start, end, midpoint, len-bucket."""
    if len(pts) < 2: return None
    def r(p): return (round(p[0], 3), round(p[1], 3))
    return (r(pts[0]), r(pts[-1]), r(pts[len(pts)//2]), len(pts)//50)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--margin-mi", type=float, default=2.5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gdir = ROOT / "gpx" / args.slug
    peaks_only = gdir / f"{args.slug}_peaks_only.gpx"
    pk = gpx_wpts(peaks_only)
    if not pk:
        raise SystemExit(f"no peaks in {peaks_only}")
    mlat = args.margin_mi / 69.0
    mlon = args.margin_mi / 53.0
    lat0 = min(p[0] for p in pk) - mlat; lat1 = max(p[0] for p in pk) + mlat
    lon0 = min(p[1] for p in pk) - mlon; lon1 = max(p[1] for p in pk) + mlon
    print(f"box: lat {lat0:.3f}..{lat1:.3f}  lon {lon0:.3f}..{lon1:.3f}  (+{args.margin_mi}mi)")

    # signatures of tracks already collected for this report (any source)
    have = set()
    for f in gdir.glob("*.gpx"):
        if "peaks_only" in f.name or "landmarks" in f.name: continue
        s = sig(gpx_track_points(f))
        if s: have.add(s)

    import json
    added = 0
    for fp in sorted(CALTOPO.glob("*.json")):
        mid = fp.stem
        try: d = json.loads(fp.read_text())
        except Exception: continue
        feats = (d.get("state") or {}).get("features", []) or []
        idx = 0
        for ft in feats:
            g = (ft or {}).get("geometry") or {}
            if g.get("type") != "LineString": continue
            coords = g.get("coordinates") or []
            pts = [(c[1], c[0]) for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
            if len(pts) < 2: continue
            if not any(lat0 <= la <= lat1 and lon0 <= lo <= lon1 for la, lo in pts[::10]):
                continue
            s = sig(pts)
            if s in have:   # already have this track from a web source
                continue
            have.add(s); idx += 1; added += 1
            title = ((ft.get("properties") or {}).get("title") or f"track{idx}")
            safe = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30] or f"track{idx}"
            out = gdir / f"{args.slug}_caltopo_{mid}_{safe}.gpx"
            if args.dry_run:
                print(f"  [dry] {out.name}  ({len(pts)} pts)")
                continue
            lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                     '<gpx version="1.1" creator="caltopo_mytracks.py" xmlns="http://www.topografix.com/GPX/1/1">',
                     f"  <trk><name>{title}</name><trkseg>"]
            for la, lo in pts:
                lines.append(f'    <trkpt lat="{la}" lon="{lo}"></trkpt>')
            lines += ["  </trkseg></trk>", "</gpx>"]
            out.write_text("\n".join(lines))
            print(f"  + {out.name}  ({len(pts)} pts)")

    print(f"\n{'would add' if args.dry_run else 'added'} {added} of your CalTopo tracks not already in the report.")


if __name__ == "__main__":
    main()
