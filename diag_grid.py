"""
diag_grid.py — Diagnose grid mesh routing

Builds a 3×3 grid programmatically (bypassing Flask), then runs Dijkstra between
every pair of adjacent stations and prints:
  - route line count
  - route distance (m)
  - expected direct distance (m)
  - ratio: actual / expected  (>3× = likely routing the long way)

Run from:
  cd /Users/williamjames/Documents/08_JPods/03_Technology
  python3 -m route_time.diag_grid
"""

from __future__ import annotations
import math
from typing import Dict, List, Tuple

from route_time.engine.network import Network, configure_jam_threshold
from route_time.engine.structures import build_traffic_circle, build_station, connect_cps
from route_time.engine.routing import find_path

_MI_TO_M = 1609.344


def _offset(lat, lon, heading_deg, distance_m):
    dlat = distance_m / 111_320.0
    dlon = distance_m / (111_320.0 * math.cos(math.radians(lat)))
    rad = math.radians(heading_deg)
    return lat + dlat * math.cos(rad), lon + dlon * math.sin(rad)


def _cp_by_heading(cp_dict, target):
    best, best_diff = None, float("inf")
    for cp in cp_dict.values():
        diff = abs((cp.heading_deg - target + 180) % 360 - 180)
        if diff < best_diff:
            best_diff = diff
            best = cp
    return best


def build_grid(center_lat=37.31, center_lon=-121.87,
               spacing_ns=1.0, spacing_ew=1.0,
               n_rows=3, n_cols=3):
    """Build a grid network and return (net, grid, ns_stations, ew_stations)."""
    net = Network(network_id="diag_grid")
    cps_state: dict = {}
    structs: dict = {}

    dlat_per_m = 1.0 / 111_320.0
    dlon_per_m = 1.0 / (111_320.0 * math.cos(math.radians(center_lat)))
    ns_m = spacing_ns * _MI_TO_M
    ew_m = spacing_ew * _MI_TO_M
    dlat = ns_m * dlat_per_m
    dlon = ew_m * dlon_per_m

    start_lat = center_lat + dlat * (n_rows - 1) / 2.0
    start_lon = center_lon - dlon * (n_cols - 1) / 2.0

    # ── 1. Traffic circles ────────────────────────────────────────────────────
    grid: List[List] = []
    for r in range(n_rows):
        row = []
        for c in range(n_cols):
            lat = start_lat - r * dlat
            lon = start_lon + c * dlon
            struct, cp_dict = build_traffic_circle(
                net, lat, lon, arm_headings=[0.0, 90.0, 180.0, 270.0]
            )
            structs[struct.structure_id] = struct
            cps_state.update(cp_dict)
            row.append((struct, cp_dict))
        grid.append(row)

    ns_stations = []  # (r, c, station_id, st_cps)
    ew_stations = []

    # ── 2. N-S stations ───────────────────────────────────────────────────────
    for r in range(n_rows - 1):
        for c in range(n_cols):
            lat = start_lat - (r + 0.5) * dlat
            lon = start_lon + c * dlon
            st, st_cps = build_station(net, lat, lon, heading_deg=0.0)
            structs[st.structure_id] = st
            cps_state.update(st_cps)
            ns_stations.append((r, c, st.structure_id, st_cps))

            _, cp_dict_north = grid[r][c]
            tc_south = _cp_by_heading(cp_dict_north, 180.0)
            st_north = st_cps.get(f"{st.structure_id}.CP_N")
            if tc_south and st_north and not tc_south.connected_to and not st_north.connected_to:
                connect_cps(net, tc_south, st_north, cps_state)

            _, cp_dict_south = grid[r + 1][c]
            tc_north = _cp_by_heading(cp_dict_south, 0.0)
            st_south = st_cps.get(f"{st.structure_id}.CP_S")
            if tc_north and st_south and not tc_north.connected_to and not st_south.connected_to:
                connect_cps(net, st_south, tc_north, cps_state)

    # ── 3. E-W stations ───────────────────────────────────────────────────────
    for r in range(n_rows):
        for c in range(n_cols - 1):
            lat = start_lat - r * dlat
            lon = start_lon + (c + 0.5) * dlon
            st, st_cps = build_station(net, lat, lon, heading_deg=90.0)
            structs[st.structure_id] = st
            cps_state.update(st_cps)
            ew_stations.append((r, c, st.structure_id, st_cps))

            _, cp_dict_west = grid[r][c]
            tc_east = _cp_by_heading(cp_dict_west, 90.0)
            st_west = st_cps.get(f"{st.structure_id}.CP_S")
            if tc_east and st_west and not tc_east.connected_to and not st_west.connected_to:
                connect_cps(net, tc_east, st_west, cps_state)

            _, cp_dict_east = grid[r][c + 1]
            tc_west = _cp_by_heading(cp_dict_east, 270.0)
            st_east = st_cps.get(f"{st.structure_id}.CP_N")
            if tc_west and st_east and not tc_west.connected_to and not st_east.connected_to:
                connect_cps(net, st_east, tc_west, cps_state)

    net.build()
    return net, grid, ns_stations, ew_stations, dlat, dlon


