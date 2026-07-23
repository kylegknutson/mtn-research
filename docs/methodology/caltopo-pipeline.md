# CalTopo + PNG map pipeline

**A report is not done until the CalTopo map AND the PNG overview are built and shipped with the markdown.** Maps and reports always go together.

Every report ships **three artifacts as one unit**:
1. `docs/peaks/<slug>.md` (or `docs/trips/<slug>.md`) — the markdown report
2. CalTopo research map (`https://caltopo.com/m/XXXXXXX`) — interactive, linked from the report header
3. `docs/maps/<slug>.png` — overview PNG embedded near the top of the report

## Fast path — kick off and walk away (preflight → build → publish)

The whole report build is designed around **two human touch points**: approve the flight-check at kickoff, approve the publish at the end. Everything in between runs without per-step permission prompts (the mechanical work lives inside allowlisted scripts, not raw Bash — no ad-hoc `mkdir`/`cp`/`rm`/heredocs).

**0. Preflight (the flight check) — one attended moment.**
```
scripts/preflight.py --peaks "Star, Taylor, Italian" --range Elk --climber kyle
```
Resolves the peaks → peak_db ids (flags ambiguous/unknown names *now*), checks CalTopo creds + climber profile, and prints the per-site **login indicators** to confirm in the Playwright-MCP browser. Confirm all 3 logins there (hard stop if any is out — see [source requirements](source-requirements.md)). Output: GO/NO-GO + the `objective_ids`.

**1. Sweep GPX in-chat (MCP browser), then file + scaffold.**
Sweep all 3 sources via the logged-in MCP browser (`browser_evaluate`, allowlisted), saving the fetched tracks to a JSON blob (the evaluate `filename`), then:
```
scripts/ingest_gpx.py     --slug <slug> --json <blob.json>     # files tracks → gpx/<slug>/
scripts/scaffold_report.py --slug <slug> --objective-ids 301,365,420 \
    --landmark "Mt Tilton Trail TH (end of CO 742)|38.9872|-106.7573|10750|trailhead" --no-nearby
```

**2. One command does all the mechanical build.**
```
scripts/build_report.py --slug <slug> --title "Star Peak Group" --climber kyle
```
Runs waypoints → your CalTopo cross-ref (tight 1 mi margin) → combo stats → drive time → overview PNG → **new CalTopo research map** → **regional-map sync**, then prints the `caltopo_id` / `regional_map_id` / PNG path / stats to drop into the report. (Re-run with `--caltopo-id <ID>` to append instead of making a duplicate map.)

**3. Write the prose.** The LLM fills `docs/peaks/<slug>.md` from the swept trip reports + the printed values (this is the only non-mechanical step).

**4. Finalize + publish.**
```
scripts/build_report.py --slug <slug> --finalize     # climber-status + index + HOME PEAK MAP + all QA gates
git add -A && git commit -m "..."                    # allowlisted
git push                                              # the ONE deliberate gate — review, then publish
```

> **Finalize always refreshes the home peak map.** `--finalize` runs `gen_peak_map.py`, which re-reads peak_db + the climb log and rewrites `docs/data/peaks.json` so the new (or edited) report's objective peaks turn **green** on the home/`/peak-map/` map. **This is not optional** — any time a report is added *or its `objective_ids` / `peak_ids` change* (e.g. adding a peak to an existing report), run `--finalize` (or `scripts/gen_peak_map.py` directly) and commit the updated `docs/data/peaks.json`, or the map will be stale. A peak only counts as "reported" via a report's `gpx/<slug>/peaks.yml` `objective_ids` (or the frontmatter `peak_ids:` fallback).

The detailed per-step reference is below; the fast path just chains it.

