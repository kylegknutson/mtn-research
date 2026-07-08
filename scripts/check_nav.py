#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_nav.py — every report must be reachable from its site's nav (and no nav entry
may point at a missing file).

The navs in mkdocs.yml / mkdocs.<climber>.yml are hand-curated (custom titles,
deliberate ordering), so this gate CHECKS rather than generates: a new report that
never got a nav entry builds fine but is unreachable from the sidebar — nothing else
catches that (gen_index --check covers the home table, not the nav).

Per config:
  mkdocs.yml            — every docs/peaks|trips|lists/*.md with an undotted stem
                          (peak slugs have no dot; a second dot ⇒ climber/skeleton file)
  mkdocs.<climber>.yml  — every docs/peaks|trips/*.<climber>.md

Plus, for every config: each .md referenced in nav must exist under docs/.

    scripts/check_nav.py          # exit 1 on any missing/dangling entry
"""
from __future__ import annotations
import sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def nav_paths(node) -> set[str]:
    """All .md paths (docs-relative) referenced anywhere in a nav tree."""
    out: set[str] = set()
    if isinstance(node, str):
        if node.endswith(".md"):
            out.add(node.lstrip("/"))
    elif isinstance(node, list):
        for item in node:
            out |= nav_paths(item)
    elif isinstance(node, dict):
        for v in node.values():
            out |= nav_paths(v)
    return out


def expected_reports(climber: str | None) -> set[str]:
    """Report pages this config must link: base reports for the main site,
    <slug>.<climber>.md for a climber site."""
    out: set[str] = set()
    for sub in ("peaks", "trips", "lists"):
        d = DOCS / sub
        if not d.exists():
            continue
        for p in d.glob("*.md"):
            dots = p.stem.count(".")
            if climber is None and dots == 0:
                out.add(f"{sub}/{p.name}")
            elif climber and p.stem.endswith(f".{climber}") and dots == 1:
                out.add(f"{sub}/{p.name}")
    return out


def check_config(cfg_path: Path, climber: str | None) -> tuple[list[str], int]:
    nav = (yaml.safe_load(cfg_path.read_text()) or {}).get("nav") or []
    in_nav = nav_paths(nav)
    expected = expected_reports(climber)
    problems = []
    for miss in sorted(expected - in_nav):
        problems.append(f"MISSING from {cfg_path.name} nav: {miss}")
    for entry in sorted(in_nav):
        if not (DOCS / entry).exists():
            problems.append(f"DANGLING in {cfg_path.name} nav: {entry} (no such file)")
    return problems, len(expected)


def main():
    configs = [(ROOT / "mkdocs.yml", None)]
    configs += sorted((p, p.name.split(".")[1]) for p in ROOT.glob("mkdocs.*.yml"))
    problems, checked = [], 0
    for cfg, climber in configs:
        probs, n = check_config(cfg, climber)
        problems += probs
        checked += n
    for p in problems:
        print(p)
    if problems:
        print(f"\n✗ {len(problems)} nav problem(s) — add the report(s) to the config's nav "
              f"(or remove the dead entry).")
        sys.exit(1)
    if not checked:
        print("✗ MISSING: found no report pages to check — check_nav.py globs are broken")
        sys.exit(1)
    print(f"✓ nav complete: {checked} report page(s) across {len(configs)} mkdocs config(s)")


if __name__ == "__main__":
    main()
