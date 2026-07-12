#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
rename_route_tracks.py — roll the descriptor-first route-name convention out to
every report's CalTopo map (Kyle, 2026-07-11).

Old: "Recommended route (composed): <slug> — 4.8 mi / 4594 ft"  (truncated views
showed nothing but "Recommended route…"). New (from build_recommended_route.
route_display_name): "Pigeon Turret day — recommended route (composed) — …".

Per slug (skippable, resumable):
  1. rebuild routes from the peaks.yml recipe (`build_route.py <slug>`) — names
     regenerate; geometry is recipe-locked (check_route_recipe keeps it honest).
     `frozen` recipes aren't rebuilt: their committed gpx <name> is rewritten
     in place instead.
  2. read the report's caltopo_id, fetch the map dump, DELETE its old
     "Recommended route (composed):"-named lines, upload the current
     *recommended*.gpx files (same map id — no link churn).
  3. re-render the overview PNG (mtime freshness).

    scripts/rename_route_tracks.py                # all slugs with a caltopo_id
    scripts/rename_route_tracks.py cuba_gulch_trio
    scripts/rename_route_tracks.py --skip jupiter_pigeon_turret   (already done)
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
SCRIPTS = ROOT / "scripts"
CT_DUMPS = ROOT / "caltopo"
NS = "{http://www.topografix.com/GPX/1/1}"


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def report_caltopo_id(slug: str) -> str | None:
    for sub in ("peaks", "trips"):
        for p in sorted((DOCS / sub).glob(f"{slug}*.md")):
            m = re.search(r"^caltopo_id:\s*([A-Z0-9]+)", p.read_text(), re.M)
            if m:
                return m.group(1)
    return None


def display_name(out: Path, slug: str) -> str:
    stem = out.stem.replace("_recommended", "")
    if stem.startswith("day_"):
        return stem[4:].replace("_", " ").title() + " day — recommended route (composed)"
    if stem.startswith("leg_"):
        return stem[4:].replace("_", " ").title() + " leg — recommended route (composed)"
    return (stem or slug).replace("_", " ").title() + " — recommended route (composed)"


def rename_frozen(f: Path, slug: str) -> None:
    """Rewrite <name> in a frozen (non-rebuildable) route file, keeping stats."""
    txt = f.read_text()
    def sub(m):
        stats = re.search(r"—\s*[\d.]+ mi / \d+ ft.*$", m.group(1))
        return f"<name>{display_name(f, slug)}{' ' + stats.group(0) if stats else ''}</name>"
    new = re.sub(r"<name>([^<]*[Rr]ecommended[^<]*)</name>", sub, txt)
    if new != txt:
        f.write_text(new)
        print(f"  renamed in place (frozen): {f.name}")


def _find_features(obj):
    """features list may nest under 'state' (same logic as caltopo_features.py)."""
    if isinstance(obj, dict):
        if isinstance(obj.get("features"), list):
            return obj["features"]
        for v in obj.values():
            got = _find_features(v)
            if got:
                return got
    return []


def old_recommended_lines(map_id: str):
    dump = CT_DUMPS / f"{map_id}.json"
    r = run([SCRIPTS / "fetch_caltopo.py", "--map", map_id])
    if not dump.exists():
        print(f"  WARN: no dump for {map_id}: {r.stderr[-200:]}")
        return []
    out = []
    for feat in _find_features(json.loads(dump.read_text())):
        p = feat.get("properties", {})
        title = p.get("title") or ""
        # BOTH conventions (old "Recommended route (composed): …" AND new
        # "… — recommended route (composed) — …"): the dump is fetched BEFORE any
        # upload in this run, so deleting every recommended-convention line and
        # re-uploading the current files makes the whole operation idempotent
        # (a prior partial run's leftovers get cleaned too).
        if p.get("class") == "Shape" and "recommended route (composed)" in title.lower():
            out.append((feat.get("id"), title))
    return out


def process(slug: str) -> None:
    d = GPX / slug
    yml = d / "peaks.yml"
    if not yml.exists():
        return
    cfg = yaml.safe_load(yml.read_text()) or {}
    map_id = report_caltopo_id(slug)
    routes = sorted(d.glob("*recommended*.gpx"))
    if not routes or not map_id:
        print(f"— {slug}: skipped ({'no routes' if not routes else 'no caltopo_id'})")
        return
    print(f"\n=== {slug} → {map_id} ===")

    rb = (cfg.get("route_build") or {})
    if rb.get("method") == "frozen":
        for f in routes:
            rename_frozen(f, slug)
    else:
        r = run([SCRIPTS / "build_route.py", slug])
        if r.returncode != 0:
            print(f"  FAIL rebuild: {r.stdout[-300:]}{r.stderr[-300:]}")
            return
        routes = sorted(d.glob("*recommended*.gpx"))

    stale = old_recommended_lines(map_id)
    for fid, title in stale:
        run([SCRIPTS / "delete_caltopo_feature.py", "--map-id", map_id, "--id", fid])
        print(f"  deleted: {title}")
    for f in routes:
        r = run([SCRIPTS / "gpx_to_caltopo.py", "--gpx", f, "--map-id", map_id, "--no-dedupe"])
        m = re.search(r"track\s+\(#\w+\)\s+(.+)", r.stdout)
        print(f"  uploaded: {m.group(1) if m else f.name}")
    run([SCRIPTS / "make_overview_map.py", slug])
    print(f"  PNG refreshed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--skip", action="append", default=[])
    args = ap.parse_args()
    slugs = ([args.slug] if args.slug else
             sorted(p.name for p in GPX.iterdir()
                    if p.is_dir() and (p / "peaks.yml").exists()))
    for s in slugs:
        if s in args.skip:
            print(f"— {s}: skipped (--skip)")
            continue
        process(s)


if __name__ == "__main__":
    main()
