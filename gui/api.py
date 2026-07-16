"""
mesh_mobility.gui.api
==================
Flask REST API backing the browser GUI.

Core network editing endpoints remain here. Other endpoints are in:
  - simulation.py    — simulation, settings, demand, travel times
  - network_io.py    — load, save, download, new, reload, merge, library
  - builders.py      — Line tool, City Mesh, Grid, Auto-connect, Build-on-lines, Crash Mesh
  - overlays.py      — overlay data endpoints
  - noelle_api.py    — Noelle AI endpoints

Endpoints in this file:
  GET  /api/network          -> current network as GeoJSON
  POST /api/network/node     -> add a node (station or switch)
  POST /api/network/circle   -> add a traffic circle
  POST /api/network/station  -> add a station structure
  DELETE /api/network/node/<id>       -> remove a node + its lines
  DELETE /api/network/structure/<sid> -> remove a structure
  POST /api/network/add_line         -> add a directed line
  DELETE /api/network/line/<id>      -> break a line pair
  POST /api/network/connect_cps      -> connect two CPs
  POST /api/network/disconnect_cp    -> disconnect a CP
  POST /api/network/structure/<sid>/rotate -> rotate a structure
  POST /api/network/structure/<sid>/move   -> move a structure
  POST /api/network/undo/push  -> push undo snapshot
  POST /api/network/undo       -> restore previous state
  POST /api/network/line/<id>/waypoint     -> add waypoint
  PUT  /api/network/line/<id>/waypoint/<n> -> move waypoint
  DELETE /api/network/line/<id>/waypoint/<n> -> remove waypoint
  POST /api/process/log_event  -> write TF/DNW process file
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

from flask import Blueprint, jsonify, request, Response

# Import engine and IO
import sys
_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

# ---------------------------------------------------------------------------
# Shared state -- imported from state.py
# ---------------------------------------------------------------------------
import subprocess as _subprocess
import pathlib as _pathlib

from mesh_mobility.gui.state import (
    _state, _net, _ALLIE_CAPTURE,
    ensure_session, set_session_cookie, auto_push_undo,
    push_undo, clear_edit_state, next_sid, sync_counters,
    reconstruct_structures_from_net, restore_structures,
    new_id, footprint_m, check_overlap,
    noelle_log, write_fault,
    cp_by_heading,
)

from mesh_mobility.engine import Network, Node, Line, Station
from mesh_mobility.engine.structures import (
    build_traffic_circle, build_station, connect_cps, disconnect_cp,
    rotate_station, rotate_traffic_circle,
    ConnectionPoint, Structure,
)
from mesh_mobility.io import load_jpd
from mesh_mobility.io.jpd_writer import serialise_jpd

api = Blueprint("api", __name__, url_prefix="/api")

# Register session lifecycle hooks from state module
api.before_request(ensure_session)
api.after_request(set_session_cookie)
api.before_request(auto_push_undo)


# _detect_state and _get_overlay_center_radius moved to overlays.py


# ---------------------------------------------------------------------------
# Network serialisation -> GeoJSON
# ---------------------------------------------------------------------------

def _network_to_geojson(net: Network) -> dict:
    features = []

    # Build reverse map: node_id -> structure_id (for tagging internal nodes)
    node_to_struct: Dict[str, str] = {}
    for struct in _state["structures"].values():
        for nid in struct.node_ids:
            node_to_struct[nid] = struct.structure_id

    # CP tip nodes -- both stub tips are hidden; replaced by one CP centre feature
    cp_tip_nodes: set = set()
    for cp in _state["cps"].values():
        cp_tip_nodes.add(cp.outbound_node.node_id)
        cp_tip_nodes.add(cp.inbound_node.node_id)

    # Build reverse map: line_id -> structure_id (lines whose both endpoints
    # are internal to the same structure -- used by the move-drag preview)
    line_to_struct: Dict[str, str] = {}
    for struct in _state["structures"].values():
        struct_nodes = set(struct.node_ids)
        for lid in struct.line_ids:
            line_to_struct[lid] = struct.structure_id

    # Lines -> LineString features (thread through waypoints)
    for lid, line in net.lines.items():
        via = _state["waypoints"].get(lid, [])
        if via:
            coords = (
                [[line.start_node.lon, line.start_node.lat]] +
                [[w["lon"], w["lat"]] for w in via] +
                [[line.end_node.lon, line.end_node.lat]]
            )
        else:
            coords = _line_coords(line)

        features.append({
            "type": "Feature",
            "id": f"line:{lid}",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "type": "line",
                "line_id": lid,
                "structure_id": line_to_struct.get(lid),
                "start_node": line.start_node.node_id,
                "end_node": line.end_node.node_id,
                "length_m": round(line.length_m, 1),
                "is_converging": line.is_converging(),
                "is_diverging": line.is_diverging(),
                "line_role": _state["line_roles"].get(lid),
                "partner_id": _state["line_pairs"].get(lid),
                "via_markers": [{"lat": w["lat"], "lon": w["lon"], "idx": i}
                                for i, w in enumerate(via)],
            },
        })

    # Nodes -> Point features
    for nid, node in net.nodes.items():
        is_station = node.node_id in net.stations
        struct_id = node_to_struct.get(nid)
        is_cp_tip = nid in cp_tip_nodes
        # Hide all internal structure nodes (including CP tips -- CPs get their own feature)
        is_hidden = struct_id is not None or is_cp_tip
        struct_obj   = _state["structures"].get(struct_id) if struct_id else None
        struct_type  = struct_obj.structure_type if struct_obj else None
        features.append({
            "type": "Feature",
            "id": f"node:{nid}",
            "geometry": {"type": "Point", "coordinates": [node.lon, node.lat]},
            "properties": {
                "type": "station" if is_station else "switch",
                "node_id": nid,
                "label": nid,
                "node_role": "station" if is_station else "switch",
                "structure_id": struct_id,
                "structure_type": struct_type,
                "is_internal": is_hidden,
            },
        })

    # One CP feature per connection point -- placed at stub-pair midpoint
    for cp in _state["cps"].values():
        struct = _state["structures"].get(cp.structure_id)
        struct_type = struct.structure_type if struct else "unknown"
        features.append({
            "type": "Feature",
            "id": f"cp:{cp.cp_id}",
            "geometry": {"type": "Point",
                         "coordinates": [cp.center_lon, cp.center_lat]},
            "properties": {
                "type":             "cp",
                "cp_id":            cp.cp_id,
                "structure_id":     cp.structure_id,
                "structure_type":   struct_type,
                "heading_deg":      cp.heading_deg,
                "outbound_node":    cp.outbound_node.node_id,
                "inbound_node":     cp.inbound_node.node_id,
                "connected_to":     cp.connected_to,
                "label":            cp.cp_id,
            },
        })

    # Structure summary for sidebar / CP rendering
    structures_meta = {s.structure_id: s.to_dict() for s in _state["structures"].values()}
    cps_meta = [cp.to_dict() for cp in _state["cps"].values()]

    center = _network_center(net)
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "network_id": net.network_id,
            "node_count": len(net.nodes),
            "line_count": len(net.lines),
            "station_count": len(net.stations),
            "total_km": round(net.total_length_m() / 1000, 2),
            "total_miles": round(net.total_length_m() / 1609.34, 1),
            "circle_count": sum(1 for s in _state["structures"].values() if s.structure_type == "circle"),
            "city_label": (_state.get("overlays") or {}).get("city_label", ""),
            "center": center,
            "structures": structures_meta,
            "cps": cps_meta,
        },
    }


def _line_coords(line: Line) -> List[List[float]]:
    start = [line.start_node.lon, line.start_node.lat]
    end   = [line.end_node.lon,   line.end_node.lat]
    coords = line.coordinates
    if coords and len(coords) > 2:
        # Preserve interior waypoints; always use live node positions for endpoints
        mid = [[lon, lat] for lat, lon in coords[1:-1]]
        return [start] + mid + [end]
    return [start, end]


def _network_center(net: Network) -> List[float]:
    if not net.nodes:
        return [0.0, 0.0]
    lats = [n.lat for n in net.nodes.values() if n.lat != 0]
    lons = [n.lon for n in net.nodes.values() if n.lon != 0]
    if not lats:
        return [0.0, 0.0]
    return [sum(lats) / len(lats), sum(lons) / len(lons)]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# Library, load, save, download, new, reload, load_text, merge_text,
# load_suggestion, save_drawn_lines, get_drawn_lines moved to network_io.py

# Simulation, settings, demand, travel_times moved to simulation.py

# build_on_lines, crash_mesh moved to builders.py


@api.get("/network")
def get_network():
    net = _net()
    if net is None:
        return jsonify({"type": "FeatureCollection", "features": [],
                        "metadata": {"network_id": "empty"}})
    return jsonify(_network_to_geojson(net))


@api.post("/process/log_event")
def process_log_event():
    """Write a TF or DNW process file from the browser TF/DNW prompt.

    Called when the developer clicks 'Log TF' or 'Log DNW' after a
    simulation run. Body:
      { "type": "TF" | "DNW" | "skip",
        "summary": "one-sentence description",
        "network": "CA_Gilroy_Clean",
        "passengers_served": 847,
        "passengers_generated": 850 }

    Writes to ~/Allie/process/inbox/. No-op if Allie drive not mounted.
    """
    data = request.json or {}
    event_type = data.get("type", "skip").upper()
    if event_type == "SKIP":
        return jsonify({"ok": True, "written": False})

    ts_str  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    inbox = _pathlib.Path.home() / "Allie" / "process" / "inbox"
    if not inbox.parent.parent.exists():
        return jsonify({"ok": True, "written": False, "note": "Allie drive not mounted"})
    inbox.mkdir(parents=True, exist_ok=True)

    network  = data.get("network", "")
    summary  = data.get("summary", "").strip()
    pax_s    = data.get("passengers_served", "?")
    pax_g    = data.get("passengers_generated", "?")

    if event_type == "TF":
        path = inbox / f"{ts_file}-tf.md"
        path.write_text(
            f"# TF — {ts_str}\n\n"
            f"summary: {summary or '(edit me)'}\n"
            f"code:    mesh_mobility/gui/api.py\n"
            f"context: network={network} passengers={pax_s}/{pax_g}\n"
            f"domain:  RT\n"
        )
    elif event_type == "DNW":
        path = inbox / f"{ts_file}-dnw.md"
        path.write_text(
            f"# DNW — {ts_str}\n\n"
            f"tried:    {summary or '(edit me)'}\n"
            f"result:   simulation ran — passengers_served={pax_s}/{pax_g}\n"
            f"revealed: \n"
            f"domain:  RT\n"
        )
    else:
        return jsonify({"error": f"Unknown type: {event_type}"}), 400

    log.info("[process] -> %s", path.name)
    return jsonify({"ok": True, "written": True, "file": path.name})


@api.post("/network/node")
def add_node():
    """Add a station or switch at a lat/lon position."""
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data = request.json or {}
    lat   = float(data["lat"])
    lon   = float(data["lon"])
    ntype = data.get("type", "switch")   # "station" or "switch"
    nid   = data.get("id") or new_id(ntype)

    node = Node(nid, lat, lon, is_station=(ntype == "station"))
    net.nodes[nid] = node
    if ntype == "station":
        net.stations[nid] = Station(nid, node)
    net.build()
    return jsonify({"node_id": nid, "lat": lat, "lon": lon, "type": ntype})


@api.delete("/network/node/<node_id>")
def remove_node(node_id: str):
    net = _net()
    if net is None or node_id not in net.nodes:
        return jsonify({"error": "Node not found"}), 404
    # Remove all lines touching this node
    dead_lines = [lid for lid, l in net.lines.items()
                  if l.start_node.node_id == node_id or l.end_node.node_id == node_id]
    for lid in dead_lines:
        del net.lines[lid]
    del net.nodes[node_id]
    net.stations.pop(node_id, None)
    net.build()
    return jsonify({"removed": node_id, "lines_removed": dead_lines})


@api.delete("/network/structure/<sid>")
def delete_structure(sid: str):
    """
    Remove an entire structure: all internal nodes, lines, and any connector
    lines attached to its CPs.  Clears partner CPs' connected_to.
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    struct = _state["structures"].get(sid)
    if struct is None:
        return jsonify({"error": f"Structure {sid} not found"}), 404

    # Clear partner CPs' connected_to before removing our CPs
    for cp_id in struct.cp_ids:
        cp = _state["cps"].get(cp_id)
        if cp and cp.connected_to:
            partner = _state["cps"].get(cp.connected_to)
            if partner:
                partner.connected_to = None

    # Remove all lines that touch any of this structure's nodes
    struct_nodes = set(struct.node_ids)
    dead_lines = [
        lid for lid, line in net.lines.items()
        if line.start_node.node_id in struct_nodes
        or line.end_node.node_id   in struct_nodes
    ]
    for lid in dead_lines:
        del net.lines[lid]
        _state["line_pairs"].pop(lid, None)
        _state["line_roles"].pop(lid, None)
        _state["waypoints"].pop(lid,  None)

    # Remove nodes
    for nid in struct.node_ids:
        net.nodes.pop(nid, None)
        net.stations.pop(nid, None)

    # Remove CPs and structure record
    for cp_id in struct.cp_ids:
        _state["cps"].pop(cp_id, None)
    del _state["structures"][sid]

    net.build()
    return jsonify({"deleted": sid, "lines_removed": dead_lines})


