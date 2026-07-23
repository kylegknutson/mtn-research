#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
drive_matrix.py — road drive-time / distance matrix between a report's trailheads
(and from the climber's home to each), for the grouping decision + trip report.

For any multi-trailhead report (a trip, or a cluster split across approaches),
the grouping hinges on approach logistics: two THs a quick reposition apart on the
same road system belong in one car-camp trip; ones 1.5 h+ apart / different
drainages are separate outings. This prints that matrix so it goes in the proposal
and the report instead of being computed ad-hoc (Kyle, 2026-07-23 — had to ask for
the Gold Dust cluster's inter-TH times; now standard). See
[[feedback-cluster-grouping-drive-matrix]].

Reads `kind: trailhead` landmarks from gpx/<slug>/peaks.yml (in file order).
Uses the public OSRM demo server (same server as build_drive_route / drive_time);
OSRM over-weights rough forest roads, so the numbers are approximate — label them
"verify in Maps" in the report.

Usage:
    scripts/drive_matrix.py --slug gold_dust_group
    scripts/drive_matrix.py --slug gold_dust_group --no-home   # TH↔TH only
    scripts/drive_matrix.py --coords "39.49,-106.66;39.52,-106.63" --names "Fulford;Nolan"
"""
from __future__ import annotations
import argparse, json, sys, urllib.request
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CLIMBERS = ROOT / "climbers"
OSRM = "https://router.project-osrm.org/table/v1/driving/"


def load_trailheads(slug: str):
    cfg = yaml.safe_load((ROOT / "gpx" / slug / "peaks.yml").read_text()) or {}
    ths = [lm for lm in (cfg.get("landmarks") or [])
           if lm.get("kind", "trailhead") == "trailhead" and lm.get("lat") is not None]
    return [(lm["name"], float(lm["lat"]), float(lm["lon"])) for lm in ths]


def osrm_table(points):
    """points = [(name, lat, lon), ...] → (durations[s], distances[m]) NxN, or None."""
    coords = ";".join(f"{lon},{lat}" for _, lat, lon in points)
    url = f"{OSRM}{coords}?annotations=duration,distance"
    try:
        with urllib.request.urlopen(url, timeout=25) as r:
            data = json.load(r)
        return data["durations"], data["distances"]
    except Exception as e:
        print(f"  OSRM table failed: {e}", file=sys.stderr)
        return None, None


def hm(secs):
    if secs is None:
        return "—"
    h = int(secs // 3600); m = int(round((secs % 3600) / 60))
    return f"{h}h {m:02d}m" if h else f"{m} min"


def mi(meters):
    return "—" if meters is None else f"{meters / 1609.34:.1f} mi"


def short(name, n=22):
    return name if len(name) <= n else name[:n - 1] + "…"


def main():
    ap = argparse.ArgumentParser(description="Trailhead drive-time / distance matrix")
    ap.add_argument("--slug", help="read trailheads from gpx/<slug>/peaks.yml")
    ap.add_argument("--coords", help="';'-separated 'lat,lon' (instead of --slug)")
    ap.add_argument("--names", help="';'-separated names matching --coords")
    ap.add_argument("--climber", default="kyle", help="home origin (climbers/<slug>.yml)")
    ap.add_argument("--no-home", action="store_true", help="omit the home→TH row")
    args = ap.parse_args()

    if args.coords:
        latlons = [c.strip().split(",") for c in args.coords.split(";")]
        names = (args.names.split(";") if args.names
                 else [f"TH{i+1}" for i in range(len(latlons))])
        ths = [(names[i].strip(), float(la), float(lo)) for i, (la, lo) in enumerate(latlons)]
    elif args.slug:
        ths = load_trailheads(args.slug)
    else:
        ap.error("pass --slug or --coords")

    if len(ths) < 2:
        print(f"only {len(ths)} trailhead(s) — no matrix needed (single-approach report).")
        return 0

    points = list(ths)
    home = None
    if not args.no_home:
        c = yaml.safe_load((CLIMBERS / f"{args.climber}.yml").read_text())
        hlat, hlon = c["home_latlon"]
        home = (f"Home ({c.get('name', args.climber)})", float(hlat), float(hlon))
        points = [home] + points

    durs, dists = osrm_table(points)
    if durs is None:
        return 1

    names = [short(p[0]) for p in points]

    # 1) Home → each TH (if included)
    if home is not None:
        print("Drive from home to each trailhead:\n")
        print("| Trailhead | Drive | Distance |")
        print("|---|---|---|")
        for j in range(1, len(points)):
            print(f"| {names[j]} | ~{hm(durs[0][j])} | {mi(dists[0][j])} |")
        print()

    # 2) TH ↔ TH matrix (trailheads only)
    off = 1 if home is not None else 0
    th_names = names[off:]
    print("Trailhead-to-trailhead (road):\n")
    header = "| ↓ from / to → | " + " | ".join(th_names) + " |"
    print(header)
    print("|" + "---|" * (len(th_names) + 1))
    for i in range(off, len(points)):
        row = [names[i]]
        for j in range(off, len(points)):
            if i == j:
                row.append("—")
            else:
                row.append(f"~{hm(durs[i][j])} / {mi(dists[i][j])}")
        print("| " + " | ".join(row) + " |")
    print("\n(OSRM estimate — over-weights rough forest roads; verify in Maps.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
