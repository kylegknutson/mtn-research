#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""
recolor_recommended.py — force every map's composed recommended route to magenta.

Convention (matches the PNG legend + gpx_to_caltopo): the "Recommended route
(composed)" line is always #E6008C. Older maps uploaded it with a palette color
(Emily's clohesey route was #00AA00 — green, same as a 14ers track). This fixes
existing maps in place via editFeature, reading each report's caltopo_id.

    scripts/recolor_recommended.py --slug clohesey_four.emily --apply
    scripts/recolor_recommended.py --all            # dry-run every report
    scripts/recolor_recommended.py --all --apply
"""
from __future__ import annotations
import argparse, logging, re
from pathlib import Path

logging.basicConfig(level=logging.ERROR)
logging.getLogger("caltopo_python").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "scripts" / "cts.ini"
ACCOUNT = "kyleg.knutson@gmail.com"
MAGENTA = "#E6008C"


def reports():
    for sub in ("peaks", "trips"):
        for p in sorted((ROOT / "docs" / sub).glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index."):
                continue
            yield p


def caltopo_id(md: Path):
    m = re.search(r"^caltopo_id:\s*(\S+)", md.read_text(), re.M)
    return m.group(1).strip() if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", help="report stem (e.g. clohesey_four.emily); default all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    targets = []
    for md in reports():
        if args.slug and md.stem != args.slug:
            continue
        mid = caltopo_id(md)
        if mid:
            targets.append((md.stem, mid))
    if not targets:
        print("no matching report with a caltopo_id"); return

    from caltopo_python import CaltopoSession
    changed = total = 0
    for stem, mid in targets:
        try:
            s = CaltopoSession(domainAndPort="caltopo.com", mapID=mid,
                               configpath=str(CONFIG), account=ACCOUNT)
            shapes = s.getFeatures(featureClass="Shape")
        except Exception as e:
            print(f"  {stem} ({mid}): skip ({e})"); continue
        for f in shapes:
            props = f.get("properties") or {}
            title = props.get("title", "")
            if "recommended route" not in title.lower():
                continue
            total += 1
            cur = props.get("stroke")
            if cur == MAGENTA:
                print(f"  ok   {stem} ({mid}): already magenta")
                continue
            print(f"  {'FIX ' if args.apply else 'WOULD'} {stem} ({mid}): {cur} -> {MAGENTA}")
            if args.apply:
                s.editFeature(id=f.get("id"), className="Shape",
                              properties={**props, "stroke": MAGENTA})
                changed += 1
    print(f"\n{total} recommended-route line(s); {changed} recolored.")


if __name__ == "__main__":
    main()