@api.post("/network/circle")
def add_circle():
    """Place a traffic circle centred at lat/lon (15m diameter, 4 arms, US/CCW)."""
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data = request.json or {}
    lat  = float(data["lat"])
    lon  = float(data["lon"])
    cid  = data.get("id") or next_sid("c")
    arms = data.get("arm_headings")   # optional [h0, h1, h2, h3]

    overlap_err = check_overlap(lat, lon, "traffic_circle")
    if overlap_err:
        return jsonify({"error": overlap_err}), 400

    try:
        struct, cps = build_traffic_circle(net, lat, lon,
                                           structure_id=cid,
                                           arm_headings=arms)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    _state["structures"][struct.structure_id] = struct
    _state["cps"].update(cps)

    return jsonify({
        "circle_id": struct.structure_id,
        "cp_ids":    struct.cp_ids,
        "node_ids":  struct.node_ids,
        "line_ids":  struct.line_ids,
    })


@api.post("/network/station")
def add_station():
    """Place a full station structure (70m, right-side loading, US/CCW)."""
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data = request.json or {}
    lat         = float(data["lat"])
    lon         = float(data["lon"])
    heading_deg = float(data.get("heading_deg", 0.0))
    sid         = data.get("id") or next_sid("s")

    overlap_err = check_overlap(lat, lon, "station")
    if overlap_err:
        return jsonify({"error": overlap_err}), 400

    try:
        struct, cps = build_station(net, lat, lon,
                                    heading_deg=heading_deg,
                                    structure_id=sid)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    _state["structures"][struct.structure_id] = struct
    _state["cps"].update(cps)

    # Tag siding lines so the renderer can invert their inbound/outbound colour
    _siding_suffixes = ("platform_in", "platform_parking_a", "platform_parking_b",
                        "platform_out")
    for lid in struct.line_ids:
        if any(lid.endswith(s) for s in _siding_suffixes):
            _state["line_roles"][lid] = "siding"

    return jsonify({
        "station_id": struct.structure_id,
        "cp_ids":     struct.cp_ids,
        "node_ids":   struct.node_ids,
        "line_ids":   struct.line_ids,
    })


