# Architecture & deployment

**Last updated:** 2026-06-02

## What it is

A solo, file-based research pipeline that turns Kyle's "I want to climb that peak" into a published, version-controlled, link-shareable research dossier. Optimized for low-ops (no servers Kyle runs), reproducibility (every artifact derives from inputs in iCloud + a few external APIs), and Claude-driven workflow (one conversation produces one full research cycle).

It is **not** an app. It is **a static site fed by an iCloud-synced repo, with scripts that pull from one private DB and several public web sources.** The "runtime" is the terminal during a Claude session; the "deploy target" is GitHub Pages.

## Components

| Layer | Component | Where it lives | Role |
|---|---|---|---|
| **Authoring runtime** | Claude session in `mtn_research/` | macOS terminal / Claude Code | The agent that drives the cycle: queries DB, reads TRs, writes markdown, runs scripts, commits |
| **Canonical methodology** | `docs/methodology/*.md` | repo (published) | **Source of truth** for how research is done: workflows, source rules, CalTopo pipeline, report template, conventions, improvement plan. Read first by any session. |
| **Memory** | `~/.claude/projects/.../memory/*.md` | per-Mac local | A **thin bootstrap pointer** to `docs/methodology/` plus a few live references (peak_db, playwright-mcp, 14ers-required, user-location). If memory conflicts with the repo docs, the docs win. |
| **Peak data — source of truth** | Supabase `peak_checklist` DB | Supabase cloud | ~861 peaks + ascents + list memberships. Read-only here. Kyle's climbed list. |
| **Peak data — client** | `peak_db_client.py` | `~/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db/` (iCloud) | Stdlib-only Python module + the read key. Shared across all Claude projects. |
| **External research sources (×3, all required)** | 14ers.com · listsofjohn.com · peakbagger.com (TRs, GPX, route/stat data, 14ers cell DB) | public web, logged-in | Driven via **Playwright MCP** (persistent profile, all 3 logged in). The Claude-in-Chrome extension is NOT used — it has an open allowlist bug. |
| **Maps** | CalTopo (interactive research maps + per-range regional "GPS Tracks" maps) | private maps | Read via `fetch_caltopo.py`; write via `gpx_to_caltopo.py` / `sync_to_regional.py`; restyle via `restyle_markers.py` (caltopo_python API). |
| **Repo (iCloud-synced)** | `Projects/mtn_research/` | iCloud Drive | Single source for code, docs, raw GPX, CalTopo dumps. Cross-Mac via iCloud sync. |
| **Tooling** | `scripts/*.py` | repo, in `scripts/` | uv inline-deps for portable scripts; stdlib for the simple ones |
| **Inputs (gitignored)** | `gpx/<slug>/`, `caltopo/<map_id>.json`, `notes/`, `scripts/cts.ini` | repo, gitignored | Personal data + credentials. Live only in iCloud. |
| **Outputs (versioned)** | `docs/**`, `climbers/*.yml`, `mkdocs.yml`, `overrides/`, scripts | repo, in git | The publishable artifacts + per-climber profiles + scripts. |
| **CI/CD** | `.github/workflows/docs.yml` | repo | On push to `main`: **lint** (source-rigor gate, `check_reports.py`) → **build** (mkdocs) → **deploy** (Pages). Lint failure blocks the deploy. |
| **Hosting** | GitHub Pages | `kylegknutson.github.io/mtn-research/` | Public, free, custom-domain-capable. Static-only. |
| **Source mirror** | GitHub `kylegknutson/mtn-research` | `github.com/kylegknutson/mtn-research` | Public repo. Markdown viewable directly. |

## Deployment diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         CLAUDE SESSION (any Kyle Mac)                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                       Claude (Sonnet, Code CLI)                          │ │
│  │   ▲                                                                      │ │
│  │   │ reads on every session start                                         │ │
│  │   │                                                                      │ │
│  │   ├─── memory bootstrap → docs/methodology/ (canonical workflow docs)    │ │
│  │   │                                                                      │ │
│  │   ├─── Playwright MCP (persistent profile; 14ers + LoJ + peakbagger      │ │
│  │   │       all logged in)  ·  Chrome extension unused (allowlist bug)     │ │
│  │   │                                                                      │ │
│  │   └─── Bash / Edit / Write / Grep / Read tools                           │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└────┬────────────────────────────────────────────────────────────────────────┬─┘
     │                                                                        │
     │  query peaks/ascents (read-only)                                       │
     ▼                                                                        │
