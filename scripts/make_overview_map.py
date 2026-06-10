#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests",
#   "mercantile",
#   "Pillow",
#   "pyproj",
#   "PyYAML",
# ]
# ///
"""
make_overview_map.py — generate a static PNG overview map for a research peak.

Uses Pillow + direct OpenTopoMap tile fetching (no matplotlib/contextily).

Runs via uv (PEP 723 inline deps) — no venv to manage. Install once per Mac:
  brew install uv

Usage:
  scripts/make_overview_map.py brown_mountain
  scripts/make_overview_map.py dolores_peak --title "Dolores Peak + Middle Peak"
  scripts/make_overview_map.py telluride_t7_t8 --zoom 12
  # equivalent: uv run scripts/make_overview_map.py brown_mountain

Output: maps/{slug}.png (or --out path)

Color scheme matches CalTopo research maps:
  Red    (#CC3333) : LoJ trip reports (*_loj*.gpx) / unclassified
  Green  (#00AA00) : 14ers.com tracks (*_14ers*.gpx)
  Blue   (#0066FF) : Peakbagger ascents (*_pbAscent*.gpx)
  Purple (#9933CC) : Kyle's personal GPS (*_caltopo_*.gpx)
  Gold   (#FFCC00) : peak summit waypoints (*peaks_only*, *summit*)
  Orange (#FF6600) : trailheads
  Purple (#9933CC) : drive-in / approach waypoints (*landmarks*, *drive_in*)
  Magenta(#E6008C) : composed "recommended" route (*recommended*) — bold cased
                     line on top, the shortest path through the ranked objectives
                     pieced from real source tracks (build_recommended_route.py)
"""

import argparse
import io
import math
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import mercantile
import yaml
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer

PEAKDB_PATH = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"

# ── constants ────────────────────────────────────────────────────────────────
GPX_NS_URI = "http://www.topografix.com/GPX/1/1"


def objective_summits(slug):
    """(lon, lat) of the report's OBJECTIVE summits (peaks.yml objective_ids →
    peak_db). Used to keep only tracks that actually SUMMIT a researched peak.
    Returns None if it can't be determined (caller falls back to a looser clip)."""
    try:
        cfg = yaml.safe_load((Path(__file__).parent.parent / "gpx" / slug / "peaks.yml").read_text())
        ids = cfg.get("objective_ids") or []
        extra = cfg.get("extra_summits") or []
        if not ids and not extra:
            return None
        out = [(e["lon"], e["lat"]) for e in extra]   # non-peak_db summits
        if ids:
            if PEAKDB_PATH not in sys.path:
                sys.path.insert(0, PEAKDB_PATH)
            from peak_db_client import peaks as _peaks
            by = {p["id"]: p for p in _peaks()}
            out += [(by[i]["lon"], by[i]["lat"]) for i in ids if i in by]
        return out or None
    except Exception:
        return None


def ranked_summits_in_view(lon_min, lon_max, lat_min, lat_max, exclude_coords):
    """Every RANKED peak_db summit whose coords fall inside the view bbox, minus
    the objective summits (already drawn gold). Returns [(lon, lat, name), …].

    Used to label *context* summits — the other ranked 13ers/14ers visible in the
    frame — so the PNG matches the CalTopo regional maps (which carry every ranked
    summit). Queried AFTER the bbox is fixed, so these never expand the frame."""
    try:
        if PEAKDB_PATH not in sys.path:
            sys.path.insert(0, PEAKDB_PATH)
        from peak_db_client import peaks as _peaks
    except Exception:
        return []
    out = []
    for p in _peaks():
        if not p.get("ranked"):
            continue
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        if not (lon_min <= lon <= lon_max and lat_min <= lat <= lat_max):
            continue
        if any(abs(lon - ol) < 1e-3 and abs(lat - ola) < 1e-3 for ol, ola in exclude_coords):
            continue   # this is an objective — already drawn gold
        out.append((lon, lat, p.get("display_name") or ""))
    return out

COLOR_PUBLIC   = (204, 51,  51,  220)   # red (fallback / unclassified public)
COLOR_KYLE     = (0,   102, 255, 180)   # blue

