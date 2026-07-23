#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
analyze_summit_location.py — is the objective's summit MARKER in the right place?

peak_db / 14ers summit coordinates can be off (Kyle, 2026-07-23: PT 13,060 B's marker
sat below where every recorded track tops out). Recorded tracks + the DEM are better
evidence than a webpage coordinate. For each objective in a slug, this reports three
candidate summit locations and how far apart they are:

  1. MARKER   — the current peaks_only.gpx coordinate (from peak_db).
  2. TRACKS   — where recorded tracks turn around / linger (their per-track farthest-
                from-start point, i.e. where climbers stood; averaged over tracks that
                reach the area). This is "where the tracks end and linger."
  3. DEM-HIGH — the highest DEM cell in the local area (the topographic summit per the
                map contours), found by sampling a grid around the marker + track cluster.

GPS <ele> is unreliable, so TRACKS uses geometry (turnaround), not recorded elevation;
the true HIGH point comes from the DEM, not GPS. If MARKER is far from both TRACKS and
DEM-HIGH, the marker is likely wrong — move it (usually to DEM-HIGH, the actual summit;
TRACKS confirms people go there). When it's ambiguous, it's a judgment call for Kyle.

Usage:
  scripts/analyze_summit_location.py pt_13060_b
  scripts/analyze_summit_location.py pt_13060_b --radius-mi 0.4 --grid-m 25 --box-m 500
  scripts/analyze_summit_location.py pt_13060_b --no-dem   # tracks-only, no network
