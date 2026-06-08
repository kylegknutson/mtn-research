#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
caltopo_mytracks.py — pull Kyle's OWN CalTopo tracks that fall within a report's
area into the report's gpx/ collection.

A research report's map must include not just the three web sources, but Kyle's
own recorded/collected tracks from his CalTopo account. Those live in the
per-range **"GPS Tracks — <Region>" regional maps** (the canonical archive — the
big "All"/C105AEV map may be deleted in future, so default to the regional map
for the peak's range). This scans the regional map's local dump for LineStrings
inside the report's bounding box and writes the new ones (deduped against what's
already collected) as gpx/<slug>/<slug>_caltopo_<mapid>_<n>.gpx.

Refresh the regional dump first so the data is current:
    scripts/fetch_caltopo.py --map <REGIONAL>   # auto-picked from the peak's range

Then:
    scripts/caltopo_mytracks.py --slug lakes_of_clouds_loop      # regional for the range
    scripts/caltopo_mytracks.py --slug <slug> --maps VKGB00L,C105AEV  # explicit
    scripts/caltopo_mytracks.py --slug <slug> --margin-mi 3

Range→regional is derived from gpx/<slug>/peaks.yml objective_ids via peak_db.
Bounding box is computed from gpx/<slug>/<slug>_peaks_only.gpx + a margin.
"""
from __future__ import annotations
import argparse, glob, hashlib, math, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CALTOPO = ROOT / "caltopo"
NS = "{http://www.topografix.com/GPX/1/1}"
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")

RANGE_TO_REGIONAL = {
    "Sangre de Cristo": "VKGB00L", "Sawatch": "L5VH4BU", "San Juan": "06AR6BF",
    "Elk": "1G2G7DM", "Gore": "6E4GJV2", "Mosquito": "LECF68J",
    "Tenmile": "7QE01UK", "Front": "DLES5CC", "Weminuche": "7AQN6TS",
    # New England
    "Eastern White Mountains": "UDK6ETR", "Western White Mountains": "UDK6ETR",
    "Carter-Moriah Range": "UDK6ETR", "Presidential Range": "UDK6ETR",
}


def gpx_track_points(path: Path):
    try: root = ET.parse(path).getroot()
    except ET.ParseError: return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(f"{NS}trkpt")]


def gpx_wpts(path: Path):
    try: root = ET.parse(path).getroot()
    except ET.ParseError: return []
    return [(float(w.get("lat")), float(w.get("lon"))) for w in root.iter(f"{NS}wpt")]


# Non-peak activity tracks (running/biking/commutes) can clip a generous bbox but
# aren't route beta — skip by title.
SKIP_TITLE = re.compile(r"\b(running|run|jog|bike|biking|ride|cycle|commute|walk|dog|"
                        r"neighborhood|errand|road\s*ride|gravel\s*ride)\b", re.I)


def sig(pts):
    """Geometry signature for dedupe: rounded start, end, midpoint, len-bucket."""
    if len(pts) < 2: return None
    def r(p): return (round(p[0], 3), round(p[1], 3))
    return (r(pts[0]), r(pts[-1]), r(pts[len(pts)//2]), len(pts)//50)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--maps", help="comma map IDs to scan (default: regional map for the peak's range)")
    ap.add_argument("--margin-mi", type=float, default=2.5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gdir = ROOT / "gpx" / args.slug
    peaks_only = gdir / f"{args.slug}_peaks_only.gpx"

    # which CalTopo dumps to scan: explicit --maps, else the regional map(s) for
    # the objective peaks' range(s).
    if args.maps:
        scan_ids = [m.strip() for m in args.maps.split(",")]
    else:
        from peak_db_client import peaks  # noqa
        by = {p["id"]: p for p in peaks()}
        cfg = yaml.safe_load((gdir / "peaks.yml").read_text())
        ranges = {(by.get(i) or {}).get("range") for i in cfg.get("objective_ids", [])}
        scan_ids = [RANGE_TO_REGIONAL[r] for r in ranges if r in RANGE_TO_REGIONAL]
        if not scan_ids:
            sys.exit(f"no regional map for range(s) {ranges}; pass --maps explicitly")
    missing = [m for m in scan_ids if not (CALTOPO / f"{m}.json").exists()]
    if missing:
        print(f"⚠ no local dump for {missing} — refresh first: "
              + " ".join(f"scripts/fetch_caltopo.py --map {m}" for m in missing))
    print(f"scanning your CalTopo maps: {', '.join(scan_ids)}")
    pk = gpx_wpts(peaks_only)
    if not pk:
        raise SystemExit(f"no peaks in {peaks_only}")
    mlat = args.margin_mi / 69.0
    mlon = args.margin_mi / 53.0
    lat0 = min(p[0] for p in pk) - mlat; lat1 = max(p[0] for p in pk) + mlat
    lon0 = min(p[1] for p in pk) - mlon; lon1 = max(p[1] for p in pk) + mlon

    # A track only belongs on the report if it reaches a researched (objective)
    # peak — passing through the bbox is not enough (Kyle, 2026-06-08). Load the
    # objective summit coords from objective_ids; require a track point within
    # ½ mi of one.
    cfg2 = yaml.safe_load((gdir / "peaks.yml").read_text()) or {}
    obj_summits = []
    try:
        from peak_db_client import peaks as _pks
        _by = {p["id"]: p for p in _pks()}
        obj_summits = [(_by[i]["lat"], _by[i]["lon"]) for i in cfg2.get("objective_ids", []) if i in _by]
    except Exception as e:
        print(f"⚠ could not load objective summits ({e}); summit filter off")
    STOL_LAT, STOL_LON = 0.5 / 69.0, 0.5 / 53.0   # ½ mi keeper threshold
    def _summits(pts):
        if not obj_summits:
            return True
        return any(abs(la - sla) <= STOL_LAT and abs(lo - slo) <= STOL_LON
                   for la, lo in pts for sla, slo in obj_summits)
    print(f"box: lat {lat0:.3f}..{lat1:.3f}  lon {lon0:.3f}..{lon1:.3f}  (+{args.margin_mi}mi)")

    # signatures of tracks already collected for this report (any source)
    have = set()
    for f in gdir.glob("*.gpx"):
        if "peaks_only" in f.name or "landmarks" in f.name: continue
        s = sig(gpx_track_points(f))
        if s: have.add(s)

    import json
    added = 0
    for mid in scan_ids:
        fp = CALTOPO / f"{mid}.json"
        if not fp.exists(): continue
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
            if not _summits(pts):     # passes through the area but doesn't top out — skip
                continue
            title = ((ft.get("properties") or {}).get("title") or f"track{idx}")
            if SKIP_TITLE.search(title):   # running/biking/etc. — not route beta
                continue
            s = sig(pts)
            if s in have:   # already have this track from a web source
                continue
            have.add(s); idx += 1; added += 1
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
