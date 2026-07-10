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
import urllib.parse
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

# Overlay data: 5TB is the durable store, local overlays/ is the working cache
_OVERLAY_5TB   = "/Volumes/Allie/data/overlays"
_OVERLAY_LOCAL = os.path.join(_rt_dir, "overlays")


def _overlay_path(filename):
    """Return the best path for an overlay file: 5TB if mounted, else local cache.
    Validates that the file contains valid JSON with features."""
    for d in (_OVERLAY_5TB, _OVERLAY_LOCAL):
        p = os.path.join(d, filename)
        if os.path.exists(p) and os.path.getsize(p) > 10:
            try:
                with open(p) as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("features"):
                    return p
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
    return None


def _overlay_path_by_state(prefix):
    """Find a state-specific overlay file by detecting state from network centroid."""
    net = _state.get("network")
    if not net:
        return None
    lats = [n.lat for n in net.nodes.values() if n.lat]
    lons = [n.lon for n in net.nodes.values() if n.lon]
    if not lats:
        return None
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)
    try:
        from mesh_mobility.scripts.census_overlays import fips_from_latlon, STATE_FIPS_TO_ABBR
        state_fips, _ = fips_from_latlon(center_lat, center_lon)
        if state_fips:
            abbr = STATE_FIPS_TO_ABBR.get(state_fips)
            if abbr:
                p = _overlay_path(f"{prefix}_{abbr}.geojson")
                if p:
                    # Also copy to generic so next request is fast
                    import shutil
                    dst = os.path.join(_OVERLAY_LOCAL, f"{prefix}.geojson")
                    shutil.copy2(p, dst)
                    return p
    except Exception:
        pass
    return None


def _overlay_save(filename, data):
    """Save overlay data to both 5TB (durable) and local (cache)."""
    for d in (_OVERLAY_5TB, _OVERLAY_LOCAL):
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, filename)
        with open(path, "w") as f:
            json.dump(data, f)
    log.info(f"Overlay saved: {filename} (5TB + local)")
if _parent not in sys.path:
    sys.path.insert(0, _parent)

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

# ---------------------------------------------------------------------------
# Noelle session log — every significant action saved to Allie
# ---------------------------------------------------------------------------
_NOELLE_LOG_DIR = "/Volumes/Allie/data/noelle_sessions"