┌──────────────────────────────────┐                                          │
│   ~/Library/.../shared/peak_db/  │   (iCloud-synced, NOT in repo)           │
│   ─────────────────────────────  │                                          │
│   peak_db_client.py  (stdlib)    │                                          │
│   peak_checklist.env (secret_key)│──┐                                       │
└──────────────────────────────────┘  │                                       │
                                      │ HTTPS / PostgREST                     │
                                      ▼                                       │
                       ┌──────────────────────────────┐                       │
                       │   Supabase (peak_checklist)  │                       │
                       │   ───────────────────────    │                       │
                       │   peaks (861)  ascents (591) │                       │
                       │   peak_lists (946)           │                       │
                       │   ← written by separate      │                       │
                       │     peak_checklist webapp    │                       │
                       └──────────────────────────────┘                       │
                                                                              │
                       ┌──────────────────────────────┐                       │
     ┌─────────────── │   Public web (HTTPS)         │ ──────────────────────┤
     │                │   ───────────────────────    │                       │
     │  Playwright    │   • 14ers · LoJ · peakbagger │   CalTopo (research +  │
     │  MCP (logged   │      (TRs, GPX, stats, cell) │   regional maps,       │
     │  in ×3)        │   • Google Maps (drive time) │   caltopo_python API)  │
     │  ◀────────────│   • CalTopo private maps     │ ─────────────────────▶ │
     │                └──────────────────────────────┘                        │
     │                                                                        │
     ▼                                                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  REPO: ~/Library/.../Projects/mtn_research/                  │
