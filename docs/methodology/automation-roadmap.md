# Automation roadmap

**Goal:** make report production more systematic — push the mechanical work into scripts so the LLM is used only for judgment, and approval/tool-call churn drops. Target outcome: one command does the data-gathering 80%, the LLM writes the narrative 20% and reviews.

This is a **spec, not yet built.** Capture of the plan so it's ready to implement.

---

## What's mechanical vs. judgment

From the Crestolita + Broken Hand session, the work split roughly:

| Mechanical (scriptable — no LLM) | Judgment (needs LLM) |
|---|---|
| Login-check all 3 sources, confirm usernames | Deciding a combo is a *real* pairing vs. coincidence |
| Resolve cross-site IDs (peak_db ↔ 14ers ↔ LoJ ↔ peakbagger) | Catching route errors (south ridge ≠ standard route) |
| Sweep TR lists from all 3 sources | Synthesizing route narrative from multiple TRs |
| Download every GPX (LoJ + 14ers lib + peakbagger) | Picking the recommended route + caveats |
| Compute combo distance/gain from exact-combo GPX | Cluster/combo framing, "what's left for this climber" |
| Query 14ers cell DB | Hazard/season judgment calls |
| Get drive time from home → TH (Maps) | Final prose + TL;DR |
| Build waypoint GPX, upload CalTopo, render PNG | Review of the auto-assembled facts |
| Emit a filled-in report skeleton | |

Most tool-call/approval volume is in the mechanical column.

---

## Proposed: `scripts/research_peak.py`

One command that does the mechanical 80% and emits a data-filled skeleton.

```
scripts/research_peak.py --peaks <id|slug>[,<id>...] [--climber kyle] [--flavor single|day|multi]
```

### Steps it automates
1. **Login verification** — hit each of the 3 sources, confirm the climber's username appears (wait past peakbagger Cloudflare). Hard-fail if any source is logged-out (per [source requirements](source-requirements.md)).
2. **ID resolution** — from peak_db, get summit coords/elev/class/range/ranked/climbed; follow LoJ → peakbagger cross-links; resolve 14ers peak IDs.
3. **Cluster analysis** — nearby unclimbed ranked 13ers+ within 8 mi, flagged same-drainage vs. different-drive.
4. **TR sweep** — list every TR per source with author/date/"additional peaks" (combo signal).
5. **GPX sweep** — download all tracks from all 3 sources to `gpx/<slug>/`, source-suffixed filenames.
6. **Stats** — compute distance/gain from the exact-combo (or standard-route) GPX tracks.
7. **Cell DB** — query 14ers community reception for each peak + primary TH.
8. **Drive time** — Maps directions from the climber's home address to the primary TH.
9. **Map build** — generate waypoint GPX, upload to CalTopo (`--no-dedupe`, source colors), capture map ID; render the PNG.
10. **Emit skeleton** — write `docs/peaks/<slug>.md` pre-filled with the report template: Quick Stats, drive row, weather link, map embed, TR tables (all 3 sources), GPX count, cell section, sources-checked footer — leaving narrative sections (recommended route, why-combined, conditions judgment, TL;DR) as clearly-marked `<!-- TODO: narrative -->` blocks.

### Then the LLM
- Reads the skeleton + the TR text it flags as route-relevant
- Writes/edits only the narrative + judgment sections
- Verifies the auto-assembled facts (catches route errors)
- Commits + pushes

### Output contract
- Idempotent: re-running refreshes data without clobbering hand-written narrative (narrative lives between sentinel markers the script won't overwrite).
- Prints a summary: sources confirmed, TR counts, GPX counts, map ID, PNG path, any gaps.

---

## Companion scripts (smaller, independently useful)

| Script | Does | Removes |
|---|---|---|
| `scripts/check_sources_login.py` | Confirms logged-in on all 3 sites; prints usernames | The manual login-check dance every session |
| `scripts/sweep_gpx.py <peakids>` | Downloads all GPX from all 3 sources for given peaks | The bespoke per-session GPX fetch code |
| `scripts/combo_stats.py <gpx...>` | Distance/gain/elev from track(s) | Inline python each time |
| `scripts/drive_time.py <lat,lon> [--climber]` | Maps drive time + directions URL from home | Manual Maps navigation |
| `scripts/narrow_down.py --criteria ...` | Runs a saved narrow-down query → `docs/lists/` | LLM doing peak_db filtering by hand |
| `scripts/scrape_14ers_checklist.py <url>` | Friend's climbed list from a 14ers checklist URL | (enables multi-climber) |

`research_peak.py` orchestrates the first four.

---

## Map QA tests (also reduces redo loops)

Pre-commit / CI checks on generated PNGs so distorted maps never publish (the recurring "redo the map" problem):

- **Aspect/extent sanity** — objective peak bbox occupies a reasonable fraction of the frame (not a dot, not clipped)
- **Track layer present** — at least one rendered LineString (catches the "only dots" failure)
- **Non-blank tiles** — basemap actually fetched (not the beige fallback)
- **Objective centered** — all peak markers within frame
- Optional: visual diff vs. a stored baseline per peak

Pair with the pending **multi-color PNG tracks** (color by source like the CalTopo map) — both live in `make_overview_map.py`.

---

## Sequencing (when we build it)

1. `check_sources_login.py` + `combo_stats.py` + `drive_time.py` — small, high-frequency, low-risk
2. `sweep_gpx.py` — consolidates the most repetitive scraping
3. `research_peak.py` — orchestrate the above + skeleton emit
4. Map QA tests + multi-color PNG
5. `narrow_down.py`, then `scrape_14ers_checklist.py` (multi-climber)

Each step independently cuts tool-call volume; `research_peak.py` is where the big LLM-usage/approval savings land.

*Last updated: 2026-05-31*
