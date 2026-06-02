# Source requirements

**Multiple sources is a hard requirement.** If all three sources weren't confirmed logged-in and checked, the research isn't valid — redo it.

## The three sources

| Source | Login (Kyle) | What it's good for |
|---|---|---|
| **14ers.com** | "Basin" | Route descriptions (when they exist), trip reports, per-peak GPX library |
| **listsofjohn.com** | "letsgocu" | Peak stats (LiDAR elev, prominence, saddle), TRs with "Additional Peaks" header (combo detection), per-TR GPX |
| **peakbagger.com** | "Kyle Knutson" | Ascent records with structured gain/distance/trailhead, ascent GPX tracks |

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

**Every report must end with a line naming all three sites + the confirmed logged-in username**, e.g.:

> **Sources checked:** 14ers.com ✓ (logged in, "Basin") · listsofjohn.com ✓ (logged in, "letsgocu") · peakbagger.com ✓ (logged in, "Kyle Knutson")

If any source isn't confirmed logged-in, the footer must say so, and the research is flagged incomplete.

## Halt conditions

- **No 14ers.com access** → halt and tell the climber. Don't substitute web-search snippets, climb13ers alone, or your own knowledge. The verification step (14ers TRs + GPX) is what makes the research trustworthy; without it the answer is plausible but unverified.

## What NOT to do

- Don't conclude "no 14ers route description = no data" — TRs and GPX are still data.
- Don't substitute web search snippets or general knowledge for the three sources.
- Don't pause to ask for direction every time a route description is missing — that's expected; dig into TRs instead.
