"""
mesh_mobility.gui.api
==================
Flask REST API backing the browser GUI.

Endpoints:
  GET  /api/network          → current network as GeoJSON
  POST /api/network/load     → load a .jpd or map.json file
  POST /api/network/save     → save current network as .jpd
  POST /api/network/node     → add a node (station or switch)
  POST /api/network/circle   → add a traffic circle (8-node structure)
  DELETE /api/network/node/<id>    → remove a node + its lines
  POST /api/network/add_line  → add a directed line between two nodes
  POST /api/network/line     → Line tool: build guideway between two map clicks
  DELETE /api/network/line/<id>    → break a line (shift-click)
  POST /api/simulation/run   → run simulation, return results
  GET  /api/simulation/frame/<n>   → pod positions at tick n (for replay)
  GET  /api/settings         → current simulation settings
  POST /api/settings         → update simulation settings
"""

from __future__ import annotations

import heapq
import json
import logging
import math
import os
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request, current_app, Response, g, has_request_context

# Import engine and IO
import sys
_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

# ---------------------------------------------------------------------------
# Shared state — imported from state.py
# ---------------------------------------------------------------------------
import subprocess as _subprocess
import pathlib as _pathlib

from mesh_mobility.gui.state import (
    _state, _net, _ALLIE_CAPTURE,
    ensure_session, set_session_cookie, auto_push_undo,
    push_undo, clear_edit_state, next_sid, sync_counters,
    reconstruct_structures_from_net, restore_structures,
    new_id, footprint_m, check_overlap,
    noelle_log, allie_capture_simulation, allie_capture_error, write_fault,
    cp_by_heading,
)

# ---------------------------------------------------------------------------
# Overlay data — reads from CrashHarvester library
# Harvesting is a separate program. MeshMobility is read-only.
# ---------------------------------------------------------------------------
from CrashHarvester.reader import MobilityData
_md = MobilityData()

from mesh_mobility.engine import Network, Node, Line, Station, Simulator
from mesh_mobility.engine.physics import PhysicsModel
from mesh_mobility.engine.structures import (
    build_traffic_circle, build_station, connect_cps, disconnect_cp,
    rotate_station, rotate_traffic_circle,
    ConnectionPoint, Structure,
)
from mesh_mobility.io import load_jpd, load_podpresenter, load_sketchup_map
from mesh_mobility.io.jpd_writer import save_jpd, serialise_jpd

api = Blueprint("api", __name__, url_prefix="/api")

# Register session lifecycle hooks from state module
api.before_request(ensure_session)
api.after_request(set_session_cookie)
api.before_request(auto_push_undo)


# _detect_state and _get_overlay_center_radius moved to overlays.py

# ---------------------------------------------------------------------------
# Network serialisation → GeoJSON
# ---------------------------------------------------------------------------

def _network_to_geojson(net: Network) -> dict:
    features = []

    # Build reverse map: node_id → structure_id (for tagging internal nodes)
    node_to_struct: Dict[str, str] = {}
    for struct in _state["structures"].values():
        for nid in struct.node_ids:
            node_to_struct[nid] = struct.structure_id

    # CP tip nodes — both stub tips are hidden; replaced by one CP centre feature
    cp_tip_nodes: set = set()
    for cp in _state["cps"].values():
        cp_tip_nodes.add(cp.outbound_node.node_id)
        cp_tip_nodes.add(cp.inbound_node.node_id)

    # Build reverse map: line_id → structure_id (lines whose both endpoints
    # are internal to the same structure — used by the move-drag preview)
    line_to_struct: Dict[str, str] = {}
    for struct in _state["structures"].values():
        struct_nodes = set(struct.node_ids)
        for lid in struct.line_ids:
            line_to_struct[lid] = struct.structure_id

    # Lines → LineString features (thread through waypoints)
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

    # Nodes → Point features
    for nid, node in net.nodes.items():
        is_station = node.node_id in net.stations
        struct_id = node_to_struct.get(nid)
        is_cp_tip = nid in cp_tip_nodes
        # Hide all internal structure nodes (including CP tips — CPs get their own feature)
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

    # One CP feature per connection point — placed at stub-pair midpoint
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


# (traffic circle and station builders are in mesh_mobility.engine.structures)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@api.get("/library")
def get_library():
    """Return the network library index."""
    maps_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "..", "mesh_mobility_maps")
    lib_path = os.path.join(maps_dir, "library.json")
    if os.path.isfile(lib_path):
        with open(lib_path) as f:
            return jsonify(json.load(f))
    # Fallback: scan directory
    networks = []
    if os.path.isdir(maps_dir):
        for fn in sorted(os.listdir(maps_dir)):
            if not fn.endswith(".jpd"):
                continue
            path = os.path.join(maps_dir, fn)
            try:
                with open(path) as f:
                    data = json.load(f)
                structs = data.get("structures", [])
                networks.append({
                    "filename": fn,
                    "name": fn.replace(".jpd", ""),
                    "total": len(structs),
                    "stations": sum(1 for s in structs if s.get("structure_type") == "station"),
                    "circles": sum(1 for s in structs if s.get("structure_type") == "traffic_circle"),
                    "country": "US",
                    "state": "",
                    "city": fn.replace(".jpd", "").replace("_", " "),
                    "developer": "JPods",
                    "modified": "",
                    "size_kb": round(os.path.getsize(path) / 1024),
                })
            except Exception:
                continue
    return jsonify({"networks": networks})


@api.get("/network")
def get_network():
    net = _net()
    if net is None:
        return jsonify({"type": "FeatureCollection", "features": [],
                        "metadata": {"network_id": "empty"}})
    return jsonify(_network_to_geojson(net))


