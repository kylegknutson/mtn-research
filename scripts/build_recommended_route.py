#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
build_recommended_route.py — compose a "recommended" route from real recorded tracks.

Given a report <slug> that has several source GPX tracks (parties who often added
extra unranked bumps, started low, or wandered), this builds the SHORTEST route
that follows the actual ground others walked but visits ONLY the report's ranked
objectives — the add-on peaks are trimmed out automatically.

Method (faithful to "follow the path others took"):
  1. Objectives = summits from *_peaks_only.gpx; start = highest trailhead in
     *_landmarks.gpx (or --start lat,lon).
  2. For every pair of objectives (incl. the start), find the SHORTEST contiguous
     segment of a SINGLE recorded track that connects them (its closest approach
     to A → closest approach to B). One leg = one real party's footsteps, so the
     elevation profile stays clean and nothing teleports across switchbacks.
  3. Order the objectives by solving the small open/closed TSP over those segment
     distances (start → all summits → back to start by default).
  4. Emit the chosen real segments end to end. Add-on peaks are never visited
     because we only route between the ranked objectives.

Output: gpx/<slug>/<slug>_recommended.gpx  (renders in the standardized
"recommended route (composed)" style on overview maps — see make_overview_map.py).

Usage:
  scripts/build_recommended_route.py baldy_lejos_trio
  scripts/build_recommended_route.py pt_13026_13408 --start auto
  scripts/build_recommended_route.py foo --start 37.95,-106.96 --no-return
