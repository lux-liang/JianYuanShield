#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Running tests with PYTHONPATH=$ROOT"
PYTHONPATH="$ROOT" python3 -m unittest discover -s tests -v "$@"
