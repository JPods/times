#!/usr/bin/env python3
"""
route_time.py  —  JPods Route-Time Simulator (Python)
======================================================
Converts the Java Route-Time simulation to Python.
Reads .jpd networks or SketchUp map.json files.
Outputs fleet-median transit times per line for use in itinerary planning.

Usage:
  python route_time.py <network_file> [options]

Arguments:
  network_file   Path to a .jpd file or a map.json file.

Options:
  --settings FILE   Path to settings.json  (default: settings.json alongside this script)
  --slots N         Number of demand slots to simulate  (default: 360 = 1 hour)
  --out DIR         Output directory for results  (default: same dir as network_file)
  --patch           Also write route_time_patch.json (line_id → route_time_ms)
  --summary         Print a human-readable summary to stdout

Examples:
  python route_time.py /Applications/RouteTime_JPods/OK_Tulsa_01.jpd --summary
  python route_time.py map.json --patch --out ./results
"""

import argparse
import json
import os
import sys

# Support running as:
#   python route_time/route_time.py  (from parent)
#   python route_time.py             (from inside route_time/)
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent   = os.path.dirname(_this_dir)

try:
    from route_time.engine import Simulator
    from route_time.io import load_jpd, load_podpresenter, load_sketchup_map
    from route_time.io import write_results, write_itinerary_patch
except ModuleNotFoundError:
    # Script is being run from inside the package dir — add parent
    sys.path.insert(0, _parent)
    from route_time.engine import Simulator
    from route_time.io import load_jpd, load_podpresenter, load_sketchup_map
    from route_time.io import write_results, write_itinerary_patch


_DEFAULT_SETTINGS = os.path.join(os.path.dirname(__file__), "settings.json")


def _load_settings(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jpd":
        return "jpd"
    # Try to detect by content
    with open(path) as f:
        try:
            data = json.load(f)
            if "lines" in data:
                return "podpresenter"
            if "edges" in data or "nodes" in data:
                return "sketchup"
        except json.JSONDecodeError:
            pass
    return "jpd"  # fallback — try XML


def main():
    parser = argparse.ArgumentParser(
        description="JPods Route-Time Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("network_file", help="Path to .jpd or map.json")
    parser.add_argument("--settings", default=_DEFAULT_SETTINGS,
                        help="Path to settings.json")
    parser.add_argument("--slots", type=int, default=360,
                        help="Demand slots to simulate (default: 360 = 1 hour)")
    parser.add_argument("--out", default=None,
                        help="Output directory (default: network file directory)")
    parser.add_argument("--patch", action="store_true",
                        help="Write route_time_patch.json alongside results")
    parser.add_argument("--summary", action="store_true",
                        help="Print human-readable summary to stdout")
    args = parser.parse_args()

    if not os.path.exists(args.network_file):
        print(f"Error: file not found: {args.network_file}", file=sys.stderr)
        sys.exit(1)

    # Load settings
    settings_path = args.settings
    if not os.path.exists(settings_path):
        print(f"Warning: settings not found at {settings_path}, using defaults")
        settings = {}
    else:
        settings = _load_settings(settings_path)

    # Load network
    fmt = _detect_format(args.network_file)
    if fmt == "jpd":
        network, _, _, _ = load_jpd(args.network_file)
    elif fmt == "podpresenter":
        network = load_podpresenter(args.network_file)
    else:
        network = load_sketchup_map(args.network_file)

    if not network.lines:
        print("Error: no lines loaded from network file.", file=sys.stderr)
        sys.exit(1)

    if not network.stations:
        print("Warning: no stations found — demand model will produce no passengers.")

    print(f"Loaded: {network}")
    print(f"Running {args.slots} slots ({args.slots * 10 / 3600:.2f} hours)...")

    # Run simulation
    sim = Simulator(network, settings)
    result = sim.run(total_slots=args.slots)

    # Output directory
    out_dir = args.out or os.path.dirname(os.path.abspath(args.network_file))

    # Write results
    results_path = write_results(result, out_dir)
    print(f"Results written: {results_path}")

    if args.patch:
        patch_path = write_itinerary_patch(result, out_dir)
        print(f"Patch written:   {patch_path}")

    # Summary
    if args.summary:
        _print_summary(result)


def _print_summary(result):
    sim = result.simulation if hasattr(result, "simulation") else {}
    d = result.to_dict()
    s = d["simulation"]
    print()
    print(f"{'=' * 56}")
    print(f"  Route-Time Summary — {d['network_id']}")
    print(f"{'=' * 56}")
    print(f"  Passengers generated : {s['passengers_generated']}")
    print(f"  Passengers served    : {s['passengers_served']}")
    served = s['passengers_served']
    generated = s['passengers_generated']
    if generated:
        pct = 100 * served / generated
        print(f"  Service rate         : {pct:.1f}%")
    print()
    print(f"  {'Line':<20} {'Length m':>10} {'Median ms':>10} {'P90 ms':>10} {'Samples':>8}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
    for ls in sorted(d["line_stats"], key=lambda x: x["line_id"]):
        median = ls["fleet_median_transit_ms"]
        p90    = ls["fleet_p90_transit_ms"]
        print(
            f"  {ls['line_id']:<20} "
            f"{ls['length_m']:>10.0f} "
            f"{_fmt(median):>10} "
            f"{_fmt(p90):>10} "
            f"{ls['sample_count']:>8}"
        )
    print()


def _fmt(v):
    if v is None:
        return "—"
    return f"{v:.0f}"


if __name__ == "__main__":
    main()
