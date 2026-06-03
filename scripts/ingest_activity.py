#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python"]
# ///
"""
ingest_activity.py — drop a GPX into the right regional CalTopo map.

Auto-classifies by track centroid, applies marker rules (summit waypoints →
blue mountain; everything else → grey dot), and appends with dedupe ON.

Default is dry-run; pass --apply to write to CalTopo.

Usage:
    scripts/ingest_activity.py my_hike.gpx                    # dry-run: show region + what would upload
    scripts/ingest_activity.py my_hike.gpx --apply            # write to CalTopo
    scripts/ingest_activity.py my_hike.gpx --map-id VKGB00L   # force a specific regional map
    scripts/ingest_activity.py my_hike.gpx --color '#FF8800'  # override track color
    scripts/ingest_activity.py my_hike.gpx --export ~/Downloads/peaks.gpx
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

logging.getLogger("caltopo_python").setLevel(logging.ERROR)
logging.basicConfig(level=logging.ERROR)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "cts.ini"
ACCOUNT = "kyleg.knutson@gmail.com"
GPX_NS = "{http://www.topografix.com/GPX/1/1}"

TRACK_COLOR = "#9933CC"   # purple — personal recordings (matches caltopo_mytracks.py)
SUMMIT_COLOR = "#2E78C7"  # blue mountain
POI_COLOR = "#9E9E9E"     # grey dot

# ---------------------------------------------------------------------------
# Region registry
# ---------------------------------------------------------------------------

REGION_MAP_IDS: dict[str, str] = {
    "sawatch": "L5VH4BU", "san_juan": "06AR6BF", "weminuche": "7AQN6TS",
    "sangre_de_cristo": "VKGB00L", "elk": "1G2G7DM", "gore": "6E4GJV2",
    "mosquito": "LECF68J", "tenmile": "7QE01UK", "front": "DLES5CC",
    "california": "F5LGTKK", "new_hampshire": "UDK6ETR", "vermont": "64P836C",
    "maine": "751MCA1", "massachusetts": "3KMUMLE", "nevada": "AMH9MNK",
    "utah": "PM8JQ6M", "arizona": "EL7D3N3", "oregon": "1CK179R",
    "washington": "U247A11", "wyoming": "CLK3609", "new_york": "D6CKS21",
    "hawaii": "VA473FB", "europe": "PQFB188",
}

# (min_lat, max_lat, min_lon, max_lon) — checked before CO range fallback
STATE_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "maine":         (43.06, 47.46, -71.08, -66.95),
    "new_hampshire": (42.70, 45.31, -72.56, -70.61),
    "vermont":       (42.73, 45.01, -73.44, -71.50),
    "massachusetts": (41.24, 42.89, -73.53, -69.93),
    "new_york":      (40.50, 45.01, -79.76, -71.86),
    "washington":    (45.55, 49.00, -124.77, -116.92),
    "oregon":        (42.00, 46.29, -124.56, -116.46),
    "california":    (32.53, 42.01, -124.41, -114.13),
    "nevada":        (35.00, 42.00, -120.00, -114.04),
    "utah":          (37.00, 42.00, -114.05, -109.04),
    "arizona":       (31.33, 37.00, -114.82, -109.04),
    "wyoming":       (40.99, 45.01, -111.05, -104.05),
    "hawaii":        (18.91, 22.24, -160.25, -154.81),
    "europe":        (35.00, 71.00, -25.00,  45.00),
}

# Centroid (lat, lon) for each CO range — used when centroid isn't in any state bbox.
# Tuned so nearest-centroid correctly assigns peaks near range boundaries
# (e.g. Jacque Peak → Gore, not Tenmile; Democrat/Lincoln → Mosquito, not Tenmile).
CO_CENTROIDS: dict[str, tuple[float, float]] = {
    "sawatch":          (39.00, -106.35),
    "san_juan":         (37.95, -107.65),
    "weminuche":        (37.65, -107.75),
    "sangre_de_cristo": (37.70, -105.55),
    "elk":              (39.10, -107.00),
    "gore":             (39.52, -106.25),  # shifted S/E to capture southern Gore (Jacque Peak)
    "mosquito":         (39.30, -106.13),  # Lincoln/Democrat cluster
    "tenmile":          (39.38, -106.12),  # Quandary/Pacific cluster
    "front":            (39.90, -105.55),
}

# ---------------------------------------------------------------------------
# Summit detection (inline from restyle_markers.py)
# ---------------------------------------------------------------------------

PEAK_WORDS = re.compile(r"\b(peak|pk|mountain|mtn|mt|summit|dome|butte|spire|"
                        r"needle|horn|baldy|benchmark|knob|hill|point|pt|pinnacle|"
                        r"crag|massif)", re.I)
POI_WORDS = re.compile(r"\b(trailhead|th|camp|campground|campsite|lake|creek|pass|"
                       r"parking|lot|wpt|waypoint|gulch|basin|spring|springs|junction|"
                       r"jct|saddle|road|rd|bridge|falls|reservoir|pond|meadow|cabin|"
                       r"hut|shelter|spur|divide|crossing|gate|tunnel|mine|ranch|store|"
                       r"hotel|home|car|truck|pickup|start|finish|trail|trailway|twinway|"
                       r"notch|woods|water|photo|height|national|wilderness|park|ridge|"
                       r"headwall|caretaker|possible|turnoff|turn|drop|spot|reception|"
                       r"take|look)\b", re.I)
NE_PEAKS: dict[str, str] = {
    "bondcliff": "Bondcliff", "galehead": "Galehead Mountain", "guyot": "Mount Guyot",
    "moosilauke": "Mount Moosilauke", "carrigain": "Mount Carrigain",
    "passaconaway": "Mount Passaconaway", "tecumseh": "Mount Tecumseh",
    "osceola": "Mount Osceola", "tripyramid": "Mount Tripyramid",
    "kinsman": "Kinsman Mountain", "moriah": "Mount Moriah", "waumbek": "Mount Waumbek",
    "isolation": "Mount Isolation", "lafayette": "Mount Lafayette",
    "lincoln": "Mount Lincoln", "garfield": "Mount Garfield", "liberty": "Mount Liberty",
    "flume": "Mount Flume", "whiteface": "Whiteface Mountain", "cannon": "Cannon Mountain",
    "zealand": "Mount Zealand", "owls head": "Owl's Head", "owl's head": "Owl's Head",
    "south twin": "South Twin Mountain", "north twin": "North Twin Mountain",
    "west bond": "West Bond", "little haystack": "Little Haystack Mountain",
    "wildcat": "Wildcat Mountain", "hancock": "Mount Hancock", "tom": "Mount Tom",
    "field": "Mount Field", "willey": "Mount Willey", "hale": "Mount Hale",
    "jackson": "Mount Jackson", "pierce": "Mount Pierce", "eisenhower": "Mount Eisenhower",
    "monroe": "Mount Monroe", "madison": "Mount Madison", "adams": "Mount Adams",
    "jefferson": "Mount Jefferson", "washington": "Mount Washington",
    "bond": "", "twin": "",
    "katahdin": "Katahdin", "top of maine": "Katahdin", "bigelow": "Bigelow Mountain",
    "sugarloaf": "Sugarloaf Mountain", "saddleback": "Saddleback Mountain",
    "abraham": "Mount Abraham", "spaulding": "Spaulding Mountain",
    "crocker": "Crocker Mountain", "old speck": "Old Speck Mountain",
    "redington": "Redington", "north brother": "North Brother",
    "south brother": "South Brother", "pamola": "Pamola Peak",
    "mansfield": "Mount Mansfield", "killington": "Killington Peak",
    "camels hump": "Camel's Hump", "camel's hump": "Camel's Hump",
    "ellen": "Mount Ellen", "bread loaf": "Bread Loaf Mountain",
    "equinox": "Mount Equinox", "greylock": "Mount Greylock",
}
_NE_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in NE_PEAKS) + r")\b", re.I)
_SUMMIT_OVERRIDES = re.compile(r"\b(top of maine)\b", re.I)

SNAP_M = 40.0


def _hav(a, b, c, d) -> float:
    R = 6_371_000.0
    dl = math.radians(c - a); do = math.radians(d - b)
    x = math.sin(dl/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(do/2)**2
    return 2*R*math.asin(math.sqrt(min(x, 1.0)))


def snap_canonical(lat, lon, export_summits) -> str | None:
    for slat, slon, name in export_summits:
        if abs(slat - lat) > 0.0006 or abs(slon - lon) > 0.0008:
            continue
        if _hav(lat, lon, slat, slon) <= SNAP_M:
            return name
    return None


def name_canonical(title: str) -> tuple[bool, str | None]:
    if not title:
        return False, None
    name = re.sub(r"\d+\s*$", "", title).strip()
    if _SUMMIT_OVERRIDES.search(name):
        m = _NE_RE.search(name)
        canon = NE_PEAKS.get(m.group(1).lower(), "") if m else ""
        return True, canon or None
    if POI_WORDS.search(name):
        return False, None
    m = _NE_RE.search(name)
    if m:
        return True, NE_PEAKS.get(m.group(1).lower(), "") or None
    if PEAK_WORDS.search(name):
        return True, None
    return False, None


# ---------------------------------------------------------------------------
# GPX parsing
# ---------------------------------------------------------------------------

def parse_gpx(path: Path):
    """Yield ('track', name, [(lat,lon),...]) and ('wpt', name, lat, lon)."""
    root = ET.parse(path).getroot()
    for trk in root.findall(f"{GPX_NS}trk"):
        name = (trk.findtext(f"{GPX_NS}name") or path.stem).strip()
        pts = []
        for seg in trk.findall(f"{GPX_NS}trkseg"):
            for pt in seg.findall(f"{GPX_NS}trkpt"):
                pts.append((float(pt.get("lat")), float(pt.get("lon"))))
        if pts:
            yield "track", name, pts
    for w in root.findall(f"{GPX_NS}wpt"):
        name = (w.findtext(f"{GPX_NS}name") or "wpt").strip()
        yield "wpt", name, float(w.get("lat")), float(w.get("lon"))


def load_export(path: Path) -> list[tuple[float, float, str]]:
    out = []
    for w in ET.parse(path).getroot().findall(f"{GPX_NS}wpt"):
        ne = w.find(f"{GPX_NS}name")
        out.append((float(w.get("lat")), float(w.get("lon")),
                    ne.text.strip() if ne is not None and ne.text else ""))
    return out


# ---------------------------------------------------------------------------
# Region classification
# ---------------------------------------------------------------------------

def classify_region(clat: float, clon: float) -> tuple[str, str] | None:
    """Return (region_name, map_id) or None."""
    for region, (mn_lat, mx_lat, mn_lon, mx_lon) in STATE_BBOXES.items():
        if mn_lat <= clat <= mx_lat and mn_lon <= clon <= mx_lon:
            return region, REGION_MAP_IDS[region]
    # Nearest CO range
    best = min(CO_CENTROIDS.items(),
               key=lambda kv: _hav(clat, clon, kv[1][0], kv[1][1]))
    region, (rlat, rlon) = best
    if _hav(clat, clon, rlat, rlon) > 300_000:
        return None
    return region, REGION_MAP_IDS[region]


# ---------------------------------------------------------------------------
# Dedupe helpers (operating on live CaltopoSession features)
# ---------------------------------------------------------------------------

def _track_pts(feature) -> list[tuple[float, float]]:
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    return [(c[1], c[0]) for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]


def _track_len(pts) -> float:
    return sum(_hav(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) for i in range(len(pts)-1))


def _is_dup_track(cand_pts, existing_feats, tol_m=30.0, coverage=0.90, len_tol=0.20) -> bool:
    if len(cand_pts) < 2:
        return False
    clen = _track_len(cand_pts)
    step = max(1, len(cand_pts) // 100)
    sample = cand_pts[::step]
    for feat in existing_feats:
        if (feat.get("geometry") or {}).get("type") != "LineString":
            continue
        ex_pts = _track_pts(feat)
        if len(ex_pts) < 2:
            continue
        if clen > 0 and _track_len(ex_pts) > 0:
            ratio = clen / _track_len(ex_pts)
            if ratio < (1 - len_tol) or ratio > 1 + len_tol:
                continue
        pad = tol_m / 111000.0
        matched = sum(
            1 for cp in sample
            if any(abs(cp[0]-ep[0]) < pad*2 and abs(cp[1]-ep[1]) < pad*2
                   and _hav(cp[0], cp[1], ep[0], ep[1]) <= tol_m
                   for ep in ex_pts)
        )
        if matched / len(sample) >= coverage:
            return True
    return False


def _is_dup_marker(lat, lon, existing_feats, tol_m=25.0) -> bool:
    for feat in existing_feats:
        if (feat.get("geometry") or {}).get("type") != "Point":
            continue
        c = (feat.get("geometry") or {}).get("coordinates") or []
        if len(c) < 2:
            continue
        if _hav(lat, lon, c[1], c[0]) <= tol_m:
            return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gpx", type=Path, help="GPX file to ingest")
    ap.add_argument("--map-id", help="Override auto-classification with this regional map ID")
    ap.add_argument("--color", default=TRACK_COLOR, help=f"Track color hex (default {TRACK_COLOR})")
    ap.add_argument("--export", type=Path,
                    help="14ers peak-export GPX for summit snap detection (auto-detected if omitted)")
    ap.add_argument("--apply", action="store_true", help="Write to CalTopo (default is dry-run)")
    args = ap.parse_args()

    if not args.gpx.exists():
        raise SystemExit(f"File not found: {args.gpx}")

    # Auto-detect export GPX
    export_path = args.export
    if export_path is None:
        candidates = sorted(PROJECT_DIR.glob("14ers_peak_export_*.gpx"))
        if candidates:
            export_path = candidates[-1]
    export_summits = load_export(export_path) if export_path and export_path.exists() else []
    if export_summits:
        print(f"Summit snap: {len(export_summits)} peaks from {export_path.name}")
    else:
        print("Summit snap: no export GPX found — name-based detection only")

    # Parse GPX
    tracks = []
    waypoints = []
    for item in parse_gpx(args.gpx):
        if item[0] == "track":
            _, name, pts = item
            tracks.append((name, pts))
        else:
            _, name, lat, lon = item
            waypoints.append((name, lat, lon))

    if not tracks and not waypoints:
        raise SystemExit("No tracks or waypoints found in GPX.")

    all_pts = [pt for _, pts in tracks for pt in pts]
    clat = sum(p[0] for p in all_pts) / len(all_pts) if all_pts else (waypoints[0][1] if waypoints else 0)
    clon = sum(p[1] for p in all_pts) / len(all_pts) if all_pts else (waypoints[0][2] if waypoints else 0)

    print(f"\nGPX: {args.gpx.name}")
    print(f"  {len(tracks)} track(s), {len(waypoints)} waypoint(s)")
    print(f"  centroid: {clat:.4f}°N, {clon:.4f}°E")

    # Region classification
    if args.map_id:
        # Find region name for the forced map ID
        region = next((r for r, mid in REGION_MAP_IDS.items() if mid == args.map_id), "custom")
        map_id = args.map_id
        print(f"  region:   {region} ({map_id})  [forced via --map-id]")
    else:
        result = classify_region(clat, clon)
        if result is None:
            raise SystemExit(
                "Could not classify region — pass --map-id to specify the target map.\n"
                f"  Centroid: {clat:.4f}°N, {clon:.4f}°E"
            )
        region, map_id = result
        print(f"  region:   {region} ({map_id})")

    # Classify waypoints
    summits_to_add: list[tuple[str, float, float]] = []  # (canonical_title, lat, lon)
    pois_to_add: list[tuple[str, float, float]] = []
    for name, lat, lon in waypoints:
        snap = snap_canonical(lat, lon, export_summits)
        is_sum, canon = name_canonical(name)
        if snap is not None:
            summits_to_add.append((snap, lat, lon))
        elif is_sum:
            summits_to_add.append((canon or name, lat, lon))
        else:
            pois_to_add.append((name, lat, lon))

    print(f"\n  Tracks to upload:  {len(tracks)}")
    print(f"  Summit markers:    {len(summits_to_add)}")
    print(f"  POI markers:       {len(pois_to_add)}")
    if summits_to_add:
        for title, lat, lon in summits_to_add:
            print(f"    summit  {title!r} @ {lat:.5f},{lon:.5f}")
    if pois_to_add:
        for title, lat, lon in pois_to_add:
            print(f"    poi     {title!r} @ {lat:.5f},{lon:.5f}")

    if not args.apply:
        print(f"\n[DRY RUN] Re-run with --apply to write to https://caltopo.com/m/{map_id}")
        return

    # --- apply ---
    from caltopo_python import CaltopoSession  # noqa: E402
    print(f"\n[APPLYING] Opening map {map_id}...")
    s = CaltopoSession(domainAndPort="caltopo.com", mapID=map_id,
                       configpath=str(CONFIG_PATH), account=ACCOUNT)
    existing = s.getFeatures() or []

    added_tracks = added_summits = added_pois = skipped = 0

    # Tracks
    for name, pts in tracks:
        if _is_dup_track(pts, existing):
            print(f"  SKIP  track {name!r}  (duplicate)")
            skipped += 1
            continue
        coords = [[lon, lat] for lat, lon in pts]
        s.addLine(points=coords, title=name, color=args.color,
                  description=f"From {args.gpx.name}")
        print(f"  +track  ({args.color}) {name!r}  [{len(pts)} pts]")
        added_tracks += 1

    # Summit markers
    for title, lat, lon in summits_to_add:
        if _is_dup_marker(lat, lon, existing):
            print(f"  SKIP  summit {title!r}  (duplicate)")
            skipped += 1
            continue
        s.addMarker(lat=lat, lon=lon, title=title, color=SUMMIT_COLOR, symbol="peak",
                    description=f"From {args.gpx.name}")
        print(f"  +summit ({SUMMIT_COLOR}) {title!r}")
        added_summits += 1

    # POI markers
    for title, lat, lon in pois_to_add:
        if _is_dup_marker(lat, lon, existing):
            print(f"  SKIP  poi {title!r}  (duplicate)")
            skipped += 1
            continue
        s.addMarker(lat=lat, lon=lon, title=title, color=POI_COLOR, symbol="point",
                    description=f"From {args.gpx.name}")
        print(f"  +poi    ({POI_COLOR}) {title!r}")
        added_pois += 1

    print(f"\nDone: +{added_tracks} track(s), +{added_summits} summit(s), "
          f"+{added_pois} POI(s), {skipped} skipped (duplicates).")
    print(f"https://caltopo.com/m/{map_id}")


if __name__ == "__main__":
    main()
