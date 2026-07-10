#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_trip_continuity.py — recommended lines must form a coherent, on-plan system.

Kyle (2026-07-10, jupiter_pigeon_turret): verbatim party tracks shipped as day routes
carried FOREIGN SUMMITS (Sunlight/Windom on the Jupiter day, another basin's approach
on the Monitor day) and didn't start at the planned camps — "a human uses these tracks
to do all of their navigation." No gate caught it. Two checks:

1. FOREIGN-SUMMIT (every slug): no *recommended*.gpx line may pass within --summit-tol
   (default 400 ft) of a RANKED peak (docs/data/peaks.json) that is not in the slug's
   objective_ids. Extra summits on a navigation line are never accidental conveniences —
   they mean the line follows some party's bigger day.

2. CHAIN ANCHORS (slugs whose peaks.yml has `legs:`): every recommended line must START
   and END within --chain-tol (default 0.3 mi) of a named anchor — a `kind: trailhead`
   landmark, a `*_target_peaks_only.gpx` camp waypoint, or a days-entry `start:` camp.
   That's what makes the day lines + legs a connected TH→camp→…→TH system.

    scripts/check_trip_continuity.py jupiter_pigeon_turret --strict
    scripts/check_trip_continuity.py --strict            # all slugs
"""
from __future__ import annotations
import argparse, json, math, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
PEAKS_JSON = ROOT / "docs" / "data" / "peaks.json"


def hav_ft(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x)) * 3.28084


def track_pts(path: Path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]


def wpts(path: Path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [(float(w.get("lat")), float(w.get("lon"))) for w in root.iter(NS + "wpt")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--summit-tol", type=float, default=400.0, help="ft")
    ap.add_argument("--chain-tol", type=float, default=0.3, help="mi")
    args = ap.parse_args()

    ranked = json.loads(PEAKS_JSON.read_text())["peaks"]
    fails = 0
    dirs = [GPX / args.slug] if args.slug else sorted(p for p in GPX.iterdir() if p.is_dir())
    for d in dirs:
        yml = d / "peaks.yml"
        if not yml.exists():
            continue
        cfg = yaml.safe_load(yml.read_text()) or {}
        # extra_summits = ranked peaks the route DELIBERATELY crosses en route
        # (declared, so a pass-over is a decision — not a leaked bigger day).
        obj_ids = set(cfg.get("objective_ids") or []) | set(cfg.get("extra_summits") or [])
        routes = sorted(d.glob("*recommended*.gpx"))
        if not routes:
            continue

        # 1) foreign summits — thin each route to ~50 m and test ranked non-objectives
        for f in routes:
            pts = track_pts(f)
            if len(pts) < 2:
                continue
            thin = pts[:: max(1, len(pts) // 2000)]
            hits = {}
            for pk in ranked:
                if pk["id"] in obj_ids:
                    continue
                # cheap bbox prefilter (~0.01° ≈ 0.7 mi)
                if not any(abs(pk["lat"] - la) < 0.01 and abs(pk["lon"] - lo) < 0.013
                           for la, lo in thin):
                    continue
                close = min(hav_ft(pk["lat"], pk["lon"], la, lo) for la, lo in pts)
                if close <= args.summit_tol:
                    hits[pk["n"]] = int(close)
            if hits:
                fails += 1
                lst = ", ".join(f"{n} ({ft} ft)" for n, ft in hits.items())
                print(f"FAIL  {d.name:26s} {f.name}: passes over NON-objective ranked "
                      f"summit(s): {lst}")

        # 2) chain anchors — only for trips that define legs:
        if cfg.get("legs"):
            anchors = [(l["lat"], l["lon"]) for l in (cfg.get("landmarks") or [])
                       if l.get("kind") == "trailhead"]
            for tf in d.glob("*_target_peaks_only.gpx"):
                anchors += wpts(tf)
            for day in (cfg.get("days") or []):
                if day.get("start"):
                    la, lo = day["start"].split(",")
                    anchors.append((float(la), float(lo)))
            for f in routes:
                pts = track_pts(f)
                if len(pts) < 2:
                    continue
                for which, (la, lo) in (("start", pts[0]), ("end", pts[-1])):
                    near = min(hav_ft(a, b, la, lo) for a, b in anchors) / 5280.0
                    if near > args.chain_tol:
                        fails += 1
                        print(f"FAIL  {d.name:26s} {f.name}: {which} is {near:.2f} mi "
                              f"from every TH/camp anchor — chain is broken")

    n = len(dirs)
    print(f"\n{n} slug(s) checked — {fails} continuity/foreign-summit failure(s).")
    if args.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
