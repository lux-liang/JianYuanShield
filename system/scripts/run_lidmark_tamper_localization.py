#!/usr/bin/env python3
"""LIDMark landmark-位移 篡改定位 —— 解决 B2 遮挡法 AUC≈0.5 的负结果.

设计思路(LIDMark 独有)：水印里嵌入的是**真实人脸的 landmark 几何**(136维)。对真图嵌水印后,
若被换脸/拼接篡改,则:
  - 水印解出的 landmark = **原真脸几何**(水印鲁棒则得以保留);
  - 对篡改图重新检测的 landmark = **被改后的可见几何**(篡改区域已变);
二者的**逐点位移**在被篡改的人脸区域显著增大 → 据此生成定位热图 → 与篡改 mask 比 AUC/IoU。
这正是全局比特水印(遮挡法)做不到、而 LIDMark 几何水印能做的篡改定位。

对照:同时报 (a) 水印 landmark 存活度(decoded vs embedded authentic 的位移, 越小越好),
(b) 定位 AUC/IoU, (c) 与遮挡法 baseline 对比。

用法:
  PYTHONPATH=. python system/scripts/run_lidmark_tamper_localization.py \
      --host-root /data1/luxliang/datasets/deepfake_images_extracted/Real \
      --num-images 200 --device cuda:2 --out system/reports/lidmark_tamper_loc
"""
from __future__ import annotations

import argparse, json, sys, time
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

DEFAULT_HOST = Path("/data1/luxliang/datasets/deepfake_images_extracted/Real")


def parse_args():
    p = argparse.ArgumentParser(description="LIDMark landmark-displacement tamper localization")
    p.add_argument("--host-root", type=Path, default=DEFAULT_HOST)
    p.add_argument("--donor-root", type=Path, default=DEFAULT_HOST)
    p.add_argument("--num-images", type=int, default=200)
    p.add_argument("--grid", type=int, default=16, help="定位热图下采样网格(评 AUC/IoU 用)")
    p.add_argument("--device", default="cuda:2")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--save-heatmaps", type=int, default=8)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/lidmark_tamper_loc")
    return p.parse_args()


def numpy_auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """rank-based ROC-AUC(Mann-Whitney), 纯 numpy。labels∈{0,1}。"""
    pos = scores[labels == 1]; neg = scores[labels == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1)
    # 处理并列: 平均秩
    _, inv, cnt = np.unique(scores, return_inverse=True, return_counts=True)
    csum = np.cumsum(cnt); start = csum - cnt
    avg = (start + csum + 1) / 2.0
    ranks = avg[inv]
    rank_pos = ranks[labels == 1].sum()
    auc = (rank_pos - pos.size * (pos.size + 1) / 2.0) / (pos.size * neg.size)
    return float(auc)


