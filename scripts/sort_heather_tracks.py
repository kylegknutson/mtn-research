#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
sort_heather_tracks.py — match Heather's downloaded GPX (gpx/heather/) to reports by LOCATION:
a track that passes within COVER_M of a report's objective summit "covers" that objective.
Tracks that cover a report's objectives are her real recorded line for it — exactly what the
route builder wants. Dry-run by default (prints matches); --copy drops matched tracks into
gpx/<slug>/heather_<id>.gpx (only those covering >= --min-cover objectives of that report).

    scripts/sort_heather_tracks.py                 # dry run, all reports
    scripts/sort_heather_tracks.py --unclimbed     # only unclimbed reports
    scripts/sort_heather_tracks.py --copy --min-frac 1.0   # copy full-coverage matches
"""
from __future__ import annotations
import argparse, math, re, shutil
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
HEATHER = GPX / "heather"
NS = "{http://www.topografix.com/GPX/1/1}"
COVER_M = 250.0          # track must pass this close to a summit to "cover" it
STEP = 8                 # sample every Nth track point (speed; fine at 250 m)


def hav(a, b, c, d):
    R = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))


def trkpts(p: Path):
    try:
        root = ET.parse(p).getroot()
    except Exception:
        return []
    return [(float(t.get("lat")), float(t.get("lon"))) for t in root.iter(NS+"trkpt")]


def objectives(slug):
    d = GPX / slug
    pk = next(d.glob("*peaks_only*.gpx"), None)
    if not pk:
        return []
    out = []
    for w in ET.parse(pk).getroot().iter(NS+"wpt"):
        nm = w.find(NS+"name")
        out.append(((float(w.get("lat")), float(w.get("lon"))), (nm.text if nm is not None else "").split(" (")[0]))
    return out


def report_slugs(unclimbed_only):
    out = []
    for sub in ("peaks", "trips"):
        for p in sorted((DOCS/sub).glob("*.md")):
            if p.stem == "index" or p.stem.count("."):
                continue
            if not (GPX/p.stem/"peaks.yml").exists():
                continue
            if unclimbed_only:
                txt = p.read_text()
                if not re.search(r"^status:\s*unclimbed", txt, re.M):
                    continue
            out.append(p.stem)
    return out


def covers(track_pts, objs):
    """min distance from each objective to the sampled track; return list of covered names."""
    if not track_pts:
        return []
    samp = track_pts[::STEP] or track_pts
    hit = []
    for (la, lo), nm in objs:
        best = min(hav(la, lo, p[0], p[1]) for p in samp)
        if best <= COVER_M:
            hit.append(nm)
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unclimbed", action="store_true")
    ap.add_argument("--copy", action="store_true")
    ap.add_argument("--min-frac", type=float, default=0.6, help="copy if track covers >= this fraction of a report's objectives")
    args = ap.parse_args()

    htracks = [(f, trkpts(f)) for f in sorted(HEATHER.glob("*.gpx"))]
    slugs = report_slugs(args.unclimbed)
    objs = {s: objectives(s) for s in slugs}

    copied = 0
    for s in slugs:
        ob = objs[s]
        if not ob:
            continue
        matches = []
        for f, pts in htracks:
            hit = covers(pts, ob)
            if hit:
                matches.append((len(hit), len(ob), f, hit))
        if not matches:
            continue
        matches.sort(reverse=True)
        print(f"\n## {s}  ({len(ob)} objectives: {', '.join(n for _,n in ob)})")
        for nh, ntot, f, hit in matches:
            frac = nh/ntot
            mark = "★" if frac >= args.min_frac else " "
            print(f"  {mark} {nh}/{ntot}  {f.name[:60]}   [{', '.join(hit)}]")
            if args.copy and frac >= args.min_frac:
                mid = re.search(r"__(\d+)\.gpx$", f.name)
                dest = GPX/s/f"heather_{mid.group(1) if mid else f.stem}.gpx"
                if not dest.exists():
                    shutil.copy(f, dest); copied += 1
    if args.copy:
        print(f"\nCopied {copied} track(s) into report dirs.")
    else:
        print("\n(dry run — re-run with --copy to drop ★ matches into gpx/<slug>/)")


if __name__ == "__main__":
    main()
