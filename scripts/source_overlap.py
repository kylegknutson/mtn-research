#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
source_overlap.py — measure how much each source's GPX duplicates the others.

Answers Kyle's question (2026-06-17): is LoJ's GPX mostly duplicates of 14ers /
peakbagger, or unique? Cross-site copies of the SAME outing get re-encoded
(different point counts), so a byte/point signature misses them. Instead we match
on the activity's shape: two tracks are the "same outing" when their measured
distance agrees within --dist-tol AND both endpoints are within --end-m.

For each report it buckets tracks by source (filename token: 14ers / _pb_ / _loj_)
and, for the named source, reports how many of its tracks have a same-outing match
in EITHER other source (duplicate) vs none (unique).

    scripts/source_overlap.py --source loj      # default; LoJ vs 14ers+pb
    scripts/source_overlap.py --source pb
"""
from __future__ import annotations
import argparse, math, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NON_TRACK = ("peaks_only", "landmark", "trailhead", "recommended", "_drive",
             "drive_in", "waypoints", "summit", "actual", "kyle")
TOKENS = {"14ers": ("14ers",), "pb": ("_pb_", "peakbagger"), "loj": ("_loj_", "listsofjohn")}


def pts(path):
    p = re.findall(r'lat="([-\d.]+)"\s+lon="([-\d.]+)"', path.read_text())
    return [(float(a), float(b)) for a, b in p]


def hav_m(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(x))


def dist_mi(pp):
    return sum(hav_m(pp[i][0], pp[i][1], pp[i+1][0], pp[i+1][1]) for i in range(len(pp)-1)) / 1609.34


def source_of(name):
    n = name.lower()
    for s, toks in TOKENS.items():
        if any(t in n for t in toks):
            return s
    return None


def same_outing(a, b, dist_tol, end_m):
    if not a or not b:
        return False
    da, db = a["d"], b["d"]
    if max(da, db) == 0 or abs(da - db) / max(da, db) > dist_tol:
        return False
    # endpoints, allowing the track to be recorded in either direction
    fwd = hav_m(*a["s"], *b["s"]) <= end_m and hav_m(*a["e"], *b["e"]) <= end_m
    rev = hav_m(*a["s"], *b["e"]) <= end_m and hav_m(*a["e"], *b["s"]) <= end_m
    return fwd or rev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="loj", choices=["loj", "pb", "14ers"])
    ap.add_argument("--dist-tol", type=float, default=0.04)
    ap.add_argument("--end-m", type=float, default=250.0)
    args = ap.parse_args()

    tot_dup = tot_uniq = 0
    reports = 0
    for d in sorted(p for p in GPX.iterdir() if p.is_dir()):
        tracks = {"14ers": [], "pb": [], "loj": []}
        for f in d.glob("*.gpx"):
            if any(x in f.name.lower() for x in NON_TRACK):
                continue
            s = source_of(f.name)
            if not s:
                continue
            pp = pts(f)
            if len(pp) < 2:
                continue
            tracks[s].append({"f": f.name, "d": dist_mi(pp), "s": pp[0], "e": pp[-1]})
        mine = tracks[args.source]
        if not mine:
            continue
        others = [t for s in tracks if s != args.source for t in tracks[s]]
        dup = sum(1 for t in mine if any(same_outing(t, o, args.dist_tol, args.end_m) for o in others))
        uniq = len(mine) - dup
        tot_dup += dup; tot_uniq += uniq; reports += 1
        print(f"  {d.name:26s} {args.source}={len(mine):2d}  dup={dup:2d}  unique={uniq:2d}"
              + (f"  (others: 14ers={len(tracks['14ers'])} pb={len(tracks['pb'])})" if uniq or dup else ""))

    n = tot_dup + tot_uniq
    print(f"\n{args.source.upper()} across {reports} report(s): {n} tracks — "
          f"{tot_dup} duplicate ({100*tot_dup//n if n else 0}%), {tot_uniq} unique ({100*tot_uniq//n if n else 0}%)")
    print(f"(same-outing = distance within {args.dist_tol*100:.0f}% AND both endpoints within {args.end_m:.0f} m)")


if __name__ == "__main__":
    main()
