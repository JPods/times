# Route-Time — JPods Network Planner

Python simulation and browser-based planning tool for JPods networks.
Reads `.jpd` files and `map.json`, outputs fleet-median transit times per line.

---

## Start the server

```bash
cd /Users/williamjames/Documents/08_JPods/03_Technology
python -m route_time.gui
```

Then open **http://localhost:5050** in the browser.

> Must be run from `03_Technology` (one level above `route_time/`).
> Running from inside `route_time/` causes a `ModuleNotFoundError`.

---

## Running

```bash
cd /Users/williamjames/Documents/08_JPods/03_Technology
python -m route_time.gui          # opens http://localhost:5050
python -m route_time.gui network.jpd   # preload a file
python -m route_time <file>       # CLI only (no browser)
```

---

## Architecture

Three programs share the same network:

| Program | Role |
|---------|------|
| **SketchUp plugin** | 3D design — places structures, assigns CPs |
| **Route-Time** (this tool) | 2D planning — simulates transit times, designs networks |
| **JPodsSM_RPi** | Runtime — Nora/Natalie/Noelle control on the Pi |

---

## Color Standard — Red Inbound, Blue Outbound

**All directional indicators across the Route-Time GUI and JPods tools follow this rule:**

| Color | Meaning |
|-------|---------|
| 🔴 **Red** | Inbound — hot end — vehicle or flow arriving |
| 🔵 **Blue** | Outbound — cool end — vehicle or flow departing |

Applied consistently to:
- Guideway polylines on the map
- CP stub-pair dots (blue dot = outbound stub, red dot = inbound stub)
- Station siding lines (south approach = red/inbound, north exit = blue/outbound)

This mirrors the physical reality: a vehicle entering a station or junction is "hot" (carrying passengers, consuming energy); a vehicle departing is "cool" (dispatched, energy stored).

---

## Connection Points (CPs)

Every structure (station, traffic circle) exposes **stub-pairs** — the universal connection interface shared with the SketchUp plugin.

- Each CP = one outbound stub + one inbound stub at the same arm tip
- CPs connect to CPs — never individual lines
- Breaking a connection always removes **both** guideways of the pair

**CP marker appearance:**
- Traffic circle CPs → oval/pill shape
- Station CPs → rectangle shape
- Both contain: blue dot (outbound) + red dot (inbound)
- Open CP → purple border
- Connected CP → green border
- Selected CP → gold target circle

**Interaction:**
- Click a CP → select (gold ring appears)
- Click a second CP → connect the pair (two guideways drawn)
- Ctrl-click a connected CP → disconnect
- Esc → cancel selection

---

## Waypoints

Shift-click any guideway line to place a draggable waypoint marker (gold handle).
Drag the marker to route the guideway pair around terrain.
Shift-click the waypoint handle to remove it.

Ctrl-click a guideway line to remove the entire pair.

---

## Structures

### Traffic Circle (US/CCW)
- 15 m diameter ring
- 4 arms (N/E/S/W), counter-clockwise travel
- Each arm: diverge before merge
- Stubs extend 15 m beyond ring edge (22.5 m from center)
- 4 CPs (one per arm)

### Station (US/CCW, right-side loading)
- ~70 m between north and south turnabouts
- NB guideway east, SB guideway west
- Siding east of NB — always traversed northward
- North turnabout: NB → SB (vehicle exits north going south)
- South turnabout: SB → NB (SB vehicle accesses station)
- 2 CPs: CP_N (north stub-pair) and CP_S (south stub-pair)

---

## Simulation

The simulation engine uses:
- **Discrete tick model** — 360 slots (1 hr, 1 passenger/10 s/station)
- **Dijkstra routing** by line weight (jammed lines → infinite weight)
- **Pod physics** — acceleration/deceleration in G, max velocity in km/h
- **Output** — fleet-median transit time per line → `route_time_ms` in itinerary.json
# times
