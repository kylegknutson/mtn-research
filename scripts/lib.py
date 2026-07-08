"""
lib.py — shared helper module for scripts/*.py (2026-07 dedup).

Before this module existed the scripts carried ~35 copies of the haversine
formula, 15+ ad-hoc GPX parsers, and 10+ identical CalTopo session inits.
Scripts import it directly (`from lib import haversine_m, trkpt_segs, …`) —
Python puts the script's own directory on sys.path, so this works from any
scripts/*.py regardless of how uv isolates its env. This is a plain stdlib
module: no shebang, no PEP 723 block, and caltopo_python is imported LAZILY
(inside caltopo_session) so scripts without that dependency can still import
lib.

DELIBERATE NON-USERS: the route-GENERATING scripts
(build_recommended_route.py and the builders that wrap it) keep their own
local math so the route output stays bit-identical — check_route_recipe.py
(a gate) FAILs unless a recipe reproduces the committed route, so their
formulas must never drift, even by refactor.
"""
from __future__ import annotations

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX_DIR = ROOT / "gpx"
DOCS_DIR = ROOT / "docs"

GPX_NS = "{http://www.topografix.com/GPX/1/1}"

CONFIG_PATH = Path(__file__).resolve().parent / "cts.ini"
DEFAULT_ACCOUNT = "kyleg.knutson@gmail.com"


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters (R=6371000.0)."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def haversine_ft(lat1, lon1, lat2, lon2):
    return haversine_m(lat1, lon1, lat2, lon2) * 3.28084


def haversine_mi(lat1, lon1, lat2, lon2):
    return haversine_m(lat1, lon1, lat2, lon2) / 1609.344


def trkpt_segs(path: Path) -> list[list[tuple[float, float]]]:
    """Per-<trk> lists of (lat, lon); a file with no <trk> structure falls back
    to all its trkpts as one track. Unparseable file → []."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    out = []
    for trk in root.iter(GPX_NS + "trk"):
        seg = [(float(p.get("lat")), float(p.get("lon"))) for p in trk.iter(GPX_NS + "trkpt")]
        if len(seg) >= 2:
            out.append(seg)
    if not out:   # no <trk> structure — treat all points as one track
        pts = [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(GPX_NS + "trkpt")]
        if len(pts) >= 2:
            out.append(pts)
    return out


def trkpts_flat(path: Path) -> list[tuple[float, float]]:
    """Flat list of every trkpt (lat, lon) in the file. Unparseable file → []."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(GPX_NS + "trkpt")]


def wpts(path: Path) -> list[dict]:
    """Waypoints as {lat, lon, name, sym} dicts. Unparseable file → []."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    out = []
    for w in root.iter(GPX_NS + "wpt"):
        out.append({
            "lat": float(w.get("lat")),
            "lon": float(w.get("lon")),
            "name": (w.findtext(GPX_NS + "name") or "").strip(),
            "sym": (w.findtext(GPX_NS + "sym") or "").strip(),
        })
    return out


def caltopo_session(map_id: str | None = None, account: str = DEFAULT_ACCOUNT):
    """Create a CaltopoSession. map_id can be None for a "mapless" session
    (used when listing maps or browsing accounts/folders).

    caltopo_python is imported lazily so scripts that never touch CalTopo can
    import lib without carrying the dependency."""
    from caltopo_python import CaltopoSession  # lazy — see module docstring

    if not CONFIG_PATH.exists():
        sys.exit(
            f"ERROR: {CONFIG_PATH} not found.\n"
            f"Copy cts.ini.template to cts.ini and fill in your credentials."
        )
    return CaltopoSession(
        domainAndPort="caltopo.com",
        mapID=map_id,  # None == mapless session, allowed
        configpath=str(CONFIG_PATH),
        account=account,
    )
