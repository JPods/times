"""
mesh_mobility.gui.noelle_api
==============================
Noelle network analysis endpoints: draft, refine, review, report, QA.
Also: network/describe, network/report, ai/recommend.

Extracted from api.py in Round 3 refactoring (2026-07-15).
"""

from __future__ import annotations

import itertools
import json
import logging
import math
import os
import random
import re as _re_road
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from flask import Blueprint, jsonify, request, Response

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

from mesh_mobility.engine import Network
from mesh_mobility.engine.network import vincenty_m
from mesh_mobility.engine.structures import (
    build_traffic_circle, build_station, connect_cps,
    ConnectionPoint, Structure,
)

# ---------------------------------------------------------------------------
# Shared state imports
# ---------------------------------------------------------------------------
from mesh_mobility.gui.state import (
    _state, _net,
    ensure_session, set_session_cookie, auto_push_undo,
    push_undo, clear_edit_state, next_sid, sync_counters,
    noelle_log, cp_by_heading,
)

# ---------------------------------------------------------------------------
# Builder imports (auto-connect for wild_guess)
# ---------------------------------------------------------------------------
from mesh_mobility.gui.builders import _best_effort_connect

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
noelle = Blueprint("noelle", __name__, url_prefix="/api")

noelle.before_request(ensure_session)
noelle.after_request(set_session_cookie)
noelle.before_request(auto_push_undo)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1, lon1, lat2, lon2):
    """Fast haversine distance in metres."""
    R = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _classify_road(name):
    """Classify road type from naming conventions across US DOTs."""
    n = name.strip().upper()
    if _re_road.match(r"^I[\s\-]?\d", n):
        return "Interstate"
    if _re_road.match(r"^US[\s\-]?\d", n):
        return "Highway"
    if _re_road.match(
        r"^(SH|SR|MN|CA|TX|FL|OH|OK|SC|NY|IL|PA|GA|NC|VA|WA|OR|CO|AZ|NV|NJ|MA|MD|CT|WI|IN|MO|TN|KY|AL|LA|MS|AR|KS|NE|IA|UT|NM|WV|ID|HI|ME|NH|RI|DE|MT|ND|SD|WY|VT|AK|DC|IH|FM|TL)[\s\-]?\d", n):
        return "Highway"
    if n == "LOCAL ROAD":
        return "Local/Arterial"
    if _re_road.match(r"^(CSAH|MSAS|CR|CO\s*RD|COUNTY)", n):
        return "Local/Arterial"
    return "Local/Arterial"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def _noelle_analyze(aadt_path, acc_path):
    """Analyse AADT + accident overlays and return a structured proposal.

    Returns dict with: stations list, crash_rates table, summary text,
    highway_boundaries, and mesh_analysis.
    """
    with open(aadt_path) as f:
        aadt_geo = json.load(f)
    with open(acc_path) as f:
        acc_geo = json.load(f)

    # ── All AADT points ──
    all_pts = []
    for feat in aadt_geo.get("features", []):
        p = feat["properties"]
        lon, lat = feat["geometry"]["coordinates"]
        all_pts.append({"road": p.get("road", "Unknown"),
                        "lat": lat, "lon": lon, "aadt": p.get("aadt", 0)})

    # ── All accident points ──
    acc_pts = []
    for feat in acc_geo.get("features", []):
        lon, lat = feat["geometry"]["coordinates"]
        ped = feat["properties"].get("pedestrian", False)
        acc_pts.append({"lat": lat, "lon": lon, "pedestrian": ped})

    # ── Classify road type ──
    roads_by_name = defaultdict(list)
    for pt in all_pts:
        roads_by_name[pt["road"]].append(pt)

    crash_rates = []
    for road, segs in roads_by_name.items():
        if road == "Unknown":
            continue
        avg_aadt = sum(s["aadt"] for s in segs) / len(segs)
        crashes = set()
        ped_crashes = set()
        for i, a in enumerate(acc_pts):
            for s in segs:
                if _haversine_m(a["lat"], a["lon"], s["lat"], s["lon"]) < 400:
                    crashes.add(i)
                    if a["pedestrian"]:
                        ped_crashes.add(i)
                    break
        if not crashes:
            continue
        rtype = _classify_road(road)
        rate = len(crashes) / (avg_aadt / 10_000) if avg_aadt > 0 else 0
        crash_rates.append({
            "road": road, "type": rtype, "avg_aadt": int(avg_aadt),
            "crashes": len(crashes), "ped_crashes": len(ped_crashes),
            "rate_per_10k": round(rate, 2),
        })
    crash_rates.sort(key=lambda x: -x["rate_per_10k"])

    # ── Crash rate summary by type ──
    type_totals = defaultdict(lambda: {"crashes": 0, "ped": 0,
                                       "aadt_sum": 0, "count": 0})
    for r in crash_rates:
        t = type_totals[r["type"]]
        t["crashes"] += r["crashes"]
        t["ped"] += r["ped_crashes"]
        t["aadt_sum"] += r["avg_aadt"]
        t["count"] += 1
    crash_rate_summary = []
    for rtype in ["Local/Arterial", "Highway", "Interstate", "State Route"]:
        t = type_totals.get(rtype)
        if not t or t["count"] == 0:
            continue
        avg = t["aadt_sum"] / t["count"]
        rate = t["crashes"] / (avg / 10_000) if avg > 0 else 0
        crash_rate_summary.append({
            "type": rtype, "crashes": t["crashes"],
            "ped_crashes": t["ped"],
            "avg_aadt": int(avg),
            "rate_per_10k": round(rate, 1),
        })

    # ── Detect arterial grid from local-road AADT clusters ──
    local_pts = [p for p in all_pts
                 if _classify_road(p["road"]) == "Local/Arterial"
                 and p["aadt"] >= 5000]
    all_lats = [p["lat"] for p in all_pts]
    all_lons = [p["lon"] for p in all_pts]
    if not all_lats:
        return {"error": "No AADT data found"}
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)

    # Cluster local-road points into N-S bands (by longitude, 0.012° ≈ 1 km)
    ns_bands = defaultdict(list)
    for p in local_pts:
        band = round(p["lon"] / 0.012) * 0.012
        ns_bands[band].append(p)
    ns_corridors = sorted([lon for lon, pts in ns_bands.items()
                           if len(pts) >= 3])

    # Cluster into E-W bands (by latitude, 0.012° ≈ 1.3 km)
    ew_bands = defaultdict(list)
    for p in local_pts:
        band = round(p["lat"] / 0.012) * 0.012
        ew_bands[band].append(p)
    ew_corridors = sorted([lat for lat, pts in ew_bands.items()
                           if len(pts) >= 3], reverse=True)

    # ── Helper: accident and AADT lookup ──
    def accidents_near(lat, lon, radius=600):
        return sum(1 for a in acc_pts
                   if _haversine_m(lat, lon, a["lat"], a["lon"]) < radius)

    def local_aadt_near(lat, lon, radius=500):
        best = 0
        for p in local_pts:
            if _haversine_m(lat, lon, p["lat"], p["lon"]) < radius:
                best = max(best, p["aadt"])
        return best

    # ── Place stations at grid intersections with signal ──
    stations = []
    for ew_lat in ew_corridors:
        for ns_lon in ns_corridors:
            crashes = accidents_near(ew_lat, ns_lon)
            aadt = local_aadt_near(ew_lat, ns_lon)
            if crashes >= 1 or aadt >= 5000:
                stations.append({
                    "name": f"Grid ({ew_lat:.3f}, {ns_lon:.3f})",
                    "lat": round(ew_lat, 6), "lon": round(ns_lon, 6),
                    "crashes": crashes, "aadt": aadt,
                    "source": "grid",
                })

    # ── Add off-grid accident hotspots ──
    acc_grid = defaultdict(lambda: {"count": 0, "lat_sum": 0, "lon_sum": 0,
                                    "ped": 0})
    for a in acc_pts:
        key = (round(a["lat"] / 0.005) * 0.005,
               round(a["lon"] / 0.005) * 0.005)
        acc_grid[key]["count"] += 1
        acc_grid[key]["lat_sum"] += a["lat"]
        acc_grid[key]["lon_sum"] += a["lon"]
        if a["pedestrian"]:
            acc_grid[key]["ped"] += 1

    for key, v in sorted(acc_grid.items(), key=lambda x: -x[1]["count"]):
        if v["count"] >= 3:
            lat = v["lat_sum"] / v["count"]
            lon = v["lon_sum"] / v["count"]
            if not any(_haversine_m(lat, lon, s["lat"], s["lon"]) < 400
                       for s in stations):
                aadt = local_aadt_near(lat, lon)
                stations.append({
                    "name": f"Accident cluster ({v['count']} crashes"
                            f", {v['ped']} ped)",
                    "lat": round(lat, 6), "lon": round(lon, 6),
                    "crashes": v["count"], "aadt": aadt,
                    "source": "accident_cluster",
                })

    stations.sort(key=lambda x: (-x["crashes"], -x["aadt"]))

    # ── Highway boundaries ──
    hwy_boundaries = []
    hwy_road_names = sorted(r for r in roads_by_name
                            if _classify_road(r) in ("Interstate", "Highway"))
    for road_name in hwy_road_names:
        pts = roads_by_name.get(road_name, [])
        if not pts:
            continue
        lats = [p["lat"] for p in pts]
        lons = [p["lon"] for p in pts]
        max_aadt = max(p["aadt"] for p in pts)
        hwy_boundaries.append({
            "road": road_name,
            "lat_range": [round(min(lats), 4), round(max(lats), 4)],
            "lon_range": [round(min(lons), 4), round(max(lons), 4)],
            "max_aadt": max_aadt,
        })

    # ── Top intersections ──
    top_3 = stations[:3]

    # ── Build summary ──
    crash_stations = sum(1 for s in stations if s["crashes"] >= 1)
    traffic_stations = sum(1 for s in stations if s["crashes"] == 0)
    grid_stations = sum(1 for s in stations if s["source"] == "grid")
    cluster_stations = sum(1 for s in stations
                           if s["source"] == "accident_cluster")
    total_acc = len(acc_pts)
    total_ped = sum(1 for a in acc_pts if a["pedestrian"])

    summary_lines = [
        f"{len(stations)} stations, zero circles. "
        f"All on the arterial grid, none on highways.",
        "",
        "The proposal follows two rules:",
        f"- Crash signal: {crash_stations} stations where people are "
        f"dying within 600m",
        f"- Traffic signal: {traffic_stations} stations on grid "
        f"intersections with 5K+ AADT on local roads",
        "",
    ]
    if top_3:
        top_parts = []
        for s in top_3:
            aadt_str = (f"{s['aadt']/1000:.1f}K AADT"
                        if s["aadt"] >= 1000 else f"{s['aadt']} AADT")
            top_parts.append(f"{s['name']} ({s['crashes']} crashes"
                             f", {aadt_str})")
        summary_lines.append("Hottest intersections: "
                             + "; ".join(top_parts))
        summary_lines.append("")

    if hwy_boundaries:
        hwy_names = ", ".join(h["road"] for h in hwy_boundaries[:6])
        summary_lines.append(f"Highways as boundaries only — {hwy_names} "
                             f"frame the neighborhoods but get no stations.")
        summary_lines.append("")

    if crash_rate_summary:
        local = next((c for c in crash_rate_summary
                      if c["type"] == "Local/Arterial"), None)
        interstate = next((c for c in crash_rate_summary
                           if c["type"] == "Interstate"), None)
        if local and interstate and interstate["rate_per_10k"] > 0:
            ratio = local["rate_per_10k"] / interstate["rate_per_10k"]
            summary_lines.append(
                f"Local arterials are {ratio:.0f}× more dangerous per "
                f"unit of traffic than interstates.")
            summary_lines.append(
                f"They carry {local['ped_crashes']} of {total_ped} "
                f"pedestrian fatalities — people are walking on "
                f"these roads and dying.")

    return {
        "stations": stations,
        "crash_rate_summary": crash_rate_summary,
        "crash_rates": crash_rates[:20],
        "highway_boundaries": hwy_boundaries,
        "grid": {
            "ns_corridors": len(ns_corridors),
            "ew_corridors": len(ew_corridors),
            "grid_stations": grid_stations,
            "cluster_stations": cluster_stations,
        },
        "data_summary": {
            "aadt_features": len(aadt_geo.get("features", [])),
            "accident_features": total_acc,
            "pedestrian_accidents": total_ped,
        },
        "summary": "\n".join(summary_lines),
    }


