#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests"]
# ///
"""
preflight.py — the "flight check" before an unattended report build.

Front-loads every blocker/decision so the build can run start-to-finish with no
mid-flight prompts. Run this at kickoff; it prints a GO / NO-GO card. The one
thing it CAN'T do itself is the live 3-source login check (that lives in the
Playwright-MCP browser the user actually logs into) — so it prints the exact
per-site indicators to verify there, and the LLM confirms them before building.

Checks:
  • Resolve each named/numbered peak → peak_db id (+ elev/class/rank/owner-status).
    Ambiguous or unresolved names are flagged HERE (ask the user now, not mid-build).
  • CalTopo creds present (scripts/cts.ini).
  • Climber profile present (climbers/<climber>.yml).
  • Prints the per-site login indicators to confirm in the MCP browser.

Usage:
    scripts/preflight.py --peaks "Star, Taylor, Italian" --range Elk
    scripts/preflight.py --peaks "301,365,420" --climber kyle
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")

LOGIN_INDICATORS = {
    "14ers.com":        'a "Log Out" link present (and your username, e.g. "Basin", top-right)',
    "listsofjohn.com":  'NO "log in to view ascents" text on a peak page (logged-in shows your ascents)',
    "peakbagger.com":   'on the HOME page (Default.aspx): "Logged in: <name>" and/or a personalized "My Home Page" → climber.aspx?cid=<id> link. The cid link is the reliable signal (the "Logged in:" string and the always-present "Log In" anchor are both unreliable via fetch / on peak pages).',
}


def resolve(token: str, rng: str | None, allp: list[dict]):
    token = token.strip()
    if not token:
        return None
    if token.lstrip("-").isdigit():
        p = next((x for x in allp if x["id"] == int(token)), None)
        return ("ok", [p]) if p else ("unresolved", [])
    cands = [p for p in allp if token.lower() in (p["display_name"] or "").lower()]
    if rng:
        cands = [p for p in cands if (p.get("range") or "").lower() == rng.lower()]
    if len(cands) == 1:
        return ("ok", cands)
    if len(cands) == 0:
        return ("unresolved", [])
    return ("ambiguous", cands)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peaks", required=True, help="comma-separated names or peak_db ids")
    ap.add_argument("--range", help="optional range filter to disambiguate names (e.g. Elk)")
    ap.add_argument("--climber", default="kyle")
    args = ap.parse_args()

    blockers = []
    try:
        from peak_db_client import peaks, ascents
        allp = peaks()
        owner_done = {a["peak_id"] for a in ascents()} if args.climber == "kyle" else set()
    except ModuleNotFoundError:
        sys.exit("peak_db unavailable — run preflight on a machine with the peak_db checkout")

    print("=" * 64)
    print(f"PREFLIGHT — climber: {args.climber}")
    print("=" * 64)

    print("\n1) PEAK RESOLUTION")
    resolved = []
    for tok in args.peaks.split(","):
        if not tok.strip():
            continue
        status, cands = resolve(tok, args.range, allp)
        if status == "ok":
            p = cands[0]
            done = "✓climbed" if p["id"] in owner_done else "unclimbed"
            resolved.append(p)
            print(f"   ✓ {tok.strip():14} → {p['display_name']!r} id={p['id']} "
                  f"{p['elevation_ft']}ft cls{p['yds_class']} rank{p.get('co_rank')} [{done}]")
        elif status == "ambiguous":
            names = ", ".join(f"{c['display_name']}(id={c['id']},{c.get('range')})" for c in cands[:6])
            print(f"   ⚠ {tok.strip():14} → AMBIGUOUS: {names}  → ask the user / add --range")
            blockers.append(f"ambiguous peak: {tok.strip()}")
        else:
            print(f"   ✗ {tok.strip():14} → NOT FOUND in peak_db → ask the user (informal name?)")
            blockers.append(f"unresolved peak: {tok.strip()}")

    print("\n2) CREDS / PROFILE")
    cts = ROOT / "scripts" / "cts.ini"
    print(f"   {'✓' if cts.exists() else '✗'} CalTopo creds: scripts/cts.ini")
    if not cts.exists():
        blockers.append("missing scripts/cts.ini")
    prof = ROOT / "climbers" / f"{args.climber}.yml"
    print(f"   {'✓' if prof.exists() else '✗'} climber profile: climbers/{args.climber}.yml")
    if not prof.exists():
        blockers.append(f"missing climbers/{args.climber}.yml")

    print("\n3) LOGIN CHECK (confirm in the Playwright-MCP browser — hard stop if any is out)")
    for site, ind in LOGIN_INDICATORS.items():
        print(f"   • {site:18} {ind}")

    if resolved:
        ids = ",".join(str(p["id"]) for p in resolved)
        print(f"\n   resolved objective_ids: {ids}")

    print("\n" + "=" * 64)
    if blockers:
        print("NO-GO — resolve first:\n   - " + "\n   - ".join(blockers))
        sys.exit(1)
    print("GO ✓ — peaks resolved, creds present. Confirm the 3 logins above, then build.")
    print("=" * 64)


if __name__ == "__main__":
    main()
