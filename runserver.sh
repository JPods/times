#!/bin/bash
# Restart the Route-Time GUI server cleanly.
# Run from anywhere: bash route_time/restart.sh

PORT=5050
KILLED=$(lsof -ti :$PORT | xargs kill -9 2>/dev/null && echo "yes" || echo "no")
[ "$KILLED" = "yes" ] && echo "Killed old server on port $PORT" || echo "No server running on port $PORT"
sleep 0.5
cd "$(dirname "$0")/.." && python3 -m route_time.gui
