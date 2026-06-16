#!/usr/bin/env python3
"""跨模型几何泛化核验 —— 谁是真·几何鲁棒(参数泛化), 谁是参数记忆/失败.

对任意水印适配器, 在 LFW 上测**多组 crop 比例 / rotate 角度**(含训练外参数)的 bit-acc。
真几何鲁棒(如 HiDDeN, CNN 编码器学到空间不变性)→ 各参数均高且泛化;
DTCWT 子带水印(KAD/WaveGuard)→ 几何失败(任何空间重采样破坏子带水印)。
据此确认"系统级几何鲁棒由 HiDDeN 覆盖"是否站得住(而非又一次参数记忆)。

用法:
  PYTHONPATH=. python system/scripts/eval_geometric_generalization.py --model hidden --num-images 500 --device cuda:4
"""
from __future__ import annotations
import argparse, json, sys, time, importlib
from pathlib import Path
import numpy as np, cv2
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
ADAPTERS = {
    "kadnet": ("system.evaluation.adapters.kadnet_adapter", "KADNetAdapter"),
    "waveguard": ("system.evaluation.adapters.waveguard_adapter", "WaveGuardModelAdapter"),
    "sepmark": ("system.evaluation.adapters.sepmark_adapter", "SepMarkModelAdapter"),
    "hidden": ("system.evaluation.adapters.hidden_adapter", "HiDDeNAdapter"),
}
DEFAULT_LFW = Path("/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="hidden", choices=sorted(ADAPTERS))
    p.add_argument("--image-root", type=Path, default=DEFAULT_LFW)
    p.add_argument("--num-images", type=int, default=500)
    p.add_argument("--device", default="cuda:4")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/geometric_generalization")
    return p.parse_args()


def crop_r(rgb, ratio):
    h, w = rgb.shape[:2]; ch, cw = int(h * ratio), int(w * ratio); y0, x0 = (h - ch) // 2, (w - cw) // 2
    return cv2.resize(rgb[y0:y0 + ch, x0:x0 + cw], (w, h), interpolation=cv2.INTER_LINEAR)

def rot(rgb, d):
    h, w = rgb.shape[:2]; M = cv2.getRotationMatrix2D((w / 2, h / 2), d, 1.0)
    return cv2.warpAffine(rgb, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

ATTACKS = {
    "clean": lambda x: x,
    "crop_0.9": lambda x: crop_r(x, 0.9), "crop_0.8": lambda x: crop_r(x, 0.8), "crop_0.7": lambda x: crop_r(x, 0.7),
    "rotate_3": lambda x: rot(x, 3), "rotate_5": lambda x: rot(x, 5), "rotate_10": lambda x: rot(x, 10),
    "rotate_-5": lambda x: rot(x, -5), "rotate_-10": lambda x: rot(x, -10),
}


def main():
    args = parse_args()
    import os; os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    mod, cls = ADAPTERS[args.model]
    ad = getattr(importlib.import_module(mod), cls)()
    if not ad.available:
        print(f"{args.model} unavailable: {ad.blocker}", file=sys.stderr); sys.exit(1)
    MSG = ad.message_length
    print(f"[init] {args.model} msg_len={MSG}")

    paths = sorted(p for p in args.image_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.num_images]
    rng = np.random.default_rng(args.seed)
    res = {k: [] for k in ATTACKS}
    t0 = time.time()
    for i, p in enumerate(paths):
        arr = np.array(Image.open(p).convert("RGB"))
        bits = rng.integers(0, 2, size=MSG).astype(np.uint8)
        wm = ad.encode(arr, bits).image
        for k, fn in ATTACKS.items():
            res[k].append(float((ad.decode(fn(wm)).bits == bits).mean()))
        if (i + 1) % 100 == 0:
            print(f"[{i+1}/{len(paths)}] elapsed={(time.time()-t0)/60:.1f}min")
    summ = {k: {"mean_bit_accuracy": round(float(np.mean(v)), 4),
                "success_rate@0.9": round(float(np.mean(np.array(v) >= 0.9)), 4), "n": len(v)} for k, v in res.items()}
    report = {"schema": "geometric-generalization.v1", "generated_at": int(time.time()),
              "model": args.model, "checkpoint": ad.checkpoint, "n": len(paths), "device": args.device,
              "results": summ,
              "note": "多组 crop 比例/rotate 角度; 真几何鲁棒=各参数均高且泛化。"}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"summary_{args.model}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(summ, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out}/summary_{args.model}.json")


if __name__ == "__main__":
    main()