# ---------------------------------------------------------------------------
# Noelle QA
# ---------------------------------------------------------------------------

def _default_qa():
    return {
        "questions": [
            {"id": "bike_trails", "q": "Where are the major bike/walking trails?", "a": ""},
            {"id": "event_venues", "q": "Any large event venues (stadiums, fairgrounds, convention centers)?", "a": ""},
            {"id": "campuses", "q": "University campuses or hospital complexes?", "a": ""},
            {"id": "transit_hubs", "q": "Transit hubs (bus stations, commuter rail, airports)?", "a": ""},
            {"id": "one_sided", "q": "Riverfronts, lakefronts, or other one-sided amenities worth connecting?", "a": ""},
            {"id": "commercial", "q": "Major shopping centers or commercial districts not on main roads?", "a": ""},
            {"id": "barriers", "q": "Linear barriers besides highways (rail lines, rivers, canals)?", "a": ""},
            {"id": "growth", "q": "Areas of new development or planned growth?", "a": ""},
        ],
    }


@noelle.get("/noelle/qa")
def get_qa():
    """Return Noelle's questions and any designer answers."""
    return jsonify(_state.get("qa") or _default_qa())


@noelle.post("/noelle/qa")
def save_qa():
    """Save designer's answers to Noelle's questions."""
    _state["qa"] = request.json or {}
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# AI recommendations (Allie)
# ---------------------------------------------------------------------------

