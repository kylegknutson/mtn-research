#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
check_source_coverage.py — make the 3-source sweep PROVE itself from files.

The reliability hole (Kyle, 2026-06-16): check_reports.py only verified that a
report's "Sources checked" footer *names* 14ers + LoJ + peakbagger — free text.
Nothing checked that GPX was actually pulled from each source, so a 14ers-only
build with a copy-pasted footer passed every gate (Gladstone shipped that way).

This closes it by reading the data, not the prose. For each report it looks at
the shared gpx/<base-slug>/ directory and, per source, counts recorded tracks by
filename token:
    14ers       → trk_14ers_*           / *_14ers_*
    listsofjohn → trk_loj_* / trk_listsofjohn_* / *_loj_*
    peakbagger  → trk_pb_* / trk_peakbagger_*    / *_pb_*

A source counts as COVERED if it has ≥1 track OR gpx/<slug>/sources.json records
it as deliberately empty, e.g.:
    { "peakbagger": {"checked": true, "found": 0, "note": "no public GPX tracks"} }

FAILs (with --strict, exit 1) when:
  * a source is neither present nor recorded as verified-empty  (sweep skipped), or
  * the report's "Sources checked ✓" footer claims a source that isn't covered
    (claim not backed by data).

Usage:
  scripts/check_source_coverage.py gladstone_peak
  scripts/check_source_coverage.py            # every report
  scripts/check_source_coverage.py --strict   # gate (in --finalize / CI)
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
PEAKS = ROOT / "docs" / "peaks"
TRIPS = ROOT / "docs" / "trips"

SOURCE_TOKENS = {
    "14ers": ("14ers",),
    "listsofjohn": ("loj", "listsofjohn"),
    "peakbagger": ("pb", "peakbagger"),
}
# files that are not source tracks
NON_TRACK = ("peaks_only", "landmark", "trailhead", "recommended", "_drive",
             "drive_in", "waypoints", "summit", "actual", "kyle")


def base_slug(report: Path) -> str:
    # gladstone_peak.emily.md → gladstone_peak ; mount_adams_trio.md → mount_adams_trio
    return report.stem.split(".")[0]


def track_sources(slug: str):
    """{source: count} of recorded track files present for this slug."""
    d = GPX / slug
    counts = {s: 0 for s in SOURCE_TOKENS}
    if not d.exists():
        return counts
    for f in d.glob("*.gpx"):
        n = f.name.lower()
        if any(x in n for x in NON_TRACK):
            continue
        for src, toks in SOURCE_TOKENS.items():
            if any(t in n for t in toks):
                counts[src] += 1
                break
    return counts


def declared_empty(slug: str):
    """sources recorded as deliberately empty in gpx/<slug>/sources.json."""
    p = GPX / slug / "sources.json"
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
    except Exception:
        return set()
    return {s for s, v in data.items()
            if isinstance(v, dict) and v.get("checked") and not v.get("found")}


def footer_claims(report: Path):
    """sources the 'Sources checked' footer marks present (any of the 3 named)."""
    txt = report.read_text()
    m = re.search(r"sources\s+checked", txt, re.I)
    if not m:
        return set()
    seg = txt[m.start():m.start() + 400]
    claimed = set()
    for src, toks in {"14ers": ("14ers",), "listsofjohn": ("listsofjohn", "loj"),
                      "peakbagger": ("peakbagger",)}.items():
        if any(re.search(t, seg, re.I) for t in toks):
            claimed.add(src)
    return claimed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="report slug (base or base.climber); default all")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    reports = []
    for folder in (PEAKS, TRIPS):
        for p in sorted(folder.glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index."):
                continue
            if args.slug and base_slug(p) != args.slug and p.stem != args.slug:
                continue
            reports.append(p)

    fails = 0
    for r in reports:
        slug = base_slug(r)
        counts = track_sources(slug)
        empty_ok = declared_empty(slug)
        claimed = footer_claims(r)
        problems = []
        for src in SOURCE_TOKENS:
            covered = counts[src] > 0 or src in empty_ok
            if not covered:
                problems.append(f"{src}: NO tracks + not recorded verified-empty")
            elif src in claimed and counts[src] == 0 and src not in empty_ok:
                problems.append(f"{src}: footer claims ✓ but no tracks")
        status = ("FAIL " if problems else "ok   ")
        if problems:
            fails += 1
        cov = " ".join(f"{s}={counts[s]}{'*' if s in empty_ok else ''}" for s in SOURCE_TOKENS)
        print(f"{status} {r.name:34s} {cov}" + (("  | " + "; ".join(problems)) if problems else ""))

    print(f"\n{len(reports)} report(s) — {fails} failing source coverage. (* = recorded verified-empty)")
    if args.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
