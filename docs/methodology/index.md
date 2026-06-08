# Methodology

This section is the **canonical source of truth** for how peak research is done in this project. It lives in the repo (not in chat history or a single machine's notes) so the workflow is reproducible on any Mac, by any session, with no prior context.

> **For Claude / any automated session:** Read this page and the relevant workflow page *before* starting a research task. The memory bootstrap file points here. If anything in memory conflicts with these docs, **these docs win.**

---

## The model

### Workflows (what kind of task is this?)

| Workflow | Trigger | Output |
|---|---|---|
| **[Narrow-down](workflows/narrow-down.md)** | Open-ended "which peaks…" question with criteria | A saved list artifact in `docs/lists/` (snapshot table + re-runnable criteria) |
| **[Single-peak report](workflows/single-peak-report.md)** | "Do a report on Peak X" | `docs/peaks/<slug>.md` + CalTopo map + PNG |
| **[Day-trip report](workflows/day-trip-report.md)** | "Research a combo/cluster day" (≥2 peaks, one outing) | `docs/peaks/<slug>.md` (day-trip flavor) + CalTopo map + PNG |
| **[Multi-day-trip report](workflows/multi-day-trip-report.md)** | "Plan a backpack trip with peaks over several days" | `docs/trips/<slug>.md` + CalTopo map + PNG |

### Cross-cutting rules (apply to every workflow)

- **[Source requirements](source-requirements.md)** — all three sources (14ers + LoJ + peakbagger) must be confirmed logged-in and checked, every time. A logged-out or skipped source = invalid research.
- **[CalTopo + PNG pipeline](caltopo-pipeline.md)** — GPX collection → CalTopo map → PNG overview. A report isn't done until all three artifacts ship together.
- **[Report template](report-template.md)** — the canonical report structure (Quick Stats, map, routes, conditions, TRs, TL;DR).
- **[Site conventions](conventions.md)** — weather link, clickable drive link, external-links-new-tab, naming.

### Climbers (who is this for?)

- This is a **multi-climber** system. Each climber has a profile in `climbers/<name>.yml` (home address for drive times, climbed-list source).
- **Kyle** is the default/owner: his reports are `docs/peaks/<slug>.md` (no suffix), his climbed list comes from the Supabase peak_db.
- **Friends** get per-climber reports `docs/peaks/<slug>.<climber>.md` and their own published site; their climbed list comes from a 14ers.com checklist URL they provide.
- **Default to Kyle only.** A report request builds *just Kyle's* report unless he explicitly says otherwise — "for Emily", "for Emily and me", "for everyone", etc. Don't fan a report out to all climbers by default. (Kyle, 2026-06-02)
- See [`climbers/_schema.md`](https://github.com/kylegknutson/mtn-research/blob/main/climbers/_schema.md) for the profile format.

### Where things live

```
docs/methodology/   ← this section: canonical workflow definitions (published)
docs/lists/         ← saved narrow-downs (snapshot + criteria)
docs/peaks/         ← single-peak + day-trip reports
docs/trips/         ← multi-day backpack trips
docs/maps/          ← PNG overviews (one per report)
climbers/           ← per-climber profiles (kyle.yml, <friend>.yml)
gpx/                ← per-report GPX collections (gitignored; shared across climbers — route geometry doesn't change by who's climbing)
scripts/            ← uv inline-dep Python (build GPX, upload CalTopo, render PNG, scrape checklists)
```

---

## Hard requirements (invariants)

These must always hold. They're elaborated in the linked pages.

1. **14ers.com reachable + logged in** before research starts, or HALT (don't substitute weaker sources).
2. **All 3 TR sources** checked per peak (14ers + LoJ + peakbagger), each confirmed logged-in.
3. **All 3 GPX sources** swept per peak.
4. **Report + CalTopo map + PNG** ship together.
5. **Combos = ranked 13ers+ only** (sub-13k bumps don't count).
6. **"Closest" = drive time** from the climber's home address, not haversine.
7. **Map waypoint scope = same-objective only** (no peaks reached from a different drive).
8. **External links open in a new tab.**
9. **Auto-generated PNGs** must pass the framing check (objective centered, not over-zoomed/distorted).
10. **"Sources checked" footer** present on every report, naming each site + confirmed username.

---

## Tech stack

| Layer | Tech |
|---|---|
| Browser automation | Playwright MCP (canonical; Chrome extension has an open allowlist bug) |
| Scripts | Python via uv inline deps (no venv) |
| Site | MkDocs Material → GitHub Pages |
| CI/CD | GitHub Actions |
| Kyle's climbed list | Supabase peak_db |
| Friends' climbed list | 14ers.com checklist (scraped) |
| Map basemap | OpenTopoMap tiles |
| Research map host | CalTopo (caltopo_python) |
| Source of truth | Git / GitHub |

*Last updated: 2026-05-31*

## Resolving peak names

When the user names a set of peaks, **resolve them yourself by geography** — if the names cluster tightly in one area (peak_db lat/lon), pick the matching peaks in that cluster rather than asking. Only ask when a name has **zero match** in peak_db, LoJ, *and* 14ers (e.g. an informal/local name like "Cotton King" = PT 13,494 — no database entry, genuinely unresolvable without the user). (Kyle, 2026-06-03)

## Cross-climber status on every report

Every report carries an auto-generated **"Other climbers"** line (between `<!-- CLIMBERS_START -->` / `<!-- CLIMBERS_END -->`) showing whether the *other* configured climbers have climbed its peak(s) — e.g. `Emily Sharpe — 1 of 2 (Mount Powell A) · Shawn D Keil — not yet`. Generated by `scripts/climber_status.py` from each climber's `climbed_ids` (peak_db for Kyle, 14ers checklist for friends); re-run it after adding a report or a new climber. CI checks it's current (`--check`). Non-CO peaks (e.g. NH) show friends as "not yet" since their source is the CO 14ers checklist. (Kyle, 2026-06-03)
