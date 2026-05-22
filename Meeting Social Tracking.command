#!/bin/zsh
# Launcher for Meeting Social Tracking

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8501
STREAMLIT_BIN="/Users/leivbraun/Library/Python/3.9/bin/streamlit"

# Kill any existing process on port 8501
EXISTING_PID=$(lsof -ti tcp:$PORT 2>/dev/null)
if [ -n "$EXISTING_PID" ]; then
  kill "$EXISTING_PID" 2>/dev/null
  sleep 0.5
fi

# Start Streamlit in background
nohup "$STREAMLIT_BIN" run "$SCRIPT_DIR/app.py" \
  --server.port=$PORT \
  --server.headless=true \
  > /tmp/meeting-tracking.log 2>&1 &

# Wait until port responds (max ~15 seconds)
for i in $(seq 1 30); do
  if curl -s --max-time 0.5 "http://localhost:$PORT" > /dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

open "http://localhost:$PORT"
