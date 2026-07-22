"""
mesh_mobility.gui.network_io
==============================
Network load, save, export, and file I/O endpoints.

Extracted from api.py in Round 4 refactoring (2026-07-15).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict

from flask import Blueprint, jsonify, request, Response

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


from mesh_mobility.engine import Network, Node, Line, Station
from mesh_mobility.engine.structures import (
    ConnectionPoint, Structure,
)
from mesh_mobility.io import load_jpd, load_podpresenter, load_sketchup_map
from mesh_mobility.io.jpd_writer import save_jpd, serialise_jpd

# ---------------------------------------------------------------------------
# Overlay data -- reads from CrashHarvester library
# ---------------------------------------------------------------------------
from CrashHarvester.reader import MobilityData
_md = MobilityData()

# ---------------------------------------------------------------------------
# Shared state imports
# ---------------------------------------------------------------------------
from mesh_mobility.gui.state import (
    _state, _net, _ALLIE_CAPTURE, _NOELLE_LOG_DIR,
    ensure_session, set_session_cookie, auto_push_undo,
    clear_edit_state, sync_counters,
    reconstruct_structures_from_net, restore_structures,
    noelle_log, write_fault,
    cp_by_heading,
)

# ---------------------------------------------------------------------------
# GeoJSON helpers -- imported from api.py (they stay there as the /network
# GET endpoint and other modules need them)
# ---------------------------------------------------------------------------
from mesh_mobility.gui.api import _network_to_geojson

# ---------------------------------------------------------------------------
# PATH SECURITY — Athena RED FLAG
# Only allow file operations in approved directories.
# Any path outside these is rejected. No exceptions.
# ---------------------------------------------------------------------------
ALLOWED_PATHS = [
    os.path.expanduser("~/Documents/08_JPods/03_Technology/00_working_code/mesh_mobility_maps/"),
    "/Applications/RouteTime_JPods/",
    os.path.expanduser("~/Allie/"),
    "/Volumes/Allie/",
    "/tmp/mesh_mobility/",
]

def _validate_path(path: str, operation: str = "access") -> str:
    """Validate that a file path is within allowed directories.

    Args:
        path: The requested file path
        operation: 'read' or 'write' — for error messages

    Returns:
        The resolved absolute path if valid

    Raises:
        ValueError: If path is outside allowed directories
    """
    if not path:
        raise ValueError(f"No path provided for {operation}")

    resolved = os.path.realpath(os.path.expanduser(path))

    # Reject path traversal attempts
    if ".." in path:
        write_fault(f"Path traversal rejected: {path}", f"operation={operation}")
        raise ValueError(f"Path traversal not allowed: {path}")

    # Check against whitelist
    for allowed in ALLOWED_PATHS:
        allowed_resolved = os.path.realpath(os.path.expanduser(allowed))
        if resolved.startswith(allowed_resolved):
            return resolved

    write_fault(f"Path outside allowed directories: {path}", f"operation={operation}, resolved={resolved}")
    raise ValueError(
        f"File {operation} restricted to approved directories. "
        f"'{path}' is not in an allowed location."
    )

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
network_io_bp = Blueprint("network_io", __name__, url_prefix="/api")

# Register session lifecycle hooks (same as api.py)
network_io_bp.before_request(ensure_session)
network_io_bp.after_request(set_session_cookie)
network_io_bp.before_request(auto_push_undo)


# ---------------------------------------------------------------------------
# Noelle observation hooks (Andi agent infrastructure)
# ---------------------------------------------------------------------------

def _noelle_on_save(net, path, state):
    """Noelle rates the network quality and logs observation.
    If she wants a human review, she asks Alice to create an Action."""
    import importlib.util
    script = "/opt/andi/scripts/noelle-observe.py"
    if not os.path.exists(script):
        return

    spec = importlib.util.spec_from_file_location("noelle_observe", script)
    noelle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(noelle)

    structures = state.get("structures", {})
    station_count = len(net.stations) if hasattr(net, "stations") else 0
    circle_count = sum(1 for s in structures.values()
                       if getattr(s, "structure_type", "") == "traffic_circle")
    connection_count = len(net.connections) if hasattr(net, "connections") else 0

    network_data = {
        "name": os.path.basename(path).replace(".jpd", ""),
        "stations": [{"id": sid} for sid in (net.stations.keys() if hasattr(net, "stations") else [])],
        "connections": [{"id": cid} for cid in (net.connections.keys() if hasattr(net, "connections") else [])],
    }
    user_email = state.get("user_email")
    stats = noelle.on_network_save(network_data, user_email)

    # Quality rating — simple heuristics Noelle applies immediately
    issues = []
    if station_count < 3:
        issues.append("too_few_stations")
    if station_count > 0 and connection_count / max(station_count, 1) < 1.0:
        issues.append("disconnected_stations")
    if station_count > 500:
        issues.append("unusually_large")

    quality = "good" if not issues else "review"

    if quality == "review":
        # Ask Alice to create an Action for human review
        try:
            alice_script = "/opt/andi/scripts/alice-observe.py"
            if os.path.exists(alice_script):
                aspec = importlib.util.spec_from_file_location("alice_observe", alice_script)
                alice = importlib.util.module_from_spec(aspec)
                aspec.loader.exec_module(alice)
                alice.on_action_needed(
                    contact_email=user_email or "staff@jpods.com",
                    action_type="network_review",
                    description=(
                        f"Noelle flagged '{os.path.basename(path)}' for review: "
                        f"{', '.join(issues)}. "
                        f"{station_count} stations, {connection_count} connections, "
                        f"{circle_count} circles."
                    ),
                    due_days=5,
                )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

def _maps_dir() -> str:
    """Resolve the maps directory: Andi library, 5TB, or code-relative fallback."""
    # Andi production layout
    andi_lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "library", "drafts")
    if os.path.isdir(andi_lib):
        return andi_lib
    # 5TB drive (Mac)
    allie_maps = "/Volumes/Allie/MeshMobility/mesh_mobility_maps"
    if os.path.isdir(allie_maps):
        return allie_maps
    # Code-relative fallback (dev)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..", "mesh_mobility_maps")


@network_io_bp.get("/library")
def get_library():
    """Return the network library index."""
    maps_dir = _maps_dir()
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
    # Noelle observation — library browse
    try:
        import importlib.util
        _ns = "/opt/andi/scripts/noelle-observe.py"
        if os.path.exists(_ns):
            spec = importlib.util.spec_from_file_location("noelle_observe", _ns)
            _no = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_no)
            _no.on_library_browse(user_email=_state.get("user_email"))
    except Exception:
        pass

    return jsonify({"networks": networks})


@network_io_bp.post("/network/load_library")
def load_library_file():
    """Load a .jpd file from the library by filename.
    Called when the app opens with ?load=filename.jpd or ?clone=filename.jpd."""
    data = request.json or {}
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"error": "filename required"}), 400
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    path = os.path.join(_maps_dir(), filename)
    if not os.path.isfile(path):
        return jsonify({"error": f"Not found in library: {filename}"}), 404
    return _load_from_path(path)


# ---------------------------------------------------------------------------
# Load / Save / Download / New / Reload
# ---------------------------------------------------------------------------

def _load_from_path(path: str):
    """Core load logic — used by both load_network and load_library_file."""
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
        if "custom_points" in file_overlays:
            _state["custom_points"] = file_overlays.pop("custom_points")
    if file_qa:
        _state["qa"] = file_qa

    sync_counters()
    return jsonify({**_network_to_geojson(net), "settings": _state["settings"]})


@network_io_bp.post("/network/load")
def load_network():
    data = request.json or {}
    path = data.get("path", "")
    try:
        path = _validate_path(path, "read")
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
    if not os.path.exists(path):
        return jsonify({"error": f"File not found: {path}"}), 400
    return _load_from_path(path)


@network_io_bp.post("/network/save")
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
        path = _validate_path(path, "write")
    except ValueError as e:
        return jsonify({"error": str(e)}), 403

    try:
        overlays = dict(_state.get("overlays") or {})
        if _state.get("custom_points"):
            overlays["custom_points"] = _state["custom_points"]
        save_jpd(net, path, _state["structures"], _state["cps"],
                 _state["settings"], overlays)
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

    # Register with WC3 as a Document (never break the save)
    try:
        from mesh_mobility.gui.auth import register_network_save
        settings = _state.get("settings") or {}
        register_network_save(os.path.basename(path), {
            "city": settings.get("city", net.network_id),
            "state": settings.get("state", ""),
            "country": settings.get("country", ""),
            "stations": len(net.stations),
            "circles": sum(1 for s in _state["structures"].values()
                           if getattr(s, "structure_type", "") == "traffic_circle"),
            "total_miles": round(net.total_length_m() / 1609.34, 1),
        })
    except Exception:
        pass

    # Noelle observation — quality rating and pattern learning
    try:
        _noelle_on_save(net, path, _state)
    except Exception:
        pass  # never break the save

    return jsonify({"saved": path})


# ---------------------------------------------------------------------------
# Merge — combine two .jpd networks by UUID
# ---------------------------------------------------------------------------

@network_io_bp.post("/network/merge")
def merge_network():
    """Merge a second .jpd into the current network.

    Structures with matching UUIDs are treated as the same physical asset —
    the current network's version is kept. New structures get renumbered
    local IDs (s#, c#) to avoid collisions. Guideways between merged
    structures are preserved. Cross-network connections must be made manually.

    Body: {path: "/path/to/other.jpd"} or {content: "<jpd json string>"}
    """
    import re as _re
    from mesh_mobility.engine.structures import (
        build_traffic_circle, build_station, connect_cps,
    )

    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded — open a network first"}), 400

    data = request.json or {}
    path = data.get("path")
    content = data.get("content")

    # Load the second network
    try:
        if content:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".jpd", mode="w", delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            result = load_jpd(tmp_path)
            os.unlink(tmp_path)
        elif path:
            if not os.path.exists(path):
                return jsonify({"error": f"File not found: {path}"}), 400
            result = load_jpd(path)
        else:
            return jsonify({"error": "Provide 'path' or 'content'"}), 400

        other_net = result[0]
        other_structs_data = result[1]
        other_cps_data = result[2]
    except Exception as e:
        return jsonify({"error": f"Failed to load merge file: {e}"}), 500

    # Build Structure/CP objects from the other network's data
    other_structs = {}
    for s in other_structs_data:
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
            structure_uuid=s.get("structure_uuid"),
        )
        other_structs[struct.structure_id] = struct

    # Collect existing UUIDs in current network
    existing_uuids = {s.structure_uuid: sid
                      for sid, s in _state["structures"].items()
                      if s.structure_uuid}

    # Determine which structures are new vs duplicates
    skipped = []   # UUIDs already present
    added = []     # new structures merged in
    id_remap = {}  # old_sid → new_sid

    sync_counters()

    for old_sid, struct in other_structs.items():
        if struct.structure_uuid and struct.structure_uuid in existing_uuids:
            # Same physical station — skip, map old ID to existing ID
            id_remap[old_sid] = existing_uuids[struct.structure_uuid]
            skipped.append(struct.structure_uuid)
            continue

        # Assign new local ID
        if struct.structure_type == "station":
            new_sid = f"s{_state['_next_s']}"
            _state["_next_s"] += 1
        else:
            new_sid = f"c{_state['_next_c']}"
            _state["_next_c"] += 1
        id_remap[old_sid] = new_sid

        # Remap node IDs: old_sid.suffix → new_sid.suffix
        new_node_ids = []
        for old_nid in struct.node_ids:
            if old_nid.startswith(old_sid + "."):
                suffix = old_nid[len(old_sid):]
                new_nid = new_sid + suffix
            else:
                new_nid = old_nid
            new_node_ids.append(new_nid)

            # Copy node from other_net to current net
            old_node = other_net.nodes.get(old_nid)
            if old_node and new_nid not in net.nodes:
                new_node = Node(node_id=new_nid, lat=old_node.lat, lon=old_node.lon,
                                is_station=old_node.is_station)
                net.nodes[new_nid] = new_node
                if old_node.is_station:
                    net.stations[new_nid] = Station(station_id=new_nid, node=new_node)

        # Remap CP IDs
        new_cp_ids = []
        for old_cpid in struct.cp_ids:
            if old_cpid.startswith(old_sid + "."):
                suffix = old_cpid[len(old_sid):]
                new_cp_ids.append(new_sid + suffix)
            else:
                new_cp_ids.append(old_cpid)

        # Remap line IDs
        new_line_ids = []
        for old_lid in struct.line_ids:
            if old_lid.startswith(old_sid + "_"):
                new_lid = new_sid + old_lid[len(old_sid):]
            else:
                new_lid = f"{new_sid}_L_{old_lid}"
            new_line_ids.append(new_lid)

            # Copy internal lines
            old_line = other_net.lines.get(old_lid)
            if old_line and new_lid not in net.lines:
                start_nid = old_line.start_node.node_id
                end_nid = old_line.end_node.node_id
                # Remap node references
                if start_nid.startswith(old_sid + "."):
                    start_nid = new_sid + start_nid[len(old_sid):]
                if end_nid.startswith(old_sid + "."):
                    end_nid = new_sid + end_nid[len(old_sid):]
                if start_nid in net.nodes and end_nid in net.nodes:
                    from mesh_mobility.engine.network import vincenty_m
                    sn = net.nodes[start_nid]
                    en = net.nodes[end_nid]
                    net.lines[new_lid] = Line(
                        line_id=new_lid, start_node=sn, end_node=en,
                        length_m=vincenty_m(sn.lat, sn.lon, en.lat, en.lon),
                        coordinates=old_line.coordinates,
                    )

        # Create the remapped structure
        new_struct = Structure(
            structure_id=new_sid,
            structure_type=struct.structure_type,
            cp_ids=new_cp_ids,
            node_ids=new_node_ids,
            line_ids=new_line_ids,
            center_lat=struct.center_lat,
            center_lon=struct.center_lon,
            heading_deg=struct.heading_deg,
            arm_headings=struct.arm_headings,
            structure_uuid=struct.structure_uuid,
        )
        _state["structures"][new_sid] = new_struct
        added.append(new_sid)

    # Remap and add CPs for new structures
    for c in other_cps_data:
        old_sid = c["structure_id"]
        new_sid = id_remap.get(old_sid)
        if not new_sid or new_sid in existing_uuids.values():
            # Skip CPs for structures we already have
            if old_sid in id_remap and id_remap[old_sid] in [s for s in _state["structures"] if _state["structures"][s].structure_uuid in existing_uuids]:
                continue

        # Remap CP ID
        old_cpid = c["cp_id"]
        if old_cpid.startswith(old_sid + "."):
            new_cpid = new_sid + old_cpid[len(old_sid):]
        else:
            new_cpid = old_cpid

        # Remap node references
        old_in = c["inbound_node"]
        old_out = c["outbound_node"]
        if old_in.startswith(old_sid + "."):
            new_in = new_sid + old_in[len(old_sid):]
        else:
            new_in = old_in
        if old_out.startswith(old_sid + "."):
            new_out = new_sid + old_out[len(old_sid):]
        else:
            new_out = old_out

        in_node = net.nodes.get(new_in)
        out_node = net.nodes.get(new_out)
        if not in_node or not out_node:
            continue

        cp = ConnectionPoint(
            cp_id=new_cpid,
            structure_id=new_sid,
            heading_deg=c["heading_deg"],
            inbound_node=in_node,
            outbound_node=out_node,
            center_lat=c["center_lat"],
            center_lon=c["center_lon"],
            connected_to=None,  # cross-network connections made manually
            cp_uuid=c.get("cp_uuid"),
        )
        _state["cps"][new_cpid] = cp

    # Copy inter-structure guideways (connections between structures in the merged file)
    for old_lid, old_line in other_net.lines.items():
        # Skip internal lines (already handled above)
        if old_lid in [lid for s in other_structs.values() for lid in s.line_ids]:
            continue
        # Remap start/end node IDs
        start_nid = old_line.start_node.node_id
        end_nid = old_line.end_node.node_id
        start_prefix = start_nid.split(".")[0] if "." in start_nid else None
        end_prefix = end_nid.split(".")[0] if "." in end_nid else None

        if start_prefix and start_prefix in id_remap:
            new_start = id_remap[start_prefix] + start_nid[len(start_prefix):]
        else:
            new_start = start_nid
        if end_prefix and end_prefix in id_remap:
            new_end = id_remap[end_prefix] + end_nid[len(end_prefix):]
        else:
            new_end = end_nid

        if new_start in net.nodes and new_end in net.nodes:
            new_lid = f"merge_{old_lid}"
            if new_lid not in net.lines:
                sn = net.nodes[new_start]
                en = net.nodes[new_end]
                from mesh_mobility.engine.network import vincenty_m
                net.lines[new_lid] = Line(
                    line_id=new_lid, start_node=sn, end_node=en,
                    length_m=vincenty_m(sn.lat, sn.lon, en.lat, en.lon),
                    coordinates=old_line.coordinates,
                )

    net.build()

    noelle_log("network_merge", {
        "source": os.path.basename(path) if path else "pasted",
        "added": len(added),
        "skipped_duplicate": len(skipped),
    })

    return jsonify({
        "added": len(added),
        "skipped_duplicate": len(skipped),
        "added_ids": added,
        "id_remap": id_remap,
    })


@network_io_bp.get("/network/download")
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


@network_io_bp.post("/network/new")
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


@network_io_bp.post("/network/reload")
def reload_network():
    """Re-read the current network file without restarting the server.

    Equivalent to the SketchUp Reload Plugin button for MeshMobility.
    The developer edits a .jpd or map.json file, then clicks Reload Network
    in the GUI -- this is the tool boundary for the process capture cycle.
    """
    path = _state.get("network_path")
    if not path:
        return jsonify({"error": "No network path on record -- load a file first"}), 400
    try:
        path = _validate_path(path, "read")
    except ValueError as e:
        return jsonify({"error": str(e)}), 403
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

    # Clear old simulation results -- they are stale after a file change
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

    # Capture the reload event -- this is the tool boundary
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


# ---------------------------------------------------------------------------
# File upload (browser sends file content as text)
# ---------------------------------------------------------------------------

@network_io_bp.post("/network/load_text")
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


@network_io_bp.post("/network/merge_text")
def merge_network_text():
    """Merge a pasted network INTO the current network (add, don't replace).

    Body:
      content   -- .jpd file text
      mode      -- "world" (default): keep original lat/lon
                   "center": shift to center_lat/center_lon
      center_lat, center_lon -- target center when mode="center"
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

    # Build ID mapping: old_id -> new_id (avoid collisions)
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
        # Don't reconnect CPs -- leave them open for manual connection
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


@network_io_bp.post("/network/load_suggestion")
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
# Drawn lines persistence
# ---------------------------------------------------------------------------

@network_io_bp.post("/network/save_drawn_lines")
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


@network_io_bp.get("/network/drawn_lines")
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
