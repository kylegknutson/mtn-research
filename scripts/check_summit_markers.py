#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_summit_markers.py — HARD GATE: every objective summit marker must sit where the
recorded tracks actually converge (the summit people top out on), not off on a shoulder.

Kyle, 2026-07-23: PT 13,060 B's marker (from peak_db) sat ~68 ft off the true summit on a
lower shoulder; the recommended route didn't reach it and it read ~27 ft low on CalTopo.
Nothing caught it — the coord was trusted from peak_db, and check_route_summits' 600 ft
tolerance let the near-miss pass. This gate closes that: for each objective it finds the
DISTINCT-TRACK CONVERGENCE (the 25 m cell the most separate recorded parties pass through =
the summit everyone tags) and FAILs if the marker is more than --fail-ft from it.

Why distinct-track convergence (not density / not DEM): raw point-density is dominated by
one party milling on a flat shoulder; a coarse DEM (ned10m, 10 m) smooths a sharp summit
knob onto the shoulder — both mis-placed PT 13,060 B in earlier passes. Convergence of many
INDEPENDENT tracks is offline, deterministic, and robust — so it can be a pass/fail gate.

Fix a failure by moving the marker: add `summit_overrides: {<peak_db id>: {lat, lon, note}}`
to gpx/<slug>/peaks.yml (build_peak_gpx honors it), then re-run build + fix_summit_markers.
Verify the target with scripts/analyze_summit_location.py.

Only objectives with >= --min-tracks distinct tracks near the marker are checkable; sparser
ones are reported "unverified (n<min)" and pass (no evidence to fail on).

Usage:
  scripts/check_summit_markers.py                 # audit all
  scripts/check_summit_markers.py pt_13060_b      # one slug
  scripts/check_summit_markers.py --strict        # exit 1 on FAIL (gate mode)
"""
from __future__ import annotations
import argparse, math, sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("_recommended", "_landmarks", "_peaks_only", "_drive", "trail_osm")

RADIUS_MI = 0.15     # collect track points within this of the marker
CELL_M = 25.0        # convergence grid cell
MIN_TRACKS = 2       # need >=2 independent parties to judge (else unverified→pass)
FAIL_FT = 60.0       # marker must be within this of the convergence (else FAIL)


def hav_ft(a, b, c, d):
    R = 20903520.0  # ft
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def trkpts(path):
    try:
        return [(float(t.get("lat")), float(t.get("lon")))
                for t in ET.parse(path).getroot().iter(NS+"trkpt")]
    except (ET.ParseError, ValueError, TypeError):
        return []   # skip a malformed/partial GPX rather than crash the gate


def objectives(d, slug):
    pk = d / f"{slug}_peaks_only.gpx"
    if not pk.exists():
        return []
    out = []
    for w in ET.parse(pk).getroot().iter(NS+"wpt"):
        nm = w.find(NS+"name")
        out.append(((float(w.get("lat")), float(w.get("lon"))),
                    (nm.text if nm is not None else "").strip()))
    return out


def find_slugs():
    return sorted({p.stem.split(".")[0]
                   for base in (DOCS/"peaks", DOCS/"trips") for p in base.glob("*.md")
                   if p.stem != "index" and not p.stem.startswith("index.")})


def check_slug(slug, fail_ft, min_tracks, radius_mi):
    d = GPX / slug
    objs = objectives(d, slug)
    if not objs:
        return []
    tracks = []
    for f in sorted(d.glob("*.gpx")):
        if any(s in f.name for s in SKIP):
            continue
        pts = trkpts(f)
        if pts:
            tracks.append((f.name, pts))
    obj_pts = [o[0] for o in objs]   # all objective marker coords (neighbor attribution)
    rows = []
    for (mlat, mlon), name in objs:
        near = {}
        for fname, pts in tracks:
            npq = []
            for p in pts:
                if hav_ft(mlat, mlon, p[0], p[1]) > radius_mi * 5280:
                    continue
                # Attribute the point to its NEAREST objective — in a multi-peak
                # report, a point near summit B must not count toward summit A's
                # convergence (else A looks "off" toward B). (Kyle, 2026-07-23)
                nearest = min(obj_pts, key=lambda o: hav_ft(o[0], o[1], p[0], p[1]))
                if nearest != (mlat, mlon):
                    continue
                npq.append(p)
            if npq:
                near[fname] = npq
        n_tracks = len(near)
        if n_tracks < min_tracks:
            rows.append((name, "unverified", n_tracks, 0.0, None)); continue
        cell_tracks = defaultdict(set); cell_pts = defaultdict(list)
        for fname, ps in near.items():
            for p in ps:
                k = (round((p[0]-mlat)*364567/CELL_M),
                     round((p[1]-mlon)*364567*math.cos(math.radians(mlat))/CELL_M))
                cell_tracks[k].add(fname); cell_pts[k].append(p)
        best = max(cell_tracks, key=lambda k: (len(cell_tracks[k]), len(cell_pts[k])))
        ps = cell_pts[best]
        clat = sum(p[0] for p in ps)/len(ps); clon = sum(p[1] for p in ps)/len(ps)
        off = hav_ft(mlat, mlon, clat, clon)
        conv_tracks = len(cell_tracks[best])
        status = "FAIL" if (conv_tracks >= min_tracks and off > fail_ft) else "ok"
        rows.append((name, status, conv_tracks, off, (clat, clon)))
    return rows


def main():
    ap = argparse.ArgumentParser(description="Summit-marker-on-convergence gate")
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--fail-ft", type=float, default=FAIL_FT)
    ap.add_argument("--min-tracks", type=int, default=MIN_TRACKS)
    ap.add_argument("--radius-mi", type=float, default=RADIUS_MI)
    args = ap.parse_args()

    slugs = [args.slug] if args.slug else find_slugs()
    total_fail = 0; verified = 0
    for slug in slugs:
        rows = check_slug(slug, args.fail_ft, args.min_tracks, args.radius_mi)
        for name, status, ntr, off, conv in rows:
            if status == "FAIL":
                total_fail += 1
                print(f"FAIL  {slug:26s} {name:22s} marker {off:.0f} ft from {ntr}-track "
                      f"convergence {conv[0]:.5f},{conv[1]:.5f} — move via summit_overrides")
            elif status == "unverified":
                if args.slug:
                    print(f"  --   {slug:26s} {name:22s} unverified ({ntr} track(s) < {args.min_tracks})")
            else:
                verified += 1
                if args.slug:
                    print(f"ok    {slug:26s} {name:22s} {off:.0f} ft from {ntr}-track convergence")

    print(f"\n{verified} objective(s) verified — {total_fail} FAIL (marker off its "
          f"track-convergence summit by >{args.fail_ft:.0f} ft).")
    if args.strict and total_fail:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
