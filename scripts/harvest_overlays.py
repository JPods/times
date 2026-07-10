#!/usr/bin/env python3
"""
harvest_overlays.py — Harvest AADT and crash data for all 50 US states.

Data sources:
  AADT:    FHWA HPMS via ArcGIS REST (geo.dot.gov) — free, no key
  Crashes: NHTSA FARS bulk CSV download — free, no key

Output: mesh_mobility/overlays/
  aadt_{st}.geojson          — traffic counts per state
  accidents_{st}.geojson     — fatal crash locations per state
  crash_density_{st}.geojson — crash density per state (grid-aggregated)

Usage:
  python3 harvest_overlays.py --all              # all 50 states
  python3 harvest_overlays.py --state sc         # single state
  python3 harvest_overlays.py --state sc,ok,mn   # multiple states
  python3 harvest_overlays.py --list             # show available states
"""

import argparse
import csv
import io
import json
import math
import os
import sys
import time
import urllib.request
import gzip
import zipfile
from pathlib import Path
from collections import defaultdict

OVERLAY_DIR = Path(__file__).parent.parent / "overlays"
OVERLAY_5TB = Path("/Volumes/Allie/data/overlays")


def _save_overlay(filename, data):
    """Save overlay to both local cache and 5TB if mounted."""
    for d in (OVERLAY_DIR, OVERLAY_5TB):
        try:
            d.mkdir(parents=True, exist_ok=True)
            with open(d / filename, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

# State FIPS → abbreviation
STATES = {
    "01":"al","02":"ak","04":"az","05":"ar","06":"ca","08":"co","09":"ct",
    "10":"de","11":"dc","12":"fl","13":"ga","15":"hi","16":"id","17":"il",
    "18":"in","19":"ia","20":"ks","21":"ky","22":"la","23":"me","24":"md",
    "25":"ma","26":"mi","27":"mn","28":"ms","29":"mo","30":"mt","31":"ne",
    "32":"nv","33":"nh","34":"nj","35":"nm","36":"ny","37":"nc","38":"nd",
    "39":"oh","40":"ok","41":"or","42":"pa","44":"ri","45":"sc","46":"sd",
    "47":"tn","48":"tx","49":"ut","50":"vt","51":"va","53":"wa","54":"wv",
    "55":"wi","56":"wy",
}
ABBR_TO_FIPS = {v: k for k, v in STATES.items()}


def _get_json(url, timeout=90):
    """Fetch URL, handle gzip, return parsed JSON or None."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "JPods/MeshMobility-Harvester",
            "Accept-Encoding": "gzip, identity",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if raw[:2] == b'\x1f\x8b':
                raw = gzip.decompress(raw)
            return json.loads(raw.decode())
    except Exception as e:
        print(f"    fetch error: {e}")
        return None


def _get_bytes(url, timeout=120):
    """Fetch URL, return raw bytes or None."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "JPods/MeshMobility-Harvester",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"    download error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# AADT — FHWA HPMS ArcGIS REST service
#   Service: https://geo.dot.gov/server/rest/services/Hosted/HPMS_FULL_{ST}_{YEAR}/FeatureServer/0
#   Fields: aadt (int), route_id, routename, f_system
#   Geometry: polylines (paths) — we extract midpoints
# ─────────────────────────────────────────────────────────────────────────────

def harvest_aadt(fips, abbr):
    """Fetch AADT data from FHWA HPMS for a state."""
    features = []
    st = abbr.upper()

    for year in (2024, 2023, 2022, 2020):
        base = (
            f"https://geo.dot.gov/server/rest/services/Hosted/"
            f"HPMS_FULL_{st}_{year}/FeatureServer/0/query"
        )
        params = (
            f"?where=aadt%3E%3D5000"
            f"&outFields=aadt,route_id,routename,f_system"
            f"&returnGeometry=true"
            f"&outSR=4326"
            f"&f=json"
            f"&resultRecordCount=4000"
        )
        url = base + params
        print(f"  Trying HPMS {st} {year}...")
        data = _get_json(url)

        if data and "features" in data and len(data["features"]) > 0:
            features = data["features"]
            total = data.get("properties", {}).get("exceededTransferLimit", False)
            print(f"  Got {len(features)} AADT records from {year}" +
                  (" (transfer limit reached)" if total else ""))

            # If we hit the limit, paginate
            if total or len(features) >= 3900:
                offset = len(features)
                while True:
                    page_url = base + params + f"&resultOffset={offset}"
                    page = _get_json(page_url)
                    if not page or "features" not in page or len(page["features"]) == 0:
                        break
                    features.extend(page["features"])
                    print(f"    ... page: +{len(page['features'])} (total {len(features)})")
                    offset += len(page["features"])
                    if not page.get("properties", {}).get("exceededTransferLimit", False):
                        break
            break
        elif data and "error" in data:
            print(f"    Service error: {data['error'].get('message', '')}")

    if not features:
        print(f"  No AADT data found for {abbr}")
        return 0

    # Convert polylines to point features (midpoint of each segment)
    geojson_features = []
    seen = set()  # deduplicate by grid cell
    for feat in features:
        attrs = feat.get("attributes", {})
        geom = feat.get("geometry", {})
        aadt = attrs.get("aadt", 0)
        if not aadt or aadt < 5000:
            continue

        route = attrs.get("routename") or attrs.get("route_id") or ""
        tier = "core" if aadt >= 10000 else "secondary"

        # Extract midpoint from polyline
        lat, lon = None, None
        paths = geom.get("paths", [])
        if paths and paths[0]:
            path = paths[0]
            mid = path[len(path) // 2]
            lon, lat = mid[0], mid[1]
        elif "x" in geom and "y" in geom:
            lon, lat = geom["x"], geom["y"]

        if lat is None or lon is None:
            continue

        # Deduplicate: snap to ~500m grid
        gkey = (round(lat * 200) / 200, round(lon * 200) / 200)
        if gkey in seen:
            continue
        seen.add(gkey)

        geojson_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"aadt": aadt, "route_name": route, "tier": tier},
        })

    if not geojson_features:
        print(f"  No usable AADT features for {abbr}")
        return 0

    geojson = {"type": "FeatureCollection", "features": geojson_features}
    _save_overlay(f"aadt_{abbr}.geojson", geojson)
    print(f"  ✓ aadt_{abbr}.geojson: {len(geojson_features)} records")
    return len(geojson_features)


