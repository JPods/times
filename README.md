# MeshMobility — JPods Network Planner

Python simulation and browser-based planning tool for JPods networks.
Reads `.jpd` files and `map.json`, simulates fleet-median transit times, and
generates walk-ride-walk isochrone coverage maps.

## Quick Start

```bash
cd /Users/williamjames/Documents/08_JPods/03_Technology/00_working_code
python3 -m mesh_mobility.gui          # opens http://localhost:5050
python3 -m mesh_mobility.gui file.jpd # preload a network
bash mesh_mobility/runserver.sh       # kill old server + restart
```

## Documentation

All detailed documentation lives in `readmes/`:

| File | Contents |
|------|----------|
| [setup.md](readmes/setup.md) | Installation, running, kill/restart, architecture, color standard, CPs, structures, simulation |
| [keyboard-shortcuts.md](readmes/keyboard-shortcuts.md) | All keyboard shortcuts — placement (1–6), CPs, move, waypoints, selection, delete |
| [basic.md](readmes/basic.md) | Core concepts — network model, lines, nodes, exclusive zones, agents |
| [settings-and-metrics.md](readmes/settings-and-metrics.md) | Simulation settings reference — physics, fleet, timing, metrics |
| [fishbone-station.md](readmes/fishbone-station.md) | Station internal topology — guideway layout, siding, platform |
| [todo.md](readmes/todo.md) | Feature backlog — template save, undo/redo, siding tool |
