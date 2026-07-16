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


def _find_closest_open_pair(struct_a_id: str, struct_b_id: str):
    """Find the closest pair of open CPs between two structures."""
    import math
    cps = _state["cps"]
    open_a = [cp for cp in cps.values() if cp.structure_id == struct_a_id and not cp.connected_to]
    open_b = [cp for cp in cps.values() if cp.structure_id == struct_b_id and not cp.connected_to]
    if not open_a:
        return None, None, f"No open CPs on {struct_a_id}"
    if not open_b:
        return None, None, f"No open CPs on {struct_b_id}"
    best_dist = float("inf")
    best_a = best_b = None
    for a in open_a:
        for b in open_b:
            dlat = a.center_lat - b.center_lat
            dlon = a.center_lon - b.center_lon
            d = math.sqrt(dlat * dlat + dlon * dlon)
            if d < best_dist:
                best_dist = d
                best_a, best_b = a, b
    return best_a, best_b, None


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


@api.post("/network/autoconnect")
def auto_connect():
    """
    Best-effort auto-connection of placed stations and circles.

    Rules:
      1. Operates on CPs (stub-pairs), not raw nodes — each CP connects once.
      2. CPs on the outer perimeter of the network are skipped; they are
         boundary gates left for the user to connect to adjacent networks.
      3. Greedy nearest-neighbor matching on the remaining inner CPs.
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    if len(_state["cps"]) < 2:
        return jsonify({"error":
            "No stub-pairs found. Place stations or traffic circles first — "
            "auto-connect only links stub-pairs, never internal nodes."}), 400

    added = _best_effort_connect(net, _state["cps"], _state["line_pairs"])
    for l in added:
        _state["line_roles"][l.line_id] = "connector"
    net.build()
    return jsonify({"lines_added": [l.line_id for l in added],
                    "count": len(added),
                    "skipped_outer": _last_autoconnect_skipped})


# ---------------------------------------------------------------------------
# Grid generator
# ---------------------------------------------------------------------------

_MI_TO_M = 1609.344


@api.post("/network/city_mesh")
def network_city_mesh():
    """Generate a mesh network within a city boundary.

    Auto-detects spacing (1x1 or 1x2 mile) based on city size.
    Queries Overpass API for major road intersections and snaps circles to them.
    Fills the boundary polygon, not a rectangle.
    """
    import urllib.request
    data = request.json or {}
    fence = data.get("fence")
    if not fence:
        return jsonify({"error": "No city boundary provided"}), 400

    # Compute bounding box and centroid from fence polygon
    coords = []
    if fence.get("type") == "Polygon":
        coords = fence["coordinates"][0]
    elif fence.get("type") == "MultiPolygon":
        for poly in fence["coordinates"]:
            coords.extend(poly[0])
    if not coords:
        return jsonify({"error": "Invalid boundary polygon"}), 400

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2

    # City span in miles
    from mesh_mobility.engine.network import vincenty_m
    span_ns_mi = vincenty_m(min_lat, center_lon, max_lat, center_lon) / 1609.34
    span_ew_mi = vincenty_m(center_lat, min_lon, center_lat, max_lon) / 1609.34

    # Auto-pick spacing: Noelle's rule
    # Small city (<6 mi): 1x1
    # Medium city: longer axis gets 2 mi spacing, shorter gets 1 mi
    if max(span_ns_mi, span_ew_mi) < 6:
        spacing_ns = 1.0
        spacing_ew = 1.0
        spacing_label = "1×1 mi"
    elif span_ns_mi > span_ew_mi:
        spacing_ns = 2.0
        spacing_ew = 1.0
        spacing_label = "2×1 mi (N-S longer)"
    else:
        spacing_ns = 1.0
        spacing_ew = 2.0
        spacing_label = "1×2 mi (E-W longer)"

    log.info(f"City Mesh: {span_ns_mi:.1f}×{span_ew_mi:.1f} mi → {spacing_label}")

    # Generate grid points within the boundary
    dlat_per_m = 1.0 / 111_320.0
    dlon_per_m = 1.0 / (111_320.0 * math.cos(math.radians(center_lat)))
    ns_m = spacing_ns * _MI_TO_M
    ew_m = spacing_ew * _MI_TO_M
    dlat = ns_m * dlat_per_m
    dlon = ew_m * dlon_per_m

    # Build a shapely-like point-in-polygon test using ray casting
    def _point_in_polygon(lat, lon, polygon_coords):
        """Ray casting algorithm for point-in-polygon."""
        n = len(polygon_coords)
        inside = False
        j = n - 1
        for i in range(n):
            yi, xi = polygon_coords[i][1], polygon_coords[i][0]
            yj, xj = polygon_coords[j][1], polygon_coords[j][0]
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # Get the polygon ring for containment test
    if fence.get("type") == "Polygon":
        poly_ring = fence["coordinates"][0]
    else:
        # MultiPolygon — use the largest ring
        poly_ring = max(fence["coordinates"], key=lambda p: len(p[0]))[0]

    # Try to fetch road intersections from Overpass API
    intersections = []
    try:
        bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
        overpass_query = f"""
        [out:json][timeout:30];
        (
          node["highway"="traffic_signals"]({bbox});
          node["highway"="crossing"]({bbox});
        );
        out body;
        """
        overpass_url = "https://overpass-api.de/api/interpreter"
        req_data = f"data={urllib.parse.quote(overpass_query)}".encode()
        req = urllib.request.Request(overpass_url, data=req_data,
                                     headers={"User-Agent": "JPods/MeshMobility"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            osm_data = json.loads(resp.read().decode())
        for elem in osm_data.get("elements", []):
            if "lat" in elem and "lon" in elem:
                intersections.append((elem["lat"], elem["lon"]))
        log.info(f"City Mesh: {len(intersections)} road intersections from Overpass")
    except Exception as e:
        log.warning(f"City Mesh: Overpass query failed ({e}) — using grid points directly")

    # Generate grid intersection points within the boundary
    n_rows = int((max_lat - min_lat) / dlat) + 2
    n_cols = int((max_lon - min_lon) / dlon) + 2
    start_lat = max_lat + dlat * 0.5
    start_lon = min_lon - dlon * 0.5

    grid_points = []
    for r in range(n_rows):
        for c in range(n_cols):
            lat = start_lat - r * dlat
            lon = start_lon + c * dlon
            if _point_in_polygon(lat, lon, poly_ring):
                grid_points.append((lat, lon, r, c))

    if not grid_points:
        return jsonify({"error": "No grid points fall within city boundary"}), 400

    # Filter to urban areas — only keep grid points near CrashHarvester library data
    urban_pts = []
    state_abbr, _, _ = _detect_state()
    if state_abbr:
        for dtype in ("population_density", "crash", "traffic", "fatal"):
            lib_data = _md.get_census(dtype, state_abbr) if dtype == "population_density" else \
                       _md._get(dtype, state_abbr, None, None, None)
            if lib_data:
                for feat in lib_data.get("features", []):
                    coords = feat.get("geometry", {}).get("coordinates")
                    if coords:
                        urban_pts.append((coords[1], coords[0]))

    if urban_pts:
        # Keep grid points within 2 miles of any data signal
        threshold_deg = 0.035  # ~2.4 miles quick pre-filter
        filtered = []
        for glat, glon, r, c in grid_points:
            for ulat, ulon in urban_pts:
                if abs(glat - ulat) < threshold_deg and abs(glon - ulon) < threshold_deg:
                    filtered.append((glat, glon, r, c))
                    break
        log.info(f"City Mesh: urban filter {len(grid_points)} → {len(filtered)} grid points "
                 f"({len(urban_pts)} data signal points)")
        if filtered:
            grid_points = filtered

    # Cap at 10×10 grid (100 circles max) — use Custom Mesh for larger
    if len(grid_points) > 100:
        log.info(f"City Mesh: capping {len(grid_points)} points to 100")
        # Keep the densest cluster — sort by proximity to centroid
        grid_points.sort(key=lambda p: (p[0] - center_lat)**2 + (p[1] - center_lon)**2)
        grid_points = grid_points[:100]

    # Snap grid points to nearest road intersection (within 800m)
    snap_threshold_m = 800
    snapped = []
    for glat, glon, r, c in grid_points:
        best_dist = snap_threshold_m
        best_lat, best_lon = glat, glon
        for ilat, ilon in intersections:
            d = vincenty_m(glat, glon, ilat, ilon)
            if d < best_dist:
                best_dist = d
                best_lat = ilat
                best_lon = ilon
        snapped.append((best_lat, best_lon, r, c))

    # Build the network — new network
    net = Network(network_id="city_mesh")
    _state["network"] = net
    clear_edit_state()

    # Place circles at snapped grid points
    grid_map = {}  # (r, c) → (struct, cp_dict)
    for lat, lon, r, c in snapped:
        struct, cp_dict = build_traffic_circle(
            net, lat, lon,
            structure_id=next_sid("c"),
            arm_headings=[0.0, 90.0, 180.0, 270.0],
        )
        _state["structures"][struct.structure_id] = struct
        _state["cps"].update(cp_dict)
        grid_map[(r, c)] = (struct, cp_dict)

    # Place stations between adjacent circles and connect
    _STATION_SPACING_MI = 0.75
    n_stations = 0

    def _stations_for_block(block_mi):
        if block_mi <= 1.05:
            return [0.5]
        n = max(1, round(block_mi / _STATION_SPACING_MI))
        return [(i + 1) / (n + 1) for i in range(n)]

    # N-S connections
    rc_set = set(grid_map.keys())
    for (r, c) in sorted(rc_set):
        if (r + 1, c) not in rc_set:
            continue
        s_north = grid_map[(r, c)]
        s_south = grid_map[(r + 1, c)]
        lat_n, lon_n = s_north[0].center_lat, s_north[0].center_lon
        lat_s, lon_s = s_south[0].center_lat, s_south[0].center_lon
        block_mi = vincenty_m(lat_n, lon_n, lat_s, lon_s) / 1609.34
        positions = _stations_for_block(block_mi)
        prev_cps = None
        prev_sid = None
        for pi, frac in enumerate(positions):
            slat = lat_n + (lat_s - lat_n) * frac
            slon = lon_n + (lon_s - lon_n) * frac
            st, st_cps = build_station(net, slat, slon, heading_deg=0.0,
                                       structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            if pi == 0:
                _, cp_dict_north = s_north
                tc_south = cp_by_heading(cp_dict_north, 180.0)
                st_north = st_cps.get(f"{st.structure_id}.CP_near_far")
                if tc_south and st_north and tc_south.connected_to is None and st_north.connected_to is None:
                    connect_cps(net, tc_south, st_north, _state["cps"])
            elif prev_cps:
                st_north = st_cps.get(f"{st.structure_id}.CP_near_far")
                prev_south = prev_cps.get(f"{prev_sid}.CP_far_near")
                if prev_south and st_north and prev_south.connected_to is None and st_north.connected_to is None:
                    connect_cps(net, prev_south, st_north, _state["cps"])

            if pi == len(positions) - 1:
                _, cp_dict_south = s_south
                tc_north = cp_by_heading(cp_dict_south, 0.0)
                st_south_cp = st_cps.get(f"{st.structure_id}.CP_far_near")
                if tc_north and st_south_cp and tc_north.connected_to is None and st_south_cp.connected_to is None:
                    connect_cps(net, st_south_cp, tc_north, _state["cps"])

            prev_cps = st_cps
            prev_sid = st.structure_id

    # E-W connections
    for (r, c) in sorted(rc_set):
        if (r, c + 1) not in rc_set:
            continue
        s_west = grid_map[(r, c)]
        s_east = grid_map[(r, c + 1)]
        lat_w, lon_w = s_west[0].center_lat, s_west[0].center_lon
        lat_e, lon_e = s_east[0].center_lat, s_east[0].center_lon
        block_mi = vincenty_m(lat_w, lon_w, lat_e, lon_e) / 1609.34
        positions = _stations_for_block(block_mi)
        prev_cps = None
        prev_sid = None
        for pi, frac in enumerate(positions):
            slat = lat_w + (lat_e - lat_w) * frac
            slon = lon_w + (lon_e - lon_w) * frac
            st, st_cps = build_station(net, slat, slon, heading_deg=90.0,
                                       structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            if pi == 0:
                _, cp_dict_west = s_west
                tc_east = cp_by_heading(cp_dict_west, 90.0)
                st_west_cp = st_cps.get(f"{st.structure_id}.CP_far_near")
                if tc_east and st_west_cp and tc_east.connected_to is None and st_west_cp.connected_to is None:
                    connect_cps(net, tc_east, st_west_cp, _state["cps"])
            elif prev_cps:
                st_west_cp = st_cps.get(f"{st.structure_id}.CP_far_near")
                prev_east = prev_cps.get(f"{prev_sid}.CP_near_far")
                if prev_east and st_west_cp and prev_east.connected_to is None and st_west_cp.connected_to is None:
                    connect_cps(net, prev_east, st_west_cp, _state["cps"])

            if pi == len(positions) - 1:
                _, cp_dict_east = s_east
                tc_west = cp_by_heading(cp_dict_east, 270.0)
                st_east_cp = st_cps.get(f"{st.structure_id}.CP_near_far")
                if tc_west and st_east_cp and tc_west.connected_to is None and st_east_cp.connected_to is None:
                    connect_cps(net, st_east_cp, tc_west, _state["cps"])

            prev_cps = st_cps
            prev_sid = st.structure_id

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("city_mesh", {
        "circles": len(grid_map),
        "stations": n_stations,
        "spacing": spacing_label,
        "intersections_snapped": len(intersections),
        "total_miles": total_miles,
    })

    return jsonify({
        "circles": len(grid_map),
        "stations": n_stations,
        "spacing": spacing_label,
        "intersections_snapped": len(intersections),
        "total_miles": total_miles,
        "span_ns_mi": round(span_ns_mi, 1),
        "span_ew_mi": round(span_ew_mi, 1),
    })


def _seg_intersect(p1, p2, p3, p4):
    """Return (lat, lon) where segment p1-p2 crosses p3-p4, or None.
    Each point is (lat, lon).  Uses 2D line-segment intersection."""
    x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if 0 < t < 1 and 0 < u < 1:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _find_crossings(lat1, lon1, lat2, lon2):
    """Find existing connections that cross the line from (lat1,lon1) to (lat2,lon2).
    Returns list of (intersection_lat, intersection_lon, cp_a, cp_b) where
    cp_a and cp_b are the two CPs of the crossed connection."""
    seen = set()
    crossings = []
    for cp in _state["cps"].values():
        if cp.connected_to is None:
            continue
        pair = tuple(sorted([cp.cp_id, cp.connected_to]))
        if pair in seen:
            continue
        seen.add(pair)
        partner = _state["cps"].get(cp.connected_to)
        if not partner:
            continue
        s_a = _state["structures"].get(cp.structure_id)
        s_b = _state["structures"].get(partner.structure_id)
        if not s_a or not s_b:
            continue
        pt = _seg_intersect(
            (lat1, lon1), (lat2, lon2),
            (s_a.center_lat, s_a.center_lon), (s_b.center_lat, s_b.center_lon),
        )
        if pt:
            crossings.append((pt[0], pt[1], cp, partner))
    return crossings


@api.post("/network/line")
def network_line():
    """Build a guideway between two user-clicked points.
    Stations every mile along the line, oriented along the line direction.
    Airport-to-city connector. Adds to existing network (does not replace).
    Where the new line crosses an existing connection, a traffic circle is
    inserted and the old connection is re-routed through it."""
    from mesh_mobility.engine.network import vincenty_m
    data = request.json or {}
    p1 = data.get("point1")  # {lat, lon}
    p2 = data.get("point2")  # {lat, lon}
    if not p1 or not p2:
        return jsonify({"error": "Two points required (point1, point2 with lat/lon)"}), 400

    lat1, lon1 = float(p1["lat"]), float(p1["lon"])
    lat2, lon2 = float(p2["lat"]), float(p2["lon"])
    total_m = vincenty_m(lat1, lon1, lat2, lon2)
    total_mi = total_m / 1609.34

    # Station spacing: 1 mile, minimum 2 stations (at endpoints)
    station_spacing_mi = 1.0
    n_stations = max(2, round(total_mi / station_spacing_mi) + 1)

    # Heading from point1 to point2
    dlat = lat2 - lat1
    dlon = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    heading = math.degrees(math.atan2(dlon, dlat)) % 360

    # Use existing network or create new
    net = _state.get("network")
    if not net:
        net = Network(network_id="line")
        _state["network"] = net
        clear_edit_state()
    sync_counters()

    # Find where the new line crosses existing connections
    crossings = _find_crossings(lat1, lon1, lat2, lon2)
    # Express crossing positions as fraction along the line (0..1)
    cross_fracs = []
    for clat, clon, cp_a, cp_b in crossings:
        if abs(lat2 - lat1) > abs(lon2 - lon1):
            frac = (clat - lat1) / (lat2 - lat1)
        else:
            frac = (clon - lon1) / (lon2 - lon1)
        cross_fracs.append((frac, clat, clon, cp_a, cp_b))
    cross_fracs.sort(key=lambda x: x[0])

    # Build the position list: evenly spaced stations + crossing insertions
    # Each entry: (frac, lat, lon, is_crossing, crossing_data)
    positions = []
    for i in range(n_stations):
        frac = i / max(1, n_stations - 1)
        slat = lat1 + (lat2 - lat1) * frac
        slon = lon1 + (lon2 - lon1) * frac
        positions.append((frac, slat, slon, False, None))

    # Insert crossing points — if a station is too close, shift it along the
    # line (halfway toward its nearest neighbor) so no station is lost.
    min_sep_m = 483  # 0.3 mi — minimum separation before shifting
    for cf, clat, clon, cp_a, cp_b in cross_fracs:
        # Find the nearest non-crossing station
        nearest_idx = None
        best_dist = float("inf")
        for idx, (pf, plat, plon, is_cross, _) in enumerate(positions):
            if is_cross:
                continue
            d = vincenty_m(clat, clon, plat, plon)
            if d < best_dist:
                best_dist = d
                nearest_idx = idx

        if best_dist < min_sep_m and nearest_idx is not None:
            # Shift the displaced station halfway toward its nearest neighbor
            old_frac = positions[nearest_idx][0]
            # Find the neighbor on the opposite side from the crossing
            neighbor_frac = None
            for idx, (pf, _, _, is_cross, _) in enumerate(positions):
                if idx == nearest_idx or is_cross:
                    continue
                # Pick the neighbor on the far side from the crossing
                if (old_frac <= cf and pf < old_frac) or (old_frac >= cf and pf > old_frac):
                    if neighbor_frac is None or abs(pf - old_frac) < abs(neighbor_frac - old_frac):
                        neighbor_frac = pf
            if neighbor_frac is None:
                # No neighbor on the far side — try the other direction
                for idx, (pf, _, _, is_cross, _) in enumerate(positions):
                    if idx == nearest_idx or is_cross:
                        continue
                    if neighbor_frac is None or abs(pf - old_frac) < abs(neighbor_frac - old_frac):
                        neighbor_frac = pf
            if neighbor_frac is not None:
                shift_frac = (old_frac + neighbor_frac) / 2.0
                shift_lat = lat1 + (lat2 - lat1) * shift_frac
                shift_lon = lon1 + (lon2 - lon1) * shift_frac
                # Only shift if the new position has enough room from the crossing
                if vincenty_m(clat, clon, shift_lat, shift_lon) >= min_sep_m:
                    positions[nearest_idx] = (shift_frac, shift_lat, shift_lon, False, None)
                else:
                    # Not enough room — designer can remove the station if unwanted
                    pass

        # Insert the crossing traffic circle
        positions.append((cf, clat, clon, True, (cp_a, cp_b)))
    positions.sort(key=lambda x: x[0])

    # Place structures along the line
    placed = []
    circles_inserted = 0
    for frac, slat, slon, is_crossing, cross_data in positions:
        if is_crossing:
            # Place a traffic circle at the crossing
            # Arms aligned to both the new line heading and the crossed connection
            cp_a, cp_b = cross_data
            s_a = _state["structures"].get(cp_a.structure_id)
            s_b = _state["structures"].get(cp_b.structure_id)
            # Heading of the crossed connection
            cdlat = s_b.center_lat - s_a.center_lat
            cdlon = (s_b.center_lon - s_a.center_lon) * math.cos(math.radians(slat))
            cross_heading = math.degrees(math.atan2(cdlon, cdlat)) % 360
            arms = [
                heading % 360,
                cross_heading % 360,
                (heading + 180) % 360,
                (cross_heading + 180) % 360,
            ]
            tc, tc_cps = build_traffic_circle(net, slat, slon,
                                               structure_id=next_sid("c"),
                                               arm_headings=arms)
            _state["structures"][tc.structure_id] = tc
            _state["cps"].update(tc_cps)
            placed.append((tc, tc_cps))
            circles_inserted += 1

            # Disconnect the old crossed connection
            disconnect_cp(net, cp_a, _state["cps"])

            # Reconnect through the traffic circle
            # cp_a's structure → TC arm closest to cp_a heading
            # cp_b's structure → TC arm closest to cp_b heading
            tc_to_a = cp_by_heading(tc_cps, (cross_heading + 180) % 360)
            tc_to_b = cp_by_heading(tc_cps, cross_heading % 360)
            if tc_to_a and cp_a.connected_to is None:
                connect_cps(net, tc_to_a, cp_a, _state["cps"])
            if tc_to_b and cp_b.connected_to is None:
                connect_cps(net, tc_to_b, cp_b, _state["cps"])
        else:
            st, st_cps = build_station(net, slat, slon, heading_deg=heading,
                                        structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            placed.append((st, st_cps))

    # Connect consecutive structures along the line
    connected = 0
    for i in range(len(placed) - 1):
        st_a, cps_a = placed[i]
        st_b, cps_b = placed[i + 1]
        cp_out = cps_a.get(f"{st_a.structure_id}.CP_near_far")
        cp_in = cps_b.get(f"{st_b.structure_id}.CP_far_near")
        if not cp_out:
            cp_out = cp_by_heading(cps_a, heading)
        if not cp_in:
            cp_in = cp_by_heading(cps_b, (heading + 180) % 360)
        if cp_out and cp_in and cp_out.connected_to is None and cp_in.connected_to is None:
            connect_cps(net, cp_out, cp_in, _state["cps"])
            connected += 1

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("line_build", {
        "stations": len([p for p in placed if p[0].structure_type == "station"]),
        "circles_inserted": circles_inserted,
        "connected": connected,
        "heading": round(heading, 1), "length_mi": round(total_mi, 1),
    })

    return jsonify({
        "stations": len([p for p in placed if p[0].structure_type == "station"]),
        "circles_inserted": circles_inserted,
        "connected": connected,
        "heading_deg": round(heading, 1),
        "line_miles": round(total_mi, 1),
        "total_miles": total_miles,
    })


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


@api.post("/network/grid")
def network_grid():
    """
    Generate a rectangular grid network:
      - Traffic circles at every intersection
      - One station at the midpoint of every block (between adjacent circles)
      - CPs connected: circle ↔ station ↔ circle along each axis

    Body (all distances in miles):
      center_lat, center_lon  — geographic centre of the grid
      spacing_ns              — up-down block size  (default 1.0)
      spacing_ew              — left-right block size  (default 1.0)
      extent_ns               — total up-down span  (default 4.0)
      extent_ew               — total left-right span  (default 4.0)
      angle_deg               — grid rotation in degrees CW from north (default 0)
      replace                 — if true (default), clear existing network first
    """
    data = request.json or {}
    center_lat = float(data.get("center_lat", 37.31))
    center_lon = float(data.get("center_lon", -121.87))
    spacing_ns = float(data.get("spacing_ns", 1.0))
    spacing_ew = float(data.get("spacing_ew", 1.0))
    extent_ns  = float(data.get("extent_ns",  4.0))
    extent_ew  = float(data.get("extent_ew",  4.0))
    angle_deg  = float(data.get("angle_deg",  0.0))
    replace    = bool(data.get("replace", True))

    if replace:
        net = Network(network_id="grid")
        _state["network"] = net
        clear_edit_state()
    else:
        net = _net()
        if net is None:
            net = Network(network_id="grid")
            _state["network"] = net

    # Convert miles → metres
    ns_m = spacing_ns * _MI_TO_M
    ew_m = spacing_ew * _MI_TO_M

    # Degrees per metre at this latitude
    dlat_per_m = 1.0 / 111_320.0
    dlon_per_m = 1.0 / (111_320.0 * math.cos(math.radians(center_lat)))

    n_rows = max(2, round(extent_ns / spacing_ns) + 1)
    n_cols = max(2, round(extent_ew / spacing_ew) + 1)

    # Rotation: angle_deg is clockwise from north
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    def _rotated(row_idx, col_idx):
        """Return (lat, lon) for grid position (row, col) with rotation applied.
        Rotate in metres (uniform scale), then convert to lat/lon."""
        # Offsets from center in metres (before rotation)
        # Row axis goes "down" (south), col axis goes "right" (east)
        dy_m = ((n_rows - 1) / 2.0 - row_idx) * ns_m   # positive = north
        dx_m = (col_idx - (n_cols - 1) / 2.0) * ew_m    # positive = east
        # Clockwise rotation (north = +y, east = +x)
        rot_dy = dy_m * cos_a - dx_m * sin_a
        rot_dx = dx_m * cos_a + dy_m * sin_a
        # Convert metres back to degrees
        lat = center_lat + rot_dy * dlat_per_m
        lon = center_lon + rot_dx * dlon_per_m
        return lat, lon

    # Arm headings for traffic circles, rotated by grid angle
    arm_headings = [(h + angle_deg) % 360 for h in [0.0, 90.0, 180.0, 270.0]]

    # ── 1. Build traffic circles at every intersection ──────────────────────
    grid: List[List] = []          # grid[r][c] = (struct, cp_dict)
    for r in range(n_rows):
        row = []
        for c in range(n_cols):
            lat, lon = _rotated(r, c)
            struct, cp_dict = build_traffic_circle(
                net, lat, lon,
                structure_id=next_sid("c"),
                arm_headings=arm_headings,
            )
            _state["structures"][struct.structure_id] = struct
            _state["cps"].update(cp_dict)
            row.append((struct, cp_dict))
        grid.append(row)

    n_stations = 0
    _STATION_SPACING_MI = 0.75  # target spacing between stations on long blocks

    def _stations_for_block(block_mi):
        """How many stations to place on a block, and their fractional positions.
        1 mile or less = 1 station at midpoint. Longer = ~0.75mi apart, evenly spaced."""
        if block_mi <= 1.05:
            return [0.5]  # single station at midpoint
        n = max(1, round(block_mi / _STATION_SPACING_MI))
        return [(i + 1) / (n + 1) for i in range(n)]

    # ── 2. Up-down blocks: stations between (r,c) and (r+1,c) ──────────────
    for r in range(n_rows - 1):
        for c in range(n_cols):
            positions = _stations_for_block(spacing_ns)
            prev_cps = None  # for chaining station-to-station
            for pi, frac in enumerate(positions):
                lat, lon = _rotated(r + frac, c)
                st, st_cps = build_station(net, lat, lon,
                                           heading_deg=(0.0 + angle_deg) % 360,
                                           structure_id=next_sid("s"))
                _state["structures"][st.structure_id] = st
                _state["cps"].update(st_cps)
                n_stations += 1

                # Rotated arm headings for CP lookups
                h_north = (0.0 + angle_deg) % 360
                h_south = (180.0 + angle_deg) % 360

                if pi == 0:
                    # First station: connect to upper circle's down arm
                    _, cp_dict_north = grid[r][c]
                    tc_south = cp_by_heading(cp_dict_north, h_south)
                    st_north = st_cps.get(f"{st.structure_id}.CP_near_far")
                    if tc_south and st_north and tc_south.connected_to is None and st_north.connected_to is None:
                        connect_cps(net, tc_south, st_north, _state["cps"])
                else:
                    # Chain: connect to previous station's down CP
                    st_north = st_cps.get(f"{st.structure_id}.CP_near_far")
                    if prev_cps and st_north and st_north.connected_to is None:
                        prev_south = prev_cps.get(f"{prev_sid}.CP_far_near")
                        if prev_south and prev_south.connected_to is None:
                            connect_cps(net, prev_south, st_north, _state["cps"])

                if pi == len(positions) - 1:
                    # Last station: connect to lower circle's up arm
                    _, cp_dict_south = grid[r + 1][c]
                    tc_north = cp_by_heading(cp_dict_south, h_north)
                    st_south = st_cps.get(f"{st.structure_id}.CP_far_near")
                    if tc_north and st_south and tc_north.connected_to is None and st_south.connected_to is None:
                        connect_cps(net, st_south, tc_north, _state["cps"])

                prev_cps = st_cps
                prev_sid = st.structure_id

    # ── 3. Left-right blocks: stations between (r,c) and (r,c+1) ─────────
    for r in range(n_rows):
        for c in range(n_cols - 1):
            positions = _stations_for_block(spacing_ew)
            prev_cps = None
            for pi, frac in enumerate(positions):
                lat, lon = _rotated(r, c + frac)
                st, st_cps = build_station(net, lat, lon,
                                           heading_deg=(90.0 + angle_deg) % 360,
                                           structure_id=next_sid("s"))
                _state["structures"][st.structure_id] = st
                _state["cps"].update(st_cps)
                n_stations += 1

                # Rotated arm headings for CP lookups
                h_east = (90.0 + angle_deg) % 360
                h_west = (270.0 + angle_deg) % 360

                if pi == 0:
                    # First station: connect to left circle's right arm
                    _, cp_dict_west = grid[r][c]
                    tc_east = cp_by_heading(cp_dict_west, h_east)
                    st_west = st_cps.get(f"{st.structure_id}.CP_far_near")
                    if tc_east and st_west and tc_east.connected_to is None and st_west.connected_to is None:
                        connect_cps(net, tc_east, st_west, _state["cps"])
                else:
                    # Chain: connect to previous station's right CP
                    st_west = st_cps.get(f"{st.structure_id}.CP_far_near")
                    if prev_cps and st_west and st_west.connected_to is None:
                        prev_east = prev_cps.get(f"{prev_sid}.CP_near_far")
                        if prev_east and prev_east.connected_to is None:
                            connect_cps(net, prev_east, st_west, _state["cps"])

                if pi == len(positions) - 1:
                    # Last station: connect to right circle's left arm
                    _, cp_dict_east = grid[r][c + 1]
                    tc_west = cp_by_heading(cp_dict_east, h_west)
                    st_east = st_cps.get(f"{st.structure_id}.CP_near_far")
                    if tc_west and st_east and tc_west.connected_to is None and st_east.connected_to is None:
                        connect_cps(net, st_east, tc_west, _state["cps"])

                prev_cps = st_cps
                prev_sid = st.structure_id

    net.build()
    return jsonify({
        "circles":   n_rows * n_cols,
        "stations":  n_stations,
        "rows":      n_rows,
        "cols":      n_cols,
        "spacing_ns_mi": spacing_ns,
        "spacing_ew_mi": spacing_ew,
        "angle_deg": angle_deg,
    })


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


# ---------------------------------------------------------------------------
# Auto-connect: CP-based nearest-neighbor matching
# ---------------------------------------------------------------------------

_last_autoconnect_skipped: List[str] = []  # cp_ids skipped as outer boundary


# ---------------------------------------------------------------------------
# Auto-connect geometry helpers
# ---------------------------------------------------------------------------

def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing from point 1 to point 2, degrees [0, 360)."""
    import math
    dlon = math.radians(lon2 - lon1)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _angular_diff(a: float, b: float) -> float:
    """Smallest unsigned angle between two headings, degrees [0, 180]."""
    return abs((a - b + 180) % 360 - 180)


