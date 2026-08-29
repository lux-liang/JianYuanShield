FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    JYS_PROJECT_ROOT=/app \
    JYS_MODEL_SOURCE_ROOT=/app/model-sources \
    JYS_DATA_ROOT=/app/data \
    JYS_WEIGHT_ROOT=/app/weights \
    JYS_REPORT_ROOT=/app/runtime/reports \
    JYS_ASSET_ROOT=/app/runtime/assets \
    JYS_INFER_DEVICE=cuda:0 \
    HOME=/tmp \
    TORCH_HOME=/tmp/torch

WORKDIR /app

RUN sed -i 's/^deb /deb [snapshot=yes] /' /etc/apt/sources.list \
    && apt-get update --snapshot 20260804T000000Z \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        --snapshot 20260804T000000Z \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.lock Dockerfile ./
COPY VERSION ./
COPY docker-compose.yml docker-compose.production.yml docker-compose.competition.yml ./
COPY offline_deploy.sh ./
COPY THIRD_PARTY_NOTICES.md ./
COPY supply-chain/ ./supply-chain/
COPY scripts/supply_chain.py scripts/build_release_image.py scripts/check_deployment.py scripts/offline_bundle.py ./scripts/
COPY system/gateway.py ./system/gateway.py
COPY deployment/ ./deployment/
RUN python scripts/supply_chain.py check \
    && python -m pip install --no-cache-dir --require-hashes \
        --only-binary=:all: \
        --extra-index-url https://download.pytorch.org/whl/cu128 \
        -r requirements.lock \
    && python scripts/supply_chain.py verify-environment \
    && python -m pip check

COPY configs/ ./configs/
COPY system/ ./system/

RUN mkdir -p /app/data/samples /app/weights /app/model-sources \
        /app/runtime/reports /app/runtime/assets /app/runtime/state \
        /app/runtime/audit-anchor \
    && useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin jys \
    && chown -R jys:jys /app/runtime /app/data

USER 10001

EXPOSE 8026 8027

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8026/api/health', timeout=5)"]

CMD ["uvicorn", "system.backend.app:app", "--host", "0.0.0.0", "--port", "8026", "--workers", "1"]
