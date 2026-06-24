#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_route_recipe.py — every report's recommended route must be REPRODUCIBLE from a recorded
recipe in peaks.yml (route_build:), and that recipe must actually rebuild the committed route.
Routes are gitignored; without this gate a recipe could drift from the route it claims to make,
or a report could have no recipe at all and silently regress on the next rebuild.

For each report:
  - graph / legs / from_track : rebuild from the recipe (to /tmp, --no-dem) and require the
    committed route to match (distance within 1% AND never stray > VERIFY_FT from the rebuild).
  - multi_segment / frozen    : require the committed *_recommended.gpx to exist & be non-empty
    (reproduction trusted: multi_segment lists exact tracks, frozen IS the source).
  - trip (days: block)        : require every day_*_recommended.gpx to exist & be non-empty.
  - no recipe                 : FAIL.

    scripts/check_route_recipe.py                 # all reports
    scripts/check_route_recipe.py cuba_gulch_trio --strict
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "scripts"))
import infer_route_recipe as ir   # pts_of, route_len_mi, build, reproduces


def report_slugs(only):
    out = []
    for sub in ("peaks", "trips"):
        for p in sorted((DOCS / sub).glob("*.md")):
            if p.stem == "index" or p.stem.count("."):
                continue
            if only and p.stem != only:
                continue
            if (GPX / p.stem / "peaks.yml").exists():
                out.append(p.stem)
    return out


def committed(slug):
    rf = GPX / slug / f"{slug}_recommended.gpx"
    return ir.pts_of(rf) if rf.exists() else []


def check(slug):
    cfg = yaml.safe_load((GPX / slug / "peaks.yml").read_text()) or {}
    if cfg.get("days"):
        days = sorted((GPX / slug).glob("day_*recommended*.gpx"))
        bad = [d.name for d in days if len(ir.pts_of(d)) < 2]
        if not days:
            return False, "trip: no day_*_recommended.gpx files"
        if bad:
            return False, f"trip: empty day route(s) {bad}"
        return True, f"trip: {len(days)} day route(s) present"

    r = cfg.get("route_build")
    if not r or not r.get("method"):
        return False, "no route_build recipe (run infer_route_recipe.py)"
    m = r["method"]

    if m in ("multi_segment", "frozen"):
        if len(committed(slug)) < 2:
            return False, f"{m}: committed route missing/empty"
        return True, f"{m}: committed route present"

    ref = committed(slug)
    if len(ref) < 2:
        return False, "committed route missing/empty"
    ref_mi = ir.route_len_mi(ref)
    flags = {"graph": ["--graph"], "legs": ["--legs"],
             "from_track": ["--from-track", r.get("track", "")]}.get(m)
    if flags is None:
        return False, f"unknown method {m!r}"
    cand = ir.build(slug, flags)
    if ir.reproduces(ref, cand, ref_mi):
        return True, f"{m} reproduces ({ref_mi:.1f} mi)"
    cm = ir.route_len_mi(cand) if cand else 0
    return False, f"{m} recipe does NOT reproduce committed route (recipe {cm:.1f} mi vs {ref_mi:.1f} mi)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    bad = 0
    for slug in report_slugs(args.slug):
        ok, msg = check(slug)
        print(f"{'ok  ' if ok else 'FAIL'}  {slug:30s} {msg}")
        if not ok:
            bad += 1
    print(f"\n{bad} report(s) without a verified route recipe.")
    if args.strict and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