# ─────────────────────────────────────────────────────────────────────────────
# FARS — Fatal crash data from NHTSA bulk CSV downloads
#   URL: https://static.nhtsa.gov/nhtsa/downloads/FARS/{YEAR}/National/FARS{YEAR}NationalCSV.zip
#   Contains ACCIDENT.CSV with LATITUDE, LONGITUD, FATALS, STATE, COUNTY, etc.
# ─────────────────────────────────────────────────────────────────────────────

def harvest_fars(fips, abbr):
    """Fetch FARS fatal crash data for a state from bulk CSV downloads."""
    state_num = int(fips)
    all_crashes = []

    for year in (2022, 2021, 2020, 2019):
        url = f"https://static.nhtsa.gov/nhtsa/downloads/FARS/{year}/National/FARS{year}NationalCSV.zip"
        print(f"  FARS {year} (downloading ZIP)...")
        raw = _get_bytes(url, timeout=180)
        if not raw:
            continue

        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
            # Find the accident file (may be in a subdirectory, case varies)
            acc_name = None
            for name in zf.namelist():
                basename = name.split("/")[-1].upper()
                if basename.startswith("ACCIDENT") and basename.endswith(".CSV"):
                    acc_name = name
                    break
            if not acc_name:
                print(f"    No ACCIDENT.CSV in ZIP")
                continue

            with zf.open(acc_name) as csvf:
                reader = csv.DictReader(io.TextIOWrapper(csvf, encoding="utf-8-sig", errors="replace"))
                for row in reader:
                    try:
                        st = int(row.get("STATE", row.get("state", row.get("\ufeffSTATE", 0))))
                    except (ValueError, TypeError):
                        continue
                    if st != state_num:
                        continue

                    try:
                        lat = float(row.get("LATITUDE", row.get("latitude", 0)))
                        lon = float(row.get("LONGITUD", row.get("longitud", 0)))
                        fatals = int(row.get("FATALS", row.get("fatals", 1)))
                    except (ValueError, TypeError):
                        continue

                    if lat == 0 or lon == 0 or abs(lat) > 90 or abs(lon) > 180:
                        continue
                    # FARS stores lon as positive for US — need negative
                    if lon > 0:
                        lon = -lon

                    all_crashes.append({
                        "lat": lat, "lon": lon, "fatals": fatals, "year": year,
                        "county": row.get("COUNTYNAME", row.get("countyname", "")),
                        "road": row.get("TWAY_ID", row.get("tway_id", "")),
                        "weather": row.get("WEATHERNAME", row.get("weathername", "")),
                        "light": row.get("LGT_CONDNAME", row.get("lgt_condname", "")),
                        "manner": row.get("MAN_COLLNAME", row.get("man_collname", "")),
                        "month": row.get("MONTHNAME", row.get("monthname", "")),
                        "hour": row.get("HOUR", row.get("hour", "")),
                    })

            print(f"    {year}: {sum(1 for c in all_crashes if c['year']==year)} crashes in {abbr.upper()}")

        except Exception as e:
            print(f"    ZIP processing error: {e}")
            continue

    if not all_crashes:
        print(f"  No FARS data for {abbr}")
        return 0

    # Build fatal crash features
    features = []
    for c in all_crashes:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
            "properties": {
                "fatals": c["fatals"],
                "year": c["year"],
                "county": c["county"],
                "road": c["road"],
                "weather": c["weather"],
                "light": c["light"],
                "manner": c["manner"],
                "month": c["month"],
                "hour": c["hour"],
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}
    _save_overlay(f"accidents_{abbr}.geojson", geojson)
    print(f"  ✓ accidents_{abbr}.geojson: {len(features)} fatal crashes")

    # Build crash density grid (200m cells)
    density_features = _build_crash_density(features)
    if density_features:
        _save_overlay(f"crash_density_{abbr}.geojson",
                      {"type": "FeatureCollection", "features": density_features})
        print(f"  ✓ crash_density_{abbr}.geojson: {len(density_features)} grid cells")

    return len(features)