def _cps_are_compatible(cp_a, cp_b) -> bool:
    """
    Two CPs are compatible for auto-connect when both directional rules pass:

    Rule 1 — Direction cone (±45°):
      The geographic bearing from cp_a to cp_b must lie within 45° of
      cp_a's outbound heading.  A north-pointing CP (heading=0) will only
      reach targets in the arc 315°–045°.

    Rule 2 — Opposite polarity (±45°):
      cp_b's outbound heading must be within 45° of the reverse of cp_a's
      heading.  North CPs connect to south CPs; NE to SW; E to W; etc.
      Prevents two same-direction stubs from being wired together.
    """
    bearing_a_to_b = _bearing_deg(cp_a.center_lat, cp_a.center_lon,
                                   cp_b.center_lat, cp_b.center_lon)
    # Rule 1 — cp_b lies inside cp_a's forward cone
    if _angular_diff(bearing_a_to_b, cp_a.heading_deg) > 45:
        return False
    # Rule 2 — cp_b faces back (opposing polarity)
    opposite_a = (cp_a.heading_deg + 180) % 360
    if _angular_diff(cp_b.heading_deg, opposite_a) > 45:
        return False
    return True


def _max_connect_dist_m(candidates) -> float:
    """
    Maximum allowed connection distance: 1.5× the median nearest-neighbor
    distance between CPs on different structures.

    This limits auto-connect to roughly one structure-span so that a CP
    never leaps over an intermediate structure to reach a more distant one.
    Returns inf when fewer than 2 candidates (no constraint applied).
    """
    import statistics
    from mesh_mobility.engine.network import vincenty_m
    if len(candidates) < 2:
        return float("inf")
    nn_dists = []
    for cp_a in candidates:
        best = float("inf")
        for cp_b in candidates:
            if cp_b.structure_id == cp_a.structure_id:
                continue
            d = vincenty_m(cp_a.center_lat, cp_a.center_lon,
                           cp_b.center_lat, cp_b.center_lon)
            if d < best:
                best = d
        if best < float("inf"):
            nn_dists.append(best)
    if not nn_dists:
        return float("inf")
    return statistics.median(nn_dists) * 1.5