@api.post("/network/load")
def load_network():
    data = request.json or {}
    path = data.get("path", "")
    if not os.path.exists(path):
        return jsonify({"error": f"File not found: {path}"}), 400

    ext = os.path.splitext(path)[1].lower()
    structs_data, cps_data, file_settings = [], [], {}
    try:
        if ext == ".jpd":
            result = load_jpd(path)
            net = result[0]
            structs_data = result[1]
            cps_data = result[2]
            file_settings = result[3]
            file_overlays = result[4] if len(result) > 4 else None
            file_qa = result[5] if len(result) > 5 else None
        else:
            with open(path) as f:
                raw = json.load(f)
            if "lines" in raw:
                net = load_podpresenter(path)
            else:
                net = load_sketchup_map(path)
            file_overlays = None
            file_qa = None
    except Exception as e:
        write_fault(f"Network load failed: {e}", f"path={path}")
        return jsonify({"error": str(e)}), 500

    _state["network"] = net
    _state["network_path"] = path
    _state["sim_frames"] = []
    _state["sim_result"] = None
    noelle_log("network_load", {"path": os.path.basename(path),
                                  "stations": len(net.stations), "nodes": len(net.nodes)})
    clear_edit_state()
    if structs_data or cps_data:
        restore_structures(structs_data, cps_data, net)
    else:
        s, c = reconstruct_structures_from_net(net)
        _state["structures"].update(s)
        _state["cps"].update(c)
    if file_settings:
        _state["settings"].update(file_settings)
    if file_overlays:
        _state["overlays"] = file_overlays
    if file_qa:
        _state["qa"] = file_qa

    # Overlays auto-populate on save, not load — keeps load fast
    sync_counters()
    return jsonify({**_network_to_geojson(net), "settings": _state["settings"]})


