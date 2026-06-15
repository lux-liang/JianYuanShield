from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path
import numpy as np
from PIL import Image
import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from system.evaluation.adapters.lidmark_adapter import LIDMarkAdapter

DATA = Path(os.environ.get("JYS_LFW_DIR", "/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown"))
ATTACKS = ["clean", "jpeg50", "jpeg70", "resize", "noise"]


def attack(arr, name, rng):
    if name == "clean":
        return arr
    if name.startswith("jpeg"):
        q = int(name[4:])
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])
        return cv2.cvtColor(cv2.imdecode(buf, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if name == "resize":
        h, w = arr.shape[:2]
        s = cv2.resize(arr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        return cv2.resize(s, (w, h), interpolation=cv2.INTER_LINEAR)
    if name == "noise":
        return np.clip(arr.astype(np.float32) + rng.normal(0, 3.0, arr.shape), 0, 255).astype(np.uint8)
    raise ValueError(name)


def main():
    # 测量 LIDMark 16-bit ID 水印的比特准确率（此前评测只测 landmark 定位，bit_accuracy=null）。
    # 注意：本脚本经 LIDMarkAdapter 的 MEA 模式编码——136 维 landmark 置零、仅嵌 16 位 id。
    # 这可能低估 LIDMark 真实 id 能力（其训练为 landmark+id 联合），真值需在完整配置(带人脸检测器)下另测。
    ap = argparse.ArgumentParser()
    ap.add_argument("--num-images", type=int, default=512)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--seed", type=int, default=20260615)
    ap.add_argument("--out", default=str(ROOT / "system/reports/lidmark_idbit_eval/summary.json"))
    a = ap.parse_args()
    os.environ["JYS_INFER_DEVICE"] = a.device
    ad = LIDMarkAdapter()
    if not ad.available:
        print("LIDMark unavailable:", ad.blocker); sys.exit(1)
    print("ckpt:", ad.checkpoint, "msg_len:", ad.message_length)
    paths = sorted(p for p in DATA.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})[:a.num_images]
    rng = np.random.default_rng(a.seed)
    accs = {k: [] for k in ATTACKS}
    t0 = time.time()
    for i, p in enumerate(paths):
        img = np.array(Image.open(p).convert("RGB"))
        msg = rng.integers(0, 2, ad.message_length, dtype=np.uint8)
        enc = ad.encode(img, msg).image
        for atk in ATTACKS:
            try:
                dec = ad.decode(attack(enc, atk, rng)).bits
                accs[atk].append(float(np.mean(dec == msg)))
            except Exception:
                pass
        if (i + 1) % 100 == 0:
            print(i + 1, "/", len(paths), "clean_acc=", round(float(np.mean(accs["clean"])), 4))
    summary = {"method": "LIDMark-idbit", "metric": "id_bit_accuracy_16bit",
               "note": "MEA-mode encode (landmark dims zeroed); may understate full-config capability",
               "checkpoint": ad.checkpoint, "n_images": len(paths), "seed": a.seed,
               "attacks": {k: {"mean_id_bit_accuracy": round(float(np.mean(v)), 6),
                               "success_rate_0.9": round(float(np.mean([x >= 0.9 for x in v])), 6),
                               "count": len(v)} for k, v in accs.items() if v}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
