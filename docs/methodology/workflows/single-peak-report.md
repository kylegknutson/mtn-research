# Workflow: Single-peak report

**Trigger:** "do a report on Peak X" (one peak, all its approaches/options).

**Output:** `docs/peaks/<slug>.md` + CalTopo map + `docs/maps/<slug>.png`, shipped together.

## Checklist

- [ ] **Login check** all three sources, confirm usernames ([source requirements](../source-requirements.md))
- [ ] **peak_db lookup**: id, LiDAR elev, lat/lon, range, class, ranked status, climbed status
- [ ] **Cluster check**: nearby unclimbed ranked 13ers+ within ~8 mi (note which are *same-drainage* combos vs different-drive)
- [ ] **TR sweep** across 14ers + LoJ + peakbagger; capture route narrative, gain/distance, season, hazards
- [ ] **GPX sweep** across all three sources → `gpx/<slug>/` ([pipeline](../caltopo-pipeline.md))
- [ ] **Drive time** from climber's home → primary trailhead (Maps, clickable link)
- [ ] **Build waypoint GPX** (summit + same-drainage neighbors + trailheads/landmarks)
- [ ] **Upload to CalTopo** (`--no-dedupe`, source colors), capture map ID
- [ ] **Render PNG** (`make_overview_map.py <slug>`), verify framing (objective centered)
- [ ] **Write report** per [report template](../report-template.md)
- [ ] **Weather link + clickable drive link** in Quick Stats ([conventions](../conventions.md))
- [ ] **"Sources checked" footer**
- [ ] **Wire nav** (`mkdocs.yml`) + **Home index** (`docs/index.md`)
- [ ] **Commit, push, verify deploy green**

## Body sections (single-peak flavor)

1. **Quick Stats** table (coords, elev, class, range, weather, drive, peak-page links)
2. **Overview map** (embedded PNG + CalTopo link)
3. **Cluster status / multi-peak link-ups** — what else is realistically baggable from the same approach
4. **Recommended route** ⭐ + alternates (A/B/C) with distance, gain, class, source TR
5. **Trailhead** + access road + vehicle notes
6. **Conditions / season** + permits + cell coverage
7. **Trip reports** table from all three sources with links
8. **TL;DR**
9. **Sources checked** footer

See [Hunts Peak](../../peaks/hunts_peak.md) and [Jacque Peak](../../peaks/jacque_peak.md) as reference implementations.
