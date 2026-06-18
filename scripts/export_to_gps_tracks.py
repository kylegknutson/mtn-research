#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
export_to_gps_tracks.py — copy each report's recommended route + its markers into
the iCloud "GPS Tracks" folder as ONE device-loadable GPX per day.

Kyle uploads each recommended *day* track to a GPS device, so every recommended
route becomes one self-contained file = the route track + that day's SUMMIT
markers + that day's TRAILHEAD. Inputs from gpx/<slug>/:
  *_recommended.gpx   one per single-day report; one PER DAY for a multi-day trip
                      (e.g. day_fortress_precipice_recommended.gpx)
  *_peaks_only.gpx    objective SUMMIT waypoints (whole report/trip)
  *_landmark*.gpx     TRAILHEAD / landmark waypoints (whole report/trip)

A multi-day trip stores ONE peaks_only / landmarks file covering every day but a
separate route per day, so we attach markers to each day SPATIALLY: a summit or
trailhead is included only if that day's track actually passes it. (For a
single-day report the one route touches every summit and the TH, so it gets them
all — same as before.)

Output: Documents/GPS Tracks/<base>.gpx, where <base> is the slug for a single-day
report, or <slug>_<dayname> for each day of a trip.

Usage:
  scripts/export_to_gps_tracks.py dolores_middle_peak     # all routes in this slug
  scripts/export_to_gps_tracks.py --all                   # every report/day
  scripts/export_to_gps_tracks.py foo --dest "/path/to/GPS Tracks"
"""
from __future__ import annotations
import argparse, math, sys, xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GPX_ROOT = REPO / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
# repo is …/CloudDocs/Projects/mtn_research → GPS Tracks is …/CloudDocs/Documents/GPS Tracks
DEFAULT_DEST = REPO.parent.parent / "Documents" / "GPS Tracks"

# A marker is "on" a day's route if the track passes within this far of it. The
# router snaps summits/trailheads within 250 m, so these leave a little slack.
SUMMIT_MATCH_M = 350.0
LANDMARK_MATCH_M = 450.0


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def _track_points_and_block(path: Path):
    """Return ([(lat,lon)...], '<trk>…</trk>' string) for the route, or (None, None).
    A day file may hold SEVERAL <trk> elements — individual out-and-back climbs that
    aren't connected by a recorded track (the no-fake-connector rule). Emit them all
    and gather every point so all of the day's summits get matched."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None, None
    trks = root.findall(NS + "trk")
    if not trks:
        return None, None
    pts, lines = [], []
    for trk in trks:
        name_el = trk.find(NS + "name")
        name = name_el.text if name_el is not None and name_el.text else "Recommended route"
        lines.append(f"<trk><name>{name}</name><trkseg>")
        for pt in trk.iter(NS + "trkpt"):
            pts.append((float(pt.get("lat")), float(pt.get("lon"))))
            ele = pt.find(NS + "ele")
            es = f"<ele>{ele.text}</ele>" if ele is not None and ele.text else ""
            lines.append(f'<trkpt lat="{pt.get("lat")}" lon="{pt.get("lon")}">{es}</trkpt>')
        lines.append("</trkseg></trk>")
    return pts, "\n".join(lines)


def _waypoints(path: Path):
    """Return [(lat, lon, '<wpt>…</wpt>' string), …] from a markers GPX."""
    if not path or not path.exists():
        return []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    out = []
    for w in root.iter(NS + "wpt"):
        lat, lon = float(w.get("lat")), float(w.get("lon"))
        parts = [f'<wpt lat="{w.get("lat")}" lon="{w.get("lon")}">']
        for tag in ("ele", "name", "sym"):
            el = w.find(NS + tag)
            if el is not None and el.text:
                parts.append(f"<{tag}>{el.text}</{tag}>")
        parts.append("</wpt>")
        out.append((lat, lon, "".join(parts)))
    return out


def _near_track(wpt, track_pts, max_m):
    la, lo, _ = wpt
    return any(hav(la, lo, tla, tlo) <= max_m for tla, tlo in track_pts)


def export_dir(slug: str, dest_dir: Path) -> list[Path]:
    """Export every recommended route in gpx/<slug>/ (one file per day)."""
    d = GPX_ROOT / slug
    if not d.exists():
        sys.exit(f"ERROR: {d} not found")
    routes = sorted(d.glob("*_recommended.gpx"))
    if not routes:
        sys.exit(f"ERROR: no *_recommended.gpx in {d} (build the route first)")

    summits = _waypoints(next(d.glob("*peaks_only*.gpx"), None))
    landmarks = _waypoints(next(d.glob("*landmark*.gpx"), None))
    multi = len(routes) > 1
    dest_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for rf in routes:
        track_pts, track_block = _track_points_and_block(rf)
        if not track_pts:
            print(f"  WARN: {rf.name} has no track points — skipped", file=sys.stderr)
            continue
        base = rf.name[:-len("_recommended.gpx")]
        out_name = base if base.startswith(slug) else f"{slug}_{base}"

        # Attach only this day's markers (single-day: the route hits them all).
        day_summits = [w for w in summits if _near_track(w, track_pts, SUMMIT_MATCH_M)] or summits
        day_landmarks = [w for w in landmarks if _near_track(w, track_pts, LANDMARK_MATCH_M)]
        if not day_landmarks and not multi:
            day_landmarks = landmarks   # single-day: keep the TH even if it snapped wide

        out = dest_dir / f"{out_name}.gpx"
        with open(out, "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<gpx version="1.1" creator="export_to_gps_tracks.py" '
                    'xmlns="http://www.topografix.com/GPX/1/1">\n')
            for _, _, xml in day_landmarks + day_summits:   # waypoints first
                f.write(xml + "\n")
            f.write(track_block + "\n")
            f.write("</gpx>\n")
        print(f"GPS Tracks: wrote {out.name}  "
              f"(route + {len(day_summits)} summit + {len(day_landmarks)} trailhead/landmark marker(s))")
        written.append(out)
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="report slug (omit with --all)")
    ap.add_argument("--all", action="store_true",
                    help="export every report under gpx/ that has a recommended route")
    ap.add_argument("--dest", default=str(DEFAULT_DEST),
                    help="destination GPS Tracks directory")
    args = ap.parse_args()
    dest = Path(args.dest)

    if args.all:
        slugs = sorted({p.parent.name for p in GPX_ROOT.glob("*/*_recommended.gpx")})
        if not slugs:
            sys.exit("No reports with a recommended route found.")
        print(f"Backfilling {len(slugs)} report(s) → {dest}")
        for s in slugs:
            export_dir(s, dest)
        return
    if not args.slug:
        ap.error("provide a slug or --all")
    export_dir(args.slug, dest)


if __name__ == "__main__":
    main()
