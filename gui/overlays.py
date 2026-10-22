"""
mesh_mobility.gui.overlays
============================
Overlay data endpoints: AADT, accidents, crash density, census data,
city switching, and overlay state management.

Reads from CrashHarvester library (read-only). Harvesting is a separate program.

Extracted from api.py in Round 3 refactoring (2026-07-15).
"""

from __future__ import annotations

import logging
import os
import shutil

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
import sys
_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

# ---------------------------------------------------------------------------
# Overlay data — reads from CrashHarvester library
# Harvesting is a separate program. MeshMobility is read-only.
# ---------------------------------------------------------------------------
from CrashHarvester.reader import MobilityData
_md = MobilityData()

# Crash data status — contact info for missing/weak states
import json as _json
_crash_status = {}
_crash_status_path = os.path.join(os.path.dirname(_rt_dir), "overlays", "crash-data-status.json")
if os.path.exists(_crash_status_path):
    try:
        with open(_crash_status_path) as _f:
            _crash_status = _json.load(_f)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Shared state imports
# ---------------------------------------------------------------------------
from mesh_mobility.gui.state import (
    _state,
    ensure_session, set_session_cookie, auto_push_undo,
    noelle_log,
)

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
overlays_bp = Blueprint("overlays", __name__, url_prefix="/api")

overlays_bp.before_request(ensure_session)
overlays_bp.after_request(set_session_cookie)
overlays_bp.before_request(auto_push_undo)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_state():
    """Detect state abbreviation from request params or network centroid."""
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        net = _state.get("network")
        if net:
            lats = [n.lat for n in net.nodes.values() if n.lat]
            lons = [n.lon for n in net.nodes.values() if n.lon]
            if lats:
                lat = sum(lats) / len(lats)
                lon = sum(lons) / len(lons)
    if lat is None:
        return None, None, None
    try:
        from mesh_mobility.scripts.census_overlays import fips_from_latlon, STATE_FIPS_TO_ABBR
        state_fips, _ = fips_from_latlon(lat, lon)
        if state_fips:
            return STATE_FIPS_TO_ABBR.get(state_fips), lat, lon
    except Exception:
        pass
    return None, lat, lon


def _get_overlay_center_radius():
    """Extract center lat/lon and radius from request params or network centroid."""
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    radius = request.args.get("radius", default=10, type=float)
    if lat is not None and lon is not None:
        return lat, lon, radius
    net = _state.get("network")
    if net:
        lats = [n.lat for n in net.nodes.values() if n.lat]
        lons = [n.lon for n in net.nodes.values() if n.lon]
        if lats:
            return sum(lats) / len(lats), sum(lons) / len(lons), radius
    return None, None, radius


# ---------------------------------------------------------------------------
# Overlay endpoints
# ---------------------------------------------------------------------------

@overlays_bp.get("/overlays/aadt")
def overlay_aadt():
    """HPMS traffic data from CrashHarvester library."""
    center_lat, center_lon, radius = _get_overlay_center_radius()
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state — place a station first"}), 404
    data = _md.get_traffic(state, center_lat, center_lon, radius)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No traffic data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --hpms {state}"}), 404


@overlays_bp.get("/overlays/accidents")
def overlay_accidents():
    """FARS fatal crash data from CrashHarvester library."""
    center_lat, center_lon, radius = _get_overlay_center_radius()
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state — place a station first"}), 404
    data = _md.get_fatals(state, center_lat, center_lon, radius)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No fatal crash data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --fars {state}"}), 404


@overlays_bp.post("/overlays/active")
def set_active_overlays():
    """Browser tells server which overlay files are loaded.
    Saved into the .jpd so opening the file restores the right city data."""
    data = request.json or {}
    _state["overlays"] = data
    return jsonify({"ok": True})


@overlays_bp.get("/overlays/active")
def get_active_overlays():
    """Return current overlay config (from loaded .jpd or set by browser)."""
    return jsonify(_state.get("overlays") or {})


