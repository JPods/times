"""
route_time.io.jpd_writer
========================
Serialize a Network back to the .jpd XML format used by the Java Route-Time tool.

Output matches the schema read by jpd_reader.py:
  <network id="..." ver="...">
    <Switches lastID="N"> <Switch ID="..." lat="..." lon="..." /> </Switches>
    <stations lastID="N"> <Station ID="..." lat="..." lon="..." /> </stations>
    <Lines lastID="N">
      <line ID="..." startNodeId="..." endNodeId="...">
        <Coordinate lat="..." lon="..." />
      </line>
    </Lines>
    <Groups lastID="0" />
  </network>
"""

from __future__ import annotations

import json as _json
import time
from typing import Dict, Optional
from xml.etree import ElementTree as ET
from xml.dom import minidom

from ..engine.network import Network


def _build_root(net: Network, structures: Optional[Dict] = None,
                cps: Optional[Dict] = None) -> ET.Element:
    """Build the XML element tree shared by serialise_jpd and save_jpd."""
    root = ET.Element("network", id=net.network_id, ver=str(int(time.time() * 1000)))

    switches = [n for n in net.nodes.values() if n.node_id not in net.stations]
    sw_el = ET.SubElement(root, "Switches", lastID=str(len(switches)))
    for node in switches:
        ET.SubElement(sw_el, "Switch",
                      ID=node.node_id,
                      lat=f"{node.lat:.14f}",
                      lon=f"{node.lon:.14f}")

    st_nodes = [net.nodes[sid] for sid in net.stations if sid in net.nodes]
    st_el = ET.SubElement(root, "stations", lastID=str(len(st_nodes)))
    for node in st_nodes:
        ET.SubElement(st_el, "Station",
                      ID=node.node_id,
                      lat=f"{node.lat:.14f}",
                      lon=f"{node.lon:.14f}")

    ln_el = ET.SubElement(root, "Lines", lastID=str(len(net.lines)))
    for lid, line in net.lines.items():
        el = ET.SubElement(ln_el, "line",
                           ID=lid,
                           startNodeId=line.start_node.node_id,
                           endNodeId=line.end_node.node_id)
        if line.coordinates:
            for lat, lon in line.coordinates:
                ET.SubElement(el, "Coordinate", lat=f"{lat:.14f}", lon=f"{lon:.14f}")
        else:
            ET.SubElement(el, "Coordinate",
                          lat=f"{line.start_node.lat:.14f}",
                          lon=f"{line.start_node.lon:.14f}")
            ET.SubElement(el, "Coordinate",
                          lat=f"{line.end_node.lat:.14f}",
                          lon=f"{line.end_node.lon:.14f}")

    ET.SubElement(root, "Groups", lastID="0")

    # Structure / CP metadata — allows full round-trip through save/load
    if structures or cps:
        meta = {
            "structures": [s.to_dict() for s in (structures or {}).values()],
            "cps":        [c.to_dict() for c in (cps or {}).values()],
        }
        meta_el = ET.SubElement(root, "StructureMeta")
        meta_el.text = _json.dumps(meta, separators=(",", ":"))

    return root


def serialise_jpd(net: Network, structures: Optional[Dict] = None,
                  cps: Optional[Dict] = None) -> bytes:
    """Return the .jpd XML content as UTF-8 bytes (no file I/O)."""
    root = _build_root(net, structures, cps)
    raw  = ET.tostring(root, encoding="unicode")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")


def save_jpd(net: Network, path: str, structures: Optional[Dict] = None,
             cps: Optional[Dict] = None):
    """Write network to a .jpd file."""
    root = _build_root(net, structures, cps)
    raw  = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")
    with open(path, "wb") as f:
        f.write(pretty)


