#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_route_summits.py — verify the composed *_recommended.gpx actually reaches
every objective summit.

The teleport gate (check_route_geometry) only checks for within-route gaps; it
does NOT verify the route touches the peaks it claims to climb. A route built
from the wrong recorded track (or a router that stops short) can pass geometry
yet never reach the summit — exactly the Gladstone scare (2026-06-16), where the
PNG made it look like the magenta route never reached the marker. This closes
that gap: for each objective summit (from gpx/<slug>/<slug>_peaks_only.gpx), it
measures the recommended route's closest approach and FAILs if it's farther than
--tol-ft (default 600 ft, a generous summit-plateau tolerance).

Usage:
  scripts/check_route_summits.py gladstone_peak
  scripts/check_route_summits.py                 # all slugs with a recommended route
  scripts/check_route_summits.py --strict        # exit 1 on any FAIL
"""
from __future__ import annotations
import re
import yaml
import argparse, math, sys, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX_ROOT = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"


def hav_ft(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x)) * 3.28084


def _objective_count(d: Path) -> int | None:
    """How many of peaks_only.gpx's waypoints are OBJECTIVES. peaks_only also
    carries nearby-context peaks when peaks.yml has `nearby: include: true`, and
    those labels are inconsistent (some have a "(5.3mi)" marker, some don't —
    homestake's nearby Savage Pk has none). build_peak_gpx always writes the
    objectives FIRST, so the authoritative count is len(objective_ids) from
    peaks.yml (or the report's frontmatter peak_ids); the rest are context."""
    yml = d / "peaks.yml"
    if yml.exists():
        try:
            cfg = yaml.safe_load(yml.read_text()) or {}
            n = len(cfg.get("objective_ids") or []) + len(cfg.get("extra_summits") or [])
            if n:
                return n
        except Exception:
            pass
    for sub in ("peaks", "trips"):
        for p in (ROOT / "docs" / sub).glob(f"{d.name}*.md"):
            m = re.search(r"^peak_ids:\s*\[([^\]]*)\]", p.read_text(), re.M)
            if m:
                return len([x for x in m.group(1).split(",") if x.strip()])
    return None


def summits(d: Path):
    """OBJECTIVE summits only (the route must reach these; nearby-context peaks
    in peaks_only.gpx are not objectives)."""
    f = d / f"{d.name}_peaks_only.gpx"
    if not f.exists():
        return []
    root = ET.parse(f).getroot()
    out = []
    for w in root.iter(NS + "wpt"):
        nm = w.find(NS + "name")
        name = nm.text if nm is not None else "?"
        out.append((name, float(w.get("lat")), float(w.get("lon"))))
    n = _objective_count(d)
    return out[:n] if n else out


def route_pts(d: Path):
    f = next(iter(d.glob("*recommended*.gpx")), None)
    if not f:
        return None
    root = ET.parse(f).getroot()
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--tol-ft", type=float, default=600.0)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    dirs = [GPX_ROOT / args.slug] if args.slug else sorted(d for d in GPX_ROOT.iterdir() if d.is_dir())
    fails = 0
    checked = 0
    for d in dirs:
        pts = route_pts(d)
        sm = summits(d)
        if pts is None or not sm:
            continue
        checked += 1
        for name, lat, lon in sm:
            near = min(hav_ft(lat, lon, p[0], p[1]) for p in pts)
            ok = near <= args.tol_ft
            if not ok:
                fails += 1
            print(f"{'ok  ' if ok else 'FAIL'}  {d.name:26s} {name[:28]:28s} closest {near:6.0f} ft")

    print(f"\n{checked} route(s) checked — {fails} summit(s) not reached.")
    if args.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