def _noelle_log(action, details=None):
    """Log a MeshMobility session event to Allie's 5TB. Fire-and-forget."""
    try:
        os.makedirs(_NOELLE_LOG_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        entry = {
            "timestamp": ts,
            "action": action,
            "remote_ip": request.headers.get("CF-Connecting-IP",
                         request.headers.get("X-Forwarded-For",
                         request.remote_addr)),
            "user_agent": request.headers.get("User-Agent", "")[:120],
        }
        if details:
            entry["details"] = details

        # Append to daily log file
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = os.path.join(_NOELLE_LOG_DIR, f"{date_str}.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # never break the request


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
    "_undo_stack":  [],   # list of serialised network snapshots for undo
}


_UNDO_MAX = 20  # max snapshots
_UNDO_SKIP_PATHS = {"/api/network/undo", "/api/network/load", "/api/network/load_text",
                     "/api/network/new", "/api/network/save", "/api/network/download",
                     "/api/simulation/run", "/api/settings", "/api/demand"}


@api.before_request
def _auto_push_undo():
    """Snapshot before any network mutation for undo support.
    Skips moves/rotates — those are high-frequency; browser pushes undo once on mousedown."""
    if request.method in ("POST", "DELETE", "PUT"):
        if request.path not in _UNDO_SKIP_PATHS and request.path.startswith("/api/network"):
            # Skip structure move/rotate — too frequent for per-call snapshots
            if "/move" in request.path or "/rotate" in request.path:
                return
            _push_undo()


def _push_undo():
    """Snapshot the current network state for undo. Call before any mutation."""
    net = _state.get("network")
    if not net:
        return
    try:
        snapshot = serialise_jpd(net, _state["structures"], _state["cps"],
                                  _state["settings"], _state.get("overlays"))
        _state["_undo_stack"].append(snapshot)
        if len(_state["_undo_stack"]) > _UNDO_MAX:
            _state["_undo_stack"].pop(0)
    except Exception:
        pass


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
        _write_fault(f"Network load failed: {e}", f"path={path}")
        return jsonify({"error": str(e)}), 500

    _state["network"] = net
    _state["network_path"] = path
    _state["sim_frames"] = []
    _state["sim_result"] = None
    _noelle_log("network_load", {"path": os.path.basename(path),
                                  "stations": len(net.stations), "nodes": len(net.nodes)})
    _clear_edit_state()
    if structs_data or cps_data:
        _restore_structures(structs_data, cps_data, net)
    else:
        s, c = _reconstruct_structures_from_net(net)
        _state["structures"].update(s)
        _state["cps"].update(c)
    if file_settings:
        _state["settings"].update(file_settings)
    if file_overlays:
        _state["overlays"] = file_overlays
    if file_qa:
        _state["qa"] = file_qa

    # Overlays auto-populate on save, not load — keeps load fast
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

    # Auto-populate census overlays before saving so they embed in the .jpd
    _ensure_overlays(net)

    try:
        save_jpd(net, path, _state["structures"], _state["cps"],
                 _state["settings"], _state.get("overlays"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    _state["network_path"] = path

    # Save a copy to Allie for every public session
    _noelle_log("network_save", {"path": os.path.basename(path),
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
    _clear_edit_state()
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

    # Log designer adjustment for Noelle learning
    from mesh_mobility.engine.network import vincenty_m as _vm
    move_dist = _vm(new_lat - dlat, new_lon - dlon, new_lat, new_lon)
    _noelle_log("structure_move", {
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
    _push_undo()
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
    _clear_edit_state()
    if structs_data or cps_data:
        _restore_structures(structs_data, cps_data, net)
    if file_settings:
        _state["settings"].update(file_settings)
    _sync_counters()

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


def _cp_by_heading(cp_dict: dict, target_heading: float) -> Optional[ConnectionPoint]:
    """Return the CP whose heading_deg is closest to target_heading."""
    best, best_diff = None, float("inf")
    for cp in cp_dict.values():
        diff = abs((cp.heading_deg - target_heading + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
            best = cp
    return best


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

    # Filter to urban areas — only keep grid points near population, crashes, or traffic
    urban_pts = []  # (lat, lon) of data signal points
    for prefix in ("population_density", "crash_density", "aadt", "accidents"):
        p = _overlay_path(f"{prefix}.geojson")
        if not p:
            continue
        try:
            with open(p) as f:
                geo = json.load(f)
            for feat in geo.get("features", []):
                coords = feat["geometry"]["coordinates"]
                urban_pts.append((coords[1], coords[0]))
        except Exception:
            continue

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
    _clear_edit_state()

    # Place circles at snapped grid points
    grid_map = {}  # (r, c) → (struct, cp_dict)
    for lat, lon, r, c in snapped:
        struct, cp_dict = build_traffic_circle(
            net, lat, lon,
            structure_id=_next_sid("c"),
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
                                       structure_id=_next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            if pi == 0:
                _, cp_dict_north = s_north
                tc_south = _cp_by_heading(cp_dict_north, 180.0)
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
                tc_north = _cp_by_heading(cp_dict_south, 0.0)
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
                                       structure_id=_next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            if pi == 0:
                _, cp_dict_west = s_west
                tc_east = _cp_by_heading(cp_dict_west, 90.0)
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
                tc_west = _cp_by_heading(cp_dict_east, 270.0)
                st_east_cp = st_cps.get(f"{st.structure_id}.CP_near_far")
                if tc_west and st_east_cp and tc_west.connected_to is None and st_east_cp.connected_to is None:
                    connect_cps(net, st_east_cp, tc_west, _state["cps"])

            prev_cps = st_cps
            prev_sid = st.structure_id

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    _noelle_log("city_mesh", {
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
        _clear_edit_state()
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
                structure_id=_next_sid("c"),
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
                                           structure_id=_next_sid("s"))
                _state["structures"][st.structure_id] = st
                _state["cps"].update(st_cps)
                n_stations += 1

                # Rotated arm headings for CP lookups
                h_north = (0.0 + angle_deg) % 360
                h_south = (180.0 + angle_deg) % 360

                if pi == 0:
                    # First station: connect to upper circle's down arm
                    _, cp_dict_north = grid[r][c]
                    tc_south = _cp_by_heading(cp_dict_north, h_south)
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
                    tc_north = _cp_by_heading(cp_dict_south, h_north)
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
                                           structure_id=_next_sid("s"))
                _state["structures"][st.structure_id] = st
                _state["cps"].update(st_cps)
                n_stations += 1

                # Rotated arm headings for CP lookups
                h_east = (90.0 + angle_deg) % 360
                h_west = (270.0 + angle_deg) % 360

                if pi == 0:
                    # First station: connect to left circle's right arm
                    _, cp_dict_west = grid[r][c]
                    tc_east = _cp_by_heading(cp_dict_west, h_east)
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
                    tc_west = _cp_by_heading(cp_dict_east, h_west)
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

    _noelle_log("simulation_run", {"stations": len(station_ids), "slots": slots,
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
    _clear_edit_state()
    if structs_data or cps_data:
        _restore_structures(structs_data, cps_data, net)
    else:
        s, c = _reconstruct_structures_from_net(net)
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
    """FHWA HPMS traffic data — checks generic, then state file from 5TB."""
    p = _overlay_path("aadt.geojson")
    if not p:
        p = _overlay_path_by_state("aadt")
    if p:
        with open(p) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "AADT data not configured — click Fetch Data"}), 404


@api.get("/overlays/accidents")
def overlay_accidents():
    """NHTSA FARS fatal crash data — checks generic, then state file from 5TB."""
    p = _overlay_path("accidents.geojson")
    if not p:
        p = _overlay_path_by_state("accidents")
    if p:
        with open(p) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Crash data not configured — click Fetch Data"}), 404


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


@api.post("/overlays/fetch")
def overlay_fetch_all():
    """Fetch all available overlay data for the current network location.

    Census (population, property values, jobs) — works for any US location.
    FARS fatal crashes — works for any US state.
    AADT and all-crash density — only available for pre-harvested cities.
    """
    data = request.json or {}
    center_lat = None
    center_lon = None

    # Try network centroid first
    net = _state.get("network")
    if net:
        lats = [n.lat for n in net.nodes.values() if n.lat]
        lons = [n.lon for n in net.nodes.values() if n.lon]
        if lats:
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)

    # Fall back to map center sent by browser
    if center_lat is None and "lat" in data and "lon" in data:
        center_lat = float(data["lat"])
        center_lon = float(data["lon"])

    if center_lat is None:
        return jsonify({"error": "No location — place a station or search for a city first"}), 400
    _noelle_log("overlay_fetch", {"lat": center_lat, "lon": center_lon})
    fetched = []
    errors = []

    # Census data (any US location)
    try:
        from mesh_mobility.scripts.census_overlays import process_location, get_api_key
        api_key = get_api_key()
        city_key = process_location(center_lat, center_lon, api_key)
        if city_key:
            fetched.extend(["population_density", "property_values", "jobs"])
            overlays = _state.get("overlays") or {}
            overlays["city"] = city_key
            if "files" not in overlays:
                overlays["files"] = []
            for layer in ("population_density", "property_values", "jobs"):
                if layer not in overlays["files"]:
                    overlays["files"].append(layer)
            _state["overlays"] = overlays
        else:
            errors.append("Census: could not determine US location")
    except Exception as e:
        errors.append(f"Census: {e}")

    # Determine state FIPS for FARS + AADT
    state_fips = None
    state_abbr = None
    try:
        from mesh_mobility.scripts.census_overlays import fips_from_latlon, STATE_FIPS_TO_ABBR
        state_fips, county_fips = fips_from_latlon(center_lat, center_lon)
        if state_fips:
            state_abbr = STATE_FIPS_TO_ABBR.get(state_fips)
    except Exception as e:
        errors.append(f"Location lookup: {e}")

    # Load ALL available data from 5TB for this state — always reload, never skip
    if state_abbr:
        import shutil
        log.info(f"Fetch Data: checking 5TB for {state_abbr.upper()}...")
        # All overlay types that might exist on 5TB per state
        state_prefixes = ["aadt", "accidents", "crash_density", "crashes_all"]
        for prefix in state_prefixes:
            src = os.path.join(_OVERLAY_5TB, f"{prefix}_{state_abbr}.geojson")
            if os.path.exists(src) and os.path.getsize(src) > 100:
                dst = os.path.join(_OVERLAY_LOCAL, f"{prefix}.geojson")
                shutil.copy2(src, dst)
                try:
                    with open(src) as _f:
                        _count = len(json.load(_f).get("features", []))
                except Exception:
                    _count = "?"
                name = prefix.replace("crashes_all", "all_crashes")
                log.info(f"  ✓ {prefix}_{state_abbr}: {_count} features")
                if name not in fetched:
                    fetched.append(name)
            else:
                log.info(f"  ✗ {prefix}_{state_abbr}: not on 5TB")

        # Also check county-specific census files
        if county_fips:
            city_key = f"{state_abbr}_{county_fips}"
            for prefix in ("population_density", "property_values", "jobs"):
                src = os.path.join(_OVERLAY_5TB, f"{prefix}_{city_key}.geojson")
                if os.path.exists(src) and os.path.getsize(src) > 100:
                    dst = os.path.join(_OVERLAY_LOCAL, f"{prefix}.geojson")
                    shutil.copy2(src, dst)
                    try:
                        with open(src) as _f:
                            _count = len(json.load(_f).get("features", []))
                    except Exception:
                        _count = "?"
                    log.info(f"  ✓ {prefix}_{city_key}: {_count} features")
                    if prefix not in fetched:
                        fetched.append(prefix)

        if fetched:
            log.info(f"Fetch Data: loaded from 5TB for {state_abbr.upper()}: {fetched}")

        # On-demand fallback for AADT if 5TB didn't have it
        if "aadt" not in fetched:
            try:
                aadt_ok = _fetch_aadt(state_abbr, center_lat, center_lon)
                if aadt_ok:
                    fetched.append("aadt")
            except Exception as e:
                errors.append(f"AADT: {e}")

    # FARS on-demand fallback if 5TB didn't have it
    if state_fips and "accidents" not in fetched:
        try:
            fars_ok = _fetch_fars(state_fips, state_abbr, center_lat, center_lon)
            if fars_ok:
                fetched.extend(["accidents", "crash_density"])
        except Exception as e:
            errors.append(f"FARS: {e}")

    return jsonify({
        "fetched": fetched,
        "location": {"lat": center_lat, "lon": center_lon},
        "errors": errors,
    })


def _fetch_aadt(state_abbr, center_lat, center_lon):
    """Fetch AADT data from FHWA HPMS for a state, filtered near the network centroid.

    Source: https://geo.dot.gov/server/rest/services/Hosted/HPMS_FULL_{ST}_{YEAR}/FeatureServer/0
    Fields: aadt (int), route_id, routename, f_system
    Geometry: polylines — we extract midpoints
    """
    import urllib.request, gzip
    overlay_dir = os.path.join(_rt_dir, "overlays")
    st = state_abbr.upper()

    # Bounding box ~30 miles around centroid
    delta = 0.4
    bbox = f"{center_lon-delta},{center_lat-delta},{center_lon+delta},{center_lat+delta}"

    features = []
    for year in (2024, 2023, 2022, 2020):
        base = (
            f"https://geo.dot.gov/server/rest/services/Hosted/"
            f"HPMS_FULL_{st}_{year}/FeatureServer/0/query"
        )
        params = (
            f"?where=aadt%3E%3D5000"
            f"&geometry={bbox}"
            f"&geometryType=esriGeometryEnvelope"
            f"&spatialRel=esriSpatialRelIntersects"
            f"&outFields=aadt,route_id,routename,f_system"
            f"&returnGeometry=true"
            f"&outSR=4326"
            f"&f=json"
            f"&resultRecordCount=4000"
        )
        url = base + params
        log.info(f"AADT: trying HPMS {st} {year}...")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "JPods/MeshMobility",
                "Accept-Encoding": "gzip, identity",
            })
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                data = json.loads(raw.decode())
        except Exception as e:
            log.warning(f"AADT {year}: {e}")
            continue

        if data and "features" in data and len(data["features"]) > 0:
            features = data["features"]
            log.info(f"AADT: got {len(features)} records from HPMS {st} {year}")
            break
        elif data and "error" in data:
            log.warning(f"AADT {year}: {data['error'].get('message', '')}")

    if not features:
        log.info(f"AADT: no data for {st}")
        return False

    # Convert polylines to point features (midpoint)
    geojson_features = []
    seen = set()
    for feat in features:
        attrs = feat.get("attributes", {})
        geom = feat.get("geometry", {})
        aadt = attrs.get("aadt", 0)
        if not aadt or aadt < 5000:
            continue

        route = attrs.get("routename") or attrs.get("route_id") or ""
        tier = "core" if aadt >= 10000 else "secondary"

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
        return False

    geojson = {"type": "FeatureCollection", "features": geojson_features}
    _overlay_save("aadt.geojson", geojson)
    return True


def _fetch_fars(state_fips, state_abbr, center_lat, center_lon):
    """Fetch FARS fatal crash data from NHTSA bulk CSV downloads.

    Source: https://static.nhtsa.gov/nhtsa/downloads/FARS/{YEAR}/National/FARS{YEAR}NationalCSV.zip
    Contains ACCIDENT.CSV with LATITUDE, LONGITUD, FATALS, STATE, etc.
    Downloads national ZIP, filters to state, then filters to ~30mi around centroid.
    """
    import urllib.request, csv, io, zipfile
    from collections import defaultdict
    overlay_dir = os.path.join(_rt_dir, "overlays")
    state_num = int(state_fips)
    delta = 0.4  # ~30 miles
    all_crashes = []

    for year in (2022, 2021, 2020, 2019):
        url = f"https://static.nhtsa.gov/nhtsa/downloads/FARS/{year}/National/FARS{year}NationalCSV.zip"
        log.info(f"FARS: downloading {year} ZIP...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JPods/MeshMobility"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read()
        except Exception as e:
            log.warning(f"FARS {year} download: {e}")
            continue

        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
            acc_name = None
            for name in zf.namelist():
                basename = name.split("/")[-1].upper()
                if basename.startswith("ACCIDENT") and basename.endswith(".CSV"):
                    acc_name = name
                    break
            if not acc_name:
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
                    if lon > 0:
                        lon = -lon

                    # Filter to area near centroid
                    if abs(lat - center_lat) > delta or abs(lon - center_lon) > delta:
                        continue

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

            log.info(f"FARS {year}: {sum(1 for c in all_crashes if c['year']==year)} crashes near centroid")
        except Exception as e:
            log.warning(f"FARS {year} processing: {e}")
            continue

    if not all_crashes:
        log.info("FARS: no crash data found near centroid")
        return False

    # Save fatal crashes
    features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
        "properties": {k: v for k, v in c.items() if k not in ("lat", "lon")},
    } for c in all_crashes]

    geojson = {"type": "FeatureCollection", "features": features}
    _overlay_save("accidents.geojson", geojson)

    # Build crash density grid (200m cells)
    cell_deg = 200 / 111000
    grid = defaultdict(lambda: {"crashes": 0, "injury": 0, "fatal": 0, "pedestrian": 0})
    for feat in features:
        lon, lat = feat["geometry"]["coordinates"]
        gx = round(lon / cell_deg) * cell_deg
        gy = round(lat / cell_deg) * cell_deg
        key = (round(gx, 6), round(gy, 6))
        grid[key]["crashes"] += 1
        grid[key]["fatal"] += feat["properties"].get("fatals", 1)
        grid[key]["injury"] += 1

    density_features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {**counts, "density": round(counts["crashes"] / 4, 1)},
    } for (lon, lat), counts in grid.items()]

    _overlay_save("crash_density.geojson", {"type": "FeatureCollection", "features": density_features})
    return True


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
    """All-severity crashes if available, falls back to FARS fatal density.
    Normalizes different state DOT formats to standard {crashes, injury, fatal, pedestrian, density}."""
    # Prefer all-severity crash data
    p = _overlay_path("crashes_all.geojson")
    if not p:
        p = _overlay_path_by_state("crashes_all")

    if p:
        with open(p) as f:
            data = json.load(f)
        # Check if this needs normalization (state DOT format vs our standard)
        if data.get("features") and "crashes" not in data["features"][0].get("properties", {}):
            data = _normalize_crash_data(data)
        return jsonify(data)

    return jsonify({"error": "All-severity crash data not available for this state. "
                    "Currently harvested: OK (OKC). More states coming."}), 404


def _normalize_crash_data(raw_geojson):
    """Convert state DOT crash point data to gridded density format.
    Aggregates individual crash points to 200m grid cells with standard properties."""
    from collections import defaultdict
    cell_deg = 200 / 111000  # ~0.0018°

    grid = defaultdict(lambda: {"crashes": 0, "injury": 0, "fatal": 0, "pedestrian": 0})

    for feat in raw_geojson.get("features", []):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})

        # Get coordinates — might be in geometry or properties
        if geom and geom.get("coordinates"):
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
        elif "LATITUDE" in props and "LONGITUDE" in props:
            lat = float(props["LATITUDE"])
            lon = float(props["LONGITUDE"])
        else:
            continue

        if lat == 0 or lon == 0:
            continue

        # Snap to grid
        gx = round(lon / cell_deg) * cell_deg
        gy = round(lat / cell_deg) * cell_deg
        key = (round(gx, 6), round(gy, 6))

        grid[key]["crashes"] += 1
        # Detect injury — various field names across states
        fat = props.get("FAT", props.get("fatals", props.get("FATALS", 0)))
        inj = props.get("INJ", props.get("INJURED", props.get("injuries", 0)))
        ped = props.get("PEDSTRIANS", props.get("pedestrian", props.get("PEDS", 0)))
        try:
            fat = int(fat) if fat and fat != "N" else 0
        except (ValueError, TypeError):
            fat = 0
        try:
            inj = int(inj) if inj and inj != "N" else 0
        except (ValueError, TypeError):
            inj = 0
        try:
            ped = int(ped) if ped and ped != "No" else 0
        except (ValueError, TypeError):
            ped = 0

        grid[key]["fatal"] += fat
        grid[key]["injury"] += (1 if inj > 0 or fat > 0 else 0)
        grid[key]["pedestrian"] += (1 if ped > 0 else 0)

    # Estimate years from data range
    years = 4  # default
    features = []
    for (lon, lat), counts in grid.items():
        density = round(counts["crashes"] / years, 1)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {**counts, "density": density},
        })

    log.info(f"Normalized crash data: {len(raw_geojson.get('features',[]))} points → {len(features)} grid cells")
    return {"type": "FeatureCollection", "features": features}


