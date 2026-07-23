#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
check_route_geometry.py — QA gate that catches "teleports" in recommended routes.

The failure (Kyle caught it, automation didn't, 2026-06-15): the composed
recommended route for a report had a ~6.45-mi straight-line jump where the graph
router shortcut a long approach instead of following the trail. It rendered as a
normal-looking magenta line, loaded tiles fine, wasn't clipped — so every existing
gate (check_maps / check_map_extents / check_reports) passed it. The only tell was
the geometry itself: two *consecutive* points an implausible distance apart.

This gate measures the gap between consecutive points WITHIN each track segment
(<trkseg>). A real recorded or composed leg has densely-spaced points (well under
a tenth of a mile apart); a teleport is a single multi-mile straight hop.

Crucially it checks *within* a segment, not across segments — so a deliberately
discontinuous route (e.g. two separate out-and-back climbs in one GPX, each its
own <trkseg>) is NOT flagged. That's an intentional break, not a teleport.

  FAIL  teleport      — a within-segment jump > FAIL_MI (no legitimate leg has
                        consecutive points this far apart)
  warn  long jump      — a within-segment jump > WARN_MI (eyeball it)

Exit non-zero on any FAIL. Wire into build_report.py --finalize alongside the
pixel gates.

Usage:
    scripts/check_route_geometry.py                 # all gpx/*/*_recommended.gpx
    scripts/check_route_geometry.py rio_grande_pyramid_three   # one slug
    scripts/check_route_geometry.py --warn-mi 0.4 --fail-mi 0.8
"""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path
import xml.etree.ElementTree as ET

GPX_ROOT = Path(__file__).resolve().parent.parent / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"

# A real leg's consecutive points are < ~0.15 mi apart (natural OSM/GPS spacing).
# Anything larger is either a router teleport or an off-trail spur that should have
# been densified. Both belong to the author to eliminate — a human following the
# recommended route on their phone shouldn't see a straight-line jump. If a real
# off-trail spur is unavoidable, densify it with intermediate waypoints so the
# largest consecutive-point gap stays under FAIL_MI. (Kyle, 2026-07-22: caught
# 0.54 mi camp spurs on rito_alto_group that had escaped as mere warns; tightened
# so gate catches them, not the human reviewer.)
WARN_MI = 0.2
FAIL_MI = 0.5

# Straight-line-run check — catch densified spurs (linear interpolation between two
# far-apart points looks like a "teleport" on the map even at small per-pair gaps).
# The interpolation SIGNATURE is MANY roughly-equal collinear points (I densify a spur
# every ~250 ft → a 0.5 mi fake spur = ~11 near-identical-bearing segments). A real
# recorded track / OSM trail that happens to run straight has only a FEW sparse points
# across the same distance (2-3 long segments). So FAIL requires BOTH a long collinear
# run AND many segments in it; a long-but-sparse run only warns (eyeball it).
# Kyle, 2026-07-22: caught a 0.53 mi / 11-segment densified spur on rito_alto_group
# day 3 that the gap-only check missed; tuned to NOT false-fire on carter_dome /
# clohesey_four (real 2-segment straight trail stretches).
STRAIGHT_WARN_MI = 0.15
STRAIGHT_FAIL_MI = 0.30
STRAIGHT_FAIL_MIN_SEGS = 5   # interpolation signature: many collinear points
BEARING_TOL_DEG = 5.0


def hav_mi(a, b):
    R = 3958.8
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def segments(path: Path):
    """Yield lists of (lat, lon) — one per <trkseg> (deliberate breaks separate them)."""
    root = ET.parse(path).getroot()
    for seg in root.iter(NS + "trkseg"):
        pts = [(float(p.get("lat")), float(p.get("lon"))) for p in seg.iter(NS + "trkpt")]
        if len(pts) >= 2:
            yield pts


def worst_jump(path: Path):
    """(jump_mi, idx, p0, p1) of the largest within-segment consecutive gap."""
    worst = (0.0, -1, None, None)
    for pts in segments(path):
        for i in range(len(pts) - 1):
            d = hav_mi(pts[i], pts[i + 1])
            if d > worst[0]:
                worst = (d, i, pts[i], pts[i + 1])
    return worst


def _bearing(a, b):
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return math.degrees(math.atan2(y, x))


def worst_straight_run(path: Path):
    """(run_mi, n_segs, start_idx, end_idx, p0, p1) of the longest run of consecutive
    segments whose bearing change stays within BEARING_TOL_DEG. n_segs distinguishes a
    densified interpolation (many segments) from a sparse-but-straight real trail."""
    worst = (0.0, 0, -1, -1, None, None)
    for pts in segments(path):
        if len(pts) < 3:
            continue
        brgs = [_bearing(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
        i = 0
        while i < len(brgs) - 1:
            total = hav_mi(pts[i], pts[i + 1])
            j = i
            while j + 1 < len(brgs):
                db = (brgs[j + 1] - brgs[j] + 180) % 360 - 180
                if abs(db) < BEARING_TOL_DEG:
                    j += 1
                    total += hav_mi(pts[j], pts[j + 1])
                else:
                    break
            if total > worst[0]:
                worst = (total, j + 1 - i, i, j + 1, pts[i], pts[j + 1])
            i = j + 1
    return worst


def main():
    ap = argparse.ArgumentParser(description="Catch teleports in recommended routes")
    ap.add_argument("slug", nargs="?", help="check one slug (default: all)")
    ap.add_argument("--warn-mi", type=float, default=WARN_MI)
    ap.add_argument("--fail-mi", type=float, default=FAIL_MI)
    args = ap.parse_args()

    if args.slug:
        files = sorted((GPX_ROOT / args.slug).glob("*_recommended.gpx"))
    else:
        files = sorted(GPX_ROOT.glob("*/*_recommended.gpx"))

    if not files:
        print("No *_recommended.gpx routes found.")
        return 0

    fails, warns = 0, 0
    for f in files:
        d, idx, p0, p1 = worst_jump(f)
        sd, sn, si, sj, sp0, sp1 = worst_straight_run(f)
        slug = f.parent.name
        # Gap failure: teleport
        if d > args.fail_mi:
            fails += 1
            print(f"FAIL  {slug:28s} teleport: {d:.2f} mi jump within a segment "
                  f"@idx{idx}  {p0} -> {p1}")
            continue
        # Straight-line-run failure: densified spur (long AND many collinear segments)
        if sd > STRAIGHT_FAIL_MI and sn >= STRAIGHT_FAIL_MIN_SEGS:
            fails += 1
            print(f"FAIL  {slug:28s} straight-line teleport: {sd:.2f} mi collinear run "
                  f"over {sn} segs (densified spur) @idx{si}..{sj}  {sp0} -> {sp1}")
            continue
        # Warnings
        if d > args.warn_mi:
            warns += 1
            print(f"warn  {slug:28s} long jump: {d:.2f} mi within a segment @idx{idx}")
        elif sd > STRAIGHT_WARN_MI:
            warns += 1
            print(f"warn  {slug:28s} straight-line run: {sd:.2f} mi over {sn} segs "
                  f"(≥{STRAIGHT_FAIL_MI} mi & ≥{STRAIGHT_FAIL_MIN_SEGS} segs would FAIL) @idx{si}..{sj}")
        else:
            print(f"ok    {slug:28s} max gap {d:.2f} mi, longest straight-run {sd:.2f} mi")

    print(f"\n{len(files)} route(s) checked — {fails} FAIL, {warns} warn.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
