# Source requirements

**Multiple sources is a hard requirement.** If all three sources weren't confirmed logged-in and checked, the research isn't valid — redo it.

> **CLASS IS SAFETY-CRITICAL — research the actual route, not the summit (Kyle, 2026-06-16).** An under-stated class drives wrong gear/rope/helmet decisions. peak_db's `yds_class` is the **per-summit STANDARD-route** grade ONLY — it does **not** describe the recommended route when that route is a traverse, ridge link-up, loop, or any non-standard line, and **connecting ridges are routinely 1–2 classes harder than either summit's standard route** (Mount Adams trio: Class 2 summits, Class 3–4 ridges; Cimarron PT 13,222 B is peak_db Class 4 while the other PTs are Class 2). For every report: pull the real route grade from **14ers route descriptions + trip reports + Roach's *Colorado Thirteeners* + climb13ers**, and set the headline class to the **hardest move on the recommended route**. **When sources disagree or the link-up grade is unstated, take the harder estimate and say so.** Enforced by `scripts/check_class.py --strict` in `build_report.py --finalize` (FAILs any report whose class is below its hardest objective's peak_db summit class).

> **ALWAYS all three — on EVERY question, not just report builds (Kyle, 2026-06-09):** 14ers.com + listsofjohn.com + peakbagger.com get checked every time, including quick/informational/one-off questions (access, ownership, conditions, "which peaks are X"). Do **not** shortcut to one or two sources because a question feels small. Origin: answered a Cielo Vista / private-land question from only 14ers + LoJ and skipped peakbagger — whose **"Ownership / Land"** field was the most on-point data (it stamps Purgatoire Peak "Private Land," confirms the northern Culebra peaks as "Pike & San Isabel NF").
>
> **For general/informational questions, also go beyond the three (Kyle, 2026-06-09):** for land ownership, ranch boundaries, access/permits, regulations, history, etc., pull in relevant outside web sources too — the landowner's own site (e.g. Cielo Vista Ranch), CPW / USFS, climbing forums, SummitPost — via WebSearch/WebFetch, **in addition to** the three core sites. The three are necessary, not always sufficient.

> **HARD STOP on a logged-out source (Kyle, 2026-06-03):** if at any point you find a required source (14ers / LoJ / peakbagger) is **not logged in**, **stop right there and prompt Kyle to log in.** Do **not** build the report from the remaining sources and patch peakbagger later — a missing source means rebuilding the GPX collection, CalTopo map, and PNG once the data arrives, which wastes the whole pipeline. Pause, ask, wait for confirmation, then continue. (Supersedes the earlier "warn and continue / PB-in-chat" degrade-gracefully behavior.)

## The sources

The three logged-in core sources, checked **every time**:

| Source | Login (Kyle) | What it's good for |
|---|---|---|
| **14ers.com** | "letsgocu" | Route descriptions (when they exist), trip reports, per-peak GPX library |
| **listsofjohn.com** | "letsgocu" | Peak stats (LiDAR elev, prominence, saddle), TRs with "Additional Peaks" header (combo detection), per-TR GPX |
| **peakbagger.com** | "Kyle Knutson" | Ascent records with structured gain/distance/trailhead, ascent GPX tracks; **"Ownership / Land"** field (NF vs "Private Land") |

> **climb13ers.com — ALWAYS consult for any Colorado peak (Kyle, 2026-06-09):** for CO peaks it's a **required 4th source**, not optional. It's the canonical 13er-focused authority and often carries the access/trailhead/private-land detail the three core sites lack — e.g. its Cielo Vista trailhead page is what definitively resolved which Culebra-Range 13ers are on the ranch vs. public, and the Whiskey-Pass / Mariquita boundary. No login needed, **but it bot-blocks WebFetch/curl (HTTP 403) → fetch it via the browser MCP** (Playwright), per [[feedback-browser-tools]]. (Its companion `climb14ers`/route pages apply for 14ers.)

| Source | Login | What it's good for |
|---|---|---|
| **climb13ers.com** | none (browser MCP only) | CO 13er route beta, trailhead + **access/ownership** detail, driving directions; required for every CO peak |

## Login verification — do this FIRST, every session

> **The MCP browser is the only authoritative login check (Kyle, 2026-06-16).** GPX sweeps run through the **Playwright-MCP browser**, so its login state is the only one that matters. `scripts/check_sources_login.py` checks a **separate, standalone Playwright profile** that routinely diverges — it false-flagged peakbagger as "logged out" while the MCP browser was logged in as Kyle, triggering a pointless "please log in" prompt. **Never prompt Kyle to log in based on `check_sources_login.py`.** Verify in the MCP browser itself (or just let the first sweep prove it). Equivalently: **don't pre-gate on a separate login check — start the sweep; if a fetch returns a login page instead of data, *then* the MCP session is logged out and you prompt.** The hard-stop below applies only to a genuinely logged-out **MCP** session / sweep.

