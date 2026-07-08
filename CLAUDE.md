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
- **Don't prompt Kyle for auth pre-emptively.** Only ask him to log in if the **MCP
  browser itself** shows logged-out (or a sweep returns a login page). Never prompt off
  `check_sources_login.py`'s standalone profile — it diverges and false-flagged a login.
- **Retro after every report (Kyle, 2026-06-16).** End each build with a 2–3 line
  self-retro: what did Kyle have to catch or correct, what was prompted that shouldn't
  have been, what got hand-written that should be a `scripts/*.py`. Fold the fix into the
  rails (gate / CLAUDE.md / memory / script) immediately — relentless improvement.
- **Assume, don't ask:** individual-vs-combo and trip grouping — pick the sensible
  default; Kyle redoes if he wants it the other way. When ≥2 reports share a
  drainage/area/drive, proactively build the Trip.
- **Default to single-push combos; don't over-hedge.** Kyle's actual log (601
  ascents) shows a high multi-peak-day tolerance — **4+ peaks on ~24% of his days,
  up to 12 in a day**; 3–6 peaks in one push is routine. So when clustered peaks
  can be linked, **combine them and frame the big day as achievable** — don't lead
  with "backpack instead" or call a 3-peak / ~20-mi day a "monster." Offer the
  backpack as an option, not the headline. (See [[feedback-climbing-patterns]].)
