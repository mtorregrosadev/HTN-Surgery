#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.logs"

if [[ -f "$LOG_DIR/api.pid" ]]; then
  kill "$(cat "$LOG_DIR/api.pid")" 2>/dev/null || true
  rm -f "$LOG_DIR/api.pid"
fi
if [[ -f "$LOG_DIR/controller.pid" ]]; then
  kill "$(cat "$LOG_DIR/controller.pid")" 2>/dev/null || true
  rm -f "$LOG_DIR/controller.pid"
fi

echo "Host API and controller stopped. MongoDB is still running in Docker."
