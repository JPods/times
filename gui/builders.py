"""
mesh_mobility.gui.builders
===========================
Network builder endpoints: Line tool, City Mesh, Grid generator, Auto-connect.

These endpoints create stations, traffic circles, and connections from user
actions. Extracted from api.py in Round 2 refactoring (2026-07-15).
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.parse
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

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

from mesh_mobility.engine import Network, Line
from mesh_mobility.engine.network import vincenty_m
from mesh_mobility.engine.structures import (
    build_traffic_circle, build_station, connect_cps, disconnect_cp,
    ConnectionPoint, Structure,
)

# ---------------------------------------------------------------------------
# Overlay data -- reads from CrashHarvester library
# ---------------------------------------------------------------------------
from CrashHarvester.reader import MobilityData
_md = MobilityData()

# ---------------------------------------------------------------------------
# Shared state imports
# ---------------------------------------------------------------------------
from mesh_mobility.gui.state import (
    _state, _net,
    ensure_session, set_session_cookie, auto_push_undo,
    clear_edit_state, next_sid, sync_counters,
    noelle_log, check_overlap,
    cp_by_heading,
)

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
builders = Blueprint("builders", __name__, url_prefix="/api")

# Register session lifecycle hooks (same as api.py)
builders.before_request(ensure_session)
builders.after_request(set_session_cookie)
builders.before_request(auto_push_undo)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MI_TO_M = 1609.344


# ---------------------------------------------------------------------------
# Helper: closest open CP pair between two structures
# ---------------------------------------------------------------------------

def _find_closest_open_pair(struct_a_id: str, struct_b_id: str):
    """Find the closest pair of open CPs between two structures."""
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


# ---------------------------------------------------------------------------
# Line segment intersection helpers
# ---------------------------------------------------------------------------

def _seg_intersect(p1, p2, p3, p4):
    """Return (lat, lon) where segment p1-p2 crosses p3-p4, or None.
    Each point is (lat, lon).  Uses 2D line-segment intersection."""
    x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
    if 0 < t < 1 and 0 < u < 1:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _find_crossings(lat1, lon1, lat2, lon2):
    """Find existing connections that cross the line from (lat1,lon1) to (lat2,lon2).
    Returns list of (intersection_lat, intersection_lon, cp_a, cp_b) where
    cp_a and cp_b are the two CPs of the crossed connection."""
    seen = set()
    crossings = []
    for cp in _state["cps"].values():
        if cp.connected_to is None:
            continue
        pair = tuple(sorted([cp.cp_id, cp.connected_to]))
        if pair in seen:
            continue
        seen.add(pair)
        partner = _state["cps"].get(cp.connected_to)
        if not partner:
            continue
        s_a = _state["structures"].get(cp.structure_id)
        s_b = _state["structures"].get(partner.structure_id)
        if not s_a or not s_b:
            continue
        pt = _seg_intersect(
            (lat1, lon1), (lat2, lon2),
            (s_a.center_lat, s_a.center_lon), (s_b.center_lat, s_b.center_lon),
        )
        if pt:
            crossings.append((pt[0], pt[1], cp, partner))
    return crossings


# ---------------------------------------------------------------------------
# Auto-connect geometry helpers
# ---------------------------------------------------------------------------

_last_autoconnect_skipped: List[str] = []  # cp_ids skipped as outer boundary


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing from point 1 to point 2, degrees [0, 360)."""
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

    Rule 1 -- Direction cone (+/-45 deg):
      The geographic bearing from cp_a to cp_b must lie within 45 deg of
      cp_a's outbound heading.  A north-pointing CP (heading=0) will only
      reach targets in the arc 315 deg--045 deg.

    Rule 2 -- Opposite polarity (+/-45 deg):
      cp_b's outbound heading must be within 45 deg of the reverse of cp_a's
      heading.  North CPs connect to south CPs; NE to SW; E to W; etc.
      Prevents two same-direction stubs from being wired together.
    """
    bearing_a_to_b = _bearing_deg(cp_a.center_lat, cp_a.center_lon,
                                   cp_b.center_lat, cp_b.center_lon)
    # Rule 1 -- cp_b lies inside cp_a's forward cone
    if _angular_diff(bearing_a_to_b, cp_a.heading_deg) > 45:
        return False
    # Rule 2 -- cp_b faces back (opposing polarity)
    opposite_a = (cp_a.heading_deg + 180) % 360
    if _angular_diff(cp_b.heading_deg, opposite_a) > 45:
        return False
    return True


def _max_connect_dist_m(candidates) -> float:
    """
    Maximum allowed connection distance: 1.5x the median nearest-neighbor
    distance between CPs on different structures.

    This limits auto-connect to roughly one structure-span so that a CP
    never leaps over an intermediate structure to reach a more distant one.
    Returns inf when fewer than 2 candidates (no constraint applied).
    """
    import statistics
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
    Uses the dot product of the heading unit vector with the (cp->centroid) vector.
    A negative dot product means the CP faces away from the interior.
    """
    rad = math.radians(cp.heading_deg)
    hx = math.sin(rad)   # east component of heading
    hy = math.cos(rad)   # north component of heading

    # Vector from CP toward centroid (rough flat-earth, fine for local networks)
    dx = centroid_lon - cp.center_lon
    dy = centroid_lat - cp.center_lat

    mag = math.hypot(dx, dy)
    if mag < 1e-9:
        return False   # CP is at the centroid -- treat as inner

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
      - on the convex hull of all CP positions, AND
      - its outbound heading faces away from the network centroid.

    Each CP is matched at most once.  Uses connect_cps() so CP state and
    line_pairs are updated correctly.
    """
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
            continue   # stale CP -- structure was deleted
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
# Auto-connect endpoint
# ---------------------------------------------------------------------------

@builders.post("/network/autoconnect")
def auto_connect():
    """
    Best-effort auto-connection of placed stations and circles.

    Rules:
      1. Operates on CPs (stub-pairs), not raw nodes -- each CP connects once.
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
# City Mesh endpoint
# ---------------------------------------------------------------------------

