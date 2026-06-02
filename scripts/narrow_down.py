#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests"]
# ///
"""
narrow_down.py — run a candidate-netting query against peak_db and save the
result as a versioned list artifact in docs/lists/.

Filters on the fields peak_db actually has — range, YDS class, elevation,
ranked, and unclimbed-for-the-climber — and sorts by straight-line distance
from the climber's home (the first-cut net). **Route gain and combo pattern
are NOT in peak_db** (they come from per-peak research), so those columns are
emitted as TODO for the research step to fill, exactly per the documented
workflow (haversine net → drive time + gain from research).

Output: docs/lists/<date>_<slug>.md with the snapshot table + a re-runnable
"Criteria" block (the exact command), so a list is both a frozen snapshot and
a saved query.

Usage:
    scripts/narrow_down.py --title "Closest unclimbed Sangre 13ers" \
        --range "Sangre de Cristo" --class-max 3 --limit 20
    scripts/narrow_down.py --title "Closest unclimbed CO 13ers" --limit 25
"""
from __future__ import annotations
import argparse, math, re, sys
from datetime import date
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
LISTS = ROOT / "docs" / "lists"
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
sys.path.insert(0, str(ROOT / "scripts"))
from peak_db_client import peaks, peak_lists  # noqa: E402
from climber import climbed_ids  # noqa: E402

LIST_ID = "co_13_14ers"


def hav_mi(la1, lo1, la2, lo2):
    R = 3958.8; p = math.pi / 180
    a = (math.sin((la2-la1)*p/2)**2 + math.cos(la1*p)*math.cos(la2*p)*math.sin((lo2-lo1)*p/2)**2)
    return 2*R*math.asin(math.sqrt(a))


def slugify(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def class_num(c):
    m = re.match(r"\s*([1-5])", str(c or ""))
    return int(m.group(1)) if m else 99


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--climber", default="kyle")
    ap.add_argument("--range", dest="rng", help="peak_db range (e.g. 'Sangre de Cristo')")
    ap.add_argument("--class-max", type=int, default=5)
    ap.add_argument("--elev-min", type=int, default=13000)
    ap.add_argument("--elev-max", type=int, default=14001)
    ap.add_argument("--within-mi", type=float, default=None, help="haversine cap from home")
    ap.add_argument("--include-climbed", action="store_true")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--print-only", action="store_true")
    args = ap.parse_args()

    prof = yaml.safe_load((ROOT / "climbers" / f"{args.climber}.yml").read_text())
    home = prof["home_latlon"]

    by_id = {p["id"]: p for p in peaks()}
    climbed = climbed_ids(args.climber)   # climber-agnostic (peak_db or 14ers checklist)
    in_list = {r["peak_id"] for r in peak_lists() if r["list_id"] == LIST_ID}

    rows = []
    for p in by_id.values():
        if p.get("state") != "CO" or not p.get("lat"): continue
        if p["id"] not in in_list or not p.get("ranked"): continue
        if not (args.elev_min <= p.get("elevation_ft", 0) <= args.elev_max): continue
        if class_num(p.get("yds_class")) > args.class_max: continue
        if args.rng and (p.get("range") or "").lower() != args.rng.lower(): continue
        if not args.include_climbed and p["id"] in climbed: continue
        d = hav_mi(home[0], home[1], p["lat"], p["lon"])
        if args.within_mi and d > args.within_mi: continue
        rows.append((d, p))
    rows.sort()
    rows = rows[:args.limit]

    # build table
    lines = [f"# {args.title}", "",
             f"*Saved {date.today().isoformat()} · climber: {prof['name']} · "
             f"{len(rows)} peaks · first-cut by straight-line distance.*", "",
             "> **Drive time, gain, and combos are blank** — they need per-peak research "
             "(peak_db has range/class/elev/ranked, not route gain or combo pattern). "
             "Run `research_peak.py` on a candidate to fill them.", "",
             "| # | Peak | Range | Elev | Class | Mi (haversine) | Drive | Gain | Combos | peak_db id |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for i, (d, p) in enumerate(rows, 1):
        nm = p["display_name"]
        lines.append(f"| {i} | {nm} | {p.get('range','')} | {p['elevation_ft']}' | "
                     f"{p.get('yds_class','')} | {d:.0f} | TODO | TODO | TODO | {p['id']} |")

    # re-runnable criteria
    crit = ["", "---", "", "## Criteria (re-runnable)", "", "```",
            "scripts/narrow_down.py \\",
            f'  --title "{args.title}" --climber {args.climber} \\',
            f"  --elev-min {args.elev_min} --elev-max {args.elev_max} "
            f"--class-max {args.class_max} --limit {args.limit}"
            + (f" \\\n  --range \"{args.rng}\"" if args.rng else "")
            + (f" --within-mi {args.within_mi}" if args.within_mi else ""),
            "```", ""]
    out = "\n".join(lines + crit) + "\n"

    if args.print_only:
        print(out); return
    LISTS.mkdir(parents=True, exist_ok=True)
    path = LISTS / f"{date.today().isoformat()}_{slugify(args.title)}.md"
    path.write_text(out)
    print(f"✓ wrote {path.relative_to(ROOT)} ({len(rows)} peaks)")
    print("  Add to mkdocs nav under Lists if you want it in the sidebar.")


if __name__ == "__main__":
    main()
