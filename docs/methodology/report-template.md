# Report template

The canonical structure for a report. Single-peak and day-trip reports live in `docs/peaks/<slug>.md`; multi-day trips in `docs/trips/<slug>.md`. Flavor-specific body differences are in each [workflow page](index.md#workflows-what-kind-of-task-is-this).

## Required header block

```markdown
# <Peak(s)> — <flavor note if combo/trip> (<Range>)

**Researched:** YYYY-MM-DD
**Report type:** Single peak | Day trip (N peaks) | Multi-day trip
**CalTopo research map:** https://caltopo.com/m/XXXXXXX
**Status in DB:** <climbed/unclimbed; cluster context>

![Overview map](../maps/<slug>.png)
*[Interactive CalTopo map](https://caltopo.com/m/XXXXXXX)*
```

## Required Quick Stats table

One column for a single peak; a column per peak for combos. **Must include** these rows:

- Elevation (LiDAR)
- Lat / Lon
- **Weather** — `[NOAA forecast](https://forecast.weather.gov/MapClick.php?lat=<lat>&lon=<lon>) (same target as 14ers / LoJ / peakbagger weather links)` — directly under Lat/Lon
- Class (standard)
- Range / Wilderness
- 14ers.com / LoJ / peakbagger links
- Peak DB id

## Required drive row

`**[<Xh Ym> via Google Maps](<directions URL>)** (origin: <home address>)` — see [conventions](conventions.md).

## Required sections — v2 format (Kyle, 2026-07-12)

Fixed order, `---` divider between every `##` section. The **At-a-glance callout is
the single home for day/trip stats** — section headings carry class only, prose never
restates mileage/gain (option-comparison tables are the one exception). Provenance
("composed from N tracks…") lives ONLY in the map-box note + the Trip-reports section.

| # | Section | Day trip / single peak | Multi-day trip |
|---|---|---|---|
| 1 | Header zone (H1 → quickstats → written-for → weather box → map box → status → PNG → provenance) | ✓ | ✓ |
| 2 | `!!! danger` box (Class 4/5 or genuinely sketchy only; ≤1 line per hazard) | if warranted | if warranted |
| 3 | Peaks covered — intro sentence (style · hardest move · access · days/nights) + table with **names linked to 14ers.com peak pages** (`14ers.com/peaks/<id>`, id from peak_db; CO peaks only) | ✓ | ✓ |
| 4 | Itinerary options (>1 option ⇒ **every option gets a day-table, same columns**; settled decisions = one inline line → *Other considerations*) | if options exist | ✓ |
| 5 | Getting there (trailhead/access; **clickable drive-from-home link lives here**) | ✓ | ✓ (train/shuttle etc.) |
| 6 | Route description, in walking order | ✓ | "The days, in order" — `### Day N` chronological, pack-in = Day 1 |
| 7 | Camps & water (basecamps + water merged) | — | ✓ |
| 8 | Gear & season (gear + conditions/season/permits + bail-outs merged) | ✓ | ✓ |
| 9 | Other considerations — *optional*: judgment forks (direction, alternate access) with full rationale | if forks exist | if forks exist |
| 10 | Trip reports & GPX (all 3 sources; sweep counts live here) | ✓ | ✓ |
| 11 | **Sources checked footer** | ✓ | ✓ |

Prose rules: **no TL;DR section** (cut 2026-07-11), **no weekday framing** (Day 1, Day 2…),
**no acclimatization talk** — see [conventions](conventions.md).

## Required footer

```markdown
**Sources checked:** 14ers.com ✓ (logged in, "<user>") · listsofjohn.com ✓ (logged in, "<user>") · peakbagger.com ✓ (logged in, "<user>")
```

## Reference implementations

- **Single peak:** [Hunts Peak](../peaks/hunts_peak.md), [Jacque Peak](../peaks/jacque_peak.md)
- **Day trip:** [Crestolita + Broken Hand](../peaks/crestolita_broken_hand.md)
- **Multi-day (v2 exemplar):** [Jupiter, Pigeon & Turret](../peaks/jupiter_pigeon_turret.emily.md)

## Rank references (Kyle, 2026-07-11)

Never expose raw `peak_db` ids in report bodies — readers (and share-page
recipients) can't use them. Peak tables use a **CO rank** column (`#58` style) and
the report defines it once: *elevation rank among Colorado's ranked 13ers + 14ers*
(peak_db's `rank`). peak_db ids live only in frontmatter/peaks.yml where the
tooling needs them.
