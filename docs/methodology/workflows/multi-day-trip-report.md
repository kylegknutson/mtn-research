# Workflow: Multi-day-trip report

**Trigger:** "plan a backpack trip with peaks over several days" — a trip with a pack-in, peaks bagged from a basecamp (or moving camps) across multiple days, and a pack-out.

**Output:** `docs/trips/<slug>.md` + CalTopo map + `docs/maps/<slug>.png`.

This is the most complex flavor: it's a day-trip report per day, wrapped in trip-level logistics (camps, water, gear, pack weight, weather windows).

## Checklist

Source rigor (all three sources, confirmed logged-in) on **every peak** in the itinerary, plus:

- [ ] **Itinerary design** — group peaks by day from the basecamp(s); balance daily gain/distance/class
- [ ] **Basecamp selection** — location(s), elevation, water access, legality (wilderness camping rules, permit zones)
- [ ] **Pack-in / pack-out** routes + distance/gain with a full pack
- [ ] **Water sources** along approach and near camp (mark on map)
- [ ] **Per-day peak stats** from GPX (each day's loop from camp). Peaks at *different* trailheads → **don't auto-route one loop**; run `build_recommended_route.py` per day-area and set `days_detail` + a per-day-sum `dist_mi`/`gain_ft`. ([Build the recommended route right](../source-requirements.md))
- [ ] **Weather** — peaks ≤6 mi apart: one `weather:` NOAA link for the central peak. Peaks >6 mi apart: a `wx:` NOAA link per `days_detail` day (forecast.weather.gov/MapClick.php?lat=&lon= for the day's central peak).
- [ ] **Gear notes** — group + personal + technical (rope/axe/crampons if any day needs it)
- [ ] **Weather-window strategy** — which day for the hardest/most-exposed peaks
- [ ] **Bailout/escape routes** from camp
- [ ] **Single CalTopo map + PNG** showing camps, water, pack route, and each day's loop

## Body sections (multi-day flavor)

1. **Trip Stats** — total days, total peaks, total distance/gain, pack-in distance, basecamp elevation
2. **Overview map** (embedded PNG + CalTopo link — camps, water, pack route, day loops)
3. **Peaks covered** — table: peak / day / class / from-camp stats / combo notes
4. **Logistics**
   - Pack-in (route, distance, gain, time with full pack)
   - Basecamp(s) (location, elevation, water, legality)
   - Pack-out
5. **Day-by-day itinerary** — one subsection per day: peaks, route, stats, connector beta, bailouts
6. **Water** — sources with locations
7. **Gear** — group / personal / technical
8. **Conditions / season / permits** — including wilderness camping/permit rules
9. **Weather strategy** — sequencing exposed days
10. **Trip reports & GPX** — grouped by source, flagging multi-day/backpack TRs specifically
11. **TL;DR**
12. **Sources checked** footer

## Notes

- **Reference implementation:** [South San Juans 3-Day](../../trips/south_san_juans_3day.md) (Bennett + Conejos + Summit/Montezuma/Unicorn trio). It's a **car-camp / move-camp-by-vehicle** trip, not a backpack — so the "pack-in/basecamp" sections become **vehicle relocations + dispersed car camps near each day's trailhead**. Adapt the template to the trip's style (backpack vs. car-camp).
- **Driving route on the PNG + directions links (Kyle, 2026-06-07/08).** For multi-day trips, show the road connecting the camps/trailheads on the overview PNG **and** give clickable directions between approaches. `build_drive_route.py --slug <slug>` routes the actual road (OSRM) through the `kind: trailhead` landmarks in `peaks.yml` order and writes `<slug>_drive.gpx`; `make_overview_map` renders any `*_drive*` file as a **reserved black dashed line** (a color *not* used on the CalTopo map, so it reads as "road", not a GPS track), and `gpx_to_caltopo` skips it (PNG-only, never uploaded). The same script also **prints clickable Google-Maps directions links per leg** — drop them into a **"Driving directions between approaches"** subsection under Logistics (standard for every trip report). `build_report.py` runs `build_drive_route` automatically when a trip has ≥2 trailheads.
- **Only summiting tracks on the map (Kyle, 2026-06-08).** A track belongs on a report's map (PNG and CalTopo) **only if it actually summits a researched/objective peak** — passing nearby is not route beta. Enforced in two places: `caltopo_mytracks.py` drops bbox tracks that don't top out within ~240 m of an `objective_ids` summit, and `make_overview_map.py` applies the same summit filter at render time (objectives from `peaks.yml` via peak_db). This also supersedes the old centroid/near-cluster clip.
- Camps/water/pack-route are first-class map features here (unlike day-trips). The objective box for the PNG should span the basecamp + the peaks, not just the summits. For trips whose zones are far apart (e.g. ~17 mi), the single PNG is a **regional locator** (peaks small, drive route shown) — per-area route detail lives on the interactive CalTopo map.