│                          (iCloud-synced; git-tracked)                        │
│                                                                              │
│   ┌──────── gitignored (personal data) ────────┐  ┌──── tracked in git ───┐ │
│   │                                             │  │                       │ │
│   │  gpx/<slug>/*.gpx                           │  │  docs/peaks/*.md      │ │
│   │  caltopo/<map_id>.json                      │  │  docs/maps/*.png      │ │
│   │  scripts/cts.ini                            │  │  scripts/*.py         │ │
│   │  notes/*.md (WIP planning)                  │  │  mkdocs.yml           │ │
│   │                                             │  │  README.md            │ │
│   └─────────────────────────────────────────────┘  └───────────────────────┘ │
│                                                                              │
│                      scripts/ (uv inline-deps, portable)                     │
│   ┌─────────────────────┬──────────────────────┬──────────────────────────┐ │
│   │ make_overview_map   │ fetch_caltopo        │ find_nearby              │ │
│   │ (Pillow+OSM tiles,  │ gpx_to_caltopo       │ combo_stats              │ │
│   │  source-colored)    │ sync_to_regional     │ drive_time               │ │
│   │ caltopo_to_gpx      │ restyle_markers      │ check_reports (CI gate)  │ │
│   │ build_*_gpx         │ delete_caltopo_marker│ (all caltopo_python/std) │ │
│   └─────────────────────┴──────────────────────┴──────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │  git push origin main  (via gh auth)
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GitHub: kylegknutson/mtn-research                    │
│                                                                              │
│   ┌──────────────────────┐         ┌──────────────────────────────────────┐ │
│   │ main branch          │ ─────▶  │ GitHub Actions: docs.yml             │ │
│   │ (markdown, PNGs,     │         │   - lint: check_reports.py (gate)    │ │
│   │  scripts, mkdocs.yml)│         │   - build: mkdocs                    │ │
│   └──────────────────────┘         │   - deploy: Pages artifact           │ │
│                                    └─────────────┬────────────────────────┘ │
│                                                  ▼                           │
│                                    ┌──────────────────────────────────────┐ │
│                                    │ gh-pages branch (static HTML)        │ │
│                                    └─────────────┬────────────────────────┘ │
└──────────────────────────────────────────────────┼──────────────────────────┘
                                                   │
                                                   ▼
                            ┌──────────────────────────────────────────┐
                            │  GitHub Pages CDN                         │
                            │  kylegknutson.github.io/mtn-research/    │
                            │                                           │
                            │  Reader (Kyle's iPhone, friends, etc.)   │
                            └──────────────────────────────────────────┘
```

**Legend:**

- Solid lines: same-machine / same-trust boundary
- Arrows across the boundary: network hop with auth (token / cookie / key)

## One research cycle, step by step

1. **Kyle:** "Find me unclimbed Sangre 13ers under 4,000 ft / 8 mi" (narrow-down) or "do a report on Peak X" (report).
2. **Claude reads `docs/methodology/`** (pointed to by the memory bootstrap) → knows the workflow, source rules, pipeline, conventions.
3. **Login check** — confirm all 3 sources logged in via Playwright (per source-requirements). No 14ers → halt.
4. **DB query** via `peak_db_client.peaks(...)` + `ascents()` → candidates; cluster analysis (nearby unclimbed ranked, same-drainage flag).
5. **TR + GPX sweep across all 3 sources** (14ers + LoJ + peakbagger) via Playwright → route stats, combo signal, every GPX track.
6. **Stats / cell / drive** → `combo_stats.py` (distance/gain), 14ers cell DB, `drive_time.py` (Maps link from the climber's home).
7. **Authoring** → `docs/peaks/<slug>.md` (or `docs/trips/` for multi-day) per the report template, ending with the "Sources checked" footer.
8. **Maps (required, ship with the report):**
   - `gpx_to_caltopo.py --gpx-dir gpx/<slug> --new-map "Research: …" --no-dedupe` → research map (summit=blue `peak`, others=gray `point`, tracks source-colored).
   - `sync_to_regional.py --slug <slug> --map-id <regional>` → also push tracks into the range's regional "GPS Tracks" map.
   - `make_overview_map.py <slug>` → `docs/maps/<slug>.png` (source-colored, objective-framed).
9. **Wire up** → map IDs + PNG into the markdown; `image:` frontmatter for the link preview; mkdocs nav + index.
10. **Commit + push** → Actions runs **lint (source gate) → build → deploy**; Pages updates in ~1 min. Don't mark "researched" until the deploy is green.
11. **Result:** a public URL with a link-preview card, openable from the phone at the trailhead, plus interactive CalTopo research + regional maps.

## Concepts added since the original design

- **Methodology is canonical and in-repo.** `docs/methodology/` (workflows, source-requirements, caltopo-pipeline, report-template, conventions, improvement-plan) is the source of truth. Memory is a thin pointer. → reproducible on any Mac, no chat history.
- **Three sources, always.** 14ers + LoJ + peakbagger must each be logged-in and checked; a "Sources checked" footer asserts it and the CI lint gate enforces it.
- **Browser = Playwright MCP** (persistent profile), not the Claude-in-Chrome extension (open allowlist bug).
- **CalTopo: research + regional maps.** Each report has a focused research map; tracks are *also* synced into a per-range regional "GPS Tracks" map (registry in `caltopo-pipeline.md`). Marker scheme: summit = blue `peak` (`#2E78C7`), everything else = gray `point` (`#9E9E9E`); tracks colored by source.
- **Multi-climber.** `climbers/<slug>.yml` holds home address (drive-time origin) + climbed-list source (peak_db for Kyle, 14ers checklist for friends). Friends get per-`(peak,climber)` reports and their own published site. (Scaffolded; not yet exercised end-to-end.)
- **Report flavors.** Single-peak · day-trip (multi-peak, one outing) · multi-day backpack (`docs/trips/`).
- **Narrow-downs as artifacts.** Saved to `docs/lists/` (snapshot + re-runnable criteria) rather than chat-only. *(Planned — see improvement-plan.)*
- **Site polish.** Flatirons favicon + home logo; per-report Open Graph link previews (own overview map as the card) via `overrides/main.html`; external links open in a new tab.

## What's reproducible vs. authoritative

| Artifact | Source of truth | Regeneratable? |
|---|---|---|
| `peaks` / `ascents` rows | Supabase (written by separate peak_checklist webapp) | No — owned upstream |
| Downloaded GPX in `gpx/<slug>/` | 14ers + LoJ + peakbagger (logged-in, via Playwright) | Yes — re-sweep all 3 sources |
| CalTopo JSON dumps in `caltopo/` | Kyle's CalTopo account | Yes — `fetch_caltopo.py` |
| Overview PNGs in `docs/maps/` | derived from `gpx/<slug>/` + OSM tiles | Yes — `make_overview_map.py` |
| Markdown in `docs/peaks/` | Claude + Kyle, version-controlled in git | Authoritative — this is the work product |
| Published mkdocs site | derived from markdown via Actions | Yes — git push triggers rebuild |
| CalTopo research maps (cloud) | Kyle's CalTopo account, written by `gpx_to_caltopo.py` | Yes — re-run script with same GPX |

**The research markdown is the only thing that isn't trivially regenerable.** Everything else is a derived artifact or an upstream mirror. That's the key property — losing the laptop costs nothing if iCloud has synced (and even iCloud loss is fine if git has the markdown).

## Trust & secrets

| Secret | Where | Risk if leaked |
|---|---|---|
| `SUPABASE_SECRET_KEY` (peak_db) | iCloud-only `shared/peak_db/peak_checklist.env` | Full RW on Kyle's climb DB. Never in git, never in chat. Rotate via Supabase dashboard. |
| CalTopo credentials | `scripts/cts.ini` (gitignored) | Full account access to maps. |
| GitHub PAT | `gh` keyring (system) | Repo push access. Per-Mac via `gh auth login`. |

Everything else (research markdown, public GPX, OSM tiles, etc.) is public-by-design.

## Why this stack

- **No server Kyle runs.** Supabase + GitHub Pages + iCloud. The only thing maintained is the markdown and scripts.
- **Multi-Mac portability solved twice.** iCloud sync handles the repo and personal data; `uv` + `gh` handle the per-Mac toolchain (one `brew install` apiece, then nothing to remember).
- **Claude is in the loop, not a one-shot.** Memory files mean every session starts informed. The workflow recipes are versioned outside the project repo (in `~/.claude/projects/.../memory/`), so they evolve with the agent.
- **Public output, private inputs.** `.gitignore` cleanly splits "research notes for the world" from "Kyle's personal GPX + CalTopo data." Same repo, two audiences.

---

*This page is regenerated whenever the architecture changes — scripts added/removed, deployment target moves, secrets rotated, etc. Update the "Last updated" date at the top when editing.*
