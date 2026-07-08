#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python"]
# ///
"""
Delete a marker by title from a CalTopo map.

Usage:
    scripts/delete_caltopo_marker.py MAP_ID "Marker title substring"

Matches markers whose title contains the substring (case-insensitive).
"""
import sys, logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("caltopo_python").setLevel(logging.WARNING)
from lib import caltopo_session

def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    map_id, needle = sys.argv[1], sys.argv[2].lower()
    s = caltopo_session(map_id)
    feats = s.getFeatures(featureClass="Marker")
    matched = [f for f in feats if needle in (f.get("properties", {}).get("title") or "").lower()]
    if not matched:
        print(f"No markers in map {map_id} match '{needle}'")
        return
    for f in matched:
        title = f["properties"]["title"]
        fid = f["id"]
        print(f"Deleting marker '{title}' ({fid})")
        s.delMarker(fid)
    print(f"Deleted {len(matched)} marker(s) from map {map_id}.")

if __name__ == "__main__":
    main()