def _convex_hull_ids(points_xy: List[tuple]) -> set:
    """
    Gift-wrapping convex hull.  points_xy is a list of (x, y, id) tuples.
    Returns the set of ids that lie on the hull.
    For fewer than 3 points every point is on the hull.
    """
    if len(points_xy) < 3:
        return {p[2] for p in points_xy}

    # Find the leftmost (then lowest) starting point
    start = min(points_xy, key=lambda p: (p[0], p[1]))
    hull_ids: set = set()
    current = start

    for _ in range(len(points_xy) + 1):   # safety limit
        hull_ids.add(current[2])
        next_pt = points_xy[0] if points_xy[0] != current else points_xy[1]
        for candidate in points_xy:
            if candidate is current:
                continue
            cx, cy = current[0], current[1]
            nx, ny = next_pt[0], next_pt[1]
            px, py = candidate[0], candidate[1]
            cross = (nx - cx) * (py - cy) - (ny - cy) * (px - cx)
            dist_n = (nx - cx) ** 2 + (ny - cy) ** 2
            dist_p = (px - cx) ** 2 + (py - cy) ** 2
            if cross < 0 or (cross == 0 and dist_p > dist_n):
                next_pt = candidate
        current = next_pt
        if current is start:
            break

    return hull_ids


def _cp_is_outward(cp, centroid_lat: float, centroid_lon: float) -> bool:
    """
    True when the CP's outbound heading points away from the network centroid.
    Uses the dot product of the heading unit vector with the (cp→centroid) vector.
    A negative dot product means the CP faces away from the interior.
    """
    import math
    rad = math.radians(cp.heading_deg)
    hx = math.sin(rad)   # east component of heading
    hy = math.cos(rad)   # north component of heading

    # Vector from CP toward centroid (rough flat-earth, fine for local networks)
    dx = centroid_lon - cp.center_lon
    dy = centroid_lat - cp.center_lat

    mag = math.hypot(dx, dy)
    if mag < 1e-9:
        return False   # CP is at the centroid — treat as inner

    dx /= mag
    dy /= mag
    dot = hx * dx + hy * dy   # positive = heading toward centroid = inner-facing
    return dot < 0             # negative = heading away = outer-facing


