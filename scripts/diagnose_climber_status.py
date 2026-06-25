#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "PyYAML"]
# ///
"""
diagnose_climber_status.py — explain WHY a friend shows climbed/not-yet for a
set of peaks, peak-by-peak. The "Other climbers" line maps a friend's 14ers
checklist ids onto peak_db ids via each peak's `fourteeners_id`; if a peak has
no `fourteeners_id` (common for unranked "PT" points), NO friend can ever match
it — it shows "not yet" forever even after they climbed it. This surfaces that.

    scripts/diagnose_climber_status.py --climber shawn --ids 645 707 726
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
sys.path.insert(0, str(ROOT / "scripts"))
from peak_db_client import peaks  # noqa: E402
from scrape_14ers_checklist import climbed_14ers_ids  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--climber", required=True)
    ap.add_argument("--ids", type=int, nargs="+", required=True)
    ap.add_argument("--url", help="override the profile checklist_url (for testing)")
    args = ap.parse_args()

    prof = yaml.safe_load((ROOT / "climbers" / f"{args.climber}.yml").read_text())
    url = args.url or (prof.get("climbed_list") or {}).get("checklist_url")
    print(f"climber: {prof.get('name')} ({args.climber})")
    print(f"checklist: {url}\n")

    checklist = climbed_14ers_ids(url)          # {14ers_id: name} climbed
    by_id = {p["id"]: p for p in peaks()}

    for pid in args.ids:
        p = by_id.get(pid)
        if not p:
            print(f"  {pid}: NOT IN peak_db"); continue
        fid = p.get("fourteeners_id")
        name = p.get("display_name") or p.get("name") or str(pid)
        if not fid:
            verdict = "✗ peak has NO fourteeners_id → friend can NEVER match (bug)"
        elif str(fid) in checklist:
            verdict = f"✓ on checklist as '{checklist[str(fid)]}' → CLIMBED"
        else:
            verdict = "— not on this climber's checklist"
        print(f"  {pid} {str(name).strip(chr(34)):28} f14_id={str(fid):>7}  {verdict}")


if __name__ == "__main__":
    main()
