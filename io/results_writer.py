"""
mesh_mobility.io.results_writer
================================
Write simulation results to JSON.

Primary output: mesh_mobility_results.json
  - Full SimResult dict including line_stats with fleet_median_transit_ms.
  - fleet_median_transit_ms feeds itinerary.json route_time_ms field.

Secondary output (optional): itinerary_patch.json
  - Minimal list of {line_id, route_time_ms} for patching an itinerary.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from ..engine.simulation import SimResult


def write_results(result: SimResult, output_dir: str, network_id: Optional[str] = None) -> str:
    """
    Write results to output_dir/mesh_mobility_results.json.
    Returns the path written.
    """
    os.makedirs(output_dir, exist_ok=True)

    d = result.to_dict()
    d["generated_at"] = datetime.now(timezone.utc).isoformat()
    if network_id:
        d["network_id"] = network_id

    path = os.path.join(output_dir, "mesh_mobility_results.json")
    with open(path, "w") as f:
        json.dump(d, f, indent=2)
    return path


def write_itinerary_patch(result: SimResult, output_dir: str) -> str:
    """
    Write a minimal patch file: [{line_id, route_time_ms}, ...].
    Natalie can use this to populate route_time_ms in new itineraries.
    (route_time_ms is a data field name, not the old product name.)
    """
    os.makedirs(output_dir, exist_ok=True)

    patch = []
    for ls in result.line_stats:
        patch.append({
            "line_id": ls["line_id"],
            "route_time_ms": ls["fleet_median_transit_ms"],
        })

    path = os.path.join(output_dir, "mesh_mobility_patch.json")
    with open(path, "w") as f:
        json.dump(patch, f, indent=2)
    return path
