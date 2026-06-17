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

Climber reports (<slug>.<climber>.md) share the base report's gpx dir, so the
route is looked up under the base slug. The only allowed exception is a genuinely
non-contiguous multi-day trip (peaks in separate areas that no party walks
between) — declare it in frontmatter with `no_single_route: true` plus a reason,
and it's exempted (and reported, never silent).

    scripts/check_route_exists.py
    scripts/check_route_exists.py gladstone_peak
    scripts/check_route_exists.py --strict
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
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

    missing = exempt = 0
    for p in reports:
        base = p.stem.split(".")[0]
        has = any((GPX / base).glob("*recommended*.gpx"))
        if has:
            continue
        meta = fm(p)
        if meta.get("no_single_route"):
            exempt += 1
            print(f"exempt {p.name:34s} (no_single_route: {str(meta.get('no_single_route'))[:40]})")
            continue
        missing += 1
        print(f"MISSING {p.name:34s} no gpx/{base}/*_recommended.gpx — build it "
              f"(scripts/build_recommended_route.py {base})")

    print(f"\n{len(reports)} report(s) — {missing} missing a recommended route, {exempt} exempt.")
    if args.strict and missing:
        sys.exit(1)


if __name__ == "__main__":
    main()
