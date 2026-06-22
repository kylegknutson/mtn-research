#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
build_recommended_route.py — compose a "recommended" route from real recorded tracks.

Given a report <slug> that has several source GPX tracks (parties who often added
extra unranked bumps, started low, or wandered), this builds the SHORTEST route
that follows the actual ground others walked but visits ONLY the report's ranked
objectives — the add-on peaks are trimmed out automatically.

Default method — pooled-track GRAPH router ("the shortest path others took"):
  1. Objectives = summits from *_peaks_only.gpx; start = highest trailhead in
     *_landmarks.gpx (or --start lat,lon).
  2. Pool every trackpoint into one graph; connect consecutive points within a
     track AND any points of different tracks that pass within --transfer-eps of
     each other (either direction). This lets the route splice part of one party's
     line onto another's where they cross — e.g. descend a peak down someone's
     *ascent* line, then rejoin a different approach.
  3. Dijkstra all-pairs shortest real-path distances among objectives; small
     open/closed TSP for the order (start → all summits → back to start by default).
  4. Stitch the real node-paths; a light RDP pass removes weave jitter. Add-on
     peaks are never visited (we only route between the ranked objectives).
Distance comes from the stitched geometry; GAIN is resampled from a DEM (GPX
<ele> is too noisy). Pass --legs for the older per-leg / whole-track router.

Output: gpx/<slug>/<slug>_recommended.gpx  (renders in the standardized
"recommended route (composed)" style on overview maps — see make_overview_map.py).

Usage:
  scripts/build_recommended_route.py baldy_lejos_trio
  scripts/build_recommended_route.py pt_13026_13408 --start auto
  scripts/build_recommended_route.py foo --legs           # older router
"""
from __future__ import annotations
import argparse, heapq, json, math, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from itertools import permutations
from pathlib import Path

GPX_ROOT = Path(__file__).resolve().parent.parent / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"


def export_to_gps_tracks(slug):
    """Mirror the just-built route (+ summit/trailhead markers) into the iCloud
    'GPS Tracks' folder. Best-effort: never fails the route build."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from export_to_gps_tracks import export_dir, DEFAULT_DEST
        export_dir(slug, DEFAULT_DEST)
    except SystemExit as ex:
        print(f"  WARN: GPS Tracks export skipped: {ex}", file=sys.stderr)
    except Exception as ex:
        print(f"  WARN: GPS Tracks export skipped: {ex}", file=sys.stderr)
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


def complete_tour(pts, obj_coords, start_coord, want_return):
    """If a single recorded track already makes a clean tour of ALL objectives
    (and, in loop mode, begins and ends near the start), return (length_m,
    trimmed_pts). Such a track is a real loop someone walked — it won't re-climb a
    peak the way independent shortest-legs can. Returns None if not a complete tour.
    """
    for la, lo in obj_coords:
        if closest_idx(pts, la, lo)[1] > SNAP_MAX_M:
            return None
    trimmed = pts
    if start_coord is not None:
        sla, slo = start_coord
        near = [i for i, p in enumerate(pts) if hav(p[0], p[1], sla, slo) <= SNAP_MAX_M]
        if not near:
            return None
        if want_return:
            if near[0] == near[-1]:
                return None              # only touches the start once → not a loop
            trimmed = pts[near[0]:near[-1] + 1]
        else:
            trimmed = pts[near[0]:]      # point-to-point: from the start onward
        for la, lo in obj_coords:        # objectives must survive the trim
            if closest_idx(trimmed, la, lo)[1] > SNAP_MAX_M:
                return None
    length = sum(hav(trimmed[i][0], trimmed[i][1], trimmed[i + 1][0], trimmed[i + 1][1])
                 for i in range(len(trimmed) - 1))
    return length, trimmed


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


# ── graph router (--graph) ────────────────────────────────────────────────────
# Pool every trackpoint into one graph, link points of any tracks that pass close
# together (either direction), and run shortest-path between objectives. This can
# splice part of one party's line onto another's where they cross mid-route — e.g.
# descend a peak down someone's *ascent* line, then rejoin a different approach —
# which the per-leg/whole-track method can't. Gain still comes from the DEM, so the
# graph's corner-cutting can't corrupt it; a light RDP pass removes weave jitter.

