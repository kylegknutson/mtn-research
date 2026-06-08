#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
ingest_gpx.py — file GPX tracks into gpx/<slug>/ from a saved blob or a folder.

Replaces the ad-hoc `python3 <<HEREDOC` + `cp` glue used to land GPX after the
in-chat Playwright sweep. The browser's `browser_evaluate` (with a `filename`)
saves a JSON object of fetched tracks; this script files each one with a
source-suffixed name into gpx/<slug>/. One allowlisted call.

Accepted JSON shapes (auto-detected):
  {"whileyh_loj8023": "<gpx string>", ...}
  {"whileyh_loj8023": {"gpx": "<gpx string>", ...}, ...}
  {"<group>": {"<name>": "<gpx>" | {"gpx": "..."}}}   # one level of nesting

Usage:
    # from a saved JSON blob (the browser_evaluate filename output)
    scripts/ingest_gpx.py --slug pearl_oyster --json pearl_oyster_gpx.json

    # from a folder of loose .gpx files
    scripts/ingest_gpx.py --slug pearl_oyster --src-dir ~/Downloads/po_tracks

    # prefix every filed track (defaults to the slug)
    scripts/ingest_gpx.py --slug pearl_oyster --json blob.json --prefix pearl_oyster

By default skips entries that aren't valid GPX (no <trkpt> and no <wpt>).
"""
from __future__ import annotations
import argparse, json, re, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def is_gpx(s: str) -> bool:
    return isinstance(s, str) and ("<trkpt" in s or "<wpt" in s or "<rtept" in s)


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")


def collect(obj, prefix=""):
    """Yield (name, gpx_string) from a possibly-nested dict."""
    if isinstance(obj, str):
        if is_gpx(obj):
            yield (prefix or "track", obj)
        return
    if isinstance(obj, dict):
        # dict with a direct gpx payload
        if "gpx" in obj and is_gpx(obj["gpx"]):
            yield (prefix or "track", obj["gpx"])
            return
        for k, v in obj.items():
            name = f"{prefix}_{k}" if prefix else k
            yield from collect(v, name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--json", help="saved JSON blob of {name: gpx|{gpx:...}}")
    ap.add_argument("--src-dir", help="folder of loose .gpx files to import")
    ap.add_argument("--prefix", help="filename prefix (default: slug)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.json and not args.src_dir:
        sys.exit("need --json or --src-dir")

    prefix = args.prefix or args.slug
    gdir = ROOT / "gpx" / args.slug
    gdir.mkdir(parents=True, exist_ok=True)

    written = 0
    if args.json:
        data = json.loads(Path(args.json).read_text())
        # unwrap a top-level {"result": ...} or {"data": ...} wrapper
        if isinstance(data, dict) and set(data) & {"result", "data"} and len(data) <= 2:
            data = data.get("data") or data.get("result") or data
        for name, gpx in collect(data):
            fn = gdir / f"{safe(prefix)}_{safe(name)}.gpx"
            print(f"  {'(dry) ' if args.dry_run else ''}{fn.name}  ({len(gpx)} bytes)")
            if not args.dry_run:
                fn.write_text(gpx)
            written += 1

    if args.src_dir:
        for f in sorted(Path(args.src_dir).expanduser().glob("*.gpx")):
            txt = f.read_text(errors="ignore")
            if not is_gpx(txt):
                continue
            fn = gdir / f"{safe(prefix)}_{safe(f.stem)}.gpx"
            print(f"  {'(dry) ' if args.dry_run else ''}{fn.name}  ({len(txt)} bytes)")
            if not args.dry_run:
                shutil.copyfile(f, fn)
            written += 1

    print(f"\n{'would file' if args.dry_run else 'filed'} {written} track(s) into gpx/{args.slug}/")


if __name__ == "__main__":
    main()
