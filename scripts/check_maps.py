#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow"]
# ///
"""
check_maps.py — QA gate for the generated overview PNGs.

Catches the recurring failure modes before they publish (the "redo the map"
loop), by analyzing the rendered pixels:

  FAIL  no track layer     — almost no source-colored route pixels ("only dots")
  FAIL  blank basemap      — mostly the beige fallback (OpenTopoMap tiles failed)
  FAIL  over-zoomed dot     — track pixels cram a tiny patch (objective shrunk away)
  warn  possibly clipped    — track bbox runs edge-to-edge (route may be cut off)
  warn  wrong dimensions    — not the expected 1200x960

Exit non-zero on any FAIL — wire into CI alongside check_reports.py.

Usage:
    scripts/check_maps.py
    scripts/check_maps.py docs/maps/star_peak_a.png   # specific file(s)
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "docs" / "maps"

EXP_W, EXP_H = 1200, 960
BEIGE = (232, 224, 213)              # COLOR_BG fallback in make_overview_map
# PNGs are recommended-route-only (Kyle, 2026-07-11) — scan for the magenta
# composed line, not the (no longer drawn) source-track colors.
TRACK_COLORS = [(230, 0, 140)]  # COLOR_RECOMMENDED #E6008C
ANALYZE = (300, 240)                 # downsample for speed


def close(px, ref, tol):
    return all(abs(px[i] - ref[i]) <= tol for i in range(3))


def analyze(path: Path):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    small = img.resize(ANALYZE, Image.NEAREST)
    px = small.load()
    aw, ah = ANALYZE
    total = aw * ah
    beige = 0
    track_pts = []
    for y in range(ah):
        for x in range(aw):
            p = px[x, y]
            if close(p, BEIGE, 8):
                beige += 1
            elif any(close(p, c, 40) for c in TRACK_COLORS):
                track_pts.append((x, y))
    res = {"dim": (w, h), "beige_frac": beige / total, "track_px": len(track_pts)}
    if track_pts:
        xs = [p[0] for p in track_pts]; ys = [p[1] for p in track_pts]
        res["track_bbox_frac"] = ((max(xs) - min(xs)) / aw, (max(ys) - min(ys)) / ah)
    else:
        res["track_bbox_frac"] = (0.0, 0.0)
    return res


def check(path: Path):
    r = analyze(path)
    fails, warns = [], []
    if r["dim"] != (EXP_W, EXP_H):
        warns.append(f"dimensions {r['dim']} != {(EXP_W, EXP_H)}")
    if r["beige_frac"] > 0.5:
        fails.append(f"blank basemap ({r['beige_frac']*100:.0f}% fallback beige — tiles failed)")
    if r["track_px"] < 60:
        fails.append(f"no track layer (only {r['track_px']} route pixels)")
    bw, bh = r["track_bbox_frac"]
    if r["track_px"] >= 60 and bw < 0.12 and bh < 0.12:
        fails.append(f"over-zoomed dot (tracks span {bw*100:.0f}%x{bh*100:.0f}% of frame)")
    if bw > 0.985 and bh > 0.985:
        warns.append("tracks run edge-to-edge (route may be clipped)")
    return fails, warns, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="PNG files (default: all docs/maps/*.png)")
    ap.add_argument("--warn-only", action="store_true")
    args = ap.parse_args()

    files = [Path(f) for f in args.files] if args.files else sorted(MAPS.glob("*.png"))
    if not files:
        sys.exit("No map PNGs found.")

    n_fail = 0
    for p in files:
        fails, warns, r = check(p)
        try:
            rel = p.resolve().relative_to(ROOT)
        except ValueError:
            rel = p
        if fails:
            n_fail += 1
            print(f"✗ {rel}")
            for f in fails: print(f"    FAIL: {f}")
        elif warns:
            print(f"~ {rel}")
        else:
            print(f"✓ {rel}")
        for w in warns:
            print(f"    warn: {w}")

    print(f"\n{len(files)} map(s): {n_fail} failing QA.")
    if n_fail and not args.warn_only:
        sys.exit(1)


if __name__ == "__main__":
    main()
