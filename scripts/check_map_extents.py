#!/usr/bin/env python3
"""
Verify that each overview map's computed bbox covers all in-scope track coordinates.

Replicates the segment-level clip + bbox logic from make_overview_map.py and checks the
invariant: every point of every in-scope segment must lie within the computed bbox. Fails
if any slug has drawn-track points that would be cut off at the canvas edge.

IMPORTANT: The clip constants below must stay in sync with make_overview_map.py.

No external dependencies — pure stdlib.

Usage:
    python scripts/check_map_extents.py              # check all slugs
    python scripts/check_map_extents.py carter_dome_group  # check one slug
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Must match make_overview_map.py
CLIP_MARGIN_MI  = 3.5
CLIP_MAX_LON    = 0.11
CLIP_MAX_LAT    = 0.08
MIN_DISPLAY_LON = 0.035
MIN_DISPLAY_LAT = 0.025
MI_PER_DEG_LON  = 53.0
MI_PER_DEG_LAT  = 69.0
PAD             = 0.04

PEAK_KEYWORDS     = ("peaks_only", "summit")
NON_TRACK_STEMS   = PEAK_KEYWORDS + (
    "trailhead", "_th_", "_th.", "basin th",
    "landmarks", "drive_in", "drive-in", "waypoints",
)

GPX_NS  = "http://www.topografix.com/GPX/1/1"
GPX_DIR = Path(__file__).resolve().parent.parent / "gpx"


def _ns(tag):
    return f"{{{GPX_NS}}}{tag}"


def parse_tracks(path: Path) -> list[list[tuple[float, float]]]:
    segs: list[list[tuple[float, float]]] = []
    try:
        root = ET.parse(path).getroot()
        for trk in root.iter(_ns("trk")):
            for seg in trk.iter(_ns("trkseg")):
                pts: list[tuple[float, float]] = []
                for pt in seg.iter(_ns("trkpt")):
                    try:
                        pts.append((float(pt.get("lon")), float(pt.get("lat"))))
                    except (TypeError, ValueError):
                        pass
                if len(pts) >= 2:
                    segs.append(pts)
    except ET.ParseError:
        pass
    return segs


def parse_peak_waypoints(path: Path) -> list[tuple[float, float]]:
    wpts: list[tuple[float, float]] = []
    try:
        root = ET.parse(path).getroot()
        for wpt in root.iter(_ns("wpt")):
            try:
                wpts.append((float(wpt.get("lon")), float(wpt.get("lat"))))
            except (TypeError, ValueError):
                pass
    except ET.ParseError:
        pass
    return wpts


def is_peak_file(path: Path) -> bool:
    stem = path.stem.lower()
    return any(kw in stem for kw in PEAK_KEYWORDS)


def is_track_file(path: Path) -> bool:
    stem = path.stem.lower()
    return not any(kw in stem for kw in NON_TRACK_STEMS)


def check_slug(slug_dir: Path) -> list[str]:
    """Returns a list of error strings; empty means OK."""
    slug = slug_dir.name
    all_segs: list[list[tuple[float, float]]] = []
    peak_lons: list[float] = []
    peak_lats: list[float] = []

    search_dirs = [slug_dir, slug_dir / "_kyle_existing"]
    for d in search_dirs:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.gpx")):
            if is_peak_file(f):
                for lon, lat in parse_peak_waypoints(f):
                    peak_lons.append(lon)
                    peak_lats.append(lat)
            elif is_track_file(f):
                for seg in parse_tracks(f):
                    all_segs.append(seg)

    if not all_segs:
        return []

    # Replicate make_overview_map.py segment-level clip + bbox exactly.
    if peak_lons:
        pk_lon_c = (min(peak_lons) + max(peak_lons)) / 2
        pk_lat_c = (min(peak_lats) + max(peak_lats)) / 2
        clip_lon = min(CLIP_MAX_LON,
                       (max(peak_lons) - min(peak_lons)) / 2 + CLIP_MARGIN_MI / MI_PER_DEG_LON)
        clip_lat = min(CLIP_MAX_LAT,
                       (max(peak_lats) - min(peak_lats)) / 2 + CLIP_MARGIN_MI / MI_PER_DEG_LAT)

        def in_scope(seg: list[tuple[float, float]]) -> bool:
            n = len(seg)
            c_lon = sum(lon for lon, _ in seg) / n
            c_lat = sum(lat for _, lat in seg) / n
            return abs(c_lon - pk_lon_c) <= clip_lon and abs(c_lat - pk_lat_c) <= clip_lat

        in_scope_segs = [s for s in all_segs if in_scope(s)]
        if not in_scope_segs:
            return []

        bbox_lons: list[float] = (
            list(peak_lons)
            + [pk_lon_c - MIN_DISPLAY_LON, pk_lon_c + MIN_DISPLAY_LON]
            + [lon for s in in_scope_segs for lon, _ in s]
        )
        bbox_lats: list[float] = (
            list(peak_lats)
            + [pk_lat_c - MIN_DISPLAY_LAT, pk_lat_c + MIN_DISPLAY_LAT]
            + [lat for s in in_scope_segs for _, lat in s]
        )
    else:
        # No peaks: all tracks are in scope, no clip applied
        in_scope_segs = all_segs
        bbox_lons = [lon for s in all_segs for lon, _ in s]
        bbox_lats = [lat for s in all_segs for _, lat in s]

    if len(set(bbox_lons)) < 2 or len(set(bbox_lats)) < 2:
        return []  # degenerate single-point case; skip

    lon_span = max(bbox_lons) - min(bbox_lons)
    lat_span = max(bbox_lats) - min(bbox_lats)
    lon_min  = min(bbox_lons) - lon_span * PAD
    lon_max  = max(bbox_lons) + lon_span * PAD
    lat_min  = min(bbox_lats) - lat_span * PAD
    lat_max  = max(bbox_lats) + lat_span * PAD

    # Invariant: every in-scope track point must be within the bbox.
    TOL = 1e-9
    errors: list[str] = []
    for seg in in_scope_segs:
        outliers = [
            (lon, lat) for lon, lat in seg
            if lon < lon_min - TOL or lon > lon_max + TOL
            or lat < lat_min - TOL or lat > lat_max + TOL
        ]
        if outliers:
            ex_lon, ex_lat = outliers[0]
            errors.append(
                f"{slug}: {len(outliers)} point(s) outside bbox "
                f"lon[{lon_min:.4f}, {lon_max:.4f}] lat[{lat_min:.4f}, {lat_max:.4f}] — "
                f"first outlier ({ex_lon:.4f}, {ex_lat:.4f})"
            )
            break  # one error per slug is enough
    return errors


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        dirs = [GPX_DIR / target]
        if not dirs[0].exists():
            print(f"ERROR: {dirs[0]} not found", file=sys.stderr)
            sys.exit(1)
    else:
        dirs = sorted(d for d in GPX_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))

    all_errors: list[str] = []
    for d in dirs:
        errors = check_slug(d)
        all_errors.extend(errors)
        status = "FAIL" if errors else "OK  "
        print(f"{status}  {d.name}")
        for e in errors:
            print(f"       {e}")

    if all_errors:
        print(f"\n{len(all_errors)} slug(s) failed.", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\nAll {len(dirs)} slug(s) OK.")


if __name__ == "__main__":
    main()
