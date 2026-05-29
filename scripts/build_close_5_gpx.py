#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""
build_close_5_gpx.py — generate peaks_only + landmarks GPX files for the
5 newly-researched close-unclimbed 13ers (Jacque, Pennsylvania, Homestake,
Savage, Star Pk A).

Each peak gets:
  gpx/<peak>/<peak>_peaks_only.gpx  — summit + nearby unclimbed ranked 13ers (gold)
  gpx/<peak>/<peak>_landmarks.gpx   — approximate trailhead + key drive-in waypoints (purple)

Approximate TH coordinates are inferred from trip-report narratives and the
14ers/PB trailhead data. Tweak exact coordinates on the CalTopo map after.

Runs via uv (PEP 723 inline deps) — no venv to manage.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, "/Users/kyleknutson/Library/Mobile Documents/com~apple~CloudDocs/shared/peak_db")
from peak_db_client import peaks  # type: ignore  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
GPX_ROOT = PROJECT / "gpx"

# Peak setup: each peak has (slug, summit_lat, summit_lon, summit_elev_ft, nearby_unclimbed_ids, landmarks)
# landmarks: list of (label, lat, lon, ele_ft)
PEAKS = [
    {
        "slug": "jacque_peak",
        "name": "Jacque Peak",
        "peak_db_id": 603,
        # Nearby unclimbed ranked 13ers within 8 mi (peak_db ids)
        "nearby_unclimbed": [402],  # Bartlett Mtn 13,348 @ 5.74mi — only nearby ranked unclimbed (different drive)
        "landmarks": [
            ("Copper Mtn Resort base TH (Woodward Express area)", 39.4914, -106.1568, 9712),
            ("CO 91 / Graveline Gulch pullout (alt TH, off-piste season)", 39.3938, -106.1469, 10500),
            ("Mayflower Gulch TH (winter alt — AVOID tailings)", 39.39056, -106.13889, 10963),
        ],
    },
    {
        "slug": "pennsylvania_mountain",
        "name": "Pennsylvania Mountain",
        "peak_db_id": 812,
        "nearby_unclimbed": [402],  # Bartlett Mtn at 7.82 mi (barely in range, different drainage)
        "landmarks": [
            ("Pika Trailhead (standard, off Hwy 9)", 39.2658, -106.1638, 11716),
            ("Mountain View Drive end (alt TH)", 39.2580, -106.1530, 11200),
            ("⚠️ CR 696 (Mosquito Pass Rd) — hostile claim-holder, AVOID", 39.2950, -106.1300, 11500),
        ],
    },
    {
        "slug": "homestake_peak",
        "name": "Homestake Peak",
        "peak_db_id": 596,
        # Savage on Kyle's list (5.72 mi) is closest unclimbed ranked but different drainage
        "nearby_unclimbed": [674],  # Savage Pk
        "landmarks": [
            ("Wurts Ditch Rd parking (before gate)", 39.3500, -106.3700, 10400),
            ("10th Mountain Memorial Hut", 39.3631, -106.4055, 10872),
            ("Hwy 24 turnoff at Webster's Sand & Gravel Pit (mp 167.5)", 39.3289, -106.3289, 9420),
            ("Crane Park TH (alt full-hike start)", 39.3294, -106.3300, 10148),
        ],
    },
    {
        "slug": "savage_peak",
        "name": "Savage Peak",
        "peak_db_id": 674,
        # Nearby unclimbed ranked: PT 13,089, PT 13,100 A, Homestake (on list), Pika Pk, Gold Dust
        "nearby_unclimbed": [732, 711, 596, 688, 412],
        "landmarks": [
            ("Missouri Lakes TH (2WD, 10,000')", 39.3858, -106.4717, 10000),
            ("Missouri Lakes 4WD parking (0.6 mi up)", 39.3850, -106.4790, 10060),
            ("⚠️ Homestake Rd (FS 703) — gated Nov 22-May 21", 39.3939, -106.4119, 8870),
            ("Homestake Rd / Missouri Creek Rd junction", 39.3863, -106.4623, 9700),
        ],
    },
    {
        "slug": "star_peak_a",
        "name": "Star Peak A",
        "peak_db_id": 301,
        # MASSIVE cluster — 14 unclimbed ranked 13ers within 8 mi
        "nearby_unclimbed": [365, 432, 477, 420, 438, 599, 417, 588, 287, 391, 305, 281, 399, 322],
        "landmarks": [
            ("End of CO 742 — Mt Tilton Trail TH", 39.0095, -106.7833, 10760),
            ("⚠️ Cottonwood Pass / CO 742 — seasonal closure late May–late October", 38.8275, -106.4119, 12126),
        ],
    },
]

