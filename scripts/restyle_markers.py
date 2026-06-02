#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["caltopo_python"]
# ///
"""
Restyle summit markers in the regional CalTopo maps: any marker sitting on a
known 14ers/13ers summit (within SNAP_M of the authoritative 14ers export) is
changed from the default red dot to the CalTopo `peak` mountain symbol in a
muted blue. Trailhead / camp / note markers (not on a summit) are left as-is.

Edits in place via editFeature (no duplicates, keeps marker IDs).

Usage:
    restyle_markers.py --export ~/Downloads/20260601-100027.gpx --map 7QE01UK   # one map
    restyle_markers.py --export ... --all                                        # every region map
    restyle_markers.py --export ... --all --color '#888888' --symbol point       # override style
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Name-based summit detection for peaks outside the CO export (e.g. New England,
# California, unranked CO points). A marker is a summit if it matches a known
# peak name or has a peak word, and has no POI/note word. POI takes precedence.
PEAK_WORDS = re.compile(r"\b(peak|pk|mountain|mtn|mt|summit|dome|butte|spire|"
                        r"needle|horn|baldy|benchmark|knob|hill|point|pt|pinnacle|"
                        r"crag|massif)", re.I)
POI_WORDS = re.compile(r"\b(trailhead|th|camp|campground|campsite|lake|creek|pass|"
                       r"parking|lot|wpt|waypoint|gulch|basin|spring|springs|junction|"
                       r"jct|saddle|road|rd|bridge|falls|reservoir|pond|meadow|cabin|"
                       r"hut|shelter|spur|divide|crossing|gate|tunnel|mine|ranch|store|"
                       r"hotel|home|car|truck|pickup|start|finish|trail|trailway|twinway|"
                       r"notch|woods|water|photo|height|national|wilderness|park|ridge|"
                       r"headwall|caretaker|possible|turnoff|turn|drop|spot|reception)\b", re.I)

# Distinctive New England peak names (NH 4000-footers + notable ME/VT/MA) that do
# not contain a peak word. Whole-word matched against the marker title.
NE_PEAKS = {
    "bondcliff", "galehead", "guyot", "moosilauke", "carrigain", "passaconaway",
    "tecumseh", "osceola", "tripyramid", "kinsman", "moriah", "waumbek",
    "isolation", "lafayette", "lincoln", "garfield", "liberty", "flume",
    "whiteface", "cannon", "zealand", "owls head", "owl's head", "south twin",
    "north twin", "west bond", "little haystack", "wildcat", "hancock",
    "tom", "field", "willey", "hale", "jackson", "pierce", "eisenhower",
    "monroe", "madison", "adams", "jefferson", "washington", "katahdin",
    "bigelow", "sugarloaf", "saddleback", "abraham", "spaulding", "crocker",
    "old speck", "mansfield", "killington", "camels hump", "camel's hump",
    "ellen", "greylock", "bond", "twin",
}
_NE_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in NE_PEAKS) + r")\b", re.I)


def name_is_summit(name):
    if not name:
        return False
    # Strip a trailing duplicate-suffix digit ("West Bond1", "Trail1") so it
    # doesn't break word-boundary matching.
    name = re.sub(r"\d+\s*$", "", name).strip()
    if POI_WORDS.search(name):
        return False
    return bool(PEAK_WORDS.search(name) or _NE_RE.search(name))

logging.getLogger("caltopo_python").setLevel(logging.ERROR)
logging.basicConfig(level=logging.ERROR)

from caltopo_python import CaltopoSession  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "cts.ini"
ACCOUNT = "kyleg.knutson@gmail.com"
NS = "{http://www.topografix.com/GPX/1/1}"

# v2 regional map IDs (see gpx_consolidation/region_caltopo_maps.md)
REGION_MAPS = {
    "weminuche": "7AQN6TS", "sawatch": "L5VH4BU", "san_juan": "06AR6BF",
    "front": "DLES5CC", "sangre_de_cristo": "VKGB00L", "elk": "1G2G7DM",
    "gore": "6E4GJV2", "mosquito": "LECF68J", "tenmile": "7QE01UK",
    "california": "F5LGTKK", "massachusetts": "3KMUMLE", "new_hampshire": "UDK6ETR",
    "nevada": "AMH9MNK", "europe": "PQFB188", "wyoming": "CLK3609", "utah": "PM8JQ6M",
    "hawaii": "VA473FB", "new_york": "D6CKS21", "oregon": "1CK179R", "vermont": "64P836C",
    "arizona": "EL7D3N3", "maine": "751MCA1", "washington": "U247A11",
}

# mtn-research project maps + other drawn maps (so summit markers match everywhere)
RESEARCH_MAPS = {
    "research_crestolita": "6TKA0RH", "gibbs_loop": "MM66DN4", "research_hunts": "2SCT1B6",
    "research_star": "607Q6C8", "research_savage": "QL51DBE", "research_homestake": "V4D61FV",
    "research_pennsylvania": "P2V1QG5", "research_jacque": "R2NF0S2", "research_brown": "Q2C5650",
    "research_telluride": "6FM1FEK", "research_dolores": "1R09CLT", "school_bus": "0J9LBCS",
    "lost_horse_loop": "DQC173P", "all_map": "C105AEV", "middle_cimarrons": "LRHNVUK",
    "hanson_group": "R7AHHPK", "nja_from_west": "VM98Q5D", "west_cuba_gulch": "8P140C2",
    "jacque": "2V59P1V", "snoden_n2": "C77EC4B", "sultan_grand_turk": "V0DJ6R0",
    "h548": "R3B1J97", "first": "8G650AG",
}

SNAP_M = 40.0


def hav(a, b, c, d):
    R = 6_371_000.0
    dl = math.radians(c - a); do = math.radians(d - b)
    x = math.sin(dl/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(do/2)**2
    return 2*R*math.asin(math.sqrt(min(x, 1.0)))


def load_summits(export_path):
    pts = []
    for w in ET.parse(export_path).getroot().findall(f"{NS}wpt"):
        pts.append((float(w.get("lat")), float(w.get("lon"))))
    return pts


def is_summit(lat, lon, summits):
    for slat, slon in summits:
        if abs(slat - lat) > 0.0006 or abs(slon - lon) > 0.0008:
            continue
        if hav(lat, lon, slat, slon) <= SNAP_M:
            return True
    return False


def restyle_map(map_id, summits, symbol, color, poi_color, apply):
    s = CaltopoSession(domainAndPort="caltopo.com", mapID=map_id,
                       configpath=str(CONFIG_PATH), account=ACCOUNT)
    feats = s.getFeatures(featureClass="Marker") or []
    changed = poi = 0
    for f in feats:
        geom = f.get("geometry") or {}
        c = geom.get("coordinates") or []
        if len(c) < 2:
            continue
        lon, lat = c[0], c[1]
        title = (f.get("properties") or {}).get("title", "")
        if is_summit(lat, lon, summits) or name_is_summit(title):
            if apply:
                s.editFeature(id=f.get("id"), className="Marker",
                              properties={"marker-symbol": symbol, "marker-color": color})
            changed += 1
        else:
            # non-summit POI -> grey dot
            if apply:
                s.editFeature(id=f.get("id"), className="Marker",
                              properties={"marker-symbol": "point", "marker-color": poi_color})
            poi += 1
    return changed, poi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, type=Path, help="14ers peak-export GPX")
    ap.add_argument("--map", help="Single map ID")
    ap.add_argument("--all", action="store_true", help="All region maps")
    ap.add_argument("--research", action="store_true", help="Also include the mtn-research / drawn maps")
    ap.add_argument("--symbol", default="peak", help="CalTopo marker-symbol (default 'peak' = mountain)")
    ap.add_argument("--color", default="#2E78C7", help="summit marker-color hex (default muted blue)")
    ap.add_argument("--poi-color", default="#888888", help="non-summit POI marker-color hex (default grey)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    summits = load_summits(args.export)
    print(f"Loaded {len(summits)} authoritative summits from {args.export.name}")
    if args.all:
        targets = list(REGION_MAPS.items())
        if args.research:
            targets += list(RESEARCH_MAPS.items())
    elif args.research:
        targets = list(RESEARCH_MAPS.items())
    else:
        targets = [("(single)", args.map)]
    mode = "APPLYING" if args.apply else "DRY RUN"
    print(f"[{mode}] summit symbol={args.symbol!r} color={args.color}  POI color={args.poi_color}\n")

    tot_c = tot_p = 0
    for region, mid in targets:
        if not mid:
            continue
        c, p = restyle_map(mid, summits, args.symbol, args.color, args.poi_color, args.apply)
        tot_c += c; tot_p += p
        print(f"  {region:18} {mid}  summit(mtn)={c:4}  POI(grey)={p:4}")
    print(f"\nTotal: {tot_c} summit markers -> blue mountain, {tot_p} POIs -> grey dot.")
    if not args.apply:
        print("Re-run with --apply to write.")


if __name__ == "__main__":
    main()
