# MeshMobility — JPods Network Planner

Python simulation and browser-based planning tool for JPods networks.
Reads `.jpd` files and `map.json`, simulates fleet-median transit times, and
generates walk-ride-walk isochrone coverage maps.

## Quick Start

**Important:** Run from `00_working_code/`, not from inside `mesh_mobility/`.
Python needs `mesh_mobility/` to be a package below the current directory.

```bash
cd ~/Documents/08_JPods/03_Technology/00_working_code
source mesh_mobility/venv/bin/activate
python -m mesh_mobility.gui          # opens http://localhost:5050
python -m mesh_mobility.gui file.jpd # preload a network
```

**Dependencies:**
- `CrashHarvester` — symlink in `00_working_code/` points `CrashHarvester → crash_harvester`
- venv is inside `mesh_mobility/venv/` (Python 3.13.3)

**Python:** Always use the project venv. See `~/Allie/readmes/57-python-setup.md`.

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
