"""
route_time.gui.api
==================
Flask REST API backing the browser GUI.

Endpoints:
  GET  /api/network          → current network as GeoJSON
  POST /api/network/load     → load a .jpd or map.json file
  POST /api/network/save     → save current network as .jpd
  POST /api/network/node     → add a node (station or switch)
  POST /api/network/circle   → add a traffic circle (8-node structure)
  DELETE /api/network/node/<id>    → remove a node + its lines
  POST /api/network/line     → add a directed line between two nodes
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
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request, current_app, Response

# Import engine and IO
import sys
_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from route_time.engine import Network, Node, Line, Station, Simulator
from route_time.engine.physics import PhysicsModel
from route_time.engine.structures import (
    build_traffic_circle, build_station, connect_cps, disconnect_cp,
    rotate_station, rotate_traffic_circle,
    ConnectionPoint, Structure,
)
from route_time.io import load_jpd, load_podpresenter, load_sketchup_map
from route_time.io.jpd_writer import save_jpd, serialise_jpd

api = Blueprint("api", __name__, url_prefix="/api")

# ---------------------------------------------------------------------------
# Allie capture helpers — fire-and-forget, never raise
# ---------------------------------------------------------------------------
import subprocess as _subprocess
import pathlib as _pathlib

_ALLIE_CAPTURE = _pathlib.Path.home() / "Allie" / "scripts" / "allie-capture.py"


def _allie_capture_simulation(result, net):
    """Log simulation completion to Allie's events.jsonl."""
    if not _ALLIE_CAPTURE.exists():
        return
    try:
        summary = result.summary if hasattr(result, "summary") else {}
        stations = summary.get("station_count", len(getattr(net, "stations", {})))
        lines = summary.get("line_count", len(getattr(net, "lines", {})))
        network_id = getattr(result, "network_id", "") or ""
        data = json.dumps({
            "network_id": network_id,
            "stations": stations,
            "lines": lines,
        })
        _subprocess.Popen(
            ["python3", str(_ALLIE_CAPTURE),
             "--source", "route-time",
             "--event",  "simulation_complete",
             "--message", f"{stations} stations, {lines} lines",
             "--data", data],
            stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL
        )
    except Exception:
        pass


def _allie_capture_error(event: str, message: str):
    """Log an error event to Allie's events.jsonl."""
    if not _ALLIE_CAPTURE.exists():
        return
    try:
        _subprocess.Popen(
            ["python3", str(_ALLIE_CAPTURE),
             "--source", "route-time",
             "--event",  event,
             "--message", message[:200]],
            stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL
        )
    except Exception:
        pass


def _write_fault(fault_text: str, context: str = "", detected_by: str = "Claude") -> None:
    """Write a FAULT file to ~/Allie/process/inbox/.

    Called at the tool boundary when a simulation or network load fails.
    Allie reads these nightly:
      - Recurring unresolved faults → ouch-list candidates
      - FAULT + TFTS pairs → Understanding candidates
    """
    from datetime import datetime, timezone
    ts_str  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    inbox = _pathlib.Path.home() / "Allie" / "process" / "inbox"
    if not inbox.parent.parent.exists():
        return   # Allie drive not mounted — skip silently
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"{ts_file}-fault.md"
    path.write_text(
        f"# FAULT — {ts_str}\n\n"
        f"system:      RT\n"
        f"detected_by: {detected_by}\n"
        f"fault:       {fault_text}\n"
        f"context:     {context}\n"
        f"resolved_at: \n"
    )
    log.info("[fault] → %s", path.name)


# ---------------------------------------------------------------------------
# Settings helper (defined before _state so it can be called inline)
# ---------------------------------------------------------------------------

def _default_settings() -> dict:
    settings_path = os.path.join(_rt_dir, "settings.json")
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            return json.load(f)
    return {
        "accInG": 1.0, "deccInG": 1.0, "maxVelocityInKMPH": 60,
        "disembarkingTimeInSec": 20, "embarkingTimeInSec": 20,
        "ticketingTimeInSec": 30, "stationEntryTimeInSec": 40,
        "stationExitTimeInSec": 40, "timeResolutionPerSec": 9,
        "podsPerStation": 8, "graceDistance": 0,
    }


