#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python"]
# ///
"""
delete_caltopo_feature.py — delete a feature (line/track OR marker) by id.

Complements delete_caltopo_marker.py (markers only). Use for stale recommended
routes, duplicate tracks, etc. Find ids with:
    scripts/fetch_caltopo.py --map <ID>
    scripts/caltopo_features.py <ID> --ids

Usage:
    scripts/delete_caltopo_feature.py --map-id 55M4430 --id <feature-uuid>
    scripts/delete_caltopo_feature.py --map-id 55M4430 --id <uuid> --class Marker
"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logging.getLogger("caltopo_python").setLevel(logging.WARNING)
from caltopo_python import CaltopoSession  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent / "cts.ini"
DEFAULT_ACCOUNT = "kyleg.knutson@gmail.com"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map-id", required=True)
    ap.add_argument("--id", required=True, help="feature id (from caltopo_features.py --ids)")
    ap.add_argument("--class", dest="cls", default="Shape",
                    help="feature class: Shape (line/polygon, default) or Marker")
    args = ap.parse_args()

    s = CaltopoSession(domainAndPort="caltopo.com", mapID=args.map_id,
                       configpath=str(CONFIG_PATH), account=DEFAULT_ACCOUNT)
    try:
        r = s.delFeature(args.id, args.cls)
    except TypeError:
        r = s.delFeature(args.id)
    print(f"Deleted {args.id} ({args.cls}) from {args.map_id} -> {r}")


if __name__ == "__main__":
    main()
