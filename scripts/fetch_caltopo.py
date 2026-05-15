#!/usr/bin/env python3
"""
Fetch CalTopo account data using caltopo_python.

Usage:
    # List all maps in your CalTopo account:
    python fetch_caltopo.py --list

    # Dump a specific map's full contents as JSON to ../caltopo/<map_id>.json:
    python fetch_caltopo.py --map <MAP_ID>

    # Dump every map you own:
    python fetch_caltopo.py --all

Credentials live in ./cts.ini (gitignored). See cts.ini.template.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Quiet caltopo_python's verbose default logging. Run with --verbose to restore.
logging.basicConfig(level=logging.WARNING)
logging.getLogger("caltopo_python").setLevel(logging.WARNING)

from caltopo_python import CaltopoSession  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CALTOPO_OUT = PROJECT_DIR / "caltopo"
CONFIG_PATH = SCRIPT_DIR / "cts.ini"
DEFAULT_ACCOUNT = "kyleg.knutson@gmail.com"


def make_session(map_id: str | None = None) -> CaltopoSession:
    """Create a CaltopoSession. map_id can be None for a "mapless" session
    (used when listing maps or browsing accounts/folders)."""
    if not CONFIG_PATH.exists():
        sys.exit(
            f"ERROR: {CONFIG_PATH} not found.\n"
            f"Copy cts.ini.template to cts.ini and fill in your credentials."
        )
    return CaltopoSession(
        domainAndPort="caltopo.com",
        mapID=map_id,  # None == mapless session, allowed
        configpath=str(CONFIG_PATH),
        account=DEFAULT_ACCOUNT,
    )


def list_maps() -> None:
    session = make_session()
    # includeBookmarks=False — Mobile-tier accounts may not have a 'rels' key
    # in accountData, which causes the default getMapList() to KeyError.
    print("=== Personal maps ===")
    try:
        maps = session.getMapList(includeBookmarks=False)
    except Exception as e:
        print(f"getMapList failed: {type(e).__name__}: {e}")
        maps = None

    if maps:
        for m in maps:
            # Each entry is a dict with id, title, updated, type, folderName, etc.
            print(json.dumps(m, indent=2, default=str))
    else:
        print("(none returned via getMapList — falling back to raw accountData parse)")
        # Direct parse of self.accountData so we still see something useful.
        ad = getattr(session, "accountData", None) or {}
        feats = ad.get("features", []) if isinstance(ad, dict) else []
        coll_maps = [
            f for f in feats
            if isinstance(f, dict)
            and f.get("properties", {}).get("class") == "CollaborativeMap"
        ]
        print(f"\nFound {len(coll_maps)} CollaborativeMap features in accountData.")
        for f in coll_maps:
            props = f.get("properties", {}) or {}
            print(f"  id={f.get('id')!r:10}  title={props.get('title')!r}  "
                  f"updated={props.get('updated')!r}  account={props.get('accountId')!r}")

    print("\n=== Accounts and folders (raw) ===")
    try:
        print(json.dumps(session.getAccountsAndFolders(), indent=2, default=str))
    except Exception as e:
        print(f"getAccountsAndFolders failed: {type(e).__name__}: {e}")


def dump_map(map_id: str) -> Path:
    CALTOPO_OUT.mkdir(parents=True, exist_ok=True)
    session = make_session(map_id)
    # The session caches the full map structure on init; expose it.
    data = getattr(session, "mapData", None)
    if data is None:
        # Fallback: try a known-public method if mapData attribute name differs in this version.
        data = {
            "note": "mapData attribute not found on session; inspect the session object.",
            "session_attrs": [a for a in dir(session) if not a.startswith("_")],
        }
    out = CALTOPO_OUT / f"{map_id}.json"
    out.write_text(json.dumps(data, indent=2, default=str))
    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")
    return out


def dump_all_maps() -> None:
    session = make_session()
    maps = session.getMapList(includeBookmarks=False) or []
    print(f"Found {len(maps)} map(s). Dumping each...")
    for m in maps:
        mid = m.get("id") or m.get("mapId") or m.get("MapID")
        title = m.get("title", "?")
        if not mid:
            print(f"  skip (no id field): {m}")
            continue
        out = CALTOPO_OUT / f"{mid}.json"
        if out.exists():
            print(f"  skip {mid} ({title}) — already dumped")
            continue
        try:
            print(f"  dumping {mid} ({title})...")
            dump_map(mid)
        except Exception as e:
            print(f"  ERROR dumping {mid} ({title}): {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch CalTopo account data.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List all maps")
    group.add_argument("--map", metavar="MAP_ID", help="Dump one map by ID")
    group.add_argument("--all", action="store_true", help="Dump every map")
    parser.add_argument("--verbose", action="store_true", help="Show full caltopo_python logs")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("caltopo_python").setLevel(logging.INFO)

    if args.list:
        list_maps()
    elif args.map:
        dump_map(args.map)
    elif args.all:
        dump_all_maps()


if __name__ == "__main__":
    main()