# ---------------------------------------------------------------------------
# Server state (single-user desktop tool)
# ---------------------------------------------------------------------------

_state: Dict = {
    "network": None,
    "network_path": None,
    "settings": _default_settings(),
    "sim_frames": [],
    "sim_result": None,
    "sim_active": False,        # True while a simulation thread is running
    "sim_instance": None,       # active Simulator object (for progress reads)
    "sim_error": None,          # error string if sim thread failed
    "structures":   {},   # structure_id → Structure
    "cps":          {},   # cp_id → ConnectionPoint
    "waypoints":    {},   # line_id → [{"lat": float, "lon": float}, ...]
    "line_pairs":   {},   # line_id → partner_line_id  (guideways always paired)
    "line_roles":   {},   # line_id → role string, e.g. "siding"
    "_next_s":      1,    # counter for s1, s2, s3 ... station IDs
    "_next_c":      1,    # counter for c1, c2, c3 ... circle IDs
    "overlays":     None, # overlay file references saved with .jpd
}


def _clear_edit_state():
    """Reset editing state when a new network is loaded."""
    _state["structures"] = {}
    _state["cps"]        = {}
    _state["waypoints"]  = {}
    _state["line_pairs"] = {}
    _state["line_roles"] = {}
    _state["_next_s"]    = 1
    _state["_next_c"]    = 1


def _next_sid(stype: str) -> str:
    """Return next sequential human-readable structure ID: s1,s2,… or c1,c2,…"""
    key = "_next_s" if stype == "s" else "_next_c"
    n = _state[key]
    _state[key] += 1
    return f"{stype}{n}"


def _sync_counters():
    """After loading a file, advance counters past any existing s#/c# IDs."""
    import re as _re
    max_s = max_c = 0
    for sid in _state["structures"]:
        m = _re.match(r'^s(\d+)$', sid)
        if m:
            max_s = max(max_s, int(m.group(1)))
        m = _re.match(r'^c(\d+)$', sid)
        if m:
            max_c = max(max_c, int(m.group(1)))
    if max_s:
        _state["_next_s"] = max_s + 1
    if max_c:
        _state["_next_c"] = max_c + 1


