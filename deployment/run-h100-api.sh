#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_ROOT=/root/jialiang_liang/projects/JianYuanShield
RUNTIME_ROOT=/root/jialiang_liang/runtime/JianYuanShield
PYTHON="$PROJECT_ROOT/.venv/bin/python"
EVIDENCE_KEY="$RUNTIME_ROOT/keys/evidence-ed25519.pem"
PROVENANCE_SECRET="$RUNTIME_ROOT/keys/provenance-secret"

test -x "$PYTHON"
test -r "$EVIDENCE_KEY"
test -r "$PROVENANCE_SECRET"

EVIDENCE_FINGERPRINT="$($PYTHON - "$EVIDENCE_KEY" <<'PY'
import hashlib
import sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization

key = serialization.load_pem_private_key(Path(sys.argv[1]).read_bytes(), password=None)
public_der = key.public_key().public_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
print(hashlib.sha256(public_der).hexdigest())
PY
)"

exec env \
  PYTHONUNBUFFERED=1 \
  CUDA_VISIBLE_DEVICES=6 \
  OMP_NUM_THREADS=8 \
  MKL_NUM_THREADS=8 \
  OPENBLAS_NUM_THREADS=8 \
  NUMEXPR_NUM_THREADS=8 \
  PYTHONPATH="$RUNTIME_ROOT/python-packages/kad:$PROJECT_ROOT" \
  JYS_PROJECT_ROOT="$PROJECT_ROOT" \
  JYS_WEIGHT_ROOT="$RUNTIME_ROOT/weights" \
  JYS_MODEL_SOURCE_ROOT="$RUNTIME_ROOT/model-sources" \
  JYS_DATA_ROOT="$RUNTIME_ROOT/data" \
  JYS_REPORT_ROOT="$RUNTIME_ROOT/reports" \
  JYS_ASSET_ROOT="$RUNTIME_ROOT/assets" \
  JYS_MODE=real_inference \
  JYS_ENABLE_DEMO=false \
  JYS_REQUIRE_API_KEY=false \
  JYS_INFER_DEVICE=cuda:0 \
  JYS_WARMUP_MODELS=false \
  JYS_MAX_CONCURRENT_INFERENCE=1 \
  JYS_MAX_QUEUED_INFERENCE=4 \
  JYS_INFERENCE_TIMEOUT_SECONDS=600 \
  JYS_RATE_LIMIT_REQUESTS=120 \
  JYS_RATE_LIMIT_WINDOW_SECONDS=60 \
  JYS_PROVENANCE_DB="$RUNTIME_ROOT/state/provenance.sqlite3" \
  JYS_AUDIT_ANCHOR="$RUNTIME_ROOT/state/provenance-audit-anchor.json" \
  JYS_PROVENANCE_SECRET_FILE="$PROVENANCE_SECRET" \
  JYS_EVIDENCE_PRIVATE_KEY="$EVIDENCE_KEY" \
  JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT="$EVIDENCE_FINGERPRINT" \
  "$PYTHON" -m uvicorn system.backend.app:app \
    --app-dir "$PROJECT_ROOT" \
    --host 127.0.0.1 \
    --port 8026 \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips 127.0.0.1
