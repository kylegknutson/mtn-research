#!/usr/bin/env python3
"""Fetch a foot-trail line from OpenStreetMap and emit it as a GPX track.

Use this to obtain the geometry of a mapped Forest-Service / hiking trail that
appears on the CalTopo base layer but is NOT in any recorded GPS track — e.g. an
east-side connector trail that links two peak groups. Route between two points
along the OSM trail network so the connector follows the real trail (never a
straight-line invention — see CLAUDE.md).

Queries Overpass for walkable ways (highway in path/footway/track/bridleway/
steps/trail + designated foot routes) inside a bbox, builds an undirected graph
from shared nodes, and Dijkstra-routes between the graph nodes nearest to --from
and --to. Writes a single-track GPX (raw OSM node elevations are absent, so the
route builder should DEM-resample it downstream).

Examples:
  # Route the east connector trail between the north-group base and PT 13,054:
  scripts/fetch_osm_trail.py \
      --from 38.078,-105.665 --to 38.060,-105.657 \
      --bbox 38.04,-105.70,38.10,-105.62 \
      --out gpx/rito_alto_group/trail_east_connector.gpx

Overpass is rate-limited / occasionally flaky; the script tries several mirrors
with backoff and reports clearly if all fail (fall back to tracing on CalTopo).
"""
import argparse
import heapq
import json
import math
import sys
import time
import urllib.parse
import urllib.request
import xml.sax.saxutils as sax

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Walkable way classes. Foot-designated tracks/paths only; no motor roads.
WALKABLE = {"path", "footway", "track", "bridleway", "steps", "trail", "cycleway"}


def haversine_m(a, b):
    R = 6371000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def fetch_overpass(bbox, timeout=60):
    """bbox = (south, west, north, east). Returns parsed JSON or raises."""
    s, w, n, e = bbox
    hw = "|".join(sorted(WALKABLE))
    q = (
        f"[out:json][timeout:{timeout}];"
        f'(way["highway"~"^({hw})$"]({s},{w},{n},{e});'
        f'way["foot"="designated"]({s},{w},{n},{e});'
        f'way["route"="hiking"]({s},{w},{n},{e}););'
        f"(._;>;);out body;"
    )
    data = urllib.parse.urlencode({"data": q}).encode()
    last_err = None
    for mirror in OVERPASS_MIRRORS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    mirror, data=data,
                    headers={"User-Agent": "mtn_research/fetch_osm_trail (personal peak research)"},
                )
                with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
                    return json.load(resp)
            except Exception as ex:  # noqa: BLE001
                last_err = ex
                sys.stderr.write(f"  overpass {mirror} attempt {attempt+1} failed: {ex}\n")
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"all Overpass mirrors failed: {last_err}")


def build_graph(osm):
    """Return (nodes: id->(lat,lon), adj: id->list[(nbr, dist_m)])."""
    nodes = {}
    for el in osm.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lat"], el["lon"])
    adj = {}
    for el in osm.get("elements", []):
        if el["type"] != "way":
            continue
        nds = el.get("nodes", [])
        for u, v in zip(nds, nds[1:]):
            if u not in nodes or v not in nodes:
                continue
            d = haversine_m(nodes[u], nodes[v])
            adj.setdefault(u, []).append((v, d))
            adj.setdefault(v, []).append((u, d))
    return nodes, adj


def nearest_node(nodes, pt):
    best, bestd = None, float("inf")
    for nid, ll in nodes.items():
        d = haversine_m(ll, pt)
        if d < bestd:
            best, bestd = nid, d
    return best, bestd


def dijkstra(adj, src, dst):
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > dist.get(u, float("inf")):
            continue
        for v, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if dst not in dist:
        return None, None
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    path.reverse()
    return path, dist[dst]


def write_gpx(pts, out, name):
    esc = sax.escape(name)
    body = "\n".join(f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}"></trkpt>' for lat, lon in pts)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="fetch_osm_trail.py" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f"  <trk><name>{esc}</name><trkseg>\n{body}\n  </trkseg></trk>\n</gpx>\n"
    )
    with open(out, "w") as fh:
        fh.write(xml)


def parse_ll(s):
    a, b = s.split(",")
    return (float(a), float(b))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="frm", required=True, help="start lat,lon")
    ap.add_argument("--to", dest="to", required=True, help="end lat,lon")
    ap.add_argument("--bbox", required=True, help="south,west,north,east")
    ap.add_argument("--out", required=True, help="output .gpx path")
    ap.add_argument("--name", default="OSM trail connector")
    ap.add_argument("--max-snap-m", type=float, default=500.0,
                    help="fail if the nearest trail node to an endpoint is farther than this")
    args = ap.parse_args()

    frm, to = parse_ll(args.frm), parse_ll(args.to)
    s, w, n, e = [float(x) for x in args.bbox.split(",")]
    sys.stderr.write(f"Querying Overpass for walkable ways in bbox ({s},{w},{n},{e}) …\n")
    osm = fetch_overpass((s, w, n, e))
    nodes, adj = build_graph(osm)
    sys.stderr.write(f"  graph: {len(nodes)} nodes, {sum(len(v) for v in adj.values())//2} edges\n")
    if not nodes:
        sys.stderr.write("No trail ways found in bbox — widen it or fall back to CalTopo tracing.\n")
        sys.exit(2)

    src, dsrc = nearest_node(nodes, frm)
    dst, ddst = nearest_node(nodes, to)
    sys.stderr.write(f"  snapped start {dsrc:.0f} m to trail; end {ddst:.0f} m to trail\n")
    if dsrc > args.max_snap_m or ddst > args.max_snap_m:
        sys.stderr.write(f"Endpoint > {args.max_snap_m:.0f} m from any trail — check coords / bbox.\n")
        sys.exit(3)

    path, length_m = dijkstra(adj, src, dst)
    if path is None:
        sys.stderr.write("No connected trail path between the endpoints in this bbox.\n")
        sys.exit(4)
    pts = [nodes[nid] for nid in path]
    write_gpx(pts, args.out, args.name)
    mi = length_m / 1609.344
    print(f"Wrote {args.out}: {len(pts)} pts, {mi:.2f} mi along OSM trail "
          f"(snap {dsrc:.0f}/{ddst:.0f} m). DEM-resample downstream for gain.")


if __name__ == "__main__":
    main()
