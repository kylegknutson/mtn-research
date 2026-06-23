#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_route_fidelity.py — the recommended route must FOLLOW a real recorded track.

Kyle (2026-06-22): the route's error vs where someone actually walked must be small —
"50 ft is a stretch." check_route_geometry only measured the gap between consecutive
route points (a crude teleport proxy that falsely fails good dense routes). This
measures the right thing: the **deviation** of the route from the nearest real source
track. A corner-cut strays hundreds of feet from the trail; a route built from real
tracks (--from-track / --legs / Kyle's recordings) stays within GPS noise.

For each report's `*_recommended.gpx`: densely sample along the line and, for every
sample, find the distance to the nearest point of any SOURCE track in gpx/<slug>/
(excluding peaks_only / landmarks / the route itself / drive-ins). The max of those
is the route's worst off-trail excursion. FAIL if it exceeds --max-ft (default 50).

    scripts/check_route_fidelity.py                 # all reports
    scripts/check_route_fidelity.py cimarron_coxcomb
    scripts/check_route_fidelity.py --max-ft 50 --strict
"""
from __future__ import annotations
import argparse, math, sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in",
        "waypoints", "summit", "actual")   # actual = Kyle recording is allowed as its OWN route via --from-track, but as a source it's fine too; keep it a source
SAMPLE_M = 8.0        # resample the route this finely so we catch mid-segment cuts
SEARCH_CELLS = 1      # 3x3 neighborhood


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def trkpts(path: Path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]


def source_points(slug: str):
    pts = []
    for f in (GPX / slug).glob("*.gpx"):
        if any(s in f.name.lower() for s in ("peaks_only", "landmark", "trailhead",
                                             "recommended", "_drive", "drive_in",
                                             "waypoints", "summit")):
            continue
        pts.extend(trkpts(f))
    return pts


class Grid:
    """Uniform lat/lon grid for fast nearest-point queries within ~cell_m."""
    def __init__(self, pts, cell_m):
        self.cells = {}
        if not pts:
            self.dlat = self.dlon = None
            return
        mean_lat = sum(p[0] for p in pts) / len(pts)
        self.dlat = cell_m / 111000.0
        self.dlon = cell_m / (111000.0 * max(0.2, math.cos(math.radians(mean_lat))))
        for la, lo in pts:
            self.cells.setdefault((int(la / self.dlat), int(lo / self.dlon)), []).append((la, lo))

    def nearest(self, la, lo):
        if self.dlat is None:
            return float("inf")
        ci, cj = int(la / self.dlat), int(lo / self.dlon)
        best = float("inf")
        for a in range(ci - SEARCH_CELLS, ci + SEARCH_CELLS + 1):
            for b in range(cj - SEARCH_CELLS, cj + SEARCH_CELLS + 1):
                for pa, po in self.cells.get((a, b), ()):
                    d = hav(la, lo, pa, po)
                    if d < best:
                        best = d
        return best


def worst_deviation(slug: str, cell_m: float):
    route = trkpts(next((GPX / slug).glob("*recommended*.gpx"), Path("/nonexistent")))
    if len(route) < 2:
        return None
    grid = Grid(source_points(slug), cell_m)
    worst = 0.0
    for i in range(len(route) - 1):
        a, b = route[i], route[i + 1]
        seg = hav(a[0], a[1], b[0], b[1])
        n = max(1, int(seg / SAMPLE_M))
        for k in range(n + 1):
            t = k / n
            la = a[0] + (b[0] - a[0]) * t
            lo = a[1] + (b[1] - a[1]) * t
            worst = max(worst, grid.nearest(la, lo))
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--max-ft", type=float, default=50.0)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    thresh_m = args.max_ft / 3.28084
    cell_m = max(thresh_m * 2, 25.0)   # search radius comfortably above the threshold

    slugs = []
    for sub in ("peaks", "trips"):
        for p in sorted((DOCS / sub).glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index.") or p.stem.count("."):
                continue
            if args.slug and p.stem != args.slug:
                continue
            slugs.append(p.stem)

    bad = checked = 0
    for slug in slugs:
        dev = worst_deviation(slug, cell_m)
        if dev is None:
            continue
        checked += 1
        ft = dev * 3.28084
        if dev > thresh_m:
            bad += 1
            print(f"FAIL  {slug:28s} strays {ft:6.0f} ft from any recorded track "
                  f"(max allowed {args.max_ft:.0f})")
        else:
            print(f"ok    {slug:28s} max {ft:5.0f} ft off-track")
    print(f"\n{checked} route(s) — {bad} exceed {args.max_ft:.0f} ft off-track.")
    if args.strict and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
