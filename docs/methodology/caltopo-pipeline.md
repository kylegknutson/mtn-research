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
scripts/build_report.py --slug <slug> --finalize     # climber-status + index + all QA gates
git add -A && git commit -m "..."                    # allowlisted
git push                                              # the ONE deliberate gate — review, then publish
```

The detailed per-step reference is below; the fast path just chains it.

> **Only summiting tracks belong on a report's map (Kyle, 2026-06-08).** A track goes on the PNG and the CalTopo map **only if it actually summits one of the researched (objective) peaks** — within ~240 m of an `objective_ids` summit. A track that merely passes through the area (an adjacent peak's route, an approach-only fragment, another day of a trip) is **not** route beta and must be left off. This is enforced automatically now: `caltopo_mytracks.py` drops non-summiting tracks at collection, and `make_overview_map.py` re-applies the filter at render. To clean a map built before this rule, use **`scripts/prune_caltopo_tracks.py --slug <slug>`** (dry-run) then `--apply` — it deletes line features that don't top out on an objective (markers/folders untouched). Pass `--objective-ids` for older reports whose `peaks.yml` predates the field.

---

## Pipeline

### 1. Build waypoint GPX
`scripts/build_peak_gpx.py --slug <slug>` reads `gpx/<slug>/peaks.yml` and writes `<slug>_peaks_only.gpx` (objective summit(s) `sym=peak` + optionally nearby unclimbed ranked 13er+ neighbors, with an `exclude` list for different-drive peaks — the Bartlett rule) and `<slug>_landmarks.gpx` (trailheads + key drive-in landmarks: gates, closed roads, seasonal closures). Summit/neighbor coords come from peak_db; TH/landmark coords are hand-researched in the config. **`peaks.yml` is the one tracked-in-git file under `gpx/`** (everything else there is gitignored derived/bulk data).

### 2. Download GPX tracks from ALL THREE sources
**Preferred: `scripts/sweep_gpx.py --slug <slug>`** — one command sweeps all three sources (resolves cross-site IDs from peak_db, pulls every GPX, dedupes by content hash) and writes a **`tr_manifest.md`** listing the *named* trip reports per source (so 14ers TRs are always enumerated, not just the GPX library). Needs the one-time automation-profile login (`check_sources_login.py --login`); falls back to a `--headed` run if peakbagger's Cloudflare blocks the headless pull. If the profile isn't set up, do the sweep in-chat via the MCP browser using the same endpoints below. **Reality (2026-06-03):** LoJ + 14ers sweep cleanly headless; peakbagger's Cloudflare blocks the automation profile (it detects the webdriver/CDP connection regardless of Chrome binary), so `sweep_gpx.py` does LoJ + 14ers autonomously and warns that **peakbagger is pulled in-chat** via the MCP browser. PB is consistently the smallest / most-duplicate GPX source, so this hybrid keeps ~all the value.

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
`--no-dedupe` is required for research maps so summit/peak markers always render even if they exist in other maps. Color by source: LoJ red (palette default), 14ers green (`#00AA00`), peakbagger blue (`#0066FF`). Capture the returned map ID.

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
3. The **tracks** themselves are unaffected — still kept and colored by source (LoJ red `#FF0000` / 14ers green `#00AA00` / peakbagger blue `#0066FF` / personal purple `#9933CC`).

Net effect: one clean set of **neon-green summit pins** + a quiet **gray** wash of secondary author waypoints, with the source-colored route lines on top.

**Exact marker scheme (matches the regional maps):**

| Marker kind | `symbol` | `color` |
|---|---|---|
| Objective summit | `peak` | `#39FF14` (neon green) |
| Any other imported waypoint | `point` | `#9E9E9E` (gray) |

**Track color convention:**

| Source | Color |
|---|---|
| LoJ trip reports | `#FF0000` red |
| 14ers.com | `#00AA00` green |
| Peakbagger | `#0066FF` blue |
| Personal recordings (Kyle's GPS) | `#9933CC` purple — cycles per-track for multi-track GPX |

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

> **Pending feature:** PNG track lines are currently all rendered red. Target is to color them by source (LoJ/14ers/peakbagger) like the CalTopo map, and to add automated map-QA tests (distortion / missing-track / blank-tile / aspect-ratio checks) that gate deploys.
