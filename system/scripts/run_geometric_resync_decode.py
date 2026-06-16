#!/usr/bin/env python3
"""几何攻击 解码端人脸 landmark 重同步(resync) —— 尝试解决 crop/rotate 几何失败.

思路(利用人脸域,无需重训):几何攻击(裁剪/旋转)破坏水印的空间对齐。解码前先用 face_alignment
检测被攻击图的 68 landmark,估计到**规范模板**(由大量干净脸的平均 landmark 求得)的相似变换,
把图 warp 回规范帧 → 近似撤销裁剪/旋转 → 再解码。对照"不重同步"基线,看几何 bit-acc 是否回升。

诚实caveat:水印嵌入在原脸帧,规范对齐只在原脸≈规范(正面居中)时近似撤销攻击;且 warp 引入二次重采样。
成败由实验给出,不预设结论。

用法:
  PYTHONPATH=. python system/scripts/run_geometric_resync_decode.py \
      --model kadnet --num-images 300 --device cuda:4 --out system/reports/geometric_resync
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

ADAPTERS = {
    "kadnet": ("system.evaluation.adapters.kadnet_adapter", "KADNetAdapter"),
    "waveguard": ("system.evaluation.adapters.waveguard_adapter", "WaveGuardModelAdapter"),
    "sepmark": ("system.evaluation.adapters.sepmark_adapter", "SepMarkModelAdapter"),
}
DEFAULT_LFW = Path("/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown")
IMG = 256


def parse_args():
    p = argparse.ArgumentParser(description="Geometric attack: decode-time face-landmark resync")
    p.add_argument("--model", default="kadnet", choices=sorted(ADAPTERS))
    p.add_argument("--image-root", type=Path, default=DEFAULT_LFW)
    p.add_argument("--num-images", type=int, default=300)
    p.add_argument("--template-images", type=int, default=150, help="求规范模板的干净脸数")
    p.add_argument("--attacks", nargs="+", default=["clean", "crop_center_0.8", "rotate_5"])
    p.add_argument("--device", default="cuda:4")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/geometric_resync")
    return p.parse_args()


def main():
    args = parse_args()
    import os
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import importlib
    from system.evaluation.attacks import apply_attack
    import face_alignment

    mod, cls = ADAPTERS[args.model]
    adapter = getattr(importlib.import_module(mod), cls)()
    if not adapter.available:
        print(f"{args.model} unavailable: {adapter.blocker}", file=sys.stderr); sys.exit(1)
    MSG = adapter.message_length
    print(f"[init] {args.model} msg_len={MSG} ckpt={adapter.checkpoint}")

    try:
        fa = face_alignment.FaceAlignment(face_alignment.LandmarksType.TWO_D, device=args.device, flip_input=False)
    except AttributeError:
        fa = face_alignment.FaceAlignment(face_alignment.LandmarksType._2D, device=args.device, flip_input=False)

    def lm(img):
        pr = fa.get_landmarks(img)
        return None if not pr else np.asarray(pr[0], dtype=np.float32)  # (68,2) px

    def to256(p):
        return np.array(Image.open(p).convert("RGB").resize((IMG, IMG), Image.BICUBIC))

    paths = sorted(p for p in args.image_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    rng = np.random.default_rng(args.seed)

    # ── 规范模板: 干净脸平均 landmark(像素, 256 帧) ──────────────────────────────
    acc = []; ti = 0
    for p in paths:
        if ti >= args.template_images:
            break
        L = lm(to256(p))
        if L is not None:
            acc.append(L); ti += 1
    canonical = np.mean(np.stack(acc, 0), 0).astype(np.float32)  # (68,2) px
    print(f"[template] built from {len(acc)} faces")

    def resync(img):
        """检测 landmark → 相似变换到规范模板 → warp 回规范帧。失败则原图返回。"""
        L = lm(img)
        if L is None:
            return img, False
        M, _ = cv2.estimateAffinePartial2D(L, canonical, method=cv2.LMEDS)
        if M is None:
            return img, False
        return cv2.warpAffine(img, M, (IMG, IMG), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101), True

    test_paths = paths[args.template_images: args.template_images + args.num_images]
    base = {a: [] for a in args.attacks}
    rsy = {a: [] for a in args.attacks}
    resync_ok = 0; n = 0
    t0 = time.time()
    for p in test_paths:
        arr = to256(p)
        if lm(arr) is None:
            continue
        n += 1
        bits = rng.integers(0, 2, size=MSG).astype(np.uint8)
        wm = adapter.encode(arr, bits).image
        for a in args.attacks:
            atk, _ = apply_attack(wm, a, image_id=p.stem, global_seed=args.seed) if a != "clean" else (wm, None)
            # baseline: 直接解码
            b = adapter.decode(atk).bits
            base[a].append(float((b == bits).mean()))
            # resync: 对齐后解码
            warped, ok = resync(atk)
            if ok:
                resync_ok += 1
            r = adapter.decode(warped).bits
            rsy[a].append(float((r == bits).mean()))
        if n % 50 == 0:
            print(f"[{n}] " + " ".join(
                f"{a}:base{np.mean(base[a]):.3f}/resync{np.mean(rsy[a]):.3f}" for a in args.attacks)
                + f"  elapsed={(time.time()-t0)/60:.1f}min")

    def summ(d):
        return {a: {"mean_bit_accuracy": round(float(np.mean(d[a])), 4),
                    "success_rate@0.9": round(float(np.mean(np.array(d[a]) >= 0.9)), 4),
                    "n": len(d[a])} for a in args.attacks}

    report = {
        "schema": "geometric-resync.v1", "generated_at": int(time.time()),
        "project": "鉴源盾", "model": args.model, "approach": "decode-time face-landmark resync to canonical template",
        "n": n, "device": args.device, "seed": args.seed,
        "baseline_no_resync": summ(base),
        "with_resync": summ(rsy),
        "resync_detect_rate": round(resync_ok / max(n * len(args.attacks), 1), 4),
        "honest_note": "水印嵌于原脸帧,规范对齐仅在原脸≈规范时近似撤销几何攻击;warp 引入二次重采样。成败以数据为准。",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"summary_{args.model}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({"baseline": report["baseline_no_resync"], "resync": report["with_resync"]},
                     indent=2, ensure_ascii=False))
    print(f"[done] → {args.out}/summary_{args.model}.json")


if __name__ == "__main__":
    main()
