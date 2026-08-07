#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${JYS_PROJECT_ROOT:-$SCRIPT_PROJECT_ROOT}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

PYTHON="${PYTHON:-python3}"
BACKEND_HOST="${JYS_BACKEND_HOST:-${BACKEND_HOST:-0.0.0.0}}"
BACKEND_PORT="${JYS_BACKEND_PORT:-${BACKEND_PORT:-8026}}"
FRONTEND_HOST="${JYS_FRONTEND_HOST:-${FRONTEND_HOST:-0.0.0.0}}"
FRONTEND_PORT="${JYS_FRONTEND_PORT:-${FRONTEND_PORT:-8027}}"

BACKEND_PID=""
FRONTEND_PID=""

port_open() {
  "$PYTHON" -c 'import socket, sys
host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(0.35)
try:
    raise SystemExit(0 if sock.connect_ex((host, port)) == 0 else 1)
finally:
    sock.close()
' "$1" "$2"
}

cleanup() {
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$ROOT"

echo "JianYuanShield dev server"
echo "root: $ROOT"

if ! "$PYTHON" -c 'import fastapi, uvicorn, cv2, numpy, PIL, skimage' >/dev/null 2>&1; then
  echo "missing runtime dependencies; run: $PYTHON -m pip install -r requirements.txt" >&2
  exit 1
fi

if port_open 127.0.0.1 "$BACKEND_PORT"; then
  echo "backend port $BACKEND_PORT is already in use; reusing existing backend"
else
  echo "starting backend: http://127.0.0.1:$BACKEND_PORT"
  "$PYTHON" -m uvicorn system.backend.app:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
  BACKEND_PID="$!"
fi

if port_open 127.0.0.1 "$FRONTEND_PORT"; then
  echo "frontend port $FRONTEND_PORT is already in use; reusing existing frontend"
else
  echo "starting frontend: http://127.0.0.1:$FRONTEND_PORT"
  (cd "$ROOT/system/frontend" && "$PYTHON" -m http.server "$FRONTEND_PORT" --bind "$FRONTEND_HOST") &
  FRONTEND_PID="$!"
fi

echo
echo "open: http://127.0.0.1:$FRONTEND_PORT"
echo "api:  http://127.0.0.1:$BACKEND_PORT"
echo "press Ctrl-C to stop services started by this script"

wait