def _reconstruct_structures_from_net(net) -> tuple:
    """
    Derive Structure and ConnectionPoint objects from a legacy .jpd network
    (one saved before <StructureMeta> was added) using node naming conventions.

    Stations:  all nodes with IDs starting "ST_"  → {sid}.guideway_near_out_tip etc.
    Circles:   all nodes with IDs starting "TC_"  → {sid}.A{i}_out / A{i}_in

    Returns (structures_dict, cps_dict).
    """
    import math as _math

    import re as _re
    _is_st = lambda p: p.startswith('ST_') or bool(_re.match(r'^s\d+$', p))
    _is_tc = lambda p: p.startswith('TC_') or bool(_re.match(r'^c\d+$', p))

    # Group nodes by their structure prefix (text before the first '.')
    prefix_nodes: dict = {}
    for nid, node in net.nodes.items():
        if '.' in nid:
            prefix = nid.split('.')[0]
            if _is_st(prefix) or _is_tc(prefix):
                prefix_nodes.setdefault(prefix, {})[nid] = node

    structures: dict = {}
    cps: dict = {}

    for sid, nodes in prefix_nodes.items():

        # Internal line_ids = lines where BOTH endpoints belong to this structure
        line_ids = [
            lid for lid, ln in net.lines.items()
            if ln.start_node.node_id in nodes and ln.end_node.node_id in nodes
        ]

        if _is_st(sid):
            # ── Station ────────────────────────────────────────────────────
            nb_n_tip = nodes.get(f"{sid}.guideway_near_out_tip")
            sb_n_tip = nodes.get(f"{sid}.guideway_far_in_tip")
            nb_s_tip = nodes.get(f"{sid}.guideway_near_in_tip")
            sb_s_tip = nodes.get(f"{sid}.guideway_far_out_tip")
            if not all([nb_n_tip, sb_n_tip, nb_s_tip, sb_s_tip]):
                continue   # incomplete — skip

            # Compute heading from guideway_near_in_end → guideway_near_out_end
            nb_n = nodes.get(f"{sid}.guideway_near_out_end")
            nb_s = nodes.get(f"{sid}.guideway_near_in_end")
            heading_deg = 0.0
            if nb_n and nb_s:
                dlat = nb_n.lat - nb_s.lat
                dlon = nb_n.lon - nb_s.lon
                heading_deg = _math.degrees(
                    _math.atan2(dlon * _math.cos(_math.radians(nb_n.lat)), dlat)
                ) % 360

            nb_h = heading_deg
            sb_h = (nb_h + 180) % 360

            cp_n = ConnectionPoint(
                cp_id=f"{sid}.CP_near_far", structure_id=sid, heading_deg=nb_h,
                inbound_node=sb_n_tip, outbound_node=nb_n_tip,
                center_lat=(nb_n_tip.lat + sb_n_tip.lat) / 2,
                center_lon=(nb_n_tip.lon + sb_n_tip.lon) / 2,
            )
            cp_s = ConnectionPoint(
                cp_id=f"{sid}.CP_far_near", structure_id=sid, heading_deg=sb_h,
                inbound_node=nb_s_tip, outbound_node=sb_s_tip,
                center_lat=(nb_s_tip.lat + sb_s_tip.lat) / 2,
                center_lon=(nb_s_tip.lon + sb_s_tip.lon) / 2,
            )

            platform = nodes.get(f"{sid}.PLATFORM")
            clat = platform.lat if platform else sum(n.lat for n in nodes.values()) / len(nodes)
            clon = platform.lon if platform else sum(n.lon for n in nodes.values()) / len(nodes)

            structures[sid] = Structure(
                structure_id=sid, structure_type="station",
                cp_ids=[cp_n.cp_id, cp_s.cp_id],
                node_ids=list(nodes.keys()), line_ids=line_ids,
                center_lat=clat, center_lon=clon, heading_deg=heading_deg,
            )
            cps[cp_n.cp_id] = cp_n
            cps[cp_s.cp_id] = cp_s

        elif _is_tc(sid):
            # ── Traffic circle ──────────────────────────────────────────────
            cp_ids = []
            tc_cps = {}
            arm_headings = []

            for arm_idx in range(4):
                out_tip = nodes.get(f"{sid}.A{arm_idx}_out")
                in_tip  = nodes.get(f"{sid}.A{arm_idx}_in")
                div     = nodes.get(f"{sid}.A{arm_idx}_div")
                if out_tip is None or in_tip is None:
                    continue

                # Heading = direction from div toward out_tip
                hdg = 0.0
                if div:
                    dlat = out_tip.lat - div.lat
                    dlon = out_tip.lon - div.lon
                    hdg  = _math.degrees(
                        _math.atan2(dlon * _math.cos(_math.radians(div.lat)), dlat)
                    ) % 360

                cp = ConnectionPoint(
                    cp_id=f"{sid}.CP{arm_idx}", structure_id=sid, heading_deg=hdg,
                    inbound_node=in_tip, outbound_node=out_tip,
                    center_lat=(out_tip.lat + in_tip.lat) / 2,
                    center_lon=(out_tip.lon + in_tip.lon) / 2,
                )
                tc_cps[cp.cp_id] = cp
                cp_ids.append(cp.cp_id)
                arm_headings.append(hdg)

            if not cp_ids:
                continue

            all_lats = [n.lat for n in nodes.values()]
            all_lons = [n.lon for n in nodes.values()]
            structures[sid] = Structure(
                structure_id=sid, structure_type="traffic_circle",
                cp_ids=cp_ids, node_ids=list(nodes.keys()), line_ids=line_ids,
                center_lat=sum(all_lats) / len(all_lats),
                center_lon=sum(all_lons) / len(all_lons),
                arm_headings=arm_headings,
            )
            cps.update(tc_cps)

    # Resolve connected_to: a line from cp_a.outbound → cp_b.inbound
    # that crosses structure boundaries marks both CPs as connected.
    out_node_to_cp = {cp.outbound_node.node_id: cp for cp in cps.values()}
    in_node_to_cp  = {cp.inbound_node.node_id:  cp for cp in cps.values()}
    for ln in net.lines.values():
        cp_a = out_node_to_cp.get(ln.start_node.node_id)
        cp_b = in_node_to_cp.get(ln.end_node.node_id)
        if cp_a and cp_b and cp_a.structure_id != cp_b.structure_id:
            cp_a.connected_to = cp_b.cp_id
            cp_b.connected_to = cp_a.cp_id

    return structures, cps


