from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import os
import re
import sys
import time
import types
from collections import Counter
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

from system.evaluation.attacks import (  # noqa: E402
    ATTACKS,
    apply_attack,
    derived_seed,
)
from system.evaluation.evidence import finalize_benchmark_summary  # noqa: E402
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


WAVEGUARD_CODE = MODEL_SOURCE_ROOT / "MEA/codes/WaveGuard"
DEFAULT_IMAGE_ROOT = DATA_ROOT / "lfw/processed/image/lfw_256"
DEFAULT_CHECKPOINT = (
    WEIGHT_ROOT
    / "MEA/models/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth"
)
DEFAULT_CHECKPOINT_SHA256 = (
    "cd093467a834cde47a0abed1d90a3ed62120092a2affcbcb1ed2f7d72b346377"
)
DEFAULT_REPORT_DIR = REPORT_ROOT / "waveguard_lfw_benchmark"
DEFAULT_ASSET_DIR = ASSET_ROOT / "waveguard_lfw_benchmark"
MSG_LEN = 30
IMG_SIZE = 256
MESSAGE_RANGE = 1.0
PRIMARY_DECODER = "tracer"
SECONDARY_DECODER = "detector"
IDENTITY_POLICY = "LFW filename stem without the trailing _dddd image ordinal"
IDENTITY_HASH_DOMAIN = "waveguard-lfw-identity.v1"
MESSAGE_DERIVATION = "SHAKE256(waveguard-message.v1, seed, image_id)"
RESULT_FIELDS = [
    "image_id",
    "source_path",
    "identity_sha256",
    "attack_type",
    "attack_config_sha256",
    "attack_derived_seed",
    "message_bits",
    "message_sha256",
    "primary_decoder",
    "bit_error_tracer",
    "bit_accuracy_tracer",
    "bit_error_detector",
    "bit_accuracy_detector",
    "psnr",
    "ssim",
    "success",
    "error",
]
QUALITY_FIELDS = [
    "image_id",
    "source_path",
    "identity_sha256",
    "message_bits",
    "message_sha256",
    "watermarked_psnr",
    "watermarked_ssim",
    "error",
]
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_LFW_IDENTITY = re.compile(r"^(?P<identity>.+)_(?P<ordinal>[0-9]{4})$")


def parse_args() -> argparse.Namespace:
    protocol = load_protocol()
    parser = argparse.ArgumentParser(
        description=(
            "Run the reproducible WaveGuard real-checkpoint benchmark on the "
            "complete 13,233-image LFW-256 dataset."
        ),
    )
    parser.add_argument("--num-images", type=int, default=13233)
    parser.add_argument(
        "--attacks",
        nargs="+",
        default=None,
        help=(
            "Canonical evaluation_protocol.v1 attack IDs; defaults to all "
            "15 registered attacks."
        ),
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
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def lfw_identity_label(identifier: str) -> str:
    stem = Path(identifier).stem
    match = _LFW_IDENTITY.fullmatch(stem)
    if match is None:
        raise ValueError(
            f"non-canonical LFW filename (expected Identity_0001): {identifier}"
        )
    return match.group("identity")


def identity_sha256(identifier: str) -> str:
    label = lfw_identity_label(identifier)
    payload = f"{IDENTITY_HASH_DOMAIN}\0{label}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_image(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        image = source.convert("RGB").resize(
            (IMG_SIZE, IMG_SIZE),
            Image.Resampling.BICUBIC,
        )
        return np.asarray(image, dtype=np.uint8).copy()


