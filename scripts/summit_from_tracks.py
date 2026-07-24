#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
summit_from_tracks.py — locate an objective's summit as the HIGHEST point the recorded
tracks reach, where they linger (Kyle, 2026-07-23).

Supersedes the horizontal distinct-track-convergence used by the first sweep pass, which
IGNORED elevation and so got pulled downhill to wherever tracks bunch (an approach ridge
or a saddle below a summit pitch). Kyle: "it should be the high point of the track
(highest track point) and likely a point where the track lingers a bit."

Method (all offline; absolute GPS <ele> is noisy but a track's OWN elevation ordering is
reliable, so we work per-track then pool):
  1. Collect trackpoints within RADIUS of the marker, attributed to their NEAREST
     objective (so a neighbor summit's traffic doesn't leak in).
  2. For EACH track, keep the points within BAND_M of that track's own max elevation in
     the window — its near-apex band (robust to one track logging 30 ft higher than
     another absolutely).
  3. Pool those near-apex points; bin into CELL_M cells; pick the cell-block the most
     DISTINCT tracks reach their apex in (ties → most points, then longest dwell) — the
     spot the most parties top out AND linger.
  4. Summit = dwell-weighted centroid of that block (plain centroid if no timestamps).

Also returns an elevation check: the block's apex elevation vs the marker's local apex —
this is the offline track-elevation signal for the hard gate (only FAIL/move when the new
summit is not LOWER than the marker on the tracks themselves).

Library: summit_from_tracks(mlat, mlon, tracks, obj_pts, ...).
CLI:
  scripts/summit_from_tracks.py --slug hunts_peak            # audit one slug
  scripts/summit_from_tracks.py --emit-sheet out.json [slugs...]   # sheet for the crops tool
  scripts/summit_from_tracks.py --emit-sheet out.json         # whole fleet
