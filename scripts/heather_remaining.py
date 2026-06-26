#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
heather_remaining.py — recompute which of Heather's candidate activity IDs are still
NOT downloaded (gpx/heather/_all_ids.txt minus the IDs already on disk), write
gpx/heather/_remaining_ids.txt, and print the count + a JS array literal of the IDs
(handy for pasting into a Playwright evaluate).

    scripts/heather_remaining.py           # write _remaining_ids.txt, print count
    scripts/heather_remaining.py --js      # also print the JS array literal
    scripts/heather_remaining.py --js --limit 50   # only the first N (batch a pull)
"""
from __future__ import annotations
import argparse, re
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "gpx" / "heather"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--js", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    allids = [l.strip() for l in (D / "_all_ids.txt").read_text().splitlines() if l.strip()]
    have = {m.group(1) for f in D.glob("*.gpx")
            for m in [re.search(r"__(\d+)\.gpx$", f.name)] if m}
    miss = [i for i in allids if i not in have]
    (D / "_remaining_ids.txt").write_text("\n".join(miss) + "\n")

    print(f"on disk: {len(have)}  |  total candidates: {len(allids)}  |  remaining: {len(miss)}")
    if args.js:
        ids = miss[:args.limit] if args.limit else miss
        print(f"\n// {len(ids)} ids")
        print("[" + ",".join(f'"{i}"' for i in ids) + "]")


if __name__ == "__main__":
    main()
