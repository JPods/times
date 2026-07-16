"""
mesh_mobility.gui.app
=====================
Flask application entry point for the MeshMobility browser GUI.

Usage:
  python -m mesh_mobility.gui [--port 5050] [network_file]

Opens http://localhost:5050 in the default browser.
"""

import logging
import os
import sys
import argparse
import threading
import webbrowser

from flask import Flask, send_from_directory, make_response

_gui_dir = os.path.dirname(os.path.abspath(__file__))
_rt_dir  = os.path.dirname(_gui_dir)
_parent  = os.path.dirname(_rt_dir)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from mesh_mobility.gui.api import api
from mesh_mobility.gui.state import _state, restore_structures
from mesh_mobility.io import load_jpd, load_podpresenter, load_sketchup_map
from mesh_mobility.engine.network import Network
import json

app = Flask(__name__, static_folder=os.path.join(_gui_dir, "static"))
app.register_blueprint(api)


_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
}


def _serve_static(filename):
    """Serve static files by reading content directly.
    Werkzeug 3.1 send_from_directory has a Content-Length mismatch bug
    when the browser sends Accept-Encoding — the server declares the raw
    file size but closes the connection before delivering the body.
    Reading the file ourselves avoids the broken code path."""
    import mimetypes
    path = os.path.join(app.static_folder, filename)
    if not os.path.isfile(path):
        return "Not found", 404
    # Prevent path traversal
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(app.static_folder)):
        return "Forbidden", 403
    ext = os.path.splitext(filename)[1].lower()
    mime = _MIME.get(ext, mimetypes.guess_type(filename)[0] or "application/octet-stream")
    if mime.startswith("text/") or mime.startswith("application/"):
        data = open(path, "r", encoding="utf-8").read()
    else:
        data = open(path, "rb").read()
    resp = make_response(data)
    resp.headers["Content-Type"] = mime
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/")
def landing():
    return _serve_static("landing.html")


@app.route("/app")
def index():
    return _serve_static("index.html")


@app.route("/library")
def library():
    return _serve_static("library.html")


@app.route("/examples/<path:filename>")
def serve_example(filename):
    """Serve example .jpd and .pdf files from mesh_mobility_maps."""
    maps_dir = os.path.join(os.path.dirname(_rt_dir), "mesh_mobility_maps")
    path = os.path.join(maps_dir, filename)
    if not os.path.isfile(path):
        return "Not found", 404
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(maps_dir)):
        return "Forbidden", 403
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".jpd":
        data = open(path, "r", encoding="utf-8").read()
        resp = make_response(data)
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    elif ext == ".pdf":
        data = open(path, "rb").read()
        resp = make_response(data)
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    else:
        return "Not found", 404
    return resp


@app.route("/examples")
def list_examples():
    """List available example files."""
    maps_dir = os.path.join(os.path.dirname(_rt_dir), "mesh_mobility_maps")
    if not os.path.isdir(maps_dir):
        return "[]", 200, {"Content-Type": "application/json"}
    files = sorted([f for f in os.listdir(maps_dir)
                    if f.endswith(".jpd") or f.endswith(".pdf")])
    return __import__("json").dumps(files), 200, {"Content-Type": "application/json"}


@app.route("/citytool")
@app.route("/citytool.html")
def citytool():
    """Serve CityTool from its original location."""
    ct_path = "/Users/williamjames/Documents/08_JPods/000_websiteReWork/citytool.html"
    if not os.path.isfile(ct_path):
        return "CityTool not found", 404
    data = open(ct_path, "r", encoding="utf-8").read()
    resp = make_response(data)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/<path:filename>")
def static_files(filename):
    return _serve_static(filename)


def _preload(path: str):
    """Load a network file at startup."""
    import json as _json
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jpd":
        net, structs_data, cps_data, file_settings = load_jpd(path)
    else:
        with open(path) as f:
            raw = _json.load(f)
        if "lines" in raw:
            net = load_podpresenter(path)
        else:
            net = load_sketchup_map(path)
        structs_data, cps_data, file_settings = [], [], {}
    _state["network"] = net
    _state["network_path"] = path
    if structs_data or cps_data:
        restore_structures(structs_data, cps_data, net)
    if file_settings:
        _state["settings"].update(file_settings)


def main():
    parser = argparse.ArgumentParser(description="MeshMobility Browser GUI")
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

    # Log to file so external tools (Claude Code) can tail output
    log_path = os.path.join(_rt_dir, "mesh_mobility.log")
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
    ))
    logging.getLogger().addHandler(file_handler)
    logging.getLogger().setLevel(logging.DEBUG)
    # Also capture Werkzeug (Flask request logs)
    logging.getLogger("werkzeug").addHandler(file_handler)

    print(f"MeshMobility → {url}")
    print(f"Log file        → {log_path}")
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)


def create_app():
    """Factory function for gunicorn: gunicorn 'mesh_mobility.gui.app:create_app()'"""
    return app


if __name__ == "__main__":
    main()