def _best_effort_connect(
    net: Network,
    cps: dict,
    line_pairs: dict,
) -> List[Line]:
    """
    Connect unconnected CPs using greedy nearest-neighbor matching.

    A CP is skipped (left as an open boundary gate) when it is BOTH:
      • on the convex hull of all CP positions, AND
      • its outbound heading faces away from the network centroid.

    Each CP is matched at most once.  Uses connect_cps() so CP state and
    line_pairs are updated correctly.
    """
    from mesh_mobility.engine.network import vincenty_m
    from mesh_mobility.engine.structures import connect_cps as _connect_cps

    global _last_autoconnect_skipped
    _last_autoconnect_skipped = []

    if len(cps) < 2:
        return []

    # --- Centroid of all CP positions ---
    centroid_lat = sum(c.center_lat for c in cps.values()) / len(cps)
    centroid_lon = sum(c.center_lon for c in cps.values()) / len(cps)

    # --- Convex hull of CP positions ---
    pts_xy = [(c.center_lon, c.center_lat, c.cp_id) for c in cps.values()]
    hull_ids = _convex_hull_ids(pts_xy)

    # --- Identify open (unconnected) inner CPs ---
    def _is_outer(cp) -> bool:
        return cp.cp_id in hull_ids and _cp_is_outward(cp, centroid_lat, centroid_lon)

    # Only CPs whose tip nodes exist in the network are eligible.
    # This guards against stale CP state (e.g., after a node deletion).
    live_nodes = set(net.nodes.keys())

    candidates = []
    for cp in cps.values():
        if cp.connected_to is not None:
            continue   # already connected
        # Both tip nodes must be live network nodes
        if (cp.outbound_node.node_id not in live_nodes or
                cp.inbound_node.node_id not in live_nodes):
            continue   # stale CP — structure was deleted
        if _is_outer(cp):
            _last_autoconnect_skipped.append(cp.cp_id)
            continue
        candidates.append(cp)

    if len(candidates) < 2:
        return []

    # --- Distance cap: no connection longer than 1 structure-span ---
    max_dist = _max_connect_dist_m(candidates)

    # --- Greedy nearest-neighbor matching (each CP used at most once) ---
    used: set = set()
    matched_pairs = []

    # Sort for determinism
    candidates.sort(key=lambda c: c.cp_id)

    for cp_a in candidates:
        if cp_a.cp_id in used:
            continue
        best_dist = float("inf")
        best_b = None
        for cp_b in candidates:
            if cp_b.cp_id in used or cp_b.cp_id == cp_a.cp_id:
                continue
            # Never connect two CPs on the same structure
            if cp_b.structure_id == cp_a.structure_id:
                continue
            # Rule: direction cone + opposite polarity
            if not _cps_are_compatible(cp_a, cp_b):
                continue
            d = vincenty_m(cp_a.center_lat, cp_a.center_lon,
                           cp_b.center_lat, cp_b.center_lon)
            # Rule: no more than one structure-span away
            if d > max_dist:
                continue
            if d < best_dist:
                best_dist = d
                best_b = cp_b
        if best_b is not None:
            matched_pairs.append((cp_a, best_b))
            used.add(cp_a.cp_id)
            used.add(best_b.cp_id)

    # --- Create lines for each matched pair ---
    added_lines: List[Line] = []
    for cp_a, cp_b in matched_pairs:
        lines = _connect_cps(net, cp_a, cp_b, cps)
        if len(lines) == 2:
            line_pairs[lines[0].line_id] = lines[1].line_id
            line_pairs[lines[1].line_id] = lines[0].line_id
        added_lines.extend(lines)

    return added_lines


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


# ---------------------------------------------------------------------------
# External data overlays (proxy to government sources)
# ---------------------------------------------------------------------------

@api.get("/overlays/aadt")
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


@api.get("/overlays/accidents")
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


@api.post("/overlays/active")
def set_active_overlays():
    """Browser tells server which overlay files are loaded.
    Saved into the .jpd so opening the file restores the right city data."""
    data = request.json or {}
    _state["overlays"] = data
    return jsonify({"ok": True})


@api.get("/overlays/active")
def get_active_overlays():
    """Return current overlay config (from loaded .jpd or set by browser)."""
    return jsonify(_state.get("overlays") or {})


@api.post("/overlays/signal_missing")
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


@api.post("/overlays/fetch")
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


@api.get("/overlays/cities")
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


@api.post("/overlays/city/<city>")
def switch_overlay_city(city):
    """Switch all overlays to a specific city dataset.

    Copies aadt_{city}.geojson → aadt.geojson, etc.
    Records the city in _state["overlays"] so it saves with the .jpd.
    """
    import shutil
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


@api.get("/noelle/qa")
def get_qa():
    """Return Noelle's questions and any designer answers."""
    return jsonify(_state.get("qa") or _default_qa())


@api.post("/noelle/qa")
def save_qa():
    """Save designer's answers to Noelle's questions."""
    _state["qa"] = request.json or {}
    return jsonify({"ok": True})


def _default_qa():
    return {
        "questions": [
            {"id": "bike_trails", "q": "Where are the major bike/walking trails?", "a": ""},
            {"id": "event_venues", "q": "Any large event venues (stadiums, fairgrounds, convention centers)?", "a": ""},
            {"id": "campuses", "q": "University campuses or hospital complexes?", "a": ""},
            {"id": "transit_hubs", "q": "Transit hubs (bus stations, commuter rail, airports)?", "a": ""},
            {"id": "one_sided", "q": "Riverfronts, lakefronts, or other one-sided amenities worth connecting?", "a": ""},
            {"id": "commercial", "q": "Major shopping centers or commercial districts not on main roads?", "a": ""},
            {"id": "barriers", "q": "Linear barriers besides highways (rail lines, rivers, canals)?", "a": ""},
            {"id": "growth", "q": "Areas of new development or planned growth?", "a": ""},
        ],
    }


@api.get("/overlays/crash_density")
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


@api.get("/overlays/mobility")
def overlay_mobility():
    """Cell mobility data — not yet in CrashHarvester library."""
    return jsonify({"error": "Mobility data not yet harvested"}), 404


@api.get("/overlays/population_density")
def overlay_population_density():
    """Census population density from CrashHarvester library."""
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state"}), 404
    data = _md.get_census("population_density", state)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No population data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --census {state}"}), 404


@api.get("/overlays/property_values")
def overlay_property_values():
    """Census property values from CrashHarvester library."""
    state, _, _ = _detect_state()
    if not state:
        return jsonify({"error": "Cannot determine state"}), 404
    data = _md.get_census("property_values", state)
    if data and data.get("features"):
        return jsonify(data)
    return jsonify({"error": f"No property value data for {state.upper()}. Harvest: python3 -m crash_harvester harvest --census {state}"}), 404


@api.get("/overlays/jobs")
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
# AI recommendations (Allie)
# ---------------------------------------------------------------------------

@api.post("/ai/recommend")
def ai_recommend():
    """
    Send network parameters to Allie for network recommendations.
    Allie returns candidate networks + explanation text.

    For now: returns a structured placeholder.
    When Allie's wcapi endpoint is configured, this proxies to her.
    """
    data = request.json or {}
    # TODO: proxy to Allie's wcapi endpoint when configured
    # allie_url = os.environ.get("ALLIE_URL", "http://localhost:8080")
    # r = requests.post(f"{allie_url}/api/jpods/recommend", json=data)
    # return jsonify(r.json())

    # Placeholder response — describes what Allie will provide
    return jsonify({
        "summary": "Allie not yet connected",
        "explanation": (
            "To connect Allie:\n"
            "1. Set ALLIE_URL environment variable to Allie's wcapi address.\n"
            "2. Allie will analyse the map bounds, station count, and budget\n"
            "   to recommend an optimised network topology.\n"
            "3. As simulation results accumulate, recommendations improve\n"
            "   based on fleet-median transit times and demand patterns."
        ),
        "options": [],
        "network": None,
    })


# ---------------------------------------------------------------------------
# Network descriptor (Noelle's view)
# ---------------------------------------------------------------------------

