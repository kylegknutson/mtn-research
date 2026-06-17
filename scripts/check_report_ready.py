#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_report_ready.py — remove the LLM's authority to SKIP a research step.

Kyle (2026-06-17): "it might be okay to hand off to the LLM to do some of the
research, but not with the authority to skip it." The fix is the same pattern
that worked for the GPX sweep (check_source_coverage): every mandatory step must
leave a CHECKABLE artifact, and publish is blocked if it's missing. Doing the
research is fine; skipping it silently is not.

This enforces three provenance fields in the report frontmatter that were
previously skippable — each must name *how* it was determined, with a recognized
verification token (so a junk placeholder can't pass):

  th_source     — trailhead verified, not inferred. Must cite OSM / a 14ers
                  trailhead / a recorded GPS-track start (NOT memory).
  class_source  — YDS class researched from route beta, not the peak_db summit
                  grade. Must cite a URL or a known beta source (14ers TR, Roach,
                  climb13ers, trip report).
  status_source — climbed status scraped, not assumed. Must cite
                  scrape_14ers_checklist / a 14ers checklist / peak_db ascents.

(The sweep itself is enforced separately by check_source_coverage.py; route/class
numbers by the route + class gates. This adds the human-judgment steps.)

    scripts/check_report_ready.py gladstone_peak.emily
    scripts/check_report_ready.py                 # audit all reports
    scripts/check_report_ready.py --strict        # gate (scoped in --finalize)
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
DIRS = [ROOT / "docs" / "peaks", ROOT / "docs" / "trips"]

# field -> regex of accepted verification tokens (case-insensitive)
REQUIRED = {
    "th_source":     r"osm|14ers|gps|recorded track|track start|trailhead db|caltopo",
    "class_source":  r"https?://|roach|climb13ers|14ers|trip report|\bTR\b|peakbagger|lists?ofjohn|\bloj\b",
    "status_source": r"scrape|checklist|peak_db|peakdb|ascents|14ers",
}


def fm(p: Path) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def check(p: Path):
    meta = fm(p)
    problems = []
    for field, tok in REQUIRED.items():
        v = str(meta.get(field) or "").strip()
        if not v:
            problems.append(f"missing {field}")
        elif not re.search(tok, v, re.I):
            problems.append(f"{field} has no recognized source token ({v[:30]!r})")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="report slug (base or base.climber); default all")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    reports = []
    for d in DIRS:
        for p in sorted(d.glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index."):
                continue
            if args.slug and p.stem != args.slug and p.stem.split(".")[0] != args.slug:
                continue
            reports.append(p)

    fails = 0
    for p in reports:
        problems = check(p)
        if problems:
            fails += 1
        print(f"{'FAIL ' if problems else 'ok   '} {p.name:34s}" +
              (("  | " + "; ".join(problems)) if problems else ""))

    print(f"\n{len(reports)} report(s) — {fails} missing required provenance.")
    if args.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
