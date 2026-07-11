# Workflow: Share a sanitized report

**Trigger:** "share the <slug> report with <someone outside emily/shawn>."

**One command:**

    scripts/share_report.py <slug>          # creates share CalTopo map too
    scripts/share_report.py <slug> --no-map

**What it does:**

1. Renders the report to a self-contained static HTML page at a tokenized, unlisted
   path — `docs/share/<slug>-<token>.html` (+ a copied PNG). Non-md files get no nav,
   no search indexing, no site chrome; `noindex,nofollow` meta set.
2. Sanitizes: frontmatter, CLIMBERS block, "Written for <climber>", climbed-status
   lines, drive-from-home rows/fragments, links into the rest of the site, and
   third-party climber names in prose (neutralized to "the party"; Kyle stays).
3. Creates a **new CalTopo map with ONLY the recommended route lines + objective
   summit markers** ("Share: <title>", URL sharing) and points every map link at it —
   the research map (all swept tracks) is never exposed.
4. Appends to the committed ledger `docs/share/shares.json`.

**Publish:** commit + push (the page deploys with the site).
**Revoke:** delete the html+png, remove the ledger row, and
`scripts/delete_caltopo_map.py <share map id> --yes`.

**Honesty about access control:** GitHub Pages has no auth. A share link is
*unlisted* (unguessable token) — the same protection level as the rest of the site,
not a login wall. Don't share anything that must stay truly private.

**Note:** `audit_caltopo_maps.py` recognizes "Share: …" maps via the ledger — they are
intentional, not orphans. (If it ever flags one, check the ledger before pruning.)
