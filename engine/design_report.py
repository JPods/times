"""
mesh_mobility.engine.design_report
==================================
Everything the design report says, as one dict. The printable page, the
Markdown copy and the JSON export are all rendered from this — never computed
separately.

  summary    design_summary(): counts, lengths, columns, solar
  segments   one row per connected CP pair, longest first
  coverage   area within walk / bike reach of a station
  stations   container station capacity (slot-limited upper bound)
  bom        bill of materials rows
  travel     last Run (travel times) if it matches the current network
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .network import Network, vincenty_m
from .structures import (
    ConnectionPoint, Structure, design_summary,
    STATION_SLOTS, STATION_LIFTS, SLOT_PODS_PER_HR, WALK_M, BIKE_M,
    _COLUMN_SPACING_M, _M_PER_MILE,
)

_COST_PER_ROUTE_MI_M = 20.0   # $M per guideway mile (Bill 2026-10-22: route miles)
_STATION_COST_M      = 2.0    # container station, planning placeholder
_CIRCLE_COST_M       = 0.5
_PODS_PER_STATION    = 4
_POD_COST_M          = 0.05
_COVERAGE_CELL_M     = 100.0


def network_signature(net: Network) -> list:
    """Changes whenever the guideway changes — used to tell a stale Run."""
    return [len(net.lines), round(net.total_length_m())]


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------

def _segment_length_m(cp: ConnectionPoint, partner: ConnectionPoint,
                      internal: set) -> Optional[float]:
    """Walk cp.outbound → partner.inbound along connecting (non-internal) lines."""
    node, total = cp.outbound_node, 0.0
    for _ in range(10_000):
        if node is partner.inbound_node or node.node_id == partner.inbound_node.node_id:
            return total
        nxt = [l for l in node.outbound if l.line_id not in internal]
        if len(nxt) != 1:
            return None
        total += nxt[0].length_m
        node = nxt[0].end_node
    return None


def segments(net: Network, structures: Dict[str, Structure],
             cps: Dict[str, ConnectionPoint]) -> List[dict]:
    internal = set()
    for s in structures.values():
        internal.update(s.line_ids)
    rows = []
    for cp in cps.values():
        partner = cps.get(cp.connected_to) if cp.connected_to else None
        if partner is None or cp.cp_id > partner.cp_id:
            continue
        length_m = _segment_length_m(cp, partner, internal)
        if length_m is None:
            continue
        rows.append({
            "from":      cp.structure_id,
            "to":        partner.structure_id,
            "length_m":  round(length_m),
            "length_mi": round(length_m / _M_PER_MILE, 2),
            "columns":   round(length_m / _COLUMN_SPACING_M),
        })
    rows.sort(key=lambda r: -r["length_m"])
    return rows


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

def _hull(pts):
    """Monotone-chain convex hull of (x, y) points, CCW."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _in_hull(hull, x, y) -> bool:
    n = len(hull)
    for i in range(n):
        (x1, y1), (x2, y2) = hull[i], hull[(i + 1) % n]
        if (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1) < 0:
            return False
    return True


