#!/bin/bash
# 鉴源盾离线部署打包脚本
# 在有网络的服务器上运行，生成可在无网络环境部署的 tar 包
set -euo pipefail

IMAGE_NAME="jianyuanshield"
IMAGE_TAG="latest"
OUTPUT_TAR="jianyuanshield_offline_$(date +%Y%m%d).tar"
DEPLOY_SCRIPT="deploy_offline.sh"

echo "[JYS] Building Docker image..."
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .

echo "[JYS] Saving image to ${OUTPUT_TAR}..."
docker save "${IMAGE_NAME}:${IMAGE_TAG}" -o "${OUTPUT_TAR}"

echo "[JYS] Creating deploy script..."
cat > "${DEPLOY_SCRIPT}" << 'DEPLOY'
#!/bin/bash
# 在答辩现场机器上运行此脚本
set -euo pipefail

IMAGE_TAR=$(ls jianyuanshield_offline_*.tar | head -1)
if [ -z "$IMAGE_TAR" ]; then
    echo "Error: no jianyuanshield_offline_*.tar found"
    exit 1
fi

echo "Loading image from $IMAGE_TAR ..."
docker load -i "$IMAGE_TAR"

echo "Starting services..."
docker compose up -d

echo ""
echo "=== 鉴源盾已启动 ==="
echo "Frontend: http://localhost:8027"
echo "Backend:  http://localhost:8026/api/status"
echo ""
echo "Health check:"
sleep 5
curl -sf http://localhost:8026/api/status && echo " OK" || echo " WARN: backend not ready yet, wait 30s"
DEPLOY

chmod +x "${DEPLOY_SCRIPT}"

echo ""
echo "=== 打包完成 ==="
echo "  镜像包: ${OUTPUT_TAR} ($(du -sh ${OUTPUT_TAR} | cut -f1))"
echo "  部署脚本: ${DEPLOY_SCRIPT}"
echo ""
echo "答辩时，将 ${OUTPUT_TAR}, ${DEPLOY_SCRIPT}, docker-compose.yml 拷贝到现场机器，运行:"
echo "  bash ${DEPLOY_SCRIPT}"
