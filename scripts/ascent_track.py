#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["supabase"]
# ///
"""
ascent_track.py — match a peak's ascent(s) to Kyle's recorded iCloud GPS track(s).

The iCloud "GPS Tracks/" files are named YYYYMMDD_County_Activity_device_actual.gpx
— dated, not peak-tagged. peak_db ascents carry date_iso. This joins the two:
given a peak (name or id), it prints each ascent's date and the iCloud _actual
track file(s) recorded that day, so we can pull the track Kyle actually walked
(for summit-marker snapping, post-climb stats, etc.).

    scripts/ascent_track.py --peak "13,308"
    scripts/ascent_track.py --peak 13308          # by peak_db id
    scripts/ascent_track.py --peak "Gladstone"
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
TRACKS = Path("/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/Documents/GPS Tracks")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peak", required=True, help="peak_db id or display-name substring")
    args = ap.parse_args()

    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks, ascents

    P = list(peaks())
    if args.peak.isdigit():
        hits = [p for p in P if p["id"] == int(args.peak)]
    else:
        hits = [p for p in P if args.peak.lower() in str(p["display_name"]).lower() and p.get("state") == "CO"]
    if not hits:
        sys.exit(f"--peak {args.peak!r}: no match")

    for p in hits:
        print(f"\n{p['display_name']}  (id {p['id']}, {p['elevation_ft']}', {p.get('county')}, "
              f"{p['lat']:.5f},{p['lon']:.5f})")
        asc = ascents(peak_id=f"eq.{p['id']}")
        if not asc:
            print("  no ascents logged"); continue
        for a in asc:
            d = (a.get("date_iso") or "")
            ymd = d.replace("-", "")[:8]
            files = sorted(TRACKS.glob(f"{ymd}_*")) if ymd else []
            print(f"  {d or '(no date)'}  {a.get('climb_name') or ''}")
            for f in files:
                print(f"      → {f.name}")
            if ymd and not files:
                print(f"      (no iCloud track dated {ymd})")


if __name__ == "__main__":
    main()
