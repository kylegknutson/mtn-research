#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
migrate_report_format_2026_07.py — one-shot fleet migration (Kyle, 2026-07-11).

Applies to every report (docs/peaks + docs/trips, incl. climber variants):
  1. drop "**Report type:** …" lines (not valuable)
  2. drop the "## TL;DR" section entirely (not adding much value)
  3. drop old "*[Interactive CalTopo map](…) — …*" caption lines (the provenance
     Note block replaced them)
  4. weather becomes a "**Trip NOAA weather:** …" header line right under the
     "**CalTopo research map:**" line — sourced from frontmatter `weather:` or a
     body "| Weather |" table row (which is then removed)
  5. header "**X:**" lines get blank-line separated (single newlines merge into
     one paragraph when rendered)

Idempotent; run once, verify with run_gates --all, delete-or-keep per taste.
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def migrate(md: Path) -> bool:
    text = orig = md.read_text()

    # 1) Report type lines
    text = re.sub(r"^\*\*Report type:\*\*.*\n", "", text, flags=re.M)

    # 2) TL;DR section: heading → next "## " heading or EOF (+ a preceding --- rule)
    text = re.sub(r"(?:^---\s*\n\s*\n)?^## TL;DR\s*\n.*?(?=^## |\Z)", "", text,
                  flags=re.M | re.S)

    # 3) old map-caption lines (superseded by the provenance Note)
    text = re.sub(r"^\*\[Interactive CalTopo map\]\(.*\n", "", text, flags=re.M)

    # 4) weather → header line under the CalTopo research map line
    wx = None
    m = re.search(r'^weather:\s*"?(\S+?)"?\s*$', text, re.M)
    if m:
        wx = m.group(1)
    rowm = re.search(r"^\|\s*\*{0,2}Weather\*{0,2}\s*\|\s*\[([^\]]+)\]\((\S+?)\)(.*)\|\s*$",
                     text, re.M)
    note = ""
    if rowm:
        wx = wx or rowm.group(2)
        note = rowm.group(3).strip().rstrip("|").strip()
        text = text.replace(rowm.group(0) + "\n", "")
    if wx and "**Trip NOAA weather:**" not in text:
        ins = f"**Trip NOAA weather:** [NOAA point forecast]({wx})"
        if note:
            ins += f" {note}"
        text = re.sub(r"(^\*\*CalTopo research map:\*\*.*$)", r"\1\n\n" + ins,
                      text, count=1, flags=re.M)

    # 4b) normalize the weather line (Kyle, 2026-07-11): link text "<Area> Weather"
    # (area = H1 stem), no "point forecast", no trailing parentheticals. ONLY
    # rewrite generic labels — hand-tuned area names ("Needle Mtns Weather")
    # must survive re-runs.
    h1 = re.search(r"^#\s+(.+)$", text, re.M)
    if h1:
        area = re.split(r"\s+[—(]", h1.group(1), maxsplit=1)[0].strip()
        text = re.sub(r"^(\s*)\*\*Trip NOAA weather:\*\*\s*\[[^\]]*point forecast[^\]]*\]\((\S+?)\).*$",
                      rf"\1**Trip NOAA weather:** [{area} Weather](\2)",
                      text, flags=re.M | re.I)

    # 4c) TWO headingless boxes (Kyle, 2026-07-11): weather first (tip style),
    # then the map in a DIFFERENT highlight (info style). No titles.
    #   convert the earlier combined '!!! tip "Map & weather"' box if present
    text = re.sub(
        r'^!!! tip "Map & weather"\n'
        r"    \*\*CalTopo research map:\*\*\s*(\S+)\s*\n"
        r"(?:\s*\n)?"
        r"(?:    \*\*Trip NOAA weather:\*\*\s*(.+)\n)?",
        lambda m: ((f'!!! tip ""\n    **Trip NOAA weather:** {m.group(2).strip()}\n\n'
                    if m.group(2) else "")
                   + f'!!! info ""\n    **CalTopo research map:** {m.group(1)}\n'),
        text, count=1, flags=re.M)
    #   fresh conversion for reports never boxed
    if '!!! info ""' not in text:
        text = re.sub(
            r"^\*\*CalTopo research map:\*\*\s*(\S+)\s*\n"
            r"(?:\s*\n)?"
            r"(?:^\*\*Trip NOAA weather:\*\*\s*(.+)\n)?",
            lambda m: ((f'!!! tip ""\n    **Trip NOAA weather:** {m.group(2).strip()}\n\n'
                        if m.group(2) else "")
                       + f'!!! info ""\n    **CalTopo research map:** {m.group(1)}\n'),
            text, count=1, flags=re.M)

    # 4e) custom admonition types + label (Kyle, 2026-07-12): weather box is
    # `!!! weather ""` (yellow) labeled "NOAA weather link:", map box is
    # `!!! map ""` (blue). Styling: docs/stylesheets/admonitions.css + share CSS.
    text = re.sub(r'^!!! tip ""\n(    \*\*)Trip NOAA weather:',
                  r'!!! weather ""\n\1NOAA weather link:', text, flags=re.M)
    text = re.sub(r'^(    \*\*)Trip NOAA weather:', r"\1NOAA weather link:", text, flags=re.M)
    text = re.sub(r'^!!! info ""\n(?=    \*\*CalTopo research map:)', '!!! map ""\n',
                  text, flags=re.M)

    # 4d) each box must be followed by a blank line — an unindented line glued to
    # the last indented row lazily continues the admonition paragraph
    text = re.sub(r"(^    \*\*(?:CalTopo research map|NOAA weather link):\*\*.*$\n)(?=\S)",
                  r"\1\n", text, flags=re.M)

    # 5) blank-line-separate consecutive header bold-lines (outside tables/admonitions)
    for _ in range(6):
        new = re.sub(r"(^\*\*[^\n|]+$)\n(\*\*)", r"\1\n\n\2", text, flags=re.M)
        if new == text:
            break
        text = new

    # tidy: collapse 3+ blank lines; drop a trailing horizontal rule
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"\n---\s*\n*\Z", "\n", text)

    if text != orig:
        md.write_text(text)
        return True
    return False


def main():
    changed = []
    for sub in ("peaks", "trips"):
        for md in sorted((DOCS / sub).glob("*.md")):
            if md.stem == "index" or md.stem.startswith("index."):
                continue
            if migrate(md):
                changed.append(f"{sub}/{md.name}")
    print(f"migrated {len(changed)} report(s)")
    for c in changed:
        print("  " + c)


if __name__ == "__main__":
    main()