# Source-colored tracks (match the CalTopo research-map scheme).
SOURCE_COLORS = {
    "loj":     (204, 51,  51,  220),   # LoJ        — red    #CC3333
    "14ers":   (0,   170, 0,   220),   # 14ers      — green  #00AA00
    "pb":      (0,   102, 255, 220),   # peakbagger — blue   #0066FF
    "caltopo": (153, 51,  204, 220),   # personal   — purple #9933CC
    "public":  (204, 51,  51,  220),   # unclassified — red
}
SOURCE_LABELS = {
    "loj": "LoJ", "14ers": "14ers", "pb": "Peakbagger",
    "caltopo": "Kyle's GPS", "public": "Public",
}


def track_source(path) -> str:
    """Classify a GPX file by source from its filename suffix."""
    n = path.name.lower()
    if "pbascent" in n:
        return "pb"
    if "_caltopo_" in n:
        return "caltopo"
    if "14ers" in n or "_unknown_" in n:
        return "14ers"
    if "loj" in n:
        return "loj"
    return "public"
COLOR_PEAK     = (255, 204, 0,   255)   # gold — objective summit(s)
COLOR_PEAK_CTX = (190, 190, 190, 255)   # silver-gray — other ranked summits in view
COLOR_DRIVE_IN = (153, 51,  204, 220)   # purple
COLOR_TH       = (255, 102, 0,   220)   # orange
COLOR_DRIVE    = (0,   0,   0,   235)   # black — the driving route between camps
                                        # (reserved: not used on the CalTopo map, so
                                        #  it reads as "road", not a GPS track)
# Composed "recommended" route — pieced together from real source tracks but
# narrowed to the report's ranked objectives (build_recommended_route.py). Drawn
# on top of everything as a bold cased magenta line so it's unmistakable as the
# synthesized recommendation, distinct from any single raw source track.
COLOR_RECOMMENDED      = (230, 0,   140, 255)   # bold magenta core
COLOR_RECOMMENDED_CASE = (25,  0,   15,  255)   # near-black casing for contrast
COLOR_BG       = (232, 224, 213)        # warm beige fallback

TILE_SIZE   = 256    # px per OSM tile
IMG_W_PX    = 1200   # output width in pixels
IMG_H_PX    = 960    # output height in pixels
TILE_TIMEOUT = 8     # seconds per tile request
MAX_TILES   = 64     # safety cap — abort basemap if needed

BASE_DIR  = Path(__file__).parent.parent
GPX_ROOT  = BASE_DIR / "gpx"
MAPS_DIR  = BASE_DIR / "docs" / "maps"   # under docs/ so MkDocs picks it up
MAPS_DIR.mkdir(parents=True, exist_ok=True)

PEAK_KEYWORDS    = ("peaks_only", "summit")
TH_KEYWORDS      = ("trailhead", "_th_", "_th.", "basin th")
DRIVE_IN_KEYWORDS = ("landmarks", "drive_in", "drive-in")

# ── GPX parsing ───────────────────────────────────────────────────────────────

def _ns(tag): return f"{{{GPX_NS_URI}}}{tag}"

def parse_tracks(gpx_path: Path) -> list[list[tuple[float, float]]]:
    try:
        root = ET.parse(gpx_path).getroot()
    except ET.ParseError:
        return []
    segs = []
    for trk in root.iter(_ns("trk")):
        for seg in trk.iter(_ns("trkseg")):
            pts = []
            for pt in seg.iter(_ns("trkpt")):
                try:
                    pts.append((float(pt.get("lon")), float(pt.get("lat"))))
                except (TypeError, ValueError):
                    continue
            if len(pts) >= 2:
                segs.append(pts)
    return segs

def parse_waypoints(gpx_path: Path) -> list[tuple[float, float, str]]:
    try:
        root = ET.parse(gpx_path).getroot()
    except ET.ParseError:
        return []
    wpts = []
    for wpt in root.iter(_ns("wpt")):
        try:
            lon, lat = float(wpt.get("lon")), float(wpt.get("lat"))
        except (TypeError, ValueError):
            continue
        name_el = wpt.find(_ns("name"))
        name = (name_el.text or "").strip() if name_el is not None else ""
        wpts.append((lon, lat, name))
    return wpts