@noelle.post("/ai/recommend")
def ai_recommend():
    """
    Send network parameters to Allie for network recommendations.
    Allie returns candidate networks + explanation text.

    For now: returns a structured placeholder.
    When Allie's wcapi endpoint is configured, this proxies to her.
    """
    data = request.json or {}
    # TODO: proxy to Allie's wcapi endpoint when configured
    return jsonify({
        "summary": "Allie not yet connected",
        "explanation": (
            "To connect Allie:\n"
            "1. Set ALLIE_URL environment variable to Allie's wcapi address.\n"
            "2. Allie will analyse the map bounds, station count, and budget\n"
            "   to recommend an optimised network topology.\n"
            "3. As simulation results accumulate, recommendations improve\n"
            "   based on fleet-median transit times and demand patterns."
        ),
        "options": [],
        "network": None,
    })


# ---------------------------------------------------------------------------
# Network descriptor (Noelle's view)
# ---------------------------------------------------------------------------

@noelle.get("/network/describe")
def describe_network():
    """Generate a structured description of the current network for Noelle.

    Returns topology, spatial layout, quality metrics, and a natural-language
    summary that can be indexed into a vector store.
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    structs_raw = _state.get("structures", {})
    # Normalize: Structure dataclass objects → dicts
    structs = {}
    for sid, s in structs_raw.items():
        structs[sid] = s.to_dict() if hasattr(s, "to_dict") else s

    cps_list = _state.get("cps", {})
    if isinstance(cps_list, list):
        cps_map = {}
        for cp in cps_list:
            d = cp.to_dict() if hasattr(cp, "to_dict") else cp
            cps_map[d["cp_id"]] = d
    elif isinstance(cps_list, dict):
        cps_map = {}
        for k, cp in cps_list.items():
            cps_map[k] = cp.to_dict() if hasattr(cp, "to_dict") else cp
    else:
        cps_map = {}

    # Classify structures
    stations = {}
    circles = {}
    for sid, s in structs.items():
        if s.get("structure_type") == "station":
            stations[sid] = s
        else:
            circles[sid] = s

    # Spatial metrics
    all_lats = [s["center_lat"] for s in structs.values()]
    all_lons = [s["center_lon"] for s in structs.values()]
    if not all_lats:
        return jsonify({"error": "Empty network"}), 400

    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)
    lat_span = max(all_lats) - min(all_lats)
    lon_span = max(all_lons) - min(all_lons)
    ns_km = lat_span * 111.0
    ew_km = lon_span * 111.0 * math.cos(math.radians(center_lat))

    # Connection analysis
    open_cps = []
    connected_cps = []
    for cp in cps_map.values():
        cp_id = cp["cp_id"]
        if cp.get("connected_to"):
            connected_cps.append(cp_id)
        else:
            open_cps.append(cp_id)

    # Structure spacing — distances between all pairs (sample if large)
    pair_dists = []
    struct_items = list(structs.items())
    pairs = list(itertools.combinations(struct_items, 2))
    if len(pairs) > 5000:
        pairs = random.sample(pairs, 5000)
    for (sid_a, sa), (sid_b, sb) in pairs:
        dlat = sa["center_lat"] - sb["center_lat"]
        dlon = (sa["center_lon"] - sb["center_lon"]) * math.cos(math.radians(center_lat))
        d_km = math.sqrt(dlat**2 + dlon**2) * 111.0
        pair_dists.append(d_km)

    # Nearest-neighbor for each structure
    nn_dists = []
    for sid_a, sa in struct_items:
        best = float("inf")
        for sid_b, sb in struct_items:
            if sid_a == sid_b:
                continue
            dlat = sa["center_lat"] - sb["center_lat"]
            dlon = (sa["center_lon"] - sb["center_lon"]) * math.cos(math.radians(center_lat))
            d = math.sqrt(dlat**2 + dlon**2) * 111.0
            if d < best:
                best = d
        if best < float("inf"):
            nn_dists.append(best)

    # Orphan detection — structures with ALL CPs open
    orphan_sids = []
    for sid, s in structs.items():
        cp_ids = s.get("cp_ids", [])
        if cp_ids and all(cpid in [c for c in open_cps] for cpid in cp_ids):
            orphan_sids.append(sid)

    # Build neighbor map — which structures connect to which
    neighbors = {}  # sid → set of neighbor sids
    for cp in cps_map.values():
        conn = cp.get("connected_to")
        struct_id = cp.get("structure_id")
        if conn and struct_id:
            conn_obj = cps_map.get(conn)
            if conn_obj:
                conn_struct = conn_obj.get("structure_id")
                if conn_struct:
                    neighbors.setdefault(struct_id, set()).add(conn_struct)
                    neighbors.setdefault(conn_struct, set()).add(struct_id)

    # Degree distribution
    degrees = {sid: len(neighbors.get(sid, set())) for sid in structs}
    degree_counts = {}
    for d in degrees.values():
        degree_counts[d] = degree_counts.get(d, 0) + 1

    # Connected components (BFS)
    visited = set()
    components = []
    for sid in structs:
        if sid in visited:
            continue
        comp = set()
        queue = [sid]
        while queue:
            s = queue.pop()
            if s in visited:
                continue
            visited.add(s)
            comp.add(s)
            for nb in neighbors.get(s, set()):
                if nb not in visited:
                    queue.append(nb)
        components.append(comp)

    # Natural-language summary
    nn_avg = sum(nn_dists) / len(nn_dists) * 1000 if nn_dists else 0  # meters
    nn_min = min(nn_dists) * 1000 if nn_dists else 0
    nn_max = max(nn_dists) * 1000 if nn_dists else 0

    summary_lines = [
        f"Network '{_state.get('network', net).network_id}' centered at ({center_lat:.4f}, {center_lon:.4f}).",
        f"Coverage: {ns_km:.1f} km N-S × {ew_km:.1f} km E-W.",
        f"Structures: {len(stations)} stations, {len(circles)} traffic circles ({len(structs)} total).",
        f"CPs: {len(connected_cps)} connected, {len(open_cps)} open.",
        f"Orphaned structures (all CPs open): {len(orphan_sids)}.",
        f"Connected components: {len(components)} (largest: {max(len(c) for c in components)} structures).",
        f"Nearest-neighbor spacing: avg {nn_avg:.0f} m, min {nn_min:.0f} m, max {nn_max:.0f} m.",
        f"Degree distribution: {dict(sorted(degree_counts.items()))}.",
    ]
    if orphan_sids:
        summary_lines.append(f"Orphans: {', '.join(orphan_sids[:20])}{'...' if len(orphan_sids) > 20 else ''}.")

    # Structure list with relative positions
    struct_descs = []
    for sid, s in structs.items():
        stype = s.get("structure_type", "unknown")
        lat, lon = s["center_lat"], s["center_lon"]
        deg = degrees.get(sid, 0)
        nbs = sorted(neighbors.get(sid, set()))
        struct_descs.append({
            "id": sid,
            "type": stype,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "heading": s.get("heading_deg", 0),
            "connections": deg,
            "neighbors": nbs,
            "open_cps": [cpid for cpid in s.get("cp_ids", []) if cpid in open_cps],
        })

    return jsonify({
        "network_id": getattr(_state.get("network", net), "network_id", "untitled"),
        "summary": "\n".join(summary_lines),
        "spatial": {
            "center": [round(center_lat, 6), round(center_lon, 6)],
            "extent_km": [round(ns_km, 2), round(ew_km, 2)],
            "nn_spacing_m": {
                "avg": round(nn_avg, 0),
                "min": round(nn_min, 0),
                "max": round(nn_max, 0),
            },
        },
        "topology": {
            "stations": len(stations),
            "circles": len(circles),
            "connected_cps": len(connected_cps),
            "open_cps": len(open_cps),
            "orphans": orphan_sids,
            "components": len(components),
            "largest_component": max(len(c) for c in components),
            "degree_distribution": dict(sorted(degree_counts.items())),
        },
        "structures": struct_descs,
    })


# ---------------------------------------------------------------------------
# Noelle Draft — data-driven station proposal
# ---------------------------------------------------------------------------

@noelle.post("/noelle/draft")
def noelle_draft():
    """Noelle analyses AADT + accident overlays and proposes stations.

    Stations only — no circles.  Circles are the designer's job.
    Highways are boundaries, not corridors.
    Primary signal: crash rate on local arterials.
    Secondary signal: AADT >= 5K on local roads.

    Query params:
      ?place=true  — also place the stations on the current network
    """
    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path):
        return jsonify({"error": "No AADT overlay — load aadt.geojson "
                        "into mesh_mobility/overlays/"}), 404
    if not os.path.exists(acc_path):
        return jsonify({"error": "No accident overlay — load "
                        "accidents.geojson into mesh_mobility/overlays/"}), 404

    result = _noelle_analyze(aadt_path, acc_path)
    if "error" in result:
        return jsonify(result), 400

    # Optionally place stations on the map
    place = request.args.get("place", "false").lower() == "true"
    placed_ids = []
    if place:
        net = _net()
        if net is None:
            _state["network"] = Network(network_id="noelle_draft")
            _state["network_path"] = None
            _state["sim_frames"] = []
            _state["sim_result"] = None
            clear_edit_state()
            net = _state["network"]

        for s in result["stations"]:
            try:
                struct, cps = build_station(
                    net, s["lat"], s["lon"],
                    heading_deg=0,
                    structure_id=next_sid("s"))
                _state["structures"][struct.structure_id] = struct
                _state["cps"].update(cps)
                placed_ids.append(struct.structure_id)
            except Exception:
                pass  # skip overlapping stations silently

        result["placed"] = len(placed_ids)
        result["placed_ids"] = placed_ids

    return jsonify(result)


@noelle.post("/noelle/wild_guess")
def noelle_wild_guess():
    """Wild Guess: add traffic circles between draft stations and auto-connect everything.

    Call after Draft + Apply. Places circles at midpoints between nearby station pairs,
    then runs auto-connect. Produces a complete connected network from Noelle's stations.
    """
    push_undo()
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    structures = _state.get("structures", {})
    cps = _state.get("cps", {})

    # Collect all station positions
    stations = []
    for sid, struct in structures.items():
        if struct.structure_type == "station":
            stations.append({
                "id": sid,
                "lat": struct.center_lat,
                "lon": struct.center_lon,
            })

    if len(stations) < 2:
        return jsonify({"error": "Need at least 2 stations — run Draft + Apply first"}), 400

    # Find station pairs that need circles between them
    max_dist_m = 2.5 * 1609.34

    pairs = []
    for i in range(len(stations)):
        for j in range(i + 1, len(stations)):
            d = vincenty_m(stations[i]["lat"], stations[i]["lon"],
                          stations[j]["lat"], stations[j]["lon"])
            if d < max_dist_m:
                pairs.append((i, j, d))

    # Sort by distance — shortest first
    pairs.sort(key=lambda x: x[2])

    # Place circles at midpoints, skip if too close to an existing structure
    placed_circles = []
    min_circle_spacing_m = 400

    for i, j, d in pairs:
        mid_lat = (stations[i]["lat"] + stations[j]["lat"]) / 2
        mid_lon = (stations[i]["lon"] + stations[j]["lon"]) / 2

        # Check if too close to any existing structure or already-placed circle
        too_close = False
        for sid, struct in structures.items():
            if vincenty_m(mid_lat, mid_lon, struct.center_lat, struct.center_lon) < min_circle_spacing_m:
                too_close = True
                break
        if too_close:
            continue

        # Determine heading: perpendicular to the line between the two stations
        dlat = stations[j]["lat"] - stations[i]["lat"]
        dlon = stations[j]["lon"] - stations[i]["lon"]
        bearing = math.degrees(math.atan2(dlon, dlat)) % 360
        circle_heading = 45 if (22.5 < bearing % 90 < 67.5) else 0

        try:
            cid = next_sid("c")
            struct, new_cps = build_traffic_circle(
                net, mid_lat, mid_lon,
                heading_deg=circle_heading,
                structure_id=cid)
            structures[cid] = struct
            cps.update(new_cps)
            placed_circles.append(cid)
        except Exception:
            pass

    # Auto-connect everything
    added_lines = _best_effort_connect(net, cps, _state["line_pairs"])
    for l in added_lines:
        _state["line_roles"][l.line_id] = "connector"
    net.build()

    noelle_log("wild_guess", {
        "stations": len(stations),
        "circles_added": len(placed_circles),
        "lines_added": len(added_lines),
    })

    return jsonify({
        "stations": len(stations),
        "circles_added": len(placed_circles),
        "circle_ids": placed_circles,
        "lines_added": len(added_lines),
        "total_structures": len(structures),
    })


# ---------------------------------------------------------------------------
# Network report (printable HTML)
# ---------------------------------------------------------------------------

@noelle.get("/network/report")
def network_report():
    """Printable HTML network summary — stations, miles, economics."""
    net = _net()
    if net is None:
        return "<h1>No network loaded</h1>", 400

    structures = _state.get("structures", {})
    stations = [(sid, s) for sid, s in structures.items() if s.structure_type == "station"]
    circles = [(sid, s) for sid, s in structures.items() if s.structure_type == "circle"]
    total_miles = round(net.total_length_m() / 1609.34, 1)
    build_cost = round(total_miles * 20, 1)
    network_id = net.network_id or "Untitled"

    # City name from overlay state
    city_label = ""
    overlays = _state.get("overlays", {})
    city_key = overlays.get("city", "")

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>JPods Network Summary — {network_id}</title>
<style>
  @media print {{ body {{ font-size: 11pt; }} }}
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; max-width: 800px;
         margin: 40px auto; padding: 0 20px; color: #222; }}
  h1 {{ color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 8px; }}
  h2 {{ color: #2e7d32; margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ padding: 6px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  .metric {{ font-size: 28px; font-weight: 700; color: #1a5276; }}
  .metric-label {{ font-size: 12px; color: #888; text-transform: uppercase; }}
  .metrics {{ display: flex; gap: 32px; margin: 20px 0; }}
  .metric-box {{ text-align: center; }}
  .footer {{ margin-top: 40px; font-size: 11px; color: #888;
             border-top: 1px solid #ddd; padding-top: 12px; }}
  .oss {{ background: #f0f8f0; padding: 8px 12px; border-radius: 4px;
          border-left: 3px solid #2e7d32; font-size: 12px; margin: 16px 0; }}
</style>
</head><body>
<h1>JPods Network Summary — {network_id}</h1>

<div class="metrics">
  <div class="metric-box"><div class="metric">{len(stations)}</div><div class="metric-label">Stations</div></div>
  <div class="metric-box"><div class="metric">{len(circles)}</div><div class="metric-label">Circles</div></div>
  <div class="metric-box"><div class="metric">{total_miles}</div><div class="metric-label">Guideway Miles</div></div>
  <div class="metric-box"><div class="metric">${build_cost:,.0f}M</div><div class="metric-label">Build Cost ($20M/mi)</div></div>
</div>

<div class="oss">Open Source — all designs created with this tool are open source and publicly shared.
Solar-powered · 13x more efficient than cars · 50x vs buses · $0.03/passenger-mile</div>

<h2>Stations ({len(stations)})</h2>
<table>
<tr><th>ID</th><th>Latitude</th><th>Longitude</th></tr>"""

    for sid, s in sorted(stations, key=lambda x: x[0]):
        html += f"\n<tr><td>{sid}</td><td>{s.center_lat:.5f}</td><td>{s.center_lon:.5f}</td></tr>"

    html += f"""
</table>

<h2>Traffic Circles ({len(circles)})</h2>
<table>
<tr><th>ID</th><th>Latitude</th><th>Longitude</th></tr>"""

    for cid, c in sorted(circles, key=lambda x: x[0]):
        html += f"\n<tr><td>{cid}</td><td>{c.center_lat:.5f}</td><td>{c.center_lon:.5f}</td></tr>"

    html += f"""
</table>

<h2>Bill of Materials (BOM)</h2>
<table>
<tr><th>Item</th><th>Quantity</th><th>Unit Cost</th><th>Total</th></tr>
<tr><td>Guideway (dual beam, solar panels, columns)</td><td>{total_miles} mi</td><td>$20M/mi</td><td>${build_cost:,.0f}M</td></tr>
<tr><td>Stations (2-slot standard)</td><td>{len(stations)}</td><td>~$2M ea</td><td>~${len(stations)*2:,}M</td></tr>
<tr><td>Traffic circles (junction structures)</td><td>{len(circles)}</td><td>~$0.5M ea</td><td>~${round(len(circles)*0.5):,}M</td></tr>
<tr><td>Vehicles (pods, 4 per station initial fleet)</td><td>{len(stations)*4}</td><td>~$50K ea</td><td>~${round(len(stations)*4*0.05):,}M</td></tr>
<tr style="font-weight:600;border-top:2px solid #333">
  <td>Total estimated</td><td></td><td></td>
  <td>${build_cost + len(stations)*2 + round(len(circles)*0.5) + round(len(stations)*4*0.05):,.0f}M</td></tr>
</table>
<p style="font-size:11px;color:#666">Note: Costs are rough planning estimates. Guideway dominates.
Actual costs vary by terrain, permitting, and local labor markets.</p>

<h2>Guideway Capacity</h2>
<p>Capacity is determined by <strong>speed × headway</strong> on the guideway, but the real constraint
is <strong>station slots</strong> — how many pods can load/unload simultaneously.
Stations are parallel processors: more slots = more throughput, without changing the guideway.</p>

<table>
<tr><th>Speed</th><th colspan="2">0.25 sec headway</th><th colspan="2">0.50 sec headway</th></tr>
<tr><th>(mph)</th><th>Pods/hr/dir</th><th>Pax/hr/dir</th><th>Pods/hr/dir</th><th>Pax/hr/dir</th></tr>
<tr><td>25 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
<tr><td>35 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
<tr><td>45 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
<tr><td>60 mph</td><td>14,400</td><td>14,400</td><td>7,200</td><td>7,200</td></tr>
</table>
<p style="font-size:11px;color:#666">Pods/hr = 3600 ÷ headway. At 0.25s: 14,400 pods/hr per direction.
Each pod carries 1-4 passengers. Speed affects trip time, not throughput.</p>

<h2>Station Throughput (the real constraint)</h2>
<p>With 30-second load/unload cycles, each slot processes 120 pods/hour.
Capacity scales by adding slots — the station is a parallel processor.</p>

<table>
<tr><th>Station Type</th><th>Slots</th><th>Pods/hr</th><th>Pax/hr (1.5 avg)</th><th>Use Case</th></tr>
<tr><td>Neighborhood</td><td>2</td><td>240</td><td>360</td><td>Residential area</td></tr>
<tr><td>Standard</td><td>4</td><td>480</td><td>720</td><td>Commercial district</td></tr>
<tr><td>High capacity</td><td>8</td><td>960</td><td>1,440</td><td>Office park, mall</td></tr>
<tr><td>Transit hub</td><td>18</td><td>2,160</td><td>3,240</td><td>Train station, airport</td></tr>
<tr><td>Major terminal</td><td>36</td><td>4,320</td><td>6,480</td><td>Stadium, convention center</td></tr>
</table>
<p style="font-size:11px;color:#666">Add stations where demand concentrates.
Two 18-slot stations 200m apart = 6,480 pax/hr without changing the guideway.
<a href="https://library.jpods.com/capacity/">Detailed capacity analysis →</a></p>

<h2>Network Summary — This Design</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Guideway miles</td><td>{total_miles} mi</td></tr>
<tr><td>Stations × 4 slots (default)</td><td>{len(stations)} × 480 pods/hr = {len(stations)*480:,} pods/hr network capacity</td></tr>
<tr><td>Build cost</td><td>${build_cost + len(stations)*2 + round(len(circles)*0.5):,.0f}M</td></tr>
<tr><td>JPods efficiency</td><td>13× more efficient than cars · 50× vs buses</td></tr>
<tr><td>Operating cost</td><td>$0.03/passenger-mile</td></tr>
<tr><td>Energy</td><td>Solar-powered — no fuel dependency</td></tr>
</table>

<p>Run the <a href="/citytool">City Assessment Tool</a> for full savings analysis including
vehicle ownership reduction, fuel savings, road maintenance, CO₂ reduction, and fiscal impact.</p>

<h2>The Cost of Free Parking</h2>
<p>The US has an estimated 800 million parking spaces for 280 million cars — roughly 3 spaces
per car. In many cities, the total cost of providing free parking (land, construction,
maintenance, and foregone tax revenue on tax-exempt land) rivals spending on public education.</p>
<p>JPods networks eliminate parked-car demand, converting low-tax parking lots to high-tax
productive land — walkable commercial, residential, and recreational space.</p>
<p style="font-size:11px;color:#666">Source: Donald Shoup,
<a href="https://www.routledge.com/The-High-Cost-of-Free-Parking/Shoup/p/book/9781032408552"><i>The High Cost of Free Parking</i></a>
(Routledge, updated edition 2011). Shoup documents that off-street parking requirements
in US zoning codes have made parking the single largest land use in most cities.</p>

<h2>Proven Model — Privately Funded Transit</h2>
<p>In 1916, every US city over 10,000 people had one or more
<a href="https://en.wikipedia.org/wiki/List_of_streetcar_systems_in_the_United_States">privately funded streetcar networks</a>
— Mobility As A Service before the term existed. The Federal-Aid Highway Act of 1916
initiated a mercantile monopoly that destroyed them. JPods restores that proven model:</p>
<table>
<tr><th></th><th>1916 Streetcars</th><th>JPods</th></tr>
<tr><td>Funding</td><td>Private</td><td>Private</td></tr>
<tr><td>Service</td><td>Fixed route, scheduled</td><td>On-demand, point-to-point</td></tr>
<tr><td>Grade</td><td>Street-level (traffic conflicts)</td><td>Grade-separated (no conflicts)</td></tr>
<tr><td>Batch size</td><td>40-passenger vehicle</td><td>1-4 passenger pod</td></tr>
<tr><td>Energy</td><td>Grid electric</td><td>Solar-powered</td></tr>
<tr><td>Coverage</td><td>Every US city &gt;10,000</td><td>Any community, any country</td></tr>
</table>
<p style="font-size:11px;color:#666">The streetcar model wasn't replaced by a better technology.
It was destroyed by federal policy — government coercion extended into transportation commerce.
JPods restores what worked, improved by a century of engineering.</p>

<h2>Regulatory — 5x5 Standard</h2>
<p>JPods networks operate under the <a href="https://www.5x5FreeMarket.com">5×5 Standard</a>:
5 times more efficient than cars, powered by sunlight within 5 years.
This performance standard replaces prescriptive regulations that have blocked
transportation innovation for over five decades.</p>

<h2>Studies &amp; Evidence</h2>

<div style="background:#fff8f0;padding:12px 16px;border-radius:4px;border-left:3px solid #e67e22;margin:12px 0;font-style:italic;font-size:12px;line-height:1.6">
"Government institutional failures blocked urban transportation innovation for
four to six decades… In retrospect, the new systems efforts have served not to
stimulate interest in new technology but to discourage already reluctant local
transit operators from considering it."
<div style="font-style:normal;font-weight:600;margin-top:6px;color:#666">
— U.S. Congressional Study, 1975</div>
</div>

<table>
<tr><th>Study</th><th>Key Finding</th></tr>
<tr><td><a href="https://library.jpods.com/congressionalstudy/">U.S. Congressional Study (1975)</a></td>
    <td>PRT provides higher service than mass transit. Government institutional failures blocked innovation for decades. Lists all JPods benefits: less congestion, less parking, reduced petroleum, mobility for disadvantaged.</td></tr>
<tr><td><a href="https://library.jpods.com/nj2007/">NJ Legislature Study (2007)</a></td>
    <td>State-level assessment of PRT feasibility and benefits for New Jersey communities.</td></tr>
<tr><td><a href="https://library.jpods.com/JPods/004Studies/LeanManufacturingTransit.pdf">Lean Manufacturing &amp; Transit (Boeing)</a></td>
    <td>Maps lean production theory to PRT. Mass transit = mass production waste. PRT = lean: continuous flow, pull-based, batch size of 1. Lean techniques show 991% productivity gains.</td></tr>
<tr><td><a href="https://library.jpods.com/capacity/">Capacity Analysis</a></td>
    <td>Station throughput scales by adding parallel load/unload slots. 18-slot station: 2,160 pax/hr. Guideway: 14,400 pods/hr at 0.25s headway.</td></tr>
</table>

<div class="footer">
  Generated by MeshMobility · JPods Network Planner<br>
  <a href="https://vimeo.com/1207891831?fl=tl&fe=ec">Video Demo</a> ·
  <a href="/citytool">City Assessment Tool</a> ·
  <a href="https://www.5x5FreeMarket.com">5×5 Standard</a> ·
  <a href="https://library.jpods.com/capacity/">Capacity</a> ·
  Open source at jpods.com
</div>
</body></html>"""

    return html


