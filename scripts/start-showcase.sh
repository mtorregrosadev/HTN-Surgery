#!/usr/bin/env bash
# Start MongoDB in Docker plus a host API/controller so native SOFA can load.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.logs"
mkdir -p "$LOG_DIR"

if [[ -x "$ROOT/.venv-sofa/bin/python" ]]; then
  PYTHON="$ROOT/.venv-sofa/bin/python"
elif [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3.12}"
fi

if [[ -n "${SURGE_PREP_MONGODB_URI:-}" ]]; then
  export SURGE_PREP_MONGODB_URI
  echo "Checking externally managed MongoDB..."
  if ! "$PYTHON" - <<'PY'
import os
import sys

client = None
try:
    from pymongo import MongoClient

    client = MongoClient(
        os.environ["SURGE_PREP_MONGODB_URI"],
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
        socketTimeoutMS=3000,
    )
    client.admin.command("ping")
except Exception as error:
    print(f"MongoDB ping failed ({type(error).__name__}).", file=sys.stderr)
    raise SystemExit(1)
finally:
    if client is not None:
        client.close()
PY
  then
    echo "Configured MongoDB is unavailable; refusing to start the API." >&2
    exit 1
  fi
else
  export SURGE_PREP_MONGODB_URI="mongodb://127.0.0.1:27017"
  if ! command -v docker >/dev/null; then
    echo "Docker is required to run MongoDB when SURGE_PREP_MONGODB_URI is unset." >&2
    exit 1
  fi

  echo "Starting MongoDB..."
  docker compose -f "$ROOT/compose.yaml" stop api controller >/dev/null 2>&1 || true
  docker compose -f "$ROOT/compose.yaml" up -d mongodb

  echo "Waiting for MongoDB..."
  for _ in $(seq 1 40); do
    if docker compose -f "$ROOT/compose.yaml" exec -T mongodb mongosh --quiet --eval 'db.adminCommand("ping").ok' >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

if ! "$PYTHON" "$ROOT/scripts/check-native-sofa.py" --skip-smoke; then
  echo "Native SOFA is unavailable. Unity must show SOFA OFFLINE; do not present the memory adapter as physics." >&2
  exit 1
fi

SOFA_ROOT="${SURGE_PREP_SOFA_ROOT:-${SOFA_ROOT:-$HOME/SOFA/SOFA_v26.06.00_MacOS}}"
export SOFA_ROOT
export SURGE_PREP_SOFA_ROOT="$SOFA_ROOT"
export SOFAPYTHON3_ROOT="$SOFA_ROOT/plugins/SofaPython3"
export PYTHONPATH="$SOFA_ROOT/lib/python3/site-packages:$SOFA_ROOT/plugins/SofaPython3/lib/python3/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export DYLD_LIBRARY_PATH="$SOFA_ROOT/lib:$SOFA_ROOT/plugins/SofaPython3/lib:$SOFA_ROOT/plugins/SofaCarving/lib${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
export LD_LIBRARY_PATH="$DYLD_LIBRARY_PATH"

export SURGE_PREP_MONGODB_DATABASE="${SURGE_PREP_MONGODB_DATABASE:-surge_prep}"
export SURGE_PREP_SIMULATION_BACKEND=sofa
export SURGE_PREP_SOFA_SCENE="${SURGE_PREP_SOFA_SCENE:-$ROOT/simulation/sofa_scene.py}"
export SURGE_PREP_API_URL="${SURGE_PREP_API_URL:-http://127.0.0.1:8000}"

echo "Starting native API..."
if [[ -f "$LOG_DIR/api.pid" ]]; then
  kill "$(cat "$LOG_DIR/api.pid")" 2>/dev/null || true
fi
nohup "$PYTHON" -m uvicorn surge_prep.app:app \
  --app-dir "$ROOT/backend/src" --host 127.0.0.1 --port 8000 \
  >"$LOG_DIR/api.log" 2>&1 </dev/null &
echo $! >"$LOG_DIR/api.pid"

for _ in $(seq 1 40); do
  if curl --fail --silent http://127.0.0.1:8000/health | grep -q '"simulation":"sofa-native"'; then
    break
  fi
  if ! kill -0 "$(cat "$LOG_DIR/api.pid")" 2>/dev/null; then
    echo "Native API failed to start:" >&2
    cat "$LOG_DIR/api.log" >&2
    exit 1
  fi
  sleep 0.25
done
if ! curl --fail --silent http://127.0.0.1:8000/health | grep -q '"simulation":"sofa-native"'; then
  echo "Native API did not report sofa-native. See $LOG_DIR/api.log" >&2
  exit 1
fi

echo "Starting Scalpel controller..."
if [[ -f "$LOG_DIR/controller.pid" ]]; then
  kill "$(cat "$LOG_DIR/controller.pid")" 2>/dev/null || true
fi
nohup "$PYTHON" -m uvicorn scalpel_controller.app:app \
  --app-dir "$ROOT/controller/src" --host 127.0.0.1 --port 8100 \
  >"$LOG_DIR/controller.log" 2>&1 </dev/null &
echo $! >"$LOG_DIR/controller.pid"

for _ in $(seq 1 40); do
  if curl --fail --silent http://127.0.0.1:8100/health | grep -q '"simulation":"sofa-native"'; then
    break
  fi
  if ! kill -0 "$(cat "$LOG_DIR/controller.pid")" 2>/dev/null; then
    echo "Scalpel controller failed to start:" >&2
    cat "$LOG_DIR/controller.log" >&2
    exit 1
  fi
  sleep 0.25
done
if ! curl --fail --silent http://127.0.0.1:8100/health | grep -q '"simulation":"sofa-native"'; then
  echo "Controller did not expose native SOFA health. See $LOG_DIR/controller.log" >&2
  exit 1
fi

echo "Showcase stack is running."
echo "  API log:        $LOG_DIR/api.log"
echo "  Controller log: $LOG_DIR/controller.log"
echo "Keep Unity focused. Stop with scripts/stop-showcase.sh."
