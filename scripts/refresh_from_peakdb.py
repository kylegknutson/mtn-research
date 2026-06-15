#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
refresh_from_peakdb.py — one command to pull climbed-status from peak_db onto the
site and deploy. Intended as the **post-processing step after the peak checklist
is updated** (run on a Mac, where peak_db + the repo live).

Pipeline (all read from peak_db / frontmatter; safe to run anytime, idempotent):
  1. gen_peak_map.py   → docs/data/peaks.json      (home map: climbed = grey)
  2. sync_status.py    → report frontmatter status: (drives the index Status col)
  3. gen_index.py      → docs/index.md + docs/data/report_stats.json (table + badges)
Then, if any of those generated outputs changed, commit + push → Pages redeploys.

    scripts/refresh_from_peakdb.py            # regenerate, commit, push
    scripts/refresh_from_peakdb.py --no-push  # regenerate + commit only
    scripts/refresh_from_peakdb.py --dry-run  # --check each generator; no writes
"""
import argparse, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DATA_OUTPUTS = ["docs/data/peaks.json", "docs/data/report_stats.json", "docs/index.md"]


def run(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-push", action="store_true", help="commit but don't push")
    ap.add_argument("--dry-run", action="store_true", help="--check generators; no writes/commit")
    args = ap.parse_args()
    flag = ["--check"] if args.dry_run else []

    run([SCRIPTS / "gen_peak_map.py", *flag], check=False)
    # capture which reports sync_status rewrites, so we stage only those
    sync = run([SCRIPTS / "sync_status.py", *flag], check=False, capture_output=True, text=True)
    sys.stdout.write(sync.stdout or ""); sys.stderr.write(sync.stderr or "")
    run([SCRIPTS / "gen_index.py", *flag], check=False)

    if args.dry_run:
        print("\n[dry run] no commit/push")
        return

    # stage only this pipeline's outputs (data/index + the report files re-statused)
    changed_reports = []
    for nm in re.findall(r"^\s+(\S+\.md):", sync.stdout or "", re.M):
        for sub in ("peaks", "trips"):
            p = ROOT / "docs" / sub / nm
            if p.exists():
                changed_reports.append(str(p.relative_to(ROOT)))
    paths = DATA_OUTPUTS + changed_reports
    run(["git", "add", *paths], check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode
    if staged == 0:
        print("\nnothing changed — climbed status already current")
        return
    run(["git", "commit", "-m", "Refresh climbed status from peak_db"], check=True)
    if args.no_push:
        print("committed (not pushed)")
    else:
        run(["git", "push", "origin", "HEAD"], check=True)
        print("pushed — GitHub Pages will redeploy")


if __name__ == "__main__":
    main()
