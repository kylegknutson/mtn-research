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
import argparse, re, sys
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


def build_table() -> str:
    rows = []
    for p in sorted(PEAKS.glob("*.md")):
        if p.name.endswith(".skeleton.md"):
            continue
        fm = frontmatter(p)
        title = re.search(r"^#\s+(.+)$", p.read_text(), re.M)
        name = title.group(1).strip() if title else p.stem
        # Trim the H1's trailing "(range/context)" or " — subtitle" for the table cell.
        name = re.split(r"\s+[—(]", name, 1)[0].strip()
        rows.append({
            "name": name, "slug": p.stem,
            "range": fm.get("range", ""), "drive": fm.get("drive_time", "—"),
            "klass": fm.get("yds_class", ""), "gain": fm.get("gain", ""),
            "status": fm.get("status", ""),
            "_min": drive_minutes(fm.get("drive_time")),
        })
    rows.sort(key=lambda r: r["_min"])
    out = ["| Peak | Range | Drive | Class | Gain | Status |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| [{r['name']}](peaks/{r['slug']}.md) | {r['range']} | "
                   f"{r['drive']} | {r['klass']} | {r['gain']} | {r['status']} |")
    return "\n".join(out)


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
    args = ap.parse_args()

    cur = INDEX.read_text()
    new = render(cur, build_table())
    if args.check:
        if cur != new:
            print("docs/index.md peak table is STALE — run scripts/gen_index.py")
            sys.exit(1)
        print("index table current ✓"); return
    if cur != new:
        INDEX.write_text(new)
        print("✓ regenerated peak table in docs/index.md")
    else:
        print("index table already current")


if __name__ == "__main__":
    main()
