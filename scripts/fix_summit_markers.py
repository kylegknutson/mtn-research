#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""
fix_summit_markers.py — reconcile a CalTopo map's summit markers to the standard.

THE standard (Kyle, 2026-07-12 — one convention across PNG and CalTopo):
  - objective summits:     peak / #39FF14 (neon green), from <slug>_peaks_only.gpx
  - other named/ranked summits in the PNG frame: peak / #000000 (black), from the
    context_peaks list make_overview_map writes into docs/maps/<slug>.extent.json
    (the PNG build is the single source of "what's in view" — this script never
    recomputes that set).

Idempotent: deletes any existing marker within ~120 m of a target summit, then
re-adds the standard marker. Works on the report's research map by default, or
any map via --map-id (share maps use this).

Origin: gpx_to_caltopo dedupes markers account-wide, so a per-report map's summit
markers got SKIPPED when they already existed in the regional map (2026-06-09).

    scripts/fix_summit_markers.py --slug trinchera_group        # dry-run
    scripts/fix_summit_markers.py --slug trinchera_group --apply
    scripts/fix_summit_markers.py --slug x --map-id ABC123 --apply   # share map
    scripts/fix_summit_markers.py --all --apply                  # every report w/ a caltopo_id
"""
from __future__ import annotations
import argparse, json, logging, math, re, subprocess, sys
from pathlib import Path
import yaml

logging.basicConfig(level=logging.ERROR)
logging.getLogger("caltopo_python").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
CONFIG = ROOT / "scripts" / "cts.ini"
ACCOUNT = "kyleg.knutson@gmail.com"
SNAP_M = 120.0
CTX_COLOR = "#000000"


def report_path(slug):
    """First report for the slug — includes climber reports (<slug>.<climber>.md)."""
    for sub in ("peaks", "trips"):
        hits = sorted((ROOT / "docs" / sub).glob(f"{slug}*.md"))
        if hits:
            return hits[0]
    return None


def caltopo_id(slug):
    p = report_path(slug)
    if not p:
        return None
    m = re.search(r"caltopo_id:\s*(\S+)", p.read_text())
    return m.group(1).strip() if m else None


def objective_coords(slug):
    """(lat, lon) for objective_ids + pass_over_summits (both peak_db ids)."""
    cfg = yaml.safe_load((ROOT / "gpx" / slug / "peaks.yml").read_text())
    ids = (cfg.get("objective_ids") or []) + (cfg.get("pass_over_summits") or [])
    out = []
    if ids:
        sys.path.insert(0, PEAKDB)
        from peak_db_client import peaks
        by = {p["id"]: p for p in peaks()}
        out = [(by[i]["lat"], by[i]["lon"]) for i in ids if i in by and by[i].get("lat")]
    return out


CONTEXT_MARGIN_MI = 4.0   # CalTopo shows ranked neighbors this far BEYOND the PNG
                          # frame (Kyle, 2026-07-12: "a larger area to see more of
                          # what's around" — the interactive map can zoom, so more
                          # context is useful there; the PNG stays tight/uncluttered).


def context_peaks(slug, margin_mi=CONTEXT_MARGIN_MI):
    """Non-objective ranked summits to mark black on CalTopo. Starts from the PNG's
    frame (extent sidecar) and EXPANDS the bbox by margin_mi so the interactive map
    carries more surrounding context than the tight PNG. Falls back to the sidecar's
    frame-set if peak_db is unavailable."""
    sidecar = ROOT / "docs" / "maps" / f"{slug}.extent.json"
    if not sidecar.exists():
        return []
    ext = json.loads(sidecar.read_text())
    lo0, lo1 = ext.get("lon_min"), ext.get("lon_max")
    la0, la1 = ext.get("lat_min"), ext.get("lat_max")
    if None in (lo0, lo1, la0, la1):
        return ext.get("context_peaks") or []
    dlat = margin_mi / 69.0
    dlon = margin_mi / (69.0 * max(math.cos(math.radians((la0 + la1) / 2)), 0.1))
    lo0, lo1, la0, la1 = lo0 - dlon, lo1 + dlon, la0 - dlat, la1 + dlat
    try:
        sys.path.insert(0, PEAKDB)
        from peak_db_client import peaks
    except Exception:
        return ext.get("context_peaks") or []   # fallback: tight PNG set
    objs = objective_coords(slug)
    out = []
    for p in peaks():
        if not p.get("ranked"):
            continue
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        if not (lo0 <= lon <= lo1 and la0 <= lat <= la1):
            continue
        if any(m_between((lat, lon), o) <= 200 for o in objs):
            continue   # this is an objective (drawn green) — skip
        out.append({"name": p.get("display_name") or "", "lat": lat, "lon": lon})
    return out


def m_between(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((lo2-lo1)/2)**2
    return 2*R*math.asin(math.sqrt(h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--map-id", help="target map override (default: the report's caltopo_id); use for share maps")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.all:
        slugs = sorted({p.stem.split(".")[0] for p in (ROOT/"docs"/"peaks").glob("*.md")
                        if not p.stem.startswith("index")}
                       | {p.stem.split(".")[0] for p in (ROOT/"docs"/"trips").glob("*.md")
                          if not p.stem.startswith("index")})
    else:
        slugs = [args.slug]

    from caltopo_python import CaltopoSession
    for slug in slugs:
        mid = args.map_id or caltopo_id(slug)
        peaks_only = ROOT / "gpx" / slug / f"{slug}_peaks_only.gpx"
        if not mid or not peaks_only.exists():
            continue
        try:
            objs = objective_coords(slug)
        except Exception as e:
            print(f"{slug}: skip ({e})"); continue
        ctx = context_peaks(slug)
        targets = objs + [(c["lat"], c["lon"]) for c in ctx]
        s = CaltopoSession(domainAndPort="caltopo.com", mapID=mid, configpath=str(CONFIG), account=ACCOUNT)
        markers = s.getFeatures(featureClass="Marker")
        near = []
        for mk in markers:
            g = (mk.get("geometry") or {}).get("coordinates") or []
            if len(g) < 2:
                continue
            mlat, mlon = g[1], g[0]
            if any(m_between((mlat, mlon), t) <= SNAP_M for t in targets):
                near.append(mk)
        print(f"{slug} ({mid}): delete {len(near)} existing summit-area marker(s), "
              f"add {len(objs)} peak/green + {len(ctx)} peak/black context")
        if not args.apply:
            continue
        for mk in near:
            s.delMarker(mk["id"])
        subprocess.run([str(ROOT/"scripts"/"gpx_to_caltopo.py"), "--gpx", str(peaks_only),
                        "--map-id", mid, "--marker-symbol", "peak", "--color", "#39FF14",
                        "--no-dedupe"], capture_output=True, text=True)
        for c in ctx:
            try:
                s.addMarker(lat=c["lat"], lon=c["lon"], title=c.get("name") or "",
                            description="Nearby ranked summit (not an objective)",
                            color=CTX_COLOR, symbol="peak")
            except Exception as e:
                print(f"  ERROR context marker {c.get('name')!r}: {e}")
        print(f"  ✓ {slug}: summit markers reconciled")


if __name__ == "__main__":
    main()