"""
from __future__ import annotations
import argparse, json, math, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
OPENTOPODATA = "https://api.opentopodata.org/v1"
SKIP = ("_recommended", "_landmarks", "_peaks_only", "_drive", "trail_osm")


def hav_mi(a, b, c, d):
    R = 3958.8
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def trkpts(path):
    return [(float(t.get("lat")), float(t.get("lon")))
            for t in ET.parse(path).getroot().iter(NS + "trkpt")]


def objectives(slug):
    pk = GPX / slug / f"{slug}_peaks_only.gpx"
    out = []
    for w in ET.parse(pk).getroot().iter(NS + "wpt"):
        nm = w.find(NS + "name")
        out.append(((float(w.get("lat")), float(w.get("lon"))),
                    (nm.text if nm is not None else "").strip()))
    return out


def sample_dem(latlons, dataset="ned10m"):
    out = []
    for i in range(0, len(latlons), 100):
        batch = latlons[i:i + 100]
        locs = "|".join(f"{a:.6f},{o:.6f}" for a, o in batch)
        url = f"{OPENTOPODATA}/{dataset}?locations=" + urllib.parse.quote(locs, safe="|,")
        data = None
        for _ in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.load(resp)
                break
            except Exception:
                time.sleep(2)
        if data is None or "results" not in data:
            raise RuntimeError(f"DEM request failed ({dataset})")
        out += [(r["location"]["lat"], r["location"]["lng"], r.get("elevation")) for r in data["results"]]
        if i + 100 < len(latlons):
            time.sleep(1.1)
    return out


def fmt(latlon):
    return f"{latlon[0]:.5f},{latlon[1]:.5f}"


def main():
    ap = argparse.ArgumentParser(description="Check a summit marker vs tracks + DEM")
    ap.add_argument("slug")
    ap.add_argument("--radius-mi", type=float, default=0.25,
                    help="collect track points within this radius of the summit (default 0.25)")
    ap.add_argument("--box-m", type=float, default=250.0,
                    help="DEM search box half-width around the marker (default 250 m — keep "
                         "tight so a higher NEIGHBOR peak doesn't win the max; widen only if "
                         "the true summit is genuinely farther off)")
    ap.add_argument("--grid-m", type=float, default=25.0, help="DEM grid spacing (default 25 m)")
    ap.add_argument("--no-dem", action="store_true", help="skip the DEM high-point search")
    args = ap.parse_args()

    d = GPX / args.slug
    if not (d / f"{args.slug}_peaks_only.gpx").exists():
        sys.exit(f"no {args.slug}_peaks_only.gpx — run build_peak_gpx.py first")

    tracks = []
    for f in sorted(d.glob("*.gpx")):
        if any(s in f.name for s in SKIP):
            continue
        pts = trkpts(f)
        if pts:
            tracks.append((f.name, pts))

    for (mlat, mlon), name in objectives(args.slug):
        print(f"\n=== {name}  (marker {fmt((mlat, mlon))}) ===")
        print(f"  {len(tracks)} recorded track(s); radius {args.radius_mi} mi")

        near_all = []
        for fname, pts in tracks:
            near_all += [p for p in pts if hav_mi(mlat, mlon, p[0], p[1]) <= args.radius_mi]
        if not near_all:
            print("  no track points within radius — widen --radius-mi")
            continue

        if args.no_dem:
            print("  (--no-dem: skipping DEM summit + track-visit analysis)")
            continue

        # (1) LOCAL DEM SUMMIT: grid in a TIGHT box around the marker (small enough not to
        # reach a higher neighbor peak — Clark A is 0.5 mi off), max cell = the summit.
        clat, clon = mlat, mlon
        dlat = args.box_m / 111320.0
        dlon = args.box_m / (111320.0 * math.cos(math.radians(clat)))
        step_lat = args.grid_m / 111320.0
        step_lon = args.grid_m / (111320.0 * math.cos(math.radians(clat)))
        grid = [(mlat, mlon)]   # probe the marker itself first
        la = clat - dlat
        while la <= clat + dlat:
            lo = clon - dlon
            while lo <= clon + dlon:
                grid.append((la, lo))
                lo += step_lon
            la += step_lat
        print(f"  sampling DEM (ned10m): {len(grid)} cells over ±{args.box_m:.0f} m box…")
        try:
            samples = sample_dem(grid)
        except Exception as e:
            print(f"  DEM failed: {e}")
            continue
        valid = [(la, lo, e) for la, lo, e in samples if e is not None]
        if not valid:
            print("  DEM returned no elevations")
            continue
        m_ft = valid[0][2] * 3.28084
        slat, slon, sele = max(valid, key=lambda x: x[2])
        s_ft = sele * 3.28084
        print(f"  DEM @ marker:            {m_ft:,.0f} ft")
        print(f"  DEM local summit:        {fmt((slat, slon))}  {s_ft:,.0f} ft  "
              f"(marker → summit {hav_mi(mlat, mlon, slat, slon) * 5280:.0f} ft, "
              f"+{s_ft - m_ft:,.0f} ft)")

        # (2) TRACK SUMMIT-VISIT: per track, the point of CLOSEST APPROACH to the DEM
        # summit (where that party actually topped out). Cluster them — this is "where
        # the tracks linger" at the TOP, immune to approach-corridor bunching and to a
        # false-summit turnaround on the ridge (Kyle, 2026-07-23).
        visits = []
        for fname, pts in tracks:
            near = [p for p in pts if hav_mi(slat, slon, p[0], p[1]) <= args.radius_mi]
            if not near:
                continue
            ca = min(near, key=lambda p: hav_mi(slat, slon, p[0], p[1]))
            visits.append((ca, fname, hav_mi(slat, slon, ca[0], ca[1]) * 5280))
        if visits:
            vlat = sum(v[0][0] for v in visits) / len(visits)
            vlon = sum(v[0][1] for v in visits) / len(visits)
            print(f"  TRACK summit-visit (closest approach to summit), {len(visits)} track(s):")
            for ca, fname, dft in sorted(visits, key=lambda x: x[1]):
                print(f"      {fname}: {fmt(ca)}  ({dft:.0f} ft from DEM summit)")
            print(f"    → mean visit {fmt((vlat, vlon))}, "
                  f"{hav_mi(slat, slon, vlat, vlon) * 5280:.0f} ft from DEM summit; "
                  f"marker → visit {hav_mi(mlat, mlon, vlat, vlon) * 5280:.0f} ft")

        mtd = hav_mi(mlat, mlon, slat, slon) * 5280
        if mtd < 120 and (s_ft - m_ft) < 20:
            print("  → marker is on the local DEM summit — GOOD, no move needed")
        else:
            print(f"  → marker sits ~{mtd:.0f} ft from / {s_ft - m_ft:+,.0f} ft below the "
                  f"local DEM summit — candidate to MOVE to {fmt((slat, slon))} "
                  f"(confirm against the track visits above; your call)")


if __name__ == "__main__":
    main()
