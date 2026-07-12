#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
regen_overview_maps.py — rebuild overview PNGs across the fleet.

For marker/legend/extent format changes in make_overview_map.py: every existing
PNG must be regenerated in the same change (CLAUDE.md format-change rule).
Titles default to each report's H1 (make_overview_map handles that), so a bulk
regen never clobbers custom titles.

    scripts/regen_overview_maps.py            # every slug with a PNG + gpx dir
    scripts/regen_overview_maps.py slug1 slug2
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def main():
    slugs = sys.argv[1:]
    if not slugs:
        slugs = sorted(p.stem for p in (ROOT / "docs" / "maps").glob("*.png")
                       if (ROOT / "gpx" / p.stem).is_dir())
    fails = []
    for i, slug in enumerate(slugs, 1):
        print(f"[{i}/{len(slugs)}] {slug}")
        r = subprocess.run([str(SCRIPTS / "make_overview_map.py"), slug],
                           capture_output=True, text=True)
        if r.returncode != 0:
            fails.append(slug)
            print(f"  FAIL: {(r.stderr or r.stdout)[-300:]}")
    print(f"\n{len(slugs) - len(fails)}/{len(slugs)} PNG(s) regenerated"
          + (f"; FAILED: {', '.join(fails)}" if fails else ""))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
