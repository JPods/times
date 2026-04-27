#!/usr/bin/env python3
"""
convert_jpd.py — Convert legacy Java Route-Time .jpd files to the new
Route-Time GUI format (with StructureMeta).

The old format stores raw Switches/Stations/Lines/Groups.
The new format requires a StructureMeta block that encodes Structure and
ConnectionPoint objects — enabling interactive editing in the browser GUI.

Conversion strategy
-------------------
1. Read old XML: parse Switches, Stations, Lines, and Groups.
2. From Groups:
   - <tmpl> elements identify station clusters (6 SW nodes + 1 ST node each).
   - <Circle> elements identify traffic circles (C1-C4 diverge corners,
     D1-D4 merge corners).
3. Infer center lat/lon and heading_deg from the old node positions.
4. Rebuild the network from scratch using build_station() and
   build_traffic_circle() — these create nodes with the correct naming
   convention and internal topology.
5. Detect inter-structure connectivity from old cross-structure lines.
   Match each connection to the geographically nearest unconnected CP pair.
6. Save the new network with StructureMeta using save_jpd().

Usage
-----
    cd /Users/williamjames/Documents/08_JPods/03_Technology
    python3 -m route_time.convert_jpd <input.jpd> [output.jpd]

    # or directly:
    python3 route_time/convert_jpd.py /Applications/RouteTime_JPods/2mi_oneSide.jpd

Output defaults to <stem>_new.jpd in the same directory as input.
"""

from __future__ import annotations

import math
import os
import sys
from typing import Dict, List, Optional, Tuple

from lxml import etree

