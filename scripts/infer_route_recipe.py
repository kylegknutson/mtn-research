#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
infer_route_recipe.py — figure out HOW a report's committed recommended route was built,
and VERIFY the recipe reproduces it, so it can be recorded in peaks.yml (route_build:) and
rebuilt deterministically. Routes are gitignored and were built per-report with ad-hoc
methods; without a recorded recipe a routine rebuild can silently replace a good route with
a wrong one (cuba: default rebuild gave 26 ft / 20.85 mi vs the real 15.8 mi).

For <slug>, the current *_recommended.gpx is the TRUTH. Tries candidate builds (to /tmp,
--no-dem) and reports the one that REPRODUCES it (distance within 1% AND the committed route
never strays more than VERIFY_FT from the candidate):
    graph        — the default shortest-path router
    legs         — the per-leg / whole-track router
    from_track:X — a single recorded track, verbatim (X = filename substring)
If none reproduces, prints `frozen` (route can't be regenerated from a simple recipe — record
multi_segment by hand, or keep the file).

    scripts/infer_route_recipe.py cuba_gulch_trio
    scripts/infer_route_recipe.py --all          # every single-day report, one line each
"""
from __future__ import annotations
import argparse, math, re, subprocess, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
SCRIPTS = ROOT / "scripts"
NS = "{http://www.topografix.com/GPX/1/1}"
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive", "drive_in",
        "waypoints", "summit")
VERIFY_FT = 50.0   # committed route must stay this close to the candidate to count as "same"


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def pts_of(path: Path):
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, FileNotFoundError):
        return []
    return [(float(p.get("lat")), float(p.get("lon"))) for p in root.iter(NS + "trkpt")]


def route_len_mi(pts):
    return sum(hav(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1)) / 1609.34


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


def max_dev_ft(ref, cand):
    """Worst distance from any ref point to the nearest segment of cand."""
    if len(cand) < 2:
        return float("inf")
    worst = 0.0
    step = max(1, len(ref) // 400)            # sample ref for speed
    for i in range(0, len(ref), step):
        p = ref[i]; best = float("inf")
        for j in range(len(cand) - 1):
            if abs(cand[j][0] - p[0]) > 0.02 or abs(cand[j][1] - p[1]) > 0.02:
                continue
            best = min(best, pt_seg_ft(p, cand[j], cand[j + 1]))
        worst = max(worst, best)
    return worst


def build(slug, extra):
    tmp = Path(f"/tmp/recipe_{slug}.gpx")
    cmd = [str(SCRIPTS / "build_recommended_route.py"), slug, "--no-dem", "--no-export",
           "--out", str(tmp)] + extra
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return pts_of(tmp)


def source_tracks(slug):
    return [f for f in sorted((GPX / slug).glob("*.gpx"))
            if not any(s in f.name.lower() for s in SKIP)]


def token(name, all_names):
    """A substring for --from-track that UNIQUELY identifies this file among the source
    tracks. A digit-bearing token like '14ers' is common to many files (trk_14ers_1..14),
    so prefer the longest digit token that matches exactly one file; fall back to the full
    stem (always unique)."""
    stem = name.replace(".gpx", "")
    cands = sorted((t for t in re.split(r"[_]", stem) if any(c.isdigit() for c in t)),
                   key=len, reverse=True)
    for c in cands:
        if sum(1 for n in all_names if c.lower() in n.lower()) == 1:
            return c
    return stem


def reproduces(ref, cand, ref_mi):
    if not cand or len(cand) < 2:
        return False
    cm = route_len_mi(cand)
    if ref_mi > 0 and abs(cm - ref_mi) / ref_mi > 0.01:
        return False
    return max_dev_ft(ref, cand) <= VERIFY_FT


def infer(slug):
    rf = next((GPX / slug).glob(f"{slug}_recommended.gpx"), None)
    if not rf:
        return ("none", "no committed route")
    ref = pts_of(rf)
    if len(ref) < 2:
        return ("none", "empty route")
    ref_mi = route_len_mi(ref)

    if reproduces(ref, build(slug, []), ref_mi):
        return ("graph", f"{ref_mi:.1f} mi")
    if reproduces(ref, build(slug, ["--legs"]), ref_mi):
        return ("legs", f"{ref_mi:.1f} mi")
    names = [t.name for t in source_tracks(slug)]
    for trk in source_tracks(slug):
        tok = token(trk.name, names)
        if reproduces(ref, build(slug, ["--from-track", tok]), ref_mi):
            return (f"from_track:{tok}", f"{ref_mi:.1f} mi via {trk.name}")
    return ("frozen", f"{ref_mi:.1f} mi — no simple recipe reproduces it")


def is_trip(slug):
    y = GPX / slug / "peaks.yml"
    return y.exists() and bool((yaml.safe_load(y.read_text()) or {}).get("days"))


def write_recipe(slug, method, track=None):
    """Insert a route_build: line into peaks.yml (after the objective_ids block). Skips if a
    recipe already exists — won't clobber a hand-set one (e.g. grizzly's multi_segment)."""
    yml = GPX / slug / "peaks.yml"
    text = yml.read_text()
    if re.search(r"^route_build:", text, re.MULTILINE):
        return "kept existing"
    if method == "from_track":
        line = f'route_build: {{method: from_track, track: "{track}"}}'
    else:
        line = f"route_build: {{method: {method}}}"
    lines = text.splitlines()
    ins = len(lines)
    for i, l in enumerate(lines):
        if re.match(r"^objective_ids:", l):
            if "[" in l:
                ins = i + 1
            else:
                j = i + 1
                while j < len(lines) and lines[j].lstrip().startswith("-"):
                    j += 1
                ins = j
            break
    lines.insert(ins, line)
    yml.write_text("\n".join(lines) + "\n")
    return "wrote " + line


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true", help="record the inferred recipe in peaks.yml")
    args = ap.parse_args()
    if args.all:
        slugs = sorted(p.parent.name for p in GPX.glob("*/peaks.yml"))
    else:
        slugs = [args.slug]
    for slug in slugs:
        if is_trip(slug):
            print(f"{slug:30s} TRIP (per-day — handle via days: block)")
            continue
        method, note = infer(slug)
        tag = ""
        if args.write and method != "none":
            base, _, track = method.partition(":")
            tag = "  → " + write_recipe(slug, base, track or None)
        print(f"{slug:30s} {method:24s} {note}{tag}")


if __name__ == "__main__":
    main()