# Mapping of peak_db ids → display names + coords for nearby unclimbed lookups
# (will fetch from peak_db at runtime)


def write_gpx(path: Path, waypoints: list[tuple[str, float, float, int | None, str]]) -> None:
    """waypoints: list of (name, lat, lon, ele_ft, sym_class)
    sym_class: 'peak' or 'landmark' (used as <sym> for downstream styling)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="build_close_5_gpx.py" xmlns="http://www.topografix.com/GPX/1/1">',
        f'  <metadata><time>{now}</time></metadata>',
    ]
    for name, lat, lon, ele_ft, sym in waypoints:
        # Convert feet to meters for GPX <ele>
        ele_m = (ele_ft * 0.3048) if ele_ft else None
        ele_tag = f'<ele>{ele_m:.1f}</ele>' if ele_m else ''
        # Escape minimal XML chars
        safe = name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
        lines.append(f'  <wpt lat="{lat}" lon="{lon}">{ele_tag}<name>{safe}</name><sym>{sym}</sym></wpt>')
    lines.append('</gpx>')
    path.write_text("\n".join(lines))


def main():
    print(f"Loading peak_db for nearby-peak lookups…")
    all_peaks = {p["id"]: p for p in peaks()}
    print(f"Loaded {len(all_peaks)} peaks.")

    for cfg in PEAKS:
        slug = cfg["slug"]
        name = cfg["name"]
        out_dir = GPX_ROOT / slug
        out_dir.mkdir(parents=True, exist_ok=True)

        # peaks_only.gpx — summit + nearby unclimbed
        summit = all_peaks[cfg["peak_db_id"]]
        peak_wpts = [
            (f"{name} (summit, {summit['elevation_ft']}')", summit["lat"], summit["lon"], summit["elevation_ft"], "peak"),
        ]
        for pid in cfg["nearby_unclimbed"]:
            p = all_peaks.get(pid)
            if not p:
                print(f"  WARN: peak id {pid} not found in DB, skipping")
                continue
            clean_name = p['display_name'].strip('"')
            label = f"{clean_name} ({p['elevation_ft']}', UNCLIMBED)"
            peak_wpts.append((label, p["lat"], p["lon"], p["elevation_ft"], "peak"))

        peaks_path = out_dir / f"{slug}_peaks_only.gpx"
        write_gpx(peaks_path, peak_wpts)
        print(f"  Wrote {peaks_path.relative_to(PROJECT)} ({len(peak_wpts)} waypoints)")

        # landmarks.gpx — TH + drive-in waypoints
        landmark_wpts = [
            (label, lat, lon, ele, "trailhead")
            for label, lat, lon, ele in cfg["landmarks"]
        ]
        landmarks_path = out_dir / f"{slug}_landmarks.gpx"
        write_gpx(landmarks_path, landmark_wpts)
        print(f"  Wrote {landmarks_path.relative_to(PROJECT)} ({len(landmark_wpts)} waypoints)")

    print(f"\nDone. Next: run gpx_to_caltopo.py for each.")


if __name__ == "__main__":
    main()
