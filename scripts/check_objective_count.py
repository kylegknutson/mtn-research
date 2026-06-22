#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_objective_count.py — the route's objectives must match the report's declared peaks.

hunts_peak shipped with a `peaks_only.gpx` that wrongly contained 3 summits (Hunts Pk
plus two already-climbed neighbors) while the report declared 1 peak — so the route-
builder linked phantom objectives and cut a corner between peaks that weren't even in
the report. This catches that class of bug: the number of summit markers in
`gpx/<slug>/*_peaks_only.gpx` must equal the report's declared objective count.

Declared count = peaks.yml `objective_ids` length if present, else the report
frontmatter `peak_ids` length, else frontmatter `peaks:`.

    scripts/check_objective_count.py            # all reports
    scripts/check_objective_count.py hunts_peak
    scripts/check_objective_count.py --strict
"""
from __future__ import annotations
import argparse, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
NS = "{http://www.topografix.com/GPX/1/1}"


def fm(p: Path) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def declared_count(slug: str, meta: dict):
    yml = GPX / slug / "peaks.yml"
    if yml.exists():
        cfg = yaml.safe_load(yml.read_text()) or {}
        if cfg.get("objective_ids"):
            return len(cfg["objective_ids"]), "peaks.yml objective_ids"
    if meta.get("peak_ids"):
        return len(meta["peak_ids"]), "frontmatter peak_ids"
    if meta.get("peaks"):
        try:
            return int(meta["peaks"]), "frontmatter peaks"
        except (TypeError, ValueError):
            pass
    return None, None


# nearby.include context peaks are labeled with a distance-from-objective suffix,
# e.g. "Pk C (13228', UNCLIMBED, 0.7mi)" — those are intentional map context, NOT
# objectives, so they don't count against the declared objective total.
CONTEXT_SUFFIX = re.compile(r",\s*[\d.]+\s*mi\)\s*$")


def peaks_only_count(slug: str):
    pk = next((GPX / slug).glob("*peaks_only*.gpx"), None)
    if not pk:
        return None
    try:
        root = ET.parse(pk).getroot()
    except ET.ParseError:
        return None
    n = 0
    for w in root.iter(NS + "wpt"):
        nm = w.find(NS + "name")
        if nm is not None and nm.text and CONTEXT_SUFFIX.search(nm.text):
            continue   # nearby context peak, not an objective
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    bad = 0
    checked = 0
    for sub in ("peaks", "trips"):
        for p in sorted((DOCS / sub).glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index."):
                continue
            base = p.stem.split(".")[0]
            if args.slug and base != args.slug and p.stem != args.slug:
                continue
            if p.stem.count("."):      # climber variant shares the base gpx
                continue
            meta = fm(p)
            declared, src = declared_count(base, meta)
            actual = peaks_only_count(base)
            if declared is None or actual is None:
                continue
            checked += 1
            if actual != declared:
                bad += 1
                print(f"MISMATCH {p.name:30s} peaks_only has {actual} summit(s) but "
                      f"{declared} declared ({src}) — phantom objectives? "
                      f"regen with build_peak_gpx.py --slug {base}")
            else:
                pass
    print(f"\n{checked} report(s) — {bad} objective-count mismatch.")
    if args.strict and bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
