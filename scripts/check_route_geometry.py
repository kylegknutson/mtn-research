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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gpx_root import gpx_roots, glob_gpx   # worktree-aware gpx resolution
NS = "{http://www.topografix.com/GPX/1/1}"

# A real leg's consecutive points are < ~0.1 mi apart. Composed routes can show
# ~0.4-0.5 mi gaps where two source tracks are stitched at a shared waypoint; those
# are acceptable. A multi-mile hop is always a router teleport.
# TODO (Kyle, 2026-06-22): FAIL_MI=1.0 only catches multi-mile teleports — it let a
# 0.77 mi corner-cut ship on cimarron's Fortress day as a mere warn. Lower to ~0.7 to
# catch sub-mile corner-cuts, but that also flags hunts_peak (whose only clean recorded
# route is a 12.6 mi point-to-point shuttle, not a loop) — needs a hunts route decision
# first. build_trip_day_routes.py now defaults to --legs so trip day routes don't cut.
WARN_MI = 0.5
FAIL_MI = 1.0


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


def main():
    ap = argparse.ArgumentParser(description="Catch teleports in recommended routes")
    ap.add_argument("slug", nargs="?", help="check one slug (default: all)")
    ap.add_argument("--warn-mi", type=float, default=WARN_MI)
    ap.add_argument("--fail-mi", type=float, default=FAIL_MI)
    args = ap.parse_args()

    if args.slug:
        files = sorted(glob_gpx(GPX_ROOT.parent, args.slug, "*_recommended.gpx"))
    else:
        slugs = sorted({p.name for r in gpx_roots(GPX_ROOT.parent) if r.is_dir()
                        for p in r.iterdir() if p.is_dir()})
        files = [f for s in slugs for f in sorted(glob_gpx(GPX_ROOT.parent, s, "*_recommended.gpx"))]

    if not files:
        print("No *_recommended.gpx routes found.")
        return 0

    fails, warns = 0, 0
    for f in files:
        d, idx, p0, p1 = worst_jump(f)
        slug = f.parent.name
        if d > args.fail_mi:
            fails += 1
            print(f"FAIL  {slug:28s} teleport: {d:.2f} mi jump within a segment "
                  f"@idx{idx}  {p0} -> {p1}")
        elif d > args.warn_mi:
            warns += 1
            print(f"warn  {slug:28s} long jump: {d:.2f} mi within a segment @idx{idx}")
        else:
            print(f"ok    {slug:28s} max within-segment gap {d:.2f} mi")

    print(f"\n{len(files)} route(s) checked — {fails} FAIL, {warns} warn.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