@api.get("/network/describe")
def describe_network():
    """Generate a structured description of the current network for Noelle.

    Returns topology, spatial layout, quality metrics, and a natural-language
    summary that can be indexed into a vector store.
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    structs_raw = _state.get("structures", {})
    # Normalize: Structure dataclass objects → dicts
    structs = {}
    for sid, s in structs_raw.items():
        structs[sid] = s.to_dict() if hasattr(s, "to_dict") else s

    cps_list = _state.get("cps", {})
    if isinstance(cps_list, list):
        cps_map = {}
        for cp in cps_list:
            d = cp.to_dict() if hasattr(cp, "to_dict") else cp
            cps_map[d["cp_id"]] = d
    elif isinstance(cps_list, dict):
        cps_map = {}
        for k, cp in cps_list.items():
            cps_map[k] = cp.to_dict() if hasattr(cp, "to_dict") else cp
    else:
        cps_map = {}

    # Classify structures
    stations = {}
    circles = {}
    for sid, s in structs.items():
        if s.get("structure_type") == "station":
            stations[sid] = s
        else:
            circles[sid] = s

    # Spatial metrics
    all_lats = [s["center_lat"] for s in structs.values()]
    all_lons = [s["center_lon"] for s in structs.values()]
    if not all_lats:
        return jsonify({"error": "Empty network"}), 400

    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)
    lat_span = max(all_lats) - min(all_lats)
    lon_span = max(all_lons) - min(all_lons)
    # Approximate km
    ns_km = lat_span * 111.0
    ew_km = lon_span * 111.0 * math.cos(math.radians(center_lat))

    # Connection analysis
    open_cps = []
    connected_cps = []
    for cp in cps_map.values():
        cp_id = cp["cp_id"]
        if cp.get("connected_to"):
            connected_cps.append(cp_id)
        else:
            open_cps.append(cp_id)

    # Structure spacing — distances between all pairs (sample if large)
    import itertools
    pair_dists = []
    struct_items = list(structs.items())
    pairs = list(itertools.combinations(struct_items, 2))
    if len(pairs) > 5000:
        import random
        pairs = random.sample(pairs, 5000)
    for (sid_a, sa), (sid_b, sb) in pairs:
        dlat = sa["center_lat"] - sb["center_lat"]
        dlon = (sa["center_lon"] - sb["center_lon"]) * math.cos(math.radians(center_lat))
        d_km = math.sqrt(dlat**2 + dlon**2) * 111.0
        pair_dists.append(d_km)

    # Nearest-neighbor for each structure
    nn_dists = []
    for sid_a, sa in struct_items:
        best = float("inf")
        for sid_b, sb in struct_items:
            if sid_a == sid_b:
                continue
            dlat = sa["center_lat"] - sb["center_lat"]
            dlon = (sa["center_lon"] - sb["center_lon"]) * math.cos(math.radians(center_lat))
            d = math.sqrt(dlat**2 + dlon**2) * 111.0
            if d < best:
                best = d
        if best < float("inf"):
            nn_dists.append(best)

    # Orphan detection — structures with ALL CPs open
    orphan_sids = []
    for sid, s in structs.items():
        cp_ids = s.get("cp_ids", [])
        if cp_ids and all(cpid in [c for c in open_cps] for cpid in cp_ids):
            orphan_sids.append(sid)

    # Build neighbor map — which structures connect to which
    neighbors = {}  # sid → set of neighbor sids
    for cp in cps_map.values():
        conn = cp.get("connected_to")
        struct_id = cp.get("structure_id")
        if conn and struct_id:
            conn_obj = cps_map.get(conn)
            if conn_obj:
                conn_struct = conn_obj.get("structure_id")
                if conn_struct:
                    neighbors.setdefault(struct_id, set()).add(conn_struct)
                    neighbors.setdefault(conn_struct, set()).add(struct_id)

    # Degree distribution
    degrees = {sid: len(neighbors.get(sid, set())) for sid in structs}
    degree_counts = {}
    for d in degrees.values():
        degree_counts[d] = degree_counts.get(d, 0) + 1

    # Connected components (BFS)
    visited = set()
    components = []
    for sid in structs:
        if sid in visited:
            continue
        comp = set()
        queue = [sid]
        while queue:
            s = queue.pop()
            if s in visited:
                continue
            visited.add(s)
            comp.add(s)
            for nb in neighbors.get(s, set()):
                if nb not in visited:
                    queue.append(nb)
        components.append(comp)

    # Natural-language summary
    nn_avg = sum(nn_dists) / len(nn_dists) * 1000 if nn_dists else 0  # meters
    nn_min = min(nn_dists) * 1000 if nn_dists else 0
    nn_max = max(nn_dists) * 1000 if nn_dists else 0

    summary_lines = [
        f"Network '{_state.get('network', net).network_id}' centered at ({center_lat:.4f}, {center_lon:.4f}).",
        f"Coverage: {ns_km:.1f} km N-S × {ew_km:.1f} km E-W.",
        f"Structures: {len(stations)} stations, {len(circles)} traffic circles ({len(structs)} total).",
        f"CPs: {len(connected_cps)} connected, {len(open_cps)} open.",
        f"Orphaned structures (all CPs open): {len(orphan_sids)}.",
        f"Connected components: {len(components)} (largest: {max(len(c) for c in components)} structures).",
        f"Nearest-neighbor spacing: avg {nn_avg:.0f} m, min {nn_min:.0f} m, max {nn_max:.0f} m.",
        f"Degree distribution: {dict(sorted(degree_counts.items()))}.",
    ]
    if orphan_sids:
        summary_lines.append(f"Orphans: {', '.join(orphan_sids[:20])}{'...' if len(orphan_sids) > 20 else ''}.")

    # Structure list with relative positions
    struct_descs = []
    for sid, s in structs.items():
        stype = s.get("structure_type", "unknown")
        lat, lon = s["center_lat"], s["center_lon"]
        deg = degrees.get(sid, 0)
        nbs = sorted(neighbors.get(sid, set()))
        struct_descs.append({
            "id": sid,
            "type": stype,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "heading": s.get("heading_deg", 0),
            "connections": deg,
            "neighbors": nbs,
            "open_cps": [cpid for cpid in s.get("cp_ids", []) if cpid in open_cps],
        })

    return jsonify({
        "network_id": getattr(_state.get("network", net), "network_id", "untitled"),
        "summary": "\n".join(summary_lines),
        "spatial": {
            "center": [round(center_lat, 6), round(center_lon, 6)],
            "extent_km": [round(ns_km, 2), round(ew_km, 2)],
            "nn_spacing_m": {
                "avg": round(nn_avg, 0),
                "min": round(nn_min, 0),
                "max": round(nn_max, 0),
            },
        },
        "topology": {
            "stations": len(stations),
            "circles": len(circles),
            "connected_cps": len(connected_cps),
            "open_cps": len(open_cps),
            "orphans": orphan_sids,
            "components": len(components),
            "largest_component": max(len(c) for c in components),
            "degree_distribution": dict(sorted(degree_counts.items())),
        },
        "structures": struct_descs,
    })


# ---------------------------------------------------------------------------
# Noelle Draft — data-driven station proposal
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    """Fast haversine distance in metres."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


import re as _re_road


def _classify_road(name):
    """Classify road type from naming conventions across US DOTs."""
    n = name.strip().upper()
    if _re_road.match(r"^I[\s\-]?\d", n):
        return "Interstate"
    if _re_road.match(r"^US[\s\-]?\d", n):
        return "Highway"
    if _re_road.match(
        r"^(SH|SR|MN|CA|TX|FL|OH|OK|SC|NY|IL|PA|GA|NC|VA|WA|OR|CO|AZ|NV|NJ|MA|MD|CT|WI|IN|MO|TN|KY|AL|LA|MS|AR|KS|NE|IA|UT|NM|WV|ID|HI|ME|NH|RI|DE|MT|ND|SD|WY|VT|AK|DC|IH|FM|TL)[\s\-]?\d", n):
        return "Highway"
    if n == "LOCAL ROAD":
        return "Local/Arterial"
    if _re_road.match(r"^(CSAH|MSAS|CR|CO\s*RD|COUNTY)", n):
        return "Local/Arterial"
    return "Local/Arterial"


def _noelle_analyze(aadt_path, acc_path):
    """Analyse AADT + accident overlays and return a structured proposal.

    Returns dict with: stations list, crash_rates table, summary text,
    highway_boundaries, and mesh_analysis.
    """
    with open(aadt_path) as f:
        aadt_geo = json.load(f)
    with open(acc_path) as f:
        acc_geo = json.load(f)

    # ── All AADT points ──
    all_pts = []
    for feat in aadt_geo.get("features", []):
        p = feat["properties"]
        lon, lat = feat["geometry"]["coordinates"]
        all_pts.append({"road": p.get("road", "Unknown"),
                        "lat": lat, "lon": lon, "aadt": p.get("aadt", 0)})

    # ── All accident points ──
    acc_pts = []
    for feat in acc_geo.get("features", []):
        lon, lat = feat["geometry"]["coordinates"]
        ped = feat["properties"].get("pedestrian", False)
        acc_pts.append({"lat": lat, "lon": lon, "pedestrian": ped})

    # ── Classify road type ──
    from collections import defaultdict

    roads_by_name = defaultdict(list)
    for pt in all_pts:
        roads_by_name[pt["road"]].append(pt)

    crash_rates = []
    for road, segs in roads_by_name.items():
        if road == "Unknown":
            continue
        avg_aadt = sum(s["aadt"] for s in segs) / len(segs)
        crashes = set()
        ped_crashes = set()
        for i, a in enumerate(acc_pts):
            for s in segs:
                if _haversine_m(a["lat"], a["lon"], s["lat"], s["lon"]) < 400:
                    crashes.add(i)
                    if a["pedestrian"]:
                        ped_crashes.add(i)
                    break
        if not crashes:
            continue
        rtype = _classify_road(road)
        rate = len(crashes) / (avg_aadt / 10_000) if avg_aadt > 0 else 0
        crash_rates.append({
            "road": road, "type": rtype, "avg_aadt": int(avg_aadt),
            "crashes": len(crashes), "ped_crashes": len(ped_crashes),
            "rate_per_10k": round(rate, 2),
        })
    crash_rates.sort(key=lambda x: -x["rate_per_10k"])

    # ── Crash rate summary by type ──
    type_totals = defaultdict(lambda: {"crashes": 0, "ped": 0,
                                       "aadt_sum": 0, "count": 0})
    for r in crash_rates:
        t = type_totals[r["type"]]
        t["crashes"] += r["crashes"]
        t["ped"] += r["ped_crashes"]
        t["aadt_sum"] += r["avg_aadt"]
        t["count"] += 1
    crash_rate_summary = []
    for rtype in ["Local/Arterial", "Highway", "Interstate", "State Route"]:
        t = type_totals.get(rtype)
        if not t or t["count"] == 0:
            continue
        avg = t["aadt_sum"] / t["count"]
        rate = t["crashes"] / (avg / 10_000) if avg > 0 else 0
        crash_rate_summary.append({
            "type": rtype, "crashes": t["crashes"],
            "ped_crashes": t["ped"],
            "avg_aadt": int(avg),
            "rate_per_10k": round(rate, 1),
        })

    # ── Detect arterial grid from local-road AADT clusters ──
    # Find N-S corridors: group local/arterial points by longitude bands
    local_pts = [p for p in all_pts
                 if _classify_road(p["road"]) == "Local/Arterial"
                 and p["aadt"] >= 5000]
    # Bounding box of all data
    all_lats = [p["lat"] for p in all_pts]
    all_lons = [p["lon"] for p in all_pts]
    if not all_lats:
        return {"error": "No AADT data found"}
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)

    # Cluster local-road points into N-S bands (by longitude, 0.012° ≈ 1 km)
    ns_bands = defaultdict(list)
    for p in local_pts:
        band = round(p["lon"] / 0.012) * 0.012
        ns_bands[band].append(p)
    # Keep bands with 3+ points (real corridors)
    ns_corridors = sorted([lon for lon, pts in ns_bands.items()
                           if len(pts) >= 3])

    # Cluster into E-W bands (by latitude, 0.012° ≈ 1.3 km)
    ew_bands = defaultdict(list)
    for p in local_pts:
        band = round(p["lat"] / 0.012) * 0.012
        ew_bands[band].append(p)
    ew_corridors = sorted([lat for lat, pts in ew_bands.items()
                           if len(pts) >= 3], reverse=True)

    # ── Helper: accident and AADT lookup ──
    def accidents_near(lat, lon, radius=600):
        return sum(1 for a in acc_pts
                   if _haversine_m(lat, lon, a["lat"], a["lon"]) < radius)

    def local_aadt_near(lat, lon, radius=500):
        best = 0
        for p in local_pts:
            if _haversine_m(lat, lon, p["lat"], p["lon"]) < radius:
                best = max(best, p["aadt"])
        return best

    # ── Place stations at grid intersections with signal ──
    stations = []
    for ew_lat in ew_corridors:
        for ns_lon in ns_corridors:
            crashes = accidents_near(ew_lat, ns_lon)
            aadt = local_aadt_near(ew_lat, ns_lon)
            if crashes >= 1 or aadt >= 5000:
                stations.append({
                    "name": f"Grid ({ew_lat:.3f}, {ns_lon:.3f})",
                    "lat": round(ew_lat, 6), "lon": round(ns_lon, 6),
                    "crashes": crashes, "aadt": aadt,
                    "source": "grid",
                })

    # ── Add off-grid accident hotspots ──
    acc_grid = defaultdict(lambda: {"count": 0, "lat_sum": 0, "lon_sum": 0,
                                    "ped": 0})
    for a in acc_pts:
        key = (round(a["lat"] / 0.005) * 0.005,
               round(a["lon"] / 0.005) * 0.005)
        acc_grid[key]["count"] += 1
        acc_grid[key]["lat_sum"] += a["lat"]
        acc_grid[key]["lon_sum"] += a["lon"]
        if a["pedestrian"]:
            acc_grid[key]["ped"] += 1

    for key, v in sorted(acc_grid.items(), key=lambda x: -x[1]["count"]):
        if v["count"] >= 3:
            lat = v["lat_sum"] / v["count"]
            lon = v["lon_sum"] / v["count"]
            if not any(_haversine_m(lat, lon, s["lat"], s["lon"]) < 400
                       for s in stations):
                aadt = local_aadt_near(lat, lon)
                stations.append({
                    "name": f"Accident cluster ({v['count']} crashes"
                            f", {v['ped']} ped)",
                    "lat": round(lat, 6), "lon": round(lon, 6),
                    "crashes": v["count"], "aadt": aadt,
                    "source": "accident_cluster",
                })

    stations.sort(key=lambda x: (-x["crashes"], -x["aadt"]))

    # ── Highway boundaries ──
    hwy_boundaries = []
    hwy_road_names = sorted(r for r in roads_by_name
                            if _classify_road(r) in ("Interstate", "Highway"))
    for road_name in hwy_road_names:
        pts = roads_by_name.get(road_name, [])
        if not pts:
            continue
        lats = [p["lat"] for p in pts]
        lons = [p["lon"] for p in pts]
        max_aadt = max(p["aadt"] for p in pts)
        hwy_boundaries.append({
            "road": road_name,
            "lat_range": [round(min(lats), 4), round(max(lats), 4)],
            "lon_range": [round(min(lons), 4), round(max(lons), 4)],
            "max_aadt": max_aadt,
        })

    # ── Top intersections ──
    top_3 = stations[:3]

    # ── Build summary ──
    crash_stations = sum(1 for s in stations if s["crashes"] >= 1)
    traffic_stations = sum(1 for s in stations if s["crashes"] == 0)
    grid_stations = sum(1 for s in stations if s["source"] == "grid")
    cluster_stations = sum(1 for s in stations
                           if s["source"] == "accident_cluster")
    total_acc = len(acc_pts)
    total_ped = sum(1 for a in acc_pts if a["pedestrian"])

    summary_lines = [
        f"{len(stations)} stations, zero circles. "
        f"All on the arterial grid, none on highways.",
        "",
        "The proposal follows two rules:",
        f"- Crash signal: {crash_stations} stations where people are "
        f"dying within 600m",
        f"- Traffic signal: {traffic_stations} stations on grid "
        f"intersections with 5K+ AADT on local roads",
        "",
    ]
    if top_3:
        top_parts = []
        for s in top_3:
            aadt_str = (f"{s['aadt']/1000:.1f}K AADT"
                        if s["aadt"] >= 1000 else f"{s['aadt']} AADT")
            top_parts.append(f"{s['name']} ({s['crashes']} crashes"
                             f", {aadt_str})")
        summary_lines.append("Hottest intersections: "
                             + "; ".join(top_parts))
        summary_lines.append("")

    if hwy_boundaries:
        hwy_names = ", ".join(h["road"] for h in hwy_boundaries[:6])
        summary_lines.append(f"Highways as boundaries only — {hwy_names} "
                             f"frame the neighborhoods but get no stations.")
        summary_lines.append("")

    if crash_rate_summary:
        local = next((c for c in crash_rate_summary
                      if c["type"] == "Local/Arterial"), None)
        interstate = next((c for c in crash_rate_summary
                           if c["type"] == "Interstate"), None)
        if local and interstate and interstate["rate_per_10k"] > 0:
            ratio = local["rate_per_10k"] / interstate["rate_per_10k"]
            summary_lines.append(
                f"Local arterials are {ratio:.0f}× more dangerous per "
                f"unit of traffic than interstates.")
            summary_lines.append(
                f"They carry {local['ped_crashes']} of {total_ped} "
                f"pedestrian fatalities — people are walking on "
                f"these roads and dying.")

    return {
        "stations": stations,
        "crash_rate_summary": crash_rate_summary,
        "crash_rates": crash_rates[:20],
        "highway_boundaries": hwy_boundaries,
        "grid": {
            "ns_corridors": len(ns_corridors),
            "ew_corridors": len(ew_corridors),
            "grid_stations": grid_stations,
            "cluster_stations": cluster_stations,
        },
        "data_summary": {
            "aadt_features": len(aadt_geo.get("features", [])),
            "accident_features": total_acc,
            "pedestrian_accidents": total_ped,
        },
        "summary": "\n".join(summary_lines),
    }


