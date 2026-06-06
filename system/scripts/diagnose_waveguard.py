from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np
import torch

from system.evaluation.runtime import DATA_ROOT, MODEL_SOURCE_ROOT, REPORT_ROOT, WEIGHT_ROOT


DEFAULT_CHECKPOINT = WEIGHT_ROOT / "mea/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth"
DEFAULT_IMAGES = DATA_ROOT / "lfw_full_upload/unknown"
DEFAULT_OUT = REPORT_ROOT / "diagnostics/waveguard"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def yuv_tensor(path: Path, device: torch.device, size: int) -> torch.Tensor:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"failed to read {path}")
    bgr = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA)
    yuv = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV).astype(np.float32)
    return torch.from_numpy(yuv / 127.5 - 1.0).permute(2, 0, 1).unsqueeze(0).to(device)


def bit_accuracy(message: torch.Tensor, decoded: torch.Tensor) -> float:
    return float((message.detach().cpu().gt(0) == decoded.detach().cpu().gt(0)).float().mean().item())


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose WaveGuard saturated detector accuracy using negative controls.")
    parser.add_argument("--num-images", type=int, default=16)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    code = MODEL_SOURCE_ROOT / "MEA/codes/WaveGuard"
    sys.path.insert(0, str(code))
    try:
        import easydict  # noqa: F401
    except ImportError:
        class EasyDict(dict):
            def __getattr__(self, name: str) -> Any:
                try:
                    return self[name]
                except KeyError as exc:
                    raise AttributeError(name) from exc

            def __setattr__(self, name: str, value: Any) -> None:
                self[name] = value

        module = types.ModuleType("easydict")
        module.EasyDict = EasyDict
        sys.modules["easydict"] = module
    try:
        import thop  # noqa: F401
    except ImportError:
        module = types.ModuleType("thop")

        def unavailable_profile(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("thop is unavailable; profiling is not part of inference diagnostics")

        module.profile = unavailable_profile
        sys.modules["thop"] = module
    old_cwd = Path.cwd()
    os.chdir(code)
    try:
        from config import training_config as cfg
        from network.decoder import Decoder
        from network.encoder import Encoder
        from utils import DTCWT_highpass
    finally:
        os.chdir(old_cwd)

    device = torch.device(args.device if torch.cuda.is_available() and args.device.startswith("cuda") else "cpu")
    encoder = Encoder().to(device).eval()
    decoder_t = Decoder(type="tracer").to(device).eval()
    decoder_d = Decoder(type="detector").to(device).eval()
    state = torch.load(args.checkpoint, map_location=device)
    load_summary: dict[str, Any] = {}
    for prefix, model in [("encoder.", encoder), ("decoder_t.", decoder_t), ("decoder_d.", decoder_d)]:
        sub = {key[len(prefix):]: value for key, value in state.items() if key.startswith(prefix)}
        info = model.load_state_dict(sub, strict=True)
        load_summary[prefix[:-1]] = {
            "checkpoint_keys": len(sub),
            "model_keys": len(model.state_dict()),
            "missing": list(info.missing_keys),
            "unexpected": list(info.unexpected_keys),
        }

    idx_e = torch.tensor([0, 2], device=device)
    idx_t = torch.tensor([0, 2, 3, 5], device=device)
    idx_d = torch.tensor([0, 2], device=device)
    images = sorted(args.image_root.glob("*.jpg"))[: args.num_images]
    rng = np.random.default_rng(20260603)
    rows = []
    with torch.no_grad():
        for path in images:
            image = yuv_tensor(path, device, cfg.image_size)
            message_np = rng.choice([-cfg.message_range, cfg.message_range], (1, cfg.message_length))
            wrong_np = rng.choice([-cfg.message_range, cfg.message_range], (1, cfg.message_length))
            message = torch.tensor(message_np, dtype=torch.float32, device=device)
            wrong = torch.tensor(wrong_np, dtype=torch.float32, device=device)
            y, u, v = image[:, [0]], image[:, [1]], image[:, [2]]
            low, high = DTCWT_highpass.images_U_dtcwt_with_low(u)
            selected = torch.index_select(high[1], 2, idx_e)[:, :, :, :, :, 0].squeeze(1)
            high[1][:, :, idx_e, :, :, 0] = encoder(selected, message).unsqueeze(1)
            embedded_u = DTCWT_highpass.dtcwt_images_U(low, high)
            watermarked = torch.cat([y, embedded_u, v], dim=1).clamp(-1, 1)

            def decode(candidate: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
                extracted = DTCWT_highpass.images_U_dtcwt_without_low(candidate[:, [1]])
                selected_t = torch.index_select(extracted[1], 2, idx_t)[:, :, :, :, :, 0].squeeze(1)
                selected_d = torch.index_select(extracted[1], 2, idx_d)[:, :, :, :, :, 0].squeeze(1)
                return decoder_t(selected_t), decoder_d(selected_d)

            decoded_t, decoded_d = decode(watermarked)
            plain_t, plain_d = decode(image)
            rows.append({
                "image": path.name,
                "correct_tracer_acc": bit_accuracy(message, decoded_t),
                "correct_detector_acc": bit_accuracy(message, decoded_d),
                "wrong_tracer_acc": bit_accuracy(wrong, decoded_t),
                "wrong_detector_acc": bit_accuracy(wrong, decoded_d),
                "plain_tracer_acc": bit_accuracy(message, plain_t),
                "plain_detector_acc": bit_accuracy(message, plain_d),
            })

    fields = [key for key in rows[0] if key != "image"] if rows else []
    means = {field: float(np.mean([row[field] for row in rows])) for field in fields}
    negative_max = max(means.get("wrong_detector_acc", 1.0), means.get("plain_detector_acc", 1.0))
    if not rows:
        conclusion = "inconclusive"
    elif means["correct_detector_acc"] >= 0.95 and negative_max <= 0.65:
        conclusion = "saturation_supported_by_negative_controls"
    elif negative_max > 0.75:
        conclusion = "possible_leakage_or_detector_bias"
    else:
        conclusion = "inconclusive"
    report = {
        "schema_version": "waveguard-diagnostic.v1",
        "generated_at": int(time.time()),
        "status": "complete" if rows else "no_images",
        "conclusion": conclusion,
        "device": str(device),
        "num_images": len(rows),
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": sha256_file(args.checkpoint),
        "load_summary": load_summary,
        "mean_accuracy": means,
        "rows": rows,
        "interpretation": [
            "Correct-message accuracy measures normal recovery.",
            "Wrong-message accuracy should remain near 0.5.",
            "Plain-image accuracy should remain near 0.5 when no message was embedded.",
        ],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "diagnostic.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.output / "diagnostic.md").write_text(
        "# WaveGuard Diagnostic\n\n"
        f"- Status: `{report['status']}`\n"
        f"- Conclusion: `{conclusion}`\n"
        f"- Device: `{device}`\n"
        f"- Images: `{len(rows)}`\n"
        f"- Mean accuracy: `{means}`\n",
        encoding="utf-8",
    )
    print(json.dumps({key: report[key] for key in ("status", "conclusion", "device", "num_images", "mean_accuracy", "load_summary")}, indent=2))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