# ---------------------------------------------------------------------------
# Noelle Report (printable HTML analysis)
# ---------------------------------------------------------------------------

@noelle.get("/noelle/report")
def noelle_report():
    """Printable HTML report of Noelle's draft analysis."""
    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path) or not os.path.exists(acc_path):
        return "<h1>No overlay data loaded</h1>", 404

    r = _noelle_analyze(aadt_path, acc_path)
    if "error" in r:
        return f"<h1>Error: {r['error']}</h1>", 400

    # Build printable HTML
    html = ["""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Noelle Network Draft — Analysis Report</title>
<style>
  @media print { body { font-size: 11pt; } }
  body { font-family: -apple-system, 'Segoe UI', sans-serif;
         max-width: 900px; margin: 2em auto; padding: 0 1em;
         color: #222; line-height: 1.5; }
  h1 { border-bottom: 2px solid #333; padding-bottom: 0.3em; }
  h2 { color: #444; margin-top: 1.5em; }
  table { border-collapse: collapse; width: 100%; margin: 1em 0; }
  th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
  th { background: #f5f5f5; font-weight: 600; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .hot { background: #fee; }
  .summary { background: #f8f9fa; padding: 1em 1.5em; border-radius: 6px;
             border-left: 4px solid #2563eb; margin: 1em 0; }
  .insight { background: #fef3c7; padding: 0.8em 1.2em; border-radius: 6px;
             border-left: 4px solid #d97706; margin: 1em 0; }
  .print-btn { background: #2563eb; color: #fff; border: none;
               padding: 8px 20px; border-radius: 4px; cursor: pointer;
               font-size: 14px; }
  .print-btn:hover { background: #1d4ed8; }
  @media print { .no-print { display: none; } }
  .star { color: #dc2626; }
  .dot  { color: #f59e0b; }
</style>
</head><body>
<div class="no-print" style="text-align:right; margin-bottom:1em">
  <button class="print-btn" onclick="window.print()">&#128424; Print Report</button>
</div>
"""]

    html.append(f"<h1>Noelle Network Draft</h1>")
    html.append(f"<p><em>Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                f" — {r['data_summary']['aadt_features']} AADT stations, "
                f"{r['data_summary']['accident_features']} fatal crashes</em></p>")

    # Summary box
    html.append(f'<div class="summary"><pre style="white-space:pre-wrap; '
                f'font-family:inherit; margin:0">{r["summary"]}</pre></div>')

    # Crash rates by road type
    html.append("<h2>Crash Rate by Road Type</h2>")
    html.append("<table><tr><th>Road Type</th><th>Crashes</th>"
                "<th>Pedestrian</th><th>Avg AADT</th>"
                "<th>Rate / 10K AADT</th></tr>")
    for cr in r["crash_rate_summary"]:
        cls = ' class="hot"' if cr["rate_per_10k"] > 20 else ""
        html.append(f'<tr{cls}><td>{cr["type"]}</td>'
                    f'<td class="num">{cr["crashes"]}</td>'
                    f'<td class="num">{cr["ped_crashes"]}</td>'
                    f'<td class="num">{cr["avg_aadt"]:,}</td>'
                    f'<td class="num"><strong>{cr["rate_per_10k"]}</strong></td>'
                    f'</tr>')
    html.append("</table>")

    # Insight box
    local = next((c for c in r["crash_rate_summary"]
                  if c["type"] == "Local/Arterial"), None)
    interstate = next((c for c in r["crash_rate_summary"]
                       if c["type"] == "Interstate"), None)
    if local and interstate and interstate["rate_per_10k"] > 0:
        ratio = local["rate_per_10k"] / interstate["rate_per_10k"]
        html.append(f'<div class="insight">'
                    f'<strong>Key insight:</strong> Local arterials are '
                    f'{ratio:.0f}&times; more dangerous per unit of traffic '
                    f'than interstates. Highways are boundaries, not '
                    f'corridors &mdash; the interior grid is where people '
                    f'die and where JPods stations belong.</div>')

    # Highway boundaries
    if r["highway_boundaries"]:
        html.append("<h2>Highway Boundaries (no stations placed)</h2>")
        html.append("<table><tr><th>Highway</th><th>Max AADT</th>"
                    "<th>Role</th></tr>")
        for h in r["highway_boundaries"]:
            html.append(f'<tr><td>{h["road"]}</td>'
                        f'<td class="num">{h["max_aadt"]:,}</td>'
                        f'<td>Neighborhood boundary</td></tr>')
        html.append("</table>")

    # Proposed stations
    html.append(f"<h2>Proposed Stations ({len(r['stations'])})</h2>")
    html.append("<table><tr><th></th><th>Location</th>"
                "<th>Crashes (600m)</th><th>Local AADT</th>"
                "<th>Source</th></tr>")
    for i, s in enumerate(r["stations"], 1):
        if s["crashes"] >= 3:
            icon = '<span class="star">&#9733;</span>'
        elif s["crashes"] >= 1:
            icon = '<span class="dot">&#8226;</span>'
        else:
            icon = ""
        cls = ' class="hot"' if s["crashes"] >= 3 else ""
        html.append(f'<tr{cls}><td>{i}</td><td>{s["name"]}</td>'
                    f'<td class="num">{icon} {s["crashes"]}</td>'
                    f'<td class="num">{s["aadt"]:,}</td>'
                    f'<td>{s["source"]}</td></tr>')
    html.append("</table>")

    # Grid info
    g = r["grid"]
    html.append(f"<h2>Grid Analysis</h2>")
    html.append(f"<p>Detected {g['ns_corridors']} N-S corridors and "
                f"{g['ew_corridors']} E-W corridors from AADT data. "
                f"{g['grid_stations']} stations on grid intersections, "
                f"{g['cluster_stations']} from accident clusters.</p>")

    # Top crash corridors
    html.append("<h2>Top Crash Corridors (per 10K AADT)</h2>")
    html.append("<table><tr><th>Road</th><th>Type</th><th>Avg AADT</th>"
                "<th>Crashes</th><th>Ped</th>"
                "<th>Rate / 10K</th></tr>")
    for cr in r["crash_rates"][:15]:
        cls = ' class="hot"' if cr["rate_per_10k"] > 5 else ""
        html.append(f'<tr{cls}><td>{cr["road"]}</td>'
                    f'<td>{cr["type"]}</td>'
                    f'<td class="num">{cr["avg_aadt"]:,}</td>'
                    f'<td class="num">{cr["crashes"]}</td>'
                    f'<td class="num">{cr["ped_crashes"]}</td>'
                    f'<td class="num"><strong>'
                    f'{cr["rate_per_10k"]}</strong></td></tr>')
    html.append("</table>")

    html.append("<hr><p style='color:#888; font-size:0.9em'>"
                "Noelle — JPods Network Design Agent. "
                "Stations only; circles are the designer's job. "
                "Data: state DOT AADT + NHTSA FARS.</p>")
    html.append("</body></html>")

    return "\n".join(html), 200, {"Content-Type": "text/html"}


