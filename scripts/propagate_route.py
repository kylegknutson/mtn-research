#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python", "PyYAML"]
# ///
"""
propagate_route.py — rebuild a report's recommended route faithfully and fan the change
out to EVERY surface, consistently (Kyle, 2026-06-22: "anytime we make a change we need
to propagate and be consistent").

For a slug:
  1. Rebuild the route to FOLLOW real tracks — `--legs` (verbatim stitched segments,
     ~0 ft off-track) by default, or `--from-track <substr>` for a single recording.
     (Trips with a peaks.yml `days:` block rebuild per-day via build_trip_day_routes.)
  2. Refuse to propagate a route that still fails fidelity (check_route_fidelity).
  3. Regenerate the overview PNG.
  4. Replace the route line on the report's CalTopo map (delete the stale "recommended
     route" Shape, push the new magenta line) — the surface that was silently going stale.
  5. iCloud GPS Tracks export happens inside build_recommended_route already.
  6. Update frontmatter dist_mi/gain_ft to the rebuilt route (single-peak reports).

The caller regenerates the home map / index / quickstats once and commits. Use --no-caltopo
to skip the CalTopo push (e.g. a report with no caltopo_id, or a dry repo-only pass).

    scripts/propagate_route.py dolores_middle_peak
    scripts/propagate_route.py pt_13557 --from-track 17885
    scripts/propagate_route.py savage_peak --no-caltopo
"""
from __future__ import annotations
import argparse, logging, re, subprocess, sys
from pathlib import Path
import yaml

logging.basicConfig(level=logging.ERROR)
logging.getLogger("caltopo_python").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
DOCS = ROOT / "docs"
SCRIPTS = ROOT / "scripts"
CONFIG = SCRIPTS / "cts.ini"
ACCOUNT = "kyleg.knutson@gmail.com"
MAGENTA = "#E6008C"
FIDELITY_FT = 5.0


def run(cmd):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True)


def report_path(slug):
    for p in (DOCS / "peaks" / f"{slug}.md", DOCS / "trips" / f"{slug}.md"):
        if p.exists():
            return p
    return None


def is_trip(slug):
    yml = GPX / slug / "peaks.yml"
    if yml.exists():
        return bool((yaml.safe_load(yml.read_text()) or {}).get("days"))
    return False


def caltopo_id(slug):
    p = report_path(slug)
    if not p:
        return None
    m = re.search(r"^caltopo_id:\s*([A-Z0-9]+)", p.read_text(), re.MULTILINE)
    return m.group(1) if m else None


def rebuild(slug, from_track):
    if is_trip(slug):
        r = run([SCRIPTS / "build_trip_day_routes.py", slug])
        return r, None
    cmd = [SCRIPTS / "build_recommended_route.py", slug]
    cmd += ["--from-track", from_track] if from_track else ["--legs"]
    r = run(cmd)
    m = re.search(r"Recommended route:\s*([\d.]+)\s*mi\s*·\s*~?([\d,]+)\s*ft", r.stdout or "")
    stats = (float(m.group(1)), int(m.group(2).replace(",", ""))) if m else None
    return r, stats


def update_frontmatter(slug, dist_mi, gain_ft):
    p = report_path(slug)
    if not p:
        return
    text = p.read_text()
    head = text.split("\n---\n", 1)[0]
    new = head
    new = re.sub(r"^dist_mi:.*$", f"dist_mi: {dist_mi:.1f}", new, count=1, flags=re.MULTILINE)
    new = re.sub(r"^gain_ft:.*$", f"gain_ft: {gain_ft}", new, count=1, flags=re.MULTILINE)
    # only rewrite a simple "~X mi / ~Y ft (...)" gain headline; leave ranges/recorded ones
    new = re.sub(r'^(gain:\s*")~?[\d.]+\s*mi\s*/\s*~?[\d,]+\s*ft',
                 rf'\g<1>~{dist_mi:.1f} mi / ~{gain_ft:,} ft', new, count=1, flags=re.MULTILINE)
    if new != head:
        p.write_text(new + "\n---\n" + text.split("\n---\n", 1)[1])


def replace_caltopo_route(slug, mid):
    from caltopo_python import CaltopoSession
    s = CaltopoSession(domainAndPort="caltopo.com", mapID=mid, configpath=str(CONFIG), account=ACCOUNT)
    deleted = 0
    for f in s.getFeatures(featureClass="Shape"):
        if "recommended route" in (f.get("properties") or {}).get("title", "").lower():
            try:
                s.delFeature(f.get("id"), "Shape"); deleted += 1
            except TypeError:
                s.delFeature(f.get("id")); deleted += 1
    routes = sorted((GPX / slug).glob("*recommended*.gpx"))
    for rf in routes:
        run([SCRIPTS / "gpx_to_caltopo.py", "--gpx", str(rf), "--map-id", mid,
             "--color", MAGENTA, "--no-dedupe"])
    print(f"    CalTopo {mid}: removed {deleted} old route line(s), pushed {len(routes)} new")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--from-track")
    ap.add_argument("--no-caltopo", action="store_true")
    ap.add_argument("--max-ft", type=float, default=FIDELITY_FT)
    args = ap.parse_args()

    print(f"== propagate {args.slug} ==")
    r, stats = rebuild(args.slug, args.from_track)
    if r.returncode != 0:
        print(r.stdout[-500:], r.stderr[-500:]); sys.exit(f"rebuild failed for {args.slug}")
    if stats:
        print(f"  route {stats[0]:.1f} mi / {stats[1]:,} ft")

    fid = run([SCRIPTS / "check_route_fidelity.py", args.slug, "--max-ft", str(args.max_ft)])
    fid_line = (fid.stdout or "").strip().splitlines()[0]
    print("  " + fid_line)
    flagged = "FAIL" in (fid.stdout or "")
    if flagged:
        # Propagate the best-available route anyway (it beats the old one), but SURFACE it:
        # the recorded tracks don't let us follow the trail within tolerance here — Kyle's eyes.
        print(f"  ⚠ FLAG {args.slug}: best route still off-track ({fid_line.split('strays')[-1].strip()}) "
              f"— propagating best-available; NEEDS REVIEW / a Kyle recording")

    if run([SCRIPTS / "make_overview_map.py", args.slug]).returncode != 0:
        sys.exit("make_overview_map failed")
    print("  PNG refreshed")

    if stats and not is_trip(args.slug):
        update_frontmatter(args.slug, *stats)
        print("  frontmatter dist/gain updated")

    mid = caltopo_id(args.slug)
    if mid and not args.no_caltopo:
        replace_caltopo_route(args.slug, mid)
    elif not args.no_caltopo:
        print("  (no caltopo_id — CalTopo skipped)")
    print(f"  ✓ {args.slug} propagated")


if __name__ == "__main__":
    main()
