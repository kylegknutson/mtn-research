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
import argparse, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
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


# A change to any of these redefines the report FORMAT (a gate, a generated/committed
# artifact's schema, the report template/runbook, the route/map builders). Per Kyle's
# rule (2026-06-18, CLAUDE.md Hard rule #1): a format change must leave EVERY report
# still conforming — so when one of these is in the push, we escalate from --changed to
# gating ALL reports, the lock that stops old reports silently drifting out of format.
def is_format_file(f: str) -> bool:
    if f == "CLAUDE.md" or f.startswith("scripts/check_") or f.startswith("scripts/gen_"):
        return True
    return f in {
        "scripts/run_gates.py", "scripts/build_report.py", "scripts/scaffold_report.py",
        "scripts/build_recommended_route.py", "scripts/make_overview_map.py",
    }


def changed_files() -> list[str]:
    """Files touched by the commits being pushed (vs origin/main)."""
    for base in ("origin/main...HEAD", "HEAD~1...HEAD"):
        r = subprocess.run(["git", "diff", "--name-only", base], cwd=ROOT,
                            capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.split()
    return []


def slugs_from_files(files) -> set[str]:
    """Base slugs touched by the given changed files."""
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

    # real report dirs only — skip helpers like gpx/_exports/, gpx/_kyle_existing/
    all_slugs = lambda: sorted(d.name for d in (ROOT / "gpx").iterdir()
                               if d.is_dir() and not d.name.startswith("_"))
    every = all_slugs()
    gate_all = False
    if args.slug:
        slugs = [args.slug]
    elif args.all:
        slugs, gate_all = every, True
    else:
        files = changed_files()
        fmt = sorted(f for f in files if is_format_file(f))
        if fmt:
            # Format change → the whole repo must still conform (Kyle's rule).
            print(f"▶ format-defining file(s) changed ({', '.join(fmt)})")
            print("▶ escalating to --all: every report must still match the new format")
            slugs, gate_all = every, True
        else:
            slugs = sorted(slugs_from_files(files))
            gate_all = set(slugs) == set(every) and bool(slugs)

    # Speed: each gate is a separate `uv run` process, and concurrent uv invocations
    # contend on uv's cache lock — so spawning 7×N (slug,gate) procs in parallel is
    # SLOWER than fewer procs. Two modes:
    #   • gating ALL reports → run each gate ONCE in its own all-reports mode (7 procs,
    #     not 7×N); the gates' inner loops are cheap now (check_route_stats scans coords
    #     by regex, not DOM). + 6 repo-wide = 13 procs.
    #   • gating a subset → one proc per (slug,gate); few slugs, so the count stays low.
    # All procs run in a thread pool (subprocess releases the GIL), wall ≈ slowest proc.
    workers = min(16, (os.cpu_count() or 4))
    fail_keys = ("FAIL", "MISSING", "STALE", "missing", "✗")

    def show_fail(label, out):
        print(f"  ✗ {label}")
        for line in out.splitlines():
            if any(k in line for k in fail_keys):
                print(f"      {line.strip()}")

    if slugs and gate_all:
        print(f"▶ gating all {len(slugs)} reports (batched: one process per gate)")
        jobs = [(f"{desc} ({gate})", [gate, "--strict"]) for gate, desc in PER_SLUG]
    elif slugs:
        print(f"▶ gating {len(slugs)} report(s): {', '.join(slugs)}")
        jobs = [(f"{slug}: {desc} ({gate})", [gate, slug, "--strict"])
                for slug in slugs for gate, desc in PER_SLUG]
    else:
        print("▶ no report files changed vs origin/main — running repo-wide freshness only")
        jobs = []

    print("▶ repo-wide freshness checks")
    jobs += [(f"repo: {desc} ({cmd[0]})", cmd) for cmd, desc in REPO_WIDE]
    fails = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run, cmd): label for label, cmd in jobs}
        for fut in futs:
            ok, out = fut.result()
            if not ok:
                fails.append(futs[fut])
                show_fail(futs[fut], out)

    if fails:
        print(f"\n✗ {len(fails)} gate failure(s) — push blocked. Fix, or `git push --no-verify` to override deliberately.")
        sys.exit(1)
    print("\n✓ all gates pass")


if __name__ == "__main__":
    main()
