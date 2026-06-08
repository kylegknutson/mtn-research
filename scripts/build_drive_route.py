#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests"]
# ///
"""
build_drive_route.py — road route connecting a trip's trailheads, for the PNG.

For a multi-day trip, draws the actual driving route between the camps/trailheads
(in itinerary order) on the overview PNG so the "how do I get between zones" is
visible. Uses the public OSRM demo server for the road geometry; falls back to
straight segments if it's unreachable.

Writes gpx/<slug>/<slug>_drive.gpx — make_overview_map renders any *_drive* file
in a reserved BLACK dashed line (a color not used on the CalTopo map), and
gpx_to_caltopo skips it (PNG-only, never uploaded).

Trailhead order = the order of `kind: trailhead` landmarks in gpx/<slug>/peaks.yml.

Usage:
    scripts/build_drive_route.py --slug south_san_juans_3day
    scripts/build_drive_route.py --slug <slug> --order "Bennett,Trio,Conejos"  # match by name substring
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import yaml, requests

ROOT = Path(__file__).resolve().parent.parent
OSRM = "https://router.project-osrm.org/route/v1/driving/"


def trailheads(slug: str, order: str | None):
    cfg = yaml.safe_load((ROOT / "gpx" / slug / "peaks.yml").read_text())
    ths = [lm for lm in cfg.get("landmarks", []) if lm.get("kind", "trailhead") == "trailhead"]
    if order:
        keys = [k.strip().lower() for k in order.split(",")]
        ths = sorted(ths, key=lambda lm: next((i for i, k in enumerate(keys)
                                               if k in lm["name"].lower()), 99))
    return ths


def osrm_leg(a, b):
    """Road geometry [(lon,lat),...] between two points, or straight fallback."""
    coords = f'{a["lon"]},{a["lat"]};{b["lon"]},{b["lat"]}'
    try:
        r = requests.get(OSRM + coords, params={"overview": "full", "geometries": "geojson"}, timeout=20)
        g = r.json()["routes"][0]["geometry"]["coordinates"]
        return [(c[0], c[1]) for c in g]
    except Exception as e:
        print(f"  OSRM failed ({e}); straight segment", file=sys.stderr)
        return [(a["lon"], a["lat"]), (b["lon"], b["lat"])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--order", help="comma-separated name substrings for trailhead order")
    args = ap.parse_args()

    ths = trailheads(args.slug, args.order)
    if len(ths) < 2:
        sys.exit(f"need ≥2 trailhead landmarks in gpx/{args.slug}/peaks.yml (found {len(ths)}) — no drive route")

    print(f"routing through {len(ths)} trailheads: " + " → ".join(t["name"][:24] for t in ths))
    segs = []
    for a, b in zip(ths, ths[1:]):
        leg = osrm_leg(a, b)
        segs.append(leg)
        print(f"  {a['name'][:20]} → {b['name'][:20]}: {len(leg)} pts")

    trksegs = "".join(
        "<trkseg>" + "".join(f'<trkpt lat="{lat:.5f}" lon="{lon:.5f}"></trkpt>' for lon, lat in seg) + "</trkseg>"
        for seg in segs
    )
    gpx = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<gpx version="1.1" creator="build_drive_route.py" xmlns="http://www.topografix.com/GPX/1/1">\n'
           f'<trk><name>Driving route ({args.slug})</name>{trksegs}</trk>\n</gpx>\n')
    out = ROOT / "gpx" / args.slug / f"{args.slug}_drive.gpx"
    out.write_text(gpx)
    print(f"✓ {out}")


if __name__ == "__main__":
    main()
