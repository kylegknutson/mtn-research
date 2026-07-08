#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""
recolor_kyle_tracks.py — force Kyle's own recorded tracks to blue on a research map.

gpx_to_caltopo.py now forces KYLE_COLOR (#0066FF) for any _kyle_existing/ file, so
NEW recordings upload blue. But recordings uploaded BEFORE that change (e.g. the
Dolores recording on R1KSN0U came in red from the palette) stay their old color —
dedupe skips re-uploading them, so this fixes them in place via editFeature.

For a slug, it reads every <trk><name> in gpx/<slug>/_kyle_existing/*.gpx and recolors
the matching Shape(s) on the slug's research map (peaks.yml caltopo_map_id, else report
frontmatter caltopo_id) to #0066FF. Exact title match, and only when the current color
differs, so source tracks (different titles) are never touched.

    scripts/recolor_kyle_tracks.py --slug dolores_middle_peak           # dry-run
    scripts/recolor_kyle_tracks.py --slug dolores_middle_peak --apply
    scripts/recolor_kyle_tracks.py --all --apply
"""
from __future__ import annotations
import argparse, logging, re
import xml.etree.ElementTree as ET
import yaml

logging.basicConfig(level=logging.ERROR)
logging.getLogger("caltopo_python").setLevel(logging.ERROR)

from lib import DOCS_DIR as DOCS, GPX_DIR as GPX, GPX_NS as NS, caltopo_session  # noqa: E402

KYLE_COLOR = "#0066FF"


def map_id_for(slug: str) -> str | None:
    yml = GPX / slug / "peaks.yml"
    if yml.exists():
        cfg = yaml.safe_load(yml.read_text()) or {}
        if cfg.get("caltopo_map_id"):
            return str(cfg["caltopo_map_id"])
    for md in (DOCS / "peaks" / f"{slug}.md", DOCS / "trips" / f"{slug}.md"):
        if md.exists():
            m = re.search(r"^caltopo_id:\s*([A-Z0-9]+)", md.read_text(), re.MULTILINE)
            if m:
                return m.group(1)
    return None


def recording_signatures(slug: str) -> tuple[set[str], set[str]]:
    """Signatures to identify a recording's track on the map: exact <trk><name>s AND
    the date strings (YYYY-MM-DD) from the *_actual* filenames. gpx_to_caltopo titles
    these tracks from the FILENAME ('<peaks> (<date>)'), not the <trk><name>, so the
    date is the reliable discriminator (source tracks never carry it). Only the auto-
    synced recordings (*_actual*) — never the manually-placed map-export side files."""
    kdir = GPX / slug / "_kyle_existing"
    titles, dates = set(), set()
    if not kdir.is_dir():
        return titles, dates
    for f in list(kdir.glob("*_actual*.gpx")) + list(kdir.glob("*_actual*.GPX")):
        d = re.search(r"\d{4}-\d{2}-\d{2}", f.name)
        if d:
            dates.add(d.group(0))
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        for trk in root.iter(NS + "trk"):
            n = trk.find(NS + "name")
            if n is not None and n.text:
                titles.add(n.text.strip())
    return titles, dates


def slugs_with_recordings():
    return sorted(p.parent.name for p in GPX.glob("*/_kyle_existing"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.slug and not args.all:
        ap.error("pass --slug <slug> or --all")

    targets = slugs_with_recordings() if args.all else [args.slug]
    total = changed = 0
    for slug in targets:
        titles, dates = recording_signatures(slug)
        mid = map_id_for(slug)
        if (not titles and not dates) or not mid:
            continue
        try:
            s = caltopo_session(mid)
            shapes = s.getFeatures(featureClass="Shape")
        except Exception as e:
            print(f"  {slug} ({mid}): skip ({e})")
            continue
        for f in shapes:
            props = f.get("properties") or {}
            title = props.get("title", "").strip()
            if "recommended route" in title.lower():
                continue   # never the composed route
            if not (title in titles or any(d in title for d in dates)):
                continue
            total += 1
            cur = props.get("stroke")
            if cur == KYLE_COLOR:
                print(f"  ok   {slug} ({mid}): {props.get('title')!r} already blue")
                continue
            print(f"  {'FIX ' if args.apply else 'WOULD'} {slug} ({mid}): "
                  f"{props.get('title')!r} {cur} -> {KYLE_COLOR}")
            if args.apply:
                s.editFeature(id=f.get("id"), className="Shape",
                              properties={**props, "stroke": KYLE_COLOR})
                changed += 1
    print(f"\n{total} Kyle track(s) matched; {changed} recolored.")


if __name__ == "__main__":
    main()
