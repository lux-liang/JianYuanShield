#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${JYS_PROJECT_ROOT:-$SCRIPT_PROJECT_ROOT}"
REPORT_ROOT="${JYS_REPORT_ROOT:-$ROOT/system/reports}"
PYTHON="${PYTHON:-python3}"
SNAPSHOT_PATH="$REPORT_ROOT/release_snapshot.json"

cd "$ROOT"

echo "[1/3] system check"
"$PYTHON" scripts/check_system.py

echo
echo "[2/3] backend smoke tests"
"$PYTHON" -m unittest discover -s tests

echo
echo "[3/3] release snapshot"
"$PYTHON" scripts/create_release_snapshot.py --output "$SNAPSHOT_PATH"

echo
echo "done: $SNAPSHOT_PATH"
