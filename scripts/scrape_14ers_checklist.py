#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "PyYAML"]
# ///
"""
scrape_14ers_checklist.py — a climber's climbed peaks from their public 14ers
checklist, mapped to peak_db ids.

A 14ers user checklist (`/php14ers/checklist.php?usernum=<N>&checklist={13ers|14ers}`)
is public + server-rendered: each climbed peak is a row
  <tr onclick="stats('13ers','<14ers_id>','<name>','<usernum>','1')">
This fetches the page (no auth), pulls the climbed 14ers ids, and maps them to
peak_db ids via `fourteeners_id` — giving a friend's climbed list the same shape
as Kyle's peak_db ascents, so the rest of the tooling is climber-agnostic.

Importable: `climbed_peak_db_ids(url) -> set[int]`.

Usage:
    scripts/scrape_14ers_checklist.py --climber emily          # reads checklist_url from profile
    scripts/scrape_14ers_checklist.py --url "https://www.14ers.com/php14ers/checklist.php?usernum=45697&checklist=13ers"
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import requests, yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
from peak_db_client import peaks  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (mtn-research checklist sync)"}
ROW = re.compile(r"""stats\(["']?(?:13ers|14ers)["']?,\s*["']?(\d+)["']?,\s*["']([^"']+)["']""", re.I)


def climbed_14ers_ids(url: str) -> dict[str, str]:
    """Return {14ers_id: name} for the climber's climbed peaks on the checklist."""
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    out = {}
    for m in ROW.finditer(r.text):
        out[m.group(1)] = m.group(2)
    return out


def climbed_peak_db_ids(url: str) -> set[int]:
    """Map the checklist's climbed 14ers ids onto peak_db ids (via fourteeners_id)."""
    ids14 = set(climbed_14ers_ids(url))
    by_f = {str(p.get("fourteeners_id")): p["id"] for p in peaks() if p.get("fourteeners_id")}
    return {by_f[i] for i in ids14 if i in by_f}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--climber")
    ap.add_argument("--url")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    url = args.url
    if not url and args.climber:
        prof = yaml.safe_load((ROOT / "climbers" / f"{args.climber}.yml").read_text())
        url = ((prof.get("climbed_list") or {}).get("checklist_url"))
    if not url:
        sys.exit("Provide --url or --climber (with checklist_url in the profile).")

    ids14 = climbed_14ers_ids(url)
    all_peaks = peaks()
    by_f = {str(p.get("fourteeners_id")): p for p in all_peaks if p.get("fourteeners_id")}
    matched = [by_f[i] for i in ids14 if i in by_f]
    ranked13 = [p for p in matched if p.get("ranked") and 13000 <= p.get("elevation_ft", 0) < 14000]
    unmatched = [ids14[i] for i in ids14 if i not in by_f]

    print(f"checklist: {url}")
    print(f"  climbed peaks on checklist: {len(ids14)}")
    print(f"  mapped to peak_db:          {len(matched)}")
    print(f"  …of which ranked 13ers:     {len(ranked13)}")
    if unmatched and not args.quiet:
        print(f"  unmatched (not in peak_db): {len(unmatched)} → {unmatched[:8]}")
    if not args.quiet:
        print("\npeak_db ids climbed (ranked 13ers):")
        print("  " + ", ".join(str(p["id"]) for p in sorted(ranked13, key=lambda x: x["id"])))


if __name__ == "__main__":
    main()