@overlays_bp.post("/overlays/signal_missing")
def overlay_signal_missing():
    """User signals that a data layer is missing for their location.
    Logs it so we know which cities/states need data harvesting."""
    data = request.json or {}
    layer = data.get("layer", "unknown")
    lat = data.get("lat")
    lon = data.get("lon")
    log.warning(f"SIGNAL MISSING DATA: layer={layer} lat={lat} lon={lon}")
    # Write to Allie's inbox for nightly processing
    try:
        import pathlib
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        inbox = pathlib.Path.home() / 'Allie' / 'process' / 'inbox'
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f'{ts}-signal-missing-{layer}.md'
        path.write_text(
            f"# SIGNAL — Missing overlay data\n\n"
            f"layer: {layer}\n"
            f"lat: {lat}\n"
            f"lon: {lon}\n"
            f"dt: {datetime.now(timezone.utc).isoformat()}\n"
        )
    except Exception:
        pass
    return jsonify({"message": f"Noted: {layer} data missing at ({lat:.3f}, {lon:.3f}). Will prioritize harvesting."})


@overlays_bp.post("/overlays/fetch")
def overlay_fetch_all():
    """Check CrashHarvester library for available data at this location.
    Reports what's available and what's missing. Does not harvest."""
    data = request.json or {}
    center_lat = center_lon = None

    net = _state.get("network")
    if net:
        lats = [n.lat for n in net.nodes.values() if n.lat]
        lons = [n.lon for n in net.nodes.values() if n.lon]
        if lats:
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)
    if center_lat is None and "lat" in data and "lon" in data:
        center_lat = float(data["lat"])
        center_lon = float(data["lon"])
    if center_lat is None:
        return jsonify({"error": "No location — place a station or search for a city first"}), 400

    noelle_log("overlay_fetch", {"lat": center_lat, "lon": center_lon})

    # Detect state from the coordinates we already resolved
    state_abbr = None
    try:
        from mesh_mobility.scripts.census_overlays import fips_from_latlon, STATE_FIPS_TO_ABBR
        state_fips, _ = fips_from_latlon(center_lat, center_lon)
        if state_fips:
            state_abbr = STATE_FIPS_TO_ABBR.get(state_fips)
    except Exception:
        pass

    fetched = []
    missing = []

    library_types = {
        "traffic": "aadt",
        "fatal": "accidents",
        "crash": "crash_density",
        "population_density": "population_density",
        "property_values": "property_values",
        "jobs": "jobs",
        "transit": "transit",
    }

    if state_abbr:
        available = _md.available_types(state_abbr)
        for lib_type, button_name in library_types.items():
            if lib_type in available:
                fetched.append(button_name)
            else:
                missing.append(button_name)
        log.info(f"Library: {state_abbr.upper()} available={fetched}, missing={missing}")

    return jsonify({
        "fetched": fetched,
        "missing": missing,
        "location": {"lat": center_lat, "lon": center_lon},
        "state": state_abbr,
    })


@overlays_bp.get("/overlays/cities")
def overlay_cities():
    """List available overlay city datasets."""
    overlay_dir = os.path.join(_rt_dir, "overlays")
    cities = set()
    for fname in os.listdir(overlay_dir):
        if fname.startswith("aadt_") and fname.endswith(".geojson"):
            city = fname[5:-8]  # strip "aadt_" and ".geojson"
            cities.add(city)
    result = {}
    for city in sorted(cities):
        result[city] = {
            "aadt": os.path.exists(
                os.path.join(overlay_dir, f"aadt_{city}.geojson")),
            "accidents": os.path.exists(
                os.path.join(overlay_dir, f"accidents_{city}.geojson")),
            "crash_density": os.path.exists(
                os.path.join(overlay_dir, f"crash_density_{city}.geojson")),
        }
    return jsonify(result)


@overlays_bp.post("/overlays/city/<city>")
def switch_overlay_city(city):
    """Switch all overlays to a specific city dataset.

    Copies aadt_{city}.geojson → aadt.geojson, etc.
    Records the city in _state["overlays"] so it saves with the .jpd.
    """
    overlay_dir = os.path.join(_rt_dir, "overlays")
    aadt_src = os.path.join(overlay_dir, f"aadt_{city}.geojson")
    if not os.path.exists(aadt_src):
        return jsonify({"error": f"No overlay data for city '{city}'"}), 404

    switched = []
    for prefix in ("aadt", "accidents", "crash_density", "population_density", "property_values", "jobs"):
        src = os.path.join(overlay_dir, f"{prefix}_{city}.geojson")
        dst = os.path.join(overlay_dir, f"{prefix}.geojson")
        if os.path.exists(src):
            shutil.copy2(src, dst)
            switched.append(prefix)

    _state["overlays"] = {"city": city, "files": switched}
    return jsonify({"city": city, "switched": switched})


