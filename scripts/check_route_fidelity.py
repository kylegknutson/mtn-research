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

A route PASSES when every over-bar excursion is inside a human-accepted problem area
(gpx/<slug>/route_accepted.yml, written by accept_route.py after Kyle reviews the inspect
map). So an off-track route fails ONLY until Kyle accepts it; once accepted, that specific
area stops failing but a NEW deviation elsewhere still does. This acceptance model is what
lets the gate be blocking without a "warn and continue" — every FAIL is a genuinely
un-reviewed problem. Un-accepted failures: run inspect_route.py <slug> for the map.

    scripts/check_route_fidelity.py                 # all reports, 3 ft
    scripts/check_route_fidelity.py jacque_peak
    scripts/check_route_fidelity.py --max-ft 3 --strict
"""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path
import yaml

from lib import DOCS_DIR as DOCS, GPX_DIR as GPX, haversine_m as hav, trkpt_segs as trkpts

SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in",
        "waypoints", "summit")
SAMPLE_M = 6.0


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


def acceptances(slug: str):
    f = GPX / slug / "route_accepted.yml"
    if not f.exists():
        return []
    return (yaml.safe_load(f.read_text()) or {}).get("accepted", []) or []


def covered(p, dev, acc):
    """Is this over-bar sample inside a human-accepted problem area?"""
    for a in acc:
        c = a.get("center") or []
        if len(c) == 2 and hav(p[0], p[1], c[0], c[1]) <= a.get("radius_m", 150) \
                and dev <= a.get("max_ft", 1e18) + 10:
            return True
    return False


def route_segments(slug: str):
    """All recommended-route segments, NEVER concatenated across joins. A trip has one
    file per day (day_*.gpx); a single report's route can also have several <trk> segments
    (individual climbs with no connector). Sampling across a join would invent a phantom
    straight connector that reads as a huge false deviation — so each <trk> stays separate.
    For a trip, use the per-day files and IGNORE the combined <slug>_recommended.gpx (it's
    stale — day names vary: day_bennett, day1_bridge, …). Rule: everything except the
    combined; fall back to the combined only when it's the sole route file (single report)."""
    rfiles = sorted((GPX / slug).glob("*recommended*.gpx"))
    others = [f for f in rfiles if f.name != f"{slug}_recommended.gpx"]
    return [seg for rf in (others or rfiles) for seg in trkpts(rf)]


def worst_deviation_ft(slug: str, cell_m: float, max_ft: float, acc):
    """Return (worst_uncovered_ft, n_accepted_excursions). worst_uncovered is the worst
    sample whose deviation exceeds max_ft and is NOT inside an accepted area — that's the
    one that needs Kyle's eyes. Samples covered by an acceptance don't count against it.
    Measured WITHIN each route segment only (never across a join)."""
    segs = route_segments(slug)
    if sum(len(s) for s in segs) < 2:
        return None
    grid = SegGrid(source_tracks(slug), cell_m)
    worst_uncov = 0.0
    accepted_hits = 0
    for seg in segs:
        for i in range(len(seg) - 1):
            a, b = seg[i], seg[i + 1]
            n = max(1, int(hav(a[0], a[1], b[0], b[1]) / SAMPLE_M))
            for k in range(n + 1):
                t = k / n
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                dev = grid.dev_ft(p)
                if dev <= max_ft:
                    continue
                if covered(p, dev, acc):
                    accepted_hits += 1
                else:
                    worst_uncov = max(worst_uncov, dev)
    return worst_uncov, accepted_hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--max-ft", type=float, default=3.0)   # the achievable best (~0.2 ft) + GPS-noise margin
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--list-fail", action="store_true", help="print only the failing slugs")
    args = ap.parse_args()
    cell_m = 40.0   # search neighborhood ~120 m; enough to find the nearest real segment

    slugs = []
    for sub in ("peaks", "trips"):
        for p in sorted((DOCS / sub).glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index.") or p.stem.count("."):
                continue
            if args.slug and p.stem != args.slug:
                continue
            slugs.append(p.stem)

    bad = accepted_ok = checked = 0
    for slug in slugs:
        acc = acceptances(slug)
        res = worst_deviation_ft(slug, cell_m, args.max_ft, acc)
        if res is None:
            continue
        uncov, hits = res
        checked += 1
        if uncov > args.max_ft:
            if args.list_fail:
                print(slug)
            else:
                tag = ">120" if math.isinf(uncov) else f"{uncov:6.0f}"
                print(f"FAIL  {slug:28s} strays {tag} ft (un-accepted) — run inspect_route.py {slug}")
            bad += 1
        elif not args.list_fail:
            if hits:
                accepted_ok += 1
                print(f"ok*   {slug:28s} on-track except {len(acc)} accepted area(s)")
            else:
                print(f"ok    {slug:28s} ≤ {args.max_ft:.0f} ft off-track")
    if not args.list_fail:
        print(f"\n{checked} route(s) — {bad} need inspection, {accepted_ok} ok via acceptance, "
              f"vs {args.max_ft} ft bar.")
    if args.strict and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
