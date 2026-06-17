#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
split_sweep_json.py — split a sweep JSON blob into individual GPX files.

The MCP-browser GPX sweep fetches several tracks at once and saves them as a
single JSON object {name: "<gpx xml>"} (browser_evaluate's filename output).
This unpacks that into gpx/<slug>/<name>.gpx, skipping any "ERR ..." values.

Usage:
    scripts/split_sweep_json.py adams_tracks.json mount_adams_trio
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    blob = Path(sys.argv[1])
    slug = sys.argv[2]
    out_dir = ROOT / "gpx" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = blob.read_text()
    # The MCP browser_evaluate result may be persisted with a wrapper when it's
    # too large to return inline:  "### Result\n<value>\n### Ran code ...".
    # Pull out the value between the markers if present.
    if raw.lstrip().startswith("### Result"):
        body = raw.split("### Result", 1)[1]
        for end in ("\n### Ran", "\n### Open tabs", "\n### Page"):
            if end in body:
                body = body.split(end, 1)[0]
        raw = body.strip()
    # The value is often a JSON-encoded *string* of the object (double-encoded):
    # parse repeatedly until we land on a dict.
    data = raw
    for _ in range(3):
        if isinstance(data, dict):
            break
        data = json.loads(data)
    n = 0
    for name, gpx in data.items():
        if not isinstance(gpx, str) or gpx.startswith("ERR") or "<gpx" not in gpx:
            print(f"  skip {name} (not GPX)")
            continue
        fn = name if name.endswith(".gpx") else f"{name}.gpx"
        (out_dir / fn).write_text(gpx)
        kb = len(gpx) // 1024
        print(f"  wrote {fn} ({kb} KB)")
        n += 1
    print(f"{n} GPX file(s) -> {out_dir}")


if __name__ == "__main__":
    main()
