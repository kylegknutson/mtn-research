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

        # Near points, keeping track identity (for the distinct-track metric).
        near = {}
        for fname, pts in tracks:
            np_ = [p for p in pts if hav_mi(mlat, mlon, p[0], p[1]) <= args.radius_mi]
            if np_:
                near[fname] = np_
        if not near:
            print("  no track points within radius — widen --radius-mi")
            continue
        near_all = [p for ps in near.values() for p in ps]

        # (A) TRACK CONVERGENCE (behavioral summit): bin near points into cells; for each
        # cell count DISTINCT tracks passing through (not raw points). The cell the MOST
        # separate parties pass through is the summit everyone tags — robust vs one party
        # milling on a flat shoulder (raw density) and vs a false-summit turnaround.
        from collections import defaultdict
        cell = 25.0  # m
        def ckey(p):
            return (round((p[0] - mlat) * 111320.0 / cell),
                    round((p[1] - mlon) * 111320.0 * math.cos(math.radians(mlat)) / cell))
        cell_tracks = defaultdict(set)
        cell_pts = defaultdict(list)
        for fname, ps in near.items():
            for p in ps:
                k = ckey(p)
                cell_tracks[k].add(fname)
                cell_pts[k].append(p)
        ranked = sorted(cell_tracks, key=lambda k: (len(cell_tracks[k]), len(cell_pts[k])), reverse=True)
        top = ranked[:5]
        def cell_centroid(k):
            ps = cell_pts[k]
            return (sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps))
        conv_k = top[0]
        conv = cell_centroid(conv_k)
        print(f"  TRACK convergence: {len(near)} track(s) reach the area; top {cell:.0f} m cells "
              f"by distinct-tracks:")
        for k in top:
            c = cell_centroid(k)
            print(f"      {fmt(c)}  {len(cell_tracks[k])} track(s), {len(cell_pts[k])} pts  "
                  f"({hav_mi(mlat, mlon, c[0], c[1]) * 5280:.0f} ft from marker)")

        if args.no_dem:
            print("  (--no-dem: skipping DEM elevations)")
            continue

        # (B) DEM elevations (ned10m — COARSE 10 m; note it can smooth a sharp knob and put
        # its max on a broad shoulder, so treat it as a cross-check, not the arbiter) at the
        # marker, the convergence cell, and the top cells; plus the ned10m grid max nearby.
        clat, clon = mlat, mlon
        dlat = args.box_m / 111320.0
        dlon = args.box_m / (111320.0 * math.cos(math.radians(clat)))
        step_lat = args.grid_m / 111320.0
        step_lon = args.grid_m / (111320.0 * math.cos(math.radians(clat)))
        probes = [(mlat, mlon), conv] + [cell_centroid(k) for k in top[1:]]
        n_probe = len(probes)
        la = clat - dlat
        while la <= clat + dlat:
            lo = clon - dlon
            while lo <= clon + dlon:
                probes.append((la, lo))
                lo += step_lon
            la += step_lat
        print(f"  sampling DEM (ned10m): {len(probes)} points (±{args.box_m:.0f} m grid + probes)…")
        try:
            samples = sample_dem(probes)
        except Exception as e:
            print(f"  DEM failed: {e}")
            continue
        ft = lambda e: e * 3.28084 if e is not None else float("nan")
        m_ft = ft(samples[0][2])
        c_ft = ft(samples[1][2])
        grid_valid = [(la, lo, e) for la, lo, e in samples[n_probe:] if e is not None]
        hlat, hlon, hele = max(grid_valid, key=lambda x: x[2]) if grid_valid else (mlat, mlon, None)
        print(f"  ned10m @ marker:      {m_ft:,.0f} ft")
        print(f"  ned10m @ convergence: {c_ft:,.0f} ft  ({'+' if c_ft >= m_ft else ''}{c_ft - m_ft:,.0f} ft vs marker)")
        if hele is not None:
            print(f"  ned10m grid max:      {fmt((hlat, hlon))}  {ft(hele):,.0f} ft  "
                  f"({hav_mi(mlat, mlon, hlat, hlon) * 5280:.0f} ft from marker)")

        cd = hav_mi(mlat, mlon, conv[0], conv[1]) * 5280
        if len(cell_tracks[conv_k]) >= 2 and cd > 100:
            print(f"  → tracks from {len(cell_tracks[conv_k])} parties converge ~{cd:.0f} ft from the "
                  f"marker at {fmt(conv)} — marker likely MISPLACED; verify elevation on CalTopo "
                  f"(ned10m is too coarse to trust here) and MOVE if that spot is higher. Your call.")
        else:
            print(f"  → convergence ~{cd:.0f} ft from marker — marker looks about right, but "
                  f"confirm against CalTopo elevation.")


if __name__ == "__main__":
    main()
