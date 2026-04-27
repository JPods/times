# Route-Time — Basic Concepts

Route-Time simulates the physical world that JPodsSM_RPi operates in.
JPodsSM_RPi is the real system — Nora, Natalie, and Noelle running on hardware.
Route-Time is the planning tool — it models that world so networks can be designed,
transit times estimated, and fleet sizes calculated before anything is built.

---

## The Real World (JPodsSM_RPi)

### Physical structure

A JPods network is a directed graph of **lines** (guideways) connecting **nodes**
(merge points, diverge points, stations). Vehicles travel one direction on each line.
The graph is stored in `network_map.json` and managed by **Noelle** (load balancer).

### Lines

Each line has:
- A unique ID
- A start node and end node with 3D coordinates
- A length (mm)
- Adjacency: which lines share the start node (predecessors) and end node (successors)
- An EZ ID if the node is a merge or diverge (see below)

### Exclusive zones (EZ)

Merges and diverges are controlled by exclusive zones — one vehicle at a time.
This is zipper-merge behavior: vehicles alternate, no two vehicles occupy the
intersection simultaneously.

Each line's start or end node carries an `ez_id`. Nora looks up the EZ geometry
from her local `map.json`. Her onboard sensors (wheel encoders, ToF, accelerometers,
cameras) tell her where she is on the line. She requests the EZ lock when she reaches
the entry distance and releases it when she clears the exit distance.

```json
"start": {
  "id": 1,
  "ez_id": "EZ_1",
  "lines": [3, 9]
},
"end": {
  "id": 2,
  "lines": [4]
}
```

- `start.lines` has 2 entries → merge → EZ required
- `end.lines` has 2 entries → diverge → EZ required
- Single entry at either end → straight through → no EZ

### Three agents

| Agent | Role | Data |
|-------|------|------|
| **Noelle** | Network — physical structure, EZ state, line occupancy | `network_map.json` |
| **Natalie** | Router — assigns trips, sequences lines from origin to destination | `trip.json` |
| **Nora** | Vehicle — executes trips, manages EZ locks, learns from experience | local `map.json` + experience DB |

Nora only needs a sequence of line IDs from Natalie. She handles all physical
behavior herself. Her experience database (keyed by line ID) stores what she has
learned from cameras, encoders, and sensors — speed profiles, braking points,
EZ timing. That knowledge stays in the vehicle and improves over time.

### Stations

Stations are structures where vehicles stop to load and unload. A station has two
connection points (CPs) — one on the north end, one on the south — that connect to
the mainline guideways. The siding (loading track) is internal to the structure.
Platform behavior (speed, stop position, door timing) is part of `trip.json`,
not `network_map.json`.

---

## How Route-Time Simulates This

### Network model

Route-Time reads lines, nodes, and CP connections to build the same directed graph
that Noelle manages at runtime. Structures (stations, traffic circles) are placed
as objects — their internal geometry is generated from a center point and heading,
matching what would be physically built.

### Transit time simulation

Route-Time uses a **discrete tick model** (1 tick = 10 seconds, 360 ticks = 1 hour).
Passengers arrive at stations at a fixed rate. Pods are dispatched by Dijkstra
routing weighted by line congestion. Pod physics (acceleration in G, max velocity
in km/h) are applied to compute travel time per line. The output is fleet-median
transit time per origin-destination pair.

### EZ simulation

Route-Time does not yet simulate EZ contention explicitly. Lines that belong to a
merge node are treated as converging into a single outgoing line; their combined
demand is checked against capacity. Full EZ lock/release timing is a Nora behavior
— it affects headway at junctions but not the network-level transit time that
Route-Time is designed to estimate.

### What Route-Time does not simulate

- Nora's onboard sensor fusion and experience database
- MQTT messaging between agents
- Hardware faults, door timing, boarding dwell variation
- Per-vehicle EZ negotiation latency

These are JPodsSM_RPi concerns. Route-Time gives Noelle and Natalie the network
design they need to make those behaviors possible.

---

## Data Formats

| File | Owner | Purpose |
|------|-------|---------|
| `network_map.json` | Noelle | Physical lines, nodes, EZ IDs, adjacency |
| `trip.json` | Natalie → Nora | Ordered line sequence + platform/speed instructions |
| `map.json` | Nora (local) | EZ geometry, segment arcs, marker positions |
| `.jpd` | Route-Time | Network save format — loads into Route-Time for planning |

Route-Time can import `map.json` (existing scale model format) and will export
`network_map.json` as the canonical format for the full-scale system.
