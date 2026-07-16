"""
mesh_mobility.gui.state
========================
Session-keyed shared state for the MeshMobility GUI.

All modules (api.py, builders.py, overlays.py, etc.) import state from here.
The _state proxy routes reads/writes to the current request's session dict.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from flask import request, g, has_request_context

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)

import sys
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from mesh_mobility.engine import Network, Node, Line, Station
from mesh_mobility.engine.structures import (
    build_traffic_circle, build_station, connect_cps, disconnect_cp,
    rotate_station, rotate_traffic_circle,
    ConnectionPoint, Structure,
)
from mesh_mobility.io.jpd_writer import serialise_jpd


# ---------------------------------------------------------------------------
# Settings helper
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
# Session-keyed state
# ---------------------------------------------------------------------------

_sessions: Dict[str, Dict] = {}
_sessions_lock = threading.Lock()
_SESSION_COOKIE = "mm_session"
_SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
_SESSION_MAX = 200


def _new_state() -> Dict:
    """Create a fresh state dict for a new session."""
    return {
        "network": None,
        "network_path": None,
        "settings": _default_settings(),
        "sim_frames": [],
        "sim_result": None,
        "sim_active": False,
        "sim_instance": None,
        "sim_error": None,
        "structures":   {},
        "cps":          {},
        "waypoints":    {},
        "line_pairs":   {},
        "line_roles":   {},
        "_next_s":      1,
        "_next_c":      1,
        "overlays":     None,
        "_undo_stack":  [],
        "_last_access": time.time(),
    }


def _get_session_id() -> str:
    """Get or create a session ID from the request cookie."""
    sid = request.cookies.get(_SESSION_COOKIE)
    if sid and sid in _sessions:
        return sid
    sid = request.args.get("session")
    if sid and sid in _sessions:
        return sid
    return None


def _get_state() -> Dict:
    """Return the state dict for the current session."""
    if not has_request_context():
        return None
    sid = getattr(g, '_mm_session_id', None)
    if sid and sid in _sessions:
        return _sessions[sid]
    sid = _get_session_id()
    if sid and sid in _sessions:
        return _sessions[sid]
    return None


class _SessionStateProxy:
    """Proxy that makes _state[key] delegate to the current session."""

    _default = _new_state()

    def __getitem__(self, key):
        s = _get_state()
        return (s or self._default)[key]

    def __setitem__(self, key, value):
        s = _get_state()
        if s:
            s[key] = value
        else:
            self._default[key] = value

    def __contains__(self, key):
        s = _get_state()
        return key in (s or self._default)

    def get(self, key, default=None):
        s = _get_state()
        return (s or self._default).get(key, default)

    def __repr__(self):
        sid = _get_session_id() if has_request_context() else None
        return f"<SessionState sid={sid}>"


_state = _SessionStateProxy()


# ---------------------------------------------------------------------------
# Session lifecycle (registered on Blueprint by api.py)
# ---------------------------------------------------------------------------

def ensure_session():
    """Create or resume a session for every API request."""
    sid = _get_session_id()
    if not sid:
        sid = str(uuid.uuid4())[:12]
        with _sessions_lock:
            if len(_sessions) >= _SESSION_MAX:
                oldest = sorted(_sessions.items(), key=lambda x: x[1].get("_last_access", 0))
                for old_sid, _ in oldest[:len(_sessions) - _SESSION_MAX + 1]:
                    del _sessions[old_sid]
                    log.info(f"Session expired: {old_sid}")
            _sessions[sid] = _new_state()
        log.info(f"New session: {sid} (total: {len(_sessions)})")
    else:
        _sessions[sid]["_last_access"] = time.time()
    g._mm_session_id = sid


def set_session_cookie(response):
    """Set session cookie on every response."""
    sid = getattr(g, '_mm_session_id', None)
    if sid:
        response.set_cookie(_SESSION_COOKIE, sid, max_age=_SESSION_MAX_AGE,
                            httponly=True, samesite='Lax')
    return response


# ---------------------------------------------------------------------------
# Undo support
# ---------------------------------------------------------------------------

_UNDO_MAX = 20
_UNDO_SKIP_PATHS = {"/api/network/undo", "/api/network/load", "/api/network/load_text",
                     "/api/network/new", "/api/network/save", "/api/network/download",
                     "/api/simulation/run", "/api/settings", "/api/demand"}


def auto_push_undo():
    """Snapshot before any network mutation for undo support."""
    if request.method in ("POST", "DELETE", "PUT"):
        if request.path not in _UNDO_SKIP_PATHS and request.path.startswith("/api/network"):
            if "/move" in request.path or "/rotate" in request.path:
                return
            push_undo()


def push_undo():
    """Snapshot the current network state for undo."""
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


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _net() -> Optional[Network]:
    return _state["network"]


def clear_edit_state():
    """Reset editing state when a new network is loaded."""
    _state["structures"] = {}
    _state["cps"]        = {}
    _state["waypoints"]  = {}
    _state["line_pairs"] = {}
    _state["line_roles"] = {}
    _state["_next_s"]    = 1
    _state["_next_c"]    = 1


def next_sid(stype: str) -> str:
    """Return next sequential structure ID: s1,s2,... or c1,c2,..."""
    key = "_next_s" if stype == "s" else "_next_c"
    n = _state[key]
    _state[key] += 1
    return f"{stype}{n}"


def sync_counters():
    """After loading a file, advance counters past any existing s#/c# IDs."""
    max_s = max_c = 0
    for sid in _state["structures"]:
        m = re.match(r'^s(\d+)$', sid)
        if m:
            max_s = max(max_s, int(m.group(1)))
        m = re.match(r'^c(\d+)$', sid)
        if m:
            max_c = max(max_c, int(m.group(1)))
    if max_s:
        _state["_next_s"] = max_s + 1
    if max_c:
        _state["_next_c"] = max_c + 1


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------

