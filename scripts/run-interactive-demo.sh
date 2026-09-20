#!/usr/bin/env bash
# Surge Prep - Complete Physical-Digital Surgical Showcase Demo
# Connects: Physical Scalpel (AprilTags) -> 3D Desk Space -> Scalpel Controller -> API/SOFA -> Unity
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTROLLER_URL="http://127.0.0.1:8100"
API_URL="http://127.0.0.1:8000"

echo "=========================================================="
echo "    Surge Prep — Physical-Digital Surgical Demo Launcher  "
echo "=========================================================="

# 1. Check if Scalpel Controller & API are running
if ! curl -s "$CONTROLLER_URL/health" | grep -q "status"; then
  echo "Backend stack not running. Starting showcase stack..."
  "$ROOT/scripts/start-showcase.sh"
else
  echo "[1/3] Scalpel Controller & API are online and healthy."
fi

# 2. Create or verify a live Demo Session with the Controller
echo "[2/3] Creating active surgical training session..."
CALIBRATION_PAYLOAD='{"deviceId":"apriltag-scalpel-tracker","transform":[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],"rmsErrorMm":0.05}'
CALIB_RESP=$(curl -s -X POST "$CONTROLLER_URL/v1/calibrations" -H "Content-Type: application/json" -d "$CALIBRATION_PAYLOAD")
CALIB_ID=$(echo "$CALIB_RESP" | grep -o '"calibrationId":"[^"]*' | cut -d'"' -f4 || echo "calib-demo-default")

SESSION_PAYLOAD="{\"exerciseId\":\"chest-tube-access-demo\",\"calibrationId\":\"$CALIB_ID\",\"toolId\":\"scalpel\",\"deviceId\":\"apriltag-scalpel-tracker\"}"
SESSION_RESP=$(curl -s -X POST "$CONTROLLER_URL/v1/sessions" -H "Content-Type: application/json" -d "$SESSION_PAYLOAD")
SESSION_ID=$(echo "$SESSION_RESP" | grep -o '"sessionId":"[^"]*' | cut -d'"' -f4 || echo "demo-session-live")

echo "Session Initialized: $SESSION_ID (Calibration: $CALIB_ID)"

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
if [[ -x "$ROOT/.venv-sofa/bin/python" ]]; then
  PYTHON="$ROOT/.venv-sofa/bin/python"
elif [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

exec "$PYTHON" -m tracker.apriltag_scalpel_streamer \
  --controller "$CONTROLLER_URL" \
  --session "$SESSION_ID" \
  "$@"
