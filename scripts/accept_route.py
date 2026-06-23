#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
accept_route.py — record Kyle's acceptance of a recommended-route deviation, so the
fidelity gate treats that specific problem area as reviewed-and-good (his workflow: once
accepted it's good unless THAT area changes; a new deviation elsewhere still fails).

Writes an entry into gpx/<slug>/route_accepted.yml (tracked, like peaks.yml):

    accepted:
      - center: [lat, lon]      # the problem point (from inspect_route)
        radius_m: 180           # how big the accepted zone is
        max_ft: 30              # deviation magnitude accepted (re-inspect if it grows past this)
        reason: "no recorded track connects A→B; approved approximate connector"
        date: "2026-06-23"

Default --at is the route's current worst un-accepted point (so you can just run it after
inspect_route shows you the map). --max-ft defaults to that point's deviation (+ a small
margin). Idempotent-ish: a near-duplicate acceptance (same area) is updated, not appended.

    scripts/accept_route.py jacque_peak --reason "no track links the two summits; ridge connector OK"
    scripts/accept_route.py jacque_peak --at 39.488,-106.18 --radius 200 --max-ft 30 --reason "..."
"""
from __future__ import annotations
import argparse, datetime, math, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
sys.path.insert(0, str(ROOT / "scripts"))
import inspect_route as ir   # reuse geometry + worst-uncovered finder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--at", help="lat,lon of the problem point (default: route's worst un-accepted)")
    ap.add_argument("--radius", type=float, default=180.0, help="accepted-zone radius (m)")
    ap.add_argument("--max-ft", type=float, help="deviation accepted (default: measured worst + 5)")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--date", default=str(datetime.date.today()))
    args = ap.parse_args()

    route, named, _ = ir.load(args.slug)
    if len(route) < 2:
        sys.exit(f"no route for {args.slug}")

    if args.at:
        lat, lon = (float(x) for x in args.at.split(","))
        # measure deviation at the named point
        best = 1e18
        for _, tk in named:
            for j in range(len(tk) - 1):
                best = min(best, ir.pt_seg_ft((lat, lon), tk[j], tk[j + 1]))
        dev = best
    else:
        w = ir.worst_uncovered(route, named, ir.acceptances(args.slug))
        if not w:
            sys.exit(f"{args.slug}: nothing un-accepted to accept — route is already clean.")
        dev, (lat, lon), _ = w

    max_ft = args.max_ft if args.max_ft is not None else math.ceil(dev) + 5
    entry = {"center": [round(lat, 6), round(lon, 6)], "radius_m": round(args.radius),
             "max_ft": round(max_ft), "reason": args.reason, "date": args.date}

    f = GPX / args.slug / "route_accepted.yml"
    data = (yaml.safe_load(f.read_text()) if f.exists() else None) or {}
    acc = data.get("accepted", []) or []
    # update an existing acceptance covering the same area instead of stacking duplicates
    for a in acc:
        c = a.get("center") or []
        if len(c) == 2 and ir.hav(lat, lon, c[0], c[1]) <= max(a.get("radius_m", 0), args.radius):
            a.update(entry)
            break
    else:
        acc.append(entry)
    data["accepted"] = acc
    f.write_text("# Human-reviewed acceptances of route deviations from recorded tracks.\n"
                 "# Each entry = a problem area Kyle saw (inspect_route) and approved.\n"
                 + yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    print(f"  ✓ accepted {args.slug} @ {lat:.5f},{lon:.5f}  ≤{max_ft:.0f} ft  r={args.radius:.0f}m")
    print(f"    {args.reason}")
    print(f"  → {f.relative_to(ROOT)} now has {len(acc)} acceptance(s)")


if __name__ == "__main__":
    main()
