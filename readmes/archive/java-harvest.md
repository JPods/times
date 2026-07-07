# Route-Time Java → Python: What's Been Ported and What Remains

Source audited: `route-time-java/src/com/instinct/`

---

## Already in the Python Port

| Feature | Java class | Python location |
|---------|-----------|-----------------|
| Physics model (acc/decc/velocity, transit_time_ms) | `SimulationSettings`, `Pod.java` | `engine/physics.py` |
| Dijkstra routing | `RouteTableService` | `engine/routing.py` |
| Station + traffic circle structures | `Network`, `StationGroup`, `Circle` | `engine/structures.py` |
| Discrete-tick simulation | `Simulator` | `engine/simulation.py` |
| Demand / LoadArray (360-slot passenger generation) | `LoadArray`, `StationLoadConfig` | `engine/demand.py` |
| Line congestion detection (>4 pods, <8m spacing → jammed) | `Line.isJammed()` | `engine/network.py Line.is_jammed()` |
| 8 reporting panels (Capacity, Velocity, Timings, Distance, Run, Network, Stations, Lines) | `SummaryResult`, `SummaryTripStats` | `engine/simulation.py _build_result()` |
| Trip stats (station-to-station, with station overhead) | `Passenger`, `TimeGridData` | `engine/simulation.py TripRecord` |
| Station data (boarded / alighted) | `StationData` | `engine/simulation.py station_stats` |
| Line data (pods arrived/left, avg time, congestion) | `LineData`, `PodQueueStat` | `engine/simulation.py line_stats` |
| Route grid (N×N travel time matrix, color-coded) | `TimeGrid`, `TimeColor` | `gui/static/simulator.js _showResults()` |
| Pod animation replay (station-to-station full routes) | visual only | `gui/static/simulator.js _buildFrames()` |
| Save/load .jpd | XML serializer | `io/` |
| Load SketchUp map.json | `NetworkLoader` | `io/sketchup_loader.py` |
| Settings (all 11 parameters) | `SimulationSettings` | `settings.json`, `gui/static/settings.js` |
| Demand editor (per-station pax/hr + destinations) | `StationLoadConfig` | `gui/static/demand.js` |
| Orphan detection (unconnected structures pulse orange) | N/A (not in Java) | `gui/static/app.js _markOrphans()` |

---

## What Remains — Ordered by Priority

### Priority 1 — Simulation Correctness

These affect whether the simulation models JPods physics accurately.

---

#### 1a. Pod Minimum Gap Formula
**Java:** `Pod.getMinGap()`, `Config.java`

```java
public double getMinGap() {
    return 2 * velocity + stoppingDistance + minGap + podLen;
}
// stoppingDistance = v² / (2 × deccInTU)
// minGap = 3 m (safety buffer)
// podLen = 3 m
```

**Current Python behavior:** Congestion uses headcount/spacing threshold. No per-pod safe following distance.  
**What to port:** Add `pod_len = 3` and `min_gap = 3` to settings; use the formula in pod advance logic so pods actually brake for the pod ahead.  
**Missing settings to add:** `podLen` (3 m), `minGap` (3 m), `podSpace` (3 m).

---

#### 1b. Proper Per-Tick Velocity Physics
**Java:** `Pod.getDisplacementAndSetNewVelocity()`

```java
// Deceleration uses midpoint formula (not linear):
if (BREAK) displacement = velocity - 0.5 * deccInTU;
if (ACCEL) displacement = velocity + 0.5 * accInTU;
```

**Current Python behavior:** `Pod.advance()` uses constant `cruise_m_per_tick` — no acceleration ramp per tick.  
**What to port:** Add `velocity` field to `Pod`; each tick apply acc/decc based on distance remaining to end of line and to pod ahead.  
**Impact:** Short guideways (< stopping distance) currently report unrealistically short transit times.

---

#### 1c. Two-Lines-Ahead Jam Detection
**Java:** `Pod.isNext2LinesJammed()`

```java
// Before taking next line, check 2 lines ahead:
if (nextLine.isJammed() || isNext2LinesJammed(nextLine) || loopDetector.isOnLoop()) {
    tryAlternateExit(crossing);
}
```

**Current Python behavior:** Jammed lines get infinite Dijkstra weight — pods re-route at dispatch time, not dynamically mid-trip.  
**What to port:** At each line transition, peek 2 lines ahead and take the alternate exit if available and clear.

---

#### 1d. Loop Detection
**Java:** `LoopDetector.java`

```java
// Tracks lines visited while in a traffic circle; flags if same line seen twice
if (lines.contains(line.getId())) isOnLoop = true;
```

**Current Python behavior:** None. Pods can circulate indefinitely in traffic circles if routing table produces a loop.  
**What to port:** `Set<line_id>` on each Pod; reset when leaving traffic circle; flag if revisiting.

---

#### 1e. Merge Locking (EZone Coordination)
**Java:** `MergeAheadEvent.java`

The most complex missing piece. When two pods approach the same merge point simultaneously, one must yield.

```java
// Priority rules:
// 1. Pod on traffic circle has precedence over pod on through-line
// 2. Pod on short line (< 50m) yields to pod on long line
// 3. Pod farther behind yields to pod closer to merge
// 4. If deadlock (both velocity == 0), the pod without lock yields
```

