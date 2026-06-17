#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
gen_index.py — regenerate the sortable peak table in docs/index.md from each
report's frontmatter, so the landing list never drifts from the actual reports.

Writes a markdown table between the sentinel markers in docs/index.md:
    <!-- PEAKS_TABLE_START -->  …generated…  <!-- PEAKS_TABLE_END -->
sorted by drive time. Columns are click-sortable on the site (tablesort).

Run after adding/editing a report (or in CI to check it's current):
    scripts/gen_index.py
    scripts/gen_index.py --check     # exit 1 if index.md is stale
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
PEAKS = ROOT / "docs" / "peaks"
INDEX = ROOT / "docs" / "index.md"
START, END = "<!-- PEAKS_TABLE_START -->", "<!-- PEAKS_TABLE_END -->"


def frontmatter(p: Path) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
    return yaml.safe_load(m.group(1)) if m else {}


def drive_minutes(s) -> int:
    if not s or s == "TODO":
        return 10**6
    h = re.search(r"(\d+)\s*h", str(s)); m = re.search(r"(\d+)\s*m", str(s))
    return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)


def _num(v):
    """Render a number for a sortable cell ('11', '3,750'); '—' if missing."""
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return f"{v:,}" if isinstance(v, int) else f"{v:g}"


def build_table(climber: str | None = None) -> str:
    rows = []
    for sub, folder in (("peaks", PEAKS), ("trips", ROOT / "docs" / "trips")):
        pattern = f"*.{climber}.md" if climber else "*.md"
        for p in sorted(folder.glob(pattern)):
            if climber:
                # this climber's reports only (e.g. <slug>.emily.md); skip an index.<climber>.md
                if p.stem == f"index.{climber}":
                    continue
            else:
                # Kyle's main index: skip skeletons / climber-suffixed reports (2nd dot ⇒ suffix).
                if p.name.count(".") > 1 or p.stem == "index":
                    continue
            fm = frontmatter(p)
            title = re.search(r"^#\s+(.+)$", p.read_text(), re.M)
            name = title.group(1).strip() if title else p.stem
            name = re.split(r"\s+[—(]", name, 1)[0].strip()
            peaks = fm.get("peaks")
            days = fm.get("days") or 1
            rows.append({
                "name": name, "url": f"{sub}/{p.stem}.md",
                "range": fm.get("range", ""),
                "klass": fm.get("class") or fm.get("yds_class", ""),
                "dist": fm.get("dist_mi"), "gain": fm.get("gain_ft"),
                "peaks": peaks, "days": days,
                "pk_day": round(peaks / days, 1) if peaks else None,
                "drive": fm.get("drive_h"), "status": fm.get("status", ""),
                "_sort": fm.get("drive_h") if fm.get("drive_h") is not None else 10**6,
            })
    rows.sort(key=lambda r: r["_sort"])
    out = ["| Peak / Trip | Range | Class | Dist (mi) | Gain (ft) | Peaks | Days | Pk/day | Drive (h) | Status |",
           "|---|---|---|--:|--:|--:|--:|--:|--:|---|"]
    for r in rows:
        out.append(
            f"| [{r['name']}]({r['url']}) | {r['range']} | {r['klass'] or '—'} | "
            f"{_num(r['dist'])} | {_num(r['gain'])} | {_num(r['peaks'])} | "
            f"{_num(r['days'])} | {_num(r['pk_day'])} | {_num(r['drive'])} | {r['status']} |")
    return "\n".join(out)


STATS_JSON = ROOT / "docs" / "data" / "report_stats.json"


def badge_for(fm) -> str:
    """Compact nav badge like '11 mi · 3,750′ · C2 · 2d'."""
    bits = []
    if fm.get("dist_mi") is not None:
        bits.append(f"{_num(fm['dist_mi'])} mi")
    if fm.get("gain_ft") is not None:
        bits.append(f"{_num(fm['gain_ft'])}′")
    klass = fm.get("class") or fm.get("yds_class")
    if klass:
        bits.append(f"C{klass}")
    if (fm.get("days") or 1) > 1:
        bits.append(f"{fm['days']}d")
    return " · ".join(bits)


def collect_badges() -> dict:
    out = {}
    for sub, folder in (("peaks", PEAKS), ("trips", ROOT / "docs" / "trips")):
        for p in sorted(folder.glob("*.md")):
            if p.name.count(".") > 1 or p.stem == "index":
                continue
            b = badge_for(frontmatter(p))
            if b:
                out[f"{sub}/{p.stem}/"] = b   # mkdocs directory-URL key
    return out


def render(index_text: str, table: str) -> str:
    block = f"{START}\n{table}\n{END}"
    if START in index_text and END in index_text:
        return re.sub(re.escape(START) + r".*?" + re.escape(END), block, index_text, flags=re.S)
    # insert after the first "## Peaks" heading, else append
    if "## Peaks" in index_text:
        return index_text.replace("## Peaks", "## Peaks\n\n*Click a column header to sort.*\n\n" + block, 1)
    return index_text + "\n\n## Peaks\n\n" + block + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if index.md is stale")
    ap.add_argument("--climber", help="regenerate index.<climber>.md from <slug>.<climber>.md reports")
    args = ap.parse_args()

    index_path = (ROOT / "docs" / f"index.{args.climber}.md") if args.climber else INDEX
    cur = index_path.read_text()
    new = render(cur, build_table(args.climber))
    if args.climber:
        # climber index = table only (no account-wide nav badges)
        if args.check:
            if cur != new:
                print(f"docs/index.{args.climber}.md is STALE — run scripts/gen_index.py --climber {args.climber}")
                sys.exit(1)
            print(f"index.{args.climber}.md current ✓"); return
        if cur != new:
            index_path.write_text(new)
            print(f"✓ regenerated peak table in docs/index.{args.climber}.md")
        else:
            print(f"index.{args.climber}.md already current")
        return

    badges = json.dumps(collect_badges(), ensure_ascii=False, indent=0, sort_keys=True)
    cur_badges = STATS_JSON.read_text() if STATS_JSON.exists() else ""
    if args.check:
        if cur != new or cur_badges != badges:
            print("docs/index.md or report_stats.json is STALE — run scripts/gen_index.py")
            sys.exit(1)
        print("index table + nav badges current ✓"); return
    if cur != new:
        INDEX.write_text(new)
        print("✓ regenerated peak table in docs/index.md")
    if cur_badges != badges:
        STATS_JSON.parent.mkdir(parents=True, exist_ok=True)
        STATS_JSON.write_text(badges)
        print(f"✓ regenerated docs/data/report_stats.json ({badges.count(chr(10))} entries)")


if __name__ == "__main__":
    main()
