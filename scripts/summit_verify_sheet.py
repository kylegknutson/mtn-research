#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
summit_verify_sheet.py — REVIEW ARTIFACT for the fleet summit-marker sweep (no writes).

Kyle, 2026-07-23: before moving ~69 flagged markers, "surface all first, no writes yet."
This builds that verify sheet. For every objective the hard gate (check_summit_markers)
FLAGS as off its distinct-track-convergence summit, it emits one row with:

  slug · summit · peak_db id · current marker coord · convergence coord · offset (ft) ·
  # distinct tracks · ned10m Δ (convergence − marker, coarse cross-check ONLY) ·
  CalTopo deep-links to BOTH points (so Kyle reads the contours himself) ·
  a ready-to-paste `summit_overrides` line.

It writes:
  - <out>.json   — machine-readable rows (feeds the apply step once Kyle approves)
  - <out>.html   — a clickable table grouped by slug (the review artifact)

It NEVER edits peaks.yml or any map. Convergence math is imported verbatim from
check_summit_markers so the sheet matches the gate exactly. ned10m is opt-out (--no-dem)
and never the arbiter — it smoothed PT 13,060 B's knob onto the shoulder; CalTopo (finer
DEM, via the deep-links) is the real height check.

peak_db id resolution: each flagged wpt is matched to the NEAREST objective_id's peak_db
coord (honoring any existing override). A flagged marker that is NOT within --id-snap-m of
any objective_id (an extra_summit or a nearby context neighbor) can't be moved via
summit_overrides — it's marked kind="manual" so Kyle knows to edit it by hand / ignore.

Usage:
  scripts/summit_verify_sheet.py                       # all flagged, with ned10m
  scripts/summit_verify_sheet.py --no-dem              # skip network (faster)
  scripts/summit_verify_sheet.py --out /tmp/sheet      # output basename
"""
from __future__ import annotations
import argparse, json, math, sys, time, urllib.parse, urllib.request
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
OPENTOPODATA = "https://api.opentopodata.org/v1"

# Import the gate's convergence machinery verbatim so the sheet == the gate.
sys.path.insert(0, str(ROOT / "scripts"))
import importlib.util
_spec = importlib.util.spec_from_file_location("csm", ROOT / "scripts" / "check_summit_markers.py")
csm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csm)


def hav_ft(a, b, c, d):
    return csm.hav_ft(a, b, c, d)


def peakdb_coords():
    """{peak_db id: (lat, lon, display_name, elevation_ft)}."""
    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    out = {}
    for p in peaks():
        if p.get("lat") is None:
            continue
        out[p["id"]] = (p["lat"], p["lon"],
                        (p.get("display_name") or "").strip('"'),
                        p.get("elevation_ft"))
    return out


def resolve_id(mlat, mlon, obj_ids, overrides, dbc, snap_m):
    """Nearest objective_id to the flagged marker (honoring existing overrides)."""
    best, best_ft = None, None
    for pid in obj_ids:
        ov = overrides.get(pid)
        if ov:
            clat, clon = float(ov["lat"]), float(ov["lon"])
        elif pid in dbc:
            clat, clon = dbc[pid][0], dbc[pid][1]
        else:
            continue
        off = hav_ft(mlat, mlon, clat, clon)
        if best_ft is None or off < best_ft:
            best, best_ft = pid, off
    if best is not None and best_ft <= snap_m * 3.28084:
        return best
    return None


def sample_dem(latlons, dataset="ned10m"):
    out = []
    for i in range(0, len(latlons), 100):
        batch = latlons[i:i + 100]
        locs = "|".join(f"{a:.6f},{o:.6f}" for a, o in batch)
        url = f"{OPENTOPODATA}/{dataset}?locations=" + urllib.parse.quote(locs, safe="|,")
        data = None
        for _ in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.load(resp)
                break
            except Exception:
                time.sleep(2)
        if data is None or "results" not in data:
            raise RuntimeError(f"DEM request failed ({dataset})")
        out += [r.get("elevation") for r in data["results"]]
        if i + 100 < len(latlons):
            time.sleep(1.1)
    return out


def caltopo_link(lat, lon, z=16):
    return f"https://caltopo.com/map.html#ll={lat:.5f},{lon:.5f}&z={z}&b=mbt"


LOWER_TOL_FT = 10.0   # convergence more than this below the marker (ned10m) ⇒ suspect
BIG_JUMP_FT = 200.0   # a move this far even when higher wants an eyeball


def verdict(r):
    """Triage a flagged marker using offset + the ned10m elevation cross-check.
      MOVE   — convergence not lower than the marker & a modest jump: genuine marker error.
      VERIFY — convergence higher but a big jump (could be a neighbor summit): Kyle's eye.
      KEEP?  — convergence reads LOWER on ned10m: the metric is likely fooled (tracks
               pile up below a summit pitch / on loop pass-through) — marker probably fine.
      no-dem — couldn't cross-check (network off)."""
    if r["kind"] != "override":
        return "manual"
    d = r["ned10m_delta_ft"]
    if d is None:
        return "no-dem"
    if d < -LOWER_TOL_FT:
        return "KEEP?"
    return "VERIFY" if r["offset_ft"] > BIG_JUMP_FT else "MOVE"


