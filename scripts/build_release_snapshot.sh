#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
SNAPSHOT_PATH="$ROOT/system/reports/release_snapshot.json"

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
