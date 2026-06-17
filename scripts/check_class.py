#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML","supabase"]
# ///
"""
check_class.py — SAFETY gate on the YDS class of every report.

The lesson (Kyle, 2026-06-16): an under-stated class is a safety problem — it
drives wrong gear/rope/helmet decisions. peak_db's `yds_class` is the
**per-summit STANDARD-route** grade ONLY. It does NOT describe the recommended
route when that route is a traverse, a ridge link-up, a loop, or any non-standard
line — and connecting ridges are frequently 1–2 classes harder than either
summit's standard route (Mount Adams trio: Class 2 summits, Class 3–4 ridges).

This compares each report's headline class against the per-summit peak_db classes:

  FAIL  report class < the hardest objective's summit class — objectively
        under-stated; fix before publishing.
  WARN  multi-peak report whose class does NOT exceed the summit max AND whose
        body never discusses the connecting ridge/traverse/saddle class — the
        link-up class was probably never researched. Pull the real route beta
        (14ers route desc + trip reports + Roach + climb13ers) and set the class
        to the ACTUAL recommended route, taking the harder estimate when unsure.

Usage:
  scripts/check_class.py                 # audit all reports (advisory)
  scripts/check_class.py --strict        # exit 1 on any FAIL (for --finalize)
  scripts/check_class.py mount_adams_trio
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
RIDGE_WORDS = re.compile(r"ridge|travers|connect|saddle|link[- ]?up|notch|gendarme|crux|chimney", re.I)


def class_value(s) -> float | None:
    """Max YDS numeric in a class string: '2'→2, '2+'→2.5, '2–3'→3, '2 (Class 3–4 crux)'→4."""
    if s is None:
        return None
    s = str(s)
    vals = []
    for m in re.finditer(r"([1-5])\s*(\+)?", s):
        v = int(m.group(1)) + (0.5 if m.group(2) else 0.0)
        vals.append(v)
    return max(vals) if vals else None


def objective_ids(slug: str) -> list[int]:
    ymlf = ROOT / "gpx" / slug / "peaks.yml"
    if ymlf.exists():
        ids = (yaml.safe_load(ymlf.read_text()) or {}).get("objective_ids")
        if ids:
            return ids
    return []


def report_class(md: Path):
    txt = md.read_text()
    fm = {}
    m = re.match(r"^---\n(.*?)\n---\n", txt, re.S)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except Exception:
            fm = {}
    # prefer yds_class (route grade incl. crux), fall back to class
    cls = fm.get("yds_class") if fm.get("yds_class") is not None else fm.get("class")
    body = txt[m.end():] if m else txt
    return cls, body, fm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    P = {p["id"]: p for p in peaks()}

    md_files = []
    for d in (ROOT / "docs" / "peaks", ROOT / "docs" / "trips"):
        md_files += sorted(d.glob("*.md"))
    fails = warns = 0
    for md in md_files:
        slug = md.stem
        if "." in slug:  # climber/skeleton variants
            continue
        if args.slug and slug != args.slug:
            continue
        ids = objective_ids(slug)
        if not ids:
            continue
        summit_cls = {i: class_value(P[i].get("yds_class")) for i in ids if i in P}
        smax = max([v for v in summit_cls.values() if v is not None], default=None)
        rcls, body, fm = report_class(md)
        rmax = class_value(rcls)
        if smax is None or rmax is None:
            continue
        multi = len(ids) >= 2
        ridge_discussed = bool(RIDGE_WORDS.search(body) and re.search(r"[Cc]lass\s*[1-5]", body))
        if rmax < smax:
            print(f"FAIL  {slug:26} report class {rcls!r} (={rmax}) < hardest summit (={smax}) — UNDER-STATED")
            fails += 1
        elif multi and rmax <= smax and not (rmax > smax or ridge_discussed):
            print(f"WARN  {slug:26} {len(ids)}-peak; class {rcls!r} = summit max ({smax}) & no ridge-class discussion — verify the traverse class")
            warns += 1
        else:
            print(f"ok    {slug:26} class {rcls!r} (route={rmax} ≥ summit={smax})")
    print(f"\n{fails} FAIL, {warns} WARN.")
    if args.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
