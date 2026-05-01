#!/bin/bash
# Route-Time server — kill any existing process then start fresh.
#
# Usage:
#   cd /Users/williamjames/Documents/08_JPods/03_Technology
#   bash route_time/runserver.sh [--no-browser] [network_file.jpd]
#
# ⚠️  IMPORTANT — the "kill && start" trap:
#   Running `kill <PID> && python -m route_time.gui` is UNSAFE.
#   If the PID is already gone, kill returns exit 1, the && short-circuits,
#   and the server never starts.  This script avoids that with 2>/dev/null
#   and an unconditional start after the kill attempt.
#
# To check for ghost processes without starting:
#   python route_time/tests/test_server.py
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
cd "$(dirname "$0")/.." && python3 -m route_time.gui "$@"
