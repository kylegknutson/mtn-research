#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests"]
# ///
"""
climber.py — shared climber helpers so the rest of the tooling is climber-agnostic.

  load_profile(slug)  -> dict
  climbed_ids(slug)    -> set[int]   peak_db ids climbed by that climber
       • source: peak_db          → Supabase ascents (Kyle)
       • source: 14ers_checklist  → scraped from their public 14ers checklist (friends)

CLI prints a quick summary:
    scripts/climber.py kyle
    scripts/climber.py emily
"""
from __future__ import annotations
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
sys.path.insert(0, str(ROOT / "scripts"))


def load_profile(slug: str) -> dict:
    p = ROOT / "climbers" / f"{slug}.yml"
    if not p.exists():
        raise SystemExit(f"No climber profile: {p}")
    return yaml.safe_load(p.read_text())


def climbed_ids(slug: str) -> set[int]:
    prof = load_profile(slug)
    src = (prof.get("climbed_list") or {}).get("source")
    if src == "peak_db":
        from peak_db_client import ascents
        return {a["peak_id"] for a in ascents()}
    if src == "14ers_checklist":
        from scrape_14ers_checklist import climbed_peak_db_ids
        url = prof["climbed_list"]["checklist_url"]
        return climbed_peak_db_ids(url)
    raise SystemExit(f"Unknown climbed_list.source: {src!r} for {slug}")


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "kyle"
    prof = load_profile(slug)
    ids = climbed_ids(slug)
    print(f"{prof['name']} ({slug}) — source: {(prof.get('climbed_list') or {}).get('source')}")
    print(f"  climbed peak_db peaks: {len(ids)}")


if __name__ == "__main__":
    main()
