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

logging.basicConfig(level=logging.WARNING)
logging.getLogger("caltopo_python").setLevel(logging.WARNING)
from lib import DOCS_DIR as DOCS, GPX_DIR as GPX, caltopo_session  # noqa: E402


def referenced_ids() -> set[str]:
    """Map ids any report points at: report frontmatter caltopo_id / regional_map_id,
    AND gpx/<slug>/peaks.yml `caltopo_map_id` (the map sync_kyle_recordings.py manages
    — it lives in peaks.yml, so it must count as referenced or the audit would flag it)."""
    ids = set()
    pat = re.compile(r"(?:caltopo_id|regional_map_id):\s*([A-Z0-9]+)")
    for md in DOCS.rglob("*.md"):
        for m in pat.finditer(md.read_text(errors="ignore")):
            ids.add(m.group(1))
    ypat = re.compile(r"^caltopo_map_id:\s*([A-Z0-9]+)", re.MULTILINE)
    for yml in GPX.glob("*/peaks.yml"):
        for m in ypat.finditer(yml.read_text(errors="ignore")):
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
    ap.add_argument("--force", action="store_true",
                    help="skip the referenced-by-a-report guard — ONLY for a deliberate "
                         "in-place replace (build_report deleting the map it's superseding)")
    args = ap.parse_args()

    protected = referenced_ids() | body_linked_ids()
    if args.list_refs:
        for i in sorted(protected):
            print(i)
        return
    if not args.map_ids:
        ap.error("provide at least one map id (or --list-refs)")

    # Guard: never delete a map a report still points at (unless --force, for a
    # deliberate replace where the frontmatter is about to be repointed).
    if not args.force:
        blocked = [m for m in args.map_ids if m in protected]
        if blocked:
            sys.exit(f"REFUSING: these ids are still referenced by a report: {', '.join(blocked)} "
                     f"(use --force only for a deliberate in-place replace)")

    s = caltopo_session(None)
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
