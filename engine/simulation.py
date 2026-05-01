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
    trip_key: Optional[str] = None   # set for sweep passengers; None for random demand

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
    # Sweep-only trips — one entry per completed sweep passenger.
    # Used for isochrone coverage and saved to sweep_trips.json for inspection.
    sweep_trips: List[dict] = field(default_factory=list)
    # O-D pairs from either sweep that had no completed trip (disconnected or jammed).
    missing_pairs: List[dict] = field(default_factory=list)

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
            "sweep_trips": self.sweep_trips,
            "missing_pairs": self.missing_pairs,
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
        # station_id → [(dest_station_id, generated_tick, trip_key), ...]
        # trip_key is a unique string for sweep passengers; None for random demand.
        self._waiting: Dict[str, List[Tuple[str, int, Optional[str]]]] = {
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
        """
        Three-phase simulation:

        Phase 1 — Sweep 1
          One vehicle dispatched from every station to every other station.
          Runs until all those trips complete (or queue empties for disconnected
          networks).  Establishes a baseline time for every reachable O-D pair.

        Phase 2 — Random demand + Sweep 2 (concurrent)
          Random passengers are generated according to the demand schedule.
          Simultaneously a second full O-D sweep is queued.  The simulation
          runs until the LAST vehicle from Sweep 2 completes its trip.
          Sweep 2 times reflect real congestion from the mixed load.

        Stopping: when Sweep 2 is fully covered, or when the queue is empty
        and no pods are in flight (handles disconnected sub-networks gracefully).
        """
        self.network.reset()
        wall_start = _time.time()
        self._current_tick = 0

        station_ids = list(self.network.stations.keys())
        ticks_per_slot = self._ticks_per_slot

        # Safety ceiling per phase: 3× the normal scheduled window
        max_ticks_per_phase = total_slots * ticks_per_slot * 3

        # ── helpers ───────────────────────────────────────────────────────────

        def _queue_sweep(sweep_num: int) -> set:
            """Queue one passenger from every station to every other.
            Each passenger gets a unique trip_key so completion can be
            tracked exactly — regardless of random demand completing the
            same O-D pair independently.
            Returns the set of trip_keys queued."""
            keys: set = set()
            for orig in station_ids:
                for dest in station_ids:
                    if dest != orig:
                        key = f"sw{sweep_num}_{orig}_{dest}"
                        self._waiting[orig].append((dest, self._current_tick, key))
                        self._passengers_generated += 1
                        keys.add(key)
            return keys

        def _tick():
            self._tick_pods()
            self._dispatch()
            self._current_tick += 1

        def _queue_empty() -> bool:
            return (not any(self._waiting.values())) and (not self._pods)

        # ── Phase 1: Sweep 1 ──────────────────────────────────────────────────
        sweep1_remaining = _queue_sweep(1)
        prev = 0

        for _ in range(max_ticks_per_phase):
            _tick()
            for trip in self._completed_trips[prev:]:
                if trip.trip_key:
                    sweep1_remaining.discard(trip.trip_key)
            prev = len(self._completed_trips)
            if not sweep1_remaining or _queue_empty():
                break

        # ── Phase 2: Random demand concurrent with Sweep 2 ───────────────────
        sweep2_remaining = _queue_sweep(2)
        demand_ticks_total = total_slots * ticks_per_slot
        demand_tick = 0

        for _ in range(max_ticks_per_phase):
            # Generate random demand in lock-step with scheduled slots
            if demand_tick < demand_ticks_total and demand_tick % ticks_per_slot == 0:
                self._generate_passengers(demand_tick // ticks_per_slot)

            _tick()
            demand_tick += 1

            for trip in self._completed_trips[prev:]:
                if trip.trip_key:
                    sweep2_remaining.discard(trip.trip_key)
            prev = len(self._completed_trips)

            if not sweep2_remaining:
                break  # all Sweep 2 trips done
            if demand_tick >= demand_ticks_total and _queue_empty():
                break  # random demand exhausted and nothing in flight

        # ── Phase 3+: Coverage rounds ─────────────────────────────────────────
        # After the two sweeps, check which O-D pairs still have no completed
        # trip.  For each reachable-but-uncovered pair, dispatch another vehicle
        # and wait for it to arrive.  Repeat until every topologically reachable
        # pair is covered, or a pair proves disconnected (jam-free route = []).
        # Each round uses a unique sweep number (3, 4, 5, …) for tracking.
        coverage_sweep = 3
        MAX_COVERAGE_ROUNDS = 20   # safety: stop after 20 extra rounds

        for _round in range(MAX_COVERAGE_ROUNDS):
            covered = {(t.origin_id, t.dest_id) for t in self._completed_trips}
            all_pairs = {(o, d) for o in station_ids for d in station_ids if o != d}
            missing = all_pairs - covered
            if not missing:
                break   # full coverage achieved

            # Filter to pairs that have a topological route (jam-free)
            reachable_missing = []
            for (orig, dest) in missing:
                src = self.network.stations[orig].node
                dst = self.network.stations[dest].node
                if find_path(self.network, src, dst, self.grace_distance, jam_free=True):
                    reachable_missing.append((orig, dest))

            if not reachable_missing:
                break   # remaining gaps are truly disconnected

            coverage_remaining: set = set()
            for (orig, dest) in reachable_missing:
                key = f"sw{coverage_sweep}_{orig}_{dest}"
                self._waiting[orig].append((dest, self._current_tick, key))
                self._passengers_generated += 1
                coverage_remaining.add(key)

            for _ in range(max_ticks_per_phase):
                _tick()
                for trip in self._completed_trips[prev:]:
                    if trip.trip_key:
                        coverage_remaining.discard(trip.trip_key)
                prev = len(self._completed_trips)
                if not coverage_remaining or _queue_empty():
                    break

            coverage_sweep += 1

        # Build result — any pairs still missing are genuinely disconnected
        all_remaining_keys: set = set()
        # (coverage_remaining may be empty by now; that's fine)
        return self._build_result(
            self._current_tick,
            wall_elapsed_s=_time.time() - wall_start,
            incomplete_sweep_keys=all_remaining_keys,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_passengers(self, slot: int):
        pairs = self._demand.get_passengers(slot)
        for origin_id, dest_id in pairs:
            if origin_id in self._waiting:
                self._waiting[origin_id].append((dest_id, self._current_tick, None))
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
                # If pod was not immediately re-dispatched and this station is
                # over its pod quota, return the surplus to the depot so other
                # pod-starved stations can pull from it.
                if pod in station.queued_pods:
                    waiting_here = bool(self._waiting.get(station.station_id))
                    if not waiting_here and len(station.queued_pods) > self.pods_per_station:
                        station.queued_pods.remove(pod)
                        self._return_to_depot(pod)
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
        dest_id, gen_tick, trip_key = waiting.pop(0)
        dest_station = self.network.stations.get(dest_id)
        if dest_station is None:
            return

        route = find_path(
            self.network,
            station.node,
            dest_station.node,
            self.grace_distance,
            jam_free=(trip_key is not None),  # sweep passengers always route
        )
        if not route:
            # Re-queue at back — keep same trip_key so sweep tracking is exact.
            waiting.append((dest_id, gen_tick, trip_key))
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
            trip_key=trip_key,
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

            dest_id, gen_tick, trip_key = waiting.pop(0)
            dest_station = self.network.stations.get(dest_id)
            if dest_station is None:
                self._depot.append(pod)
                continue

            route = find_path(
                self.network,
                station.node,
                dest_station.node,
                self.grace_distance,
                jam_free=(trip_key is not None),  # sweep passengers always route
            )
            if not route:
                # Re-queue at back — keep same trip_key so sweep tracking is exact.
                # Permanently unreachable pairs will stay here until the safety
                # ceiling ends the phase; they will simply not appear in trip_stats.
                waiting.append((dest_id, gen_tick, trip_key))
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
                trip_key=trip_key,
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

    def _build_result(self, total_ticks: int, wall_elapsed_s: float = 0.0,
                      incomplete_sweep_keys: Optional[set] = None) -> SimResult:
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

        # -------------------------------------------------------
        # Sweep trips — one row per completed sweep passenger
        # -------------------------------------------------------
        sweep_trips = []
        for trip in self._completed_trips:
            if trip.trip_key is None:
                continue
            total_ms = trip.travel_ms(tick_s) + self._station_overhead_ms
            wait_ms  = trip.wait_ms(tick_s)
            sweep_trips.append({
                "trip_key":   trip.trip_key,
                "sweep":      int(trip.trip_key[2]) if len(trip.trip_key) > 2 else 0,
                "origin_id":  trip.origin_id,
                "dest_id":    trip.dest_id,
                "travel_min": round(total_ms  / 60_000, 3),
                "wait_min":   round(wait_ms   / 60_000, 3),
                "dist_m":     round(trip.route_length_m, 1),
            })
        sweep_trips.sort(key=lambda r: (r["origin_id"], r["dest_id"], r["sweep"]))

        # O-D pairs that had no completed sweep trip
        missing_pairs = []
        if incomplete_sweep_keys:
            seen: set = set()
            for key in sorted(incomplete_sweep_keys):
                # key format: "sw{N}_{orig}_{dest}"
                parts = key.split("_", 2)
                if len(parts) == 3:
                    _, orig, dest = parts
                    pair = (orig, dest)
                    if pair not in seen:
                        seen.add(pair)
                        missing_pairs.append({"origin_id": orig, "dest_id": dest})

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
            sweep_trips=sweep_trips,
            missing_pairs=missing_pairs,
        )


def _round_opt(v):
    if v is None:
        return None
    return round(v, 1)
