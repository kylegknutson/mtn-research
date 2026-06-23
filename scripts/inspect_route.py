#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
inspect_route.py — emit the geometry of a recommended route's worst fidelity problem,
for a human visual review (Kyle's workflow: when a route can't follow a real track, show
the problem area + a proposed fix, accept/redirect, lock it in).

Finds the route's worst deviation from any recorded source track, then dumps (as JSON) the
route, the nearby source tracks, the objective summits, and a bbox zoomed to the problem —
ready to render as an inline map. Prints a human summary too.

    scripts/inspect_route.py jacque_peak
    scripts/inspect_route.py jacque_peak --json   # geometry for rendering
"""
from __future__ import annotations
import argparse, json, math, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in",
        "waypoints", "summit")


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def tracks_in(path: Path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    out = []
    for trk in root.iter(NS + "trk"):
        seg = [(float(p.get("lat")), float(p.get("lon"))) for p in trk.iter(NS + "trkpt")]
        if len(seg) >= 2:
            out.append(seg)
    if not out:
        pts = [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]
        if len(pts) >= 2:
            out.append(pts)
    return out


def pt_seg_ft(p, a, b):
    lat0 = math.radians(p[0]); kx = 111320.0 * math.cos(lat0); ky = 110540.0
    ax, ay = (a[1] - p[1]) * kx, (a[0] - p[0]) * ky
    bx, by = (b[1] - p[1]) * kx, (b[0] - p[0]) * ky
    dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
    if L2 == 0.0:
        m = math.hypot(ax, ay)
    else:
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / L2)); m = math.hypot(ax + t * dx, ay + t * dy)
    return m * 3.28084


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    d = GPX / args.slug

    rf = next(d.glob("*recommended*.gpx"), None)
    route = [p for t in (tracks_in(rf) if rf else []) for p in t]
    if len(route) < 2:
        sys.exit(f"no route for {args.slug}")
    srctracks = []
    for f in d.glob("*.gpx"):
        if not any(s in f.name.lower() for s in SKIP):
            srctracks.extend(tracks_in(f))
    src = [(p, ti, pi) for ti, t in enumerate(srctracks) for pi, p in enumerate(t)]

    # worst route sample vs nearest source segment
    worst = (0.0, None)
    SAMPLE = 8.0
    for i in range(len(route) - 1):
        a, b = route[i], route[i + 1]
        seg = hav(*a, *b); n = max(1, int(seg / SAMPLE))
        for k in range(n + 1):
            t = k / n
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            best = 1e18
            for (sp, ti, pi) in src:
                if abs(sp[0] - p[0]) > 0.01 or abs(sp[1] - p[1]) > 0.01:
                    continue
                tk = srctracks[ti]
                if pi > 0:
                    best = min(best, pt_seg_ft(p, tk[pi - 1], tk[pi]))
                if pi < len(tk) - 1:
                    best = min(best, pt_seg_ft(p, tk[pi], tk[pi + 1]))
            if best > worst[0]:
                worst = (best, p)

    wlat, wlon = worst[1]
    # bbox: ~0.4 mi around the worst point
    dlat = 0.006
    dlon = 0.006 / max(0.3, math.cos(math.radians(wlat)))
    bb = (wlat - dlat, wlon - dlon, wlat + dlat, wlon + dlon)

    def inbox(p):
        return bb[0] <= p[0] <= bb[2] and bb[1] <= p[1] <= bb[3]

    pk = next(d.glob("*peaks_only*.gpx"), None)
    objs = []
    if pk:
        for w in ET.parse(pk).getroot().iter(NS + "wpt"):
            objs.append({"lat": float(w.get("lat")), "lon": float(w.get("lon")),
                         "name": (w.find(NS + "name").text or "")})

    if args.json:
        clip = lambda seq: [[round(x, 6) for x in p] for p in seq if inbox(p)]
        print(json.dumps({
            "slug": args.slug, "worst_ft": round(worst[0], 1), "worst": [wlat, wlon],
            "bbox": [round(x, 6) for x in bb],
            "route": clip(route),
            "tracks": [clip(t) for t in srctracks if any(inbox(p) for p in t)],
            "objectives": objs,
        }))
    else:
        print(f"{args.slug}: worst deviation {worst[0]:.0f} ft from any recorded track "
              f"@ {wlat:.5f},{wlon:.5f}")
        print(f"  source tracks: {len(srctracks)} · objectives: "
              + ", ".join(o['name'].split(' (')[0] for o in objs))


if __name__ == "__main__":
    main()
