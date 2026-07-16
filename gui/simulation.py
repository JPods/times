"""
mesh_mobility.gui.simulation
==============================
Simulation, settings, and demand endpoints.

Extracted from api.py in Round 4 refactoring (2026-07-15).
"""

from __future__ import annotations

import heapq
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Dict

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine imports
# ---------------------------------------------------------------------------
import sys
_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

import subprocess as _subprocess
import pathlib as _pathlib

from mesh_mobility.engine import Network, Simulator
from mesh_mobility.engine.physics import PhysicsModel

# ---------------------------------------------------------------------------
# Shared state imports
# ---------------------------------------------------------------------------
from mesh_mobility.gui.state import (
    _state, _net, _ALLIE_CAPTURE,
    ensure_session, set_session_cookie, auto_push_undo,
    noelle_log, allie_capture_simulation, allie_capture_error, write_fault,
)

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
sim_bp = Blueprint("simulation", __name__, url_prefix="/api")

# Register session lifecycle hooks (same as api.py)
sim_bp.before_request(ensure_session)
sim_bp.after_request(set_session_cookie)
sim_bp.before_request(auto_push_undo)


# ---------------------------------------------------------------------------
# Sweep trips JSON export
# ---------------------------------------------------------------------------

def _save_sweep_json(result) -> None:
    """Write sweep_trips.json alongside the network file (or in _rt_dir).

    Format:
      {
        "network_id": "...",
        "generated_at": "2026-04-30T12:00:00Z",
        "station_count": 30,
        "expected_pairs": 870,
        "covered_pairs": 870,
        "missing_count": 0,
        "missing_pairs": [],
        "trips": [
          {"trip_key": "sw1_s1_s2", "sweep": 1, "origin_id": "s1", "dest_id": "s2",
           "travel_min": 2.4, "wait_min": 0.0, "dist_m": 1200.0},
          ...
        ]
      }
    """
    try:
        n = result.summary.get("station_count", 0)
        expected = n * (n - 1)  # pairs per sweep x 2 sweeps worth of keys
        covered  = expected - len(result.missing_pairs)

        payload = {
            "network_id":    result.network_id,
            "generated_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "station_count": n,
            "expected_pairs": expected,
            "covered_pairs":  max(0, covered),
            "missing_count":  len(result.missing_pairs),
            "missing_pairs":  result.missing_pairs,
            "trips":          result.sweep_trips,
        }

        out_path = os.path.join(_rt_dir, "sweep_trips.json")
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)
        log.info("sweep_trips.json written: %d trips, %d missing pairs → %s",
                 len(result.sweep_trips), len(result.missing_pairs), out_path)
    except Exception as exc:
        import traceback, sys
        print(f"[sweep_trips] ERROR: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        log.warning("Could not write sweep_trips.json: %s", exc)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

@sim_bp.post("/simulation/run")
def run_simulation():
    from mesh_mobility.engine.demand import LoadArray

    if _state.get("sim_active"):
        return jsonify({"error": "Simulation already running"}), 409

    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    data = request.json or {}
    slots = int(data.get("slots", 360))
    settings = _state["settings"].copy()
    incoming = {k: v for k, v in data.get("settings", {}).items() if v is not None and v == v}  # drop None and NaN
    settings.update(incoming)
    if incoming:
        _state["settings"].update(incoming)  # keep travel_times in sync

    demand_config = {}
    demand_path = os.path.join(_rt_dir, "demand.json")
    if os.path.exists(demand_path):
        try:
            with open(demand_path) as f:
                demand_config = json.load(f)
        except Exception:
            pass

    station_ids = list(net.stations.keys())
    demand = LoadArray(station_ids, demand_config=demand_config)
    sim = Simulator(net, settings, demand=demand)

    noelle_log("simulation_run", {"stations": len(station_ids), "slots": slots,
                                    "network_id": getattr(net, "network_id", "")})
    _state["sim_active"]   = True
    _state["sim_instance"] = sim
    _state["sim_result"]   = None
    _state["sim_error"]    = None

    # Tool boundary -- simulation start captured.
    network_name = getattr(net, "network_id", "") or ""
    allie_capture_simulation.__func__ if hasattr(allie_capture_simulation, "__func__") else None
    if _ALLIE_CAPTURE.exists():
        try:
            _subprocess.Popen(
                ["python3", str(_ALLIE_CAPTURE),
                 "--source", "route-time",
                 "--event",  "simulation_start",
                 "--message", f"{network_name} — {len(station_ids)} stations, {slots} slots",
                 "--data",   json.dumps({"network_id": network_name, "slots": slots,
                                         "stations": len(station_ids)})],
                stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _run_thread():
        try:
            result = sim.run(total_slots=slots)
            _state["sim_result"] = result

            # Detect silent failure: passengers generated but none served
            pax_served    = getattr(result.simulation if hasattr(result, "simulation")
                                    else result, "passengers_served", None)
            pax_generated = getattr(result.simulation if hasattr(result, "simulation")
                                    else result, "passengers_generated", None)
            if (pax_served is not None and pax_generated is not None
                    and pax_generated > 0 and pax_served == 0):
                write_fault(
                    "0 passengers served with non-zero demand",
                    f"network={network_name}, stations={len(station_ids)}, slots={slots}; "
                    f"check station connectivity and routing",
                )

            _save_sweep_json(result)
            allie_capture_simulation(result, net)
        except Exception as exc:
            import traceback
            _state["sim_error"] = str(exc)
            log.error("Simulation thread error: %s", traceback.format_exc())
            write_fault(f"Simulation exception: {exc}", f"network={network_name}")
            allie_capture_error("simulation_error", str(exc))
        finally:
            _state["sim_active"]   = False
            _state["sim_instance"] = None

    t = threading.Thread(target=_run_thread, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@sim_bp.get("/simulation/progress")
def simulation_progress():
    """Poll during an async simulation run.

    Returns:
      { "status": "running", "completed_origins": [...], "total_stations": N }
      { "status": "done",    "result": { ... } }
      { "status": "error",   "error": "..." }
      { "status": "idle" }
    """
    if _state.get("sim_error"):
        err = _state["sim_error"]
        _state["sim_error"] = None
        return jsonify({"status": "error", "error": err})

    result = _state.get("sim_result")
    if result and not _state.get("sim_active"):
        return jsonify({"status": "done", "result": result.to_dict()})

    sim = _state.get("sim_instance")
    if sim and _state.get("sim_active"):
        all_sids = list(sim.network.stations.keys())
        n = len(all_sids)

        # Read completed sweep trips (thread-safe: list is append-only)
        orig_dests: Dict[str, set] = {}
        for trip in list(sim._completed_trips):
            if trip.trip_key:
                if trip.origin_id not in orig_dests:
                    orig_dests[trip.origin_id] = set()
                orig_dests[trip.origin_id].add(trip.dest_id)

        # An origin is "complete" once it has a completed trip to every other station
        completed = [s for s in all_sids if len(orig_dests.get(s, set())) >= n - 1]

        # Count total covered O-D pairs for progress display
        covered_pairs = sum(len(v) for v in orig_dests.values())
        total_pairs   = n * (n - 1)

        return jsonify({
            "status":            "running",
            "completed_origins": completed,
            "total_stations":    n,
            "covered_pairs":     covered_pairs,
            "total_pairs":       total_pairs,
        })

    return jsonify({"status": "idle"})


@sim_bp.post("/trip/dispatch")
def trip_dispatch():
    """Receive a live trip request from the JPods phone app.

    Looks up the estimated travel time from the last simulation result for
    this O-D pair and returns it alongside a queued status.

    Body (from Django TravelView):
        origin_station_id, destination_station_id, trip_id, contact_name, price, network_id
    """
    data   = request.json or {}
    origin = data.get("origin_station_id", "")
    dest   = data.get("destination_station_id", "")

    travel_time_ms = None
    sim = _state.get("sim_result")
    if sim:
        # SimResult.trip_stats is keyed by (origin_platform, dest_platform)
        # Station node IDs end in .PLATFORM; try both bare ID and .PLATFORM suffix
        ts = getattr(sim, "trip_stats", {})
        for o_key in (origin, f"ST_{origin}.PLATFORM", f"{origin}.PLATFORM"):
            for d_key in (dest, f"ST_{dest}.PLATFORM", f"{dest}.PLATFORM"):
                stats = ts.get((o_key, d_key))
                if stats:
                    travel_time_ms = getattr(stats, "median_ms", None)
                    break
            if travel_time_ms is not None:
                break

    return jsonify({
        "status":          "queued",
        "trip_id":         data.get("trip_id"),
        "contact_name":    data.get("contact_name"),
        "origin":          origin,
        "destination":     dest,
        "travel_time_ms":  travel_time_ms,
        "travel_time_s":   round(travel_time_ms / 1000, 1) if travel_time_ms else None,
        "sim_available":   sim is not None,
    })


@sim_bp.get("/settings")
def get_settings():
    return jsonify(_state["settings"])


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------

@sim_bp.get("/demand")
def get_demand():
    """Return demand config + current station list."""
    demand_path = os.path.join(_rt_dir, "demand.json")
    config = {}
    if os.path.exists(demand_path):
        try:
            with open(demand_path) as f:
                raw = json.load(f)
            # Strip comment keys (prefixed with _)
            config = {k: v for k, v in raw.items() if not k.startswith("_")}
            if "stations" in config:
                config["stations"] = {
                    k: v for k, v in config["stations"].items()
                    if not k.startswith("_")
                }
        except Exception:
            pass

    net = _net()
    station_ids = list(net.stations.keys()) if net else []
    return jsonify({
        "config":      config,
        "station_ids": station_ids,
        "total_slots": config.get("total_slots", 360),
    })


@sim_bp.post("/demand")
def post_demand():
    """Save demand config to demand.json."""
    data = request.json or {}
    demand_path = os.path.join(_rt_dir, "demand.json")
    with open(demand_path, "w") as f:
        json.dump(data, f, indent=2)
    return jsonify({"ok": True})


@sim_bp.post("/settings")
def post_settings():
    updates = request.json or {}
    _state["settings"].update(updates)
    return jsonify(_state["settings"])


# ---------------------------------------------------------------------------
# Analytical travel times (Dijkstra -- used by isochrone)
# ---------------------------------------------------------------------------

@sim_bp.get("/network/travel_times")
def network_travel_times():
    """
    Dijkstra-based travel times from a given origin station to all reachable
    stations, using network line lengths and cruise speed.

    Query params:
      origin  -- station node_id (e.g. "s32.PLATFORM")
      speed   -- cruise speed km/h (optional; falls back to settings)

    Returns:
      { "origin": <id>, "travel_min": { dest_id: minutes, ... } }
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    origin_id = request.args.get("origin", "")
    if origin_id not in net.nodes:
        return jsonify({"error": f"Node {origin_id!r} not found"}), 400

    speed_kmh = float(request.args.get("speed", 0) or
                      _state["settings"].get("maxVelocityInKMPH", 60))
    speed_m_per_min = speed_kmh * 1000 / 60

    # Dijkstra over all nodes -- edge weight = length_m (metres).
    # Treat zero-length connection lines as free (0.001 m) so inter-CP
    # connections never break the path.
    INF = float("inf")
    dist_m: dict = {origin_id: 0.0}
    pq = [(0.0, origin_id)]

    while pq:
        cost, nid = heapq.heappop(pq)
        if cost > dist_m.get(nid, INF):
            continue
        node = net.nodes[nid]
        for line in node.outbound:
            w = max(line.length_m, 0.001)   # allow zero-length connection lines
            new_cost = cost + w
            end_id = line.end_node.node_id
            if new_cost < dist_m.get(end_id, INF):
                dist_m[end_id] = new_cost
                heapq.heappush(pq, (new_cost, end_id))

    # Extract station-to-station times (minutes)
    travel_min = {}
    for sid, station in net.stations.items():
        if sid == origin_id:
            continue
        d = dist_m.get(sid)
        if d is not None and d < INF:
            travel_min[sid] = round(d / speed_m_per_min, 3)

    return jsonify({"origin": origin_id, "travel_min": travel_min})