def _restore_structures(structures_data: list, cps_data: list, net) -> None:
    """Rebuild _state["structures"] and _state["cps"] from saved metadata."""
    for s in structures_data:
        struct = Structure(
            structure_id=s["structure_id"],
            structure_type=s["structure_type"],
            cp_ids=s["cp_ids"],
            node_ids=s["node_ids"],
            line_ids=s["line_ids"],
            center_lat=s.get("center_lat", 0.0),
            center_lon=s.get("center_lon", 0.0),
            heading_deg=s.get("heading_deg", 0.0),
            arm_headings=s.get("arm_headings", []),
        )
        _state["structures"][struct.structure_id] = struct
    for c in cps_data:
        in_node  = net.nodes.get(c["inbound_node"])
        out_node = net.nodes.get(c["outbound_node"])
        if in_node is None or out_node is None:
            continue   # dangling reference — skip
        cp = ConnectionPoint(
            cp_id=c["cp_id"],
            structure_id=c["structure_id"],
            heading_deg=c["heading_deg"],
            inbound_node=in_node,
            outbound_node=out_node,
            center_lat=c["center_lat"],
            center_lon=c["center_lon"],
            connected_to=c.get("connected_to"),
        )
        _state["cps"][cp.cp_id] = cp


def _net() -> Optional[Network]:
    return _state["network"]


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


# (traffic circle and station builders are in route_time.engine.structures)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
            net, structs_data, cps_data, file_settings = load_jpd(path)
        else:
            with open(path) as f:
                raw = json.load(f)
            if "lines" in raw:
                net = load_podpresenter(path)
            else:
                net = load_sketchup_map(path)
    except Exception as e:
        _write_fault(f"Network load failed: {e}", f"path={path}")
        return jsonify({"error": str(e)}), 500

    _state["network"] = net
    _state["network_path"] = path
    _state["sim_frames"] = []
    _state["sim_result"] = None
    _clear_edit_state()
    if structs_data or cps_data:
        _restore_structures(structs_data, cps_data, net)
    else:
        s, c = _reconstruct_structures_from_net(net)
        _state["structures"].update(s)
        _state["cps"].update(c)
    if file_settings:
        _state["settings"].update(file_settings)
    _sync_counters()
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
        # Inject noelle_draft if present
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
    _clear_edit_state()
    return jsonify({"network_id": nid})


