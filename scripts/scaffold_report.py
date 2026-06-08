#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
scaffold_report.py — create gpx/<slug>/ and its peaks.yml from CLI args.

Replaces the ad-hoc `mkdir` + heredoc that used to scaffold a new report's
waypoint config (each of which prompts in raw Bash). One allowlisted call.

Usage:
    scripts/scaffold_report.py --slug star_peak_group \
        --objective-ids 301,365,420 \
        --landmark "Mt Tilton Trail TH (end of CO 742)|38.9872|-106.7573|10750|trailhead" \
        --no-nearby

    # landmark format (repeatable): "name|lat|lon|ele_ft|kind"   (kind: trailhead|landmark)

Idempotent-ish: refuses to overwrite an existing peaks.yml unless --force.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent


def parse_landmark(s: str) -> dict:
    parts = [p.strip() for p in s.split("|")]
    if len(parts) < 3:
        raise SystemExit(f"bad --landmark {s!r} (need name|lat|lon[|ele_ft|kind])")
    name, lat, lon = parts[0], float(parts[1]), float(parts[2])
    ele = int(parts[3]) if len(parts) > 3 and parts[3] else None
    kind = parts[4] if len(parts) > 4 and parts[4] else "trailhead"
    d = {"name": name, "lat": lat, "lon": lon, "kind": kind}
    if ele is not None:
        d["ele_ft"] = ele
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--objective-ids", required=True, help="comma-separated peak_db ids")
    ap.add_argument("--landmark", action="append", default=[], help="name|lat|lon|ele_ft|kind (repeatable)")
    ap.add_argument("--nearby", dest="nearby", action="store_true", default=False)
    ap.add_argument("--no-nearby", dest="nearby", action="store_false")
    ap.add_argument("--radius-mi", type=float, default=8.0)
    ap.add_argument("--exclude", default="", help="comma-separated peak_db ids to leave off nearby")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ids = [int(x) for x in args.objective_ids.split(",") if x.strip()]
    gdir = ROOT / "gpx" / args.slug
    gdir.mkdir(parents=True, exist_ok=True)
    yml = gdir / "peaks.yml"
    if yml.exists() and not args.force:
        sys.exit(f"{yml} already exists (use --force to overwrite)")

    cfg = {"objective_ids": ids}
    nearby = {"include": bool(args.nearby)}
    if args.nearby:
        nearby["radius_mi"] = args.radius_mi
        nearby["exclude"] = [int(x) for x in args.exclude.split(",") if x.strip()]
    cfg["nearby"] = nearby
    if args.landmark:
        cfg["landmarks"] = [parse_landmark(s) for s in args.landmark]

    # write with a leading comment
    header = f"# Waypoint config — {args.slug} (scaffold_report.py)\n"
    yml.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print(f"✓ {yml}")
    print(f"  objective_ids: {ids}  nearby: {args.nearby}  landmarks: {len(args.landmark)}")


if __name__ == "__main__":
    main()
