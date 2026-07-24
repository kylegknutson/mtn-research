#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml"]
# ///
"""
apply_summit_overrides.py — write the track-located summit coords into peaks.yml.

Takes a summit_from_tracks.py sheet JSON and, for each row of the chosen tier (default
AUTO), sets gpx/<slug>/peaks.yml `summit_overrides[<peak_db id>] = {lat, lon, note}` so
build_peak_gpx.py places the marker there across rebuilds. Uses ruamel round-trip so the
hand-written comments in peaks.yml survive.

Only AUTO rows by default — the finder-confident ones. MANUAL rows (badly-misplaced
markers, technical peaks) are left for Kyle to hand-place. Idempotent: re-running updates
the same keys.

  scripts/apply_summit_overrides.py --sheet sheet.json                 # dry-run (AUTO)
  scripts/apply_summit_overrides.py --sheet sheet.json --apply
  scripts/apply_summit_overrides.py --sheet sheet.json --tier AUTO,MANUAL --apply
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"


def main():
    ap = argparse.ArgumentParser(description="Write track-located summit coords to peaks.yml")
    ap.add_argument("--sheet", required=True, help="summit_from_tracks.py JSON")
    ap.add_argument("--tier", default="AUTO", help="comma-separated verdicts to apply (default AUTO)")
    ap.add_argument("--apply", action="store_true", help="write (else dry-run)")
    args = ap.parse_args()

    tiers = {t.strip() for t in args.tier.split(",")}
    rows = [r for r in json.loads(Path(args.sheet).read_text())
            if r.get("verdict") in tiers and r.get("kind") == "override" and r.get("peak_db_id") is not None]
    by_slug = {}
    for r in rows:
        by_slug.setdefault(r["slug"], []).append(r)

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096                     # don't wrap our one-line flow maps
    n_written = 0
    for slug in sorted(by_slug):
        p = GPX / slug / "peaks.yml"
        if not p.exists():
            print(f"  SKIP {slug}: no peaks.yml"); continue
        data = yaml.load(p.read_text())
        ov = data.get("summit_overrides")
        if not isinstance(ov, CommentedMap):
            ov = CommentedMap()
            data["summit_overrides"] = ov
        for r in sorted(by_slug[slug], key=lambda r: -r["offset_ft"]):
            pid = int(r["peak_db_id"])
            lat, lon = r["convergence"]
            de = r.get("track_dele_ft")
            note = (f"track summit ({r['n_tracks']} trk); peak_db was ~{r['offset_ft']} ft off"
                    + (f", ~{de} ft low" if isinstance(de, int) and de > 0 else ""))
            entry = CommentedMap()
            entry["lat"] = lat
            entry["lon"] = lon
            entry["note"] = note
            entry.fa.set_flow_style()     # render as {lat: .., lon: .., note: ..}
            ov[pid] = entry
            n_written += 1
            print(f"  {'write' if args.apply else 'would'} {slug:24s} id {pid:>5} "
                  f"→ {lat},{lon}  ({r['name'][:26]})")
        if args.apply:
            with p.open("w") as fh:
                yaml.dump(data, fh)

    print(f"\n{n_written} override(s) across {len(by_slug)} slug(s) "
          f"[{'APPLIED' if args.apply else 'dry-run'}].")
    if args.apply:
        print("Next: rebuild peaks_only for these slugs (build_peak_gpx.py --slug <slug>).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
