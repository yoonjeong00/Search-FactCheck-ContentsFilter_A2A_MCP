#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
PID_FILE="$RUNTIME_DIR/honcho.pid"
LOG_FILE="$RUNTIME_DIR/dev.log"

mkdir -p "$RUNTIME_DIR"

is_running() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

require_honcho() {
  if ! python -m honcho --help >/dev/null 2>&1; then
    echo "honcho is not installed in current Python environment."
    echo "Install it with: pip install honcho"
    exit 1
  fi
}

up() {
  require_honcho

  if is_running; then
    echo "Already running (pid $(cat "$PID_FILE"))."
    exit 0
  fi

  # 새 기동 로그부터 보기 쉽게 초기화
  : > "$LOG_FILE"

  echo "Starting services with honcho (agents only)..."
  cd "$ROOT_DIR"
  python -m honcho start -f Procfile.agents >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  sleep 1
  if is_running; then
    local pid
    pid="$(cat "$PID_FILE")"
    echo "Started. pid=$pid"
    echo "Log: $LOG_FILE"
    echo "Honcho is running in this terminal. Ctrl+C to stop."
    # 스크립트가 끝나 stdin이 끊기는 것을 막기 위해 honcho가 종료될 때까지 대기
    wait "$pid"
  else
    echo "Failed to start. Check log: $LOG_FILE"
    exit 1
  fi
}

down() {
  if ! is_running; then
    echo "Not running."
    rm -f "$PID_FILE"
    exit 0
  fi

  local pid
  pid="$(cat "$PID_FILE")"
  echo "Stopping honcho (pid $pid)..."
  kill "$pid" >/dev/null 2>&1 || true
  sleep 1
  rm -f "$PID_FILE"
  echo "Stopped."
}

status() {
  if is_running; then
    echo "Runner: running (pid $(cat "$PID_FILE"))"
  else
    echo "Runner: stopped"
  fi

  for port in 50051 50052 50053 50054 50055; do
    if lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
      echo "Port $port: LISTEN"
    else
      echo "Port $port: NOT LISTENING"
    fi
  done
}

logs() {
  if [[ ! -f "$LOG_FILE" ]]; then
    echo "No log file found at $LOG_FILE"
    exit 1
  fi
  tail -f "$LOG_FILE"
}

case "${1:-}" in
  up) up ;;
  up-all)
    echo "Starting ALL services with honcho (including MCP). Not recommended with Cursor MCP/stdio."
    echo "If you still want this mode, manually run MCP separately in Cursor and use `./scripts/devctl.sh up` for agents."
    exit 1
    ;;
  down) down ;;
  status) status ;;
  logs) logs ;;
  *)
    echo "Usage: $0 {up|down|status|logs}"
    exit 1
    ;;
esac
