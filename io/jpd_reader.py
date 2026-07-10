"""
mesh_mobility.io.jpd_reader
========================
Parse a .jpd file into a Network.

Supports two formats (auto-detected by first non-whitespace byte):

JSON (version 2 — current):
  {
    "format": "jpd", "version": 2, "network_id": "...",
    "settings": {...},
    "switches":   [{"id","lat","lon"}, ...],
    "stations":   [{"id","lat","lon"}, ...],
    "lines":      [{"id","start","end","coordinates":[[lat,lon],...]},...],
    "structures": [...],
    "cps":        [...]
  }

XML (version 1 — legacy Java format, read-only):
  <network id="..." ver="...">
    <Switches> <Switch ID="SWn" lat="..." lon="..." /> </Switches>
    <stations> <Station ID="STn" lat="..." lon="..." /> </stations>
    <Lines>
      <line ID="Ln" startNodeId="SWx" endNodeId="SWy">
        <Coordinate lat="..." lon="..." />
      </line>
    </Lines>
    <StructureMeta>{"structures":[...],"cps":[...]}</StructureMeta>
  </network>
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from ..engine.network import Line, Network, Node, Station, vincenty_m


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load(path: str, network_id: Optional[str] = None
         ) -> Tuple[Network, List[dict], List[dict], Dict]:
    """
    Parse a .jpd file and return (Network, structures_data, cps_data, settings).

    structures_data / cps_data are lists of dicts from Structure/CP .to_dict().
    settings is a dict of simulation settings (empty for legacy XML files).
    All three are empty for legacy files that pre-date the modern schema.

    network_id defaults to the filename without extension.
    """
    if network_id is None:
        network_id = os.path.splitext(os.path.basename(path))[0]

    with open(path, "rb") as f:
        first = f.read(1)

    if first == b"{":
        return _load_json(path, network_id)
    else:
        return _load_xml(path, network_id)


# ---------------------------------------------------------------------------
# JSON loader (version 2 — current format)
# ---------------------------------------------------------------------------

def _load_json(path: str, network_id: str
               ) -> Tuple[Network, List[dict], List[dict], Dict]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    nid = raw.get("network_id", network_id)
    net = Network(network_id=nid)

    for sw in raw.get("switches", []):
        nid_ = sw["id"]
        node = Node(node_id=nid_, lat=float(sw["lat"]), lon=float(sw["lon"]),
                    is_station=False)
        net.nodes[nid_] = node

    for st in raw.get("stations", []):
        nid_ = st["id"]
        node = Node(node_id=nid_, lat=float(st["lat"]), lon=float(st["lon"]),
                    is_station=True)
        net.nodes[nid_] = node
        net.stations[nid_] = Station(station_id=nid_, node=node)

    for ln in raw.get("lines", []):
        lid      = ln["id"]
        start_id = ln["start"]
        end_id   = ln["end"]
        if start_id not in net.nodes or end_id not in net.nodes:
            continue  # dangling reference — skip
        coords = [(float(c[0]), float(c[1])) for c in ln.get("coordinates", [])]
        length_m = _chain_length(coords)
        if length_m == 0:
            sn = net.nodes[start_id]
            en = net.nodes[end_id]
            length_m = vincenty_m(sn.lat, sn.lon, en.lat, en.lon)
        net.lines[lid] = Line(
            line_id=lid,
            start_node=net.nodes[start_id],
            end_node=net.nodes[end_id],
            length_m=length_m,
            coordinates=coords,
        )

    net.build()

    structures_data = raw.get("structures", [])
    cps_data        = raw.get("cps", [])
    settings        = raw.get("settings", {})
    overlays        = raw.get("overlays")

    # Restore embedded overlay data to active files
    overlay_data = raw.get("overlay_data")
    if overlay_data:
        import os
        rt_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        overlay_dir = os.path.join(rt_dir, "overlays")
        for prefix, geojson in overlay_data.items():
            dst = os.path.join(overlay_dir, f"{prefix}.geojson")
            with open(dst, "w") as f:
                json.dump(geojson, f)
    elif not overlays:
        # Legacy .jpd with no overlay data — try to match by centroid
        overlays = _detect_city_from_network(net, raw)

    # Restore QA if present
    qa = raw.get("qa")

    return net, structures_data, cps_data, settings, overlays, qa


def _detect_city_from_network(net, raw):
    """Detect which city overlay files to use from network coordinates.

    Reads station positions, computes centroid, matches against available
    overlay files by checking which city's AADT data contains points
    nearest the centroid. Returns overlays dict or None.
    """
    import os

    # Get centroid from structures or nodes
    lats, lons = [], []
    for s in raw.get("structures", []):
        lat = s.get("center_lat")
        lon = s.get("center_lon")
        if lat and lon:
            lats.append(lat)
            lons.append(lon)
    if not lats:
        for n in list(raw.get("stations", [])) + list(raw.get("switches", [])):
            if "lat" in n and "lon" in n:
                lats.append(n["lat"])
                lons.append(n["lon"])
    if not lats:
        return None

    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    # Check available city overlay files
    rt_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    overlay_dir = os.path.join(rt_dir, "overlays")
    if not os.path.isdir(overlay_dir):
        return None

    # Find city keys from aadt_*.geojson files
    cities = set()
    for fname in os.listdir(overlay_dir):
        if fname.startswith("aadt_") and fname.endswith(".geojson"):
            cities.add(fname[5:-8])

    # For each city, load AADT and compute centroid distance
    import math
    best_city = None
    best_dist = float("inf")
    for city in cities:
        aadt_path = os.path.join(overlay_dir, f"aadt_{city}.geojson")
        try:
            with open(aadt_path) as f:
                geo = json.load(f)
            clats = [feat["geometry"]["coordinates"][1]
                     for feat in geo.get("features", [])[:50]]
            clons = [feat["geometry"]["coordinates"][0]
                     for feat in geo.get("features", [])[:50]]
            if not clats:
                continue
            clat = sum(clats) / len(clats)
            clon = sum(clons) / len(clons)
            dist = math.sqrt((center_lat - clat)**2 + (center_lon - clon)**2)
            if dist < best_dist:
                best_dist = dist
                best_city = city
        except Exception:
            continue

    # Match if within ~1 degree (~100km)
    if best_city and best_dist < 1.0:
        import shutil
        switched = []
        for prefix in ("aadt", "accidents", "crash_density", "population_density", "property_values", "jobs"):
            src = os.path.join(overlay_dir, f"{prefix}_{best_city}.geojson")
            dst = os.path.join(overlay_dir, f"{prefix}.geojson")
            if os.path.exists(src):
                shutil.copy2(src, dst)
                switched.append(prefix)
        return {"city": best_city, "files": switched,
                "auto_detected": True}

    return None


# ---------------------------------------------------------------------------
# XML loader (version 1 — legacy Java format, read-only)
# ---------------------------------------------------------------------------

def _load_xml(path: str, network_id: str
              ) -> Tuple[Network, List[dict], List[dict], Dict]:
    from lxml import etree

    parser = etree.XMLParser(recover=True)
    tree   = etree.parse(path, parser)
    root   = tree.getroot()

    net = Network(network_id=network_id)

    for sw in root.findall(".//Switch"):
        nid  = sw.get("ID")
        node = Node(node_id=nid, lat=float(sw.get("lat", 0)),
                    lon=float(sw.get("lon", 0)), is_station=False)
        net.nodes[nid] = node

    for st in root.findall(".//Station"):
        nid  = st.get("ID")
        node = Node(node_id=nid, lat=float(st.get("lat", 0)),
                    lon=float(st.get("lon", 0)), is_station=True)
        net.nodes[nid] = node
        net.stations[nid] = Station(station_id=nid, node=node)

    for ln in root.findall(".//line"):
        lid      = ln.get("ID")
        start_id = ln.get("startNodeId")
        end_id   = ln.get("endNodeId")
        if start_id not in net.nodes or end_id not in net.nodes:
            continue
        coords = [
            (float(c.get("lat")), float(c.get("lon")))
            for c in ln.findall("Coordinate")
        ]
        length_m = _chain_length(coords)
        if length_m == 0:
            sn = net.nodes[start_id]
            en = net.nodes[end_id]
            length_m = vincenty_m(sn.lat, sn.lon, en.lat, en.lon)
        net.lines[lid] = Line(
            line_id=lid,
            start_node=net.nodes[start_id],
            end_node=net.nodes[end_id],
            length_m=length_m,
            coordinates=coords,
        )

    net.build()

    structures_data: List[dict] = []
    cps_data:        List[dict] = []
    meta_el = root.find("StructureMeta")
    if meta_el is not None and meta_el.text:
        try:
            meta = json.loads(meta_el.text)
            structures_data = meta.get("structures", [])
            cps_data        = meta.get("cps", [])
        except Exception:
            pass

    return net, structures_data, cps_data, {}, None, None  # legacy: no settings/overlays/qa


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _chain_length(coords: list) -> float:
    """Sum of vincenty distances along a coordinate chain."""
    total = 0.0
    for i in range(len(coords) - 1):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[i + 1]
        total += vincenty_m(lat1, lon1, lat2, lon2)
    return total
