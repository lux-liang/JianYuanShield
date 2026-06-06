from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import torch
import torchvision.transforms.functional as TF
from PIL import Image

from system.evaluation.runtime import DATA_ROOT, MODEL_SOURCE_ROOT, REPORT_ROOT, WEIGHT_ROOT


DEFAULT_OPTIONS = WEIGHT_ROOT / "mea/HiDDeN/runs/train-test-1 2025.07.09--12-49-43/options-and-config.pickle"
DEFAULT_CHECKPOINT = WEIGHT_ROOT / "mea/HiDDeN/runs/train-test-1 2025.07.09--12-49-43/checkpoints/train-test-1--epoch-200.pyt"
DEFAULT_IMAGES = DATA_ROOT / "lfw_full_upload/unknown"
DEFAULT_OUT = REPORT_ROOT / "diagnostics/hidden"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_image(path: Path, height: int, width: int, device: torch.device) -> torch.Tensor:
    image = Image.open(path).convert("RGB")
    if image.height < height or image.width < width:
        image = image.resize((max(width, image.width), max(height, image.height)))
    array = np.asarray(image)
    y = max((array.shape[0] - height) // 2, 0)
    x = max((array.shape[1] - width) // 2, 0)
    tensor = TF.to_tensor(array[y:y + height, x:x + width]).to(device)
    return (tensor * 2 - 1).unsqueeze(0)


def accuracy(message: np.ndarray, decoded: np.ndarray, mode: str) -> float:
    if mode == "round":
        prediction = np.rint(decoded).clip(0, 1)
    elif mode == "threshold_0.5":
        prediction = decoded >= 0.5
    elif mode == "threshold_0":
        prediction = decoded > 0
    else:
        raise ValueError(mode)
    return float(np.mean(prediction == message))


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose HiDDeN near-random recovery without changing benchmark outputs.")
    parser.add_argument("--num-images", type=int, default=16)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--options", type=Path, default=DEFAULT_OPTIONS)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    code = MODEL_SOURCE_ROOT / "MEA/codes/HiDDeN"
    sys.path.insert(0, str(code))
    import utils
    from model.hidden import Hidden
    from noise_layers.noiser import Noiser

    device = torch.device(args.device if torch.cuda.is_available() and args.device.startswith("cuda") else "cpu")
    _, config, noise_config = utils.load_options(args.options)
    model = Hidden(config, device, Noiser(noise_config, device), None)
    checkpoint = torch.load(args.checkpoint, map_location=device)
    checkpoint_keys = set(checkpoint.keys()) if isinstance(checkpoint, dict) else set()
    utils.model_from_checkpoint(model, checkpoint)
    model.encoder_decoder.eval()
    model.discriminator.eval()

    images = sorted(args.image_root.glob("*.jpg"))[: args.num_images]
    rng = np.random.default_rng(20260603)
    rows: list[dict[str, Any]] = []
    bit_predictions: list[np.ndarray] = []
    fixed_message = np.tile(np.array([[0, 1]], dtype=np.float32), (1, (config.message_length + 1) // 2))[:, :config.message_length]
    with torch.no_grad():
        for index, path in enumerate(images):
            image = load_image(path, config.H, config.W, device)
            random_message = rng.integers(0, 2, size=(1, config.message_length)).astype(np.float32)
            message_np = fixed_message if index < max(1, len(images) // 2) else random_message
            message = torch.from_numpy(message_np).to(device)
            encoded = model.encoder_decoder.encoder(image, message)
            decoded = model.encoder_decoder.decoder(encoded).detach().cpu().numpy()
            bit_predictions.append(decoded.reshape(-1))
            wrong = 1.0 - message_np
            rows.append({
                "image": path.name,
                "message_mode": "fixed" if index < max(1, len(images) // 2) else "random",
                "decoded_min": float(decoded.min()),
                "decoded_max": float(decoded.max()),
                "decoded_mean": float(decoded.mean()),
                "acc_round": accuracy(message_np, decoded, "round"),
                "acc_threshold_0_5": accuracy(message_np, decoded, "threshold_0.5"),
                "acc_threshold_0": accuracy(message_np, decoded, "threshold_0"),
                "wrong_message_acc": accuracy(wrong, decoded, "threshold_0.5"),
            })

    means = {
        key: float(np.mean([row[key] for row in rows]))
        for key in ("acc_round", "acc_threshold_0_5", "acc_threshold_0", "wrong_message_acc")
    } if rows else {}
    decoded_all = np.stack(bit_predictions) if bit_predictions else np.empty((0, config.message_length))
    best_accuracy = max((means.get(key, 0.0) for key in ("acc_round", "acc_threshold_0_5", "acc_threshold_0")), default=0.0)
    if not rows:
        conclusion = "inconclusive"
    elif best_accuracy >= 0.8:
        conclusion = "legacy_decision_rule_issue"
    elif abs(best_accuracy - 0.5) <= 0.08:
        conclusion = "domain_shift_or_checkpoint_protocol_mismatch"
    else:
        conclusion = "inconclusive"
    report = {
        "schema_version": "hidden-diagnostic.v1",
        "generated_at": int(time.time()),
        "status": "complete" if rows else "no_images",
        "conclusion": conclusion,
        "device": str(device),
        "num_images": len(rows),
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": sha256_file(args.checkpoint),
        "options": str(args.options),
        "options_sha256": sha256_file(args.options),
        "checkpoint_top_level_keys": sorted(checkpoint_keys)[:50],
        "message_length": int(config.message_length),
        "decoder_statistics": {
            "global_mean": float(decoded_all.mean()) if decoded_all.size else None,
            "global_std": float(decoded_all.std()) if decoded_all.size else None,
            "per_bit_mean": decoded_all.mean(axis=0).tolist() if decoded_all.size else [],
        },
        "mean_accuracy": means,
        "rows": rows,
        "recommendations": [
            "Compare options-and-config with the checkpoint training run.",
            "Validate message convention against the original HiDDeN test script.",
            "Run an in-distribution training-data sample if available.",
            "Do not label the result as domain shift until protocol mismatch is excluded.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "diagnostic.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# HiDDeN Diagnostic",
        "",
        f"- Status: `{report['status']}`",
        f"- Conclusion: `{conclusion}`",
        f"- Device: `{device}`",
        f"- Images: `{len(rows)}`",
        f"- Mean accuracy: `{means}`",
        "",
        "The diagnostic compares round, threshold-0.5, and threshold-0 decision rules and includes an inverted-message negative control.",
    ]
    (args.output / "diagnostic.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "conclusion", "device", "num_images", "mean_accuracy")}, indent=2))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
