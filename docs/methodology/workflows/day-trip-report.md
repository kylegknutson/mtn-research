# Workflow: Day-trip report

**Trigger:** "research a combo/cluster day" — 2+ ranked peaks done in a single outing. Examples: Crestolita + Broken Hand; Star + Taylor + Italian.

**Output:** `docs/peaks/<slug>.md` (day-trip flavor) + CalTopo map + `docs/maps/<slug>.png`.

A day-trip report is a single-peak report extended to cover the linkage between peaks. Same source rigor on **every** peak in the trip.

## Checklist

Everything in the [single-peak checklist](single-peak-report.md), applied to each peak, plus:

- [ ] **Confirm it's a real pairing** — check TRs for how often these peaks are actually done together (combo evidence), not just geographic proximity
- [ ] **Connector beta** — the ridge/traverse between peaks: class, distance, exposure
- [ ] **Combo stats from GPX** — compute total distance + gain from the exact-combo TR tracks (not the sum of two standalone climbs)
- [ ] **Single CalTopo map + PNG** covering all peaks in the trip (objective box spans the peaks)

## Body sections (day-trip flavor)

1. **Quick Stats** — a column per peak (elev, lat/lon, weather, class, peak-page links)
2. **Overview map** (embedded PNG + CalTopo link)
3. **Why these together** — TR evidence the combo is a real/standard pairing; the ranked-13er+ combo logic
4. **Drive + approach** — clickable drive link, primary + alternate trailheads
5. **Recommended plan** ⭐ — the linkage: approach → peak 1 → connector → peak 2 → exit, with **combo stats** (distance/gain measured from exact-combo GPX) and per-segment class
6. **Per-peak route notes** — standard line for each + alternates (couloirs, ridges)
7. **Alternate approach** (if a meaningfully different start exists)
8. **Conditions / season** + permits + hazards
9. **Trip reports & GPX** — grouped by source (14ers / LoJ / peakbagger), flagging which TRs did the exact combo
10. **TL;DR**
11. **Sources checked** footer

## Notes

- **Combo stats are measured, not summed.** Two peaks 0.6 mi apart share approach and connector — pull the distance/gain from a TR GPX that actually did both, not from adding two standalone numbers.
- **Big days are fine.** A combo day can blow past the "short day" gain threshold — that's expected; just frame it as a full alpine outing.

See [Crestolita + Broken Hand](../../peaks/crestolita_broken_hand.md) as the reference implementation.
