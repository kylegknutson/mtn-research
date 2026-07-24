#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow", "mercantile", "requests", "pyproj", "PyYAML"]
# ///
"""
summit_review_crops.py — VISUAL before/after for the summit-marker sweep.

Kyle, 2026-07-23: "I'm not sure I can verify without looking at the map before and
after." Coordinates + an elevation delta aren't enough — you need to SEE it. For each
flagged objective this renders a small OpenTopoMap (contour) crop with:

  · recorded track points near the summit  — faint blue dots (where people actually went)
  · CURRENT marker (peak_db)               — red ring + crosshair
  · PROPOSED convergence                    — green dot

…so you can read the contours and judge whether the green point sits on the true summit
knob the tracks top out on, or whether it's been pulled below a summit pitch / onto a
loop pass-through (in which case leave the red marker alone).

Reads the verify sheet JSON (scripts/summit_verify_sheet.py output) so verdicts + coords
match the gate exactly. Renders MOVE + VERIFY by default (the ones needing a decision);
--all adds the KEEP? bucket. Writes a single self-contained HTML contact sheet (crops
embedded as data URIs; forced light card so it's readable on any theme). No writes to any
peaks.yml or map.

Usage:
  scripts/summit_review_crops.py --sheet <sheet.json> --out <review.html>
  scripts/summit_review_crops.py --sheet <sheet.json> --out <review.html> --all
"""
from __future__ import annotations
import argparse, base64, importlib.util, io, json, math, sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("_recommended", "_landmarks", "_peaks_only", "_drive", "trail_osm")

# reuse the map builder's projection + tile stitching
_spec = importlib.util.spec_from_file_location("mom", ROOT / "scripts" / "make_overview_map.py")
mom = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mom)

# cache tiles across candidates (clusters share tiles → far fewer fetches)
_tile_cache: dict = {}
_orig_fetch = mom.fetch_tile
def _cached_fetch(x, y, z):
    k = (x, y, z)
    if k not in _tile_cache:
        _tile_cache[k] = _orig_fetch(x, y, z)
    return _tile_cache[k]
mom.fetch_tile = _cached_fetch

ZOOM = 17          # OpenTopoMap max; tightest contours
CROP_PX = 520      # crop window side (~490 m at z17, lat 38) — fits offsets up to ~200 m
WINDOW_M = 260     # gather track points within this of the summit for the dots


