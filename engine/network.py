"""
route_time.engine.network
=========================
Domain model: Network, Node, Line, Station.

Vocabulary:
  - Node     : a Switch or Station in the .jpd / map.json graph
  - Line     : a directed edge from one Node to another (one-way travel segment)
  - Station  : a Node that generates and absorbs passenger demand
  - Network  : the full graph — a dict of Lines indexed by line_id

"Parallel" is not used here.  Two Lines sharing start/end nodes are
alternate lines.  See PRINCIPLES.md vocabulary note.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Geography helpers
# ---------------------------------------------------------------------------

_R_EARTH_M = 6_371_000.0  # mean Earth radius, metres


def vincenty_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Approximate great-circle distance in metres (haversine; sufficient for planning)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _R_EARTH_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

@dataclass
class Node:
    node_id: str
    lat: float
    lon: float
    is_station: bool = False

    # outbound lines from this node (populated by Network.build())
    outbound: List["Line"] = field(default_factory=list, repr=False)
    # inbound lines to this node
    inbound: List["Line"] = field(default_factory=list, repr=False)

    def __hash__(self):
        return hash(self.node_id)

    def __eq__(self, other):
        return isinstance(other, Node) and self.node_id == other.node_id


# ---------------------------------------------------------------------------
# Station
# ---------------------------------------------------------------------------

@dataclass
class Station:
    station_id: str
    node: Node
    # pods currently queued here (waiting for passengers or holding)
    queued_pods: List["Pod"] = field(default_factory=list, repr=False)

    @property
    def lat(self) -> float:
        return self.node.lat

    @property
    def lon(self) -> float:
        return self.node.lon


# ---------------------------------------------------------------------------
# Line
# ---------------------------------------------------------------------------

_JAMMED_POD_THRESHOLD = 4   # >4 pods on the line
_JAMMED_SPACING_M     = 8   # <8m per pod → jammed (recomputed by Simulator from settings)

MAX_WEIGHT = float("inf")


def configure_jam_threshold(min_headway_s: float, max_velocity_kmph: float,
                             pod_len_m: float = 3.0):
    """
    Set the jam-spacing threshold from physics settings.

    min_spacing = (max_velocity × min_headway) + pod_length
    At 60 km/h and 0.25s headway:  16.67 m/s × 0.25 + 3 = 7.17 m
    """
    global _JAMMED_SPACING_M
    v_ms = max_velocity_kmph * 1000.0 / 3600.0
    _JAMMED_SPACING_M = v_ms * min_headway_s + pod_len_m


@dataclass
class Line:
    line_id: str
    start_node: Node
    end_node: Node
    length_m: float                          # geodetic metres
    coordinates: List[tuple] = field(default_factory=list, repr=False)  # [(lat, lon), ...]

    # If set, this line is a station access line (exit, platform, re-entry).
    # Routing must not use it as a through-route for other stations.
    station_access_id: Optional[str] = field(default=None, repr=False)

    # runtime state (reset each simulation run)
    pods_on_line: List["Pod"] = field(default_factory=list, repr=False)

    # per-run transit time samples (ms) collected during simulation
    transit_samples_ms: List[float] = field(default_factory=list, repr=False)

    @property
    def length_mm(self) -> float:
        return self.length_m * 1000

    def is_jammed(self) -> bool:
        n = len(self.pods_on_line)
        if n == 0:
            return False
        return n > _JAMMED_POD_THRESHOLD and (self.length_m / n) < _JAMMED_SPACING_M

    def get_weight(self) -> float:
        return MAX_WEIGHT if self.is_jammed() else self.length_m

    def is_converging(self) -> bool:
        """True if another line also ends at this line's end_node (ezone candidate)."""
        return len(self.end_node.inbound) > 1

    def is_diverging(self) -> bool:
        """True if this line's start_node has multiple outbound lines (switch)."""
        return len(self.start_node.outbound) > 1

    def reset(self):
        self.pods_on_line.clear()
        self.transit_samples_ms.clear()

    def record_transit(self, elapsed_ms: float):
        self.transit_samples_ms.append(elapsed_ms)

    def fleet_median_ms(self) -> Optional[float]:
        s = sorted(self.transit_samples_ms)
        n = len(s)
        if n == 0:
            return None
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    def fleet_mean_ms(self) -> Optional[float]:
        if not self.transit_samples_ms:
            return None
        return sum(self.transit_samples_ms) / len(self.transit_samples_ms)

    def fleet_p90_ms(self) -> Optional[float]:
        s = sorted(self.transit_samples_ms)
        if not s:
            return None
        idx = min(int(len(s) * 0.9), len(s) - 1)
        return s[idx]


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

@dataclass
class Network:
    network_id: str
    nodes: Dict[str, Node] = field(default_factory=dict)
    lines: Dict[str, Line] = field(default_factory=dict)
    stations: Dict[str, Station] = field(default_factory=dict)

    def build(self):
        """Populate outbound/inbound adjacency on every Node."""
        for node in self.nodes.values():
            node.outbound.clear()
            node.inbound.clear()
        for line in self.lines.values():
            line.start_node.outbound.append(line)
            line.end_node.inbound.append(line)

    def reset(self):
        """Clear runtime state for a fresh simulation run."""
        for line in self.lines.values():
            line.reset()
        for station in self.stations.values():
            station.queued_pods.clear()

    def total_length_m(self) -> float:
        return sum(l.length_m for l in self.lines.values())

    def station_list(self) -> List[Station]:
        return list(self.stations.values())

    def __repr__(self):
        return (
            f"Network({self.network_id!r}, "
            f"nodes={len(self.nodes)}, lines={len(self.lines)}, "
            f"stations={len(self.stations)}, "
            f"total_km={self.total_length_m()/1000:.2f})"
        )
