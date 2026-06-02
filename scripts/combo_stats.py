#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
combo_stats.py — distance / gain / elevation from one or more GPX tracks.

Pure stdlib, no auth. Replaces the inline python we kept re-writing to read
combo stats off trip-report GPX.

Usage:
    scripts/combo_stats.py gpx/crestolita_broken_hand/*loj*.gpx
    scripts/combo_stats.py --slug crestolita_broken_hand        # all tracks in gpx/<slug>/
    scripts/combo_stats.py --slug savage_peak --best            # just the single best (longest) track summary

Output per file: distance (mi), cumulative gain (ft), min/max elev (ft), #points.
With --slug, also prints a combined range across all tracks (the figure to quote
in a report's stats table).
"""
from __future__ import annotations
import argparse, glob, math, sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://www.topografix.com/GPX/1/1}"
ROOT = Path(__file__).resolve().parent.parent
M_TO_FT = 3.28084


def haversine_mi(la1, lo1, la2, lo2):
    R = 3958.8
    p = math.pi / 180
    a = (math.sin((la2-la1)*p/2)**2
         + math.cos(la1*p)*math.cos(la2*p)*math.sin((lo2-lo1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))


def track_stats(path: Path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    pts = []
    for tp in root.iter(f"{NS}trkpt"):
        lat = float(tp.get("lat")); lon = float(tp.get("lon"))
        ele = tp.findtext(f"{NS}ele")
        pts.append((lat, lon, float(ele) if ele else None))
    if len(pts) < 2:
        return None
    dist = 0.0
    gain = 0.0
    for i in range(1, len(pts)):
        la1, lo1, e1 = pts[i-1]; la2, lo2, e2 = pts[i]
        dist += haversine_mi(la1, lo1, la2, lo2)
        if e1 is not None and e2 is not None and e2 > e1:
            gain += (e2 - e1) * M_TO_FT
    elevs = [e * M_TO_FT for _, _, e in pts if e is not None]
    return {
        "dist_mi": dist,
        "gain_ft": gain,
        "min_ft": min(elevs) if elevs else None,
        "max_ft": max(elevs) if elevs else None,
        "npts": len(pts),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="GPX files (globs ok)")
    ap.add_argument("--slug", help="Use all track files in gpx/<slug>/ (excludes peaks_only/landmarks)")
    ap.add_argument("--best", action="store_true", help="Only print the longest track + the combined range")
    args = ap.parse_args()

    files: list[Path] = []
    if args.slug:
        for f in sorted((ROOT / "gpx" / args.slug).glob("*.gpx")):
            if "peaks_only" in f.name or "landmarks" in f.name:
                continue
            files.append(f)
    files += [Path(p) for pat in args.files for p in glob.glob(pat)]
    if not files:
        sys.exit("No GPX files. Use --slug <slug> or pass file paths/globs.")

    rows = []
    for f in files:
        s = track_stats(f)
        if s:
            rows.append((f, s))
        elif not args.best:
            print(f"  (no track) {f.name}")

    if not rows:
        sys.exit("No track data found.")

    if not args.best:
        print(f"{'distance':>9}  {'gain':>8}  {'elev range':>16}  {'pts':>6}  file")
        for f, s in rows:
            er = f"{s['min_ft']:.0f}-{s['max_ft']:.0f}'" if s['min_ft'] else "—"
            print(f"{s['dist_mi']:>7.1f}mi  {s['gain_ft']:>6.0f}'  {er:>16}  {s['npts']:>6}  {f.name}")

    # Robust aggregate: drop tracks with no elevation data (gain==0) and distance
    # outliers (> 2.5x the median distance — e.g. a TR where the peak was a minor
    # add to a much longer day) so the quoted range reflects the actual objective.
    dists = sorted(s['dist_mi'] for _, s in rows)
    med = dists[len(dists)//2]
    core = [(f, s) for f, s in rows if s['gain_ft'] > 0 and s['dist_mi'] <= 2.5 * med]
    used = core or rows
    n_drop = len(rows) - len(used)
    dmin = min(s['dist_mi'] for _, s in used); dmax = max(s['dist_mi'] for _, s in used)
    gmin = min(s['gain_ft'] for _, s in used); gmax = max(s['gain_ft'] for _, s in used)
    longest = max(used, key=lambda r: r[1]['dist_mi'])
    print(f"\nAcross {len(used)} track(s)" + (f" ({n_drop} outlier/no-elev dropped)" if n_drop else "") + ":")
    print(f"  distance range: {dmin:.1f}–{dmax:.1f} mi")
    print(f"  gain range:     {gmin:.0f}–{gmax:.0f} ft")
    print(f"  longest track:  {longest[0].name}  ({longest[1]['dist_mi']:.1f} mi / {longest[1]['gain_ft']:.0f} ft)")
    print(f"  STATS_LINE: ~{dmin:.0f}–{dmax:.0f} mi, ~{round(gmin,-2):.0f}–{round(gmax,-2):.0f} ft")


if __name__ == "__main__":
    main()
