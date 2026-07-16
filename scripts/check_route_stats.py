#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
check_route_stats.py — guard against headline mileage/gain that the GPX disagrees with.

The lesson (Kyle, 2026-06-10): route distance/gain in a report headline must come
from MEASURED GPX (14ers / LoJ / peakbagger tracks), never from a climb13ers prose
estimate. climb13ers numbers are an author's drawn approximation ("Not intended for
use as a GPX track") — fine for class/conditions, wrong as the headline stat.

For every report with recorded tracks in gpx/<slug>/, this compares the frontmatter
`gain:` headline against the recorded-track distance range and flags:

  * HEADLINE-SOURCE : the gain string cites "climb13ers" (an estimate as headline).
  * SHORTER-THAN-REAL : a mileage in the headline is well below the shortest recorded
                        track — i.e. an optimistic estimate no party actually walked.

It's advisory (lists findings); pass --strict to exit non-zero when any are found,
so it can gate a finalize step.

Usage:
  scripts/check_route_stats.py            # audit all reports
  scripts/check_route_stats.py baldy_lejos_trio
  scripts/check_route_stats.py --strict
"""
from __future__ import annotations
import argparse, math, re, sys, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX_ROOT = ROOT / "gpx"
sys.path.insert(0, str(ROOT / "scripts"))
from gpx_root import glob_gpx   # worktree-aware gpx resolution
PEAKS_DIR = ROOT / "docs" / "peaks"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in", "waypoints", "summit")
SHORTER_TOL = 0.80   # headline mileage below shortest_recorded * this → flag


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


# Fast path: scan trackpoint coords with a regex instead of building a full DOM.
# After the 3-source grind each report dir holds a dozen+ large source tracks, and
# ET.parse of all of them dominated run_gates (~4 s/report). A text scan is ~10x
# faster; fall back to a real parse only if the standard "lat=…" lon=…"" order misses.
_TRKPT = re.compile(r'<trkpt\s+lat="([-\d.]+)"\s+lon="([-\d.]+)"')


def track_miles(path: Path):
    try:
        text = path.read_text()
    except OSError:
        return None
    pts = [(float(a), float(b)) for a, b in _TRKPT.findall(text)]
    if len(pts) < 2:
        try:                       # non-standard attribute order → real parse
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return None
        pts = [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]
        if len(pts) < 2:
            return None
    return sum(hav(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
               for i in range(len(pts) - 1)) / 1609.34


def frontmatter_gain(report: Path):
    if not report.exists():
        return ""
    txt = report.read_text().splitlines()
    if not txt or txt[0].strip() != "---":
        return ""
    for line in txt[1:]:
        if line.strip() == "---":
            break
        if line.startswith("gain:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return ""


def miles_in(s: str):
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*mi", s)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="check one slug (default: all)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any findings")
    args = ap.parse_args()

    dirs = [GPX_ROOT / args.slug] if args.slug else sorted(d for d in GPX_ROOT.iterdir() if d.is_dir())
    findings = 0
    for d in dirs:
        slug = d.name
        files = [f for f in glob_gpx(ROOT, slug, "*.gpx") if not any(s in f.name.lower() for s in SKIP)]
        miles = [m for f in files if (m := track_miles(f))]
        if not miles:
            continue
        lo, hi = min(miles), max(miles)
        gain = frontmatter_gain(PEAKS_DIR / f"{slug}.md")
        # The headline mileage legitimately comes from the DEM-measured composed
        # *_recommended.gpx, which IS the route. When it's a standalone climb
        # trimmed from multi-peak recorded tracks (e.g. Campbell Creek, where every
        # recorded track also bags Handies/13801), the recommended route is rightly
        # SHORTER than any recorded track — that's not an optimistic estimate, it's
        # measured. So exempt any headline mileage that matches the recommended
        # route's own measured length (within 15%) from SHORTER-THAN-REAL.
        rec = next((track_miles(f) for f in glob_gpx(ROOT, slug, "*recommended*.gpx")), None)
        flags = []
        if re.search(r"climb\s*13ers", gain, re.I):
            flags.append("HEADLINE-SOURCE (climb13ers estimate in headline)")
        for m in miles_in(gain):
            if rec and abs(m - rec) <= 0.15 * rec:
                continue  # headline == measured recommended route → ground truth
            if m < lo * SHORTER_TOL:
                flags.append(f"SHORTER-THAN-REAL ({m:.1f} mi headline vs {lo:.1f} mi shortest recorded)")
                break
        status = "  ".join(flags) if flags else "ok"
        if flags:
            findings += 1
        marker = "⚠ " if flags else "  "
        print(f"{marker}{slug:26s} recorded {lo:4.1f}-{hi:4.1f} mi (n={len(miles)})  gain: {gain[:48]:48s} {status}")

    print(f"\n{findings} report(s) flagged.")
    if args.strict and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
