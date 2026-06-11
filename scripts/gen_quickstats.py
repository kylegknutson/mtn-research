#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
gen_quickstats.py — render the "At a glance" stat callout at the top of each report.

Reads the structured frontmatter (dist_mi, gain_ft, class, peaks, days, drive_h,
days_detail) and writes a highlighted Material admonition between
<!-- QUICKSTATS_START --> / <!-- QUICKSTATS_END --> markers, inserted right after
the H1 if the markers aren't there yet. Single source of truth = the frontmatter.

    scripts/gen_quickstats.py            # update all reports
    scripts/gen_quickstats.py --check    # exit 1 if any report's callout is stale
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
DIRS = [ROOT / "docs" / "peaks", ROOT / "docs" / "trips"]
START, END = "<!-- QUICKSTATS_START -->", "<!-- QUICKSTATS_END -->"


def fm(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def n_mi(v):
    return None if v is None else (f"{v:g}")


def n_ft(v):
    return None if v is None else f"{int(v):,}"


def stat_line(d):
    """Compact '11 mi · 3,750 ft · Class 2 · 3 peaks' from a dict."""
    bits = []
    if d.get("dist_mi") is not None:
        bits.append(f"**{n_mi(d['dist_mi'])} mi**")
    if d.get("gain_ft") is not None:
        bits.append(f"**{n_ft(d['gain_ft'])} ft** gain")
    if d.get("class"):
        bits.append(f"**Class {d['class']}**")
    pk = d.get("peaks")
    if pk:
        bits.append(f"{pk} peak" + ("s" if pk != 1 else ""))
    return " · ".join(bits)


def render(meta):
    days = meta.get("days") or 1
    detail = meta.get("days_detail")
    drive = meta.get("drive_h")
    drive_s = f"~{drive:g} h drive" if drive is not None else None
    lines = []
    if detail:
        lines.append(f'!!! tip "At a glance — {days}-day trip"')
        for i, dd in enumerate(detail, 1):
            label = dd.get("label", f"Day {i}")
            lines.append(f"    **Day {i} ({label}):** {stat_line(dd)}")
        total = stat_line(meta)
        if drive_s:
            total += f" · {drive_s}"
        lines.append(f"    **Total:** {total}")
    else:
        head = stat_line(meta)
        if drive_s:
            head += f" · {drive_s}"
        lines.append('!!! tip "At a glance — recommended day"')
        lines.append(f"    {head}")
    return "\n".join(lines)


def apply(path: Path, check: bool):
    text = path.read_text()
    meta = fm(text)
    if not stat_line(meta):
        return None  # no stats to show
    # blank lines inside the markers so the admonition is its own block
    block = f"{START}\n\n{render(meta)}\n\n{END}"
    if START in text and END in text:
        new = re.sub(re.escape(START) + r".*?" + re.escape(END), block, text, count=1, flags=re.S)
    else:
        # insert right after the first H1 line
        m = re.search(r"^#\s+.+$", text, re.M)
        if not m:
            return None
        i = m.end()
        new = text[:i] + "\n\n" + block + text[i:]
    if new != text:
        if not check:
            path.write_text(new)
        return path.name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    changed = []
    for d in DIRS:
        for md in sorted(d.glob("*.md")):
            if md.stem.count(".") or md.stem == "index":
                continue
            r = apply(md, args.check)
            if r:
                changed.append(f"{d.name}/{r}")
    if args.check:
        if changed:
            print("STALE quickstats callouts — run scripts/gen_quickstats.py:", file=sys.stderr)
            for c in changed:
                print("  " + c, file=sys.stderr)
            sys.exit(1)
        print("quickstats callouts current")
    else:
        print(f"updated {len(changed)} callout(s)" + (": " + ", ".join(changed) if changed else ""))


if __name__ == "__main__":
    main()