def thin_track(pts, min_m):
    if not pts:
        return pts
    out = [pts[0]]
    for p in pts[1:]:
        if hav(out[-1][0], out[-1][1], p[0], p[1]) >= min_m:
            out.append(p)
    if out[-1] is not pts[-1]:
        out.append(pts[-1])
    return out


def build_graph(tracks, transfer_eps):
    """nodes = all (thinned) points; edges = within-track neighbors + short
    transfer edges between points of any tracks within transfer_eps (bidirectional)."""
    nodes, adj, track_of = [], [], []
    for ti, pts in enumerate(tracks):
        i0 = len(nodes)
        for p in pts:
            nodes.append(p); adj.append([]); track_of.append(ti)
        for k in range(len(pts) - 1):
            i, j = i0 + k, i0 + k + 1
            w = hav(pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1])
            adj[i].append((j, w)); adj[j].append((i, w))
    if not nodes:
        return nodes, adj
    mean_lat = sum(n[0] for n in nodes) / len(nodes)
    dlat = transfer_eps / 111000.0
    dlon = transfer_eps / (111000.0 * max(0.2, math.cos(math.radians(mean_lat))))
    grid = {}
    CELL_CAP = 64   # cap transfer-grid occupancy so dense clusters (many tracks
                    # converging at a summit/TH) can't make this O(n²) and hang
    for i, n in enumerate(nodes):
        lst = grid.setdefault((int(n[0] / dlat), int(n[1] / dlon)), [])
        if len(lst) < CELL_CAP:
            lst.append(i)
    for i, n in enumerate(nodes):
        ci, cj = int(n[0] / dlat), int(n[1] / dlon)
        for a in (ci - 1, ci, ci + 1):
            for b in (cj - 1, cj, cj + 1):
                for j in grid.get((a, b), ()):
                    if j <= i or track_of[j] == track_of[i]:
                        continue
                    dd = hav(n[0], n[1], nodes[j][0], nodes[j][1])
                    if dd <= transfer_eps:
                        adj[i].append((j, dd)); adj[j].append((i, dd))
    return nodes, adj


