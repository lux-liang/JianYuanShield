from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
import types
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

# Must be set before Torch initializes CUDA/CuBLAS.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.attacks import ATTACKS, apply_attack  # noqa: E402
from system.evaluation.evidence import (  # noqa: E402
    build_dataset_manifest,
    finalize_benchmark_summary,
)
from system.evaluation.protocol import load_protocol  # noqa: E402
from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.evaluation.runtime import (  # noqa: E402
    ASSET_ROOT,
    DATA_ROOT,
    MODEL_SOURCE_ROOT,
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
)


SEPMARK_CODE = MODEL_SOURCE_ROOT / "MEA/codes/SepMark"
DEFAULT_IMAGE_ROOT = DATA_ROOT / "lfw/processed/image/lfw_256"
DEFAULT_CHECKPOINT = (
    WEIGHT_ROOT
    / "MEA/models/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_108.pth"
)
DEFAULT_CHECKPOINT_SHA256 = (
    "433992186176483bd92341fd033cf3c2fa2682f159aea7fe4542c4a6b88b5e55"
)
DEFAULT_SELECTION_EVIDENCE = (
    REPORT_ROOT / "sepmark-official-smoke-20260804/summary.json"
)
DEFAULT_REPORT_DIR = REPORT_ROOT / "sepmark_lfw_benchmark"
DEFAULT_ASSET_DIR = ASSET_ROOT / "sepmark_lfw_benchmark"
MSG_LEN = 128
IMG_SIZE = 256
MESSAGE_RANGE = 0.1
PRIMARY_DECODER = "decoder_C"
SECONDARY_DECODER = "decoder_RF"
RESULT_FIELDS = [
    "image_id",
    "source_path",
    "attack_type",
    "attack_config_sha256",
    "message_bits",
    "message_sha256",
    "primary_decoder",
    "bit_error_c",
    "bit_accuracy_c",
    "bit_error_rf",
    "bit_accuracy_rf",
    "psnr",
    "ssim",
    "success",
    "error",
]
QUALITY_FIELDS = [
    "image_id",
    "source_path",
    "message_bits",
    "message_sha256",
    "watermarked_psnr",
    "watermarked_ssim",
    "error",
]
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


