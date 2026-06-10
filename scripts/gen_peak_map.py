#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
gen_peak_map.py — emit docs/data/peaks.json for the interactive home-page map.

Pulls every ranked Colorado peak (13ers + 14ers) from peak_db, then flags which
ones have a research report by reading each gpx/<slug>/peaks.yml `objective_ids`
(+ `extra_summits`) and matching to docs/peaks/<slug>.md or docs/trips/<slug>.md.

Output (compact) consumed by docs/javascripts/peak-map.js:
    { "generated": "...", "counts": {...},
      "peaks": [ {id, n(ame), ft, lat, lon, rng, r(ank), f(ourteener), u(rl), t(itle)} ] }

Run after adding/editing a report (build_report --finalize calls it):
    scripts/gen_peak_map.py
    scripts/gen_peak_map.py --check   # exit 1 if peaks.json is stale
"""
from __future__ import annotations
import argparse, json, re, sys
from datetime import date
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
OUT = DOCS / "data" / "peaks.json"
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"


def report_for(slug: str):
    """(url, title) for a slug's report, or None. mkdocs uses directory URLs."""
    for sub in ("peaks", "trips"):
        p = DOCS / sub / f"{slug}.md"
        if p.exists():
            m = re.search(r"^#\s+(.+)$", p.read_text(), re.M)
            title = (m.group(1).strip() if m else slug.replace("_", " ").title())
            return f"{sub}/{slug}/", title
    return None


def frontmatter(p: Path) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
    return yaml.safe_load(m.group(1)) if m else {}


def id_to_report() -> dict[int, tuple[str, str]]:
    """peak_db id -> (url, title), from each gpx/<slug>/peaks.yml `objective_ids`,
    falling back to a report's frontmatter `peak_ids` when it has no peaks.yml."""
    out = {}
    # 1) gpx/<slug>/peaks.yml objective_ids
    for yml in sorted(GPX.glob("*/peaks.yml")):
        rep = report_for(yml.parent.name)
        if not rep:
            continue
        try:
            cfg = yaml.safe_load(yml.read_text()) or {}
        except Exception:
            continue
        for oid in (cfg.get("objective_ids") or []):
            out.setdefault(int(oid), rep)
    # 2) frontmatter peak_ids fallback (reports without a peaks.yml)
    for sub in ("peaks", "trips"):
        for md in sorted((DOCS / sub).glob("*.md")):
            if md.stem.count(".") or md.stem == "index":
                continue
            for pid in (frontmatter(md).get("peak_ids") or []):
                m = re.search(r"^#\s+(.+)$", md.read_text(), re.M)
                title = m.group(1).strip() if m else md.stem
                out.setdefault(int(pid), (f"{sub}/{md.stem}/", title))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks as _peaks, ascents as _ascents

    reports = id_to_report()
    climbed = {a["peak_id"] for a in _ascents() if a.get("peak_id") is not None}
    feats = []
    n_rep = n_14 = n_climbed = n_todo = n_with_report = 0
    for p in _peaks():
        if not p.get("ranked"):
            continue
        if p.get("state") not in ("CO", "Colorado"):
            continue   # Colorado 13ers/14ers only (peak_db also holds other states' lists)
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        ft = p.get("elevation_ft") or 0
        is14 = ft >= 14000
        rep = reports.get(p["id"])
        is_climbed = p["id"] in climbed
        rec = {
            "id": p["id"],
            "n": (p.get("display_name") or "").strip().strip('"'),
            "ft": ft,
            "lat": round(lat, 5), "lon": round(lon, 5),
            "rng": p.get("range") or "",
            "r": p.get("co_rank"),
            "f": 1 if is14 else 0,
        }
        # Always attach the report link if one exists — a climbed peak keeps its
        # old report (just shown grey). Color precedence: climbed (grey) wins over
        # reported (green); todo (red) is the rest. So a researched peak turns grey
        # the moment it's in the climb log, but stays clickable to the report.
        if rep:
            rec["u"], rec["t"] = rep
            n_with_report += 1
        if is_climbed:
            rec["s"] = "done"; rec["c"] = 1; n_climbed += 1
        elif rep:
            rec["s"] = "rep"; n_rep += 1
        else:
            rec["s"] = "todo"; n_todo += 1
        if is14:
            n_14 += 1
        feats.append(rec)

    feats.sort(key=lambda r: -(r["ft"] or 0))
    payload = {
        "generated": date.today().isoformat(),
        "counts": {"total": len(feats), "fourteeners": n_14,
                   "green": n_rep, "climbed": n_climbed, "todo": n_todo,
                   "with_report": n_with_report,
                   "reports": len(set(id(r) for r in reports.values()))},
        "peaks": feats,
    }
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    if args.check:
        cur = OUT.read_text() if OUT.exists() else ""
        # compare ignoring the generated date line
        norm = lambda s: re.sub(r'"generated":"[^"]*",', "", s)
        if norm(cur) != norm(text):
            print("peaks.json is STALE — run scripts/gen_peak_map.py", file=sys.stderr)
            sys.exit(1)
        print("peaks.json current"); return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    c = payload["counts"]
    print(f"wrote {OUT.relative_to(ROOT)} — {c['total']} ranked peaks "
          f"({c['fourteeners']} 14ers), {c['with_report']} peaks across reports")
    # show any report whose peaks didn't map (helps catch missing peaks.yml)
    mapped_slugs = {u for u, _ in reports.values()}
    all_reports = {f"{s}/{p.stem}/" for s in ("peaks", "trips")
                   for p in (DOCS / s).glob("*.md") if p.stem.count(".") == 0 and p.stem != "index"}
    unmapped = sorted(all_reports - mapped_slugs)
    if unmapped:
        print(f"  note: {len(unmapped)} report(s) not on the map (no peaks.yml objective_ids): "
              + ", ".join(unmapped))


if __name__ == "__main__":
    main()
