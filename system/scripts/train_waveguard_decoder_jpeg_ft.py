#!/usr/bin/env python3
"""WaveGuard JPEG 鲁棒性强化 —— 仅微调 detector 解码器(自给自足, 无需原训练管线).

背景: WaveGuard 原训练的 network/noise 模块(可微JPEG+deepfake噪声层)没拷到 box(缺代码),
无法复跑原管线. 但 jpeg50 弱点(LFW: bit-acc 89% / success@0.9 仅 37%)本质是**解码器**
对 JPEG 压缩残差的鲁棒性不足. 因此采用自洽方案:
  冻结编码器 → 生成水印图 → 真实 cv2 JPEG(Q∈[jpeg-min,jpeg-max]) → 只微调 decoder_d
(编码器不动, JPEG 作用在解码器输入上是固定退化, 无需可微JPEG). 诚实标注为"解码器适配", 非全模型重训.
微调后**同进程**在 LFW 上重测 clean/jpeg50/jpeg70/resize/noise, 与原 89%/37% 对照, 并存权重.

用法:
  PYTHONPATH=. python system/scripts/train_waveguard_decoder_jpeg_ft.py \
      --epochs 4 --train-images 6000 --bench-images 1000 --device cuda:3 \
      --out system/reports/waveguard_decoder_jpeg_ft
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

DEFAULT_CELEBA = Path("/home/luxliang/JianYuanShield/datasets/celeba_hq_kadnet/train_128")
DEFAULT_LFW = Path("/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown")


def parse_args():
    p = argparse.ArgumentParser(description="WaveGuard decoder-only JPEG hardening (D1)")
    p.add_argument("--celeba-root", type=Path, default=DEFAULT_CELEBA)
    p.add_argument("--lfw-root", type=Path, default=DEFAULT_LFW)
    p.add_argument("--epochs", type=int, default=4)
    p.add_argument("--train-images", type=int, default=6000)
    p.add_argument("--bench-images", type=int, default=1000)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--accum", type=int, default=16, help="梯度累积步数(等效 batch)")
    p.add_argument("--jpeg-min", type=int, default=40)
    p.add_argument("--jpeg-max", type=int, default=60)
    p.add_argument("--clean-prob", type=float, default=0.3, help="训练时保留 clean 样本比例(防遗忘)")
    p.add_argument("--device", default="cuda:3")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/waveguard_decoder_jpeg_ft")
    return p.parse_args()


def main():
    args = parse_args()
    import os
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import torch

    from system.backend.model_adapters import WaveGuardAdapter
    a = WaveGuardAdapter.get()
    dev = a.device
    mr = float(a.cfg.message_range)
    MSG = int(a.cfg.message_length)
    IMG = a.IMG_SIZE
    print(f"[init] WaveGuard loaded device={dev} msg_len={MSG} img={IMG} message_range={mr}")

    # 冻结编码器, 微调 detector 解码器(eval 模式冻结 BN 统计量, B=1 累积更稳)
    for p_ in a.encoder.parameters():
        p_.requires_grad_(False)
    for p_ in a.decoder_t.parameters():
        p_.requires_grad_(False)
    for p_ in a.decoder_d.parameters():
        p_.requires_grad_(True)
    a.encoder.eval(); a.decoder_t.eval(); a.decoder_d.eval()
    opt = torch.optim.Adam([p_ for p_ in a.decoder_d.parameters() if p_.requires_grad], lr=args.lr)

    # 备份原始 decoder_d 权重(用于"原始 vs 微调"对照基准)
    import copy
    orig_dec_d_state = copy.deepcopy(a.decoder_d.state_dict())

    def to256(path: Path) -> np.ndarray:
        return np.array(Image.open(path).convert("RGB").resize((IMG, IMG), Image.BICUBIC))

    def encode_wm(arr256: np.ndarray, bits: np.ndarray) -> np.ndarray:
        """冻结编码器嵌入水印, 返回水印图 uint8(无梯度)。"""
        yuv = a._rgb_to_yuv_tensor(arr256)
        msg_vals = (bits.astype(np.float32) * 2 - 1) * mr
        msg_t = torch.tensor(msg_vals, dtype=torch.float32, device=dev).unsqueeze(0)
        with torch.no_grad():
            y, u, v = yuv[:, [0]], yuv[:, [1]], yuv[:, [2]]
            lp, hp = a.DTCWT.images_U_dtcwt_with_low(u)
            sel = torch.index_select(hp[1], 2, a.indices_enc)[:, :, :, :, :, 0].squeeze(1)
            emb = a.encoder(sel, msg_t).unsqueeze(1)
            hp[1][:, :, a.indices_enc, :, :, 0] = emb
            u_emb = a.DTCWT.dtcwt_images_U(lp, hp)
            wm_yuv = torch.cat([y, u_emb, v], dim=1).clamp(-1, 1)
        return a._yuv_tensor_to_rgb(wm_yuv)

    def decode_logits(arr256: np.ndarray, grad: bool):
        """detector 解码: 返回 (1,MSG) logits。grad=True 时对 decoder_d 求导。"""
        yuv = a._rgb_to_yuv_tensor(arr256)
        with torch.no_grad():
            u = yuv[:, [1]]
            _, hp = a.DTCWT.images_U_dtcwt_with_low(u)
            sel_d = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
        sel_d = sel_d.detach()
        if grad:
            return a.decoder_d(sel_d)
        with torch.no_grad():
            return a.decoder_d(sel_d)

    def jpeg(arr: np.ndarray, q: int) -> np.ndarray:
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, int(q)])
        return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)

    rng = np.random.default_rng(args.seed)
    train_paths = sorted(p for p in args.celeba_root.rglob("*")
                         if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.train_images]
    assert train_paths, f"no celeba images under {args.celeba_root}"
    print(f"[data] train images={len(train_paths)}")
    mse = torch.nn.MSELoss()

    # ── 微调 ────────────────────────────────────────────────────────────────
    t0 = time.time()
    step = 0
    opt.zero_grad()
    for ep in range(1, args.epochs + 1):
        order = rng.permutation(len(train_paths))
        run_loss = 0.0; cnt = 0
        for j, idx in enumerate(order):
            arr = to256(train_paths[idx])
            bits = rng.integers(0, 2, size=MSG).astype(np.uint8)
            wm = encode_wm(arr, bits)
            if rng.random() < args.clean_prob:
                atk = wm
            else:
                atk = jpeg(wm, int(rng.integers(args.jpeg_min, args.jpeg_max + 1)))
            out = decode_logits(atk, grad=True)            # (1,MSG) 带梯度
            target = torch.tensor((bits.astype(np.float32) * 2 - 1) * mr,
                                  dtype=torch.float32, device=dev).unsqueeze(0)
            loss = mse(out, target) / args.accum
            loss.backward()
            run_loss += loss.item() * args.accum; cnt += 1
            step += 1
            if step % args.accum == 0:
                opt.step(); opt.zero_grad()
            if (j + 1) % 1000 == 0:
                print(f"  [ep{ep}] {j+1}/{len(order)} loss={run_loss/max(cnt,1):.5f} "
                      f"elapsed={(time.time()-t0)/60:.1f}min")
        print(f"[epoch {ep}/{args.epochs}] mean_loss={run_loss/max(cnt,1):.5f}")
    opt.step(); opt.zero_grad()
    ft_dec_d_state = copy.deepcopy(a.decoder_d.state_dict())

    # ── 对照基准: 在 LFW 上比较 原始 decoder_d vs 微调 decoder_d ────────────────
    bench_paths = sorted(p for p in args.lfw_root.rglob("*")
                         if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.bench_images]
    attacks = ["clean", "jpeg50", "jpeg70", "resize", "noise"]

    def attack_img(arr: np.ndarray, name: str, r) -> np.ndarray:
        if name == "clean":
            return arr
        if name.startswith("jpeg"):
            return jpeg(arr, int(name[4:]))
        if name == "resize":
            h, w = arr.shape[:2]
            s = cv2.resize(arr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
            return cv2.resize(s, (w, h), interpolation=cv2.INTER_LINEAR)
        if name == "noise":
            return np.clip(arr.astype(np.float32) + r.normal(0, 3.0, arr.shape), 0, 255).astype(np.uint8)
        return arr

    def bench(dec_state, label):
        a.decoder_d.load_state_dict(dec_state)
        a.decoder_d.eval()
        res = {atk: [] for atk in attacks}
        rb = np.random.default_rng(args.seed + 7)
        for pth in bench_paths:
            arr = to256(pth)
            bits = rb.integers(0, 2, size=MSG).astype(np.uint8)
            wm = encode_wm(arr, bits)
            for atk in attacks:
                im = attack_img(wm, atk, rb)
                logits = decode_logits(im, grad=False)
                pred = (logits.detach().cpu().numpy()[0] > 0).astype(np.uint8)
                res[atk].append(float((pred == bits).mean()))
        summary = {}
        for atk in attacks:
            v = np.array(res[atk])
            summary[atk] = {"mean_bit_accuracy": round(float(v.mean()), 4),
                            "success_rate@0.9": round(float((v >= 0.9).mean()), 4),
                            "n": int(v.size)}
        print(f"[bench:{label}] " + "  ".join(
            f"{atk}={summary[atk]['mean_bit_accuracy']:.3f}/{summary[atk]['success_rate@0.9']:.3f}"
            for atk in attacks))
        return summary

    print("\n[bench] LFW 对照(bit-acc/success@0.9):")
    bench_orig = bench(orig_dec_d_state, "orig_decoder")
    bench_ft = bench(ft_dec_d_state, "finetuned_decoder")

    # ── 存档: 微调 decoder_d + 合并完整 state_dict(编码器/tracer 不变) ────────────
    args.out.mkdir(parents=True, exist_ok=True)
    torch.save(ft_dec_d_state, args.out / "decoder_d_jpeg_ft.pth")
    # 合并: 读原始全量 state_dict, 替换 decoder_d.*
    from system.backend.model_adapters import WAVEGUARD_CKPT
    full = torch.load(str(WAVEGUARD_CKPT), map_location="cpu", weights_only=True)
    for k, v in ft_dec_d_state.items():
        full[f"decoder_d.{k}"] = v.cpu()
    torch.save(full, args.out / "model_state_jpegft.pth")

    report = {
        "schema": "waveguard-decoder-jpeg-ft.v1",
        "generated_at": int(time.time()),
        "project": "鉴源盾", "method": "WaveGuard",
        "approach": "decoder_d_only_finetune (encoder frozen; real cv2 JPEG on decoder input; 自给自足)",
        "honest_note": "仅微调 detector 解码器以增强 JPEG 鲁棒性, 非全模型重训(原训练 network/noise 模块缺失). 编码器/PSNR/SSIM不变。",
        "train_images": len(train_paths), "epochs": args.epochs,
        "jpeg_range": [args.jpeg_min, args.jpeg_max], "clean_prob": args.clean_prob,
        "bench_images": len(bench_paths), "device": str(dev), "seed": args.seed,
        "lfw_orig_decoder": bench_orig,
        "lfw_finetuned_decoder": bench_ft,
        "saved_decoder": str(args.out / "decoder_d_jpeg_ft.pth"),
        "saved_full_checkpoint": str(args.out / "model_state_jpegft.pth"),
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({"lfw_orig_decoder": bench_orig, "lfw_finetuned_decoder": bench_ft}, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out/'summary.json'}")


if __name__ == "__main__":
    main()
