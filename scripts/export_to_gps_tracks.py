#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
export_to_gps_tracks.py — copy a report's recommended route + markers into the
iCloud "GPS Tracks" folder so it's loadable on the phone / GPS app.

For a report <slug> this merges three already-built files from gpx/<slug>/ —
  <slug>_recommended.gpx   the composed recommended route (track)
  <slug>_peaks_only.gpx    the objective SUMMIT waypoints
  <slug>_landmarks.gpx     the TRAILHEAD (and other landmark) waypoints
into ONE GPX (one <trk> + the summit/trailhead <wpt>s) and writes it to:
  ~/…/CloudDocs/Documents/GPS Tracks/<slug>_recommended.gpx

This runs automatically at the end of build_recommended_route.py, so every new
route lands in GPS Tracks. Use it standalone to backfill existing reports.

Usage:
  scripts/export_to_gps_tracks.py dolores_middle_peak
  scripts/export_to_gps_tracks.py --all            # every slug with a route
  scripts/export_to_gps_tracks.py foo --dest "/path/to/GPS Tracks"
"""
from __future__ import annotations
import argparse, sys, xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GPX_ROOT = REPO / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
# repo is …/CloudDocs/Projects/mtn_research → GPS Tracks is …/CloudDocs/Documents/GPS Tracks
DEFAULT_DEST = REPO.parent.parent / "Documents" / "GPS Tracks"


def _waypoints_xml(path: Path) -> list[str]:
    """Return each <wpt> element from a markers GPX as a serialized string."""
    if not path or not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    out = []
    for w in root.iter(NS + "wpt"):
        lat, lon = w.get("lat"), w.get("lon")
        parts = [f'<wpt lat="{lat}" lon="{lon}">']
        for tag in ("ele", "name", "sym"):
            el = w.find(NS + tag)
            if el is not None and el.text:
                parts.append(f"<{tag}>{el.text}</{tag}>")
        parts.append("</wpt>")
        out.append("".join(parts))
    return out


def _track_block(path: Path) -> str | None:
    """Return the recommended route's <trk>…</trk> serialized, or None."""
    if not path.exists():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    trk = root.find(NS + "trk")
    if trk is None:
        return None
    name_el = trk.find(NS + "name")
    name = name_el.text if name_el is not None and name_el.text else "Recommended route"
    lines = [f"<trk><name>{name}</name><trkseg>"]
    for pt in trk.iter(NS + "trkpt"):
        ele = pt.find(NS + "ele")
        es = f"<ele>{ele.text}</ele>" if ele is not None and ele.text else ""
        lines.append(f'<trkpt lat="{pt.get("lat")}" lon="{pt.get("lon")}">{es}</trkpt>')
    lines.append("</trkseg></trk>")
    return "\n".join(lines)


def export(slug: str, dest_dir: Path) -> Path:
    d = GPX_ROOT / slug
    if not d.exists():
        sys.exit(f"ERROR: {d} not found")
    route_f = d / f"{slug}_recommended.gpx"
    track = _track_block(route_f)
    if track is None:
        sys.exit(f"ERROR: no recommended route at {route_f} (build it first)")

    summits = _waypoints_xml(next(d.glob("*peaks_only*.gpx"), None))
    trailheads = _waypoints_xml(next(d.glob("*landmark*.gpx"), None))

    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{slug}_recommended.gpx"
    with open(out, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<gpx version="1.1" creator="export_to_gps_tracks.py" '
                'xmlns="http://www.topografix.com/GPX/1/1">\n')
        for w in trailheads + summits:        # waypoints first (GPX convention)
            f.write(w + "\n")
        f.write(track + "\n")
        f.write("</gpx>\n")
    print(f"GPS Tracks: wrote {out}  "
          f"(route + {len(summits)} summit + {len(trailheads)} trailhead marker(s))")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="report slug (omit with --all)")
    ap.add_argument("--all", action="store_true",
                    help="export every slug under gpx/ that has a recommended route")
    ap.add_argument("--dest", default=str(DEFAULT_DEST),
                    help="destination GPS Tracks directory")
    args = ap.parse_args()
    dest = Path(args.dest)

    if args.all:
        slugs = sorted(p.parent.name for p in GPX_ROOT.glob("*/*_recommended.gpx"))
        if not slugs:
            sys.exit("No reports with a recommended route found.")
        print(f"Backfilling {len(slugs)} report(s) → {dest}")
        for s in slugs:
            export(s, dest)
        return
    if not args.slug:
        ap.error("provide a slug or --all")
    export(args.slug, dest)


if __name__ == "__main__":
    main()