@api.post("/network/add_line")
def add_line():
    """Add a directed line from start_node to end_node."""
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data = request.json or {}
    start_id = data["start_node"]
    end_id   = data["end_node"]
    if start_id not in net.nodes or end_id not in net.nodes:
        return jsonify({"error": "Node not found"}), 404
    lid = data.get("id") or new_id("L")
    from mesh_mobility.engine.network import vincenty_m
    sn = net.nodes[start_id]
    en = net.nodes[end_id]
    length_m = vincenty_m(sn.lat, sn.lon, en.lat, en.lon)
    line = Line(lid, sn, en, length_m)
    net.lines[lid] = line
    net.build()
    return jsonify({"line_id": lid, "length_m": round(length_m, 1)})


@api.delete("/network/line/<line_id>")
def break_line(line_id: str):
    """
    Remove a guideway pair -- guideways always travel in pairs so both
    are removed together.  Also clears the CP connected_to on both ends.
    """
    net = _net()
    if net is None or line_id not in net.lines:
        return jsonify({"error": "Line not found"}), 404

    partner_id = _state["line_pairs"].pop(line_id, None)
    removed    = [line_id]

    del net.lines[line_id]
    _state["waypoints"].pop(line_id, None)

    if partner_id and partner_id in net.lines:
        _state["line_pairs"].pop(partner_id, None)
        del net.lines[partner_id]
        _state["waypoints"].pop(partner_id, None)
        removed.append(partner_id)

    # Clear connected_to on any CP whose outbound tip no longer has an outgoing line
    live_starts = {l.start_node.node_id for l in net.lines.values()}
    for cp in _state["cps"].values():
        if cp.connected_to and cp.outbound_node.node_id not in live_starts:
            partner_cp = _state["cps"].get(cp.connected_to)
            cp.connected_to = None
            if partner_cp:
                partner_cp.connected_to = None

    net.build()
    return jsonify({"broken": removed})


