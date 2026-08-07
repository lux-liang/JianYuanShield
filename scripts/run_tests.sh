#!/usr/bin/env bash
set -euo pipefail
SCRIPT_PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${JYS_PROJECT_ROOT:-$SCRIPT_PROJECT_ROOT}"
PYTHON="${JYS_TEST_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi
echo "Running tests with $PYTHON and PYTHONPATH=$ROOT"
PYTHONPATH="$ROOT" "$PYTHON" -m unittest discover -s tests -v "$@"
