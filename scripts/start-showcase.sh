#!/usr/bin/env bash
# Start MongoDB in Docker plus a host API/controller so native SOFA can load.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

if ! command -v docker >/dev/null; then
  echo "Docker is required to run MongoDB." >&2
  exit 1
fi

echo "Starting MongoDB..."
docker compose -f "$ROOT/compose.yaml" up -d mongodb

echo "Waiting for MongoDB..."
for _ in $(seq 1 40); do
  if docker compose -f "$ROOT/compose.yaml" exec -T mongodb mongosh --quiet --eval 'db.adminCommand("ping").ok' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3.12}"
fi

if ! "$PYTHON" "$ROOT/scripts/check-native-sofa.py"; then
  echo "Native SOFA is unavailable. Unity must show SOFA OFFLINE; do not present the memory adapter as physics." >&2
  exit 1
fi

eval "$("$PYTHON" "$ROOT/scripts/check-native-sofa.py" --export-env --skip-smoke | grep '^export ')"

export SURGE_PREP_MONGODB_URI="${SURGE_PREP_MONGODB_URI:-mongodb://127.0.0.1:27017}"
export SURGE_PREP_MONGODB_DATABASE="${SURGE_PREP_MONGODB_DATABASE:-surge_prep}"
export SURGE_PREP_SIMULATION_BACKEND=sofa
export SURGE_PREP_SOFA_SCENE="${SURGE_PREP_SOFA_SCENE:-$ROOT/simulation/sofa_scene.py}"
export SURGE_PREP_API_URL="${SURGE_PREP_API_URL:-http://127.0.0.1:8000}"

echo "Starting native API..."
(
  cd "$ROOT/backend"
  "$PYTHON" -m uvicorn surge_prep.app:app --host 127.0.0.1 --port 8000
) >"$LOG_DIR/api.log" 2>&1 &
echo $! >"$LOG_DIR/api.pid"

if [[ -x "$ROOT/controller/.venv/bin/python" ]]; then
  CONTROLLER_PYTHON="$ROOT/controller/.venv/bin/python"
else
  CONTROLLER_PYTHON="$PYTHON"
fi

echo "Starting Scalpel controller..."
(
  cd "$ROOT/controller"
  "$CONTROLLER_PYTHON" -m uvicorn scalpel_controller.app:app --host 127.0.0.1 --port 8100
) >"$LOG_DIR/controller.log" 2>&1 &
echo $! >"$LOG_DIR/controller.pid"

echo "Showcase stack is running."
echo "  API log:        $LOG_DIR/api.log"
echo "  Controller log: $LOG_DIR/controller.log"
echo "Keep Unity focused. Stop with scripts/stop-showcase.sh."
