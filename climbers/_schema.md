# Climber profile schema

Each climber gets a `climbers/<slug>.yml`. Adding a friend should be mechanical: copy this shape, fill in their values, provide their 14ers checklist URL.

## Fields

| Field | Required | Notes |
|---|---|---|
| `name` | ✓ | Display name |
| `slug` | ✓ | Lowercase, used in filenames (`<report>.<slug>.md`) and site naming |
| `is_default` | — | `true` only for Kyle (owner). Default climber's reports are unsuffixed. |
| `home_address` | ✓ | Used verbatim as the origin in Google Maps directions links |
| `home_latlon` | ✓ | `[lat, lon]` — for haversine first-cut candidate netting |
| `climbed_list.source` | ✓ | `peak_db` (Kyle) or `14ers_checklist` (friends) |
| `climbed_list.checklist_url` | for friends | The 14ers.com checklist URL the friend provides; scraped for their done/unclimbed list |
| `site.mkdocs_config` | ✓ | Which mkdocs config builds this climber's site |
| `site.url` | ✓ | Published URL |
| `accounts.{14ers,listsofjohn,peakbagger}` | ✓ | Logged-in usernames for the Sources-checked footer + login verification |
| `preferences.default_list` | — | e.g. `co_13_14ers` |
| `preferences.closest_means` | — | always `drive_time` |
| `preferences.combo_rule` | — | always `ranked_13er_plus` |

## Friend example (template)

```yaml
name: Alex Example
slug: alex
home_address: "123 Example St, Denver, CO 80202"
home_latlon: [39.7392, -104.9903]
climbed_list:
  source: 14ers_checklist
  checklist_url: "https://www.14ers.com/checklist.php?..."   # Alex provides
site:
  mkdocs_config: mkdocs.alex.yml
  url: "https://kylegknutson.github.io/mtn-research-alex/"
accounts:
  14ers: "<alex 14ers username>"
  listsofjohn: "<or n/a — may use Kyle's session for lookups>"
  peakbagger: "<or n/a>"
preferences:
  default_list: co_13_14ers
  closest_means: drive_time
  combo_rule: ranked_13er_plus
```

## Notes

- **Reports are per-(peak, climber).** Kyle: `docs/peaks/<slug>.md`. Friend: `docs/peaks/<slug>.<slug>.md`. The route research (GPX, CalTopo tracks) is shared — only the climber-specific framing differs (their done/unclimbed status, their drive time from their address, their cluster "what's left for you").
- **GPX is shared across climbers** — route geometry doesn't change based on who's climbing. `gpx/<slug>/` is one collection per peak/trip.
- **Friend climbed-lists** come from the 14ers.com checklist URL they provide (scraped via `scripts/scrape_14ers_checklist.py` — to be built in the multi-climber phase). Kyle's comes from peak_db.
- **Privacy:** if a friend's home address should not be public, store it in `climbers/<slug>.private.yml` (gitignored) and reference it at build time. Default `climbers/<slug>.yml` is committed.
