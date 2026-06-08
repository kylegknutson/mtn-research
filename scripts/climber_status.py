#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML", "requests"]
# ///
"""
climber_status.py — inject an "Other climbers" line into every report showing
which OTHER configured climbers have (or haven't) climbed the report's peak(s).

Each report is owned by a climber (unsuffixed = kyle; <slug>.<climber>.md = that
friend). For every other climber in climbers/*.yml, this computes their climbed
status for the report's peaks (from peak_db for Kyle, from the 14ers checklist
for friends — via climber.climbed_ids) and writes it between sentinels:

    <!-- CLIMBERS_START -->
    **Other climbers:** Emily — not yet · Shawn — climbed 2 of 3 (PT 13,108, PT 13,110)
    <!-- CLIMBERS_END -->

Re-runnable (refreshes the line); run after adding a report or a new climber.
Peak IDs come from gpx/<slug>/peaks.yml objective_ids, else the report's
"Peak DB id" Quick-Stats row(s).

    scripts/climber_status.py
    scripts/climber_status.py --check     # exit 1 if any report's line is stale
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
PEAKS = ROOT / "docs" / "peaks"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")

# peak_db (Kyle's local Supabase client) and climber helpers depend on the local
# peak_db checkout, which is NOT present in CI. Import lazily/optionally so the
# freshness check can degrade gracefully there instead of crashing.
try:
    from peak_db_client import peaks  # noqa: E402
    from climber import climbed_ids   # noqa: E402
    DATA_AVAILABLE = True
except ModuleNotFoundError:
    DATA_AVAILABLE = False
    def peaks(): return []
    def climbed_ids(_): return set()

START, END = "<!-- CLIMBERS_START -->", "<!-- CLIMBERS_END -->"


def all_climbers():
    out = {}
    for f in sorted((ROOT / "climbers").glob("*.yml")):
        d = yaml.safe_load(f.read_text()) or {}
        out[f.stem] = d.get("name", f.stem)
    return out


def owner_of(path: Path) -> str:
    # <slug>.md → kyle; <slug>.<climber>.md → climber
    parts = path.name[:-3].split(".")
    return parts[1] if len(parts) > 1 else "kyle"


def base_slug(path: Path) -> str:
    return path.name[:-3].split(".")[0]


def peak_ids_for(path: Path) -> list[int]:
    yml = ROOT / "gpx" / base_slug(path) / "peaks.yml"
    if yml.exists():
        cfg = yaml.safe_load(yml.read_text()) or {}
        if cfg.get("objective_ids"):
            return list(cfg["objective_ids"])
    # fallback: parse "Peak DB id" / "peak_db id" table row(s)
    ids = []
    for m in re.finditer(r"peak[\s_]*db id\s*\|([^\n]+)", path.read_text(), re.I):
        ids += [int(x) for x in re.findall(r"-?\d+", m.group(1))]
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not DATA_AVAILABLE:
        # CI / any machine without the local peak_db checkout cannot recompute
        # climbed status. Don't fail the build — this check is enforced locally
        # before commit, where peak_db + the 14ers session are available.
        if args.check:
            print("peak_db unavailable here — skipping climber-status freshness check")
            sys.exit(0)
        sys.exit("peak_db unavailable — run climber_status.py on a machine with the peak_db checkout")

    names = all_climbers()
    by_id = {p["id"]: p for p in peaks()}
    climbed = {c: climbed_ids(c) for c in names}

    stale = []
    for path in sorted(PEAKS.glob("*.md")):
        if path.name.endswith(".skeleton.md"):
            continue
        owner = owner_of(path)
        ids = peak_ids_for(path)
        if not ids:
            continue
        others = [c for c in names if c != owner]
        parts = []
        for c in others:
            done = [i for i in ids if i in climbed[c]]
            if not done:
                parts.append(f"{names[c]} — not yet")
            elif len(done) == len(ids):
                parts.append(f"{names[c]} — ✓ all" if len(ids) > 1 else f"{names[c]} — ✓ climbed")
            else:
                dn = ", ".join((by_id.get(i, {}).get("display_name", str(i)) or str(i)).strip('"') for i in done)
                parts.append(f"{names[c]} — {len(done)} of {len(ids)} ({dn})")
        line = "**Other climbers:** " + " · ".join(parts) if parts else ""
        block = f"{START}\n{line}\n{END}"

        text = path.read_text()
        if START in text and END in text:
            new = re.sub(re.escape(START) + r".*?" + re.escape(END), block, text, flags=re.S)
        else:
            # insert just before the first "## Quick stats", else after first "---"
            if "## Quick stats" in text:
                new = text.replace("## Quick stats", block + "\n\n## Quick stats", 1)
            else:
                new = re.sub(r"\n---\n", "\n---\n\n" + block + "\n", text, count=1)
        if new != text:
            if args.check:
                stale.append(path.name)
            else:
                path.write_text(new)
                print(f"  {path.name}: {line or '(no other climbers)'}")

    if args.check:
        if stale:
            print("stale climber-status in: " + ", ".join(stale)); sys.exit(1)
        print("climber-status current ✓")
    else:
        print(f"\nclimbers: {', '.join(names.values())}")


if __name__ == "__main__":
    main()
