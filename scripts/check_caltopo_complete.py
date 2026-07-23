#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""Verify a report's CalTopo research map actually CONTAINS what it should:
every recommended route, plus its source tracks.

Kyle, 2026-07-23: the "recommended routes missing from CalTopo" bug (caused by
hand-patching that desynced the map) passed every existing gate — nothing checked
that the map's *contents* match the report. This gate closes that: for each report
with a `caltopo_id`, it compares the local map dump (caltopo/<id>.json) against the
slug's gpx dir and FAILs if a recommended route is missing or all source tracks are
gone (the cimarron-2026-06 failure mode).

**Local-only, like every CalTopo check.** CalTopo creds (cts.ini) are gitignored and
the map dumps aren't committed, so in CI (or any machine without the dump) this
NO-OPs — it can only verify a map whose dump is present locally. Run
`scripts/fetch_caltopo.py --map <id>` (or a fresh build_report, which writes the dump)
before relying on it. Absence of a dump = "can't verify" = skip, never a false FAIL.

Checks per report (only if its map dump exists locally):
  1. Every `*_recommended.gpx` in gpx/<slug>/ has a matching "recommended route"
     line on the map. Missing any → FAIL.
  2. If the gpx dir has source tracks (trk_*, trail_osm_*), the map must have a
     non-zero count of non-recommended line features. Zero → FAIL.

Usage:
  scripts/check_caltopo_complete.py                 # all reports (skips those w/o a local dump)
  scripts/check_caltopo_complete.py rito_alto_group # one slug
  scripts/check_caltopo_complete.py --strict        # exit nonzero on FAIL
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
CALTOPO = ROOT / "caltopo"


def find_report_md(slug):
    for base in (DOCS / "peaks", DOCS / "trips"):
        p = base / f"{slug}.md"
        if p.exists():
            return p
    return None


def caltopo_id_of(md_path):
    m = re.search(r"^caltopo_id:\s*([A-Za-z0-9]+)", md_path.read_text(), re.MULTILINE)
    return m.group(1) if m else None


def map_line_titles(map_id):
    """Return list of LineString feature titles on the map, or None if no local dump."""
    dump = CALTOPO / f"{map_id}.json"
    if not dump.exists():
        return None
    data = json.loads(dump.read_text())
    feats = (data.get("state") or {}).get("features", []) or []
    titles = []
    for f in feats:
        if not isinstance(f, dict):
            continue
        if (f.get("geometry") or {}).get("type") == "LineString":
            titles.append((f.get("properties") or {}).get("title", "") or "")
    return titles


def check_slug(slug):
    """Return (status, message): status in {'ok','fail','skip'}."""
    md = find_report_md(slug)
    if not md:
        return "skip", f"{slug}: no report md"
    gdir = GPX / slug
    if not gdir.exists():
        return "skip", f"{slug}: no gpx dir"
    cid = caltopo_id_of(md)
    if not cid:
        return "skip", f"{slug}: no caltopo_id in frontmatter"
    dump = CALTOPO / f"{cid}.json"
    if not dump.exists():
        return "skip", f"{slug}: no local dump for map {cid} (fetch_caltopo --map {cid} to verify)"
    # A local dump older than the report's routes is STALE — it predates the current
    # routes, so its contents say nothing about the live map. Skip (don't false-FAIL a
    # push on stale local state). build_report writes the dump AFTER uploading, so a
    # freshly-built report's dump is newer than its routes → gets verified.
    route_mtimes = [p.stat().st_mtime for p in gdir.glob("*_recommended.gpx")]
    if route_mtimes and dump.stat().st_mtime < max(route_mtimes):
        return "skip", f"{slug}: dump for {cid} older than routes (stale — re-fetch to verify)"
    titles = map_line_titles(cid)

    fails = []
    # 1) every recommended route present
    rec_files = sorted(gdir.glob("*_recommended.gpx"))
    n_rec_on_map = sum(1 for t in titles if "recommended route" in t.lower())
    if len(rec_files) > n_rec_on_map:
        fails.append(
            f"map {cid} has {n_rec_on_map} recommended-route line(s) but the report has "
            f"{len(rec_files)} *_recommended.gpx ({', '.join(f.stem for f in rec_files)}) "
            f"— a recommended route is MISSING from the map"
        )
    # 2) source tracks not wiped
    src_files = [p for p in gdir.glob("*.gpx")
                 if p.name.startswith(("trk_", "trail_osm_"))]
    n_src_on_map = sum(1 for t in titles if "recommended route" not in t.lower())
    if src_files and n_src_on_map == 0:
        fails.append(
            f"map {cid} has ZERO source-track lines but the report has {len(src_files)} "
            f"recorded/OSM tracks — source tracks missing from the map"
        )

    if fails:
        return "fail", f"{slug} (map {cid}):\n      " + "\n      ".join(fails)
    return "ok", f"ok    {slug:26s}  map {cid}: {n_rec_on_map} recommended + {n_src_on_map} source line(s)"


def main():
    ap = argparse.ArgumentParser(description="CalTopo research-map completeness gate")
    ap.add_argument("slug", nargs="?", help="one slug (default: all)")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    if args.slug:
        slugs = [args.slug]
    else:
        slugs = sorted({p.stem.split(".")[0]
                        for base in (DOCS / "peaks", DOCS / "trips") for p in base.glob("*.md")
                        if p.stem != "index" and not p.stem.startswith("index.")})

    fails = skips = 0
    for slug in slugs:
        status, msg = check_slug(slug)
        if status == "fail":
            fails += 1
            print(f"FAIL  {msg}")
        elif status == "skip":
            skips += 1
            if args.slug:  # only be chatty about skips in single-slug mode
                print(f"skip  {msg}")
        elif args.slug:
            print(msg)

    checked = len(slugs) - skips
    print(f"\n{checked} map(s) verified, {skips} skipped (no local dump), {fails} FAIL.")
    if args.strict and fails:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
