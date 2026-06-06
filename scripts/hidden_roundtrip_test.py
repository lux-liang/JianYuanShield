#!/usr/bin/env python3
"""
HiDDeN Round-Trip Test: encode → decode on same image (no noise).
If this fails, checkpoint is broken. If it succeeds, LFW result = domain shift.
"""
import sys, os, json, time, numpy as np, torch

HIDDEN_CODE = "/data1/luxliang/work/vpsg_competition_candidates/MEA/codes/HiDDeN"
CKPT = ("/data1/luxliang/work/vpsg_competition_candidates/weights/mea/HiDDeN"
        "/runs/train-test-1 2025.07.09--12-49-43/checkpoints/train-test-1--epoch-200.pyt")
OPTIONS = ("/data1/luxliang/work/vpsg_competition_candidates/weights/mea/HiDDeN"
           "/runs/train-test-1 2025.07.09--12-49-43/options-and-config.pickle")
# Use CelebA-HQ images — closer to face training distribution than w-sub
IMG_DIR = "/data1/luxliang/work/vpsg_competition_candidates/datasets/celeba_hq_lidmark/val"
OUT_JSON = "/data1/luxliang/work/vpsg_competition_candidates/system/reports/diagnostics/hidden_roundtrip.json"

sys.path.insert(0, HIDDEN_CODE)
os.chdir(HIDDEN_CODE)

import utils
from model.hidden import Hidden
from noise_layers.noiser import Noiser
from PIL import Image
import torchvision.transforms.functional as TF

device = torch.device("cuda:0")

print("[HiDDeN] Loading checkpoint & config...")
train_options, hidden_config, noise_config = utils.load_options(OPTIONS)
noiser = Noiser(noise_config, torch.device("cuda:0"))
checkpoint = torch.load(CKPT, map_location=device)
hidden_net = Hidden(hidden_config, device, noiser, None)
utils.model_from_checkpoint(hidden_net, checkpoint)
hidden_net.encoder_decoder.eval()

H, W = hidden_config.H, hidden_config.W
print(f"[HiDDeN] H={H} W={W} message_length={hidden_config.message_length}")

# Find test images (try CelebA-HQ val, fallback to LFW benchmark)
img_paths = []
for d in [IMG_DIR,
          "/data1/luxliang/work/vpsg_competition_candidates/datasets/celeba_hq_kadnet/val_128",
          "/data1/luxliang/work/vpsg_competition_candidates/system/assets/lfw_benchmark"]:
    if os.path.isdir(d):
        exts = {".jpg", ".jpeg", ".png"}
        for f in sorted(os.listdir(d)):
            if os.path.splitext(f)[1].lower() in exts:
                img_paths.append(os.path.join(d, f))
        if img_paths:
            print(f"[HiDDeN] Using images from: {d}")
            break

img_paths = img_paths[:16]
assert img_paths, "No test images found"

results = []
accs_roundtrip = []
accs_lfw_style = []

with torch.no_grad():
    for img_path in img_paths:
        img = Image.open(img_path).convert("RGB")
        arr = np.array(img)
        # Center-crop to H×W
        cy, cx = arr.shape[0]//2, arr.shape[1]//2
        arr = arr[max(0,cy-H//2):cy-H//2+H, max(0,cx-W//2):cx-W//2+W]
        if arr.shape[0] < H or arr.shape[1] < W:
            from PIL import Image as PILImage
            img_r = PILImage.fromarray(arr).resize((W, H))
            arr = np.array(img_r)

        # [-1, 1] normalization (HiDDeN convention)
        t = TF.to_tensor(arr).unsqueeze(0).to(device)
        t = t * 2 - 1

        msg = torch.randint(0, 2, (1, hidden_config.message_length), dtype=torch.float32).to(device)

        # Encode
        encoded, _, decoded = hidden_net.encoder_decoder(t, msg)

        # Round-trip accuracy (decode from ENCODED image, no attack)
        dec_rt = decoded.detach().cpu().numpy().round().clip(0, 1)
        msg_np = msg.detach().cpu().numpy()
        acc_rt = float(np.mean(dec_rt == msg_np))
        accs_roundtrip.append(acc_rt)

        # Also try: decode from ORIGINAL image (should be ~50% if watermark not there)
        _, _, decoded_orig = hidden_net.encoder_decoder(t, msg)
        # Note: encode() always runs the full forward pass; for original-only we need encoder_decoder
        # Actually the above IS encode+decode of t. Let's do raw decode of t:
        dec_logits_orig = hidden_net.encoder_decoder.decoder(t)
        dec_orig = torch.sigmoid(dec_logits_orig).detach().cpu().numpy().round().clip(0, 1) \
                   if dec_logits_orig.min() < 0 else dec_logits_orig.detach().cpu().numpy().round().clip(0, 1)
        acc_orig = float(np.mean(dec_orig == msg_np))

        results.append({
            "image": os.path.basename(img_path),
            "acc_roundtrip": round(acc_rt, 4),
            "acc_original_image": round(acc_orig, 4),
            "decoded_mean_rt": round(float(decoded.mean()), 4),
        })
        print(f"  {os.path.basename(img_path)}: round-trip acc={acc_rt:.3f}, orig_acc={acc_orig:.3f}")

mean_rt = float(np.mean(accs_roundtrip))
print(f"\n[HiDDeN] Mean round-trip accuracy: {mean_rt:.4f}")

if mean_rt > 0.90:
    conclusion = "checkpoint_valid_domain_shift"
    explanation = ("Round-trip accuracy > 90% confirms checkpoint works correctly. "
                   "LFW failure (50%) is genuine domain shift: model trained on web images, tested on face portraits.")
elif mean_rt > 0.70:
    conclusion = "checkpoint_partial_domain_shift"
    explanation = "Moderate round-trip accuracy suggests both domain shift and possible overfitting."
else:
    conclusion = "checkpoint_broken"
    explanation = ("Round-trip accuracy ≤ 70% even on training-similar images. "
                   "Checkpoint is fundamentally broken — likely training failure or epoch-200 > num_epochs issue.")

out = {
    "schema": "hidden-roundtrip.v1",
    "generated_at": int(time.time()),
    "mean_roundtrip_accuracy": round(mean_rt, 4),
    "conclusion": conclusion,
    "explanation": explanation,
    "num_images": len(results),
    "results": results,
}
os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
with open(OUT_JSON, "w") as f:
    json.dump(out, f, indent=2)
print(f"[HiDDeN] Saved → {OUT_JSON}")
print(f"[HiDDeN] CONCLUSION: {conclusion}")
print(f"[HiDDeN] {explanation}")