_FOOTPRINT_M = {
    "station":        45.0,
    "traffic_circle": 22.5,
}
_FOOTPRINT_DEFAULT = 45.0


def footprint_m(struct_type: str) -> float:
    return _FOOTPRINT_M.get(struct_type, _FOOTPRINT_DEFAULT)


def check_overlap(new_lat: float, new_lon: float, new_type: str,
                  exclude_sid: str | None = None) -> str | None:
    """Return error string if new structure overlaps an existing one."""
    from mesh_mobility.engine.network import vincenty_m
    new_r = footprint_m(new_type)
    for sid, struct in _state["structures"].items():
        if sid == exclude_sid:
            continue
        min_sep = new_r + footprint_m(struct.structure_type)
        dist = vincenty_m(new_lat, new_lon, struct.center_lat, struct.center_lon)
        if dist < min_sep:
            return (f"Too close to {sid} "
                    f"({dist:.0f} m < {min_sep:.0f} m minimum separation)")
    return None


# ---------------------------------------------------------------------------
# Structure reconstruction from legacy .jpd files
# ---------------------------------------------------------------------------

def reconstruct_structures_from_net(net) -> tuple:
    """
    Derive Structure and ConnectionPoint objects from a legacy .jpd network.
    Returns (structures_dict, cps_dict).
    """
    _is_st = lambda p: p.startswith('ST_') or bool(re.match(r'^s\d+$', p))
    _is_tc = lambda p: p.startswith('TC_') or bool(re.match(r'^c\d+$', p))

    prefix_nodes: dict = {}
    for nid, node in net.nodes.items():
        if '.' in nid:
            prefix = nid.split('.')[0]
            if _is_st(prefix) or _is_tc(prefix):
                prefix_nodes.setdefault(prefix, {})[nid] = node

    structures: dict = {}
    cps: dict = {}

    for sid, nodes in prefix_nodes.items():
        line_ids = [
            lid for lid, ln in net.lines.items()
            if ln.start_node.node_id in nodes and ln.end_node.node_id in nodes
        ]

        if _is_st(sid):
            nb_n_tip = nodes.get(f"{sid}.guideway_near_out_tip")
            sb_n_tip = nodes.get(f"{sid}.guideway_far_in_tip")
            nb_s_tip = nodes.get(f"{sid}.guideway_near_in_tip")
            sb_s_tip = nodes.get(f"{sid}.guideway_far_out_tip")
            if not all([nb_n_tip, sb_n_tip, nb_s_tip, sb_s_tip]):
                continue

            nb_n = nodes.get(f"{sid}.guideway_near_out_end")
            nb_s = nodes.get(f"{sid}.guideway_near_in_end")
            heading_deg = 0.0
            if nb_n and nb_s:
                dlat = nb_n.lat - nb_s.lat
                dlon = nb_n.lon - nb_s.lon
                heading_deg = math.degrees(
                    math.atan2(dlon * math.cos(math.radians(nb_n.lat)), dlat)
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
            cp_ids = []
            tc_cps = {}
            arm_headings = []

            for arm_idx in range(4):
                out_tip = nodes.get(f"{sid}.A{arm_idx}_out")
                in_tip  = nodes.get(f"{sid}.A{arm_idx}_in")
                div     = nodes.get(f"{sid}.A{arm_idx}_div")
                if out_tip is None or in_tip is None:
                    continue

                hdg = 0.0
                if div:
                    dlat = out_tip.lat - div.lat
                    dlon = out_tip.lon - div.lon
                    hdg  = math.degrees(
                        math.atan2(dlon * math.cos(math.radians(div.lat)), dlat)
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

    # Resolve connected_to
    out_node_to_cp = {cp.outbound_node.node_id: cp for cp in cps.values()}
    in_node_to_cp  = {cp.inbound_node.node_id:  cp for cp in cps.values()}
    for ln in net.lines.values():
        cp_a = out_node_to_cp.get(ln.start_node.node_id)
        cp_b = in_node_to_cp.get(ln.end_node.node_id)
        if cp_a and cp_b and cp_a.structure_id != cp_b.structure_id:
            cp_a.connected_to = cp_b.cp_id
            cp_b.connected_to = cp_a.cp_id

    return structures, cps


def restore_structures(structures_data: list, cps_data: list, net) -> None:
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
            continue
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


# ---------------------------------------------------------------------------
# CP heading helper — used by builders and connection logic
# ---------------------------------------------------------------------------

def cp_by_heading(cp_dict: dict, target_heading: float) -> Optional[ConnectionPoint]:
    """Return the CP whose heading_deg is closest to target_heading."""
    best, best_diff = None, float("inf")
    for cp in cp_dict.values():
        diff = abs((cp.heading_deg - target_heading + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
            best = cp
    return best


# ---------------------------------------------------------------------------
# Allie capture and fault helpers
# ---------------------------------------------------------------------------

import subprocess as _subprocess
import pathlib as _pathlib

_ALLIE_CAPTURE = _pathlib.Path.home() / "Allie" / "scripts" / "allie-capture.py"


def allie_capture_simulation(result, net):
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


def allie_capture_error(event: str, message: str):
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


def write_fault(fault_text: str, context: str = "", detected_by: str = "Claude") -> None:
    """Write a FAULT file to ~/Allie/process/inbox/."""
    ts_str  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    inbox = _pathlib.Path.home() / "Allie" / "process" / "inbox"
    if not inbox.parent.parent.exists():
        return
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
# Noelle session log
# ---------------------------------------------------------------------------

_NOELLE_LOG_DIR = "/Volumes/Allie/data/noelle_sessions"


def noelle_log(action, details=None):
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
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = os.path.join(_NOELLE_LOG_DIR, f"{date_str}.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