def classify_file(path: Path, is_kyle: bool) -> str:
    stem = path.stem.lower()
    if stem.endswith("_drive") or "_drive_" in stem:
        return "drive_route"      # the road connecting camps (multi-day) — PNG only
    if "recommended" in stem:
        return "recommended"      # composed shortest route through the objectives
    if "peaks_only" in stem or "summit" in stem:
        return "peak"
    if any(k in stem for k in TH_KEYWORDS):
        return "th"
    if any(k in stem for k in DRIVE_IN_KEYWORDS):
        return "drive_in"
    if "waypoints" in stem:
        return "mixed_wpt"
    return "track_kyle" if is_kyle else "track_public"

def classify_waypoint_by_name(name: str) -> str:
    n = name.lower()
    if any(t in n for t in ("trailhead", " th)", "parking", "pullout", "mine th", "basin th")):
        return "th"
    if any(t in n for t in ("pass", "junction", "jct", "road jct", "saddle", "col", "drive-in")):
        return "drive_in"
    return "peak"


# ── projection helpers ────────────────────────────────────────────────────────

_WGS84_TO_WM = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

def lonlat_to_px(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """WGS84 lon/lat → pixel coordinates in the global tile grid at given zoom."""
    n = 2 ** zoom
    x_tile = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y_tile = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x_tile * TILE_SIZE, y_tile * TILE_SIZE

def px_to_img(px: float, py: float,
              origin_px: float, origin_py: float,
              scale_x: float, scale_y: float,
              img_h: int) -> tuple[int, int]:
    """Global tile-pixel → image pixel.

    Both coordinate systems have y=0 at top, y increasing downward (north → south),
    so NO flip is needed. (The img_h parameter is retained for call-site stability.)
    """
    ix = (px - origin_px) * scale_x
    iy = (py - origin_py) * scale_y
    return int(round(ix)), int(round(iy))


# ── tile fetching ─────────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "mtn-research-map/1.0 (personal research tool)"

def fetch_tile(x: int, y: int, z: int) -> Image.Image | None:
    url = f"https://a.tile.opentopomap.org/{z}/{x}/{y}.png"
    try:
        r = SESSION.get(url, timeout=TILE_TIMEOUT)
        if r.status_code == 200:
            return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        print(f"  tile {z}/{x}/{y}: {e}", file=sys.stderr)
    return None

def build_basemap(lon_min, lon_max, lat_min, lat_max, zoom) -> tuple[Image.Image, float, float, float]:
    """
    Download + stitch tiles for the bounding box.
    Returns (basemap_image, origin_px_x, origin_px_y, scale_px_per_world_px).
    The scale is 1.0 — world-px and image-px are the same.
    """
    tiles = list(mercantile.tiles(lon_min, lat_min, lon_max, lat_max, zooms=zoom))
    if len(tiles) > MAX_TILES:
        print(f"Warning: {len(tiles)} tiles at zoom={zoom}, truncating to {MAX_TILES}", file=sys.stderr)
        tiles = tiles[:MAX_TILES]

    print(f"Fetching {len(tiles)} tiles at zoom={zoom}…", flush=True)

    xs, ys = [t.x for t in tiles], [t.y for t in tiles]
    min_tx, max_tx = min(xs), max(xs)
    min_ty, max_ty = min(ys), max(ys)

    canvas_w = (max_tx - min_tx + 1) * TILE_SIZE
    canvas_h = (max_ty - min_ty + 1) * TILE_SIZE
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (*COLOR_BG, 255))

    for i, tile in enumerate(tiles):
        img_t = fetch_tile(tile.x, tile.y, zoom)
        if img_t:
            ix = (tile.x - min_tx) * TILE_SIZE
            iy = (tile.y - min_ty) * TILE_SIZE
            canvas.paste(img_t, (ix, iy))
        if (i + 1) % 4 == 0 or i == len(tiles) - 1:
            print(f"  {i+1}/{len(tiles)} tiles done", flush=True)

    # origin in global pixel space
    origin_px = min_tx * TILE_SIZE
    origin_py = min_ty * TILE_SIZE
    return canvas, origin_px, origin_py


# ── drawing ───────────────────────────────────────────────────────────────────

