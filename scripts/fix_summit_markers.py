#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""
fix_summit_markers.py — ensure a report's CalTopo map has proper summit markers.

gpx_to_caltopo dedupes markers account-wide, so a per-report map's summit markers
get SKIPPED when they already exist in the regional map — leaving the research
map with no summit markers (Kyle, 2026-06-09). This restores them.

Idempotent: deletes any existing marker within ~120 m of an objective summit,
then re-adds one **peak / #39FF14 (neon green)** marker per summit from
gpx/<slug>/<slug>_peaks_only.gpx (via gpx_to_caltopo --no-dedupe).

    scripts/fix_summit_markers.py --slug trinchera_group        # dry-run
    scripts/fix_summit_markers.py --slug trinchera_group --apply
    scripts/fix_summit_markers.py --all --apply                  # every report w/ a caltopo_id
"""
from __future__ import annotations
import argparse, logging, math, re, subprocess, sys
from pathlib import Path
import yaml

logging.basicConfig(level=logging.ERROR)
logging.getLogger("caltopo_python").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
CONFIG = ROOT / "scripts" / "cts.ini"
ACCOUNT = "kyleg.knutson@gmail.com"
SNAP_M = 120.0


def report_path(slug):
    for p in (ROOT / "docs" / "peaks" / f"{slug}.md", ROOT / "docs" / "trips" / f"{slug}.md"):
        if p.exists():
            return p
    return None


def caltopo_id(slug):
    p = report_path(slug)
    if not p:
        return None
    m = re.search(r"caltopo_id:\s*(\S+)", p.read_text())
    return m.group(1).strip() if m else None


def objective_coords(slug):
    """(lat, lon) for objective_ids (peak_db) + extra_summits."""
    cfg = yaml.safe_load((ROOT / "gpx" / slug / "peaks.yml").read_text())
    out = [(e["lat"], e["lon"]) for e in (cfg.get("extra_summits") or [])]
    ids = cfg.get("objective_ids") or []
    if ids:
        sys.path.insert(0, PEAKDB)
        from peak_db_client import peaks
        by = {p["id"]: p for p in peaks()}
        out += [(by[i]["lat"], by[i]["lon"]) for i in ids if i in by and by[i].get("lat")]
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
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if args.all:
        slugs = sorted({p.stem for p in (ROOT/"docs"/"peaks").glob("*.md") if p.stem.count(".") == 0}
                       | {p.stem for p in (ROOT/"docs"/"trips").glob("*.md")})
    else:
        slugs = [args.slug]

    from caltopo_python import CaltopoSession
    for slug in slugs:
        mid = caltopo_id(slug)
        peaks_only = ROOT / "gpx" / slug / f"{slug}_peaks_only.gpx"
        if not mid or not peaks_only.exists():
            continue
        try:
            objs = objective_coords(slug)
        except Exception as e:
            print(f"{slug}: skip ({e})"); continue
        s = CaltopoSession(domainAndPort="caltopo.com", mapID=mid, configpath=str(CONFIG), account=ACCOUNT)
        markers = s.getFeatures(featureClass="Marker")
        near = []
        for mk in markers:
            g = (mk.get("geometry") or {}).get("coordinates") or []
            if len(g) < 2:
                continue
            mlat, mlon = g[1], g[0]
            if any(m_between((mlat, mlon), o) <= SNAP_M for o in objs):
                near.append(mk)
        action = f"delete {len(near)} existing summit-area marker(s), add {len(objs)} peak/green"
        print(f"{slug} ({mid}): {len(objs)} objectives — {action}")
        if not args.apply:
            continue
        for mk in near:
            s.delMarker(mk["id"])
        subprocess.run([str(ROOT/"scripts"/"gpx_to_caltopo.py"), "--gpx", str(peaks_only),
                        "--map-id", mid, "--marker-symbol", "peak", "--color", "#39FF14",
                        "--no-dedupe"], capture_output=True, text=True)
        print(f"  ✓ {slug}: summit markers restored")


if __name__ == "__main__":
    main()