- **Prefer LOOPS; treat recommended mileage as a floor.** Calibrated against Kyle's
  actual tracks: he always loops (never out-and-backs) and does ~15–25% more distance
  than my route (much more on single-peak loops); **gain estimates are reliable**.
  So recommend loop options (esp. single peaks), and don't call these outings "runs"
  — he fast-hikes up and jogs down. (See [[feedback-climbing-patterns]].)
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
   - **ALWAYS scrape EVERY objective peak's GPX library, then DEDUP the combined set**
     (Kyle, 2026-06-16). A single peak's library misses combo/loop tracks that start
     from a *different* peak — the Wayah Group "all-6 loop" tracks lived on the other
     peaks' libraries, so a one-peak sweep made me wrongly call it a point-to-point
     shuttle. The same track also appears in several peaks' libraries, so after
     scraping all of them, **dedup** (by file/track) before building the collection.
     This is non-negotiable — never sweep just one or two of the objective peaks.
   - **LoJ GPX is on TRIP REPORTS, not peak pages (Kyle, 2026-06-17).** A LoJ peak
     page (`/peak/<pkid>`) has NO `.gpx` link — checking it says "empty" and is a FALSE
     negative (it falsely flagged Gladstone, which has 4 TR tracks). The real path:
     peak page → trip-report ids (`tr?Id=<id>&pkid=<pkid>`) → each TR page exposes a gpx
     id → download `listsofjohn.com/gpx/<gpxid>.gpx`. `sweep_peak.py --emit loj` now does
     this harvest. LoJ tracks are ~60% UNIQUE vs 14ers/peakbagger (measured,
     `source_overlap.py`) — worth harvesting, not duplicates.
   - **Never prompt Kyle to log in based on `check_sources_login.py`** — it checks a
     separate standalone profile that routinely diverges. Verify in the MCP browser,
     or just sweep and let a failed fetch (login page, not GPX) be the signal.
   - **Do NOT send Kyle to `check_sources_login.py --login` / `sweep_gpx.py` for
     peakbagger.** That standalone profile gets stuck forever on peakbagger's
     Cloudflare "Verifying you are human…" wall (it's an automated profile Cloudflare
     won't clear — we hit this 2026-06-16). The MCP browser is the only reliable
     peakbagger path; `sweep_gpx.py` is at best a 14ers+LoJ headless convenience.
3. File the swept tracks into `gpx/<slug>/` with `scripts/ingest_gpx.py --slug <slug>
   --json <blob.json>` (for browser_evaluate blobs; direct downloads just get named +
   moved there).
4. `scripts/scaffold_report.py --slug <slug> --objective-ids …` writes
   `gpx/<slug>/peaks.yml`; then fill in `nearby.include`, the trailhead landmark, and the
   `route_build:` recipe (see step 6).
5. `scripts/build_report.py --slug <slug>` — chains the whole data phase
   (build_peak_gpx → caltopo_mytracks → combo_stats → drive_time → **build_route from
   the peaks.yml recipe** → make_overview_map → gpx_to_caltopo --new-map → summit
   markers → sync_to_regional). If peaks.yml has no `route_build:`/`days:` yet it warns
   and skips the route — add the recipe and re-run (or run `build_route.py` +
   `make_overview_map.py` yourself) before --finalize.
6. **The route RECIPE (`route_build:` in peaks.yml) — `scripts/build_route.py <slug>`
   re-runs it standalone when iterating.** It dispatches to the right builder; **gain from
   DEM, distance from GPX**. The recipe records HOW the route is built so it's reproducible
   (routes are gitignored — a plain `build_recommended_route.py` rebuild can silently
   replace a good route with a wrong one; cuba did exactly that). Recipe forms:
   `{method: from_track, track: "<substr>"}` (one recorded track verbatim — best, follows
   every switchback), `{method: graph}` (shortest-path; RDP-simplified, can cut corners —
   the fidelity gate flags those), `{method: legs}` (per-leg/whole-track stitch),
   `{method: multi_segment, tracks:[a,b]}` (disconnected objectives → separate `<trk>`s via
   `build_multi_segment_route.py`; never invent a straight connector), `{method: frozen}`
   (route can't be regenerated — the committed `*_recommended.gpx` IS the source, allow-listed
   in `.gitignore`). For a new report, pick a track-following recipe; if unsure run
   `scripts/infer_route_recipe.py <slug>` to find what reproduces a built route. **A trip
   (days: block) builds per-day via `build_trip_day_routes.py`.** `build_route` auto-mirrors
   the route + summit + trailhead markers into the iCloud **`Documents/GPS Tracks/`** (phone-
   loadable) via `export_to_gps_tracks.py` (backfill: `--all`). `check_route_recipe.py` (a
   gate) FAILs unless the recipe reproduces the committed route.
7. Write `docs/peaks/<slug>.md` (prose + structured frontmatter) and add it to
   `mkdocs.yml` nav (`check_nav.py`, a gate, FAILs any report unreachable from its
   site's nav).
8. `scripts/build_report.py --slug <slug> --finalize` — climber-status + index +
   quickstats + peak-map + **all gates** (nav, teleport/geometry, route-stats, maps,
   extents, reports).
9. `git add … && git commit … && git push` (all allow-listed).

## Hard rules
- **One recommended route per DAY for multi-day trips (Kyle, 2026-06-21).**
  A single-day report has exactly one recommended route; a multi-day **Trip** (frontmatter
  `days: N`, N>1) has **N routes — one composed line per day** (the day clusters can be miles
  apart with no recorded track between them, so there is no single line). Build them with
  **`scripts/build_trip_day_routes.py <slug>`**, which reads a `days:` block in
  `gpx/<slug>/peaks.yml` (each day = `{label, objective_ids}` — a subset of the trip's
  `objective_ids`), composes each day's route from its objective subset + nearest trailhead
  (via `build_recommended_route.py --peaks-only`), and writes `day_<label>_recommended.gpx`.
  `gen_peak_map`/`make_overview_map` draw EVERY `*recommended*.gpx`, so all day routes show
  on the home + overview maps. **No `no_single_route` exemption** — it's gone (it left South
  San Juans with no route at all); `check_route_exists.py` now FAILs a trip with fewer routes
  than days. (Don't leave a stale combined `<slug>_recommended.gpx` next to the day files —
  delete it so it isn't double-drawn.)
- **Rebuild a research map → leave NO duplicate/orphaned CalTopo map (Kyle, 2026-06-21).**
  Each `build_report` rebuild WITHOUT `--caltopo-id` mints a NEW CalTopo map and repoints
  the report's frontmatter to it — orphaning the OLD map on the account. A lingering orphan
  is the "wrong version" Kyle opened by mistake. This is now closed on both ends: (a)
  `build_report.py`'s `--new-map` branch reads the report's current `caltopo_id` and
  **deletes that superseded map** after the new one is created (targeted — only the id this
  report pointed at; via `delete_caltopo_map.py … --force`); (b) `--finalize` runs
  `scripts/audit_caltopo_maps.py` (non-fatal) to surface any other orphaned "Research:" map.
  After any research change, the account is clean only when `audit_caltopo_maps.py` reports
  **0 orphaned**; prune leftovers with `audit_caltopo_maps.py --prune` (or
  `delete_caltopo_map.py <id> --yes`). Personal maps ("GPS Tracks — …", named hikes) are
  never touched. CalTopo is local-only (cts.ini gitignored) — these checks no-op in CI.
- **Kyle's recorded climbs sync onto the research maps (Kyle, 2026-06-22).** peak_checklist
  drops Garmin climbs as `gpx/<slug>/_kyle_existing/<peaks> YYYY-MM-DD_actual.gpx`;
  **`scripts/sync_kyle_recordings.py`** puts them on the slug's CalTopo map + PNG (ledger-gated
  no-op, `--dry-run`, soft-fail, auto commit+push). Map resolution is **duplicate-safe**:
  peaks.yml `caltopo_map_id` → else report frontmatter `caltopo_id` (backfilled into peaks.yml)
  → else create new — so it reuses the existing research map instead of orphaning a duplicate.
  Conventions: Kyle's recordings render **blue `#0066FF`** (gpx_to_caltopo forces `KYLE_COLOR`;
  `recolor_kyle_tracks.py --all --apply` fixes old ones); objective summits **green `#39FF14`
  `peak`, ALL objectives** (not climbed-only); recommended routes magenta. `restyle_markers.py`
  is regional-only. Detail: `docs/methodology/caltopo-pipeline.md`.
