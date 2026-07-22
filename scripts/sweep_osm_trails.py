#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""Sweep the full OSM trail network around a report's objectives + neighbors +
landmarks, save each trail as its own <slug>/trail_osm_<name>.gpx, and make them
available as source tracks for route composition.

Kyle, 2026-07-22: made this a **standard** step in the sweep workflow — right
alongside the 3-source track sweep (14ers/LoJ/peakbagger). The reason: recorded
tracks tell you where climbers HAVE walked, but mapped OSM trails tell you where
the terrain lets you walk that no one happened to record. Both matter for
recommending a route. The Rito Alto build spent iterations discovering the
Rito Alto Trail + North Fork Crestone Trail + Hermit Pass Trail that connect
the objectives — trails that no recorded track covers cleanly. Fetching those
first makes route composition natural, not archaeological.

Usage:
  scripts/sweep_osm_trails.py --slug <slug>                    # default 2-mi bbox pad
  scripts/sweep_osm_trails.py --slug <slug> --pad-mi 3          # wider bbox
  scripts/sweep_osm_trails.py --slug <slug> --dry-run           # print, don't write

The bbox is computed from every coord in peaks.yml (objective peaks via peak_db,
context peaks, landmarks). Each OSM way with highway=path/footway/track/trail/
bridleway (or route=hiking, foot=designated) becomes one .gpx track file named
after its OSM name (or `unnamed-<hwy>-<hash>` if unnamed). Files skip the source
coverage check (they're mapped-trail data, not recorded tracks) — the sweep_peak
`_count_on_disk` SKIP pattern includes 'trail_osm' so they never inflate the
14ers/LoJ/peakbagger counts.

**Downstream:** build_recommended_route.py picks these up as ordinary source
tracks (they're not in its SKIP list unless named the exact wrong way). The graph
router treats them as walkable edges — exactly what you want when a mapped trail
connects two objectives.
"""
import argparse
import hashlib
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

WALKABLE_HW = ("path", "footway", "track", "bridleway", "steps", "trail")

MI_PER_DEG_LAT = 69.0
def mi_per_deg_lon(lat): return 69.0 * math.cos(math.radians(lat))


def _load_peaks_yml(slug):
    import yaml
    p = GPX / slug / "peaks.yml"
    if not p.exists():
        sys.exit(f"no peaks.yml at {p}")
    return yaml.safe_load(p.read_text())


def _peak_coords(ids):
    """Look up coords for a list of peak_db ids."""
    if not ids: return []
    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    by = {p["id"]: p for p in peaks()}
    out = []
    for i in ids:
        p = by.get(i)
        if p and p.get("lat") is not None and p.get("lon") is not None:
            out.append((float(p["lat"]), float(p["lon"])))
    return out


def compute_bbox(slug, pad_mi):
    """(S, W, N, E) enclosing every objective/context/landmark point in peaks.yml, padded."""
    cfg = _load_peaks_yml(slug) or {}
    coords = _peak_coords((cfg.get("objective_ids") or []) + (cfg.get("context_ids") or []))
    for lm in (cfg.get("landmarks") or []):
        if lm.get("lat") is not None and lm.get("lon") is not None:
            coords.append((float(lm["lat"]), float(lm["lon"])))
    if not coords:
        sys.exit("no coords resolvable from peaks.yml (objective/context/landmarks)")
    lats = [c[0] for c in coords]; lons = [c[1] for c in coords]
    lat0 = (min(lats)+max(lats))/2
    pad_lat = pad_mi / MI_PER_DEG_LAT
    pad_lon = pad_mi / mi_per_deg_lon(lat0)
    return (min(lats)-pad_lat, min(lons)-pad_lon, max(lats)+pad_lat, max(lons)+pad_lon)


def fetch_overpass(bbox, timeout=90):
    """Fetch all walkable ways + their nodes in bbox. Retries mirrors on failure."""
    s, w, n, e = bbox
    hw_re = "|".join(WALKABLE_HW)
    q = (
        f"[out:json][timeout:{timeout}];"
        f'(way["highway"~"^({hw_re})$"]({s},{w},{n},{e});'
        f'way["foot"="designated"]({s},{w},{n},{e});'
        f'way["route"="hiking"]({s},{w},{n},{e}););'
        f"(._;>;);out body;"
    )
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for mirror in OVERPASS_MIRRORS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    mirror, data=data,
                    headers={"User-Agent": "mtn_research/sweep_osm_trails (personal peak research)"},
                )
                with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
                    return json.load(resp)
            except Exception as ex:  # noqa: BLE001
                last = ex
                sys.stderr.write(f"  overpass {mirror} attempt {attempt+1}: {ex}\n")
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def _safe_slug(name):
    s = re.sub(r"[^\w]+", "_", name).strip("_").lower()
    return s[:60]


def write_trail_gpx(dest, way_name, coords):
    """Write one <trk> file for an OSM way (coords = list of (lat, lon))."""
    body = "\n".join(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}"></trkpt>' for lat, lon in coords)
    dest.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="sweep_osm_trails" xmlns="http://www.topografix.com/GPX/1/1">\n'
        f'  <trk><name>{_escape_xml(way_name)}</name><trkseg>\n'
        f"{body}\n  </trkseg></trk>\n</gpx>\n"
    )


def _escape_xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--pad-mi", type=float, default=2.0, help="padding around objective+context+landmark bbox (default 2 mi)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite existing trail_osm_*.gpx files")
    args = ap.parse_args()

    slug_dir = GPX / args.slug
    if not slug_dir.exists():
        sys.exit(f"no slug dir at {slug_dir}")

    bbox = compute_bbox(args.slug, args.pad_mi)
    print(f"bbox: {bbox}  ({args.pad_mi}-mi pad)")

    if args.dry_run:
        print("(dry-run — not fetching or writing)")
        return

    osm = fetch_overpass(bbox)
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in osm.get("elements", []) if e["type"] == "node"}
    ways = [e for e in osm.get("elements", []) if e["type"] == "way"]

    # Group ways by name so a multi-way trail becomes a single file per way (keeps
    # geometry intact; sub-way ordering is determined by OSM's way list order).
    # Files: trail_osm_<safe-name>_<way-id>.gpx  (way id disambiguates same-name segments)
    wrote = 0
    for w in ways:
        pts = [nodes[n] for n in w.get("nodes", []) if n in nodes]
        if len(pts) < 2:
            continue
        t = w.get("tags", {})
        name = t.get("name") or f"unnamed-{t.get('highway', '?')}"
        slug_name = _safe_slug(name)
        fname = f"trail_osm_{slug_name}_{w['id']}.gpx"
        dest = slug_dir / fname
        if dest.exists() and not args.force:
            continue
        write_trail_gpx(dest, name, pts)
        wrote += 1
    print(f"  wrote {wrote} trail file(s) to {slug_dir}/trail_osm_*.gpx (of {len(ways)} way(s) in bbox)")


if __name__ == "__main__":
    main()
