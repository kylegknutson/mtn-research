#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
build_peak_gpx.py — generate a report's waypoint GPX from peak_db + a config.

Generic replacement for the hardcoded build_close_5_gpx.py. For a given <slug>
it reads gpx/<slug>/peaks.yml and writes:
  gpx/<slug>/<slug>_peaks_only.gpx  — objective summit(s) + (optionally) nearby
                                      unclimbed ranked 13er+ neighbors
  gpx/<slug>/<slug>_landmarks.gpx   — trailheads + drive-in landmarks

Summit coords/names/elevations come from peak_db (authoritative). Trailhead and
landmark coords are hand-researched and live in the config (peak_db has no TH
data). "Nearby unclimbed ranked" is computed from peak_db (within radius, ranked,
13k+, not in Kyle's ascents) and filtered by an explicit `exclude` list so a
geographically-near-but-different-drive peak (the Bartlett lesson) is left off.

Config format (gpx/<slug>/peaks.yml):
    objective_ids: [258, 524]      # peak_db ids of the report's target peak(s)
    nearby:
      include: true                # add nearby unclimbed ranked neighbors
      radius_mi: 8
      exclude: [402]               # peak_db ids to leave off (different drive)
    landmarks:
      - {name: "South Colony 2WD TH", lat: 37.97592, lon: -105.50657, ele_ft: 9880, kind: trailhead}
      - {name: "Broken Hand Pass", lat: 37.9614, lon: -105.5760, ele_ft: 12900, kind: landmark}

Usage:
    scripts/build_peak_gpx.py --slug crestolita_broken_hand
    scripts/build_peak_gpx.py --slug crestolita_broken_hand --dry-run
"""
from __future__ import annotations
import argparse, math, sys
from datetime import datetime, timezone
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
from peak_db_client import peaks, ascents, peak_lists  # noqa: E402

LIST_ID = "co_13_14ers"


def hav_mi(la1, lo1, la2, lo2):
    R = 3958.8; p = math.pi / 180
    a = (math.sin((la2-la1)*p/2)**2
         + math.cos(la1*p)*math.cos(la2*p)*math.sin((lo2-lo1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))


def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_gpx(path: Path, wpts: list[dict], dry: bool):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="build_peak_gpx.py" xmlns="http://www.topografix.com/GPX/1/1">',
             f"  <metadata><time>{now}</time></metadata>"]
    for w in wpts:
        ele = f"<ele>{w['ele_ft']*0.3048:.1f}</ele>" if w.get("ele_ft") else ""
        sym = w.get("sym", "point")
        lines.append(f'  <wpt lat="{w["lat"]}" lon="{w["lon"]}">{ele}<name>{esc(w["name"])}</name><sym>{sym}</sym></wpt>')
    lines.append("</gpx>")
    if dry:
        print(f"  [dry] would write {path.relative_to(ROOT)} ({len(wpts)} wpts)")
    else:
        path.write_text("\n".join(lines) + "\n")
        print(f"  wrote {path.relative_to(ROOT)} ({len(wpts)} wpts)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gdir = ROOT / "gpx" / args.slug
    cfg_path = gdir / "peaks.yml"
    if not cfg_path.exists():
        sys.exit(f"No config: {cfg_path}\nCreate it (see this script's docstring for the format).")
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    obj_ids = cfg.get("objective_ids") or []
    if not obj_ids:
        sys.exit("config needs objective_ids: [<peak_db id>, ...]")

    by_id = {p["id"]: p for p in peaks()}
    climbed = {a["peak_id"] for a in ascents()}
    in_list = {r["peak_id"] for r in peak_lists() if r["list_id"] == LIST_ID}

    # objective summits → blue peak (sym=peak)
    peak_wpts = []
    objs = []
    for pid in obj_ids:
        p = by_id.get(pid)
        if not p:
            print(f"  WARN objective id {pid} not in peak_db"); continue
        objs.append(p)
        cls = p.get("yds_class")
        label = f'{p["display_name"].strip(chr(34))} ({p["elevation_ft"]}\''
        label += f", Class {cls}" if cls else ""
        label += ", UNCLIMBED)" if p["id"] not in climbed else ")"
        peak_wpts.append({"name": label, "lat": p["lat"], "lon": p["lon"],
                          "ele_ft": p["elevation_ft"], "sym": "peak"})

    # nearby unclimbed ranked neighbors
    nb = cfg.get("nearby") or {}
    if nb.get("include"):
        radius = float(nb.get("radius_mi", 8))
        exclude = set(nb.get("exclude") or []) | set(obj_ids)
        cands = []
        for p in by_id.values():
            if p["id"] in exclude: continue
            if p.get("state") != "CO" or not p.get("lat"): continue
            if p["id"] not in in_list or not p.get("ranked"): continue
            if p.get("elevation_ft", 0) < 13000: continue
            if p["id"] in climbed: continue
            d = min(hav_mi(o["lat"], o["lon"], p["lat"], p["lon"]) for o in objs)
            if d <= radius:
                cands.append((d, p))
        for d, p in sorted(cands):
            peak_wpts.append({
                "name": f'{p["display_name"].strip(chr(34))} ({p["elevation_ft"]}\', UNCLIMBED, {d:.1f}mi)',
                "lat": p["lat"], "lon": p["lon"], "ele_ft": p["elevation_ft"], "sym": "peak"})
        print(f"  nearby unclimbed ranked within {radius:.0f}mi: {len(cands)} "
              f"(excluded {len(set(nb.get('exclude') or []))})")

    # landmarks
    lm_wpts = []
    for lm in (cfg.get("landmarks") or []):
        lm_wpts.append({"name": lm["name"], "lat": lm["lat"], "lon": lm["lon"],
                        "ele_ft": lm.get("ele_ft"), "sym": "point"})

    gdir.mkdir(parents=True, exist_ok=True)
    write_gpx(gdir / f"{args.slug}_peaks_only.gpx", peak_wpts, args.dry_run)
    write_gpx(gdir / f"{args.slug}_landmarks.gpx", lm_wpts, args.dry_run)


if __name__ == "__main__":
    main()
