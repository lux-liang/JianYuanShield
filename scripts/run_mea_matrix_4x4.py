#!/usr/bin/env python3
"""Run the frozen four-model, double-embedding MEA evidence matrix."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
from PIL import Image


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))

from system.evaluation.protocol import load_protocol  # noqa: E402
from system.evaluation.runtime import (  # noqa: E402
    DATA_ROOT,
    REPORT_ROOT,
    logical_path,
)


TARGET_MODELS = ("LIDMark", "KAD-Net", "SepMark", "WaveGuard")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SAMPLE_DOMAIN = "jys-mea-sample.v1"
IMAGE_ID_DOMAIN = "jys-mea-image.v1"
MESSAGE_DOMAIN = "jys-mea-message.v1"
MANIFEST_SCHEMA = "mea-shared-dataset-manifest.v1"
CONFIG_SCHEMA = "mea-matrix-run-config.v1"
RAW_SCHEMA = "mea-matrix-raw.v1"
PROGRESS_SCHEMA = "mea-matrix-progress.v1"
SUMMARY_SCHEMA = "mea-matrix-summary.v1"

RAW_FIELDS = [
    "raw_schema_version",
    "row_id",
    "cell_id",
    "source_model",
    "attacker_model",
    "sample_index",
    "image_id",
    "source_path",
    "protocol_sha256",
    "protocol_seed",
    "success_threshold",
    "dataset_manifest_sha256",
    "run_config_sha256",
    "source_checkpoint_sha256",
    "attacker_checkpoint_sha256",
    "source_primary_decoder",
    "attacker_primary_decoder",
    "source_message_length",
    "source_message_bits",
    "source_message_sha256",
    "attacker_message_length",
    "attacker_message_bits",
    "attacker_message_sha256",
    "source_decoded_bits",
    "source_decoded_sha256",
    "attacker_decoded_bits",
    "attacker_decoded_sha256",
    "source_bit_errors",
    "source_ber",
    "source_bit_accuracy",
    "source_exact_match",
    "source_success",
    "attacker_bit_errors",
    "attacker_ber",
    "attacker_bit_accuracy",
    "attacker_exact_match",
    "attacker_success",
    "first_embedding_psnr",
    "first_embedding_ssim",
    "second_vs_original_psnr",
    "second_vs_original_ssim",
    "second_vs_first_psnr",
    "second_vs_first_ssim",
    "status",
    "error_stage",
    "error_type",
    "error",
]

EVIDENCE_FILES = (
    "dataset_manifest.json",
    "run_config.json",
    "raw_results.csv",
    "progress.json",
    "summary.json",
)
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_EMBEDDED_POSIX_ABSOLUTE = re.compile(r"(^|[\s\"'(=])/(?!/)[^\s\"')]*")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images-per-cell",
        type=int,
        default=256,
        help="Number of content-addressed shared images in each of the 16 cells.",
    )
    parser.add_argument(
        "--image-root",
        type=Path,
        default=DATA_ROOT / "lfw/processed/image/lfw_256",
        help="Shared RGB input directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORT_ROOT / "mea_4x4",
        help="Unique evidence run directory.",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        help="Frozen evaluation protocol JSON.",
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("JYS_INFER_DEVICE", "cuda:0"),
        help="Inference device exposed to all four adapters.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume only when manifest and run_config match byte-for-byte semantics.",
    )
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def formatted_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _contains_absolute_path(value: str) -> bool:
    return bool(
        value.startswith(("/", "\\\\"))
        or _WINDOWS_ABSOLUTE.match(value)
        or _EMBEDDED_POSIX_ABSOLUTE.search(value)
        or re.search(r"(?:^|[\s\"'(=])[A-Za-z]:[\\/]", value)
        or re.search(r"(?:^|[\s\"'(=])\\\\[^\\\s]+\\", value)
    )


def assert_no_absolute_paths(value: Any, label: str = "artifact") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert_no_absolute_paths(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_no_absolute_paths(item, f"{label}[{index}]")
    elif isinstance(value, str) and _contains_absolute_path(value):
        raise ValueError(f"absolute host path rejected at {label}")


def safe_error(exc: BaseException) -> str:
    message = " ".join(str(exc).split())[:500]
    if not message:
        return "no_error_details"
    if _contains_absolute_path(message):
        return "details_redacted_absolute_path"
    return message


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    assert_no_absolute_paths(value, path.name)
    atomic_write_bytes(path, formatted_json_bytes(value))


def atomic_write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    for index, row in enumerate(rows):
        assert_no_absolute_paths(row, f"raw_results[{index}]")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=RAW_FIELDS,
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _logical(path: Path) -> str:
    return logical_path(path.expanduser().resolve())


def _candidate_digest(candidates: Sequence[Mapping[str, Any]]) -> str:
    stable = [
        {
            "path": item["path"],
            "size_bytes": item["size_bytes"],
            "file_sha256": item["file_sha256"],
        }
        for item in candidates
    ]
    return canonical_sha256(stable)


def _rgb_digest(array: np.ndarray) -> str:
    header = f"RGB\0uint8\0{array.shape[0]}\0{array.shape[1]}\0".encode("ascii")
    return sha256_bytes(header + np.ascontiguousarray(array).tobytes())


def build_dataset_manifest(image_root: Path, count: int, seed: int) -> dict[str, Any]:
    image_root = image_root.expanduser().resolve()
    if not image_root.is_dir():
        raise FileNotFoundError(f"image root not found: {_logical(image_root)}")
    if count <= 0:
        raise ValueError("--images-per-cell must be positive")

    paths = sorted(
        path
        for path in image_root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    candidates: list[dict[str, Any]] = []
    for path in paths:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(image_root).as_posix()
        except ValueError as exc:
            raise ValueError("dataset candidate escapes image root") from exc
        if path.is_symlink():
            raise ValueError(f"dataset symlink rejected: {relative}")
        file_sha = sha256_file(resolved)
        score = sha256_bytes(
            (
                f"{SAMPLE_DOMAIN}\0{seed}\0{relative}\0{file_sha}"
            ).encode("utf-8")
        )
        candidates.append(
            {
                "path": relative,
                "size_bytes": resolved.stat().st_size,
                "file_sha256": file_sha,
                "selection_score_sha256": score,
            }
        )

    if len(candidates) < count:
        raise ValueError(
            f"requested {count} images, but only {len(candidates)} candidates exist"
        )

    selected = sorted(
        candidates, key=lambda item: (item["selection_score_sha256"], item["path"])
    )[:count]
    files: list[dict[str, Any]] = []
    for sample_index, item in enumerate(selected):
        path = image_root / str(item["path"])
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
        pixel_sha = _rgb_digest(rgb)
        image_id = sha256_bytes(
            (
                f"{IMAGE_ID_DOMAIN}\0{item['path']}\0{item['file_sha256']}\0{pixel_sha}"
            ).encode("utf-8")
        )
        files.append(
            {
                "sample_index": sample_index,
                "image_id": image_id,
                "path": item["path"],
                "size_bytes": item["size_bytes"],
                "file_sha256": item["file_sha256"],
                "canonical_rgb_sha256": pixel_sha,
                "width": int(rgb.shape[1]),
                "height": int(rgb.shape[0]),
                "color_space": "RGB",
                "dtype": "uint8",
                "selection_score_sha256": item["selection_score_sha256"],
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA,
        "dataset_root": _logical(image_root),
        "selection_method": "lowest_sha256_content_score_without_replacement",
        "selection_domain": SAMPLE_DOMAIN,
        "seed": seed,
        "candidate_count": len(candidates),
        "candidate_digest_sha256": _candidate_digest(candidates),
        "sample_count": count,
        "files": files,
        "files_digest_sha256": canonical_sha256(files),
    }
    assert_no_absolute_paths(manifest, "dataset_manifest")
    return manifest


def load_manifest_images(
    image_root: Path, manifest: Mapping[str, Any]
) -> dict[str, np.ndarray]:
    root = image_root.expanduser().resolve()
    loaded: dict[str, np.ndarray] = {}
    for item in manifest["files"]:
        path = (root / str(item["path"])).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("manifest image escapes image root") from exc
        if not path.is_file() or sha256_file(path) != item["file_sha256"]:
            raise RuntimeError(f"manifest image file hash drift: {item['image_id']}")
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
        if _rgb_digest(rgb) != item["canonical_rgb_sha256"]:
            raise RuntimeError(f"manifest canonical RGB drift: {item['image_id']}")
        if [int(rgb.shape[1]), int(rgb.shape[0])] != [item["width"], item["height"]]:
            raise RuntimeError(f"manifest image geometry drift: {item['image_id']}")
        loaded[str(item["image_id"])] = rgb
    return loaded


def derive_message(
    seed: int,
    role: str,
    model_name: str,
    image_id: str,
    bit_length: int,
) -> np.ndarray:
    if role not in {"source", "attacker"}:
        raise ValueError("message role must be source or attacker")
    if bit_length <= 0:
        raise ValueError("message bit length must be positive")
    domain = (
        f"{MESSAGE_DOMAIN}\0{seed}\0{role}\0{model_name}\0{image_id}\0{bit_length}"
    ).encode("utf-8")
    byte_count = (bit_length + 7) // 8
    material = hashlib.shake_256(domain).digest(byte_count)
    return np.unpackbits(
        np.frombuffer(material, dtype=np.uint8), bitorder="big"
    )[:bit_length].astype(np.uint8)


def bits_text(bits: np.ndarray) -> str:
    values = np.asarray(bits).reshape(-1)
    if values.size == 0 or not np.isin(values, [0, 1]).all():
        raise ValueError("bits must be a non-empty binary vector")
    return "".join("1" if int(value) else "0" for value in values)


def bits_sha256(bits: np.ndarray) -> str:
    values = np.asarray(bits, dtype=np.uint8).reshape(-1)
    return sha256_bytes(values.tobytes())


def parse_bits(value: str, length: int) -> np.ndarray:
    if len(value) != length or set(value) - {"0", "1"}:
        raise ValueError("raw bit vector is not binary or has the wrong length")
    return np.fromiter((character == "1" for character in value), dtype=np.uint8)


def _float_text(value: Any, label: str) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return format(number, ".17g")


def _metric_record(truth: np.ndarray, decoded: np.ndarray, threshold: float) -> dict[str, str]:
    if truth.shape != decoded.shape:
        raise ValueError("decoded message length drift")
    errors = int(np.count_nonzero(truth != decoded))
    ber = errors / int(truth.size)
    accuracy = 1.0 - ber
    return {
        "bit_errors": str(errors),
        "ber": _float_text(ber, "ber"),
        "accuracy": _float_text(accuracy, "accuracy"),
        "exact_match": "1" if errors == 0 else "0",
        "success": "1" if accuracy >= threshold else "0",
    }


def implementation_manifest() -> dict[str, Any]:
    files = [
        Path(__file__).resolve(),
        SCRIPT_PROJECT_ROOT / "system/evaluation/adapters/base.py",
        SCRIPT_PROJECT_ROOT / "system/evaluation/adapters/multi_embedding.py",
        SCRIPT_PROJECT_ROOT / "system/evaluation/adapters/lidmark_adapter.py",
        SCRIPT_PROJECT_ROOT / "system/evaluation/adapters/kadnet_adapter.py",
        SCRIPT_PROJECT_ROOT / "system/evaluation/adapters/sepmark_adapter.py",
        SCRIPT_PROJECT_ROOT / "system/evaluation/adapters/waveguard_adapter.py",
        SCRIPT_PROJECT_ROOT / "system/evaluation/metrics.py",
        SCRIPT_PROJECT_ROOT / "system/evaluation/protocol.py",
    ]
    records = [
        {"path": _logical(path), "sha256": sha256_file(path)} for path in files
    ]
    return {"files": records, "files_digest_sha256": canonical_sha256(records)}


def configure_determinism(seed: int, device: str, *, apply: bool) -> dict[str, Any]:
    os.environ["JYS_INFER_DEVICE"] = device
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed)
    record: dict[str, Any] = {
        "requested_device": device,
        "message_rng": "stateless_SHAKE256",
        "sample_selection": "content_addressed_SHA256",
        "python_random_seed": seed,
        "numpy_legacy_seed": seed,
        "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        "torch_deterministic_algorithms": False,
        "verified": False,
        "errors": [],
    }
    if not apply:
        record["runtime_configuration"] = "test_injection_no_torch_import"
        record["verified"] = True
        return record

    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.use_deterministic_algorithms(True)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        record.update(
            {
                "runtime_configuration": "applied",
                "torch_version": str(torch.__version__),
                "cuda_available": bool(torch.cuda.is_available()),
                "cuda_visible_devices": os.environ.get(
                    "CUDA_VISIBLE_DEVICES", "not_restricted"
                ),
                "torch_deterministic_algorithms": True,
                "verified": True,
            }
        )
    except Exception as exc:
        record["runtime_configuration"] = "failed"
        record["errors"] = [f"{exc.__class__.__name__}:{safe_error(exc)}"]
    return record


def checkpoint_records(
    adapter_classes: Mapping[str, type[Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    records: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name in TARGET_MODELS:
        adapter_class = adapter_classes.get(name)
        if adapter_class is None:
            records[name] = {
                "status": "registry_missing",
                "checkpoint": None,
                "checkpoint_sha256": None,
                "checkpoint_size_bytes": None,
                "expected_checkpoint_sha256": None,
                "integrity_verified": False,
                "message_length": None,
                "primary_decoder": None,
                "secondary_decoder": None,
                "selection_policy": None,
            }
            errors.append(f"adapter_registry_missing:{name}")
            continue
        checkpoint_raw = getattr(adapter_class, "checkpoint", None)
        checkpoint = (
            Path(str(checkpoint_raw)).expanduser().resolve() if checkpoint_raw else None
        )
        exists = bool(checkpoint and checkpoint.is_file())
        actual_sha = sha256_file(checkpoint) if checkpoint and exists else None
        expected_sha = getattr(adapter_class, "expected_checkpoint_sha256", None)
        integrity = exists and (expected_sha is None or actual_sha == expected_sha)
        message_length = getattr(adapter_class, "message_length", None)
        primary_decoder = getattr(adapter_class, "primary_decoder", None)
        record = {
            "status": "available" if integrity else "unavailable",
            "checkpoint": _logical(checkpoint) if checkpoint else None,
            "checkpoint_sha256": actual_sha,
            "checkpoint_size_bytes": checkpoint.stat().st_size if exists and checkpoint else None,
            "expected_checkpoint_sha256": expected_sha,
            "integrity_verified": bool(integrity),
            "message_length": message_length,
            "primary_decoder": primary_decoder,
            "secondary_decoder": getattr(adapter_class, "secondary_decoder", None),
            "selection_policy": getattr(adapter_class, "checkpoint_selection", None),
        }
        records[name] = record
        if not exists:
            errors.append(f"checkpoint_missing:{name}")
        elif not integrity:
            errors.append(f"checkpoint_sha256_mismatch:{name}")
        if not isinstance(message_length, int) or message_length <= 0:
            errors.append(f"message_length_invalid:{name}")
        if not isinstance(primary_decoder, str) or not primary_decoder:
            errors.append(f"primary_decoder_missing:{name}")
    return records, errors


def verify_backend_checkpoint_bindings(records: Mapping[str, Mapping[str, Any]]) -> None:
    from system.backend import model_adapters as backend

    bindings = {
        "SepMark": backend.SEPMARK_CKPT,
        "WaveGuard": backend.WAVEGUARD_CKPT,
    }
    for name, loaded_path in bindings.items():
        if _logical(Path(loaded_path)) != records[name]["checkpoint"]:
            raise RuntimeError(f"backend checkpoint binding drift for {name}")
        if sha256_file(Path(loaded_path)) != records[name]["checkpoint_sha256"]:
            raise RuntimeError(f"backend checkpoint hash drift for {name}")


def build_run_config(
    *,
    protocol_path: Path,
    protocol: Mapping[str, Any],
    protocol_sha: str,
    manifest_sha: str,
    images_per_cell: int,
    checkpoints: Mapping[str, Mapping[str, Any]],
    implementation: Mapping[str, Any],
    determinism: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CONFIG_SCHEMA,
        "protocol": {
            "schema_version": protocol["schema_version"],
            "path": _logical(protocol_path),
            "sha256": protocol_sha,
            "seed": protocol["seed"],
            "success_threshold": protocol["success_threshold"],
        },
        "matrix": {
            "ordered_models": list(TARGET_MODELS),
            "expected_model_count": 4,
            "expected_cell_count": 16,
            "images_per_cell": images_per_cell,
            "expected_row_count": 16 * images_per_cell,
            "cell_semantics": "ordered source_model then attacker_model",
        },
        "message_derivation": {
            "schema_version": MESSAGE_DOMAIN,
            "algorithm": "SHAKE256(domain,seed,role,model,image_id,bit_length)",
            "bit_order": "big",
            "pairing_policy": (
                "source message is shared across attackers; attacker message is shared "
                "across source models; roles are domain-separated"
            ),
        },
        "quality_semantics": {
            "first_embedding": "original vs source watermarked",
            "second_vs_original": "original vs attacker re-watermarked",
            "second_vs_first": "source watermarked vs attacker re-watermarked",
        },
        "models": {name: dict(checkpoints[name]) for name in TARGET_MODELS},
        "dataset_manifest": {
            "path": "dataset_manifest.json",
            "sha256": manifest_sha,
        },
        "implementation": dict(implementation),
        "determinism": dict(determinism),
        "raw_results": {
            "path": "raw_results.csv",
            "schema_version": RAW_SCHEMA,
            "fields": list(RAW_FIELDS),
        },
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row["source_model"]),
        str(row["attacker_model"]),
        str(row["image_id"]),
    )


def expected_keys(manifest: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    return [
        (source, attacker, str(item["image_id"]))
        for source in TARGET_MODELS
        for attacker in TARGET_MODELS
        for item in manifest["files"]
    ]


def _blank_row() -> dict[str, str]:
    return {field: "" for field in RAW_FIELDS}


def _base_row(
    *,
    source: str,
    attacker: str,
    sample: Mapping[str, Any],
    source_message: np.ndarray,
    attacker_message: np.ndarray,
    protocol: Mapping[str, Any],
    protocol_sha: str,
    manifest_sha: str,
    config_sha: str,
    checkpoints: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    row = _blank_row()
    image_id = str(sample["image_id"])
    cell_id = f"{source}::{attacker}"
    row.update(
        {
            "raw_schema_version": RAW_SCHEMA,
            "row_id": sha256_bytes(
                f"{RAW_SCHEMA}\0{source}\0{attacker}\0{image_id}".encode("utf-8")
            ),
            "cell_id": cell_id,
            "source_model": source,
            "attacker_model": attacker,
            "sample_index": str(sample["sample_index"]),
            "image_id": image_id,
            "source_path": str(sample["path"]),
            "protocol_sha256": protocol_sha,
            "protocol_seed": str(protocol["seed"]),
            "success_threshold": _float_text(
                protocol["success_threshold"], "success_threshold"
            ),
            "dataset_manifest_sha256": manifest_sha,
            "run_config_sha256": config_sha,
            "source_checkpoint_sha256": str(
                checkpoints[source]["checkpoint_sha256"] or ""
            ),
            "attacker_checkpoint_sha256": str(
                checkpoints[attacker]["checkpoint_sha256"] or ""
            ),
            "source_primary_decoder": str(checkpoints[source]["primary_decoder"] or ""),
            "attacker_primary_decoder": str(
                checkpoints[attacker]["primary_decoder"] or ""
            ),
            "source_message_length": str(source_message.size),
            "source_message_bits": bits_text(source_message),
            "source_message_sha256": bits_sha256(source_message),
            "attacker_message_length": str(attacker_message.size),
            "attacker_message_bits": bits_text(attacker_message),
            "attacker_message_sha256": bits_sha256(attacker_message),
        }
    )
    return row


def _quality_value(container: Mapping[str, Any], key: str, label: str) -> str:
    if key not in container:
        raise ValueError(f"missing quality metric: {label}")
    number = float(container[key])
    if not math.isfinite(number):
        raise ValueError(f"quality metric must be finite: {label}")
    if key == "ssim" and not -1.0 <= number <= 1.0:
        raise ValueError(f"SSIM out of range: {label}")
    if key == "psnr" and number < 0.0:
        raise ValueError(f"PSNR out of range: {label}")
    return _float_text(number, label)


def success_row(
    base: Mapping[str, str],
    result: Any,
    source_message: np.ndarray,
    attacker_message: np.ndarray,
    threshold: float,
) -> dict[str, str]:
    if result.source_model != base["source_model"]:
        raise ValueError("source model identity drift")
    if result.attacker_model != base["attacker_model"]:
        raise ValueError("attacker model identity drift")
    source_decoded = np.asarray(result.first_decoded_message).reshape(-1)
    attacker_decoded = np.asarray(result.second_decoded_message).reshape(-1)
    if not np.isin(source_decoded, [0, 1]).all():
        raise ValueError("source decoder returned non-binary values")
    if not np.isin(attacker_decoded, [0, 1]).all():
        raise ValueError("attacker decoder returned non-binary values")
    source_decoded = source_decoded.astype(np.uint8)
    attacker_decoded = attacker_decoded.astype(np.uint8)
    source_metrics = _metric_record(source_message, source_decoded, threshold)
    attacker_metrics = _metric_record(attacker_message, attacker_decoded, threshold)

    row = dict(base)
    row.update(
        {
            "source_decoded_bits": bits_text(source_decoded),
            "source_decoded_sha256": bits_sha256(source_decoded),
            "attacker_decoded_bits": bits_text(attacker_decoded),
            "attacker_decoded_sha256": bits_sha256(attacker_decoded),
            "source_bit_errors": source_metrics["bit_errors"],
            "source_ber": source_metrics["ber"],
            "source_bit_accuracy": source_metrics["accuracy"],
            "source_exact_match": source_metrics["exact_match"],
            "source_success": source_metrics["success"],
            "attacker_bit_errors": attacker_metrics["bit_errors"],
            "attacker_ber": attacker_metrics["ber"],
            "attacker_bit_accuracy": attacker_metrics["accuracy"],
            "attacker_exact_match": attacker_metrics["exact_match"],
            "attacker_success": attacker_metrics["success"],
            "first_embedding_psnr": _quality_value(
                result.first_embedding_quality, "psnr", "first_embedding_psnr"
            ),
            "first_embedding_ssim": _quality_value(
                result.first_embedding_quality, "ssim", "first_embedding_ssim"
            ),
            "second_vs_original_psnr": _quality_value(
                result.second_embedding_quality_vs_original,
                "psnr",
                "second_vs_original_psnr",
            ),
            "second_vs_original_ssim": _quality_value(
                result.second_embedding_quality_vs_original,
                "ssim",
                "second_vs_original_ssim",
            ),
            "second_vs_first_psnr": _quality_value(
                result.second_embedding_quality_vs_first,
                "psnr",
                "second_vs_first_psnr",
            ),
            "second_vs_first_ssim": _quality_value(
                result.second_embedding_quality_vs_first,
                "ssim",
                "second_vs_first_ssim",
            ),
            "status": "ok",
        }
    )
    return row


def error_row(
    base: Mapping[str, str], stage: str, exc: BaseException
) -> dict[str, str]:
    row = dict(base)
    row.update(
        {
            "status": "error",
            "error_stage": stage,
            "error_type": exc.__class__.__name__,
            "error": safe_error(exc),
        }
    )
    return row


def validate_raw_row(
    row: Mapping[str, str],
    *,
    manifest_by_id: Mapping[str, Mapping[str, Any]],
    protocol: Mapping[str, Any],
    protocol_sha: str,
    manifest_sha: str,
    config_sha: str,
    checkpoints: Mapping[str, Mapping[str, Any]],
) -> None:
    if set(row) != set(RAW_FIELDS):
        raise ValueError("raw row schema drift")
    source, attacker, image_id = _row_key(row)
    if source not in TARGET_MODELS or attacker not in TARGET_MODELS:
        raise ValueError("raw row contains unexpected model")
    if image_id not in manifest_by_id:
        raise ValueError("raw row contains unexpected image")
    sample = manifest_by_id[image_id]
    source_length = int(checkpoints[source]["message_length"])
    attacker_length = int(checkpoints[attacker]["message_length"])
    expected_source = derive_message(
        int(protocol["seed"]), "source", source, image_id, source_length
    )
    expected_attacker = derive_message(
        int(protocol["seed"]), "attacker", attacker, image_id, attacker_length
    )
    expected_base = _base_row(
        source=source,
        attacker=attacker,
        sample=sample,
        source_message=expected_source,
        attacker_message=expected_attacker,
        protocol=protocol,
        protocol_sha=protocol_sha,
        manifest_sha=manifest_sha,
        config_sha=config_sha,
        checkpoints=checkpoints,
    )
    for field in (
        "raw_schema_version",
        "row_id",
        "cell_id",
        "sample_index",
        "source_path",
        "protocol_sha256",
        "protocol_seed",
        "success_threshold",
        "dataset_manifest_sha256",
        "run_config_sha256",
        "source_checkpoint_sha256",
        "attacker_checkpoint_sha256",
        "source_primary_decoder",
        "attacker_primary_decoder",
        "source_message_length",
        "source_message_bits",
        "source_message_sha256",
        "attacker_message_length",
        "attacker_message_bits",
        "attacker_message_sha256",
    ):
        if row[field] != expected_base[field]:
            raise ValueError(f"raw row contract drift: {field}")
    if row["status"] == "error":
        if not row["error_stage"] or not row["error_type"] or not row["error"]:
            raise ValueError("error row is missing error evidence")
        return
    if row["status"] != "ok":
        raise ValueError("raw row status must be ok or error")
    source_decoded = parse_bits(row["source_decoded_bits"], source_length)
    attacker_decoded = parse_bits(row["attacker_decoded_bits"], attacker_length)
    if row["source_decoded_sha256"] != bits_sha256(source_decoded):
        raise ValueError("source decoded-message hash drift")
    if row["attacker_decoded_sha256"] != bits_sha256(attacker_decoded):
        raise ValueError("attacker decoded-message hash drift")
    for prefix, truth, decoded in (
        ("source", expected_source, source_decoded),
        ("attacker", expected_attacker, attacker_decoded),
    ):
        expected_metrics = _metric_record(
            truth, decoded, float(protocol["success_threshold"])
        )
        mapping = {
            "bit_errors": f"{prefix}_bit_errors",
            "ber": f"{prefix}_ber",
            "accuracy": f"{prefix}_bit_accuracy",
            "exact_match": f"{prefix}_exact_match",
            "success": f"{prefix}_success",
        }
        for metric, field in mapping.items():
            if row[field] != expected_metrics[metric]:
                raise ValueError(f"raw metric drift: {field}")
    for field in (
        "first_embedding_psnr",
        "first_embedding_ssim",
        "second_vs_original_psnr",
        "second_vs_original_ssim",
        "second_vs_first_psnr",
        "second_vs_first_ssim",
    ):
        value = float(row[field])
        if not math.isfinite(value):
            raise ValueError(f"raw quality metric is not finite: {field}")
        if field.endswith("ssim") and not -1.0 <= value <= 1.0:
            raise ValueError(f"raw SSIM out of range: {field}")
        if field.endswith("psnr") and value < 0.0:
            raise ValueError(f"raw PSNR out of range: {field}")


def load_existing_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RAW_FIELDS:
            raise RuntimeError("existing raw_results.csv schema does not match")
        return [dict(row) for row in reader]


def _mean_stats(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(array.mean()),
        "std": float(array.std(ddof=1)) if array.size > 1 else 0.0,
        "median": float(np.median(array)),
        "min": float(array.min()),
        "max": float(array.max()),
    }


def _wilson(successes: int, total: int) -> list[float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def coverage_and_matrix(
    rows: Sequence[Mapping[str, str]], manifest: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    expected = expected_keys(manifest)
    expected_set = set(expected)
    counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = _row_key(row)
        counts[key] = counts.get(key, 0) + 1
    duplicate_rows = sum(count - 1 for count in counts.values() if count > 1)
    unexpected_rows = sum(count for key, count in counts.items() if key not in expected_set)
    observed_expected = expected_set & set(counts)
    missing_rows = len(expected_set - set(counts))
    valid_rows = sum(
        1
        for row in rows
        if _row_key(row) in expected_set and row.get("status") == "ok"
    )
    error_rows = sum(
        1
        for row in rows
        if _row_key(row) in expected_set and row.get("status") == "error"
    )
    coverage = {
        "expected_rows": len(expected),
        "observed_unique_expected_rows": len(observed_expected),
        "valid_rows": valid_rows,
        "error_rows": error_rows,
        "missing_rows": missing_rows,
        "duplicate_rows": duplicate_rows,
        "unexpected_rows": unexpected_rows,
    }

    matrix: dict[str, dict[str, Any]] = {}
    sample_count = int(manifest["sample_count"])
    for source in TARGET_MODELS:
        matrix[source] = {}
        for attacker in TARGET_MODELS:
            cell_rows = [
                row
                for row in rows
                if row.get("source_model") == source
                and row.get("attacker_model") == attacker
            ]
            cell_errors = sum(row.get("status") == "error" for row in cell_rows)
            cell_valid = [row for row in cell_rows if row.get("status") == "ok"]
            complete = (
                len(cell_rows) == sample_count
                and len({_row_key(row) for row in cell_rows}) == sample_count
                and not cell_errors
            )
            aggregates: dict[str, Any] | None = None
            if complete:
                source_successes = sum(int(row["source_success"]) for row in cell_valid)
                attacker_successes = sum(int(row["attacker_success"]) for row in cell_valid)
                aggregates = {
                    "source_bit_accuracy": _mean_stats(
                        [float(row["source_bit_accuracy"]) for row in cell_valid]
                    ),
                    "attacker_bit_accuracy": _mean_stats(
                        [float(row["attacker_bit_accuracy"]) for row in cell_valid]
                    ),
                    "source_success_rate": source_successes / sample_count,
                    "source_success_rate_wilson95": _wilson(
                        source_successes, sample_count
                    ),
                    "attacker_success_rate": attacker_successes / sample_count,
                    "attacker_success_rate_wilson95": _wilson(
                        attacker_successes, sample_count
                    ),
                    "first_embedding_psnr": _mean_stats(
                        [float(row["first_embedding_psnr"]) for row in cell_valid]
                    ),
                    "first_embedding_ssim": _mean_stats(
                        [float(row["first_embedding_ssim"]) for row in cell_valid]
                    ),
                    "second_vs_original_psnr": _mean_stats(
                        [float(row["second_vs_original_psnr"]) for row in cell_valid]
                    ),
                    "second_vs_original_ssim": _mean_stats(
                        [float(row["second_vs_original_ssim"]) for row in cell_valid]
                    ),
                    "second_vs_first_psnr": _mean_stats(
                        [float(row["second_vs_first_psnr"]) for row in cell_valid]
                    ),
                    "second_vs_first_ssim": _mean_stats(
                        [float(row["second_vs_first_ssim"]) for row in cell_valid]
                    ),
                }
            matrix[source][attacker] = {
                "cell_id": f"{source}::{attacker}",
                "status": "complete" if complete else "incomplete",
                "expected_rows": sample_count,
                "observed_rows": len(cell_rows),
                "valid_rows": len(cell_valid),
                "error_rows": cell_errors,
                "missing_rows": max(0, sample_count - len({_row_key(row) for row in cell_rows})),
                "aggregates": aggregates,
            }
    coverage["expected_cells"] = 16
    coverage["complete_cells"] = sum(
        cell["status"] == "complete"
        for source_cells in matrix.values()
        for cell in source_cells.values()
    )
    return coverage, matrix


def markdown_table(matrix: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> str:
    header = "| Source -> Attacker |" + "".join(
        f" {name} source, attacker |" for name in TARGET_MODELS
    )
    separator = "|---|" + "---|" * len(TARGET_MODELS)
    rows = []
    for source in TARGET_MODELS:
        cells = []
        for attacker in TARGET_MODELS:
            cell = matrix[source][attacker]
            aggregates = cell.get("aggregates")
            if cell["status"] != "complete" or not aggregates:
                cells.append(" incomplete ")
            else:
                first = aggregates["source_bit_accuracy"]["mean"]
                second = aggregates["attacker_bit_accuracy"]["mean"]
                cells.append(f" {first:.3%}, {second:.3%} ")
        rows.append(f"| **{source}** |" + "|".join(cells) + "|")
    return "\n".join([header, separator, *rows])


def build_progress(
    rows: Sequence[Mapping[str, str]],
    manifest: Mapping[str, Any],
    raw_path: Path,
) -> dict[str, Any]:
    coverage, matrix = coverage_and_matrix(rows, manifest)
    complete = (
        coverage["complete_cells"] == 16
        and coverage["valid_rows"] == coverage["expected_rows"]
        and coverage["error_rows"] == 0
        and coverage["missing_rows"] == 0
        and coverage["duplicate_rows"] == 0
        and coverage["unexpected_rows"] == 0
    )
    return {
        "schema_version": PROGRESS_SCHEMA,
        "status": "complete" if complete else "incomplete",
        "updated_at": int(time.time()),
        "coverage": coverage,
        "cells": {
            cell["cell_id"]: {
                key: value
                for key, value in cell.items()
                if key != "aggregates"
            }
            for source_cells in matrix.values()
            for cell in source_cells.values()
        },
        "raw_results": {
            "path": "raw_results.csv",
            "sha256": sha256_file(raw_path) if raw_path.is_file() else None,
        },
    }


def build_summary(
    *,
    rows: Sequence[Mapping[str, str]],
    manifest: Mapping[str, Any],
    output_dir: Path,
    checkpoints: Mapping[str, Mapping[str, Any]],
    protocol: Mapping[str, Any],
    protocol_sha: str,
    preflight_errors: Sequence[str],
    postflight: Mapping[str, Any],
    started_at: float,
) -> dict[str, Any]:
    coverage, matrix = coverage_and_matrix(rows, manifest)
    postflight_ok = bool(postflight.get("verified"))
    complete = (
        not preflight_errors
        and postflight_ok
        and coverage["complete_cells"] == 16
        and coverage["valid_rows"] == coverage["expected_rows"]
        and coverage["error_rows"] == 0
        and coverage["missing_rows"] == 0
        and coverage["duplicate_rows"] == 0
        and coverage["unexpected_rows"] == 0
    )
    raw_path = output_dir / "raw_results.csv"
    config_path = output_dir / "run_config.json"
    manifest_path = output_dir / "dataset_manifest.json"
    summary = {
        "schema_version": SUMMARY_SCHEMA,
        "status": "complete" if complete else "incomplete",
        "evidence_status": "complete_unsigned" if complete else "incomplete",
        "claim_valid": False,
        "claim_status": "review_and_signature_required" if complete else "evidence_incomplete",
        "generated_at": int(time.time()),
        "elapsed_seconds": max(0.0, time.time() - started_at),
        "protocol": {
            "schema_version": protocol["schema_version"],
            "path": _logical(Path(str(protocol["_source_path"]))),
            "sha256": protocol_sha,
            "seed": protocol["seed"],
            "success_threshold": protocol["success_threshold"],
        },
        "artifacts": {
            "dataset_manifest": {
                "path": "dataset_manifest.json",
                "sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
            },
            "run_config": {
                "path": "run_config.json",
                "sha256": sha256_file(config_path) if config_path.is_file() else None,
            },
            "raw_results": {
                "path": "raw_results.csv",
                "sha256": sha256_file(raw_path) if raw_path.is_file() else None,
            },
        },
        "models": list(TARGET_MODELS),
        "model_count": len(TARGET_MODELS),
        "checkpoint_evidence": {
            name: dict(checkpoints[name]) for name in TARGET_MODELS
        },
        "images_per_cell": manifest["sample_count"],
        "coverage": coverage,
        "preflight_errors": list(preflight_errors),
        "postflight_input_audit": dict(postflight),
        "matrix": matrix,
        "markdown_table": markdown_table(matrix),
    }
    assert_no_absolute_paths(summary, "summary")
    return summary


def _postflight_audit(
    *,
    protocol_path: Path,
    protocol_sha: str,
    image_root: Path,
    manifest: Mapping[str, Any],
    checkpoints: Mapping[str, Mapping[str, Any]],
    adapter_classes: Mapping[str, type[Any]],
    implementation: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if sha256_file(protocol_path) != protocol_sha:
        errors.append("protocol_sha256_drift")
    try:
        load_manifest_images(image_root, manifest)
    except Exception as exc:
        errors.append(f"dataset_drift:{exc.__class__.__name__}")
    for name in TARGET_MODELS:
        reference = checkpoints[name]
        adapter_class = adapter_classes.get(name)
        checkpoint_raw = getattr(adapter_class, "checkpoint", None) if adapter_class else None
        if not checkpoint_raw:
            errors.append(f"checkpoint_missing:{name}")
            continue
        checkpoint = Path(str(checkpoint_raw)).expanduser().resolve()
        if (
            not checkpoint.is_file()
            or sha256_file(checkpoint) != reference.get("checkpoint_sha256")
        ):
            errors.append(f"checkpoint_drift:{name}")
    current_implementation = implementation_manifest()
    if current_implementation != implementation:
        errors.append("implementation_sha256_drift")
    return {
        "verified": not errors,
        "errors": errors,
        "protocol_sha256_unchanged": "protocol_sha256_drift" not in errors,
        "dataset_files_unchanged": not any(error.startswith("dataset_drift") for error in errors),
        "checkpoint_sha256_unchanged": not any(
            error.startswith("checkpoint_") for error in errors
        ),
        "implementation_sha256_unchanged": "implementation_sha256_drift" not in errors,
    }


def _load_or_initialize_contract(
    *,
    output_dir: Path,
    manifest: Mapping[str, Any],
    config: Mapping[str, Any],
    resume: bool,
) -> list[dict[str, str]]:
    existing = [name for name in EVIDENCE_FILES if (output_dir / name).exists()]
    if existing and not resume:
        raise RuntimeError(
            "evidence directory is not empty; use a unique --output or --resume"
        )
    manifest_path = output_dir / "dataset_manifest.json"
    config_path = output_dir / "run_config.json"
    raw_path = output_dir / "raw_results.csv"
    if existing:
        if not manifest_path.is_file() or not config_path.is_file():
            raise RuntimeError("orphan evidence state lacks manifest or run_config")
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_config = json.loads(config_path.read_text(encoding="utf-8"))
        if existing_manifest != manifest:
            raise RuntimeError("resume dataset manifest mismatch")
        if existing_config != config:
            raise RuntimeError("resume run_config mismatch")
        return load_existing_rows(raw_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(config_path, config)
    atomic_write_csv(raw_path, [])
    return []


def run_matrix(
    args: argparse.Namespace,
    *,
    adapter_classes: Mapping[str, type[Any]] | None = None,
    evaluator: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    started_at = time.time()
    if args.images_per_cell <= 0:
        raise ValueError("--images-per-cell must be positive")
    image_root = args.image_root.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    protocol_path = (
        args.protocol.expanduser().resolve()
        if args.protocol
        else Path(load_protocol()["_source_path"]).resolve()
    )
    protocol = load_protocol(str(protocol_path))
    seed = protocol.get("seed")
    threshold = protocol.get("success_threshold")
    if not isinstance(seed, int):
        raise ValueError("protocol seed must be an integer")
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError("protocol success_threshold must be between 0 and 1")
    threshold = float(threshold)
    protocol_sha = sha256_file(protocol_path)

    injected = adapter_classes is not None
    determinism = configure_determinism(seed, str(args.device), apply=not injected)
    if adapter_classes is None:
        from system.evaluation.adapters import get_mea_adapter_classes

        adapter_classes = get_mea_adapter_classes()
    if evaluator is None:
        from system.evaluation.adapters import evaluate_double_embedding

        evaluator = evaluate_double_embedding

    manifest = build_dataset_manifest(image_root, args.images_per_cell, seed)
    manifest_sha = sha256_bytes(formatted_json_bytes(manifest))
    checkpoints, preflight_errors = checkpoint_records(adapter_classes)
    if not determinism.get("verified"):
        preflight_errors.append("determinism_configuration_failed")
    implementation = implementation_manifest()
    config = build_run_config(
        protocol_path=protocol_path,
        protocol=protocol,
        protocol_sha=protocol_sha,
        manifest_sha=manifest_sha,
        images_per_cell=args.images_per_cell,
        checkpoints=checkpoints,
        implementation=implementation,
        determinism=determinism,
    )
    existing_rows = _load_or_initialize_contract(
        output_dir=output_dir,
        manifest=manifest,
        config=config,
        resume=bool(args.resume),
    )
    manifest_file_sha = sha256_file(output_dir / "dataset_manifest.json")
    config_file_sha = sha256_file(output_dir / "run_config.json")
    manifest_by_id = {
        str(item["image_id"]): item for item in manifest["files"]
    }

    seen: set[tuple[str, str, str]] = set()
    valid_existing: list[dict[str, str]] = []
    for row in existing_rows:
        validate_raw_row(
            row,
            manifest_by_id=manifest_by_id,
            protocol=protocol,
            protocol_sha=protocol_sha,
            manifest_sha=manifest_file_sha,
            config_sha=config_file_sha,
            checkpoints=checkpoints,
        )
        key = _row_key(row)
        if key in seen:
            raise RuntimeError("duplicate row in existing raw_results.csv")
        seen.add(key)
        if row["status"] == "ok":
            valid_existing.append(row)

    rows = valid_existing
    atomic_write_csv(output_dir / "raw_results.csv", _sort_rows(rows, manifest))
    initial_postflight = {"verified": False, "errors": ["run_not_finished"]}
    initial_summary = build_summary(
        rows=rows,
        manifest=manifest,
        output_dir=output_dir,
        checkpoints=checkpoints,
        protocol=protocol,
        protocol_sha=protocol_sha,
        preflight_errors=preflight_errors,
        postflight=initial_postflight,
        started_at=started_at,
    )
    atomic_write_json(output_dir / "summary.json", initial_summary)
    atomic_write_json(
        output_dir / "progress.json",
        build_progress(rows, manifest, output_dir / "raw_results.csv"),
    )

    if preflight_errors:
        return initial_summary

    if not injected:
        try:
            verify_backend_checkpoint_bindings(checkpoints)
        except Exception as exc:
            preflight_errors.append(f"backend_checkpoint_binding:{exc.__class__.__name__}")

    adapters: dict[str, Any] = {}
    if not preflight_errors:
        for name in TARGET_MODELS:
            try:
                adapter = adapter_classes[name]()
                if not adapter.available:
                    raise RuntimeError(str(adapter.blocker or "adapter unavailable"))
                if str(getattr(adapter, "primary_decoder", "")) != str(
                    checkpoints[name]["primary_decoder"]
                ):
                    raise RuntimeError("primary decoder contract drift")
                adapters[name] = adapter
            except Exception as exc:
                preflight_errors.append(
                    f"adapter_initialization:{name}:{exc.__class__.__name__}:{safe_error(exc)}"
                )

    if preflight_errors:
        summary = build_summary(
            rows=rows,
            manifest=manifest,
            output_dir=output_dir,
            checkpoints=checkpoints,
            protocol=protocol,
            protocol_sha=protocol_sha,
            preflight_errors=preflight_errors,
            postflight={"verified": False, "errors": ["preflight_failed"]},
            started_at=started_at,
        )
        atomic_write_json(output_dir / "summary.json", summary)
        return summary

    try:
        images = load_manifest_images(image_root, manifest)
    except Exception as exc:
        preflight_errors.append(
            f"dataset_materialization:{exc.__class__.__name__}:{safe_error(exc)}"
        )
        summary = build_summary(
            rows=rows,
            manifest=manifest,
            output_dir=output_dir,
            checkpoints=checkpoints,
            protocol=protocol,
            protocol_sha=protocol_sha,
            preflight_errors=preflight_errors,
            postflight={"verified": False, "errors": ["preflight_failed"]},
            started_at=started_at,
        )
        atomic_write_json(output_dir / "summary.json", summary)
        return summary

    completed_keys = {_row_key(row) for row in rows}
    for source in TARGET_MODELS:
        for attacker in TARGET_MODELS:
            cell_rows: list[dict[str, str]] = []
            for sample in manifest["files"]:
                image_id = str(sample["image_id"])
                key = (source, attacker, image_id)
                if key in completed_keys:
                    continue
                source_message = derive_message(
                    seed,
                    "source",
                    source,
                    image_id,
                    int(checkpoints[source]["message_length"]),
                )
                attacker_message = derive_message(
                    seed,
                    "attacker",
                    attacker,
                    image_id,
                    int(checkpoints[attacker]["message_length"]),
                )
                base = _base_row(
                    source=source,
                    attacker=attacker,
                    sample=sample,
                    source_message=source_message,
                    attacker_message=attacker_message,
                    protocol=protocol,
                    protocol_sha=protocol_sha,
                    manifest_sha=manifest_file_sha,
                    config_sha=config_file_sha,
                    checkpoints=checkpoints,
                )
                try:
                    result = evaluator(
                        images[image_id].copy(),
                        adapters[source],
                        adapters[attacker],
                        source_message,
                        attacker_message,
                        threshold=threshold,
                    )
                    row = success_row(
                        base,
                        result,
                        source_message,
                        attacker_message,
                        threshold,
                    )
                except Exception as exc:
                    row = error_row(base, "evaluate_double_embedding", exc)
                cell_rows.append(row)
                completed_keys.add(key)

            if cell_rows:
                rows.extend(cell_rows)
                rows = _sort_rows(rows, manifest)
                atomic_write_csv(output_dir / "raw_results.csv", rows)
                atomic_write_json(
                    output_dir / "progress.json",
                    build_progress(rows, manifest, output_dir / "raw_results.csv"),
                )
                running_summary = build_summary(
                    rows=rows,
                    manifest=manifest,
                    output_dir=output_dir,
                    checkpoints=checkpoints,
                    protocol=protocol,
                    protocol_sha=protocol_sha,
                    preflight_errors=preflight_errors,
                    postflight={"verified": False, "errors": ["run_not_finished"]},
                    started_at=started_at,
                )
                atomic_write_json(output_dir / "summary.json", running_summary)

    for row in rows:
        validate_raw_row(
            row,
            manifest_by_id=manifest_by_id,
            protocol=protocol,
            protocol_sha=protocol_sha,
            manifest_sha=manifest_file_sha,
            config_sha=config_file_sha,
            checkpoints=checkpoints,
        )
    postflight = _postflight_audit(
        protocol_path=protocol_path,
        protocol_sha=protocol_sha,
        image_root=image_root,
        manifest=manifest,
        checkpoints=checkpoints,
        adapter_classes=adapter_classes,
        implementation=implementation,
    )
    summary = build_summary(
        rows=rows,
        manifest=manifest,
        output_dir=output_dir,
        checkpoints=checkpoints,
        protocol=protocol,
        protocol_sha=protocol_sha,
        preflight_errors=preflight_errors,
        postflight=postflight,
        started_at=started_at,
    )
    atomic_write_json(output_dir / "summary.json", summary)
    atomic_write_json(
        output_dir / "progress.json",
        build_progress(rows, manifest, output_dir / "raw_results.csv"),
    )
    return summary


def _sort_rows(
    rows: Sequence[Mapping[str, str]], manifest: Mapping[str, Any]
) -> list[dict[str, str]]:
    model_order = {name: index for index, name in enumerate(TARGET_MODELS)}
    sample_order = {
        str(item["image_id"]): int(item["sample_index"])
        for item in manifest["files"]
    }
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            model_order.get(row["source_model"], len(model_order)),
            model_order.get(row["attacker_model"], len(model_order)),
            sample_order.get(row["image_id"], len(sample_order)),
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_matrix(args)
    except Exception as exc:
        print(f"[MEA] fatal: {exc.__class__.__name__}: {safe_error(exc)}", file=sys.stderr)
        return 2
    print(summary["markdown_table"])
    print(
        f"[MEA] status={summary['status']} "
        f"valid={summary['coverage']['valid_rows']}/"
        f"{summary['coverage']['expected_rows']} "
        f"errors={summary['coverage']['error_rows']}"
    )
    return 0 if summary["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
