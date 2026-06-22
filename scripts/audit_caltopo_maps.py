#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python"]
# ///
"""
audit_caltopo_maps.py — find (and optionally prune) ORPHANED "Research:" CalTopo
maps so a rebuilt report never leaves a stale duplicate behind.

Every research rebuild (build_report without --caltopo-id) mints a NEW map and
the report's frontmatter is repointed to it — orphaning the OLD map on the
account. Opening that stale orphan by mistake is exactly the "wrong version"
failure. This audit closes the loop: a "Research: …" map whose id is referenced
by NO report (frontmatter caltopo_id/regional_map_id OR a caltopo.com/m/<id>
body link) is an orphan and should be deleted.

Only "Research:" maps are considered — personal maps ("GPS Tracks — …", named
hikes) are never flagged.

Exit code: 0 if no orphans (or after a successful --prune), 1 if orphans remain.
So it works as a gate. Requires ./cts.ini (gitignored) — skips cleanly (exit 0)
when creds are absent, e.g. in CI, like the other CalTopo-touching steps.

Usage:
    scripts/audit_caltopo_maps.py            # report orphans (exit 1 if any)
    scripts/audit_caltopo_maps.py --prune    # delete them, then report
"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logging.getLogger("caltopo_python").setLevel(logging.WARNING)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from delete_caltopo_map import referenced_ids, body_linked_ids  # noqa: E402

CONFIG_PATH = SCRIPT_DIR / "cts.ini"
DEFAULT_ACCOUNT = "kyleg.knutson@gmail.com"
RESEARCH_PREFIX = "Research:"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prune", action="store_true", help="delete the orphaned research maps")
    args = ap.parse_args()

    if not CONFIG_PATH.exists():
        print(f"audit_caltopo_maps: {CONFIG_PATH.name} absent — skipping CalTopo audit (ok).")
        return  # exit 0: no creds (CI) → can't audit, don't fail the build

    from caltopo_python import CaltopoSession
    s = CaltopoSession(domainAndPort="caltopo.com", mapID=None,
                       configpath=str(CONFIG_PATH), account=DEFAULT_ACCOUNT)
    try:
        maps = s.getMapList(includeBookmarks=False) or []
    except Exception as e:
        print(f"audit_caltopo_maps: could not list maps ({type(e).__name__}: {e}) — skipping.")
        return

    protected = referenced_ids() | body_linked_ids()
    research = [(m.get("id"), m.get("title", "")) for m in maps
                if str(m.get("title", "")).startswith(RESEARCH_PREFIX)]
    orphans = [(mid, title) for mid, title in research if mid and mid not in protected]

    print(f"CalTopo: {len(maps)} maps · {len(research)} research · "
          f"{len(orphans)} orphaned (not referenced by any report)")
    if not orphans:
        print("✓ no duplicate/orphaned research maps")
        return

    for mid, title in orphans:
        print(f"  ORPHAN  {mid}  {title}")

    if not args.prune:
        print("\nRun with --prune to delete these, or `scripts/delete_caltopo_map.py <id> --yes`.")
        sys.exit(1)

    acct = getattr(s, "accountIdInternet", None) or getattr(s, "accountId", None)
    if not acct:
        sys.exit("ERROR: could not resolve CalTopo account id")
    failed = 0
    for mid, title in orphans:
        r = s._sendRequest("delete", f"/api/v1/acct/{acct}/CollaborativeMap",
                           None, id=mid, returnJson="ALL", blocking=True)
        ok = r is not False and r is not None
        print(f"  {'deleted' if ok else 'FAILED '} {mid}  {title}")
        failed += 0 if ok else 1
    if failed:
        sys.exit(f"{failed} deletion(s) failed")
    print("✓ pruned all orphaned research maps")


if __name__ == "__main__":
    main()
