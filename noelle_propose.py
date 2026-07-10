#!/usr/bin/env python3
"""
Noelle Network Proposal — data-driven station/circle placement for Greenville.

Usage:
    python3 noelle_propose.py propose          # Place structures based on AADT data
    python3 noelle_propose.py snapshot "note"   # Record current state with a note
    python3 noelle_propose.py diff              # Show changes since last snapshot
    python3 noelle_propose.py history           # Show all snapshots

Workflow:
    1. Noelle proposes: places stations and circles at key intersections (NOT connected)
    2. Designer reviews: moves/adds/removes structures based on local knowledge
    3. Designer connects: Auto-Connect or manual CP clicks
    4. Snapshot: record the state with designer's explanation
    5. Repeat: break, rearrange, reconnect, snapshot
    6. Noelle documents: each delta teaches what humans value
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RT_URL = "http://localhost:5050"
HISTORY_DIR = Path.home() / "Documents" / "08_JPods" / "03_Technology" / "00_working_code" / "mesh_mobility" / "noelle_history"


def _api(method, path, body=None):
    """Call MeshMobility API."""
    url = f"{RT_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _geocode(query):
    """Geocode a location using Nominatim (same as MeshMobility city search)."""
    import urllib.parse
    q = urllib.parse.quote(query + ", Greenville, SC")
    url = f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1"
    req = urllib.request.Request(url, headers={"User-Agent": "JPods-MeshMobility/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        results = json.loads(r.read())
    if results:
        return float(results[0]["lat"]), float(results[0]["lon"])
    return None, None


# ── Greenville corridor data from SCDOT 2024 ────────────────────────────────
# Key intersections along corridors with 10,000+ AADT
# Format: (name, lat, lon, type, heading, aadt)
# Geocoded from SCDOT station descriptions

PROPOSED_NODES = [
    # ── US 276 corridor (Laurens Rd / Poinsett Hwy) — highest AADT ──
    ("US276 @ Main St",           34.8510, -82.3990, "circle", 0, 47600),
    ("US276 @ E Butler Rd",       34.8430, -82.3680, "station", 45, 35500),
    ("US276 @ Woodruff Rd",       34.8230, -82.3270, "circle", 0, 43800),
    ("US276 @ Standing Springs",  34.8050, -82.3100, "station", 45, 31500),
    ("US276 @ Rutherford Rd",     34.8550, -82.4050, "circle", 0, 38700),
    ("US276 @ Old Buncombe Rd",   34.8620, -82.4150, "station", 0, 23500),

    # ── US 29 corridor (Wade Hampton / Church St / Fairview) ──
    ("US29 @ W Main St",          34.8520, -82.4020, "circle", 0, 42400),
    ("US29 @ Pleasantburg Dr",    34.8640, -82.3780, "circle", 0, 34700),
    ("US29 @ Wade Hampton Blvd",  34.8700, -82.3680, "station", 45, 27800),
    ("US29 @ Fairview Rd",        34.8780, -82.3550, "circle", 0, 36300),
    ("US29 @ Church St",          34.8560, -82.3950, "station", 0, 23600),

    # ── US 25 corridor (White Horse Rd / Augusta Rd) ──
    ("US25 @ Anderson Rd",        34.8380, -82.4240, "station", 135, 41000),
    ("US25 @ N Washington Ave",   34.8470, -82.4130, "circle", 0, 29300),
    ("US25 @ Augusta Rd / I-85",  34.8200, -82.4350, "circle", 0, 38400),
    ("US25 @ White Horse Rd",     34.8100, -82.4500, "station", 135, 25700),
    ("US25 @ Old White Horse Rd", 34.8300, -82.4300, "station", 135, 18500),

    # ── US 123 corridor (N Academy / Buncombe) ──
    ("US123 @ Buncombe St",       34.8560, -82.3890, "circle", 0, 34400),
    ("US123 @ N Academy St",      34.8530, -82.3930, "station", 90, 25800),
    ("US123 @ E North St",        34.8570, -82.3850, "station", 90, 25800),

    # ── SC 14 / Woodruff Rd commercial corridor ──
    ("SC14 @ Woodruff Rd",        34.8250, -82.3200, "circle", 0, 31500),
    ("SC14 @ NE Main St",         34.8350, -82.3100, "station", 45, 19600),
    ("SC14 @ S Buncombe Rd",      34.8150, -82.3400, "station", 0, 27100),
    ("SC14 @ Fairview Rd",        34.8450, -82.3000, "station", 45, 10900),

    # ── Downtown Greenville core ──
    ("Downtown Main St",          34.8516, -82.3990, "station", 0, 20100),
    ("Downtown S Main / Augusta", 34.8460, -82.4010, "circle", 0, 20100),
    ("Cleveland St / Augusta",    34.8490, -82.4040, "station", 90, 28200),

    # ── SC 146 / Gresham Rd (Mauldin connector) ──
    ("SC146 @ Laurens Rd",        34.8300, -82.3500, "station", 90, 17000),
    ("SC146 @ Gresham Rd",        34.8200, -82.3400, "station", 90, 17400),

    # ── SC 183 / W Parker / College ──
    ("SC183 @ College St",        34.8500, -82.3950, "station", 0, 23500),
    ("SC183 @ White Horse Rd",    34.8350, -82.4400, "circle", 0, 15700),
    ("SC183 @ W Parker Rd",       34.8420, -82.4200, "station", 90, 15000),

    # ── I-385 corridor stations ──
    ("I385 @ Roper Mountain",     34.8150, -82.3550, "station", 90, 25400),
    ("I385 @ Haywood Rd",         34.8300, -82.3650, "station", 90, 30800),
]


def propose():
    """Place proposed structures on the MeshMobility map (not connected)."""
    # Start fresh
    _api("POST", "/api/network/new", {"network_id": "noelle_greenville_draft"})
    print("Created new network: noelle_greenville_draft")
    time.sleep(0.3)

    placed = 0
    for name, lat, lon, stype, heading, aadt in PROPOSED_NODES:
        try:
            if stype == "station":
                r = _api("POST", "/api/network/station",
                         {"lat": lat, "lon": lon, "heading_deg": heading})
                sid = r.get("station_id", "?")
            else:
                arms = [heading, heading + 90, heading + 180, heading + 270]
                r = _api("POST", "/api/network/circle",
                         {"lat": lat, "lon": lon, "arm_headings": arms})
                sid = r.get("circle_id", "?")
            placed += 1
            print(f"  {sid}: {name} ({stype}, {heading}°) AADT={aadt:,}")
            time.sleep(0.05)  # don't hammer the server
        except Exception as e:
            print(f"  FAILED: {name} — {e}")

    print(f"\nPlaced {placed} structures. NOT connected.")
    print("Designer: review positions, move to local knowledge, then Auto-Connect.")
    print(f"Snapshot with: python3 noelle_propose.py snapshot 'initial Noelle proposal'")


def snapshot(note=""):
    """Record current network state with a note."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

    # Get network descriptor
    try:
        desc = _api("GET", "/api/network/describe")
    except Exception as e:
        desc = {"error": str(e)}

    # Download .jpd
    jpd_path = HISTORY_DIR / f"{ts}.jpd"
    try:
        url = f"{RT_URL}/api/network/download"
        urllib.request.urlretrieve(url, str(jpd_path))
    except Exception as e:
        print(f"Warning: could not save .jpd: {e}")
        jpd_path = None

    # Save snapshot metadata
    snap = {
        "timestamp": ts,
        "note": note,
        "network_id": desc.get("network_id", "?"),
        "topology": desc.get("topology", {}),
        "spatial": desc.get("spatial", {}),
        "jpd_file": str(jpd_path) if jpd_path else None,
    }
    meta_path = HISTORY_DIR / f"{ts}.json"
    meta_path.write_text(json.dumps(snap, indent=2))

    topo = desc.get("topology", {})
    print(f"Snapshot {ts}")
    print(f"  Note: {note}")
    print(f"  Stations: {topo.get('stations', '?')}, Circles: {topo.get('circles', '?')}")
    print(f"  Connected CPs: {topo.get('connected_cps', '?')}, Open: {topo.get('open_cps', '?')}")
    print(f"  Components: {topo.get('components', '?')}, Orphans: {len(topo.get('orphans', []))}")
    print(f"  Saved: {meta_path}")
    if jpd_path:
        print(f"  JPD:   {jpd_path}")


