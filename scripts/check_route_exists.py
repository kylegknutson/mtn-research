#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_route_exists.py — every report must have a composed recommended route.

Kyle (2026-06-17): "all reports should always have a recommended route." A report
without a `gpx/<slug>/*_recommended.gpx` shows no magenta route on its PNG, its
CalTopo map, or the home-page map. This gate makes that a hard requirement.

Kyle (2026-06-21): one route per DAY — a single-day report needs ≥1 recommended
route; a multi-day Trip (frontmatter `days: N`, N>1) needs ≥N route files (one
composed line per day; the day clusters can be miles apart with no track between,
so there is no single line). NO exemption — the old `no_single_route` escape hatch
is gone (it left South San Juans with no route at all). Build per-day routes with
scripts/build_trip_day_routes.py (reads peaks.yml `days:`).

Climber reports (<slug>.<climber>.md) share the base report's gpx dir, so routes
are looked up under the base slug.

    scripts/check_route_exists.py
    scripts/check_route_exists.py gladstone_peak
    scripts/check_route_exists.py --strict
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from gpx_root import glob_gpx   # worktree-aware gpx resolution
GPX = ROOT / "gpx"


def fm(p: Path) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    reports = []
    for sub in ("peaks", "trips"):
        for p in sorted((ROOT / "docs" / sub).glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index."):
                continue
            if args.slug and p.stem != args.slug and p.stem.split(".")[0] != args.slug:
                continue
            reports.append(p)

    missing = short = 0
    for p in reports:
        base = p.stem.split(".")[0]
        routes = glob_gpx(ROOT, base, "*recommended*.gpx")
        meta = fm(p)
        try:
            days = int(meta.get("days") or 1)
        except (TypeError, ValueError):
            days = 1
        need = days if days > 1 else 1   # multi-day Trip → one route PER DAY
        if not routes:
            missing += 1
            tool = "build_trip_day_routes.py" if need > 1 else "build_recommended_route.py"
            print(f"MISSING {p.name:34s} no gpx/{base}/*_recommended.gpx — build it "
                  f"(scripts/{tool} {base})")
        elif len(routes) < need:
            short += 1
            print(f"SHORT   {p.name:34s} {len(routes)} route(s) but days: {days} — a multi-day "
                  f"trip needs one route PER DAY (scripts/build_trip_day_routes.py {base})")

    print(f"\n{len(reports)} report(s) — {missing} missing a route, {short} short of one-route-per-day.")
    if args.strict and (missing or short):
        sys.exit(1)


if __name__ == "__main__":
    main()
