"""
route_time.io.jpd_reader
========================
Parse a .jpd file (Java XML serialization) into a Network.

.jpd schema:
  <network id="..." ver="...">
    <Switches lastID="N">
      <Switch ID="SWn" lat="..." lon="..." />
    </Switches>
    <stations lastID="N">
      <Station ID="STn" lat="..." lon="..." />
    </stations>
    <Lines lastID="N">
      <line ID="Ln" startNodeId="SWx" endNodeId="SWy">
        <Coordinate lat="..." lon="..." />
        ...
      </line>
    </Lines>
    <Groups lastID="N">
      <tmpl ID="NG-n" idList="SWa,SWb,...,STn," type="template" />
      <Circle ID="NGn" C1="..." C2="..." C3="..." C4="..."
              D1="..." D2="..." D3="..." D4="..." type="cg" />
    </Groups>
  </network>

Node IDs in the .jpd are "SWn" / "STn".
Line IDs are "Ln".
Stations are nodes whose ID starts with "ST".

Length is computed as geodetic distance (Vincenty/haversine) from
the Coordinate chain.
"""

from __future__ import annotations

import os
from typing import Optional

from lxml import etree

from ..engine.network import Line, Network, Node, Station, vincenty_m


def load(path: str, network_id: Optional[str] = None) -> Network:
    """
    Parse a .jpd file and return a Network.

    network_id defaults to the filename without extension.
    """
    if network_id is None:
        network_id = os.path.splitext(os.path.basename(path))[0]

    parser = etree.XMLParser(recover=True)
    tree = etree.parse(path, parser)
    root = tree.getroot()

    net = Network(network_id=network_id)

    # ---- Nodes: Switches ----
    for sw in root.findall(".//Switch"):
        nid  = sw.get("ID")
        lat  = float(sw.get("lat", 0))
        lon  = float(sw.get("lon", 0))
        node = Node(node_id=nid, lat=lat, lon=lon, is_station=False)
        net.nodes[nid] = node

    # ---- Nodes: Stations ----
    for st in root.findall(".//Station"):
        nid  = st.get("ID")
        lat  = float(st.get("lat", 0))
        lon  = float(st.get("lon", 0))
        node = Node(node_id=nid, lat=lat, lon=lon, is_station=True)
        net.nodes[nid] = node
        net.stations[nid] = Station(station_id=nid, node=node)

    # ---- Lines ----
    for ln in root.findall(".//line"):
        lid      = ln.get("ID")
        start_id = ln.get("startNodeId")
        end_id   = ln.get("endNodeId")

        if start_id not in net.nodes or end_id not in net.nodes:
            continue  # dangling reference — skip

        coords = []
        for coord in ln.findall("Coordinate"):
            coords.append((float(coord.get("lat")), float(coord.get("lon"))))

        # Compute length from coordinate chain
        length_m = _chain_length(coords)
        if length_m == 0:
            # Fall back to straight-line between endpoints
            sn = net.nodes[start_id]
            en = net.nodes[end_id]
            length_m = vincenty_m(sn.lat, sn.lon, en.lat, en.lon)

        line = Line(
            line_id=lid,
            start_node=net.nodes[start_id],
            end_node=net.nodes[end_id],
            length_m=length_m,
            coordinates=coords,
        )
        net.lines[lid] = line

    net.build()
    return net


def _chain_length(coords: list) -> float:
    """Sum of haversine distances along a coordinate chain."""
    total = 0.0
    for i in range(len(coords) - 1):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[i + 1]
        total += vincenty_m(lat1, lon1, lat2, lon2)
    return total
