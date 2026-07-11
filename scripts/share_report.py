#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["markdown", "PyYAML"]
# ///
"""
share_report.py — sanitized, unlisted, TTL'd report shares on Cloudflare Pages.

Kyle (2026-07-11): shares live OUTSIDE the research site — a separate Cloudflare
Pages project (same account as peak_checklist, project `mtn-share`), open (no auth)
but enumeration-resistant, with a lifetime of a few months, regenerable later.

Layout (staged locally in share_site/, deployed via wrangler):
  share_site/s/<16-hex-token>/index.html   ← sanitized report (self-contained)
  share_site/s/<16-hex-token>/map.png      ← recommended-only overview PNG
  share_site/index.html                    ← blank (no root listing)
  share_site/robots.txt + _headers         ← deny crawlers, X-Robots-Tag noindex

Anti-enumeration: no slug in the URL, 64-bit tokens, no cross-links, no index,
noindex everywhere. Open link ≠ discoverable link.

Ledger (COMMITTED — the source of truth; pages are regenerable):
  share/ledger.json — [{slug, token, source, share_map, created, ttl_days}]

Commands:
    scripts/share_report.py <slug>                  # new share (+ share CalTopo map)
    scripts/share_report.py <slug> --ttl-days 60
    scripts/share_report.py --rebuild               # regen ALL live shares from ledger
    scripts/share_report.py --prune                 # expire: rm pages + share maps
    scripts/share_report.py --publish               # wrangler pages deploy share_site
  (typical: <slug> && --publish;  cleanup: --prune && --publish)

Sanitized out: frontmatter · CLIMBERS block · "Written for <climber>" · status lines ·
drive-from-home rows/fragments · research/regional CalTopo links (→ the share map) ·
site-internal links · third-party climber names (neutralized; Kyle stays).

NOTE: shares are OPEN by design — the token is the only lock. Don't share anything
that must stay truly private.
"""
from __future__ import annotations
import argparse, json, re, secrets, shutil, subprocess, sys
from datetime import date, timedelta
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
GPX = ROOT / "gpx"
SCRIPTS = ROOT / "scripts"
SITE_DIR = ROOT / "share_site"          # staged deploy dir (gitignored; regenerable)
LEDGER = ROOT / "share" / "ledger.json"  # committed source of truth
PROJECT = "mtn-share"
SHARE_HOST = f"https://{PROJECT}.pages.dev"
DEFAULT_TTL = 120

