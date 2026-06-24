#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests", "mercantile", "Pillow"]
# ///
"""
inspect_route_png.py — same as inspect_route.py but renders the worst-deviation problem
area onto a real OpenTopoMap basemap and saves a PNG (so it shows up anywhere, incl. remote
control where inline SVG widgets don't render).

    scripts/inspect_route_png.py mount_adams_trio            # writes /tmp/inspect_<slug>.png
    scripts/inspect_route_png.py mount_adams_trio -o foo.png

Route magenta, recorded tracks green, the nearest "suggested fix" track bold orange, the
worst point a red ring, objectives green dots. Reuses inspect_route's geometry/acceptances.
"""
from __future__ import annotations
import argparse, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import inspect_route as ir
import mercantile, requests
from PIL import Image, ImageDraw, ImageFont

TILE = 256
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "mtn-research-map/1.0 (personal research tool)"


def lonlat_to_px(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lr = math.radians(lat)
    y = (1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * n
    return x * TILE, y * TILE


def fetch_tile(x, y, z):
    for sub in ("a", "b", "c"):
        try:
            r = SESSION.get(f"https://{sub}.tile.opentopomap.org/{z}/{x}/{y}.png", timeout=20)
            if r.status_code == 200:
                import io
                return Image.open(io.BytesIO(r.content)).convert("RGBA")
        except Exception:
            continue
    return None


def font(sz):
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("-o", "--out")
    ap.add_argument("--at", help="lat,lon to center on (default: worst un-accepted deviation) — "
                                 "use to show a specific (e.g. now-fixed) spot")
    args = ap.parse_args()

    route_segs, named, objs = ir.load(args.slug)
    if sum(len(s) for s in route_segs) < 2:
        sys.exit(f"no route for {args.slug}")
    if args.at:
        wlat, wlon = (float(x) for x in args.at.split(","))
        dev, bti = 1e18, None
        for ti, (_, tk) in enumerate(named):
            for j in range(len(tk) - 1):
                d = ir.pt_seg_ft((wlat, wlon), tk[j], tk[j + 1])
                if d < dev:
                    dev, bti = d, ti
    else:
        w = ir.worst_uncovered(route_segs, named, ir.acceptances(args.slug))
        if not w:
            sys.exit(f"OK {args.slug}: no un-accepted deviation.")
        dev, (wlat, wlon), bti = w

    # frame: wide enough for topo context, deviation still visible (~3% of view)
    half_m = min(420.0, max(140.0, dev / 3.28084 * 16.0))
    dlat = half_m / 111000.0
    dlon = half_m / (111000.0 * max(0.3, math.cos(math.radians(wlat))))
    lat_min, lat_max = wlat - dlat, wlat + dlat
    lon_min, lon_max = wlon - dlon, wlon + dlon

    zoom = 17
    while zoom > 12 and len(list(mercantile.tiles(lon_min, lat_min, lon_max, lat_max, zooms=zoom))) > 9:
        zoom -= 1
    tiles = list(mercantile.tiles(lon_min, lat_min, lon_max, lat_max, zooms=zoom))
    minx, miny = min(t.x for t in tiles), min(t.y for t in tiles)
    maxx, maxy = max(t.x for t in tiles), max(t.y for t in tiles)
    canvas = Image.new("RGBA", ((maxx - minx + 1) * TILE, (maxy - miny + 1) * TILE), (240, 238, 232, 255))
    print(f"fetching {len(tiles)} tiles z{zoom}…", flush=True)
    for t in tiles:
        im = fetch_tile(t.x, t.y, zoom)
        if im:
            canvas.paste(im, ((t.x - minx) * TILE, (t.y - miny) * TILE))
    origin_px, origin_py = minx * TILE, miny * TILE

    # crop to bbox (Web-Mercator pixels), then scale to a target width
    l = lonlat_to_px(lon_min, lat_max, zoom)[0] - origin_px
    t_ = lonlat_to_px(lon_min, lat_max, zoom)[1] - origin_py
    r = lonlat_to_px(lon_max, lat_min, zoom)[0] - origin_px
    b = lonlat_to_px(lon_max, lat_min, zoom)[1] - origin_py
    crop = canvas.crop((int(l), int(t_), int(r), int(b)))
    W = 1000
    s = W / crop.width
    img = crop.resize((W, int(crop.height * s)), Image.LANCZOS).convert("RGBA")
    H = img.height
    draw = ImageDraw.Draw(img, "RGBA")

    def xy(lon, lat):
        px, py = lonlat_to_px(lon, lat, zoom)
        return ((px - origin_px - l) * s, (py - origin_py - t_) * s)

    def line(seg, color, lw):
        pts = [xy(p[1], p[0]) for p in seg]
        if len(pts) >= 2:
            draw.line(pts, fill=color, width=lw, joint="curve")

    for _, tk in named:                       # recorded tracks
        line(tk, (47, 158, 68, 150), 3)
    if bti is not None:                        # suggested-fix track
        line(named[bti][1], (240, 140, 0, 235), 7)
    for seg in route_segs:                     # recommended route
        line(seg, (230, 0, 140, 255), 4)
    wx, wy = xy(wlon, wlat)                     # worst point
    draw.ellipse([wx - 11, wy - 11, wx + 11, wy + 11], outline=(224, 49, 49, 255), width=4)
    for o in objs:                             # objectives in view
        if lat_min <= o["lat"] <= lat_max and lon_min <= o["lon"] <= lon_max:
            ox, oy = xy(o["lon"], o["lat"])
            draw.ellipse([ox - 6, oy - 6, ox + 6, oy + 6], fill=(57, 255, 20, 255), outline=(0, 0, 0, 255))
            draw.text((ox + 9, oy - 6), o["name"].split(" (")[0], fill=(17, 17, 17, 255), font=font(15))

    # title card + scale bar
    f1, f2 = font(20), font(15)
    draw.rectangle([8, 8, 8 + 430, 8 + 64], fill=(255, 255, 255, 210))
    draw.text((16, 14), args.slug, fill=(17, 17, 17, 255), font=f1)
    sub = (f"route vs nearest recorded track here  (magenta=route  orange=track  green=tracks)"
           if args.at else
           f"worst un-accepted deviation: {dev:.0f} ft  (magenta=route  orange=fix  green=tracks)")
    draw.text((16, 40), sub, fill=(193, 30, 30, 255), font=f2)
    view_ft = (lon_max - lon_min) * 111320.0 * math.cos(math.radians(wlat)) * 3.28084
    nice = min([50, 100, 200, 300, 500], key=lambda v: abs(v / view_ft * W - 150))
    barpx = nice / view_ft * W
    draw.line([(W - 30 - barpx, H - 26), (W - 30, H - 26)], fill=(17, 17, 17, 255), width=4)
    draw.text((W - 30 - barpx / 2 - 14, H - 48), f"{nice} ft", fill=(17, 17, 17, 255), font=f2)

    out = args.out or f"/tmp/inspect_{args.slug}.png"
    img.convert("RGB").save(out)
    print(f"  ✓ {out}  ({dev:.0f} ft @ {wlat:.5f},{wlon:.5f}, z{zoom})")


if __name__ == "__main__":
    main()