@api.get("/overlays/mobility")
def overlay_mobility():
    """Cell mobility travel pattern data — checks 5TB then local cache."""
    p = _overlay_path("mobility.geojson")
    if p:
        with open(p) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "Mobility data not configured"}), 404


def _ensure_overlays(net):
    """On .jpd save, check if overlay files exist for this network's location.

    If any are missing or empty, auto-fetch from government APIs:
      - Census (population density, property values, jobs) — any US location
      - AADT (traffic counts) — any US state via FHWA HPMS
      - FARS (fatal crashes + crash density) — any US state via NHTSA bulk CSV
    """
    all_layers = ("population_density", "property_values", "jobs", "aadt", "accidents", "crash_density")

    # Check which are missing (from both 5TB and local)
    missing = [layer for layer in all_layers if not _overlay_path(f"{layer}.geojson")]

    if not missing:
        return

    # Compute centroid from network
    lats = [n.lat for n in net.nodes.values() if n.lat]
    lons = [n.lon for n in net.nodes.values() if n.lon]
    if not lats:
        log.warning("Overlay auto-fetch: no positioned nodes in network")
        return

    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)
    log.info(f"Overlay auto-fetch: missing {missing} for ({center_lat:.4f}, {center_lon:.4f})")

    # Census overlays
    census_missing = [l for l in missing if l in ("population_density", "property_values", "jobs")]
    if census_missing:
        try:
            from mesh_mobility.scripts.census_overlays import process_location, get_api_key
            api_key = get_api_key()
            city_key = process_location(center_lat, center_lon, api_key)
            if city_key:
                overlays = _state.get("overlays") or {}
                overlays["city"] = city_key
                if "files" not in overlays:
                    overlays["files"] = []
                for layer in ("population_density", "property_values", "jobs"):
                    if layer not in overlays["files"]:
                        overlays["files"].append(layer)
                _state["overlays"] = overlays
                log.info(f"Census overlays populated for {city_key}")
        except Exception as e:
            log.error(f"Census auto-fetch failed: {e}")

    # Determine state for AADT + FARS
    state_fips, state_abbr = None, None
    if any(l in missing for l in ("aadt", "accidents", "crash_density")):
        try:
            from mesh_mobility.scripts.census_overlays import fips_from_latlon, STATE_FIPS_TO_ABBR
            state_fips, _ = fips_from_latlon(center_lat, center_lon)
            if state_fips:
                state_abbr = STATE_FIPS_TO_ABBR.get(state_fips)
        except Exception as e:
            log.error(f"FIPS lookup failed: {e}")

    # AADT
    if "aadt" in missing and state_abbr:
        try:
            _fetch_aadt(state_abbr, center_lat, center_lon)
        except Exception as e:
            log.error(f"AADT auto-fetch failed: {e}")

    # FARS + crash density
    if ("accidents" in missing or "crash_density" in missing) and state_fips and state_abbr:
        try:
            _fetch_fars(state_fips, state_abbr, center_lat, center_lon)
        except Exception as e:
            log.error(f"FARS auto-fetch failed: {e}")


