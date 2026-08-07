from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
import types
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Must be set before Torch initializes CUDA/CuBLAS.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

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
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
)


DEFAULT_IMAGE_ROOT = DATA_ROOT / "lfw/processed/image/lfw_128"
DEFAULT_REPORT_DIR = REPORT_ROOT / "kadnet_lfw_benchmark"
DEFAULT_ASSET_DIR = ASSET_ROOT / "kadnet_lfw_benchmark"
DEFAULT_CHECKPOINT = WEIGHT_ROOT / "KAD-Net/ST/128/models/EC_100.pth"
MSG_LEN = 30
IMG_SIZE = 128
RESULT_FIELDS = [
    "image_id",
    "source_path",
    "attack_type",
    "attack_config_sha256",
    "message_bits",
    "message_sha256",
    "bit_error",
    "bit_accuracy",
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
        description="Run the reproducible KAD-Net real-checkpoint benchmark on LFW.",
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
    return bool(stripped) and (Path(stripped).is_absolute() or bool(_WINDOWS_ABSOLUTE.match(stripped)))


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
        (path for path in root.rglob("*") if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if limit > 0:
        if len(images) < limit:
            raise RuntimeError(f"requested {limit} images but dataset contains {len(images)}")
        images = images[:limit]
    return images


def image_id(path: Path, image_root: Path) -> str:
    relative = path.expanduser().resolve().relative_to(image_root.expanduser().resolve()).as_posix()
    if _is_absolute_host_path(relative) or relative.startswith("../"):
        raise ValueError("image_id must be dataset-relative")
    return relative


def message_for_image(seed: int, identifier: str, length: int = MSG_LEN) -> np.ndarray:
    """Derive an image-scoped message without depending on traversal or resume order."""

    if length <= 0:
        raise ValueError("message length must be positive")
    payload = f"kadnet-message.v1\0{seed}\0{identifier}".encode("utf-8")
    packed = hashlib.shake_256(payload).digest((length + 7) // 8)
    return np.unpackbits(np.frombuffer(packed, dtype=np.uint8), bitorder="big")[:length].astype(np.uint8)


def message_bits(message: np.ndarray) -> str:
    return "".join(str(int(bit)) for bit in message.tolist())


def message_sha256(message: np.ndarray) -> str:
    return hashlib.sha256(message.astype(np.uint8, copy=False).tobytes()).hexdigest()


def resolve_attacks(requested: list[str] | None, protocol: dict[str, Any]) -> list[str]:
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
    missing_implementations = [attack_id for attack_id in selected if attack_id not in ATTACKS]
    if missing_implementations:
        raise ValueError("canonical attacks missing shared implementations: " + ", ".join(missing_implementations))

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


def compute_metrics(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float]:
    if reference.shape != candidate.shape:
        raise ValueError(f"quality metric shape mismatch: {reference.shape} != {candidate.shape}")
    if reference.ndim != 3 or reference.shape[2] != 3:
        raise ValueError("quality metrics require HxWx3 RGB images")
    minimum_side = min(reference.shape[:2])
    if minimum_side < 3:
        raise ValueError("quality metrics require image sides of at least three pixels")
    window = min(7, minimum_side if minimum_side % 2 else minimum_side - 1)
    return (
        float(peak_signal_noise_ratio(reference, candidate, data_range=255)),
        float(structural_similarity(reference, candidate, channel_axis=2, data_range=255, win_size=window)),
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
            raise ValueError(f"source_path must be dataset-relative and equal image_id: {key}")
        expected_message = message_for_image(seed, row["image_id"])
        if row["message_bits"] != message_bits(expected_message):
            raise ValueError(f"message derivation mismatch: {key}")
        if row["message_sha256"] != message_sha256(expected_message):
            raise ValueError(f"message hash mismatch: {key}")
        if row["attack_config_sha256"] != ATTACKS[row["attack_type"]].config_hash:
            raise ValueError(f"attack configuration mismatch: {key}")

        if row["error"]:
            if any(row[field] for field in ("bit_error", "bit_accuracy", "psnr", "ssim")):
                raise ValueError(f"error row contains metrics: {key}")
            if row["success"] != "0":
                raise ValueError(f"error row marked successful: {key}")
        else:
            ber = _float(row, "bit_error")
            accuracy = _float(row, "bit_accuracy")
            psnr = _float(row, "psnr")
            ssim = _float(row, "ssim")
            if not 0.0 <= ber <= 1.0 or not 0.0 <= accuracy <= 1.0:
                raise ValueError(f"bit metric outside [0,1]: {key}")
            if abs((1.0 - ber) - accuracy) > 1e-7:
                raise ValueError(f"bit metric identity failed: {key}")
            if psnr == -math.inf or not -1.0 <= ssim <= 1.0:
                raise ValueError(f"invalid quality metric: {key}")
            expected_success = "1" if accuracy >= success_threshold else "0"
            if row["success"] != expected_success:
                raise ValueError(f"success threshold mismatch: {key}")
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
                raise ValueError(f"watermarked error row contains metrics: {identifier}")
        else:
            psnr = _float(row, "watermarked_psnr")
            ssim = _float(row, "watermarked_ssim")
            if psnr == -math.inf or not -1.0 <= ssim <= 1.0:
                raise ValueError(f"invalid watermarked quality metric: {identifier}")
        indexed[identifier] = row
    return indexed


def _mean(rows: Iterable[dict[str, str]], field: str) -> float | str | None:
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
    expected_keys = {(identifier, attack) for identifier in image_ids for attack in attacks}
    error_rows = [row for row in result_rows.values() if row["error"]]
    missing_keys = expected_keys - set(result_rows)
    quality_errors = [row for row in quality_rows.values() if row["error"]]
    missing_quality = set(image_ids) - set(quality_rows)
    complete = not missing_keys and not error_rows and not missing_quality and not quality_errors

    attack_summaries: dict[str, Any] = {}
    for attack in attacks:
        rows = [result_rows[(identifier, attack)] for identifier in image_ids if (identifier, attack) in result_rows]
        valid = [row for row in rows if not row["error"]]
        attack_summaries[attack] = {
            "status": "complete" if len(valid) == len(image_ids) else "incomplete",
            "count": len(rows),
            "valid_count": len(valid),
            "error_count": len(rows) - len(valid),
            "mean_bit_error": _mean(valid, "bit_error"),
            "mean_bit_accuracy": _mean(valid, "bit_accuracy"),
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
        "method": "KAD-Net",
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
        "message_derivation": "SHAKE256(kadnet-message.v1, seed, image_id)",
        "attacks": attack_summaries,
        "success_definition": f"bit_accuracy >= {success_threshold}",
        "watermarked_quality": {
            "status": "complete" if len(valid_quality) == len(image_ids) else "incomplete",
            "count": len(quality_rows),
            "valid_count": len(valid_quality),
            "error_count": len(quality_errors),
            "missing_count": len(missing_quality),
            "mean_psnr": _mean(valid_quality, "watermarked_psnr"),
            "mean_ssim": _mean(valid_quality, "watermarked_ssim"),
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
    return [rows[key] for identifier in image_ids for attack in attacks if (key := (identifier, attack)) in rows]


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
    expected_files = []
    for path in images:
        expected_files.append({
            "path": image_id(path, image_root),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    if manifest.get("files") != expected_files:
        raise ValueError("dataset content changed since benchmark initialization")
    if manifest.get("files_digest_sha256") != _canonical_json_hash(expected_files):
        raise ValueError("dataset manifest digest mismatch")
    return manifest


def _ensure_run_config(path: Path, expected: dict[str, Any], result_state_exists: bool) -> None:
    _assert_no_absolute_paths(expected, "run_config")
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        _assert_no_absolute_paths(current, "existing_run_config")
        if current != expected:
            raise RuntimeError("existing benchmark configuration does not match requested run")
        return
    if result_state_exists:
        raise RuntimeError("existing benchmark rows have no run_config.json; refusing to mix results")
    _atomic_write_json(path, expected)


def _save_artifact(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image.astype(np.uint8)).save(path)


def build_adapter(checkpoint: Path):
    """Bind one explicit checkpoint and isolate the optional upstream attack pool."""

    checkpoint = checkpoint.expanduser().resolve()
    if not checkpoint.is_file():
        raise FileNotFoundError(f"checkpoint not found: {logical_path(checkpoint)}")
    from system.evaluation.adapters import kadnet_adapter

    class CheckpointBoundKADNetAdapter(kadnet_adapter.KADNetAdapter):
        @property
        def checkpoint(self) -> str:
            return str(checkpoint)

        @property
        def available(self) -> bool:
            return checkpoint.is_file()

        @property
        def blocker(self) -> str | None:
            return None if self.available else "kadnet_checkpoint_missing"

        def _load_models(self) -> None:
            if hasattr(self, "_encoder"):
                return
            import torch
            import torch.nn as nn

            source = str(kadnet_adapter.KADNET_CODE)
            if source not in sys.path:
                sys.path.insert(0, source)
            for module_name in list(sys.modules):
                if module_name in {"network", "config"} or module_name.startswith("network."):
                    del sys.modules[module_name]

            # The official ST core imports Random_Noise even though encoder and
            # decoder inference never use it. Upstream's optional attack package
            # references unreleased SimSwap files, so expose only the inert class
            # required to import the checkpoint-backed core.
            import network

            random_noise_stub = types.ModuleType("network.Random_Noise")

            class RandomNoise(nn.Module):
                def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                    super().__init__()

                def forward(self, values: Any) -> tuple[Any, Any, Any]:
                    return values[0], values[0], values[0]

            random_noise_stub.Random_Noise = RandomNoise
            sys.modules["network.Random_Noise"] = random_noise_stub
            from network.ST_EncoderDecoder import ST_Decoder, ST_Encoder

            device_name = os.environ.get("JYS_INFER_DEVICE", "cuda:0")
            self._device = torch.device(device_name if torch.cuda.is_available() else "cpu")
            state = torch.load(checkpoint, map_location="cpu", weights_only=True)
            encoder_state = {
                key[len("encoder."):]: value
                for key, value in state.items()
                if key.startswith("encoder.")
            }
            decoder_state = {
                key[len("decoder_C."):]: value
                for key, value in state.items()
                if key.startswith("decoder_C.")
            }
            if not encoder_state or not decoder_state:
                raise RuntimeError("checkpoint lacks encoder or decoder_C state")
            encoder_attention = "se" if any(".se." in key for key in encoder_state) else None
            decoder_attention = "se" if any(".se." in key for key in decoder_state) else None
            encoder = ST_Encoder(MSG_LEN, attention=encoder_attention)
            decoder = ST_Decoder(MSG_LEN, attention=decoder_attention)
            encoder.load_state_dict(encoder_state, strict=True)
            decoder.load_state_dict(decoder_state, strict=True)
            self._encoder = encoder.to(self._device).eval()
            self._decoder = decoder.to(self._device).eval()
            self._ckpt_path = str(checkpoint)

    return CheckpointBoundKADNetAdapter()


def main() -> None:
    args = parse_args()
    if args.flush_every <= 0:
        raise ValueError("flush-every must be positive")
    if args.artifact_limit < 0:
        raise ValueError("artifact-limit must be non-negative")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in {":4096:8", ":16:8"}:
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 or :16:8")
    os.environ.setdefault("JYS_INFER_DEVICE", args.device)
    import torch

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
    image_root = args.image_root.expanduser().resolve()
    images = list_images(image_root, args.num_images)
    if not images:
        raise RuntimeError("selected dataset is empty")
    image_ids = [image_id(path, image_root) for path in images]
    if len(image_ids) != len(set(image_ids)):
        raise RuntimeError("dataset-relative image IDs are not unique")

    checkpoint = args.checkpoint.expanduser().resolve()
    adapter = build_adapter(checkpoint)
    if not adapter.available or not adapter.checkpoint:
        raise RuntimeError(f"KAD-Net unavailable: {adapter.blocker}")
    discovered_checkpoint = Path(adapter.checkpoint).expanduser().resolve()
    if discovered_checkpoint != checkpoint:
        raise RuntimeError("adapter did not bind the requested checkpoint")
    checkpoint_hash = sha256_file(checkpoint)
    if checkpoint_hash is None:
        raise FileNotFoundError(f"checkpoint not found: {logical_path(checkpoint)}")

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
    dataset_manifest = _validate_dataset_manifest(manifest_path, image_root, images, args.seed)
    manifest_hash = sha256_file(manifest_path)
    protocol_path = Path(protocol["_source_path"])
    protocol_hash = sha256_file(protocol_path)
    if manifest_hash is None or protocol_hash is None:
        raise RuntimeError("evidence input hash unavailable")

    run_config = {
        "schema_version": "kadnet-benchmark-config.v1",
        "method": "KAD-Net",
        "mode": "real_checkpoint",
        "protocol_version": protocol["schema_version"],
        "protocol_path": logical_path(protocol_path),
        "protocol_sha256": protocol_hash,
        "attack_ids": attacks,
        "attack_contract_sha256": attack_contract_hash(attacks, protocol),
        "success_threshold": success_threshold,
        "seed": args.seed,
        "message_length": MSG_LEN,
        "message_derivation": "SHAKE256(kadnet-message.v1, seed, image_id)",
        "determinism": {
            "torch_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cudnn_deterministic": True,
            "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        },
        "model_input_size": IMG_SIZE,
        "image_root": logical_path(image_root),
        "sample_count": len(images),
        "dataset_files_digest_sha256": dataset_manifest["files_digest_sha256"],
        "dataset_manifest_path": logical_path(manifest_path),
        "dataset_manifest_sha256": manifest_hash,
        "checkpoint": logical_path(checkpoint),
        "checkpoint_sha256": checkpoint_hash,
        "result_schema": RESULT_FIELDS,
        "watermarked_quality_schema": QUALITY_FIELDS,
    }
    _ensure_run_config(config_path, run_config, result_state_exists)

    expected_keys = {(identifier, attack) for identifier in image_ids for attack in attacks}
    result_rows = load_result_rows(results_path, expected_keys, args.seed, success_threshold)
    quality_rows = load_quality_rows(quality_path, set(image_ids), args.seed)
    started = time.time()

    def flush(processed: int, status: str = "running") -> None:
        _atomic_write_csv(results_path, RESULT_FIELDS, _ordered_result_rows(result_rows, image_ids, attacks))
        _atomic_write_csv(quality_path, QUALITY_FIELDS, _ordered_quality_rows(quality_rows, image_ids))
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
            if (identifier, attack) not in result_rows or result_rows[(identifier, attack)]["error"]
        ]
        quality_pending = identifier not in quality_rows or bool(quality_rows[identifier]["error"])
        if not target_keys and not quality_pending:
            if (index + 1) % args.flush_every == 0:
                flush(index + 1)
            continue

        message = message_for_image(args.seed, identifier)
        bits = message_bits(message)
        message_hash = message_sha256(message)
        try:
            original = np.array(Image.open(path).convert("RGB"), dtype=np.uint8)
            encoded_result = adapter.encode(original, message)
            encoded = encoded_result.image.astype(np.uint8, copy=False)
            used_checkpoint = Path(str(encoded_result.metadata.get("checkpoint", ""))).expanduser().resolve()
            if used_checkpoint != checkpoint:
                raise RuntimeError("adapter checkpoint changed during benchmark")
            watermarked_psnr, watermarked_ssim = compute_metrics(original, encoded)
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
                _save_artifact(sample_dir / "watermarked.png", encoded)
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
                    "bit_error": "",
                    "bit_accuracy": "",
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
                    encoded,
                    attack,
                    image_id=identifier,
                    global_seed=args.seed,
                )
                if attack_metadata["config_hash"] != ATTACKS[attack].config_hash:
                    raise RuntimeError("shared attack metadata hash mismatch")
                decoded_result = adapter.decode(attacked)
                decoded = np.asarray(decoded_result.bits, dtype=np.uint8).reshape(-1)
                if decoded.shape != message.shape:
                    raise ValueError(f"decoder returned {decoded.size} bits; expected {message.size}")
                ber = float(np.mean(decoded != message))
                accuracy = 1.0 - ber
                attacked_psnr, attacked_ssim = compute_metrics(original, attacked)
                result_rows[key] = {
                    "image_id": identifier,
                    "source_path": identifier,
                    "attack_type": attack,
                    "attack_config_sha256": attack_metadata["config_hash"],
                    "message_bits": bits,
                    "message_sha256": message_hash,
                    "bit_error": _metric_text(ber),
                    "bit_accuracy": _metric_text(accuracy),
                    "psnr": _metric_text(attacked_psnr),
                    "ssim": _metric_text(attacked_ssim),
                    "success": "1" if accuracy >= success_threshold else "0",
                    "error": "",
                }
                if index < args.artifact_limit:
                    _save_artifact(asset_dir / f"sample_{index + 1:05d}" / f"{attack}.png", attacked)
            except Exception as exc:
                result_rows[key] = {
                    "image_id": identifier,
                    "source_path": identifier,
                    "attack_type": attack,
                    "attack_config_sha256": ATTACKS[attack].config_hash,
                    "message_bits": bits,
                    "message_sha256": message_hash,
                    "bit_error": "",
                    "bit_accuracy": "",
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
    result_rows = load_result_rows(results_path, expected_keys, args.seed, success_threshold)
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
        model="KAD-Net",
        checkpoint=checkpoint,
        results_path=results_path,
        dataset_manifest_path=manifest_path,
        sample_count=len(images),
        seed=args.seed,
        attack_ids=attacks,
        command=sys.argv,
    )
    summary["watermarked_quality_csv_path"] = logical_path(quality_path)
    summary["watermarked_quality_csv_sha256"] = sha256_file(quality_path)
    summary["run_config_path"] = logical_path(config_path)
    summary["run_config_sha256"] = sha256_file(config_path)
    _assert_no_absolute_paths(summary, "final_summary")
    _atomic_write_json(summary_path, summary)
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
