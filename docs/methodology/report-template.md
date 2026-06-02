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

## Required sections

| Section | Single peak | Day trip | Multi-day |
|---|---|---|---|
| Quick Stats | ✓ | ✓ (per-peak cols) | Trip Stats |
| Overview map (PNG + CalTopo) | ✓ | ✓ | ✓ |
| Cluster / why-combined | cluster status | why these together | peaks-covered table |
| Recommended route/plan ⭐ | ✓ | ✓ (with combo stats) | day-by-day itinerary |
| Alternates | ✓ | ✓ | per-day bailouts |
| Trailhead / approach | ✓ | ✓ | pack-in/out + camps |
| Conditions / season / permits | ✓ | ✓ | ✓ (+ camping rules) |
| Cell coverage | ✓ | ✓ | ✓ |
| Trip reports (all 3 sources) | ✓ | ✓ | ✓ |
| TL;DR | ✓ | ✓ | ✓ |
| **Sources checked footer** | ✓ | ✓ | ✓ |

## Required footer

```markdown
**Sources checked:** 14ers.com ✓ (logged in, "<user>") · listsofjohn.com ✓ (logged in, "<user>") · peakbagger.com ✓ (logged in, "<user>")
```

## Reference implementations

- **Single peak:** [Hunts Peak](../peaks/hunts_peak.md), [Jacque Peak](../peaks/jacque_peak.md)
- **Day trip:** [Crestolita + Broken Hand](../peaks/crestolita_broken_hand.md)
- **Multi-day:** *(none yet — first one sets the pattern)*

> Existing reports predate parts of this template (cell-coverage format and trailhead-table-vs-bullet vary). Normalize on the next freshness pass rather than a bulk rewrite.
