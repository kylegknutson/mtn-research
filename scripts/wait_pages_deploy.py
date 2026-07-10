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


def latest_run(branch: str, sha: str | None):
    cmd = ["gh", "run", "list", "--branch", branch, "--limit", "1",
           "--json", "status,conclusion,displayTitle,url"]
    if sha:
        cmd += ["--commit", sha]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    runs = json.loads(r.stdout or "[]")
    return runs[0] if runs else None


def head_sha() -> str | None:
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default="main")
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--timeout-min", type=float, default=15.0)
    ap.add_argument("--commit", default=None,
                    help="wait for THIS commit's run (default: local HEAD). Without a "
                         "sha filter, a just-pushed commit races the previous run's "
                         "'completed' and false-reports it (hit 2026-07-10).")
    args = ap.parse_args()

    sha = args.commit or head_sha()
    deadline = time.monotonic() + args.timeout_min * 60
    while time.monotonic() < deadline:
        run = latest_run(args.branch, sha)
        if run and run.get("status") == "completed":
            concl = run.get("conclusion") or "?"
            print(f"deploy: {concl}  ({run.get('displayTitle', '')})\n{run.get('url', '')}")
            sys.exit(0 if concl == "success" else 1)
        time.sleep(args.interval)
    sys.exit(f"✗ timed out after {args.timeout_min:g} min waiting on the {args.branch} deploy")


if __name__ == "__main__":
    main()
