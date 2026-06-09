# Source requirements

**Multiple sources is a hard requirement.** If all three sources weren't confirmed logged-in and checked, the research isn't valid — redo it.

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

1. Navigate to each site and confirm the logged-in username appears.
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