@api.post("/network/line/<line_id>/waypoint")
def add_waypoint(line_id: str):
    """
    Shift-click on a guideway line: add a draggable waypoint at {lat, lon}.
    The polyline will thread through this point, pulling both stubs of the pair.
    Returns updated via_markers list and recalculated length_m.
    """
    net = _net()
    if net is None or line_id not in net.lines:
        return jsonify({"error": "Line not found"}), 404
    data = request.json or {}
    lat = float(data["lat"])
    lon = float(data["lon"])

    via = _state["waypoints"].setdefault(line_id, [])
    via.append({"lat": lat, "lon": lon})
    _recalc_line_length(net, line_id)

    return jsonify({
        "line_id": line_id,
        "via_markers": [{"lat": w["lat"], "lon": w["lon"], "idx": i}
                        for i, w in enumerate(via)],
        "length_m": round(net.lines[line_id].length_m, 1),
    })


@api.put("/network/line/<line_id>/waypoint/<int:idx>")
def move_waypoint(line_id: str, idx: int):
    """Drag a waypoint to a new position."""
    net = _net()
    if net is None or line_id not in net.lines:
        return jsonify({"error": "Line not found"}), 404
    via = _state["waypoints"].get(line_id, [])
    if idx < 0 or idx >= len(via):
        return jsonify({"error": "Waypoint index out of range"}), 400
    data = request.json or {}
    via[idx] = {"lat": float(data["lat"]), "lon": float(data["lon"])}
    _recalc_line_length(net, line_id)

    return jsonify({
        "line_id": line_id,
        "via_markers": [{"lat": w["lat"], "lon": w["lon"], "idx": i}
                        for i, w in enumerate(via)],
        "length_m": round(net.lines[line_id].length_m, 1),
    })