@overlays_bp.get("/overlays/crash_density")
def overlay_crash_density():
    """All-severity crash data from CrashHarvester library.
    Checks data quality — warns if it's just repackaged fatal data."""
    center_lat, center_lon, radius = _get_overlay_center_radius()
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state — place a station first"}), 404
    data = _md.get_crashes(state, center_lat, center_lon, radius)
    if not data or not data.get("features"):
        # Detect which county is missing
        county_fips, county_name = _detect_county(center_lat, center_lon)
        # Check if we have ANY state data (other counties)
        all_state = _md.get_crashes(state)
        has_partial = bool(all_state and all_state.get("features"))
        error_msg = f"No crash data for {county_name or 'this area'}, {state.upper()}."
        if has_partial:
            error_msg += f" Data exists for other {state.upper()} counties but not this one."
        # Check if we have contact info for this state
        missing = _crash_status.get("missing_states", {}).get(state.upper(), {})
        resp = {
            "error": error_msg,
            "state": state.upper(),
            "county_fips": county_fips,
            "county_name": county_name,
            "has_partial": has_partial,
            "lat": center_lat,
            "lon": center_lon,
        }
        if missing:
            resp["contact"] = missing
        return jsonify(resp), 404

    # Quality check: if crashes ≈ fatal, this is just FARS repackaged, not real all-severity
    sample = data["features"][:200]
    if sample:
        total_crashes = sum(f["properties"].get("crashes", 0) for f in sample)
        total_fatal = sum(f["properties"].get("fatal", 0) for f in sample)
        if total_crashes > 0 and total_fatal > 0 and total_crashes < total_fatal * 3:
            log.warning(f"Crash data for {state.upper()} appears to be repackaged FARS — "
                        f"crashes/fatal ratio = {total_crashes/total_fatal:.1f} (expected >50)")
            return jsonify({"error": f"All-severity crash data for {state.upper()} is not available. "
                            f"Current data is only fatal crashes repackaged. "
                            f"Use the ! button to signal this state needs real DOT crash data."}), 404

    return jsonify(data)


@overlays_bp.get("/overlays/transit")
def overlay_transit():
    """Transit rail/subway stations from CrashHarvester library."""
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state — place a station first"}), 404
    data = _md.get_transit(state)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No transit data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --transit {state}"}), 404


@overlays_bp.get("/overlays/mobility")
def overlay_mobility():
    """Cell mobility data — not yet in CrashHarvester library."""
    return jsonify({"error": "Mobility data not yet harvested"}), 404


@overlays_bp.get("/overlays/custom_points")
def get_custom_points():
    """Return saved custom points from the current session/jpd."""
    points = _state.get("custom_points")
    if points:
        return jsonify(points)
    return jsonify([])


@overlays_bp.post("/overlays/custom_points")
def set_custom_points():
    """Save custom points to session (persists with .jpd save)."""
    data = request.json
    if not isinstance(data, list):
        return jsonify({"error": "Expected JSON array of {lat, lon, label}"}), 400
    _state["custom_points"] = data
    return jsonify({"ok": True, "count": len(data)})


@overlays_bp.get("/overlays/custom_points/presets")
def list_custom_presets():
    """List available preset point files in overlays/ directory."""
    import json as json_mod
    overlay_dir = os.path.join(_rt_dir, "overlays")
    presets = []
    for fname in sorted(os.listdir(overlay_dir)):
        if fname.endswith(".json") and not fname.startswith(("aadt", "accidents", "crash", "population", "property", "jobs")):
            path = os.path.join(overlay_dir, fname)
            try:
                with open(path) as f:
                    data = json_mod.load(f)
                count = len(data) if isinstance(data, list) else 0
                presets.append({"file": fname, "name": fname[:-5].replace("_", " ").title(), "count": count})
            except Exception:
                pass
    return jsonify(presets)


@overlays_bp.get("/overlays/custom_points/preset/<filename>")
def load_custom_preset(filename):
    """Load a preset point file."""
    import json as json_mod
    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400
    overlay_dir = os.path.join(_rt_dir, "overlays")
    path = os.path.join(overlay_dir, filename)
    if not os.path.exists(path):
        return jsonify({"error": f"File not found: {filename}"}), 404
    with open(path) as f:
        data = json_mod.load(f)
    if isinstance(data, list):
        _state["custom_points"] = data
        return jsonify(data)
    return jsonify({"error": "File is not a point array"}), 400


