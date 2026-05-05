"""
route_time.engine.routing
=========================
Dijkstra on the Line graph.

Edge weight = line.get_weight() (length_m, or inf if jammed).
graceDistance (Java: small bias to prefer shorter hops) is supported but
defaults to 0.

Returns a list of Lines from source_node to target_node,
or an empty list if no path exists.
"""

from __future__ import annotations

import heapq
from typing import Dict, List, Optional

from .network import Line, Network, Node, MAX_WEIGHT


def find_path(
    network: Network,
    source: Node,
    target: Node,
    grace_distance: float = 0.0,
    jam_free: bool = False,
) -> List[Line]:
    """
    Dijkstra shortest path.

    Returns ordered list of Lines from source → target.
    Returns [] if no path exists (disconnected or all routes jammed).

    jam_free=True: use line.length_m directly, ignoring jam weight.
    Use this for sweep passengers so they always find a topological route
    even when lines are temporarily congested.

    Station access rule: lines tagged with station_access_id are only
    traversable when their station is the source or target station.
    This prevents through-vehicles from bypassing a jammed through-guideway
    by cutting through an intermediate station's platform.
    """
    # Determine which station access IDs are permitted on this trip.
    # A line is permitted if its station_access_id matches the source or
    # target station (identified by the node's station membership).
    _src_sid = _station_id_of(network, source)
    _tgt_sid = _station_id_of(network, target)
    _allowed_access = {s for s in (_src_sid, _tgt_sid) if s is not None}

    # dist[node_id] = best known cost to reach that node
    dist: Dict[str, float] = {source.node_id: 0.0}
    # prev[node_id] = (arriving_line, previous_node_id)
    prev: Dict[str, tuple] = {}

    # priority queue: (cost, node_id)
    pq = [(0.0, source.node_id)]

    while pq:
        cost, nid = heapq.heappop(pq)
        if cost > dist.get(nid, MAX_WEIGHT):
            continue

        node = network.nodes[nid]
        if node is target:
            break

        for line in node.outbound:
            # Skip station access lines that belong to a different station
            if (line.station_access_id is not None and
                    line.station_access_id not in _allowed_access):
                continue
            if jam_free:
                w = max(line.length_m, 0.001) + grace_distance
            else:
                w = line.get_weight() + grace_distance
                if w >= MAX_WEIGHT:
                    continue
            new_cost = cost + w
            nxt = line.end_node.node_id
            if new_cost < dist.get(nxt, MAX_WEIGHT):
                dist[nxt] = new_cost
                prev[nxt] = (line, nid)
                heapq.heappush(pq, (new_cost, nxt))

    # Reconstruct path
    if target.node_id not in prev and source is not target:
        return []

    path: List[Line] = []
    cur = target.node_id
    while cur in prev:
        line, pred = prev[cur]
        path.append(line)
        cur = pred
    path.reverse()
    return path


def _station_id_of(network: Network, node: Node) -> Optional[str]:
    """
    Return the station structure ID that owns this node, or None.

    Station platform nodes are named "<sid>.PLATFORM".  This extracts
    the structure ID prefix so we know which access lines are permitted.
    """
    nid = node.node_id
    # Direct platform match: "ST001.PLATFORM"
    if nid in network.stations:
        dot = nid.rfind(".")
        if dot > 0:
            return nid[:dot]
    # Siding nodes share the same prefix: "ST001.SIDE_N", "ST001.SIDE_S"
    dot = nid.rfind(".")
    if dot > 0:
        return nid[:dot]
    return None


def find_path_by_id(
    network: Network,
    source_id: str,
    target_id: str,
    grace_distance: float = 0.0,
) -> List[Line]:
    src = network.nodes.get(source_id)
    tgt = network.nodes.get(target_id)
    if src is None or tgt is None:
        return []
    return find_path(network, src, tgt, grace_distance)
