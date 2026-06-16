#!/usr/bin/env python3
"""WaveGuard 联合微调强化 JPEG 鲁棒性 —— 自行补全缺失的 STE 噪声层(修复 D1, 完整批训版).

原 WaveGuard 训练依赖 network/noise 模块(可微JPEG + 噪声层),该模块没拷到 box(缺代码)。
本脚本**自行补全**该模块核心:用**直通估计(STE)**实现噪声层 —— 前向=真实 cv2 退化(JPEG/
resize/noise/blur),反向=恒等(noised = clean + (degrade(clean.detach()) - clean.detach()),
梯度照常回流编码器)。这正是原训练对付"不可微JPEG"的标准做法。据此对 model_state_16 做
**编码器+双解码器联合微调**(真实 batch + train-mode BN, 稳定),保留保真度损失(encoder_w)维持 PSNR。
微调后在 LFW 上做 clean/jpeg50/jpeg70/jpeg90/resize/noise + PSNR 的"原始 vs 微调"对照并存档。
诚实标注:STE 噪声为重建实现(非原模块逐字节复原);deepfake-GAN 噪声分支因权重缺失未参与。

用法:
  PYTHONPATH=. python system/scripts/train_waveguard_jpeg_ste_finetune.py \
      --epochs 4 --train-images 6000 --batch-size 16 --bench-images 1000 --device cuda:3 \
      --out system/reports/waveguard_jpeg_ste_ft
"""
from __future__ import annotations

import argparse, json, sys, time, copy
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
    p = argparse.ArgumentParser(description="WaveGuard joint finetune w/ reconstructed STE noise (D1)")
    p.add_argument("--celeba-root", type=Path, default=DEFAULT_CELEBA)
    p.add_argument("--lfw-root", type=Path, default=DEFAULT_LFW)
    p.add_argument("--epochs", type=int, default=4)
    p.add_argument("--train-images", type=int, default=6000)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--bench-images", type=int, default=1000)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--fidelity-w", type=float, default=15.0, help="保真度损失权重(原训练 encoder_w=15)")
    p.add_argument("--msg-d-w", type=float, default=3.0)
    p.add_argument("--msg-t-w", type=float, default=1.0)
    p.add_argument("--device", default="cuda:3")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/waveguard_jpeg_ste_ft")
    return p.parse_args()


