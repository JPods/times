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

import json
import math
import os
import uuid
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
        "podsPerStation": 4, "graceDistance": 0,
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
    "structures":   {},   # structure_id → Structure
    "cps":          {},   # cp_id → ConnectionPoint
    "waypoints":    {},   # line_id → [{"lat": float, "lon": float}, ...]
    "line_pairs":   {},   # line_id → partner_line_id  (guideways always paired)
    "line_roles":   {},   # line_id → role string, e.g. "siding"
}


def _clear_edit_state():
    """Reset editing state when a new network is loaded."""
    _state["structures"] = {}
    _state["cps"]        = {}
    _state["waypoints"]  = {}
    _state["line_pairs"] = {}
    _state["line_roles"] = {}


def _reconstruct_structures_from_net(net) -> tuple:
    """
    Derive Structure and ConnectionPoint objects from a legacy .jpd network
    (one saved before <StructureMeta> was added) using node naming conventions.

    Stations:  all nodes with IDs starting "ST_"  → {sid}.NB_N_tip etc.
    Circles:   all nodes with IDs starting "TC_"  → {sid}.A{i}_out / A{i}_in

    Returns (structures_dict, cps_dict).
    """
    import math as _math

    # Group nodes by their structure prefix (text before the first '.')
    prefix_nodes: dict = {}
    for nid, node in net.nodes.items():
        if '.' in nid:
            prefix = nid.split('.')[0]
            if prefix.startswith('ST_') or prefix.startswith('TC_'):
                prefix_nodes.setdefault(prefix, {})[nid] = node

    structures: dict = {}
    cps: dict = {}

    for sid, nodes in prefix_nodes.items():

        # Internal line_ids = lines where BOTH endpoints belong to this structure
        line_ids = [
            lid for lid, ln in net.lines.items()
            if ln.start_node.node_id in nodes and ln.end_node.node_id in nodes
        ]

        if sid.startswith('ST_'):
            # ── Station ────────────────────────────────────────────────────
            nb_n_tip = nodes.get(f"{sid}.NB_N_tip")
            sb_n_tip = nodes.get(f"{sid}.SB_N_tip")
            nb_s_tip = nodes.get(f"{sid}.NB_S_tip")
            sb_s_tip = nodes.get(f"{sid}.SB_S_tip")
            if not all([nb_n_tip, sb_n_tip, nb_s_tip, sb_s_tip]):
                continue   # incomplete — skip

            # Compute heading from NB_S → NB_N
            nb_n = nodes.get(f"{sid}.NB_N")
            nb_s = nodes.get(f"{sid}.NB_S")
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
                cp_id=f"{sid}.CP_N", structure_id=sid, heading_deg=nb_h,
                inbound_node=sb_n_tip, outbound_node=nb_n_tip,
                center_lat=(nb_n_tip.lat + sb_n_tip.lat) / 2,
                center_lon=(nb_n_tip.lon + sb_n_tip.lon) / 2,
            )
            cp_s = ConnectionPoint(
                cp_id=f"{sid}.CP_S", structure_id=sid, heading_deg=sb_h,
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

        elif sid.startswith('TC_'):
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
    if line.coordinates:
        return [[lon, lat] for lat, lon in line.coordinates]
    return [
        [line.start_node.lon, line.start_node.lat],
        [line.end_node.lon,   line.end_node.lat],
    ]


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
    structs_data, cps_data = [], []
    try:
        if ext == ".jpd":
            net, structs_data, cps_data = load_jpd(path)
        else:
            with open(path) as f:
                raw = json.load(f)
            if "lines" in raw:
                net = load_podpresenter(path)
            else:
                net = load_sketchup_map(path)
    except Exception as e:
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
    return jsonify(_network_to_geojson(net))


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
        save_jpd(net, path, _state["structures"], _state["cps"])
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
        content = serialise_jpd(net, _state["structures"], _state["cps"])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    filename = f"{net.network_id}.jpd"
    return Response(
        content,
        mimetype="application/xml",
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
    cid  = data.get("id") or _new_id("TC")
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
    sid         = data.get("id") or _new_id("ST")

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
    _siding_suffixes = ("NB_to_side", "SIDE_entry", "SIDE_exit", "SIDE_to_NB")
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


@api.post("/network/connect_cps")
def connect_cps_endpoint():
    """Connect two stub-pairs: cp_a.out→cp_b.in and cp_b.out→cp_a.in."""
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data   = request.json or {}
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
            st, st_cps = build_station(net, lat, lon, heading_deg=0.0)
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            # North circle south arm ↔ station CP_N (north end, heading=0°)
            _, cp_dict_north = grid[r][c]
            tc_south = _cp_by_heading(cp_dict_north, 180.0)
            st_north = st_cps.get(f"{st.structure_id}.CP_N")
            if tc_south and st_north and tc_south.connected_to is None and st_north.connected_to is None:
                connect_cps(net, tc_south, st_north, _state["cps"])

            # Station CP_S (south end, heading=180°) ↔ south circle north arm
            _, cp_dict_south = grid[r + 1][c]
            tc_north = _cp_by_heading(cp_dict_south, 0.0)
            st_south = st_cps.get(f"{st.structure_id}.CP_S")
            if tc_north and st_south and tc_north.connected_to is None and st_south.connected_to is None:
                connect_cps(net, st_south, tc_north, _state["cps"])

    # ── 3. E-W blocks: station between (r,c) and (r,c+1) ───────────────────
    for r in range(n_rows):
        for c in range(n_cols - 1):
            lat = start_lat - r * dlat
            lon = start_lon + (c + 0.5) * dlon
            st, st_cps = build_station(net, lat, lon, heading_deg=90.0)
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            # West circle east arm ↔ station CP_S (west end, heading=270°)
            _, cp_dict_west = grid[r][c]
            tc_east = _cp_by_heading(cp_dict_west, 90.0)
            st_west = st_cps.get(f"{st.structure_id}.CP_S")
            if tc_east and st_west and tc_east.connected_to is None and st_west.connected_to is None:
                connect_cps(net, tc_east, st_west, _state["cps"])

            # Station CP_N (east end, heading=90°) ↔ east circle west arm
            _, cp_dict_east = grid[r][c + 1]
            tc_west = _cp_by_heading(cp_dict_east, 270.0)
            st_east = st_cps.get(f"{st.structure_id}.CP_N")
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
# Simulation
# ---------------------------------------------------------------------------

@api.post("/simulation/run")
def run_simulation():
    from route_time.engine.demand import LoadArray
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400
    data = request.json or {}
    slots = int(data.get("slots", 360))
    settings = _state["settings"].copy()
    settings.update(data.get("settings", {}))

    # Load demand config from demand.json if present alongside the network file
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
    result = sim.run(total_slots=slots)
    _state["sim_result"] = result
    return jsonify(result.to_dict())


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
            d = vincenty_m(cp_a.center_lat, cp_a.center_lon,
                           cp_b.center_lat, cp_b.center_lon)
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

    structs_data, cps_data = [], []
    try:
        if suffix == ".jpd":
            net, structs_data, cps_data = load_jpd(tmp_path)
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
    return jsonify(_network_to_geojson(net))


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
