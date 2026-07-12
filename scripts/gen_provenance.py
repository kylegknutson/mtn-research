#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
gen_provenance.py — the "distilled from N recorded GPS tracks" note on every report.

Kyle (2026-07-11) wanted the share pages' provenance note on the normal reports too.
Generator-managed (like quickstats) so it can't drift: a marked block is inserted
right under the overview-map image and refreshed from the gpx dir on every run.

  <!-- PROVENANCE_START -->
  *The recommended route was distilled from **N recorded GPS tracks** of real trips
  (14ers.com · ListsofJohn · peakbagger · Kyle's recordings) — all layered on the
  [interactive CalTopo research map](https://caltopo.com/m/<id>).*
  <!-- PROVENANCE_END -->

The source list is built per-slug from sources.json counts + presence of Kyle's own
track files, so it never overclaims. Count = the route builder's source pool (same
exclusions). Reports without a gpx dir / recommended route are skipped.

    scripts/gen_provenance.py            # update all reports
    scripts/gen_provenance.py --check    # exit 1 if any block is stale (gate)
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
GPX = ROOT / "gpx"
START, END = "<!-- PROVENANCE_START -->", "<!-- PROVENANCE_END -->"
SKIP = ("peaks_only", "landmark", "trailhead", "recommended", "_drive",
        "drive_in", "waypoints", "summit", "target")
SRC_LABEL = {"14ers": "14ers.com", "listsofjohn": "ListsofJohn", "peakbagger": "peakbagger"}


def source_count(slug: str) -> int:
    return sum(1 for f in (GPX / slug).glob("*.gpx")
               if not any(s in f.name.lower() for s in SKIP))


def source_list(slug: str) -> str:
    d = GPX / slug
    parts = []
    sj = d / "sources.json"
    if sj.exists():
        counts = json.loads(sj.read_text())
        for key in ("14ers", "listsofjohn", "peakbagger"):
            c = counts.get(key)
            n = c.get("found", c) if isinstance(c, dict) else c
            if n:
                parts.append(SRC_LABEL[key])
    if any(True for f in d.glob("*.gpx")
           if ("kyle" in f.name.lower() or "caltopo" in f.name.lower())
           and not any(s in f.name.lower() for s in SKIP)):
        parts.append("Kyle's recordings")
    return " · ".join(parts) if parts else "recorded trips"


def block(slug: str, caltopo_id: str | None) -> str:
    n = source_count(slug)
    tail = (f" — all layered on the [interactive CalTopo research map]"
            f"(https://caltopo.com/m/{caltopo_id})." if caltopo_id else ".")
    return (f"{START}\n*Note: the recommended route was distilled from **{n} recorded GPS "
            f"tracks** of real trips ({source_list(slug)}){tail}*\n{END}")


def apply(md: Path, check: bool):
    slug = md.stem.split(".")[0]
    d = GPX / slug
    if not d.is_dir() or not list(d.glob("*recommended*.gpx")) or source_count(slug) == 0:
        return None
    text = md.read_text()
    m = re.search(r"^caltopo_id:\s*([A-Z0-9]+)", text, re.M)
    blk = block(slug, m.group(1) if m else None)
    if START in text and END in text:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END), blk, text, count=1, flags=re.S)
    else:
        img = re.search(rf"^!\[[^\]]*\]\(\.\./maps/{slug}\.png\)\s*$", text, re.M)
        if not img:
            return None
        i = img.end()
        new = text[:i] + "\n" + blk + text[i:]
    # blank lines around the block — butted neighbors merge paragraphs / setext-mangle
    new = new.replace(f"{END}\n---", f"{END}\n\n---")
    new = re.sub(rf"(\.png\)) *\n({re.escape(START)})", r"\1\n\n\2", new)
    if new != text:
        if not check:
            md.write_text(new)
        return md.name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    changed = []
    for sub in ("peaks", "trips"):
        for md in sorted((DOCS / sub).glob("*.md")):
            if md.stem == "index" or md.stem.startswith("index."):
                continue
            r = apply(md, args.check)
            if r:
                changed.append(f"{sub}/{r}")
    if args.check:
        if changed:
            print("STALE provenance notes — run scripts/gen_provenance.py:", file=sys.stderr)
            for c in changed:
                print("  " + c, file=sys.stderr)
            sys.exit(1)
        print("provenance notes current")
    else:
        print(f"updated {len(changed)} note(s)" + (": " + ", ".join(changed) if changed else ""))


if __name__ == "__main__":
    main()