@builders.post("/network/city_mesh")
def network_city_mesh():
    """Generate a mesh network within a city boundary.

    Auto-detects spacing (1x1 or 1x2 mile) based on city size.
    Queries Overpass API for major road intersections and snaps circles to them.
    Fills the boundary polygon, not a rectangle.
    """
    import urllib.request
    # Lazy import to avoid circular dependency
    from mesh_mobility.gui.overlays import _detect_state
    from CrashHarvester.reader import MobilityData
    _md = MobilityData()

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
    span_ns_mi = vincenty_m(min_lat, center_lon, max_lat, center_lon) / 1609.34
    span_ew_mi = vincenty_m(center_lat, min_lon, center_lat, max_lon) / 1609.34

    # Auto-pick spacing: Noelle's rule
    # Small city (<6 mi): 1x1
    # Medium city: longer axis gets 2 mi spacing, shorter gets 1 mi
    if max(span_ns_mi, span_ew_mi) < 6:
        spacing_ns = 1.0
        spacing_ew = 1.0
        spacing_label = "1\u00d71 mi"
    elif span_ns_mi > span_ew_mi:
        spacing_ns = 2.0
        spacing_ew = 1.0
        spacing_label = "2\u00d71 mi (N-S longer)"
    else:
        spacing_ns = 1.0
        spacing_ew = 2.0
        spacing_label = "1\u00d72 mi (E-W longer)"

    log.info(f"City Mesh: {span_ns_mi:.1f}\u00d7{span_ew_mi:.1f} mi \u2192 {spacing_label}")

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
        # MultiPolygon -- use the largest ring
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
        log.warning(f"City Mesh: Overpass query failed ({e}) -- using grid points directly")

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

    # Filter to urban areas -- only keep grid points near CrashHarvester library data
    urban_pts = []
    state_abbr, _, _ = _detect_state()
    if state_abbr:
        for dtype in ("population_density", "crash", "traffic", "fatal"):
            lib_data = _md.get_census(dtype, state_abbr) if dtype == "population_density" else \
                       _md._get(dtype, state_abbr, None, None, None)
            if lib_data:
                for feat in lib_data.get("features", []):
                    coords = feat.get("geometry", {}).get("coordinates")
                    if coords:
                        urban_pts.append((coords[1], coords[0]))

    if urban_pts:
        # Keep grid points within 2 miles of any data signal
        threshold_deg = 0.035  # ~2.4 miles quick pre-filter
        filtered = []
        for glat, glon, r, c in grid_points:
            for ulat, ulon in urban_pts:
                if abs(glat - ulat) < threshold_deg and abs(glon - ulon) < threshold_deg:
                    filtered.append((glat, glon, r, c))
                    break
        log.info(f"City Mesh: urban filter {len(grid_points)} \u2192 {len(filtered)} grid points "
                 f"({len(urban_pts)} data signal points)")
        if filtered:
            grid_points = filtered

    # Cap at 10x10 grid (100 circles max) -- use Custom Mesh for larger
    if len(grid_points) > 100:
        log.info(f"City Mesh: capping {len(grid_points)} points to 100")
        # Keep the densest cluster -- sort by proximity to centroid
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

    # Build the network -- new network
    net = Network(network_id="city_mesh")
    _state["network"] = net
    clear_edit_state()

    # Place circles at snapped grid points
    grid_map = {}  # (r, c) -> (struct, cp_dict)
    for lat, lon, r, c in snapped:
        struct, cp_dict = build_traffic_circle(
            net, lat, lon,
            structure_id=next_sid("c"),
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
                                       structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            if pi == 0:
                _, cp_dict_north = s_north
                tc_south = cp_by_heading(cp_dict_north, 180.0)
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
                tc_north = cp_by_heading(cp_dict_south, 0.0)
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
                                       structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            n_stations += 1

            if pi == 0:
                _, cp_dict_west = s_west
                tc_east = cp_by_heading(cp_dict_west, 90.0)
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
                tc_west = cp_by_heading(cp_dict_east, 270.0)
                st_east_cp = st_cps.get(f"{st.structure_id}.CP_near_far")
                if tc_west and st_east_cp and tc_west.connected_to is None and st_east_cp.connected_to is None:
                    connect_cps(net, st_east_cp, tc_west, _state["cps"])

            prev_cps = st_cps
            prev_sid = st.structure_id

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("city_mesh", {
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


# ---------------------------------------------------------------------------
# Line tool endpoint
# ---------------------------------------------------------------------------

@builders.post("/network/line")
def network_line():
    """Build a guideway between two user-clicked points.
    Stations every mile along the line, oriented along the line direction.
    Airport-to-city connector. Adds to existing network (does not replace).
    Where the new line crosses an existing connection, a traffic circle is
    inserted and the old connection is re-routed through it."""
    data = request.json or {}
    p1 = data.get("point1")  # {lat, lon}
    p2 = data.get("point2")  # {lat, lon}
    if not p1 or not p2:
        return jsonify({"error": "Two points required (point1, point2 with lat/lon)"}), 400

    lat1, lon1 = float(p1["lat"]), float(p1["lon"])
    lat2, lon2 = float(p2["lat"]), float(p2["lon"])
    total_m = vincenty_m(lat1, lon1, lat2, lon2)
    total_mi = total_m / 1609.34

    # Station spacing: 1 mile, minimum 2 stations (at endpoints)
    station_spacing_mi = 1.0
    n_stations = max(2, round(total_mi / station_spacing_mi) + 1)

    # Heading from point1 to point2
    dlat = lat2 - lat1
    dlon = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    heading = math.degrees(math.atan2(dlon, dlat)) % 360

    # Use existing network or create new
    net = _state.get("network")
    if not net:
        net = Network(network_id="line")
        _state["network"] = net
        clear_edit_state()
    sync_counters()

    # Find where the new line crosses existing connections
    crossings = _find_crossings(lat1, lon1, lat2, lon2)
    # Express crossing positions as fraction along the line (0..1)
    cross_fracs = []
    for clat, clon, cp_a, cp_b in crossings:
        if abs(lat2 - lat1) > abs(lon2 - lon1):
            frac = (clat - lat1) / (lat2 - lat1)
        else:
            frac = (clon - lon1) / (lon2 - lon1)
        cross_fracs.append((frac, clat, clon, cp_a, cp_b))
    cross_fracs.sort(key=lambda x: x[0])

    # Build the position list: evenly spaced stations + crossing insertions
    # Each entry: (frac, lat, lon, is_crossing, crossing_data)
    positions = []
    for i in range(n_stations):
        frac = i / max(1, n_stations - 1)
        slat = lat1 + (lat2 - lat1) * frac
        slon = lon1 + (lon2 - lon1) * frac
        positions.append((frac, slat, slon, False, None))

    # Insert crossing points -- if a station is too close, shift it along the
    # line (halfway toward its nearest neighbor) so no station is lost.
    min_sep_m = 483  # 0.3 mi -- minimum separation before shifting
    for cf, clat, clon, cp_a, cp_b in cross_fracs:
        # Find the nearest non-crossing station
        nearest_idx = None
        best_dist = float("inf")
        for idx, (pf, plat, plon, is_cross, _) in enumerate(positions):
            if is_cross:
                continue
            d = vincenty_m(clat, clon, plat, plon)
            if d < best_dist:
                best_dist = d
                nearest_idx = idx

        if best_dist < min_sep_m and nearest_idx is not None:
            # Shift the displaced station halfway toward its nearest neighbor
            old_frac = positions[nearest_idx][0]
            # Find the neighbor on the opposite side from the crossing
            neighbor_frac = None
            for idx, (pf, _, _, is_cross, _) in enumerate(positions):
                if idx == nearest_idx or is_cross:
                    continue
                # Pick the neighbor on the far side from the crossing
                if (old_frac <= cf and pf < old_frac) or (old_frac >= cf and pf > old_frac):
                    if neighbor_frac is None or abs(pf - old_frac) < abs(neighbor_frac - old_frac):
                        neighbor_frac = pf
            if neighbor_frac is None:
                # No neighbor on the far side -- try the other direction
                for idx, (pf, _, _, is_cross, _) in enumerate(positions):
                    if idx == nearest_idx or is_cross:
                        continue
                    if neighbor_frac is None or abs(pf - old_frac) < abs(neighbor_frac - old_frac):
                        neighbor_frac = pf
            if neighbor_frac is not None:
                shift_frac = (old_frac + neighbor_frac) / 2.0
                shift_lat = lat1 + (lat2 - lat1) * shift_frac
                shift_lon = lon1 + (lon2 - lon1) * shift_frac
                # Only shift if the new position has enough room from the crossing
                if vincenty_m(clat, clon, shift_lat, shift_lon) >= min_sep_m:
                    positions[nearest_idx] = (shift_frac, shift_lat, shift_lon, False, None)
                else:
                    # Not enough room -- designer can remove the station if unwanted
                    pass

        # Insert the crossing traffic circle
        positions.append((cf, clat, clon, True, (cp_a, cp_b)))
    positions.sort(key=lambda x: x[0])

    # Place structures along the line
    placed = []
    circles_inserted = 0
    for frac, slat, slon, is_crossing, cross_data in positions:
        if is_crossing:
            # Place a traffic circle at the crossing
            # Arms aligned to both the new line heading and the crossed connection
            cp_a, cp_b = cross_data
            s_a = _state["structures"].get(cp_a.structure_id)
            s_b = _state["structures"].get(cp_b.structure_id)
            # Heading of the crossed connection
            cdlat = s_b.center_lat - s_a.center_lat
            cdlon = (s_b.center_lon - s_a.center_lon) * math.cos(math.radians(slat))
            cross_heading = math.degrees(math.atan2(cdlon, cdlat)) % 360
            arms = [
                heading % 360,
                cross_heading % 360,
                (heading + 180) % 360,
                (cross_heading + 180) % 360,
            ]
            tc, tc_cps = build_traffic_circle(net, slat, slon,
                                               structure_id=next_sid("c"),
                                               arm_headings=arms)
            _state["structures"][tc.structure_id] = tc
            _state["cps"].update(tc_cps)
            placed.append((tc, tc_cps))
            circles_inserted += 1

            # Disconnect the old crossed connection
            disconnect_cp(net, cp_a, _state["cps"])

            # Reconnect through the traffic circle
            # cp_a's structure -> TC arm closest to cp_a heading
            # cp_b's structure -> TC arm closest to cp_b heading
            tc_to_a = cp_by_heading(tc_cps, (cross_heading + 180) % 360)
            tc_to_b = cp_by_heading(tc_cps, cross_heading % 360)
            if tc_to_a and cp_a.connected_to is None:
                connect_cps(net, tc_to_a, cp_a, _state["cps"])
            if tc_to_b and cp_b.connected_to is None:
                connect_cps(net, tc_to_b, cp_b, _state["cps"])
        else:
            st, st_cps = build_station(net, slat, slon, heading_deg=heading,
                                        structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            placed.append((st, st_cps))

    # Connect consecutive structures along the line
    connected = 0
    for i in range(len(placed) - 1):
        st_a, cps_a = placed[i]
        st_b, cps_b = placed[i + 1]
        cp_out = cps_a.get(f"{st_a.structure_id}.CP_near_far")
        cp_in = cps_b.get(f"{st_b.structure_id}.CP_far_near")
        if not cp_out:
            cp_out = cp_by_heading(cps_a, heading)
        if not cp_in:
            cp_in = cp_by_heading(cps_b, (heading + 180) % 360)
        if cp_out and cp_in and cp_out.connected_to is None and cp_in.connected_to is None:
            connect_cps(net, cp_out, cp_in, _state["cps"])
            connected += 1

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("line_build", {
        "stations": len([p for p in placed if p[0].structure_type == "station"]),
        "circles_inserted": circles_inserted,
        "connected": connected,
        "heading": round(heading, 1), "length_mi": round(total_mi, 1),
    })

    return jsonify({
        "stations": len([p for p in placed if p[0].structure_type == "station"]),
        "circles_inserted": circles_inserted,
        "connected": connected,
        "heading_deg": round(heading, 1),
        "line_miles": round(total_mi, 1),
        "total_miles": total_miles,
    })


# ---------------------------------------------------------------------------
# Grid generator endpoint
# ---------------------------------------------------------------------------

@builders.post("/network/grid")
def network_grid():
    """
    Generate a rectangular grid network:
      - Traffic circles at every intersection
      - One station at the midpoint of every block (between adjacent circles)
      - CPs connected: circle <-> station <-> circle along each axis

    Body (all distances in miles):
      center_lat, center_lon  -- geographic centre of the grid
      spacing_ns              -- up-down block size  (default 1.0)
      spacing_ew              -- left-right block size  (default 1.0)
      extent_ns               -- total up-down span  (default 4.0)
      extent_ew               -- total left-right span  (default 4.0)
      angle_deg               -- grid rotation in degrees CW from north (default 0)
      replace                 -- if true (default), clear existing network first
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
        clear_edit_state()
    else:
        net = _net()
        if net is None:
            net = Network(network_id="grid")
            _state["network"] = net

    # Convert miles -> metres
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

    # -- 1. Build traffic circles at every intersection --
    grid: List[List] = []          # grid[r][c] = (struct, cp_dict)
    for r in range(n_rows):
        row = []
        for c in range(n_cols):
            lat, lon = _rotated(r, c)
            struct, cp_dict = build_traffic_circle(
                net, lat, lon,
                structure_id=next_sid("c"),
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

    # -- 2. Up-down blocks: stations between (r,c) and (r+1,c) --
    for r in range(n_rows - 1):
        for c in range(n_cols):
            positions = _stations_for_block(spacing_ns)
            prev_cps = None  # for chaining station-to-station
            for pi, frac in enumerate(positions):
                lat, lon = _rotated(r + frac, c)
                st, st_cps = build_station(net, lat, lon,
                                           heading_deg=(0.0 + angle_deg) % 360,
                                           structure_id=next_sid("s"))
                _state["structures"][st.structure_id] = st
                _state["cps"].update(st_cps)
                n_stations += 1

                # Rotated arm headings for CP lookups
                h_north = (0.0 + angle_deg) % 360
                h_south = (180.0 + angle_deg) % 360

                if pi == 0:
                    # First station: connect to upper circle's down arm
                    _, cp_dict_north = grid[r][c]
                    tc_south = cp_by_heading(cp_dict_north, h_south)
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
                    tc_north = cp_by_heading(cp_dict_south, h_north)
                    st_south = st_cps.get(f"{st.structure_id}.CP_far_near")
                    if tc_north and st_south and tc_north.connected_to is None and st_south.connected_to is None:
                        connect_cps(net, st_south, tc_north, _state["cps"])

                prev_cps = st_cps
                prev_sid = st.structure_id

    # -- 3. Left-right blocks: stations between (r,c) and (r,c+1) --
    for r in range(n_rows):
        for c in range(n_cols - 1):
            positions = _stations_for_block(spacing_ew)
            prev_cps = None
            for pi, frac in enumerate(positions):
                lat, lon = _rotated(r, c + frac)
                st, st_cps = build_station(net, lat, lon,
                                           heading_deg=(90.0 + angle_deg) % 360,
                                           structure_id=next_sid("s"))
                _state["structures"][st.structure_id] = st
                _state["cps"].update(st_cps)
                n_stations += 1

                # Rotated arm headings for CP lookups
                h_east = (90.0 + angle_deg) % 360
                h_west = (270.0 + angle_deg) % 360

                if pi == 0:
                    # First station: connect to left circle's right arm
                    _, cp_dict_west = grid[r][c]
                    tc_east = cp_by_heading(cp_dict_west, h_east)
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
                    tc_west = cp_by_heading(cp_dict_east, h_west)
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
# Build on drawn lines endpoint
# ---------------------------------------------------------------------------

@builders.post("/network/build_on_lines")
def network_build_on_lines():
    """Build a network on designer-drawn corridor lines.

    Input: {lines: [[{lat, lon}, ...], ...]}
    Each line is a polyline the designer drew on the map.
    Places stations every ~0.6 mi along each line, oriented to local heading.
    Places traffic circles where lines cross within 400m.
    Connects stations along their line and to circles at intersections.
    """
    data = request.json or {}
    lines = data.get("lines", [])
    if not lines:
        return jsonify({"error": "No lines provided. Draw corridor lines first."}), 400

    STATION_SPACING_M = 1000  # ~0.6 miles

    # Build new network
    net = Network(network_id="drawn_corridors")
    _state["network"] = net
    clear_edit_state()

    n_stations = 0
    n_circles = 0

    # -- Find where lines cross -> traffic circles --
    circle_points = []
    cross_threshold_m = 400

    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            for pi in lines[i]:
                for pj in lines[j]:
                    dist = vincenty_m(pi["lat"], pi["lon"], pj["lat"], pj["lon"])
                    if dist < cross_threshold_m:
                        mlat = (pi["lat"] + pj["lat"]) / 2
                        mlon = (pi["lon"] + pj["lon"]) / 2
                        too_close = any(vincenty_m(mlat, mlon, c[0], c[1]) < 800
                                        for c in circle_points)
                        if not too_close:
                            circle_points.append((mlat, mlon, [i, j]))
                            break
                else:
                    continue
                break

    # Place traffic circles
    circle_structs = {}
    for clat, clon, line_idxs in circle_points:
        headings = []
        for li in line_idxs:
            pts = lines[li]
            if len(pts) >= 2:
                dlat = pts[-1]["lat"] - pts[0]["lat"]
                dlon = (pts[-1]["lon"] - pts[0]["lon"]) * math.cos(math.radians(pts[0]["lat"]))
                h = math.degrees(math.atan2(dlon, dlat)) % 360
                headings.extend([h, (h + 180) % 360])
        headings = sorted(set(round(h / 10) * 10 for h in headings))
        if len(headings) < 4:
            headings = [0.0, 90.0, 180.0, 270.0]

        struct, cp_dict = build_traffic_circle(
            net, clat, clon,
            structure_id=next_sid("c"),
            arm_headings=[float(h) for h in headings[:8]],
        )
        _state["structures"][struct.structure_id] = struct
        _state["cps"].update(cp_dict)
        circle_structs[(round(clat, 5), round(clon, 5))] = (struct, cp_dict)
        n_circles += 1

    # -- Place stations along each line --
    all_placed = {}  # line_idx -> [(struct, cps, lat, lon, heading)]

    for li, line_pts in enumerate(lines):
        if len(line_pts) < 2:
            continue

        # Cumulative distance along the polyline
        cum_dist = [0.0]
        for k in range(1, len(line_pts)):
            d = vincenty_m(line_pts[k-1]["lat"], line_pts[k-1]["lon"],
                           line_pts[k]["lat"], line_pts[k]["lon"])
            cum_dist.append(cum_dist[-1] + d)
        total_len = cum_dist[-1]
        if total_len < 200:
            continue

        n_seg = max(1, round(total_len / STATION_SPACING_M))
        station_dists = [total_len * i / n_seg for i in range(n_seg + 1)]

        placed = []
        for target_d in station_dists:
            # Interpolate position
            slat, slon = line_pts[-1]["lat"], line_pts[-1]["lon"]
            for k in range(1, len(cum_dist)):
                if cum_dist[k] >= target_d:
                    frac = (target_d - cum_dist[k-1]) / max(1, cum_dist[k] - cum_dist[k-1])
                    slat = line_pts[k-1]["lat"] + (line_pts[k]["lat"] - line_pts[k-1]["lat"]) * frac
                    slon = line_pts[k-1]["lon"] + (line_pts[k]["lon"] - line_pts[k-1]["lon"]) * frac
                    break

            # Skip if too close to a traffic circle
            near_circle = any(vincenty_m(slat, slon, cl, cn) < 300
                              for (cl, cn) in circle_structs)
            if near_circle:
                continue

            # Local heading
            local_heading = 0
            for k in range(1, len(line_pts)):
                if cum_dist[k] >= target_d:
                    dl = line_pts[k]["lat"] - line_pts[k-1]["lat"]
                    dn = (line_pts[k]["lon"] - line_pts[k-1]["lon"]) * math.cos(math.radians(line_pts[k]["lat"]))
                    if abs(dl) + abs(dn) > 0.0001:
                        local_heading = math.degrees(math.atan2(dn, dl)) % 360
                    break

            st, st_cps = build_station(net, slat, slon, heading_deg=local_heading,
                                        structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            placed.append((st, st_cps, slat, slon, local_heading))
            n_stations += 1

        all_placed[li] = placed

        # Connect consecutive stations along this line
        for k in range(1, len(placed)):
            prev_st, prev_cps, _, _, prev_h = placed[k-1]
            cur_st, cur_cps, _, _, cur_h = placed[k]
            cp_out = cp_by_heading(prev_cps, prev_h)
            cp_in = cp_by_heading(cur_cps, (cur_h + 180) % 360)
            if cp_out and cp_in and cp_out.connected_to is None and cp_in.connected_to is None:
                connect_cps(net, cp_out, cp_in, _state["cps"])

    # Connect line endpoints to nearest traffic circles
    for li, placed in all_placed.items():
        if not placed:
            continue
        for endpoint in [placed[0], placed[-1]]:
            st, st_cps, slat, slon, sh = endpoint
            best_dist = 2000
            best_circle = None
            for (clat, clon), (cstruct, ccps) in circle_structs.items():
                d = vincenty_m(slat, slon, clat, clon)
                if d < best_dist:
                    best_dist = d
                    best_circle = (cstruct, ccps, clat, clon)
            if best_circle:
                cstruct, ccps, clat, clon = best_circle
                dl = clat - slat
                dn = (clon - slon) * math.cos(math.radians(slat))
                h_to = math.degrees(math.atan2(dn, dl)) % 360
                cp_st = cp_by_heading(st_cps, h_to)
                cp_tc = cp_by_heading(ccps, (h_to + 180) % 360)
                if cp_st and cp_tc and cp_st.connected_to is None and cp_tc.connected_to is None:
                    connect_cps(net, cp_st, cp_tc, _state["cps"])

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("build_on_lines", {
        "lines": len(lines), "circles": n_circles,
        "stations": n_stations, "total_miles": total_miles,
    })

    return jsonify({
        "lines_used": len(lines),
        "circles": n_circles,
        "stations": n_stations,
        "total_miles": total_miles,
    })


# ---------------------------------------------------------------------------
# Crash mesh endpoint
# ---------------------------------------------------------------------------

@builders.post("/network/crash_mesh")
def network_crash_mesh():
    """Build a network from crash corridor lines.

    5-stage algorithm:
    1. Extract corridor LINES from crash density data (top 10% cells -> polylines)
    2. (Future: Option-drag to adjust lines)
    3. Place traffic circles where corridors cross
    4. Place stations along each line, 0.5-0.75 mi apart, oriented to line heading
    5. Connect along lines and between lines at circles
    """
    data = request.json or {}
    fence = data.get("fence")
    threshold_pct = data.get("threshold_pct", 10)

    if not fence:
        return jsonify({"error": "No city boundary provided"}), 400

    coords = []
    if fence.get("type") == "Polygon":
        coords = fence["coordinates"][0]
    elif fence.get("type") == "MultiPolygon":
        for poly in fence["coordinates"]:
            coords.extend(poly[0])
    if not coords:
        return jsonify({"error": "Invalid boundary polygon"}), 400

    lons_f = [c[0] for c in coords]
    lats_f = [c[1] for c in coords]
    center_lat = (min(lats_f) + max(lats_f)) / 2
    center_lon = (min(lons_f) + max(lons_f)) / 2

    # Detect state
    state_abbr = None
    try:
        from mesh_mobility.scripts.census_overlays import fips_from_latlon, STATE_FIPS_TO_ABBR
        state_fips, _ = fips_from_latlon(center_lat, center_lon)
        if state_fips:
            state_abbr = STATE_FIPS_TO_ABBR.get(state_fips)
    except Exception:
        pass
    if not state_abbr:
        return jsonify({"error": "Cannot determine state for crash data"}), 400

    # Get crash data from library
    span_mi = vincenty_m(min(lats_f), center_lon, max(lats_f), center_lon) / 1609.34
    crash_data = _md.get_crashes(state_abbr, center_lat, center_lon, radius_miles=max(20, span_mi))
    if not crash_data or not crash_data.get("features"):
        return jsonify({"error": f"No crash data for {state_abbr.upper()}. Run CrashHarvester first."}), 404

    # Point-in-polygon filter
    def _pip(px, py, poly):
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    poly_coords = coords

    # Filter crash cells to boundary
    in_boundary = []
    for f in crash_data["features"]:
        lon, lat = f["geometry"]["coordinates"]
        if _pip(lon, lat, poly_coords):
            in_boundary.append(f)

    if not in_boundary:
        return jsonify({"error": "No crash data within boundary"}), 400

    # -- STAGE 1: Extract corridor lines from top crash cells --
    all_counts = sorted([f["properties"]["crashes"] for f in in_boundary], reverse=True)
    cutoff_idx = max(1, int(len(all_counts) * threshold_pct / 100))
    threshold = all_counts[min(cutoff_idx, len(all_counts) - 1)]
    hot_cells = [(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0],
                  f["properties"]["crashes"])
                 for f in in_boundary if f["properties"]["crashes"] >= threshold]
    log.info(f"Crash Mesh Stage 1: {len(hot_cells)} hot cells (threshold={threshold})")

    # Cluster into corridors: cells within ~500m are same corridor
    cluster_deg = 0.005  # ~500m
    corridors = []  # each corridor = ordered list of (lat, lon)
    used = [False] * len(hot_cells)

    # Sort hottest first -- seed corridors from biggest concentrations
    indices = sorted(range(len(hot_cells)), key=lambda i: hot_cells[i][2], reverse=True)

    for seed_idx in indices:
        if used[seed_idx]:
            continue
        corridor = [seed_idx]
        used[seed_idx] = True
        # Grow by adding nearest unused neighbor repeatedly
        grew = True
        while grew:
            grew = False
            tail_lat, tail_lon, _ = hot_cells[corridor[-1]]
            head_lat, head_lon, _ = hot_cells[corridor[0]]
            best_tail = (-1, float("inf"))
            best_head = (-1, float("inf"))
            for j in range(len(hot_cells)):
                if used[j]:
                    continue
                jlat, jlon, _ = hot_cells[j]
                dt = abs(jlat - tail_lat) + abs(jlon - tail_lon)
                dh = abs(jlat - head_lat) + abs(jlon - head_lon)
                if dt < cluster_deg and dt < best_tail[1]:
                    best_tail = (j, dt)
                if dh < cluster_deg and dh < best_head[1]:
                    best_head = (j, dh)
            if best_tail[0] >= 0:
                corridor.append(best_tail[0])
                used[best_tail[0]] = True
                grew = True
            if best_head[0] >= 0 and best_head[0] != best_tail[0]:
                corridor.insert(0, best_head[0])
                used[best_head[0]] = True
                grew = True

        if len(corridor) >= 3:
            # Convert to (lat, lon) list -- already ordered by growth
            line = [(hot_cells[i][0], hot_cells[i][1]) for i in corridor]
            corridors.append(line)

    log.info(f"Crash Mesh Stage 1: {len(corridors)} corridor lines extracted")

    # -- STAGE 3: Find where corridors cross -> traffic circles --
    circle_points = []  # (lat, lon, [corridor_indices])
    cross_threshold_m = 400  # corridors within 400m of each other = intersection

    for i in range(len(corridors)):
        for j in range(i + 1, len(corridors)):
            # Check each point on corridor i against corridor j
            for plat, plon in corridors[i]:
                for qlat, qlon in corridors[j]:
                    dist = vincenty_m(plat, plon, qlat, qlon)
                    if dist < cross_threshold_m:
                        # Intersection found -- use midpoint
                        mlat = (plat + qlat) / 2
                        mlon = (plon + qlon) / 2
                        # Check not too close to existing circle
                        too_close = False
                        for clat, clon, _ in circle_points:
                            if vincenty_m(mlat, mlon, clat, clon) < 800:
                                too_close = True
                                break
                        if not too_close:
                            circle_points.append((mlat, mlon, [i, j]))
                            break  # one intersection per corridor pair is enough
                else:
                    continue
                break

    log.info(f"Crash Mesh Stage 3: {len(circle_points)} intersection circles")

    # -- STAGE 4 & 5: Build network -- circles, stations, connections --
    net = Network(network_id="crash_mesh")
    _state["network"] = net
    clear_edit_state()

    n_stations = 0
    n_circles = 0
    STATION_SPACING_M = 1000  # ~0.6 miles

    # Place traffic circles at intersections
    circle_structs = {}  # (lat,lon) -> (struct, cp_dict)
    for clat, clon, corridor_idxs in circle_points:
        # Determine arm headings from the corridors that cross here
        headings = []
        for ci in corridor_idxs:
            corr = corridors[ci]
            lat_s, lon_s = corr[0]
            lat_e, lon_e = corr[-1]
            dlat = lat_e - lat_s
            dlon = (lon_e - lon_s) * math.cos(math.radians((lat_s + lat_e) / 2))
            h = math.degrees(math.atan2(dlon, dlat)) % 360
            headings.append(h)
            headings.append((h + 180) % 360)
        # Deduplicate headings that are too close
        headings = sorted(set(round(h / 10) * 10 for h in headings))
        if len(headings) < 4:
            headings = [0.0, 90.0, 180.0, 270.0]

        struct, cp_dict = build_traffic_circle(
            net, clat, clon,
            structure_id=next_sid("c"),
            arm_headings=[float(h) for h in headings[:8]],
        )
        _state["structures"][struct.structure_id] = struct
        _state["cps"].update(cp_dict)
        circle_structs[(round(clat, 5), round(clon, 5))] = (struct, cp_dict)
        n_circles += 1

    # Place stations along each corridor line
    corridor_stations = {}  # corridor_idx -> [(struct, cps, lat, lon)]
    for ci, line in enumerate(corridors):
        # Compute cumulative distance along the line
        cum_dist = [0.0]
        for k in range(1, len(line)):
            d = vincenty_m(line[k-1][0], line[k-1][1], line[k][0], line[k][1])
            cum_dist.append(cum_dist[-1] + d)
        total_len = cum_dist[-1]
        if total_len < 200:
            continue

        # Compute corridor heading
        dlat = line[-1][0] - line[0][0]
        dlon = (line[-1][1] - line[0][1]) * math.cos(math.radians((line[0][0] + line[-1][0]) / 2))
        heading = math.degrees(math.atan2(dlon, dlat)) % 360

        # Generate station positions at regular intervals
        n_seg = max(1, round(total_len / STATION_SPACING_M))
        station_dists = [total_len * i / n_seg for i in range(n_seg + 1)]

        placed = []
        for target_d in station_dists:
            # Interpolate position along the polyline
            for k in range(1, len(cum_dist)):
                if cum_dist[k] >= target_d:
                    frac = (target_d - cum_dist[k-1]) / max(1, cum_dist[k] - cum_dist[k-1])
                    slat = line[k-1][0] + (line[k][0] - line[k-1][0]) * frac
                    slon = line[k-1][1] + (line[k][1] - line[k-1][1]) * frac
                    break
            else:
                slat, slon = line[-1]

            # Check if a traffic circle is already close -- skip station
            is_circle = False
            for (clat, clon), _ in circle_structs.items():
                if vincenty_m(slat, slon, clat, clon) < 300:
                    is_circle = True
                    break
            if is_circle:
                continue

            # Local heading between neighboring line points
            local_heading = heading
            for k in range(1, len(line)):
                if cum_dist[k] >= target_d:
                    dl = line[k][0] - line[k-1][0]
                    dn = (line[k][1] - line[k-1][1]) * math.cos(math.radians(line[k][0]))
                    if abs(dl) + abs(dn) > 0.0001:
                        local_heading = math.degrees(math.atan2(dn, dl)) % 360
                    break

            st, st_cps = build_station(net, slat, slon, heading_deg=local_heading,
                                        structure_id=next_sid("s"))
            _state["structures"][st.structure_id] = st
            _state["cps"].update(st_cps)
            placed.append((st, st_cps, slat, slon, local_heading))
            n_stations += 1

        corridor_stations[ci] = placed

        # Connect consecutive stations along this corridor
        for k in range(1, len(placed)):
            prev_st, prev_cps, _, _, prev_h = placed[k-1]
            cur_st, cur_cps, _, _, cur_h = placed[k]
            cp_out = cp_by_heading(prev_cps, prev_h)
            cp_in = cp_by_heading(cur_cps, (cur_h + 180) % 360)
            if cp_out and cp_in and cp_out.connected_to is None and cp_in.connected_to is None:
                connect_cps(net, cp_out, cp_in, _state["cps"])

    # Connect corridor endpoints to nearest traffic circles
    for ci, placed in corridor_stations.items():
        if not placed:
            continue
        for endpoint in [placed[0], placed[-1]]:
            st, st_cps, slat, slon, sh = endpoint
            best_dist = 2000  # max 2km to connect
            best_circle = None
            best_heading = None
            for (clat, clon), (cstruct, ccps) in circle_structs.items():
                d = vincenty_m(slat, slon, clat, clon)
                if d < best_dist:
                    best_dist = d
                    best_circle = (cstruct, ccps, clat, clon)
            if best_circle:
                cstruct, ccps, clat, clon = best_circle
                # heading from station to circle
                dl = clat - slat
                dn = (clon - slon) * math.cos(math.radians(slat))
                h_to_circle = math.degrees(math.atan2(dn, dl)) % 360
                cp_st = cp_by_heading(st_cps, h_to_circle)
                cp_tc = cp_by_heading(ccps, (h_to_circle + 180) % 360)
                if cp_st and cp_tc and cp_st.connected_to is None and cp_tc.connected_to is None:
                    connect_cps(net, cp_st, cp_tc, _state["cps"])

    net.build()
    total_miles = round(net.total_length_m() / 1609.34, 1)

    noelle_log("crash_mesh", {
        "corridors": len(corridors),
        "circles": n_circles,
        "stations": n_stations,
        "threshold": threshold,
        "hot_cells": len(hot_cells),
        "total_miles": total_miles,
    })

    return jsonify({
        "corridors": len(corridors),
        "circles": n_circles,
        "stations": n_stations,
        "hot_cells": len(hot_cells),
        "threshold": threshold,
        "total_miles": total_miles,
    })