def main():
    ap = argparse.ArgumentParser(description="Fleet summit-marker verify sheet (no writes)")
    ap.add_argument("--fail-ft", type=float, default=csm.FAIL_FT)
    ap.add_argument("--min-tracks", type=int, default=csm.MIN_TRACKS)
    ap.add_argument("--radius-mi", type=float, default=csm.RADIUS_MI)
    ap.add_argument("--id-snap-m", type=float, default=200.0,
                    help="max marker→objective_id distance to attribute a peak_db id (default 200 m)")
    ap.add_argument("--no-dem", action="store_true", help="skip ned10m cross-check (no network)")
    ap.add_argument("--out", default=str(ROOT / "scratch_summit_sheet"),
                    help="output basename (.json + .html)")
    args = ap.parse_args()

    dbc = peakdb_coords()
    slugs = csm.find_slugs()
    rows = []
    for slug in slugs:
        d = GPX / slug
        cfg_path = d / "peaks.yml"
        if not cfg_path.exists():
            continue
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        obj_ids = cfg.get("objective_ids") or []
        overrides = {int(k): v for k, v in (cfg.get("summit_overrides") or {}).items()}

        gate_rows = csm.check_slug(slug, args.fail_ft, args.min_tracks, args.radius_mi)
        for name, status, ntr, off, conv in gate_rows:
            if status != "FAIL" or conv is None:
                continue
            # find this objective's current marker coord (objectives() order == gate order)
            objs = csm.objectives(d, slug)
            marker = next((c for c, n in objs if n == name), None)
            if marker is None:
                continue
            mlat, mlon = marker
            clat, clon = conv
            pid = resolve_id(mlat, mlon, obj_ids, overrides, dbc, args.id_snap_m)
            kind = "override" if pid is not None else "manual"
            rows.append({
                "slug": slug, "name": name, "peak_db_id": pid, "kind": kind,
                "marker": [round(mlat, 5), round(mlon, 5)],
                "convergence": [round(clat, 5), round(clon, 5)],
                "offset_ft": round(off), "n_tracks": ntr,
                "ned10m_marker_ft": None, "ned10m_conv_ft": None, "ned10m_delta_ft": None,
                "marker_link": caltopo_link(mlat, mlon),
                "conv_link": caltopo_link(clat, clon),
            })

    # ned10m cross-check (marker + convergence for every row, batched)
    if not args.no_dem and rows:
        probes = []
        for r in rows:
            probes.append(tuple(r["marker"]))
            probes.append(tuple(r["convergence"]))
        try:
            els = sample_dem(probes)
            for i, r in enumerate(rows):
                m_e, c_e = els[2 * i], els[2 * i + 1]
                if m_e is not None:
                    r["ned10m_marker_ft"] = round(m_e * 3.28084)
                if c_e is not None:
                    r["ned10m_conv_ft"] = round(c_e * 3.28084)
                if m_e is not None and c_e is not None:
                    r["ned10m_delta_ft"] = round((c_e - m_e) * 3.28084)
        except Exception as e:
            print(f"  ned10m cross-check skipped: {e}", file=sys.stderr)

    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(rows, indent=2))
    write_html(out.with_suffix(".html"), rows, args)

    for r in rows:
        r["verdict"] = verdict(r)
    out.with_suffix(".json").write_text(json.dumps(rows, indent=2))  # rewrite w/ verdict

    # terminal summary — triage counts first, then rows grouped by verdict
    order = {"MOVE": 0, "VERIFY": 1, "KEEP?": 2, "no-dem": 3, "manual": 4}
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"\n{len(rows)} flagged across {len({r['slug'] for r in rows})} slug(s).  Triage:")
    for v in sorted(counts, key=lambda v: order.get(v, 9)):
        print(f"    {v:8s} {counts[v]:3d}")
    print("\n  MOVE  = convergence not lower & modest jump — genuine marker error")
    print("  VERIFY= convergence higher but a >200 ft jump — eyeball (could be a neighbor)")
    print("  KEEP? = convergence reads LOWER on ned10m — metric likely fooled; marker probably fine\n")
    for r in sorted(rows, key=lambda r: (order.get(r["verdict"], 9), r["slug"], -r["offset_ft"])):
        d = r["ned10m_delta_ft"]
        dtxt = "  ned10mΔ   —" if d is None else f"  ned10mΔ {('+' if d >= 0 else ''):>1}{d:>4} ft"
        print(f"    {r['verdict']:7s} {r['slug'][:24]:24s} {r['name'][:26]:26s} "
              f"{r['offset_ft']:4d} ft  {r['n_tracks']:2d} trk{dtxt}")
    print(f"\n  JSON: {out.with_suffix('.json')}")
    print(f"  HTML: {out.with_suffix('.html')}")


