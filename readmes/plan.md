# Route-Time — Feature Plan

Status legend: ✅ Done · 🔧 Partial · ⬜ Not started

---

## 1. Startup & Server

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Launch server from `03_Technology/` | ✅ | `python -m route_time.gui` opens http://localhost:5050 | Browser opens, empty map loads |
| Preload network file at startup | ✅ | `python -m route_time.gui network.jpd` | Network renders on load |
| Persist map view (pan/zoom) across sessions | ✅ | Pan, reload page | Returns to same view |
| Restore last-loaded network | ⬜ | Restart server | Last network reloads automatically |
| Kill stale server on restart | ⬜ | Script or `lsof -ti :5050 | xargs kill -9` | One command restarts cleanly |

---

## 2. Palette — Current Features

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Place station — N/S, E/W, NE/SW, NW/SE | ✅ | Click preset, click map | Station appears at correct heading |
| Place traffic circle — N/E/S/W arms | ✅ | Click button, click map | Circle appears with 4 arms |
| Place traffic circle — NE/SE/SW/NW arms | ✅ | Click 45° button, click map | Circle rotated 45° |
| Place switch node | ✅ | Click button, click map | Switch node placed |
| Draw free guideway line | ✅ | Click two nodes | Directed line drawn |
| Auto-connect network | ✅ | Click Auto-connect | Inner CPs connected, outer left open |
| Waypoint tool — add bend to guideway pair | ✅ | Waypoint tool + click guideway | Draggable handle appears |
| Right-click guideway — aligned bend | ✅ | Right-click guideway | Aligned waypoint added |
| Run simulation | ✅ | Click Run, set slots | Fleet-median times shown in sidebar |
| Tile layer selector (OSM/satellite/topo/dark) | ✅ | Select from dropdown | Map tiles change |
| Collapse palette | ✅ | Click ▲ | Palette collapses to header |

---

## 3. Palette — Needed Features

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Load network from file | ✅ | Click Load, pick .jpd | Network renders, map fits to bounds |
| Save network to file | ✅ | Click Save, enter name | .jpd written to disk |
| New empty network | ✅ | Click New, confirm | Blank network, map cleared |
| Export to `network_map.json` | ⬜ | Click Export | Valid network_map.json written |
| Import from `map.json` (JPodsSM_RPi format) | 🔧 | Load existing map.json | Lines and EZs render correctly |
| Load template (.tld) | ⬜ | Pick template from list | Reusable sub-network placed at cursor |
| Save selection as template (.tld) | ⬜ | Select region, Export template | .tld file saved, reloadable |
| Undo / Redo | ⬜ | Ctrl+Z / Ctrl+Y | Last action reversed / re-applied |

---

## 4. Object Behavior — Stations & Traffic Circles

### 4a. Placement

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Station placed as single object | ✅ | Click map in station mode | All internal nodes + lines + CPs created together |
| Traffic circle placed as single object | ✅ | Click map in circle mode | Ring + stubs + CPs created together |
| Proximity guard — reject overlap | ✅ | Place two structures too close | Error message, no placement |
| Heading preset applied on placement | ✅ | Select heading, click map | Station oriented correctly |
| Station arms rotate from panel | ✅ | Select CP, adjust heading | Internal lines redraw at new heading |

### 4b. Removal

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Delete key removes selected structure | ✅ | Click structure, press Delete | All internal nodes/lines/CPs removed |
| Connector guideways detached on delete | ✅ | Delete connected structure | Partner CP cleared, connector lines removed |
| Region select + Delete removes multiple | ✅ | Shift-drag, Delete | All selected structures removed cleanly |
| Delete single CP | ⬜ | Select lone CP, Delete | CP and its stubs removed |

### 4c. Moving

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Alt+drag CP — moves whole structure | 🔧 | Hold Alt, drag CP marker | Structure (lines + CPs) redraws at drop point |
| Alt+drag structure line — moves whole structure | 🔧 | Hold Alt, drag internal line | Same as above |
| Alt cursor (teal circle) shows grab radius | ✅ | Hold Alt key | Teal circle cursor appears |
| Internal lines disappear on drag start | 🔧 | Begin Alt+drag | Lines vanish immediately (layer group remove) |
| Lines redraw correctly on drop | 🔧 | Release Alt+drag | Full structure redraws via re-render |
| Proximity guard on move | ✅ | Drop structure on top of another | Error, structure snaps back |
| Connector lines follow moved structure | ⬜ | Move connected structure | Connector guideways update to new CP positions |

### 4d. Alignment

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Station heading panel (rotate in place) | ✅ | Select CP, change heading | Station rotates, CPs reposition |
| Traffic circle arm rotation | ✅ | Select CP, rotate | All 4 arms rotate |
| Snap to grid | ⬜ | Hold Shift while placing | Structure snaps to grid spacing |
| Align two structures (share axis) | ⬜ | Select two, click Align | Structures aligned on N/S or E/W axis |

---

## 5. Free Guideway Behavior

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Alt+drag guideway — bend both lines of pair | ✅ | Hold Alt, drag free guideway | New bend point on both guideways |
| Alt+drag existing waypoint handle | ✅ | Hold Alt near handle | Existing handle moves |
| Shift+click guideway — add waypoint | ✅ | Shift+click line | Draggable yellow handle appears |
| Shift+click handle — remove waypoint | ✅ | Shift+click handle | Handle and bend point removed |
| Ctrl+click guideway — remove pair | ✅ | Ctrl+click line | Both guideways of pair deleted |
| Connect CP to CP | ✅ | Click CP, click second CP | Two connector guideways drawn |
| Disconnect CP pair | ✅ | Ctrl+click connected CP | Both connector guideways removed |