> **Only summiting tracks belong on a report's map (Kyle, 2026-06-08).** A track goes on the PNG and the CalTopo map **only if it actually summits one of the researched (objective) peaks** — within ~240 m of an `objective_ids` summit. A track that merely passes through the area (an adjacent peak's route, an approach-only fragment, another day of a trip) is **not** route beta and must be left off. This is enforced automatically now: `caltopo_mytracks.py` drops non-summiting tracks at collection, and `make_overview_map.py` re-applies the filter at render. To clean a map built before this rule, use **`scripts/prune_caltopo_tracks.py --slug <slug>`** (dry-run) then `--apply` — it deletes line features that don't top out on an objective (markers/folders untouched). Pass `--objective-ids` for older reports whose `peaks.yml` predates the field.

---

## Pipeline

### 1. Build waypoint GPX
`scripts/build_peak_gpx.py --slug <slug>` reads `gpx/<slug>/peaks.yml` and writes `<slug>_peaks_only.gpx` (objective summit(s) `sym=peak` + optionally nearby unclimbed ranked 13er+ neighbors, with an `exclude` list for different-drive peaks — the Bartlett rule) and `<slug>_landmarks.gpx` (trailheads + key drive-in landmarks: gates, closed roads, seasonal closures). Summit/neighbor coords come from peak_db; TH/landmark coords are hand-researched in the config. **`peaks.yml` is the one tracked-in-git file under `gpx/`** (everything else there is gitignored derived/bulk data).

### 2. Download GPX tracks from ALL THREE sources
**Primary path: sweep all three sources in-chat via the MCP browser** (it's the login
source of truth and the only thing that clears peakbagger's Cloudflare check — see
CLAUDE.md). **Optional headless convenience: `scripts/sweep_gpx.py --slug <slug>`** for
the LoJ + 14ers portion only — it resolves cross-site IDs from peak_db, pulls every GPX,
dedupes by content hash, and writes a **`tr_manifest.md`** listing the *named* trip
reports per source. Do **not** rely on it (or `check_sources_login.py --login`) for
peakbagger: Cloudflare permanently blocks the automation profile (it detects the
webdriver/CDP connection regardless of Chrome binary — re-confirmed 2026-06-16), so
peakbagger is always pulled in-chat via the MCP browser.

Not just LoJ. *"Always download the tracks from all sites not just LoJ. That's an important part of the research, finding all GPX files out there and pulling them together into one map."* (Kyle, 2026-05-29)

- **LoJ**: `/gpx/<id>.gpx` per trip report — pull every TR's GPX, each has route variations
- **14ers.com**: per-peak GPX library (`gpxlib_locator.php?peakid=<id>`) covering TR uploads + member uploads + official routes; plus per-route official GPX
- **peakbagger**: per-ascent GPX (`/climber/GPXFile.aspx?aid=<aid>&sep=1`) — **confirm logged in first** (see [source requirements](source-requirements.md))

Filename convention (keeps colors/groups distinct on upload):
```
<slug>_<author>_<year>_loj<trId>.gpx
<slug>_<author>_<year>_14ersTR<id>.gpx
<slug>_<author>_<year>_14ersGPXlib<id>.gpx
<slug>_<author>_<year>_pbAscent<aid>.gpx
```
Over-pulling is fine — the upload script dedupes identical tracks. Better to grab everything than miss a route variation.

### 2b. Cross-reference KYLE'S OWN CalTopo maps (required)
**Requirement (Kyle, 2026-06-03):** *"There are missing tracks… you did not cross reference my own caltopo maps. Always look there also when building the report-specific maps."* The three web sources are not enough — Kyle's CalTopo account holds his **recorded GPS tracks + collected archive** with on-the-ground beta the web misses. Those live in the **per-range "GPS Tracks — <Region>" regional maps** (the canonical archive — use these, not the big "All"/`C105AEV` map, which Kyle may delete; everything in it also lives in the regionals).

```
scripts/fetch_caltopo.py --map <REGIONAL_ID>    # refresh the range's regional map (auto-picked)
scripts/caltopo_mytracks.py --slug <slug>       # add his tracks in the report's bbox
```

