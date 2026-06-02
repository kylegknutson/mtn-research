#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
check_reports.py — lint peak/trip reports for the hard requirements.

Currently enforces the **source-rigor gate** (goal 5): every report must carry a
"Sources checked" footer naming all three sources (14ers + listsofjohn +
peakbagger). A report without it = unverifiable research and fails the check.

Also warns (non-fatal) on a few template basics: an embedded overview map, a
CalTopo link, and a NOAA weather link.

Exit code is non-zero if any report FAILS a hard check — wire into CI.

Usage:
    scripts/check_reports.py                # check all docs/peaks + docs/trips
    scripts/check_reports.py --warn-only    # never exit non-zero (report only)
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIRS = [ROOT / "docs" / "peaks", ROOT / "docs" / "trips"]

REQUIRED_SOURCES = {
    "14ers": re.compile(r"14ers", re.I),
    "listsofjohn": re.compile(r"listsofjohn|\bLoJ\b", re.I),
    "peakbagger": re.compile(r"peakbagger", re.I),
}
SOURCES_FOOTER = re.compile(r"sources\s+checked", re.I)


GRANDFATHER = "<!-- pre-3-source-rule -->"


def check(path: Path):
    text = path.read_text()
    fails, warns = [], []
    # Reports made before the 3-source rule can carry an explicit grandfather
    # marker; their source-rigor gaps are downgraded to warnings (tracked for a
    # freshness pass) rather than failing the build. Remove the marker once fixed.
    grandfathered = GRANDFATHER in text
    bucket = warns if grandfathered else fails

    # HARD: Sources checked footer naming all three
    m = SOURCES_FOOTER.search(text)
    if not m:
        bucket.append('missing "Sources checked" footer'
                      + (" (grandfathered)" if grandfathered else ""))
    else:
        footer = text[m.start():m.start() + 400]
        missing = [name for name, rx in REQUIRED_SOURCES.items() if not rx.search(footer)]
        if missing:
            bucket.append(f'Sources-checked footer missing: {", ".join(missing)}'
                          + (" (grandfathered)" if grandfathered else ""))

    # WARN: structured frontmatter (machine-readable fields for the index/table)
    fm = re.match(r"---\n(.*?)\n---\n", text, re.S)
    fm_block = fm.group(1) if fm else ""
    RECOMMENDED_FM = ["range", "drive_time", "yds_class", "gain", "status", "regional_map_id"]
    missing_fm = [k for k in RECOMMENDED_FM if not re.search(rf"^{k}:", fm_block, re.M)]
    if missing_fm:
        warns.append(f"frontmatter missing: {', '.join(missing_fm)}")

    # WARN: template basics
    if "![Overview map]" not in text and "/maps/" not in text:
        warns.append("no embedded overview map")
    if "caltopo.com/m/" not in text:
        warns.append("no CalTopo map link")
    if "forecast.weather.gov" not in text:
        warns.append("no NOAA weather link")

    return fails, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-only", action="store_true")
    args = ap.parse_args()

    reports = []
    for d in REPORT_DIRS:
        if d.exists():
            reports += sorted(p for p in d.glob("*.md"))

    n_fail = 0
    for p in reports:
        fails, warns = check(p)
        rel = p.relative_to(ROOT)
        if fails:
            n_fail += 1
            print(f"✗ {rel}")
            for f in fails:
                print(f"    FAIL: {f}")
            for w in warns:
                print(f"    warn: {w}")
        elif warns:
            print(f"~ {rel}")
            for w in warns:
                print(f"    warn: {w}")
        else:
            print(f"✓ {rel}")

    print(f"\n{len(reports)} report(s): {n_fail} failing the source-rigor gate.")
    if n_fail and not args.warn_only:
        sys.exit(1)


if __name__ == "__main__":
    main()
