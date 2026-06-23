#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
inspect_route.py — render a recommended route's worst UN-ACCEPTED fidelity problem for a
human visual review (Kyle's workflow, 2026-06-22):

    normal report flow → draw route → fidelity check → if it would FAIL, show Kyle a map of
    the problem area + the reference track + a suggested fix → he ACCEPTS (lock it) or
    REDIRECTS → after that it's good unless that specific area changes.

This finds the route's worst deviation from any recorded source track that is NOT already
covered by an acceptance in gpx/<slug>/route_accepted.yml, then:
  --json : dumps route + nearby tracks + the suggested-fix polyline + objectives + bbox,
           clipped to the problem area (for an external renderer).
  --svg  : emits a self-contained SVG map (route magenta, reference tracks green, the
           suggested fix bold orange, worst point red, objectives) — pass to show_widget.
  (default): prints a one-line human summary + the suggested fix command.

A route whose every over-bar excursion is already accepted prints "OK — all deviations
accepted" and exits 0. Accept a shown problem with scripts/accept_route.py.

    scripts/inspect_route.py jacque_peak
    scripts/inspect_route.py jacque_peak --svg > /tmp/jacque.svg
    scripts/inspect_route.py jacque_peak --json
"""
from __future__ import annotations
import argparse, html, json, math, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in",
        "waypoints", "summit")
SAMPLE_M = 6.0
BAR_FT = 3.0


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


def acceptances(slug):
    f = GPX / slug / "route_accepted.yml"
    if not f.exists():
        return []
    return (yaml.safe_load(f.read_text()) or {}).get("accepted", []) or []


def covered(p, dev, acc):
    for a in acc:
        c = a.get("center") or []
        if len(c) == 2 and hav(p[0], p[1], c[0], c[1]) <= a.get("radius_m", 150) \
                and dev <= a.get("max_ft", 1e18) + 10:
            return True
    return False


def load(slug):
    d = GPX / slug
    rf = next(d.glob("*recommended*.gpx"), None)
    route = [p for t in (tracks_in(rf) if rf else []) for p in t]
    named = []  # (filename, track)
    for f in d.glob("*.gpx"):
        if not any(s in f.name.lower() for s in SKIP):
            for t in tracks_in(f):
                named.append((f.name, t))
    objs = []
    pk = next(d.glob("*peaks_only*.gpx"), None)
    if pk:
        for w in ET.parse(pk).getroot().iter(NS + "wpt"):
            nm = w.find(NS + "name")
            objs.append({"lat": float(w.get("lat")), "lon": float(w.get("lon")),
                         "name": (nm.text if nm is not None else "") or ""})
    return route, named, objs


def worst_uncovered(route, named, acc):
    """Return (dev_ft, point, nearest_track_index) for the worst route sample whose
    deviation exceeds the bar and is not covered by an acceptance. None if all-clear."""
    worst = (0.0, None, None)
    for i in range(len(route) - 1):
        a, b = route[i], route[i + 1]
        seg = hav(*a, *b); n = max(1, int(seg / SAMPLE_M))
        for k in range(n + 1):
            t = k / n
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            best, bti = 1e18, None
            for ti, (_, tk) in enumerate(named):
                for j in range(len(tk) - 1):
                    if abs(tk[j][0] - p[0]) > 0.01 or abs(tk[j][1] - p[1]) > 0.01:
                        continue
                    dd = pt_seg_ft(p, tk[j], tk[j + 1])
                    if dd < best:
                        best, bti = dd, ti
            if best > worst[0] and best > BAR_FT and not covered(p, best, acc):
                worst = (best, p, bti)
    return worst if worst[1] else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--svg", action="store_true")
    args = ap.parse_args()

    route, named, objs = load(args.slug)
    if len(route) < 2:
        sys.exit(f"no route for {args.slug}")
    acc = acceptances(args.slug)
    w = worst_uncovered(route, named, acc)
    if not w:
        print(f"OK  {args.slug}: every over-{BAR_FT:.0f}-ft deviation is accepted "
              f"({len(acc)} acceptance(s)) — no un-reviewed problem.")
        return
    dev, (wlat, wlon), bti = w

    # frame so the deviation is ~10% of the view (always clearly visible), min ~165 ft wide
    half_m = min(400.0, max(25.0, dev / 3.28084 * 5.0))
    dlat = half_m / 111000.0
    dlon = half_m / (111000.0 * max(0.3, math.cos(math.radians(wlat))))
    bb = (wlat - dlat, wlon - dlon, wlat + dlat, wlon + dlon)
    inbox = lambda p: bb[0] <= p[0] <= bb[2] and bb[1] <= p[1] <= bb[3]
    fix_file = named[bti][0] if bti is not None else None
    fix_poly = named[bti][1] if bti is not None else []   # full track; render clips it

    if args.json:
        clip = lambda seq: [[round(x, 6) for x in p] for p in seq if inbox(p)]
        print(json.dumps({
            "slug": args.slug, "worst_ft": round(dev, 1), "worst": [round(wlat, 6), round(wlon, 6)],
            "bbox": [round(x, 6) for x in bb],
            "route": clip(route),
            "tracks": [clip(t) for _, t in named if any(inbox(p) for p in t)],
            "fix_track": fix_file, "fix_poly": [[round(x, 6) for x in p] for p in fix_poly],
            "objectives": objs, "acceptances": acc,
        }))
    elif args.svg:
        print(render_svg(args.slug, dev, (wlat, wlon), bb, route, named, fix_poly, objs, inbox))
    else:
        toks = (fix_file or "").replace(".gpx", "").split("_")
        tok = next((t for t in toks if any(ch.isdigit() for ch in t)), fix_file)
        print(f"{args.slug}: worst UN-ACCEPTED deviation {dev:.0f} ft @ {wlat:.5f},{wlon:.5f}")
        print(f"  nearest recorded track there: {fix_file}")
        print(f"  suggested fix → follow that track here: "
              f"build_recommended_route.py {args.slug} --from-track {tok}")
        print(f"  or accept as-is: accept_route.py {args.slug} --at {wlat:.5f},{wlon:.5f} "
              f"--max-ft {math.ceil(dev)} --reason '...'")


def render_svg(slug, dev, worst, bb, route, named, fix_poly, objs, inbox):
    W = H = 600; PAD = 8
    s0, w0, s1, w1 = bb
    mlat, mlon = (s0 + s1) / 2, (w0 + w1) / 2
    # expanded clip box (draw segments to just past the edge so nothing pops out abruptly)
    es, ew = (s1 - s0) * 0.08, (w1 - w0) * 0.08
    ebox = lambda p: (s0 - es) <= p[0] <= (s1 + es) and (w0 - ew) <= p[1] <= (w1 + ew)
    view_w_m = (w1 - w0) * 111320.0 * math.cos(math.radians(mlat))
    step_m = max(1.0, view_w_m / 240)
    def xy(p):
        x = PAD + (p[1] - w0) / (w1 - w0) * (W - 2 * PAD)
        y = PAD + (s1 - p[0]) / (s1 - s0) * (H - 2 * PAD)
        return f"{x:.1f},{y:.1f}"
    def poly(seq, **kw):
        # densify each segment, keep in-box runs, draw each run as its own polyline so a
        # sparse line that merely crosses the box is still drawn (filtering points drops it)
        runs, cur = [], []
        for i in range(len(seq) - 1):
            a, b = seq[i], seq[i + 1]
            n = max(1, int(hav(*a, *b) / step_m))
            for k in range(n + 1):
                t = k / n
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if ebox(p):
                    cur.append(p)
                elif cur:
                    runs.append(cur); cur = []
        if cur:
            runs.append(cur)
        attrs = " ".join(f'{k.replace("_","-")}="{v}"' for k, v in kw.items())
        out = ""
        for run in runs:
            if len(run) > 80:
                st = len(run) / 80
                run = [run[int(i * st)] for i in range(80)] + [run[-1]]
            if len(run) >= 2:
                out += f'<polyline points="{" ".join(xy(p) for p in run)}" fill="none" {attrs}/>'
        return out
    refs = "".join(poly(t, stroke="#2f9e44", stroke_width=2, opacity=0.55) for _, t in named)
    fix = poly(fix_poly, stroke="#f08c00", stroke_width=5, opacity=0.95, stroke_linecap="round")
    rt = poly(route, stroke="#E6008C", stroke_width=3)
    wx = xy(worst)
    # scale bar: pick a round footage that renders ~120 px
    view_ft = (w1 - w0) * 111320.0 * math.cos(math.radians((s0 + s1) / 2)) * 3.28084
    px_per_ft = (W - 2 * PAD) / view_ft
    nice = min([25, 50, 100, 200, 500, 1000], key=lambda v: abs(v * px_per_ft - 120))
    barpx = nice * px_per_ft
    scale = (f'<g font-family="sans-serif"><line x1="{W-20-barpx:.0f}" y1="{H-22}" '
             f'x2="{W-20}" y2="{H-22}" stroke="#111" stroke-width="3"/>'
             f'<text x="{W-20-barpx/2:.0f}" y="{H-28}" font-size="11" fill="#111" '
             f'text-anchor="middle">{nice} ft</text></g>')
    pks = ""
    for o in objs:
        if inbox((o["lat"], o["lon"])):
            x, y = xy((o["lat"], o["lon"])).split(",")
            label = html.escape(o["name"].split(" (")[0])
            pks += (f'<circle cx="{x}" cy="{y}" r="5" fill="#39FF14" stroke="#111" stroke-width="1.5"/>'
                    f'<text x="{float(x)+8}" y="{float(y)+4}" font-size="12" fill="#111" '
                    f'font-family="sans-serif">{label}</text>')
    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
        f'<rect width="{W}" height="{H}" fill="#f5f3ee"/>'
        f'{refs}{fix}{rt}'
        f'<circle cx="{wx.split(",")[0]}" cy="{wx.split(",")[1]}" r="7" fill="none" '
        f'stroke="#e03131" stroke-width="3"/>'
        f'{scale}{pks}'
        f'<g font-family="sans-serif">'
        f'<rect x="8" y="8" width="320" height="74" rx="5" fill="#ffffffcc"/>'
        f'<text x="18" y="28" font-size="15" font-weight="bold" fill="#111">{html.escape(slug)}</text>'
        f'<text x="18" y="47" font-size="13" fill="#e03131">worst un-accepted deviation: {dev:.0f} ft</text>'
        f'<text x="18" y="64" font-size="12" fill="#2f9e44">━ recorded tracks  '
        f'<tspan fill="#f08c00">━ suggested fix</tspan>  <tspan fill="#E6008C">━ current route</tspan></text>'
        f'</g></svg>'
    )


if __name__ == "__main__":
    main()