@api.post("/noelle/draft")
def noelle_draft():
    """Noelle analyses AADT + accident overlays and proposes stations.

    Stations only — no circles.  Circles are the designer's job.
    Highways are boundaries, not corridors.
    Primary signal: crash rate on local arterials.
    Secondary signal: AADT >= 5K on local roads.

    Query params:
      ?place=true  — also place the stations on the current network
    """
    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path):
        return jsonify({"error": "No AADT overlay — load aadt.geojson "
                        "into mesh_mobility/overlays/"}), 404
    if not os.path.exists(acc_path):
        return jsonify({"error": "No accident overlay — load "
                        "accidents.geojson into mesh_mobility/overlays/"}), 404

    result = _noelle_analyze(aadt_path, acc_path)
    if "error" in result:
        return jsonify(result), 400

    # Optionally place stations on the map
    place = request.args.get("place", "false").lower() == "true"
    placed_ids = []
    if place:
        net = _net()
        if net is None:
            _state["network"] = Network(network_id="noelle_draft")
            _state["network_path"] = None
            _state["sim_frames"] = []
            _state["sim_result"] = None
            clear_edit_state()
            net = _state["network"]

        for s in result["stations"]:
            try:
                struct, cps = build_station(
                    net, s["lat"], s["lon"],
                    heading_deg=0,
                    structure_id=next_sid("s"))
                _state["structures"][struct.structure_id] = struct
                _state["cps"].update(cps)
                placed_ids.append(struct.structure_id)
            except Exception:
                pass  # skip overlapping stations silently

        result["placed"] = len(placed_ids)
        result["placed_ids"] = placed_ids

    return jsonify(result)


@api.post("/noelle/wild_guess")
def noelle_wild_guess():
    """Wild Guess: add traffic circles between draft stations and auto-connect everything.

    Call after Draft + Apply. Places circles at midpoints between nearby station pairs,
    then runs auto-connect. Produces a complete connected network from Noelle's stations.
    """
    push_undo()
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    structures = _state.get("structures", {})
    cps = _state.get("cps", {})

    # Collect all station positions
    stations = []
    for sid, struct in structures.items():
        if struct.structure_type == "station":
            stations.append({
                "id": sid,
                "lat": struct.center_lat,
                "lon": struct.center_lon,
            })

    if len(stations) < 2:
        return jsonify({"error": "Need at least 2 stations — run Draft + Apply first"}), 400

    # Find station pairs that need circles between them
    # Use distance threshold: stations within ~2.5 miles get a circle at their midpoint
    max_dist_m = 2.5 * 1609.34
    from mesh_mobility.engine.network import vincenty_m

    pairs = []
    for i in range(len(stations)):
        for j in range(i + 1, len(stations)):
            d = vincenty_m(stations[i]["lat"], stations[i]["lon"],
                          stations[j]["lat"], stations[j]["lon"])
            if d < max_dist_m:
                pairs.append((i, j, d))

    # Sort by distance — shortest first
    pairs.sort(key=lambda x: x[2])

    # Place circles at midpoints, skip if too close to an existing structure
    placed_circles = []
    min_circle_spacing_m = 400  # don't place circles within 400m of each other

    for i, j, d in pairs:
        mid_lat = (stations[i]["lat"] + stations[j]["lat"]) / 2
        mid_lon = (stations[i]["lon"] + stations[j]["lon"]) / 2

        # Check if too close to any existing structure or already-placed circle
        too_close = False
        for sid, struct in structures.items():
            if vincenty_m(mid_lat, mid_lon, struct.center_lat, struct.center_lon) < min_circle_spacing_m:
                too_close = True
                break
        if too_close:
            continue

        # Determine heading: perpendicular to the line between the two stations
        dlat = stations[j]["lat"] - stations[i]["lat"]
        dlon = stations[j]["lon"] - stations[i]["lon"]
        bearing = math.degrees(math.atan2(dlon, dlat)) % 360
        # Use 0° or 45° circle depending on bearing
        circle_heading = 45 if (22.5 < bearing % 90 < 67.5) else 0

        try:
            cid = next_sid("c")
            struct, new_cps = build_traffic_circle(
                net, mid_lat, mid_lon,
                heading_deg=circle_heading,
                structure_id=cid)
            structures[cid] = struct
            cps.update(new_cps)
            placed_circles.append(cid)
        except Exception:
            pass

    # Auto-connect everything
    added_lines = _best_effort_connect(net, cps, _state["line_pairs"])
    for l in added_lines:
        _state["line_roles"][l.line_id] = "connector"
    net.build()

    noelle_log("wild_guess", {
        "stations": len(stations),
        "circles_added": len(placed_circles),
        "lines_added": len(added_lines),
    })

    return jsonify({
        "stations": len(stations),
        "circles_added": len(placed_circles),
        "circle_ids": placed_circles,
        "lines_added": len(added_lines),
        "total_structures": len(structures),
    })


@api.get("/network/report")
def network_report():
    """Printable HTML network summary — stations, miles, economics."""
    net = _net()
    if net is None:
        return "<h1>No network loaded</h1>", 400

    structures = _state.get("structures", {})
    stations = [(sid, s) for sid, s in structures.items() if s.structure_type == "station"]
    circles = [(sid, s) for sid, s in structures.items() if s.structure_type == "circle"]
    total_miles = round(net.total_length_m() / 1609.34, 1)
    build_cost = round(total_miles * 20, 1)
    network_id = net.network_id or "Untitled"

    # City name from overlay state
    city_label = ""
    overlays = _state.get("overlays", {})
    city_key = overlays.get("city", "")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>JPods Network Summary — {network_id}</title>