1. In the **MCP browser**, navigate to each site and confirm the logged-in username appears (or skip ahead and let the first GPX fetch confirm it — logged-out returns an HTML login page, not GPX).
2. **peakbagger especially:** it sits behind Cloudflare. A pull run before the "Just a moment" challenge clears (~4s) — or on an expired session — silently returns **logged-out** data, which exposes **fewer ascents and fewer GPX tracks**.
   - Real example (Crestolita + Broken Hand, 2026-05-31): a logged-out PB pull got 3 GPX tracks; re-running confirmed-logged-in surfaced **5 more** Broken Hand ascent tracks.
   - Always confirm `Logged in: Kyle Knutson` on the peakbagger page before scraping. Re-pull if the first check shows logged-out.
3. If 14ers.com can't be reached at all (e.g. Chrome extension allowlist bug), **HALT** — see [the no-14ers rule](#halt-conditions).

## What to pull per peak

- **14ers.com**: peak page (`?t=tripreports`), `/php14ers/tripmain.php` TR search (POST with `peakn=<id>`), per-peak GPX library (`/php14ers/gpxlib_locator.php?peakid=<id>` → `/php14ers/download.php?type=gpxlibrary&file=<path>`), official route GPX from route pages
- **listsofjohn.com**: `/peak/<lojId>` → TR list → `/tr?Id=<trId>&pkid=<lojId>`; GPX at `/gpx/<id>.gpx`
- **peakbagger.com**: `/peak.aspx?pid=<pid>` → ascent list → ascent GPX at `/climber/GPXFile.aspx?aid=<aid>&sep=1`

## Synthesize, don't single-source

Cross-reference gain/distance across multiple TRs. A peak's "standard route gain" should be consistent across several reports. Don't quote one TR's number as gospel.

## Distance/gain headlines come from MEASURED GPX, never climb13ers prose (Kyle, 2026-06-10)

climb13ers mileage/gain is an **author's estimate drawn on a map** — their own pages say *"Route shown is an approximation. Not intended for use as a GPX track."* Treat it like any single estimate:

- **Headline distance/gain must be derived from recorded GPX** (14ers / LoJ / peakbagger tracks) or the composed recommended route — *not* lifted from climb13ers. climb13ers is for class, conditions, trailhead/access, and route narrative.
- When you do cite a climb13ers number, **label it "(climb13ers estimate)"** and sanity-check it against the recorded tracks. If it's well below the shortest recorded line, say so.
- **GPS *elevation* is garbage; gain must come from a DEM, not the GPX `<ele>`.** Barometric drift makes these 14ers-library tracks log 37,000' of "gain" and 14,000' summits on 13ers. **Distance from GPX is reliable; gain from GPX is not.** Resample a terrain model (DEM) along the route instead — `build_recommended_route.py` does this automatically (USGS 10 m via opentopodata, ~6 m/20 ft accumulation threshold) and lands within ~1% of CalTopo's gain. Don't quote GPS-`<ele>` gain, and don't trust climb13ers' gain either. (The Baldy Lejos saga: climb13ers' "2,630'" became the headline, then a raw-GPS number said "4,500'", then a smoothed-GPS number said "2,600'" — all wrong; the **DEM truth, confirmed on CalTopo, is ~3,600'.**)

**Tools that enforce/serve this:**
- `scripts/build_recommended_route.py <slug>` — composes the **shortest route through only the ranked objectives** from the real source tracks (add-on peaks trimmed automatically), reports distance, and **measures gain from a DEM** (matches CalTopo; `--no-dem` falls back to noisy GPS). By default it uses a **pooled-track graph router** that can splice part of one party's line onto another's where they cross (either direction — a recorded *ascent* line is a valid *descent*), finding the true shortest real-ground loop; `--legs` selects the older per-leg/whole-track method. Output `gpx/<slug>/<slug>_recommended.gpx` renders in the standardized **bold-magenta "recommended route (composed)"** style on the overview map.
- `scripts/check_route_stats.py [--strict]` — audits every report's `gain:` headline against its recorded-track range; flags climb13ers-sourced headlines and any mileage shorter than the shortest recorded track. Run it before finalizing.

### Build the recommended route right (do this WHILE building the report) — Kyle, 2026-06-11

A batch run across existing reports showed that `build_recommended_route.py` only
produces trustworthy numbers when three inputs are clean. **Set these up as you
build each report, not after** — retrofitting is the painful path:

1. **`peaks.yml` `objective_ids` = ONLY the report's actual ranked objectives.**
   Don't let it carry the whole range. Failures we hit: `powell_eagles_nest`'s
   `peaks_only` held the entire 13-peak Gore traverse; `homestake` carried a stray
   "Savage Pk" 8 km away. Keep `nearby.include: false` unless the report really is
   that group, and don't pad `extra_summits`. (A bloated set also explodes the
   route: >8 objectives falls back to a nearest-neighbor tour, not the optimum.)