@overlays_bp.get("/overlays/crash_data_status")
def overlay_crash_data_status():
    """All 50 states crash data availability — what we have, what needs manual effort.
    Returns three tiers: harvested (auto), portal_required (human needed), missing."""
    import json as json_mod

    catalog_path = os.path.join(_parent, "crash_harvester", "all_sources_catalog.json")
    portal_states = {}
    if os.path.exists(catalog_path):
        with open(catalog_path) as f:
            catalog = json_mod.load(f)
        portal_states = catalog.get("portal_required_states", {}).get("states", {})

    # Check what's actually in the library
    all_states = [
        "ak", "al", "ar", "az", "ca", "co", "ct", "dc", "de", "fl",
        "ga", "hi", "ia", "id", "il", "in", "ks", "ky", "la", "ma",
        "md", "me", "mi", "mn", "mo", "ms", "mt", "nc", "nd", "ne",
        "nh", "nj", "nm", "nv", "ny", "oh", "ok", "or", "pa", "ri",
        "sc", "sd", "tn", "tx", "ut", "va", "vt", "wa", "wi", "wv", "wy",
    ]

    harvested = []
    portal_required = []
    missing = []

    for st in all_states:
        has_crash = _md.is_available("crash", st)
        has_fatal = _md.is_available("fatal", st)
        st_upper = st.upper()
        if has_crash:
            harvested.append({"state": st_upper, "type": "all_severity"})
        elif st_upper in portal_states:
            info = portal_states[st_upper]
            portal_required.append({
                "state": st_upper,
                "portal": info.get("portal", ""),
                "action": info.get("action", ""),
                "has_fatal": has_fatal,
            })
        else:
            missing.append({"state": st_upper, "has_fatal": has_fatal})

    return jsonify({
        "harvested": harvested,
        "portal_required": portal_required,
        "missing": missing,
        "summary": {
            "total": len(all_states),
            "harvested": len(harvested),
            "portal_required": len(portal_required),
            "missing": len(missing),
        },
    })


@overlays_bp.get("/overlays/population_density")
def overlay_population_density():
    """Census population density from CrashHarvester library."""
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state"}), 404
    data = _md.get_census("population_density", state)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No population data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --census {state}"}), 404


@overlays_bp.get("/overlays/property_values")
def overlay_property_values():
    """Census property values from CrashHarvester library."""
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state"}), 404
    data = _md.get_census("property_values", state)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No property value data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --census {state}"}), 404


@overlays_bp.get("/overlays/jobs")
def overlay_jobs():
    """Census jobs data from CrashHarvester library."""
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state"}), 404
    data = _md.get_census("jobs", state)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No jobs data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --census {state}"}), 404

# ---------------------------------------------------------------------------
# Data Search Protocol — active search when data is missing
# Established 2026-07-30
# ---------------------------------------------------------------------------
import threading
import time as _time

_active_searches = {}  # key = state, value = search state dict


def _detect_county(lat, lon):
    """Detect county FIPS from lat/lon via FCC API."""
    try:
        import urllib.request
        url = f"https://geo.fcc.gov/api/census/area?lat={lat}&lon={lon}&format=json"
        r = urllib.request.urlopen(url, timeout=10)
        import json as _jmod
        data = _jmod.loads(r.read())
        for result in data.get("results", []):
            fips = result.get("county_fips", "")
            name = result.get("county_name", "")
            if fips and len(fips) >= 5:
                return fips[2:], name  # 3-digit county code, county name
    except Exception:
        pass
    return None, None

