# Site conventions

Small, consistent rules that apply to every report and page.

## Weather link (required in Quick Stats)

Every report's Quick Stats table includes a **Weather** row directly under Lat/Lon:

- URL: `https://forecast.weather.gov/MapClick.php?lat=<summit_lat>&lon=<summit_lon>` (primary summit's LiDAR coords)
- This is the **same NOAA target** that 14ers / LoJ / peakbagger all link to — one link covers all three
- Value format: `[NOAA forecast](URL) (same target as 14ers / LoJ / peakbagger weather links)`
- Multi-peak reports: use the primary peak's coords, label `Weather (Primary Pk)` — the forecast resolution covers the cluster

## Drive-from-home (required, clickable)

The "Drive from Boulder" / "Drive from home" row must be a **clickable Google Maps directions link**:

- Origin: the climber's home address (Kyle: `1162 Peakview Circle, Boulder, CO 80302`)
- Destination: the primary trailhead's coordinates
- URL: `https://www.google.com/maps/dir/?api=1&origin=<url-encoded-address>&destination=<lat>,<lon>`
- Format: `**[1h 42m via Google Maps](URL)** (origin: <short address>)`
- Drive time itself is measured via Maps directions (Playwright), not estimated

## "Closest" = drive time, not haversine

When ranking peaks by proximity, default to **drive time from the climber's home**, not straight-line distance. Haversine badly misorders Colorado peaks (a Sangre peak can be farther in miles but a shorter drive than an Elk Range peak). Use haversine only as a first-cut net to pull candidates (top 50–75), then rank the finalists by Maps drive time.

## External links open in a new tab

Implemented site-wide via `docs/javascripts/external-links-new-tab.js` (Material `document$`-subscribed; marks every external-origin `a[href^="http"]` with `target="_blank" rel="noopener noreferrer"` on load and on instant-nav). 

- Just write plain markdown links `[text](url)` — do NOT add `{target="_blank"}` or raw HTML
- Internal links (peak↔peak, anchors) stay same-tab automatically
- If a theme/plugin update breaks it, fix the JS — don't add per-link attributes

## Naming conventions

- Slugs use underscores: `jacque_peak`, `crestolita_broken_hand`
- Single-peak / day-trip reports: `docs/peaks/<slug>.md`
- Multi-day trips: `docs/trips/<slug>.md`
- Per-climber (friend) reports: `docs/peaks/<slug>.<climber>.md` (Kyle = unsuffixed default)
- Saved narrow-downs: `docs/lists/YYYY-MM-DD_<slug>.md`
- GPX: `gpx/<slug>/<slug>_<author>_<year>_<source><id>.gpx`
- Maps: `docs/maps/<slug>.png`

## Publishing checklist

After writing/updating a report:
1. Add to `mkdocs.yml` nav
2. Add to `docs/index.md` (grouped by region/category)
3. Commit + push
4. Confirm the GitHub Actions deploy is green before calling it done

## Report frontmatter (structured, machine-readable)

Every report opens with a YAML frontmatter block. Beyond `image:` (the link-preview
card), these fields make reports queryable — they drive the auto-generated index /
sortable peak table (planned) and the link-preview metadata.

```yaml
---
image: maps/<slug>.png        # link-preview card (the report's own overview map)
range: Sangre de Cristo       # peak_db range — drives grouping/filtering
drive_time: "3h 58m"          # from the climber's home (matches the report's drive row)
yds_class: "3"                # YDS class of the standard line (quoted; `yds_class` not
                              #   `class`, to avoid the Jinja reserved-word gotcha)
gain: "6,400–7,100 ft"        # standard-route gain (range if multiple TRs)
status: unclimbed             # unclimbed | climbed (for the default climber)
caltopo_id: 6TKA0RH           # research map ID (omit if none yet)
regional_map_id: VKGB00L      # the range's regional "GPS Tracks" map
---
```

`check_reports.py` warns on any report missing the recommended fields (range,
drive_time, yds_class, gain, status, regional_map_id). It's a warning, not a hard
fail — but new reports should always include them.

## Landing-page peak table (auto-generated)

`docs/index.md` has a sortable peak table between `<!-- PEAKS_TABLE_START -->` and
`<!-- PEAKS_TABLE_END -->`, generated from each report's frontmatter by
`scripts/gen_index.py` (sorted by drive time; click headers to re-sort via
tablesort). **Don't hand-edit between the markers.** After adding/editing a report:

```
scripts/gen_index.py     # regenerate the table
```

CI runs `gen_index.py --check` and fails if the table is stale.

## Naming multi-peak reports

A **single-day** multi-peak report (a combo/cluster day, *not* a stated multi-day trip) is titled **`<tallest peak name> Group`** + the after-dash subtitle, e.g. `# Broken Hand Peak Group — combination day (Sangre de Cristo)` (Broken Hand 13,575' > Crestolita 13,264'), `# Mount Powell Group — combination day (Gore Range)`. A **stated multi-day** report keeps a descriptive title (e.g. "Lakes of the Clouds — 7-peak loop"). (Kyle, 2026-06-03)
