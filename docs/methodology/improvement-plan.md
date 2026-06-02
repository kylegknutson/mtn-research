# Improvement plan

A formal, prioritized plan for evolving this project. Supersedes the narrower [automation roadmap](automation-roadmap.md) (now folded in as Theme A). Living document — check items off and re-prioritize as things land.

*Last updated: 2026-06-02*

---

## Stated goals (the "why")

From the project's [methodology model](index.md) and Kyle's scoping:

1. **Multiple workflows** — narrow-down queries *and* reports, each with its own shape.
2. **Persistent narrow-downs** — saved artifacts (snapshot + re-runnable criteria), not chat tables.
3. **Three report flavors** — single peak · single-day multi-peak · multi-day backpack (with pack in/out).
4. **Multi-climber** — build reports for friends, each with their own home origin, climbed list, and published site.
5. **Source rigor** — 14ers + LoJ + peakbagger always used and confirmed; a missing source = invalid research.
6. **Reproducible anywhere** — runs from any Mac with no chat-history context; canonical state lives in GitHub.
7. **Systematized** — script the mechanical work so the LLM only does judgment, cutting tool-call/approval churn.

Everything below serves one or more of these.

---

## Current state (done)

- Methodology is canonical in `docs/methodology/` (workflows, source rules, CalTopo pipeline, conventions, report template). Memory is a thin pointer.
- 11 peak reports published; each ships report + CalTopo map + PNG, weather link, clickable drive link, all-3-source TRs + "Sources checked" footer.
- Regional CalTopo maps registry + `sync_to_regional.py`; all reports' tracks synced to their range maps.
- Canonical marker scheme (blue `peak` summits / gray `point` others) enforced via `gpx_to_caltopo.py --marker-symbol` + `restyle_markers.py`; all maps normalized.
- Site: Flatirons favicon + home logo, social-card + per-report link previews, external-links-new-tab.
- Climber profile schema + `climbers/kyle.yml`.

---

## Themes & backlog

Effort: **S** ≤ ½ day · **M** ~1 day · **L** multi-day. Impact on the goals in (parens).

### Theme A — Automation (cut LLM usage + approvals) → goals 5,6,7
The core lever. Push mechanical work into scripts; LLM only writes narrative + reviews.

| ID | Item | Effort | Notes |
|---|---|---|---|
| A1 | `check_sources_login.py` | S | Confirm logged-in on all 3 sites, print usernames. High-frequency. |
| A2 | `combo_stats.py` | S | Distance/gain/elev from GPX track(s). Replaces inline python. |
| A3 | `drive_time.py --climber` | S | Maps drive time + directions URL from a climber's home. |
| A4 | `sweep_gpx.py <peakids>` | M | Download all GPX from all 3 sources, source-suffixed filenames. Consolidates the most repetitive scraping. |
| A5 | `build_peak_gpx.py <slug>` | M | Generic replacement for the hardcoded `build_close_5_gpx.py` (summit + nearby-ranked + TH/landmark waypoints from peak_db + a per-peak coords config). |
| A6 | `research_peak.py` orchestrator | L | Runs A1–A5 + cell DB + CalTopo map + PNG, emits a data-filled report skeleton with `<!-- TODO: narrative -->` blocks. Idempotent (sentinel-guarded narrative). The big win. |
| A7 | `narrow_down.py --criteria` | M | Run a saved narrow-down query → `docs/lists/`. Removes LLM-by-hand peak_db filtering. |

### Theme B — Quality gates / testing → goals 5,7
Stop the recurring failure modes from shipping.

| ID | Item | Effort | Notes |
|---|---|---|---|
| B1 | Map-QA tests | M | Gate PNGs: objective centered, not over-zoomed/dot, track layer present, non-blank tiles. Catches the "redo the map" loop. |
| B2 | Multi-color PNG tracks | S | Color route lines by source (LoJ/14ers/pb) like CalTopo. In `make_overview_map.py`. |
| B3 | Source-check gate | S | CI/pre-commit fails a report lacking a valid "Sources checked" footer naming all 3 sites. Makes goal 5 enforceable, not just convention. |
| B4 | Link-rot check | S | CI checks external links in reports resolve (14ers/LoJ/PB/CalTopo/Maps). |
| B5 | Report ↔ template conformance | M | Lint reports against `report-template.md` (required sections present, TR-table column order, cell-coverage section not left TODO). |

### Theme C — Data model / structure → goals 1,2,6
Make the content machine-readable so indexes and queries stop being hand-maintained.

| ID | Item | Effort | Notes |
|---|---|---|---|
| C1 | Structured report frontmatter | M | `range, gain, class, drive_time, status, regional_map_id, caltopo_id` per report. Drives C2/C3 and OG descriptions. |
| C2 | Auto-generated index / nav | M | Build `index.md` + nav from frontmatter — kills drift between files, nav, and the Home list. |
| C3 | Sortable/filterable peak table | M | Landing-page table (sort by drive time / gain / range / status) generated from frontmatter. |
| C4 | Produce real `docs/lists/` artifacts | S | Actually emit the narrow-down snapshots we've only done in chat (pairs with A7). |

### Theme D — Multi-climber (prove it end-to-end) → goal 4
Currently scaffolded but never exercised.

| ID | Item | Effort | Notes |
|---|---|---|---|
| D1 | `scrape_14ers_checklist.py <url>` | M | A friend's climbed/unclimbed list from their 14ers checklist URL. |
| D2 | Multi-site CI build | M | `deploy.yml` builds N sites (Kyle + each friend) from `mkdocs.<climber>.yml`, each to its own Pages URL. |
| D3 | First friend, end-to-end | M | Onboard one real friend: profile + checklist + one report + their published site. Shakes out the per-(peak,climber) flow. |