- **Change the report format → refresh EVERY report in the same change (Kyle, 2026-06-18).**
  Any change to the report "format" — a new/renamed frontmatter field, a new gate or
  required provenance token, a map style/legend, the report template, quickstats, the
  index/nav schema — is INCOMPLETE until **all existing reports are brought up to the new
  format and `scripts/run_gates.py --all` passes clean.** Never ship a format change that
  only the new report satisfies (that's exactly how 14 reports silently lost source-coverage
  + provenance). The pre-push hook only gates `--changed`, so it will NOT catch this for you —
  after any format change you MUST run `run_gates.py --all` yourself and fix every report it
  flags before committing. If refreshing all of them in one pass is too big, it's still not
  "done": track the remainder as an explicit backlog ([[project-reverify-reports]]) and keep
  `run_gates.py --all` as the definition of done. **The lock is wired:** `run_gates.py` (pre-push
  hook) auto-escalates from `--changed` to `--all` whenever the push touches a format-defining
  file (`CLAUDE.md`, `scripts/check_*`, `scripts/gen_*`, `run_gates.py`, `build_report.py`,
  `scaffold_report.py`, `build_recommended_route.py`, `make_overview_map.py`) — so a format
  change can't land unless every existing report still passes. (CI can't do this — GPX tracks
  are gitignored, absent there; the lock is local in the hook, which has the working-tree tracks.)
- **Use the allow-listed `scripts/*.py` + the Grep / Read / Glob / Edit / Write
  tools.** NEVER run inline `python3 <<'PY'` heredocs, `uv run /tmp/*.py`, or
  `grep`/`sed`/`head`/`cat`/`find`/`awk` in Bash — none are allow-listed and each
  prompts Kyle. **If you need a reusable check, commit it as `scripts/<name>.py` AND add
  a `"Bash(scripts/<name>.py *)"` entry to `.claude/settings.json` `permissions.allow`**
  — there is no glob rule; every script has its own entry, and a missing one is how 700+
  one-off approvals piled up in settings.local.json by 2026-07.
- **Headline distance from measured GPX; gain from a DEM** — never climb13ers prose,
  never GPS `<ele>` (it logs 30,000′ on a 13er).