def coverage(structures: Dict[str, Structure]) -> dict:
    """Area within walk / bike reach of any station, and the share of the
    network's footprint (convex hull of all structures) that it covers."""
    st = [s for s in structures.values() if s.structure_type == "station"]
    allpts = [(s.center_lat, s.center_lon) for s in structures.values()]
    out = {"walk_m": WALK_M, "bike_m": BIKE_M, "walk_km2": 0.0, "bike_km2": 0.0,
           "footprint_km2": 0.0, "walk_pct": None, "bike_pct": None}
    if not st:
        return out
    lat0 = sum(p[0] for p in allpts) / len(allpts)
    lon0 = sum(p[1] for p in allpts) / len(allpts)
    my = 111_320.0
    mx = 111_320.0 * math.cos(math.radians(lat0))
    xy = lambda lat, lon: ((lon - lon0) * mx, (lat - lat0) * my)
    c = _COVERAGE_CELL_M
    walk, bike = set(), set()
    rw, rb = int(WALK_M // c) + 1, int(BIKE_M // c) + 1
    for s in st:
        sx, sy = xy(s.center_lat, s.center_lon)
        ci, cj = round(sx / c), round(sy / c)
        for i in range(ci - rb, ci + rb + 1):
            dx = i * c - sx
            for j in range(cj - rb, cj + rb + 1):
                d2 = dx * dx + (j * c - sy) ** 2
                if d2 <= BIKE_M * BIKE_M:
                    bike.add((i, j))
                    if d2 <= WALK_M * WALK_M:
                        walk.add((i, j))
    cell_km2 = (c / 1000) ** 2
    out["walk_km2"] = round(len(walk) * cell_km2, 1)
    out["bike_km2"] = round(len(bike) * cell_km2, 1)
    hull = _hull([xy(*p) for p in allpts])
    if len(hull) >= 3:
        xs, ys = [p[0] for p in hull], [p[1] for p in hull]
        inside = [(i, j)
                  for i in range(math.floor(min(xs) / c), math.ceil(max(xs) / c) + 1)
                  for j in range(math.floor(min(ys) / c), math.ceil(max(ys) / c) + 1)
                  if _in_hull(hull, i * c, j * c)]
        if inside:
            out["footprint_km2"] = round(len(inside) * cell_km2, 1)
            out["walk_pct"] = round(100 * sum(1 for k in inside if k in walk) / len(inside))
            out["bike_pct"] = round(100 * sum(1 for k in inside if k in bike) / len(inside))
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def design_report(net: Network, structures: Dict[str, Structure],
                  cps: Dict[str, ConnectionPoint],
                  travel: Optional[dict] = None, city_label: str = "") -> dict:
    s = design_summary(net, structures)
    n_st, n_tc = s["station_count"], s["circle_count"]
    pods = n_st * _PODS_PER_STATION
    bom = [
        {"item": "Guideway (dual beam, solar panels, columns)",
         "qty": f"{s['route_miles']} mi ({s['route_km']} km)",
         "unit": f"${_COST_PER_ROUTE_MI_M:.0f}M/mi",
         "total_m": round(s["route_miles"] * _COST_PER_ROUTE_MI_M, 1)},
        {"item": f"Container stations ({STATION_SLOTS} slots, {STATION_LIFTS} lifts)",
         "qty": n_st, "unit": f"~${_STATION_COST_M:.0f}M ea",
         "total_m": round(n_st * _STATION_COST_M, 1)},
        {"item": "Traffic circles (junction structures)",
         "qty": n_tc, "unit": f"~${_CIRCLE_COST_M}M ea",
         "total_m": round(n_tc * _CIRCLE_COST_M, 1)},
        {"item": f"Vehicles (pods, {_PODS_PER_STATION} per station initial fleet)",
         "qty": pods, "unit": f"~${_POD_COST_M * 1000:.0f}K ea",
         "total_m": round(pods * _POD_COST_M, 1)},
    ]
    if travel and travel.get("signature") != network_signature(net):
        travel = None
    return {
        "network_id":    net.network_id or "Untitled",
        "city_label":    city_label,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary":       s,
        "segments":      segments(net, structures, cps),
        "coverage":      coverage(structures),
        "stations": {
            "slots": STATION_SLOTS, "lifts": STATION_LIFTS,
            "slot_pods_per_hr": SLOT_PODS_PER_HR,
            "station_pods_per_hr_max": STATION_SLOTS * SLOT_PODS_PER_HR,
            "network_pods_per_hr_max": n_st * STATION_SLOTS * SLOT_PODS_PER_HR,
            "lift_limited": True,
        },
        "bom":           bom,
        "bom_total_m":   round(sum(r["total_m"] for r in bom), 1),
        "travel":        travel,
    }
