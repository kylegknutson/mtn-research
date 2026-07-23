#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python"]
# ///
"""
Upload one or more .gpx files to a CalTopo map for visualization.

Runs via uv (PEP 723 inline deps) — no venv to manage. Install once per Mac:
  brew install uv

Two modes:
  --new-map TITLE   create a new map for this research session
  --map-id ID       append to an existing map

Tracks are added as colored lines, waypoints as markers. Files are grouped
into folders by source (parsed from filename suffix `_caltopo_<MAP_ID>.gpx`,
or the bare filename stem otherwise).

Usage:
    scripts/gpx_to_caltopo.py --gpx-dir ../gpx/dolores_peak \\
        --new-map "Research: Dolores + Middle Peak" --sharing URL

    scripts/gpx_to_caltopo.py --gpx <one.gpx> --gpx <two.gpx> --map-id ABC1234

The map URL is printed at the end. Default sharing for new maps is URL
(anyone with the link can view) — change with --sharing.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logging.getLogger("caltopo_python").setLevel(logging.WARNING)

from lib import CONFIG_PATH, GPX_NS, ROOT, caltopo_session, haversine_m  # noqa: E402

CALTOPO_DIR = ROOT / "caltopo"

# Track color palette — 16 visually distinct colors for per-track variety.
# Source convention (used by sync_to_regional.py): red=LoJ, green=14ers, blue=PB,
# purple=personal recordings. #39FF14 is reserved for summit markers — not here.
# Kyle's own recordings (files under a `_kyle_existing/` dir) are forced to KYLE_COLOR
# so they read consistently on web maps the way they already do blue in the report
# PNGs (make_overview_map.COLOR_KYLE). Explicit --color still overrides.
KYLE_COLOR = "#0066FF"   # blue — matches make_overview_map COLOR_KYLE (0,102,255)

# The composed recommended route is ALWAYS magenta (#E6008C, matches the PNG legend).
# RESERVED: no source-track palette color may be magenta OR anywhere near it — no
# magenta / pink / rose / crimson / red hues — or a recorded track gets confused for
# the recommended route on the CalTopo map (Kyle, 2026-07-23). The palette below is
# deliberately restricted to blues / greens / orange-yellows / violets, none of which
# read as magenta or red. RECOMMENDED_COLOR + RESERVED_HUE_RANGE are asserted against
# the palette at import so a future edit can't reintroduce a colliding color.
RECOMMENDED_COLOR = "#E6008C"   # magenta — recommended routes only
KYLE_HUE = 216                  # #0066FF blue — reserved for Kyle's recordings

# Base source-track hues: NO blue (reserved for Kyle), NO magenta/pink/red (reserved
# for recommended / confusing). Source→color is NOT a fixed convention (Kyle, 2026-07-23
# — colors don't need to mean "which source"); tracks just cycle through these.
BASE_PALETTE = [
    "#00AA00",  # green
    "#FF8800",  # orange
    "#9933CC",  # purple
    "#00BBCC",  # teal
    "#FFCC00",  # yellow
    "#99CC00",  # chartreuse
    "#6633FF",  # indigo
    "#009966",  # sea green
]


def _hue_deg(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx == mn:
        return 0.0
    d = mx - mn
    if mx == r:
        hue = ((g - b) / d) % 6
    elif mx == g:
        hue = (b - r) / d + 2
    else:
        hue = (r - g) / d + 4
    return hue * 60


def _mix(hexcolor: str, toward: tuple[int, int, int], frac: float) -> str:
    h = hexcolor.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    out = [round(c + (t - c) * frac) for c, t in zip(rgb, toward)]
    return "#" + "".join(f"{v:02X}" for v in out)


# When a map has more source tracks than base hues, keep them distinct by shifting
# LIGHTNESS in tiers (hue unchanged, so still never magenta/red/blue). Tier 0 = base,
# then alternate darker / lighter, deepening each round → base×N distinct shades,
# effectively unlimited. (Kyle, 2026-07-23: "what if there are more than 10 tracks?")
_BLACK, _WHITE = (0, 0, 0), (255, 255, 255)
_TIER_MIX = [None, (_BLACK, 0.45), (_WHITE, 0.45), (_BLACK, 0.68), (_WHITE, 0.68)]


def track_color(index: int) -> str:
    """Deterministic distinct color for the index-th source track on a map."""
    n = len(BASE_PALETTE)
    base = BASE_PALETTE[index % n]
    tier = (index // n) % len(_TIER_MIX)
    if tier == 0:
        return base
    toward, frac = _TIER_MIX[tier]
    return _mix(base, toward, frac)


# Backward-compat alias — old code referenced PALETTE[i % len(PALETTE)].
PALETTE = BASE_PALETTE

# Guard (fires at import so a bad palette edit can never ship): every base color must
# be well clear of magenta (recommended), the red band, AND Kyle's blue.
_MAGENTA_HUE = _hue_deg(RECOMMENDED_COLOR)
for _c in BASE_PALETTE:
    _hd = _hue_deg(_c)
    _dmag = min(abs(_hd - _MAGENTA_HUE), 360 - abs(_hd - _MAGENTA_HUE))
    _dblue = min(abs(_hd - KYLE_HUE), 360 - abs(_hd - KYLE_HUE))
    assert _dmag > 40, f"palette {_c} (hue {_hd:.0f}°) too close to recommended magenta"
    assert not (_hd < 25 or _hd > 345), f"palette {_c} (hue {_hd:.0f}°) in the red band — confusing"
    assert _dblue > 25, f"palette {_c} (hue {_hd:.0f}°) too close to Kyle-blue ({KYLE_HUE}°)"


def parse_gpx(path: Path):
    """Yield ('track', name, desc, [[lon,lat],...]) and ('wpt', name, desc, lat, lon, ele)."""
    tree = ET.parse(path)
    root = tree.getroot()
    for trk in root.findall(f"{GPX_NS}trk"):
        name = (trk.findtext(f"{GPX_NS}name") or path.stem).strip()
        desc = (trk.findtext(f"{GPX_NS}desc") or "").strip()
        coords = []
        for seg in trk.findall(f"{GPX_NS}trkseg"):
            for pt in seg.findall(f"{GPX_NS}trkpt"):
                lon = float(pt.get("lon"))
                lat = float(pt.get("lat"))
                coords.append([lon, lat])
        if coords:
            yield ("track", name, desc, coords)
    for w in root.findall(f"{GPX_NS}wpt"):
        name = (w.findtext(f"{GPX_NS}name") or "wpt").strip()
        desc = (w.findtext(f"{GPX_NS}desc") or "").strip()
        ele_t = w.findtext(f"{GPX_NS}ele")
        ele = float(ele_t) if ele_t else None
        sym = (w.findtext(f"{GPX_NS}sym") or "").strip()
        yield ("wpt", name, desc, float(w.get("lat")), float(w.get("lon")), ele, sym)


# --- Dedupe helpers ----------------------------------------------------------

def bbox_of_latlon(points):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return (min(lats), min(lons), max(lats), max(lons))


def bboxes_overlap(b1, b2, pad_deg: float = 0.0) -> bool:
    s1, w1, n1, e1 = b1
    s2, w2, n2, e2 = b2
    return not (n1 + pad_deg < s2 or n2 + pad_deg < s1 or e1 + pad_deg < w2 or e2 + pad_deg < w1)


def track_length_m(points) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += haversine_m(points[i-1][0], points[i-1][1], points[i][0], points[i][1])
    return total


def load_existing_features() -> tuple[list[dict], list[dict]]:
    """Return (existing_tracks, existing_markers) collected from caltopo/*.json.

    Each track dict: {map_id, map_title, title, points, bbox, length_m}
    Each marker dict: {map_id, map_title, title, lat, lon, ele}
    """
    tracks, markers = [], []
    if not CALTOPO_DIR.exists():
        return tracks, markers
    for path in sorted(CALTOPO_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        feats = (data.get("state") or {}).get("features", []) or []
        # Map title from CollaborativeMap feature, fallback to file stem
        map_title = path.stem
        for f in feats:
            p = (f or {}).get("properties") or {}
            if p.get("class") == "CollaborativeMap" and p.get("title"):
                map_title = p["title"]
                break
        for f in feats:
            if not isinstance(f, dict):
                continue
            geom = f.get("geometry") or {}
            gt = geom.get("type")
            props = f.get("properties") or {}
            title = props.get("title") or "(untitled)"
            if gt == "LineString":
                pts = [(c[1], c[0]) for c in geom.get("coordinates", []) if isinstance(c, (list, tuple)) and len(c) >= 2]
                if len(pts) < 2:
                    continue
                tracks.append({
                    "map_id": path.stem,
                    "map_title": map_title,
                    "title": title,
                    "points": pts,
                    "bbox": bbox_of_latlon(pts),
                    "length_m": track_length_m(pts),
                })
            elif gt == "Point":
                c = geom.get("coordinates")
                if not c or len(c) < 2:
                    continue
                markers.append({
                    "map_id": path.stem,
                    "map_title": map_title,
                    "title": title,
                    "lat": c[1],
                    "lon": c[0],
                    "ele": c[2] if len(c) >= 3 else None,
                })
    return tracks, markers


def candidate_track_matches_existing(
    cand_pts,           # list[(lat, lon)]
    existing_tracks,    # from load_existing_features()
    point_tol_m: float = 30.0,
    coverage_threshold: float = 0.90,
    length_tol: float = 0.20,
):
    """Return (matched_existing, score) or (None, 0.0)."""
    if len(cand_pts) < 2:
        return None, 0.0
    cand_bbox = bbox_of_latlon(cand_pts)
    cand_len = track_length_m(cand_pts)
    pad = max(point_tol_m / 111000.0, 0.0001)  # convert tol to deg lat (~)

    # Subsample candidate to ~100 points for speed
    step = max(1, len(cand_pts) // 100)
    sample = cand_pts[::step]

    best_match, best_score = None, 0.0
    for ex in existing_tracks:
        if not bboxes_overlap(cand_bbox, ex["bbox"], pad_deg=pad):
            continue
        # Length filter: lengths must be within ±length_tol
        if cand_len > 0 and ex["length_m"] > 0:
            ratio = cand_len / ex["length_m"]
            if ratio < (1 - length_tol) or ratio > 1 + length_tol:
                continue
        # Point coverage: % of sample points with a nearest existing-point within tol
        matched = 0
        for clat, clon in sample:
            for elat, elon in ex["points"]:
                # Quick lat/lon prefilter: skip far points
                if abs(elat - clat) > pad * 2 or abs(elon - clon) > pad * 2:
                    continue
                if haversine_m(clat, clon, elat, elon) <= point_tol_m:
                    matched += 1
                    break
        score = matched / len(sample)
        if score > best_score:
            best_score, best_match = score, ex
        if score >= coverage_threshold:
            return ex, score
    return (best_match, best_score) if best_score >= coverage_threshold else (None, best_score)


def marker_matches_existing(lat, lon, existing_markers, tol_m: float = 25.0):
    for em in existing_markers:
        if haversine_m(lat, lon, em["lat"], em["lon"]) <= tol_m:
            return em
    return None


# --- end dedupe helpers ------------------------------------------------------


def source_label(path: Path) -> str:
    """Group key. e.g. dolores_xxx_caltopo_CVV0.gpx -> 'CalTopo CVV0'."""
    stem = path.stem
    m = re.search(r"_caltopo_([A-Z0-9]+)$", stem)
    if m:
        return f"CalTopo {m.group(1)}"
    # Fallback: anything after the last underscore that looks like an ID
    parts = stem.split("_")
    if len(parts) >= 2:
        return parts[-1]
    return stem


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpx-dir", type=Path, help="Directory containing .gpx files")
    ap.add_argument("--gpx", action="append", type=Path, default=[],
                    help="Specific .gpx file (can repeat)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--new-map", metavar="TITLE", help="Create a new map with this title")
    g.add_argument("--map-id", metavar="ID", help="Append to an existing map")
    ap.add_argument("--sharing", default="URL",
                    choices=["SECRET", "PRIVATE", "URL", "PUBLIC"],
                    help="Sharing mode for newly-created maps (default URL)")
    ap.add_argument("--color", help="Hex color (#RRGGBB) overriding the palette for ALL tracks/markers in this run. Useful when appending a second source to an existing map so it's visually distinct.")
    ap.add_argument("--marker-symbol", default="point", help="CalTopo marker symbol for waypoints in this run (e.g. 'point' for generic, 'peak' for summits). Default 'point'.")
    ap.add_argument("--color-offset", type=int, default=0,
                    help="Skip N colors in the palette before assigning. Use when appending so colors don't collide with prior uploads.")
    ap.add_argument("--vary-colors", action="store_true",
                    help="Cycle the palette per TRACK (not per group) so adjacent tracks are easier to tell apart.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse and group files but don't upload")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="Disable account-wide dedupe (default: ON — skip tracks/markers already in your CalTopo maps)")
    ap.add_argument("--dedupe-point-tol-m", type=float, default=30.0,
                    help="Per-point distance tolerance for track-match detection (default 30m)")
    ap.add_argument("--dedupe-coverage", type=float, default=0.90,
                    help="Fraction of candidate sample points that must match for a track to count as duplicate (default 0.90)")
    ap.add_argument("--dedupe-marker-tol-m", type=float, default=25.0,
                    help="Marker dedupe radius (default 25m)")
    args = ap.parse_args()

    files: list[Path] = []
    if args.gpx_dir:
        files.extend(sorted(args.gpx_dir.glob("*.gpx")))
        # Also include any user-recorded tracks routed here by the
        # peak_checklist phase12 pipeline (and any manually-curated older
        # ones). Same treatment as the public-source tracks; classifier
        # picks them up by filename / _kyle_existing convention.
        kyle_dir = args.gpx_dir / "_kyle_existing"
        if kyle_dir.is_dir():
            files.extend(sorted(kyle_dir.glob("*.gpx")))
            files.extend(sorted(kyle_dir.glob("*.GPX")))
    files.extend(args.gpx)
    # *_drive*.gpx is a PNG-only annotation (the road between camps, drawn black
    # on the overview) — never upload it to CalTopo.
    skipped_drive = [f for f in files if f.stem.endswith("_drive") or "_drive_" in f.stem]
    files = [f for f in files if f not in skipped_drive]
    for f in skipped_drive:
        print(f"  skip (PNG-only drive route): {f.name}")
    if not files:
        sys.exit("No .gpx files specified. Use --gpx-dir or --gpx.")

    # Group files by source label
    grouped: dict[str, list[Path]] = {}
    for f in files:
        grouped.setdefault(source_label(f), []).append(f)

    print(f"Found {len(files)} GPX file(s) in {len(grouped)} group(s):")
    for label, fs in grouped.items():
        print(f"  [{label}] {len(fs)} file(s)")
        for f in fs:
            print(f"      - {f.name}")

    if args.dry_run:
        return

    if not CONFIG_PATH.exists():
        sys.exit(f"Missing {CONFIG_PATH}")

    # Dedupe: load existing features from local caltopo/ dumps
    existing_tracks, existing_markers = ([], [])
    if not args.no_dedupe:
        existing_tracks, existing_markers = load_existing_features()
        print(f"\nDedupe: loaded {len(existing_tracks)} existing track(s) and "
              f"{len(existing_markers)} marker(s) from {CALTOPO_DIR}/*.json")
        print("(Run scripts/fetch_caltopo.py --all first if your local dumps are stale.)")

    # Open or create the target map
    if args.new_map:
        # Mapless session, then openMap('[NEW]') with title.
        session = caltopo_session(None)
        ok = session.openMap("[NEW]", newTitle=args.new_map, newSharing=args.sharing)
        if not ok:
            sys.exit("openMap('[NEW]') failed")
        map_id = session.mapID
        print(f"\nCreated new map: {map_id}  ({args.new_map}, sharing={args.sharing})")
    else:
        session = caltopo_session(args.map_id)
        map_id = args.map_id
        print(f"\nAppending to existing map: {map_id}")

    # Scope dedupe to the TARGET map only. A research map must carry ALL of this
    # report's source tracks even if near-identical tracks live on OTHER maps in
    # the account — account-wide dedupe silently dropped the recorded tracks from
    # cimarron_six's map, leaving only the recommended route (Kyle, 2026-06-16).
    # For a --new-map the target isn't in the dumps yet → nothing to dedupe (right,
    # the map is empty); for an append it stays idempotent against its own contents.
    if not args.no_dedupe and (existing_tracks or existing_markers):
        bt, bm = len(existing_tracks), len(existing_markers)
        existing_tracks = [t for t in existing_tracks if t["map_id"] == map_id]
        existing_markers = [m for m in existing_markers if m["map_id"] == map_id]
        print(f"Dedupe scoped to target map {map_id}: {len(existing_tracks)} track(s), "
              f"{len(existing_markers)} marker(s) (was {bt}/{bm} account-wide).")

    # Add a folder per source group, then features inside
    track_count = wpt_count = skipped_tracks = skipped_markers = 0
    track_color_idx = 0  # for --vary-colors
    folder_id_cache: dict[str, str | None] = {}

    def get_folder_id(label: str):
        if label in folder_id_cache:
            return folder_id_cache[label]
        try:
            fid = session.addFolder(label=label)
        except Exception as e:
            print(f"  WARN: addFolder({label!r}) failed: {e}; uploading without folder")
            fid = None
        folder_id_cache[label] = fid
        return fid

    for i, (label, fs) in enumerate(grouped.items()):
        if args.color:
            color = args.color
        else:
            color = track_color(i + args.color_offset)   # group color (markers)

        for f in fs:
            for entry in parse_gpx(f):
                kind = entry[0]
                if kind == "track":
                    _, name, desc, coords = entry
                    # Convert to (lat, lon) for dedupe check
                    cand_pts = [(c[1], c[0]) for c in coords]
                    if not args.no_dedupe and existing_tracks:
                        match, score = candidate_track_matches_existing(
                            cand_pts, existing_tracks,
                            point_tol_m=args.dedupe_point_tol_m,
                            coverage_threshold=args.dedupe_coverage,
                        )
                        if match:
                            print(f"    SKIP   {name!r}  -- duplicate of "
                                  f"{match['title']!r} in map {match['map_id']} "
                                  f"({match['map_title']!r}); score={score:.2f}")
                            skipped_tracks += 1
                            continue
                    folder_id = get_folder_id(label)
                    # Every source track gets its OWN distinct color (per-track, not
                    # per-group) so a busy research map with many tracks stays legible.
                    # (Kyle, 2026-07-23 — dropped the source→color convention.)
                    line_color = args.color if args.color else track_color(track_color_idx + args.color_offset)
                    if not args.color and "_kyle_existing" in f.parts:
                        line_color = KYLE_COLOR   # Kyle's own recordings always blue on web maps
                    track_color_idx += 1
                    # Convention: the composed recommended route is ALWAYS magenta
                    # (matches the PNG legend), on every map incl. climber maps —
                    # never a palette color that collides with a source track.
                    if "recommended route" in (name or "").lower():
                        line_color = RECOMMENDED_COLOR
                    try:
                        session.addLine(
                            points=coords,
                            title=name,
                            description=desc or f"From {f.name}",
                            color=line_color,
                            folderId=folder_id,
                        )
                        track_count += 1
                        print(f"    track  ({line_color}) {name}  [{len(coords)} pts]")
                    except Exception as e:
                        print(f"    ERROR addLine {name!r}: {e}")
                elif kind == "wpt":
                    _, name, desc, lat, lon, ele, wsym = entry
                    # Per-waypoint <sym> wins over the run default; trailheads
                    # (sym=hiking) get CalTopo's blue hiker icon.
                    msym = wsym if wsym and wsym != "point" else args.marker_symbol
                    mcolor = "#0066FF" if wsym == "hiking" else color
                    if not args.no_dedupe and existing_markers:
                        m = marker_matches_existing(lat, lon, existing_markers,
                                                    tol_m=args.dedupe_marker_tol_m)
                        if m:
                            print(f"    SKIP   marker {name!r} @ {lat:.5f},{lon:.5f}  "
                                  f"-- existing marker {m['title']!r} within "
                                  f"{args.dedupe_marker_tol_m}m in map {m['map_id']}")
                            skipped_markers += 1
                            continue
                    folder_id = get_folder_id(label)
                    try:
                        session.addMarker(
                            lat=lat,
                            lon=lon,
                            title=name,
                            description=desc or f"From {f.name}",
                            color=mcolor,
                            symbol=msym,
                            folderId=folder_id,
                        )
                        wpt_count += 1
                        print(f"    marker ({color}) {name}  @ {lat:.5f},{lon:.5f}")
                    except Exception as e:
                        print(f"    ERROR addMarker {name!r}: {e}")

    url = f"https://caltopo.com/m/{map_id}"
    print(f"\nUploaded {track_count} track(s) and {wpt_count} marker(s).")
    if skipped_tracks or skipped_markers:
        print(f"Skipped {skipped_tracks} duplicate track(s) and {skipped_markers} duplicate marker(s) (already in your account). Pass --no-dedupe to disable.")
    print(f"View map: {url}")


if __name__ == "__main__":
    main()