def main():
    args = parse_args()
    import os
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import torch

    from system.backend.model_adapters import WaveGuardAdapter, WAVEGUARD_CKPT
    a = WaveGuardAdapter.get()
    dev = a.device
    mr = float(a.cfg.message_range); MSG = int(a.cfg.message_length); IMG = a.IMG_SIZE
    print(f"[init] WaveGuard device={dev} msg={MSG} img={IMG} message_range={mr} batch={args.batch_size}")

    orig_state = {n: copy.deepcopy(getattr(a, n).state_dict()) for n in ("encoder", "decoder_t", "decoder_d")}

    def to256(path: Path) -> np.ndarray:
        return np.array(Image.open(path).convert("RGB").resize((IMG, IMG), Image.BICUBIC))

    def rgb_batch_to_yuv(rgb_list) -> "torch.Tensor":
        """list[(256,256,3) uint8 RGB] → (B,3,256,256) float[-1,1] (cv2 YUV, 与适配器一致)。"""
        ts = []
        for rgb in rgb_list:
            yuv = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2YUV).astype(np.float32)
            ts.append(torch.from_numpy(yuv / 127.5 - 1.0).permute(2, 0, 1))
        return torch.stack(ts, 0).to(dev)

    def yuv_batch_to_rgb(yuv_t) -> list:
        out = []
        arr = yuv_t.detach().cpu().permute(0, 2, 3, 1).numpy()
        for i in range(arr.shape[0]):
            yuv = np.clip((arr[i] + 1.0) * 127.5, 0, 255).astype(np.uint8)
            out.append(cv2.cvtColor(yuv, cv2.COLOR_YUV2RGB))
        return out

    def encode_grad(yuv):
        """可微编码 (B,3,256,256)→(watermarked_yuv[grad], cover_u, msg_bits)。"""
        B = yuv.shape[0]
        bits = np.random.default_rng().integers(0, 2, size=(B, MSG)).astype(np.uint8)
        msg_t = torch.tensor((bits.astype(np.float32) * 2 - 1) * mr, dtype=torch.float32, device=dev)
        y, u, v = yuv[:, [0]], yuv[:, [1]], yuv[:, [2]]
        lp, hp = a.DTCWT.images_U_dtcwt_with_low(u)
        sel = torch.index_select(hp[1], 2, a.indices_enc)[:, :, :, :, :, 0].squeeze(1)
        emb = a.encoder(sel, msg_t).unsqueeze(1)
        hp[1][:, :, a.indices_enc, :, :, 0] = emb
        u_emb = a.DTCWT.dtcwt_images_U(lp, hp)
        wm_yuv = torch.cat([y, u_emb, v], dim=1).clamp(-1, 1)
        return wm_yuv, u, msg_t, bits

    def real_degrade(rgb_u8, attack, r):
        if attack == "clean":
            return rgb_u8
        if attack.startswith("jpeg"):
            q = int(attack[4:])
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
            return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        if attack == "resize":
            h, w = rgb_u8.shape[:2]
            s = cv2.resize(rgb_u8, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
            return cv2.resize(s, (w, h), interpolation=cv2.INTER_LINEAR)
        if attack == "noise":
            return np.clip(rgb_u8.astype(np.float32) + r.normal(0, 3.0, rgb_u8.shape), 0, 255).astype(np.uint8)
        if attack == "blur":
            return cv2.GaussianBlur(rgb_u8, (5, 5), 1.2)
        return rgb_u8

    def ste_noise(wm_yuv, attacks, r):
        """STE 批: 每图独立采样攻击。前向=真实退化, 反向=恒等。"""
        wm_rgb = yuv_batch_to_rgb(wm_yuv)
        deg_rgb = [real_degrade(wm_rgb[i], attacks[i], r) for i in range(len(wm_rgb))]
        deg_yuv = rgb_batch_to_yuv(deg_rgb)
        return wm_yuv + (deg_yuv - wm_yuv.detach())

    def decode_paths(noised_yuv):
        u = noised_yuv[:, [1]]
        _, hp = a.DTCWT.images_U_dtcwt_with_low(u)
        sel_t = torch.index_select(hp[1], 2, a.indices_dec_t)[:, :, :, :, :, 0].squeeze(1)
        sel_d = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
        return a.decoder_t(sel_t), a.decoder_d(sel_d)

    rng = np.random.default_rng(args.seed)
    train_paths = sorted(p for p in args.celeba_root.rglob("*")
                         if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.train_images]
    assert train_paths, f"no celeba under {args.celeba_root}"
    print(f"[data] train={len(train_paths)}")
    mse = torch.nn.MSELoss()
    ATK_POOL = (["clean"] * 5 + ["jpeg35", "jpeg40", "jpeg45", "jpeg50", "jpeg55", "jpeg60"] * 2
                + ["resize"] * 2 + ["noise"] * 2 + ["blur"])

    # train-mode BN (真实 batch → 稳定统计量), 全部权重可训练
    for m in (a.encoder, a.decoder_t, a.decoder_d):
        m.train()
        for p_ in m.parameters():
            p_.requires_grad_(True)
    opt = torch.optim.Adam(list(a.encoder.parameters()) + list(a.decoder_t.parameters())
                           + list(a.decoder_d.parameters()), lr=args.lr)
    B = args.batch_size
    t0 = time.time()
    for ep in range(1, args.epochs + 1):
        order = rng.permutation(len(train_paths)); rl = 0.0; fl = 0.0; nb = 0
        for bs in range(0, len(order) - B + 1, B):
            idxs = order[bs:bs + B]
            rgb_list = [to256(train_paths[i]) for i in idxs]
            yuv = rgb_batch_to_yuv(rgb_list)
            wm_yuv, cover_u, msg_t, _ = encode_grad(yuv)
            attacks = [ATK_POOL[int(rng.integers(len(ATK_POOL)))] for _ in range(B)]
            noised = ste_noise(wm_yuv, attacks, rng)
            out_t, out_d = decode_paths(noised)
            loss_fid = mse(wm_yuv[:, [1]], cover_u)
            loss = (args.msg_d_w * mse(out_d, msg_t) + args.msg_t_w * mse(out_t, msg_t)
                    + args.fidelity_w * loss_fid)
            opt.zero_grad(); loss.backward(); opt.step()
            rl += loss.item(); fl += loss_fid.item(); nb += 1
            if nb % 100 == 0:
                print(f"  [ep{ep}] batch {nb} loss={rl/nb:.5f} fid={fl/nb:.5f} elapsed={(time.time()-t0)/60:.1f}min")
        print(f"[epoch {ep}/{args.epochs}] mean_loss={rl/max(nb,1):.5f} mean_fid={fl/max(nb,1):.5f}")
    ft_state = {n: copy.deepcopy(getattr(a, n).state_dict()) for n in ("encoder", "decoder_t", "decoder_d")}

    # ── 对照基准 (LFW, eval 模式): 原始 vs 微调, 全攻击 + PSNR ────────────────────
    from skimage.metrics import peak_signal_noise_ratio, structural_similarity
    bench_paths = sorted(p for p in args.lfw_root.rglob("*")
                         if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.bench_images]
    attacks_b = ["clean", "jpeg50", "jpeg70", "jpeg90", "resize", "noise"]

    def load(state):
        for n in ("encoder", "decoder_t", "decoder_d"):
            getattr(a, n).load_state_dict(state[n]); getattr(a, n).eval()

    def bench(state, label):
        load(state)
        res = {atk: [] for atk in attacks_b}; psnrs = []; ssims = []
        rb = np.random.default_rng(args.seed + 7)
        for bs in range(0, len(bench_paths), B):
            chunk = bench_paths[bs:bs + B]
            rgb_list = [to256(p) for p in chunk]
            yuv = rgb_batch_to_yuv(rgb_list)
            with torch.no_grad():
                wm_yuv, _, _, bits = encode_grad(yuv)
            wm_rgb = yuv_batch_to_rgb(wm_yuv)
            for i in range(len(chunk)):
                psnrs.append(float(peak_signal_noise_ratio(rgb_list[i], wm_rgb[i], data_range=255)))
                ssims.append(float(structural_similarity(rgb_list[i], wm_rgb[i], channel_axis=2, data_range=255)))
            for atk in attacks_b:
                deg = [real_degrade(wm_rgb[i], atk, rb) for i in range(len(chunk))]
                with torch.no_grad():
                    yd = rgb_batch_to_yuv(deg); u = yd[:, [1]]
                    _, hp = a.DTCWT.images_U_dtcwt_with_low(u)
                    sel_d = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
                    preds = (a.decoder_d(sel_d).cpu().numpy() > 0).astype(np.uint8)
                for i in range(len(chunk)):
                    res[atk].append(float((preds[i] == bits[i]).mean()))
        summ = {atk: {"mean_bit_accuracy": round(float(np.mean(res[atk])), 4),
                      "success_rate@0.9": round(float(np.mean(np.array(res[atk]) >= 0.9)), 4)}
                for atk in attacks_b}
        summ["_psnr"] = round(float(np.mean(psnrs)), 2); summ["_ssim"] = round(float(np.mean(ssims)), 4)
        print(f"[bench:{label}] PSNR={summ['_psnr']} " + " ".join(
            f"{atk}={summ[atk]['mean_bit_accuracy']:.3f}/{summ[atk]['success_rate@0.9']:.3f}" for atk in attacks_b))
        return summ

    print("\n[bench] LFW 原始 vs 微调:")
    b_orig = bench(orig_state, "orig")
    b_ft = bench(ft_state, "finetuned")

    args.out.mkdir(parents=True, exist_ok=True)
    full = torch.load(str(WAVEGUARD_CKPT), map_location="cpu", weights_only=True)
    for sub in ("encoder", "decoder_t", "decoder_d"):
        for k, v in ft_state[sub].items():
            full[f"{sub}.{k}"] = v.cpu()
    torch.save(full, args.out / "model_state_jpegste_ft.pth")

    report = {
        "schema": "waveguard-jpeg-ste-ft.v2", "generated_at": int(time.time()),
        "project": "鉴源盾", "method": "WaveGuard",
        "approach": "joint encoder+decoder finetune, batched train-mode BN, reconstructed STE noise (forward=real cv2, backward=identity)",
        "honest_note": ("STE 噪声层为自行重建(非原 network/noise 逐字节复原); deepfake-GAN 噪声分支因权重缺失未参与; "
                        "训练聚焦信号级(JPEG/resize/noise/blur)鲁棒性; 保真度损失维持 PSNR。"),
        "train_images": len(train_paths), "epochs": args.epochs, "batch_size": B,
        "loss_weights": {"fidelity": args.fidelity_w, "msg_d": args.msg_d_w, "msg_t": args.msg_t_w},
        "bench_images": len(bench_paths), "device": str(dev), "seed": args.seed,
        "lfw_orig": b_orig, "lfw_finetuned": b_ft,
        "saved_checkpoint": str(args.out / "model_state_jpegste_ft.pth"),
        "elapsed_seconds": round(time.time() - t0, 1),
    }
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({"lfw_orig": b_orig, "lfw_finetuned": b_ft}, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out/'summary.json'}")


if __name__ == "__main__":
    main()