# Attribution header (Kyle, 2026-07-11): the BODY is author-neutral ("the author");
# who prepared it + how to reach him lives in one box at the top.
AUTHOR_NAME = "Kyle Knutson"
AUTHOR_EMAIL = "kyleg.knutson@gmail.com"
AUTHOR_14ERS = "https://www.14ers.com/forum/memberlist.php?mode=viewprofile&un=letsgocu"
AUTHOR_14ERS_LABEL = "14ers.com: letsgocu"

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
.prepared{background:#fdf2f8;border:1px solid #e6008c33;border-radius:6px;
padding:.6rem 1rem;margin:1rem 0;font-size:.95rem}
"""


def load_ledger():
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else []


def save_ledger(entries):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(entries, indent=1) + "\n")


def find_report(slug: str) -> Path:
    cands = (sorted((DOCS / "peaks").glob(f"{slug}*.md"))
             + sorted((DOCS / "trips").glob(f"{slug}*.md")))
    if not cands:
        sys.exit(f"ERROR: no report found for slug {slug!r}")
    return cands[0]


def source_track_count(slug: str) -> int:
    """Recorded GPS source tracks that informed the recommended route (same
    exclusions as the route builder's source pool)."""
    skip = ("peaks_only", "landmark", "trailhead", "recommended", "_drive",
            "drive_in", "waypoints", "summit", "target")
    return sum(1 for f in (GPX / slug).glob("*.gpx")
               if not any(s in f.name.lower() for s in skip))


def sanitize(text: str, share_map_url: str | None, slug: str) -> str:
    import yaml
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    text = re.sub(r"<!-- CLIMBERS_START -->.*?<!-- CLIMBERS_END -->\n?", "", text, flags=re.S)
    out = []
    for line in text.splitlines():
        low = line.lower()
        if (low.startswith("*written for") or low.startswith("**status for")
                or low.startswith("**status in db") or low.startswith("**researched:")
                or "| drive from" in low or "| **drive from" in low):
            continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\s*·\s*\*\*~?[\d.]+ ?h drive\*\*", "", text)
    if share_map_url:
        n_src = source_track_count(slug)
        text = re.sub(r"https://caltopo\.com/m/[A-Z0-9]+", share_map_url, text)
        # ONE map line (Kyle, 2026-07-11) + a provenance note; the PNG caption
        # link was redundant and is dropped.
        text = text.replace(
            "**CalTopo research map:**",
            "**Interactive CalTopo map with recommended route:**")
        text = re.sub(
            rf"^(\*\*Interactive CalTopo map with recommended route:\*\*.*)$",
            rf"\1\n*The recommended route was distilled from **{n_src} recorded GPS "
            rf"tracks** of real trips (14ers.com · ListsofJohn · peakbagger · the "
            rf"author's own recordings).*",
            text, flags=re.M)
        text = re.sub(r"\*\[Interactive CalTopo map\]\([^)]*\)[^\n]*\n?", "", text)
    else:
        text = re.sub(r"^.*caltopo\.com/m/.*$\n?", "", text, flags=re.M)
    text = re.sub(rf"\.\./maps/{slug}\.png", "map.png", text)
    text = re.sub(r"\[([^\]]+)\]\((?!http)[^)]+\.md[^)]*\)", r"\1", text)
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
    # the author is named ONCE, in the header box — body prose stays neutral
    text = re.sub(r"\bKyle Knutson(?:’s|'s)\b", "the author's", text)
    text = re.sub(r"\bKyle(?:’s|'s)\b", "the author's", text)
    text = re.sub(r"\bKyle Knutson\b", "the author", text)
    text = re.sub(r"\bKyle\b", "the author", text)
    return text


def render(entry) -> None:
    """(Re)generate share_site/s/<token>/ from the current report state."""
    report = find_report(entry["slug"])
    md = sanitize(report.read_text(), entry.get("share_map"), entry["slug"])
    body = markdown.markdown(md, extensions=["tables", "admonition", "fenced_code"])
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title = re.sub(r"<[^>]+>", "", m.group(1)) if m else entry["slug"]
    expires = (date.fromisoformat(entry["created"])
               + timedelta(days=entry.get("ttl_days", DEFAULT_TTL))).isoformat()
    # every external link opens a new tab (the report is the reader's home base)
    body = re.sub(r'<a href="(http[^"]+)"',
                  r'<a href="\1" target="_blank" rel="noopener noreferrer"', body)
    prepared = (f"<div class='prepared'>Prepared by <strong>{AUTHOR_NAME}</strong> — "
                f"questions: <a href='mailto:{AUTHOR_EMAIL}'>{AUTHOR_EMAIL}</a> · "
                f"<a href='{AUTHOR_14ERS}' target='_blank' rel='noopener noreferrer'>"
                f"{AUTHOR_14ERS_LABEL}</a></div>")
    # header box directly under the H1
    body = re.sub(r"(</h1>)", r"\1\n" + prepared.replace("\\", "\\\\"), body, count=1)
    html = (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<meta name='robots' content='noindex,nofollow'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title><style>{CSS}</style></head><body>\n{body}\n"
            f"<footer>Shared {entry['created']} · link expires ~{expires} · "
            f"conditions change — verify everything yourself</footer>"
            f"</body></html>\n")
    dest = SITE_DIR / "s" / entry["token"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(html)
    shutil.copyfile(DOCS / "maps" / f"{entry['slug']}.png", dest / "map.png")


def write_site_chrome():
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "index.html").write_text(
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='robots' content='noindex,nofollow'><title>—</title></head>"
        "<body></body></html>\n")
    (SITE_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (SITE_DIR / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n")


def new_share(slug: str, ttl: int, no_map: bool):
    entry = {"slug": slug, "token": secrets.token_hex(8),
             "source": find_report(slug).name, "share_map": None,
             "created": date.today().isoformat(), "ttl_days": ttl}
    if not no_map:
        title_m = re.search(r"^#\s+(.+)$", find_report(slug).read_text(), re.M)
        title = title_m.group(1).strip() if title_m else slug
        files = sorted((GPX / slug).glob("*recommended*.gpx"))
        pk = GPX / slug / f"{slug}_peaks_only.gpx"
        if pk.exists():
            files.append(pk)
        if not files:
            sys.exit(f"ERROR: no recommended routes under gpx/{slug}/")
        cmd = [str(SCRIPTS / "gpx_to_caltopo.py"), "--new-map", f"Share: {title}",
               "--sharing", "URL", "--marker-symbol", "peak", "--no-dedupe"]
        for f in files:
            cmd += ["--gpx", str(f)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"caltopo\.com/m/([A-Z0-9]+)", r.stdout)
        if not m:
            print(r.stdout[-800:], file=sys.stderr)
            sys.exit("ERROR: share CalTopo map creation failed")
        entry["share_map"] = f"https://caltopo.com/m/{m.group(1)}"
        print(f"share CalTopo map: {entry['share_map']}")
    write_site_chrome()
    render(entry)
    save_ledger(load_ledger() + [entry])
    print(f"\nShare link (after --publish): {SHARE_HOST}/s/{entry['token']}/")


def rebuild():
    write_site_chrome()
    live = load_ledger()
    for e in live:
        render(e)
    print(f"rebuilt {len(live)} share(s) into {SITE_DIR}")


def prune():
    keep, dropped = [], []
    for e in load_ledger():
        exp = date.fromisoformat(e["created"]) + timedelta(days=e.get("ttl_days", DEFAULT_TTL))
        (keep if date.today() <= exp else dropped).append(e)
    for e in dropped:
        shutil.rmtree(SITE_DIR / "s" / e["token"], ignore_errors=True)
        if e.get("share_map"):
            mid = e["share_map"].rsplit("/", 1)[-1]
            subprocess.run([str(SCRIPTS / "delete_caltopo_map.py"), mid, "--yes"])
        print(f"pruned {e['slug']} ({e['token']}, created {e['created']})")
    save_ledger(keep)
    print(f"{len(dropped)} expired share(s) pruned, {len(keep)} live. Run --publish to deploy.")


def publish():
    rebuild()   # always deploy from a fresh, ledger-true state
    r = subprocess.run(["npx", "-y", "wrangler", "pages", "deploy", str(SITE_DIR),
                        "--project-name", PROJECT, "--commit-dirty=true"],
                       capture_output=True, text=True)
    print(r.stdout[-1200:] or r.stderr[-1200:])
    if r.returncode != 0:
        sys.exit("ERROR: wrangler deploy failed (npx wrangler login? project created?)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--ttl-days", type=int, default=DEFAULT_TTL)
    ap.add_argument("--no-map", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--publish", action="store_true")
    args = ap.parse_args()

    if args.slug:
        new_share(args.slug, args.ttl_days, args.no_map)
    if args.prune:
        prune()
    if args.rebuild and not args.slug and not args.publish:
        rebuild()
    if args.publish:
        publish()
    if not any([args.slug, args.prune, args.rebuild, args.publish]):
        ap.print_help()


if __name__ == "__main__":
    main()