**Current Python behavior:** No merge coordination. Both pods try to enter the merge point simultaneously.  
**Impact:** Overstates throughput on networks with heavy merge traffic (traffic circles under load).

---

### Priority 2 — Accurate Pod Redistribution

---

#### 2a. Pod Distributor (Long-Wait Redistribution)
**Java:** `PodDistributor.java`

```java
// If a passenger has been waiting > 5 minutes and no pod is at their station:
// Find closest station with a free pod and dispatch it empty to the waiting station
if (waitingTime > timeResolutionPerSec * 300) {
    callPod(closestNeighbourWithFreePod, waitingStation);
}
```

**Current Python behavior:** Pods dispatch from depot when needed; no rebalancing of pods already at other stations.  
**Impact:** Underestimates wait times for edge stations far from depot.

---

#### 2b. Station Pod Capacity Cap
**Java:** `Station.callPodFromDepot()`, max 75 pods per station

```java
private static final int RESERVED_POD = 75;
if (podsExpended.get() >= RESERVED_POD) return;
```

**Current Python behavior:** Unlimited pods can be dispatched. A runaway demand scenario won't cap correctly.

---

### Priority 3 — Analysis Features

---

#### 3a. Time Graph (Accessibility Rings)
**Java:** `TimeGraph.java`, `GraphPainter.java`

Draws concentric rings on the map around a clicked station showing which areas are reachable within 5, 10, 20, 30 minutes. Rings include walking distance from the click point to the nearest station, plus simulated travel time, plus walking from destination station to click destination.

**Key formula:**
```java
ringRadius_m = walkingSpeed * (ringTime - travelTime - walkingTimeToNearestStation)
```

Color bands match `TimeColor` (green < 5 min → red > 30 min).

**Status:** Not started. Requires: TimeGridData (✅ have it), vincenty distance (✅ have it), Leaflet circle layer.

---

#### 3b. Modal Comparison (Car / Bus / Train vs JPod)
**Java:** `SavingDisplay.java`

Three bar charts: Energy (Wh/km), Speed (km/h), Land use (sq ft/km).

**Hardcoded values from Java:**

| Mode | Energy (Wh/km) | Speed (km/h) | Land (sq ft/km) | Bar color |
|------|----------------|--------------|-----------------|-----------|
| JPod | 79 | simulated avg | 1,500 | #4CAF50 green |
| Car | 642 | 38 | 30,000 | #F44336 red |
| Bus | 774 | 15 | 24,000 | #FF9800 orange |
| Train | 547 | 29 | 42,000 | #2196F3 blue |

**Status:** Not started. Simple chart — all values are constants except JPod speed and total network km from the simulation result.

---

#### 3c. Merge Load Calculator
**Java:** `MergeLoadCalculator.java`

Counts how many O-D paths pass through each convergence node. Normalizes to get relative load at each merge. Used to highlight high-traffic merge points on the map.

```java
// For all O-D pairs:
//   Run Dijkstra, count how many paths include each switch node
mergeLoads[nodeId] = pathsThrough / (stationCount * 2)
```

**Status:** Not started. Straightforward post-processing of routing results.

---

### Priority 4 — Reusability Features

---

#### 4a. Template Save/Load (.tld)
**Java:** `TemplateManager.java`, `MergingService.java`

Save a selected sub-network as a `.tld` XML file (same format as `.jpd`). Load and place at a map click point — coordinates are translated relative to the bounding-box center.

```java
// Placement translation:
lat_new = clickLat + (node.lat - templateCenterLat)
lon_new = clickLon + (node.lon - templateCenterLon)
```

**Status:** Designed in `readmes/todo.md`. API endpoint spec written. Not implemented.

---

#### 4b. Network Validation
**Java:** `NetworkValidator.java`

Three checks before simulation:
1. **Incomplete switches** — node with 0 inputs or 0 outputs, or (2 inputs AND 2 outputs with no through-connection)
2. **Incomplete lines** — line missing start or end node
3. **Unreachable paths** — Dijkstra returns no route between any station pair

**Status:** Not started. The orphan pulse (new) catches case 3 visually; formal validation for cases 1 and 2 would improve pre-sim error messages.

---

## Settings to Add

These Java `SimulationSettings` fields are not yet in `settings.json`:

| Setting | Default | Used for |
|---------|---------|---------|
| `podLen` | 3 m | Minimum gap formula |
| `minGap` | 3 m | Minimum gap formula |
| `podSpace` | 3 m | Station parking spacing |
| `slowMotion` | 0 | Animation speed multiplier |
| `jpodBarColor` | #4CAF50 | Modal comparison chart |
| `carBarColor` | #F44336 | Modal comparison chart |
| `busBarColor` | #FF9800 | Modal comparison chart |
| `trainBarColor` | #2196F3 | Modal comparison chart |

---

## What to Skip

| Java feature | Reason |
|-------------|--------|
| Swing/AWT GUI (JFrame, JTable, JDialog, etc.) | Browser replaces all of it |
| XML serialization (JAXB, SAXBuilder, XMLOutputter) | Python uses JSON for .jpd |
| WorkspaceManager singleton | Python uses Flask `_state` dict |
| GlobalTimeKeeper | Python uses local tick counter |
| Thread safety (AtomicInteger, synchronized) | Python sim is single-threaded |
| RoundRobin pod selection | Absorbed by Dijkstra dispatch |
| ResultManager (.res files) | Python returns JSON directly |
