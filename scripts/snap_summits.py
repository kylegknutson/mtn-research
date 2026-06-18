#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
snap_summits.py — move summit markers to where the recorded GPS tracks converge.

Kyle (2026-06-16): "a lot of these summit markers are off a bit. Probably the
best place is where the tracks seem to end." Summit markers come from peak_db /
14ers point coords, which are often a USGS benchmark or list-rounded point that
sits 30–150 m off the spot where everyone's tracks actually top out. The tracks
DON'T lie: many independent out-and-back parties all turn around at the true high
point, so the densest cluster of trackpoints near the listed summit IS the summit
people stood on — and the marker should sit there, consistent with the tracks
drawn on the map.

For each objective in gpx/<slug>/<slug>_peaks_only.gpx, this gathers all recorded
trackpoints within WINDOW_M of the listed coord, finds the densest neighborhood
(the mill-around spot at the top), and reports the offset. With --apply it
rewrites <slug>_peaks_only.gpx with the snapped coords (names/ele/sym preserved),
so a subsequent `fix_summit_markers.py --slug <slug> --apply` moves the CalTopo
marker to match.

    scripts/snap_summits.py --slug gladstone_peak              # audit one
    scripts/snap_summits.py                                    # audit all
    scripts/snap_summits.py --slug gladstone_peak --apply      # rewrite peaks_only.gpx
    scripts/snap_summits.py --min-ft 40                        # only report/snap offsets >40 ft
