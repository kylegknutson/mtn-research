#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
sync_to_regional.py — add a research peak's GPX into its REGIONAL CalTopo map,
applying the imported-marker rules.

For the given <slug> (a gpx/<slug>/ directory) and regional map <map-id>:
  1. Tracks      → uploaded grouped by source, colored (LoJ red / 14ers green /
                   peakbagger blue), waypoints stripped, dedupe ON.
  2. Imported waypoints → summit pins (within ~75 m of an objective summit from
                   <slug>_peaks_only.gpx, or named like one) are DROPPED; all
                   other imported markers are recolored GRAY (symbol=point,
                   #9E9E9E), dedupe ON.
  3. Objective summits → uploaded from <slug>_peaks_only.gpx as BLUE MOUNTAIN
                   markers (symbol=peak, #2E78C7), dedupe ON (so "use mine" —
                   added only if not already present). This matches the existing
                   summit-marker scheme on the regional maps.

Dedupe is left ON for every step (regional maps accumulate many peaks). Run
fetch_caltopo.py --map <id> first so the local dedupe snapshot is current; this
script does that automatically.

Usage:
  scripts/sync_to_regional.py --slug crestolita_broken_hand --map-id VKGB00L
"""
from __future__ import annotations
import argparse, math, os, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

NS = "http://www.topografix.com/GPX/1/1"
ET.register_namespace("", NS)
NST = f"{{{NS}}}"
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

GRAY = "#9E9E9E"           # non-summit imported markers (symbol=point)
SUMMIT_COLOR = "#39FF14"  # objective summits — neon green mountain markers (symbol=peak)
SRC_COLOR = {"loj": "#FF0000", "14ers": "#00AA00", "pb": "#0066FF"}


def hav(la1, lo1, la2, lo2):
    R = 6371000.0; p = math.pi / 180
    a = math.sin((la2-la1)*p/2)**2 + math.cos(la1*p)*math.cos(la2*p)*math.sin((lo2-lo1)*p/2)**2
    return 2*R*math.asin(math.sqrt(a))


def source_of(fname: str) -> str:
    if "pbAscent" in fname: return "pb"
    if "14ers" in fname or "_unknown_" in fname: return "14ers"
    return "loj"


def read_summits(peaks_only: Path):
    out = []
    if not peaks_only.exists(): return out
    for w in ET.parse(peaks_only).getroot().iter(f"{NST}wpt"):
        out.append((float(w.get("lat")), float(w.get("lon")),
                    (w.findtext(f"{NST}name") or "").strip()))
    return out


def run_upload(gpx_path_or_dir: str, map_id: str, color: str, is_dir: bool, symbol: str = "point"):
    flag = "--gpx-dir" if is_dir else "--gpx"
    cmd = [str(SCRIPTS / "gpx_to_caltopo.py"), flag, gpx_path_or_dir,
           "--map-id", map_id, "--color", color, "--marker-symbol", symbol]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    up = sk = 0
    for line in out.splitlines():
        if line.startswith("Uploaded"):
            # "Uploaded N track(s) and M marker(s)."
            parts = line.replace("(s)", "").split()
            try: up = int(parts[1]) + int(parts[4])
            except Exception: pass
        if line.startswith("Skipped"):
            sk = line
    return up, sk, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--map-id", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gdir = ROOT / "gpx" / args.slug
    if not gdir.exists():
        sys.exit(f"No gpx dir: {gdir}")
    peaks_only = gdir / f"{args.slug}_peaks_only.gpx"
    summits = read_summits(peaks_only)

    track_files = [f for f in sorted(gdir.glob("*.gpx"))
                   if "peaks_only" not in f.name and "landmarks" not in f.name]

    print(f"\n=== {args.slug} → {args.map_id} ===")
    print(f"  {len(track_files)} track files · {len(summits)} objective summits")

    # refresh local dedupe snapshot
    if not args.dry_run:
        subprocess.run([str(SCRIPTS / "fetch_caltopo.py"), "--map", args.map_id],
                       capture_output=True, text=True)

    tmp = Path(tempfile.mkdtemp(prefix=f"sync_{args.slug}_"))
    # 1. tracks grouped by source, waypoints stripped
    groups = {"loj": [], "14ers": [], "pb": []}
    all_wpts = []
    for f in track_files:
        tree = ET.parse(f); root = tree.getroot()
        for w in list(root.findall(f"{NST}wpt")):
            all_wpts.append((float(w.get("lat")), float(w.get("lon")),
                             (w.findtext(f"{NST}name") or "").strip(),
                             w.findtext(f"{NST}ele")))
            root.remove(w)
        g = source_of(f.name)
        gd = tmp / g; gd.mkdir(exist_ok=True)
        tree.write(gd / f.name, xml_declaration=True, encoding="UTF-8")
        groups[g].append(f.name)

    total_tracks = 0
    for g, files in groups.items():
        if not files: continue
        if args.dry_run:
            print(f"  [tracks/{g}] would upload {len(files)} files as {SRC_COLOR[g]}")
            continue
        up, sk, _ = run_upload(str(tmp / g), args.map_id, SRC_COLOR[g], is_dir=True)
        total_tracks += up
        print(f"  [tracks/{g}] +{up}  ({sk or 'no skips'})")

    # 2. classify imported waypoints → gray (non-summit), drop summits
    def is_summit(lat, lon, name):
        if any(hav(lat, lon, sl, so) <= 75 for sl, so, _ in summits): return True
        n = name.lower()
        return any(sn.strip('"').lower().split(" (")[0] in n for _, _, sn in summits if sn)
    seen = set(); gray = []; dropped = 0
    for lat, lon, name, ele in all_wpts:
        if is_summit(lat, lon, name): dropped += 1; continue
        key = (round(lat, 4), round(lon, 4), name.lower())
        if key in seen: continue
        seen.add(key); gray.append((lat, lon, name, ele))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gray_path = tmp / f"{args.slug}_imported_gray.gpx"
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="mtn-research" xmlns="http://www.topografix.com/GPX/1/1">',
             f"  <metadata><time>{now}</time></metadata>"]
    for lat, lon, name, ele in gray:
        safe = (name or "wpt").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        et = f"<ele>{ele}</ele>" if ele else ""
        lines.append(f'  <wpt lat="{lat}" lon="{lon}">{et}<name>{safe}</name></wpt>')
    lines.append("</gpx>")
    gray_path.write_text("\n".join(lines))
    print(f"  imported waypoints: {len(all_wpts)} → {dropped} summit-dropped, {len(gray)} gray")

    if not args.dry_run and gray:
        up, sk, _ = run_upload(str(gray_path), args.map_id, GRAY, is_dir=False)
        print(f"  [markers/gray] +{up}  ({sk or 'no skips'})")

    # 3. objective summits → blue mountain markers (symbol=peak)
    if not args.dry_run and peaks_only.exists():
        up, sk, _ = run_upload(str(peaks_only), args.map_id, SUMMIT_COLOR, is_dir=False, symbol="peak")
        print(f"  [markers/summit] +{up}  ({sk or 'no skips'})")

    print(f"  DONE — {total_tracks} new tracks added")


if __name__ == "__main__":
    main()