"""
from __future__ import annotations
import argparse, importlib.util, json, math, sys
from collections import defaultdict
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / fn)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

snap = _load("snap", "snap_summits.py")
csm = _load("csm", "check_summit_markers.py")
svs = _load("svs", "summit_verify_sheet.py")

RADIUS_MI = 0.18     # search around the marker (covers markers up to ~950 ft off)
RIDGE_TOL_M = 4.0    # ± band around a track's spike-robust apex elevation (~13 ft — tight,
                     # because on a summit ridge even 15 ft of along-crest averaging pulls
                     # the marker off the true high point, Kyle 2026-07-23)
TOPK = 5             # apex elevation = median of a track's highest TOPK points (so a lone
                     # GPS spike can't set the apex — Kyle: bad data shouldn't drag it)
FEW_FT_M = 1.524     # 5 ft. Prefer the highest track point over the turnaround ONLY if it is
                     # more than this above it; if the turnaround is within 5 ft of the
                     # highest realistic points it's GPS-noise territory, so the physical
                     # turnaround is the better summit (Kyle 2026-07-24). Self-corrects
                     # out-and-back (top≈turnaround→turnaround) vs traverse (summit clearly
                     # above the far exit-edge→highest).
CELL_M = 25.0        # clustering grid cell
MIN_TRACKS = 2       # need >=2 tracks with elevation to judge


def m_between(a, b, c, d):
    return snap.m_between(a, b, c, d)


def summit_from_tracks(mlat, mlon, tracks, obj_pts,
                       radius_mi=RADIUS_MI, cell_m=CELL_M):
    """Locate the summit as where the most distinct tracks reach their highest point.

    Per track, take its SINGLE highest point near the marker (where it topped out / turned
    around). Pool across tracks; the cell-block the most DISTINCT tracks' high points fall
    in is the summit everyone tags. Return the actual high point closest to that block's
    centroid — a MEDOID, so the marker always lands ON a track (a mean centroid could fall
    in the gap between two strands, off any track — Kyle caught this on Baldy Lejos).

    Returns {found:(lat,lon)|None, n_tracks, summit_ele_m, marker_ele_m, method}.
    tracks: segments of (lat, lon, epoch|None, ele_m|None); obj_pts: all objective coords.
    """
    radius_m = radius_mi * 1609.344
    apex = []            # (lat, lon, ele, track_idx, dwell)
    apex_eles = []       # per-track apex elevation (elevation cross-check)
    marker_best = (None, None)   # (dist_m, ele_m) — nearest track point to the marker
    for ti, seg in enumerate(tracks):
        win = []
        for i, p in enumerate(seg):
            la, lo, ep, el = p
            if el is None:
                continue
            dm = m_between(mlat, mlon, la, lo)
            if dm > radius_m:
                continue
            if min(obj_pts, key=lambda o: m_between(o[0], o[1], la, lo)) != (mlat, mlon):
                continue
            win.append((la, lo, ep, el, i))
            if dm <= 60.0 and (marker_best[0] is None or dm < marker_best[0]):
                marker_best = (dm, el)
        if not win:
            continue
        # This track's summit vote (Kyle 2026-07-24): the highest realistic point vs. the
        # turnaround, preferring the highest ONLY if it's genuinely higher (> a few ft).
        # (1) spike-robust apex elevation = median of the top-K highest points — one bad
        # reading can't set it; (2) a tight ±RIDGE_TOL band around it excludes spikes above
        # AND non-summit below; (3) HP = the highest point in that band; TA = the turnaround
        # (near point farthest from where the track entered the window, where they lingered).
        # Use HP if it out-tops TA by > FEW_FT (traverse: summit clearly above the far exit
        # edge); else TA (out-and-back: top ≈ turnaround within GPS noise → the physical
        # reversal is the truer summit).
        eles_desc = sorted((p[3] for p in win), reverse=True)
        topk = eles_desc[:min(TOPK, len(eles_desc))]
        apex_ele = topk[len(topk) // 2]                 # median of the top-K
        band = [p for p in win if abs(p[3] - apex_ele) <= RIDGE_TOL_M] or \
               [max(win, key=lambda p: p[3])]

        def dwell_of(p):
            i = p[4]
            nxt = seg[i + 1] if i + 1 < len(seg) else None
            if p[2] is not None and nxt is not None and nxt[2] is not None:
                dt = max(0.0, min(snap.DT_CAP, nxt[2] - p[2]))
                disp = m_between(p[0], p[1], nxt[0], nxt[1])
                if dt > 0 and (disp / dt) < snap.SPEED_STOP:
                    return dt
            return 0.0

        entry = win[0]
        hp = max(band, key=lambda p: (p[3], dwell_of(p)))                       # highest realistic
        ta = max(win, key=lambda p: (m_between(entry[0], entry[1], p[0], p[1]),
                                     dwell_of(p)))                              # turnaround
        vote = hp if (hp[3] - ta[3] > FEW_FT_M) else ta
        apex_eles.append(apex_ele)
        apex.append((vote[0], vote[1], vote[3], ti, 1.0))
    n_tracks = len({a[3] for a in apex})
    if n_tracks < MIN_TRACKS:
        return {"found": None, "n_tracks": n_tracks, "summit_ele_m": None,
                "marker_ele_m": marker_best[1], "method": "insufficient-tracks"}

    def cellkey(la, lo):
        return (round((la - mlat) * 111320.0 / cell_m),
                round((lo - mlon) * 111320.0 * math.cos(math.radians(mlat)) / cell_m))
    cell_tracks = defaultdict(set)
    cell_pts = defaultdict(list)
    for (la, lo, el, ti, w) in apex:
        cell_tracks[cellkey(la, lo)].add(ti)
        cell_pts[cellkey(la, lo)].append((la, lo, el, ti, w))

    def block(k):
        ts, ps = set(), []
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                ts |= cell_tracks.get((k[0] + i, k[1] + j), set())
                ps += cell_pts.get((k[0] + i, k[1] + j), [])
        return ts, ps
    best = max(cell_tracks, key=lambda k: (len(block(k)[0]), len(block(k)[1]),
                                           sum(p[4] for p in block(k)[1])))
    bts, ps = block(best)
    wsum = sum(p[4] for p in ps) or len(ps)
    clat = sum(p[0] * p[4] for p in ps) / wsum
    clon = sum(p[1] * p[4] for p in ps) / wsum
    # MEDOID: the actual apex point closest to that (dwell-weighted) centroid — the marker
    # always lands ON a track, never in a gap between strands.
    medoid = min(ps, key=lambda p: m_between(clat, clon, p[0], p[1]))
    eles = [p[2] for p in ps if p[2] is not None]
    return {"found": (medoid[0], medoid[1]), "n_tracks": len(bts),
            "summit_ele_m": (max(eles) if eles else None),
            "marker_ele_m": marker_best[1],
            "method": "apex-medoid"}


def objective_pts(slug):
    d = GPX / slug
    return [c for c, _ in csm.objectives(d, slug)]


def audit_slug(slug):
    d = GPX / slug
    objs = csm.objectives(d, slug)
    if not objs:
        return
    tracks = snap.recorded_tracks(d)
    obj_pts = [c for c, _ in objs]
    print(f"\n{slug}  ({len(tracks)} tracks)")
    for (mlat, mlon), name in objs:
        r = summit_from_tracks(mlat, mlon, tracks, obj_pts)
        if not r["found"]:
            print(f"  --   {name[:28]:28s} {r['method']} ({r['n_tracks']} trk)")
            continue
        off = m_between(mlat, mlon, r["found"][0], r["found"][1]) * 3.28084
        de = ""
        if r["summit_ele_m"] is not None and r["marker_ele_m"] is not None:
            de = f"  Δele {(r['summit_ele_m']-r['marker_ele_m'])*3.28084:+.0f} ft (track)"
        print(f"  {name[:28]:28s} summit {off:5.0f} ft from marker  "
              f"{r['n_tracks']:2d} trk{de}")


def emit_sheet(out_path, slugs):
    dbc = svs.peakdb_coords()
    rows = []
    for slug in slugs:
        d = GPX / slug
        cfg_path = d / "peaks.yml"
        if not cfg_path.exists():
            continue
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        obj_ids = cfg.get("objective_ids") or []
        overrides = {int(k): v for k, v in (cfg.get("summit_overrides") or {}).items()}
        objs = csm.objectives(d, slug)
        if not objs:
            continue
        tracks = snap.recorded_tracks(d)
        obj_pts = [c for c, _ in objs]
        for (mlat, mlon), name in objs:
            r = summit_from_tracks(mlat, mlon, tracks, obj_pts)
            if not r["found"]:
                continue
            clat, clon = r["found"]
            off = round(m_between(mlat, mlon, clat, clon) * 3.28084)
            dele = None
            if r["summit_ele_m"] is not None and r["marker_ele_m"] is not None:
                dele = round((r["summit_ele_m"] - r["marker_ele_m"]) * 3.28084)
            pid = svs.resolve_id(mlat, mlon, obj_ids, overrides, dbc, 200.0)
            rows.append({
                "slug": slug, "name": name, "peak_db_id": pid,
                "kind": "override" if pid is not None else "manual",
                "marker": [round(mlat, 5), round(mlon, 5)],
                "convergence": [round(clat, 5), round(clon, 5)],
                "offset_ft": off, "n_tracks": r["n_tracks"],
                "track_dele_ft": dele,
                "ned10m_marker_ft": None, "ned10m_conv_ft": None, "ned10m_delta_ft": None,
                "verdict": tier(off, r["n_tracks"], dele),
                "marker_link": svs.caltopo_link(mlat, mlon),
                "conv_link": svs.caltopo_link(clat, clon),
            })
    Path(out_path).write_text(json.dumps(rows, indent=2))
    for t in ("AUTO", "MANUAL"):
        sel = [r for r in rows if r["verdict"] == t]
        print(f"\n{t}: {len(sel)}")
        for r in sorted(sel, key=lambda r: -r["offset_ft"]):
            de = "" if r["track_dele_ft"] is None else f"  Δele {r['track_dele_ft']:+d} ft"
            print(f"  {r['slug'][:22]:22s} {r['name'][:24]:24s} {r['offset_ft']:4d} ft  "
                  f"{r['n_tracks']:2d} trk{de}")
    n_ok = sum(1 for r in rows if r["verdict"] == "ok")
    print(f"\n{len(rows)} located · {n_ok} already within 60 ft (untouched)")
    print(f"  sheet: {out_path}")


# Confidence tier for an auto-move. AUTO = clean walk-up the finder nails; MANUAL = the
# finder can't be trusted (marker badly misplaced so the true summit may be off-frame /
# in a dense multi-peak basin; thin evidence; or a huge track-Δele that flags a steep,
# GPS-noisy technical peak). Kyle places/decides MANUAL ones; AUTO applies programmatically.
AUTO_MAX_OFFSET = 300     # ft — beyond this the marker is grossly off; don't trust the auto-fix
AUTO_MIN_TRACKS = 3       # need a real crowd, not 2 tracks
AUTO_MAX_DELE = 150       # ft — |track Δele| above this = steep/noisy technical peak


def tier(off, n_tracks, dele):
    if off < 60:
        return "ok"
    if off > AUTO_MAX_OFFSET or n_tracks < AUTO_MIN_TRACKS or \
       (dele is not None and abs(dele) > AUTO_MAX_DELE):
        return "MANUAL"
    return "AUTO"


def main():
    ap = argparse.ArgumentParser(description="Summit = highest lingered track point")
    ap.add_argument("--slug")
    ap.add_argument("--emit-sheet", metavar="OUT", help="write a crops-compatible sheet JSON")
    ap.add_argument("slugs", nargs="*", help="limit --emit-sheet to these slugs (default all)")
    args = ap.parse_args()

    if args.slug:
        audit_slug(args.slug)
        return
    if args.emit_sheet:
        slugs = args.slugs or csm.find_slugs()
        emit_sheet(args.emit_sheet, slugs)
        return
    ap.error("give --slug <slug> or --emit-sheet <out> [slugs...]")


if __name__ == "__main__":
    main()