# ---------------------------------------------------------------------------
# Noelle Refine — prune + add based on data signal
# ---------------------------------------------------------------------------

@noelle.post("/noelle/refine")
def noelle_refine():
    """Noelle prunes and adds stations on the existing network.

    Prune: remove stations with no crash or AADT signal within 600m.
    Add: place stations where data shows signal but no structure exists.
    Circles are never touched — they are the designer's work.

    Returns what was pruned and added so the designer can review.
    """
    net = _net()
    if net is None:
        return jsonify({"error": "No network loaded"}), 400

    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path) or not os.path.exists(acc_path):
        return jsonify({"error": "No overlay data — load AADT + accident "
                        "overlays first"}), 404

    # Also load crash density if available
    density_path = os.path.join(_rt_dir, "overlays", "crash_density.geojson")
    density_pts = []
    if os.path.exists(density_path):
        with open(density_path) as f:
            dg = json.load(f)
        for feat in dg.get("features", []):
            lon, lat = feat["geometry"]["coordinates"]
            density_pts.append({"lat": lat, "lon": lon,
                                "crashes": feat["properties"].get("crashes", 0)})

    # Load AADT local arterial points
    with open(aadt_path) as f:
        aadt_geo = json.load(f)
    local_pts = []
    for feat in aadt_geo.get("features", []):
        p = feat["properties"]
        road = p.get("road", "Unknown")
        if _classify_road(road) == "Local/Arterial" and p.get("aadt", 0) >= 5000:
            lon, lat = feat["geometry"]["coordinates"]
            local_pts.append({"lat": lat, "lon": lon, "aadt": p["aadt"]})

    # Load accident points
    with open(acc_path) as f:
        acc_geo = json.load(f)
    acc_pts = []
    for feat in acc_geo.get("features", []):
        lon, lat = feat["geometry"]["coordinates"]
        acc_pts.append({"lat": lat, "lon": lon})

    def has_signal(lat, lon, radius=600):
        """Check if a location has crash or AADT signal."""
        for a in acc_pts:
            if _haversine_m(lat, lon, a["lat"], a["lon"]) < radius:
                return True
        for p in local_pts:
            if _haversine_m(lat, lon, p["lat"], p["lon"]) < radius:
                return True
        for d in density_pts:
            if (d["crashes"] >= 20
                    and _haversine_m(lat, lon, d["lat"], d["lon"]) < radius):
                return True
        return False

    # === PRUNE: remove stations with no signal ===
    pruned = []
    structs_to_remove = []
    for sid, s in list(_state["structures"].items()):
        d = s.to_dict() if hasattr(s, "to_dict") else s
        stype = d.get("structure_type", "unknown")
        # Never prune circles — designer's work
        if stype != "station":
            continue
        lat = d.get("center_lat")
        lon = d.get("center_lon")
        if lat is None or lon is None:
            continue
        if not has_signal(lat, lon):
            structs_to_remove.append(sid)
            pruned.append({"id": sid, "lat": lat, "lon": lon})

    # Delete pruned structures
    for sid in structs_to_remove:
        struct = _state["structures"].get(sid)
        if not struct:
            continue
        # Clear partner CPs
        for cp_id in struct.cp_ids:
            cp = _state["cps"].get(cp_id)
            if cp and cp.connected_to:
                partner = _state["cps"].get(cp.connected_to)
                if partner:
                    partner.connected_to = None
        # Remove lines
        struct_nodes = set(struct.node_ids)
        dead_lines = [lid for lid, line in net.lines.items()
                      if line.start_node.node_id in struct_nodes
                      or line.end_node.node_id in struct_nodes]
        for lid in dead_lines:
            net.lines.pop(lid, None)
            _state["line_pairs"].pop(lid, None)
            _state["line_roles"].pop(lid, None)
            _state["waypoints"].pop(lid, None)
        for nid in struct.node_ids:
            net.nodes.pop(nid, None)
            net.stations.pop(nid, None)
        for cp_id in struct.cp_ids:
            _state["cps"].pop(cp_id, None)
        del _state["structures"][sid]

    # === ADD: place stations where signal exists but no structure ===
    proposal = _noelle_analyze(aadt_path, acc_path)
    noelle_stations = proposal.get("stations", []) if "error" not in proposal else []

    # Filter to proposals not near any existing structure
    existing_pts = []
    for sid, s in _state["structures"].items():
        d = s.to_dict() if hasattr(s, "to_dict") else s
        lat = d.get("center_lat")
        lon = d.get("center_lon")
        if lat and lon:
            existing_pts.append({"lat": lat, "lon": lon})

    added = []
    for ns in noelle_stations:
        near_existing = any(
            _haversine_m(ns["lat"], ns["lon"], ep["lat"], ep["lon"]) < 400
            for ep in existing_pts)
        if near_existing:
            continue
        try:
            struct, cps = build_station(
                net, ns["lat"], ns["lon"],
                heading_deg=0, structure_id=next_sid("s"))
            _state["structures"][struct.structure_id] = struct
            _state["cps"].update(cps)
            existing_pts.append({"lat": ns["lat"], "lon": ns["lon"]})
            added.append({"id": struct.structure_id,
                          "lat": ns["lat"], "lon": ns["lon"],
                          "crashes": ns.get("crashes", 0),
                          "aadt": ns.get("aadt", 0)})
        except Exception:
            pass

    if structs_to_remove:
        net.build()

    return jsonify({
        "pruned": len(pruned),
        "pruned_list": pruned,
        "added": len(added),
        "added_list": added[:20],
        "summary": f"Pruned {len(pruned)} stations (no data signal). "
                   f"Added {len(added)} stations (data signal, no structure).",
    })


