#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML"]
# ///
"""
sync_kyle_recordings.py — push Kyle's Garmin recordings onto the CalTopo research
maps + report PNGs.

The separate peak_checklist project auto-syncs Garmin climbs and drops each as a
peak-named GPX into gpx/<slug>/_kyle_existing/ here (filename
`<peak1>, <peak2> YYYY-MM-DD_actual.gpx`, the GPX's <trk><name> already rewritten).
This project owns getting those recordings onto the slug's CalTopo research map and
re-rendering its overview PNG. peak_checklist's phase12_pipeline.sh calls this as its
last step (and skips gracefully until it exists).

For each NEW `*_actual*.gpx` under gpx/<slug>/_kyle_existing/ (ledger-gated in the
gitignored .caltopo_sync_ledger.json):

  1. Resolve the slug's research map — DUPLICATE-SAFE:
       a. gpx/<slug>/peaks.yml `caltopo_map_id`            → append to it
       b. else the report's frontmatter `caltopo_id`       → append to it, AND backfill
          (docs/peaks/<slug>.md or docs/trips/<slug>.md)     caltopo_map_id into peaks.yml
       c. else                                             → create a new map over
          --gpx-dir gpx/<slug> (which includes _kyle_existing/), capture the id, write
          caltopo_map_id into peaks.yml.
     (b) is the key deviation from a naive "no id → create": baldy_lejos_trio and
     pt_13308_13166 already have research maps in their frontmatter — creating a new map
     would orphan a duplicate, exactly what audit_caltopo_maps.py guards against.
  2. Append each new recording (gpx_to_caltopo.py --map-id <id> --gpx <file>); _kyle_existing
     files render in Kyle-blue on the web map (gpx_to_caltopo forces it). Dedupe is ON, so a
     recording already on the map is skipped — safe.
  3. Regenerate the overview PNG (make_overview_map.py <slug>).
  4. Mark each file processed in the ledger.

After all slugs, if anything changed and not --dry-run: commit + push the tracked artifacts
(peaks.yml + docs/maps/*.png; the GPX themselves are gitignored — they ride iCloud).

Idempotent (ledger-gated clean no-op), soft-fails per slug (one bad CalTopo call doesn't
abort the rest), and accepts --dry-run.

Usage:
    scripts/sync_kyle_recordings.py
    scripts/sync_kyle_recordings.py --dry-run
    scripts/sync_kyle_recordings.py --slug dolores_middle_peak   # limit to one slug
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
GPX = ROOT / "gpx"
SCRIPTS = ROOT / "scripts"
DOCS = ROOT / "docs"
LEDGER = ROOT / ".caltopo_sync_ledger.json"
RECORDING_GLOB = "*_actual*.gpx"   # the auto-synced recordings (not map-export side files)


def load_ledger() -> dict:
    if LEDGER.exists():
        try:
            return json.loads(LEDGER.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def report_path(slug: str) -> Path | None:
    for p in (DOCS / "peaks" / f"{slug}.md", DOCS / "trips" / f"{slug}.md"):
        if p.exists():
            return p
    return None


def frontmatter_caltopo_id(slug: str) -> str | None:
    p = report_path(slug)
    if not p:
        return None
    m = re.search(r"^caltopo_id:\s*([A-Z0-9]+)", p.read_text(), re.MULTILINE)
    return m.group(1) if m else None


def peaks_yml_map_id(ycfg: dict) -> str | None:
    v = ycfg.get("caltopo_map_id")
    return str(v) if v else None


def write_peaks_yml_map_id(yml: Path, map_id: str):
    """Insert/replace `caltopo_map_id:` in peaks.yml, preserving hand formatting."""
    text = yml.read_text()
    if re.search(r"^caltopo_map_id:", text, re.MULTILINE):
        text = re.sub(r"^caltopo_map_id:.*$", f"caltopo_map_id: {map_id}   # https://caltopo.com/m/{map_id}",
                      text, count=1, flags=re.MULTILINE)
    else:
        # insert right after the objective_ids block (its line, or the last list item)
        lines = text.splitlines()
        out, inserted, in_objs = [], False, False
        for ln in lines:
            out.append(ln)
            if not inserted:
                if re.match(r"^objective_ids:\s*\[", ln):       # inline list
                    out.append(f"caltopo_map_id: {map_id}   # https://caltopo.com/m/{map_id}")
                    inserted = True
                elif re.match(r"^objective_ids:\s*$", ln):       # block list follows
                    in_objs = True
                elif in_objs and not re.match(r"^\s*-\s", ln):   # first non-item after block
                    out.insert(-1, f"caltopo_map_id: {map_id}   # https://caltopo.com/m/{map_id}")
                    inserted = True
        if not inserted:
            out.append(f"caltopo_map_id: {map_id}   # https://caltopo.com/m/{map_id}")
        text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
    yml.write_text(text)


def run(cmd) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True)


def report_title(slug: str) -> str:
    p = report_path(slug)
    if p:
        m = re.search(r"^#\s+(.+)$", p.read_text(), re.MULTILINE)
        if m:
            return m.group(1).strip()
    return slug.replace("_", " ").title()


def sync_slug(slug: str, new_files: list[Path], ledger: dict, dry_run: bool) -> bool:
    """Process one slug's new recordings. Returns True if anything changed."""
    yml = GPX / slug / "peaks.yml"
    if not yml.exists():
        print(f"  SKIP {slug}: no peaks.yml")
        return False
    ycfg = yaml.safe_load(yml.read_text()) or {}

    map_id = peaks_yml_map_id(ycfg)
    source = "peaks.yml caltopo_map_id"
    if not map_id:
        fid = frontmatter_caltopo_id(slug)
        if fid:
            map_id, source = fid, "report frontmatter caltopo_id (backfilling peaks.yml)"

    names = ", ".join(f.name for f in new_files)
    if map_id:
        print(f"  {slug}: {len(new_files)} new recording(s) [{names}] → append to {map_id} ({source})")
    else:
        print(f"  {slug}: {len(new_files)} new recording(s) [{names}] → CREATE new map (no existing research map)")
    if dry_run:
        return False

    if map_id:
        if source.startswith("report frontmatter"):
            write_peaks_yml_map_id(yml, map_id)   # backfill so we never create a duplicate later
        for f in new_files:
            r = run([SCRIPTS / "gpx_to_caltopo.py", "--map-id", map_id, "--gpx", str(f), "--sharing", "URL"])
            if r.returncode != 0:
                print(r.stdout[-600:] if r.stdout else "", r.stderr[-600:] if r.stderr else "", sep="\n")
                raise RuntimeError(f"gpx_to_caltopo append failed for {f.name}")
            print("   ", (r.stdout or "").strip().splitlines()[-1] if r.stdout else "(no output)")
    else:
        r = run([SCRIPTS / "gpx_to_caltopo.py", "--gpx-dir", str(GPX / slug),
                 "--new-map", f"Research: {report_title(slug)}", "--sharing", "URL"])
        if r.returncode != 0:
            print(r.stdout[-600:] if r.stdout else "", r.stderr[-600:] if r.stderr else "", sep="\n")
            raise RuntimeError("gpx_to_caltopo --new-map failed")
        m = re.search(r"caltopo\.com/m/(\w+)", r.stdout or "") or re.search(r"Created new map:\s*(\w+)", r.stdout or "")
        if not m:
            raise RuntimeError("could not capture new map id from gpx_to_caltopo output")
        map_id = m.group(1)
        write_peaks_yml_map_id(yml, map_id)
        print(f"    created map {map_id}; wrote caltopo_map_id to peaks.yml")
        # Summit markers: match build_report's research-map convention — the `peak`
        # mountain symbol in green #39FF14 for EVERY objective (the --gpx-dir upload
        # added them palette-colored; re-add green with --no-dedupe). Kyle's tracks
        # stay blue, so green summits read distinctly.
        pk = next((GPX / slug).glob("*peaks_only*.gpx"), None)
        if pk:
            run([SCRIPTS / "gpx_to_caltopo.py", "--gpx", str(pk), "--map-id", map_id,
                 "--marker-symbol", "peak", "--color", "#39FF14", "--no-dedupe"])

    r = run([SCRIPTS / "make_overview_map.py", slug])
    if r.returncode != 0:
        raise RuntimeError("make_overview_map failed")

    for f in new_files:
        ledger[f"{slug}/{f.name}"] = map_id
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, mutate nothing")
    ap.add_argument("--slug", help="limit to one slug")
    ap.add_argument("--no-push", action="store_true", help="commit but don't push")
    args = ap.parse_args()

    ledger = load_ledger()
    # discover new recordings, grouped by slug
    by_slug: dict[str, list[Path]] = {}
    for kdir in sorted(GPX.glob("*/_kyle_existing")):
        slug = kdir.parent.name
        if args.slug and slug != args.slug:
            continue
        for f in sorted(list(kdir.glob(RECORDING_GLOB)) + list(kdir.glob(RECORDING_GLOB.upper()))):
            if f"{slug}/{f.name}" not in ledger:
                by_slug.setdefault(slug, []).append(f)

    if not by_slug:
        print("sync_kyle_recordings: nothing new to sync (clean no-op).")
        return

    print(f"sync_kyle_recordings: {sum(len(v) for v in by_slug.values())} new recording(s) "
          f"across {len(by_slug)} slug(s)" + ("  [DRY-RUN]" if args.dry_run else ""))
    changed = False
    for slug, files in by_slug.items():
        try:
            if sync_slug(slug, files, ledger, args.dry_run):
                changed = True
        except Exception as e:
            print(f"  SOFT-FAIL {slug}: {e}  (continuing)")

    if args.dry_run:
        print("\n[DRY-RUN] no changes written.")
        return

    LEDGER.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    if not changed:
        print("\nNo CalTopo/PNG changes; ledger updated.")
        return

    # commit + push the tracked artifacts (peaks.yml + PNGs; GPX are gitignored)
    add = run(["git", "-C", str(ROOT), "add", "gpx", "docs/maps"])
    msg = ("sync_kyle_recordings: push Garmin recordings to CalTopo maps + PNGs\n\n"
           f"Synced {sum(len(v) for v in by_slug.values())} recording(s) across "
           f"{len(by_slug)} slug(s): {', '.join(by_slug)}.\n\n"
           "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>")
    c = run(["git", "-C", str(ROOT), "commit", "-m", msg])
    if c.returncode != 0:
        print((c.stdout or "") + (c.stderr or ""))
        print("  (nothing committed — maybe no tracked changes)")
        return
    print("  committed.")
    if not args.no_push:
        p = run(["git", "-C", str(ROOT), "push"])
        print("  pushed." if p.returncode == 0 else f"  PUSH FAILED:\n{(p.stdout or '')+(p.stderr or '')}")


if __name__ == "__main__":
    main()
