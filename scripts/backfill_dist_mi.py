#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
backfill_dist_mi.py — ensure every SINGLE-DAY report's frontmatter has `dist_mi`,
measured from its committed recommended-route GPX (CLAUDE.md: headline distance
comes from measured GPX). Without dist_mi, gen_quickstats omits the distance and
the "At a glance" box silently drops it (caught on sunshine_13094, 2026-06-25).

Multi-day TRIPS (frontmatter days>1) legitimately have no single distance — one
route per day — so they're skipped.

    scripts/backfill_dist_mi.py            # report missing/stale dist_mi (dry run)
    scripts/backfill_dist_mi.py --write    # write measured dist_mi into frontmatter
    scripts/backfill_dist_mi.py --check     # exit 1 if any single-day report lacks dist_mi
"""
from __future__ import annotations
import argparse, math, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PEAKS = ROOT / "docs" / "peaks"
TRIPS = ROOT / "docs" / "trips"
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def base_slug(path: Path) -> str:
    return path.name[:-3].split(".")[0]


def fm_get(text: str, key: str):
    m = re.search(rf"^{key}:\s*(.+)$", text.split("\n---\n", 1)[0], re.MULTILINE)
    return m.group(1).strip() if m else None


def route_miles(slug: str):
    """Total geodesic length (mi) across all <trkseg> of every recommended route gpx."""
    files = sorted((GPX / slug).glob("*recommended*.gpx"))
    if not files:
        return None
    total_m = 0.0
    for f in files:
        for seg in ET.parse(f).getroot().iter(NS + "trkseg"):
            pts = [(float(t.get("lat")), float(t.get("lon"))) for t in seg.iter(NS + "trkpt")]
            total_m += sum(hav(*pts[i], *pts[i+1]) for i in range(len(pts) - 1))
    return total_m / 1609.344 if total_m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    missing, wrote = [], []
    for path in sorted(PEAKS.glob("*.md")) + sorted(TRIPS.glob("*.md")):
        if path.name.endswith(".skeleton.md"):
            continue
        text = path.read_text()
        if "\n---\n" not in text:
            continue
        days = fm_get(text, "days")
        if days and days.strip().isdigit() and int(days) > 1:
            continue  # multi-day trip → no single distance
        if fm_get(text, "dist_mi"):
            continue  # already has it
        mi = route_miles(base_slug(path))
        if mi is None:
            missing.append((path.name, "no recommended route gpx"))
            continue
        missing.append((path.name, f"{mi:.1f} mi"))
        if args.write:
            head, body = text.split("\n---\n", 1)
            if re.search(r"^gain_ft:", head, re.MULTILINE):
                head = re.sub(r"^(gain_ft:)", f"dist_mi: {mi:.1f}\n\\1", head, count=1, flags=re.MULTILINE)
            else:
                head = head.rstrip() + f"\ndist_mi: {mi:.1f}"
            path.write_text(head + "\n---\n" + body)
            wrote.append(f"{path.name}: dist_mi {mi:.1f}")

    if args.check:
        real = [m for m in missing if not m[1].endswith("mi") or True]
        gap = [m for m in missing]
        if gap:
            print("single-day reports missing dist_mi:")
            for n, why in gap:
                print(f"  {n}: {why}")
            sys.exit(1)
        print("every single-day report has dist_mi ✓")
        return

    if args.write:
        print(f"wrote dist_mi to {len(wrote)} report(s):")
        for w in wrote:
            print(f"  {w}")
    else:
        print(f"{len(missing)} single-day report(s) missing dist_mi:")
        for n, why in missing:
            print(f"  {n}: {why}")
        print("\n(dry run — re-run with --write)")


if __name__ == "__main__":
    main()
