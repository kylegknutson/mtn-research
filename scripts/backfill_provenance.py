#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
backfill_provenance.py — fill th_source / class_source / status_source on reports
that already have 3-source coverage, deriving each from data that's actually
present (never faking — the no-skip rule applies to me too).

  th_source     ← peaks.yml trailhead landmark, but ONLY claimed as
                  "recorded GPS-track starts" when the report's swept tracks really
                  begin within --th-tol-mi of it (verified here). If no trailhead or
                  no track confirms it, the field is LEFT BLANK and flagged — not faked.
  class_source  ← the route-beta sources the report actually cites (scanned from the
                  body: 14ers TR / Roach / climb13ers / listsofjohn / peakbagger).
  status_source ← peak_db ascents (Kyle) or scrape_14ers_checklist <climber> (climber
                  reports) — the real mechanism.

Inserts only the MISSING fields, just before the frontmatter's closing '---'
(text insert, so existing formatting is untouched).

    scripts/backfill_provenance.py            # dry-run, list what it would write
    scripts/backfill_provenance.py --apply
    scripts/backfill_provenance.py --slug cuba_gulch_trio --apply
"""
from __future__ import annotations
import argparse, math, re, xml.etree.ElementTree as ET
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
NS = "{http://www.topografix.com/GPX/1/1}"
FIELDS = ("th_source", "class_source", "status_source")
NON_TRACK = ("peaks_only", "landmark", "trailhead", "recommended", "_drive",
             "drive_in", "waypoints", "summit", "actual", "kyle")


def hav_mi(a, b, c, d):
    R = 3958.8
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(x))


def fm_block(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return m, (yaml.safe_load(m.group(1)) or {}) if m else (None, {})


def trailhead(slug):
    p = GPX / slug / "peaks.yml"
    if not p.exists():
        return None
    cfg = yaml.safe_load(p.read_text()) or {}
    for lm in (cfg.get("landmarks") or []):
        if lm.get("kind") == "trailhead":
            return lm.get("name"), lm.get("lat"), lm.get("lon")
    return None


def track_start_confirms(slug, lat, lon, tol_mi):
    best = 99.0
    for f in (GPX / slug).glob("*.gpx"):
        n = f.name.lower()
        if any(x in n for x in NON_TRACK):
            continue
        try:
            root = ET.parse(f).getroot()
        except Exception:
            continue
        pts = root.iter(NS + "trkpt")
        first = next(pts, None)
        if first is not None:
            best = min(best, hav_mi(lat, lon, float(first.get("lat")), float(first.get("lon"))))
    return best <= tol_mi, best


def beta_cited(text):
    src = []
    if re.search(r"14ers\.com|tripreport\.php|\b14ers TR\b", text, re.I): src.append("14ers.com route beta / trip reports")
    if re.search(r"\broach\b", text, re.I): src.append("Roach guidebook")
    if re.search(r"climb13ers", text, re.I): src.append("climb13ers")
    if re.search(r"listsofjohn|lists of john|\bLoJ\b", text, re.I): src.append("listsofjohn")
    if re.search(r"peakbagger", text, re.I): src.append("peakbagger")
    return src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--th-tol-mi", type=float, default=1.5)
    args = ap.parse_args()

    # Only touch reports that ALREADY pass 3-source coverage, so each filled report
    # is immediately push-able (a coverage-failing report would be blocked by the
    # pre-push hook anyway, and its provenance is better filled during its sweep).
    import subprocess
    cov = subprocess.run([str(ROOT / "scripts" / "check_source_coverage.py")],
                         capture_output=True, text=True)
    failing = {ln.split()[1].split(".")[0] for ln in cov.stdout.splitlines()
               if ln.startswith("FAIL")}

    reports = []
    for sub in ("peaks", "trips"):
        for p in sorted((ROOT / "docs" / sub).glob("*.md")):
            if p.stem == "index" or p.stem.startswith("index."):
                continue
            if args.slug and p.stem != args.slug and p.stem.split(".")[0] != args.slug:
                continue
            if not args.slug and p.stem.split(".")[0] in failing:
                continue   # coverage not done yet — fill provenance during its sweep
            reports.append(p)

    wrote = flagged = 0
    for p in reports:
        text = p.read_text()
        m, meta = fm_block(text)
        if not m:
            continue
        missing = [f for f in FIELDS if not str(meta.get(f) or "").strip()]
        if not missing:
            continue
        base = p.stem.split(".")[0]
        climber = p.stem.split(".")[1] if p.stem.count(".") else None
        lines, notes = [], []

        if "th_source" in missing:
            th = trailhead(base)
            if th and th[1] is not None:
                ok, d = track_start_confirms(base, th[1], th[2], args.th_tol_mi)
                if ok:
                    lines.append(f'th_source: "recorded GPS-track starts at {th[0]} '
                                 f'({th[1]},{th[2]}) — swept tracks begin {d:.1f} mi away"')
                else:
                    notes.append(f"th_source NOT auto-filled (no track starts within "
                                 f"{args.th_tol_mi} mi; closest {d:.1f}) — verify manually")
            else:
                notes.append("th_source NOT auto-filled (no trailhead in peaks.yml) — verify manually")
        if "class_source" in missing:
            cited = beta_cited(text)
            if cited:
                lines.append(f'class_source: "route beta — {", ".join(cited)} (see route options)"')
            else:
                notes.append("class_source NOT auto-filled (no beta sources cited in body) — add manually")
        if "status_source" in missing:
            lines.append(f'status_source: "{f"scrape_14ers_checklist {climber}" if climber else "peak_db ascents"}"')

        print(f"{'WRITE' if (lines and args.apply) else 'would'}  {p.name}: +{len(lines)} field(s)"
              + (f"  ⚠ {'; '.join(notes)}" if notes else ""))
        if notes:
            flagged += 1
        if lines and args.apply:
            new = text[:m.end(1)] + "\n" + "\n".join(lines) + text[m.end(1):]
            p.write_text(new)
            wrote += 1

    print(f"\n{wrote} report(s) updated, {flagged} with a field left for manual fill.")


if __name__ == "__main__":
    main()
