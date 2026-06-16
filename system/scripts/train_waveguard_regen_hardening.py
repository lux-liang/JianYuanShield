#!/usr/bin/env python3
"""WaveGuard 对抗式"AI 再生成"硬化 —— 让水印扛住生成式再生成攻击(冲一等奖的前沿贡献).

现代去水印的核心威胁是**生成式再生成**(把图过一遍 AE/扩散重生成,水印随像素被重写)。本轮基线里
除 KAD 外各模型再生成后成功率≈0。本脚本做对抗式硬化:把**自训练 AE 再生成**加入 STE 噪声池
(前向=AE(水印图)重建, 反向=恒等),编码器+双解码器联合训练,学到**再生成可存活**的嵌入。
保真度损失维持 PSNR; 同时保留信号级攻击(jpeg/resize/noise)防遗忘。

**防过拟合护栏(关键)**: 训练只用 AE#1; 验收同时报 AE#1(训练过) 与 **AE#2(架构不同 latent=192, held-out)**,
若 held-out AE#2 上也存活 → 真·再生成鲁棒(学到对抗生成式重写的嵌入), 而非记忆单一 AE。

用法:
  PYTHONPATH=. python system/scripts/train_waveguard_regen_hardening.py \
      --base-ckpt system/reports/waveguard_allatk_ste_ft/model_state_jpegste_ft.pth \
      --ae1 system/reports/face_autoencoder/checkpoints/best.pt \
      --ae2 system/reports/face_autoencoder_heldout/checkpoints/best.pt \
      --epochs 6 --train-images 7000 --device cuda:4 --out system/reports/waveguard_regen_hardened
"""
from __future__ import annotations
import argparse, json, sys, time, copy
from pathlib import Path
import numpy as np, cv2
from PIL import Image

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
DEFAULT_CELEBA = Path("/home/luxliang/JianYuanShield/datasets/celeba_hq_kadnet/train_128")
DEFAULT_LFW = Path("/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown")
IMG = 256


def parse_args():
    p = argparse.ArgumentParser(description="WaveGuard adversarial regeneration hardening")
    p.add_argument("--base-ckpt", type=Path, default=PROJECT_DIR / "system/reports/waveguard_allatk_ste_ft/model_state_jpegste_ft.pth")
    p.add_argument("--ae1", type=Path, default=PROJECT_DIR / "system/reports/face_autoencoder/checkpoints/best.pt")
    p.add_argument("--ae2", type=Path, default=PROJECT_DIR / "system/reports/face_autoencoder_heldout/checkpoints/best.pt")
    p.add_argument("--ae3", type=Path, default=PROJECT_DIR / "system/reports/face_autoencoder_heldout3/checkpoints/best.pt",
                   help="held-out AE(训练不用,仅验收泛化)")
    p.add_argument("--ae1-latent", type=int, default=128)
    p.add_argument("--ae2-latent", type=int, default=192)
    p.add_argument("--ae3-latent", type=int, default=160)
    p.add_argument("--celeba-root", type=Path, default=DEFAULT_CELEBA)
    p.add_argument("--lfw-root", type=Path, default=DEFAULT_LFW)
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--train-images", type=int, default=7000)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--bench-images", type=int, default=600)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--fidelity-w", type=float, default=35.0, help="强保真度锚定防 PSNR 崩塌")
    p.add_argument("--device", default="cuda:4")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/waveguard_regen_hardened")
    return p.parse_args()


def build_ae(torch, nn, latent_ch):
    class ConvBlock(nn.Module):
        def __init__(s, i, o, k=3, st=1, p=1):
            super().__init__(); s.block = nn.Sequential(nn.Conv2d(i, o, k, st, p, bias=False), nn.BatchNorm2d(o), nn.LeakyReLU(0.1, True))
        def forward(s, x): return s.block(x)
    class UpBlock(nn.Module):
        def __init__(s, i, o):
            super().__init__(); s.block = nn.Sequential(nn.ConvTranspose2d(i, o, 4, 2, 1, bias=False), nn.BatchNorm2d(o), nn.ReLU(True))
        def forward(s, x): return s.block(x)
    class FaceAutoEncoder(nn.Module):
        def __init__(s, latent_ch=128):
            super().__init__()
            s.enc1 = ConvBlock(3, 64, st=2); s.enc2 = ConvBlock(64, 128, st=2); s.enc3 = ConvBlock(128, 256, st=2); s.enc4 = ConvBlock(256, latent_ch, st=2)
            s.dec1 = UpBlock(latent_ch, 256); s.dec2 = UpBlock(256, 128); s.dec3 = UpBlock(128, 64); s.dec4 = UpBlock(64, 32)
            s.out_conv = nn.Sequential(nn.Conv2d(32, 3, 3, 1, 1), nn.Sigmoid())
        def forward(s, x):
            z = s.enc4(s.enc3(s.enc2(s.enc1(x)))); return s.out_conv(s.dec4(s.dec3(s.dec2(s.dec1(z)))))
    m = FaceAutoEncoder(latent_ch)
    return m