def _census_overlay_or_fetch(layer_name):
    """Serve a census overlay — checks 5TB then local, auto-fetches if missing."""
    p = _overlay_path(f"{layer_name}.geojson")
    if p:
        with open(p) as f:
            return jsonify(json.load(f))

    # Auto-fetch: detect location from current network centroid
    net = _state.get("network")
    if not net:
        return jsonify({"error": f"No network loaded — load a .jpd first"}), 404

    lats = [n.lat for n in net.nodes.values() if n.lat]
    lons = [n.lon for n in net.nodes.values() if n.lon]
    if not lats:
        return jsonify({"error": "Network has no positioned nodes"}), 404

    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    try:
        from mesh_mobility.scripts.census_overlays import process_location, get_api_key
        log.info(f"Auto-fetching census data for ({center_lat:.4f}, {center_lon:.4f})...")
        api_key = get_api_key()
        city_key = process_location(center_lat, center_lon, api_key)
    except Exception as e:
        log.error(f"Census auto-fetch failed: {e}")
        return jsonify({"error": f"Census data fetch failed: {e}"}), 500

    if not city_key:
        return jsonify({"error": "Could not determine location — is this in the US?"}), 404

    # Serve the now-populated file
    if os.path.exists(local_path) and os.path.getsize(local_path) > 10:
        with open(local_path) as f:
            return jsonify(json.load(f))

    return jsonify({"error": f"Census data fetched but {layer_name} not generated for this county"}), 404


@api.get("/overlays/population_density")
def overlay_population_density():
    """Census ACS population density by tract — auto-fetches if missing."""
    return _census_overlay_or_fetch("population_density")


@api.get("/overlays/property_values")
def overlay_property_values():
    """Census ACS median home value by tract — auto-fetches if missing."""
    return _census_overlay_or_fetch("property_values")


@api.get("/overlays/jobs")
def overlay_jobs():
    """Census ACS employed civilians by tract — auto-fetches if missing."""
    return _census_overlay_or_fetch("jobs")


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
    from mesh_mobility.engine.network import vincenty_m
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


@api.post("/noelle/wild_guess")
def noelle_wild_guess():
    """Wild Guess: add traffic circles between draft stations and auto-connect everything.

    Call after Draft + Apply. Places circles at midpoints between nearby station pairs,
    then runs auto-connect. Produces a complete connected network from Noelle's stations.
    """
    _push_undo()
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
            cid = _next_sid("c")
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

    _noelle_log("wild_guess", {
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