def draw_track(draw: ImageDraw.ImageDraw, seg: list[tuple[float, float]],
               color: tuple, lw: int,
               origin_px, origin_py, scale_x, scale_y, img_h, zoom,
               dashed=False):
    # Convert to image pixels — clamp to a generous range to avoid overflow
    pts_img = []
    for lon, lat in seg:
        px, py = lonlat_to_px(lon, lat, zoom)
        ix, iy = px_to_img(px, py, origin_px, origin_py, scale_x, scale_y, img_h)
        # Skip points absurdly far off canvas (> 5× image size) to avoid huge dist values
        if -5 * img_h < ix < 6 * img_h and -5 * img_h < iy < 6 * img_h:
            pts_img.append((ix, iy))
    if len(pts_img) < 2:
        return
    if dashed:
        # Fast dashed: draw every other batch of N consecutive points
        DASH_PTS = 12   # draw 12 consecutive point-pairs, skip 6
        GAP_PTS  = 6
        cycle = DASH_PTS + GAP_PTS
        for i in range(len(pts_img) - 1):
            if (i % cycle) < DASH_PTS:
                draw.line([pts_img[i], pts_img[i + 1]], fill=color, width=lw)
    else:
        draw.line(pts_img, fill=color, width=lw)

def draw_star(draw: ImageDraw.ImageDraw, ix: int, iy: int, size: int, color: tuple, outline=(0,0,0,255)):
    """Draw a 5-pointed star centred at (ix, iy)."""
    pts = []
    for i in range(10):
        angle = math.radians(-90 + i * 36)
        r = size if i % 2 == 0 else size * 0.4
        pts.append((ix + r * math.cos(angle), iy + r * math.sin(angle)))
    draw.polygon(pts, fill=color, outline=outline)

