#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_route_fidelity.py — the recommended route must FOLLOW a real recorded track.

Kyle (2026-06-22): these routes guide him in real time ON the mountain, so they must be
correct BEFORE the climb — they can't wait for his own _actual track. The route's error
vs where real people walked must be tiny ("I'd rather have 5 ft"). This measures the
route's DEVIATION from the nearest real source track — using point-to-SEGMENT distance
(not point-to-point), so a route copied faithfully from a track reads ~0 ft regardless of
how the track is sampled. A corner-cut or a graph shortcut strays far; a verbatim
(--from-track) or tightly-stitched (--legs) route stays on the line.

The grid rasterizes track SEGMENTS into cells (not just endpoints), so a route that sits
on a sparse/hand-drawn track reads ~0 ft instead of being falsely flagged — that fix turned
most apparent "outliers" into measurement artifacts. Real on-track routes read ≤2 ft; the
genuine problems are all ≥20 ft (clean bimodal split), so the default bar is 3 ft.

For each report's `*_recommended.gpx`: resample the route finely and, for every sample,
take the min distance to any SEGMENT of any SOURCE track in gpx/<slug>/ (excluding
peaks_only / landmarks / the route itself / drive-ins). The max is the worst off-trail
excursion. FAIL if it exceeds --max-ft (default 3).

Routes that genuinely can't reach the threshold from available third-party tracks need a
human look (and ultimately Kyle's own recording) — run with --list-fail to get that set;
they're tracked in scripts/fidelity_exceptions.txt as the inspection backlog.

    scripts/check_route_fidelity.py                 # all reports, 3 ft
    scripts/check_route_fidelity.py cuba_gulch_trio
    scripts/check_route_fidelity.py --max-ft 3 --strict
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
        "waypoints", "summit")
SAMPLE_M = 6.0


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
    out = []
    for trk in root.iter(NS + "trk"):
        seg = [(float(p.get("lat")), float(p.get("lon"))) for p in trk.iter(NS + "trkpt")]
        if len(seg) >= 2:
            out.append(seg)
    if not out:   # no <trk> structure — treat all points as one track
        pts = [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]
        if len(pts) >= 2:
            out.append(pts)
    return out


def source_tracks(slug: str):
    tracks = []
    for f in (GPX / slug).glob("*.gpx"):
        if any(s in f.name.lower() for s in SKIP):
            continue
        tracks.extend(trkpts(f))
    return tracks


def pt_seg_ft(p, a, b):
    """Distance (ft) from point p to segment a-b, in local-meter projection around p."""
    lat0 = math.radians(p[0])
    kx = 111320.0 * math.cos(lat0)
    ky = 110540.0
    ax, ay = (a[1] - p[1]) * kx, (a[0] - p[0]) * ky
    bx, by = (b[1] - p[1]) * kx, (b[0] - p[0]) * ky
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0.0:
        m = math.hypot(ax, ay)
    else:
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        m = math.hypot(ax + t * dx, ay + t * dy)
    return m * 3.28084


