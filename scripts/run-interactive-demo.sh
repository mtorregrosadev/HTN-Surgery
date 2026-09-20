#!/usr/bin/env bash
# Surge Prep - Complete Physical-Digital Surgical Showcase Demo
# Connects: Physical Scalpel (AprilTags) -> 3D Desk Space -> Scalpel Controller -> API/SOFA -> Unity
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

CONTROLLER_URL="http://127.0.0.1:8100"
API_URL="http://127.0.0.1:8000"

echo "=========================================================="
echo "    Surge Prep — Physical-Digital Surgical Demo Launcher  "
echo "=========================================================="

# Select Python Interpreter
if [[ -x "$ROOT/.venv-sofa/bin/python" ]]; then
  PYTHON="$ROOT/.venv-sofa/bin/python"
elif [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

LOCAL_API_PID=""
LOCAL_CTRL_PID=""

cleanup() {
  if [[ -n "$LOCAL_API_PID" ]]; then
    kill "$LOCAL_API_PID" 2>/dev/null || true
  fi
  if [[ -n "$LOCAL_CTRL_PID" ]]; then
    kill "$LOCAL_CTRL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# 1. Check if Controller & API are running
if ! curl -s "$CONTROLLER_URL/health" | grep -q "status"; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "Starting full showcase stack with Docker MongoDB..."
    "$ROOT/scripts/start-showcase.sh"
  else
    echo "[Notice] Docker unavailable; launching local demo stack (In-Memory Store)..."
    export SURGE_PREP_MONGODB_URI=""
    export SURGE_PREP_SIMULATION_BACKEND="${SURGE_PREP_SIMULATION_BACKEND:-sofa}"
    export SURGE_PREP_API_URL="$API_URL"

    # Start API
    nohup "$PYTHON" -m uvicorn surge_prep.app:app \
      --app-dir "$ROOT/backend/src" --host 127.0.0.1 --port 8000 \
      >"$LOG_DIR/api.log" 2>&1 &
    LOCAL_API_PID=$!

    # Start Controller
    nohup "$PYTHON" -m uvicorn scalpel_controller.app:app \
      --app-dir "$ROOT/controller/src" --host 127.0.0.1 --port 8100 \
      >"$LOG_DIR/controller.log" 2>&1 &
    LOCAL_CTRL_PID=$!

    echo "Waiting for services to initialize..."
    for _ in $(seq 1 30); do
      if curl -s "$CONTROLLER_URL/health" | grep -q "status"; then
        break
      fi
      sleep 0.3
    done
  fi
fi

if ! curl -s "$CONTROLLER_URL/health" | grep -q "status"; then
  echo "Error: Scalpel Controller failed to start. Check $LOG_DIR/controller.log and $LOG_DIR/api.log" >&2
  exit 1
fi
echo "[1/3] Scalpel Controller & API are online and healthy."

# 2. Create an active surgical training session
echo "[2/3] Creating active surgical training session..."
CALIBRATION_PAYLOAD='{"deviceId":"apriltag-scalpel-tracker","transform":[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],"rmsErrorMm":0.05}'
CALIB_RESP=$(curl -s -X POST "$CONTROLLER_URL/v1/calibrations" -H "Content-Type: application/json" -d "$CALIBRATION_PAYLOAD")
CALIB_ID=$(echo "$CALIB_RESP" | grep -o '"calibrationId":"[^"]*' | cut -d'"' -f4 || echo "calib-demo-default")

SESSION_PAYLOAD="{\"exerciseId\":\"chest-tube-access-demo\",\"calibrationId\":\"$CALIB_ID\",\"toolId\":\"scalpel\",\"deviceId\":\"apriltag-scalpel-tracker\"}"
SESSION_RESP=$(curl -s -X POST "$CONTROLLER_URL/v1/sessions" -H "Content-Type: application/json" -d "$SESSION_PAYLOAD")
SESSION_ID=$(echo "$SESSION_RESP" | grep -o '"sessionId":"[^"]*' | cut -d'"' -f4 || echo "demo-session-live")

echo "Session Ready: $SESSION_ID (Calibration: $CALIB_ID)"

echo "----------------------------------------------------------"
echo "  HOW TO RUN THE DEMO:"
echo "  1. The tracking window will now open on your camera feed."
echo "  2. 3D Desk Space Registration:"
echo "     - Press 'p' to PIVOT CALIBRATE: hold scalpel tip at one"
echo "       fixed spot on the desk and gently rotate the handle."
echo "     - OR press 'c' if you have Desk Tag 0 lying on the table."
echo "  3. Open Unity, open 'ChestTubeShowcase', and press Play."
echo "  4. Physical scalpel movements directly control the 3D"
echo "     virtual scalpel and deform the virtual patient!"
echo "----------------------------------------------------------"

# 3. Launch the 3D Desk Space & Scalpel Tracker Streamer
"$PYTHON" -m tracker.apriltag_scalpel_streamer \
  --controller "$CONTROLLER_URL" \
  --session "$SESSION_ID" \
  "$@"