---

## 6. Simulation Parameters

All parameters editable in sidebar. Defaults match Java version.

### Vehicle physics

| Parameter | Default | Java equivalent | Status |
|-----------|---------|-----------------|--------|
| Max velocity | 60 km/h | `maxVelocityInKMPH = 60` | ✅ |
| Acceleration | 1.0 G | `accInG = 1` | ✅ |
| Deceleration | 1.0 G | `deccInG = 1` | ✅ |
| Pod length | 3 m | `podLen = 3` | ⬜ |
| Pod spacing (min gap) | 3 m | `minGap = 3` | ⬜ |
| Grace distance | 0 m | `graceDistance = 0` | ⬜ |

### Fleet

| Parameter | Default | Java equivalent | Status |
|-----------|---------|-----------------|--------|
| Pods per station | 4 | `podsPerStation = 4` | ✅ |
| Pods per km | 20 | `podsPerKm = 20` | ⬜ |
| Simulation slots (1 hr) | 360 | 1 passenger / 10 sec / station | ✅ |

### Station timing

| Parameter | Default | Java equivalent | Status |
|-----------|---------|-----------------|--------|
| Embarking time | 20 sec | `embarkingTimeInSec = 20` | ⬜ |
| Disembarking time | 20 sec | `disembarkingTimeInSec = 20` | ⬜ |
| Ticketing time | 30 sec | `ticketingTimeInSec = 30` | ⬜ |
| Station entry time | 40 sec | `stationEntryTimeInSec = 40` | ⬜ |
| Station exit time | 40 sec | `stationExitTimeInSec = 40` | ⬜ |

### Network / pedestrian

| Parameter | Default | Java equivalent | Status |
|-----------|---------|-----------------|--------|
| Walking speed | 10 km/h | `walkingSpeedKMPH = 10` | ⬜ |
| Network total length | computed | `total_km` in metadata | ✅ |
| Time resolution | 9 ticks/sec | `timeResolutionPerSec = 9` | ✅ |

---

## 7. Simulation Output & Replay

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Fleet-median transit time per line | ✅ | Run simulation | Times shown in sidebar |
| Simulation summary in sidebar | ✅ | Run simulation | Line-by-line results table |
| Pod animation replay | 🔧 | Run, step through frames | Pods move along guideways |
| Comparison vs car/bus/train | ⬜ | Set modal params | Side-by-side time comparison bar chart |
| Export simulation results | ⬜ | Click Export results | CSV or JSON of transit times |

---

## 8. Map Overlays

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| AADT traffic overlay | 🔧 | Toggle AADT | Traffic density shown on map |
| Accident overlay | 🔧 | Toggle Accidents | Accident hotspots shown |
| Mobility / demand overlay | 🔧 | Toggle Mobility | Demand heatmap shown |
| EZ (exclusive zone) overlay | ⬜ | Toggle EZ | Merge/diverge zones highlighted |

---

## 9. Data Formats

| Feature | Status | Test | Outcome |
|---------|--------|------|---------|
| Save / load `.jpd` | ✅ | Round-trip save and reload | Network identical after reload |
| Import SketchUp `map.json` | 🔧 | Load map.json from JPodsSM_RPi | Lines render, EZs recognized |
| Export `network_map.json` | ⬜ | Click Export | Valid file matching new schema |
| Import `network_map.json` | ⬜ | Load network_map.json | Network renders correctly |
| Load `.tld` template | ⬜ | Pick template, place on map | Sub-network placed as group |

---

## 10. What Else Is Needed

These are not in the Java version but are needed for the browser tool:

| Feature | Status | Notes |
|---------|--------|-------|
| Keyboard shortcut reference (palette hints) | ✅ | 5-section palette help |
| Multi-network composite view | ⬜ | Load two .jpd files, show together |
| WebClerk integration — save network to Alice | ⬜ | POST network to wcapi for storage/sharing |
| Allie AI recommendation panel | 🔧 | `/ai/recommend` endpoint exists |
| Network validation — orphan nodes, dead ends | ⬜ | Check before simulation |
| Auto-route between two clicked stations | ⬜ | Dijkstra path highlight on map |
| Scale bar / distance tool | ⬜ | Click two points, show distance |
| Print / screenshot export | ⬜ | Capture map + sidebar as image |

---

## Key Bindings Reference

| Gesture | Action |
|---------|--------|
| Click map (tool active) | Place station / circle / switch |
| Click CP | Select for connect |
| Click second CP | Connect the pair |
| Ctrl+click connected CP | Disconnect |
| Alt+drag CP or structure line | Move whole structure |
| Alt+drag free guideway | Add/move bend point on pair |
| Waypoint tool + click guideway | Add routing bend |
| Right-click guideway | Add aligned bend |
| Shift+waypoint handle | Remove waypoint |
| Shift+drag | Rubber-band region select |
| Delete / Backspace | Remove selected structure or region |
| Shift+node | Remove single node |
| Ctrl+guideway | Remove guideway pair |
| Esc | Cancel current operation |