2. **Mark the real start `kind: trailhead`; passes/saddles are `kind: landmark`.**
   `--start auto` picks the highest-elevation `kind: trailhead`. If a pass is
   mistakenly a trailhead (or the only "trailhead" is a high saddle), the route
   starts mid-mountain and undercounts (e.g. it grabbed *Broken Hand Pass* as the
   start for crestolita). The generated `*_landmarks.gpx` flattens `kind`, so the
   peaks.yml is the source of truth here.
3. **The swept tracks must match that trailhead's approach.** If the GPX library
   tracks come from a different drainage, every objective/start "snaps" far from
   the nearest track and the loop is fiction (jacque snapped 5 km, crestolita
   0.9 km). 

**Verification (must pass before trusting the numbers):** run
`build_recommended_route.py <slug>` and check the output has **no `WARN: … snaps
… m`** lines (start + every objective within ~250 m of a real track) and that the
distance/gain are **sane vs. the recorded-track range**. If it warns or the loop
is wildly off (e.g. 22 mi for a peak documented as a ~4-mile day), the inputs are
wrong — fix the objective set / trailhead, don't publish the number. Then copy
the DEM distance/gain into the structured stat frontmatter (`dist_mi`, `gain_ft`)
and push the magenta route to the CalTopo map. For multi-trailhead trips (peaks
at *different* THs, like a car-camp weekend) **don't** auto-route one loop — set
`days_detail` and let `dist_mi`/`gain_ft` be the per-day sum.

## The "Sources checked" footer

**Every report must end with a line naming all sites checked + the confirmed logged-in username** (and **climb13ers.com for any CO peak**), e.g.:

> **Sources checked:** 14ers.com ✓ (logged in, "letsgocu") · listsofjohn.com ✓ (logged in, "letsgocu") · peakbagger.com ✓ (logged in, "Kyle Knutson") · climb13ers.com ✓

If any source isn't confirmed logged-in, the footer must say so, and the research is flagged incomplete.

## Halt conditions

- **No 14ers.com access** → halt and tell the climber. Don't substitute web-search snippets, climb13ers alone, or your own knowledge. The verification step (14ers TRs + GPX) is what makes the research trustworthy; without it the answer is plausible but unverified.

## What NOT to do

- Don't conclude "no 14ers route description = no data" — TRs and GPX are still data.
- Don't substitute web search snippets or general knowledge for the three sources.
- Don't pause to ask for direction every time a route description is missing — that's expected; dig into TRs instead.

## Checking login reliably (Kyle, 2026-06-09)

Visible "log in / log out" **text** is unreliable — it renders differently per page and false-negatives (this cost a wasted hard-stop). Check a **personalized element via same-origin fetch** instead (cross-origin fetch fails, so be on that site's origin):

- **14ers.com** — fetch `https://www.14ers.com/`; logged in iff an `<a href>` matches `ucp.php?mode=logout` (secondary: username, e.g. "Basin", in the HTML).
- **listsofjohn.com** — fetch any peak page (e.g. `/peak/468`); logged in iff the text **"log in to view ascents" is ABSENT** (it only renders when logged out).
- **peakbagger.com** — fetch `https://peakbagger.com/Default.aspx`; logged in iff an `<a href>` matches `climber.aspx?cid=<digits>` (your personalized My-Home link). Do **not** trust the "Logged in:" string or the always-present "Log In" anchor.

These signals are encoded in `scripts/preflight.py` (`LOGIN_INDICATORS`).

## Resolving peaks: never silently drop coord-null rows (Kyle, 2026-06-09)

**peak_db can contain a ranked peak with MISSING coordinates** (null lat/lon). This happened with 6 of the lowest-ranked 13ers (ids 822/817/825/839/819/652) — **backfilled 2026-06-09, now 0 remaining** — but it can recur on newly-added peaks. The trap: most resolution/nearby code filters `if p['lat'] and p['lon']`, which **silently excludes such rows** — so a peak that *is* in the database looks "missing." This caused a wrong "not in peak_db" conclusion on PT 13,003.

**Rule:** when resolving a named/numbered peak, match by **id / name / elevation FIRST, without the coord filter**, and only then check coords. If a matched peak has null coords, treat it as "in peak_db but needs coordinates" (look them up on LoJ/14ers), not "not in peak_db."

**Workaround in a report config** (until peak_db is fixed): carry the peak in `gpx/<slug>/peaks.yml` as `extra_summits: [{name, lat, lon[, ele_ft]}]` (coords from LoJ/14ers). `build_peak_gpx` adds them to `peaks_only`, and the summit-only-tracks filter (`make_overview_map` / `caltopo_mytracks` / `prune_caltopo_tracks`) counts them so their tracks aren't dropped.
