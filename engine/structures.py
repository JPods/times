"""
route_time.engine.structures
============================
Factory functions that build Station and TrafficCircle structures
as atomic units with the correct internal topology.

Every structure exposes ConnectionPoints (stub-pairs).
Stub-pairs connect to stub-pairs — this is the universal interface
shared with the SketchUp plugin's connection point rule.

ConnectionPoint
  cp_id          unique id, e.g. "S017.CP0"
  structure_id   which structure this CP belongs to
  heading_deg    direction stubs point OUTWARD (0=north, 90=east, ...)
  inbound_node   Node  — vehicle arrives FROM outside
  outbound_node  Node  — vehicle departs TO outside
  center_lat/lon midpoint between the two stub tips
  connected_to   cp_id of the connected CP, or None

Structure
  structure_id
  structure_type  "station" | "traffic_circle"
  cp_ids          ordered list of CP ids
  node_ids        all internal node ids
  line_ids        all internal line ids

Geometry notes
--------------
All positions computed in degrees lat/lon.
  DEG_PER_M_LAT = 1/111_320          ~constant worldwide
  DEG_PER_M_LON = 1/(111_320*cos(lat))  varies with latitude

Traffic circle (US/CCW):
  15 m diameter ring (7.5 m radius)
  4 arms at 0°/90°/180°/270° (N/E/S/W), rotatable
  Each arm: outbound stub and inbound stub, each extending 15 m
            beyond the ring edge (22.5 m from center)
  Ring nodes (8): N_div, N_merge, W_div, W_merge,
                  S_div, S_merge, E_div, E_merge
  CCW ring order: N_div→N_merge→arc→W_div→W_merge→arc→
                  S_div→S_merge→arc→E_div→E_merge→arc→N_div

  At each arm:
    diverge (outbound) node comes BEFORE merge (inbound) in CCW order
    outbound stub: ring_div → outbound_tip  (going outward)
    inbound stub:  inbound_tip → ring_merge (going inward)
    CP center = midpoint(outbound_tip, inbound_tip)

Station (US/CCW, right-side loading, ~70 m between turnabouts):
  Oriented along a heading_deg (default 0 = north-south, NB going north)
  NB guideway on east, SB guideway on west
  Station siding east of NB, traversed northward, ~7 m wide
  Turnabout at north end: NB(east) → SB(west), CCW loop
  Turnabout at south end: SB(west) → NB(east), CCW loop
  2 CPs: north stub-pair and south stub-pair
    Each CP = NB tip + SB tip at that end

  Internal nodes (approximate, sufficient for routing):
    NB_south, SB_south     — south external stubs
    TA_south_nb, TA_south_sb — south turnabout nodes
    SIDING_south, SIDING_north — platform siding entry/exit
    TA_north_nb, TA_north_sb — north turnabout nodes
    NB_north, SB_north     — north external stubs
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .network import Line, Network, Node, Station, vincenty_m


# ---------------------------------------------------------------------------
# Geography helpers
# ---------------------------------------------------------------------------

def _deg_per_m(lat: float):
    """Returns (deg_lat_per_m, deg_lon_per_m) at given latitude."""
    lat_r = math.radians(lat)
    dlat = 1 / 111_320.0
    dlon = 1 / (111_320.0 * math.cos(lat_r))
    return dlat, dlon


def _offset(lat: float, lon: float, heading_deg: float, distance_m: float):
    """Move from (lat, lon) by distance_m in heading_deg direction."""
    dlat, dlon = _deg_per_m(lat)
    rad = math.radians(heading_deg)
    return (
        lat + math.cos(rad) * distance_m * dlat,
        lon + math.sin(rad) * distance_m * dlon,
    )


def _midpoint(lat1, lon1, lat2, lon2):
    return (lat1 + lat2) / 2, (lon1 + lon2) / 2


# ---------------------------------------------------------------------------
# ConnectionPoint
# ---------------------------------------------------------------------------

@dataclass
class ConnectionPoint:
    cp_id:         str
    structure_id:  str
    heading_deg:   float          # direction stubs point OUTWARD
    inbound_node:  Node           # vehicle arrives from outside
    outbound_node: Node           # vehicle departs to outside
    center_lat:    float
    center_lon:    float
    connected_to:  Optional[str] = None   # other cp_id

    def to_dict(self) -> dict:
        return {
            "cp_id":         self.cp_id,
            "structure_id":  self.structure_id,
            "heading_deg":   self.heading_deg,
            "inbound_node":  self.inbound_node.node_id,
            "outbound_node": self.outbound_node.node_id,
            "center_lat":    self.center_lat,
            "center_lon":    self.center_lon,
            "connected_to":  self.connected_to,
        }


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

@dataclass
class Structure:
    structure_id:   str
    structure_type: str           # "station" | "traffic_circle"
    cp_ids:         List[str]     # ordered CP ids
    node_ids:       List[str]
    line_ids:       List[str]
    center_lat:     float = 0.0
    center_lon:     float = 0.0
    heading_deg:    float = 0.0           # station: NB travel direction
    arm_headings:   List[float] = field(default_factory=list)  # traffic_circle

    def to_dict(self) -> dict:
        return {
            "structure_id":   self.structure_id,
            "structure_type": self.structure_type,
            "cp_ids":         self.cp_ids,
            "node_ids":       self.node_ids,
            "line_ids":       self.line_ids,
            "center_lat":     self.center_lat,
            "center_lon":     self.center_lon,
            "heading_deg":    self.heading_deg,
            "arm_headings":   self.arm_headings,
        }


# ---------------------------------------------------------------------------
# Internal builder helpers
# ---------------------------------------------------------------------------

def _node(net: Network, nid: str, lat: float, lon: float,
          is_station: bool = False) -> Node:
    n = Node(nid, lat, lon, is_station=is_station)
    net.nodes[nid] = n
    if is_station:
        net.stations[nid] = Station(nid, n)
    return n


def _line(net: Network, lid: str, start: Node, end: Node,
          coords: List[Tuple[float, float]] = None) -> Line:
    length_m = vincenty_m(start.lat, start.lon, end.lat, end.lon)
    l = Line(lid, start, end, length_m, coordinates=coords or [])
    net.lines[lid] = l
    return l


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Traffic Circle builder
# ---------------------------------------------------------------------------

# Physical constants
_CIRCLE_RADIUS_M = 7.5    # 15 m diameter → 7.5 m radius
_STUB_LENGTH_M   = 15.0   # stubs extend 15 m beyond ring edge
_STUB_SPACING_M  = 1.5    # lateral spacing between inbound and outbound stub tips
# (half-spacing each side of the arm centreline)

# Default arm headings (N, E, S, W) in degrees
_DEFAULT_ARM_HEADINGS = [0.0, 90.0, 180.0, 270.0]


def build_traffic_circle(
    net: Network,
    center_lat: float,
    center_lon: float,
    structure_id: Optional[str] = None,
    arm_headings: Optional[List[float]] = None,
) -> Tuple[Structure, Dict[str, ConnectionPoint]]:
    """
    Build a traffic circle and add all nodes/lines to net.
    Returns (Structure, {cp_id: ConnectionPoint}).

    arm_headings: list of 4 outward-pointing headings in degrees.
    Default: [0, 90, 180, 270] = N, E, S, W.
    Each arm can be rotated independently by changing its heading.

    CCW ring order (US standard):
      Arm 0 (N) div → Arm 0 merge → arc → Arm 3 (W) div → Arm 3 merge →
      arc → Arm 2 (S) div → Arm 2 merge → arc → Arm 1 (E) div → Arm 1 merge →
      arc → Arm 0 (N) div

    At each arm the stub-pair is:
      outbound stub: ring_div_node ──→ outbound_tip_node  (going outward)
      inbound stub:  inbound_tip_node ──→ ring_merge_node (going inward)
    """
    sid = structure_id or _uid("TC")
    arms = arm_headings if arm_headings else list(_DEFAULT_ARM_HEADINGS)
    assert len(arms) == 4

    dlat, dlon = _deg_per_m(center_lat)

    def ring_node(name, heading_deg, dist_m):
        lat, lon = _offset(center_lat, center_lon, heading_deg, dist_m)
        return _node(net, f"{sid}.{name}", lat, lon)

    def stub_node(name, heading_deg, dist_m, lateral_m, lateral_heading_deg):
        lat, lon = _offset(center_lat, center_lon, heading_deg, dist_m)
        lat, lon = _offset(lat, lon, lateral_heading_deg, lateral_m)
        return _node(net, f"{sid}.{name}", lat, lon)

    # Build ring nodes and stubs for each arm
    # CCW arm order: arm 0(N), arm 3(W), arm 2(S), arm 1(E) → indices [0,3,2,1]
    ccw_arm_order = [0, 3, 2, 1]

    arm_nodes = {}   # arm_idx → {div, merge, out_tip, in_tip}

    for i, arm_idx in enumerate(ccw_arm_order):
        h = arms[arm_idx]               # outward heading of this arm
        inward_h = (h + 180) % 360     # toward center

        # Ring nodes sit on the ring circumference
        # Diverge slightly CCW-ahead of centre, merge slightly CCW-behind
        # For simplicity, place both div and merge at the ring edge on the arm axis
        # offset laterally by half _STUB_SPACING_M
        right_h = (h + 90) % 360   # rightward from outward direction
        left_h  = (h - 90) % 360

        # Diverge node: on the ring, slightly to the right (outbound is right side)
        div_lat, div_lon = _offset(center_lat, center_lon, h, _CIRCLE_RADIUS_M)
        div_lat, div_lon = _offset(div_lat, div_lon, right_h, _STUB_SPACING_M / 2)
        div_node = _node(net, f"{sid}.A{arm_idx}_div", div_lat, div_lon)

        # Merge node: on the ring, slightly to the left (inbound is left side)
        mrg_lat, mrg_lon = _offset(center_lat, center_lon, h, _CIRCLE_RADIUS_M)
        mrg_lat, mrg_lon = _offset(mrg_lat, mrg_lon, left_h, _STUB_SPACING_M / 2)
        mrg_node = _node(net, f"{sid}.A{arm_idx}_merge", mrg_lat, mrg_lon)

        # Stub tips (15 m beyond ring edge = 22.5 m from center)
        total_dist = _CIRCLE_RADIUS_M + _STUB_LENGTH_M
        out_lat, out_lon = _offset(center_lat, center_lon, h, total_dist)
        out_lat, out_lon = _offset(out_lat, out_lon, right_h, _STUB_SPACING_M / 2)
        out_tip = _node(net, f"{sid}.A{arm_idx}_out", out_lat, out_lon)

        in_lat, in_lon = _offset(center_lat, center_lon, h, total_dist)
        in_lat, in_lon = _offset(in_lat, in_lon, left_h, _STUB_SPACING_M / 2)
        in_tip = _node(net, f"{sid}.A{arm_idx}_in", in_lat, in_lon)

        arm_nodes[arm_idx] = {
            "div": div_node, "merge": mrg_node,
            "out_tip": out_tip, "in_tip": in_tip,
            "heading": h,
        }

    # Build ring lines (CCW: arm_order [0,3,2,1])
    line_ids = []
    for i in range(4):
        cur_arm = ccw_arm_order[i]
        nxt_arm = ccw_arm_order[(i + 1) % 4]
        cur = arm_nodes[cur_arm]
        nxt = arm_nodes[nxt_arm]

        # div → merge (within same arm, small lateral arc)
        l = _line(net, f"{sid}.RL{cur_arm}a", cur["div"], cur["merge"])
        line_ids.append(l.line_id)

        # merge → next div (arc between arms)
        l = _line(net, f"{sid}.RL{cur_arm}b", cur["merge"], nxt["div"])
        line_ids.append(l.line_id)

    # Build stub lines
    node_ids = []
    for arm_idx, an in arm_nodes.items():
        # outbound stub: div → out_tip
        l = _line(net, f"{sid}.A{arm_idx}_out_stub", an["div"], an["out_tip"])
        line_ids.append(l.line_id)
        # inbound stub: in_tip → merge
        l = _line(net, f"{sid}.A{arm_idx}_in_stub", an["in_tip"], an["merge"])
        line_ids.append(l.line_id)
        node_ids.extend([an["div"].node_id, an["merge"].node_id,
                         an["out_tip"].node_id, an["in_tip"].node_id])

    # Build ConnectionPoints (one per arm)
    cps: Dict[str, ConnectionPoint] = {}
    cp_ids = []
    for arm_idx in range(4):
        an = arm_nodes[arm_idx]
        cp_id = f"{sid}.CP{arm_idx}"
        clat, clon = _midpoint(an["out_tip"].lat, an["out_tip"].lon,
                               an["in_tip"].lat,  an["in_tip"].lon)
        cp = ConnectionPoint(
            cp_id=cp_id,
            structure_id=sid,
            heading_deg=an["heading"],
            inbound_node=an["in_tip"],
            outbound_node=an["out_tip"],
            center_lat=clat,
            center_lon=clon,
        )
        cps[cp_id] = cp
        cp_ids.append(cp_id)

    struct = Structure(
        structure_id=sid,
        structure_type="traffic_circle",
        cp_ids=cp_ids,
        node_ids=node_ids,
        line_ids=line_ids,
        center_lat=center_lat,
        center_lon=center_lon,
        arm_headings=list(arms),
    )

    net.build()
    return struct, cps


# ---------------------------------------------------------------------------
# Station builder
# ---------------------------------------------------------------------------

_STATION_LENGTH_M   = 70.0   # distance between north and south turnabouts
_STATION_WIDTH_M    = 7.0    # east-west width (NB to siding)
_TURNABOUT_RADIUS_M = 4.0    # CCW loop radius
_STUB_EXT_M         = 10.0   # how far stubs extend beyond turnabout


def build_station(
    net: Network,
    center_lat: float,
    center_lon: float,
    heading_deg: float = 0.0,   # 0 = north-south, NB going north (east side)
    structure_id: Optional[str] = None,
    mark_platform_as_station: bool = True,
) -> Tuple[Structure, Dict[str, ConnectionPoint]]:
    """
    Build a station and add all nodes/lines to net.
    Returns (Structure, {cp_id: ConnectionPoint}).

    heading_deg: the direction NB travels (0 = northward).
    center_lat/center_lon: the geometric centre — midpoint between NB and SB tracks.

    Internal structure (local coords, right = east_h direction):
      NB track:  W/2 right of centre
      SB track:  W/2 left  of centre
      Siding:    3W/2 right of centre
      North CP (outbound = NB_N_tip, inbound = SB_N_tip): symmetric ±W/2
      South CP (outbound = SB_S_tip, inbound = NB_S_tip): symmetric ±W/2

    Flow (NB vehicle):
      NB_south_in → siding_entry → [platform] → siding_exit → NB_north_out
      OR: siding_exit → TA_north → SB_north_out

    Flow (SB vehicle):
      SB_south_in → TA_south → siding_entry → [platform] → siding_exit → NB_north_out
      OR: siding_exit → TA_north → SB_north_out
    """
    sid = structure_id or _uid("ST")

    # Direction vectors
    nb_h   = heading_deg             # NB goes this direction
    sb_h   = (nb_h + 180) % 360     # SB goes opposite
    east_h = (nb_h + 90)  % 360     # right of NB travel direction
    west_h = (nb_h - 90)  % 360     # left  of NB travel direction

    half = _STATION_LENGTH_M / 2
    W    = _STATION_WIDTH_M
    S    = _STUB_EXT_M

    # center_lat/center_lon is the true geometric centre of the station —
    # the midpoint between the NB and SB tracks.
    # NB is W/2 to the RIGHT of centre; SB is W/2 to the LEFT.
    # Siding is W/2 + W = 3W/2 to the right of centre.
    # This makes the stub-pair at each CP fully symmetric: outbound stub
    # on the right of the travel axis, inbound stub on the left.

    def pt(name, fwd_m, lat_m):
        """Place a node at (fwd_m forward, lat_m rightward) from centre."""
        lat, lon = _offset(center_lat, center_lon, nb_h,   fwd_m)
        lat, lon = _offset(lat,        lon,        east_h, lat_m)
        return _node(net, f"{sid}.{name}", lat, lon)

    # ── NB guideway (W/2 right of centre) ──────────────────────────────────
    NB_N = pt("NB_N",  half,  +W/2)   # NB north end
    NB_S = pt("NB_S", -half,  +W/2)   # NB south end

    # ── SB guideway (W/2 left of centre) ───────────────────────────────────
    SB_N = pt("SB_N",  half,  -W/2)
    SB_S = pt("SB_S", -half,  -W/2)

    # ── Siding / platform (3W/2 right of centre = W right of NB) ───────────
    SIDE_N   = pt("SIDE_N",    half * 0.4, +3*W/2)  # siding exit  (north of platform)
    SIDE_S   = pt("SIDE_S",   -half * 0.4, +3*W/2)  # siding entry (south of platform)
    PLATFORM = pt("PLATFORM",  0,          +3*W/2)

    PLATFORM.is_station = mark_platform_as_station
    if mark_platform_as_station:
        net.stations[PLATFORM.node_id] = Station(PLATFORM.node_id, PLATFORM)

    # ── Turnabout midpoints (midway between NB and SB = on centre axis) ────
    TA_N_mid = pt("TA_N_mid",  half, 0)
    TA_S_mid = pt("TA_S_mid", -half, 0)

    # ── External stub tips ──────────────────────────────────────────────────
    NB_N_tip = pt("NB_N_tip",  half + S, +W/2)
    SB_N_tip = pt("SB_N_tip",  half + S, -W/2)
    NB_S_tip = pt("NB_S_tip", -half - S, +W/2)
    SB_S_tip = pt("SB_S_tip", -half - S, -W/2)

    # ---- Lines ----
    line_ids = []

    def ln(name, a, b):
        l = _line(net, f"{sid}.{name}", a, b)
        line_ids.append(l.line_id)
        return l

    # NB main guideway (through the station, past both turnabouts)
    ln("NB_S_in",   NB_S_tip, NB_S)      # approaching from south
    ln("NB_main",   NB_S, NB_N)          # through the station length
    ln("NB_N_out",  NB_N, NB_N_tip)      # departing to north

    # SB main guideway
    ln("SB_N_in",   SB_N_tip, SB_N)      # approaching from north
    ln("SB_main",   SB_N, SB_S)          # through the station length
    ln("SB_S_out",  SB_S, SB_S_tip)      # departing to south

    # NB → siding entry (NB vehicle peels right into platform)
    ln("NB_to_side", NB_S, SIDE_S)

    # Siding through platform (northward)
    ln("SIDE_entry", SIDE_S, PLATFORM)
    ln("SIDE_exit",  PLATFORM, SIDE_N)

    # Siding → NB merge (vehicle exits platform back onto NB)
    ln("SIDE_to_NB", SIDE_N, NB_N)

    # North turnabout: NB_N → CCW loop → SB_N (vehicle exits north, goes south)
    ln("TA_N_a", NB_N,    TA_N_mid)
    ln("TA_N_b", TA_N_mid, SB_N)

    # South turnabout: SB_S → CCW loop → NB_S (SB vehicle accesses station)
    ln("TA_S_a", SB_S,    TA_S_mid)
    ln("TA_S_b", TA_S_mid, NB_S)

    # ---- ConnectionPoints ----
    # North CP: NB_N_tip (outbound, vehicle exits north on NB)
    #           SB_N_tip (inbound, vehicle enters from north on SB)
    #   inbound_node  = SB_N_tip  (vehicle arrives at station from north via SB)
    #   outbound_node = NB_N_tip  (vehicle departs station going north via NB)
    north_clat, north_clon = _midpoint(NB_N_tip.lat, NB_N_tip.lon,
                                       SB_N_tip.lat, SB_N_tip.lon)
    cp_north = ConnectionPoint(
        cp_id        = f"{sid}.CP_N",
        structure_id = sid,
        heading_deg  = nb_h,           # pointing northward
        inbound_node = SB_N_tip,       # SB arrives from north
        outbound_node= NB_N_tip,       # NB departs northward
        center_lat   = north_clat,
        center_lon   = north_clon,
    )

    # South CP: NB_S_tip (inbound, NB vehicle approaches from south)
    #           SB_S_tip (outbound, vehicle departs south on SB)
    south_clat, south_clon = _midpoint(NB_S_tip.lat, NB_S_tip.lon,
                                       SB_S_tip.lat, SB_S_tip.lon)
    cp_south = ConnectionPoint(
        cp_id        = f"{sid}.CP_S",
        structure_id = sid,
        heading_deg  = sb_h,           # pointing southward (stubs point away)
        inbound_node = NB_S_tip,       # NB arrives from south
        outbound_node= SB_S_tip,       # SB departs southward
        center_lat   = south_clat,
        center_lon   = south_clon,
    )

    all_node_ids = [n.node_id for n in [
        NB_N, NB_S, SB_N, SB_S, SIDE_N, SIDE_S, PLATFORM,
        TA_N_mid, TA_S_mid, NB_N_tip, SB_N_tip, NB_S_tip, SB_S_tip,
    ]]

    struct = Structure(
        structure_id   = sid,
        structure_type = "station",
        cp_ids         = [cp_north.cp_id, cp_south.cp_id],
        node_ids       = all_node_ids,
        line_ids       = line_ids,
        center_lat     = center_lat,
        center_lon     = center_lon,
        heading_deg    = heading_deg,
    )

    cps = {cp_north.cp_id: cp_north, cp_south.cp_id: cp_south}

    net.build()
    return struct, cps


# ---------------------------------------------------------------------------
# Connect two ConnectionPoints
# ---------------------------------------------------------------------------

def connect_cps(
    net: Network,
    cp_a: ConnectionPoint,
    cp_b: ConnectionPoint,
    cps: Dict[str, ConnectionPoint],
) -> List[Line]:
    """
    Connect two stub-pairs:
      cp_a.outbound_tip ──→ cp_b.inbound_tip
      cp_b.outbound_tip ──→ cp_a.inbound_tip

    Returns the two new lines added.
    """
    lid_ab = _uid("CX")
    lid_ba = _uid("CX")

    l_ab = _line(net, lid_ab, cp_a.outbound_node, cp_b.inbound_node)
    l_ba = _line(net, lid_ba, cp_b.outbound_node, cp_a.inbound_node)

    cp_a.connected_to = cp_b.cp_id
    cp_b.connected_to = cp_a.cp_id

    net.build()
    return [l_ab, l_ba]


def disconnect_cp(
    net: Network,
    cp: ConnectionPoint,
    cps: Dict[str, ConnectionPoint],
):
    """Remove the lines connecting cp to its partner and clear connected_to."""
    if cp.connected_to is None:
        return
    partner = cps.get(cp.connected_to)

    # Remove lines between these two CPs
    to_remove = []
    for lid, line in net.lines.items():
        nodes = {line.start_node.node_id, line.end_node.node_id}
        cp_nodes = {cp.inbound_node.node_id, cp.outbound_node.node_id}
        partner_nodes = (
            {partner.inbound_node.node_id, partner.outbound_node.node_id}
            if partner else set()
        )
        if nodes & cp_nodes and nodes & partner_nodes:
            to_remove.append(lid)

    for lid in to_remove:
        del net.lines[lid]

    cp.connected_to = None
    if partner:
        partner.connected_to = None

    net.build()


# ---------------------------------------------------------------------------
# In-place rotation  (preserves all node/line/CP IDs)
# ---------------------------------------------------------------------------

def _update_line_lengths(net: Network, line_ids: List[str]):
    """Recompute length_m for each line after node positions have changed."""
    for lid in line_ids:
        if lid in net.lines:
            ln = net.lines[lid]
            ln.length_m = vincenty_m(
                ln.start_node.lat, ln.start_node.lon,
                ln.end_node.lat,   ln.end_node.lon,
            )


def rotate_station(
    net: Network,
    struct: Structure,
    cps_dict: Dict[str, "ConnectionPoint"],
    new_heading_deg: float,
):
    """
    Rotate a station to new_heading_deg without changing any IDs.
    Node lat/lon positions are recomputed from the stored center.
    Connector lines attached to the CPs automatically inherit the new positions
    because they hold references to the same Node objects.
    """
    sid  = struct.structure_id
    clat = struct.center_lat
    clon = struct.center_lon
    nb_h   = new_heading_deg
    east_h = (nb_h + 90) % 360
    half   = _STATION_LENGTH_M / 2
    W      = _STATION_WIDTH_M
    S      = _STUB_EXT_M

    # (fwd_m along NB, lat_m rightward) — centre = midpoint between NB and SB.
    # NB is W/2 right, SB is W/2 left, siding is 3W/2 right.
    # Stubs are symmetric: outbound (+W/2) and inbound (-W/2).
    offsets = {
        "NB_N":     ( half,       +W/2),
        "NB_S":     (-half,       +W/2),
        "SB_N":     ( half,       -W/2),
        "SB_S":     (-half,       -W/2),
        "SIDE_N":   ( half*0.4,  +3*W/2),
        "SIDE_S":   (-half*0.4,  +3*W/2),
        "PLATFORM": ( 0,         +3*W/2),
        "TA_N_mid": ( half,       0),
        "TA_S_mid": (-half,       0),
        "NB_N_tip": ( half + S,  +W/2),
        "SB_N_tip": ( half + S,  -W/2),
        "NB_S_tip": (-half - S,  +W/2),
        "SB_S_tip": (-half - S,  -W/2),
    }

    for suffix, (fwd_m, lat_m) in offsets.items():
        nid = f"{sid}.{suffix}"
        if nid in net.nodes:
            node = net.nodes[nid]
            lat, lon = _offset(clat, clon, nb_h,   fwd_m)
            lat, lon = _offset(lat,  lon,  east_h, lat_m)
            node.lat = lat
            node.lon = lon

    _update_line_lengths(net, struct.line_ids)

    # Update CP positions and headings
    sb_h = (nb_h + 180) % 360
    for cp_id in struct.cp_ids:
        cp = cps_dict.get(cp_id)
        if not cp:
            continue
        cp.heading_deg = nb_h if cp_id.endswith(".CP_N") else sb_h
        cp.center_lat  = (cp.inbound_node.lat + cp.outbound_node.lat) / 2
        cp.center_lon  = (cp.inbound_node.lon + cp.outbound_node.lon) / 2

    struct.heading_deg = new_heading_deg
    net.build()


def rotate_traffic_circle(
    net: Network,
    struct: Structure,
    cps_dict: Dict[str, "ConnectionPoint"],
    new_arm_headings: List[float],
):
    """
    Rotate a traffic circle to new arm headings without changing any IDs.
    All node positions are recomputed from the stored center.
    """
    assert len(new_arm_headings) == 4
    sid  = struct.structure_id
    clat = struct.center_lat
    clon = struct.center_lon
    arms = new_arm_headings

    for arm_idx in range(4):
        h       = arms[arm_idx]
        right_h = (h + 90) % 360
        left_h  = (h - 90) % 360
        total   = _CIRCLE_RADIUS_M + _STUB_LENGTH_M
        sp      = _STUB_SPACING_M / 2

        def _set(name, base_h, base_dist, side_h, side_dist):
            nid = f"{sid}.{name}"
            if nid in net.nodes:
                lat, lon = _offset(clat, clon, base_h, base_dist)
                lat, lon = _offset(lat, lon, side_h, side_dist)
                net.nodes[nid].lat = lat
                net.nodes[nid].lon = lon

        _set(f"A{arm_idx}_div",   h, _CIRCLE_RADIUS_M, right_h,  sp)
        _set(f"A{arm_idx}_merge", h, _CIRCLE_RADIUS_M, left_h,   sp)
        _set(f"A{arm_idx}_out",   h, total,            right_h,  sp)
        _set(f"A{arm_idx}_in",    h, total,            left_h,   sp)

    _update_line_lengths(net, struct.line_ids)

    # Update CP positions and headings
    for i, cp_id in enumerate(struct.cp_ids):
        cp = cps_dict.get(cp_id)
        if not cp:
            continue
        cp.heading_deg = arms[i]
        cp.center_lat  = (cp.inbound_node.lat + cp.outbound_node.lat) / 2
        cp.center_lon  = (cp.inbound_node.lon + cp.outbound_node.lon) / 2

    struct.arm_headings = list(new_arm_headings)
    net.build()