- **The 3-source sweep must PROVE itself — claims aren't checking (Kyle, 2026-06-16).**
  The Gladstone report shipped a footer saying "all sources swept" when only 14ers
  was pulled; the old `check_reports` lint only matched the footer *text*. So:
  **actually sweep 14ers + LoJ + peakbagger in the MCP browser** (peakbagger GPX =
  `climber/GPXFile.aspx?aid=<aid>&sep=1` on ascents that have a track; LoJ often has
  no downloadable GPX — that's fine), name files `trk_14ers_*` / `trk_loj_*` /
  `trk_pb_*`, and when a source truly has none, record it in `gpx/<slug>/sources.json`
  (`{"listsofjohn":{"checked":true,"found":0,"note":"…"}}`). `check_source_coverage.py`
  (in `--finalize`, scoped to the slug) FAILs unless every source has tracks or a
  verified-empty record — and FAILs a footer that claims a source with no data.
- **No authority to SKIP a research step (Kyle, 2026-06-17).** Doing the research
  is fine; skipping it silently is not — every mandatory step must leave a checkable
  artifact or the build fails. Beyond the sweep (sources.json) and route/class gates,
  `check_report_ready.py` (in `--finalize`) FAILs unless the frontmatter names HOW the
  judgment steps were verified: **`th_source`** (OSM / 14ers TH / recorded-track start —
  never memory), **`class_source`** (a beta URL: 14ers TR / Roach / climb13ers — not the
  peak_db summit grade), **`status_source`** (scrape_14ers_checklist / peak_db ascents —
  never assumed). A junk placeholder won't pass (the gate requires a recognized source token).
- **Verify IDs and trailheads from the source — peak_db can be wrong (Kyle, 2026-06-16).**
  peak_db's `peakbagger_id` for Gladstone pointed at *Mount Wilcox* (pid 5667 vs the
  real 5817). Before using a cross-site id, confirm the page is the right peak (LoJ's
  peak page cross-links the correct peakbagger id). Confirm trailhead identity from
  **OSM** (Overpass: `node[highway=trailhead]` near the recorded track start), not from
  memory. Recorded-track *starts* are real data; the TH **name/elevation** must be
  verified, not inferred. Only connectors may be inferred — label them as such.
- **Class is SAFETY-CRITICAL — research the actual route, not the summit.** peak_db
  `yds_class` is the **per-summit STANDARD-route** grade ONLY. For any traverse, ridge
  link-up, loop, or non-standard line the connecting terrain is often **1–2 classes
  harder** (Mount Adams trio: Class 2 summits, Class 3–4 ridges; Cimarron PT 13,222 B
  is Class 4). Research the real grade from route beta (14ers route desc + trip reports
  + Roach + climb13ers) and set the headline to the **hardest move on the recommended
  route**. **When unsure, take the harder estimate** — under-stating class drives wrong
  gear/rope/helmet decisions. `scripts/check_class.py --strict` (in `--finalize`) FAILs
  any report whose class is below its hardest objective's peak_db class.
- **Verify inputs are COMPLETE before asserting any conclusion (Kyle, 2026-06-16).**
  Almost every miss this session came from concluding on partial data — swept ONE peak's
  GPX library and called Wayah a shuttle (it's a loop); used summit class and called Adams
  "Class 2" (ridges are 3–4); one radius scan → "5 peaks" (6); read a logged-OUT 14ers
  page. Before stating a route shape, class, peak count, or status **as fact**, confirm:
  **all objective peaks' GPX libraries swept + deduped · logged in (MCP browser) · whole
  cluster scanned (`find_peaks_near.py`) · route class from beta, not peak_db summit.**
  Concluding from one source → label it provisional, not fact.
- **Scrape the report-climber's climbed status EVERY time — never assume (Kyle, 2026-06).**
  Kyle: peak_db ascents (or `find_peaks_near.py`). Other climbers:
  `scripts/scrape_14ers_checklist.py --climber <slug>`. Set the report status from the
  scrape. (Regenerate a climber's home page with `gen_index.py --climber <slug>`.)
- **Identify peak clusters with `scripts/find_peaks_near.py`** (`--near "<peak>"` or
  `--center lat,lon`) — lists ranked neighbors + climbed status + every source id. Not
  inline peak_db python.
- **Red `!!! danger` box only for Class 4/5 or a genuinely sketchy section** (serious
  exposure, a notorious obstacle like the Clohesey 4x4 road). Ordinary Class 2/2+/3 days:
  just write the summary normally — no alarm box.
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