def _station_platform(net, sid):
    """Return the PLATFORM node for a station structure."""
    pid = f"{sid}.PLATFORM"
    return net.nodes.get(pid)


def _direct_dist_m(net, sid_a, sid_b, dlat_deg, dlon_deg):
    """Straight-line geographic distance between two station PLATFORM nodes."""
    a = _station_platform(net, sid_a)
    b = _station_platform(net, sid_b)
    if not a or not b:
        return None
    import math
    d_lat = (b.lat - a.lat) * 111_320.0
    d_lon = (b.lon - a.lon) * 111_320.0 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.sqrt(d_lat ** 2 + d_lon ** 2)


def main():
    SPACING = 1.0   # miles per block
    N_ROWS, N_COLS = 3, 3

    print(f"\n=== Grid diagnostic: {N_ROWS}×{N_COLS} grid, {SPACING}-mile blocks ===\n")

    net, grid, ns_stns, ew_stns, dlat, dlon = build_grid(
        spacing_ns=SPACING, spacing_ew=SPACING,
        n_rows=N_ROWS, n_cols=N_COLS
    )

    block_m = SPACING * _MI_TO_M
    ok = 0
    warn = 0

    def check(label, sid_a, sid_b, expected_m):
        nonlocal ok, warn
        a_node = _station_platform(net, sid_a)
        b_node = _station_platform(net, sid_b)
        if not a_node or not b_node:
            print(f"  MISSING PLATFORM  {label}")
            return

        route = find_path(net, a_node, b_node)
        if not route:
            print(f"  NO PATH  {label}  {sid_a} → {sid_b}")
            warn += 1
            return

        route_m = sum(ln.length_m for ln in route)
        ratio   = route_m / expected_m if expected_m else 0
        flag    = "  ✓" if ratio < 3.0 else "  ⚠ LONG ROUTE"
        if ratio >= 3.0:
            warn += 1
            # Show first few and last few line IDs for inspection
            ids = [ln.line_id for ln in route]
            snippet = ids[:3] + (["..."] if len(ids) > 6 else []) + ids[-3:]
            print(f"{flag} {label}  lines={len(route)}  "
                  f"route={route_m:.0f}m  expected≈{expected_m:.0f}m  "
                  f"ratio={ratio:.1f}×\n"
                  f"       route: {snippet}")
        else:
            ok += 1
            print(f"{flag} {label}  lines={len(route)}  "
                  f"route={route_m:.0f}m  expected≈{expected_m:.0f}m  ratio={ratio:.1f}×")

    print("── N-S adjacent station pairs (one block apart, same column) ──")
    # ns_stns is ordered col-major — group by column first, then sort by row.
    from collections import defaultdict
    ns_by_col: dict = defaultdict(list)
    for r, c, sid, cps in ns_stns:
        ns_by_col[c].append((r, c, sid, cps))

    for col in sorted(ns_by_col):
        col_stns = sorted(ns_by_col[col], key=lambda x: x[0])
        for i in range(len(col_stns) - 1):
            r_a, c_a, sid_a, _ = col_stns[i]
            r_b, c_b, sid_b, _ = col_stns[i + 1]
            label = f"NS({r_a},{c_a})→NS({r_b},{c_b})"
            check(label, sid_a, sid_b, expected_m=block_m)
            check(f"NS({r_b},{c_b})→NS({r_a},{c_a})", sid_b, sid_a, expected_m=block_m)

    print("\n── E-W adjacent station pairs (one block apart, same row) ──")
    for i in range(len(ew_stns) - 1):
        r_a, c_a, sid_a, _ = ew_stns[i]
        r_b, c_b, sid_b, _ = ew_stns[i + 1]
        if r_a != r_b:
            continue  # different rows
        label = f"EW({r_a},{c_a})→EW({r_a},{c_b})"
        check(label, sid_a, sid_b, expected_m=block_m)
        check(f"EW({r_a},{c_b})→EW({r_a},{c_a})", sid_b, sid_a, expected_m=block_m)

    print("\n── Cross-type pairs (N-S station → E-W station at same intersection) ──")
    # For each row r and column c, there is a circle at grid[r][c].
    # The N-S station at (r,c) and the E-W station at (r,c) are at the same circle.
    for r_ns, c_ns, sid_ns, _ in ns_stns:
        for r_ew, c_ew, sid_ew, _ in ew_stns:
            # N-S station between rows r_ns and r_ns+1 in column c_ns
            # E-W station between cols c_ew and c_ew+1 in row r_ew
            # They share a circle if one is adjacent — skip for now (complex geometry)
            pass

    print(f"\nSummary: {ok} OK, {warn} warnings")

    if warn:
        print("\nTroubleshoot: long routes indicate a guideway connection is reversed")
        print("or a circle arm was matched to the wrong heading.")
        print("Check the ⚠ routes — the line IDs reveal which circle arm is wrong.")


if __name__ == "__main__":
    main()
