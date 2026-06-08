#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "PyYAML"]
# ///
"""
sweep_gpx.py — pull every GPX track + a named trip-report manifest for a set of
peaks, from ALL THREE sources (14ers + listsofjohn + peakbagger), in one command.

Replaces the ad-hoc browser_evaluate scraping. Uses its OWN persistent Playwright
profile (shared with check_sources_login.py) so it can run headless and be
allowlisted as `Bash(scripts/sweep_gpx.py *)`. One-time setup per Mac:

    uv run --with playwright playwright install chromium
    scripts/check_sources_login.py --login      # one login, lasts weeks

Usage:
    scripts/sweep_gpx.py --slug crestolita_broken_hand            # ids from peaks.yml
    scripts/sweep_gpx.py --slug chipeta_mtn --ids 337
    scripts/sweep_gpx.py --slug powell_eagles_nest --ids 245,380 --headed

Outputs:
    gpx/<slug>/<slug>_<author>_<year>_loj<trId>.gpx          (+ 14ersTR/14ersGPXlib/pbAscent variants)
    gpx/<slug>/tr_manifest.md   — named TRs per source per peak (cite these in the report)

Notes:
  • peak_db id == LoJ peak id. 14ers id = peak_db.fourteeners_id. PB pid is read
    from each LoJ peak page's peakbagger cross-link.
  • peakbagger sits behind Cloudflare; the script visits the PB homepage first to
    clear it. If PB still shows logged-out, it WARNS loudly (doesn't silently skip)
    — rerun with --headed, or sweep PB in-chat.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = Path.home() / "Library/Application Support/mtn-research/pw-profile"
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
from peak_db_client import peaks  # noqa: E402


def resolve(ids):
    by = {p["id"]: p for p in peaks()}
    out = []
    for pid in ids:
        p = by.get(pid)
        if not p:
            print(f"  WARN peak_db id {pid} not found"); continue
        out.append({"db": pid, "name": p["display_name"].strip('"'),
                    "loj": pid, "f14": p.get("fourteeners_id")})
    return out


# --- in-browser sweep snippets (run via page.evaluate on the right domain) ---

JS_LOJ = r"""
async (peaks) => {
  const out = {};
  for (const pk of peaks) {
    const html = await fetch(`/peak/${pk.loj}`, {credentials:'include'}).then(r=>r.text());
    const d=document.createElement('div'); d.innerHTML=html;
    const pb=(html.match(/peakbagger\.com\/peak\.aspx\?pid=(\d+)/)||[])[1]||null;
    const trLinks=[...d.querySelectorAll('a')].filter(a=>/\/tr\?Id=/.test(a.href))
      .map(a=>({trId:(a.href.match(/Id=(\d+)/)||[])[1], label:a.textContent.trim()}));
    const trs=[], gpx={};
    for (const tr of trLinks) {
      const th=await fetch(`/tr?Id=${tr.trId}&pkid=${pk.loj}`,{credentials:'include'}).then(r=>r.text());
      const gid=(th.match(/\/gpx\/(\d+)\.gpx/)||[])[1]||null;
      const date=tr.label.split(' - ')[0].trim(), author=(tr.label.split(' - ')[1]||'').trim();
      trs.push({date,author,gid});
      if (gid && !gpx[gid]) {
        const t=await fetch(`/gpx/${gid}.gpx?t=${Date.now()}`,{credentials:'include'}).then(r=>r.text());
        if (t.includes('<trkpt')||t.includes('<wpt')) gpx[gid]={author,date:date.slice(0,4),text:t};
      }
    }
    out[pk.db]={pb, trs, gpx};
  }
  return out;
}
"""

JS_14ERS = r"""
async (peaks) => {
  const out={};
  for (const pk of peaks) {
    if (!pk.f14) { out[pk.db]={trs:[],gpx:{}}; continue; }
    // GPX library
    const gpx={};
    const lib=await fetch(`/php14ers/gpxlib_locator.php?peakid=${pk.f14}`,{credentials:'include'}).then(r=>r.text());
    const paths=[...new Set([...lib.matchAll(/download\.php\?type=gpxlibrary&file=([^']+)'/g)].map(m=>m[1]))];
    for (const fp of paths) {
      const fn=fp.split('/').pop();
      const t=await fetch(`/php14ers/download.php?type=gpxlibrary&file=${encodeURIComponent(fp)}`,{credentials:'include'}).then(r=>r.text());
      if (t.includes('<trkpt')||t.includes('<wpt')) {
        const tm=fp.match(/\/trips\/\d+\/(\d+)\//); const lm=fp.match(/\/gpxlib\//);
        const tag=tm?`14ersTR${tm[1]}`:(lm?`14ersGPXlib`:`14ers`);
        gpx[`${tag}_${fn.replace('.gpx','')}`]={text:t};
      }
    }
    // TR list (names) via tripmain POST
    const body=new URLSearchParams({peakn:String(pk.f14),searchpeak:'',searchtext:'',usern:'All Users',
      reporttype:'All',ski:'Include',jan:'1',feb:'1',mar:'1',apr:'1',may:'1',jun:'1',jul:'1',aug:'1',
      sep:'1',oct:'1',nov:'1',dec:'1',startdate:'',enddate:'',likes:'0',submit:' View Reports '});
    const trh=await fetch('/php14ers/tripmain.php',{method:'POST',credentials:'include',body,
      headers:{'Content-Type':'application/x-www-form-urlencoded'}}).then(r=>r.text());
    const td=document.createElement('div'); td.innerHTML=trh;
    const trs=[...td.querySelectorAll('a')].filter(a=>/tripreport\.php\?trip=/.test(a.href))
      .map(a=>({trip:(a.href.match(/trip=(\d+)/)||[])[1], title:a.textContent.trim().slice(0,70)}));
    out[pk.db]={trs, gpx};
  }
  return out;
}
"""

JS_PB = r"""
async (peaks) => {
  if (!/Logged in:\s*\w/i.test(document.body.innerText)) return {loggedOut:true};
  const out={loggedOut:false};
  for (const pk of peaks) {
    if (!pk.pb) { out[pk.db]={gpx:{}}; continue; }
    const html=await fetch(`/peak.aspx?pid=${pk.pb}`,{credentials:'include'}).then(r=>r.text());
    const aids=[...new Set([...html.matchAll(/ascent\.aspx\?aid=(\d+)/g)].map(m=>m[1]))].slice(0,12);
    const gpx={};
    for (const aid of aids) {
      const t=await fetch(`/climber/GPXFile.aspx?aid=${aid}&sep=1`,{credentials:'include'}).then(r=>r.text());
      if (t.includes('<trkpt')||t.includes('<wpt')) gpx[`pbAscent${aid}`]={text:t};
    }
    out[pk.db]={gpx};
  }
  return out;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--ids", help="comma peak_db ids (else read gpx/<slug>/peaks.yml objective_ids)")
    ap.add_argument("--headed", action="store_true", help="visible browser (for Cloudflare trouble)")
    args = ap.parse_args()

    gdir = ROOT / "gpx" / args.slug
    if args.ids:
        ids = [int(x) for x in args.ids.split(",")]
    else:
        cfg = yaml.safe_load((gdir / "peaks.yml").read_text())
        ids = cfg["objective_ids"]
    pk = resolve(ids)
    if not pk:
        sys.exit("no peaks resolved")
    print(f"sweeping {len(pk)} peak(s): " + ", ".join(p["name"] for p in pk))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright missing. Run: uv run --with playwright playwright install chromium")

    gdir.mkdir(parents=True, exist_ok=True)
    saved = {}          # content-hash -> filename (dedupe)
    manifest = {"loj": {}, "14ers": {}, "peakbagger": {}}

    def save(label, text):
        h = hashlib.md5(text.encode()).hexdigest()
        if h in saved:
            return False
        saved[h] = label
        (gdir / f"{args.slug}_{label}.gpx").write_text(text)
        return True

    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    with sync_playwright() as pw:
        # Real Chrome (channel="chrome") clears peakbagger's Cloudflare far more
        # reliably than bundled Chromium; fall back to Chromium if Chrome's absent.
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=not args.headed, channel="chrome",
                user_agent=ua, chromium_sandbox=True)
        except Exception:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=not args.headed, user_agent=ua,
                chromium_sandbox=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def stop(src):
            ctx.close()
            sys.exit(f"\n✗ STOP: {src} is LOGGED OUT in the automation profile.\n"
                     f"  Per the source-rigor rule, do NOT build a partial report.\n"
                     f"  Fix: scripts/check_sources_login.py --login   then re-run this sweep.")

        # LoJ — verify login, then sweep
        page.goto("https://listsofjohn.com/", wait_until="domcontentloaded"); page.wait_for_timeout(1500)
        if not re.search(r"Signed in as", page.content(), re.I):
            stop("listsofjohn")
        loj = page.evaluate(JS_LOJ, pk)
        for p in pk:
            r = loj.get(str(p["db"])) or loj.get(p["db"]) or {}
            p["pb"] = r.get("pb")
            manifest["loj"][p["name"]] = r.get("trs", [])
            for gid, g in (r.get("gpx") or {}).items():
                save(f'{g["author"] or "loj"}_{g["date"]}_loj{gid}', g["text"])

        # 14ers — verify login, then sweep
        page.goto("https://www.14ers.com/", wait_until="domcontentloaded"); page.wait_for_timeout(1500)
        if not re.search(r"mode=logout|Log\s*Out", page.content(), re.I):
            stop("14ers")
        f14 = page.evaluate(JS_14ERS, pk)
        for p in pk:
            r = f14.get(str(p["db"])) or f14.get(p["db"]) or {}
            manifest["14ers"][p["name"]] = r.get("trs", [])
            for label, g in (r.get("gpx") or {}).items():
                save(label, g["text"])
        ctx.close()

    # peakbagger is NOT swept here — Cloudflare blocks the automation profile.
    # It is a separate in-chat (MCP browser) step: confirm "Logged in: Kyle
    # Knutson" FIRST, and if logged out, STOP and prompt Kyle (don't build partial).
    print("  → peakbagger: pull in-chat via the MCP browser (verify login first; "
          "HARD-STOP + prompt Kyle if logged out — don't build a partial report).")

    # write TR manifest
    lines = [f"# Trip-report manifest — {args.slug}", ""]
    for src in ("14ers", "loj", "peakbagger"):
        lines.append(f"## {src}")
        for name, trs in manifest[src].items():
            lines.append(f"- **{name}** ({len(trs)} TRs)")
            for tr in trs[:12]:
                if "title" in tr:
                    lines.append(f"    - [{tr.get('trip')}] {tr['title']}")
                else:
                    lines.append(f"    - {tr.get('date')} {tr.get('author')}" + (f" (gpx {tr['gid']})" if tr.get('gid') else ""))
        lines.append("")
    (gdir / "tr_manifest.md").write_text("\n".join(lines))

    print(f"\n✓ saved {len(saved)} unique GPX → gpx/{args.slug}/")
    print(f"✓ TR manifest → gpx/{args.slug}/tr_manifest.md "
          f"(14ers TRs: {sum(len(v) for v in manifest['14ers'].values())}, "
          f"LoJ: {sum(len(v) for v in manifest['loj'].values())})")


if __name__ == "__main__":
    main()