def diff():
    """Show changes since last snapshot."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snaps = sorted(HISTORY_DIR.glob("*.json"))
    if not snaps:
        print("No snapshots yet. Run: python3 noelle_propose.py snapshot 'note'")
        return

    last = json.loads(snaps[-1].read_text())
    try:
        current_desc = _api("GET", "/api/network/describe")
    except Exception as e:
        print(f"Cannot reach MeshMobility: {e}")
        return

    prev = last.get("topology", {})
    curr = current_desc.get("topology", {})

    print(f"Changes since snapshot {last['timestamp']}:")
    print(f"  Note was: {last.get('note', '(none)')}")
    print()

    for key in ["stations", "circles", "connected_cps", "open_cps", "components"]:
        p = prev.get(key, 0)
        c = curr.get(key, 0)
        delta = c - p
        sign = "+" if delta > 0 else ""
        if delta != 0:
            print(f"  {key}: {p} → {c} ({sign}{delta})")

    prev_orphans = set(prev.get("orphans", []))
    curr_orphans = set(curr.get("orphans", []))
    new_orphans = curr_orphans - prev_orphans
    fixed_orphans = prev_orphans - curr_orphans
    if new_orphans:
        print(f"  New orphans: {', '.join(sorted(new_orphans))}")
    if fixed_orphans:
        print(f"  Fixed orphans: {', '.join(sorted(fixed_orphans))}")

    prev_deg = prev.get("degree_distribution", {})
    curr_deg = curr.get("degree_distribution", {})
    if prev_deg != curr_deg:
        print(f"  Degree distribution: {prev_deg} → {curr_deg}")


def history():
    """Show all snapshots."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    snaps = sorted(HISTORY_DIR.glob("*.json"))
    if not snaps:
        print("No snapshots yet.")
        return

    for path in snaps:
        snap = json.loads(path.read_text())
        topo = snap.get("topology", {})
        print(f"{snap['timestamp']}  "
              f"S={topo.get('stations','?')} C={topo.get('circles','?')} "
              f"conn={topo.get('connected_cps','?')} open={topo.get('open_cps','?')} "
              f"comp={topo.get('components','?')}  "
              f"— {snap.get('note', '(no note)')}")


def main():
    parser = argparse.ArgumentParser(description="Noelle Network Proposal")
    parser.add_argument("command", choices=["propose", "snapshot", "diff", "history"])
    parser.add_argument("note", nargs="?", default="")
    args = parser.parse_args()

    if args.command == "propose":
        propose()
    elif args.command == "snapshot":
        snapshot(args.note)
    elif args.command == "diff":
        diff()
    elif args.command == "history":
        history()


if __name__ == "__main__":
    main()
