# Architecture & deployment

**Last updated:** 2026-05-21

## What it is

A solo, file-based research pipeline that turns Kyle's "I want to climb that peak" into a published, version-controlled, link-shareable research dossier. Optimized for low-ops (no servers Kyle runs), reproducibility (every artifact derives from inputs in iCloud + a few external APIs), and Claude-driven workflow (one conversation produces one full research cycle).

It is **not** an app. It is **a static site fed by an iCloud-synced repo, with scripts that pull from one private DB and several public web sources.** The "runtime" is the terminal during a Claude session; the "deploy target" is GitHub Pages.

## Components

| Layer | Component | Where it lives | Role |
|---|---|---|---|
| **Authoring runtime** | Claude session in `mtn_research/` | macOS terminal / Claude Code | The agent that drives the cycle: queries DB, reads TRs, writes markdown, runs scripts, commits |
| **Memory** | `~/.claude/projects/.../memory/*.md` | per-Mac local | Claude's persistent project memory: workflow recipes (`scripts_workflow.md`), DB usage (`peak_db.md`), cell-coverage patterns (`cell_coverage_research.md`) |
| **Peak data — source of truth** | Supabase `peak_checklist` DB | Supabase cloud | 861 peaks + 591 ascents + 946 list memberships. Read-only here. |
| **Peak data — client** | `peak_db_client.py` | `~/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db/` (iCloud) | Stdlib-only Python module + the read key. Shared across all Claude projects. |
| **External research sources** | 14ers.com (TRs, GPX library, cell-reception DB, route descriptions) | public web | Pulled via Chrome MCP (for logged-in views) + curl (for public GPX files) |
| **External research sources** | CalTopo (interactive maps) | public web + private maps | Read existing maps via `fetch_caltopo.py`; write research maps via `gpx_to_caltopo.py` |
| **Repo (iCloud-synced)** | `Projects/mtn_research/` | iCloud Drive | Single source for code, docs, raw GPX, CalTopo dumps. Cross-Mac via iCloud sync. |
| **Tooling** | `scripts/*.py` | repo, in `scripts/` | uv inline-deps for portable scripts; stdlib for the simple ones |
| **Inputs (gitignored)** | `gpx/<slug>/`, `caltopo/<map_id>.json`, `notes/`, `scripts/cts.ini` | repo, gitignored | Personal data + credentials. Live only in iCloud. |
| **Outputs (versioned)** | `docs/peaks/<slug>.md`, `docs/maps/<slug>.png`, `mkdocs.yml`, `README.md` | repo, in git | The publishable artifacts. |
| **CI/CD** | `.github/workflows/deploy.yml` | repo | On push to `main`: mkdocs build → deploy to `gh-pages` |
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
│  │   ├─── ~/.claude/projects/<proj>/memory/                                 │ │
│  │   │       MEMORY.md → peak_db.md, cell_coverage_research.md,             │ │
│  │   │                   scripts_workflow.md                                │ │
│  │   │                                                                      │ │
│  │   ├─── Chrome MCP (Claude in Chrome extension, kyleg.knutson profile)   │ │
│  │   │       logged-in 14ers.com session for TRs, GPX library, etc.        │ │
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
     │  14ers.com     │   • 14ers.com (TRs, GPX,    │   CalTopo (maps,      │
     │  (curl + UA)   │      cell DB, routes)        │   caltopo_python API)  │
     │  ◀────────────│   • CalTopo public + private │ ─────────────────────▶ │
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
│   │ (Pillow+OSM tiles)  │ (caltopo_python)     │ (stdlib)                 │ │
│   ├─────────────────────┼──────────────────────┼──────────────────────────┤ │
│   │ gpx_to_caltopo      │ caltopo_to_gpx       │                          │ │
│   │ (caltopo_python)    │ (stdlib)             │                          │ │
│   └─────────────────────┴──────────────────────┴──────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │  git push origin main  (via gh auth)
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GitHub: kylegknutson/mtn-research                    │
│                                                                              │
│   ┌──────────────────────┐         ┌──────────────────────────────────────┐ │
│   │ main branch          │ ─────▶  │ GitHub Actions: deploy.yml           │ │
│   │ (markdown, PNGs,     │         │   - install mkdocs-material          │ │
│   │  scripts, mkdocs.yml)│         │   - mkdocs build                     │ │
│   └──────────────────────┘         │   - push site/ to gh-pages branch    │ │
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

1. **Kyle:** "Find me unclimbed Sangre 13ers under 4,000 ft / 8 mi."
2. **Claude reads memory** → knows to use `peak_db_client` (not Google Sheets), to pull TRs at the broad-research stage, to use the Chrome extension for logged-in features, to use uv-based scripts.
3. **DB query** via `peak_db_client.peaks(range="eq.Sangre de Cristo", ...)` and `ascents()` → list of candidates.
4. **TR pull** via Chrome MCP → narrows by route stats, access flags, recent conditions.
5. **Cell coverage check** via 14ers.com community DB URL pattern (memorized) → flagged "no data, use InReach."
6. **Deep dive for chosen peaks** → more TR reads, route GPX download via curl (no auth needed for public GPX), peak DB lookups for cluster context.
7. **Authoring** → `docs/peaks/<slug>.md` written by Claude. References interactive CalTopo map URL + overview PNG path.
8. **Map generation** → `scripts/make_overview_map.py <slug>` reads `gpx/<slug>/*.gpx`, calls OpenTopoMap tiles, writes `docs/maps/<slug>.png`.
9. **CalTopo research map** (optional, when GPX warrants it) → `scripts/gpx_to_caltopo.py --gpx-dir gpx/<slug> --new-map "Research: ..."` → returns shareable URL, pasted into the markdown.
10. **mkdocs.yml nav update** → add the new peak to the sidebar.
11. **Commit + push** via `gh`-authed `git push` → GitHub Actions runs → Pages updates in ~1 min.
12. **Result:** a public URL Kyle can open from his phone at the trailhead, plus a CalTopo map he can layer on his offline planning.

## What's reproducible vs. authoritative

| Artifact | Source of truth | Regeneratable? |
|---|---|---|
| `peaks` / `ascents` rows | Supabase (written by separate peak_checklist webapp) | No — owned upstream |
| Downloaded GPX in `gpx/<slug>/` | 14ers.com (publicly downloadable per-trip) | Yes — re-curl |
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