`caltopo_mytracks.py` resolves the regional map from the peak's `range` (peak_db), computes the bbox from `<slug>_peaks_only.gpx` (+ margin), scans that regional dump for LineStrings inside it, and writes the ones **not already collected** (geometry-deduped against the web sweep; running/biking activity tracks skipped by title) as `<slug>_caltopo_<mapid>_<name>.gpx`. Upload these to the research map in a distinct color (purple `#9933CC`) so his own tracks are visible vs. the web sources. Sanity-check the result — a stray far-away track can clip a generous bbox (drop it).

### 3. Upload to CalTopo
```
scripts/gpx_to_caltopo.py --gpx-dir gpx/<slug> --new-map "Research: <Peak>" --no-dedupe
```
`--no-dedupe` is required for research maps so summit/peak markers always render even if they exist in other maps. **Track colors (Kyle, 2026-07-23):** magenta `#E6008C` is RESERVED for the recommended route; blue `#0066FF` is RESERVED for Kyle's own recordings. Every other source track (recorded + OSM trail) gets a distinct color from a palette of safe hues (greens/oranges/purples/teals/yellows — NO magenta/pink/red/blue), assigned **per-track** via `gpx_to_caltopo.track_color(i)`, which shifts lightness in tiers past the 8 base hues so >8 tracks stay distinct. There is NO fixed source→color convention anymore. An import-time guard rejects any palette color near magenta/red/blue. Capture the returned map ID.

### 3b. Also add the new tracks to the REGIONAL map
**Requirement (Kyle, 2026-06):** every external GPX track pulled during research goes into **two** CalTopo maps — the per-research map (above) *and* the **regional map** for the range those peaks sit in. The per-research map is the focused working view; the regional map is the durable, cumulative archive of every track for that range, built up over time across all research sessions.

```
scripts/gpx_to_caltopo.py --gpx-dir gpx/<slug> --map-id <REGIONAL_MAP_ID>
```

- Append to the existing regional map (`--map-id`, not `--new-map`).
- **Leave dedupe ON** here (omit `--no-dedupe`) — the regional map accumulates many peaks, so duplicate tracks/markers already present should be skipped. Only the per-research map needs `--no-dedupe` (so its own summit markers always render).
- Pick the regional map by the peaks' `range` field in peak_db (Sangre de Cristo, Sawatch, San Juan, Elk, Gore, Mosquito, Tenmile, etc.).
- For a multi-range objective, add to each relevant regional map.

