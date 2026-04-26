# Route-Time — Settings and Metrics Reference

Settings live in `settings.json` at the project root.  
Edit via the **⚙ Settings** panel in the palette or directly in the file.  
All values match Java `SimulationSettings` defaults.

---

## Settings Variables

### Vehicle Physics

| Setting | Default | Unit | Effect |
|---------|---------|------|--------|
| `maxVelocityInKMPH` | 60 | km/h | Cruise speed once fully accelerated. Higher = shorter travel time on long guideways. No effect if the guideway is too short to reach cruise. |
| `accInG` | 1.0 | G (9.81 m/s²) | Acceleration from rest to cruise. Higher = shorter ramp-up distance; pods reach cruise faster. |
| `deccInG` | 1.0 | G (9.81 m/s²) | Deceleration into a station. Higher = shorter stopping distance. |
| `graceDistance` | 0 | m | Bias added to every edge weight in Dijkstra. A small positive value (1–5 m) nudges routing to prefer fewer, shorter hops over many long ones. |

**Physics model** for one guideway segment:

```
d_acc  = (v_max² − v_entry²) / (2 × acc)       — distance to reach cruise
d_decc = (v_max² − v_exit²)  / (2 × decc)      — distance to stop
```

If `d_acc + d_decc > segment_length`, the pod never reaches cruise — a triangular velocity profile is computed to find the peak speed instead.

---

### Fleet

| Setting | Default | Unit | Effect |
|---------|---------|------|--------|
| `podsPerStation` | 4 | pods | Pods pre-positioned at each station at simulation start. More pods = shorter wait times, especially under high demand. |
| `timeResolutionPerSec` | 9 | ticks/s | Internal simulation clock. One tick = 1/9 s ≈ 111 ms. Do not change unless matching a specific Java run for comparison. |

**Derived:** Total pods in network = `podsPerStation × station_count`.

---

### Station Timing

These are overhead times — the time a passenger spends **outside the moving pod**. They are not modeled tick-by-tick; they are added analytically to every trip time.

| Setting | Default | Seconds | Phase |
|---------|---------|---------|-------|
| `ticketingTimeInSec` | 30 | 30 s | Buying ticket at kiosk |
| `stationEntryTimeInSec` | 40 | 40 s | Walking from street to platform |
| `embarkingTimeInSec` | 20 | 20 s | Boarding the pod |
| `disembarkingTimeInSec` | 20 | 20 s | Exiting the pod |
| `stationExitTimeInSec` | 40 | 40 s | Walking from platform to street |

**Total station overhead at defaults: 150 seconds (2 min 30 s) per trip.**

Every trip time shown in the sidebar and route grid includes this overhead.  
To model an express station (no ticketing, direct boarding): set `ticketingTimeInSec = 0`, `stationEntryTimeInSec = 0`.

---

## Simulation Inputs

### `demand.json` — Passenger Volume

Controls how many passengers per hour depart each station, and where they go.

```json
{
  "total_slots": 360,
  "stations": {
    "ST_xxx": {
      "destinations": {
        "ST_yyy": 180,
        "ST_zzz": 180
      }
    }
  }
}
```

- `total_slots` = 360 slots/hour = 1 passenger generated every 10 seconds per station.
- Each destination value is the number of those 360 slots assigned to that destination.
- Stations not listed get uniform random distribution across all other stations.
- Sum of destination values should not exceed `total_slots`.

**Increasing load:** Run at 360 slots (default) → 720 → 1440. At high load, pods become unavailable, wait times grow, some passengers are not served. The route grid cells will shift from green toward red.

### Simulation Slots (UI)

The **Slots** input in the palette sets `total_slots` for the run.  
360 slots = 1 simulated hour, 1 passenger/10 sec/station.  
720 slots = double demand. 1440 = quadruple (stress test).

---

## Output Metrics

### Capacity Panel

| Metric | What it means |
|--------|--------------|
| Carried | Passengers who completed origin → destination |
| Travelling | Passengers in motion at simulation end |
| Waiting | Passengers still in queue at simulation end |
| Throughput/hr | Carried ÷ simulated hours — effective system capacity |

**Congestion signal:** If `Waiting > 0` at end of simulation, supply is falling behind demand. Increase `podsPerStation` or reduce load.

---

### Velocity Panel (km/h)

| Metric | What it means |
|--------|--------------|
| Avg velocity | Mean of (route_distance ÷ pod_travel_time) × 3.6, across all completed trips |
| Slowest | Minimum trip velocity — identifies the most congested or longest route |

Avg velocity will always be ≤ `maxVelocityInKMPH`. It drops below cruise on short segments where the pod never reaches full speed, and on heavily loaded networks where routing around jammed lines adds distance.

---

### Timings Panel