def hav_m(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def slug_trackpts(slug):
    pts = []
    d = GPX / slug
    for f in sorted(d.glob("*.gpx")):
        if any(s in f.name for s in SKIP):
            continue
        try:
            for t in ET.parse(f).getroot().iter(NS + "trkpt"):
                pts.append((float(t.get("lat")), float(t.get("lon"))))
        except (ET.ParseError, ValueError, TypeError):
            continue
    return pts


def render_crop(slug, marker, conv, trackpts):
    """Topo crop centered on the marker/convergence midpoint. Returns PNG bytes or None."""
    mlat, mlon = marker
    clat, clon = conv
    clat0, clon0 = (mlat + clat) / 2, (mlon + clon) / 2   # crop center
    # bbox big enough that the CROP_PX window is fully covered by fetched tiles
    dlat = (CROP_PX / 2 + 40) / 111320.0
    dlon = (CROP_PX / 2 + 40) / (111320.0 * math.cos(math.radians(clat0)))
    lon_min, lon_max = clon0 - dlon, clon0 + dlon
    lat_min, lat_max = clat0 - dlat, clat0 + dlat
    try:
        canvas, origin_px, origin_py = mom.build_basemap(lon_min, lon_max, lat_min, lat_max, ZOOM)
    except Exception as e:
        print(f"  {slug}: basemap failed ({e})", file=sys.stderr)
        return None
    draw = ImageDraw.Draw(canvas, "RGBA")

    def to_img(lat, lon):
        px, py = mom.lonlat_to_px(lon, lat, ZOOM)
        return mom.px_to_img(px, py, origin_px, origin_py, 1.0, 1.0, canvas.height)

    # track points (faint blue)
    for la, lo in trackpts:
        if hav_m(clat0, clon0, la, lo) > WINDOW_M * 1.6:
            continue
        ix, iy = to_img(la, lo)
        draw.ellipse([ix - 2, iy - 2, ix + 2, iy + 2], fill=(30, 90, 220, 150))

    # current marker — red ring + crosshair
    ix, iy = to_img(mlat, mlon)
    r = 9
    draw.line([ix - r - 4, iy, ix + r + 4, iy], fill=(220, 20, 20, 255), width=2)
    draw.line([ix, iy - r - 4, ix, iy + r + 4], fill=(220, 20, 20, 255), width=2)
    draw.ellipse([ix - r, iy - r, ix + r, iy + r], outline=(220, 20, 20, 255), width=3)

    # proposed convergence — green filled dot
    jx, jy = to_img(clat, clon)
    draw.ellipse([jx - 7, jy - 7, jx + 7, jy + 7], fill=(20, 190, 40, 255),
                 outline=(255, 255, 255, 255), width=2)

    # crop centered on midpoint
    cx, cy = to_img(clat0, clon0)
    half = CROP_PX // 2
    box = (cx - half, cy - half, cx + half, cy + half)
    crop = canvas.crop(box).convert("RGB")
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


VERDICT_ORDER = {"AUTO": 0, "MANUAL": 1, "MOVE": 2, "VERIFY": 3, "KEEP?": 4,
                 "no-dem": 5, "manual": 6}


def main():
    ap = argparse.ArgumentParser(description="Visual before/after crops for the marker sweep")
    ap.add_argument("--sheet", required=True, help="summit_verify_sheet.py JSON output")
    ap.add_argument("--out", required=True, help="output HTML contact sheet")
    ap.add_argument("--all", action="store_true", help="include the KEEP? bucket too")
    ap.add_argument("--only", help="comma-separated verdicts to render (overrides default)")
    ap.add_argument("--png-dir", help="also write each crop as a standalone PNG here (for spot-checks)")
    ap.add_argument("--artifact", action="store_true", help="emit body-only HTML (no doctype) for Artifact publishing")
    args = ap.parse_args()

    rows = json.loads(Path(args.sheet).read_text())
    if args.only:
        want = {v.strip() for v in args.only.split(",")}
    else:
        want = {"MOVE", "VERIFY"} | ({"KEEP?"} if args.all else set())
    rows = [r for r in rows if r.get("verdict") in want]
    rows.sort(key=lambda r: (VERDICT_ORDER.get(r["verdict"], 9), r["slug"], -r["offset_ft"]))
    print(f"Rendering {len(rows)} crop(s): {sorted(want)}", flush=True)

    tracks_by_slug: dict = {}
    cards = []
    for i, r in enumerate(rows):
        slug = r["slug"]
        if slug not in tracks_by_slug:
            tracks_by_slug[slug] = slug_trackpts(slug)
        png = render_crop(slug, tuple(r["marker"]), tuple(r["convergence"]),
                          tracks_by_slug[slug])
        print(f"  [{i+1}/{len(rows)}] {slug} / {r['name']}", flush=True)
        if args.png_dir and png:
            pd = Path(args.png_dir); pd.mkdir(parents=True, exist_ok=True)
            safe = f"{r['verdict'].strip('?')}_{slug}_{r['peak_db_id']}.png"
            (pd / safe).write_bytes(png)
        img = ("data:image/png;base64," + base64.b64encode(png).decode()) if png else ""
        # prefer the offline track Δelevation (v2) over ned10m if present
        d = r.get("track_dele_ft", r.get("ned10m_delta_ft"))
        lbl = "Δele(track)" if r.get("track_dele_ft") is not None else "ned10mΔ"
        dtxt = "—" if d is None else f"{'+' if d >= 0 else ''}{d} ft"
        cards.append((r, img, f"{lbl} {dtxt}"))

    write_html(Path(args.out), cards, want, artifact=args.artifact)
    print(f"\n  HTML: {args.out}")
    print(f"  ({len(_tile_cache)} unique tiles fetched)")


def write_html(path, cards, want, artifact=False):
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    css = """
    :root{color-scheme:light}
    body{background:#fff;color:#141414;font:14px/1.45 system-ui,sans-serif;margin:1.5rem}
    h1{font-size:20px}h2{margin:1.6rem 0 .4rem;border-bottom:2px solid #ddd;padding-bottom:3px}
    .legend{margin:.3rem 0 1rem;color:#333}
    .legend b.r{color:#dc1414}.legend b.g{color:#14be28}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
    .card{border:1px solid #ccc;border-radius:8px;overflow:hidden;background:#fafafa}
    .card img{width:100%;display:block;background:#eee}
    .meta{padding:6px 9px}
    .meta .nm{font-weight:600}
    .meta .sub{color:#555;font-size:12.5px;font-variant-numeric:tabular-nums}
    .warn{color:#b00;font-weight:600}
    a{color:#06c;text-decoration:none}a:hover{text-decoration:underline}
    code{font-size:11px;background:#eee;padding:1px 4px;border-radius:3px}
    """
    head = f"<style>{css}</style>" if artifact else \
        f"<!doctype html><meta charset='utf-8'><title>Summit marker review</title><style>{css}</style>"
    parts = [head,
             "<h1>Summit-marker review — before/after</h1>",
             "<p class='legend'><b class='r'>red ⊕</b> = current marker (peak_db) &nbsp;·&nbsp; "
             "<b class='g'>green ●</b> = proposed convergence &nbsp;·&nbsp; "
             "<span style='color:#1e5adc'>blue dots</span> = recorded track points. "
             "Move the marker only if green sits on the summit knob the contours + tracks agree on.</p>"]
    order = sorted(want, key=lambda v: VERDICT_ORDER.get(v, 9))
    for v in order:
        vc = [c for c in cards if c[0]["verdict"] == v]
        if not vc:
            continue
        parts.append(f"<h2>{esc(v)} ({len(vc)})</h2><div class='grid'>")
        for r, img, dtxt in vc:
            _d = r.get("track_dele_ft", r.get("ned10m_delta_ft"))
            dcls = "warn" if (_d is not None and _d < -10) else ""
            ov = (f'{r["peak_db_id"]}: {{lat: {r["convergence"][0]}, lon: {r["convergence"][1]}}}'
                  if r["kind"] == "override" else "(manual)")
            parts.append(
                f"<div class='card'><img src='{img}' loading='lazy'>"
                f"<div class='meta'><div class='nm'>{esc(r['name'])}</div>"
                f"<div class='sub'>{esc(r['slug'])} · id {r['peak_db_id'] or '—'}</div>"
                f"<div class='sub'>offset <b>{r['offset_ft']} ft</b> · {r['n_tracks']} tracks · "
                f"<span class='{dcls}'>{dtxt}</span></div>"
                f"<div class='sub'><a href='{r['marker_link']}' target='_blank'>marker↗</a> "
                f"<a href='{r['conv_link']}' target='_blank'>convergence↗</a></div>"
                f"<div class='sub'><code>{esc(ov)}</code></div></div></div>")
        parts.append("</div>")
    path.write_text("\n".join(parts))


if __name__ == "__main__":
    main()
