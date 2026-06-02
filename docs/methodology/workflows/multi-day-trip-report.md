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
- [ ] **Per-day peak stats** from GPX (each day's loop from camp)
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

- **No reference implementation yet.** First multi-day report will set the concrete pattern; refine this page from it.
- Camps/water/pack-route are first-class map features here (unlike day-trips). The objective box for the PNG should span the basecamp + the peaks, not just the summits.
