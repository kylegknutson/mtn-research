#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
wait_pages_deploy.py — block until the latest Pages deploy run on main completes.

Replaces the ad-hoc `until ... gh run list ... sleep` Bash loop (not allow-listed →
prompted Kyle every push, 2026-07-10). Polls `gh run list` every --interval seconds
and exits 0 on success, 1 on failure/timeout — so "don't mark researched until the
deploy is green" is one allow-listed call:

    scripts/wait_pages_deploy.py
    scripts/wait_pages_deploy.py --branch main --timeout-min 15
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time


def latest_run(branch: str):
    r = subprocess.run(
        ["gh", "run", "list", "--branch", branch, "--limit", "1",
         "--json", "status,conclusion,displayTitle,url"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    runs = json.loads(r.stdout or "[]")
    return runs[0] if runs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--timeout-min", type=float, default=15.0)
    args = ap.parse_args()

    deadline = time.monotonic() + args.timeout_min * 60
    while time.monotonic() < deadline:
        run = latest_run(args.branch)
        if run and run.get("status") == "completed":
            concl = run.get("conclusion") or "?"
            print(f"deploy: {concl}  ({run.get('displayTitle', '')})\n{run.get('url', '')}")
            sys.exit(0 if concl == "success" else 1)
        time.sleep(args.interval)
    sys.exit(f"✗ timed out after {args.timeout_min:g} min waiting on the {args.branch} deploy")


if __name__ == "__main__":
    main()