@api.post("/network/save")
def save_network():
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data = request.json or {}
    path = data.get("path") or _state.get("network_path")
    if not path:
        return jsonify({"error": "No save path provided"}), 400
    if not path.endswith(".jpd"):
        path = path + ".jpd"

    try:
        save_jpd(net, path, _state["structures"], _state["cps"],
                 _state["settings"], _state.get("overlays"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    _state["network_path"] = path

    # Save a copy to Allie for every public session
    noelle_log("network_save", {"path": os.path.basename(path),
                                  "stations": len(net.stations), "nodes": len(net.nodes)})
    # Archive the .jpd to Allie
    try:
        archive_dir = os.path.join(_NOELLE_LOG_DIR, "networks")
        os.makedirs(archive_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        archive_name = f"{ts}_{os.path.basename(path)}"
        save_jpd(net, os.path.join(archive_dir, archive_name),
                 _state["structures"], _state["cps"],
                 _state["settings"], _state.get("overlays"))
    except Exception:
        pass  # never break the save

    return jsonify({"saved": path})


@api.get("/network/download")
def download_network():
    """Return the current network as a .jpd file download (no server-side path required)."""
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    try:
        content_bytes = serialise_jpd(net, _state["structures"], _state["cps"],
                                      _state["settings"],
                                      _state.get("overlays"))
        # Inject qa and noelle_draft if present
        qa = _state.get("qa")
        if qa:
            d = json.loads(content_bytes)
            d["qa"] = qa
            content_bytes = json.dumps(d, indent=2, ensure_ascii=False).encode("utf-8")
        noelle_draft = _state.get("noelle_draft")
        if noelle_draft:
            d = json.loads(content_bytes)
            d["noelle_draft"] = noelle_draft
            content_bytes = json.dumps(d, indent=2,
                                       ensure_ascii=False).encode("utf-8")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    filename = f"{net.network_id}.jpd"
    return Response(
        content_bytes,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.post("/network/new")
def new_network():
    data = request.json or {}
    nid = data.get("network_id", "untitled")
    _state["network"] = Network(network_id=nid)
    _state["network_path"] = None
    _state["sim_frames"] = []
    _state["sim_result"] = None
    _state["overlays"] = None
    _state["qa"] = None
    clear_edit_state()
    _md.clear_cache()
    return jsonify({"network_id": nid})


@api.post("/network/reload")
def reload_network():
    """Re-read the current network file without restarting the server.

    Equivalent to the SketchUp Reload Plugin button for MeshMobility.
    The developer edits a .jpd or map.json file, then clicks Reload Network
    in the GUI — this is the tool boundary for the process capture cycle.
    """
    path = _state.get("network_path")
    if not path:
        return jsonify({"error": "No network path on record — load a file first"}), 400
    if not os.path.exists(path):
        return jsonify({"error": f"File not found: {path}"}), 400

    ext = os.path.splitext(path)[1].lower()
    structs_data, cps_data, file_settings = [], [], {}
    try:
        if ext == ".jpd":
            net, structs_data, cps_data, file_settings = load_jpd(path)
        else:
            with open(path) as f:
                raw = json.load(f)
            if "lines" in raw:
                net = load_podpresenter(path)
            else:
                net = load_sketchup_map(path)
    except Exception as e:
        write_fault(f"Network reload failed: {e}", f"path={path}")
        return jsonify({"error": str(e)}), 500

    # Clear old simulation results — they are stale after a file change
    _state["network"]      = net
    _state["sim_frames"]   = []
    _state["sim_result"]   = None
    clear_edit_state()
    if structs_data or cps_data:
        restore_structures(structs_data, cps_data, net)
    else:
        s, c = reconstruct_structures_from_net(net)
        _state["structures"].update(s)
        _state["cps"].update(c)
    if file_settings:
        _state["settings"].update(file_settings)
    sync_counters()

    # Capture the reload event — this is the tool boundary
    if _ALLIE_CAPTURE.exists():
        try:
            _subprocess.Popen(
                ["python3", str(_ALLIE_CAPTURE),
                 "--source", "route-time",
                 "--event",  "network_reload",
                 "--message", f"Reloaded {os.path.basename(path)}",
                 "--data",   json.dumps({"path": path, "network_id": net.network_id})],
                stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL,
            )
        except Exception:
            pass

    return jsonify({**_network_to_geojson(net),
                    "settings": _state["settings"],
                    "reloaded": path})


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
    from datetime import datetime, timezone
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

    log.info("[process] → %s", path.name)
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
    Remove a guideway pair — guideways always travel in pairs so both
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


# _find_closest_open_pair moved to builders.py
from mesh_mobility.gui.builders import _find_closest_open_pair


@api.post("/network/connect_cps")
def connect_cps_endpoint():
    """Connect two stub-pairs: cp_a.out→cp_b.in and cp_b.out→cp_a.in.

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
        # Structure-level connect — find closest open pair
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
    Rotate a structure in place — preserves all node/line/CP IDs.
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
    Translate a structure by a lat/lon delta — preserves all IDs.
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
    """Manually push an undo snapshot — called by browser on drag start."""
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
    import tempfile
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


# auto_connect endpoint moved to builders.py


# network_city_mesh endpoint moved to builders.py


# _seg_intersect, _find_crossings, and network_line endpoint moved to builders.py


@api.post("/network/save_drawn_lines")
def save_drawn_lines():
    """Save designer-drawn corridor lines for retrospection and iteration."""
    data = request.json or {}
    lines = data.get("lines", [])
    _state["drawn_lines"] = lines
    # Also save to file for persistence across restarts
    lines_dir = os.path.join(_rt_dir, "drawn_lines")
    os.makedirs(lines_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    path = os.path.join(lines_dir, f"lines_{ts}.json")
    with open(path, "w") as f:
        json.dump({"lines": lines, "saved_at": ts}, f, indent=2)
    # Also save as "latest"
    with open(os.path.join(lines_dir, "lines_latest.json"), "w") as f:
        json.dump({"lines": lines, "saved_at": ts}, f, indent=2)
    log.info(f"Saved {len(lines)} drawn lines to {path}")
    return jsonify({"saved": len(lines), "path": path})


@api.get("/network/drawn_lines")
def get_drawn_lines():
    """Load the most recently saved drawn lines."""
    # Try in-memory first
    if _state.get("drawn_lines"):
        return jsonify({"lines": _state["drawn_lines"]})
    # Try latest file
    path = os.path.join(_rt_dir, "drawn_lines", "lines_latest.json")
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify({"lines": []})


@api.post("/network/build_on_lines")
def network_build_on_lines():
    """Build a network on designer-drawn corridor lines.

    Input: {lines: [[{lat, lon}, ...], ...]}
    Each line is a polyline the designer drew on the map.
    Places stations every ~0.6 mi along each line, oriented to local heading.
    Places traffic circles where lines cross within 400m.
    Connects stations along their line and to circles at intersections.
    """
    from mesh_mobility.engine.network import vincenty_m
    data = request.json or {}
    lines = data.get("lines", [])
    if not lines:
        return jsonify({"error": "No lines provided. Draw corridor lines first."}), 400

    STATION_SPACING_M = 1000  # ~0.6 miles

    # Build new network
    net = Network(network_id="drawn_corridors")
    _state["network"] = net
    clear_edit_state()

    n_stations = 0
    n_circles = 0

    # ── Find where lines cross → traffic circles ──
    circle_points = []
    cross_threshold_m = 400

    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            for pi in lines[i]:
                for pj in lines[j]:
                    dist = vincenty_m(pi["lat"], pi["lon"], pj["lat"], pj["lon"])
                    if dist < cross_threshold_m:
                        mlat = (pi["lat"] + pj["lat"]) / 2
                        mlon = (pi["lon"] + pj["lon"]) / 2
                        too_close = any(vincenty_m(mlat, mlon, c[0], c[1]) < 800
                                        for c in circle_points)
                        if not too_close:
                            circle_points.append((mlat, mlon, [i, j]))
                            break
                else:
                    continue
                break

    # Place traffic circles
    circle_structs = {}
    for clat, clon, line_idxs in circle_points:
        headings = []
        for li in line_idxs:
            pts = lines[li]
            if len(pts) >= 2:
                dlat = pts[-1]["lat"] - pts[0]["lat"]
                dlon = (pts[-1]["lon"] - pts[0]["lon"]) * math.cos(math.radians(pts[0]["lat"]))
                h = math.degrees(math.atan2(dlon, dlat)) % 360
                headings.extend([h, (h + 180) % 360])
        headings = sorted(set(round(h / 10) * 10 for h in headings))
        if len(headings) < 4:
            headings = [0.0, 90.0, 180.0, 270.0]

        struct, cp_dict = build_traffic_circle(
            net, clat, clon,
            structure_id=next_sid("c"),
            arm_headings=[float(h) for h in headings[:8]],
        )
        _state["structures"][struct.structure_id] = struct
        _state["cps"].update(cp_dict)
        circle_structs[(round(clat, 5), round(clon, 5))] = (struct, cp_dict)
        n_circles += 1

    # ── Place stations along each line ──
    all_placed = {}  # line_idx → [(struct, cps, lat, lon, heading)]

    for li, line_pts in enumerate(lines):
        if len(line_pts) < 2:
            continue

        # Cumulative distance along the polyline
        cum_dist = [0.0]
        for k in range(1, len(line_pts)):
            d = vincenty_m(line_pts[k-1]["lat"], line_pts[k-1]["lon"],
                           line_pts[k]["lat"], line_pts[k]["lon"])
            cum_dist.append(cum_dist[-1] + d)
        total_len = cum_dist[-1]
        if total_len < 200:
            continue

        n_seg = max(1, round(total_len / STATION_SPACING_M))
        station_dists = [total_len * i / n_seg for i in range(n_seg + 1)]

        placed = []
        for target_d in station_dists:
            # Interpolate position
            slat, slon = line_pts[-1]["lat"], line_pts[-1]["lon"]
            for k in range(1, len(cum_dist)):
                if cum_dist[k] >= target_d:
                    frac = (target_d - cum_dist[k-1]) / max(1, cum_dist[k] - cum_dist[k-1])
                    slat = line_pts[k-1]["lat"] + (line_pts[k]["lat"] - line_pts[k-1]["lat"]) * frac
                    slon = line_pts[k-1]["lon"] + (line_pts[k]["lon"] - line_pts[k-1]["lon"]) * frac
                    break

            # Skip if too close to a traffic circle
            near_circle = any(vincenty_m(slat, slon, cl, cn) < 300
                              for (cl, cn) in circle_structs)
            if near_circle:
                continue

            # Local heading
            local_heading = 0
            for k in range(1, len(line_pts)):
                if cum_dist[k] >= target_d:
                    dl = line_pts[k]["lat"] - line_pts[k-1]["lat"]
                    dn = (line_pts[k]["lon"] - line_pts[k-1]["lon"]) * math.cos(math.radians(line_pts[k]["lat"]))
                    if abs(dl) + abs(dn) > 0.0001:
                        local_heading = math.degrees(math.atan2(dn, dl)) % 360
                    break

            st, st_cps = build_station(net, slat, slon, heading_deg=local_heading,
                                        structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            placed.append((st, st_cps, slat, slon, local_heading))
            n_stations += 1

        all_placed[li] = placed

        # Connect consecutive stations along this line
        for k in range(1, len(placed)):
            prev_st, prev_cps, _, _, prev_h = placed[k-1]
            cur_st, cur_cps, _, _, cur_h = placed[k]
            cp_out = cp_by_heading(prev_cps, prev_h)
            cp_in = cp_by_heading(cur_cps, (cur_h + 180) % 360)
            if cp_out and cp_in and cp_out.connected_to is None and cp_in.connected_to is None:
                connect_cps(net, cp_out, cp_in, _state["cps"])

    # Connect line endpoints to nearest traffic circles
    for li, placed in all_placed.items():
        if not placed:
            continue
        for endpoint in [placed[0], placed[-1]]:
            st, st_cps, slat, slon, sh = endpoint
            best_dist = 2000
            best_circle = None
            for (clat, clon), (cstruct, ccps) in circle_structs.items():
                d = vincenty_m(slat, slon, clat, clon)
                if d < best_dist:
                    best_dist = d
                    best_circle = (cstruct, ccps, clat, clon)
            if best_circle:
                cstruct, ccps, clat, clon = best_circle
                dl = clat - slat
                dn = (clon - slon) * math.cos(math.radians(slat))
                h_to = math.degrees(math.atan2(dn, dl)) % 360
                cp_st = cp_by_heading(st_cps, h_to)
                cp_tc = cp_by_heading(ccps, (h_to + 180) % 360)
                if cp_st and cp_tc and cp_st.connected_to is None and cp_tc.connected_to is None:
                    connect_cps(net, cp_st, cp_tc, _state["cps"])

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("build_on_lines", {
        "lines": len(lines), "circles": n_circles,
        "stations": n_stations, "total_miles": total_miles,
    })

    return jsonify({
        "lines_used": len(lines),
        "circles": n_circles,
        "stations": n_stations,
        "total_miles": total_miles,
    })


@api.post("/network/crash_mesh")
def network_crash_mesh():
    """Build a network from crash corridor lines.

    5-stage algorithm:
    1. Extract corridor LINES from crash density data (top 10% cells → polylines)
    2. (Future: Option-drag to adjust lines)
    3. Place traffic circles where corridors cross
    4. Place stations along each line, 0.5-0.75 mi apart, oriented to line heading
    5. Connect along lines and between lines at circles
    """
    from mesh_mobility.engine.network import vincenty_m
    data = request.json or {}
    fence = data.get("fence")
    threshold_pct = data.get("threshold_pct", 10)

    if not fence:
        return jsonify({"error": "No city boundary provided"}), 400

    coords = []
    if fence.get("type") == "Polygon":
        coords = fence["coordinates"][0]
    elif fence.get("type") == "MultiPolygon":
        for poly in fence["coordinates"]:
            coords.extend(poly[0])
    if not coords:
        return jsonify({"error": "Invalid boundary polygon"}), 400

    lons_f = [c[0] for c in coords]
    lats_f = [c[1] for c in coords]
    center_lat = (min(lats_f) + max(lats_f)) / 2
    center_lon = (min(lons_f) + max(lons_f)) / 2

    # Detect state
    state_abbr = None
    try:
        from mesh_mobility.scripts.census_overlays import fips_from_latlon, STATE_FIPS_TO_ABBR
        state_fips, _ = fips_from_latlon(center_lat, center_lon)
        if state_fips:
            state_abbr = STATE_FIPS_TO_ABBR.get(state_fips)
    except Exception:
        pass
    if not state_abbr:
        return jsonify({"error": "Cannot determine state for crash data"}), 400

    # Get crash data from library
    span_mi = vincenty_m(min(lats_f), center_lon, max(lats_f), center_lon) / 1609.34
    crash_data = _md.get_crashes(state_abbr, center_lat, center_lon, radius_miles=max(20, span_mi))
    if not crash_data or not crash_data.get("features"):
        return jsonify({"error": f"No crash data for {state_abbr.upper()}. Run CrashHarvester first."}), 404

    # Point-in-polygon filter
    def _pip(px, py, poly):
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    poly_coords = coords

    # Filter crash cells to boundary
    in_boundary = []
    for f in crash_data["features"]:
        lon, lat = f["geometry"]["coordinates"]
        if _pip(lon, lat, poly_coords):
            in_boundary.append(f)

    if not in_boundary:
        return jsonify({"error": "No crash data within boundary"}), 400

    # ── STAGE 1: Extract corridor lines from top crash cells ──────────────
    all_counts = sorted([f["properties"]["crashes"] for f in in_boundary], reverse=True)
    cutoff_idx = max(1, int(len(all_counts) * threshold_pct / 100))
    threshold = all_counts[min(cutoff_idx, len(all_counts) - 1)]
    hot_cells = [(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0],
                  f["properties"]["crashes"])
                 for f in in_boundary if f["properties"]["crashes"] >= threshold]
    log.info(f"Crash Mesh Stage 1: {len(hot_cells)} hot cells (threshold={threshold})")

    # Cluster into corridors: cells within ~500m are same corridor
    cluster_deg = 0.005  # ~500m
    corridors = []  # each corridor = ordered list of (lat, lon)
    used = [False] * len(hot_cells)

    # Sort hottest first — seed corridors from biggest concentrations
    indices = sorted(range(len(hot_cells)), key=lambda i: hot_cells[i][2], reverse=True)

    for seed_idx in indices:
        if used[seed_idx]:
            continue
        corridor = [seed_idx]
        used[seed_idx] = True
        # Grow by adding nearest unused neighbor repeatedly
        grew = True
        while grew:
            grew = False
            tail_lat, tail_lon, _ = hot_cells[corridor[-1]]
            head_lat, head_lon, _ = hot_cells[corridor[0]]
            best_tail = (-1, float("inf"))
            best_head = (-1, float("inf"))
            for j in range(len(hot_cells)):
                if used[j]:
                    continue
                jlat, jlon, _ = hot_cells[j]
                dt = abs(jlat - tail_lat) + abs(jlon - tail_lon)
                dh = abs(jlat - head_lat) + abs(jlon - head_lon)
                if dt < cluster_deg and dt < best_tail[1]:
                    best_tail = (j, dt)
                if dh < cluster_deg and dh < best_head[1]:
                    best_head = (j, dh)
            if best_tail[0] >= 0:
                corridor.append(best_tail[0])
                used[best_tail[0]] = True
                grew = True
            if best_head[0] >= 0 and best_head[0] != best_tail[0]:
                corridor.insert(0, best_head[0])
                used[best_head[0]] = True
                grew = True

        if len(corridor) >= 3:
            # Convert to (lat, lon) list — already ordered by growth
            line = [(hot_cells[i][0], hot_cells[i][1]) for i in corridor]
            corridors.append(line)

    log.info(f"Crash Mesh Stage 1: {len(corridors)} corridor lines extracted")

    # ── STAGE 3: Find where corridors cross → traffic circles ─────────────
    circle_points = []  # (lat, lon, [corridor_indices])
    cross_threshold_m = 400  # corridors within 400m of each other = intersection

    for i in range(len(corridors)):
        for j in range(i + 1, len(corridors)):
            # Check each point on corridor i against corridor j
            for plat, plon in corridors[i]:
                for qlat, qlon in corridors[j]:
                    dist = vincenty_m(plat, plon, qlat, qlon)
                    if dist < cross_threshold_m:
                        # Intersection found — use midpoint
                        mlat = (plat + qlat) / 2
                        mlon = (plon + qlon) / 2
                        # Check not too close to existing circle
                        too_close = False
                        for clat, clon, _ in circle_points:
                            if vincenty_m(mlat, mlon, clat, clon) < 800:
                                too_close = True
                                break
                        if not too_close:
                            circle_points.append((mlat, mlon, [i, j]))
                            break  # one intersection per corridor pair is enough
                else:
                    continue
                break

    log.info(f"Crash Mesh Stage 3: {len(circle_points)} intersection circles")

    # ── STAGE 4 & 5: Build network — circles, stations, connections ───────
    net = Network(network_id="crash_mesh")
    _state["network"] = net
    clear_edit_state()

    n_stations = 0
    n_circles = 0
    STATION_SPACING_M = 1000  # ~0.6 miles

    # Place traffic circles at intersections
    circle_structs = {}  # (lat,lon) → (struct, cp_dict)
    for clat, clon, corridor_idxs in circle_points:
        # Determine arm headings from the corridors that cross here
        headings = []
        for ci in corridor_idxs:
            corr = corridors[ci]
            lat_s, lon_s = corr[0]
            lat_e, lon_e = corr[-1]
            dlat = lat_e - lat_s
            dlon = (lon_e - lon_s) * math.cos(math.radians((lat_s + lat_e) / 2))
            h = math.degrees(math.atan2(dlon, dlat)) % 360
            headings.append(h)
            headings.append((h + 180) % 360)
        # Deduplicate headings that are too close
        headings = sorted(set(round(h / 10) * 10 for h in headings))
        if len(headings) < 4:
            headings = [0.0, 90.0, 180.0, 270.0]

        struct, cp_dict = build_traffic_circle(
            net, clat, clon,
            structure_id=next_sid("c"),
            arm_headings=[float(h) for h in headings[:8]],
        )
        _state["structures"][struct.structure_id] = struct
        _state["cps"].update(cp_dict)
        circle_structs[(round(clat, 5), round(clon, 5))] = (struct, cp_dict)
        n_circles += 1

    # Place stations along each corridor line
    corridor_stations = {}  # corridor_idx → [(struct, cps, lat, lon)]
    for ci, line in enumerate(corridors):
        # Compute cumulative distance along the line
        cum_dist = [0.0]
        for k in range(1, len(line)):
            d = vincenty_m(line[k-1][0], line[k-1][1], line[k][0], line[k][1])
            cum_dist.append(cum_dist[-1] + d)
        total_len = cum_dist[-1]
        if total_len < 200:
            continue

        # Compute corridor heading
        dlat = line[-1][0] - line[0][0]
        dlon = (line[-1][1] - line[0][1]) * math.cos(math.radians((line[0][0] + line[-1][0]) / 2))
        heading = math.degrees(math.atan2(dlon, dlat)) % 360

        # Generate station positions at regular intervals
        n_seg = max(1, round(total_len / STATION_SPACING_M))
        station_dists = [total_len * i / n_seg for i in range(n_seg + 1)]

        placed = []
        for target_d in station_dists:
            # Interpolate position along the polyline
            for k in range(1, len(cum_dist)):
                if cum_dist[k] >= target_d:
                    frac = (target_d - cum_dist[k-1]) / max(1, cum_dist[k] - cum_dist[k-1])
                    slat = line[k-1][0] + (line[k][0] - line[k-1][0]) * frac
                    slon = line[k-1][1] + (line[k][1] - line[k-1][1]) * frac
                    break
            else:
                slat, slon = line[-1]

            # Check if a traffic circle is already close — skip station
            is_circle = False
            for (clat, clon), _ in circle_structs.items():
                if vincenty_m(slat, slon, clat, clon) < 300:
                    is_circle = True
                    break
            if is_circle:
                continue

            # Local heading between neighboring line points
            local_heading = heading
            for k in range(1, len(line)):
                if cum_dist[k] >= target_d:
                    dl = line[k][0] - line[k-1][0]
                    dn = (line[k][1] - line[k-1][1]) * math.cos(math.radians(line[k][0]))
                    if abs(dl) + abs(dn) > 0.0001:
                        local_heading = math.degrees(math.atan2(dn, dl)) % 360
                    break

            st, st_cps = build_station(net, slat, slon, heading_deg=local_heading,
                                        structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            placed.append((st, st_cps, slat, slon, local_heading))
            n_stations += 1

        corridor_stations[ci] = placed

        # Connect consecutive stations along this corridor
        for k in range(1, len(placed)):
            prev_st, prev_cps, _, _, prev_h = placed[k-1]
            cur_st, cur_cps, _, _, cur_h = placed[k]
            cp_out = cp_by_heading(prev_cps, prev_h)
            cp_in = cp_by_heading(cur_cps, (cur_h + 180) % 360)
            if cp_out and cp_in and cp_out.connected_to is None and cp_in.connected_to is None:
                connect_cps(net, cp_out, cp_in, _state["cps"])

    # Connect corridor endpoints to nearest traffic circles
    for ci, placed in corridor_stations.items():
        if not placed:
            continue
        for endpoint in [placed[0], placed[-1]]:
            st, st_cps, slat, slon, sh = endpoint
            best_dist = 2000  # max 2km to connect
            best_circle = None
            best_heading = None
            for (clat, clon), (cstruct, ccps) in circle_structs.items():
                d = vincenty_m(slat, slon, clat, clon)
                if d < best_dist:
                    best_dist = d
                    best_circle = (cstruct, ccps, clat, clon)
            if best_circle:
                cstruct, ccps, clat, clon = best_circle
                # heading from station to circle
                dl = clat - slat
                dn = (clon - slon) * math.cos(math.radians(slat))
                h_to_circle = math.degrees(math.atan2(dn, dl)) % 360
                cp_st = cp_by_heading(st_cps, h_to_circle)
                cp_tc = cp_by_heading(ccps, (h_to_circle + 180) % 360)
                if cp_st and cp_tc and cp_st.connected_to is None and cp_tc.connected_to is None:
                    connect_cps(net, cp_st, cp_tc, _state["cps"])

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("crash_mesh", {
        "corridors": len(corridors),
        "circles": n_circles,
        "stations": n_stations,
        "threshold": threshold,
        "hot_cells": len(hot_cells),
        "total_miles": total_miles,
    })

    return jsonify({
        "corridors": len(corridors),
        "circles": n_circles,
        "stations": n_stations,
        "hot_cells": len(hot_cells),
        "threshold": threshold,
        "total_miles": total_miles,
    })


# network_grid endpoint moved to builders.py


# ---------------------------------------------------------------------------
# Analytical travel times (Dijkstra — used by isochrone)
# ---------------------------------------------------------------------------

@api.get("/network/travel_times")
def network_travel_times():
    """
    Dijkstra-based travel times from a given origin station to all reachable
    stations, using network line lengths and cruise speed.

    Query params:
      origin  — station node_id (e.g. "s32.PLATFORM")
      speed   — cruise speed km/h (optional; falls back to settings)

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

    # Dijkstra over all nodes — edge weight = length_m (metres).
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
        expected = n * (n - 1)  # pairs per sweep × 2 sweeps worth of keys
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

@api.post("/simulation/run")
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

    # Tool boundary — simulation start captured.
    # This is the "Reload Plugin" moment for MeshMobility: the developer changed
    # something and is now testing it. If a fix was being tested, write a TF
    # or TFTS after the run (the browser will prompt).
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


@api.get("/simulation/progress")
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


@api.post("/trip/dispatch")
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


@api.get("/settings")
def get_settings():
    return jsonify(_state["settings"])


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------

@api.get("/demand")
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


@api.post("/demand")
def post_demand():
    """Save demand config to demand.json."""
    data = request.json or {}
    demand_path = os.path.join(_rt_dir, "demand.json")
    with open(demand_path, "w") as f:
        json.dump(data, f, indent=2)
    return jsonify({"ok": True})


@api.post("/settings")
def post_settings():
    updates = request.json or {}
    _state["settings"].update(updates)
    return jsonify(_state["settings"])


# Auto-connect helpers and _best_effort_connect moved to builders.py


# ---------------------------------------------------------------------------
# File upload (browser sends file content as text)
# ---------------------------------------------------------------------------

@api.post("/network/load_text")
def load_network_text():
    """Receive file content from browser file picker, write to temp, load."""
    import tempfile
    data = request.json or {}
    content  = data.get("content", "")
    filename = data.get("filename", "upload.jpd")
    ext = os.path.splitext(filename)[1].lower()

    suffix = ext if ext in (".jpd", ".json") else ".jpd"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    structs_data, cps_data, file_settings, file_overlays, file_qa = [], [], {}, None, None
    try:
        if suffix == ".jpd":
            net, structs_data, cps_data, file_settings, file_overlays, file_qa = load_jpd(tmp_path)
        else:
            with open(tmp_path) as f:
                raw = json.load(f)
            if "lines" in raw:
                net = load_podpresenter(tmp_path)
            else:
                net = load_sketchup_map(tmp_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(tmp_path)

    _state["network"] = net
    _state["network_path"] = None
    _state["sim_frames"] = []
    _state["sim_result"] = None
    clear_edit_state()
    if structs_data or cps_data:
        restore_structures(structs_data, cps_data, net)
    else:
        s, c = reconstruct_structures_from_net(net)
        _state["structures"].update(s)
        _state["cps"].update(c)
    if file_settings:
        _state["settings"].update(file_settings)
    # Restore QA and overlays from loaded file
    if file_qa:
        _state["qa"] = file_qa
    if file_overlays:
        _state["overlays"] = file_overlays

    # Overlays auto-populate on save, not load
    sync_counters()
    return jsonify({**_network_to_geojson(net), "settings": _state["settings"],
                    "overlays": _state.get("overlays")})


@api.post("/network/merge_text")
def merge_network_text():
    """Merge a pasted network INTO the current network (add, don't replace).

    Body:
      content   — .jpd file text
      mode      — "world" (default): keep original lat/lon
                   "center": shift to center_lat/center_lon
      center_lat, center_lon — target center when mode="center"
    """
    import tempfile
    data = request.json or {}
    content = data.get("content", "")
    mode = data.get("mode", "world")
    target_lat = float(data.get("center_lat", 0))
    target_lon = float(data.get("center_lon", 0))

    if not content.strip():
        return jsonify({"error": "No content to merge"}), 400

    # Ensure we have a network to merge into
    if _state["network"] is None:
        _state["network"] = Network(network_id="merged")
        clear_edit_state()

    # Parse the incoming network
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jpd", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        src_net, src_structs, src_cps, src_settings, src_overlays, src_qa = load_jpd(tmp_path)
    except Exception as e:
        return jsonify({"error": f"Parse failed: {e}"}), 500
    finally:
        os.unlink(tmp_path)

    # Calculate offset if mode="center"
    offset_lat, offset_lon = 0.0, 0.0
    if mode == "center" and target_lat != 0:
        # Find center of source network
        src_lats = [s.get("lat", 0) for s in (src_structs or []) if s.get("lat")]
        src_lons = [s.get("lon", 0) for s in (src_structs or []) if s.get("lon")]
        if not src_lats:
            # Try from nodes
            for n in src_net.nodes.values():
                if hasattr(n, "lat") and n.lat:
                    src_lats.append(n.lat)
                    src_lons.append(n.lon)
        if src_lats:
            src_center_lat = sum(src_lats) / len(src_lats)
            src_center_lon = sum(src_lons) / len(src_lons)
            offset_lat = target_lat - src_center_lat
            offset_lon = target_lon - src_center_lon

    # Build ID mapping: old_id → new_id (avoid collisions)
    dst_net = _state["network"]
    id_map = {}

    # Merge nodes with new IDs
    for old_id, node in src_net.nodes.items():
        new_id = old_id
        suffix = 1
        while new_id in dst_net.nodes:
            new_id = f"{old_id}_m{suffix}"
            suffix += 1
        id_map[old_id] = new_id
        node.id = new_id
        if hasattr(node, "lat") and node.lat:
            node.lat += offset_lat
            node.lon += offset_lon
        dst_net.nodes[new_id] = node

    # Merge stations
    for old_id, station in src_net.stations.items():
        new_id = id_map.get(old_id, old_id)
        station.id = new_id
        # Update node references
        if hasattr(station, "node_ids"):
            station.node_ids = [id_map.get(nid, nid) for nid in station.node_ids]
        dst_net.stations[new_id] = station

    # Merge lines with remapped node IDs
    for old_id, line in src_net.lines.items():
        new_id = old_id
        suffix = 1
        while new_id in dst_net.lines:
            new_id = f"{old_id}_m{suffix}"
            suffix += 1
        id_map[old_id] = new_id
        line.id = new_id
        line.start = id_map.get(line.start, line.start)
        line.end = id_map.get(line.end, line.end)
        dst_net.lines[new_id] = line

    # Merge structures metadata with new IDs and offset
    merged_structs = 0
    merged_cps = 0
    for s_data in (src_structs or []):
        old_sid = s_data.get("structure_id", "")
        new_sid = old_sid
        suffix = 1
        while new_sid in _state["structures"]:
            new_sid = f"{old_sid}_m{suffix}"
            suffix += 1
        id_map[old_sid] = new_sid

        s_data["structure_id"] = new_sid
        if offset_lat != 0:
            if "lat" in s_data:
                s_data["lat"] = s_data["lat"] + offset_lat
            if "lon" in s_data:
                s_data["lon"] = s_data["lon"] + offset_lon

        # Remap node_ids and cp_ids
        if "node_ids" in s_data:
            s_data["node_ids"] = [id_map.get(nid, nid) for nid in s_data["node_ids"]]
        if "cp_ids" in s_data:
            s_data["cp_ids"] = [id_map.get(cid, cid) if cid in id_map
                                else cid.replace(old_sid, new_sid, 1)
                                for cid in s_data["cp_ids"]]
        if "line_ids" in s_data:
            s_data["line_ids"] = [id_map.get(lid, lid) if lid in id_map
                                  else lid.replace(old_sid, new_sid, 1)
                                  for lid in s_data["line_ids"]]

        # Create Structure object
        struct = Structure(
            structure_id=new_sid,
            structure_type=s_data.get("structure_type", "station"),
            cp_ids=s_data.get("cp_ids", []),
            node_ids=s_data.get("node_ids", []),
            line_ids=s_data.get("line_ids", []),
            lat=s_data.get("lat"),
            lon=s_data.get("lon"),
            heading_deg=s_data.get("heading_deg", 0),
        )
        _state["structures"][new_sid] = struct
        merged_structs += 1

    # Merge CP metadata
    for cp_data in (src_cps or []):
        old_cpid = cp_data.get("cp_id", "")
        # Find which structure this CP belongs to and remap
        new_cpid = old_cpid
        for old_sid, new_sid in id_map.items():
            if old_cpid.startswith(old_sid + "."):
                new_cpid = old_cpid.replace(old_sid, new_sid, 1)
                break

        cp = ConnectionPoint(
            cp_id=new_cpid,
            structure_id=id_map.get(cp_data.get("structure_id", ""), cp_data.get("structure_id", "")),
            heading_deg=cp_data.get("heading_deg", 0),
            lat=cp_data.get("lat", 0) + offset_lat,
            lon=cp_data.get("lon", 0) + offset_lon,
        )
        # Don't reconnect CPs — leave them open for manual connection
        _state["cps"][new_cpid] = cp
        merged_cps += 1

    # Rebuild network graph
    dst_net.build()
    sync_counters()

    log.info(f"Merged: {merged_structs} structures, {merged_cps} CPs, mode={mode}")
    noelle_log("merge_network", {
        "mode": mode,
        "structures": merged_structs,
        "cps": merged_cps,
        "offset_lat": offset_lat,
        "offset_lon": offset_lon,
    })

    return jsonify({
        **_network_to_geojson(dst_net),
        "merged_structures": merged_structs,
        "merged_cps": merged_cps,
        "mode": mode,
    })


@api.post("/network/load_suggestion")
def load_suggestion():
    """Accept an Allie-suggested GeoJSON network and load it."""
    data = request.json or {}
    geojson = data.get("network")
    if not geojson:
        return jsonify({"error": "No network in suggestion"}), 400
    net = _geojson_to_network(geojson)
    _state["network"] = net
    _state["network_path"] = None
    return jsonify(_network_to_geojson(net))


def _geojson_to_network(geojson: dict) -> Network:
    """Reconstruct a Network from our own GeoJSON format."""
    from mesh_mobility.engine.network import vincenty_m
    meta = geojson.get("metadata", {})
    net = Network(network_id=meta.get("network_id", "suggested"))
    for f in geojson.get("features", []):
        t = f["properties"].get("type", "")
        if t in ("station", "switch"):
            coords = f["geometry"]["coordinates"]
            nid = f["properties"]["node_id"]
            node = Node(nid, coords[1], coords[0], is_station=(t == "station"))
            net.nodes[nid] = node
            if t == "station":
                net.stations[nid] = Station(nid, node)
    for f in geojson.get("features", []):
        if f["properties"].get("type") == "line":
            props = f["properties"]
            lid = props["line_id"]
            sn = net.nodes.get(props["start_node"])
            en = net.nodes.get(props["end_node"])
            if sn and en:
                coords = f["geometry"]["coordinates"]
                length_m = sum(
                    vincenty_m(coords[i][1], coords[i][0], coords[i+1][1], coords[i+1][0])
                    for i in range(len(coords)-1)
                ) if len(coords) > 1 else vincenty_m(sn.lat, sn.lon, en.lat, en.lon)
                line = Line(lid, sn, en, length_m,
                            coordinates=[(c[1], c[0]) for c in coords])
                net.lines[lid] = line
    net.build()
    return net


# Overlay endpoints moved to overlays.py
# Noelle endpoints moved to noelle_api.py
