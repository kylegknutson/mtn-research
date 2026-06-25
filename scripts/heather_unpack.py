#!/usr/bin/env python3
"""Unpack a Playwright evaluate-result batch (JSON {filename: gpx}) into gpx/heather/.
The MCP wraps the result; we dig out the object whose values are GPX strings."""
import json, sys, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent / "gpx" / "heather"
ROOT.mkdir(parents=True, exist_ok=True)

def find_map(obj):
    """Return the first dict whose values look like GPX text."""
    if isinstance(obj, dict):
        if obj and all(isinstance(v, str) for v in obj.values()) and \
           any("<gpx" in v[:200] for v in obj.values()):
            return obj
        for v in obj.values():
            m = find_map(v)
            if m: return m
    elif isinstance(obj, list):
        for v in obj:
            m = find_map(v)
            if m: return m
    return None

def main():
    p = pathlib.Path(sys.argv[1])
    raw = p.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # MCP sometimes wraps as [{"type":"text","text":"<json>"}]
        m = re.search(r'"text"\s*:\s*"(.*)"\s*}', raw, re.S)
        data = json.loads(json.loads('"' + m.group(1) + '"')) if m else {}
    mp = find_map(data) or {}
    n = 0
    for fn, gpx in mp.items():
        fn = "".join(c for c in fn if c.isalnum() or c in "._-") or f"act_{n}.gpx"
        (ROOT / fn).write_text(gpx)
        n += 1
    total = len(list(ROOT.glob("*.gpx")))
    print(f"wrote {n} from {p.name}; gpx/heather now has {total} gpx files")

if __name__ == "__main__":
    main()
