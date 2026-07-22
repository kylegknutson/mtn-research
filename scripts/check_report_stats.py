#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""Catch stale stats: verify a report's frontmatter dist_mi / gain_ft / days_detail
matches the actual recommended-route files on disk.

Kyle, 2026-07-22: caught two rounds of this on Rito Alto — the frontmatter kept a
stale number after a route rebuild (e.g. 25.65 mi vs actual 27.89). Fleet-wide the
same drift can happen any time routes change without someone remembering to update
the frontmatter. This gate prevents that.

Rules:
1. **Frontmatter `dist_mi` = sum(days_detail[*].dist_mi)** — arithmetic consistency
   inside the frontmatter itself. Prevents a discrepancy between the trip total
   the reader sees at the top and the per-day breakdown in the quickstats.
2. **Frontmatter `dist_mi` matches the sum of all `*_recommended.gpx` haversine
   distances** in the slug's gpx dir (day_*_recommended + leg_*_recommended),
   within ±5% (or ±0.3 mi absolute for very short trips). Prevents stale mileage
   after a route rebuild.
3. **Frontmatter `gain_ft` = sum(days_detail[*].gain_ft)** — same check for gain.
4. Similarly ±10% (or ±200 ft absolute) tolerance for gain vs summed route gain,
   IF the routes carry <ele> data (many don't — build_recommended_route DEM-samples
   at build time and doesn't always persist). When elevations are missing, gain
   route-check is skipped (arithmetic check in #3 still runs).

Runs on every report that has `days_detail` in frontmatter (multi-day trips + any
day-detail single reports). Skip reports without days_detail.

Usage:
  scripts/check_report_stats.py                    # check all
  scripts/check_report_stats.py rito_alto_group    # one slug
  scripts/check_report_stats.py --strict           # exit nonzero on failure
"""
import argparse
import math
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"

# Tolerances — fail if OUTSIDE these bands.
DIST_TOL_PCT = 5.0         # arithmetic + route-vs-frontmatter tolerance
DIST_TOL_ABS_MI = 0.3      # min absolute tolerance for very short trips
GAIN_TOL_PCT = 10.0
GAIN_TOL_ABS_FT = 200

# Reports with known pre-existing drift that predates this gate. Fixing them
# requires investigating the actual route (may be a bad committed route file, not
# just a frontmatter typo). Listed here so this gate can ship + catch NEW drift
# on OTHER reports; each entry should be resolved and REMOVED, not kept forever.
# Kyle, 2026-07-22: gate landed with these open — track in [[project-report-stat-drift]].
KNOWN_DRIFT = {
    "star_peak_group",   # day_italian_recommended.gpx = 26.67 mi (vs ~6 mi expected)
                         # — route file itself needs investigation.
}


def hav_mi(a, b):
    R = 3958.8
    la1, lo1 = math.radians(a[0]), math.radians(a[1])
    la2, lo2 = math.radians(b[0]), math.radians(b[1])
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def measure_gpx_dist_mi(path):
    """Sum consecutive-point haversine distance across all trkseg."""
    total = 0.0
    pts_re = re.compile(r'<trkpt\s+lat="([-\d.]+)"\s+lon="([-\d.]+)"')
    seg_re = re.compile(r"<trkseg>(.*?)</trkseg>", re.DOTALL)
    raw = path.read_text()
    for seg in seg_re.findall(raw):
        pts = [(float(a), float(b)) for a, b in pts_re.findall(seg)]
        for i in range(1, len(pts)):
            total += hav_mi(pts[i - 1], pts[i])
    return total


def measure_gpx_gain_ft(path):
    """Cumulative ascent from <ele> tags across all trkseg. Returns None if no <ele>."""
    ele_re = re.compile(
        r'<trkpt[^>]*>[^<]*<ele>([-\d.]+)</ele>'
    )
    raw = path.read_text()
    eles = [float(x) for x in ele_re.findall(raw)]
    if len(eles) < 2:
        return None
    total_m = sum(max(0.0, eles[i] - eles[i - 1]) for i in range(1, len(eles)))
    return total_m * 3.28084


def parse_frontmatter(md_path):
    txt = md_path.read_text()
    m = re.match(r"^---\n(.*?)\n---", txt, re.DOTALL)
    if not m:
        return None
    return yaml.safe_load(m.group(1))


def find_report_md(slug):
    for base in (DOCS / "peaks", DOCS / "trips"):
        p = base / f"{slug}.md"
        if p.exists():
            return p
    return None


def check_slug(slug):
    """Return list of failures (empty if OK) plus a summary string."""
    md = find_report_md(slug)
    if not md:
        return [], f"{slug}: no report md — skip"
    fm = parse_frontmatter(md) or {}
    if not fm.get("days_detail"):
        return [], f"{slug}: no days_detail — skip"

    # 1) days_detail arithmetic vs frontmatter totals
    fails = []
    days = fm["days_detail"]
    days_dist_sum = sum(float(d.get("dist_mi", 0)) for d in days)
    days_gain_sum = sum(float(d.get("gain_ft", 0)) for d in days)
    fm_dist = float(fm.get("dist_mi", 0))
    fm_gain = float(fm.get("gain_ft", 0))

    def within(x, y, pct, abs_min):
        return abs(x - y) <= max(y * pct / 100.0, abs_min)

    if not within(days_dist_sum, fm_dist, DIST_TOL_PCT, DIST_TOL_ABS_MI):
        fails.append(
            f"frontmatter dist_mi={fm_dist:.2f} but sum(days_detail.dist_mi)={days_dist_sum:.2f} "
            f"(delta {abs(days_dist_sum - fm_dist):.2f} mi)"
        )
    if not within(days_gain_sum, fm_gain, GAIN_TOL_PCT, GAIN_TOL_ABS_FT):
        fails.append(
            f"frontmatter gain_ft={fm_gain:.0f} but sum(days_detail.gain_ft)={days_gain_sum:.0f} "
            f"(delta {abs(days_gain_sum - fm_gain):.0f} ft)"
        )

    # 2) route files vs frontmatter dist_mi — DISTANCE only. Gain from routes is
    # unreliable because build_recommended_route DEM-samples at build time but
    # doesn't always persist <ele> to the GPX; a gain-from-routes check gets a
    # ~30% low reading and false-fires. The arithmetic check in #1 above still
    # catches days_detail vs frontmatter gain drift.
    slug_dir = GPX / slug
    if slug_dir.exists():
        route_dist = 0.0
        for gpx in sorted(slug_dir.glob("*_recommended.gpx")):
            route_dist += measure_gpx_dist_mi(gpx)
        if route_dist > 0 and not within(route_dist, fm_dist, DIST_TOL_PCT, DIST_TOL_ABS_MI):
            fails.append(
                f"frontmatter dist_mi={fm_dist:.2f} but sum(actual *_recommended.gpx)={route_dist:.2f} "
                f"(delta {abs(route_dist - fm_dist):.2f} mi — route files updated but frontmatter stale?)"
            )

    if fails:
        return fails, ""
    return [], f"ok    {slug:28s}  dist={fm_dist:.2f} mi  gain={fm_gain:.0f} ft"


def main():
    ap = argparse.ArgumentParser(description="Report-stat freshness gate")
    ap.add_argument("slug", nargs="?", help="check one slug (default: all)")
    ap.add_argument("--strict", action="store_true", help="exit nonzero on any FAIL")
    args = ap.parse_args()

    if args.slug:
        slugs = [args.slug]
    else:
        slugs = sorted(
            {p.stem.split(".")[0] for base in (DOCS / "peaks", DOCS / "trips") for p in base.glob("*.md")
             if p.stem != "index" and not p.stem.startswith("index.")}
        )

    total_fail = 0
    known_still_drifting = []
    for slug in slugs:
        fails, summary = check_slug(slug)
        if fails:
            if slug in KNOWN_DRIFT:
                known_still_drifting.append(slug)
                print(f"note  {slug} — known drift (bypassed until fixed):")
                for f in fails:
                    print(f"      {f}")
            else:
                total_fail += 1
                print(f"FAIL  {slug}")
                for f in fails:
                    print(f"      {f}")
        elif summary and args.slug:  # be verbose only in single-slug mode
            print(summary)
    # A KNOWN_DRIFT slug that has been FIXED should be removed from the set.
    for slug in KNOWN_DRIFT - set(known_still_drifting):
        print(f"note  {slug} listed as KNOWN_DRIFT but now passes — remove from KNOWN_DRIFT set")

    if args.strict and total_fail:
        print(f"\n{total_fail} report(s) with stat drift.")
        return 1
    print(f"\n{len(slugs)} report(s) checked — {total_fail} FAIL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
