#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""
verify_peakbagger_ids.py — audit (and fix) peak_db's peakbagger_id column
against the peakbagger cross-link on each listsofjohn.com peak page.

Why: peak_db's peakbagger_id is systematically wrong — vestal_arrow_trinities
(2026-07-10) had all 5 wrong and jupiter_pigeon_turret 4 of 5 (Vestal 5752 →
5852, Pigeon 5690 → 5856). The authoritative id lives on each peak's LoJ page,
which cross-links peakbagger.com/peak.aspx?pid=NNNN (LoJ peak id == peak_db id).

Sweeps LoJ in the shared persistent Playwright profile (same one as
sweep_gpx.py / check_sources_login.py — LoJ works headless there; no
Cloudflare). Fetches are rate-limited (default 1/s) and cached in
tmp_pb_verify.json (gitignored) so an interrupted sweep resumes for free and
--apply never refetches.

Usage:
    scripts/verify_peakbagger_ids.py                  # sweep ALL peaks, report diffs (dry run)
    scripts/verify_peakbagger_ids.py --ids 96,127     # subset (peak_db ids)
    scripts/verify_peakbagger_ids.py --apply          # sweep if needed + write fixes to peak_db
    scripts/verify_peakbagger_ids.py --fresh          # ignore the cache, refetch
    scripts/verify_peakbagger_ids.py --delay 2        # slower polling
    scripts/verify_peakbagger_ids.py --headed         # visible browser (debug)

--apply patches BOTH peakbagger_id and peakbagger_url (they must stay in sync;
same shape as peak_db/patch_peakbagger_culebra_redmtn.py) for every MISMATCH
and DB-MISSING row, and logs old→new to tmp_pb_verify_applied.json so a bad
apply is reversible. Rows whose LoJ page has no peakbagger cross-link are
reported but never written.

NEGATIVE peak_db ids are skipped entirely: those are the manually-added
out-of-state peaks (state highpoints, Sierra, NE 111ers, Cascades) where
peak_db id != LoJ id — /peak/<negative> is a garbage URL, so their pb ids
can't be verified this way (measured 2026-07-10: all 206 skips were negative).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tmp_pb_verify.json"
APPLIED_LOG = ROOT / "tmp_pb_verify_applied.json"
PROFILE_DIR = Path.home() / "Library/Application Support/mtn-research/pw-profile"
PB_RE = re.compile(r"peakbagger\.com/peak\.aspx\?pid=(\d+)", re.I)
LOGGED_OUT_RE = re.compile(r"log in to view ascents", re.I)

sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
from peak_db_client import _load_env, peaks  # noqa: E402


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