def dijkstra(adj, src):
    INF = float("inf")
    dist = [INF] * len(adj)
    prev = [-1] * len(adj)
    dist[src] = 0.0
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd; prev[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, prev


def path_nodes(prev, src, dst):
    out, u = [], dst
    while u != -1:
        out.append(u)
        if u == src:
            break
        u = prev[u]
    out.reverse()
    return out if out and out[0] == src else []


def rdp(pts, eps_m):
    """Ramer–Douglas–Peucker simplification (keeps (lat,lon,ele) tuples)."""
    if len(pts) < 3:
        return pts
    lat0 = pts[0][0]
    kx = math.cos(math.radians(lat0)) * 111320.0
    ky = 111320.0
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        xa, ya = pts[a][1] * kx, pts[a][0] * ky
        xb, yb = pts[b][1] * kx, pts[b][0] * ky
        dx, dy = xb - xa, yb - ya
        L = math.hypot(dx, dy)
        maxd, idx = -1.0, -1
        for i in range(a + 1, b):
            xi, yi = pts[i][1] * kx, pts[i][0] * ky
            if L < 1e-6:                          # degenerate base (closed loop)
                dperp = math.hypot(xi - xa, yi - ya)   # → keep the farthest point
            else:
                dperp = abs((xi - xa) * dy - (yi - ya) * dx) / L
            if dperp > maxd:
                maxd, idx = dperp, i
        if maxd > eps_m:
            keep[idx] = True
            stack.append((a, idx)); stack.append((idx, b))
    return [p for i, p in enumerate(pts) if keep[i]]


def tsp_order(pd, n, has_start, want_return):
    """Order terminals (index 0 = start if has_start). Brute-force for small N;
    nearest-neighbor for large N so a bloated objective set can't blow up (N!)."""
    obj_ids = list(range(1, n)) if has_start else list(range(n))
    if len(obj_ids) <= 8:
        best = None
        for perm in permutations(obj_ids):
            order = ([0, *perm] + ([0] if want_return else [])) if has_start else list(perm)
            tot = sum(pd(order[k], order[k + 1]) for k in range(len(order) - 1))
            if best is None or tot < best[0]:
                best = (tot, order)
        return best[1]
    # nearest-neighbor
    start = 0 if has_start else obj_ids[0]
    unvisited = set(obj_ids); unvisited.discard(start)
    order = [start]; cur = start
    while unvisited:
        nxt = min(unvisited, key=lambda j: pd(cur, j))
        order.append(nxt); unvisited.discard(nxt); cur = nxt
    if has_start and want_return:
        order.append(0)
    return order


def graph_route(tracks, terms, has_start, want_return, thin_m, transfer_eps, rdp_eps):
    """Shortest real-path route through the terminals via the pooled-track graph.
    Returns (route_pts, dist_m, order_indices)."""
    # Adaptive thinning: keep the node count bounded so dense/huge track sets
    # (e.g. 120k+ points across many long tracks) don't make the graph build crawl.
    NODE_CAP = 30000
    tm, te = thin_m, transfer_eps
    total = sum(len(thin_track(t, tm)) for t in tracks)
    if total > NODE_CAP:
        k = total / NODE_CAP
        tm, te = thin_m * k, transfer_eps * k
        print(f"Large track set ({total} pts) → thinning to {tm:.0f} m (transfer {te:.0f} m)")
    nodes, adj = build_graph([thin_track(t, tm) for t in tracks], te)
    print(f"Graph: {len(nodes)} nodes (thin {tm:.0f} m, transfer {te:.0f} m)")
    snapped = []
    for label, la, lo in terms:
        bi, bd = closest_idx(nodes, la, lo)
        if bd > SNAP_MAX_M:
            print(f"  WARN: {label} snaps {bd:.0f} m from nearest track point")
        snapped.append(bi)
    srcs = {idx: dijkstra(adj, idx) for idx in set(snapped)}

    def pd(i, j):
        return srcs[snapped[i]][0][snapped[j]]

    order = tsp_order(pd, len(terms), has_start, want_return)
    if any(math.isinf(pd(order[k], order[k + 1])) for k in range(len(order) - 1)):
        sys.exit("ERROR (--graph): terminals not all connected; tracks may not "
                 "overlap. Try a larger --transfer-eps.")
    # reconstruct node path
    seq = []
    for k in range(len(order) - 1):
        a, b = order[k], order[k + 1]
        p = path_nodes(srcs[snapped[a]][1], snapped[a], snapped[b])
        if k:
            p = p[1:]
        seq.extend(p)
    route = rdp([nodes[i] for i in seq], rdp_eps)
    dist = sum(hav(route[i][0], route[i][1], route[i + 1][0], route[i + 1][1])
               for i in range(len(route) - 1))
    return route, dist, order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--start", default="auto", help="'auto' (highest trailhead), 'none', or 'lat,lon'")
    ap.add_argument("--no-return", action="store_true", help="point-to-point (don't return to start)")
    ap.add_argument("--no-dem", action="store_true", help="use noisy GPX elevation instead of resampling a DEM")
    ap.add_argument("--dem-dataset", default="ned10m", help="opentopodata dataset (default ned10m = USGS 10m, US)")
    ap.add_argument("--legs", action="store_true", help="use the older per-leg stitched / whole-track router instead of the default graph router")
    ap.add_argument("--thin", type=float, default=12.0, help="[graph] thin tracks to this spacing (m)")
    ap.add_argument("--transfer-eps", type=float, default=18.0, help="[graph] max gap to hop between tracks (m)")
    ap.add_argument("--rdp-eps", type=float, default=8.0, help="[graph] simplification tolerance to remove weave jitter (m)")
    ap.add_argument("--from-track", help="use a recorded track (filename substring) VERBATIM as the route, "
                    "instead of composing — for when the router routes long but one real party track already "
                    "makes the efficient tour (use scripts/analyze_tracks.py to find it). DEM-measures + writes it.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--peaks-only", default=None,
                    help="objectives GPX to use instead of the slug's *_peaks_only.gpx — "
                         "pass a per-DAY subset to compose a single day's route on a multi-day "
                         "trip (combine with --start <day TH lat,lon> and --out day_<label>_recommended.gpx)")
    args = ap.parse_args()

    d = GPX_ROOT / args.slug
    if not d.exists():
        sys.exit(f"ERROR: {d} not found")

    # Escape hatch: designate a single recorded track as the route. The graph/legs
    # routers minimize distance through pooled points and can stitch a long path
    # (cuba_gulch_trio: 22 mi composed vs a real 15.8 mi party track that tours all
    # three). When analyze_tracks.py shows a clean single track, use it verbatim.
    if args.from_track:
        matches = sorted(f for f in d.glob("*.gpx")
                         if args.from_track.lower() in f.name.lower()
                         and not any(s in f.name.lower() for s in SKIP))
        if len(matches) != 1:
            sys.exit(f"--from-track {args.from_track!r}: matched {[m.name for m in matches]} — be specific.")
        src_f = matches[0]
        route = parse_track_points(src_f)
        if len(route) < 2:
            sys.exit(f"--from-track: {src_f.name} has no usable points")
        dist = sum(hav(route[i][0], route[i][1], route[i+1][0], route[i+1][1])
                   for i in range(len(route)-1))
        print(f"Using recorded track verbatim: {src_f.name} — {dist/1609.34:.2f} mi")
        if args.no_dem:
            gain, gain_src = gps_gain(route), "GPS <ele> (noisy)"
        else:
            print(f"Sampling DEM ({args.dem_dataset}) for elevation gain…")
            try:
                gain, used = dem_gain(route, args.dem_dataset); gain_src = f"DEM {used}"
            except Exception as ex:
                gain, gain_src = gps_gain(route), "GPS <ele> (DEM failed — noisy!)"
                print(f"  WARN: {ex}; fell back to GPS elevation", file=sys.stderr)
        print(f"\nRecommended route: {dist/1609.34:.2f} mi · ~{gain*3.281:.0f} ft gain "
              f"[{gain_src}] · {len(route)} pts")
        out = Path(args.out) if args.out else d / f"{args.slug}_recommended.gpx"
        with open(out, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<gpx version="1.1" creator="build_recommended_route.py" '
                    'xmlns="http://www.topografix.com/GPX/1/1">\n')
            f.write(f'<trk><name>Recommended route (composed): {args.slug} '
                    f'— {dist/1609.34:.1f} mi / {gain*3.281:.0f} ft</name><trkseg>\n')
            for la, lo, ele in route:
                es = f"<ele>{ele:.1f}</ele>" if ele is not None else ""
                f.write(f'<trkpt lat="{la:.6f}" lon="{lo:.6f}">{es}</trkpt>\n')
            f.write("</trkseg></trk>\n</gpx>\n")
        print(f"Wrote {out}")
        export_to_gps_tracks(args.slug)
        return

    track_files = [f for f in sorted(d.glob("*.gpx"))
                   if not any(s in f.name.lower() for s in SKIP)]
    tracks = [parse_track_points(f) for f in track_files]
    keep = [(f, t) for f, t in zip(track_files, tracks) if len(t) >= 2]
    track_files, tracks = [f for f, _ in keep], [t for _, t in keep]
    if not tracks:
        sys.exit("ERROR: no usable source tracks")
    print(f"Source tracks: {len(tracks)}")

    pk = Path(args.peaks_only) if args.peaks_only else next(d.glob("*peaks_only*.gpx"), None)
    if not pk or not pk.exists():
        sys.exit("ERROR: no *_peaks_only.gpx (need objective summits)")
    objs = parse_waypoints(pk)
    # peaks_only can carry NEARBY context peaks (nearby.include) after the real
    # objectives — build_peak_gpx writes the objectives FIRST, then context. Routing
    # ALL of them links peaks that aren't objectives (homestake routed through Savage
    # + PT 13,002; hunts through its already-climbed neighbors). Trim to the declared
    # objective count so the route only visits the report's actual objectives.
    if not args.peaks_only:   # an explicit --peaks-only subset is already exactly the objectives
        yml0 = d / "peaks.yml"
        if yml0.exists():
            import yaml
            oid = (yaml.safe_load(yml0.read_text()) or {}).get("objective_ids") or []
            if oid and len(oid) < len(objs):
                print(f"  (trimming {len(objs)} peaks_only markers to {len(oid)} objective(s); "
                      f"rest are nearby context)")
                objs = objs[:len(oid)]
    print(f"Objectives ({len(objs)}): " + ", ".join(o[2].split(" (")[0] for o in objs))

    # terminals: list of (label, lat, lon); start (if any) first
    terms = []
    start = None
    if args.start == "auto":
        # Prefer peaks.yml landmarks marked kind: trailhead (the generated
        # *_landmarks.gpx flattens kind, so the highest *point* could be a pass).
        # Among trailheads pick the highest-elevation (best drivable) start.
        ths = []
        yml = d / "peaks.yml"
        if yml.exists():
            import yaml
            cfg = yaml.safe_load(yml.read_text()) or {}
            for l in (cfg.get("landmarks") or []):
                if l.get("kind") == "trailhead" and l.get("lat") is not None:
                    ths.append((l.get("ele_ft") or 0, l["lat"], l["lon"], l["name"]))
        if not ths:  # fallback: highest waypoint in the landmarks gpx
            lm = next(d.glob("*landmark*.gpx"), None)
            ths = [(ele or 0, la, lo, nm) for la, lo, nm, ele in (parse_waypoints(lm) if lm else [])]
        if ths:
            ths.sort(reverse=True)
            _, la, lo, nm = ths[0]
            start = (nm, la, lo)
            print(f"Start: {nm} ({ths[0][0]:.0f} ft)")
    elif args.start != "none":
        la, lo = (float(x) for x in args.start.split(","))
        start = ("start", la, lo)
    if start:
        terms.append(start)
    obj_terms = [(nm.split(" (")[0], la, lo) for la, lo, nm, _ in objs]
    terms += obj_terms

    if not args.legs:
        route, dist, order = graph_route(
            tracks, terms, bool(start), not args.no_return,
            args.thin, args.transfer_eps, args.rdp_eps)
        print("Order: " + " -> ".join(terms[k][0] for k in order))
    else:
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

        # order via TSP (brute force small N, nearest-neighbor large N)
        order = tsp_order(pdist, n, bool(start), not args.no_return)
        total = sum(pdist(order[k], order[k + 1]) for k in range(len(order) - 1))
        if math.isinf(total):
            sys.exit("ERROR: some legs have no single track connecting them "
                     "(no party walked directly between two objectives). "
                     "Add a bridging track or visit objectives separately, or try --graph.")

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

        # Prefer a whole recorded track that already makes a clean tour of every
        # objective when one is competitive: per-leg stitching minimizes each leg
        # independently, which can re-climb a peak (e.g. descending the ascent ridge
        # because that half is marginally shorter). A single real loop avoids that.
        obj_coords = [(la, lo) for la, lo, _, _ in objs]
        start_coord = (start[1], start[2]) if start else None
        completes = []
        for ti, pts in enumerate(tracks):
            c = complete_tour(pts, obj_coords, start_coord, not args.no_return)
            if c:
                completes.append((c[0], c[1], ti))
        completes.sort(key=lambda x: x[0])
        if completes and completes[0][0] <= dist * 1.05:
            cl, cpts, cti = completes[0]
            print(f"\nUsing whole track {track_files[cti].name} — a clean "
                  f"{cl/1609.34:.2f} mi loop through all objectives "
                  f"(stitched legs were {dist/1609.34:.2f} mi but re-climbed a peak).")
            route, dist = cpts, cl
        elif completes:
            print(f"\n(Shortest complete single track is {completes[0][0]/1609.34:.2f} mi "
                  f"via {track_files[completes[0][2]].name}; keeping the stitched "
                  f"{dist/1609.34:.2f} mi route.)")
        else:
            print("\n(No single track tours all objectives; using the stitched route.)")

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
    export_to_gps_tracks(args.slug)


if __name__ == "__main__":
    main()