def _build_crash_density(features, cell_m=200):
    """Aggregate crash points into a grid of density cells."""
    cell_deg = cell_m / 111000  # ~0.0018°

    grid = defaultdict(lambda: {"crashes": 0, "injury": 0, "fatal": 0, "pedestrian": 0})
    for f in features:
        lon, lat = f["geometry"]["coordinates"]
        gx = round(lon / cell_deg) * cell_deg
        gy = round(lat / cell_deg) * cell_deg
        key = (round(gx, 6), round(gy, 6))
        fatals = f["properties"].get("fatals", 1)
        grid[key]["crashes"] += 1
        grid[key]["fatal"] += fatals
        grid[key]["injury"] += 1

    density_features = []
    for (lon, lat), counts in grid.items():
        density = round(counts["crashes"] / 4, 1)  # 4 years of data
        density_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "crashes": counts["crashes"],
                "injury": counts["injury"],
                "fatal": counts["fatal"],
                "pedestrian": counts["pedestrian"],
                "density": density,
            },
        })

    return density_features


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def process_state(abbr):
    """Harvest all overlay data for a single state."""
    fips = ABBR_TO_FIPS.get(abbr)
    if not fips:
        print(f"Unknown state: {abbr}")
        return

    print(f"\n{'='*60}")
    print(f"  {abbr.upper()} (FIPS {fips})")
    print(f"{'='*60}")

    harvest_aadt(fips, abbr)
    harvest_fars(fips, abbr)
    print(f"  Done: {abbr.upper()}")


def main():
    parser = argparse.ArgumentParser(description="Harvest AADT and crash data for US states")
    parser.add_argument("--state", help="State abbreviation(s), comma-separated (e.g., sc,ok,mn)")
    parser.add_argument("--all", action="store_true", help="All 50 states + DC")
    parser.add_argument("--list", action="store_true", help="List available states")
    parser.add_argument("--aadt-only", action="store_true", help="Only harvest AADT")
    parser.add_argument("--fars-only", action="store_true", help="Only harvest FARS crashes")
    args = parser.parse_args()

    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        for fips, abbr in sorted(STATES.items(), key=lambda x: x[1]):
            path_a = OVERLAY_DIR / f"aadt_{abbr}.geojson"
            path_c = OVERLAY_DIR / f"accidents_{abbr}.geojson"
            path_d = OVERLAY_DIR / f"crash_density_{abbr}.geojson"
            status_a = "✓" if path_a.exists() and path_a.stat().st_size > 10 else " "
            status_c = "✓" if path_c.exists() and path_c.stat().st_size > 10 else " "
            status_d = "✓" if path_d.exists() and path_d.stat().st_size > 10 else " "
            print(f"  {abbr}  AADT[{status_a}]  Crashes[{status_c}]  Density[{status_d}]")
        return

    if args.all:
        states = sorted(STATES.values())
    elif args.state:
        states = [s.strip().lower() for s in args.state.split(",") if s.strip()]
    else:
        parser.print_help()
        return

    for abbr in states:
        fips = ABBR_TO_FIPS.get(abbr)
        if not fips:
            print(f"Unknown state: {abbr}")
            continue
        print(f"\n{'='*60}")
        print(f"  {abbr.upper()} (FIPS {fips})")
        print(f"{'='*60}")
        if not args.fars_only:
            harvest_aadt(fips, abbr)
        if not args.aadt_only:
            harvest_fars(fips, abbr)
        print(f"  Done: {abbr.upper()}")
        time.sleep(1)  # Rate limit between states


if __name__ == "__main__":
    main()