# ---------------------------------------------------------------------------
# Path setup — allow running as script or as module
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)   # .../03_Technology
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from route_time.engine.network import Network, vincenty_m
from route_time.engine.structures import (
    ConnectionPoint, Structure,
    build_station, build_traffic_circle, connect_cps,
)
from route_time.io.jpd_writer import save_jpd


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True bearing from (lat1,lon1) to (lat2,lon2), 0=north, clockwise."""
    dlon = math.radians(lon2 - lon1)
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    x = math.sin(dlon) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r)
         - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _centroid(pts: List[Tuple[float, float]]) -> Tuple[float, float]:
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _snap45(angle: float) -> float:
    """Snap angle to nearest 45° increment."""
    return round(angle / 45) * 45 % 360


# ---------------------------------------------------------------------------
# Load the old .jpd
# ---------------------------------------------------------------------------

def _load_old(path: str):
    """
    Parse a legacy .jpd and return:
      nodes      : {id → (lat, lon, is_station)}
      old_lines  : [(start_id, end_id, tcId_or_None)]
      templates  : {tmpl_id → [node_id, ...]}   — station clusters
      circles    : {circle_id → {"C": [c1..c4], "D": [d1..d4]}}
    """
    parser = etree.XMLParser(recover=True)
    root = etree.parse(path, parser).getroot()

    nodes: Dict[str, Tuple[float, float, bool]] = {}
    for sw in root.findall(".//Switch"):
        nid = sw.get("ID")
        nodes[nid] = (float(sw.get("lat", 0)), float(sw.get("lon", 0)), False)
    for st in root.findall(".//Station"):
        nid = st.get("ID")
        nodes[nid] = (float(st.get("lat", 0)), float(st.get("lon", 0)), True)

    old_lines = []
    for ln in root.findall(".//line"):
        old_lines.append((
            ln.get("startNodeId"),
            ln.get("endNodeId"),
            ln.get("tcId"),          # None for cross-structure lines
        ))

    templates: Dict[str, List[str]] = {}
    circles: Dict[str, Dict] = {}
    for tmpl in root.findall(".//tmpl"):
        tid = tmpl.get("ID")
        ids = [x for x in tmpl.get("idList", "").split(",") if x]
        templates[tid] = ids

    for circ in root.findall(".//Circle"):
        cid = circ.get("ID")
        circles[cid] = {
            "C": [circ.get(f"C{i}") for i in range(1, 5)],
            "D": [circ.get(f"D{i}") for i in range(1, 5)],
        }

    return nodes, old_lines, templates, circles


# ---------------------------------------------------------------------------
# Infer station heading
# ---------------------------------------------------------------------------

def _station_heading(st_lat: float, st_lon: float,
                     sw_ids: List[str],
                     nodes: Dict) -> float:
    """
    Estimate the NB travel direction for a station.

    Strategy: split SW nodes into "north half" and "south half" by
    latitude relative to the ST node.  NB direction = bearing from the
    south-half centroid to the north-half centroid.

    Falls back to 0° (north-south) if the geometry is degenerate.
    """
    pts = [(nodes[n][0], nodes[n][1])
           for n in sw_ids if n in nodes]
    if len(pts) < 2:
        return 0.0

    north = [(la, lo) for la, lo in pts if la > st_lat]
    south = [(la, lo) for la, lo in pts if la <= st_lat]

    if north and south:
        nc = _centroid(north)
        sc = _centroid(south)
    elif north:
        nc = _centroid(north)
        sc = (st_lat, st_lon)
    else:
        sc = _centroid(south)
        nc = (st_lat, st_lon)

    raw = _bearing(sc[0], sc[1], nc[0], nc[1])
    return _snap45(raw)


# ---------------------------------------------------------------------------
# Infer circle arm headings
# ---------------------------------------------------------------------------

def _circle_arm_headings(circ_data: Dict, nodes: Dict,
                         clat: float, clon: float) -> List[float]:
    """
    Derive 4 arm headings from the C1-C4 diverge corner nodes.
    Each Ci sits at the ring edge on one arm; its bearing from the centre
    gives the outward arm heading, snapped to 45°.
    Falls back gracefully if nodes are missing.
    """
    headings = []
    for cid in circ_data["C"]:
        if cid and cid in nodes:
            n = nodes[cid]
            h = _snap45(_bearing(clat, clon, n[0], n[1]))
            headings.append(h)
        else:
            headings.append(float(len(headings) * 90))  # fallback

    # Deduplicate / ensure we have exactly 4
    seen = []
    for h in headings:
        if h not in seen:
            seen.append(h)
    while len(seen) < 4:
        seen.append((seen[-1] + 90) % 360)
    return seen[:4]


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(input_path: str, output_path: Optional[str] = None) -> str:
    """
    Convert a legacy .jpd to the new format.
    Returns the output path.
    """
    if output_path is None:
        stem = os.path.splitext(input_path)[0]
        output_path = stem + "_new.jpd"

    print(f"\n{'='*60}")
    print(f"Input : {input_path}")
    print(f"Output: {output_path}")
    print(f"{'='*60}")

    nodes, old_lines, templates, circles = _load_old(input_path)
    print(f"  Old nodes    : {len(nodes)}")
    print(f"  Old lines    : {len(old_lines)}")
    print(f"  Station tmpls: {len(templates)}")
    print(f"  Circles      : {len(circles)}")

    net_id = os.path.splitext(os.path.basename(input_path))[0]
    net = Network(network_id=net_id)
    structures: Dict[str, Structure] = {}
    cps: Dict[str, ConnectionPoint] = {}

    # Map old node_id → new structure_id (for connectivity detection)
    node_to_struct: Dict[str, str] = {}

    # ----------------------------------------------------------------
    # 1. Build traffic circles
    # ----------------------------------------------------------------
    print("\n--- Traffic Circles ---")
    for circ_id, circ_data in circles.items():
        all_ids = [n for n in circ_data["C"] + circ_data["D"] if n]
        pts = [(nodes[n][0], nodes[n][1]) for n in all_ids if n in nodes]
        if not pts:
            print(f"  SKIP {circ_id}: no valid nodes")
            continue

        clat, clon = _centroid(pts)
        arms = _circle_arm_headings(circ_data, nodes, clat, clon)

        struct, cp_dict = build_traffic_circle(net, clat, clon,
                                               arm_headings=arms)
        structures[struct.structure_id] = struct
        cps.update(cp_dict)
        for nid in all_ids:
            node_to_struct[nid] = struct.structure_id

        print(f"  {circ_id} → {struct.structure_id}  "
              f"({clat:.5f}, {clon:.5f})  arms={arms}")

    # ----------------------------------------------------------------
    # 2. Build stations
    # ----------------------------------------------------------------
    print("\n--- Stations ---")
    for tmpl_id, id_list in templates.items():
        st_ids = [n for n in id_list if n in nodes and nodes[n][2]]
        sw_ids = [n for n in id_list if n in nodes and not nodes[n][2]]

        if not st_ids:
            print(f"  SKIP {tmpl_id}: no ST node found")
            continue

        st_nid = st_ids[0]
        st_lat, st_lon, _ = nodes[st_nid]
        heading = _station_heading(st_lat, st_lon, sw_ids, nodes)

        struct, cp_dict = build_station(net, st_lat, st_lon,
                                        heading_deg=heading)
        structures[struct.structure_id] = struct
        cps.update(cp_dict)
        for nid in id_list:
            node_to_struct[nid] = struct.structure_id

        print(f"  {tmpl_id} ({st_nid}) → {struct.structure_id}  "
              f"({st_lat:.5f}, {st_lon:.5f})  hdg={heading}°")

    # ----------------------------------------------------------------
    # 3. Detect inter-structure connections
    # ----------------------------------------------------------------
    # Lines that cross structure boundaries indicate CP-to-CP connections.
    # Count how many old lines cross each pair — then connect that many
    # CP pairs (using geographic nearest-first matching).

    pair_count: Dict[Tuple[str, str], int] = {}
    for start_id, end_id, tc_id in old_lines:
        sa = node_to_struct.get(start_id)
        ea = node_to_struct.get(end_id)
        if sa and ea and sa != ea:
            key = tuple(sorted([sa, ea]))
            pair_count[key] = pair_count.get(key, 0) + 1

    print(f"\n--- Connectivity ({len(pair_count)} structure pairs) ---")

    # Each CP pair uses 2 old lines (A→B and B→A), so connections ≈ count//2.
    # We connect min(count//2, available_cp_slots) times per pair.

    def _closest_cp_pair(struct_a, struct_b):
        """Return (cp_a, cp_b) with shortest center distance, both unconnected."""
        best_dist = float("inf")
        best = None
        for cpa_id in struct_a.cp_ids:
            cpa = cps.get(cpa_id)
            if not cpa or cpa.connected_to is not None:
                continue
            for cpb_id in struct_b.cp_ids:
                cpb = cps.get(cpb_id)
                if not cpb or cpb.connected_to is not None:
                    continue
                d = vincenty_m(cpa.center_lat, cpa.center_lon,
                               cpb.center_lat, cpb.center_lon)
                if d < best_dist:
                    best_dist = d
                    best = (cpa, cpb, d)
        return best

    connected_count = 0
    for (sa_id, sb_id), line_count in sorted(pair_count.items(),
                                              key=lambda x: -x[1]):
        sa = structures.get(sa_id)
        sb = structures.get(sb_id)
        if not sa or not sb:
            continue
        # How many CP connections to make for this pair
        n_connections = max(1, line_count // 2)
        for _ in range(n_connections):
            best = _closest_cp_pair(sa, sb)
            if not best:
                break
            cpa, cpb, dist = best
            connect_cps(net, cpa, cpb, cps)
            connected_count += 1
            print(f"  {cpa.cp_id} ↔ {cpb.cp_id}  ({dist:.0f} m)")

    # ----------------------------------------------------------------
    # 4. Report & save
    # ----------------------------------------------------------------
    n_st  = sum(1 for s in structures.values() if s.structure_type == "station")
    n_tc  = sum(1 for s in structures.values() if s.structure_type == "traffic_circle")
    n_con = sum(1 for cp in cps.values() if cp.connected_to) // 2

    print(f"\n--- Summary ---")
    print(f"  Stations      : {n_st}")
    print(f"  Traffic circles: {n_tc}")
    print(f"  CPs total     : {len(cps)}")
    print(f"  CP pairs connected: {n_con}")
    print(f"  Nodes in new net: {len(net.nodes)}")
    print(f"  Lines in new net: {len(net.lines)}")

    save_jpd(net, output_path, structures=structures, cps=cps)
    print(f"\nSaved → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Batch conversion
# ---------------------------------------------------------------------------

def convert_all(source_dir: str, dest_dir: str):
    """Convert every .jpd in source_dir, write results to dest_dir."""
    os.makedirs(dest_dir, exist_ok=True)
    files = sorted(f for f in os.listdir(source_dir) if f.endswith(".jpd"))
    print(f"Found {len(files)} .jpd files in {source_dir}")
    ok, fail = [], []
    for fname in files:
        src = os.path.join(source_dir, fname)
        dst = os.path.join(dest_dir, fname)
        try:
            convert(src, dst)
            ok.append(fname)
        except Exception as exc:
            print(f"\n  ERROR converting {fname}: {exc}")
            fail.append((fname, str(exc)))

    print(f"\n{'='*60}")
    print(f"Batch done: {len(ok)} ok, {len(fail)} failed")
    if fail:
        print("Failures:")
        for fname, err in fail:
            print(f"  {fname}: {err}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Convert legacy JPods .jpd files to new Route-Time GUI format"
    )
    parser.add_argument("input", nargs="?",
                        help="Single .jpd file to convert")
    parser.add_argument("output", nargs="?",
                        help="Output path (default: <stem>_new.jpd beside input)")
    parser.add_argument("--all", metavar="SOURCE_DIR",
                        help="Batch-convert all .jpd in SOURCE_DIR")
    parser.add_argument("--dest", metavar="DEST_DIR",
                        default="/Applications/RouteTime_JPods/converted",
                        help="Destination directory for --all (default: %(default)s)")
    args = parser.parse_args()

    if args.all:
        convert_all(args.all, args.dest)
    elif args.input:
        convert(args.input, args.output)
    else:
        parser.print_help()