# ---------------------------------------------------------------------------
# Noelle Review — compare designer network to Noelle's draft
# ---------------------------------------------------------------------------

@noelle.post("/noelle/review")
def noelle_review():
    """Generate Noelle's draft and embed it in the current network state.

    Triggered by shift-click Open. Noelle's draft is stored in the .jpd
    as `noelle_draft` — a list of proposed stations. The browser can
    extract it and load in a second tab for visual comparison.
    """
    aadt_path = os.path.join(_rt_dir, "overlays", "aadt.geojson")
    acc_path = os.path.join(_rt_dir, "overlays", "accidents.geojson")
    if not os.path.exists(aadt_path) or not os.path.exists(acc_path):
        return jsonify({"error": "No overlay data — cannot review"}), 404

    proposal = _noelle_analyze(aadt_path, acc_path)
    if "error" in proposal:
        return jsonify(proposal), 400

    noelle_stations = proposal.get("stations", [])

    # Build Noelle's draft as a minimal .jpd dict (structures only, no lines)
    noelle_net = Network(network_id="noelle_draft")
    noelle_structs_list = []
    noelle_cps_list = []
    n_counter = 1
    for s in noelle_stations:
        sid = f"s{n_counter}"
        n_counter += 1
        try:
            struct, cps = build_station(
                noelle_net, s["lat"], s["lon"],
                heading_deg=0, structure_id=sid)
            noelle_structs_list.append(struct.to_dict())
            noelle_cps_list.extend(cp.to_dict() for cp in cps.values())
        except Exception:
            pass

    # Store in _state so it saves with the .jpd
    _state["noelle_draft"] = {
        "stations": noelle_stations,
        "structures": noelle_structs_list,
        "cps": noelle_cps_list,
        "summary": proposal.get("summary", ""),
        "crash_rate_summary": proposal.get("crash_rate_summary", []),
    }

    return jsonify({
        "noelle_stations": len(noelle_structs_list),
        "summary": proposal.get("summary", ""),
    })


