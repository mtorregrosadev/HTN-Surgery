#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

if [[ -x "$ROOT/.venv-sofa/bin/python" ]]; then
  PYTHON="$ROOT/.venv-sofa/bin/python"
elif [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export SURGE_PREP_MONGODB_URI=""
export SURGE_PREP_SIMULATION_BACKEND="${SURGE_PREP_SIMULATION_BACKEND:-memory}"
export SURGE_PREP_API_URL="http://127.0.0.1:8000"

# Kill previous if any
if [[ -f "$LOG_DIR/api.pid" ]]; then
  kill "$(cat "$LOG_DIR/api.pid")" 2>/dev/null || true
fi
if [[ -f "$LOG_DIR/controller.pid" ]]; then
  kill "$(cat "$LOG_DIR/controller.pid")" 2>/dev/null || true
fi

echo "Starting Backend API (:8000)..."
nohup "$PYTHON" -m uvicorn surge_prep.app:app \
  --app-dir "$ROOT/backend/src" --host 127.0.0.1 --port 8000 \
  >"$LOG_DIR/api.log" 2>&1 &
echo $! >"$LOG_DIR/api.pid"

echo "Starting Scalpel Controller (:8100)..."
nohup "$PYTHON" -m uvicorn scalpel_controller.app:app \
  --app-dir "$ROOT/controller/src" --host 127.0.0.1 --port 8100 \
  >"$LOG_DIR/controller.log" 2>&1 &
echo $! >"$LOG_DIR/controller.pid"

for _ in $(seq 1 30); do
  if curl -s http://127.0.0.1:8100/health | grep -q "status"; then
    echo "Services are online!"
    exit 0
  fi
  sleep 0.3
done

echo "Error: Services did not start in time." >&2
exit 1