def sweep(ids: list[int], cache: dict, delay: float, headed: bool) -> None:
    """Fetch each LoJ peak page and record its peakbagger pid in the cache."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright missing. Run: uv run --with playwright playwright install chromium")

    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    fetch_js = ("async (id) => { const r = await fetch('/peak/'+id, {credentials:'include'}); "
                "return {status: r.status, text: await r.text()}; }")
    logged_out = warned = False

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=not headed, channel="chrome",
                user_agent=ua, chromium_sandbox=True)
        except Exception:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=not headed, user_agent=ua,
                chromium_sandbox=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://listsofjohn.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        for n, pid in enumerate(ids, 1):
            try:
                r = page.evaluate(fetch_js, pid)
                if r["status"] != 200:
                    cache[str(pid)] = {"error": f"HTTP {r['status']}"}
                else:
                    html = r["text"]
                    if not warned and LOGGED_OUT_RE.search(html):
                        logged_out = warned = True
                        print("  WARN: LoJ shows logged OUT in the automation profile "
                              "(continuing — the cross-link may still render)")
                    m = PB_RE.search(html)
                    cache[str(pid)] = {"pid": int(m.group(1)) if m else None}
            except Exception as e:  # network hiccup: record + move on, resumable via --fresh-less rerun
                cache[str(pid)] = {"error": str(e)[:120]}
            if n % 25 == 0 or n == len(ids):
                CACHE.write_text(json.dumps(cache, indent=1))
                print(f"  … swept {n}/{len(ids)}")
            # abort early if logged out AND the cross-link really doesn't render
            if logged_out and n >= 5 and not any(
                    cache.get(str(i), {}).get("pid") for i in ids[:n]):
                ctx.close()
                sys.exit("✗ STOP: logged out and no peakbagger cross-links render on LoJ.\n"
                         "  Fix: scripts/check_sources_login.py --login   then re-run.")
            time.sleep(delay)
        ctx.close()
    CACHE.write_text(json.dumps(cache, indent=1))


def patch_row(row_id: int, body: dict) -> list[dict]:
    url, key = _load_env()
    endpoint = f"{url}/rest/v1/peaks?{urllib.parse.urlencode({'id': f'eq.{row_id}'})}"
    req = urllib.request.Request(
        endpoint, data=json.dumps(body).encode(), method="PATCH",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "Prefer": "return=representation"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ids", help="comma-separated peak_db ids (default: ALL peaks)")
    ap.add_argument("--apply", action="store_true", help="write fixes to peak_db")
    ap.add_argument("--fresh", action="store_true", help="ignore tmp_pb_verify.json, refetch")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between LoJ fetches (default 1)")
    ap.add_argument("--headed", action="store_true", help="visible browser")
    args = ap.parse_args()

    rows = {p["id"]: p for p in peaks()}
    if args.ids:
        target = []
        for tok in args.ids.split(","):
            i = int(tok)
            if i not in rows:
                sys.exit(f"peak_db id {i} not found")
            if i <= 0:
                sys.exit(f"peak_db id {i} is a manually-added non-LoJ row (negative id) — "
                         "its LoJ page doesn't exist, so its pb id can't be verified here")
            target.append(i)
    else:
        skipped = sum(1 for i in rows if i <= 0)
        target = sorted(i for i in rows if i > 0)
        if skipped:
            print(f"skipping {skipped} manually-added non-LoJ row(s) (negative peak_db id)")

    cache = {} if args.fresh else load_cache()
    todo = [i for i in target if "pid" not in cache.get(str(i), {})]
    print(f"verifying {len(target)} peak(s); {len(target) - len(todo)} cached, "
          f"{len(todo)} to fetch from LoJ (~{len(todo) * (args.delay + 0.5) / 60:.0f} min)")
    if todo:
        sweep(todo, cache, args.delay, args.headed)

    # diff
    match, mismatch, db_missing, loj_missing, errors = [], [], [], [], []
    for i in target:
        row, c = rows[i], cache.get(str(i), {})
        if c.get("error"):
            errors.append((row, c["error"]))
            continue
        loj_pid, db_pid = c.get("pid"), row.get("peakbagger_id")
        if loj_pid is None:
            loj_missing.append(row)
        elif db_pid == loj_pid:
            match.append(row)
        elif not db_pid:
            db_missing.append((row, loj_pid))
        else:
            mismatch.append((row, loj_pid))

    print(f"\n=== peakbagger_id audit: {len(match)} OK · {len(mismatch)} MISMATCH · "
          f"{len(db_missing)} DB-MISSING · {len(loj_missing)} no LoJ cross-link · "
          f"{len(errors)} fetch errors ===")
    for row, loj_pid in mismatch:
        print(f"  MISMATCH   id {row['id']:>4}  {row['display_name']:<32} "
              f"db {row['peakbagger_id']}  →  loj {loj_pid}")
    for row, loj_pid in db_missing:
        print(f"  DB-MISSING id {row['id']:>4}  {row['display_name']:<32} "
              f"db None  →  loj {loj_pid}")
    for row in loj_missing:
        print(f"  NO-LINK    id {row['id']:>4}  {row['display_name']:<32} "
              f"db {row.get('peakbagger_id')}  (LoJ page has no pb cross-link — left alone)")
    for row, err in errors:
        print(f"  ERROR      id {row['id']:>4}  {row['display_name']:<32} {err}")

    fixes = mismatch + db_missing
    if not args.apply:
        if fixes:
            print(f"\nDry run. Re-run with --apply to fix {len(fixes)} row(s) in peak_db.")
        return
    if not fixes:
        print("\nNothing to apply.")
        return

    print(f"\napplying {len(fixes)} fix(es) to peak_db …")
    applied = json.loads(APPLIED_LOG.read_text()) if APPLIED_LOG.exists() else []
    ok = 0
    for row, loj_pid in fixes:
        body = {"peakbagger_id": loj_pid,
                "peakbagger_url": f"https://www.peakbagger.com/peak.aspx?pid={loj_pid}"}
        result = patch_row(row["id"], body)
        good = bool(result) and result[0].get("peakbagger_id") == loj_pid
        ok += good
        applied.append({"id": row["id"], "name": row["display_name"],
                        "old_pid": row.get("peakbagger_id"), "old_url": row.get("peakbagger_url"),
                        "new_pid": loj_pid, "ok": good})
        print(f"  id {row['id']:>4}  {row['display_name']:<32} "
              f"{row.get('peakbagger_id')} → {loj_pid}  {'OK' if good else 'FAILED: ' + json.dumps(result)}")
    APPLIED_LOG.write_text(json.dumps(applied, indent=1))
    print(f"\n✓ {ok}/{len(fixes)} applied (old values logged → {APPLIED_LOG.name})")
    if ok < len(fixes):
        sys.exit(1)


if __name__ == "__main__":
    main()
