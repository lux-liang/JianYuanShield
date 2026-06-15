#!/bin/bash
# 鉴源盾离线部署打包脚本
# 在有网络的服务器上运行，生成可在无网络环境部署的 tar 包
#
# 重要：本脚本【不打包模型权重】——权重文件通常数 GB，需另行准备。
# 请在运行此脚本后，按照"权重目录准备说明"将权重文件复制到答辩机器。
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

# ============================================================
# 权重目录准备说明（⚠️ 必读，启动前完成）
# ============================================================
# 本镜像不含模型权重。启动前需另行提供权重目录，并修改以下配置：
#
# 1. 将以下目录结构准备到本机某路径（以 /data/jys_model_source 为例）：
#    /data/jys_model_source/
#    ├── MEA/codes/WaveGuard/          # WaveGuard 推理源码
#    ├── MEA/codes/LIDMark/            # LIDMark 推理源码（可选）
#    └── ...
#
# 2. 将 ./weights/ 目录填充：
#    ./weights/mea/WaveGuard/exp_highpass/.../model_state_16.pth
#    ./weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth
#    ./weights/mea/HiDDeN/runs/.../hidden_celeba_noise--epoch-300.pyt
#    ./weights/mea/KAD-Net/EC_50.pth
#
# 3. 取消注释下方 docker-compose.yml volumes 中的 model_source 挂载行：
#    - /data/jys_model_source:/app/model_source:ro
#    并将 /data/jys_model_source 替换为实际路径。
#
# 4. 就绪检查（启动前运行）：
#    ls ./weights/mea/WaveGuard/exp_highpass/*/model_state_16.pth && echo "WaveGuard OK"
#    ls ./weights/mea/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_115.pth && echo "SepMark OK"
#    ls ./weights/mea/HiDDeN/runs/*/hidden_celeba_noise--epoch-300.pyt && echo "HiDDeN OK"
#    ls ./weights/mea/KAD-Net/EC_50.pth && echo "KAD-Net OK"
# ============================================================

IMAGE_TAR=$(ls jianyuanshield_offline_*.tar 2>/dev/null | head -1)
if [ -z "$IMAGE_TAR" ]; then
    echo "Error: no jianyuanshield_offline_*.tar found"
    exit 1
fi

echo "Loading image from $IMAGE_TAR ..."
docker load -i "$IMAGE_TAR"

echo ""
echo "=== 权重就绪检查 ==="
WEIGHT_OK=true
for f in \
    "./weights/mea/WaveGuard/exp_highpass" \
    "./weights/mea/SepMark/results" \
    "./weights/mea/HiDDeN/runs" \
    "./weights/mea/KAD-Net"; do
    if [ ! -d "$f" ]; then
        echo "  MISSING: $f"
        WEIGHT_OK=false
    else
        echo "  OK: $f"
    fi
done
if [ "$WEIGHT_OK" = "false" ]; then
    echo ""
    echo "⚠️  部分权重目录缺失。请参考上方'权重目录准备说明'填充后再启动。"
    echo "   如要继续（仅前端/API 演示，推理将报错），请输入 y 确认："
    read -r confirm
    if [ "$confirm" != "y" ]; then
        echo "已取消启动。"
        exit 1
    fi
fi

echo ""
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
echo "⚠️  重要提醒：模型权重【未打包进镜像】，需另行准备。"
echo "   请在答辩机器上运行 deploy_offline.sh 前，按照脚本顶部说明准备权重目录。"
echo ""
echo "答辩时，将以下文件拷贝到现场机器并运行："
echo "  ${OUTPUT_TAR}, ${DEPLOY_SCRIPT}, docker-compose.yml, weights/ 目录"
echo "  bash ${DEPLOY_SCRIPT}"
