#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""
Retroactively restyle markers on each report's CalTopo research map:
  - summit markers (marker-symbol == "peak"): strip the verbose
    " (13,118', Class 2, UNCLIMBED)" suffix → just the peak name.
  - trailhead markers (coord-matched to a peaks.yml `kind: trailhead` landmark):
    CalTopo blue hiker icon (marker-symbol "hiking", color #0066FF).

    scripts/retro_restyle_markers.py            # dry run (prints planned changes)
    scripts/retro_restyle_markers.py --apply
    scripts/retro_restyle_markers.py --apply --slug baldy_lejos_trio   # one report
"""
from __future__ import annotations
import argparse, logging, math, re
from pathlib import Path
import yaml
logging.basicConfig(level=logging.ERROR)
from caltopo_python import CaltopoSession

ROOT = Path(__file__).resolve().parent.parent
CONFIG = str(ROOT / "scripts" / "cts.ini")
ACCOUNT = "kyleg.knutson@gmail.com"
TH_SYMBOL, TH_COLOR = "hiking", "#0066FF"
SNAP_M = 80.0


def hav(a, b, c, d):
    R = 6371000; p1, p2 = math.radians(a), math.radians(c)
    dp = math.radians(c - a); dl = math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def frontmatter(p: Path) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(), re.S)
    return (yaml.safe_load(m.group(1)) or {}) if m else {}


def trailheads(slug: str):
    y = ROOT / "gpx" / slug / "peaks.yml"
    if not y.exists():
        return []
    cfg = yaml.safe_load(y.read_text()) or {}
    return [(l["lat"], l["lon"], l["name"]) for l in (cfg.get("landmarks") or [])
            if l.get("kind") == "trailhead" and l.get("lat") is not None]


def clean_summit(title: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", title).strip()   # drop a trailing "(...)"


def reports():
    seen = {}
    for sub in ("peaks", "trips"):
        for md in sorted((ROOT / "docs" / sub).glob("*.md")):
            if md.stem.count(".") or md.stem == "index":
                continue
            cid = frontmatter(md).get("caltopo_id")
            if cid:
                seen.setdefault(cid, md.stem)   # dedupe shared map IDs
    return seen   # {map_id: slug}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--slug")
    args = ap.parse_args()

    targets = reports()
    if args.slug:
        targets = {c: s for c, s in targets.items() if s == args.slug}

    tot_sum = tot_th = 0
    for cid, slug in sorted(targets.items(), key=lambda kv: kv[1]):
        ths = trailheads(slug)
        s = CaltopoSession(domainAndPort="caltopo.com", mapID=cid, configpath=CONFIG, account=ACCOUNT)
        feats = s.getFeatures(featureClass="Marker") or []
        sums = thc = 0
        for f in feats:
            pr = f.get("properties") or {}
            geom = f.get("geometry") or {}
            c = geom.get("coordinates") or []
            if len(c) < 2:
                continue
            lon, lat = c[0], c[1]
            title = pr.get("title", "")
            sym = pr.get("marker-symbol", "")
            # summit: strip verbose title
            if sym == "peak":
                ct = clean_summit(title)
                if ct and ct != title:
                    print(f"  [{slug}] summit  {title!r} → {ct!r}")
                    if args.apply:
                        s.editFeature(id=f["id"], className="Marker", properties={"title": ct})
                    sums += 1
                continue
            # trailhead: coord-match to a kind:trailhead landmark
            if any(hav(lat, lon, t[0], t[1]) <= SNAP_M for t in ths):
                if pr.get("marker-symbol") != TH_SYMBOL or pr.get("marker-color") != TH_COLOR:
                    print(f"  [{slug}] TH      {title!r} → hiking/{TH_COLOR}")
                    if args.apply:
                        s.editFeature(id=f["id"], className="Marker",
                                      properties={"marker-symbol": TH_SYMBOL, "marker-color": TH_COLOR})
                    thc += 1
        if sums or thc:
            print(f"[{slug} / {cid}] {sums} summit title(s), {thc} trailhead(s)")
        tot_sum += sums; tot_th += thc
    print(f"\n{'APPLIED' if args.apply else 'DRY RUN'}: {tot_sum} summit titles, {tot_th} trailheads across {len(targets)} maps")


if __name__ == "__main__":
    main()
