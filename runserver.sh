#!/bin/bash
# MeshMobility server — kill any existing process then start fresh.
#
# Usage:
#   cd /Users/williamjames/Documents/08_JPods/03_Technology
#   bash mesh_mobility/runserver.sh [--no-browser] [network_file.jpd]
#
# ⚠️  IMPORTANT — the "kill && start" trap:
#   Running `kill <PID> && python -m mesh_mobility.gui` is UNSAFE.
#   If the PID is already gone, kill returns exit 1, the && short-circuits,
#   and the server never starts.  This script avoids that with 2>/dev/null
#   and an unconditional start after the kill attempt.
#
# To check for ghost processes without starting:
#   python mesh_mobility/tests/test_server.py
#   lsof -ti :5050

PORT=5050
PIDS=$(lsof -ti :$PORT 2>/dev/null)

if [ -n "$PIDS" ]; then
    echo "Killing old server on port $PORT (PID: $PIDS)"
    echo "$PIDS" | xargs kill -9 2>/dev/null
    sleep 0.5
else
    echo "No server running on port $PORT"
fi

# Always start — never conditional on the kill result
cd "$(dirname "$0")/.."

# Activate venv if present
VENV="$(dirname "$0")/.venv"
if [ -d "$VENV" ]; then
    source "$VENV/bin/activate"
fi

# Use gunicorn for production (handles concurrent users)
# Fall back to Flask dev server if gunicorn not installed
if command -v gunicorn &>/dev/null; then
    echo "Starting with gunicorn (1 worker, 8 threads — handles ~100 concurrent users)"
    gunicorn "mesh_mobility.gui.app:create_app()" \
        --bind 0.0.0.0:$PORT \
        --workers 1 \
        --threads 8 \
        --timeout 120 \
        --access-logfile - \
        "$@"
else
    echo "gunicorn not found — using Flask dev server (single user only)"
    echo "Install gunicorn:  pip install gunicorn"
    python3 -m mesh_mobility.gui "$@"
fi