class SegGrid:
    """Grid of source-track POINTS → (track, index); query checks segments incident to
    nearby points, so we get true point-to-segment distance cheaply."""
    def __init__(self, tracks, cell_m):
        self.tracks = tracks
        self.cells = {}
        pts = [p for t in tracks for p in t]
        if not pts:
            self.dlat = None
            return
        mean_lat = sum(p[0] for p in pts) / len(pts)
        self.dlat = cell_m / 111000.0
        self.dlon = cell_m / (111000.0 * max(0.2, math.cos(math.radians(mean_lat))))
        # Rasterize each SEGMENT into every cell it crosses — so a long/sparse segment
        # (hand-drawn CalTopo line, coarse track) is found even when its endpoints are far
        # from the query point. Indexing only endpoints (the old way) missed those and
        # over-reported deviation for routes that were actually on a sparse track.
        for ti, t in enumerate(tracks):
            for si in range(len(t) - 1):
                a, b = t[si], t[si + 1]
                ca = (int(a[0] / self.dlat), int(a[1] / self.dlon))
                cb = (int(b[0] / self.dlat), int(b[1] / self.dlon))
                steps = max(abs(cb[0] - ca[0]), abs(cb[1] - ca[1]), 1)
                seen = set()
                for k in range(steps + 1):
                    f = k / steps
                    cell = (int((a[0] + (b[0] - a[0]) * f) / self.dlat),
                            int((a[1] + (b[1] - a[1]) * f) / self.dlon))
                    if cell not in seen:
                        seen.add(cell)
                        self.cells.setdefault(cell, []).append((ti, si))

    def dev_ft(self, p):
        if self.dlat is None:
            return float("inf")
        ci, cj = int(p[0] / self.dlat), int(p[1] / self.dlon)
        best = float("inf")
        seen = set()
        for a in (ci - 1, ci, ci + 1):
            for b in (cj - 1, cj, cj + 1):
                for ti, si in self.cells.get((a, b), ()):
                    if (ti, si) in seen:
                        continue
                    seen.add((ti, si))
                    t = self.tracks[ti]
                    best = min(best, pt_seg_ft(p, t[si], t[si + 1]))
        return best


def worst_deviation_ft(slug: str, cell_m: float):
    route = []
    rf = next((GPX / slug).glob("*recommended*.gpx"), None)
    if rf:
        for t in trkpts(rf):
            route.extend(t)
    if len(route) < 2:
        return None
    grid = SegGrid(source_tracks(slug), cell_m)
    worst = 0.0
    for i in range(len(route) - 1):
        a, b = route[i], route[i + 1]
        seg = hav(a[0], a[1], b[0], b[1])
        n = max(1, int(seg / SAMPLE_M))
        for k in range(n + 1):
            t = k / n
            worst = max(worst, grid.dev_ft((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)))
    return worst


def exceptions():
    """Slugs known to be off-track (no recorded track follows the trail there) — tracked
    in scripts/fidelity_exceptions.txt so the gate warns instead of failing until each is
    resolved (a Kyle recording / a human-approved connector). New reports aren't listed,
    so they MUST pass."""
    f = ROOT / "scripts" / "fidelity_exceptions.txt"
    out = set()
    if f.exists():
        for ln in f.read_text().splitlines():
            ln = ln.split("#")[0].strip()
            if ln:
                out.add(ln)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--max-ft", type=float, default=3.0)   # the achievable best (~0.2 ft) + GPS-noise margin
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--list-fail", action="store_true", help="print only the failing slugs")
    args = ap.parse_args()
    cell_m = 40.0   # search neighborhood ~120 m; enough to find the nearest real segment
    exempt = exceptions()

    slugs = []
    for sub in ("peaks", "trips"):
        for p in sorted((DOCS / sub).glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index.") or p.stem.count("."):
                continue
            if args.slug and p.stem != args.slug:
                continue
            slugs.append(p.stem)

    bad = warned = checked = 0
    for slug in slugs:
        dev = worst_deviation_ft(slug, cell_m)
        if dev is None:
            continue
        checked += 1
        tag = ">120" if math.isinf(dev) else f"{dev:6.0f}"
        if dev > args.max_ft:
            if slug in exempt:
                warned += 1
                if not args.list_fail:
                    print(f"warn  {slug:28s} {tag} ft off-track (tracked exception — needs review)")
            elif args.list_fail:
                print(slug)
            else:
                bad += 1
                print(f"FAIL  {slug:28s} strays {tag} ft from any recorded track")
        elif not args.list_fail:
            print(f"ok    {slug:28s} max {dev:4.1f} ft off-track")
    if not args.list_fail:
        print(f"\n{checked} route(s) — {bad} FAIL, {warned} tracked-exception, "
              f"vs {args.max_ft} ft bar.")
    if args.strict and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