VERDICT_HELP = {
    "MOVE": "convergence not lower & a modest jump — genuine marker error, safe to move",
    "VERIFY": "convergence higher but a >200 ft jump — eyeball (could be a neighbor summit)",
    "KEEP?": "convergence reads LOWER on ned10m — the metric is likely fooled (tracks pile "
             "up below a summit pitch / on a loop pass-through); marker is probably fine",
    "no-dem": "no elevation cross-check available",
    "manual": "flagged marker is not an objective_id (extra_summit / context neighbor)",
}


def write_html(path, rows, args):
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    for r in rows:
        r.setdefault("verdict", verdict(r))
    order = {"MOVE": 0, "VERIFY": 1, "KEEP?": 2, "no-dem": 3, "manual": 4}
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    parts = ["<h1>Summit-marker verify sheet</h1>",
             f"<p>{len(rows)} objectives flagged &gt;{args.fail_ft:.0f} ft off their "
             "distinct-track-convergence summit. <b>No writes made.</b> "
             "Click a coord to open CalTopo and read the contours — the "
             "<b>convergence</b> point should sit on the summit knob the recorded tracks "
             "top out on. ned10m is a <i>coarse cross-check only</i>, but a strongly "
             "negative &Delta; is a reliable sign the convergence is below the summit.</p>",
             "<p><b>Triage:</b> " + " &nbsp; ".join(
                 f"{v} {counts[v]}" for v in sorted(counts, key=lambda v: order.get(v, 9))) + "</p>",
             "<ul>" + "".join(f"<li><b>{v}</b> — {esc(VERDICT_HELP[v])}</li>"
                              for v in sorted(counts, key=lambda v: order.get(v, 9))) + "</ul>"]
    for v in sorted(counts, key=lambda v: order.get(v, 9)):
        vrows = [r for r in rows if r["verdict"] == v]
        parts.append(f"<h2>{esc(v)} &nbsp;<span style='font-weight:400;font-size:14px'>"
                     f"({len(vrows)}) — {esc(VERDICT_HELP[v])}</span></h2>")
        parts.append("<table><thead><tr><th>slug</th><th>summit</th><th>id</th>"
                     "<th>offset</th><th>tracks</th><th>ned10mΔ</th>"
                     "<th>marker</th><th>convergence</th><th>override line</th>"
                     "</tr></thead><tbody>")
        for r in sorted(vrows, key=lambda r: (r["slug"], -r["offset_ft"])):
            d = r["ned10m_delta_ft"]
            dtxt = "—" if d is None else f"{'+' if d >= 0 else ''}{d} ft"
            dcls = "warn" if (d is not None and d < -LOWER_TOL_FT) else ""
            if r["kind"] == "override":
                ov = (f'{r["peak_db_id"]}: {{lat: {r["convergence"][0]}, '
                      f'lon: {r["convergence"][1]}, note: "{r["n_tracks"]}-track '
                      f'convergence; peak_db was ~{r["offset_ft"]} ft off"}}')
            else:
                ov = "(manual — not an objective_id)"
            m, c = r["marker"], r["convergence"]
            parts.append(
                f"<tr><td>{esc(r['slug'])}</td><td>{esc(r['name'])}</td>"
                f"<td>{r['peak_db_id'] or '—'}</td>"
                f"<td class='num'>{r['offset_ft']} ft</td>"
                f"<td class='num'>{r['n_tracks']}</td>"
                f"<td class='num {dcls}'>{dtxt}</td>"
                f"<td><a href='{r['marker_link']}' target='_blank'>{m[0]},{m[1]}</a></td>"
                f"<td><a href='{r['conv_link']}' target='_blank'>{c[0]},{c[1]}</a></td>"
                f"<td><code>{esc(ov)}</code></td></tr>")
        parts.append("</tbody></table>")
    style = ("<style>body{font:14px/1.5 system-ui,sans-serif;margin:2rem;max-width:1250px}"
             "table{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}"
             "th,td{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}"
             "th{background:#f0f0f0}.num{text-align:right;font-variant-numeric:tabular-nums}"
             ".warn{color:#b00;font-weight:600}code{font-size:12px;white-space:nowrap}"
             "h2{margin-top:1.5rem}a{color:#06c}</style>")
    path.write_text("<!doctype html><meta charset='utf-8'>" + style + "\n".join(parts))


if __name__ == "__main__":
    main()
