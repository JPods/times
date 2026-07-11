#!/usr/bin/env python3
"""
census_overlays.py — Pull Census ACS data and generate heatmap GeoJSON overlays.

Generates overlay files for MeshMobility:
  - population_density_{state}.geojson
  - property_values_{state}.geojson
  - jobs_{state}.geojson

Usage:
  python3 census_overlays.py --city Greenville
  python3 census_overlays.py --all
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

CRED_PATH = Path.home() / "Allie" / "config" / "wc_credentials.json"
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
            pass  # 5TB may not be mounted

CITIES = {
    "Greenville": {"state": "45", "county": "045", "center": [34.85, -82.40]},
    "Tulsa":      {"state": "40", "county": "143", "center": [36.15, -95.99]},
    "Bloomington":{"state": "27", "county": "053", "center": [44.84, -93.30]},
}
STATE_ABBR = {"45": "sc", "40": "ok", "27": "mn"}

# Full state FIPS → abbreviation map for any US location
STATE_FIPS_TO_ABBR = {
    "01":"al","02":"ak","04":"az","05":"ar","06":"ca","08":"co","09":"ct",
    "10":"de","11":"dc","12":"fl","13":"ga","15":"hi","16":"id","17":"il",
    "18":"in","19":"ia","20":"ks","21":"ky","22":"la","23":"me","24":"md",
    "25":"ma","26":"mi","27":"mn","28":"ms","29":"mo","30":"mt","31":"ne",
    "32":"nv","33":"nh","34":"nj","35":"nm","36":"ny","37":"nc","38":"nd",
    "39":"oh","40":"ok","41":"or","42":"pa","44":"ri","45":"sc","46":"sd",
    "47":"tn","48":"tx","49":"ut","50":"vt","51":"va","53":"wa","54":"wv",
    "55":"wi","56":"wy",
}


def fips_from_latlon(lat, lon):
    """Look up state + county FIPS from lat/lon using the FCC Area API (free, no key)."""
    url = f"https://geo.fcc.gov/api/census/area?lat={lat}&lon={lon}&format=json"
    result = census_get(url)
    if not result or "results" not in result or not result["results"]:
        return None, None
    r = result["results"][0]
    state_fips = r.get("state_fips", "")
    county_fips = r.get("county_fips", "")
    # FCC returns 5-digit county_fips (state+county) — strip state prefix to get 3-digit
    if len(county_fips) == 5 and county_fips.startswith(state_fips):
        county_fips = county_fips[len(state_fips):]
    return state_fips, county_fips


def process_location(lat, lon, api_key, label=None):
    """Fetch census overlays for any US lat/lon. Returns the city key used for filenames."""
    state_fips, county_fips = fips_from_latlon(lat, lon)
    if not state_fips or not county_fips:
        print(f"  Could not determine FIPS for ({lat}, {lon})")
        return None

    abbr = STATE_FIPS_TO_ABBR.get(state_fips)
    if not abbr:
        print(f"  Unknown state FIPS: {state_fips}")
        return None

    # Use state_county as the city key (e.g., "tx_113")
    city_key = f"{abbr}_{county_fips}" if label is None else label

    print(f"\n{'='*60}")
    print(f"  Location: ({lat:.4f}, {lon:.4f}) → state={state_fips} ({abbr}), county={county_fips}")
    print(f"  Key: {city_key}")
    print(f"{'='*60}")

    centroids = fetch_tract_centroids(state_fips, county_fips)
    if not centroids:
        print("  FAILED to fetch centroids. Skipping.")
        return None

    # Population density
    print("  Fetching population...")
    pop = fetch_acs_data(state_fips, county_fips, "B01003_001E", api_key)
    if pop:
        geo = build_overlay(pop, centroids, 0, "population_density", state_fips, county_fips, compute_density=True)
        if geo and geo["features"]:
            _save_overlay(f"population_density_{city_key}.geojson", geo)
            _save_overlay("population_density.geojson", geo)
            print(f"  ✓ population_density_{city_key}: {len(geo['features'])} tracts")

    # Property values
    print("  Fetching property values...")
    prop = fetch_acs_data(state_fips, county_fips, "B25077_001E", api_key)
    if prop:
        geo = build_overlay(prop, centroids, 0, "property_values", state_fips, county_fips)
        if geo and geo["features"]:
            _save_overlay(f"property_values_{city_key}.geojson", geo)
            _save_overlay("property_values.geojson", geo)
            print(f"  ✓ property_values_{city_key}: {len(geo['features'])} tracts")

    # Jobs
    print("  Fetching employment...")
    jobs = fetch_acs_data(state_fips, county_fips, "B23025_004E", api_key)
    if jobs:
        geo = build_overlay(jobs, centroids, 0, "jobs", state_fips, county_fips)
        if geo and geo["features"]:
            _save_overlay(f"jobs_{city_key}.geojson", geo)
            _save_overlay("jobs.geojson", geo)
            print(f"  ✓ jobs_{city_key}: {len(geo['features'])} tracts")

    print(f"  Done: {city_key}")
    return city_key


def get_api_key():
    with open(CRED_PATH) as f:
        return json.load(f)["census_api_key"]


def census_get(url):
    import gzip
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "JPods/MeshMobility",
            "Accept-Encoding": "gzip, identity",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            # Handle gzip if server sends it
            if raw[:2] == b'\x1f\x8b':
                raw = gzip.decompress(raw)
            return json.loads(raw.decode())
    except Exception as e:
        print(f"  Error: {e}")
        return None


def fetch_acs_data(state, county, variables, api_key):
    """Fetch ACS 5-year data by tract. Returns header + rows."""
    url = (
        f"https://api.census.gov/data/2022/acs/acs5"
        f"?get={variables},NAME"
        f"&for=tract:*&in=state:{state}%20county:{county}"
        f"&key={api_key}"
    )
    return census_get(url)


def fetch_tract_centroids(state, county):
    """Fetch tract centroids + area from TIGERweb. Returns dict: tract → {lat, lon, area_m2}."""
    tiger_url = (
        f"https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/8/query"
        f"?where=STATE%3D%27{state}%27+AND+COUNTY%3D%27{county}%27"
        f"&outFields=TRACT,AREALAND,CENTLAT,CENTLON"
        f"&returnGeometry=false&f=json"
    )
    print(f"  Fetching tract centroids...")
    result = census_get(tiger_url)
    if not result or "features" not in result:
        print(f"  TIGERweb response keys: {list(result.keys()) if result else 'None'}")
        return None

    centroids = {}
    for feat in result["features"]:
        attrs = feat["attributes"]
        tract = attrs.get("TRACT", "")
        try:
            lat = float(attrs.get("CENTLAT", 0))
            lon = float(attrs.get("CENTLON", 0))
            area = int(attrs.get("AREALAND", 1))
        except (ValueError, TypeError):
            continue
        if lat and lon:
            centroids[tract] = {"lat": lat, "lon": lon, "area_m2": area}

    print(f"  Got {len(centroids)} tract centroids")
    return centroids


def build_overlay(acs_data, centroids, value_idx, layer_name, state, county, compute_density=False):
    """Build heatmap GeoJSON from ACS data + centroids."""
    if not acs_data or not centroids:
        return None

    header = acs_data[0]
    features = []

    for row in acs_data[1:]:
        try:
            val = int(row[value_idx]) if row[value_idx] else 0
        except (ValueError, TypeError):
            val = 0
        if val <= 0:
            continue

        tract = row[header.index("tract")]
        centroid = centroids.get(tract)
        if not centroid:
            continue

        intensity = val
        props = {
            "tract": tract,
            "value": val,
            "name": row[header.index("NAME")] if "NAME" in header else "",
            "layer": layer_name,
        }

        if compute_density and centroid["area_m2"] > 0:
            area_mi2 = centroid["area_m2"] / 2589988.11
            density = round(val / max(area_mi2, 0.01))
            props["density"] = density
            intensity = density

        props["intensity"] = intensity

        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Point",
                "coordinates": [centroid["lon"], centroid["lat"]],
            },
        })

    return {
        "type": "FeatureCollection",
        "metadata": {"layer": layer_name, "count": len(features)},
        "features": features,
    }


def process_city(city_name, api_key):
    info = CITIES.get(city_name)
    if not info:
        print(f"Unknown city: {city_name}")
        return

    state, county = info["state"], info["county"]
    abbr = STATE_ABBR[state]

    print(f"\n{'='*60}")
    print(f"  {city_name} (state={state}, county={county})")
    print(f"{'='*60}")

    # Fetch tract centroids
    centroids = fetch_tract_centroids(state, county)
    if not centroids:
        print("  FAILED to fetch centroids. Skipping.")
        return

    # Population density (B01003_001E = total population)
    print("  Fetching population...")
    pop = fetch_acs_data(state, county, "B01003_001E", api_key)
    if pop:
        geo = build_overlay(pop, centroids, 0, "population_density", state, county, compute_density=True)
        if geo and geo["features"]:
            _save_overlay(f"population_density_{abbr}.geojson", geo)
            print(f"  ✓ population_density_{abbr}: {len(geo['features'])} tracts")

    # Property values (B25077_001E = median home value)
    print("  Fetching property values...")
    prop = fetch_acs_data(state, county, "B25077_001E", api_key)
    if prop:
        geo = build_overlay(prop, centroids, 0, "property_values", state, county)
        if geo and geo["features"]:
            _save_overlay(f"property_values_{abbr}.geojson", geo)
            print(f"  ✓ property_values_{abbr}: {len(geo['features'])} tracts")

    # Jobs (B23025_004E = employed civilians 16+)
    print("  Fetching employment...")
    jobs = fetch_acs_data(state, county, "B23025_004E", api_key)
    if jobs:
        geo = build_overlay(jobs, centroids, 0, "jobs", state, county)
        if geo and geo["features"]:
            _save_overlay(f"jobs_{abbr}.geojson", geo)
            print(f"  ✓ jobs_{abbr}: {len(geo['features'])} tracts")

    print(f"  Done: {city_name}")


def process_state(state_fips, api_key):
    """Fetch census overlays for an entire state (all counties, all tracts)."""
    abbr = STATE_FIPS_TO_ABBR.get(state_fips)
    if not abbr:
        print(f"Unknown state FIPS: {state_fips}")
        return

    # Skip if already done
    if (OVERLAY_DIR / f"population_density_{abbr}.geojson").exists():
        print(f"  {abbr.upper()}: already exists, skipping")
        return

    print(f"\n{'='*60}")
    print(f"  {abbr.upper()} (state FIPS={state_fips}) — statewide")
    print(f"{'='*60}")

    # Fetch tract centroids for all counties (county="*" is not supported by TIGERweb)
    # Instead, fetch county list first, then centroids per county
    centroids = {}
    try:
        county_url = (f"https://api.census.gov/data/2022/acs/acs5?"
                      f"get=NAME&for=county:*&in=state:{state_fips}&key={api_key}")
        county_data = census_get(county_url)
        if county_data and len(county_data) > 1:
            counties = [row[-1] for row in county_data[1:]]
        else:
            counties = []
    except Exception as e:
        print(f"  FAILED to list counties: {e}")
        return

    print(f"  {len(counties)} counties")
    for ci, county in enumerate(counties):
        try:
            c = fetch_tract_centroids(state_fips, county)
            if c:
                centroids.update(c)
        except Exception:
            pass
        if (ci + 1) % 20 == 0:
            print(f"    centroids: {ci+1}/{len(counties)} counties, {len(centroids)} tracts")

    if not centroids:
        print("  FAILED to fetch any centroids. Skipping.")
        return
    print(f"  {len(centroids)} total tracts")

    # Population density
    print("  Fetching population...")
    try:
        pop_url = (f"https://api.census.gov/data/2022/acs/acs5?"
                   f"get=NAME,B01003_001E&for=tract:*&in=state:{state_fips}&key={api_key}")
        pop = census_get(pop_url)
        if pop and len(pop) > 1:
            geo = build_overlay(pop, centroids, 1, "population_density",
                                state_fips, "*", compute_density=True)
            if geo and geo["features"]:
                _save_overlay(f"population_density_{abbr}.geojson", geo)
                print(f"  population_density_{abbr}: {len(geo['features'])} tracts")
    except Exception as e:
        print(f"  population FAILED: {e}")

    # Property values
    print("  Fetching property values...")
    try:
        prop_url = (f"https://api.census.gov/data/2022/acs/acs5?"
                    f"get=NAME,B25077_001E&for=tract:*&in=state:{state_fips}&key={api_key}")
        prop = census_get(prop_url)
        if prop and len(prop) > 1:
            geo = build_overlay(prop, centroids, 1, "property_values",
                                state_fips, "*")
            if geo and geo["features"]:
                _save_overlay(f"property_values_{abbr}.geojson", geo)
                print(f"  property_values_{abbr}: {len(geo['features'])} tracts")
    except Exception as e:
        print(f"  property_values FAILED: {e}")

    # Jobs
    print("  Fetching employment...")
    try:
        jobs_url = (f"https://api.census.gov/data/2022/acs/acs5?"
                    f"get=NAME,B23025_004E&for=tract:*&in=state:{state_fips}&key={api_key}")
        jobs = census_get(jobs_url)
        if jobs and len(jobs) > 1:
            geo = build_overlay(jobs, centroids, 1, "jobs",
                                state_fips, "*")
            if geo and geo["features"]:
                _save_overlay(f"jobs_{abbr}.geojson", geo)
                print(f"  jobs_{abbr}: {len(geo['features'])} tracts")
    except Exception as e:
        print(f"  jobs FAILED: {e}")

    print(f"  Done: {abbr.upper()}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", help="Greenville, Tulsa, or Bloomington")
    parser.add_argument("--state", help="State FIPS code (e.g. 48 for TX)")
    parser.add_argument("--all-states", action="store_true",
                        help="Process all 51 states (skips existing)")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    api_key = get_api_key()

    if args.all_states:
        for fips in sorted(STATE_FIPS_TO_ABBR.keys()):
            try:
                process_state(fips, api_key)
            except Exception as e:
                print(f"  {STATE_FIPS_TO_ABBR[fips].upper()} FAILED: {e}")
    elif args.state:
        process_state(args.state, api_key)
    elif args.all:
        for city in CITIES:
            process_city(city, api_key)
    elif args.city:
        process_city(args.city, api_key)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
