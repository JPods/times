"""
route_time.engine.simulation
============================
Discrete-tick simulation engine.

Mirrors Java Simulator logic:
  - 360 slots × 10 ticks per slot (timeResolutionPerSec=9 → tick_s ≈ 0.111s)
    → total ticks ≈ 360 × 10 / tick_s  (Java: ~32,400 ticks for 1-hour sim)
  - Every 10 ticks: generate passengers for current slot
  - Each tick: move pods, board/alight passengers, record line transits
  - Pods dispatched from depot when a station has demand and a clear line
  - Pods return to depot when no passengers and ≥ podsPerStation queued

This engine does not render anything.  It accumulates statistics in
Line.transit_samples_ms and returns a SimResult.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .demand import LoadArray
from .network import Line, Network, Node, Station
from .physics import PhysicsModel
from .routing import find_path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pod
# ---------------------------------------------------------------------------

@dataclass
class Pod:
    pod_id: str
    current_line: Optional[Line] = None
    position_m: float = 0.0        # distance travelled on current_line
    speed_m_s: float = 0.0
    destination_station: Optional[Station] = None
    passenger_count: int = 0

    # path remaining: ordered list of Lines to traverse
    route: List[Line] = field(default_factory=list)

    # timing
    line_entry_tick: int = 0       # tick when pod entered current_line
    in_depot: bool = True

    def is_at_end_of_line(self) -> bool:
        if self.current_line is None:
            return False
        return self.position_m >= self.current_line.length_m

    def advance(self, physics: PhysicsModel):
        """Move pod one tick along its current line."""
        if self.current_line is None or self.in_depot:
            return
        # Simple cruise model — acceleration handled by physics for stats
        # (per-tick position uses cruise speed for throughput simulation)
        self.position_m += physics.cruise_m_per_tick
        self.position_m = min(self.position_m, self.current_line.length_m)


# ---------------------------------------------------------------------------
# SimResult
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    network_id: str
    settings: dict
    total_ticks: int
    passengers_generated: int
    passengers_served: int
    line_stats: List[dict] = field(default_factory=list)
    station_stats: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema": "jpods.route_time.v1",
            "network_id": self.network_id,
            "settings": self.settings,
            "simulation": {
                "total_ticks": self.total_ticks,
                "passengers_generated": self.passengers_generated,
                "passengers_served": self.passengers_served,
            },
            "line_stats": self.line_stats,
            "station_stats": self.station_stats,
        }


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class Simulator:
    # Generate passengers every this many ticks (matches Java: every 10 ticks)
    PASSENGER_GEN_INTERVAL = 10

    def __init__(self, network: Network, settings: dict):
        self.network = network
        self.settings = settings
        self.physics = PhysicsModel(settings)

        self.pods_per_station: int = settings.get("podsPerStation", 4)
        self.disembark_s: float    = settings.get("disembarkingTimeInSec", 20)
        self.embark_s: float       = settings.get("embarkingTimeInSec", 20)
        self.ticketing_s: float    = settings.get("ticketingTimeInSec", 30)
        self.station_entry_s: float = settings.get("stationEntryTimeInSec", 40)
        self.station_exit_s: float  = settings.get("stationExitTimeInSec", 40)
        self.grace_distance: float  = settings.get("graceDistance", 0.0)

        tps = settings.get("timeResolutionPerSec", 9)
        self.tick_s: float = 1.0 / tps

        self._pods: List[Pod] = []
        self._depot: List[Pod] = []
        self._demand: LoadArray = LoadArray(
            [s.station_id for s in network.stations.values()]
        )
        self._waiting: Dict[str, List[str]] = {
            sid: [] for sid in network.stations
        }  # station_id → [dest_station_id, ...]
        self._passengers_generated = 0
        self._passengers_served = 0
        self._current_tick = 0

        # Pre-create depot pods (4 per station)
        pod_counter = 0
        for station in network.stations.values():
            for _ in range(self.pods_per_station):
                p = Pod(pod_id=f"POD_{pod_counter:04d}", in_depot=True)
                self._depot.append(p)
                pod_counter += 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, total_slots: int = LoadArray.SLOTS) -> SimResult:
        """Run simulation for total_slots demand slots."""
        self.network.reset()
        ticks_per_slot = self.PASSENGER_GEN_INTERVAL
        total_ticks = total_slots * ticks_per_slot

        for tick in range(total_ticks):
            self._current_tick = tick

            # Generate passengers every PASSENGER_GEN_INTERVAL ticks
            if tick % ticks_per_slot == 0:
                slot = tick // ticks_per_slot
                self._generate_passengers(slot)

            # Move all active pods
            self._tick_pods()

            # Dispatch pods from depot to meet demand
            self._dispatch()

        return self._build_result(total_ticks)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_passengers(self, slot: int):
        pairs = self._demand.get_passengers(slot)
        for origin_id, dest_id in pairs:
            if origin_id in self._waiting:
                self._waiting[origin_id].append(dest_id)
                self._passengers_generated += 1

    def _tick_pods(self):
        completed = []
        for pod in list(self._pods):
            pod.advance(self.physics)
            if pod.is_at_end_of_line():
                completed.append(pod)

        for pod in completed:
            self._arrive_at_line_end(pod)

    def _arrive_at_line_end(self, pod: Pod):
        line = pod.current_line
        if line is None:
            return

        # Record transit time for this line
        elapsed_ticks = self._current_tick - pod.line_entry_tick
        elapsed_ms = elapsed_ticks * self.tick_s * 1000
        # Replace with physics-based estimate for accuracy
        physics_ms = self.physics.transit_time_ms(line.length_m)
        line.record_transit(physics_ms)

        line.pods_on_line.remove(pod)

        end_node = line.end_node

        # If end_node is a station, handle boarding/alighting
        station = self.network.stations.get(end_node.node_id)
        if station is not None and pod.destination_station is not None:
            if pod.destination_station.station_id == station.station_id:
                # Pod has arrived at destination
                pod.passenger_count = 0
                pod.destination_station = None
                self._passengers_served += 1
                # Park pod at this station or return to depot
                station.queued_pods.append(pod)
                pod.current_line = None
                pod.in_depot = False
                if pod in self._pods:
                    self._pods.remove(pod)
                # Check for waiting passengers at this station
                self._board_from_station(station, pod)
                return

        # Continue on route
        if pod.route:
            next_line = pod.route.pop(0)
            self._enter_line(pod, next_line)
        else:
            # Route complete — park or return to depot
            pod.current_line = None
            if station:
                station.queued_pods.append(pod)
                pod.in_depot = False
                if pod in self._pods:
                    self._pods.remove(pod)
            else:
                self._return_to_depot(pod)

    def _board_from_station(self, station: Station, pod: Pod):
        """If passengers are waiting at this station, immediately dispatch pod."""
        waiting = self._waiting.get(station.station_id, [])
        if not waiting:
            return
        dest_id = waiting.pop(0)
        dest_station = self.network.stations.get(dest_id)
        if dest_station is None:
            return

        route = find_path(
            self.network,
            station.node,
            dest_station.node,
            self.grace_distance,
        )
        if not route:
            return

        pod.destination_station = dest_station
        pod.passenger_count = 1
        pod.route = route[1:] if len(route) > 1 else []
        if station.station_id in [s.station_id for s in pod.route[0].start_node.outbound if False]:
            pass  # placeholder
        if pod in station.queued_pods:
            station.queued_pods.remove(pod)
        pod.in_depot = False
        self._enter_line(pod, route[0])
        self._pods.append(pod)

    def _dispatch(self):
        """For each station with waiting passengers and an available pod, dispatch."""
        for station in self.network.stations.values():
            waiting = self._waiting.get(station.station_id, [])
            if not waiting:
                continue
            # Find an available pod (at this station or from depot)
            pod = None
            if station.queued_pods:
                pod = station.queued_pods.pop(0)
            elif self._depot:
                pod = self._depot.pop(0)
                pod.in_depot = False
            if pod is None:
                continue

            dest_id = waiting.pop(0)
            dest_station = self.network.stations.get(dest_id)
            if dest_station is None:
                self._depot.append(pod)
                continue

            route = find_path(
                self.network,
                station.node,
                dest_station.node,
                self.grace_distance,
            )
            if not route:
                log.warning("No route from %s to %s", station.station_id, dest_id)
                self._depot.append(pod)
                continue

            pod.destination_station = dest_station
            pod.passenger_count = 1
            pod.route = route[1:] if len(route) > 1 else []
            self._enter_line(pod, route[0])
            self._pods.append(pod)

    def _enter_line(self, pod: Pod, line: Line):
        pod.current_line = line
        pod.position_m = 0.0
        pod.line_entry_tick = self._current_tick
        line.pods_on_line.append(pod)

    def _return_to_depot(self, pod: Pod):
        if pod in self._pods:
            self._pods.remove(pod)
        pod.in_depot = True
        pod.current_line = None
        pod.destination_station = None
        pod.passenger_count = 0
        pod.route.clear()
        self._depot.append(pod)

    def _build_result(self, total_ticks: int) -> SimResult:
        line_stats = []
        for lid, line in self.network.lines.items():
            line_stats.append({
                "line_id": lid,
                "start_node": line.start_node.node_id,
                "end_node": line.end_node.node_id,
                "length_m": round(line.length_m, 1),
                "sample_count": len(line.transit_samples_ms),
                "fleet_median_transit_ms": _round_opt(line.fleet_median_ms()),
                "fleet_mean_transit_ms":   _round_opt(line.fleet_mean_ms()),
                "fleet_p90_transit_ms":    _round_opt(line.fleet_p90_ms()),
            })

        station_stats = []
        for sid, st in self.network.stations.items():
            waiting_count = len(self._waiting.get(sid, []))
            station_stats.append({
                "station_id": sid,
                "passengers_waiting_end": waiting_count,
            })

        return SimResult(
            network_id=self.network.network_id,
            settings=self.settings,
            total_ticks=total_ticks,
            passengers_generated=self._passengers_generated,
            passengers_served=self._passengers_served,
            line_stats=line_stats,
            station_stats=station_stats,
        )


def _round_opt(v):
    if v is None:
        return None
    return round(v, 1)
