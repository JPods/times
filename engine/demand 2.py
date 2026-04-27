"""
route_time.engine.demand
========================
Passenger demand model.

LoadArray schedules passengers across 360 simulation slots (one hour,
10 seconds per slot).  Demand is expressed in passengers per hour —
any positive number, not capped at 360.

  360 pax/hr  → one passenger every slot (10 seconds)
  720 pax/hr  → two passengers per slot
   36 pax/hr  → one passenger every 10 slots (every 100 seconds)
  500 pax/hr  → mixed (1 or 2 per slot, evenly spread)

demand.json format — gravity model (recommended):
  {
    "pax_per_hour": 360,          ← global default for unlisted stations
    "stations": {
      "ST_airport":   { "departures": 800, "arrivals": 1200 },
      "ST_downtown":  { "departures": 600, "arrivals": 400  }
    }
  }

demand.json format — explicit O-D (advanced):
  {
    "stations": {
      "ST_xxx": { "destinations": { "ST_yyy": 200, "ST_zzz": 160 } }
    }
  }

In gravity mode:
  flow(O→D) ∝ departures[O] × arrivals[D]
  "arrivals" is an attraction weight — it controls WHERE departures go,
  not how many arrive (conservation is approximate at planning accuracy).

In explicit mode:
  destination values are pax/hr from that origin to that destination.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class LoadArray:
    """
    One-hour demand schedule.

    slot 0..359 → 10 seconds each.
    get_passengers(slot) returns a list of (origin_id, dest_id) pairs —
    zero, one, or more per slot depending on each station's pax/hr rate.
    """

    SLOTS = 360                # ticks per simulated hour
    SLOT_DURATION_S = 10       # seconds per tick

    def __init__(self, station_ids: List[str], seed: int = 42,
                 demand_config: Optional[dict] = None):
        self._station_ids = station_ids
        self._table: Dict[int, List[Tuple[str, str]]] = {s: [] for s in range(self.SLOTS)}
        self._build(seed, demand_config or {})

    @classmethod
    def from_file(cls, station_ids: List[str], path: Path, seed: int = 42) -> "LoadArray":
        with open(path) as f:
            config = json.load(f)
        return cls(station_ids, seed=seed, demand_config=config)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self, seed: int, config: dict):
        rng = random.Random(seed)
        station_set   = set(self._station_ids)
        station_cfgs  = config.get("stations", {})
        default_pax   = float(config.get("pax_per_hour", self.SLOTS))

        # Detect mode: any station with departures/arrivals → gravity
        gravity_mode = any(
            isinstance(sc, dict) and ("departures" in sc or "arrivals" in sc)
            for sc in station_cfgs.values()
        )

        if gravity_mode:
            self._build_gravity(rng, station_cfgs, station_set, default_pax)
        else:
            self._build_explicit(rng, station_cfgs, station_set, default_pax)

    def _build_gravity(self, rng: random.Random, station_cfgs: dict,
                       station_set: set, default_pax: float):
        """
        Gravity model.

        departures[O]  → pax/hr that originate at O
        arrivals[D]    → attraction weight; destination chosen proportional to this
        """
        n = len(self._station_ids)
        if n < 2:
            return

        dep: Dict[str, float] = {}
        arr: Dict[str, float] = {}
        for sid in self._station_ids:
            sc = station_cfgs.get(sid, {})
            if isinstance(sc, dict):
                dep[sid] = float(sc.get("departures", default_pax))
                arr[sid] = float(sc.get("arrivals",   default_pax))
            else:
                dep[sid] = default_pax
                arr[sid] = default_pax

        for origin in self._station_ids:
            others  = [s for s in self._station_ids if s != origin]
            if not others:
                continue

            rate    = dep[origin]                   # pax/hr
            n_pax   = max(0, int(round(rate)))      # total passengers this hour
            weights = [arr[d] for d in others]
            total_w = sum(weights) or 1.0

            self._schedule(rng, origin, others, weights, total_w, n_pax)

    def _build_explicit(self, rng: random.Random, station_cfgs: dict,
                        station_set: set, default_pax: float):
        """
        Explicit O-D mode: destinations dict gives pax/hr per dest.
        Stations not in config use uniform distribution at default_pax total.
        """
        n = len(self._station_ids)
        if n < 2:
            return

        for origin in self._station_ids:
            others = [s for s in self._station_ids if s != origin]
            if not others:
                continue

            sc       = station_cfgs.get(origin, {})
            raw_dest = sc.get("destinations", {}) if isinstance(sc, dict) else {}

            valid = {
                k: float(v) for k, v in raw_dest.items()
                if k in station_set and k != origin
                   and isinstance(v, (int, float)) and v > 0
            }

            if valid:
                dests   = list(valid.keys())
                weights = list(valid.values())
                total_w = sum(weights)
                n_pax   = int(round(total_w))
            else:
                dests   = others
                weights = [1.0] * len(others)
                total_w = float(len(others))
                n_pax   = int(round(default_pax))

            self._schedule(rng, origin, dests, weights, total_w, n_pax)

    def _schedule(self, rng: random.Random, origin: str,
                  dests: List[str], weights: List[float], total_w: float,
                  n_pax: int):
        """
        Spread n_pax passengers from origin evenly across SLOTS slots.
        Destination is chosen weighted-randomly from dests/weights.
        """
        if n_pax <= 0 or not dests:
            return

        for i in range(n_pax):
            # Deterministic even spread: passenger i goes in slot floor(i*SLOTS/n_pax)
            slot = int(i * self.SLOTS / n_pax) % self.SLOTS

            # Weighted random destination
            r   = rng.random() * total_w
            cum = 0.0
            chosen = dests[-1]
            for d, w in zip(dests, weights):
                cum += w
                if r <= cum:
                    chosen = d
                    break

            self._table[slot].append((origin, chosen))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_passengers(self, slot: int) -> List[Tuple[str, str]]:
        """Return list of (origin_id, dest_id) pairs generated in this slot."""
        return self._table.get(slot % self.SLOTS, [])

    @property
    def total_passengers(self) -> int:
        return sum(len(v) for v in self._table.values())
