#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""Recolor a report's CalTopo map source tracks to the current palette, IN PLACE.

Kyle, 2026-07-23: after the palette change (reserve magenta for recommended, drop
red/pink/blue from source tracks), existing maps still carry the OLD colors. Rather
than a full build_report rebuild (which churns the map ID + rewrites frontmatter +
reruns the whole data phase), this recolors each existing map's source-track strokes
in place via caltopo `editFeature` (properties merge — title/geometry untouched).
Same map ID, no frontmatter change, no repo diff, idempotent (rerun = same colors).

Coloring, matching gpx_to_caltopo:
  - recommended routes (title ~ "recommended route")  → RECOMMENDED_COLOR (magenta)
  - Kyle's own recordings (title matches a gpx/<slug>/_kyle_existing/*.gpx <name>)
                                                       → KYLE_COLOR (blue)
  - every other LineString (source track / OSM trail) → track_color(i), assigned in
    stable title-sorted order so reruns are deterministic.
Only features whose current stroke differs from the target are edited (idempotent,
minimal API calls).

Local/CalTopo-only (needs cts.ini). Usage:
  scripts/recolor_map_tracks.py <slug>            # one report
  scripts/recolor_map_tracks.py --all             # every report with a caltopo_id
  scripts/recolor_map_tracks.py <slug> --dry-run  # show planned changes, no edits
"""
import argparse
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from gpx_to_caltopo import track_color, RECOMMENDED_COLOR, KYLE_COLOR  # noqa: E402
from lib import caltopo_session  # noqa: E402

ROOT = SCRIPTS.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
GPX_NS = "{http://www.topografix.com/GPX/1/1}"


def find_report_md(slug):
    for base in (DOCS / "peaks", DOCS / "trips"):
        p = base / f"{slug}.md"
        if p.exists():
            return p
    return None


def caltopo_id_of(md_path):
    m = re.search(r"^caltopo_id:\s*([A-Za-z0-9]+)", md_path.read_text(), re.MULTILINE)
    return m.group(1) if m else None


def kyle_track_names(slug):
    """<name>s of Kyle's own recordings (gpx/<slug>/_kyle_existing/*.gpx) — kept blue."""
    import xml.etree.ElementTree as ET
    names = set()
    kd = GPX / slug / "_kyle_existing"
    if not kd.is_dir():
        return names
    for f in list(kd.glob("*.gpx")) + list(kd.glob("*.GPX")):
        try:
            root = ET.parse(f).getroot()
        except Exception:
            continue
        for trk in root.findall(f"{GPX_NS}trk"):
            nm = (trk.findtext(f"{GPX_NS}name") or f.stem).strip()
            if nm:
                names.add(nm)
    return names


def target_color_map(features, kyle_names):
    """Given the map's LineString features, return {feature_id: target_hex}."""
    lines = [f for f in features
             if isinstance(f, dict) and (f.get("geometry") or {}).get("type") == "LineString"]
    out = {}
    source_lines = []
    for f in lines:
        p = f.get("properties") or {}
        title = p.get("title") or ""
        fid = f.get("id")
        if "recommended route" in title.lower():
            out[fid] = RECOMMENDED_COLOR
        elif title in kyle_names:
            out[fid] = KYLE_COLOR
        else:
            source_lines.append((title, fid))
    # Stable, deterministic order for source tracks → palette
    for i, (_, fid) in enumerate(sorted(source_lines, key=lambda x: (x[0], str(x[1])))):
        out[fid] = track_color(i)
    return out


def current_stroke(features, fid):
    for f in features:
        if f.get("id") == fid:
            p = f.get("properties") or {}
            return (p.get("stroke") or "").upper()
    return ""


def recolor(slug, dry_run=False):
    md = find_report_md(slug)
    if not md:
        return f"skip  {slug}: no report md"
    cid = caltopo_id_of(md)
    if not cid:
        return f"skip  {slug}: no caltopo_id"
    session = caltopo_session(cid)
    raw = session.getFeatures()
    # getFeatures() returns {'ids':..., 'state': {'features': [...]}} (same shape as
    # the fetch_caltopo dump), not a bare list.
    feats = (raw.get("state") or {}).get("features", []) if isinstance(raw, dict) else (raw or [])
    if not feats:
        return f"skip  {slug}: map {cid} has no features (or fetch failed)"
    targets = target_color_map(feats, kyle_track_names(slug))
    changed = 0
    for fid, target in targets.items():
        if current_stroke(feats, fid) == target.upper():
            continue
        changed += 1
        if not dry_run:
            session.editFeature(id=fid, className="Shape",
                                properties={"stroke": target}, blocking=True)
    verb = "would recolor" if dry_run else "recolored"
    return f"ok    {slug:26s} map {cid}: {verb} {changed}/{len(targets)} track(s)"


def main():
    ap = argparse.ArgumentParser(description="Recolor CalTopo map source tracks in place")
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.all:
        slugs = sorted({p.stem.split(".")[0]
                        for base in (DOCS / "peaks", DOCS / "trips") for p in base.glob("*.md")
                        if p.stem != "index" and not p.stem.startswith("index.")})
    elif args.slug:
        slugs = [args.slug]
    else:
        ap.error("give a slug or --all")

    for slug in slugs:
        try:
            print(recolor(slug, dry_run=args.dry_run))
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {slug}: {e}")


if __name__ == "__main__":
    main()
