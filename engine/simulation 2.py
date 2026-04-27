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
import statistics
import time as _time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .demand import LoadArray
from .network import Line, Network, Node, Station, configure_jam_threshold
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
# TripRecord
# ---------------------------------------------------------------------------

@dataclass
class TripRecord:
    """One passenger trip: origin station → destination station."""
    origin_id: str
    dest_id: str
    dispatch_tick: int
    generated_tick: int    # when passenger entered the waiting queue
    route_length_m: float  # total geodetic distance of the route
    arrive_tick: int = -1

    def travel_ms(self, tick_s: float) -> float:
        """Pod travel time only — does not include station overhead."""
        return (self.arrive_tick - self.dispatch_tick) * tick_s * 1000

    def wait_ms(self, tick_s: float) -> float:
        """Time passenger spent waiting before pod was dispatched."""
        return max(0.0, (self.dispatch_tick - self.generated_tick) * tick_s * 1000)


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
    summary: dict = field(default_factory=dict)
    line_stats: List[dict] = field(default_factory=list)
    trip_stats: List[dict] = field(default_factory=list)
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
            "summary": self.summary,
            "trip_stats": self.trip_stats,
            "line_stats": self.line_stats,
            "station_stats": self.station_stats,
        }


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class Simulator:

    def __init__(self, network: Network, settings: dict,
                 demand: Optional[LoadArray] = None):
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

        # Ticks per demand slot: physics resolution × slot duration in seconds.
        # At tps=9 and SLOT_DURATION_S=10: 90 ticks/slot → 360 slots × 90 = 32,400 ticks = 1 hour.
        # Previously hardcoded as 10, which compressed simulated time to 6m40s instead of 1 hour.
        self._ticks_per_slot: int = max(1, round(tps * LoadArray.SLOT_DURATION_S))

        # Apply headway-based jam threshold to the network module
        configure_jam_threshold(
            min_headway_s     = float(settings.get("minHeadwaySec", 0.25)),
            max_velocity_kmph = float(settings.get("maxVelocityInKMPH", 60)),
            pod_len_m         = float(settings.get("podLen", 3.0)),
        )

        # Station overhead: time a passenger spends outside the moving pod
        # (ticketing + station entry + embarking + disembarking + station exit)
        self._station_overhead_ms: float = (
            settings.get("ticketingTimeInSec",    30) +
            settings.get("stationEntryTimeInSec", 40) +
            settings.get("embarkingTimeInSec",    20) +
            settings.get("disembarkingTimeInSec", 20) +
            settings.get("stationExitTimeInSec",  40)
        ) * 1000.0  # → ms

        self._pods: List[Pod] = []
        self._depot: List[Pod] = []
        self._demand: LoadArray = demand or LoadArray(
            [s.station_id for s in network.stations.values()]
        )
        # station_id → [(dest_station_id, generated_tick), ...]
        self._waiting: Dict[str, List[Tuple[str, int]]] = {
            sid: [] for sid in network.stations
        }
        self._passengers_generated = 0
        self._passengers_served = 0
        self._current_tick = 0
        self._active_trips: Dict[str, TripRecord] = {}   # pod_id → TripRecord
        self._completed_trips: List[TripRecord] = []

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
        wall_start = _time.time()
        ticks_per_slot = self._ticks_per_slot
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

        return self._build_result(total_ticks, wall_elapsed_s=_time.time() - wall_start)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_passengers(self, slot: int):
        pairs = self._demand.get_passengers(slot)
        for origin_id, dest_id in pairs:
            if origin_id in self._waiting:
                self._waiting[origin_id].append((dest_id, self._current_tick))
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
                # Complete trip record
                trip = self._active_trips.pop(pod.pod_id, None)
                if trip is not None:
                    trip.arrive_tick = self._current_tick
                    self._completed_trips.append(trip)
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
        dest_id, gen_tick = waiting.pop(0)
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

        route_len = sum(line.length_m for line in route)
        pod.destination_station = dest_station
        pod.passenger_count = 1
        pod.route = route[1:] if len(route) > 1 else []
        if pod in station.queued_pods:
            station.queued_pods.remove(pod)
        pod.in_depot = False
        self._enter_line(pod, route[0])
        self._pods.append(pod)
        self._active_trips[pod.pod_id] = TripRecord(
            origin_id=station.station_id,
            dest_id=dest_station.station_id,
            dispatch_tick=self._current_tick,
            generated_tick=gen_tick,
            route_length_m=route_len,
        )

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

            dest_id, gen_tick = waiting.pop(0)
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

            route_len = sum(line.length_m for line in route)
            pod.destination_station = dest_station
            pod.passenger_count = 1
            pod.route = route[1:] if len(route) > 1 else []
            self._enter_line(pod, route[0])
            self._pods.append(pod)
            self._active_trips[pod.pod_id] = TripRecord(
                origin_id=station.station_id,
                dest_id=dest_station.station_id,
                dispatch_tick=self._current_tick,
                generated_tick=gen_tick,
                route_length_m=route_len,
            )

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

    def _build_result(self, total_ticks: int, wall_elapsed_s: float = 0.0) -> SimResult:
        tick_s = self.tick_s

        # -------------------------------------------------------
        # Trip stats (station-to-station, including overhead)
        # -------------------------------------------------------
        trip_groups: Dict[tuple, List[float]] = defaultdict(list)
        for trip in self._completed_trips:
            total_ms = trip.travel_ms(tick_s) + self._station_overhead_ms
            trip_groups[(trip.origin_id, trip.dest_id)].append(total_ms)

        # Compute route geometry (line sequence) for each unique O-D pair
        route_line_ids: Dict[tuple, List[str]] = {}
        for (origin_id, dest_id) in trip_groups.keys():
            src_st = self.network.stations.get(origin_id)
            dst_st = self.network.stations.get(dest_id)
            if src_st and dst_st:
                route = find_path(
                    self.network, src_st.node, dst_st.node, self.grace_distance
                )
                route_line_ids[(origin_id, dest_id)] = [ln.line_id for ln in route]

        trip_stats = []
        for (origin_id, dest_id), durations in sorted(trip_groups.items()):
            n = len(durations)
            s = sorted(durations)
            trip_stats.append({
                "origin_id": origin_id,
                "dest_id": dest_id,
                "sample_count": n,
                "median_trip_ms":      round(statistics.median(s), 1),
                "mean_trip_ms":        round(statistics.mean(s), 1),
                "p90_trip_ms":         round(s[min(int(n * 0.9), n - 1)], 1) if n >= 10 else None,
                "station_overhead_ms": round(self._station_overhead_ms, 1),
                "route_line_ids":      route_line_ids.get((origin_id, dest_id), []),
            })

        # -------------------------------------------------------
        # Summary panels (mirrors Java SummaryTripStats)
        # -------------------------------------------------------
        completed = self._completed_trips
        n_carried   = len(completed)
        n_travelling = sum(1 for p in self._pods if p.passenger_count > 0)
        n_waiting    = sum(len(q) for q in self._waiting.values())

        travel_times_s  = [t.travel_ms(tick_s) / 1000 for t in completed]
        wait_times_s    = [t.wait_ms(tick_s)   / 1000 for t in completed]
        distances_m     = [t.route_length_m            for t in completed]

        velocities_kmph: List[float] = []
        for t in completed:
            travel_s = t.travel_ms(tick_s) / 1000
            if travel_s > 0 and t.route_length_m > 0:
                velocities_kmph.append((t.route_length_m / travel_s) * 3.6)

        simulated_s      = total_ticks * tick_s
        simulated_hours  = simulated_s / 3600
        throughput_per_hr = round(n_carried / simulated_hours, 1) if simulated_hours > 0 else 0

        def _hms(sec: float) -> str:
            sec = int(sec)
            return f"{sec // 3600:02d}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"

        # Convergences / divergences (switches)
        convergences = sum(1 for n in self.network.nodes.values() if len(n.inbound)  > 1)
        divergences  = sum(1 for n in self.network.nodes.values() if len(n.outbound) > 1)

        summary = {
            # Capacity
            "passengers_carried":   n_carried,
            "passengers_travelling": n_travelling,
            "passengers_waiting":   n_waiting,
            "throughput_per_hour":  throughput_per_hr,
            # Velocity (km/h)
            "avg_velocity_kmph":    round(statistics.mean(velocities_kmph),  1) if velocities_kmph else 0,
            "slowest_velocity_kmph": round(min(velocities_kmph),             1) if velocities_kmph else 0,
            # Timings (minutes)
            "avg_trip_time_min":     round(statistics.mean(travel_times_s) / 60, 2) if travel_times_s else 0,
            "longest_trip_time_min": round(max(travel_times_s) / 60,             2) if travel_times_s else 0,
            "longest_wait_time_min": round(max(wait_times_s)   / 60,             2) if wait_times_s   else 0,
            # Distance (km)
            "avg_trip_distance_km":   round(statistics.mean(distances_m) / 1000, 3) if distances_m else 0,
            "total_trip_distance_km": round(sum(distances_m)             / 1000, 3),
            # Run
            "simulated_time_hms": _hms(simulated_s),
            "machine_time_hms":   _hms(wall_elapsed_s),
            # Network
            "station_count":       len(self.network.stations),
            "line_count":          len(self.network.lines),
            "total_network_km":    round(self.network.total_length_m() / 1000, 3),
            "total_pods":          self.pods_per_station * len(self.network.stations),
            # Stations (convergences / divergences)
            "convergence_count": convergences,
            "divergence_count":  divergences,
        }

        # -------------------------------------------------------
        # Line stats — includes congestion metrics
        # -------------------------------------------------------
        max_line_km = max(
            (l.length_m for l in self.network.lines.values()), default=1
        ) / 1000

        line_stats = []
        for lid, line in self.network.lines.items():
            mean_ms  = line.fleet_mean_ms()
            n_transits = len(line.transit_samples_ms)
            # congestion ratio: avg transit time vs physics minimum (0=fast, 1=jammed)
            phys_ms  = self.physics.transit_time_ms(line.length_m) if line.length_m > 0 else None
            congestion = None
            if mean_ms and phys_ms and phys_ms > 0:
                congestion = round(min((mean_ms / phys_ms) - 1.0, 1.0), 3)  # 0=free-flow, 1=double-time
            line_stats.append({
                "line_id":    lid,
                "start_node": line.start_node.node_id,
                "end_node":   line.end_node.node_id,
                "length_m":   round(line.length_m, 1),
                "pods_arrived": n_transits,
                "pods_left":    n_transits,
                "avg_time_s":   round(mean_ms / 1000, 2) if mean_ms else None,
                "congestion":   congestion,
                "fleet_median_transit_ms": _round_opt(line.fleet_median_ms()),
                "fleet_mean_transit_ms":   _round_opt(mean_ms),
                "fleet_p90_transit_ms":    _round_opt(line.fleet_p90_ms()),
            })

        # -------------------------------------------------------
        # Station stats — passengers boarded / alighted
        # -------------------------------------------------------
        station_boarded  = defaultdict(int)
        station_alighted = defaultdict(int)
        for trip in completed:
            station_boarded[trip.origin_id]  += 1
            station_alighted[trip.dest_id]   += 1

        station_stats = []
        for sid, st in self.network.stations.items():
            waiting_count = len(self._waiting.get(sid, []))
            station_stats.append({
                "station_id":          sid,
                "passengers_boarded":  station_boarded.get(sid, 0),
                "passengers_alighted": station_alighted.get(sid, 0),
                "passengers_waiting_end": waiting_count,
            })

        return SimResult(
            network_id=self.network.network_id,
            settings=self.settings,
            total_ticks=total_ticks,
            passengers_generated=self._passengers_generated,
            passengers_served=self._passengers_served,
            summary=summary,
            trip_stats=trip_stats,
            line_stats=line_stats,
            station_stats=station_stats,
        )


def _round_opt(v):
    if v is None:
        return None
    return round(v, 1)