@api.delete("/network/line/<line_id>/waypoint/<int:idx>")
def remove_waypoint(line_id: str, idx: int):
    """Shift-click on a waypoint marker to remove it."""
    net = _net()
    if net is None or line_id not in net.lines:
        return jsonify({"error": "Line not found"}), 404
    via = _state["waypoints"].get(line_id, [])
    if idx < 0 or idx >= len(via):
        return jsonify({"error": "Waypoint index out of range"}), 400
    via.pop(idx)
    _recalc_line_length(net, line_id)

    return jsonify({
        "line_id": line_id,
        "via_markers": [{"lat": w["lat"], "lon": w["lon"], "idx": i}
                        for i, w in enumerate(via)],
        "length_m": round(net.lines[line_id].length_m, 1),
    })


def _recalc_line_length(net: Network, line_id: str):
    """Recompute line.length_m to include waypoint path length."""
    from mesh_mobility.engine.network import vincenty_m
    line = net.lines[line_id]
    via  = _state["waypoints"].get(line_id, [])
    pts  = ([(line.start_node.lat, line.start_node.lon)] +
            [(w["lat"], w["lon"]) for w in via] +
            [(line.end_node.lat, line.end_node.lon)])
    line.length_m = sum(
        vincenty_m(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
        for i in range(len(pts) - 1)
    )


# _find_closest_open_pair is in builders.py
from mesh_mobility.gui.builders import _find_closest_open_pair


@api.post("/network/connect_cps")
def connect_cps_endpoint():
    """Connect two stub-pairs: cp_a.out->cp_b.in and cp_b.out->cp_a.in.

    Accepts either explicit CP IDs (cp_a, cp_b) or structure IDs
    (struct_a, struct_b). When structure IDs are given, the closest
    pair of open CPs between the two structures is selected automatically.
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data = request.json or {}

    struct_a = data.get("struct_a")
    struct_b = data.get("struct_b")
    if struct_a and struct_b:
        # Structure-level connect -- find closest open pair
        cp_a, cp_b, err = _find_closest_open_pair(struct_a, struct_b)
        if err:
            return jsonify({"error": err}), 400
        cp_a_id, cp_b_id = cp_a.cp_id, cp_b.cp_id
    else:
        cp_a_id = data.get("cp_a")
        cp_b_id = data.get("cp_b")
        cp_a = _state["cps"].get(cp_a_id)
        cp_b = _state["cps"].get(cp_b_id)
        if cp_a is None or cp_b is None:
            return jsonify({"error": "CP not found"}), 404
        if cp_a.connected_to:
            return jsonify({"error": f"{cp_a_id} is already connected to {cp_a.connected_to}"}), 400
        if cp_b.connected_to:
            return jsonify({"error": f"{cp_b_id} is already connected to {cp_b.connected_to}"}), 400

    lines = connect_cps(net, cp_a, cp_b, _state["cps"])
    if len(lines) == 2:
        _state["line_pairs"][lines[0].line_id] = lines[1].line_id
        _state["line_pairs"][lines[1].line_id] = lines[0].line_id
        _state["line_roles"][lines[0].line_id] = "connector"
        _state["line_roles"][lines[1].line_id] = "connector"
    return jsonify({
        "connected":   [cp_a_id, cp_b_id],
        "lines_added": [l.line_id for l in lines],
    })


@api.post("/network/disconnect_cp")
def disconnect_cp_endpoint():
    """Disconnect a stub-pair from its partner."""
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data  = request.json or {}
    cp_id = data.get("cp_id")
    cp    = _state["cps"].get(cp_id)
    if cp is None:
        return jsonify({"error": "CP not found"}), 404

    disconnect_cp(net, cp, _state["cps"])
    return jsonify({"disconnected": cp_id})


@api.post("/network/structure/<sid>/rotate")
def rotate_structure(sid: str):
    """
    Rotate a structure in place -- preserves all node/line/CP IDs.
    Only lat/lon positions and CP headings are updated.
    Connector lines automatically inherit the new geometry.

    For stations:  { "heading_deg": 45 }
    For circles:   { "arm_headings": [45, 135, 225, 315] }
                   or { "rotation_deg": 45 }  (adds to current headings)
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    struct = _state["structures"].get(sid)
    if struct is None:
        return jsonify({"error": f"Structure {sid} not found"}), 404

    data = request.json or {}

    if struct.structure_type == "station":
        new_h = data.get("heading_deg")
        if new_h is None:
            return jsonify({"error": "heading_deg required"}), 400
        rotate_station(net, struct, _state["cps"], float(new_h))

    elif struct.structure_type == "traffic_circle":
        if "arm_headings" in data:
            new_arms = [float(h) for h in data["arm_headings"]]
        elif "rotation_deg" in data:
            delta = float(data["rotation_deg"])
            new_arms = [(h + delta) % 360 for h in struct.arm_headings]
        else:
            return jsonify({"error": "arm_headings or rotation_deg required"}), 400
        if len(new_arms) != 4:
            return jsonify({"error": "arm_headings must have 4 values"}), 400
        rotate_traffic_circle(net, struct, _state["cps"], new_arms)

    else:
        return jsonify({"error": f"Unknown structure type: {struct.structure_type}"}), 400

    return jsonify({
        "rotated": sid,
        "structure_type": struct.structure_type,
        "heading_deg": struct.heading_deg,
        "arm_headings": struct.arm_headings,
    })


@api.post("/network/structure/<sid>/move")
def move_structure(sid: str):
    """
    Translate a structure by a lat/lon delta -- preserves all IDs.
    Body: { "dlat": ..., "dlon": ... }
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    struct = _state["structures"].get(sid)
    if struct is None:
        return jsonify({"error": f"Structure {sid} not found"}), 404

    data = request.json or {}
    dlat = float(data.get("dlat", 0))
    dlon = float(data.get("dlon", 0))

    new_lat = struct.center_lat + dlat
    new_lon = struct.center_lon + dlon

    overlap_err = check_overlap(new_lat, new_lon, struct.structure_type,
                                 exclude_sid=sid)
    if overlap_err:
        return jsonify({"error": overlap_err}), 400

    struct.center_lat = new_lat
    struct.center_lon = new_lon

    if struct.structure_type == "station":
        rotate_station(net, struct, _state["cps"], struct.heading_deg)
    elif struct.structure_type == "traffic_circle":
        rotate_traffic_circle(net, struct, _state["cps"], struct.arm_headings)

    # Log designer adjustment for Noelle learning
    from mesh_mobility.engine.network import vincenty_m as _vm
    move_dist = _vm(new_lat - dlat, new_lon - dlon, new_lat, new_lon)
    noelle_log("structure_move", {
        "id": sid, "type": struct.structure_type,
        "from": [new_lat - dlat, new_lon - dlon],
        "to": [new_lat, new_lon],
        "distance_m": round(move_dist),
    })

    return jsonify({
        "moved": sid,
        "center_lat": struct.center_lat,
        "center_lon": struct.center_lon,
    })


@api.post("/network/undo/push")
def network_undo_push():
    """Manually push an undo snapshot -- called by browser on drag start."""
    push_undo()
    return jsonify({"ok": True, "undos": len(_state.get("_undo_stack", []))})


@api.post("/network/undo")
def network_undo():
    """Restore the previous network state. Ctrl+Z on the browser calls this."""
    stack = _state.get("_undo_stack", [])
    if not stack:
        return jsonify({"error": "Nothing to undo"}), 400

    snapshot = stack.pop()

    # Load the snapshot as if it were a .jpd file
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".jpd", delete=False) as tmp:
        tmp.write(snapshot)
        tmp_path = tmp.name

    try:
        result = load_jpd(tmp_path)
        net = result[0]
        structs_data = result[1]
        cps_data = result[2]
        file_settings = result[3]
    except Exception as e:
        return jsonify({"error": f"Undo failed: {e}"}), 500
    finally:
        os.unlink(tmp_path)

    _state["network"] = net
    _state["sim_frames"] = []
    _state["sim_result"] = None
    clear_edit_state()
    if structs_data or cps_data:
        restore_structures(structs_data, cps_data, net)
    if file_settings:
        _state["settings"].update(file_settings)
    sync_counters()

    return jsonify({**_network_to_geojson(net), "settings": _state["settings"],
                    "undos_remaining": len(stack)})


# Overlay endpoints moved to overlays.py
# Noelle endpoints moved to noelle_api.py
