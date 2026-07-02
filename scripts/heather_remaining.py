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
    ap.add_argument("--add-unavailable", nargs="+", metavar="ID",
                    help="append ids to _unavailable_ids.txt (export redirects to "
                         "/dashboard: private/hidden/export-restricted) and exit")
    args = ap.parse_args()

    unavailf = D / "_unavailable_ids.txt"
    if args.add_unavailable:
        cur = {l.strip() for l in unavailf.read_text().splitlines() if l.strip()} if unavailf.exists() else set()
        new = [i for i in args.add_unavailable if i not in cur]
        if new:
            with unavailf.open("a") as fh:
                fh.write("\n".join(new) + "\n")
        print(f"recorded {len(new)} unavailable id(s); _unavailable_ids.txt now has {len(cur) + len(new)}")
        return

    allids = [l.strip() for l in (D / "_all_ids.txt").read_text().splitlines() if l.strip()]
    have = {m.group(1) for f in D.glob("*.gpx")
            for m in [re.search(r"__(\d+)\.gpx$", f.name)] if m}
    # ids fetched OK but deliberately not saved (rides / no-GPS) — permanently
    # excluded so they don't reappear at the top of every batch forever.
    skipf = D / "_skipped_ids.txt"
    skipped = {l.strip() for l in skipf.read_text().splitlines() if l.strip()} if skipf.exists() else set()
    # ids whose export redirects to /dashboard (private/hidden/export-restricted) —
    # undownloadable to a follower; excluded so remaining can converge to 0.
    unavail = {l.strip() for l in unavailf.read_text().splitlines() if l.strip()} if unavailf.exists() else set()
    miss = [i for i in allids if i not in have and i not in skipped and i not in unavail]
    (D / "_remaining_ids.txt").write_text("\n".join(miss) + "\n")

    print(f"on disk: {len(have)}  |  total candidates: {len(allids)}  |  "
          f"skipped(rides/no-gps): {len(skipped)}  |  unavailable(private): {len(unavail)}  |  "
          f"remaining: {len(miss)}")
    if args.js:
        ids = miss[:args.limit] if args.limit else miss
        print(f"\n// {len(ids)} ids")
        print("[" + ",".join(f'"{i}"' for i in ids) + "]")


if __name__ == "__main__":
    main()
