#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
run_gates.py — the enforcement entry point (pre-push hook + CI).

Kyle (2026-06-17): "ensure the LLM isn't working around the rules." CLAUDE.md and
skills are guidance the model can ignore; the lock has to be outside its
discretion. This runs the full gate set and exits non-zero on any failure — wired
to .githooks/pre-push so a push is BLOCKED if it would ship a rule violation.

Default (--changed): gate only the reports being pushed (base slugs derived from
changed docs/peaks, docs/trips, gpx/ files vs origin/main), so the existing
backlog doesn't freeze every push — but anything you TOUCH must pass. Plus the
repo-wide freshness --check gates (index / quickstats / peak-map / source-rigor /
maps) always run, since those committed artifacts must never drift.

    scripts/run_gates.py --changed        # default: changed reports + repo-wide --check
    scripts/run_gates.py --all            # every report (heavy; for an audit)
    scripts/run_gates.py --slug gladstone_peak
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "scripts"

# per-report gates (each accepts "<slug> --strict" and exits non-zero on failure)
PER_SLUG = [
    ("check_source_coverage.py", "3-source GPX present"),
    ("check_report_ready.py", "th/class/status provenance"),
    ("check_class.py", "class ≥ hardest summit"),
    ("check_route_stats.py", "headline mileage matches GPX"),
    ("check_route_summits.py", "route reaches each summit"),
    ("check_route_exists.py", "has a recommended route"),
    ("check_map_fresh.py", "PNG not stale vs route/tracks"),
]
# repo-wide artifact-freshness gates (committed files must match frontmatter)
REPO_WIDE = [
    (["check_reports.py"], "source-rigor footer"),
    (["check_maps.py"], "map QA"),
    (["check_map_extents.py"], "map extents"),
    (["gen_index.py", "--check"], "index table current"),
    (["gen_quickstats.py", "--check"], "quick-stats current"),
    (["gen_peak_map.py", "--check"], "home-map data current"),
]


def changed_slugs() -> set[str]:
    """Base slugs touched by the commits being pushed (vs origin/main)."""
    for base in ("origin/main...HEAD", "HEAD~1...HEAD"):
        r = subprocess.run(["git", "diff", "--name-only", base], cwd=ROOT,
                            capture_output=True, text=True)
        if r.returncode == 0:
            files = r.stdout.split()
            break
    else:
        files = []
    slugs = set()
    for f in files:
        parts = f.split("/")
        if len(parts) >= 3 and parts[0] == "docs" and parts[1] in ("peaks", "trips"):
            slugs.add(Path(parts[2]).stem.split(".")[0])
        elif len(parts) >= 2 and parts[0] == "gpx":
            slugs.add(parts[1])
    return slugs


def run(cmd) -> tuple[bool, str]:
    r = subprocess.run([str(S / cmd[0])] + cmd[1:], cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--changed", action="store_true", help="gate only pushed reports (default)")
    g.add_argument("--all", action="store_true", help="gate every report")
    g.add_argument("--slug")
    args = ap.parse_args()

    if args.slug:
        slugs = [args.slug]
    elif args.all:
        slugs = sorted(d.name for d in (ROOT / "gpx").iterdir() if d.is_dir())
    else:
        slugs = sorted(changed_slugs())

    fails = []
    if slugs:
        print(f"▶ gating {len(slugs)} report(s): {', '.join(slugs)}")
        for slug in slugs:
            for gate, desc in PER_SLUG:
                ok, out = run([gate, slug, "--strict"])
                if not ok:
                    fails.append(f"{slug}: {desc} ({gate})")
                    print(f"  ✗ {slug:24s} {desc}")
                    for line in out.splitlines():
                        if "FAIL" in line or "MISSING" in line or "STALE" in line or "missing" in line:
                            print(f"      {line.strip()}")
    else:
        print("▶ no report files changed vs origin/main — running repo-wide freshness only")

    print("▶ repo-wide freshness checks")
    for cmd, desc in REPO_WIDE:
        ok, out = run(cmd)
        if not ok:
            fails.append(f"repo: {desc} ({cmd[0]})")
            print(f"  ✗ {desc} ({cmd[0]})")

    if fails:
        print(f"\n✗ {len(fails)} gate failure(s) — push blocked. Fix, or `git push --no-verify` to override deliberately.")
        sys.exit(1)
    print("\n✓ all gates pass")


if __name__ == "__main__":
    main()