"""
from __future__ import annotations
import argparse, json, math, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from itertools import permutations
from pathlib import Path

GPX_ROOT = Path(__file__).resolve().parent.parent / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in", "waypoints", "summit")
SNAP_MAX_M = 250.0   # a track must pass this close to "reach" an objective

# Elevation gain: GPS <ele> in the source tracks is unreliable (barometric drift —
# these tracks log 14,000' summits on 13ers), so by default we resample a real DEM
# along the route like CalTopo does. ned10m = USGS 10 m (US); srtm30m = global
# fallback. A ~6 m (≈20 ft) accumulation threshold matches CalTopo's gain filter.
DEM_THIN_M = 20.0
DEM_GAIN_THRESHOLD_M = 6.0
OPENTOPODATA = "https://api.opentopodata.org/v1"


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def parse_track_points(path: Path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    pts = []
    for p in root.iter(NS + "trkpt"):
        e = p.find(NS + "ele")
        ele = float(e.text) if e is not None and e.text else None
        pts.append((float(p.get("lat")), float(p.get("lon")), ele))
    return pts


def parse_waypoints(path: Path):
    root = ET.parse(path).getroot()
    out = []
    for w in root.iter(NS + "wpt"):
        n = w.find(NS + "name")
        e = w.find(NS + "ele")
        out.append((float(w.get("lat")), float(w.get("lon")),
                    n.text if n is not None else "",
                    float(e.text) if e is not None and e.text else None))
    return out


def closest_idx(pts, lat, lon):
    best, bi = 1e18, -1
    for i, p in enumerate(pts):
        d = hav(lat, lon, p[0], p[1])
        if d < best:
            best, bi = d, i
    return bi, best


def seg_len(pts, i, j):
    if i > j:
        i, j = j, i
    return sum(hav(pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1]) for k in range(i, j))


def best_segment(tracks, A, B):
    """Shortest single-track contiguous segment connecting terminals A,B.
    A,B are (lat,lon). Returns (length_m, track_index, idx_A, idx_B) where idx_A is
    the track point closest to A and idx_B closest to B, or None."""
    best = None
    for ti, pts in enumerate(tracks):
        ia, da = closest_idx(pts, A[0], A[1])
        ib, db = closest_idx(pts, B[0], B[1])
        if da > SNAP_MAX_M or db > SNAP_MAX_M:
            continue
        L = seg_len(pts, ia, ib)
        if best is None or L < best[0]:
            best = (L, ti, ia, ib)   # idx_A=ia, idx_B=ib
    return best


def accumulated_gain(eles, threshold_m):
    """Sum positive elevation deltas, ignoring runs of net climb below threshold."""
    if not eles:
        return 0.0
    gain = 0.0; accum = 0.0; prev = eles[0]
    for e in eles[1:]:
        de = e - prev
        if de > 0:
            accum += de
        else:
            if accum > threshold_m:
                gain += accum
            accum = 0.0
        prev = e
    if accum > threshold_m:
        gain += accum
    return gain


def gps_gain(route):
    """Fallback gain from the GPX <ele> values (noisy — caps single-step spikes)."""
    eles = [p[2] for p in route if p[2] is not None]
    if not eles:
        return 0.0
    clean = [eles[0]]
    for e in eles[1:]:
        if abs(e - clean[-1]) <= 40:   # drop barometric spikes
            clean.append(e)
    return accumulated_gain(clean, 8.0)


def sample_dem(latlons, dataset):
    """Elevations (m) for [(lat,lon),...] via opentopodata; None for any miss."""
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
        out += [r.get("elevation") for r in data["results"]]
        if i + 100 < len(latlons):
            time.sleep(1.1)   # public rate limit: 1 req/s
    return out


def dem_gain(route, dataset):
    """Resample a DEM along the route and return (gain_m, dataset_used).
    Thins to ~DEM_THIN_M spacing first; fills ned10m gaps from srtm30m."""
    thinned = [(route[0][0], route[0][1])]
    for la, lo, _ in route[1:]:
        if hav(thinned[-1][0], thinned[-1][1], la, lo) >= DEM_THIN_M:
            thinned.append((la, lo))
    eles = sample_dem(thinned, dataset)
    used = dataset
    if any(e is None for e in eles):   # fill misses (e.g. outside US for ned10m)
        fill = sample_dem(thinned, "srtm30m")
        eles = [e if e is not None else f for e, f in zip(eles, fill)]
        used = f"{dataset}+srtm30m"
    eles = [e for e in eles if e is not None]
    return accumulated_gain(eles, DEM_GAIN_THRESHOLD_M), used


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--start", default="auto", help="'auto' (highest trailhead), 'none', or 'lat,lon'")
    ap.add_argument("--no-return", action="store_true", help="point-to-point (don't return to start)")
    ap.add_argument("--no-dem", action="store_true", help="use noisy GPX elevation instead of resampling a DEM")
    ap.add_argument("--dem-dataset", default="ned10m", help="opentopodata dataset (default ned10m = USGS 10m, US)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d = GPX_ROOT / args.slug
    if not d.exists():
        sys.exit(f"ERROR: {d} not found")

    track_files = [f for f in sorted(d.glob("*.gpx"))
                   if not any(s in f.name.lower() for s in SKIP)]
    tracks = [parse_track_points(f) for f in track_files]
    keep = [(f, t) for f, t in zip(track_files, tracks) if len(t) >= 2]
    track_files, tracks = [f for f, _ in keep], [t for _, t in keep]
    if not tracks:
        sys.exit("ERROR: no usable source tracks")
    print(f"Source tracks: {len(tracks)}")

    pk = next(d.glob("*peaks_only*.gpx"), None)
    if not pk:
        sys.exit("ERROR: no *_peaks_only.gpx (need objective summits)")
    objs = parse_waypoints(pk)
    print(f"Objectives ({len(objs)}): " + ", ".join(o[2].split(" (")[0] for o in objs))

    # terminals: list of (label, lat, lon); start (if any) first
    terms = []
    start = None
    if args.start == "auto":
        lm = next(d.glob("*landmark*.gpx"), None)
        ths = [(ele or 0, la, lo, nm) for la, lo, nm, ele in (parse_waypoints(lm) if lm else [])]
        if ths:
            ths.sort(reverse=True)
            _, la, lo, nm = ths[0]
            start = (nm, la, lo)
            print(f"Start: {nm} ({ths[0][0] * 3.281:.0f} ft)")
    elif args.start != "none":
        la, lo = (float(x) for x in args.start.split(","))
        start = ("start", la, lo)
    if start:
        terms.append(start)
    obj_terms = [(nm.split(" (")[0], la, lo) for la, lo, nm, _ in objs]
    terms += obj_terms

    n = len(terms)
    # pairwise shortest single-track segments
    seg = {}
    for i in range(n):
        for j in range(i + 1, n):
            s = best_segment(tracks, terms[i][1:], terms[j][1:])
            if s:
                L, ti, ia, ib = s
                seg[(i, j)] = (L, ti, ia, ib)   # idx_A near i, idx_B near j
                seg[(j, i)] = (L, ti, ib, ia)   # reversed: idx_A near j, idx_B near i

    def pdist(i, j):
        return seg[(i, j)][0] if (i, j) in seg else float("inf")

    # order via brute-force TSP
    obj_ids = list(range(1, n)) if start else list(range(n))
    best = None
    for perm in permutations(obj_ids):
        if start:
            order = [0, *perm] + ([] if args.no_return else [0])
        else:
            order = list(perm)
        tot = sum(pdist(order[k], order[k + 1]) for k in range(len(order) - 1))
        if best is None or tot < best[0]:
            best = (tot, order)
    total, order = best
    if math.isinf(total):
        sys.exit("ERROR: some legs have no single track connecting them "
                 "(no party walked directly between two objectives). "
                 "Add a bridging track or visit objectives separately.")

    print("Order: " + " -> ".join(terms[k][0] for k in order))

    # emit segments
    route = []
    for k in range(len(order) - 1):
        a, b = order[k], order[k + 1]
        L, ti, ia, ib = seg[(a, b)]   # ia near a, ib near b
        pts = tracks[ti]
        lo_i, hi_i = (ia, ib) if ia <= ib else (ib, ia)
        chunk = pts[lo_i:hi_i + 1]
        if ia > ib:
            chunk = chunk[::-1]   # orient so chunk starts at a, ends at b
        if route:
            chunk = chunk[1:]
        route.extend(chunk)
        print(f"  {terms[a][0]:>22s} -> {terms[b][0]:<22s} {L/1609.34:5.2f} mi  via {track_files[ti].name}")

    dist = sum(hav(route[i][0], route[i][1], route[i + 1][0], route[i + 1][1])
               for i in range(len(route) - 1))

    if args.no_dem:
        gain, gain_src = gps_gain(route), "GPS <ele> (noisy)"
    else:
        print(f"Sampling DEM ({args.dem_dataset}) for elevation gain…")
        try:
            gain, used = dem_gain(route, args.dem_dataset)
            gain_src = f"DEM {used}"
        except Exception as ex:
            gain, gain_src = gps_gain(route), "GPS <ele> (DEM failed — noisy!)"
            print(f"  WARN: {ex}; fell back to GPS elevation", file=sys.stderr)

    print(f"\nRecommended route: {dist / 1609.34:.2f} mi · ~{gain * 3.281:.0f} ft gain "
          f"[{gain_src}] · {len(route)} pts")

    out = Path(args.out) if args.out else d / f"{args.slug}_recommended.gpx"
    with open(out, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="build_recommended_route.py" '
                'xmlns="http://www.topografix.com/GPX/1/1">\n')
        f.write(f'<trk><name>Recommended route (composed): {args.slug} '
                f'— {dist / 1609.34:.1f} mi / {gain * 3.281:.0f} ft</name><trkseg>\n')
        for la, lo, ele in route:
            es = f"<ele>{ele:.1f}</ele>" if ele is not None else ""
            f.write(f'<trkpt lat="{la:.6f}" lon="{lo:.6f}">{es}</trkpt>\n')
        f.write("</trkseg></trk>\n</gpx>\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