def message_for_image(seed: int, identifier: str, length: int = MSG_LEN) -> np.ndarray:
    """Derive a traversal- and resume-independent binary message per image."""

    if length <= 0:
        raise ValueError("message length must be positive")
    payload = f"waveguard-message.v1\0{seed}\0{identifier}".encode("utf-8")
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
    missing = [attack_id for attack_id in selected if attack_id not in ATTACKS]
    if missing:
        raise ValueError(
            "canonical attacks missing shared implementations: " + ", ".join(missing)
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
    if math.isinf(value):
        if value < 0:
            raise ValueError("negative infinity metric is not auditable")
        return "inf"
    return f"{value:.8f}"


def _safe_error(stage: str, error: BaseException) -> str:
    return f"{stage}:{type(error).__name__}"


def _manifest_body(
    image_root: Path,
    images: list[Path],
    seed: int,
) -> dict[str, Any]:
    identifiers = [image_id(path, image_root) for path in images]
    identity_hashes = [identity_sha256(identifier) for identifier in identifiers]
    files = [
        {
            "path": identifier,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "identity_sha256": identity_hash,
        }
        for path, identifier, identity_hash in zip(
            images,
            identifiers,
            identity_hashes,
            strict=True,
        )
    ]
    if any(entry["sha256"] is None for entry in files):
        raise RuntimeError("dataset file hash unavailable")
    counts = Counter(identity_hashes)
    identity_distribution = [
        {"identity_sha256": digest, "image_count": counts[digest]}
        for digest in sorted(counts)
    ]
    return {
        "schema_version": "waveguard-dataset-manifest.v1",
        "dataset_root": logical_path(image_root),
        "selection": f"sorted_dataset_relative_path:first:{len(images)}",
        "seed": seed,
        "sample_count": len(images),
        "identity_policy": IDENTITY_POLICY,
        "identity_hash_domain": IDENTITY_HASH_DOMAIN,
        "unique_identity_count": len(counts),
        "identity_distribution": identity_distribution,
        "identity_distribution_sha256": _canonical_json_hash(identity_distribution),
        "files": files,
        "files_digest_sha256": _canonical_json_hash(files),
    }


def build_dataset_manifest(
    *,
    image_root: Path,
    images: list[Path],
    output_path: Path,
    seed: int,
) -> dict[str, Any]:
    payload = {
        **_manifest_body(image_root, images, seed),
        "generated_at": int(time.time()),
    }
    _assert_no_absolute_paths(payload, "dataset_manifest")
    _atomic_write_json(output_path, payload)
    return payload


def _validate_dataset_manifest(
    manifest_path: Path,
    image_root: Path,
    images: list[Path],
    seed: int,
) -> dict[str, Any]:
    current = json.loads(manifest_path.read_text(encoding="utf-8"))
    _assert_no_absolute_paths(current, "dataset_manifest")
    generated_at = current.get("generated_at")
    if not isinstance(generated_at, int) or generated_at < 0:
        raise ValueError("dataset manifest generated_at is invalid")
    expected = {
        **_manifest_body(image_root, images, seed),
        "generated_at": generated_at,
    }
    if current != expected:
        raise ValueError("dataset manifest does not match current dataset evidence")
    return current


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
        if row["identity_sha256"] != identity_sha256(row["image_id"]):
            raise ValueError(f"identity hash mismatch: {key}")
        if row["primary_decoder"] != PRIMARY_DECODER:
            raise ValueError(f"primary decoder mismatch: {key}")
        expected_message = message_for_image(seed, row["image_id"])
        if row["message_bits"] != message_bits(expected_message):
            raise ValueError(f"message derivation mismatch: {key}")
        if row["message_sha256"] != message_sha256(expected_message):
            raise ValueError(f"message hash mismatch: {key}")
        if row["attack_config_sha256"] != ATTACKS[row["attack_type"]].config_hash:
            raise ValueError(f"attack configuration mismatch: {key}")
        expected_attack_seed = str(derived_seed(seed, row["image_id"], row["attack_type"]))
        if row["attack_derived_seed"] != expected_attack_seed:
            raise ValueError(f"attack seed mismatch: {key}")

        metric_fields = (
            "bit_error_tracer",
            "bit_accuracy_tracer",
            "bit_error_detector",
            "bit_accuracy_detector",
            "psnr",
            "ssim",
        )
        if row["error"]:
            if any(row[field] for field in metric_fields):
                raise ValueError(f"error row contains metrics: {key}")
            if row["success"] != "0":
                raise ValueError(f"error row marked successful: {key}")
        else:
            ber_tracer = _float(row, "bit_error_tracer")
            accuracy_tracer = _float(row, "bit_accuracy_tracer")
            ber_detector = _float(row, "bit_error_detector")
            accuracy_detector = _float(row, "bit_accuracy_detector")
            psnr = _float(row, "psnr")
            ssim = _float(row, "ssim")
            for decoder, ber, accuracy in (
                (PRIMARY_DECODER, ber_tracer, accuracy_tracer),
                (SECONDARY_DECODER, ber_detector, accuracy_detector),
            ):
                if not 0.0 <= ber <= 1.0 or not 0.0 <= accuracy <= 1.0:
                    raise ValueError(f"{decoder} metric outside [0,1]: {key}")
                if abs((1.0 - ber) - accuracy) > 1e-7:
                    raise ValueError(f"{decoder} metric identity failed: {key}")
            if psnr == -math.inf or not -1.0 <= ssim <= 1.0:
                raise ValueError(f"invalid attacked-quality metric: {key}")
            expected_success = "1" if accuracy_tracer >= success_threshold else "0"
            if row["success"] != expected_success:
                raise ValueError(f"tracer success threshold mismatch: {key}")
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
        if row["identity_sha256"] != identity_sha256(identifier):
            raise ValueError(f"watermarked identity hash mismatch: {identifier}")
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


def _mean(rows: Iterable[dict[str, str]], field: str) -> float | str | None:
    values = [float(row[field]) for row in rows if not row["error"] and row[field]]
    if not values:
        return None
    if any(math.isnan(value) or value == -math.inf for value in values):
        raise ValueError(f"non-finite aggregate input: {field}")
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
    dataset_manifest: dict[str, Any],
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
            "mean_bit_error": _mean(valid, "bit_error_tracer"),
            "mean_bit_accuracy": _mean(valid, "bit_accuracy_tracer"),
            "mean_bit_error_tracer": _mean(valid, "bit_error_tracer"),
            "mean_bit_accuracy_tracer": _mean(valid, "bit_accuracy_tracer"),
            "mean_bit_error_detector": _mean(valid, "bit_error_detector"),
            "mean_bit_accuracy_detector": _mean(valid, "bit_accuracy_detector"),
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
        "method": "WaveGuard",
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
        "message_derivation": MESSAGE_DERIVATION,
        "message_embedding_values": [-MESSAGE_RANGE, MESSAGE_RANGE],
        "primary_decoder": PRIMARY_DECODER,
        "secondary_decoder": SECONDARY_DECODER,
        "attacks": attack_summaries,
        "success_definition": (
            f"tracer bit_accuracy >= {success_threshold}; detector is reported "
            "independently and never changes success"
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
        "dataset_identity_evidence": {
            "policy": dataset_manifest["identity_policy"],
            "hash_domain": dataset_manifest["identity_hash_domain"],
            "unique_identity_count": dataset_manifest["unique_identity_count"],
            "identity_distribution_sha256": dataset_manifest[
                "identity_distribution_sha256"
            ],
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


def _ensure_run_config(
    path: Path,
    expected: dict[str, Any],
    preexisting_state: bool,
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
    if preexisting_state:
        raise RuntimeError(
            "existing benchmark state has no run_config.json; refusing to mix results"
        )
    _atomic_write_json(path, expected)


def checkpoint_selection_evidence(
    checkpoint: Path,
    checkpoint_hash: str,
) -> dict[str, Any]:
    checkpoint = checkpoint.expanduser().resolve()
    if checkpoint == DEFAULT_CHECKPOINT.expanduser().resolve():
        if checkpoint.name != "model_state_16.pth":
            raise RuntimeError("fixed WaveGuard checkpoint filename drift")
        if checkpoint_hash != DEFAULT_CHECKPOINT_SHA256:
            raise RuntimeError("fixed WaveGuard checkpoint SHA-256 mismatch")
        return {
            "policy": "fixed_content_addressed_checkpoint",
            "auto_select_latest": False,
            "checkpoint_sha256": checkpoint_hash,
        }
    return {
        "policy": "explicit_checkpoint_override",
        "auto_select_latest": False,
        "checkpoint_sha256": checkpoint_hash,
    }


def _checkpoint_components(
    state: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for name in ("encoder", "decoder_t", "decoder_d"):
        prefix = f"{name}."
        component = {
            key[len(prefix):]: value
            for key, value in state.items()
            if isinstance(key, str) and key.startswith(prefix)
        }
        if not component:
            raise RuntimeError(f"checkpoint lacks required {name} state")
        components[name] = component
    unexpected = [
        key
        for key in state
        if not isinstance(key, str)
        or not key.startswith(("encoder.", "decoder_t.", "decoder_d.", "gnn."))
    ]
    if unexpected:
        raise RuntimeError("checkpoint contains unexpected state namespace")
    return components


def _load_waveguard_classes() -> tuple[Any, type[Any], type[Any]]:
    if not WAVEGUARD_CODE.is_dir():
        raise FileNotFoundError(
            f"WaveGuard source not found: {logical_path(WAVEGUARD_CODE)}"
        )
    collision_roots = ("config", "network", "utils", "pytorch_ssim")
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name in collision_roots
        or name.startswith(tuple(f"{root}." for root in collision_roots))
    }
    saved_thop = sys.modules.get("thop")
    for name in saved_modules:
        del sys.modules[name]
    if importlib.util.find_spec("thop") is None:
        # WaveGuard's SimAM module imports THOP's profiler but never calls it
        # during construction or inference.  Isolate that training-only symbol
        # so the numerical inference graph has no undeclared runtime dependency.
        thop_module = types.ModuleType("thop")

        def unavailable_profile(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("THOP profiling is outside the benchmark graph")

        thop_module.profile = unavailable_profile
        sys.modules["thop"] = thop_module
    old_cwd = Path.cwd()
    inserted = str(WAVEGUARD_CODE) not in sys.path
    if inserted:
        sys.path.insert(0, str(WAVEGUARD_CODE))
    try:
        os.chdir(WAVEGUARD_CODE)
        importlib.invalidate_caches()
        config_module = importlib.import_module("config")
        encoder_module = importlib.import_module("network.encoder")
        decoder_module = importlib.import_module("network.decoder")
        cfg = config_module.training_config
        encoder_class = encoder_module.Encoder
        decoder_class = decoder_module.Decoder
    finally:
        os.chdir(old_cwd)
        for name in list(sys.modules):
            if name in collision_roots or name.startswith(
                tuple(f"{root}." for root in collision_roots)
            ):
                del sys.modules[name]
        sys.modules.update(saved_modules)
        if saved_thop is None:
            sys.modules.pop("thop", None)
        else:
            sys.modules["thop"] = saved_thop
        if inserted:
            sys.path.remove(str(WAVEGUARD_CODE))
    return cfg, encoder_class, decoder_class


def _resolve_device(device_name: str) -> torch.device:
    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA device requested but CUDA is unavailable")
    return device


def _rgb_to_yuv_tensor(image: np.ndarray, device: torch.device) -> torch.Tensor:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("WaveGuard input must be HxWx3 uint8 RGB")
    yuv = cv2.cvtColor(image, cv2.COLOR_RGB2YUV).astype(np.float32)
    tensor = torch.from_numpy(
        np.ascontiguousarray((yuv / 127.5 - 1.0).transpose(2, 0, 1))
    )
    return tensor.to(device=device, dtype=torch.float32).unsqueeze(0)


def _yuv_tensor_to_rgb(tensor: torch.Tensor) -> np.ndarray:
    if tensor.ndim != 4 or tensor.shape[0] != 1 or tensor.shape[1] != 3:
        raise ValueError("WaveGuard YUV output must have shape 1x3xHxW")
    yuv = (
        (tensor.detach().cpu()[0].permute(1, 2, 0).numpy() + 1.0) * 127.5
    )
    yuv_u8 = np.clip(yuv, 0, 255).astype(np.uint8)
    return cv2.cvtColor(yuv_u8, cv2.COLOR_YUV2RGB)


class WaveGuardCheckpointModel:
    def __init__(self, checkpoint: Path, device_name: str) -> None:
        checkpoint = checkpoint.expanduser().resolve()
        if not checkpoint.is_file():
            raise FileNotFoundError(
                f"checkpoint not found: {logical_path(checkpoint)}"
            )
        device = _resolve_device(device_name)
        cfg, encoder_class, decoder_class = _load_waveguard_classes()
        if int(cfg.message_length) != MSG_LEN:
            raise RuntimeError("WaveGuard source message length drift")
        if int(cfg.image_size) != IMG_SIZE:
            raise RuntimeError("WaveGuard source image size drift")
        if float(cfg.message_range) != MESSAGE_RANGE:
            raise RuntimeError("WaveGuard source message range drift")
        cfg.device = str(device)

        state = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if not isinstance(state, Mapping):
            raise TypeError("WaveGuard checkpoint must be a state-dict mapping")
        components = _checkpoint_components(state)
        encoder = encoder_class()
        decoder_t = decoder_class(type="tracer")
        decoder_d = decoder_class(type="detector")
        encoder.load_state_dict(components["encoder"], strict=True)
        decoder_t.load_state_dict(components["decoder_t"], strict=True)
        decoder_d.load_state_dict(components["decoder_d"], strict=True)

        from pytorch_wavelets import DTCWTForward, DTCWTInverse

        self.checkpoint = checkpoint
        self.device = device
        self.encoder = encoder.to(device).eval()
        self.decoder_t = decoder_t.to(device).eval()
        self.decoder_d = decoder_d.to(device).eval()
        self.forward_wavelet = DTCWTForward(
            J=2,
            biort="near_sym_b",
            qshift="qshift_b",
        ).to(device).eval()
        self.inverse_wavelet = DTCWTInverse(
            biort="near_sym_b",
            qshift="qshift_b",
        ).to(device).eval()
        self.indices_encoder = torch.tensor([0, 2], device=device)
        self.indices_tracer = torch.tensor([0, 2, 3, 5], device=device)
        self.indices_detector = torch.tensor([0, 2], device=device)
        self.checkpoint_component_key_counts = {
            name: len(component) for name, component in components.items()
        }

    def encode(self, image: np.ndarray, message: np.ndarray) -> np.ndarray:
        if image.shape != (IMG_SIZE, IMG_SIZE, 3):
            raise ValueError(f"WaveGuard image shape must be {IMG_SIZE}x{IMG_SIZE}x3")
        bits = np.asarray(message, dtype=np.uint8).reshape(-1)
        if bits.shape != (MSG_LEN,) or not np.all((bits == 0) | (bits == 1)):
            raise ValueError(f"WaveGuard message must contain {MSG_LEN} binary bits")
        image_tensor = _rgb_to_yuv_tensor(image, self.device)
        message_values = (bits.astype(np.float32) * 2.0 - 1.0) * MESSAGE_RANGE
        message_tensor = torch.from_numpy(message_values).to(self.device).unsqueeze(0)
        with torch.inference_mode():
            y, u, v = image_tensor[:, [0]], image_tensor[:, [1]], image_tensor[:, [2]]
            low_pass, high_pass = self.forward_wavelet(u)
            high_pass = list(high_pass)
            high_pass[1] = high_pass[1].clone()
            selected = torch.index_select(
                high_pass[1],
                2,
                self.indices_encoder,
            )[:, :, :, :, :, 0].squeeze(1)
            embedded = self.encoder(selected, message_tensor).unsqueeze(1)
            high_pass[1][:, :, self.indices_encoder, :, :, 0] = embedded
            embedded_u = self.inverse_wavelet((low_pass, high_pass))
            watermarked = torch.cat([y, embedded_u, v], dim=1).clamp(-1, 1)
        return _yuv_tensor_to_rgb(watermarked)

    def decode(self, image: np.ndarray) -> dict[str, np.ndarray]:
        if image.shape != (IMG_SIZE, IMG_SIZE, 3):
            raise ValueError(f"WaveGuard image shape must be {IMG_SIZE}x{IMG_SIZE}x3")
        image_tensor = _rgb_to_yuv_tensor(image, self.device)
        with torch.inference_mode():
            _, high_pass = self.forward_wavelet(image_tensor[:, [1]])
            selected_t = torch.index_select(
                high_pass[1],
                2,
                self.indices_tracer,
            )[:, :, :, :, :, 0].squeeze(1)
            selected_d = torch.index_select(
                high_pass[1],
                2,
                self.indices_detector,
            )[:, :, :, :, :, 0].squeeze(1)
            decoded_t = self.decoder_t(selected_t)[0]
            decoded_d = self.decoder_d(selected_d)[0]
        if decoded_t.numel() != MSG_LEN or decoded_d.numel() != MSG_LEN:
            raise RuntimeError("WaveGuard decoder returned an unexpected message length")
        return {
            PRIMARY_DECODER: decoded_t.detach().cpu().gt(0).numpy().astype(np.uint8),
            SECONDARY_DECODER: decoded_d.detach().cpu().gt(0).numpy().astype(np.uint8),
        }


def build_model(checkpoint: Path, device_name: str) -> WaveGuardCheckpointModel:
    return WaveGuardCheckpointModel(checkpoint, device_name)


def _save_artifact(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = image.astype(np.uint8)
    if path.exists():
        with Image.open(path) as existing:
            existing_array = np.asarray(existing.convert("RGB"), dtype=np.uint8)
        if not np.array_equal(existing_array, candidate):
            raise RuntimeError(f"existing artifact differs: {logical_path(path)}")
        return
    Image.fromarray(candidate).save(path)


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
    candidate = np.asarray(canvas, dtype=np.uint8)
    _save_artifact(output_path, candidate)


def build_artifact_manifest(asset_dir: Path, output_path: Path) -> dict[str, Any]:
    files = []
    if asset_dir.is_dir():
        for path in sorted(
            (candidate for candidate in asset_dir.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(asset_dir).as_posix(),
        ):
            if path.resolve() == output_path.resolve():
                continue
            digest = sha256_file(path)
            if digest is None:
                raise RuntimeError("artifact hash unavailable")
            files.append({
                "path": path.relative_to(asset_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": digest,
            })
    payload = {
        "schema_version": "benchmark-artifact-manifest.v1",
        "asset_root": logical_path(asset_dir),
        "file_count": len(files),
        "files": files,
        "files_digest_sha256": _canonical_json_hash(files),
    }
    _assert_no_absolute_paths(payload, "artifact_manifest")
    _atomic_write_json(output_path, payload)
    return payload


def _result_row_base(
    identifier: str,
    attack: str,
    bits: str,
    message_hash: str,
    seed: int,
) -> dict[str, str]:
    return {
        "image_id": identifier,
        "source_path": identifier,
        "identity_sha256": identity_sha256(identifier),
        "attack_type": attack,
        "attack_config_sha256": ATTACKS[attack].config_hash,
        "attack_derived_seed": str(derived_seed(seed, identifier, attack)),
        "message_bits": bits,
        "message_sha256": message_hash,
        "primary_decoder": PRIMARY_DECODER,
    }


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
    model_contract = protocol["models"]["WaveGuard"]
    if model_contract.get("primary_decoder") != PRIMARY_DECODER:
        raise ValueError("WaveGuard primary decoder drift from evaluation protocol")
    if model_contract.get("secondary_decoder") != SECONDARY_DECODER:
        raise ValueError("WaveGuard secondary decoder drift from evaluation protocol")

    image_root = args.image_root.expanduser().resolve()
    images = list_images(image_root, args.num_images)
    if not images:
        raise RuntimeError("selected dataset is empty")
    image_ids = [image_id(path, image_root) for path in images]
    if len(image_ids) != len(set(image_ids)):
        raise RuntimeError("dataset-relative image IDs are not unique")
    for identifier in image_ids:
        lfw_identity_label(identifier)

    checkpoint = args.checkpoint.expanduser().resolve()
    checkpoint_hash = sha256_file(checkpoint)
    if checkpoint_hash is None:
        raise FileNotFoundError(f"checkpoint not found: {logical_path(checkpoint)}")
    checkpoint_selection = checkpoint_selection_evidence(checkpoint, checkpoint_hash)

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
    artifact_manifest_path = report_dir / "artifact_manifest.json"
    state_paths = (
        results_path,
        quality_path,
        manifest_path,
        config_path,
        summary_path,
        progress_path,
        artifact_manifest_path,
    )
    preexisting_state = any(path.exists() for path in state_paths)
    if config_path.exists() and not manifest_path.exists():
        raise RuntimeError("run_config.json exists without dataset_manifest.json")
    if not manifest_path.exists():
        if preexisting_state:
            raise RuntimeError(
                "existing benchmark state has no dataset_manifest.json; refusing overwrite"
            )
        build_dataset_manifest(
            image_root=image_root,
            images=images,
            output_path=manifest_path,
            seed=args.seed,
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
        "schema_version": "waveguard-benchmark-config.v1",
        "method": "WaveGuard",
        "mode": "real_checkpoint",
        "protocol_version": protocol["schema_version"],
        "protocol_path": logical_path(protocol_path),
        "protocol_sha256": protocol_hash,
        "attack_ids": attacks,
        "attack_contract_sha256": attack_contract_hash(attacks, protocol),
        "model_contract_sha256": _canonical_json_hash(model_contract),
        "success_threshold": success_threshold,
        "success_definition": "tracer bit_accuracy >= success_threshold",
        "primary_decoder": PRIMARY_DECODER,
        "secondary_decoder": SECONDARY_DECODER,
        "seed": args.seed,
        "message_length": MSG_LEN,
        "message_range": MESSAGE_RANGE,
        "message_derivation": MESSAGE_DERIVATION,
        "bit_decision": "decoder output > 0",
        "determinism": {
            "torch_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cudnn_deterministic": True,
            "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        },
        "checkpoint_loading": {
            "torch_weights_only": True,
            "encoder_strict": True,
            "tracer_strict": True,
            "detector_strict": True,
            "ignored_training_component": "gnn",
        },
        "model_input_size": IMG_SIZE,
        "preprocessing": "RGB bicubic resize to 256x256; OpenCV RGB-to-YUV; [-1,1]",
        "image_root": logical_path(image_root),
        "sample_count": len(images),
        "dataset_files_digest_sha256": dataset_manifest["files_digest_sha256"],
        "dataset_manifest_path": logical_path(manifest_path),
        "dataset_manifest_sha256": manifest_hash,
        "identity_policy": IDENTITY_POLICY,
        "identity_hash_domain": IDENTITY_HASH_DOMAIN,
        "unique_identity_count": dataset_manifest["unique_identity_count"],
        "identity_distribution_sha256": dataset_manifest[
            "identity_distribution_sha256"
        ],
        "checkpoint": logical_path(checkpoint),
        "checkpoint_sha256": checkpoint_hash,
        "checkpoint_selection": checkpoint_selection,
        "device": args.device,
        "asset_dir": logical_path(asset_dir),
        "artifact_limit": args.artifact_limit,
        "result_schema": RESULT_FIELDS,
        "watermarked_quality_schema": QUALITY_FIELDS,
    }
    _ensure_run_config(config_path, run_config, preexisting_state)

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
    model = build_model(checkpoint, args.device)
    if model.checkpoint.expanduser().resolve() != checkpoint:
        raise RuntimeError("WaveGuard model did not bind the requested checkpoint")

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
            dataset_manifest,
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
        identity_hash = identity_sha256(identifier)
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
            if quality_pending:
                watermarked_psnr, watermarked_ssim = compute_metrics(
                    original,
                    watermarked,
                )
                quality_rows[identifier] = {
                    "image_id": identifier,
                    "source_path": identifier,
                    "identity_sha256": identity_hash,
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
                    "identity_sha256": identity_hash,
                    "message_bits": bits,
                    "message_sha256": message_hash,
                    "watermarked_psnr": "",
                    "watermarked_ssim": "",
                    "error": safe_error,
                }
            for key in target_keys:
                result_rows[key] = {
                    **_result_row_base(
                        identifier,
                        key[1],
                        bits,
                        message_hash,
                        args.seed,
                    ),
                    "bit_error_tracer": "",
                    "bit_accuracy_tracer": "",
                    "bit_error_detector": "",
                    "bit_accuracy_detector": "",
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
                if attack_metadata["derived_seed"] != derived_seed(
                    args.seed,
                    identifier,
                    attack,
                ):
                    raise RuntimeError("shared attack seed mismatch")
                decoded = model.decode(attacked)
                decoded_tracer = np.asarray(decoded[PRIMARY_DECODER]).reshape(-1)
                decoded_detector = np.asarray(decoded[SECONDARY_DECODER]).reshape(-1)
                for decoder_name, decoded_bits in (
                    (PRIMARY_DECODER, decoded_tracer),
                    (SECONDARY_DECODER, decoded_detector),
                ):
                    if decoded_bits.shape != message.shape:
                        raise ValueError(
                            f"{decoder_name} output length does not match message"
                        )
                    if decoded_bits.dtype != np.uint8:
                        raise TypeError(f"{decoder_name} decisions must use uint8 dtype")
                    if not np.all((decoded_bits == 0) | (decoded_bits == 1)):
                        raise ValueError(f"{decoder_name} returned non-binary decisions")
                ber_tracer = float(np.mean(decoded_tracer != message))
                ber_detector = float(np.mean(decoded_detector != message))
                accuracy_tracer = 1.0 - ber_tracer
                accuracy_detector = 1.0 - ber_detector
                attacked_psnr, attacked_ssim = compute_metrics(original, attacked)
                result_rows[key] = {
                    **_result_row_base(
                        identifier,
                        attack,
                        bits,
                        message_hash,
                        args.seed,
                    ),
                    "bit_error_tracer": _metric_text(ber_tracer),
                    "bit_accuracy_tracer": _metric_text(accuracy_tracer),
                    "bit_error_detector": _metric_text(ber_detector),
                    "bit_accuracy_detector": _metric_text(accuracy_detector),
                    "psnr": _metric_text(attacked_psnr),
                    "ssim": _metric_text(attacked_ssim),
                    "success": "1" if accuracy_tracer >= success_threshold else "0",
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
                    **_result_row_base(
                        identifier,
                        attack,
                        bits,
                        message_hash,
                        args.seed,
                    ),
                    "bit_error_tracer": "",
                    "bit_accuracy_tracer": "",
                    "bit_error_detector": "",
                    "bit_accuracy_detector": "",
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
        dataset_manifest,
    )
    if summary["status"] != "complete":
        _atomic_write_json(summary_path, summary)
        flush(len(images), status="incomplete")
        print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
        raise SystemExit(2)

    summary = finalize_benchmark_summary(
        summary,
        model="WaveGuard",
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
    summary["runner_path"] = logical_path(Path(__file__))
    summary["runner_sha256"] = sha256_file(Path(__file__))
    compatibility_path = Path(__file__).with_name(
        "run_waveguard_lfw_small_benchmark.py"
    )
    if compatibility_path.is_file():
        summary["compatibility_entrypoint_path"] = logical_path(compatibility_path)
        summary["compatibility_entrypoint_sha256"] = sha256_file(compatibility_path)

    make_grid(grid_samples, asset_dir / "grid.png")
    artifact_manifest = build_artifact_manifest(asset_dir, artifact_manifest_path)
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
    summary["artifact_manifest_path"] = logical_path(artifact_manifest_path)
    summary["artifact_manifest_sha256"] = sha256_file(artifact_manifest_path)
    summary["artifact_files_digest_sha256"] = artifact_manifest[
        "files_digest_sha256"
    ]
    summary["progress_path"] = logical_path(progress_path)
    summary["progress_sha256"] = sha256_file(progress_path)
    _assert_no_absolute_paths(summary, "final_summary")
    _atomic_write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
