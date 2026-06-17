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
  const PEAKS = __PEAKS__; const meta = {pb_pids:{}, loj_gpx:false, errors:[]};
  for (const p of PEAKS) { try {
    const h = await (await fetch('https://listsofjohn.com/peak/'+p.loj, {credentials:'include'})).text();
    const pid = (h.match(/peakbagger\.com\/peak\.aspx\?pid=(\d+)/i)||[])[1];
    if (pid) meta.pb_pids[p.loj] = pid;
    if (/href=["'][^"']*\.gpx/i.test(h)) meta.loj_gpx = true;
  } catch(e) { meta.errors.push('loj '+p.loj+': '+e.message); } }
  return JSON.stringify({_meta: JSON.stringify(meta)});
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
    for f in (GPX / slug).glob("trk_*.gpx"):
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
        st["loj_gpx"] = bool(meta.get("loj_gpx"))
        save_state(slug, st)
        print(f"  LoJ: verified pids {meta.get('pb_pids', {})}; loj_gpx={st['loj_gpx']}")
        if meta.get("errors"):
            print("  errors:", *meta["errors"], sep="\n    ")
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
    save_state(slug, st)
    print(f"  {src}: {written} new track(s) (total {n})")
    if meta.get("errors"):
        print("  errors:", *meta["errors"], sep="\n    ")


def finalize(slug):
    st = load_state(slug)
    c = st["counts"]
    sources = {
        "14ers": {"checked": True, "found": c.get("14ers", 0), "note": "gpxlib_locator.php"},
        "peakbagger": {"checked": True, "found": c.get("peakbagger", 0),
                       "note": f"verified pids {st.get('pids', {})}"},
        "listsofjohn": {"checked": True, "found": 0 if not st.get("loj_gpx") else -1,
                        "note": "no downloadable GPX (text TRs)" if not st.get("loj_gpx")
                                else "LoJ GPX present — fetch manually"},
    }
    (GPX / slug / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    print(f"  sources.json: 14ers={c.get('14ers',0)} peakbagger={c.get('peakbagger',0)} "
          f"listsofjohn={'0 (none)' if not st.get('loj_gpx') else 'present'}\n")
    subprocess.run([str(ROOT / "scripts" / "check_source_coverage.py"), slug])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--emit", choices=["loj", "14ers", "pb"])
    ap.add_argument("--ingest", nargs=2, metavar=("WHICH", "FILE"))
    ap.add_argument("--finalize", action="store_true")
    args = ap.parse_args()
    if args.emit:
        emit(args.slug, args.emit)
    elif args.ingest:
        ingest(args.slug, args.ingest[0], args.ingest[1])
    elif args.finalize:
        finalize(args.slug)
    else:
        ap.error("one of --emit / --ingest / --finalize required")


if __name__ == "__main__":
    main()
