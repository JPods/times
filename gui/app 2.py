"""
route_time.gui.app
==================
Flask application entry point for the Route-Time browser GUI.

Usage:
  python -m route_time.gui [--port 5050] [network_file]

Opens http://localhost:5050 in the default browser.
"""

import os
import sys
import argparse
import threading
import webbrowser

from flask import Flask, send_from_directory

_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from route_time.gui.api import api, _state, load_jpd, load_podpresenter, load_sketchup_map
from route_time.engine.network import Network
import json

app = Flask(__name__, static_folder=os.path.join(_gui_dir, "static"))
app.register_blueprint(api)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


def _preload(path: str):
    """Load a network file at startup."""
    import json as _json
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jpd":
        net = load_jpd(path)
    else:
        with open(path) as f:
            raw = _json.load(f)
        if "lines" in raw:
            net = load_podpresenter(path)
        else:
            net = load_sketchup_map(path)
    _state["network"] = net
    _state["network_path"] = path


def main():
    parser = argparse.ArgumentParser(description="Route-Time Browser GUI")
    parser.add_argument("network_file", nargs="?", help="Optional .jpd or map.json to open")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.network_file and os.path.exists(args.network_file):
        _preload(args.network_file)
        print(f"Loaded: {args.network_file}")
    else:
        # Start with an empty ready-to-edit network
        _state["network"] = Network(network_id="untitled")

    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"Route-Time GUI → {url}")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
