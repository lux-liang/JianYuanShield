#!/usr/bin/env python3
"""LIDMark 完整配置 16-bit ID 比特精度正测 (修复 D2).

背景: 早先 run_lidmark_idbit_eval.py 在 **MEA 模式**(136 维 landmark 全置 0)下测得
clean id-bit-acc≈62% (近随机). 但 landmark 置零是 out-of-distribution 输入, 可能低估
真实能力. LIDMark 的 watermark 是 152 维 = [136 维归一化 landmark, 16 维 id]:
  - utils.py:calculate_metrics → gt_landmarks_flat=wms[:,:136], gt_landmarks_pixels=points*img_size
    ⇒ landmark 归一化口径 = 坐标 / img_size ∈ [0,1] (与分辨率无关).
本脚本用 face_alignment(2DFAN4+S3FD, 权重已在 box torch hub 缓存, 离线可用) 检测 68 点真实
landmark, 按 [0,1] 归一化填入 watermark 前 136 维, 在**完整配置**下测 16-bit id 比特精度;
并在**同一批图**上跑 MEA(landmark 置零)对照, 直接量化"置零是否低估". 诚实呈现两者。

用法:
  PYTHONPATH=. python system/scripts/run_lidmark_idbit_full.py \
      --image-root /data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown \
      --num-images 1000 --device cuda:0 --out system/reports/lidmark_idbit_full
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

DEFAULT_IMAGE_ROOT = Path(
    "/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown"
)
DEFAULT_ATTACKS = ["clean", "jpeg50", "resize_0.5x", "gaussian_noise_sigma_3"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LIDMark 完整配置 16-bit ID 比特精度正测")
    p.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    p.add_argument("--num-images", type=int, default=1000)
    p.add_argument("--attacks", nargs="+", default=DEFAULT_ATTACKS)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/lidmark_idbit_full")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    import os
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)

    import torch
    from system.evaluation.adapters.lidmark_adapter import (
        LIDMarkAdapter, IMG_SIZE, WM_LEN, LANDMARK_LEN, MSG_LEN,
    )
    from system.evaluation.attacks import apply_attack
    from system.evaluation.metrics import bit_metrics

    # ── 模型(复用适配器加载逻辑, 保证与基准一致) ─────────────────────────────
    adapter = LIDMarkAdapter()
    if not adapter.available:
        print(f"LIDMark unavailable: {adapter.blocker}", file=sys.stderr)
        sys.exit(1)
    adapter._load_models()
    enc, dec, device = adapter._encoder, adapter._decoder, adapter._device
    print(f"[init] LIDMark ckpt={adapter.checkpoint}  device={device}")

    # ── face_alignment(离线, 用 box torch hub 缓存的 2DFAN4 + S3FD) ───────────
    import face_alignment
    try:
        fa = face_alignment.FaceAlignment(
            face_alignment.LandmarksType.TWO_D, device=str(device), flip_input=False)
    except AttributeError:
        fa = face_alignment.FaceAlignment(
            face_alignment.LandmarksType._2D, device=str(device), flip_input=False)
    print("[init] face_alignment ready (offline cached weights)")

    def detect_landmarks_norm(img_uint8: np.ndarray):
        """返回 [0,1] 归一化的 136 维 landmark 向量(检测失败返回 None)。"""
        h, w = img_uint8.shape[:2]
        preds = fa.get_landmarks(img_uint8)
        if not preds:
            return None
        pts = np.asarray(preds[0], dtype=np.float32)  # (68,2) 像素 (x,y)
        norm = pts.copy()
        norm[:, 0] /= float(w)
        norm[:, 1] /= float(h)
        norm = np.clip(norm, 0.0, 1.0)
        return norm.reshape(-1)  # 136, 顺序 [x0,y0,x1,y1,...] 与 view(68,2) 一致

    def encode_with_wm(img_uint8: np.ndarray, id_bits: np.ndarray, landmarks_norm) -> np.ndarray:
        """构造 152 维 watermark 并嵌入。landmarks_norm=None → MEA 模式(置零)。"""
        img_pil = Image.fromarray(img_uint8).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)
        arr = np.array(img_pil).astype(np.float32) / 255.0
        t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(device) * 2 - 1
        wm_np = np.zeros(WM_LEN, dtype=np.float32)
        if landmarks_norm is not None:
            wm_np[:LANDMARK_LEN] = landmarks_norm
        wm_np[LANDMARK_LEN:] = id_bits.astype(np.float32) * 2 - 1
        wm_t = torch.from_numpy(wm_np).unsqueeze(0).to(device)
        with torch.no_grad():
            out = enc(t, wm_t).clamp(-1, 1)
        enc_np = ((out[0].cpu().numpy().transpose(1, 2, 0) + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
        if enc_np.shape[:2] != img_uint8.shape[:2]:
            enc_np = np.array(Image.fromarray(enc_np).resize(
                (img_uint8.shape[1], img_uint8.shape[0]), Image.BICUBIC))
        return enc_np

    def decode_id(img_uint8: np.ndarray) -> np.ndarray:
        arr = np.array(Image.fromarray(img_uint8).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)).astype(np.float32) / 255.0
        t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(device) * 2 - 1
        with torch.no_grad():
            _, id_logits = dec(t)
        return (torch.sigmoid(id_logits).cpu().numpy()[0] >= 0.5).astype(np.uint8)

    # ── 数据 ────────────────────────────────────────────────────────────────
    paths = sorted(p for p in args.image_root.rglob("*")
                   if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.num_images]
    if not paths:
        print(f"no images under {args.image_root}", file=sys.stderr)
        sys.exit(1)
    rng = np.random.default_rng(args.seed)

    # acc 累积: arm ∈ {full, mea}, 每个 attack 一组
    accs = {arm: {a: [] for a in args.attacks} for arm in ("full", "mea")}
    n_detected = 0
    n_total = 0
    t0 = time.time()

    for i, pth in enumerate(paths):
        img = np.array(Image.open(pth).convert("RGB"))
        lmk = detect_landmarks_norm(img)
        n_total += 1
        if lmk is None:
            continue  # 完整配置需要真实 landmark; 检测失败的图不计入(两 arm 都跳过, 保证同批)
        n_detected += 1
        id_bits = rng.integers(0, 2, size=MSG_LEN).astype(np.uint8)

        wm_full = encode_with_wm(img, id_bits, lmk)     # 真实 landmark
        wm_mea = encode_with_wm(img, id_bits, None)     # 置零对照

        for a in args.attacks:
            try:
                atk_full, _ = apply_attack(wm_full, a, image_id=pth.stem, global_seed=args.seed)
                atk_mea, _ = apply_attack(wm_mea, a, image_id=pth.stem, global_seed=args.seed)
            except Exception as e:  # noqa: BLE001
                print(f"  WARN attack {a} on {pth.name}: {e!r}")
                continue
            accs["full"][a].append(bit_metrics(id_bits, decode_id(atk_full))["accuracy"])
            accs["mea"][a].append(bit_metrics(id_bits, decode_id(atk_mea))["accuracy"])

        if (i + 1) % 100 == 0:
            el = time.time() - t0
            cf = np.mean(accs["full"]["clean"]) if accs["full"]["clean"] else float("nan")
            print(f"[{i+1}/{len(paths)}] detected={n_detected} clean_full_idacc={cf:.4f} "
                  f"eta={el/(i+1)*(len(paths)-i-1)/60:.1f}min")

    def summarize(arm: str) -> dict:
        out = {}
        for a in args.attacks:
            v = np.array(accs[arm][a], dtype=float)
            if v.size == 0:
                out[a] = {"status": "empty"}
                continue
            out[a] = {
                "mean_id_bit_accuracy": round(float(v.mean()), 6),
                "success_rate@0.9": round(float((v >= 0.9).mean()), 6),
                "n": int(v.size),
            }
        return out

    report = {
        "schema": "lidmark-idbit-full.v1",
        "generated_at": int(time.time()),
        "project": "鉴源盾", "method": "LIDMark", "metric": "16-bit ID bit accuracy",
        "checkpoint": adapter.checkpoint,
        "image_root": str(args.image_root),
        "requested_images": len(paths),
        "faces_detected": n_detected, "images_seen": n_total,
        "face_detection_rate": round(n_detected / max(n_total, 1), 4),
        "landmark_source": "face_alignment 2DFAN4+S3FD (offline cached), norm=coords/imgsize∈[0,1]",
        "device": str(device), "seed": args.seed,
        "attacks": args.attacks,
        "full_config": summarize("full"),
        "mea_zeroed_landmark": summarize("mea"),
        "elapsed_seconds": round(time.time() - t0, 1),
        "interpretation_note": (
            "full_config = 真实 landmark 填入前136维(in-distribution); "
            "mea_zeroed_landmark = landmark 置零(OOD, 旧基准口径). "
            "比较二者 clean id-bit-acc 即可判断'置零是否低估 LIDMark 的 id 比特能力'。"
        ),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    rp = args.out / "summary.json"
    rp.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ("faces_detected", "full_config", "mea_zeroed_landmark")},
                     indent=2, ensure_ascii=False))
    print(f"[done] → {rp}")


if __name__ == "__main__":
    main()
