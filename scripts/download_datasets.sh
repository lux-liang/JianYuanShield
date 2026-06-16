#!/usr/bin/env bash
# 鉴源盾 — Deepfake 数据集 / 换脸模型 下载脚本
# ⚠️ 在【能联网的机器】上运行（算力 box 只能连 Tsinghua，下不了 HF/Kaggle/GDrive）。
#    下完用 rsync/scp 上传到 box: /data1/luxliang/datasets/  (占位目录已存在)
#
# 用法: bash download_datasets.sh <target>   target ∈ {models, ffhq, celebdf, dfdc, ff++, df40, all-auto}
#   all-auto = 无需人工审批的全部(models + ffhq缩略图 + celebdf + dfdc-preview)
#
# 前置(各自一次性)：
#   Kaggle: pip install kaggle; 在 kaggle.com/settings 生成 API token → ~/.kaggle/kaggle.json (chmod 600)
#   HF:     pip install "huggingface_hub[cli]"; huggingface-cli login (DF40/部分镜像需要)
#   其它:   pip install gdown insightface onnxruntime-gpu
set -euo pipefail
OUT="${JYS_DATASET_OUT:-$HOME/jys_datasets}"   # 本地暂存目录；下完再上传 box
mkdir -p "$OUT"
echo "下载暂存目录: $OUT  (完成后 rsync 到 box: /data1/luxliang/datasets/)"

dl_models() {  # P1 闭环必备：换脸/重演模型权重(开源,无EULA,可直下)
  echo "== 换脸模型 InSwapper (insightface) =="
  python -c "import insightface; insightface.app.FaceAnalysis(name='buffalo_l').prepare(ctx_id=0)" || true
  python - <<'PY'
from insightface.model_zoo import get_model
get_model('inswapper_128.onnx', download=True, download_zip=False)  # ~250MB
print("inswapper_128.onnx ready (在 ~/.insightface/models/)")
PY
  echo "== (可选)SimSwap: git clone https://github.com/neuralchen/SimSwap + release 权重 =="
  echo "== (可选)重演 First-Order-Motion: git clone https://github.com/AliaksandrSiarohin/first-order-model =="
}

dl_ffhq() {    # 可选：高清/多族群干净人脸源(无审批)
  echo "== FFHQ 128px 缩略图 (~1.95GB) =="
  git clone https://github.com/NVlabs/ffhq-dataset "$OUT/ffhq-repo" 2>/dev/null || true
  ( cd "$OUT/ffhq-repo" && python download_ffhq.py --thumbs ) || \
  huggingface-cli download --repo-type dataset marcosv/ffhq-dataset --local-dir "$OUT/ffhq"
}

dl_celebdf() { # 必须：Kaggle 非官方镜像(只需 Kaggle 账号,绕过官方表单) ~14GB
  echo "== Celeb-DF v2 (Kaggle 镜像 reubensuju/celeb-df-v2, ~14GB) =="
  kaggle datasets download -d reubensuju/celeb-df-v2 -p "$OUT/celebdf_v2" --unzip
}

dl_dfdc() {    # 可选：Kaggle preview(~4GB) 或单分片. 需先网页 Accept Rules
  echo "== DFDC preview (~4GB). 先在 kaggle.com/c/deepfake-detection-challenge 点 Accept Rules =="
  kaggle competitions download -c deepfake-detection-challenge -f dfdc_train_part_0.zip -p "$OUT/dfdc" || \
  echo "若失败: 多半未接受规则，或文件名变更，到竞赛 Data 页确认分片名。"
}

dl_ffpp() {    # 必须但需人工审批：FF++
  cat <<'EOF'
== FaceForensics++ : 需人工签 EULA/表单(我/脚本无法自动下) ==
1) 今天就填表单(审批 1-3 天): https://docs.google.com/forms/d/e/1FAIpQLSdRRR3L5zAv6tQ_CKxmK4W96tAab_pfBu2EKAgQbeDVhmXagg/viewform
2) 审批通过后会收到 download-FaceForensics.py
3) 最小子集(c23, 仅换脸+重演代表+原始, 几GB):
   python download-FaceForensics.py <OUT>/faceforensics -d original        -c c23 -t videos --server EU2
   python download-FaceForensics.py <OUT>/faceforensics -d Deepfakes       -c c23 -t videos --server EU2
   python download-FaceForensics.py <OUT>/faceforensics -d NeuralTextures  -c c23 -t videos --server EU2
应急(非官方, 仅需Kaggle账号): kaggle datasets download -d xdxd003/ff-c23
EOF
}

dl_df40() {    # 建议但需人工审批：DF40
  cat <<'EOF'
== DF40 : 需人工签 EULA/表单(我/脚本无法自动下) ==
1) 今天就填表单: https://docs.google.com/forms/d/1ESAWoWusOEGEEVnXCH_emv-wJqCYMhCbD6-85RMIoDk
   (许可 CC BY-NC 4.0, 竞赛非商业用途符合)
2) 通过后发 Google Drive + 百度网盘链接; 最小子集只取 FS(换脸)+FR(重演)两类:
   gdown --folder <Drive链接> -O <OUT>/df40
   (国内机器 Drive 不通则走百度网盘手动转存)
EOF
}

case "${1:-help}" in
  models) dl_models;;
  ffhq) dl_ffhq;;
  celebdf) dl_celebdf;;
  dfdc) dl_dfdc;;
  ff++|ffpp) dl_ffpp;;
  df40) dl_df40;;
  all-auto) dl_models; dl_ffhq; dl_celebdf; dl_dfdc; echo; echo ">>> 人工审批项(今天提交):"; dl_ffpp; dl_df40;;
  *) sed -n '2,16p' "$0";;
esac

cat <<EOF

下一步(你来做)：把 $OUT 上传到 box——
  rsync -avP -e 'ssh -p 10085' $OUT/  luxliang@127.0.0.1:/data1/luxliang/datasets/
然后告诉我，我接着写 P1 闭环(嵌水印→换脸→解码)脚本并在 box 上跑。
EOF
