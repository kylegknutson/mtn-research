#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
audit_recommended_routes.py — flag reports whose recommended route is much longer
than a single recorded track that already tours every objective.

The Cuba Gulch failure (Kyle, 2026-06-16): the default graph router stitched a
22 mi path through the pooled tracks when one real party track toured all three
peaks in 15.8 mi. The router minimizes distance through pooled points but doesn't
prefer a clean single-track tour, so it can over-route — inflating the headline
distance AND (via the extra drop/re-climb) the DEM gain.

For each report this compares the recommended route's distance against the
SHORTEST single source track that summits all objectives (within --tol-ft):

  FLAG  recommended > best_single * --ratio  → router likely over-routed.
        Fix: scripts/build_recommended_route.py <slug> --from-track <substring>
        (use scripts/analyze_tracks.py <slug> to see the candidates).

Reports where no single track tours all objectives (genuinely composed routes)
are reported as 'composed' and never flagged.

Usage:
    scripts/audit_recommended_routes.py
    scripts/audit_recommended_routes.py --ratio 1.25
"""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path
import xml.etree.ElementTree as ET
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX_ROOT = ROOT / "gpx"
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
NS = "{http://www.topografix.com/GPX/1/1}"
HELPER = ("recommended", "peaks_only", "landmark", "_drive", "drive_in", "summit", "waypoint")


def hav_mi(a, b):
    R = 3958.8
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))


def pts(path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]


def dist_mi(p):
    return sum(hav_mi(p[i], p[i+1]) for i in range(len(p)-1)) if len(p) > 1 else 0.0


def load_peakdb():
    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    return {p["id"]: p for p in peaks()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", type=float, default=1.25, help="flag if recommended > best-single * ratio")
    ap.add_argument("--tol-ft", type=float, default=250)
    args = ap.parse_args()
    tol_mi = args.tol_ft / 5280.0
    P = load_peakdb()

    flags = 0
    print(f"{'slug':28} {'rec_mi':>7} {'best1':>6}  note")
    for d in sorted(p for p in GPX_ROOT.iterdir() if p.is_dir()):
        slug = d.name
        rec = next(d.glob("*recommended*.gpx"), None)
        ymlf = d / "peaks.yml"
        if not rec or not ymlf.exists():
            continue
        ids = (yaml.safe_load(ymlf.read_text()) or {}).get("objective_ids") or []
        objs = [(P[i]["lat"], P[i]["lon"]) for i in ids if i in P]
        if not objs:
            continue
        rec_mi = dist_mi(pts(rec))
        # shortest single source track that summits ALL objectives
        best = None
        for f in d.glob("*.gpx"):
            if any(h in f.name.lower() for h in HELPER):
                continue
            tp = pts(f)
            if len(tp) < 2:
                continue
            if all(min(hav_mi(p, c) for p in tp) <= tol_mi for c in objs):
                td = dist_mi(tp)
                if best is None or td < best[0]:
                    best = (td, f.name)
        if best is None:
            print(f"{slug:28} {rec_mi:7.1f}     —  composed (no single track tours all {len(objs)})")
            continue
        ratio = rec_mi / best[0] if best[0] else 1.0
        tag = ""
        if ratio >= args.ratio:
            tag = f"  <-- FLAG: single track does all {len(objs)} in {best[0]:.1f} mi ({best[1]})"
            flags += 1
        print(f"{slug:28} {rec_mi:7.1f} {best[0]:6.1f}{tag}")
    print(f"\n{flags} report(s) flagged (recommended >= {args.ratio}x a clean single-track tour).")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
