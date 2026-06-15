#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
sync_status.py — set each report's frontmatter `status:` from peak_db ascents.

A report is `climbed` when every `objective_ids` peak in its `gpx/<slug>/peaks.yml`
is in the climb log, else `unclimbed`. This is the machine field the index table's
Status column reads; the home map derives separately (gen_peak_map.py). Reports
without `objective_ids` are skipped (can't be determined).

    scripts/sync_status.py            # apply: rewrite stale frontmatter status
    scripts/sync_status.py --check    # exit 1 if any report's status is stale (no writes)

Needs peak_db access (SUPABASE_URL/SUPABASE_SECRET_KEY env or the iCloud .env), so
it runs on a Mac, not in CI. Called by refresh_from_peakdb.py.
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"


def climbed_ids() -> set[int]:
    sys.path.insert(0, PEAKDB)
    from peak_db_client import ascents as _ascents
    return {a["peak_id"] for a in _ascents() if a.get("peak_id") is not None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 on drift; don't write")
    args = ap.parse_args()

    climbed = climbed_ids()
    stale = []
    for sub in ("peaks", "trips"):
        for md in sorted((ROOT / "docs" / sub).glob("*.md")):
            if md.stem.count(".") or md.stem == "index":
                continue
            yml = ROOT / "gpx" / md.stem / "peaks.yml"
            if not yml.exists():
                continue
            ids = (yaml.safe_load(yml.read_text()) or {}).get("objective_ids") or []
            if not ids:
                continue
            want = "climbed" if all(i in climbed for i in ids) else "unclimbed"
            text = md.read_text()
            m = re.search(r"^status:\s*(\S+)\s*$", text, re.M)
            cur = m.group(1) if m else None
            if cur != want:
                stale.append((md, cur, want))
                if not args.check and m:
                    md.write_text(text[:m.start()] + f"status: {want}" + text[m.end():])
                    print(f"  {md.name}: {cur} → {want}")

    if args.check:
        if stale:
            print(f"STALE status in {len(stale)} report(s) — run scripts/sync_status.py:", file=sys.stderr)
            for md, cur, want in stale:
                print(f"  {md.name}: {cur} → {want}", file=sys.stderr)
            sys.exit(1)
        print("report statuses current ✓")
    else:
        print(f"synced {len(stale)} report status(es)")
    return [md for md, _, _ in stale]


if __name__ == "__main__":
    main()
