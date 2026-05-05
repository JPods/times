"""
route_time.io.jpd_writer
========================
Serialize a Network to the .jpd JSON format.

Schema (version 2):
  {
    "format":     "jpd",
    "version":    2,
    "network_id": "...",
    "saved_at":   <unix-ms>,
    "settings":   { ... },          # simulation settings panel state
    "switches":   [{"id","lat","lon"}, ...],
    "stations":   [{"id","lat","lon"}, ...],
    "lines":      [{"id","start","end","coordinates":[[lat,lon],...]},...],
    "structures": [...],            # Structure.to_dict() list
    "cps":        [...]             # ConnectionPoint.to_dict() list
  }

Legacy XML .jpd files are still readable via jpd_reader.py (auto-detected).
"""

from __future__ import annotations

import json
import time
from typing import Dict, Optional

from ..engine.network import Network


def _build_dict(net: Network,
                structures: Optional[Dict] = None,
                cps: Optional[Dict] = None,
                settings: Optional[Dict] = None) -> dict:
    """Build the serialisable dict shared by serialise_jpd and save_jpd."""
    switches = [
        {"id": n.node_id, "lat": n.lat, "lon": n.lon}
        for n in net.nodes.values()
        if n.node_id not in net.stations
    ]
    stations = [
        {"id": n.node_id, "lat": n.lat, "lon": n.lon}
        for n in net.nodes.values()
        if n.node_id in net.stations
    ]
    lines = []
    for lid, line in net.lines.items():
        coords = line.coordinates or [
            [line.start_node.lat, line.start_node.lon],
            [line.end_node.lat,   line.end_node.lon],
        ]
        lines.append({
            "id":          lid,
            "start":       line.start_node.node_id,
            "end":         line.end_node.node_id,
            "coordinates": [[lat, lon] for lat, lon in coords],
        })

    return {
        "format":     "jpd",
        "version":    2,
        "network_id": net.network_id,
        "saved_at":   int(time.time() * 1000),
        "settings":   settings or {},
        "switches":   switches,
        "stations":   stations,
        "lines":      lines,
        "structures": [s.to_dict() for s in (structures or {}).values()],
        "cps":        [c.to_dict() for c in (cps or {}).values()],
    }


def serialise_jpd(net: Network,
                  structures: Optional[Dict] = None,
                  cps: Optional[Dict] = None,
                  settings: Optional[Dict] = None) -> bytes:
    """Return the .jpd JSON content as UTF-8 bytes (no file I/O)."""
    d = _build_dict(net, structures, cps, settings)
    return json.dumps(d, indent=2, ensure_ascii=False).encode("utf-8")


def save_jpd(net: Network, path: str,
             structures: Optional[Dict] = None,
             cps: Optional[Dict] = None,
             settings: Optional[Dict] = None):
    """Write network to a .jpd JSON file."""
    d = _build_dict(net, structures, cps, settings)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