"""
from __future__ import annotations
import argparse, math, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX_ROOT = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
ET.register_namespace("", "http://www.topografix.com/GPX/1/1")
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in", "waypoints", "summit_")
WINDOW_M = 120.0   # search radius around the listed coord — a believable summit-coord
                   # error ceiling. Wider (e.g. 250 m) lets the density peak escape
                   # to busier approach/saddle segments and mis-snap (Gladstone jumped
                   # 708 ft at 250 m but a correct 36 ft at 120 m).
INNER_M = 22.0     # neighborhood radius defining "the cluster at the top"
MIN_PTS = 6        # need at least this many nearby trackpoints to trust a snap


def m_between(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


SPEED_STOP = 0.6     # m/s — below this a step counts as "stopped" (dwell)
DT_CAP = 600.0       # s — clamp gaps (pauses / track splits) so they don't dominate
MOVE_FLOOR = 0.04    # weight a moving step gets relative to its dt (keeps some signal)


def _epoch(s):
    """Parse an ISO-8601 <time> to epoch seconds (no Date.now; pure parse)."""
    try:
        s = s.strip().replace("Z", "+00:00")
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def recorded_tracks(d: Path, only_substr: str | None = None):
    """List of tracks; each a list of (lat, lon, epoch|None).

    only_substr: if set, use only GPX files whose name contains it (e.g. 'actual'
    to snap from Kyle's own recorded track rather than the crowd).
    """
    out = []
    for f in d.glob("*.gpx"):
        if any(s in f.name.lower() for s in SKIP):
            continue
        if only_substr and only_substr.lower() not in f.name.lower():
            continue
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        for trk in root.iter(NS + "trk"):
            seg = []
            for p in trk.iter(NS + "trkpt"):
                t = p.find(NS + "time")
                e = p.find(NS + "ele")
                seg.append((float(p.get("lat")), float(p.get("lon")),
                            _epoch(t.text) if t is not None and t.text else None,
                            float(e.text) if e is not None and e.text else None))
            if len(seg) >= 2:
                out.append(seg)
    return out


def turnaround(lat, lon, tracks, window_m):
    """Spur-tip near (lat,lon): the in-window point farthest from the track body
    outside the window — i.e. where an out-and-back literally turns around.
    Returns (tlat,tlon,off_ft) or None."""
    mlat, mlon = 111320.0, 111320.0 * math.cos(math.radians(lat))
    near, far = [], []
    for seg in tracks:
        for p in seg:
            dx, dy = (p[1] - lon) * mlon, (p[0] - lat) * mlat
            (near if dx * dx + dy * dy <= window_m * window_m else far).append(p)
    if not near or not far:
        return None
    flat = sum(p[0] for p in far) / len(far)
    flon = sum(p[1] for p in far) / len(far)
    tip = max(near, key=lambda p: m_between(flat, flon, p[0], p[1]))
    return tip[0], tip[1], m_between(lat, lon, tip[0], tip[1]) * 3.28084


def highpoint(lat, lon, tracks, window_m):
    """Highest-<ele> trackpoint within window_m of (lat,lon); (hlat,hlon,off_ft) or None.
    Relative elevation within a track is reliable even when absolute GPS ele isn't,
    so this cross-checks the dwell snap against where the track actually topped out."""
    mlat, mlon = 111320.0, 111320.0 * math.cos(math.radians(lat))
    best = None
    for seg in tracks:
        for p in seg:
            if p[3] is None:
                continue
            dx, dy = (p[1] - lon) * mlon, (p[0] - lat) * mlat
            if dx * dx + dy * dy <= window_m * window_m and (best is None or p[3] > best[3]):
                best = p
    if best is None:
        return None
    return best[0], best[1], m_between(lat, lon, best[0], best[1]) * 3.28084


def _dwell_weighted(lat, lon, tracks, window_m):
    """Weighted nearby points: weight = seconds the party DWELLED at that spot.

    Where a track step is slow (someone sat at the top), it gets its full dt of
    weight; a fast step (walking the approach) gets only MOVE_FLOOR·dt. So the
    weight piles up where people actually stopped — the summit — not where the
    trail merely passes. Tracks without usable timestamps fall back to a flat
    per-point weight (count density).
    """
    mlat = 111320.0
    mlon = 111320.0 * math.cos(math.radians(lat))
    near = []
    for seg in tracks:
        for i, p in enumerate(seg):
            dx = (p[1] - lon) * mlon
            dy = (p[0] - lat) * mlat
            if dx * dx + dy * dy > window_m * window_m:
                continue
            w = 1.0
            if p[2] is not None and i + 1 < len(seg) and seg[i + 1][2] is not None:
                dt = max(0.0, min(DT_CAP, seg[i + 1][2] - p[2]))
                ddx = (seg[i + 1][1] - p[1]) * mlon
                ddy = (seg[i + 1][0] - p[0]) * mlat
                disp = math.hypot(ddx, ddy)
                if dt > 0:
                    w = dt if (disp / dt) < SPEED_STOP else dt * MOVE_FLOOR
            near.append((p[0], p[1], dx, dy, w))
    return near


def snap(lat, lon, tracks, window_m=WINDOW_M):
    """Dwell-weighted summit: the INNER_M-cell block holding the most dwell time
    within window_m of (lat,lon). Returns ((slat,slon), peak_block_weight, n_near)."""
    near = _dwell_weighted(lat, lon, tracks, window_m)
    if len(near) < MIN_PTS:
        return None, 0, len(near)
    cells = {}
    for p in near:
        cells.setdefault((int(p[2] // INNER_M), int(p[3] // INNER_M)), []).append(p)

    def blockw(k):
        return sum(p[4] for i in (-1, 0, 1) for j in (-1, 0, 1)
                   for p in cells.get((k[0]+i, k[1]+j), []))

    best_key = max(cells, key=blockw)
    block = [p for i in (-1, 0, 1) for j in (-1, 0, 1)
             for p in cells.get((best_key[0]+i, best_key[1]+j), [])]
    wsum = sum(p[4] for p in block)
    slat = sum(p[0] * p[4] for p in block) / wsum
    slon = sum(p[1] * p[4] for p in block) / wsum
    return (slat, slon), round(blockw(best_key)), len(near)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-ft", type=float, default=30.0,
                    help="only report/snap when offset exceeds this (default 30 ft)")
    ap.add_argument("--window-m", type=float, default=WINDOW_M,
                    help=f"search radius around listed coord (default {WINDOW_M:.0f} m)")
    ap.add_argument("--apply-max-ft", type=float, default=120.0,
                    help="with --apply, snap offsets between --min-ft and this; print larger "
                         "ones as REVIEW and leave them (default 120 ft)")
    ap.add_argument("--only", help="use only track files whose name contains this (e.g. 'actual')")
    ap.add_argument("--diag", action="store_true",
                    help="also print the track high-point offset (elevation cross-check)")
    ap.add_argument("--coords", action="store_true", help="with --diag, print candidate lat/lon")
    ap.add_argument("--dump-near", help="emit JSON {points, candidates} for this summit-name substring")
    args = ap.parse_args()

    if args.dump_near:
        import json
        d = GPX_ROOT / args.slug
        tracks = recorded_tracks(d, args.only)
        po = ET.parse(d / f"{d.name}_peaks_only.gpx").getroot()
        for w in po.iter(NS + "wpt"):
            nm = w.find(NS + "name").text if w.find(NS + "name") is not None else "?"
            if args.dump_near.lower() not in (nm or "").lower():
                continue
            lat, lon = float(w.get("lat")), float(w.get("lon"))
            near = _dwell_weighted(lat, lon, tracks, args.window_m)
            s, _, _ = snap(lat, lon, tracks, args.window_m)
            hp = highpoint(lat, lon, tracks, args.window_m)
            pts = [[round(p[0], 6), round(p[1], 6), round(p[4], 1)] for p in near]
            print(json.dumps({
                "name": nm, "window_m": args.window_m,
                "db": [lat, lon],
                "dwell": [round(s[0], 6), round(s[1], 6)] if s else None,
                "high": [round(hp[0], 6), round(hp[1], 6)] if hp else None,
                "points": pts}))
            return
        sys.exit(f"--dump-near {args.dump_near!r}: not found")

    dirs = [GPX_ROOT / args.slug] if args.slug else sorted(d for d in GPX_ROOT.iterdir() if d.is_dir())
    total_snapped = 0
    for d in dirs:
        po = d / f"{d.name}_peaks_only.gpx"
        if not po.exists():
            continue
        tracks = recorded_tracks(d, args.only)
        if not tracks:
            continue
        tree = ET.parse(po)
        root = tree.getroot()
        changed = False
        for w in root.iter(NS + "wpt"):
            lat, lon = float(w.get("lat")), float(w.get("lon"))
            nm = (w.find(NS + "name").text if w.find(NS + "name") is not None else "?")
            s, n_inner, n_near = snap(lat, lon, tracks, args.window_m)
            if s is None:
                print(f"  --   {d.name:24s} {nm[:26]:26s} too few nearby pts ({n_near})")
                continue
            off_ft = m_between(lat, lon, s[0], s[1]) * 3.28084
            flag = off_ft >= args.min_ft
            review = flag and off_ft > args.apply_max_ft
            do_snap = flag and args.apply and not review
            mark = "SNAP  " if do_snap else ("REVIEW" if review else ("off   " if flag else "ok    "))
            diag = ""
            if args.diag:
                hp = highpoint(lat, lon, tracks, args.window_m)
                ta = turnaround(lat, lon, tracks, args.window_m)
                diag = (f"  | highpoint {hp[2]:4.0f} ft" if hp else "  | no ele") + \
                       (f" | turnaround {ta[2]:4.0f} ft" if ta else "")
                if args.coords:
                    diag += (f"\n         db={lat:.5f},{lon:.5f}  dwell={s[0]:.5f},{s[1]:.5f}"
                             + (f"  high={hp[0]:.5f},{hp[1]:.5f}" if hp else "")
                             + (f"  turn={ta[0]:.5f},{ta[1]:.5f}" if ta else ""))
            print(f"  {mark} {d.name:24s} {nm[:26]:26s} offset {off_ft:5.0f} ft  (cluster {n_inner}/{n_near} pts){diag}")
            if do_snap:
                w.set("lat", f"{s[0]:.5f}")
                w.set("lon", f"{s[1]:.5f}")
                changed = True
                total_snapped += 1
        if changed:
            tree.write(po, xml_declaration=True, encoding="UTF-8")
            print(f"  ✓ rewrote {po.name} — run fix_summit_markers.py --slug {d.name} --apply")

    if args.apply:
        print(f"\nSnapped {total_snapped} summit marker(s) "
              f"(≤{args.apply_max_ft:.0f} ft); REVIEW rows left unchanged.")


if __name__ == "__main__":
    main()
