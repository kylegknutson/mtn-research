#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "PyYAML"]
# ///
"""
check_sources_login.py — confirm the three research sources are logged in.

Goal-5 helper: before any research, verify 14ers + listsofjohn + peakbagger
are authenticated. Prints each site's status + detected username and exits
non-zero if any is logged out — so a session (or `research_peak.py` later)
can hard-fail fast instead of pulling logged-out data.

This uses its OWN persistent Playwright profile (separate from the Claude-in-
Chrome / Playwright-MCP browser). One-time setup per Mac:

    # 1. install the browser binary (once)
    uv run --with playwright playwright install chromium
    # 2. log in interactively (opens a window; log into all 3, then press Enter)
    scripts/check_sources_login.py --login

Thereafter:
    scripts/check_sources_login.py            # headless check, exit 1 if any logged out
    scripts/check_sources_login.py --climber kyle

Profile lives at ~/Library/Application Support/mtn-research/pw-profile (not
iCloud-synced — browser profiles shouldn't sync).
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = Path.home() / "Library/Application Support/mtn-research/pw-profile"

# (key, url, regex that matches ONLY when logged in; group 1 = username if the
#  site exposes it). 14ers is detected by its Log Out link (the "hi <name>"
#  greeting is unreliable — it false-matched "...Basin..." page text once and
#  isn't the login username anyway), so no username is asserted for it.
SITES = [
    ("14ers",       "https://www.14ers.com/",
        re.compile(r"mode=logout|Log\s*Out", re.I)),
    ("listsofjohn", "https://listsofjohn.com/",
        re.compile(r"Signed in as\s+([A-Za-z0-9_]+)", re.I)),
    ("peakbagger",  "https://peakbagger.com/",
        re.compile(r"Logged in:\s*([^\n|<]+)", re.I)),
]


def load_expected(climber: str) -> dict:
    p = ROOT / "climbers" / f"{climber}.yml"
    if not p.exists():
        return {}
    return (yaml.safe_load(p.read_text()) or {}).get("accounts", {}) or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true",
                    help="Open a headed window to log in interactively, then verify.")
    ap.add_argument("--climber", default="kyle", help="Climber slug for expected usernames.")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not available. Run: uv run --with playwright playwright install chromium")

    expected = load_expected(args.climber)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    results = {}

    with sync_playwright() as p:
        # Prefer the real Chrome binary (channel="chrome") — Cloudflare (peakbagger)
        # trusts it far more than Playwright's bundled Chromium, which it often
        # blocks at the bot check. Fall back to bundled Chromium if Chrome isn't found.
        ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        try:
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=not args.login, channel="chrome",
                user_agent=ua, chromium_sandbox=True)
        except Exception:
            try:
                ctx = p.chromium.launch_persistent_context(
                    str(PROFILE_DIR), headless=not args.login, user_agent=ua,
                    chromium_sandbox=True)
            except Exception as e:
                sys.exit(f"Could not launch a browser ({e}).\n"
                         f"Run once: uv run --with playwright playwright install chromium")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if args.login:
            print("Opening each site. Log into any that aren't, then press Enter here.")
            for key, url, _ in SITES:
                page.goto(url, wait_until="domcontentloaded")
                print(f"  → {key}: {url}")
            input("Press Enter when all three are logged in… ")

        for key, url, rx in SITES:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)  # let any Cloudflare / JS settle
                body = page.content()
                m = rx.search(body)
                user = (m.group(1).strip() if (m and m.lastindex) else None)
                results[key] = ("LOGGED IN", user) if m else ("logged out", None)
            except Exception as e:
                results[key] = ("error", str(e)[:60])
        ctx.close()

    print(f"\n{'site':14} {'status':12} {'user':20} expected")
    all_ok = True
    for key, _u, _ in SITES:
        status, user = results.get(key, ("?", None))
        exp = expected.get(key, "—")
        ok = status == "LOGGED IN"
        all_ok &= ok
        flag = "" if (not user or not exp or exp == "—" or user.lower().startswith(str(exp).lower()[:5])) else "  ⚠ mismatch"
        print(f"{key:14} {status:12} {str(user or '—'):20} {exp}{flag}")

    if not all_ok:
        print("\nOne or more sources are logged out. Run with --login to fix.")
        sys.exit(1)
    print("\nAll three sources logged in.")


if __name__ == "__main__":
    main()
