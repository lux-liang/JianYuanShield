FROM pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies（所有版本由 requirements.txt 钉死，确保可复现）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
       PyWavelets kornia lpips easydict

# Copy project source (weights are mounted at runtime, not baked in)
COPY system/ ./system/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY docs/ ./docs/

# Stub weight directories (actual weights mounted via volume)
RUN mkdir -p weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models \
             weights/mea/WaveGuard/exp_highpass \
             weights/mea/HiDDeN/runs

# Model source code (required for inference)
COPY MEA/      ./MEA/
COPY LIDMark/  ./LIDMark/
COPY WaveGuard/ ./WaveGuard/
COPY KAD-Net/  ./KAD-Net/

EXPOSE 8026 8027

ENV PYTHONPATH=/app
ENV JYS_DATA_ROOT=/app/data
# JYS_MODEL_SOURCE_ROOT 指向外部权重/代码挂载点（docker-compose.yml 通过 volume 提供）
# 默认值 /app/model_source 可被 docker-compose.yml 中的环境变量覆盖
ENV JYS_MODEL_SOURCE_ROOT=/app/model_source

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8026/api/status || exit 1

CMD ["sh", "-c", "\
    uvicorn system.backend.app:app --host 0.0.0.0 --port 8026 & \
    python3 -m http.server 8027 --directory system/frontend \
"]
