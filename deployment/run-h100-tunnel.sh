#!/usr/bin/env bash
set -euo pipefail

RUNTIME_ROOT=/root/jialiang_liang/runtime/JianYuanShield
exec /usr/bin/ssh \
  -N -T \
  -i "$RUNTIME_ROOT/keys/public-edge-tunnel-ed25519" \
  -o BatchMode=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=20 \
  -o ServerAliveCountMax=3 \
  -o StrictHostKeyChecking=accept-new \
  -o UserKnownHostsFile="$RUNTIME_ROOT/keys/public-edge-known-hosts" \
  -R 127.0.0.1:18080:127.0.0.1:8026 \
  jian-tunnel@81.70.178.203
