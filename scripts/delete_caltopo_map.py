#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python"]
# ///
"""
delete_caltopo_map.py — delete an ENTIRE CalTopo map (CollaborativeMap) by id.

Complements delete_caltopo_feature.py (which deletes features WITHIN a map).
Use to remove orphaned/duplicate "Research: …" maps superseded by a rebuild.
Find ids + titles with: scripts/fetch_caltopo.py --list

This is DESTRUCTIVE and irreversible. It requires --yes, and it refuses to delete
any map id still referenced (caltopo_id/regional_map_id) by a report under docs/.

Usage:
    scripts/delete_caltopo_map.py --list-refs            # show ids referenced by reports
    scripts/delete_caltopo_map.py 30G1DS1 --dry-run
    scripts/delete_caltopo_map.py 30G1DS1 1R09CLT --yes

Credentials live in ./cts.ini (gitignored), same as fetch_caltopo.py.
"""
from __future__ import annotations
import argparse, logging, re, sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logging.getLogger("caltopo_python").setLevel(logging.WARNING)
from caltopo_python import CaltopoSession  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "cts.ini"
DEFAULT_ACCOUNT = "kyleg.knutson@gmail.com"
DOCS = PROJECT_DIR / "docs"


def referenced_ids() -> set[str]:
    """Map ids any report points at via caltopo_id / regional_map_id frontmatter."""
    ids = set()
    pat = re.compile(r"(?:caltopo_id|regional_map_id):\s*([A-Z0-9]+)")
    for md in DOCS.rglob("*.md"):
        for m in pat.finditer(md.read_text(errors="ignore")):
            ids.add(m.group(1))
    return ids


def body_linked_ids() -> set[str]:
    """Map ids linked in report BODY text (caltopo.com/m/<id>) — also protected."""
    ids = set()
    pat = re.compile(r"caltopo\.com/m/([A-Z0-9]+)")
    for md in DOCS.rglob("*.md"):
        for m in pat.finditer(md.read_text(errors="ignore")):
            ids.add(m.group(1))
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("map_ids", nargs="*", help="CalTopo map id(s) to delete")
    ap.add_argument("--yes", action="store_true", help="actually delete (required)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be deleted")
    ap.add_argument("--list-refs", action="store_true", help="print ids referenced by reports and exit")
    args = ap.parse_args()

    protected = referenced_ids() | body_linked_ids()
    if args.list_refs:
        for i in sorted(protected):
            print(i)
        return
    if not args.map_ids:
        ap.error("provide at least one map id (or --list-refs)")

    # Guard: never delete a map a report still points at.
    blocked = [m for m in args.map_ids if m in protected]
    if blocked:
        sys.exit(f"REFUSING: these ids are still referenced by a report: {', '.join(blocked)}")

    s = CaltopoSession(domainAndPort="caltopo.com", mapID=None,
                       configpath=str(CONFIG_PATH), account=DEFAULT_ACCOUNT)
    acct = getattr(s, "accountIdInternet", None) or getattr(s, "accountId", None)
    if not acct:
        sys.exit("ERROR: could not resolve CalTopo account id from session")

    for mid in args.map_ids:
        if args.dry_run or not args.yes:
            print(f"[dry-run] would DELETE map {mid} "
                  f"(acct {acct})  — pass --yes to delete")
            continue
        r = s._sendRequest("delete", f"/api/v1/acct/{acct}/CollaborativeMap",
                           None, id=mid, returnJson="ALL", blocking=True)
        ok = r is not False and r is not None
        print(f"{'deleted' if ok else 'FAILED '} {mid} -> {r}")


if __name__ == "__main__":
    main()
