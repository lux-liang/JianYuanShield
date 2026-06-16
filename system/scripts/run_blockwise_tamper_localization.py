#!/usr/bin/env python3
"""分块独立水印 → 篡改定位(架构改动, 攻克遮挡/landmark法的失败).

思路:全局消息水印无法定位(整体存活或整体降级)。改为**每个空间块嵌入独立水印**(各块各自的随机消息),
解码时逐块解码→**逐块比特准确率图**;被篡改的块其自身水印被破坏→该块 bit-acc 掉→直接定位篡改区。
天然避开"中心先验"假象:未篡改块无论在什么位置 bit-acc 都高(对照=clean 各块 acc 应均匀高),
仅被篡改块掉→AUC 测的是真定位。

用 HiDDeN(小分辨率鲁棒、CNN 几何亦稳)逐块嵌入。

用法:
  PYTHONPATH=. python system/scripts/run_blockwise_tamper_localization.py \
      --grid 4 --num-images 200 --device cuda:4 --out system/reports/blockwise_tamper_loc
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np, cv2
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
DEFAULT_HOST = Path("/data1/luxliang/datasets/deepfake_images_extracted/Real")
IMG = 256


def parse_args():
    p = argparse.ArgumentParser(description="Block-wise watermark tamper localization (HiDDeN)")
    p.add_argument("--model", default="hidden", choices=["hidden", "kadnet"])
    p.add_argument("--host-root", type=Path, default=DEFAULT_HOST)
    p.add_argument("--donor-root", type=Path, default=DEFAULT_HOST)
    p.add_argument("--grid", type=int, default=4, help="GxG 分块(256/G px 每块)")
    p.add_argument("--num-images", type=int, default=200)
    p.add_argument("--device", default="cuda:4")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--save-heatmaps", type=int, default=8)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/blockwise_tamper_loc")
    return p.parse_args()


def numpy_auc(scores, labels):
    s = np.asarray(scores, float); l = np.asarray(labels, int)
    pos = s[l == 1]; neg = s[l == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    _, inv, cnt = np.unique(s, return_inverse=True, return_counts=True)
    csum = np.cumsum(cnt); avg = (csum - cnt + csum + 1) / 2.0
    ranks = avg[inv]
    return float((ranks[l == 1].sum() - pos.size * (pos.size + 1) / 2.0) / (pos.size * neg.size))


def main():
    args = parse_args()
    import os; os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import importlib
    reg = {"hidden": ("system.evaluation.adapters.hidden_adapter", "HiDDeNAdapter"),
           "kadnet": ("system.evaluation.adapters.kadnet_adapter", "KADNetAdapter")}
    mod, cls = reg[args.model]
    ad = getattr(importlib.import_module(mod), cls)()
    if not ad.available:
        print(f"{args.model} unavailable: {ad.blocker}", file=sys.stderr); sys.exit(1)
    MSG = ad.message_length; G = args.grid; bs = IMG // G
    print(f"[init] {args.model} msg_len={MSG} grid={G}x{G} block={bs}px")

    def to256(p): return np.array(Image.open(p).convert("RGB").resize((IMG, IMG), Image.BICUBIC))

    def face_mask(h, w):
        m = np.zeros((h, w), np.uint8)
        cv2.ellipse(m, (w // 2, int(0.45 * h)), (int(0.27 * min(h, w)), int(0.32 * min(h, w))), 0, 0, 360, 255, -1)
        return m > 0

    host_paths = sorted(p for p in args.host_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    donor_paths = sorted(p for p in args.donor_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    rng = np.random.default_rng(args.seed)

    aucs = []; clean_block_acc_all = []; tampered_clean_block_acc = []; tampered_inmask_block_acc = []
    ious = []; saved = 0; n = 0; t0 = time.time()
    asset = args.out / "heatmaps"

    for hi, hp in enumerate(host_paths):
        if n >= args.num_images:
            break
        host = to256(hp)
        msgs = {}  # (i,j)->bits
        wm = host.copy()
        for i in range(G):
            for j in range(G):
                blk = host[i*bs:(i+1)*bs, j*bs:(j+1)*bs]
                m = rng.integers(0, 2, size=MSG).astype(np.uint8); msgs[(i, j)] = m
                wm[i*bs:(i+1)*bs, j*bs:(j+1)*bs] = ad.encode(blk, m).image
        # clean 对照: 各块 acc(应均匀高)
        clean_acc = np.zeros((G, G), np.float32)
        for i in range(G):
            for j in range(G):
                b = ad.decode(wm[i*bs:(i+1)*bs, j*bs:(j+1)*bs]).bits
                clean_acc[i, j] = float((b == msgs[(i, j)]).mean())
        clean_block_acc_all.append(clean_acc.mean())

        # 篡改: 拼入 donor 人脸区域
        dp = donor_paths[int(rng.integers(len(donor_paths)))]
        if dp == hp: dp = donor_paths[(int(rng.integers(len(donor_paths))) + 1) % len(donor_paths)]
        donor = to256(dp); M = face_mask(IMG, IMG)
        tampered = wm.copy(); tampered[M] = donor[M]

        score = np.zeros((G, G), np.float32); true = np.zeros((G, G), np.uint8); tamp_acc = np.zeros((G, G), np.float32)
        for i in range(G):
            for j in range(G):
                b = ad.decode(tampered[i*bs:(i+1)*bs, j*bs:(j+1)*bs]).bits
                acc = float((b == msgs[(i, j)]).mean()); tamp_acc[i, j] = acc
                score[i, j] = 1.0 - acc
                true[i, j] = 1 if M[i*bs:(i+1)*bs, j*bs:(j+1)*bs].mean() >= 0.5 else 0
        n += 1
        for i in range(G):
            for j in range(G):
                (tampered_inmask_block_acc if true[i, j] else tampered_clean_block_acc).append(tamp_acc[i, j])
        auc = numpy_auc(score.reshape(-1), true.reshape(-1))
        if not np.isnan(auc): aucs.append(auc)
        thr = float(np.median(score)); pred = (score >= max(thr, 1e-6)).astype(np.uint8)
        inter = int(((pred == 1) & (true == 1)).sum()); union = int(((pred == 1) | (true == 1)).sum())
        if union: ious.append(inter / union)

        if saved < args.save_heatmaps:
            hm = cv2.resize((score * 255).astype(np.uint8), (IMG, IMG), interpolation=cv2.INTER_NEAREST)
            hm = cv2.applyColorMap(hm, cv2.COLORMAP_JET)
            tm = cv2.resize((true * 255).astype(np.uint8), (IMG, IMG), interpolation=cv2.INTER_NEAREST)
            panel = np.concatenate([cv2.cvtColor(wm, cv2.COLOR_RGB2BGR), cv2.cvtColor(tampered, cv2.COLOR_RGB2BGR),
                                    hm, cv2.cvtColor(tm[..., None].repeat(3, 2), cv2.COLOR_RGB2BGR)], axis=1)
            asset.mkdir(parents=True, exist_ok=True); cv2.imwrite(str(asset / f"bw_{saved:02d}.png"), panel); saved += 1
        if (hi + 1) % 50 == 0:
            print(f"[{hi+1}] used={n} AUC={np.mean(aucs):.3f} clean_blk={np.mean(clean_block_acc_all):.3f} "
                  f"tamp_inmask={np.mean(tampered_inmask_block_acc):.3f} tamp_clean={np.mean(tampered_clean_block_acc):.3f}")

    report = {
        "schema": "blockwise-tamper-loc.v1", "generated_at": int(time.time()),
        "project": "鉴源盾", "model": args.model, "grid": G, "block_px": bs, "n": n,
        "mechanism": "每块独立水印→逐块bit-acc图→篡改块自身水印被破坏而掉→定位(避开中心先验)",
        "mean_localization_auc": round(float(np.mean(aucs)), 4) if aucs else None,
        "mean_iou_median_thr": round(float(np.mean(ious)), 4) if ious else None,
        "control_clean_block_acc_mean": round(float(np.mean(clean_block_acc_all)), 4),
        "tampered_inmask_block_acc_mean": round(float(np.mean(tampered_inmask_block_acc)), 4) if tampered_inmask_block_acc else None,
        "tampered_outmask_block_acc_mean": round(float(np.mean(tampered_clean_block_acc)), 4) if tampered_clean_block_acc else None,
        "interpretation": ("clean_block_acc 高且均匀=分块水印可用(对照); 篡改后 inmask块acc «  outmask块acc 即真定位; "
                           "AUC 由'篡改块自身水印被破坏'驱动,非中心先验。"),
        "device": args.device, "seed": args.seed,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ("n", "mean_localization_auc", "mean_iou_median_thr",
                                             "control_clean_block_acc_mean", "tampered_inmask_block_acc_mean",
                                             "tampered_outmask_block_acc_mean")}, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out/'summary.json'}")


if __name__ == "__main__":
    main()