@noelle.get("/noelle/draft_jpd")
def noelle_draft_jpd():
    """Return the embedded Noelle draft as a loadable .jpd for the second tab."""
    draft = _state.get("noelle_draft")
    if not draft:
        return jsonify({"error": "No Noelle draft — shift-click Open first"}), 404

    d = {
        "format": "jpd",
        "version": 2,
        "network_id": "noelle_draft",
        "saved_at": int(time.time() * 1000),
        "settings": _state.get("settings", {}),
        "switches": [],
        "stations": [],
        "lines": [],
        "structures": draft.get("structures", []),
        "cps": draft.get("cps", []),
    }
    # Include overlay data so the second tab has the same overlays
    overlays = _state.get("overlays")
    if overlays:
        d["overlays"] = overlays
    overlay_data = {}
    overlay_dir = os.path.join(_rt_dir, "overlays")
    if overlays and overlays.get("city"):
        city = overlays["city"]
        for prefix in ("aadt", "accidents", "crash_density", "population_density", "property_values", "jobs"):
            fpath = os.path.join(overlay_dir, f"{prefix}_{city}.geojson")
            if os.path.exists(fpath):
                with open(fpath) as f:
                    overlay_data[prefix] = json.load(f)
    if overlay_data:
        d["overlay_data"] = overlay_data

    content = json.dumps(d, indent=2, ensure_ascii=False).encode("utf-8")
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition":
                 'attachment; filename="noelle_draft.jpd"'},
    )