| Metric | What it means |
|--------|--------------|
| Avg trip time | Mean pod-in-motion time (seconds ÷ 60). Does **not** include station overhead. |
| Longest trip | Worst-case travel time — the hardest origin-destination pair |
| Longest wait | Worst-case time from passenger generation to pod dispatch. Grows under congestion. |

---

### Distance Panel

| Metric | What it means |
|--------|--------------|
| Avg trip distance | Mean route length in km |
| Total trip distance | Sum of all pod travel across all completed trips |

Total trip distance ÷ avg trip distance ≈ number of completed trips (cross-check against Carried).

---

### Run Panel

| Metric | What it means |
|--------|--------------|
| Simulated time | Duration of the simulated scenario (HH:MM:SS) — 360 slots × 10 s/slot = 1:00:00 |
| Machine time | Actual CPU time to run the simulation — should be < 1 s for normal networks |

---

### Network Panel

| Metric | What it means |
|--------|--------------|
| Stations | Number of station structures placed |
| Lines | Number of directed guideway segments |
| Length (km) | Total guideway length — the network's physical scale |
| Total pods | `podsPerStation × station_count` — total fleet size |

---

### Stations Panel

Renamed from Java "Switches." Shows the topology of decision points.

| Metric | What it means |
|--------|--------------|
| Convergences | Nodes where 2+ inbound lines merge (merge zones / EZs) |
| Divergences | Nodes where 1 line splits into 2+ outbound (switch points) |

High convergence count relative to line count = dense merging network (traffic circle heavy).  
Low count = mostly through-routing with few branching points.

---

### Line Data Table

One row per guideway segment that carried at least one pod.

| Column | What it means |
|--------|--------------|
| Line | Line ID (truncated) |
| In / Out | Number of pods that entered and exited this segment |
| Avg s | Average pod traversal time in seconds |
| Cong | Congestion bar — green = free-flow, red = heavily loaded |

**Congestion ratio:** `(avg_actual_time ÷ physics_minimum_time) − 1`.  
0.0 = free-flow (actual matches physics minimum).  
1.0 = double the physics minimum (pod waited or detoured).  
Values above 0.5 indicate lines that need capacity relief.

---

### Station Data Table

One row per station.

| Column | What it means |
|--------|--------------|
| Boarded | Passengers dispatched from this station |
| Alighted | Passengers delivered to this station |

Balanced stations (Boarded ≈ Alighted) indicate uniform demand. A high-departure, low-arrival station is a major origin (e.g., a transit hub or park-and-ride). A high-arrival, low-departure station is a major destination (e.g., an employment center or event venue). This asymmetry informs fleet rebalancing needs.

---

### Trip Times Table

One row per origin-destination pair. Sorted by longest median trip first.

| Column | What it means |
|--------|--------------|
| Origin → Dest | Station pair |
| Median | Median door-to-door trip time including 150 s station overhead |
| n | Number of completed trips — low counts mean infrequent demand or connectivity problems |

---

### Route Grid

N × N matrix. Rows = origin, columns = destination.

| Color | Minutes | Meaning |
|-------|---------|---------|
| Bright green | < 5 min | Excellent — short, direct route |
| Green-yellow | 5–10 min | Good |
| Yellow | 10–15 min | Acceptable |
| Yellow-orange | 15–20 min | Marginal — consider adding a direct connection |
| Orange-brown | 20–25 min | Poor — network too sparse or demand too high |
| Orange-red | 25–30 min | Congested or very indirect routing |
| Red | > 30 min | Unacceptable — redesign the network segment |

Empty cells (—) mean no trips were completed between that pair during the simulation. Check connectivity (are those stations reachable from each other?).

---

## Key Relationships

```
Door-to-door trip time = pod_travel_time + station_overhead (150 s default)

pod_travel_time = sum of transit_time_ms for each guideway in the route

transit_time_ms per segment:
  if short segment:  t = ramp_up + ramp_down  (no cruise)
  if long segment:   t = ramp_up + cruise + ramp_down

avg_velocity = route_distance_m / pod_travel_time_s × 3.6  (km/h)

throughput_per_hour = passengers_carried / (total_ticks × tick_s / 3600)

congestion_ratio = (avg_actual_time_ms / physics_min_time_ms) − 1
```

---

## Tuning Guide

| Goal | Lever |
|------|-------|
| Reduce trip times | Increase `maxVelocityInKMPH`, shorten guideway routes (add direct connections) |
| Reduce wait times | Increase `podsPerStation`, reduce `ticketingTimeInSec` / `stationEntryTimeInSec` |
| Increase throughput | More pods, more parallel guideways, relieve jammed segments |
| Model a more walk-friendly station | Lower station entry/exit times |
| Stress-test the network | Double or quadruple slots; watch route grid shift toward red |
| Find bottlenecks | Sort Line Data by Congestion; the red bars are the constraints |
