# mtn-research

Kyle's Colorado peak research notes — routes, link-ups, conditions, trip reports.

Rendered site: <https://kylegknutson.github.io/mtn-research/>

## Repo layout

```
docs/peaks/        markdown research notes (one per trip/cluster)
docs/maps/         static PNG overview maps (one per slug)
gpx/{slug}/        downloaded + generated GPX for each peak
caltopo/           dumped CalTopo map JSON (one file per map id)
scripts/           tooling — all scripts run directly on any Mac (see below)
```

## Running scripts (any Mac, no venv setup)

All Python scripts in `scripts/` are directly executable. The ones that need
external deps use **[uv](https://docs.astral.sh/uv/)** with [PEP 723 inline
metadata](https://peps.python.org/pep-0723/) — uv builds and caches a per-script
env on first run.

**One-time setup per Mac:**

```bash
brew install uv
```

That's it. No `pip install`, no `requirements.txt`, no venv to remember the
path of. Just:

```bash
scripts/make_overview_map.py hunts_peak --title "Hunts Peak"
scripts/fetch_caltopo.py --map C105AEV
scripts/gpx_to_caltopo.py --gpx-dir gpx/pt_13557 --new-map "Research: PT 13,557"
scripts/find_nearby.py --center 38.3831,-105.94582 --radius-km 5
scripts/caltopo_to_gpx.py caltopo/C105AEV.json --out gpx/_kyle_existing/
```

uv caches downloaded packages in `~/.cache/uv` — the first run of each script
takes a few seconds to resolve deps; subsequent runs are instant.

### Why this approach

- **iCloud-safe**: no venv inside the iCloud-synced project (dylibs get evicted)
- **No "wrong Mac" friction**: no hardcoded `~/dev/mtn_venv` path
- **Self-documenting**: each script lists its deps in its own header
- **Stdlib-only scripts** (`find_nearby.py`, `caltopo_to_gpx.py`) just use the
  system `python3` — no uv overhead

## Peak data source

Live climb log lives in Supabase, read via the stdlib-only Python client at
`~/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db/`. See that
directory's README. The client is imported on demand by Claude during research
— no need to keep a local copy of the peak list.

## CalTopo credentials

`scripts/cts.ini` (gitignored) — copy `cts.ini.template` and fill in.
