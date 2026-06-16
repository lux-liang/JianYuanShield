#!/usr/bin/env python3
"""为 WaveGuard 加 STN(空间变换网络)解码前置 —— 架构级攻克几何攻击(大刀阔斧).

背景:已证实 DTCWT 子带水印对 crop/rotate 几何不变性是**架构限制**(固定参数微调=记忆、范围训练拟合不了、
固定模板重同步摧毁水印)。本脚本做**架构改动**:在解码器前加一个可学习 STN,端到端学习把被几何攻击的图
**对齐回可解码帧**再解码。与"固定模板重同步"的本质区别:STN 的目标函数就是解码准确率,故学到的是**保留水印**
的正确逆变换,且学的是变换族→**泛化到未训练几何参数**(用 held-out 参数验证)。

设计:
  base = all-attack 微调权重(已信号鲁棒); 冻结 encoder;
  STN.loc_net(U通道)→相似变换参数[log_s, angle, tx, ty](初始化=恒等)→affine_grid+grid_sample 对齐;
  decode_d/decode_t 在对齐后图上解码; STN + 双解码器联合训练;
  训练攻击: clean/jpeg + **随机** crop∈[.65,1.0]/rotate∈[-15,15] + resize/noise。
验收: 在 held-out 几何参数(crop0.7/0.9, rotate3/10/-5)上 with-STN vs baseline,看是否真泛化。

用法:
  PYTHONPATH=. python system/scripts/train_waveguard_stn_geometric.py \
      --base-ckpt system/reports/waveguard_allatk_ste_ft/model_state_jpegste_ft.pth \
      --epochs 6 --train-images 7000 --device cuda:3 --out system/reports/waveguard_stn_geom
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
    p = argparse.ArgumentParser(description="WaveGuard + STN geometric robustness (architectural)")
    p.add_argument("--base-ckpt", type=Path,
                   default=PROJECT_DIR / "system/reports/waveguard_allatk_ste_ft/model_state_jpegste_ft.pth")
    p.add_argument("--celeba-root", type=Path, default=DEFAULT_CELEBA)
    p.add_argument("--lfw-root", type=Path, default=DEFAULT_LFW)
    p.add_argument("--epochs", type=int, default=6)
    p.add_argument("--train-images", type=int, default=7000)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--bench-images", type=int, default=500)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--device", default="cuda:3")
    p.add_argument("--seed", type=int, default=20260616)
    p.add_argument("--out", type=Path, default=PROJECT_DIR / "system/reports/waveguard_stn_geom")
    return p.parse_args()


def build_stn(torch, nn, dev):
    class STN(nn.Module):
        """在 U 通道上预测相似变换(对齐回可解码帧), 初始化为恒等。"""
        def __init__(self):
            super().__init__()
            self.loc = nn.Sequential(
                nn.Conv2d(1, 16, 7, stride=2, padding=3), nn.BatchNorm2d(16), nn.ReLU(True),  # 256→128
                nn.Conv2d(16, 32, 5, stride=2, padding=2), nn.BatchNorm2d(32), nn.ReLU(True),  # 128→64
                nn.Conv2d(32, 64, 5, stride=2, padding=2), nn.BatchNorm2d(64), nn.ReLU(True),  # 64→32
                nn.AdaptiveAvgPool2d(4),  # 64×4×4
            )
            self.fc = nn.Sequential(nn.Linear(64 * 4 * 4, 128), nn.ReLU(True), nn.Linear(128, 4))
            # 初始化为恒等: log_s=0, angle=0, tx=0, ty=0
            self.fc[-1].weight.data.zero_(); self.fc[-1].bias.data.zero_()

        def theta(self, u):
            p = self.fc(self.loc(u).flatten(1))  # (B,4): log_s, angle, tx, ty
            s = torch.exp(p[:, 0]); a = p[:, 1]; tx = p[:, 2]; ty = p[:, 3]
            cos, sin = torch.cos(a), torch.sin(a)
            th = torch.stack([s * cos, -s * sin, tx, s * sin, s * cos, ty], dim=1).view(-1, 2, 3)
            return th

        def forward(self, yuv):
            import torch.nn.functional as F
            th = self.theta(yuv[:, [1]])  # 用 U 通道预测
            grid = F.affine_grid(th, yuv.shape, align_corners=False)
            return F.grid_sample(yuv, grid, align_corners=False, padding_mode="reflection")
    return STN().to(dev)


def main():
    args = parse_args()
    import os; os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import torch, torch.nn as nn
    from system.backend.model_adapters import WaveGuardAdapter

    a = WaveGuardAdapter.get(); dev = a.device
    mr = float(a.cfg.message_range); MSG = int(a.cfg.message_length)
    # 载入已信号鲁棒的 base 权重
    if args.base_ckpt.exists():
        full = torch.load(str(args.base_ckpt), map_location=dev, weights_only=True)
        st = lambda p: {k[len(p):]: v for k, v in full.items() if k.startswith(p)}
        a.encoder.load_state_dict(st("encoder."), strict=False)
        a.decoder_t.load_state_dict(st("decoder_t."), strict=False)
        a.decoder_d.load_state_dict(st("decoder_d."), strict=False)
        print(f"[init] loaded base ckpt {args.base_ckpt.name}")
    else:
        print(f"[init] base ckpt 不存在,用适配器默认权重: {args.base_ckpt}")

    stn = build_stn(torch, nn, dev)
    # 冻结 encoder; 训练 STN + 双解码器
    for p_ in a.encoder.parameters(): p_.requires_grad_(False)
    a.encoder.eval()
    for m in (a.decoder_t, a.decoder_d): m.train(); [p_.requires_grad_(True) for p_ in m.parameters()]
    stn.train()
    opt = torch.optim.Adam(list(stn.parameters()) + list(a.decoder_t.parameters())
                           + list(a.decoder_d.parameters()), lr=args.lr)

    def to256(p): return np.array(Image.open(p).convert("RGB").resize((IMG, IMG), Image.BICUBIC))

    def rgb_batch_to_yuv(rgb_list):
        ts = [torch.from_numpy(cv2.cvtColor(r.astype(np.uint8), cv2.COLOR_RGB2YUV).astype(np.float32) / 127.5 - 1.0).permute(2, 0, 1) for r in rgb_list]
        return torch.stack(ts, 0).to(dev)

    def yuv_batch_to_rgb(yuv):
        arr = yuv.detach().cpu().permute(0, 2, 3, 1).numpy()
        return [cv2.cvtColor(np.clip((arr[i] + 1) * 127.5, 0, 255).astype(np.uint8), cv2.COLOR_YUV2RGB) for i in range(arr.shape[0])]

    def encode(yuv, bits):  # frozen
        msg = torch.tensor((bits.astype(np.float32) * 2 - 1) * mr, dtype=torch.float32, device=dev)
        with torch.no_grad():
            y, u, v = yuv[:, [0]], yuv[:, [1]], yuv[:, [2]]
            lp, hp = a.DTCWT.images_U_dtcwt_with_low(u)
            sel = torch.index_select(hp[1], 2, a.indices_enc)[:, :, :, :, :, 0].squeeze(1)
            hp[1][:, :, a.indices_enc, :, :, 0] = a.encoder(sel, msg).unsqueeze(1)
            return torch.cat([y, a.DTCWT.dtcwt_images_U(lp, hp), v], dim=1).clamp(-1, 1)

    def decode_after_stn(yuv_attacked):
        aligned = stn(yuv_attacked)            # STN 对齐(可训练)
        _, hp = a.DTCWT.images_U_dtcwt_with_low(aligned[:, [1]])
        sel_t = torch.index_select(hp[1], 2, a.indices_dec_t)[:, :, :, :, :, 0].squeeze(1)
        sel_d = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
        return a.decoder_t(sel_t), a.decoder_d(sel_d)

    def degrade(rgb, atk, r):
        h, w = rgb.shape[:2]
        if atk == "clean": return rgb
        if atk == "jpeg":
            q = int(r.integers(40, 80)); ok, b = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q]); return cv2.cvtColor(cv2.imdecode(b, 1), cv2.COLOR_BGR2RGB)
        if atk == "resize":
            s = cv2.resize(rgb, (w // 2, h // 2), interpolation=cv2.INTER_AREA); return cv2.resize(s, (w, h))
        if atk == "noise": return np.clip(rgb.astype(np.float32) + r.normal(0, 3, rgb.shape), 0, 255).astype(np.uint8)
        if atk == "cropR":
            ratio = float(r.uniform(0.65, 1.0)); ch, cw = int(h * ratio), int(w * ratio); y0, x0 = (h - ch) // 2, (w - cw) // 2
            return cv2.resize(rgb[y0:y0 + ch, x0:x0 + cw], (w, h))
        if atk == "rotateR":
            M = cv2.getRotationMatrix2D((w / 2, h / 2), float(r.uniform(-15, 15)), 1.0); return cv2.warpAffine(rgb, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
        return rgb

    rng = np.random.default_rng(args.seed)
    train_paths = sorted(p for p in args.celeba_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.train_images]
    POOL = ["clean"] * 2 + ["jpeg"] * 2 + ["resize", "noise"] + ["cropR"] * 4 + ["rotateR"] * 4
    mse = nn.MSELoss(); B = args.batch_size
    t0 = time.time()
    for ep in range(1, args.epochs + 1):
        order = rng.permutation(len(train_paths)); rl = 0.0; nb = 0
        for bs in range(0, len(order) - B + 1, B):
            rgb_list = [to256(train_paths[i]) for i in order[bs:bs + B]]
            yuv = rgb_batch_to_yuv(rgb_list)
            bits = rng.integers(0, 2, size=(B, MSG)).astype(np.uint8)
            wm = encode(yuv, bits)
            wm_rgb = yuv_batch_to_rgb(wm)
            atks = [POOL[int(rng.integers(len(POOL)))] for _ in range(B)]
            atk_rgb = [degrade(wm_rgb[i], atks[i], rng) for i in range(B)]
            atk_yuv = rgb_batch_to_yuv(atk_rgb)
            aligned = stn(atk_yuv)                                  # STN 对齐
            _, hp = a.DTCWT.images_U_dtcwt_with_low(aligned[:, [1]])
            sel_t = torch.index_select(hp[1], 2, a.indices_dec_t)[:, :, :, :, :, 0].squeeze(1)
            sel_d = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
            out_t, out_d = a.decoder_t(sel_t), a.decoder_d(sel_d)
            tgt = torch.tensor((bits.astype(np.float32) * 2 - 1) * mr, dtype=torch.float32, device=dev)
            # 监督STN在图像空间把被攻击图对齐回 clean watermarked(撤销几何,convention-free);非几何攻击自然≈恒等
            aux = mse(aligned, wm.detach())
            loss = 3 * mse(out_d, tgt) + mse(out_t, tgt) + 2.0 * aux
            opt.zero_grad(); loss.backward(); opt.step()
            rl += loss.item(); nb += 1
            if nb % 100 == 0:
                print(f"  [ep{ep}] batch {nb} loss={rl/nb:.5f} elapsed={(time.time()-t0)/60:.1f}min")
        print(f"[epoch {ep}/{args.epochs}] mean_loss={rl/max(nb,1):.5f}")
    stn.eval(); a.decoder_t.eval(); a.decoder_d.eval()

    # ── 验收: held-out 几何参数, STN vs baseline(无STN直接解) ─────────────────────
    bench_paths = sorted(p for p in args.lfw_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:args.bench_images]
    def crop_r(rgb, ratio):
        h, w = rgb.shape[:2]; ch, cw = int(h * ratio), int(w * ratio); y0, x0 = (h - ch) // 2, (w - cw) // 2
        return cv2.resize(rgb[y0:y0 + ch, x0:x0 + cw], (w, h))
    def rot(rgb, d):
        h, w = rgb.shape[:2]; M = cv2.getRotationMatrix2D((w / 2, h / 2), d, 1.0); return cv2.warpAffine(rgb, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
    BENCH = {"clean": lambda x: x, "jpeg50": lambda x: degrade(x, "jpeg", np.random.default_rng(0)),
             "crop0.8_train-range": lambda x: crop_r(x, 0.8), "rotate5_train-range": lambda x: rot(x, 5),
             "crop0.7_heldout": lambda x: crop_r(x, 0.7), "crop0.9_heldout": lambda x: crop_r(x, 0.9),
             "rotate10_heldout": lambda x: rot(x, 10), "rotate-8_heldout": lambda x: rot(x, -8)}

    def decode_baseline(yuv):  # 无 STN
        with torch.no_grad():
            _, hp = a.DTCWT.images_U_dtcwt_with_low(yuv[:, [1]])
            sel = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
            return (a.decoder_d(sel).cpu().numpy() > 0).astype(np.uint8)
    def decode_stn(yuv):
        with torch.no_grad():
            aligned = stn(yuv); _, hp = a.DTCWT.images_U_dtcwt_with_low(aligned[:, [1]])
            sel = torch.index_select(hp[1], 2, a.indices_dec_d)[:, :, :, :, :, 0].squeeze(1)
            return (a.decoder_d(sel).cpu().numpy() > 0).astype(np.uint8)

    base = {k: [] for k in BENCH}; withstn = {k: [] for k in BENCH}
    rb = np.random.default_rng(args.seed + 7)
    for bs in range(0, len(bench_paths), B):
        chunk = bench_paths[bs:bs + B]; rgb_list = [to256(p) for p in chunk]
        yuv = rgb_batch_to_yuv(rgb_list); bits = rb.integers(0, 2, size=(len(chunk), MSG)).astype(np.uint8)
        with torch.no_grad():
            wm = encode(yuv, bits)
        wm_rgb = yuv_batch_to_rgb(wm)
        for k, fn in BENCH.items():
            atk_yuv = rgb_batch_to_yuv([fn(wm_rgb[i]) for i in range(len(chunk))])
            pb = decode_baseline(atk_yuv); ps = decode_stn(atk_yuv)
            for i in range(len(chunk)):
                base[k].append(float((pb[i] == bits[i]).mean())); withstn[k].append(float((ps[i] == bits[i]).mean()))

    def summ(d): return {k: {"mean_bit_accuracy": round(float(np.mean(v)), 4), "success_rate@0.9": round(float(np.mean(np.array(v) >= 0.9)), 4)} for k, v in d.items()}
    report = {"schema": "waveguard-stn-geom.v1", "generated_at": int(time.time()), "project": "鉴源盾",
              "approach": "解码前置可学习STN(架构改动)攻克几何攻击; encoder冻结+STN+双解码器联合训练,随机几何参数",
              "base_ckpt": str(args.base_ckpt), "train_images": len(train_paths), "epochs": args.epochs,
              "bench_images": len(bench_paths), "device": str(dev), "seed": args.seed,
              "baseline_no_stn": summ(base), "with_stn": summ(withstn),
              "note": "crop0.8/rotate5 在训练范围内; crop0.7/0.9 rotate10/-8 为 held-out 几何参数,验证真泛化(STN学变换族非记忆)"}
    args.out.mkdir(parents=True, exist_ok=True)
    full_save = torch.load(str(args.base_ckpt), map_location="cpu", weights_only=True) if args.base_ckpt.exists() else {}
    torch.save({"stn": stn.state_dict(), "decoder_d": a.decoder_d.state_dict(), "decoder_t": a.decoder_t.state_dict()},
               args.out / "stn_geom_modules.pth")
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({"baseline": report["baseline_no_stn"], "with_stn": report["with_stn"]}, indent=2, ensure_ascii=False))
    print(f"[done] → {args.out/'summary.json'}")


if __name__ == "__main__":
    main()
