# mtn_research — build runbook for Claude

This repo publishes deeply-researched Colorado 13er/14er reports to a MkDocs site
on GitHub Pages. **The mechanical pipeline is a set of allow-listed `scripts/*.py`.
Your job is to drive those rails and write the prose — not to re-invent the
pipeline with ad-hoc shell.** (A 2026-06 "simple report" ballooned into dozens of
permission prompts because I improvised with inline `python3` heredocs, `/tmp`
scripts, and raw `grep`/`sed` instead of using the scripts. Don't repeat that.)

## Operating mode (Kyle, 2026-06)
- **Autonomous:** build → run all gates → commit → **push** → report. Don't stop to
  ask "should I push?" — publishing to his own Pages site is pre-authorized.
- **Stop ONLY for:** a gate failure, or a genuine judgment call (ambiguous/conflicting
  scope, something destructive/irreversible, or a fork that's expensive if wrong).
- **Assume, don't ask:** individual-vs-combo and trip grouping — pick the sensible
  default; Kyle redoes if he wants it the other way. When ≥2 reports share a
  drainage/area/drive, proactively build the Trip.
- **Never invent a straight-line combo connector.** If no recorded track links two
  peaks, make them individual climbs (each its own `<trkseg>`). The teleport gate
  enforces this.

## The rails — how to build a report (do NOT improvise around these)
Every step below is an **allow-listed** call or a Grep/Read/Edit/Write tool. A
single-peak/group report is essentially:

1. `scripts/preflight.py --slug <slug> --ids <peak_db ids>` — resolve peaks, creds,
   climber profile → GO/NO-GO. Surfaces ambiguity NOW, not mid-build.
2. **Sweep GPX from all 3 sources in the Playwright-MCP browser** (already logged in
   — it's the login source of truth, and it clears peakbagger's Cloudflare check).
   Save tracks into `gpx/<slug>/`. **This is THE sweep path — use it for all three.**
   - **Never prompt Kyle to log in based on `check_sources_login.py`** — it checks a
     separate standalone profile that routinely diverges. Verify in the MCP browser,
     or just sweep and let a failed fetch (login page, not GPX) be the signal.
   - **Do NOT send Kyle to `check_sources_login.py --login` / `sweep_gpx.py` for
     peakbagger.** That standalone profile gets stuck forever on peakbagger's
     Cloudflare "Verifying you are human…" wall (it's an automated profile Cloudflare
     won't clear — we hit this 2026-06-16). The MCP browser is the only reliable
     peakbagger path; `sweep_gpx.py` is at best a 14ers+LoJ headless convenience.
3. Write `gpx/<slug>/peaks.yml` (`objective_ids`, `nearby.include`, trailhead landmark).
4. `scripts/build_report.py --slug <slug>` — chains the whole data phase
   (build_peak_gpx → caltopo_mytracks → combo_stats → drive_time → make_overview_map
   → gpx_to_caltopo --new-map → summit markers → sync_to_regional).
5. `scripts/build_recommended_route.py <slug>` — composed route; **gain from DEM,
   distance from GPX**. If the teleport gate flags it, re-run with `--legs`.
6. Write `docs/peaks/<slug>.md` (prose + structured frontmatter) and add it to
   `mkdocs.yml` nav.
7. `scripts/gen_quickstats.py`
8. `scripts/build_report.py --slug <slug> --finalize` — climber-status + index +
   peak-map + **all gates** (teleport/geometry, route-stats, maps, extents, reports).
9. `git add … && git commit … && git push` (all allow-listed).

## Hard rules
- **Use the allow-listed `scripts/*.py` + the Grep / Read / Glob / Edit / Write
  tools.** NEVER run inline `python3 <<'PY'` heredocs, `uv run /tmp/*.py`, or
  `grep`/`sed`/`head`/`cat`/`find`/`awk` in Bash — none are allow-listed and each
  prompts Kyle. **If you need a reusable check, commit it as `scripts/<name>.py`**
  (the `scripts/*.py *` allow rule covers it automatically).
- **Headline distance from measured GPX; gain from a DEM** — never climb13ers prose,
  never GPS `<ele>` (it logs 30,000′ on a 13er).
- **All 3 sources (14ers + LoJ + peakbagger) every time, + climb13ers for CO peaks**,
  named in the report's "Sources checked" footer (CI lint enforces it).
- Don't mark a report "researched" until the Pages deploy is green.

## Where the detail lives
- `docs/architecture.md` — full system map + the fast path.
- `docs/methodology/` — source-requirements, caltopo-pipeline, report-template,
  conventions, and per-workflow checklists (`workflows/*.md`).
- peak_db client: `/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db`
  (Kyle's climbed-list + peak metadata; query via `preflight.py`/`find_nearby.py`,
  not inline python).