@api.post("/network/reload")
def reload_network():
    """Re-read the current network file without restarting the server.

    Equivalent to the SketchUp Reload Plugin button for Route-Time.
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
        _write_fault(f"Network reload failed: {e}", f"path={path}")
        return jsonify({"error": str(e)}), 500

    # Clear old simulation results — they are stale after a file change
    _state["network"]      = net
    _state["sim_frames"]   = []
    _state["sim_result"]   = None
    _clear_edit_state()
    if structs_data or cps_data:
        _restore_structures(structs_data, cps_data, net)
    else:
        s, c = _reconstruct_structures_from_net(net)
        _state["structures"].update(s)
        _state["cps"].update(c)
    if file_settings:
        _state["settings"].update(file_settings)
    _sync_counters()

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
            f"code:    route_time/gui/api.py\n"
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
    nid   = data.get("id") or _new_id(ntype)

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
    cid  = data.get("id") or _next_sid("c")
    arms = data.get("arm_headings")   # optional [h0, h1, h2, h3]

    overlap_err = _check_overlap(lat, lon, "traffic_circle")
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
    sid         = data.get("id") or _next_sid("s")

    overlap_err = _check_overlap(lat, lon, "station")
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


@api.post("/network/line")
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
    lid = data.get("id") or _new_id("L")
    from route_time.engine.network import vincenty_m
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
    from route_time.engine.network import vincenty_m
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

    overlap_err = _check_overlap(new_lat, new_lon, struct.structure_type,
                                 exclude_sid=sid)
    if overlap_err:
        return jsonify({"error": overlap_err}), 400

    struct.center_lat = new_lat
    struct.center_lon = new_lon

    if struct.structure_type == "station":
        rotate_station(net, struct, _state["cps"], struct.heading_deg)
    elif struct.structure_type == "traffic_circle":
        rotate_traffic_circle(net, struct, _state["cps"], struct.arm_headings)

    return jsonify({
        "moved": sid,
        "center_lat": struct.center_lat,
        "center_lon": struct.center_lon,
    })


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


def _cp_by_heading(cp_dict: dict, target_heading: float) -> Optional[ConnectionPoint]:
    """Return the CP whose heading_deg is closest to target_heading."""
    best, best_diff = None, float("inf")
    for cp in cp_dict.values():
        diff = abs((cp.heading_deg - target_heading + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
            best = cp
    return best


@api.post("/network/grid")
def network_grid():
    """
    Generate a rectangular grid network:
      - Traffic circles at every intersection
      - One station at the midpoint of every block (between adjacent circles)
      - CPs connected: circle ↔ station ↔ circle along each axis

    Body (all distances in miles):
      center_lat, center_lon  — geographic centre of the grid
      spacing_ns              — N-S block size  (default 1.0)
      spacing_ew              — E-W block size  (default 1.0)
      extent_ns               — total N-S span  (default 4.0)
      extent_ew               — total E-W span  (default 4.0)
      replace                 — if true (default), clear existing network first
    """
    data = request.json or {}
    center_lat = float(data.get("center_lat", 37.31))
    center_lon = float(data.get("center_lon", -121.87))
    spacing_ns = float(data.get("spacing_ns", 1.0))
    spacing_ew = float(data.get("spacing_ew", 1.0))
    extent_ns  = float(data.get("extent_ns",  4.0))
    extent_ew  = float(data.get("extent_ew",  4.0))
    replace    = bool(data.get("replace", True))

    if replace:
        net = Network(network_id="grid")
        _state["network"] = net
        _clear_edit_state()
    else:
        net = _net()
        if net is None:
            net = Network(network_id="grid")
            _state["network"] = net

    # Convert miles → metres → degrees
    dlat_per_m = 1.0 / 111_320.0
    dlon_per_m = 1.0 / (111_320.0 * math.cos(math.radians(center_lat)))

    ns_m = spacing_ns * _MI_TO_M
    ew_m = spacing_ew * _MI_TO_M

    dlat = ns_m * dlat_per_m   # degrees lat per row step (going south)
    dlon = ew_m * dlon_per_m   # degrees lon per col step (going east)

    n_rows = max(2, round(extent_ns / spacing_ns) + 1)
    n_cols = max(2, round(extent_ew / spacing_ew) + 1)

    # Top-left corner (northwest)
    start_lat = center_lat + dlat * (n_rows - 1) / 2.0
    start_lon = center_lon - dlon * (n_cols - 1) / 2.0

    # ── 1. Build traffic circles at every intersection ──────────────────────
    grid: List[List] = []          # grid[r][c] = (struct, cp_dict)
    for r in range(n_rows):
        row = []
        for c in range(n_cols):
            lat = start_lat - r * dlat
            lon = start_lon + c * dlon
            struct, cp_dict = build_traffic_circle(
                net, lat, lon,
                structure_id=_next_sid("c"),
                arm_headings=[0.0, 90.0, 180.0, 270.0],
            )
            _state["structures"][struct.structure_id] = struct
            _state["cps"].update(cp_dict)
            row.append((struct, cp_dict))
        grid.append(row)

    n_stations = 0

    # ── 2. N-S blocks: station between (r,c) and (r+1,c) ───────────────────
    for r in range(n_rows - 1):
        for c in range(n_cols):
            lat = start_lat - (r + 0.5) * dlat
            lon = start_lon + c * dlon
            st, st_cps = build_station(net, lat, lon, heading_deg=0.0,
                                       structure_id=_next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            # North circle south arm ↔ station CP_near_far (heading=0°)
            _, cp_dict_north = grid[r][c]
            tc_south = _cp_by_heading(cp_dict_north, 180.0)
            st_north = st_cps.get(f"{st.structure_id}.CP_near_far")
            if tc_south and st_north and tc_south.connected_to is None and st_north.connected_to is None:
                connect_cps(net, tc_south, st_north, _state["cps"])

            # Station CP_far_near (heading=180°) ↔ south circle north arm
            _, cp_dict_south = grid[r + 1][c]
            tc_north = _cp_by_heading(cp_dict_south, 0.0)
            st_south = st_cps.get(f"{st.structure_id}.CP_far_near")
            if tc_north and st_south and tc_north.connected_to is None and st_south.connected_to is None:
                connect_cps(net, st_south, tc_north, _state["cps"])

    # ── 3. E-W blocks: station between (r,c) and (r,c+1) ───────────────────
    for r in range(n_rows):
        for c in range(n_cols - 1):
            lat = start_lat - r * dlat
            lon = start_lon + (c + 0.5) * dlon
            st, st_cps = build_station(net, lat, lon, heading_deg=90.0,
                                       structure_id=_next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            # West circle east arm ↔ station CP_far_near (west end, heading=270°)
            _, cp_dict_west = grid[r][c]
            tc_east = _cp_by_heading(cp_dict_west, 90.0)
            st_west = st_cps.get(f"{st.structure_id}.CP_far_near")
            if tc_east and st_west and tc_east.connected_to is None and st_west.connected_to is None:
                connect_cps(net, tc_east, st_west, _state["cps"])

            # Station CP_near_far (east end, heading=90°) ↔ east circle west arm
            _, cp_dict_east = grid[r][c + 1]
            tc_west = _cp_by_heading(cp_dict_east, 270.0)
            st_east = st_cps.get(f"{st.structure_id}.CP_near_far")
            if tc_west and st_east and tc_west.connected_to is None and st_east.connected_to is None:
                connect_cps(net, st_east, tc_west, _state["cps"])

    net.build()
    return jsonify({
        "circles":   n_rows * n_cols,
        "stations":  n_stations,
        "rows":      n_rows,
        "cols":      n_cols,
        "spacing_ns_mi": spacing_ns,
        "spacing_ew_mi": spacing_ew,
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
    from route_time.engine.demand import LoadArray

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

    _state["sim_active"]   = True
    _state["sim_instance"] = sim
    _state["sim_result"]   = None
    _state["sim_error"]    = None

    # Tool boundary — simulation start captured.
    # This is the "Reload Plugin" moment for Route-Time: the developer changed
    # something and is now testing it. If a fix was being tested, write a TF
    # or TFTS after the run (the browser will prompt).
    network_name = getattr(net, "network_id", "") or ""
    _allie_capture_simulation.__func__ if hasattr(_allie_capture_simulation, "__func__") else None
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
                _write_fault(
                    "0 passengers served with non-zero demand",
                    f"network={network_name}, stations={len(station_ids)}, slots={slots}; "
                    f"check station connectivity and routing",
                )

            _save_sweep_json(result)
            _allie_capture_simulation(result, net)
        except Exception as exc:
            import traceback
            _state["sim_error"] = str(exc)
            log.error("Simulation thread error: %s", traceback.format_exc())
            _write_fault(f"Simulation exception: {exc}", f"network={network_name}")
            _allie_capture_error("simulation_error", str(exc))
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
    from route_time.engine.network import vincenty_m
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
    from route_time.engine.network import vincenty_m
    from route_time.engine.structures import connect_cps as _connect_cps

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

    structs_data, cps_data, file_settings, file_overlays = [], [], {}, None
    try:
        if suffix == ".jpd":
            net, structs_data, cps_data, file_settings, file_overlays = load_jpd(tmp_path)
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
    _clear_edit_state()
    if structs_data or cps_data:
        _restore_structures(structs_data, cps_data, net)
    else:
        s, c = _reconstruct_structures_from_net(net)
        _state["structures"].update(s)
        _state["cps"].update(c)
    if file_settings:
        _state["settings"].update(file_settings)
    # Overlay data is restored by the reader (writes to active overlay files)
    if file_overlays:
        _state["overlays"] = file_overlays
    _sync_counters()
    return jsonify({**_network_to_geojson(net), "settings": _state["settings"],
                    "overlays": _state.get("overlays")})


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
    from route_time.engine.network import vincenty_m
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
    """
    Proxy FHWA HPMS Annual Average Daily Traffic data.
    Requires FHWA_API_KEY env var, or falls back to a local GeoJSON file.
    See route_time/overlays/README.md for setup.
    """
    local_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    if os.path.exists(local_path):
        with open(local_path) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "AADT data not configured"}), 404


@api.get("/overlays/accidents")
def overlay_accidents():
    """
    Proxy NHTSA / state crash data.
    Falls back to local GeoJSON file: route_time/overlays/accidents.geojson
    """
    local_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if os.path.exists(local_path):
        with open(local_path) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Accident data not configured"}), 404


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
    for prefix in ("aadt", "accidents", "crash_density"):
        src = os.path.join(overlay_dir, f"{prefix}_{city}.geojson")
        dst = os.path.join(overlay_dir, f"{prefix}.geojson")
        if os.path.exists(src):
            shutil.copy2(src, dst)
            switched.append(prefix)

    _state["overlays"] = {"city": city, "files": switched}
    return jsonify({"city": city, "switched": switched})


@api.get("/overlays/crash_density")
def overlay_crash_density():
    """All-severity crash density grid — pre-aggregated from full crash data."""
    local_path = os.path.join(_rt_dir, "overlays", "crash_density.geojson")
    if os.path.exists(local_path):
        with open(local_path) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Crash density data not configured"}), 404


@api.get("/overlays/mobility")
def overlay_mobility():
    """
    Cell mobility travel pattern data.
    Falls back to local GeoJSON file: route_time/overlays/mobility.geojson
    """
    local_path = os.path.join(_rt_dir, "overlays", "mobility.geojson")
    if os.path.exists(local_path):
        with open(local_path) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Mobility data not configured"}), 404


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
# Helpers
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6].upper()}"


# Approximate footprint radius in metres for each structure type.
# Station: half-length (35 m) + stub extension (10 m) = 45 m
# Circle:  ring radius (7.5 m) + stub length (15 m)   = 22.5 m
_FOOTPRINT_M = {
    "station":        45.0,
    "traffic_circle": 22.5,
}
_FOOTPRINT_DEFAULT = 45.0   # conservative fallback


def _footprint_m(struct_type: str) -> float:
    return _FOOTPRINT_M.get(struct_type, _FOOTPRINT_DEFAULT)


def _check_overlap(new_lat: float, new_lon: float, new_type: str,
                   exclude_sid: str | None = None) -> str | None:
    """
    Return an error string if the proposed centre (new_lat, new_lon) would
    land within one footprint of any existing structure, else return None.
    Two structures overlap when the distance between their centres is less than
    footprint(new) + footprint(existing).
    """
    from route_time.engine.network import vincenty_m
    new_r = _footprint_m(new_type)
    for sid, struct in _state["structures"].items():
        if sid == exclude_sid:
            continue
        min_sep = new_r + _footprint_m(struct.structure_type)
        dist = vincenty_m(new_lat, new_lon, struct.center_lat, struct.center_lon)
        if dist < min_sep:
            return (f"Too close to {sid} "
                    f"({dist:.0f} m < {min_sep:.0f} m minimum separation)")
    return None


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
                        "into route_time/overlays/"}), 404
    if not os.path.exists(acc_path):
        return jsonify({"error": "No accident overlay — load "
                        "accidents.geojson into route_time/overlays/"}), 404

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
            _clear_edit_state()
            net = _state["network"]

        for s in result["stations"]:
            try:
                struct, cps = build_station(
                    net, s["lat"], s["lon"],
                    heading_deg=0,
                    structure_id=_next_sid("s"))
                _state["structures"][struct.structure_id] = struct
                _state["cps"].update(cps)
                placed_ids.append(struct.structure_id)
            except Exception:
                pass  # skip overlapping stations silently

        result["placed"] = len(placed_ids)
        result["placed_ids"] = placed_ids

    return jsonify(result)


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
                heading_deg=0, structure_id=_next_sid("s"))
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
        for prefix in ("aadt", "accidents", "crash_density"):
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
