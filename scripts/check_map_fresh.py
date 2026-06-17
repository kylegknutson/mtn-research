#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
check_map_fresh.py — catch overview PNGs that are out of date with their GPX.

Kyle (2026-06-17): Star + Gladstone PNGs were missing the recommended route /
LoJ+pb legend because the PNG was built BEFORE the route/tracks were added, and
nothing flagged the staleness. This is the safety net: a report's
docs/maps/<slug>.png must be at least as new as its composed route and its source
tracks, or it's drawing a stale picture.

FAILs (with --strict) when, for a report that has an overview PNG:
  * its `*_recommended.gpx` is newer than the PNG  (route likely missing/stale), or
  * any source track (trk_*/14ers/loj/pb) is newer than the PNG  (legend stale).
Fix = re-run `scripts/make_overview_map.py <slug>`.

    scripts/check_map_fresh.py            # audit all
    scripts/check_map_fresh.py gladstone_peak
    scripts/check_map_fresh.py --strict   # gate
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
MAPS = ROOT / "docs" / "maps"
SKIP = ("peaks_only", "landmark", "trailhead", "_drive", "drive_in", "waypoints",
        "summit", "actual", "kyle")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    dirs = [GPX / args.slug] if args.slug else sorted(d for d in GPX.iterdir() if d.is_dir())
    stale = 0
    checked = 0
    for d in dirs:
        png = MAPS / f"{d.name}.png"
        if not png.exists():
            continue
        checked += 1
        pmt = png.stat().st_mtime
        newer = []
        for f in d.glob("*.gpx"):
            n = f.name.lower()
            if any(x in n for x in SKIP):
                continue
            if f.stat().st_mtime > pmt + 1:   # 1s slack
                tag = "route" if "recommended" in n else "track"
                newer.append(tag)
        if newer:
            stale += 1
            kinds = "route+tracks" if "route" in newer and "track" in newer else \
                    ("route" if "route" in newer else "tracks")
            print(f"STALE  {d.name:26s} PNG older than {kinds} — re-run make_overview_map.py {d.name}")
    print(f"\n{checked} map(s) checked — {stale} stale.")
    if args.strict and stale:
        sys.exit(1)


if __name__ == "__main__":
    main()