def _run_data_search(state):
    """Background thread: try ArcGIS harvest for missing state data.
    Harvests statewide, normalizes by county, checks target county."""
    search = _active_searches.get(state)
    if not search:
        return
    search["status"] = "searching"

    # Detect target county from search lat/lon
    slat = search.get("lat")
    slon = search.get("lon")
    target_county, target_county_name = None, None
    if slat and slon:
        try:
            target_county, target_county_name = _detect_county(float(slat), float(slon))
            search["target_county"] = target_county
            search["target_county_name"] = target_county_name
            log.info(f"[DataSearch] Target: {target_county_name} County ({target_county}) in {state.upper()}")
        except Exception:
            pass

    # Build source list
    sources = []
    try:
        from CrashHarvester.harvest.arcgis_dot import CONFIGS
        for key, cfg in CONFIGS.items():
            if key.startswith(state) or key == state:
                sources.append({
                    "name": f"ArcGIS: {key}",
                    "config_key": key,
                    "url": cfg.get("url", ""),
                    "notes": cfg.get("notes", ""),
                })
    except Exception as e:
        log.warning(f"[DataSearch] Could not load ArcGIS configs: {e}")

    if not sources:
        search["status"] = "not_found"
        search["sources"] = []
        search["message"] = (
            f"No ArcGIS endpoint configured for {state.upper()}. "
            f"State DOT data may need to be obtained manually."
        )
        return

    search["sources"] = [{"name": s["name"], "url": s["url"], "status": "pending"} for s in sources]
    search["total"] = len(sources)

    for i, src in enumerate(sources):
        if search.get("cancelled"):
            search["status"] = "cancelled"
            return

        search["current"] = src["name"]
        search["tried"] = i + 1
        search["sources"][i]["status"] = "trying"

        try:
            from CrashHarvester.harvest.arcgis_dot import harvest_arcgis
            harvest_arcgis(sources[i]["config_key"])
            search["sources"][i]["status"] = "done"

            # Check if we now have data
            _md._cache.clear()
            slat = search.get("lat")
            slon = search.get("lon")
            srad = search.get("radius", 10)
            if slat and slon:
                test = _md.get_crashes(state, float(slat), float(slon), float(srad))
            else:
                test = _md.get_crashes(state)
            if test and test.get("features"):
                county_msg = f" ({target_county_name} County)" if target_county_name else ""
                search["status"] = "found"
                search["message"] = f"Crash data for {state.upper()}{county_msg} is now available. Reload Data."
                search["feature_count"] = len(test["features"])
                log.info(f"[DataSearch] Found {len(test['features'])} features for {state.upper()}{county_msg}")
                return
            else:
                # Data harvested but not for target county
                all_test = _md.get_crashes(state)
                if all_test and all_test.get("features"):
                    search["sources"][i]["status"] = "partial"
                    log.info(f"[DataSearch] {src['name']} has data but not for target area")
                else:
                    search["sources"][i]["status"] = "no_data"
        except Exception as e:
            search["sources"][i]["status"] = f"error: {str(e)[:100]}"
            log.warning(f"[DataSearch] {src['name']} failed: {e}")

    county_msg = f" ({target_county_name} County)" if target_county_name else ""
    search["status"] = "not_found"
    search["message"] = (
        f"Search complete. Could not find crash data for {state.upper()}{county_msg}. "
        f"Checked {len(sources)} source(s). The state DOT may not publish data for this county, "
        f"or may require a data request."
    )


@overlays_bp.post("/overlays/search_data")
def overlay_search_data():
    """Start a background search for missing crash data."""
    state = request.json.get("state", "").lower() if request.is_json else ""
    if not state:
        state_detected, _, _ = _detect_state()
        state = state_detected or ""
    if not state:
        return jsonify({"error": "No state specified"}), 400

    existing = _active_searches.get(state)
    if existing and existing["status"] == "searching":
        return jsonify(existing)

    lat = request.json.get("lat") if request.is_json else None
    lon = request.json.get("lon") if request.is_json else None
    radius = request.json.get("radius", 10) if request.is_json else 10
    _md._cache.clear()
    if lat and lon:
        test = _md.get_crashes(state, float(lat), float(lon), float(radius))
    else:
        test = _md.get_crashes(state)
    if test and test.get("features"):
        return jsonify({
            "status": "found",
            "state": state.upper(),
            "message": f"Crash data for {state.upper()} is already available. Reload Data.",
            "feature_count": len(test["features"]),
        })

    search = {
        "state": state.upper(),
        "status": "starting",
        "started": _time.time(),
        "lat": lat,
        "lon": lon,
        "radius": radius,
        "sources": [],
        "tried": 0,
        "total": 0,
        "current": "",
        "message": f"Searching for crash data for {state.upper()}...",
    }
    _active_searches[state] = search

    t = threading.Thread(target=_run_data_search, args=(state,), daemon=True)
    t.start()

    return jsonify(search)


@overlays_bp.get("/overlays/search_status")
def overlay_search_status():
    """Poll search progress."""
    state = request.args.get("state", "").lower()
    if not state:
        return jsonify({"error": "No state specified"}), 400
    search = _active_searches.get(state)
    if not search:
        return jsonify({"status": "none", "state": state.upper()})
    result = dict(search)
    result["elapsed"] = round(_time.time() - search["started"], 1)
    return jsonify(result)
