# Workflow: Narrow-down

**Trigger:** an open-ended "which peaks…" question with criteria. Examples:
- "peaks I haven't done, usually climbed alone, under 4k ft of gain, ranked by distance from me"
- "San Juan climbs that combine a lot of mountains"
- "give me the next 5 in that list"

**Output:** a saved list artifact in `docs/lists/YYYY-MM-DD_<slug>.md` — a frozen result table (snapshot) **plus** the re-runnable criteria. Also surface the table in chat.

## Steps

1. **Login check** all three sources ([source requirements](../source-requirements.md)).
2. **Pick the climber** (default Kyle). Their climbed list + home address come from `climbers/<name>.yml`.
3. **Query the candidate pool** from peak_db: filter the relevant list (`co_13_14ers`, etc.) to ranked peaks, subtract the climber's climbed set, apply the stated criteria (range, gain, class, list membership, season).
4. **First-cut sort by haversine** from the climber's home; pull a wide net (top ~50–75) so drive-time reordering doesn't miss anything.
5. **Enrich finalists** from all three sources for the columns below (gain, class, trailhead, combo pattern).
6. **Rank by drive time** from the climber's home (Maps directions), not haversine.
7. **Write the artifact** (template below) and surface the table in chat.

## Candidate table format (required columns, in order)

`# | Peak | Range | Drive (Maps) | Class | Gain | Trailhead | Confidence | Combos`

- **#** — rank by drive time
- **Peak** — display name, quoted if quoted in the DB (`"Pk Z"`)
- **Range** — from peak_db `range` (don't guess)
- **Drive (Maps)** — `1h 42m`, ideally a clickable directions link
- **Class** — YDS (`2`, `3`, `2(+)`)
- **Gain** — feet, range if multiple TRs (`3,422–3,500'`)
- **Trailhead** — short name
- **Confidence** — `High`/`Medium`/`Low` + 1-line reason
- **Combos** — ranked-13er+-only rule: `Mostly Solo` / `Solo` / `Combined` / `Mostly Combined` / `Mixed`, with ranked partner(s) in parens

Below the table: ★ best-solo / ★★ standout callouts, and a "skip when you want a solo half-day" summary of the Combined entries.

## "Combined" definition (ranked-13er+ only)

Only count a peak as "combined" if at least one *additional ranked 13er/14er* is climbed the same day. Sub-13k bumps and unranked summits **don't count** (Tucker/Union/Copper near Jacque; Galena near Homestake; Music near Savage). Filter the "Additional Peaks" lists to ranked 13er+ before tallying.

## Saved-list artifact format

```markdown
# <Question / title>

**Run date:** YYYY-MM-DD · **Climber:** Kyle · **Source pool:** <list, e.g. co_13_14ers ranked, unclimbed>

## Result (snapshot)
<the candidate table>
<callouts>

## Criteria (re-runnable)
- Filters: <range / gain / class / list / season>
- Climbed-list source: <peak_db | 14ers checklist URL>
- Sort: drive time from <home address>
- Net size: top N by haversine, re-ranked by drive time
```

The snapshot is frozen at run time; the criteria block lets a future session regenerate it. Re-running produces a new dated file (don't overwrite).
