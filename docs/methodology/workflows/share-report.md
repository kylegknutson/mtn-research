# Workflow: Share a sanitized report (Cloudflare Pages)

**Trigger:** "share the <slug> report with <someone outside emily/shawn>."

Shares live OUTSIDE the research site — a separate Cloudflare Pages project
(**`mtn-share`**, same account as peak_checklist) at `https://mtn-share.pages.dev`.
Open links (no auth), enumeration-resistant, with a lifetime of a few months.

**Commands (`scripts/share_report.py`):**

    scripts/share_report.py <slug>            # new share + share CalTopo map
    scripts/share_report.py <slug> --ttl-days 60
    scripts/share_report.py --publish         # rebuild all + wrangler deploy
    scripts/share_report.py --prune           # expire old: rm pages + share maps
    scripts/share_report.py --rebuild         # regen share_site/ from the ledger

Typical: `share_report.py <slug> && share_report.py --publish` → hand out
`https://mtn-share.pages.dev/s/<token>/`.

**How it stays contained:**

- Sanitizer strips: frontmatter, CLIMBERS block, "Written for <climber>", climbed
  status, drive-from-home rows/fragments, site-internal links, research/regional
  CalTopo links, and neutralizes third-party climber names ("the party").
- Each share gets its OWN CalTopo map ("Share: <title>") holding only the
  recommended route lines + objective summit markers — never the research map.
- Anti-enumeration: `/s/<16-hex-token>/` paths (no slug), no root index, no
  cross-links, robots.txt deny-all + X-Robots-Tag noindex. Open ≠ discoverable.

**Source of truth:** `share/ledger.json` (committed). `share_site/` is a gitignored
staging dir — fully regenerable (`--rebuild`), so links survive machine changes and
re-shares keep their tokens.

**Lifetime:** `ttl_days` (default 120) from `created`. Run `--prune && --publish`
occasionally (candidate for the peak_checklist_bin cron family). Pruned shares 404;
their share maps are deleted; regenerating later is one command.

**One-time setup per Mac:** `npx wrangler login` (Cloudflare OAuth). First deploy:
`npx wrangler pages project create mtn-share --production-branch main`, then
`share_report.py --publish`.

**Honesty about access control:** no auth — the token is the only lock. Don't share
anything that must stay truly private.
