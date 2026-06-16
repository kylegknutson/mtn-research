#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
audit_caltopo_tracks.py — flag report CalTopo maps that are MISSING source tracks.

Catches the dedupe regression (Kyle, 2026-06-16): gpx_to_caltopo used to dedupe
candidate tracks account-wide, so on a fresh map the recorded source tracks got
skipped as "duplicates" of tracks on other maps — leaving only the recommended
route. cimarron_six and williams_mountains both shipped with just the magenta line.

For every report with a `caltopo_id`, this compares:
  • source tracks present locally in gpx/<slug>/ (recorded + Kyle-CalTopo tracks,
    excluding recommended/peaks_only/landmark helper files), vs
  • non-recommended tracks actually on the map (from caltopo/<id>.json).

Run `scripts/fetch_caltopo.py --all` first to refresh the local dumps.

  FLAG  map has 0 source tracks but gpx/<slug>/ has some → backfill needed.
  thin  map has fewer source tracks than the gpx dir (worth a look).

Usage:
    scripts/fetch_caltopo.py --all
    scripts/audit_caltopo_tracks.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DUMP_DIR = ROOT / "caltopo"
GPX_ROOT = ROOT / "gpx"
HELPER = ("recommended", "peaks_only", "landmark", "_drive", "drive_in", "summit", "waypoint")


def find_features(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("features"), list):
            return obj["features"]
        for v in obj.values():
            r = find_features(v)
            if r is not None:
                return r
    return None


def map_source_tracks(map_id: str):
    dump = DUMP_DIR / f"{map_id}.json"
    if not dump.exists():
        return None
    feats = find_features(json.loads(dump.read_text())) or []
    n = 0
    for f in feats:
        if (f.get("geometry") or {}).get("type") not in ("LineString", "MultiLineString"):
            continue
        title = (f.get("properties", {}).get("title") or "").lower()
        if "recommended route" in title:
            continue
        n += 1
    return n


def gpx_source_tracks(slug: str):
    d = GPX_ROOT / slug
    if not d.exists():
        return 0
    return sum(1 for f in d.glob("*.gpx")
               if not any(h in f.name.lower() for h in HELPER))


def caltopo_id_of(md: Path):
    m = re.search(r'^caltopo_id:\s*"?(\w+)"?', md.read_text(), re.M)
    return m.group(1) if m else None


def main():
    reports = [p for p in list((ROOT / "docs/peaks").glob("*.md")) + list((ROOT / "docs/trips").glob("*.md"))
               if p.name.count(".") == 1]
    flags = thins = 0
    print(f"{'map':9} {'slug':28} {'gpx':>4} {'map':>4}")
    for md in sorted(reports):
        mid = caltopo_id_of(md)
        if not mid:
            continue
        slug = md.stem
        gpx_n = gpx_source_tracks(slug)
        map_n = map_source_tracks(mid)
        if map_n is None:
            print(f"{mid:9} {slug:28} {gpx_n:>4}    ?   (no dump — run fetch_caltopo.py --all)")
            continue
        tag = ""
        if gpx_n > 0 and map_n == 0:
            tag = "  <-- FLAG: map has NO source tracks"; flags += 1
        elif gpx_n - map_n >= 2:
            tag = "  <-- thin"; thins += 1
        print(f"{mid:9} {slug:28} {gpx_n:>4} {map_n:>4}{tag}")
    print(f"\n{flags} map(s) FLAGGED (no source tracks), {thins} thin.")
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