#### Regional map registry
Regional maps follow the **"GPS Tracks — <Range>"** naming on CalTopo. Get the current list any time with `scripts/fetch_caltopo.py --list` (authoritative — don't rely on local `caltopo/*.json` dumps, which go stale after a re-render).

| Range | Regional map | CalTopo ID |
|---|---|---|
| Sangre de Cristo | GPS Tracks — Sangre De Cristo | `VKGB00L` |
| Sawatch | GPS Tracks — Sawatch | `L5VH4BU` |
| San Juan | GPS Tracks — San Juan | `06AR6BF` |
| Elk | GPS Tracks — Elk | `1G2G7DM` |
| Gore | GPS Tracks — Gore | `6E4GJV2` |
| Mosquito | GPS Tracks — Mosquito | `LECF68J` |
| Tenmile | GPS Tracks — Tenmile | `7QE01UK` |
| Front | GPS Tracks — Front | `DLES5CC` |
| Weminuche | GPS Tracks — Weminuche | `7AQN6TS` |

(Also non-CO archives: Washington, California, Nevada, Arizona, Utah, Oregon, Wyoming, Maine, NH, VT, NY, MA, Hawaii, Europe — same naming.)

**Coordination note:** these regional maps are maintained/re-rendered in a separate workflow. If another session is actively re-rendering one, **hold off** writing to it until that finishes (a concurrent append can be lost or conflict). Re-fetch with `fetch_caltopo.py --map <ID>` before deduping against it so the local snapshot is current.

### 4. Wire the map ID into the report
Update the header `**CalTopo research map:**` line and the caption `*[Interactive CalTopo map](https://caltopo.com/m/<id>)*`.

### 5. Render the PNG
```
scripts/make_overview_map.py <slug> --title "<Peak>"
```
Auto-renders track lines on OpenTopoMap tiles.

### 6. Commit, push, verify deploy green
Do NOT mark a peak "researched" or update the index until all three artifacts are committed and the GitHub Pages deploy succeeds.

## Imported-GPX marker handling — strip summits, gray the rest
**Requirement (Kyle, 2026-06):** trip-report GPX files arrive with their *own* embedded waypoints (the author's summit pins, camps, trailheads, junctions, water, random marks). These must not be uploaded as-is — they duplicate and clash with the climber's authoritative markers and clutter the map. On import:

1. **Summit markers → DROP, use mine.** Any imported waypoint at/near a known summit (matches a `peaks_only.gpx` summit by name, or within ~75 m of one) is discarded. The objective summits are added from `peaks_only.gpx` as **neon-green mountain markers — `symbol=peak`, `color=#39FF14`** (the canonical summit scheme on the regional maps). Dedupe ON, so they're added only if not already present.
2. **All other imported markers → GRAY — `symbol=point`, `color=#9E9E9E`.** They stay on the map as useful context (camps, junctions, the TR author's trailhead) but are visually subordinated to the summit pins.
3. The **tracks** themselves are unaffected — kept and colored per-track from the safe palette (no magenta/pink/red/blue; magenta reserved for the recommended route, blue for Kyle's recordings). To re-apply the current palette to an existing map without a full rebuild, use **`scripts/recolor_map_tracks.py <slug>`** (edits strokes in place — same map ID, no frontmatter/repo churn, idempotent). `scripts/check_caltopo_complete.py` verifies a map still has all its recommended routes + source tracks.

Net effect: one clean set of **neon-green summit pins** + a quiet **gray** wash of secondary author waypoints, with the source-colored route lines on top.

**Exact marker scheme (matches the regional maps):**

| Marker kind | `symbol` | `color` |
|---|---|---|
| Objective summit | `peak` | `#39FF14` (neon green) |
| **Context summit** — other named/ranked peak in the PNG frame (Kyle, 2026-07-12) | `peak` | `#000000` (black) |
| **Trailhead** (peaks.yml `kind: trailhead`) | **`hiking`** (CalTopo blue hiker w/ pack) | **`#0066FF`** (blue) |
| Any other imported waypoint | `point` | `#9E9E9E` (gray) |

The overview PNG uses the same convention — green mountain icons for objectives, black
for other named/ranked summits in view — so PNG and CalTopo read identically.

> **Marker names + trailhead symbol (Kyle, 2026-06-15).** Summit marker titles are **just the peak name** — no `(13,118', Class 2, UNCLIMBED)` suffix (that lives in the report). `build_peak_gpx.py` writes name-only summits and tags `kind: trailhead` landmarks with `<sym>hiking</sym>`; `gpx_to_caltopo.py` honors each waypoint's `<sym>` (trailheads → the blue `hiking` icon). To restyle maps built before this: **`scripts/retro_restyle_markers.py`** (dry-run) then `--apply` — strips verbose summit titles and switches coord-matched trailheads to `hiking`/`#0066FF`. (Unknown CalTopo symbol codes fall back to an empty circle — `hiking` is the verified hiker-with-backpack code, not `trailhead`/`hiker`.)

**Track color convention:**

| Source | Color |
|---|---|
| LoJ trip reports | `#FF0000` red |
| 14ers.com | `#00AA00` green |
| Peakbagger | `#0066FF` blue |
| Personal recordings (Kyle's GPS) | `#9933CC` purple — cycles per-track for multi-track GPX |

> **Summit-marker dedup gotcha (Kyle, 2026-06-09):** `gpx_to_caltopo.py` dedupes
> markers **account-wide** (it loads the `caltopo/*.json` regional dumps and skips
> any marker within ~25 m of an existing one). So when a per-report research map is
> built *after* the objective already exists on its regional map, the report map's
> summit markers get **silently skipped** — the map ends up with trailhead/POI
> markers but **no green summit peaks**. (Surfaced on the Trinchera group: its map had
> only the Blue Lakes TH marker.) The PNG is unaffected — `make_overview_map.py`
> draws `peaks_only.gpx` directly.
> - **In the pipeline:** `build_report.py` runs `fix_summit_markers.py --slug <slug>
>   --map-id <new id> --apply` after the CalTopo upload — research maps always carry
>   green objectives + black context summits. `share_report.py` runs the same for
>   each new share map.
> - **Repairing an existing map:** `scripts/fix_summit_markers.py --slug <slug>`
>   (dry-run) / `--apply`, or `--all --apply` for every report, or `--map-id` for an
>   arbitrary map (share maps). Idempotent: deletes any marker within ~120 m of a
>   target summit, then re-adds one `peak`/`#39FF14` marker per objective (from
>   `peaks_only.gpx`) and one `peak`/`#000000` per context summit (from the
>   `context_peaks` list in `docs/maps/<slug>.extent.json` — the PNG build is the
>   single source of "what's in view"). Objectives = peaks.yml `objective_ids` +
>   `pass_over_summits`. Skips reports lacking a `peaks.yml` or `caltopo_id`.
>
> **Implementation:**
> - **New uploads:** `scripts/sync_to_regional.py` enforces the marker scheme (reuses `gpx_to_caltopo.py --marker-symbol`, default `point`).
> - **Personal activity ingestion:** `scripts/ingest_activity.py` auto-classifies by region and applies the same marker rules; tracks cycle through the 13-color palette starting at purple.
> - **Normalizing existing maps:** `scripts/restyle_markers.py` rewrites every marker on a map in place via `editFeature` — summit-named or summit-located markers → `peak`/`#39FF14`, everything else → `point`/gray. Also renames markers to the canonical peak name when known. Run with `--poi-color "#9E9E9E"` to match the regional gray.
>   ```
>   scripts/restyle_markers.py --export /tmp/peakdb_summits.gpx --map <ID> --poi-color "#9E9E9E" --apply
>   ```
> - All regional maps were normalized to the prior blue scheme on 2026-06-02; re-run `restyle_markers.py --apply` to update to neon green.

## Map waypoint scope — objective only

- **Include**: the summit(s), trailhead(s), key drive-in landmarks, and nearby unclimbed ranked 13ers+ that are *plausibly same-outing* (same drainage / ridge-connected / shared approach).
- **Exclude**: nearby peaks reached from a *different drive entirely* (opposite side of a pass/mine/wilderness boundary). Mention them in the report's cluster text if relevant, but they don't belong as map markers.
- Origin of this rule: putting Bartlett Mtn (across Climax Mine, a different drive) on the Jacque/Pennsylvania maps was noise. *"Why are you making a map for Bartlett?"* (Kyle, 2026-05-29)

## PNG framing — avoid distortion / over-zoom

The recurring failure mode: distant tracks (a TR where the peak was a minor add to another range's day, a mega-traverse, a long sub-13k outback) drag the bbox out and shrink the actual peaks to dots.

`make_overview_map.py` handles this by sizing the bbox around the **objective peak-marker bounding box + a ~1.5 mi margin** (auto-sizing: tight for one peak, spanning for a combo; floored and capped). Tracks that wander far render off-canvas — that wider context lives on the interactive CalTopo map, not the PNG.

If a PNG comes out distorted or over-zoomed, the fix is in `make_overview_map.py`'s bbox logic, **not** the GPX inputs.

## PNG context summits — every ranked peak in view gets a marker

The PNG marks **every ranked 13er/14er that falls inside the frame**, not just the
report's objectives (Kyle, 2026-06-09) — matching the CalTopo regional maps, which
carry all ranked summits.

- **Objective summits** (from `peaks_only.gpx`): **gold** star, always labeled.
- **Other ranked summits in view** (queried from peak_db *after* the bbox is fixed, so
  they never expand the frame): **silver-gray** star. To avoid label soup in dense or
  oversized frames, only the **nearest ~12 to the objective** are labeled; the rest get
  just a star (`MAX_CONTEXT_LABELS` in `make_overview_map.py`).
- Disable with `--no-context-summits` if a particular map needs to stay minimal.

> Note: a frame that pulls in *dozens* of ranked summits (e.g. crestolita_broken_hand
> caught 62) is usually a symptom of an **oversized bbox** — a long in-scope track
> dragging the extent — not a context-summit problem. Tighten the bbox, don't disable
> context summits.

> **Pending feature:** PNG track lines are currently all rendered red. Target is to color them by source (LoJ/14ers/peakbagger) like the CalTopo map, and to add automated map-QA tests (distortion / missing-track / blank-tile / aspect-ratio checks) that gate deploys.

## Syncing Kyle's recorded climbs onto the research maps

The separate **peak_checklist** project auto-syncs Kyle's Garmin climbs and drops each
as `gpx/<slug>/_kyle_existing/<peaks> YYYY-MM-DD_actual.gpx`. mtn_research owns getting
those onto the slug's CalTopo research map + report PNG via
**`scripts/sync_kyle_recordings.py`** (peak_checklist's `phase12_pipeline.sh` calls it
as its last step). It is ledger-gated (`.caltopo_sync_ledger.json`, gitignored — a clean
no-op when nothing is new), `--dry-run`-able, soft-fails per slug, and auto commits+pushes
the tracked artifacts (peaks.yml + PNGs; the GPX ride iCloud, gitignored).

**Map resolution is duplicate-safe** — a rebuild must never orphan a duplicate (see the
no-duplicate-maps hard rule). For each slug with new `*_actual*.gpx`:
1. `gpx/<slug>/peaks.yml` `caltopo_map_id` → append the recording to it;
2. else the report's frontmatter `caltopo_id` (the existing research map) → append to it,
   and **backfill** `caltopo_map_id` into peaks.yml;
3. else → create a new map over `--gpx-dir gpx/<slug>`, capture the id, write it to peaks.yml.

`caltopo_map_id` (peaks.yml) is the **same** map as the report's `caltopo_id` — it lives in
peaks.yml so the sync (which reads peaks.yml, not the `.md`) can find it. `delete_caltopo_map.py`
and `audit_caltopo_maps.py` scan it too, so a sync-managed map isn't flagged orphaned.

**Color / marker conventions on research maps:**
- **Kyle's recordings (`_kyle_existing/`): blue `#0066FF`** — `gpx_to_caltopo.py` forces
  `KYLE_COLOR` for these files (matches the PNG `COLOR_KYLE`). Fix any pre-convention
  recordings in place with `scripts/recolor_kyle_tracks.py --all --apply` (matches a recording
  by the filename date in its on-map title, or its `<trk><name>`). NOTE: gpx_to_caltopo titles
  these tracks from the **filename** (`<peaks> (<date>)`), not the GPX `<trk><name>`.
- **Objective summits: green `#39FF14` `peak` symbol, ALL objectives** (not climbed-only —
  climbed reads from the blue recorded track passing through). build_report sets this; sync's
  create-path re-applies it. `restyle_markers.py` is **regional-only** (its default is also
  `#39FF14`).
- **Recommended routes: magenta `#E6008C`**; fix stragglers with `scripts/recolor_recommended.py`.
