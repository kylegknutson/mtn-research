#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["markdown", "PyYAML"]
# ///
"""
share_report.py — publish a SANITIZED, unlisted copy of one report for outsiders.

Kyle (2026-07-11): share single reports with people who shouldn't see the whole
site, the climber pages, or the research CalTopo maps. This renders a report to a
self-contained static HTML page at a tokenized path (docs/share/<slug>-<token>.html
— MkDocs copies non-md files verbatim: no nav, no search index, no site chrome)
and, unless --no-map, creates a NEW CalTopo map holding ONLY the recommended
route lines + objective summit markers ("Share: <title>", URL sharing).

Sanitized out:
  frontmatter · CLIMBERS block · "Written for <climber>" · Status-for/in-DB lines ·
  drive-from-home rows and quickstats drive fragments (personal origins) · research/
  regional CalTopo links (replaced by the share map, or removed) · links into the
  rest of the site (only the embedded PNG copy remains)

A committed ledger (docs/share/shares.json) records slug/token/share-map/date —
revoke a share by deleting its html+png and `delete_caltopo_map.py <share id>`.

NOTE: GitHub Pages has no auth — a share link is unlisted (unguessable token),
the same protection level as the rest of the site, not a login wall.

Usage:
    scripts/share_report.py jupiter_pigeon_turret                # emily/base auto
    scripts/share_report.py gladstone_peak --no-map
"""
from __future__ import annotations
import argparse, json, re, secrets, shutil, subprocess, sys
from datetime import date
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SHARE = DOCS / "share"
GPX = ROOT / "gpx"
SCRIPTS = ROOT / "scripts"
SITE = "https://kylegknutson.github.io/mtn-research"

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:860px;margin:2rem auto;
padding:0 1rem;color:#222;line-height:1.55}
h1{border-bottom:2px solid #e6008c;padding-bottom:.3rem}
table{border-collapse:collapse;margin:1rem 0;width:100%}
td,th{border:1px solid #ccc;padding:.4rem .6rem;text-align:left;font-size:.95rem}
img{max-width:100%;height:auto;border:1px solid #ddd}
.admonition{border-left:4px solid #888;background:#f6f6f6;padding:.6rem 1rem;margin:1rem 0}
.admonition.danger{border-color:#c00;background:#fff0f0}
.admonition.tip{border-color:#e6008c;background:#fdf2f8}
.admonition-title{font-weight:700;margin:0 0 .3rem}
blockquote{border-left:3px solid #ccc;margin:1rem 0;padding:.2rem 1rem;color:#555}
footer{margin-top:3rem;font-size:.8rem;color:#888;border-top:1px solid #ddd;padding-top:.6rem}
"""


def find_report(slug: str) -> Path:
    cands = (sorted((DOCS / "peaks").glob(f"{slug}*.md"))
             + sorted((DOCS / "trips").glob(f"{slug}*.md")))
    if not cands:
        sys.exit(f"ERROR: no report found for slug {slug!r}")
    return cands[0]


def sanitize(text: str, share_map_url: str | None, png_name: str, slug: str) -> str:
    # frontmatter off
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    # climbers block
    text = re.sub(r"<!-- CLIMBERS_START -->.*?<!-- CLIMBERS_END -->\n?", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        low = line.lower()
        if low.startswith("*written for"):
            continue
        if low.startswith("**status for") or low.startswith("**status in db"):
            continue
        if low.startswith("**researched:"):
            continue
        if "| drive from" in low or "| **drive from" in low:
            continue
        out.append(line)
    text = "\n".join(out)
    # quickstats drive fragment ("· **~7.4 h drive**")
    text = re.sub(r"\s*·\s*\*\*~?[\d.]+ ?h drive\*\*", "", text)
    # research CalTopo links → share map (or strip the line/link)
    if share_map_url:
        text = re.sub(r"https://caltopo\.com/m/[A-Z0-9]+", share_map_url, text)
        text = text.replace("**CalTopo research map:**", "**Interactive map (recommended route):**")
        # swept-track counts describe the research map, not the share map
        text = re.sub(r"\*\[Interactive CalTopo map\]\([^)]*\)[^\n]*",
                      f"*[Interactive map — recommended route]({share_map_url})*", text)
    else:
        text = re.sub(r"^.*caltopo\.com/m/.*$\n?", "", text, flags=re.M)
    # image path → local copy
    text = re.sub(rf"\.\./maps/{slug}\.png", png_name, text)
    # md links into the rest of the site → plain text (keep external http links)
    text = re.sub(r"\[([^\]]+)\]\((?!http)[^)]+\.md[^)]*\)", r"\1", text)
    # neutralize third-party climber names in prose (Kyle, the author, stays)
    import yaml
    for cy in sorted((ROOT / "climbers").glob("*.yml")):
        try:
            nm = (yaml.safe_load(cy.read_text()) or {}).get("name", "")
        except Exception:
            continue
        first = nm.split()[0] if nm else ""
        if not first or first.lower() == "kyle":
            continue
        text = re.sub(rf"\b{re.escape(first)}(?:’s|'s)\b", "the party's", text)
        text = re.sub(rf"\b{re.escape(first)}\b", "the party", text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--no-map", action="store_true", help="skip the share CalTopo map")
    args = ap.parse_args()

    report = find_report(args.slug)
    token = secrets.token_hex(4)
    base = f"{args.slug}-{token}"
    SHARE.mkdir(parents=True, exist_ok=True)

    # 1) share CalTopo map: recommended lines + objective summits only
    share_url = None
    if not args.no_map:
        title_m = re.search(r"^#\s+(.+)$", report.read_text(), re.M)
        title = title_m.group(1).strip() if title_m else args.slug
        files = sorted((GPX / args.slug).glob("*recommended*.gpx"))
        pk = GPX / args.slug / f"{args.slug}_peaks_only.gpx"
        if pk.exists():
            files.append(pk)
        if not files:
            sys.exit(f"ERROR: no recommended routes under gpx/{args.slug}/")
        cmd = [str(SCRIPTS / "gpx_to_caltopo.py"),
               "--new-map", f"Share: {title}", "--sharing", "URL",
               "--marker-symbol", "peak", "--no-dedupe"]
        for f in files:
            cmd += ["--gpx", str(f)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"caltopo\.com/m/([A-Z0-9]+)", r.stdout)
        if not m:
            print(r.stdout[-800:], file=sys.stderr)
            sys.exit("ERROR: share CalTopo map creation failed")
        share_url = f"https://caltopo.com/m/{m.group(1)}"
        print(f"share CalTopo map: {share_url}")

    # 2) sanitize + render
    png_name = f"{base}.png"
    md = sanitize(report.read_text(), share_url, png_name, args.slug)
    body = markdown.markdown(md, extensions=["tables", "admonition", "fenced_code"])
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    page_title = re.sub(r"<[^>]+>", "", title_m.group(1)) if title_m else args.slug
    html = (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<meta name='robots' content='noindex,nofollow'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{page_title}</title><style>{CSS}</style></head><body>\n{body}\n"
            f"<footer>Shared {date.today().isoformat()} · route research by Kyle Knutson · "
            f"conditions change — verify everything yourself</footer></body></html>\n")
    (SHARE / f"{base}.html").write_text(html)
    shutil.copyfile(DOCS / "maps" / f"{args.slug}.png", SHARE / png_name)

    # 3) ledger
    ledger_f = SHARE / "shares.json"
    ledger = json.loads(ledger_f.read_text()) if ledger_f.exists() else []
    ledger.append({"slug": args.slug, "file": f"{base}.html", "date": date.today().isoformat(),
                   "share_map": share_url, "source": report.name})
    ledger_f.write_text(json.dumps(ledger, indent=1) + "\n")

    print(f"\nShare page: {SITE}/share/{base}.html")
    print("(commit + push to publish; revoke = delete the html/png + the share map)")


if __name__ == "__main__":
    main()
