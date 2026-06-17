#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "supabase"]
# ///
"""
sweep_peak.py — deterministic 3-source GPX sweep (14ers + peakbagger + LoJ).

Kyle (2026-06-16): the data-gathering shouldn't be "at the will of the LLM." This
codifies the *what/how* so the only manual step is running generated fetches in
the authenticated MCP browser. Everything else — which URLs, GPX extraction, the
VERIFIED peakbagger pid (peak_db's can be wrong — it mapped Gladstone to Mount
Wilcox), dedup, naming, sources.json, coverage — is deterministic here.

CORS reality (verified 2026-06-16): browser fetch only works SAME-ORIGIN for
these sites (14ers fetched fine from peakbagger.com but NOT from listsofjohn.com;
peakbagger only from peakbagger.com). So each source is fetched from its own
origin — three navigate+evaluate steps, with the peakbagger pid threaded from the
LoJ step via gpx/<slug>/.sweep_state.json.

Source patterns (verified live):
  loj    listsofjohn.com/peak/<id>  → verified peakbagger pid (cross-link) + gpx check
  14ers  14ers.com/php14ers/gpxlib_locator.php?peakid=<f14> → /usercontent/trips/.../*.gpx
  pb     peakbagger.com/peak.aspx?pid=<pid> → ascent.aspx?aid=<aid> →
         climber/GPXFile.aspx?aid=<aid>&sep=1   (only ascents that have a track)

Workflow (per peak/slug):
  1. scripts/sweep_peak.py --slug S --emit loj      # run on listsofjohn.com → file
     scripts/sweep_peak.py --slug S --ingest loj <file>
  2. scripts/sweep_peak.py --slug S --emit 14ers    # run on www.14ers.com → file
     scripts/sweep_peak.py --slug S --ingest 14ers <file>
  3. scripts/sweep_peak.py --slug S --emit pb        # run on peakbagger.com → file
     scripts/sweep_peak.py --slug S --ingest pb <file>
  4. scripts/sweep_peak.py --slug S --finalize       # sources.json + coverage check
Each --emit prints the URL to navigate to first, then the JS for browser_evaluate.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"


def state_path(slug):
    return GPX / slug / ".sweep_state.json"


def load_state(slug):
    p = state_path(slug)
    return json.loads(p.read_text()) if p.exists() else {"pids": {}, "loj_gpx": False,
                                                          "counts": {"14ers": 0, "peakbagger": 0}}


def save_state(slug, st):
    state_path(slug).write_text(json.dumps(st, indent=2) + "\n")


def objective_peaks(slug):
    cfg = yaml.safe_load((GPX / slug / "peaks.yml").read_text())
    ids = cfg.get("objective_ids") or []
    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    by = {p["id"]: p for p in peaks()}
    return [{"loj": i, "f14": by[i].get("fourteeners_id"), "name": by[i].get("display_name")}
            for i in ids if i in by]


# --- fetch JS per origin (each returns a JSON string) ---------------------------
JS_LOJ = r"""async () => {
  // LoJ GPX is NOT on the peak page — it's attached to individual trip reports.
  // Per peak: read the peak page (→ peakbagger pid cross-link + its TR ids), then
  // open each TR (tr?Id=<id>&pkid=<pkid>), pull its gpx id, and download
  // listsofjohn.com/gpx/<gpxid>.gpx. Not every TR has a track; that's fine.
  const PEAKS = __PEAKS__; const out = {}; const meta = {pb_pids:{}, tr_seen:0, errors:[]};
  for (const p of PEAKS) { try {
    const h = await (await fetch('https://listsofjohn.com/peak/'+p.loj, {credentials:'include'})).text();
    const pid = (h.match(/peakbagger\.com\/peak\.aspx\?pid=(\d+)/i)||[])[1];
    if (pid) meta.pb_pids[p.loj] = pid;
    const trs = [...new Set([...h.matchAll(/tr\?Id=(\d+)/gi)].map(m=>m[1]))];
    for (const tr of trs) { try {
      meta.tr_seen++;
      const t = await (await fetch('https://listsofjohn.com/tr?Id='+tr+'&pkid='+p.loj, {credentials:'include'})).text();
      const gid = (t.match(/\/gpx\/gpx_download\.php\?id=(\d+)/i) || t.match(/\/gpx\/(\d+)\.gpx/i) || [])[1];
      if (!gid) continue;
      const g = await (await fetch('https://listsofjohn.com/gpx/'+gid+'.gpx', {credentials:'include'})).text();
      if (g.includes('<trkpt')) out['trk_loj_'+gid] = g;
    } catch(e) { meta.errors.push('loj tr '+tr+': '+e.message); } }
  } catch(e) { meta.errors.push('loj '+p.loj+': '+e.message); } }
  out['_meta'] = JSON.stringify(meta);
  return JSON.stringify(out);
}"""

JS_14ERS = r"""async () => {
  const PEAKS = __PEAKS__; const out = {}; const errs = []; let n = 0;
  for (const p of PEAKS) { if (!p.f14) continue; try {
    const loc = await (await fetch('https://www.14ers.com/php14ers/gpxlib_locator.php?peakid='+p.f14, {credentials:'include'})).text();
    const urls = [...new Set([...loc.matchAll(/\/usercontent\/trips\/[^"'\s]*\.gpx/gi)].map(m=>m[0]))];
    for (const u of urls) {
      const g = await (await fetch('https://www.14ers.com'+u, {credentials:'include'})).text();
      if (g.includes('<trkpt')) out['trk_14ers_'+(++n)] = g;
    }
  } catch(e) { errs.push('14ers '+p.f14+': '+e.message); } }
  out['_meta'] = JSON.stringify({errors: errs}); return JSON.stringify(out);
}"""

JS_PB = r"""async () => {
  const PIDS = __PIDS__; const out = {}; const errs = []; let n = 0;
  for (const pid of PIDS) { try {
    const pk = await (await fetch('https://peakbagger.com/peak.aspx?pid='+pid, {credentials:'include'})).text();
    const aids = [...new Set([...pk.matchAll(/ascent\.aspx\?aid=(\d+)/g)].map(m=>m[1]))];
    for (const aid of aids) {
      const asc = await (await fetch('https://peakbagger.com/climber/ascent.aspx?aid='+aid, {credentials:'include'})).text();
      if (/GPXFile\.aspx/i.test(asc)) {
        const g = await (await fetch('https://peakbagger.com/climber/GPXFile.aspx?aid='+aid+'&sep=1', {credentials:'include'})).text();
        if (g.includes('<trkpt')) out['trk_pb_'+(++n)] = g;
      }
    }
  } catch(e) { errs.push('pb '+pid+': '+e.message); } }
  out['_meta'] = JSON.stringify({errors: errs}); return JSON.stringify(out);
}"""


def emit(slug, which):
    peaks = objective_peaks(slug)
    if which == "loj":
        url = f"https://listsofjohn.com/peak/{peaks[0]['loj']}" if peaks else "https://listsofjohn.com/"
        js = JS_LOJ.replace("__PEAKS__", json.dumps([{"loj": p["loj"]} for p in peaks]))
    elif which == "14ers":
        url = f"https://www.14ers.com/php14ers/peak.php?peakid={peaks[0]['f14']}" if peaks else "https://www.14ers.com/"
        js = JS_14ERS.replace("__PEAKS__", json.dumps([{"f14": p["f14"]} for p in peaks]))
    else:  # pb
        st = load_state(slug)
        pids = sorted(set(st.get("pids", {}).values()))
        if not pids:
            sys.exit("no pids yet — run `--emit loj` + `--ingest loj <file>` first")
        url = f"https://peakbagger.com/peak.aspx?pid={pids[0]}"
        js = JS_PB.replace("__PIDS__", json.dumps(pids))
    print(f"# 1) navigate the MCP browser to: {url}", file=sys.stderr)
    print(f"# 2) browser_evaluate(function=<the JS below>)  — then: sweep_peak.py --slug {slug} --ingest {which} <persisted-file>", file=sys.stderr)
    print(js)


def _unwrap(raw):
    if raw.lstrip().startswith("### Result"):
        body = raw.split("### Result", 1)[1]
        for end in ("\n### Ran", "\n### Open tabs", "\n### Page"):
            if end in body:
                body = body.split(end, 1)[0]
        raw = body.strip()
    data = raw
    for _ in range(3):
        if isinstance(data, dict):
            break
        data = json.loads(data)
    return data


def _sig(gpx):
    p = re.findall(r'lat="([-\d.]+)"\s+lon="([-\d.]+)"', gpx)
    if len(p) < 2:
        return None
    return (len(p), round(float(p[0][0]), 4), round(float(p[0][1]), 4),
            round(float(p[-1][0]), 4), round(float(p[-1][1]), 4))


def _existing_sigs(slug):
    sigs = set()
    for f in (GPX / slug).glob("*.gpx"):
        n = f.name.lower()
        if any(x in n for x in ("peaks_only", "landmark", "trailhead", "recommended",
                                "_drive", "drive_in", "waypoints", "summit", "actual", "kyle")):
            continue
        s = _sig(f.read_text())
        if s:
            sigs.add(s)
    return sigs


def ingest(slug, which, blob_path):
    data = _unwrap(Path(blob_path).read_text())
    meta = json.loads(data.pop("_meta", "{}")) if isinstance(data.get("_meta"), str) else {}
    st = load_state(slug)
    if which == "loj":
        st["pids"].update(meta.get("pb_pids", {}))
        st["swept"] = sorted(set(st.get("swept", []) + ["listsofjohn"]))
        # write harvested LoJ TR tracks (dedup against disk), keep the gpx id in
        # the filename so it's traceable back to the LoJ trip report
        seen = _existing_sigs(slug)
        written = 0
        for name, gpx in sorted(data.items()):
            if not isinstance(gpx, str) or "<trkpt" not in gpx:
                continue
            sig = _sig(gpx)
            if sig and sig in seen:
                print(f"  dedup {name}"); continue
            if sig:
                seen.add(sig)
            (GPX / slug / f"{name}.gpx").write_text(gpx)
            written += 1
            print(f"  wrote {name}.gpx ({len(gpx)//1024} KB)")
        st["loj_gpx"] = _count_on_disk(slug)["listsofjohn"] > 0
        save_state(slug, st)
        print(f"  LoJ: {written} new track(s); TRs seen {meta.get('tr_seen', '?')}; "
              f"verified pids {meta.get('pb_pids', {})}")
        if meta.get("errors"):
            print("  errors:", *meta["errors"][:5], sep="\n    ")
        return
    # 14ers / pb: write track files, dedup against what's on disk
    seen = _existing_sigs(slug)
    src = "14ers" if which == "14ers" else "peakbagger"
    n = st["counts"].get(src, 0)
    written = 0
    for name, gpx in sorted(data.items()):
        if not isinstance(gpx, str) or "<trkpt" not in gpx:
            continue
        sig = _sig(gpx)
        if sig and sig in seen:
            print(f"  dedup {name}"); continue
        seen.add(sig)
        n += 1
        fn = f"trk_{'14ers' if which=='14ers' else 'pb'}_{n}.gpx"
        (GPX / slug / fn).write_text(gpx)
        written += 1
        print(f"  wrote {fn} ({len(gpx)//1024} KB)")
    st["counts"][src] = n
    st["swept"] = sorted(set(st.get("swept", []) + [src]))
    save_state(slug, st)
    print(f"  {src}: {written} new track(s) (total {n})")
    if meta.get("errors"):
        print("  errors:", *meta["errors"], sep="\n    ")


def _count_on_disk(slug):
    """Actual track files present, by source — so finalize is accurate even when
    only some source steps were re-run (e.g. add pb/loj to a report that already
    has 14ers tracks, without re-fetching/renumbering 14ers)."""
    c = {"14ers": 0, "peakbagger": 0, "listsofjohn": 0}
    skip = ("peaks_only", "landmark", "trailhead", "recommended", "_drive",
            "drive_in", "waypoints", "summit", "actual", "kyle")
    for f in (GPX / slug).glob("*.gpx"):
        n = f.name.lower()
        if any(x in n for x in skip):
            continue
        if "14ers" in n:
            c["14ers"] += 1
        elif "_pb_" in n or "peakbagger" in n:
            c["peakbagger"] += 1
        elif "_loj_" in n or "listsofjohn" in n:
            c["listsofjohn"] += 1
    return c


def finalize(slug):
    st = load_state(slug)
    c = _count_on_disk(slug)
    swept = set(st.get("swept", []))
    # LoJ was checked globally by the batch loj step (tmp_lojgpx.json). If that
    # evidence covers ALL this report's objectives, LoJ counts as honestly swept
    # (so a 0-file LoJ is a real verified-empty, not an unchecked claim).
    lg = ROOT / "tmp_lojgpx.json"
    if lg.exists():
        ev = json.loads(lg.read_text())
        objs = [str(i) for i in _objs(slug)]
        if objs and all(o in ev for o in objs):
            swept.add("listsofjohn")

    def rec(src, found, note_found, note_empty):
        # files present → covered. 0 files but this source was ACTUALLY swept this
        # session → honest verified-empty. 0 files and NOT swept → checked:false, so
        # check_source_coverage keeps FAILing (no authority to claim empty unchecked).
        if found:
            return {"checked": True, "found": found, "note": note_found}
        if src in swept:
            return {"checked": True, "found": 0, "note": note_empty}
        return {"checked": False, "found": 0, "note": "NOT SWEPT — re-run this source's sweep"}

    sources = {
        "14ers": rec("14ers", c["14ers"], "gpxlib_locator.php", "no 14ers library / not a 14ers.com peak"),
        "peakbagger": rec("peakbagger", c["peakbagger"],
                          f"verified pids {st.get('pids', {})}", "no ascents with downloadable GPS tracks"),
        "listsofjohn": rec("listsofjohn", c["listsofjohn"],
                           "LoJ member GPX tracks", "no downloadable GPX (text TRs only)"),
    }
    (GPX / slug / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    unchecked = [s for s, v in sources.items() if not v["checked"]]
    print(f"  sources.json: 14ers={c['14ers']} peakbagger={c['peakbagger']} listsofjohn={c['listsofjohn']}"
          + (f"  ⚠ NOT SWEPT: {', '.join(unchecked)}" if unchecked else "") + "\n")
    subprocess.run([str(ROOT / "scripts" / "check_source_coverage.py"), slug])


# ============================ BATCH (whole backlog) ============================
# One consolidated fetch per source-origin covering every peak that NEEDS that
# source, tracks keyed by peak id, then distributed to each report by objective.
# 14ers is only fetched for reports that lack it (never renumber existing routes).

SLUG_FILTER = None   # set by --slugs to scope the batch to a few reports (chunking)


def _all_reports():
    out = []
    for d in (ROOT / "docs" / "peaks", ROOT / "docs" / "trips"):
        for p in sorted(d.glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index."):
                continue
            slug = p.stem.split(".")[0]
            yml = GPX / slug / "peaks.yml"
            if yml.exists():
                out.append(slug)
    out = sorted(set(out))
    if SLUG_FILTER:
        out = [s for s in out if s in SLUG_FILTER]
    return out


def _objs(slug):
    cfg = yaml.safe_load((GPX / slug / "peaks.yml").read_text()) or {}
    return cfg.get("objective_ids") or []


def _disk_counts(slug):
    return _count_on_disk(slug)   # single source of truth (globs *.gpx + tokens)


def _peakdb_by_id():
    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    return {p["id"]: p for p in peaks()}


def batch_plan():
    """{slug: {'need14','needpb', objs:[ids]}} + peak metadata."""
    by = _peakdb_by_id()
    plan = {}
    for slug in _all_reports():
        objs = _objs(slug)
        c = _disk_counts(slug)
        plan[slug] = {"objs": objs,
                      "need14": c["14ers"] == 0 and any(by.get(i, {}).get("fourteeners_id") for i in objs),
                      "needpb": c["peakbagger"] == 0,
                      "needloj_check": True}
    return plan, by


def emit_batch(which):
    plan, by = batch_plan()
    if which == "loj":
        ids = sorted({i for s in plan.values() for i in s["objs"]})
        peaks = [{"loj": i} for i in ids]
        url = "https://listsofjohn.com/peak/" + str(ids[0]) if ids else "https://listsofjohn.com/"
        js = (r"""async () => { const PEAKS = __P__; const meta = {pid:{}, loj_gpx:{}, errors:[]};
for (const p of PEAKS){ try { const h = await (await fetch('https://listsofjohn.com/peak/'+p.loj,{credentials:'include'})).text();
  const pid=(h.match(/peakbagger\.com\/peak\.aspx\?pid=(\d+)/i)||[])[1]; if(pid) meta.pid[p.loj]=pid;
  meta.loj_gpx[p.loj]=/href=["'][^"']*\.gpx/i.test(h);
} catch(e){ meta.errors.push('loj '+p.loj+': '+e.message);} }
return JSON.stringify({_meta:JSON.stringify(meta)}); }""").replace("__P__", json.dumps(peaks))
    elif which == "14ers":
        f14 = sorted({by[i]["fourteeners_id"] for s in plan.values() if s["need14"]
                      for i in s["objs"] if by.get(i, {}).get("fourteeners_id")})
        peaks = [{"f14": x} for x in f14]
        url = f"https://www.14ers.com/php14ers/peak.php?peakid={f14[0]}" if f14 else "https://www.14ers.com/"
        js = (r"""async () => { const PEAKS = __P__; const out = {}; const errs=[];
for (const p of PEAKS){ try { const loc = await (await fetch('https://www.14ers.com/php14ers/gpxlib_locator.php?peakid='+p.f14,{credentials:'include'})).text();
  const urls=[...new Set([...loc.matchAll(/\/usercontent\/trips\/[^"'\s]*\.gpx/gi)].map(m=>m[0]))]; let n=0;
  for(const u of urls){ const g=await (await fetch('https://www.14ers.com'+u,{credentials:'include'})).text();
    if(g.includes('<trkpt')) out['f14_'+p.f14+'_'+(++n)]=g; }
} catch(e){ errs.push('14ers '+p.f14+': '+e.message);} }
out['_meta']=JSON.stringify({errors:errs}); return JSON.stringify(out); }""").replace("__P__", json.dumps(peaks))
    else:  # pb — needs pid map from loj step
        pidmap = json.loads((ROOT / "tmp_pidmap.json").read_text()) if (ROOT / "tmp_pidmap.json").exists() else {}
        # pids for peaks belonging to reports that need pb
        want = {str(i) for s in plan.values() if s["needpb"] for i in s["objs"]}
        pids = sorted({pidmap[k] for k in want if k in pidmap})
        peaks = [{"pid": x} for x in pids]
        url = f"https://peakbagger.com/peak.aspx?pid={pids[0]}" if pids else "https://peakbagger.com/"
        js = (r"""async () => { const PEAKS = __P__; const out={}; const errs=[];
for (const p of PEAKS){ try { const pk=await (await fetch('https://peakbagger.com/peak.aspx?pid='+p.pid,{credentials:'include'})).text();
  const aids=[...new Set([...pk.matchAll(/ascent\.aspx\?aid=(\d+)/g)].map(m=>m[1]))]; let n=0;
  for(const aid of aids){ const asc=await (await fetch('https://peakbagger.com/climber/ascent.aspx?aid='+aid,{credentials:'include'})).text();
    if(/GPXFile\.aspx/i.test(asc)){ const g=await (await fetch('https://peakbagger.com/climber/GPXFile.aspx?aid='+aid+'&sep=1',{credentials:'include'})).text();
      if(g.includes('<trkpt')) out['pb_'+p.pid+'_'+(++n)]=g; } }
} catch(e){ errs.push('pb '+p.pid+': '+e.message);} }
out['_meta']=JSON.stringify({errors:errs}); return JSON.stringify(out); }""").replace("__P__", json.dumps(peaks))
    print(f"# navigate to: {url}\n# then browser_evaluate(<JS below>); persist; sweep_peak.py --ingest-batch {which} <file>", file=sys.stderr)
    print(js)


def ingest_batch(which, blob_path):
    data = _unwrap(Path(blob_path).read_text())
    meta = json.loads(data.pop("_meta", "{}")) if isinstance(data.get("_meta"), str) else {}
    plan, by = batch_plan()
    if which == "loj":
        pidmap = meta.get("pid", {})
        (ROOT / "tmp_pidmap.json").write_text(json.dumps(pidmap))
        (ROOT / "tmp_lojgpx.json").write_text(json.dumps(meta.get("loj_gpx", {})))
        print(f"  resolved {len(pidmap)} peakbagger pids; saved to tmp_pidmap.json")
        if meta.get("errors"): print("  errors:", *meta["errors"][:5], sep="\n    ")
        return
    # group fetched tracks by source-key id
    bykey = {}
    for name, gpx in data.items():
        if not isinstance(gpx, str) or "<trkpt" not in gpx:
            continue
        m = re.match(r"(f14|pb)_(\d+)_\d+", name)
        if m:
            bykey.setdefault(m.group(2), []).append(gpx)
    pidmap = json.loads((ROOT / "tmp_pidmap.json").read_text()) if (ROOT / "tmp_pidmap.json").exists() else {}
    pid_for = {str(loj): pid for loj, pid in pidmap.items()}
    written = 0
    for slug, s in plan.items():
        if which == "14ers" and not s["need14"]:
            continue
        if which == "pb" and not s["needpb"]:
            continue
        seen = _existing_sigs(slug)
        n = _disk_counts(slug)["14ers" if which == "14ers" else "peakbagger"]
        for i in s["objs"]:
            key = str(by[i]["fourteeners_id"]) if which == "14ers" and by.get(i, {}).get("fourteeners_id") else pid_for.get(str(i))
            for gpx in bykey.get(str(key), []) if key else []:
                sig = _sig(gpx)
                if sig and sig in seen:
                    continue
                seen.add(sig)
                n += 1
                fn = f"trk_{'14ers' if which=='14ers' else 'pb'}_{n}.gpx"
                (GPX / slug / fn).write_text(gpx)
                written += 1
        print(f"  {slug}: {which} now {_disk_counts(slug)['14ers' if which=='14ers' else 'peakbagger']}")
    (ROOT / f"tmp_swept_{which}.flag").write_text("1")   # integrity: this source WAS fetched
    print(f"\n  wrote {written} {which} track(s) across reports")


def finalize_batch():
    # Integrity: the LoJ pid/gpx step must have run (it's how we know LoJ-empty +
    # which pids exist). peakbagger verified-empty (found=0) is only honest if the
    # pb batch ran — so per report we SKIP finalizing any report still missing pb
    # unless the pb sweep flag is present (leave it failing for a later pass).
    if not (ROOT / "tmp_pidmap.json").exists():
        sys.exit("refusing finalize: LoJ step hasn't run (no tmp_pidmap.json)")
    pb_swept = (ROOT / "tmp_swept_pb.flag").exists()
    lojgpx = json.loads((ROOT / "tmp_lojgpx.json").read_text()) if (ROOT / "tmp_lojgpx.json").exists() else {}
    pidmap = json.loads((ROOT / "tmp_pidmap.json").read_text()) if (ROOT / "tmp_pidmap.json").exists() else {}
    plan, by = batch_plan()
    # integrity: every report that still NEEDS 14ers must have gotten it (else the
    # 14ers batch wasn't run / failed) — don't finalize over a half-done sweep.
    still14 = [s for s in plan if plan[s]["need14"] and _disk_counts(s)["14ers"] == 0]
    if still14 and not (ROOT / "tmp_swept_14ers.flag").exists():
        sys.exit(f"refusing finalize: {len(still14)} report(s) still need 14ers "
                 f"(run the 14ers batch): {', '.join(still14[:6])}")
    wrote = 0
    for slug in plan:
        if (GPX / slug / "sources.json").exists():
            continue   # already verified (e.g. Gladstone) — leave it alone
        c = _disk_counts(slug)
        if c["peakbagger"] == 0 and not pb_swept:
            continue   # can't honestly claim pb verified-empty yet — later pass
        objs = [str(i) for i in plan[slug]["objs"]]
        loj_any = any(lojgpx.get(o) for o in objs)
        pids = {o: pidmap[o] for o in objs if o in pidmap}
        sources = {
            "14ers": {"checked": True, "found": c["14ers"], "note": "gpxlib_locator.php"
                      if c["14ers"] else "not a 14ers.com peak / no library"},
            "peakbagger": {"checked": True, "found": c["peakbagger"],
                           "note": f"verified pids {pids}" if c["peakbagger"]
                                   else "no ascents with downloadable GPS tracks"},
            "listsofjohn": {"checked": True, "found": c["listsofjohn"],
                            "note": "LoJ member GPX tracks" if c["listsofjohn"]
                                    else "no downloadable GPX (text TRs only)"},
        }
        (GPX / slug / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
        wrote += 1
    print(f"  wrote sources.json for {wrote} report(s) (skipped already-verified + pb-incomplete)")
    subprocess.run([str(ROOT / "scripts" / "check_source_coverage.py")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--emit", choices=["loj", "14ers", "pb"])
    ap.add_argument("--ingest", nargs=2, metavar=("WHICH", "FILE"))
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--emit-batch", choices=["loj", "14ers", "pb"], dest="emit_batch")
    ap.add_argument("--ingest-batch", nargs=2, metavar=("WHICH", "FILE"), dest="ingest_batch")
    ap.add_argument("--finalize-batch", action="store_true", dest="finalize_batch")
    ap.add_argument("--slugs", help="comma-separated report slugs to scope a batch (chunking)")
    args = ap.parse_args()
    if args.slugs:
        global SLUG_FILTER
        SLUG_FILTER = set(args.slugs.split(","))
    if args.emit_batch:
        emit_batch(args.emit_batch)
    elif args.ingest_batch:
        ingest_batch(args.ingest_batch[0], args.ingest_batch[1])
    elif args.finalize_batch:
        finalize_batch()
    elif args.emit:
        emit(args.slug, args.emit)
    elif args.ingest:
        ingest(args.slug, args.ingest[0], args.ingest[1])
    elif args.finalize:
        finalize(args.slug)
    else:
        ap.error("one of --emit / --ingest / --finalize required")


if __name__ == "__main__":
    main()