def main():
    args = parse_args()
    import os; os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import torch, torch.nn as nn
    from system.backend.model_adapters import WaveGuardAdapter, WAVEGUARD_CKPT
    a = WaveGuardAdapter.get(); dev = a.device
    mr = float(a.cfg.message_range); MSG = int(a.cfg.message_length)

    def load_full(ckpt):
        full = torch.load(str(ckpt), map_location=dev, weights_only=True)
        st = lambda p: {k[len(p):]: v for k, v in full.items() if k.startswith(p)}
        a.encoder.load_state_dict(st("encoder."), strict=False); a.decoder_t.load_state_dict(st("decoder_t."), strict=False); a.decoder_d.load_state_dict(st("decoder_d."), strict=False)
    if args.base_ckpt.exists():
        load_full(args.base_ckpt); print(f"[init] base {args.base_ckpt.name}")

    def load_ae(ckpt, latent):
        ae = build_ae(torch, nn, latent).to(dev)
        s = torch.load(str(ckpt), map_location=dev, weights_only=True)
        sd = s.get("model", s) if isinstance(s, dict) else s
        ae.load_state_dict(sd, strict=True); ae.eval()
        for p_ in ae.parameters(): p_.requires_grad_(False)
        return ae
    # 训练用 AE 集成(ae1+ae2),提升对"再生成"这一攻击族的泛化;ae3 完全留作 held-out 验收
    ae1 = load_ae(args.ae1, args.ae1_latent); print(f"[init] train-AE#1 {args.ae1.name}")
    ae_train = [ae1]
    if args.ae2.exists():
        ae_train.append(load_ae(args.ae2, args.ae2_latent)); print(f"[init] train-AE#2 {args.ae2.name}")
    ae_held = load_ae(args.ae3, args.ae3_latent) if args.ae3.exists() else None
    print(f"[init] held-out AE#3 {'loaded ' + args.ae3.name if ae_held else 'NOT FOUND — held-out bench skipped'}")

    for m in (a.encoder, a.decoder_t, a.decoder_d):
        m.eval()  # 冻结 BN 统计(B=16 也用 eval 保稳)，权重可训练
        for p_ in m.parameters(): p_.requires_grad_(True)
    opt = torch.optim.Adam(list(a.encoder.parameters()) + list(a.decoder_t.parameters()) + list(a.decoder_d.parameters()), lr=args.lr)

    def to256(p): return np.array(Image.open(p).convert("RGB").resize((IMG, IMG), Image.BICUBIC))
    def rgb2yuv(rgb_list):
        return torch.stack([torch.from_numpy(cv2.cvtColor(r.astype(np.uint8), cv2.COLOR_RGB2YUV).astype(np.float32) / 127.5 - 1).permute(2, 0, 1) for r in rgb_list], 0).to(dev)
    def yuv2rgb(yuv):
        arr = yuv.detach().cpu().permute(0, 2, 3, 1).numpy()
        return [cv2.cvtColor(np.clip((arr[i] + 1) * 127.5, 0, 255).astype(np.uint8), cv2.COLOR_YUV2RGB) for i in range(arr.shape[0])]

    def encode(yuv, bits):
        msg = torch.tensor((bits.astype(np.float32) * 2 - 1) * mr, dtype=torch.float32, device=dev)
        y, u, v = yuv[:, [0]], yuv[:, [1]], yuv[:, [2]]
        lp, hp = a.DTCWT.images_U_dtcwt_with_low(u)
        sel = torch.index_select(hp[1], 2, a.indices_enc)[:, :, :, :, :, 0].squeeze(1)
        hp[1][:, :, a.indices_enc, :, :, 0] = a.encoder(sel, msg).unsqueeze(1)
        return torch.cat([y, a.DTCWT.dtcwt_images_U(lp, hp), v], dim=1).clamp(-1, 1), u

    def decode_paths(yuv):
        _, hp = a.DTCWT.images_U_dtcwt_with_low(yuv[:, [1]])
        st = torch.index_select(hp[1], 2, a.indices_dec_t)[:, :, :, :, :, 0].squeeze(1)
        sd = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
        return a.decoder_t(st), a.decoder_d(sd)

    def ae_regen_rgb(wm_rgb_list, ae):
        """对一批水印图做 AE 再生成(256→128→AE→256), 返回 rgb_u8 list(无梯度)。"""
        t = torch.stack([torch.from_numpy(cv2.resize(r, (128, 128)).astype(np.float32) / 255.).permute(2, 0, 1) for r in wm_rgb_list], 0).to(dev)
        with torch.no_grad():
            rec = ae(t).clamp(0, 1)
        rec = (rec.cpu().permute(0, 2, 3, 1).numpy() * 255).astype(np.uint8)
        return [cv2.resize(rec[i], (IMG, IMG)) for i in range(rec.shape[0])]

    def sig_degrade(rgb, atk, r):
        h, w = rgb.shape[:2]
        if atk == "clean": return rgb
        if atk == "jpeg":
            q = int(r.integers(40, 80)); ok, b = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q]); return cv2.cvtColor(cv2.imdecode(b, 1), cv2.COLOR_BGR2RGB)
        if atk == "resize":
            s = cv2.resize(rgb, (w // 2, h // 2), interpolation=cv2.INTER_AREA); return cv2.resize(s, (w, h))
        if atk == "noise": return np.clip(rgb.astype(np.float32) + r.normal(0, 3, rgb.shape), 0, 255).astype(np.uint8)
        return rgb

    rng = np.random.default_rng(args.seed)
    train_paths = sorted(p for p in args.celeba_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.train_images]
    # 强调 regen, 兼顾信号级防遗忘
    POOL = ["regen"] * 6 + ["clean"] * 2 + ["jpeg"] * 2 + ["resize", "noise"]
    mse = nn.MSELoss(); B = args.batch_size; t0 = time.time()
    for ep in range(1, args.epochs + 1):
        order = rng.permutation(len(train_paths)); rl = 0.0; nb = 0
        for bs in range(0, len(order) - B + 1, B):
            rgb_list = [to256(train_paths[i]) for i in order[bs:bs + B]]
            yuv = rgb2yuv(rgb_list); bits = rng.integers(0, 2, size=(B, MSG)).astype(np.uint8)
            wm, cover_u = encode(yuv, bits)
            wm_rgb = yuv2rgb(wm)
            atks = [POOL[int(rng.integers(len(POOL)))] for _ in range(B)]
            deg_rgb = []
            regen_idx = [i for i, x in enumerate(atks) if x == "regen"]
            ae_pick = ae_train[int(rng.integers(len(ae_train)))]  # 集成:每批随机选一个训练AE
            regen_out = ae_regen_rgb([wm_rgb[i] for i in regen_idx], ae_pick) if regen_idx else []
            ri = 0
            for i in range(B):
                if atks[i] == "regen": deg_rgb.append(regen_out[ri]); ri += 1
                else: deg_rgb.append(sig_degrade(wm_rgb[i], atks[i], rng))
            deg_yuv = rgb2yuv(deg_rgb)
            noised = wm + (deg_yuv - wm.detach())  # STE: 前向退化, 反向恒等 → 梯度回编码器
            out_t, out_d = decode_paths(noised)
            tgt = torch.tensor((bits.astype(np.float32) * 2 - 1) * mr, dtype=torch.float32, device=dev)
            loss = 3 * mse(out_d, tgt) + mse(out_t, tgt) + args.fidelity_w * mse(wm[:, [1]], cover_u)
            opt.zero_grad(); loss.backward(); opt.step(); rl += loss.item(); nb += 1
            if nb % 100 == 0: print(f"  [ep{ep}] b{nb} loss={rl/nb:.5f} t={(time.time()-t0)/60:.1f}min")
        print(f"[epoch {ep}/{args.epochs}] loss={rl/max(nb,1):.5f}")
    ft = {n: copy.deepcopy(getattr(a, n).state_dict()) for n in ("encoder", "decoder_t", "decoder_d")}

    # ── 验收: regen(AE1 trained) / regen(AE2 held-out) / clean / jpeg50, 原始 vs 硬化 ──
    from skimage.metrics import peak_signal_noise_ratio
    bench_paths = sorted(p for p in args.lfw_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.bench_images]
    orig = {n: copy.deepcopy(v) for n, v in [(n, None) for n in ()]}  # placeholder
    # 重新载入原始 base 作对照
    def snapshot(): return {n: copy.deepcopy(getattr(a, n).state_dict()) for n in ("encoder", "decoder_t", "decoder_d")}
    def restore(s):
        for n in ("encoder", "decoder_t", "decoder_d"): getattr(a, n).load_state_dict(s[n]); getattr(a, n).eval()
    base_state = None
    if args.base_ckpt.exists():
        load_full(args.base_ckpt); base_state = snapshot()
    else:
        base_state = ft  # no base; compare ft to itself (degenerate)

    def bench(state, label):
        restore(state); psnrs = []
        keys = ["clean", "jpeg50", "regen_train_ae1"] + (["regen_heldout_ae3"] if ae_held is not None else [])
        res = {k: [] for k in keys}
        rb = np.random.default_rng(args.seed + 7)
        for bs in range(0, len(bench_paths), B):
            chunk = bench_paths[bs:bs + B]; rgb_list = [to256(p) for p in chunk]
            yuv = rgb2yuv(rgb_list); bits = rb.integers(0, 2, size=(len(chunk), MSG)).astype(np.uint8)
            with torch.no_grad(): wm, _ = encode(yuv, bits)
            wm_rgb = yuv2rgb(wm)
            for p_, r_ in zip(rgb_list, wm_rgb): psnrs.append(float(peak_signal_noise_ratio(p_, r_, data_range=255)))
            variants = {"clean": wm_rgb, "jpeg50": [sig_degrade(x, "jpeg", np.random.default_rng(0)) for x in wm_rgb],
                        "regen_train_ae1": ae_regen_rgb(wm_rgb, ae1)}
            if ae_held is not None: variants["regen_heldout_ae3"] = ae_regen_rgb(wm_rgb, ae_held)
            for k, vrgb in variants.items():
                with torch.no_grad():
                    yv = rgb2yuv(vrgb); _, hp = a.DTCWT.images_U_dtcwt_with_low(yv[:, [1]])
                    sd = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
                    preds = (a.decoder_d(sd).cpu().numpy() > 0).astype(np.uint8)
                for i in range(len(chunk)): res[k].append(float((preds[i] == bits[i]).mean()))
        summ = {k: {"mean_bit_accuracy": round(float(np.mean(v)), 4), "success_rate@0.9": round(float(np.mean(np.array(v) >= 0.9)), 4)} for k, v in res.items() if v}
        summ["_psnr"] = round(float(np.mean(psnrs)), 2)
        print(f"[bench:{label}] PSNR={summ['_psnr']} " + " ".join(f"{k}={summ[k]['mean_bit_accuracy']:.3f}/{summ[k]['success_rate@0.9']:.3f}" for k in res if res[k]))
        return summ

    print("\n[bench] 原始(base) vs 再生成硬化:")
    b_base = bench(base_state, "base")
    b_ft = bench(ft, "regen_hardened")

    args.out.mkdir(parents=True, exist_ok=True)
    full = torch.load(str(WAVEGUARD_CKPT), map_location="cpu", weights_only=True)
    for sub in ("encoder", "decoder_t", "decoder_d"):
        for k, v in ft[sub].items(): full[f"{sub}.{k}"] = v.cpu()
    torch.save(full, args.out / "model_state_regen_hardened.pth")
    report = {"schema": "waveguard-regen-hardening.v1", "generated_at": int(time.time()), "project": "鉴源盾", "method": "WaveGuard",
              "approach": "adversarial regeneration hardening: AE集成(ae1+ae2)再生成入STE训练池; 强保真度锚定防PSNR崩塌; encoder+decoders joint",
              "guardrail": "训练用 AE集成(ae1 latent128 + ae2 latent192); 验收 held-out AE#3(latent160,训练完全未见)检验真泛化非记忆;并报 PSNR 防画质崩塌",
              "train_images": len(train_paths), "epochs": args.epochs, "bench_images": len(bench_paths),
              "fidelity_w": args.fidelity_w,
              "ae_train": [str(args.ae1), str(args.ae2)], "ae_heldout": str(args.ae3) if ae_held else None,
              "device": str(dev), "seed": args.seed,
              "base": b_base, "regen_hardened": b_ft}
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({"base": b_base, "regen_hardened": b_ft}, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out/'summary.json'}")


if __name__ == "__main__":
    main()