<style>
  @media print {{ body {{ font-size: 11pt; }} }}
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 800px;
         margin: 40px auto; padding: 0 20px; color: #222; }}
  h1 {{ color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 8px; }}
  h2 {{ color: #2e7d32; margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ padding: 6px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  .metric {{ font-size: 28px; font-weight: 700; color: #1a5276; }}
  .metric-label {{ font-size: 12px; color: #888; text-transform: uppercase; }}
  .metrics {{ display: flex; gap: 32px; margin: 20px 0; }}
  .metric-box {{ text-align: center; }}
  .footer {{ margin-top: 40px; font-size: 11px; color: #888;
             border-top: 1px solid #ddd; padding-top: 12px; }}
  .oss {{ background: #f0f8f0; padding: 8px 12px; border-radius: 4px;
          border-left: 3px solid #2e7d32; font-size: 12px; margin: 16px 0; }}
</style>
</head><body>
<h1>JPods Network Summary — {network_id}</h1>

<div class="metrics">
  <div class="metric-box"><div class="metric">{len(stations)}</div><div class="metric-label">Stations</div></div>
  <div class="metric-box"><div class="metric">{len(circles)}</div><div class="metric-label">Circles</div></div>
  <div class="metric-box"><div class="metric">{total_miles}</div><div class="metric-label">Guideway Miles</div></div>
  <div class="metric-box"><div class="metric">${build_cost:,.0f}M</div><div class="metric-label">Build Cost ($20M/mi)</div></div>
</div>

<div class="oss">Open Source — all designs created with this tool are open source and publicly shared.
Solar-powered · 13x more efficient than cars · 50x vs buses · $0.03/passenger-mile</div>

<h2>Stations ({len(stations)})</h2>
<table>
<tr><th>ID</th><th>Latitude</th><th>Longitude</th></tr>"""

    for sid, s in sorted(stations, key=lambda x: x[0]):
        html += f"\n<tr><td>{sid}</td><td>{s.center_lat:.5f}</td><td>{s.center_lon:.5f}</td></tr>"

    html += f"""
</table>

<h2>Traffic Circles ({len(circles)})</h2>
<table>
<tr><th>ID</th><th>Latitude</th><th>Longitude</th></tr>"""

    for cid, c in sorted(circles, key=lambda x: x[0]):
        html += f"\n<tr><td>{cid}</td><td>{c.center_lat:.5f}</td><td>{c.center_lon:.5f}</td></tr>"

    html += f"""
</table>

<h2>Bill of Materials (BOM)</h2>
<table>
<tr><th>Item</th><th>Quantity</th><th>Unit Cost</th><th>Total</th></tr>
<tr><td>Guideway (dual beam, solar panels, columns)</td><td>{total_miles} mi</td><td>$20M/mi</td><td>${build_cost:,.0f}M</td></tr>
<tr><td>Stations (2-slot standard)</td><td>{len(stations)}</td><td>~$2M ea</td><td>~${len(stations)*2:,}M</td></tr>
<tr><td>Traffic circles (junction structures)</td><td>{len(circles)}</td><td>~$0.5M ea</td><td>~${round(len(circles)*0.5):,}M</td></tr>
<tr><td>Vehicles (pods, 4 per station initial fleet)</td><td>{len(stations)*4}</td><td>~$50K ea</td><td>~${round(len(stations)*4*0.05):,}M</td></tr>
<tr style="font-weight:600;border-top:2px solid #333">
  <td>Total estimated</td><td></td><td></td>
  <td>${build_cost + len(stations)*2 + round(len(circles)*0.5) + round(len(stations)*4*0.05):,.0f}M</td></tr>
</table>
<p style="font-size:11px;color:#666">Note: Costs are rough planning estimates. Guideway dominates.
Actual costs vary by terrain, permitting, and local labor markets.</p>

<h2>Guideway Capacity</h2>
<p>Capacity is determined by <strong>speed × headway</strong> on the guideway, but the real constraint
is <strong>station slots</strong> — how many pods can load/unload simultaneously.
Stations are parallel processors: more slots = more throughput, without changing the guideway.</p>

<table>
<tr><th>Speed</th><th colspan="2">0.25 sec headway</th><th colspan="2">0.50 sec headway</th></tr>
<tr><th>(mph)</th><th>Pods/hr/dir</th><th>Pax/hr/dir</th><th>Pods/hr/dir</th><th>Pax/hr/dir</th></tr>
<tr><td>25 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
<tr><td>35 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
<tr><td>45 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
<tr><td>60 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
</table>
<p style="font-size:11px;color:#666">Pods/hr = 3600 ÷ headway. At 0.25s: 14,400 pods/hr per direction.
Each pod carries 1-4 passengers. Speed affects trip time, not throughput.</p>

<h2>Station Throughput (the real constraint)</h2>
<p>With 30-second load/unload cycles, each slot processes 120 pods/hour.
Capacity scales by adding slots — the station is a parallel processor.</p>

<table>
<tr><th>Station Type</th><th>Slots</th><th>Pods/hr</th><th>Pax/hr (1.5 avg)</th><th>Use Case</th></tr>
<tr><td>Neighborhood</td><td>2</td><td>240</td><td>360</td><td>Residential area</td></tr>
<tr><td>Standard</td><td>4</td><td>480</td><td>720</td><td>Commercial district</td></tr>
<tr><td>High capacity</td><td>8</td><td>960</td><td>1,440</td><td>Office park, mall</td></tr>
<tr><td>Transit hub</td><td>18</td><td>2,160</td><td>3,240</td><td>Train station, airport</td></tr>
<tr><td>Major terminal</td><td>36</td><td>4,320</td><td>6,480</td><td>Stadium, convention center</td></tr>
</table>
<p style="font-size:11px;color:#666">Add stations where demand concentrates.
Two 18-slot stations 200m apart = 6,480 pax/hr without changing the guideway.
<a href="https://library.jpods.com/capacity/">Detailed capacity analysis →</a></p>

<h2>Network Summary — This Design</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Guideway miles</td><td>{total_miles} mi</td></tr>
<tr><td>Stations × 4 slots (default)</td><td>{len(stations)} × 480 pods/hr = {len(stations)*480:,} pods/hr network capacity</td></tr>
<tr><td>Build cost</td><td>${build_cost + len(stations)*2 + round(len(circles)*0.5):,.0f}M</td></tr>
<tr><td>JPods efficiency</td><td>13× more efficient than cars · 50× vs buses</td></tr>
<tr><td>Operating cost</td><td>$0.03/passenger-mile</td></tr>
<tr><td>Energy</td><td>Solar-powered — no fuel dependency</td></tr>
</table>

<p>Run the <a href="/citytool">City Assessment Tool</a> for full savings analysis including
vehicle ownership reduction, fuel savings, road maintenance, CO₂ reduction, and fiscal impact.</p>

<h2>The Cost of Free Parking</h2>
<p>The US has an estimated 800 million parking spaces for 280 million cars — roughly 3 spaces
per car. In many cities, the total cost of providing free parking (land, construction,
maintenance, and foregone tax revenue on tax-exempt land) rivals spending on public education.</p>
<p>JPods networks eliminate parked-car demand, converting low-tax parking lots to high-tax
productive land — walkable commercial, residential, and recreational space.</p>
<p style="font-size:11px;color:#666">Source: Donald Shoup,
<a href="https://www.routledge.com/The-High-Cost-of-Free-Parking/Shoup/p/book/9781032408552"><i>The High Cost of Free Parking</i></a>
(Routledge, updated edition 2011). Shoup documents that off-street parking requirements
in US zoning codes have made parking the single largest land use in most cities.</p>

<h2>Proven Model — Privately Funded Transit</h2>
<p>In 1916, every US city over 10,000 people had one or more
<a href="https://en.wikipedia.org/wiki/List_of_streetcar_systems_in_the_United_States">privately funded streetcar networks</a>
— Mobility As A Service before the term existed. The Federal-Aid Highway Act of 1916
initiated a mercantile monopoly that destroyed them. JPods restores that proven model:</p>
<table>
<tr><th></th><th>1916 Streetcars</th><th>JPods</th></tr>
<tr><td>Funding</td><td>Private</td><td>Private</td></tr>
<tr><td>Service</td><td>Fixed route, scheduled</td><td>On-demand, point-to-point</td></tr>
<tr><td>Grade</td><td>Street-level (traffic conflicts)</td><td>Grade-separated (no conflicts)</td></tr>
<tr><td>Batch size</td><td>40-passenger vehicle</td><td>1-4 passenger pod</td></tr>
<tr><td>Energy</td><td>Grid electric</td><td>Solar-powered</td></tr>
<tr><td>Coverage</td><td>Every US city &gt;10,000</td><td>Any community, any country</td></tr>
</table>
<p style="font-size:11px;color:#666">The streetcar model wasn't replaced by a better technology.
It was destroyed by federal policy — government coercion extended into transportation commerce.
JPods restores what worked, improved by a century of engineering.</p>

<h2>Regulatory — 5x5 Standard</h2>
<p>JPods networks operate under the <a href="https://www.5x5FreeMarket.com">5×5 Standard</a>:
5 times more efficient than cars, powered by sunlight within 5 years.
This performance standard replaces prescriptive regulations that have blocked
transportation innovation for over five decades.</p>

<h2>Studies &amp; Evidence</h2>

<div style="background:#fff8f0;padding:12px 16px;border-radius:4px;border-left:3px solid #e67e22;margin:12px 0;font-style:italic;font-size:12px;line-height:1.6">
"Government institutional failures blocked urban transportation innovation for
four to six decades… In retrospect, the new systems efforts have served not to
stimulate interest in new technology but to discourage already reluctant local
transit operators from considering it."
<div style="font-style:normal;font-weight:600;margin-top:6px;color:#666">
— U.S. Congressional Study, 1975</div>
</div>

<table>
<tr><th>Study</th><th>Key Finding</th></tr>
<tr><td><a href="https://library.jpods.com/congressionalstudy/">U.S. Congressional Study (1975)</a></td>
    <td>PRT provides higher service than mass transit. Government institutional failures blocked innovation for decades. Lists all JPods benefits: less congestion, less parking, reduced petroleum, mobility for disadvantaged.</td></tr>
<tr><td><a href="https://library.jpods.com/nj2007/">NJ Legislature Study (2007)</a></td>
    <td>State-level assessment of PRT feasibility and benefits for New Jersey communities.</td></tr>
<tr><td><a href="https://library.jpods.com/JPods/004Studies/LeanManufacturingTransit.pdf">Lean Manufacturing &amp; Transit (Boeing)</a></td>
    <td>Maps lean production theory to PRT. Mass transit = mass production waste. PRT = lean: continuous flow, pull-based, batch size of 1. Lean techniques show 991% productivity gains.</td></tr>
<tr><td><a href="https://library.jpods.com/capacity/">Capacity Analysis</a></td>
    <td>Station throughput scales by adding parallel load/unload slots. 18-slot station: 2,160 pax/hr. Guideway: 14,400 pods/hr at 0.25s headway.</td></tr>
</table>

<div class="footer">
  Generated by MeshMobility · JPods Network Planner<br>
  <a href="https://vimeo.com/1207891831?fl=tl&fe=ec">Video Demo</a> ·
  <a href="/citytool">City Assessment Tool</a> ·
  <a href="https://www.5x5FreeMarket.com">5×5 Standard</a> ·
  <a href="https://library.jpods.com/capacity/">Capacity</a> ·
  Open source at jpods.com
</div>
</body></html>"""

    return html


@api.get("/noelle/report")
def noelle_report():
    """Printable HTML report of Noelle's draft analysis."""
    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path) or not os.path.exists(acc_path):
        return "<h1>No overlay data loaded</h1>", 404

    r = _noelle_analyze(aadt_path, acc_path)
    if "error" in r:
        return f"<h1>Error: {r['error']}</h1>", 400

    # Build printable HTML
    html = ["""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Noelle Network Draft — Analysis Report</title>
<style>
  @media print { body { font-size: 11pt; } }
  body { font-family: -apple-system, 'Segoe UI', sans-serif;
         max-width: 900px; margin: 2em auto; padding: 0 1em;
         color: #222; line-height: 1.5; }
  h1 { border-bottom: 2px solid #333; padding-bottom: 0.3em; }
  h2 { color: #444; margin-top: 1.5em; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; }
  th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
  th { background: #f5f5f5; font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .hot { background: #fee; }
  .summary { background: #f8f9fa; padding: 1em 1.5em; border-radius: 6px;
             border-left: 4px solid #2563eb; margin: 1em 0; }
  .insight { background: #fef3c7; padding: 0.8em 1.2em; border-radius: 6px;
             border-left: 4px solid #d97706; margin: 1em 0; }
  .print-btn { background: #2563eb; color: #fff; border: none;
               padding: 8px 20px; border-radius: 4px; cursor: pointer;
               font-size: 14px; }
  .print-btn:hover { background: #1d4ed8; }
  @media print { .no-print { display: none; } }
  .star { color: #dc2626; }
  .dot  { color: #f59e0b; }
</style>
</head><body>
<div class="no-print" style="text-align:right; margin-bottom:1em">
  <button class="print-btn" onclick="window.print()">&#128424; Print Report</button>
</div>
"""]

    html.append(f"<h1>Noelle Network Draft</h1>")
    html.append(f"<p><em>Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                f" — {r['data_summary']['aadt_features']} AADT stations, "
                f"{r['data_summary']['accident_features']} fatal crashes</em></p>")

    # Summary box
    html.append(f'<div class="summary"><pre style="white-space:pre-wrap; '
                f'font-family:inherit; margin:0">{r["summary"]}</pre></div>')

    # Crash rates by road type
    html.append("<h2>Crash Rate by Road Type</h2>")
    html.append("<table><tr><th>Road Type</th><th>Crashes</th>"
                "<th>Pedestrian</th><th>Avg AADT</th>"
                "<th>Rate / 10K AADT</th></tr>")
    for cr in r["crash_rate_summary"]:
        cls = ' class="hot"' if cr["rate_per_10k"] > 20 else ""
        html.append(f'<tr{cls}><td>{cr["type"]}</td>'
                    f'<td class="num">{cr["crashes"]}</td>'
                    f'<td class="num">{cr["ped_crashes"]}</td>'
                    f'<td class="num">{cr["avg_aadt"]:,}</td>'
                    f'<td class="num"><strong>{cr["rate_per_10k"]}</strong></td>'
                    f'</tr>')
    html.append("</table>")

    # Insight box
    local = next((c for c in r["crash_rate_summary"]
                  if c["type"] == "Local/Arterial"), None)
    interstate = next((c for c in r["crash_rate_summary"]
                       if c["type"] == "Interstate"), None)
    if local and interstate and interstate["rate_per_10k"] > 0:
        ratio = local["rate_per_10k"] / interstate["rate_per_10k"]
        html.append(f'<div class="insight">'
                    f'<strong>Key insight:</strong> Local arterials are '
                    f'{ratio:.0f}&times; more dangerous per unit of traffic '
                    f'than interstates. Highways are boundaries, not '
                    f'corridors &mdash; the interior grid is where people '
                    f'die and where JPods stations belong.</div>')

    # Highway boundaries
    if r["highway_boundaries"]:
        html.append("<h2>Highway Boundaries (no stations placed)</h2>")
        html.append("<table><tr><th>Highway</th><th>Max AADT</th>"
                    "<th>Role</th></tr>")
        for h in r["highway_boundaries"]:
            html.append(f'<tr><td>{h["road"]}</td>'
                        f'<td class="num">{h["max_aadt"]:,}</td>'
                        f'<td>Neighborhood boundary</td></tr>')
        html.append("</table>")

    # Proposed stations
    html.append(f"<h2>Proposed Stations ({len(r['stations'])})</h2>")
    html.append("<table><tr><th></th><th>Location</th>"
                "<th>Crashes (600m)</th><th>Local AADT</th>"
                "<th>Source</th></tr>")
    for i, s in enumerate(r["stations"], 1):
        if s["crashes"] >= 3:
            icon = '<span class="star">&#9733;</span>'
        elif s["crashes"] >= 1:
            icon = '<span class="dot">&#8226;</span>'
        else:
            icon = ""
        cls = ' class="hot"' if s["crashes"] >= 3 else ""
        html.append(f'<tr{cls}><td>{i}</td><td>{s["name"]}</td>'
                    f'<td class="num">{icon} {s["crashes"]}</td>'
                    f'<td class="num">{s["aadt"]:,}</td>'
                    f'<td>{s["source"]}</td></tr>')
    html.append("</table>")

    # Grid info
    g = r["grid"]
    html.append(f"<h2>Grid Analysis</h2>")
    html.append(f"<p>Detected {g['ns_corridors']} N-S corridors and "
                f"{g['ew_corridors']} E-W corridors from AADT data. "
                f"{g['grid_stations']} stations on grid intersections, "
                f"{g['cluster_stations']} from accident clusters.</p>")

    # Top crash corridors
    html.append("<h2>Top Crash Corridors (per 10K AADT)</h2>")
    html.append("<table><tr><th>Road</th><th>Type</th><th>Avg AADT</th>"
                "<th>Crashes</th><th>Ped</th>"
                "<th>Rate / 10K</th></tr>")
    for cr in r["crash_rates"][:15]:
        cls = ' class="hot"' if cr["rate_per_10k"] > 5 else ""
        html.append(f'<tr{cls}><td>{cr["road"]}</td>'
                    f'<td>{cr["type"]}</td>'
                    f'<td class="num">{cr["avg_aadt"]:,}</td>'
                    f'<td class="num">{cr["crashes"]}</td>'
                    f'<td class="num">{cr["ped_crashes"]}</td>'
                    f'<td class="num"><strong>'
                    f'{cr["rate_per_10k"]}</strong></td></tr>')
    html.append("</table>")

    html.append("<hr><p style='color:#888; font-size:0.9em'>"
                "Noelle — JPods Network Design Agent. "
                "Stations only; circles are the designer's job. "
                "Data: state DOT AADT + NHTSA FARS.</p>")
    html.append("</body></html>")

    return "\n".join(html), 200, {"Content-Type": "text/html"}


# ---------------------------------------------------------------------------
# Noelle Review — compare designer network to Noelle's draft (training signal)
# ---------------------------------------------------------------------------

@api.post("/noelle/refine")
def noelle_refine():
    """Noelle prunes and adds stations on the existing network.

    Prune: remove stations with no crash or AADT signal within 600m.
    Add: place stations where data shows signal but no structure exists.
    Circles are never touched — they are the designer's work.

    Returns what was pruned and added so the designer can review.
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path) or not os.path.exists(acc_path):
        return jsonify({"error": "No overlay data — load AADT + accident "
                        "overlays first"}), 404

    # Also load crash density if available
    density_path = os.path.join(_rt_dir, "overlays", "crash_density.geojson")
    density_pts = []
    if os.path.exists(density_path):
        with open(density_path) as f:
            dg = json.load(f)
        for feat in dg.get("features", []):
            lon, lat = feat["geometry"]["coordinates"]
            density_pts.append({"lat": lat, "lon": lon,
                                "crashes": feat["properties"].get("crashes", 0)})

    # Load AADT local arterial points
    with open(aadt_path) as f:
        aadt_geo = json.load(f)
    local_pts = []
    for feat in aadt_geo.get("features", []):
        p = feat["properties"]
        road = p.get("road", "Unknown")
        if _classify_road(road) == "Local/Arterial" and p.get("aadt", 0) >= 5000:
            lon, lat = feat["geometry"]["coordinates"]
            local_pts.append({"lat": lat, "lon": lon, "aadt": p["aadt"]})

    # Load accident points
    with open(acc_path) as f:
        acc_geo = json.load(f)
    acc_pts = []
    for feat in acc_geo.get("features", []):
        lon, lat = feat["geometry"]["coordinates"]
        acc_pts.append({"lat": lat, "lon": lon})

    def has_signal(lat, lon, radius=600):
        """Check if a location has crash or AADT signal."""
        for a in acc_pts:
            if _haversine_m(lat, lon, a["lat"], a["lon"]) < radius:
                return True
        for p in local_pts:
            if _haversine_m(lat, lon, p["lat"], p["lon"]) < radius:
                return True
        for d in density_pts:
            if (d["crashes"] >= 20
                    and _haversine_m(lat, lon, d["lat"], d["lon"]) < radius):
                return True
        return False

    # === PRUNE: remove stations with no signal ===
    pruned = []
    structs_to_remove = []
    for sid, s in list(_state["structures"].items()):
        d = s.to_dict() if hasattr(s, "to_dict") else s
        stype = d.get("structure_type", "unknown")
        # Never prune circles — designer's work
        if stype != "station":
            continue
        lat = d.get("center_lat")
        lon = d.get("center_lon")
        if lat is None or lon is None:
            continue
        if not has_signal(lat, lon):
            structs_to_remove.append(sid)
            pruned.append({"id": sid, "lat": lat, "lon": lon})

    # Delete pruned structures
    for sid in structs_to_remove:
        struct = _state["structures"].get(sid)
        if not struct:
            continue
        # Clear partner CPs
        for cp_id in struct.cp_ids:
            cp = _state["cps"].get(cp_id)
            if cp and cp.connected_to:
                partner = _state["cps"].get(cp.connected_to)
                if partner:
                    partner.connected_to = None
        # Remove lines
        struct_nodes = set(struct.node_ids)
        dead_lines = [lid for lid, line in net.lines.items()
                      if line.start_node.node_id in struct_nodes
                      or line.end_node.node_id in struct_nodes]
        for lid in dead_lines:
            net.lines.pop(lid, None)
            _state["line_pairs"].pop(lid, None)
            _state["line_roles"].pop(lid, None)
            _state["waypoints"].pop(lid, None)
        for nid in struct.node_ids:
            net.nodes.pop(nid, None)
            net.stations.pop(nid, None)
        for cp_id in struct.cp_ids:
            _state["cps"].pop(cp_id, None)
        del _state["structures"][sid]

    # === ADD: place stations where signal exists but no structure ===
    # Get Noelle's proposal
    proposal = _noelle_analyze(aadt_path, acc_path)
    noelle_stations = proposal.get("stations", []) if "error" not in proposal else []

    # Filter to proposals not near any existing structure
    existing_pts = []
    for sid, s in _state["structures"].items():
        d = s.to_dict() if hasattr(s, "to_dict") else s
        lat = d.get("center_lat")
        lon = d.get("center_lon")
        if lat and lon:
            existing_pts.append({"lat": lat, "lon": lon})

    added = []
    for ns in noelle_stations:
        near_existing = any(
            _haversine_m(ns["lat"], ns["lon"], ep["lat"], ep["lon"]) < 400
            for ep in existing_pts)
        if near_existing:
            continue
        try:
            struct, cps = build_station(
                net, ns["lat"], ns["lon"],
                heading_deg=0, structure_id=next_sid("s"))
            _state["structures"][struct.structure_id] = struct
            _state["cps"].update(cps)
            existing_pts.append({"lat": ns["lat"], "lon": ns["lon"]})
            added.append({"id": struct.structure_id,
                          "lat": ns["lat"], "lon": ns["lon"],
                          "crashes": ns.get("crashes", 0),
                          "aadt": ns.get("aadt", 0)})
        except Exception:
            pass

    if structs_to_remove:
        net.build()

    return jsonify({
        "pruned": len(pruned),
        "pruned_list": pruned,
        "added": len(added),
        "added_list": added[:20],
        "summary": f"Pruned {len(pruned)} stations (no data signal). "
                   f"Added {len(added)} stations (data signal, no structure).",
    })


@api.post("/noelle/review")
def noelle_review():
    """Generate Noelle's draft and embed it in the current network state.

    Triggered by shift-click Open. Noelle's draft is stored in the .jpd
    as `noelle_draft` — a list of proposed stations. The browser can
    extract it and load in a second tab for visual comparison.
    """
    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path) or not os.path.exists(acc_path):
        return jsonify({"error": "No overlay data — cannot review"}), 404

    proposal = _noelle_analyze(aadt_path, acc_path)
    if "error" in proposal:
        return jsonify(proposal), 400

    noelle_stations = proposal.get("stations", [])

    # Build Noelle's draft as a minimal .jpd dict (structures only, no lines)
    noelle_net = Network(network_id="noelle_draft")
    noelle_structs_list = []
    noelle_cps_list = []
    n_counter = 1
    for s in noelle_stations:
        sid = f"s{n_counter}"
        n_counter += 1
        try:
            struct, cps = build_station(
                noelle_net, s["lat"], s["lon"],
                heading_deg=0, structure_id=sid)
            noelle_structs_list.append(struct.to_dict())
            noelle_cps_list.extend(cp.to_dict() for cp in cps.values())
        except Exception:
            pass

    # Store in _state so it saves with the .jpd
    _state["noelle_draft"] = {
        "stations": noelle_stations,
        "structures": noelle_structs_list,
        "cps": noelle_cps_list,
        "summary": proposal.get("summary", ""),
        "crash_rate_summary": proposal.get("crash_rate_summary", []),
    }

    return jsonify({
        "noelle_stations": len(noelle_structs_list),
        "summary": proposal.get("summary", ""),
    })


@api.get("/noelle/draft_jpd")
def noelle_draft_jpd():
    """Return the embedded Noelle draft as a loadable .jpd for the second tab."""
    draft = _state.get("noelle_draft")
    if not draft:
        return jsonify({"error": "No Noelle draft — shift-click Open first"}), 404

    d = {
        "format": "jpd",
        "version": 2,
        "network_id": "noelle_draft",
        "saved_at": int(time.time() * 1000),
        "settings": _state.get("settings", {}),
        "switches": [],
        "stations": [],
        "lines": [],
        "structures": draft.get("structures", []),
        "cps": draft.get("cps", []),
    }
    # Include overlay data so the second tab has the same overlays
    overlays = _state.get("overlays")
    if overlays:
        d["overlays"] = overlays
    overlay_data = {}
    overlay_dir = os.path.join(_rt_dir, "overlays")
    if overlays and overlays.get("city"):
        city = overlays["city"]
        for prefix in ("aadt", "accidents", "crash_density", "population_density", "property_values", "jobs"):
            fpath = os.path.join(overlay_dir, f"{prefix}_{city}.geojson")
            if os.path.exists(fpath):
                with open(fpath) as f:
                    overlay_data[prefix] = json.load(f)
    if overlay_data:
        d["overlay_data"] = overlay_data

    content = json.dumps(d, indent=2, ensure_ascii=False).encode("utf-8")
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition":
                 'attachment; filename="noelle_draft.jpd"'},
    )
