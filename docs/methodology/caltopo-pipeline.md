# CalTopo + PNG map pipeline

**A report is not done until the CalTopo map AND the PNG overview are built and shipped with the markdown.** Maps and reports always go together.

Every report ships **three artifacts as one unit**:
1. `docs/peaks/<slug>.md` (or `docs/trips/<slug>.md`) — the markdown report
2. CalTopo research map (`https://caltopo.com/m/XXXXXXX`) — interactive, linked from the report header
3. `docs/maps/<slug>.png` — overview PNG embedded near the top of the report

## Pipeline

### 1. Build waypoint GPX
Generate `gpx/<slug>/<slug>_peaks_only.gpx` (summit + nearby same-objective unclimbed ranked peaks) and `<slug>_landmarks.gpx` (trailheads + key drive-in landmarks: gates, closed roads, seasonal closures). Summit + nearby-peak coords come from peak_db.

### 2. Download GPX tracks from ALL THREE sources
Not just LoJ. *"Always download the tracks from all sites not just LoJ. That's an important part of the research, finding all GPX files out there and pulling them together into one map."* (Kyle, 2026-05-29)

- **LoJ**: `/gpx/<id>.gpx` per trip report — pull every TR's GPX, each has route variations
- **14ers.com**: per-peak GPX library (`gpxlib_locator.php?peakid=<id>`) covering TR uploads + member uploads + official routes; plus per-route official GPX
- **peakbagger**: per-ascent GPX (`/climber/GPXFile.aspx?aid=<aid>&sep=1`) — **confirm logged in first** (see [source requirements](source-requirements.md))

Filename convention (keeps colors/groups distinct on upload):
```
<slug>_<author>_<year>_loj<trId>.gpx
<slug>_<author>_<year>_14ersTR<id>.gpx
<slug>_<author>_<year>_14ersGPXlib<id>.gpx
<slug>_<author>_<year>_pbAscent<aid>.gpx
```
Over-pulling is fine — the upload script dedupes identical tracks. Better to grab everything than miss a route variation.

### 3. Upload to CalTopo
```
scripts/gpx_to_caltopo.py --gpx-dir gpx/<slug> --new-map "Research: <Peak>" --no-dedupe
```
`--no-dedupe` is required for research maps so summit/peak markers always render even if they exist in other maps. Color by source: LoJ red (palette default), 14ers green (`#00AA00`), peakbagger blue (`#0066FF`). Capture the returned map ID.

### 4. Wire the map ID into the report
Update the header `**CalTopo research map:**` line and the caption `*[Interactive CalTopo map](https://caltopo.com/m/<id>)*`.

### 5. Render the PNG
```
scripts/make_overview_map.py <slug> --title "<Peak>"
```
Auto-renders track lines on OpenTopoMap tiles.

### 6. Commit, push, verify deploy green
Do NOT mark a peak "researched" or update the index until all three artifacts are committed and the GitHub Pages deploy succeeds.

## Map waypoint scope — objective only

- **Include**: the summit(s), trailhead(s), key drive-in landmarks, and nearby unclimbed ranked 13ers+ that are *plausibly same-outing* (same drainage / ridge-connected / shared approach).
- **Exclude**: nearby peaks reached from a *different drive entirely* (opposite side of a pass/mine/wilderness boundary). Mention them in the report's cluster text if relevant, but they don't belong as map markers.
- Origin of this rule: putting Bartlett Mtn (across Climax Mine, a different drive) on the Jacque/Pennsylvania maps was noise. *"Why are you making a map for Bartlett?"* (Kyle, 2026-05-29)

## PNG framing — avoid distortion / over-zoom

The recurring failure mode: distant tracks (a TR where the peak was a minor add to another range's day, a mega-traverse, a long sub-13k outback) drag the bbox out and shrink the actual peaks to dots.

`make_overview_map.py` handles this by sizing the bbox around the **objective peak-marker bounding box + a ~1.5 mi margin** (auto-sizing: tight for one peak, spanning for a combo; floored and capped). Tracks that wander far render off-canvas — that wider context lives on the interactive CalTopo map, not the PNG.

If a PNG comes out distorted or over-zoomed, the fix is in `make_overview_map.py`'s bbox logic, **not** the GPX inputs.

> **Pending feature:** PNG track lines are currently all rendered red. Target is to color them by source (LoJ/14ers/peakbagger) like the CalTopo map, and to add automated map-QA tests (distortion / missing-track / blank-tile / aspect-ratio checks) that gate deploys.
