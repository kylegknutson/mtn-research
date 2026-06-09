#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""
prune_caltopo_tracks.py — remove line features from a report's CalTopo map that
do NOT summit one of the report's objective peaks.

A track belongs on a report's map only if it actually tops out on a researched
(objective) peak; bbox-adjacent tracks for *other* peaks are not route beta
(Kyle, 2026-06-08). This cleans maps built before that rule existed.

Only **Shape / LineString** features are considered — markers, folders, and the
objective summit markers are never touched. Objective summits come from
gpx/<slug>/peaks.yml `objective_ids` via peak_db.

Usage:
    scripts/prune_caltopo_tracks.py --slug pt_13155_group            # dry-run
    scripts/prune_caltopo_tracks.py --slug pt_13155_group --apply     # delete
    scripts/prune_caltopo_tracks.py --map-id 07PMBS1 --objective-ids 645,707,726 --apply

Always dry-run first and eyeball the kill list.
"""
from __future__ import annotations
import argparse, logging, re, sys
from pathlib import Path
import yaml

logging.basicConfig(level=logging.ERROR)
for n in ("caltopo_python",):
    logging.getLogger(n).setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
PEAKDB_PATH = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
CONFIG = ROOT / "scripts" / "cts.ini"
ACCOUNT = "kyleg.knutson@gmail.com"
STOL_LAT, STOL_LON = 0.5 / 69.0, 0.5 / 53.0   # ½ mi keeper threshold


def report_caltopo_id(slug: str) -> str | None:
    for p in (ROOT / "docs" / "peaks" / f"{slug}.md", ROOT / "docs" / "trips" / f"{slug}.md"):
        if p.exists():
            m = re.search(r"caltopo_id:\s*(\S+)", p.read_text())
            if m:
                return m.group(1).strip()
    return None


def objective_summits(ids):
    sys.path.insert(0, PEAKDB_PATH)
    from peak_db_client import peaks
    by = {p["id"]: p for p in peaks()}
    return [(by[i]["lat"], by[i]["lon"]) for i in ids if i in by]


def summits(coords, obj):
    # coords: GeoJSON LineString [[lon,lat],...]
    for c in coords:
        if not isinstance(c, (list, tuple)) or len(c) < 2:
            continue
        lon, lat = c[0], c[1]
        for sla, slo in obj:
            if abs(lat - sla) <= STOL_LAT and abs(lon - slo) <= STOL_LON:
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--map-id")
    ap.add_argument("--objective-ids", help="comma ids (overrides peaks.yml)")
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    args = ap.parse_args()

    map_id = args.map_id or (report_caltopo_id(args.slug) if args.slug else None)
    if not map_id:
        sys.exit("need --map-id or --slug with a caltopo_id in its report")

    extra = []
    if args.objective_ids:
        ids = [int(x) for x in args.objective_ids.split(",") if x.strip()]
    else:
        cfg = yaml.safe_load((ROOT / "gpx" / args.slug / "peaks.yml").read_text())
        ids = cfg.get("objective_ids", [])
        extra = [(e["lat"], e["lon"]) for e in (cfg.get("extra_summits") or [])]
    obj = objective_summits(ids) + extra
    if not obj:
        sys.exit(f"no objective summits resolved for ids {ids}")

    from caltopo_python import CaltopoSession
    s = CaltopoSession(domainAndPort="caltopo.com", mapID=map_id, configpath=str(CONFIG), account=ACCOUNT)
    shapes = s.getFeatures(featureClass="Shape")
    lines = [f for f in shapes if (f.get("geometry") or {}).get("type") == "LineString"]

    keep, kill = [], []
    for f in lines:
        title = (f.get("properties") or {}).get("title") or f["id"]
        coords = (f.get("geometry") or {}).get("coordinates") or []
        (keep if summits(coords, obj) else kill).append((f["id"], title))

    print(f"\nmap {map_id}: {len(lines)} line features — {len(keep)} summit an objective, {len(kill)} do NOT")
    print("\nKEEP (summits an objective):")
    for _i, t in keep: print(f"  ✓ {t}")
    print("\n" + ("DELETING" if args.apply else "WOULD DELETE") + " (no objective summit):")
    for _i, t in kill: print(f"  ✗ {t}")

    if args.apply and kill:
        for fid, t in kill:
            s.delFeature(fid, "Shape")
        print(f"\nDeleted {len(kill)} non-summiting line feature(s) from {map_id}.")
    elif not args.apply:
        print(f"\n(dry-run — re-run with --apply to delete the {len(kill)} marked features)")


if __name__ == "__main__":
    main()
