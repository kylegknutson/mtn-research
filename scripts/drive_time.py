#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
drive_time.py — Google Maps directions URL (and optional drive-time estimate)
from a climber's home address to a trailhead.

The directions URL is deterministic and offline — this is the link that goes in
a report's "Drive from <home>" row. The actual "Xh Ym" figure still comes from
opening that URL (or the browser step); pass --estimate for a rough OSRM driving
estimate when you just want a ballpark without the browser.

Usage:
    scripts/drive_time.py --to 37.97592,-105.50657
    scripts/drive_time.py --to 37.97592,-105.50657 --climber kyle
    scripts/drive_time.py --to 37.97592,-105.50657 --estimate
"""
from __future__ import annotations
import argparse, json, sys, urllib.parse, urllib.request
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CLIMBERS = ROOT / "climbers"


def load_climber(slug: str) -> dict:
    p = CLIMBERS / f"{slug}.yml"
    if not p.exists():
        sys.exit(f"No climber profile: {p}")
    return yaml.safe_load(p.read_text())


def maps_url(origin: str, dest_latlon: str) -> str:
    # Match the existing reports' style: spaces -> '+', commas kept literal.
    o = origin.replace(" ", "+")
    return ("https://www.google.com/maps/dir/?api=1"
            f"&origin={o}"
            f"&destination={dest_latlon}")


def osrm_estimate(orig_latlon, dest_latlon):
    """Rough driving time/distance via the public OSRM demo server. Estimate only."""
    o_lat, o_lon = orig_latlon
    d_lat, d_lon = (float(x) for x in dest_latlon.split(","))
    url = (f"https://router.project-osrm.org/route/v1/driving/"
           f"{o_lon},{o_lat};{d_lon},{d_lat}?overview=false")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.load(r)
        route = data["routes"][0]
        secs = route["duration"]; meters = route["distance"]
        h = int(secs // 3600); m = int((secs % 3600) // 60)
        mi = meters / 1609.34
        return f"~{h}h {m}m / {mi:.0f} mi (OSRM estimate — verify in Maps)"
    except Exception as e:
        return f"(OSRM estimate unavailable: {e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="Destination 'lat,lon'")
    ap.add_argument("--climber", default="kyle", help="Climber slug (climbers/<slug>.yml). Default kyle.")
    ap.add_argument("--estimate", action="store_true", help="Also fetch a rough OSRM driving estimate")
    ap.add_argument("--label", default="", help="Optional trailhead label for the markdown snippet")
    args = ap.parse_args()

    c = load_climber(args.climber)
    origin = c["home_address"]
    url = maps_url(origin, args.to)

    print(f"Climber:     {c['name']}  (origin: {origin})")
    print(f"Destination: {args.to}{('  ['+args.label+']') if args.label else ''}")
    print(f"\nMaps directions URL:\n{url}")
    print(f"\nMarkdown row:\n| Drive from {origin.split(',')[1].strip()} | **[Xh Ym via Google Maps]({url})** (origin: {origin.split(',')[0]}) |")

    if args.estimate:
        est = osrm_estimate(c["home_latlon"], args.to)
        print(f"\nDrive estimate: {est}")


if __name__ == "__main__":
    main()
