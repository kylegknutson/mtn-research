#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["supabase"]
# ///
"""
find_peaks_near.py — ranked peaks near a point or a named peak, with climbed status.

Replaces the inline peak_db spatial lookups I kept hand-writing (Campbell, Adams,
Wayah, Clohesey, 2026-06). Use it to turn a screenshot/cluster into the actual
peak set: which ranked 13ers+ are near here, which are unclimbed, and every
source id you need to sweep them.

Usage:
    scripts/find_peaks_near.py --near "Mount Oklahoma" --radius-mi 4
    scripts/find_peaks_near.py --center 39.18,-106.51 --radius-mi 3.5
    scripts/find_peaks_near.py --near "Magdalene Mountain" --all          # include unranked
    scripts/find_peaks_near.py --center 38.9,-106.4 --climber emily        # Emily's climbed status

Climbed status: Kyle's peak_db ascents by default; --climber <slug> scrapes that
climber's 14ers checklist (climbers/<slug>.yml) instead.
"""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"


def mi(a, b, c, d):
    R = 3958.8
    la1, lo1, la2, lo2 = map(math.radians, [a, b, c, d])
    return 2 * R * math.asin(math.sqrt(math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2))


def climbed_ids(climber: str | None) -> set:
    if not climber or climber == "kyle":
        sys.path.insert(0, PEAKDB)
        from peak_db_client import ascents
        return {a["peak_id"] for a in ascents()}
    # other climber → scrape their 14ers checklist via the existing script
    import subprocess, re
    r = subprocess.run([str(ROOT / "scripts" / "scrape_14ers_checklist.py"), "--climber", climber],
                       capture_output=True, text=True)
    m = re.search(r"peak_db ids climbed.*?\n\s*([\d,\s]+)", r.stdout, re.S)
    return {int(x) for x in re.findall(r"\d+", m.group(1))} if m else set()


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--near", help="peak name (uses its peak_db coords as the center)")
    g.add_argument("--center", help="'lat,lon'")
    ap.add_argument("--radius-mi", type=float, default=4.0)
    ap.add_argument("--all", action="store_true", help="include unranked peaks")
    ap.add_argument("--climber", default="kyle", help="climbed-status source (default kyle)")
    args = ap.parse_args()

    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks, find_peak
    P = list(peaks())

    if args.center:
        clat, clon = (float(x) for x in args.center.split(","))
        label = args.center
    else:
        hit = [r for r in (find_peak(args.near) or []) if r.get("state") == "CO"]
        if not hit:
            sys.exit(f"--near {args.near!r}: not found in peak_db")
        clat, clon, label = hit[0]["lat"], hit[0]["lon"], hit[0]["display_name"]

    done = climbed_ids(args.climber)
    rows = []
    for p in P:
        if p.get("lat") is None or p.get("state") != "CO":
            continue
        if not args.all and not p.get("ranked"):
            continue
        d = mi(clat, clon, p["lat"], p["lon"])
        if d <= args.radius_mi:
            rows.append((d, p))

    print(f"Ranked peaks within {args.radius_mi} mi of {label}  (climbed = {args.climber}):")
    print(f"  {'mi':>4}  {'id':>4}  {'name':22} {'elev':>6} {'cls':>4} {'rank':>5}  {'14ers':>6} {'pb':>6}  status")
    for d, p in sorted(rows, key=lambda r: r[0]):   # key: distance ties must not compare the peak dicts
        st = "✓ climbed" if p["id"] in done else "✗ UNCLIMBED"
        print(f"  {d:4.2f}  {p['id']:>4}  {str(p['display_name'])[:22]:22} {p['elevation_ft']:>6} "
              f"{str(p.get('yds_class')):>4} {str(p.get('co_rank')):>5}  "
              f"{str(p.get('fourteeners_id')):>6} {str(p.get('peakbagger_id')):>6}  {st}")
    n_unc = sum(1 for _, p in rows if p["id"] not in done)
    print(f"\n{len(rows)} ranked peak(s); {n_unc} unclimbed by {args.climber}.")


if __name__ == "__main__":
    main()
