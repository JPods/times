"""
route_time.engine.demand
========================
Passenger demand model.

Java LoadArray: 360 slots × N stations.
Each slot = 10 seconds of simulation time.
One passenger generated per slot per station, destination ≠ origin.

This class produces (origin_station_id, dest_station_id) pairs
keyed by slot number.  The simulation engine calls get_passengers(slot)
at each passenger-generation tick.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple


class LoadArray:
    """
    360-slot demand table.

    slot 0..359 → one hour of simulation, 10 seconds per slot.
    Each slot generates one passenger per station.
    """

    SLOTS = 360
    SLOT_DURATION_S = 10

    def __init__(self, station_ids: List[str], seed: int = 42):
        self._station_ids = station_ids
        self._table: Dict[int, List[Tuple[str, str]]] = {}
        self._build(seed)

    def _build(self, seed: int):
        rng = random.Random(seed)
        n = len(self._station_ids)
        for slot in range(self.SLOTS):
            pairs = []
            for i, origin in enumerate(self._station_ids):
                if n < 2:
                    continue
                # pick a destination ≠ origin
                choices = [s for s in self._station_ids if s != origin]
                dest = rng.choice(choices)
                pairs.append((origin, dest))
            self._table[slot] = pairs

    def get_passengers(self, slot: int) -> List[Tuple[str, str]]:
        """Return list of (origin_id, dest_id) for this slot."""
        return self._table.get(slot % self.SLOTS, [])

    @property
    def total_passengers(self) -> int:
        return sum(len(v) for v in self._table.values())
