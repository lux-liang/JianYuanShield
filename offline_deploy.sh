#!/usr/bin/env bash
# Production-only entrypoint for signed competition bundle creation/restoration.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "${SCRIPT_DIR}/scripts/offline_bundle.py" ]]; then
  HELPER="${SCRIPT_DIR}/scripts/offline_bundle.py"
elif [[ -f "${SCRIPT_DIR}/offline_bundle.py" ]]; then
  HELPER="${SCRIPT_DIR}/offline_bundle.py"
else
  echo "offline deployment failed: scripts/offline_bundle.py is missing" >&2
  exit 2
fi

if [[ $# -eq 0 ]]; then
  echo "usage: $0 {create|preflight|restore|status|stop} [options]" >&2
  exit 2
fi

case "$1" in
  create|preflight|restore|status|stop)
    exec python3 "${HELPER}" "$@"
    ;;
  *)
    echo "offline deployment failed: only signed production subcommands are supported" >&2
    exit 2
    ;;
esac