def main():
    args = parse_args()
    import os
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import torch
    from system.evaluation.adapters.lidmark_adapter import LIDMarkAdapter, IMG_SIZE, WM_LEN, LANDMARK_LEN, MSG_LEN

    adapter = LIDMarkAdapter()
    if not adapter.available:
        print(f"LIDMark unavailable: {adapter.blocker}", file=sys.stderr); sys.exit(1)
    adapter._load_models()
    enc, dec, dev = adapter._encoder, adapter._decoder, adapter._device

    import face_alignment
    try:
        fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device=str(dev), flip_input=False)
    except AttributeError:
        fa = face_alignment.FaceAlignment(face_alignment.LandmarksType._2D, device=str(dev), flip_input=False)
    print(f"[init] LIDMark + face_alignment ready, device={dev}")

    def detect_norm(img):
        preds = fa.get_landmarks(img)
        if not preds:
            return None
        pts = np.asarray(preds[0], dtype=np.float32)
        h, w = img.shape[:2]
        n = pts.copy(); n[:, 0] /= w; n[:, 1] /= h
        return np.clip(n, 0, 1)  # (68,2)

    def encode_lm(img, lm_norm, id_bits):
        img_pil = Image.fromarray(img).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)
        arr = np.array(img_pil).astype(np.float32) / 255.0
        t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(dev) * 2 - 1
        wm = np.zeros(WM_LEN, dtype=np.float32)
        wm[:LANDMARK_LEN] = lm_norm.reshape(-1)
        wm[LANDMARK_LEN:] = id_bits.astype(np.float32) * 2 - 1
        wm_t = torch.from_numpy(wm).unsqueeze(0).to(dev)
        with torch.no_grad():
            out = enc(t, wm_t).clamp(-1, 1)
        e = ((out[0].cpu().numpy().transpose(1, 2, 0) + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
        if e.shape[:2] != img.shape[:2]:
            e = np.array(Image.fromarray(e).resize((img.shape[1], img.shape[0]), Image.BICUBIC))
        return e

    def decode_lm(img):
        arr = np.array(Image.fromarray(img).resize((IMG_SIZE, IMG_SIZE), Image.BICUBIC)).astype(np.float32) / 255.0
        t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(dev) * 2 - 1
        with torch.no_grad():
            lm_pred, _ = dec(t)
        return lm_pred.cpu().numpy()[0].reshape(-1, 2)  # (68,2) normalized

    def face_mask(h, w):
        m = np.zeros((h, w), np.uint8)
        cv2.ellipse(m, (w // 2, int(0.45 * h)), (int(0.27 * min(h, w)), int(0.32 * min(h, w))), 0, 0, 360, 255, -1)
        return m > 0

    host_paths = sorted(p for p in args.host_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    donor_paths = sorted(p for p in args.donor_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    rng = np.random.default_rng(args.seed)

    aucs = []; uni_aucs = []; ious = []; lm_survival = []; occ_aucs_note = "见 system/reports/tamper_localization (遮挡法 baseline≈0.5)"
    n_used = 0; G = args.grid
    asset_dir = args.out / "heatmaps"; saved = 0
    t0 = time.time()

    for i, hp in enumerate(host_paths):
        if n_used >= args.num_images:
            break
        host = np.array(Image.open(hp).convert("RGB"))
        H, W = host.shape[:2]
        L_auth = detect_norm(host)
        if L_auth is None:
            continue
        id_bits = rng.integers(0, 2, size=MSG_LEN).astype(np.uint8)
        wm_host = encode_lm(host, L_auth, id_bits)
        # donor (different image)
        dp = donor_paths[int(rng.integers(len(donor_paths)))]
        if dp == hp:
            dp = donor_paths[(int(rng.integers(len(donor_paths))) + 1) % len(donor_paths)]
        donor = np.array(Image.open(dp).convert("RGB").resize((W, H), Image.BICUBIC))
        M = face_mask(H, W)
        tampered = wm_host.copy(); tampered[M] = donor[M]

        L_dec = decode_lm(tampered)          # 水印解出的(原真脸)几何 (68,2) normalized
        L_act = detect_norm(tampered)        # 篡改图实际可见几何
        if L_act is None:
            continue
        n_used += 1
        lm_survival.append(float(np.mean(np.linalg.norm(L_dec - L_auth, axis=1))))  # 越小=水印landmark越鲁棒

        # 逐点位移 → 空间热图(在 decoded 与 actual 位置都打高斯权重)
        disp = np.linalg.norm(L_dec - L_act, axis=1)  # (68,) in [0,1] coords
        heat = np.zeros((H, W), np.float32)
        heat_uni = np.zeros((H, W), np.float32)  # 对照: 均匀权重(=中心 landmark 先验, 隔离"位移"真贡献)
        for k in range(68):
            for Lset in (L_dec, L_act):
                x = int(np.clip(Lset[k, 0] * W, 0, W - 1)); y = int(np.clip(Lset[k, 1] * H, 0, H - 1))
                heat[y, x] += disp[k]
                heat_uni[y, x] += 1.0
        heat = cv2.GaussianBlur(heat, (0, 0), sigmaX=W * 0.04)
        heat_uni = cv2.GaussianBlur(heat_uni, (0, 0), sigmaX=W * 0.04)

        # 下采样到 G×G 评 AUC/IoU(对齐 mask)
        ms = (cv2.resize(M.astype(np.float32), (G, G), interpolation=cv2.INTER_AREA) >= 0.5).astype(np.uint8).reshape(-1)
        hs = cv2.resize(heat, (G, G), interpolation=cv2.INTER_AREA).reshape(-1)
        hu = cv2.resize(heat_uni, (G, G), interpolation=cv2.INTER_AREA).reshape(-1)
        auc = numpy_auc(hs, ms); auc_u = numpy_auc(hu, ms)
        if not np.isnan(auc):
            aucs.append(auc)
        if not np.isnan(auc_u):
            uni_aucs.append(auc_u)
        thr = np.median(hs)
        pred = (hs >= thr).astype(np.uint8)
        inter = int(((pred == 1) & (ms == 1)).sum()); union = int(((pred == 1) | (ms == 1)).sum())
        if union > 0:
            ious.append(inter / union)

        if saved < args.save_heatmaps:
            hn = (heat / (heat.max() + 1e-9) * 255).astype(np.uint8)
            hn = cv2.applyColorMap(hn, cv2.COLORMAP_JET)
            panel = np.concatenate([cv2.cvtColor(wm_host, cv2.COLOR_RGB2BGR),
                                    cv2.cvtColor(tampered, cv2.COLOR_RGB2BGR),
                                    hn,
                                    cv2.cvtColor((M.astype(np.uint8) * 255)[..., None].repeat(3, 2), cv2.COLOR_RGB2BGR)], axis=1)
            asset_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(asset_dir / f"loc_{saved:02d}.png"), panel)
            saved += 1

        if (i + 1) % 50 == 0:
            print(f"[{i+1}] used={n_used} mean_AUC={np.mean(aucs):.3f} mean_IoU={np.mean(ious):.3f} "
                  f"lm_surv={np.mean(lm_survival):.4f}")

    report = {
        "schema": "lidmark-tamper-loc.v1", "generated_at": int(time.time()),
        "project": "鉴源盾", "method": "LIDMark landmark-displacement tamper localization",
        "mechanism": ("嵌入真脸landmark→篡改→水印解出的(真)landmark vs 篡改图实测landmark 的逐点位移定位篡改区; "
                      "解决全局比特水印遮挡法 AUC≈0.5 的负结果"),
        "n": n_used, "grid": G, "device": str(dev), "seed": args.seed,
        "mean_localization_auc": round(float(np.mean(aucs)), 4) if aucs else None,
        "central_prior_control_auc": round(float(np.mean(uni_aucs)), 4) if uni_aucs else None,
        "displacement_gain_over_prior": (round(float(np.mean(aucs) - np.mean(uni_aucs)), 4)
                                          if aucs and uni_aucs else None),
        "control_note": ("central_prior_control_auc = 均匀权重(仅中心 landmark 先验)的 AUC; "
                         "mean_localization_auc - 该值 = '位移信号'的真实定位增益。"),
        "mean_iou_median_thr": round(float(np.mean(ious)), 4) if ious else None,
        "mean_landmark_watermark_displacement": round(float(np.mean(lm_survival)), 5) if lm_survival else None,
        "landmark_displacement_note": "水印解出landmark vs 嵌入真landmark 的平均位移([0,1]坐标),越小=水印几何越鲁棒",
        "occlusion_baseline": occ_aucs_note,
        "manipulation_type": "face_region_splice", "evidence_level": "real_image_splice_forgery",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ("n", "mean_localization_auc", "mean_iou_median_thr",
                                             "mean_landmark_watermark_displacement")}, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out/'summary.json'}  heatmaps={saved}")


if __name__ == "__main__":
    main()
