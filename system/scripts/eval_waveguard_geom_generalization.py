#!/usr/bin/env python3
"""核验 WaveGuard 几何微调是否**泛化到未训练的几何参数**(防"只记住训练用的 crop0.8/rotate5").

加载 all-attack 微调 checkpoint, 在 LFW 上测:
  训练过的几何参数: crop_center_0.8, rotate_5
  **未训练的几何参数(held-out)**: crop_center_0.7, crop_center_0.9, rotate_3, rotate_10, rotate_-5
若 held-out 几何也高 → 真几何鲁棒; 若仅训练参数高 → 参数特异性记忆(诚实标注)。
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np, cv2
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
DEFAULT_LFW = Path("/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown")
IMG = 256


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", type=Path, default=PROJECT_DIR / "system/reports/waveguard_allatk_ste_ft/model_state_jpegste_ft.pth")
    p.add_argument("--lfw-root", type=Path, default=DEFAULT_LFW)
    p.add_argument("--num-images", type=int, default=500)
    p.add_argument("--device", default="cuda:4")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/waveguard_geom_generalization")
    return p.parse_args()


def crop_ratio(rgb, ratio):
    h, w = rgb.shape[:2]; ch, cw = int(h * ratio), int(w * ratio); y0, x0 = (h - ch) // 2, (w - cw) // 2
    return cv2.resize(rgb[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_LINEAR)

def rotate_deg(rgb, deg):
    h, w = rgb.shape[:2]; M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(rgb, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

ATTACKS = {
    "clean": lambda x: x,
    "crop0.8_TRAINED": lambda x: crop_ratio(x, 0.8),
    "rotate5_TRAINED": lambda x: rotate_deg(x, 5),
    "crop0.7_heldout": lambda x: crop_ratio(x, 0.7),
    "crop0.9_heldout": lambda x: crop_ratio(x, 0.9),
    "rotate3_heldout": lambda x: rotate_deg(x, 3),
    "rotate10_heldout": lambda x: rotate_deg(x, 10),
    "rotate-5_heldout": lambda x: rotate_deg(x, -5),
}


def main():
    args = parse_args()
    import os; os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import torch
    from system.backend.model_adapters import WaveGuardAdapter
    a = WaveGuardAdapter.get()
    # 载入微调 checkpoint
    full = torch.load(str(args.ckpt), map_location=a.device, weights_only=True)
    def strip(pfx): return {k[len(pfx):]: v for k, v in full.items() if k.startswith(pfx)}
    a.encoder.load_state_dict(strip("encoder."), strict=False)
    a.decoder_t.load_state_dict(strip("decoder_t."), strict=False)
    a.decoder_d.load_state_dict(strip("decoder_d."), strict=False)
    a.encoder.eval(); a.decoder_t.eval(); a.decoder_d.eval()
    mr = float(a.cfg.message_range); MSG = int(a.cfg.message_length)
    print(f"[init] loaded ft ckpt {args.ckpt.name}")

    def encode(arr, bits):
        yuv = a._rgb_to_yuv_tensor(arr)
        msg = torch.tensor((bits.astype(np.float32) * 2 - 1) * mr, dtype=torch.float32, device=a.device).unsqueeze(0)
        with torch.no_grad():
            y, u, v = yuv[:, [0]], yuv[:, [1]], yuv[:, [2]]
            lp, hp = a.DTCWT.images_U_dtcwt_with_low(u)
            sel = torch.index_select(hp[1], 2, a.indices_enc)[:, :, :, :, :, 0].squeeze(1)
            hp[1][:, :, a.indices_enc, :, :, 0] = a.encoder(sel, msg).unsqueeze(1)
            wm = torch.cat([y, a.DTCWT.dtcwt_images_U(lp, hp), v], dim=1).clamp(-1, 1)
        return a._yuv_tensor_to_rgb(wm)

    def decode(arr):
        yuv = a._rgb_to_yuv_tensor(arr)
        with torch.no_grad():
            _, hp = a.DTCWT.images_U_dtcwt_with_low(yuv[:, [1]])
            sel = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
            return (a.decoder_d(sel).cpu().numpy()[0] > 0).astype(np.uint8)

    paths = sorted(p for p in args.lfw_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.num_images]
    rng = np.random.default_rng(args.seed)
    res = {k: [] for k in ATTACKS}
    t0 = time.time()
    for i, p in enumerate(paths):
        arr = np.array(Image.open(p).convert("RGB").resize((IMG, IMG), Image.BICUBIC))
        bits = rng.integers(0, 2, size=MSG).astype(np.uint8)
        wm = encode(arr, bits)
        for k, fn in ATTACKS.items():
            res[k].append(float((decode(fn(wm)) == bits).mean()))
        if (i + 1) % 100 == 0:
            print(f"[{i+1}/{len(paths)}] elapsed={(time.time()-t0)/60:.1f}min")
    summ = {k: {"mean_bit_accuracy": round(float(np.mean(v)), 4),
                "success_rate@0.9": round(float(np.mean(np.array(v) >= 0.9)), 4), "n": len(v)} for k, v in res.items()}
    report = {"schema": "waveguard-geom-generalization.v1", "generated_at": int(time.time()),
              "ckpt": str(args.ckpt), "n": len(paths), "device": args.device,
              "results": summ,
              "note": "_TRAINED=训练池含的几何参数; _heldout=未训练几何参数。held-out 也高则为真几何泛化。"}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(summ, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out/'summary.json'}")


if __name__ == "__main__":
    main()
