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
        return jsonify({"error": f"No all-severity crash data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --state-dot {state} RAW_FILE"}), 404

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


@overlays_bp.get("/overlays/mobility")
def overlay_mobility():
    """Cell mobility data — not yet in CrashHarvester library."""
    return jsonify({"error": "Mobility data not yet harvested"}), 404


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