### Theme E — Content depth / UX → goals 1,3
Make the reports richer and the multi-day flavor real.

| ID | Item | Effort | Notes |
|---|---|---|---|
| E1 | First multi-day trip report | M | Exercise the `docs/trips/` flavor (basecamp, day-by-day, pack in/out, gear). Only the day-trip flavor has a real example so far. |
| E2 | Elevation-profile charts | M | Per-route elevation profile from the GPX, embedded in the report. |
| E3 | "Trip packet" export | L | Bundle a report into an offline packet (PDF + GPX + static map) for a planned outing. |

### Theme F — Maintenance / hygiene → goal 6
Keep the foundation honest.

| ID | Item | Effort | Notes |
|---|---|---|---|
| F1 | Refresh `architecture.md` | S | Stale (2026-05-21): says Chrome MCP (now Playwright), missing regional maps, marker scheme, new scripts, methodology section, multi-climber. |
| F2 | Report-freshness checker | M | Flag reports whose source TR counts have grown materially since the "Researched:" date → candidates for a freshness pass. |
| F3 | GPX backup story | S | GPX is gitignored (iCloud-only). Either document the re-fetch-from-source recovery path or add a periodic archive. |
| F4 | Consolidate CalTopo scripts | M | `gpx_to_caltopo` / `sync_to_regional` / `restyle_markers` / `caltopo_to_gpx` / `delete_caltopo_marker` overlap — factor shared logic into one small module. |

---

## Recommended sequencing

Build in order of *value per effort*, smallest-first within a wave so each step independently reduces friction.

**Wave 1 — quick wins (mostly S):** A1, A2, A3, B2, F1, B3
→ Removes the most repetitive per-session steps, fixes the stale architecture doc, makes source-rigor enforceable, and gets source-colored PNGs.

**Wave 2 — consolidation (M):** A5, B1, C1 ✅ *(done 2026-06-02)*; **A4 → moved to Wave 3**
→ Generic GPX builder, the map-QA gate, machine-readable frontmatter. **A4 (`sweep_gpx`) was moved to Wave 3:** a headless cross-domain GPX sweep needs the authenticated-session-reuse that `research_peak.py` has to design anyway (a browser can only fetch same-origin, so it must navigate each of the 3 sites logged-in). Building it before that auth is solved would force a second login — explicitly avoided. Until then, the sweep is done in-chat via the MCP browser (already efficient).

**Wave 3 — the orchestrator (L):** A6 ✅ *(done 2026-06-02)* · A4 (resolved) · A7 (next)
→ **A6 `research_peak.py` built:** the auth question was resolved by *not* fighting it — the authenticated TR/GPX sweep stays an in-chat Playwright-MCP step (already logged in, no second login), and `research_peak.py` does everything mechanical *after* the sweep: regenerate waypoints, cluster analysis, combo stats, drive-time URL, and emit a data-filled report skeleton (`<slug>.skeleton.md`) with frontmatter + Quick Stats + cluster + Sources footer + `<!-- TODO -->` narrative blocks, then prints the map-build commands. The LLM fills the judgment sections and verifies. This is the big tool-call/approval saver. **A4 standalone `sweep_gpx` is therefore not needed** as separate infra — the sweep lives in the MCP browser. **A7 (`narrow_down.py`) is the remaining Wave 3 item.**

**Wave 4 — surface & scale (M):** C2 ✅ C3 ✅ C4 ✅ D1 ✅ D2 ✅ D3 ✅ *(done 2026-06-02)* — **Wave 4 complete**
→ Auto-built sortable index table (C2/C3, CI-checked) + saved lists (C4) done. **Multi-climber data layer done:** `scrape_14ers_checklist.py` pulls a friend's climbed list from their public 14ers checklist (correct path: `/php14ers/checklist.php?usernum=<N>&checklist={13ers|14ers}` — server-rendered, no auth) and maps it to peak_db ids; `climber.py` `climbed_ids(slug)` makes the tooling climber-agnostic (peak_db for Kyle, checklist for friends); `narrow_down`/`research_peak` compute "unclimbed" per climber. **Emily onboarded** (`climbers/emily.yml`, 157 ranked 13ers) — her narrow-downs correctly differ from Kyle's. **D2 ✅ Emily has a published site** at [kylegknutson.github.io/mtn-research/emily/](https://kylegknutson.github.io/mtn-research/emily/) — `mkdocs.emily.yml` (INHERIT + exclude_docs to scope to her content, shared maps/methodology), built into the `/emily/` subpath by the same CI deploy, seeded with a Crestolita + Broken Hand report written for her (her 3h 26m drive from Highland, both unclimbed on her checklist). A `hooks/climber_home.py` retargets `index.<climber>.md` → site root. Home address set to Highland, Denver. **Multi-climber is proven end-to-end.** Adding the next friend is mechanical: profile YAML + their checklist URL + an `mkdocs.<name>.yml` + one CI build line.

**Wave 5 — depth (M–L):** E1, E2, F2, F4, B4, B5, E3
→ Multi-day reports, elevation profiles, freshness/link-rot checks, script consolidation, trip packets.

---

## How to use this doc

- When starting an improvement, mark it in-flight here and link the commit/PR.
- New ideas get an ID under the right theme.
- Re-sequence freely — the waves are a default, not a contract.