def draw_triangle(draw: ImageDraw.ImageDraw, ix: int, iy: int, size: int, color: tuple):
    h = int(size * 1.2)
    pts = [(ix, iy - h), (ix - size, iy + size // 2), (ix + size, iy + size // 2)]
    draw.polygon(pts, fill=color, outline=(0, 0, 0, 255))

def draw_square(draw: ImageDraw.ImageDraw, ix: int, iy: int, size: int, color: tuple):
    draw.rectangle([ix - size, iy - size, ix + size, iy + size],
                   fill=color, outline=(0, 0, 0, 255))

def draw_label(draw: ImageDraw.ImageDraw, ix: int, iy: int, text: str, font):
    label = text.split("(")[0].strip()[:26]
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = ix + 5, iy - th // 2
    # white backing
    draw.rectangle([tx - 2, ty - 1, tx + tw + 2, ty + th + 1],
                   fill=(255, 255, 255, 190))
    draw.text((tx, ty), label, fill=(20, 20, 20, 255), font=font)


# ── legend ────────────────────────────────────────────────────────────────────

def draw_legend(img: Image.Image, public_sources, has_kyle, has_peak, has_drive_in, has_th, font, has_drive_route=False, has_context_peak=False, has_recommended=False):
    items = []
    if has_recommended: items.append(("Recommended route (composed)", COLOR_RECOMMENDED[:3]))
    for src in (public_sources or []):
        items.append((f"{SOURCE_LABELS.get(src, src)} routes", SOURCE_COLORS.get(src, COLOR_PUBLIC)[:3]))
    if has_kyle:    items.append(("Imported tracks (Kyle)", COLOR_KYLE[:3]))
    if has_drive_route: items.append(("Driving route (road)",  COLOR_DRIVE[:3]))
    if has_peak:    items.append(("Objective summit ★",      COLOR_PEAK[:3]))
    if has_context_peak: items.append(("Other ranked summit ★", COLOR_PEAK_CTX[:3]))
    if has_drive_in:items.append(("Drive-in / landmark ▲", COLOR_DRIVE_IN[:3]))
    if has_th:      items.append(("Trailhead ■",            COLOR_TH[:3]))
    if not items:   return

    pad = 8
    lh = 18
    box_w = 220
    box_h = pad * 2 + len(items) * lh
    legend = Image.new("RGBA", (box_w, box_h), (255, 255, 255, 210))
    d = ImageDraw.Draw(legend)
    for i, (label, color) in enumerate(items):
        y = pad + i * lh
        d.rectangle([pad, y + 4, pad + 12, y + 12], fill=color + (255,))
        d.text((pad + 16, y), label, fill=(20, 20, 20, 255), font=font)

    margin = 10
    img.paste(legend, (margin, img.height - box_h - margin), legend)


# ── main ──────────────────────────────────────────────────────────────────────

def build_map(slug: str, out_path: Path, zoom: int | None = None, title: str = "",
              context_summits: bool = True):
    gpx_dir  = GPX_ROOT / slug
    kyle_dir = gpx_dir / "_kyle_existing"

    if not gpx_dir.exists():
        print(f"ERROR: GPX dir not found: {gpx_dir}", file=sys.stderr)
        sys.exit(1)

    public_files = list(gpx_dir.glob("*.gpx"))
    kyle_files   = list(kyle_dir.glob("*.gpx")) if kyle_dir.exists() else []

    buckets = {"track_public": [], "track_kyle": [], "peak": [], "context_peak": [], "drive_in": [], "th": [], "drive_route": [], "recommended": []}
    all_lons, all_lats = [], []
    track_lons, track_lats = [], []   # tracks only — preferred bbox driver when present
    peak_lons, peak_lats = [], []     # peak markers — fallback bbox driver when no tracks

    def _ingest(path, is_kyle):
        kind = classify_file(path, is_kyle)
        if kind == "drive_route":
            # Drawn (clipped to frame by PIL) but NOT a bbox driver — the road
            # loops far through valleys; letting it set the extent would blow the
            # frame. The peak markers define the extent; this just overlays on it.
            buckets["drive_route"].extend(parse_tracks(path))
            return
        if kind == "recommended":
            segs = parse_tracks(path)
            buckets["recommended"].extend(segs)
            for seg in segs:
                for lon, lat in seg:
                    all_lons.append(lon); all_lats.append(lat)
                    track_lons.append(lon); track_lats.append(lat)
            return
        if kind.startswith("track"):
            segs = parse_tracks(path)
            if kind == "track_public":
                src = track_source(path)
                buckets["track_public"].extend((seg, src) for seg in segs)
            else:
                buckets[kind].extend(segs)
            for seg in segs:
                for lon, lat in seg:
                    all_lons.append(lon); all_lats.append(lat)
                    track_lons.append(lon); track_lats.append(lat)
        elif kind == "mixed_wpt":
            for lon, lat, name in parse_waypoints(path):
                wkind = classify_waypoint_by_name(name)
                buckets[wkind].append((lon, lat, name))
                all_lons.append(lon); all_lats.append(lat)
                if wkind == "peak":
                    peak_lons.append(lon); peak_lats.append(lat)
        else:
            for lon, lat, name in parse_waypoints(path):
                buckets[kind].append((lon, lat, name))
                all_lons.append(lon); all_lats.append(lat)
                if kind == "peak":
                    peak_lons.append(lon); peak_lats.append(lat)

    for f in public_files: _ingest(f, False)
    for f in kyle_files:   _ingest(f, True)

    if not all_lons:
        print(f"ERROR: no coordinates found in {gpx_dir}", file=sys.stderr)
        sys.exit(1)

    # ── segment-level clip + bbox ─────────────────────────────────────────────
    # A segment is "in scope" if its centroid is within CLIP_MARGIN_MI of the
    # objective cluster. In-scope segments contribute ALL their points to the
    # bbox and are the only segments drawn. This prevents the split where a
    # segment's far-end points are clipped from the bbox but still drawn,
    # causing visible cut-offs at the canvas edge.
    #
    # Out-of-scope segments (a peak as a minor add to a far-away range day,
    # a mega-traverse, a sub-13k outback) are dropped from both bbox and drawing.
    #
    # CLIP_MARGIN_MI: centroid must be within this distance of the objective box.
    # CLIP_MAX_*: fallback hard cap for very spread-out peak clusters.
    # MIN_DISPLAY_*: floor so a single-waypoint-only map stays usable.
    CLIP_MARGIN_MI  = 3.5
    CLIP_MAX_LON    = 0.11
    CLIP_MAX_LAT    = 0.08
    MIN_DISPLAY_LON = 0.035   # ~1.9 mi floor
    MIN_DISPLAY_LAT = 0.025   # ~1.7 mi floor
    MI_PER_DEG_LON  = 53.0    # ~at 38°N; close enough for a centroid check
    MI_PER_DEG_LAT  = 69.0

    if peak_lons:
        pk_lon_c = (min(peak_lons) + max(peak_lons)) / 2
        pk_lat_c = (min(peak_lats) + max(peak_lats)) / 2
        peaks_ll = list(zip(peak_lons, peak_lats))

        # A track belongs on the map ONLY if it actually SUMMITS a researched
        # (objective) peak — a track that merely passes nearby is not route beta
        # (Kyle, 2026-06-08). Objectives come from peaks.yml objective_ids
        # (authoritative), so neighbor-peak markers don't qualify a track.
        obj = objective_summits(slug)
        if obj:
            SUMMIT_TOL_MI = 0.5    # within ~½ mi of a researched summit counts (Kyle, 2026-06-08)
            def _seg_in_scope(seg):
                for lon, lat in seg:
                    for olon, olat in obj:
                        if abs(lon - olon) * MI_PER_DEG_LON <= SUMMIT_TOL_MI \
                           and abs(lat - olat) * MI_PER_DEG_LAT <= SUMMIT_TOL_MI:
                            return True
                return False
        else:
            # Fallback (no objective_ids available): keep tracks whose centroid
            # is within 5 mi of the nearest peak marker.
            CLIP_NEAR_MI = 5.0
            def _seg_in_scope(seg):
                n = len(seg)
                c_lon = sum(lon for lon, _ in seg) / n
                c_lat = sum(lat for _, lat in seg) / n
                return any(abs(c_lon - plon) * MI_PER_DEG_LON <= CLIP_NEAR_MI
                           and abs(c_lat - plat) * MI_PER_DEG_LAT <= CLIP_NEAR_MI
                           for plon, plat in peaks_ll)

        # Filter drawing buckets in-place — only in-scope segments are drawn
        # and only their points contribute to the bbox.
        buckets["track_public"] = [(s, src) for s, src in buckets["track_public"] if _seg_in_scope(s)]
        buckets["track_kyle"]   = [s        for s        in buckets["track_kyle"]   if _seg_in_scope(s)]
        buckets["recommended"]  = [s        for s        in buckets["recommended"]  if _seg_in_scope(s)]

        bbox_lons = (list(peak_lons)
                     + [pk_lon_c - MIN_DISPLAY_LON, pk_lon_c + MIN_DISPLAY_LON])
        bbox_lats = (list(peak_lats)
                     + [pk_lat_c - MIN_DISPLAY_LAT, pk_lat_c + MIN_DISPLAY_LAT])
        for s, _ in buckets["track_public"]:
            bbox_lons.extend(lon for lon, _ in s)
            bbox_lats.extend(lat for _, lat in s)
        for s in buckets["track_kyle"]:
            bbox_lons.extend(lon for lon, _ in s)
            bbox_lats.extend(lat for _, lat in s)
        for s in buckets["recommended"]:
            bbox_lons.extend(lon for lon, _ in s)
            bbox_lats.extend(lat for _, lat in s)
        _bx, _by = bbox_lons, bbox_lats

    elif track_lons:
        _bx, _by = track_lons, track_lats
    else:
        _bx, _by = all_lons, all_lats

    # Degenerate guard (single point): pad ~3 km each way
    if len(set(_bx)) < 2 or len(set(_by)) < 2:
        center_lon = _bx[0] if _bx else 0
        center_lat = _by[0] if _by else 0
        _bx = [center_lon - 0.04, center_lon + 0.04]
        _by = [center_lat - 0.03, center_lat + 0.03]

    pad = 0.04
    lon_span = max(_bx) - min(_bx)
    lat_span = max(_by) - min(_by)
    lon_min = min(_bx) - lon_span * pad
    lon_max = max(_bx) + lon_span * pad
    lat_min = min(_by) - lat_span * pad
    lat_max = max(_by) + lat_span * pad

    # Context summits: every OTHER ranked 13er/14er inside the (now-fixed) frame,
    # so the PNG matches the CalTopo regional maps. Queried after the bbox so they
    # never expand it — only what's already "in view" gets a marker.
    if context_summits:
        obj_coords = objective_summits(slug) or []
        ctx = ranked_summits_in_view(lon_min, lon_max, lat_min, lat_max, obj_coords)
        # don't double-mark a summit already drawn from peaks_only.gpx (gold)
        obj_pts = {(round(l, 4), round(a, 4)) for l, a, _ in buckets["peak"]}
        for lon, lat, name in ctx:
            if (round(lon, 4), round(lat, 4)) in obj_pts:
                continue
            buckets["context_peak"].append((lon, lat, name))
        if buckets["context_peak"]:
            print(f"Context summits in view: {len(buckets['context_peak'])} ranked")

    # Auto zoom: target ~400 px across the span in the output image
    if zoom is None:
        lon_span_padded = lon_max - lon_min
        if   lon_span_padded > 0.5:  zoom = 11
        elif lon_span_padded > 0.12: zoom = 12
        elif lon_span_padded > 0.08: zoom = 13
        else:                        zoom = 14

    print(f"Extent: lon {lon_min:.4f}–{lon_max:.4f}, lat {lat_min:.4f}–{lat_max:.4f}, zoom={zoom}")

    # ── basemap ──────────────────────────────────────────────────────────────
    try:
        canvas, origin_px, origin_py = build_basemap(lon_min, lon_max, lat_min, lat_max, zoom)
    except Exception as e:
        print(f"Warning: basemap failed ({e}); using blank background", file=sys.stderr)
        canvas = Image.new("RGBA", (IMG_W_PX, IMG_H_PX), (*COLOR_BG, 255))
        origin_px = origin_py = 0

    # Compute pixel coords of our view corners
    px_lo, py_lo = lonlat_to_px(lon_min, lat_max, zoom)  # top-left (lat_max = top)
    px_hi, py_hi = lonlat_to_px(lon_max, lat_min, zoom)  # bottom-right

    # Crop canvas to our view (may be smaller than canvas if tiles go outside)
    ox = origin_px   # canvas origin in global pixel space
    oy = origin_py
    crop_x0 = max(0, int(px_lo - ox))
    crop_y0 = max(0, int(py_lo - oy))
    crop_x1 = min(canvas.width,  int(px_hi - ox) + 1)
    crop_y1 = min(canvas.height, int(py_hi - oy) + 1)
    canvas = canvas.crop((crop_x0, crop_y0, crop_x1, crop_y1))

    # scale to output size
    img = canvas.resize((IMG_W_PX, IMG_H_PX), Image.LANCZOS).convert("RGBA")

    # after crop+resize, origin is the crop corner; scale maps global→image
    origin_px = px_lo   # now px_lo is our new "zero"
    origin_py = py_lo
    scale_x = IMG_W_PX / (px_hi - px_lo)
    scale_y = IMG_H_PX / (py_hi - py_lo)

    draw = ImageDraw.Draw(img, "RGBA")

    # ── draw tracks ─────────────────────────────────────────────────────────
    for seg, src in buckets["track_public"]:
        draw_track(draw, seg, SOURCE_COLORS.get(src, COLOR_PUBLIC), 3, origin_px, origin_py, scale_x, scale_y, IMG_H_PX, zoom)
    for seg in buckets["track_kyle"]:
        draw_track(draw, seg, COLOR_KYLE, 2, origin_px, origin_py, scale_x, scale_y, IMG_H_PX, zoom, dashed=True)
    # driving route between camps — drawn last/on top, black dashed (multi-day)
    for seg in buckets["drive_route"]:
        draw_track(draw, seg, COLOR_DRIVE, 3, origin_px, origin_py, scale_x, scale_y, IMG_H_PX, zoom, dashed=True)
    # composed "recommended" route — bold cased magenta, on top of all source tracks
    for seg in buckets["recommended"]:
        draw_track(draw, seg, COLOR_RECOMMENDED_CASE, 7, origin_px, origin_py, scale_x, scale_y, IMG_H_PX, zoom)
    for seg in buckets["recommended"]:
        draw_track(draw, seg, COLOR_RECOMMENDED, 4, origin_px, origin_py, scale_x, scale_y, IMG_H_PX, zoom)

    # ── load font ────────────────────────────────────────────────────────────
    try:
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
        font_lg = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except Exception:
        font_sm = font_lg = ImageFont.load_default()

    # ── draw markers ─────────────────────────────────────────────────────────
    marker_cfg = {
        "drive_in":     (COLOR_DRIVE_IN, draw_triangle, 7),
        "th":           (COLOR_TH,       draw_square,   6),
        "context_peak": (COLOR_PEAK_CTX, draw_star,     7),
        "peak":         (COLOR_PEAK,     draw_star,     10),
    }
    # In a dense/large frame, labelling every ranked summit makes label soup.
    # Mark them all, but only LABEL the nearest N to the objective; the rest get
    # just a star (Kyle, 2026-06-09).
    MAX_CONTEXT_LABELS = 12
    label_context = set()   # ids (lon,lat) of context summits that get a text label
    if buckets["context_peak"]:
        if buckets["peak"]:
            oc_lon = sum(l for l, _, _ in buckets["peak"]) / len(buckets["peak"])
            oc_lat = sum(a for _, a, _ in buckets["peak"]) / len(buckets["peak"])
        else:
            oc_lon = (lon_min + lon_max) / 2
            oc_lat = (lat_min + lat_max) / 2
        ranked_by_dist = sorted(
            buckets["context_peak"],
            key=lambda t: (t[0] - oc_lon) ** 2 + (t[1] - oc_lat) ** 2)
        for lon, lat, _ in ranked_by_dist[:MAX_CONTEXT_LABELS]:
            label_context.add((lon, lat))

    # context summits first, objective(s) last so the gold star/label sits on top
    for kind in ("drive_in", "th", "context_peak", "peak"):
        color, draw_fn, size = marker_cfg[kind]
        for lon, lat, name in buckets[kind]:
            px, py = lonlat_to_px(lon, lat, zoom)
            ix, iy = px_to_img(px, py, origin_px, origin_py, scale_x, scale_y, IMG_H_PX)
            draw_fn(draw, ix, iy, size, color)
            if name and (kind != "context_peak" or (lon, lat) in label_context):
                font = font_lg if kind == "peak" else font_sm
                draw_label(draw, ix, iy, name, font)

    # ── title ────────────────────────────────────────────────────────────────
    display_title = title or slug.replace("_", " ").title()
    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
    except Exception:
        font_title = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), display_title, font=font_title)
    tw = bbox[2] - bbox[0]
    tx = (IMG_W_PX - tw) // 2
    draw.rectangle([tx - 6, 6, tx + tw + 6, 34], fill=(255, 255, 255, 200))
    draw.text((tx, 8), display_title, fill=(20, 20, 20, 255), font=font_title)

    # ── legend ───────────────────────────────────────────────────────────────
    present_sources = []
    for _seg, src in buckets["track_public"]:
        if src not in present_sources:
            present_sources.append(src)
    draw_legend(img, present_sources, bool(buckets["track_kyle"]),
                bool(buckets["peak"]), bool(buckets["drive_in"]), bool(buckets["th"]), font_sm,
                has_drive_route=bool(buckets["drive_route"]),
                has_context_peak=bool(buckets["context_peak"]),
                has_recommended=bool(buckets["recommended"]))

    # ── attribution ──────────────────────────────────────────────────────────
    attr = "Map tiles © OpenTopoMap (CC-BY-SA) | SRTM"
    draw.text((4, IMG_H_PX - 14), attr, fill=(60, 60, 60, 200), font=font_sm)

    # ── save ─────────────────────────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(str(out_path), format="PNG", optimize=True)
    print(f"Saved: {out_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate static overview map PNG for a peak slug")
    parser.add_argument("slug")
    parser.add_argument("--out",   help="Output path (default: maps/{slug}.png)")
    parser.add_argument("--zoom",  type=int, default=None, help="Override zoom level (default: auto)")
    parser.add_argument("--title", default="", help="Map title")
    parser.add_argument("--no-context-summits", action="store_true",
                        help="don't mark other ranked 13ers/14ers visible in the frame")
    args = parser.parse_args()

    out = Path(args.out) if args.out else MAPS_DIR / f"{args.slug}.png"
    build_map(slug=args.slug, out_path=out, zoom=args.zoom, title=args.title,
              context_summits=not args.no_context_summits)


if __name__ == "__main__":
    main()
