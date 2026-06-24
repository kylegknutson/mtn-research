#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
build_route.py — build a report's recommended route from its RECORDED RECIPE in peaks.yml,
so the close-following route is reproducible and can't silently regress on a rebuild.

peaks.yml `route_build:` records HOW the route is built:
    route_build: {method: from_track, track: "cuba-gultch-13076-13003-13179"}
    route_build: {method: graph}
    route_build: {method: legs}
    route_build: {method: multi_segment, tracks: [trio_14ers_1, lakefork_14ers_6]}
    route_build: {method: frozen}     # keep the committed *_recommended.gpx; don't rebuild
A trip (days: block) builds per-day via build_trip_day_routes.

This is the single entry point the pipeline should call instead of build_recommended_route
directly. Recipes are discovered/verified by infer_route_recipe.py and checked by
check_route_recipe.py.

    scripts/build_route.py cuba_gulch_trio
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
SCRIPTS = ROOT / "scripts"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--no-dem", action="store_true")
    args = ap.parse_args()

    yml = GPX / args.slug / "peaks.yml"
    if not yml.exists():
        sys.exit(f"ERROR: {yml} not found")
    cfg = yaml.safe_load(yml.read_text()) or {}

    if cfg.get("days"):
        cmd = [SCRIPTS / "build_trip_day_routes.py", args.slug]
        if args.no_dem:
            cmd.append("--no-dem")
        sys.exit(subprocess.run([str(c) for c in cmd]).returncode)

    r = cfg.get("route_build")
    if not r or not r.get("method"):
        sys.exit(f"ERROR: {args.slug} has no route_build recipe in peaks.yml. "
                 f"Run infer_route_recipe.py {args.slug} to find one, then record it.")
    m = r["method"]
    extra = ["--no-dem"] if args.no_dem else []

    if m == "frozen":
        rf = GPX / args.slug / f"{args.slug}_recommended.gpx"
        if not rf.exists():
            sys.exit(f"ERROR: {args.slug} recipe is 'frozen' but {rf.name} is missing — "
                     f"the committed route is the source and can't be regenerated.")
        print(f"{args.slug}: frozen recipe — keeping committed {rf.name} (not rebuilt)")
        return
    if m == "graph":
        cmd = [SCRIPTS / "build_recommended_route.py", args.slug, "--graph"] + extra
    elif m == "legs":
        cmd = [SCRIPTS / "build_recommended_route.py", args.slug, "--legs"] + extra
    elif m == "from_track":
        if not r.get("track"):
            sys.exit(f"ERROR: {args.slug} from_track recipe missing 'track'")
        cmd = [SCRIPTS / "build_recommended_route.py", args.slug, "--from-track", r["track"]] + extra
    elif m == "multi_segment":
        if not r.get("tracks"):
            sys.exit(f"ERROR: {args.slug} multi_segment recipe missing 'tracks'")
        cmd = [SCRIPTS / "build_multi_segment_route.py", args.slug, "--tracks", ",".join(r["tracks"])]
    else:
        sys.exit(f"ERROR: unknown route_build method {m!r} for {args.slug}")

    print(f"{args.slug}: building via recipe '{m}'"
          + (f" ({r.get('track') or ','.join(r.get('tracks', []))})" if r.get("track") or r.get("tracks") else ""))
    sys.exit(subprocess.run([str(c) for c in cmd]).returncode)


if __name__ == "__main__":
    main()
