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
    if d.get("loss_ft") is not None:
        bits.append(f"{n_ft(d['loss_ft'])} ft descent")
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
    wx = meta.get("weather")            # one central NOAA link (peaks ≤6 mi apart)
    lines = []
    if detail:
        # Trip: a summary line (peaks · drive · central weather), then one list
        # item per day. The list (and the blank line) force each day onto its own
        # line — plain newlines inside an admonition collapse into one paragraph.
        lines.append(f'!!! tip "At a glance — {days}-day trip"')
        summ = f"**{meta['peaks']} peaks**" if meta.get("peaks") else ""
        # Backpack trips: a TRIP TOTAL in the summary line (Kyle, 2026-07-10 — always
        # for multi-day pack-ins). Computed from the components (pack-in + days +
        # pack-out) so it can never disagree with the lines below it.
        comps = ([meta["approach"]] if meta.get("approach") else []) + list(detail) \
            + ([meta["packout"]] if meta.get("packout") else [])
        if meta.get("approach") or meta.get("packout"):
            tot_mi = sum(c.get("dist_mi") or 0 for c in comps)
            tot_ft = sum(c.get("gain_ft") or 0 for c in comps)
            if tot_mi and tot_ft:
                summ += (" · " if summ else "") + \
                    f"**trip total ~{n_mi(tot_mi)} mi · ~{n_ft(tot_ft)} ft**"
        if drive_s:
            summ += (" · " if summ else "") + f"**{drive_s}**"
        if wx:
            summ += (" · " if summ else "") + f"[weather]({wx})"
        lines.append(f"    {summ}")
        lines.append("")
        # Backpack trips: pack-in/pack-out are first-class "At a glance" lines
        # (Kyle, 2026-07-10 — ALWAYS for multi-day backpacks). Frontmatter:
        #   approach: {label, dist_mi, gain_ft, loss_ft}   packout: {…}
        appr = meta.get("approach")
        if appr:
            lines.append(f"    - **{appr.get('label', 'Pack-in')}:** {stat_line(appr)}")
        # `move: true` entries are non-climbing legs (mid-trip camp moves) — rendered
        # in chronological position but not numbered as climbing days (and not counted
        # against frontmatter `days:`, which stays = climbing days with routes).
        day_n = 0
        for dd in detail:
            if dd.get("move"):
                lines.append(f"    - **{dd.get('label', 'Camp move')}:** {stat_line(dd)}")
                continue
            day_n += 1
            label = dd.get("label", f"Day {day_n}")
            item = f"    - **Day {day_n} ({label}):** {stat_line(dd)}"
            if dd.get("wx"):           # per-day link when peaks are >6 mi apart
                item += f" · [weather]({dd['wx']})"
            lines.append(item)
        po = meta.get("packout")
        if po:
            lines.append(f"    - **{po.get('label', 'Pack-out')}:** {stat_line(po)}")
    else:
        head = stat_line(meta)
        if drive_s:
            head += f" · {drive_s}"
        if wx:
            head += f" · [weather]({wx})"
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
            # Skip index pages only (index.md, index.<climber>.md). EVERY real
            # report gets the callout — Kyle's AND climber reports (<slug>.<climber>.md);
            # the old `stem.count(".")` skip silently excluded climber reports, so
            # their format quietly drifted from Kyle's (Gladstone had no "At a glance").
            if md.stem == "index" or md.stem.startswith("index."):
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
