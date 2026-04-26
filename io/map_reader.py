"""
route_time.io.map_reader
========================
Parse a SketchUp-generated map.json (podPresenter format) into a Network.

map.json schema (podPresenter):
  {
    "mapId": 1,
    "lines": [
      {
        "id": 1,
        "startPoint": {"id": "EP1", "x": ..., "y": ...},
        "endPoint":   {"id": "EP2", "x": ..., "y": ...},
        "length": 836,   ← in mm
        "segments": [
          {"xs": ..., "ys": ..., "xe": ..., "ye": ...,
           "len": ..., "lenCum": ..., "radius": ...},
          ...
        ]
      },
      ...
    ],
    "ezones": [...],
    "markers": [...],
    "dead_end_nodes": [...]
  }

Coordinates in map.json are local mm (not lat/lon).
Route-Time uses length_m for Dijkstra weights; we convert mm → m.
Nodes are synthesized from endpoint IDs.

For the SketchUp new format (network.json / seg_NNNNNN IDs):
  connections[].id = segment id (used as line_id)
  from/to = {structure_id, stub}
  These are topology-only; length must be derived from build output.
  Use the generated map.json (Build Network output) when available.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from ..engine.network import Line, Network, Node, Station


def load_podpresenter(path: str, network_id: Optional[str] = None) -> Network:
    """
    Load a podPresenter-format map.json.
    Coordinates are local mm; converted to metres for length.
    Nodes have no lat/lon — set to 0.0.
    """
    if network_id is None:
        network_id = os.path.splitext(os.path.basename(path))[0]

    with open(path) as f:
        data = json.load(f)

    net = Network(network_id=network_id)

    # Collect all endpoint IDs first
    ep_coords: dict = {}  # ep_id → (x_mm, y_mm)

    for ln in data.get("lines", []):
        sp = ln["startPoint"]
        ep = ln["endPoint"]
        ep_coords[sp["id"]] = (sp.get("x", 0), sp.get("y", 0))
        ep_coords[ep["id"]] = (ep.get("x", 0), ep.get("y", 0))

    # Build nodes
    for ep_id, (x, y) in ep_coords.items():
        node = Node(node_id=ep_id, lat=0.0, lon=0.0, is_station=False)
        # Store local coords in node (reuse lat/lon fields for local space)
        node.lat = float(x)
        node.lon = float(y)
        net.nodes[ep_id] = node

    # Build lines
    for ln in data.get("lines", []):
        lid      = str(ln["id"])
        start_id = ln["startPoint"]["id"]
        end_id   = ln["endPoint"]["id"]
        length_mm = float(ln.get("length", 0))
        length_m  = length_mm / 1000.0

        if start_id not in net.nodes or end_id not in net.nodes:
            continue

        line = Line(
            line_id=lid,
            start_node=net.nodes[start_id],
            end_node=net.nodes[end_id],
            length_m=length_m,
        )
        net.lines[lid] = line

    # Identify station nodes from dead_end_nodes or markers
    # podPresenter does not have explicit station types — caller must mark them.
    # Convention: endpoints that are dead ends are treated as stations.
    dead_ends = set(data.get("dead_end_nodes", []))
    # dead_end_nodes may be strings or objects; normalise
    normalised_dead = set()
    for d in dead_ends:
        if isinstance(d, str):
            normalised_dead.add(d)
        elif isinstance(d, dict):
            # format "S020.CP0" or "EP1"
            normalised_dead.add(d.get("id", ""))

    # Fall back: nodes with only inbound or only outbound links after build
    # are terminal nodes (candidate stations).
    net.build()

    # Mark terminal nodes as stations
    for nid, node in net.nodes.items():
        is_terminal = (not node.outbound) or (not node.inbound)
        if is_terminal or nid in normalised_dead:
            node.is_station = True
            net.stations[nid] = Station(station_id=nid, node=node)

    return net


def load_sketchup_map(path: str, network_id: Optional[str] = None) -> Network:
    """
    Load a SketchUp Build Network output (map.json with nodes/edges format).

    SketchUp map.json schema:
      {
        "nodes": [{"id": "S017", "x": ..., "y": ..., "z": ...}, ...],
        "edges": [{"id": "seg_120211", "from": "S017", "to": "S018",
                   "length_mm": 12345, "track": 0}, ...],
        ...
      }
    If the map.json is in podPresenter format (has "lines" key), delegates
    to load_podpresenter().
    """
    with open(path) as f:
        data = json.load(f)

    # Auto-detect format
    if "lines" in data:
        return load_podpresenter(path, network_id)

    if network_id is None:
        network_id = os.path.splitext(os.path.basename(path))[0]

    net = Network(network_id=network_id)

    for nd in data.get("nodes", []):
        nid = nd["id"]
        node = Node(
            node_id=nid,
            lat=float(nd.get("x", 0)),
            lon=float(nd.get("y", 0)),
        )
        net.nodes[nid] = node

    for ed in data.get("edges", []):
        eid      = ed["id"]
        start_id = ed["from"]
        end_id   = ed["to"]
        length_m = float(ed.get("length_mm", 0)) / 1000.0

        if start_id not in net.nodes or end_id not in net.nodes:
            continue

        line = Line(
            line_id=eid,
            start_node=net.nodes[start_id],
            end_node=net.nodes[end_id],
            length_m=length_m,
        )
        net.lines[eid] = line

    net.build()

    # Terminal nodes → stations
    for nid, node in net.nodes.items():
        if not node.outbound or not node.inbound:
            node.is_station = True
            net.stations[nid] = Station(station_id=nid, node=node)

    return net