def parse_args() -> argparse.Namespace:
    protocol = load_protocol()
    parser = argparse.ArgumentParser(
        description="Run the reproducible SepMark real-checkpoint benchmark on LFW.",
    )
    parser.add_argument("--num-images", type=int, default=13233)
    parser.add_argument(
        "--attacks",
        nargs="+",
        default=None,
        help="Canonical evaluation_protocol.v1 attack IDs; defaults to the complete protocol set.",
    )
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=int(protocol["seed"]))
    parser.add_argument("--artifact-limit", type=int, default=16)
    parser.add_argument("--flush-every", type=int, default=100)
    return parser.parse_args()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_write_csv(
    path: Path,
    fieldnames: list[str],
    rows: Iterable[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _canonical_json_hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_absolute_host_path(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and (
        Path(stripped).is_absolute() or bool(_WINDOWS_ABSOLUTE.match(stripped))
    )


def _assert_no_absolute_paths(payload: Any, context: str) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            _assert_no_absolute_paths(value, f"{context}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _assert_no_absolute_paths(value, f"{context}[{index}]")
    elif isinstance(payload, str) and _is_absolute_host_path(payload):
        raise ValueError(f"absolute host path forbidden in {context}")


def list_images(root: Path, limit: int) -> list[Path]:
    root = root.expanduser().resolve()
    if limit < 0:
        raise ValueError("num-images must be non-negative")
    if not root.is_dir():
        raise FileNotFoundError(f"image root not found: {logical_path(root)}")
    images = sorted(
        (
            path
            for path in root.rglob("*")
            if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if limit > 0:
        if len(images) < limit:
            raise RuntimeError(
                f"requested {limit} images but dataset contains {len(images)}"
            )
        images = images[:limit]
    return images


def image_id(path: Path, image_root: Path) -> str:
    relative = path.expanduser().resolve().relative_to(
        image_root.expanduser().resolve()
    ).as_posix()
    if _is_absolute_host_path(relative) or relative.startswith("../"):
        raise ValueError("image_id must be dataset-relative")
    return relative


def load_image(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        image = source.convert("RGB").resize(
            (IMG_SIZE, IMG_SIZE),
            Image.Resampling.BICUBIC,
        )
        return np.asarray(image, dtype=np.uint8).copy()


def message_for_image(seed: int, identifier: str, length: int = MSG_LEN) -> np.ndarray:
    """Derive an image-scoped message without traversal or resume-order state."""

    if length <= 0:
        raise ValueError("message length must be positive")
    payload = f"sepmark-message.v1\0{seed}\0{identifier}".encode("utf-8")
    packed = hashlib.shake_256(payload).digest((length + 7) // 8)
    return np.unpackbits(
        np.frombuffer(packed, dtype=np.uint8),
        bitorder="big",
    )[:length].astype(np.uint8)


def message_bits(message: np.ndarray) -> str:
    return "".join(str(int(bit)) for bit in message.tolist())


def message_sha256(message: np.ndarray) -> str:
    return hashlib.sha256(
        message.astype(np.uint8, copy=False).tobytes()
    ).hexdigest()


def resolve_attacks(
    requested: list[str] | None,
    protocol: dict[str, Any],
) -> list[str]:
    protocol_entries = {entry["id"]: entry for entry in protocol["attacks"]}
    canonical_ids = list(protocol_entries)
    selected = canonical_ids if requested is None else list(requested)
    if not selected:
        raise ValueError("at least one canonical attack is required")
    if len(selected) != len(set(selected)):
        raise ValueError("attack IDs must be unique")
    unknown = [attack_id for attack_id in selected if attack_id not in protocol_entries]
    if unknown:
        raise ValueError("non-canonical attack IDs: " + ", ".join(unknown))
    missing_implementations = [
        attack_id for attack_id in selected if attack_id not in ATTACKS
    ]
    if missing_implementations:
        raise ValueError(
            "canonical attacks missing shared implementations: "
            + ", ".join(missing_implementations)
        )

    for attack_id in selected:
        registered = protocol_entries[attack_id]
        shared = ATTACKS[attack_id]
        if registered.get("type") != shared.type:
            raise ValueError(f"attack type drift for {attack_id}")
        for key, value in shared.parameters.items():
            if registered.get("parameters", {}).get(key) != value:
                raise ValueError(f"attack parameter drift for {attack_id}.{key}")
    return selected


def attack_contract_hash(attacks: list[str], protocol: dict[str, Any]) -> str:
    entries = {entry["id"]: entry for entry in protocol["attacks"]}
    return _canonical_json_hash([
        {
            "protocol": entries[attack_id],
            "shared_config_sha256": ATTACKS[attack_id].config_hash,
        }
        for attack_id in attacks
    ])


def compute_metrics(
    reference: np.ndarray,
    candidate: np.ndarray,
) -> tuple[float, float]:
    if reference.shape != candidate.shape:
        raise ValueError(
            f"quality metric shape mismatch: {reference.shape} != {candidate.shape}"
        )
    if reference.ndim != 3 or reference.shape[2] != 3:
        raise ValueError("quality metrics require HxWx3 RGB images")
    minimum_side = min(reference.shape[:2])
    if minimum_side < 3:
        raise ValueError("quality metrics require image sides of at least three pixels")
    if np.array_equal(reference, candidate):
        return math.inf, 1.0
    window = min(7, minimum_side if minimum_side % 2 else minimum_side - 1)
    return (
        float(peak_signal_noise_ratio(reference, candidate, data_range=255)),
        float(
            structural_similarity(
                reference,
                candidate,
                channel_axis=2,
                data_range=255,
                win_size=window,
            )
        ),
    )


def _metric_text(value: float) -> str:
    if math.isnan(value):
        raise ValueError("NaN metric is not auditable")
    return "inf" if math.isinf(value) and value > 0 else f"{value:.8f}"


def _safe_error(stage: str, error: BaseException) -> str:
    return f"{stage}:{type(error).__name__}"


def _load_csv(path: Path, fieldnames: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fieldnames:
            raise ValueError(f"CSV schema mismatch: {logical_path(path)}")
        rows = list(reader)
    _assert_no_absolute_paths(rows, path.name)
    return rows


def _float(row: dict[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric field {field}") from exc
    if math.isnan(value):
        raise ValueError(f"NaN is forbidden in {field}")
    return value


def load_result_rows(
    path: Path,
    expected_keys: set[tuple[str, str]],
    seed: int,
    success_threshold: float = 0.9,
) -> dict[tuple[str, str], dict[str, str]]:
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in _load_csv(path, RESULT_FIELDS):
        key = (row["image_id"], row["attack_type"])
        if key in indexed:
            raise ValueError(f"duplicate result key: {key}")
        if key not in expected_keys:
            raise ValueError(f"unexpected result key: {key}")
        if row["source_path"] != row["image_id"]:
            raise ValueError(
                f"source_path must be dataset-relative and equal image_id: {key}"
            )
        if row["primary_decoder"] != PRIMARY_DECODER:
            raise ValueError(f"primary decoder mismatch: {key}")
        expected_message = message_for_image(seed, row["image_id"])
        if row["message_bits"] != message_bits(expected_message):
            raise ValueError(f"message derivation mismatch: {key}")
        if row["message_sha256"] != message_sha256(expected_message):
            raise ValueError(f"message hash mismatch: {key}")
        if row["attack_config_sha256"] != ATTACKS[row["attack_type"]].config_hash:
            raise ValueError(f"attack configuration mismatch: {key}")

        metric_fields = (
            "bit_error_c",
            "bit_accuracy_c",
            "bit_error_rf",
            "bit_accuracy_rf",
            "psnr",
            "ssim",
        )
        if row["error"]:
            if any(row[field] for field in metric_fields):
                raise ValueError(f"error row contains metrics: {key}")
            if row["success"] != "0":
                raise ValueError(f"error row marked successful: {key}")
        else:
            ber_c = _float(row, "bit_error_c")
            accuracy_c = _float(row, "bit_accuracy_c")
            ber_rf = _float(row, "bit_error_rf")
            accuracy_rf = _float(row, "bit_accuracy_rf")
            psnr = _float(row, "psnr")
            ssim = _float(row, "ssim")
            for decoder, ber, accuracy in (
                ("decoder_C", ber_c, accuracy_c),
                ("decoder_RF", ber_rf, accuracy_rf),
            ):
                if not 0.0 <= ber <= 1.0 or not 0.0 <= accuracy <= 1.0:
                    raise ValueError(f"{decoder} metric outside [0,1]: {key}")
                if abs((1.0 - ber) - accuracy) > 1e-7:
                    raise ValueError(f"{decoder} metric identity failed: {key}")
            if psnr == -math.inf or not -1.0 <= ssim <= 1.0:
                raise ValueError(f"invalid attacked-quality metric: {key}")
            expected_success = "1" if accuracy_c >= success_threshold else "0"
            if row["success"] != expected_success:
                raise ValueError(f"decoder_C success threshold mismatch: {key}")
        indexed[key] = row
    return indexed


def load_quality_rows(
    path: Path,
    expected_ids: set[str],
    seed: int,
) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in _load_csv(path, QUALITY_FIELDS):
        identifier = row["image_id"]
        if identifier in indexed:
            raise ValueError(f"duplicate watermarked-quality key: {identifier}")
        if identifier not in expected_ids:
            raise ValueError(f"unexpected watermarked-quality key: {identifier}")
        if row["source_path"] != identifier:
            raise ValueError(f"watermarked source_path mismatch: {identifier}")
        expected_message = message_for_image(seed, identifier)
        if row["message_bits"] != message_bits(expected_message):
            raise ValueError(f"watermarked message derivation mismatch: {identifier}")
        if row["message_sha256"] != message_sha256(expected_message):
            raise ValueError(f"watermarked message hash mismatch: {identifier}")
        if row["error"]:
            if row["watermarked_psnr"] or row["watermarked_ssim"]:
                raise ValueError(
                    f"watermarked error row contains metrics: {identifier}"
                )
        else:
            psnr = _float(row, "watermarked_psnr")
            ssim = _float(row, "watermarked_ssim")
            if psnr == -math.inf or not -1.0 <= ssim <= 1.0:
                raise ValueError(
                    f"invalid watermarked-quality metric: {identifier}"
                )
        indexed[identifier] = row
    return indexed


def _mean(
    rows: Iterable[dict[str, str]],
    field: str,
) -> float | str | None:
    values = [float(row[field]) for row in rows if not row["error"] and row[field]]
    if not values:
        return None
    if any(value == math.inf for value in values):
        return "inf"
    return round(float(np.mean(values)), 8)


def build_summary(
    result_rows: dict[tuple[str, str], dict[str, str]],
    quality_rows: dict[str, dict[str, str]],
    image_ids: list[str],
    attacks: list[str],
    success_threshold: float,
    results_path: Path,
    quality_path: Path,
) -> dict[str, Any]:
    expected_keys = {
        (identifier, attack)
        for identifier in image_ids
        for attack in attacks
    }
    error_rows = [row for row in result_rows.values() if row["error"]]
    missing_keys = expected_keys - set(result_rows)
    quality_errors = [row for row in quality_rows.values() if row["error"]]
    missing_quality = set(image_ids) - set(quality_rows)
    complete = (
        not missing_keys
        and not error_rows
        and not missing_quality
        and not quality_errors
    )

    attack_summaries: dict[str, Any] = {}
    for attack in attacks:
        rows = [
            result_rows[(identifier, attack)]
            for identifier in image_ids
            if (identifier, attack) in result_rows
        ]
        valid = [row for row in rows if not row["error"]]
        attack_summaries[attack] = {
            "status": "complete" if len(valid) == len(image_ids) else "incomplete",
            "count": len(rows),
            "valid_count": len(valid),
            "error_count": len(rows) - len(valid),
            "primary_decoder": PRIMARY_DECODER,
            "mean_bit_error": _mean(valid, "bit_error_c"),
            "mean_bit_accuracy": _mean(valid, "bit_accuracy_c"),
            "mean_bit_error_rf": _mean(valid, "bit_error_rf"),
            "mean_bit_accuracy_rf": _mean(valid, "bit_accuracy_rf"),
            "mean_bit_error_c": _mean(valid, "bit_error_c"),
            "mean_bit_accuracy_c": _mean(valid, "bit_accuracy_c"),
            "mean_psnr": _mean(valid, "psnr"),
            "mean_ssim": _mean(valid, "ssim"),
            "success_rate": round(
                sum(row["success"] == "1" for row in valid) / len(valid),
                8,
            ) if valid else None,
        }

    valid_quality = [row for row in quality_rows.values() if not row["error"]]
    summary = {
        "project": "鉴源盾",
        "method": "SepMark",
        "mode": "real_checkpoint",
        "status": "complete" if complete else "incomplete",
        "data_type": "real_lfw_images",
        "requested_images": len(image_ids),
        "evaluated_rows": len(result_rows) - len(error_rows),
        "result_rows": len(result_rows),
        "expected_result_rows": len(expected_keys),
        "error_rows": len(error_rows),
        "missing_rows": len(missing_keys),
        "message_length": MSG_LEN,
        "message_derivation": "SHAKE256(sepmark-message.v1, seed, image_id)",
        "message_embedding_values": [-MESSAGE_RANGE, MESSAGE_RANGE],
        "primary_decoder": PRIMARY_DECODER,
        "secondary_decoder": SECONDARY_DECODER,
        "attacks": attack_summaries,
        "success_definition": (
            f"decoder_C bit_accuracy >= {success_threshold}; "
            "decoder_RF is reported independently and never changes success"
        ),
        "attacked_quality_reference": "original_preprocessed_image_vs_attacked_image",
        "watermarked_quality": {
            "status": "complete" if len(valid_quality) == len(image_ids) else "incomplete",
            "count": len(quality_rows),
            "valid_count": len(valid_quality),
            "error_count": len(quality_errors),
            "missing_count": len(missing_quality),
            "mean_psnr": _mean(valid_quality, "watermarked_psnr"),
            "mean_ssim": _mean(valid_quality, "watermarked_ssim"),
            "reference": "original_preprocessed_image_vs_watermarked_image",
            "csv_path": logical_path(quality_path),
            "csv_sha256": sha256_file(quality_path),
        },
        "results_csv_path": logical_path(results_path),
        "results_csv_sha256": sha256_file(results_path),
    }
    _assert_no_absolute_paths(summary, "summary")
    return summary


def _ordered_result_rows(
    rows: dict[tuple[str, str], dict[str, str]],
    image_ids: list[str],
    attacks: list[str],
) -> list[dict[str, str]]:
    return [
        rows[key]
        for identifier in image_ids
        for attack in attacks
        if (key := (identifier, attack)) in rows
    ]


def _ordered_quality_rows(
    rows: dict[str, dict[str, str]],
    image_ids: list[str],
) -> list[dict[str, str]]:
    return [rows[identifier] for identifier in image_ids if identifier in rows]


def _validate_dataset_manifest(
    manifest_path: Path,
    image_root: Path,
    images: list[Path],
    seed: int,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _assert_no_absolute_paths(manifest, "dataset_manifest")
    if manifest.get("schema_version") != "dataset-manifest.v1":
        raise ValueError("dataset manifest schema mismatch")
    if manifest.get("dataset_root") != logical_path(image_root):
        raise ValueError("dataset root changed since benchmark initialization")
    if manifest.get("seed") != seed or manifest.get("sample_count") != len(images):
        raise ValueError("dataset manifest selection changed")
    expected_files = [
        {
            "path": image_id(path, image_root),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in images
    ]
    if manifest.get("files") != expected_files:
        raise ValueError("dataset content changed since benchmark initialization")
    if manifest.get("files_digest_sha256") != _canonical_json_hash(expected_files):
        raise ValueError("dataset manifest digest mismatch")
    return manifest


def _ensure_run_config(
    path: Path,
    expected: dict[str, Any],
    result_state_exists: bool,
) -> None:
    _assert_no_absolute_paths(expected, "run_config")
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        _assert_no_absolute_paths(current, "existing_run_config")
        if current != expected:
            raise RuntimeError(
                "existing benchmark configuration does not match requested run"
            )
        return
    if result_state_exists:
        raise RuntimeError(
            "existing benchmark rows have no run_config.json; refusing to mix results"
        )
    _atomic_write_json(path, expected)


def checkpoint_selection_evidence(
    checkpoint: Path,
    checkpoint_hash: str,
) -> dict[str, Any]:
    """Bind the EC108 default to its frozen same-sample checkpoint comparison."""

    checkpoint = checkpoint.expanduser().resolve()
    default_checkpoint = DEFAULT_CHECKPOINT.expanduser().resolve()
    if checkpoint != default_checkpoint:
        return {
            "policy": "explicit_checkpoint_override",
            "auto_select_latest": False,
        }
    if checkpoint.name != "EC_108.pth" or checkpoint_hash != DEFAULT_CHECKPOINT_SHA256:
        raise RuntimeError("default EC108 checkpoint identity does not match frozen evidence")
    evidence_path = DEFAULT_SELECTION_EVIDENCE.expanduser().resolve()
    if not evidence_path.is_file():
        raise FileNotFoundError(
            f"default checkpoint selection evidence not found: {logical_path(evidence_path)}"
        )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    recommendation = evidence.get("recommended_checkpoint_for_full_lfw_evaluation", {})
    if (
        evidence.get("status") != "complete"
        or recommendation.get("epoch") != 108
        or recommendation.get("sha256") != checkpoint_hash
        or Path(str(recommendation.get("path", ""))).name != checkpoint.name
    ):
        raise RuntimeError("default EC108 selection evidence is inconsistent")
    return {
        "policy": "frozen_same_sample_checkpoint_comparison",
        "auto_select_latest": False,
        "selected_epoch": 108,
        "evidence_run_id": evidence.get("run_id"),
        "evidence_path": logical_path(evidence_path),
        "evidence_sha256": sha256_file(evidence_path),
    }


def _checkpoint_components(
    state: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for name in ("encoder", "decoder_C", "decoder_RF"):
        prefix = f"{name}."
        component = {
            key[len(prefix):]: value
            for key, value in state.items()
            if key.startswith(prefix)
        }
        if not component:
            raise RuntimeError(f"checkpoint lacks required {name} state")
        components[name] = component
    return components


def _load_sepmark_classes() -> tuple[type[Any], type[Any]]:
    network_dir = SEPMARK_CODE / "network"
    if not network_dir.is_dir():
        raise FileNotFoundError(
            f"SepMark source not found: {logical_path(SEPMARK_CODE)}"
        )

    package_name = "jys_sepmark_network"
    for module_name in list(sys.modules):
        if module_name == package_name or module_name.startswith(f"{package_name}."):
            del sys.modules[module_name]

    package = types.ModuleType(package_name)
    package.__path__ = [str(network_dir)]
    package.__package__ = package_name
    sys.modules[package_name] = package

    def load_submodule(name: str) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{name}",
            network_dir / f"{name}.py",
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load SepMark module: {name}")
        module = importlib.util.module_from_spec(spec)
        module.__package__ = package_name
        sys.modules[f"{package_name}.{name}"] = module
        spec.loader.exec_module(module)
        return module

    load_submodule("ResBlock")
    load_submodule("ConvBlock")
    init_spec = importlib.util.spec_from_file_location(
        package_name,
        network_dir / "__init__.py",
        submodule_search_locations=[str(network_dir)],
    )
    if init_spec is None or init_spec.loader is None:
        raise ImportError("cannot load SepMark network package")
    init_spec.loader.exec_module(package)
    encoder_module = load_submodule("Encoder_U")
    decoder_module = load_submodule("Decoder_U")
    return encoder_module.DW_Encoder, decoder_module.DW_Decoder


def _resolve_device(device_name: str) -> torch.device:
    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA device requested but CUDA is unavailable")
    return device


def _to_tensor(image: np.ndarray, device: torch.device) -> torch.Tensor:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("SepMark input must be HxWx3 uint8 RGB")
    tensor = torch.from_numpy(
        np.ascontiguousarray(image.transpose(2, 0, 1))
    ).to(device=device, dtype=torch.float32)
    return tensor.div(127.5).sub(1.0).unsqueeze(0)


def _to_uint8(tensor: torch.Tensor) -> np.ndarray:
    if tensor.ndim != 3 or tensor.shape[0] != 3:
        raise ValueError("SepMark output must be 3xHxW")
    array = (
        tensor.detach()
        .cpu()
        .clamp(-1, 1)
        .permute(1, 2, 0)
        .numpy()
        + 1.0
    ) * 127.5
    return np.clip(array + 0.5, 0, 255).astype(np.uint8)


class SepMarkCheckpointModel:
    def __init__(self, checkpoint: Path, device_name: str) -> None:
        checkpoint = checkpoint.expanduser().resolve()
        if not checkpoint.is_file():
            raise FileNotFoundError(
                f"checkpoint not found: {logical_path(checkpoint)}"
            )
        device = _resolve_device(device_name)
        encoder_class, decoder_class = _load_sepmark_classes()
        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if not isinstance(state, Mapping):
            raise TypeError("SepMark checkpoint must be a state-dict mapping")
        components = _checkpoint_components(state)

        encoder_attention = (
            "se" if any(".se." in key for key in components["encoder"]) else None
        )
        decoder_c_attention = (
            "se" if any(".se." in key for key in components["decoder_C"]) else None
        )
        decoder_rf_attention = (
            "se" if any(".se." in key for key in components["decoder_RF"]) else None
        )
        encoder = encoder_class(MSG_LEN, attention=encoder_attention)
        decoder_c = decoder_class(MSG_LEN, attention=decoder_c_attention)
        decoder_rf = decoder_class(MSG_LEN, attention=decoder_rf_attention)
        encoder.load_state_dict(components["encoder"], strict=True)
        decoder_c.load_state_dict(components["decoder_C"], strict=True)
        decoder_rf.load_state_dict(components["decoder_RF"], strict=True)

        self.checkpoint = checkpoint
        self.device = device
        self.encoder = encoder.to(device).eval()
        self.decoder_c = decoder_c.to(device).eval()
        self.decoder_rf = decoder_rf.to(device).eval()

    def encode(self, image: np.ndarray, message: np.ndarray) -> np.ndarray:
        if image.shape != (IMG_SIZE, IMG_SIZE, 3):
            raise ValueError(f"SepMark image shape must be {IMG_SIZE}x{IMG_SIZE}x3")
        bits = np.asarray(message, dtype=np.uint8).reshape(-1)
        if bits.shape != (MSG_LEN,) or not np.all((bits == 0) | (bits == 1)):
            raise ValueError(f"SepMark message must contain {MSG_LEN} binary bits")
        image_tensor = _to_tensor(image, self.device)
        message_values = (bits.astype(np.float32) * 2.0 - 1.0) * MESSAGE_RANGE
        message_tensor = torch.from_numpy(message_values).to(self.device).unsqueeze(0)
        with torch.inference_mode():
            encoded = self.encoder(image_tensor, message_tensor).clamp(-1, 1)
        return _to_uint8(encoded[0])

    def decode(self, image: np.ndarray) -> dict[str, np.ndarray]:
        if image.shape != (IMG_SIZE, IMG_SIZE, 3):
            raise ValueError(f"SepMark image shape must be {IMG_SIZE}x{IMG_SIZE}x3")
        image_tensor = _to_tensor(image, self.device)
        with torch.inference_mode():
            decoded_c = self.decoder_c(image_tensor)[0]
            decoded_rf = self.decoder_rf(image_tensor)[0]
        if decoded_c.numel() != MSG_LEN or decoded_rf.numel() != MSG_LEN:
            raise RuntimeError("SepMark decoder returned an unexpected message length")
        return {
            "decoder_C": decoded_c.detach().cpu().gt(0).numpy().astype(np.uint8),
            "decoder_RF": decoded_rf.detach().cpu().gt(0).numpy().astype(np.uint8),
        }


def build_model(checkpoint: Path, device_name: str) -> SepMarkCheckpointModel:
    return SepMarkCheckpointModel(checkpoint, device_name)


def _save_artifact(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image.astype(np.uint8)).save(path)


def _heatmap(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    difference = np.mean(
        np.abs(reference.astype(np.float32) - candidate.astype(np.float32)),
        axis=2,
    )
    difference = np.clip(
        difference / max(float(difference.max()), 1.0) * 255.0,
        0,
        255,
    ).astype(np.uint8)
    return cv2.cvtColor(
        cv2.applyColorMap(difference, cv2.COLORMAP_JET),
        cv2.COLOR_BGR2RGB,
    )


def make_grid(
    samples: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
    output_path: Path,
) -> None:
    if not samples:
        return
    tile = 160
    rows = min(6, len(samples))
    canvas = Image.new("RGB", (4 * tile, rows * tile), "white")
    labels = ["original", "watermarked", "attacked", "attack diff"]
    draw = ImageDraw.Draw(canvas)
    for row_index, sample in enumerate(samples[:rows]):
        for column_index, array in enumerate(sample):
            image = Image.fromarray(array).resize(
                (tile, tile),
                Image.Resampling.BICUBIC,
            )
            canvas.paste(image, (column_index * tile, row_index * tile))
            draw.text(
                (column_index * tile + 6, row_index * tile + 6),
                labels[column_index],
                fill=(255, 255, 255),
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def main() -> None:
    args = parse_args()
    if args.flush_every <= 0:
        raise ValueError("flush-every must be positive")
    if args.artifact_limit < 0:
        raise ValueError("artifact-limit must be non-negative")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in {":4096:8", ":16:8"}:
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 or :16:8")

    np.random.seed(args.seed % (2**32))
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)

    protocol = load_protocol()
    attacks = resolve_attacks(args.attacks, protocol)
    success_threshold = float(protocol["success_threshold"])
    model_contract = protocol["models"]["SepMark"]
    if model_contract.get("primary_decoder") != PRIMARY_DECODER:
        raise ValueError("SepMark primary decoder drift from evaluation protocol")
    if model_contract.get("secondary_decoder") != SECONDARY_DECODER:
        raise ValueError("SepMark secondary decoder drift from evaluation protocol")
    image_root = args.image_root.expanduser().resolve()
    images = list_images(image_root, args.num_images)
    if not images:
        raise RuntimeError("selected dataset is empty")
    image_ids = [image_id(path, image_root) for path in images]
    if len(image_ids) != len(set(image_ids)):
        raise RuntimeError("dataset-relative image IDs are not unique")

    checkpoint = args.checkpoint.expanduser().resolve()
    checkpoint_hash = sha256_file(checkpoint)
    if checkpoint_hash is None:
        raise FileNotFoundError(f"checkpoint not found: {logical_path(checkpoint)}")
    checkpoint_selection = checkpoint_selection_evidence(
        checkpoint,
        checkpoint_hash,
    )
    model = build_model(checkpoint, args.device)
    if model.checkpoint.expanduser().resolve() != checkpoint:
        raise RuntimeError("SepMark model did not bind the requested checkpoint")

    report_dir = args.report_dir.expanduser().resolve()
    asset_dir = args.asset_dir.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    results_path = report_dir / "results.csv"
    quality_path = report_dir / "watermarked_quality.csv"
    manifest_path = report_dir / "dataset_manifest.json"
    config_path = report_dir / "run_config.json"
    summary_path = report_dir / "summary.json"
    progress_path = report_dir / "progress.json"

    result_state_exists = results_path.exists() or quality_path.exists()
    if config_path.exists() and not manifest_path.exists():
        raise RuntimeError("run_config.json exists without dataset_manifest.json")
    if not manifest_path.exists():
        if result_state_exists:
            raise RuntimeError("existing benchmark rows have no dataset_manifest.json")
        build_dataset_manifest(
            image_root=image_root,
            images=images,
            output_path=manifest_path,
            seed=args.seed,
            selection=f"sorted_dataset_relative_path:first:{len(images)}",
        )
    dataset_manifest = _validate_dataset_manifest(
        manifest_path,
        image_root,
        images,
        args.seed,
    )
    manifest_hash = sha256_file(manifest_path)
    protocol_path = Path(protocol["_source_path"])
    protocol_hash = sha256_file(protocol_path)
    if manifest_hash is None or protocol_hash is None:
        raise RuntimeError("evidence input hash unavailable")

    run_config = {
        "schema_version": "sepmark-benchmark-config.v1",
        "method": "SepMark",
        "mode": "real_checkpoint",
        "protocol_version": protocol["schema_version"],
        "protocol_path": logical_path(protocol_path),
        "protocol_sha256": protocol_hash,
        "attack_ids": attacks,
        "attack_contract_sha256": attack_contract_hash(attacks, protocol),
        "model_contract_sha256": _canonical_json_hash(model_contract),
        "success_threshold": success_threshold,
        "success_definition": "decoder_C bit_accuracy >= success_threshold",
        "primary_decoder": PRIMARY_DECODER,
        "secondary_decoder": SECONDARY_DECODER,
        "seed": args.seed,
        "message_length": MSG_LEN,
        "message_range": MESSAGE_RANGE,
        "message_derivation": "SHAKE256(sepmark-message.v1, seed, image_id)",
        "bit_decision": "decoder output > 0",
        "determinism": {
            "torch_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cudnn_deterministic": True,
            "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        },
        "model_input_size": IMG_SIZE,
        "preprocessing": "RGB bicubic resize to 256x256, uint8 then [-1,1]",
        "image_root": logical_path(image_root),
        "sample_count": len(images),
        "dataset_files_digest_sha256": dataset_manifest["files_digest_sha256"],
        "dataset_manifest_path": logical_path(manifest_path),
        "dataset_manifest_sha256": manifest_hash,
        "checkpoint": logical_path(checkpoint),
        "checkpoint_sha256": checkpoint_hash,
        "checkpoint_selection": checkpoint_selection,
        "device": args.device,
        "asset_dir": logical_path(asset_dir),
        "artifact_limit": args.artifact_limit,
        "result_schema": RESULT_FIELDS,
        "watermarked_quality_schema": QUALITY_FIELDS,
    }
    _ensure_run_config(config_path, run_config, result_state_exists)

    expected_keys = {
        (identifier, attack)
        for identifier in image_ids
        for attack in attacks
    }
    result_rows = load_result_rows(
        results_path,
        expected_keys,
        args.seed,
        success_threshold,
    )
    quality_rows = load_quality_rows(quality_path, set(image_ids), args.seed)
    grid_samples: list[
        tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]
    ] = []
    started = time.time()

    def flush(processed: int, status: str = "running") -> None:
        _atomic_write_csv(
            results_path,
            RESULT_FIELDS,
            _ordered_result_rows(result_rows, image_ids, attacks),
        )
        _atomic_write_csv(
            quality_path,
            QUALITY_FIELDS,
            _ordered_quality_rows(quality_rows, image_ids),
        )
        summary = build_summary(
            result_rows,
            quality_rows,
            image_ids,
            attacks,
            success_threshold,
            results_path,
            quality_path,
        )
        if summary["status"] == "complete":
            summary["status"] = "auditing"
        _atomic_write_json(summary_path, summary)
        elapsed = max(0.0, time.time() - started)
        remaining = len(images) - processed
        eta = (elapsed / processed * remaining) if processed else None
        _atomic_write_json(progress_path, {
            "schema_version": "benchmark-progress.v1",
            "status": status,
            "processed_images": processed,
            "total_images": len(images),
            "result_rows": len(result_rows),
            "expected_result_rows": len(expected_keys),
            "error_rows": sum(bool(row["error"]) for row in result_rows.values()),
            "elapsed_s": round(elapsed, 3),
            "eta_s": round(eta, 3) if eta is not None else None,
            "updated_at": int(time.time()),
        })

    for index, path in enumerate(images):
        identifier = image_ids[index]
        target_keys = [
            (identifier, attack)
            for attack in attacks
            if (identifier, attack) not in result_rows
            or result_rows[(identifier, attack)]["error"]
        ]
        quality_pending = (
            identifier not in quality_rows or bool(quality_rows[identifier]["error"])
        )
        if not target_keys and not quality_pending:
            if (index + 1) % args.flush_every == 0:
                flush(index + 1)
            continue

        message = message_for_image(args.seed, identifier)
        bits = message_bits(message)
        message_hash = message_sha256(message)
        try:
            original = load_image(path)
            watermarked = np.asarray(model.encode(original, message))
            if watermarked.dtype != np.uint8:
                raise TypeError(
                    f"encoder returned dtype {watermarked.dtype}; expected uint8"
                )
            if watermarked.shape != original.shape:
                raise ValueError(
                    f"encoder returned shape {watermarked.shape}; expected {original.shape}"
                )
            watermarked_psnr, watermarked_ssim = compute_metrics(
                original,
                watermarked,
            )
            quality_rows[identifier] = {
                "image_id": identifier,
                "source_path": identifier,
                "message_bits": bits,
                "message_sha256": message_hash,
                "watermarked_psnr": _metric_text(watermarked_psnr),
                "watermarked_ssim": _metric_text(watermarked_ssim),
                "error": "",
            }
            if index < args.artifact_limit:
                sample_dir = asset_dir / f"sample_{index + 1:05d}"
                _save_artifact(sample_dir / "original.png", original)
                _save_artifact(sample_dir / "watermarked.png", watermarked)
        except Exception as exc:
            safe_error = _safe_error("encode", exc)
            if quality_pending:
                quality_rows[identifier] = {
                    "image_id": identifier,
                    "source_path": identifier,
                    "message_bits": bits,
                    "message_sha256": message_hash,
                    "watermarked_psnr": "",
                    "watermarked_ssim": "",
                    "error": safe_error,
                }
            for key in target_keys:
                result_rows[key] = {
                    "image_id": identifier,
                    "source_path": identifier,
                    "attack_type": key[1],
                    "attack_config_sha256": ATTACKS[key[1]].config_hash,
                    "message_bits": bits,
                    "message_sha256": message_hash,
                    "primary_decoder": PRIMARY_DECODER,
                    "bit_error_c": "",
                    "bit_accuracy_c": "",
                    "bit_error_rf": "",
                    "bit_accuracy_rf": "",
                    "psnr": "",
                    "ssim": "",
                    "success": "0",
                    "error": safe_error,
                }
            if (index + 1) % args.flush_every == 0:
                flush(index + 1)
            continue

        for key in target_keys:
            attack = key[1]
            try:
                attacked, attack_metadata = apply_attack(
                    watermarked,
                    attack,
                    image_id=identifier,
                    global_seed=args.seed,
                )
                if attack_metadata["config_hash"] != ATTACKS[attack].config_hash:
                    raise RuntimeError("shared attack metadata hash mismatch")
                decoded = model.decode(attacked)
                decoded_c = np.asarray(decoded["decoder_C"]).reshape(-1)
                decoded_rf = np.asarray(decoded["decoder_RF"]).reshape(-1)
                if decoded_c.shape != message.shape or decoded_rf.shape != message.shape:
                    raise ValueError(
                        "decoder output length does not match the embedded message"
                    )
                if decoded_c.dtype != np.uint8:
                    raise TypeError("decoder_C decisions must use uint8 dtype")
                if decoded_rf.dtype != np.uint8:
                    raise TypeError("decoder_RF decisions must use uint8 dtype")
                if not np.all((decoded_c == 0) | (decoded_c == 1)):
                    raise ValueError("decoder_C returned non-binary decisions")
                if not np.all((decoded_rf == 0) | (decoded_rf == 1)):
                    raise ValueError("decoder_RF returned non-binary decisions")
                ber_c = float(np.mean(decoded_c != message))
                ber_rf = float(np.mean(decoded_rf != message))
                accuracy_c = 1.0 - ber_c
                accuracy_rf = 1.0 - ber_rf
                attacked_psnr, attacked_ssim = compute_metrics(original, attacked)
                result_rows[key] = {
                    "image_id": identifier,
                    "source_path": identifier,
                    "attack_type": attack,
                    "attack_config_sha256": attack_metadata["config_hash"],
                    "message_bits": bits,
                    "message_sha256": message_hash,
                    "primary_decoder": PRIMARY_DECODER,
                    "bit_error_c": _metric_text(ber_c),
                    "bit_accuracy_c": _metric_text(accuracy_c),
                    "bit_error_rf": _metric_text(ber_rf),
                    "bit_accuracy_rf": _metric_text(accuracy_rf),
                    "psnr": _metric_text(attacked_psnr),
                    "ssim": _metric_text(attacked_ssim),
                    "success": "1" if accuracy_c >= success_threshold else "0",
                    "error": "",
                }
                if index < args.artifact_limit:
                    _save_artifact(
                        asset_dir / f"sample_{index + 1:05d}" / f"{attack}.png",
                        attacked,
                    )
                if args.artifact_limit > 0 and len(grid_samples) < 6 and attack in {
                    "clean",
                    "jpeg70",
                    "resize_0.5x",
                    "gaussian_noise_sigma_3",
                }:
                    grid_samples.append((
                        original,
                        watermarked,
                        attacked,
                        _heatmap(watermarked, attacked),
                    ))
            except Exception as exc:
                result_rows[key] = {
                    "image_id": identifier,
                    "source_path": identifier,
                    "attack_type": attack,
                    "attack_config_sha256": ATTACKS[attack].config_hash,
                    "message_bits": bits,
                    "message_sha256": message_hash,
                    "primary_decoder": PRIMARY_DECODER,
                    "bit_error_c": "",
                    "bit_accuracy_c": "",
                    "bit_error_rf": "",
                    "bit_accuracy_rf": "",
                    "psnr": "",
                    "ssim": "",
                    "success": "0",
                    "error": _safe_error("attack_or_decode", exc),
                }

        if (index + 1) % args.flush_every == 0:
            flush(index + 1)
            print(
                f"[{index + 1}/{len(images)}] rows={len(result_rows)}/{len(expected_keys)} "
                f"errors={sum(bool(row['error']) for row in result_rows.values())}",
                flush=True,
            )

    flush(len(images), status="auditing")
    result_rows = load_result_rows(
        results_path,
        expected_keys,
        args.seed,
        success_threshold,
    )
    quality_rows = load_quality_rows(quality_path, set(image_ids), args.seed)
    summary = build_summary(
        result_rows,
        quality_rows,
        image_ids,
        attacks,
        success_threshold,
        results_path,
        quality_path,
    )
    if summary["status"] != "complete":
        _atomic_write_json(summary_path, summary)
        flush(len(images), status="incomplete")
        print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
        raise SystemExit(2)

    summary = finalize_benchmark_summary(
        summary,
        model="SepMark",
        checkpoint=checkpoint,
        results_path=results_path,
        dataset_manifest_path=manifest_path,
        sample_count=len(images),
        seed=args.seed,
        attack_ids=attacks,
        command=sys.argv,
    )
    summary["primary_decoder"] = PRIMARY_DECODER
    summary["secondary_decoder"] = SECONDARY_DECODER
    summary["watermarked_quality_csv_path"] = logical_path(quality_path)
    summary["watermarked_quality_csv_sha256"] = sha256_file(quality_path)
    summary["run_config_path"] = logical_path(config_path)
    summary["run_config_sha256"] = sha256_file(config_path)
    _assert_no_absolute_paths(summary, "final_summary")
    _atomic_write_json(summary_path, summary)
    make_grid(grid_samples, asset_dir / "grid.png")
    _atomic_write_json(progress_path, {
        "schema_version": "benchmark-progress.v1",
        "status": "complete",
        "processed_images": len(images),
        "total_images": len(images),
        "result_rows": len(result_rows),
        "expected_result_rows": len(expected_keys),
        "error_rows": 0,
        "updated_at": int(time.time()),
    })
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
