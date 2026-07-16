#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML","supabase"]
# ///
"""
check_coordinates.py — every coordinate a report PRINTS must sit on the peak.

Kyle (2026-07-15): brown_mountain.md shipped its "Lat / Lon" row and its NOAA
forecast link at lon −108.63785 — a full degree (≈54 mi) west of Brown Mtn A's
real −107.63785. A digit slip in a hand-typed coordinate, and nothing caught it:
no gate compared a report's stated coordinates against peak_db. This closes that
hole (the same class the class/route/source gates each closed for their field).

For each report it extracts every printed coordinate —
  * "| Lat / Lon | LAT, LON | …" table cells (one per objective; unicode minus), and
  * NOAA MapClick links (forecast.weather.gov/MapClick.php?lat=…&lon=…) in the body
    AND the frontmatter `weather:` field —
and FAILs (with --strict) any that lands more than --tol-mi (default 8) from the
NEAREST objective summit (peak_db coords for the report's peak_ids / objective_ids).

8 mi clears legitimate variance — a per-peak summit matches its own peak at ~0 mi,
and a trip's deliberately-central weather point sits within ~2.5 mi of its nearest
peak ("all N within ~5 mi") — while a degree-scale typo (≈50+ mi) always fails.

Usage:
  scripts/check_coordinates.py                 # audit all reports (advisory)
  scripts/check_coordinates.py brown_mountain
  scripts/check_coordinates.py --strict        # gate
"""
from __future__ import annotations
import argparse, math, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from gpx_root import gpx_file   # worktree-aware peaks.yml resolution
PEAKDB = "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db"
NOAA_RE = re.compile(r"MapClick\.php\?lat=([-\d.−–—]+)&lon=([-\d.−–—]+)")
# a lat,lon pair inside a table cell (tolerates a leading ~ and a trailing "(verify)")
PAIR_RE = re.compile(r"(-?[\d.−–—]+)\s*,\s*(-?[\d.−–—]+)")
DASHES = str.maketrans({"−": "-", "–": "-", "—": "-"})


def to_float(s):
    try:
        return float(s.translate(DASHES).strip())
    except (ValueError, AttributeError):
        return None


def plausible(lat, lon) -> bool:
    # broad US-West window — rejects an elevation like "13,347" parsed as a pair,
    # but keeps a degree-typo (e.g. −108.6 for a −107.6 peak) so distance can flag it.
    return lat is not None and lon is not None and 24 <= lat <= 50 and -125 <= lon <= -100


def hav_mi(a, b, c, d):
    R = 3958.8
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def frontmatter(md_text):
    m = re.match(r"^---\n(.*?)\n---\n", md_text, re.S)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}


def printed_coords(text):
    """[(kind, lat, lon), …] every coordinate the report prints."""
    out = []
    for line in text.splitlines():                       # "| Lat / Lon | lat, lon | …"
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        labels = [i for i, c in enumerate(cells)
                  if re.sub(r"\s", "", c).lower().startswith("lat/lon")]
        if not labels:
            continue
        for c in cells[labels[0] + 1:]:
            mm = PAIR_RE.search(c)
            if mm:
                la, lo = to_float(mm.group(1)), to_float(mm.group(2))
                if plausible(la, lo):
                    out.append(("Lat/Lon row", la, lo))
    for mm in NOAA_RE.finditer(text):                    # NOAA links (body + frontmatter)
        la, lo = to_float(mm.group(1)), to_float(mm.group(2))
        if plausible(la, lo):
            out.append(("NOAA link", la, lo))
    return out


def objective_ids(fm, base):
    ids = fm.get("peak_ids")
    if not ids:
        yml = gpx_file(ROOT, base, "peaks.yml")
        if yml.exists():
            try:
                ids = (yaml.safe_load(yml.read_text()) or {}).get("objective_ids")
            except Exception:
                ids = None
    return [int(i) for i in (ids or []) if str(i).lstrip("-").isdigit()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--tol-mi", type=float, default=8.0)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, PEAKDB)
    from peak_db_client import peaks
    P = {p["id"]: p for p in peaks()}

    md_files = []
    for d in (ROOT / "docs" / "peaks", ROOT / "docs" / "trips"):
        md_files += sorted(d.glob("*.md"))
    fails = checked = 0
    for md in md_files:
        slug = md.stem
        if slug == "index" or slug.startswith("index."):
            continue
        base = slug.split(".")[0]
        if args.slug and base != args.slug and slug != args.slug:
            continue
        text = md.read_text()
        ids = objective_ids(frontmatter(text), base)
        summits = [(P[i]["lat"], P[i]["lon"]) for i in ids
                   if i in P and P[i].get("lat") is not None]
        coords = printed_coords(text)
        if not summits or not coords:   # nothing to verify against / nothing printed
            continue
        checked += 1
        bad = [(kind, la, lo, min(hav_mi(la, lo, sa, so) for sa, so in summits))
               for kind, la, lo in coords]
        bad = [b for b in bad if b[3] > args.tol_mi]
        if bad:
            fails += 1
            for kind, la, lo, near in bad:
                print(f"FAIL  {slug:30s} {kind}: {la:.5f}, {lo:.5f} is {near:.1f} mi "
                      f"from the nearest objective summit")
        else:
            print(f"ok    {slug:30s} {len(coords)} coord(s) within {args.tol_mi:.0f} mi")

    print(f"\n{checked} report(s) checked — {fails} with an off-peak coordinate.")
    if args.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
