from __future__ import annotations

"""
run_watermark_dataset_benchmark.py  ——  Track A: 适配器无关的大规模鲁棒性评测器
评测 4 个鲁棒水印模型在新数据集真假脸(deepfake_images_extracted)上的
全攻击套件表现，验证跨数据集泛化 + AIGC(合成脸)可水印性。

运行示例(冒烟):
  PYTHONPATH=. python system/scripts/run_watermark_dataset_benchmark.py \\
    --model kadnet \\
    --image-root /data1/luxliang/datasets/deepfake_images_extracted/Real \\
    --report-subdir kadnet_deepfakeset_real \\
    --num-images 2 --device cuda:5
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# ── 项目根加入 sys.path ────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# ── 模型名称映射表 (CLI key -> adapter module & class name) ───────────────────
_MODEL_MAP: dict[str, tuple[str, str]] = {
    "kadnet":    ("system.evaluation.adapters.kadnet_adapter",    "KADNetAdapter"),
    "waveguard": ("system.evaluation.adapters.waveguard_adapter", "WaveGuardModelAdapter"),
    "hidden":    ("system.evaluation.adapters.hidden_adapter",    "HiDDeNAdapter"),
    "sepmark":   ("system.evaluation.adapters.sepmark_adapter",   "SepMarkModelAdapter"),
    "lidmark":   ("system.evaluation.adapters.lidmark_adapter",   "LIDMarkAdapter"),
}

# 模型 key -> 在报告/协议中使用的规范名称
_MODEL_CANONICAL: dict[str, str] = {
    "kadnet":    "KAD-Net",
    "waveguard": "WaveGuard",
    "hidden":    "HiDDeN",
    "sepmark":   "SepMark",
    "lidmark":   "LIDMark",
}

DEFAULT_ATTACKS = [
    "clean", "jpeg50", "jpeg70", "jpeg90", "webp50",
    "resize_0.5x", "crop_center_0.8", "rotate_5",
    "gaussian_blur_5", "gaussian_noise_sigma_3",
    "brightness_0.85", "contrast_1.2",
    "platform_wechat_v1", "platform_douyin_v1",
]

FLUSH_EVERY = 200   # 每处理多少张图片落盘一次


# ─────────────────────────────────────────────────────────────────────────────
# 参数解析
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Track A: adapter-agnostic watermark robustness benchmark on new dataset",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--model",
        choices=list(_MODEL_MAP.keys()),
        required=True,
        help="水印模型 (kadnet/waveguard/hidden/sepmark/lidmark)",
    )
    p.add_argument(
        "--image-root",
        type=Path,
        required=True,
        help="图片根目录，递归搜索 *.jpg/*.jpeg/*.png",
    )
    p.add_argument(
        "--report-subdir",
        required=True,
        help="报告子目录名称 (写入 system/reports/<NAME>/)",
    )
    p.add_argument("--num-images", type=int, default=5000, help="最多处理的图片数量")
    p.add_argument("--device", default="cuda:0", help="推理设备 (如 cuda:5)")
    p.add_argument("--seed", type=int, default=20260616, help="随机种子")
    p.add_argument("--artifact-limit", type=int, default=50,
                   help="最多保存多少张水印图片到 artifacts 目录")
    p.add_argument(
        "--attacks",
        nargs="+",
        default=DEFAULT_ATTACKS,
        help="攻击 ID 列表 (来自 system.evaluation.attacks.ATTACKS)",
    )
    return p.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────

def load_adapter(model_key: str):
    """按 CLI key 动态导入并实例化适配器。"""
    import importlib
    module_name, cls_name = _MODEL_MAP[model_key]
    module = importlib.import_module(module_name)
    cls = getattr(module, cls_name)
    return cls()


def list_images(root: Path, limit: int) -> list[Path]:
    """递归列出所有图片，按路径排序后截取 limit 张。"""
    exts = {".jpg", ".jpeg", ".png"}
    imgs = sorted(p for p in root.rglob("*") if p.suffix.lower() in exts)
    if limit > 0:
        imgs = imgs[:limit]
    return imgs


def read_done(csv_path: Path) -> set[tuple[str, str]]:
    """从已有 CSV 中读出已完成的 (image_id, attack_id) 对，用于断点续跑。"""
    if not csv_path.exists():
        return set()
    done: set[tuple[str, str]] = set()
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["image_id"], row["attack_id"]))
    return done


_CSV_FIELDS = [
    "image_id", "source_path", "label",
    "attack_id", "attack_category", "evidence_level",
    "bit_accuracy", "bit_error", "success",
    "psnr_wm_vs_orig", "ssim_wm_vs_orig",
    "error",
]


def append_rows(csv_path: Path, rows: list[dict[str, Any]]) -> None:
    """追加写入 CSV，首次写入时添加表头。"""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def infer_label(img_path: Path) -> str:
    """
    从路径推断标签：
      - 父目录名为 Real  -> label=real
      - 父目录名为 Fake  -> label=fake
      - 否则          -> label=unknown
    """
    parent_name = img_path.parent.name.lower()
    if parent_name == "real":
        return "real"
    if parent_name == "fake":
        return "fake"
    return "unknown"


def load_success_threshold() -> tuple[float, bool]:
    """
    从 evaluation_protocol.v1.json 读取 success_threshold；
    读取失败时回退到 0.9 并标记 fallback=True。
    """
    try:
        from system.evaluation.protocol import load_protocol
        protocol = load_protocol()
        return float(protocol["success_threshold"]), False
    except Exception:
        return 0.9, True


def build_summary(
    csv_path: Path,
    attacks: list[str],
    model_canonical: str,
    ckpt_str: str,
    image_root: str,
    dataset_name: str,
    n_requested: int,
    success_threshold: float,
    threshold_fallback: bool,
) -> dict[str, Any]:
    """从 CSV 汇总每个攻击的均值统计。"""
    rows: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if not r.get("error")]

    summary: dict[str, Any] = {
        "project": "鉴源盾",
        "track": "A",
        "method": model_canonical,
        "checkpoint": ckpt_str,
        "image_root": image_root,
        "dataset_name": dataset_name,
        "n_requested": n_requested,
        "n_evaluated_rows": len(rows),
        "success_threshold": success_threshold,
        "success_threshold_source": (
            "configs/evaluation_protocol.v1.json"
            if not threshold_fallback
            else "fallback_default_0.9"
        ),
        "attacks": {},
    }

    for attack_id in attacks:
        subset = [r for r in rows if r["attack_id"] == attack_id]
        if not subset:
            summary["attacks"][attack_id] = {"status": "pending", "count": 0}
            continue

        def _floats(key: str) -> np.ndarray:
            return np.array([float(r[key]) for r in subset if r.get(key) != ""])

        bit_acc = _floats("bit_accuracy")
        bit_err = _floats("bit_error")
        psnr_vals = _floats("psnr_wm_vs_orig")
        ssim_vals = _floats("ssim_wm_vs_orig")
        success_arr = np.array([r["success"] == "1" for r in subset], dtype=float)

        # 按标签分组的成功率
        real_rows = [r for r in subset if r.get("label") == "real"]
        fake_rows = [r for r in subset if r.get("label") == "fake"]
        real_success = (
            round(float(np.mean([r["success"] == "1" for r in real_rows])), 6)
            if real_rows else None
        )
        fake_success = (
            round(float(np.mean([r["success"] == "1" for r in fake_rows])), 6)
            if fake_rows else None
        )

        summary["attacks"][attack_id] = {
            "status": "complete",
            "count": len(subset),
            "mean_bit_accuracy": round(float(bit_acc.mean()), 6) if bit_acc.size else None,
            "mean_bit_error": round(float(bit_err.mean()), 6) if bit_err.size else None,
            f"success_rate@{success_threshold}": round(float(success_arr.mean()), 6),
            "mean_psnr_wm_vs_orig": round(float(psnr_vals.mean()), 6) if psnr_vals.size else None,
            "mean_ssim_wm_vs_orig": round(float(ssim_vals.mean()), 6) if ssim_vals.size else None,
            "n_real": len(real_rows),
            "n_fake": len(fake_rows),
            f"success_rate_real@{success_threshold}": real_success,
            f"success_rate_fake@{success_threshold}": fake_success,
        }

    return summary


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # ── 1. 设置推理设备(必须在导入适配器前) ─────────────────────────────────
    import os
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)

    # ── 2. 导入后续依赖(依赖 sys.path 与环境变量已就绪) ─────────────────────
    from system.evaluation.attacks import apply_attack, ATTACKS as ATTACK_REGISTRY
    from system.evaluation.metrics import bit_metrics, image_quality
    from system.evaluation.run_metadata import build_run_metadata
    from system.evaluation.runtime import REPORT_ROOT

    # ── 3. 校验攻击 ID ────────────────────────────────────────────────────────
    unknown_attacks = [a for a in args.attacks if a not in ATTACK_REGISTRY]
    if unknown_attacks:
        print(
            f"[ERROR] 未知攻击 ID: {unknown_attacks}\n"
            f"可用 ID: {sorted(ATTACK_REGISTRY.keys())}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── 4. 加载适配器 ─────────────────────────────────────────────────────────
    print(f"[INFO] 正在加载适配器: {args.model}")
    adapter = load_adapter(args.model)
    if not adapter.available:
        print(f"[ERROR] 适配器不可用: {adapter.blocker}", file=sys.stderr)
        sys.exit(1)

    model_canonical = _MODEL_CANONICAL[args.model]
    ckpt_str = str(adapter.checkpoint) if adapter.checkpoint else "unknown"
    msg_len = adapter.message_length
    print(f"[INFO] 模型={model_canonical}  checkpoint={ckpt_str}  message_length={msg_len}")

    # ── 5. 读取 success_threshold ─────────────────────────────────────────────
    success_threshold, threshold_fallback = load_success_threshold()
    if threshold_fallback:
        print(
            "[WARN] 无法从 evaluation_protocol.v1.json 读取 success_threshold，"
            "回退到默认值 0.9",
            file=sys.stderr,
        )
    print(f"[INFO] success_threshold={success_threshold}"
          f"  (source={'protocol' if not threshold_fallback else 'fallback'})")

    # ── 6. 建立报告目录 ───────────────────────────────────────────────────────
    report_dir = REPORT_ROOT / args.report_subdir
    artifact_dir = report_dir / "artifacts"
    report_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    csv_path = report_dir / "results.csv"
    summary_path = report_dir / "summary.json"
    progress_path = report_dir / "progress.json"

    # ── 7. 列出图片 & 断点续跑 ────────────────────────────────────────────────
    images = list_images(args.image_root, args.num_images)
    if not images:
        print(f"[ERROR] 在 {args.image_root} 下未找到任何图片", file=sys.stderr)
        sys.exit(1)
    print(f"[INFO] 找到 {len(images)} 张图片 (limit={args.num_images})")

    done = read_done(csv_path)
    print(f"[INFO] 已完成行数(断点续跑): {len(done)}")

    dataset_name = args.image_root.name  # 例如 Real / Fake

    # ── 8. 随机种子(消息生成用) ───────────────────────────────────────────────
    rng = np.random.default_rng(args.seed)

    # ── 9. 主循环 ─────────────────────────────────────────────────────────────
    pending: list[dict[str, Any]] = []
    artifact_count = 0
    processed = 0
    t0 = time.time()

    for img_path in images:
        image_id = img_path.stem
        label = infer_label(img_path)

        # 加载原始图片
        try:
            img_orig = np.array(Image.open(img_path).convert("RGB"))
        except Exception as exc:
            # 图片无法读取 -> 对所有攻击都记录 error 行
            for attack_id in args.attacks:
                if (image_id, attack_id) not in done:
                    pending.append({
                        "image_id": image_id,
                        "source_path": str(img_path),
                        "label": label,
                        "attack_id": attack_id,
                        "attack_category": "",
                        "evidence_level": "",
                        "bit_accuracy": "",
                        "bit_error": "",
                        "success": "0",
                        "psnr_wm_vs_orig": "",
                        "ssim_wm_vs_orig": "",
                        "error": f"image_load_error: {repr(exc)}",
                    })
            processed += 1
            continue

        # 生成随机消息(每张图片独立)
        msg = rng.integers(0, 2, size=(msg_len,)).astype(np.uint8)

        # 编码水印
        try:
            enc_result = adapter.encode(img_orig, msg)
            enc_arr: np.ndarray = enc_result.image  # uint8 RGB, 与原图同尺寸
        except Exception as exc:
            for attack_id in args.attacks:
                if (image_id, attack_id) not in done:
                    pending.append({
                        "image_id": image_id,
                        "source_path": str(img_path),
                        "label": label,
                        "attack_id": attack_id,
                        "attack_category": "",
                        "evidence_level": "",
                        "bit_accuracy": "",
                        "bit_error": "",
                        "success": "0",
                        "psnr_wm_vs_orig": "",
                        "ssim_wm_vs_orig": "",
                        "error": f"encode_error: {repr(exc)}",
                    })
            processed += 1
            continue

        # 计算水印图 vs 原图的质量指标(仅算一次)
        try:
            wm_quality = image_quality(img_orig, enc_arr)
            psnr_wm = wm_quality["psnr"]
            ssim_wm = wm_quality["ssim"]
        except Exception as exc:
            psnr_wm = float("nan")
            ssim_wm = float("nan")
            print(
                f"[WARN] image_quality 计算失败 image_id={image_id}: {exc}",
                file=sys.stderr,
            )

        # 保存水印样本(artifact)
        if artifact_count < args.artifact_limit:
            try:
                Image.fromarray(enc_arr).save(
                    artifact_dir / f"{image_id}_watermarked.jpg", quality=95
                )
                artifact_count += 1
            except Exception:
                pass

        # 对每个攻击进行测试
        for attack_id in args.attacks:
            if (image_id, attack_id) in done:
                continue

            attack_spec = ATTACK_REGISTRY[attack_id]

            try:
                # 在真实被操纵后的图上 decode，不走捷径
                attacked_arr, attack_meta = apply_attack(
                    enc_arr,
                    attack_id,
                    image_id=image_id,
                    global_seed=args.seed,
                )
                dec_result = adapter.decode(attacked_arr)
                decoded_bits: np.ndarray = dec_result.bits  # uint8

                bm = bit_metrics(msg, decoded_bits, success_threshold=success_threshold)
                bit_acc = bm["accuracy"]
                bit_err = bm["ber"]
                success_flag = "1" if bm["success"] else "0"

                pending.append({
                    "image_id": image_id,
                    "source_path": str(img_path),
                    "label": label,
                    "attack_id": attack_id,
                    "attack_category": attack_meta.get("category", attack_spec.category),
                    "evidence_level": attack_meta.get("evidence_level", attack_spec.evidence_level),
                    "bit_accuracy": f"{bit_acc:.6f}",
                    "bit_error": f"{bit_err:.6f}",
                    "success": success_flag,
                    "psnr_wm_vs_orig": f"{psnr_wm:.6f}",
                    "ssim_wm_vs_orig": f"{ssim_wm:.6f}",
                    "error": "",
                })

            except Exception as exc:
                pending.append({
                    "image_id": image_id,
                    "source_path": str(img_path),
                    "label": label,
                    "attack_id": attack_id,
                    "attack_category": attack_spec.category,
                    "evidence_level": attack_spec.evidence_level,
                    "bit_accuracy": "",
                    "bit_error": "",
                    "success": "0",
                    "psnr_wm_vs_orig": "",
                    "ssim_wm_vs_orig": "",
                    "error": f"attack_or_decode_error: {repr(exc)}",
                })

        processed += 1

        # 周期落盘(每 FLUSH_EVERY 张)
        if pending and processed % FLUSH_EVERY == 0:
            append_rows(csv_path, pending)
            pending = []

            elapsed = time.time() - t0
            remaining = len(images) - processed
            eta_s = elapsed / processed * remaining if processed > 0 else 0

            # 中间 summary
            if csv_path.exists():
                mid_summary = build_summary(
                    csv_path, args.attacks, model_canonical, ckpt_str,
                    str(args.image_root), dataset_name, len(images),
                    success_threshold, threshold_fallback,
                )
                summary_path.write_text(
                    json.dumps(mid_summary, indent=2, ensure_ascii=False)
                )
                clean_entry = mid_summary["attacks"].get("clean", {})
                clean_acc = clean_entry.get("mean_bit_accuracy", "?")
                clean_sr = clean_entry.get(f"success_rate@{success_threshold}", "?")
            else:
                clean_acc, clean_sr = "?", "?"

            progress_path.write_text(json.dumps({
                "processed": processed,
                "total": len(images),
                "elapsed_s": round(elapsed, 1),
                "eta_s": round(eta_s, 1),
                "artifacts_saved": artifact_count,
                "updated_at": int(time.time()),
            }, indent=2))

            print(
                f"[{processed}/{len(images)}] "
                f"clean_bit_acc={clean_acc}  clean_sr@{success_threshold}={clean_sr}  "
                f"eta={round(eta_s / 60, 1)}min"
            )

    # ── 10. 末尾落盘 ──────────────────────────────────────────────────────────
    if pending:
        append_rows(csv_path, pending)

    # ── 11. 最终 summary ──────────────────────────────────────────────────────
    if not csv_path.exists():
        print("[WARN] CSV 文件不存在，无法生成 summary", file=sys.stderr)
        sys.exit(0)

    final_summary = build_summary(
        csv_path, args.attacks, model_canonical, ckpt_str,
        str(args.image_root), dataset_name, len(images),
        success_threshold, threshold_fallback,
    )

    # 附加 run_metadata
    final_summary["run_metadata"] = build_run_metadata(
        model=model_canonical,
        checkpoint=Path(ckpt_str) if ckpt_str != "unknown" else None,
        seed=args.seed,
        command=sys.argv,
    )

    # run_metadata 中补充本脚本特有字段
    final_summary["run_metadata"].update({
        "generated_at": int(time.time()),  # 确保字段存在(build_run_metadata 已含此字段)
        "device": args.device,
        "image_root": str(args.image_root),
        "dataset_name": dataset_name,
        "n": len(images),
        "n_attacks": len(args.attacks),
        "artifact_limit": args.artifact_limit,
        "artifacts_saved": artifact_count,
        "success_threshold": success_threshold,
        "success_threshold_fallback": threshold_fallback,
    })

    summary_path.write_text(json.dumps(final_summary, indent=2, ensure_ascii=False))
    progress_path.write_text(json.dumps({
        "processed": len(images),
        "total": len(images),
        "status": "complete",
        "artifacts_saved": artifact_count,
        "updated_at": int(time.time()),
    }, indent=2))

    # 打印摘要(不含 run_metadata 以减少噪声)
    printable = {k: v for k, v in final_summary.items() if k != "run_metadata"}
    print(json.dumps(printable, indent=2, ensure_ascii=False))
    print(f"\n[INFO] 报告已写入: {report_dir}")


if __name__ == "__main__":
    main()
