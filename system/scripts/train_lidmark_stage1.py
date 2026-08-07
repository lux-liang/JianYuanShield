#!/usr/bin/env python3
"""Run deterministic, resumable LIDMark Stage-1 training on prepared LFW data.

The persisted configuration and all generated metadata use logical runtime
paths (``data/...``, ``weights/...``, ``reports/...`` and ``model-sources/...``).
Absolute paths are materialized only in memory from the JYS_* runtime roots.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import random
import re
import shutil
import subprocess
import sys
import time
import traceback
from typing import Any, Iterable, Mapping


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import (  # noqa: E402
    DATA_ROOT,
    MODEL_SOURCE_ROOT,
    PROJECT_ROOT,
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
)


SCRIPT_VERSION = "1.1.0"
DEFAULT_RUN_ID = "lidmark-lfw-id-s20260603-128"
DEFAULT_SOURCE_COMMIT = "fc1c8f93e3ce496d273dde866f3e5ec191e4d0e4"
PORTABLE_PATH_FIELDS = (
    "source_root",
    "dataset_manifest",
    "report_root",
    "img_path",
    "wm_path",
    "weight_path",
)
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_CHECKPOINT_PATTERN = re.compile(r"checkpoint_epoch_([1-9][0-9]*)\.pth")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_SINGLE_GPU_PATTERN = re.compile(r"[0-9]+")


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run-id must be 1-128 characters using letters, digits, '.', '_' or '-'"
        )
    return run_id


def parse_visible_gpu(value: str | None) -> int:
    if value is None or not _SINGLE_GPU_PATTERN.fullmatch(value.strip()):
        raise RuntimeError(
            "CUDA_VISIBLE_DEVICES must contain exactly one non-negative GPU index"
        )
    return int(value.strip())


def require_visible_gpu(expected_physical_gpu: int) -> int:
    physical_gpu = parse_visible_gpu(os.environ.get("CUDA_VISIBLE_DEVICES"))
    if physical_gpu != expected_physical_gpu:
        raise RuntimeError(
            "CUDA_VISIBLE_DEVICES does not match the configured physical GPU: "
            f"{physical_gpu} != {expected_physical_gpu}"
        )
    return physical_gpu


def build_stage1_config(
    run_id: str = DEFAULT_RUN_ID,
    *,
    seed: int = 20260603,
    batch_size: int = 64,
    epochs: int = 20,
    num_workers: int = 4,
    image_size: int = 128,
    physical_gpu: int = 2,
    source_commit: str = DEFAULT_SOURCE_COMMIT,
) -> dict[str, Any]:
    """Build a JSON-compatible YAML config containing only logical paths."""
    validate_run_id(run_id)
    if seed < 0:
        raise ValueError("seed must be non-negative")
    if batch_size != 64:
        raise ValueError("LIDMark Stage-1 uses the preregistered batch size 64")
    if epochs < 1 or num_workers < 0:
        raise ValueError("epochs must be positive and num-workers must be non-negative")
    if image_size != 128:
        raise ValueError("LIDMark Stage-1 currently supports image-size 128 only")
    if physical_gpu < 0:
        raise ValueError("physical-gpu must be non-negative")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source-commit must be a full lowercase Git SHA-1")

    dataset_root = "data/lfw/lidmark_identity_disjoint"
    return {
        "schema_version": "jys.lidmark.stage1.v1",
        "experiment_id": run_id,
        "source_root": "model-sources/LIDMark",
        "source_commit": source_commit,
        "dataset_manifest": f"{dataset_root}/manifests/dataset_manifest.json",
        "report_root": f"reports/{run_id}",
        "img_size": image_size,
        "encoder_blocks": 3,
        "decoder_blocks": 1,
        "img_path": f"{dataset_root}/image/lfw_{image_size}",
        "wm_path": f"{dataset_root}/watermark_152/lfw",
        "weight_path": f"weights/lidmark/{run_id}",
        "sep_model": False,
        "gpu_ids": str(physical_gpu),
        "seed": seed,
        "encoder_channels": 64,
        "decoder_channels": 64,
        "discriminator_channels": 64,
        "discriminator_blocks": 3,
        "watermark_length": 152,
        "epochs": epochs,
        "batch_size": batch_size,
        "num_workers": num_workers,
        "train_transform": "resize_normalize_no_crop",
        "lr": 4.3e-4,
        "manipulation_mode": "common",
        "manipulation_layers": [
            "RandomDistortion(['Identity()', 'Resize(0.5)', 'GaussianBlur(2,3)', "
            "'MedBlur(3)', 'JpegTest(50)', 'JpegMask(50)'])"
        ],
        "encoder_weight": 1.97,
        "landmark_loss_weight": 11.5,
        "id_loss_weight": 14.7,
        "discriminator_weight": 0.007,
        "validation": {"enable": True, "save_count": 0},
        "resume": {"enable": True, "epoch": 0},
        "verify_dataset_files": True,
    }


def runtime_roots() -> dict[str, Path]:
    return {
        "data": DATA_ROOT,
        "weights": WEIGHT_ROOT,
        "reports": REPORT_ROOT,
        "model-sources": MODEL_SOURCE_ROOT,
        "project": PROJECT_ROOT,
    }


def resolve_portable_reference(reference: str | Path, roots: Mapping[str, Path]) -> Path:
    """Resolve a logical reference below an approved root and reject traversal."""
    raw = Path(reference)
    if raw.is_absolute() or ".." in raw.parts or not raw.parts:
        raise ValueError(f"path must be a non-empty logical reference: {reference}")
    root_name = raw.parts[0]
    if root_name in roots and root_name != "project":
        root = Path(roots[root_name]).expanduser().resolve()
        suffix = raw.parts[1:]
    else:
        root = Path(roots["project"]).expanduser().resolve()
        suffix = raw.parts
    candidate = root.joinpath(*suffix).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path escapes approved root: {reference}") from error
    return candidate


def materialize_config(
    config: Mapping[str, Any], roots: Mapping[str, Path] | None = None
) -> dict[str, Any]:
    """Resolve portable config paths for the upstream LIDMark classes in memory."""
    approved_roots = runtime_roots() if roots is None else dict(roots)
    missing_roots = {"data", "weights", "reports", "model-sources", "project"} - set(
        approved_roots
    )
    if missing_roots:
        raise ValueError(f"missing runtime root mappings: {sorted(missing_roots)}")
    materialized = dict(config)
    for field in PORTABLE_PATH_FIELDS:
        if field not in config:
            raise ValueError(f"configuration is missing {field}")
        materialized[field] = str(
            resolve_portable_reference(str(config[field]), approved_roots)
        )
    return materialized


def validate_stage1_config(config: Mapping[str, Any]) -> None:
    required = {
        "experiment_id",
        "source_commit",
        "img_size",
        "watermark_length",
        "epochs",
        "batch_size",
        "gpu_ids",
        "train_transform",
        "manipulation_mode",
        "validation",
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"configuration is missing fields: {missing}")
    validate_run_id(str(config["experiment_id"]))
    for field in PORTABLE_PATH_FIELDS:
        value = Path(str(config.get(field, "")))
        if value.is_absolute() or ".." in value.parts or not value.parts:
            raise ValueError(f"configuration field {field} must be a logical path")
    if int(config["batch_size"]) != 64:
        raise ValueError("LIDMark Stage-1 requires batch_size=64")
    if int(config["watermark_length"]) != 152:
        raise ValueError("LIDMark Stage-1 requires watermark_length=152")
    if int(config["img_size"]) != 128:
        raise ValueError("LIDMark Stage-1 currently supports img_size 128 only")
    if int(config["epochs"]) < 1:
        raise ValueError("epochs must be positive")
    if config["train_transform"] != "resize_normalize_no_crop":
        raise ValueError("landmark labels require resize_normalize_no_crop")
    if bool(config.get("sep_model")):
        raise ValueError("Stage-1 evidence runner requires the unified LIDMark model")
    if config["manipulation_mode"] != "common":
        raise ValueError("Stage-1 evidence runner requires common manipulation mode")
    validation = config["validation"]
    if not isinstance(validation, Mapping) or not bool(validation.get("enable")):
        raise ValueError("validation must be enabled")
    if not re.fullmatch(r"[0-9a-f]{40}", str(config["source_commit"])):
        raise ValueError("source_commit must be a full lowercase Git SHA-1")


def load_structured_config(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        import yaml

        value = yaml.safe_load(content)
    if not isinstance(value, dict):
        raise ValueError(f"configuration must be a mapping: {path}")
    return value


def load_training_dependencies() -> None:
    global DataLoader, np, torch

    import numpy as np_module
    import torch as torch_module
    from torch.utils.data import DataLoader as data_loader_class

    np = np_module
    torch = torch_module
    DataLoader = data_loader_class


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_bytes(path, content.encode("utf-8"))


def run_git(source_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def capture_source_state(
    source_root: Path, report_root: Path, expected_commit: str
) -> dict[str, Any]:
    commit = run_git(source_root, "rev-parse", "HEAD").decode().strip()
    status = run_git(source_root, "status", "--porcelain=v1").decode()
    diff = run_git(source_root, "diff", "--binary", "HEAD")
    diff_path = report_root / "source.diff"
    atomic_write_bytes(diff_path, diff)
    state = {
        "source_root": logical_path(source_root),
        "commit": commit,
        "expected_commit": expected_commit,
        "commit_matches": commit == expected_commit,
        "status_porcelain": status.splitlines(),
        "clean": not status.strip(),
        "diff_path": logical_path(diff_path),
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "diff_size_bytes": len(diff),
    }
    atomic_write_json(report_root / "source_state.json", state)
    if commit != expected_commit:
        raise RuntimeError(f"LIDMark source commit mismatch: {commit} != {expected_commit}")
    if status.strip():
        raise RuntimeError("LIDMark source worktree must be clean")
    return state


def verify_file_hash_manifest(
    file_hash_manifest: Path, dataset_root: Path, expected_entries: int | None
) -> dict[str, Any]:
    verified = 0
    for line_number, raw_line in enumerate(
        file_hash_manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        expected_sha, separator, relative_text = raw_line.partition("  ")
        if not separator or not _SHA256_PATTERN.fullmatch(expected_sha):
            raise ValueError(f"invalid files.sha256 line {line_number}")
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"unsafe files.sha256 path on line {line_number}")
        candidate = (dataset_root / relative).resolve()
        try:
            candidate.relative_to(dataset_root.resolve())
        except ValueError as error:
            raise ValueError(f"manifest path escapes dataset root: {relative_text}") from error
        if not candidate.is_file():
            raise FileNotFoundError(f"dataset file is missing: {logical_path(candidate)}")
        actual_sha = sha256_file(candidate)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"dataset file hash mismatch: {logical_path(candidate)}"
            )
        verified += 1
    if expected_entries is not None and verified != expected_entries:
        raise RuntimeError(
            f"dataset file count mismatch: verified {verified}, expected {expected_entries}"
        )
    return {"verified": True, "entry_count": verified}


def copy_dataset_evidence(
    dataset_manifest_path: Path, report_root: Path, verify_files: bool
) -> dict[str, Any]:
    dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    if not dataset_manifest.get("identity_disjoint"):
        raise RuntimeError("dataset manifest is not identity-disjoint")
    if int(dataset_manifest.get("failure_count", -1)) != 0:
        raise RuntimeError("dataset manifest contains failed samples")
    hash_record = dataset_manifest["file_hash_manifest"]
    file_hash_manifest = resolve_portable_reference(
        str(hash_record["path"]), runtime_roots()
    )
    actual_hash_manifest_sha = sha256_file(file_hash_manifest)
    if actual_hash_manifest_sha != hash_record["sha256"]:
        raise RuntimeError("dataset file-hash manifest digest mismatch")
    verification = {"verified": False, "entry_count": 0}
    if verify_files:
        verification = verify_file_hash_manifest(
            file_hash_manifest,
            dataset_manifest_path.parent.parent,
            int(hash_record["entry_count"]),
        )

    evidence_root = report_root / "dataset_evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in (
        "dataset_manifest.json",
        "splits.json",
        "identity_map.json",
        "failures.jsonl",
        "files.sha256",
        "smoke_report.json",
    ):
        source = dataset_manifest_path.parent / name
        if source.is_file():
            destination = evidence_root / name
            shutil.copy2(source, destination)
            copied.append(
                {
                    "name": name,
                    "sha256": sha256_file(destination),
                    "size_bytes": destination.stat().st_size,
                }
            )
    result = {
        "source_manifest": logical_path(dataset_manifest_path),
        "source_manifest_sha256": sha256_file(dataset_manifest_path),
        "file_hash_manifest": logical_path(file_hash_manifest),
        "file_hash_manifest_sha256": actual_hash_manifest_sha,
        "file_verification": verification,
        "copied": copied,
    }
    atomic_write_json(report_root / "dataset_evidence.json", result)
    return result


def configure_reproducibility(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def epoch_seed(base_seed: int, epoch: int, phase: str) -> int:
    phase_offsets = {"train": 0, "val": 10_000_000}
    if phase not in phase_offsets:
        raise ValueError(f"unknown phase: {phase}")
    return base_seed + phase_offsets[phase] + epoch * 1009


def build_loader(
    image_dataset_class: Any,
    seed_worker: Any,
    config: Mapping[str, Any],
    split: str,
    epoch: int,
) -> Any:
    if split not in ("train", "val"):
        raise ValueError(f"unsupported Stage-1 split: {split}")
    # The official train transform randomly crops after resizing without
    # transforming the 136 landmark labels. Using the deterministic test-mode
    # resize keeps image geometry and target coordinates aligned.
    dataset = image_dataset_class(
        str(Path(str(config["img_path"])) / split),
        str(Path(str(config["wm_path"])) / str(config["img_size"]) / split),
        int(config["img_size"]),
        int(config["watermark_length"]),
        mode="test",
    )
    dataset.lst_wm = sorted(dataset.lst_wm)
    generator = torch.Generator()
    generator.manual_seed(epoch_seed(int(config["seed"]), epoch, split))
    return DataLoader(
        dataset,
        batch_size=int(config["batch_size"]),
        num_workers=int(config.get("num_workers", 4)),
        shuffle=split == "train",
        drop_last=split == "train",
        worker_init_fn=seed_worker,
        generator=generator,
        pin_memory=True,
        persistent_workers=False,
    )


def scalar_metrics(result: Mapping[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for name, value in result.items():
        if torch.is_tensor(value):
            scalar = float(value.detach().cpu())
        else:
            scalar = float(value)
        if not math.isfinite(scalar):
            raise FloatingPointError(f"non-finite metric {name}={scalar}")
        metrics[name] = scalar
    return metrics


def gradient_stats(modules: Iterable[Any]) -> dict[str, Any]:
    squared_norm = torch.zeros((), device="cuda:0", dtype=torch.float64)
    maximum = torch.zeros((), device="cuda:0", dtype=torch.float32)
    tensor_count = 0
    element_count = 0
    for module in modules:
        for parameter in module.parameters():
            gradient = parameter.grad
            if gradient is None:
                continue
            if not bool(torch.isfinite(gradient).all()):
                raise FloatingPointError("non-finite gradient detected")
            detached = gradient.detach()
            squared_norm += detached.double().square().sum()
            maximum = torch.maximum(maximum, detached.abs().max())
            tensor_count += 1
            element_count += gradient.numel()
    if tensor_count == 0:
        raise RuntimeError("no gradients were produced")
    total_norm = float(torch.sqrt(squared_norm).cpu())
    max_abs = float(maximum.cpu())
    if not math.isfinite(total_norm) or not math.isfinite(max_abs):
        raise FloatingPointError("non-finite gradient summary")
    return {
        "finite": True,
        "tensor_count": tensor_count,
        "element_count": element_count,
        "total_l2_norm": total_norm,
        "max_abs": max_abs,
    }


def weighted_average(rows: list[tuple[int, dict[str, float]]]) -> dict[str, float]:
    total = sum(weight for weight, _ in rows)
    if total <= 0:
        raise RuntimeError("no samples were accumulated")
    names = rows[0][1].keys()
    averages = {
        name: sum(weight * metrics[name] for weight, metrics in rows) / total
        for name in names
    }
    if not all(math.isfinite(value) for value in averages.values()):
        raise FloatingPointError("non-finite epoch average")
    return averages


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()


def checkpoint_epoch(path: Path) -> int:
    match = _CHECKPOINT_PATTERN.fullmatch(path.name)
    if match is None:
        raise ValueError(f"invalid checkpoint filename: {path.name}")
    return int(match.group(1))


def available_checkpoints(weight_root: Path) -> list[Path]:
    return sorted(weight_root.glob("checkpoint_epoch_*.pth"), key=checkpoint_epoch)


def write_checkpoint_hashes(
    weight_root: Path, report_root: Path
) -> list[dict[str, Any]]:
    records = [
        {
            "epoch": checkpoint_epoch(path),
            "path": logical_path(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in available_checkpoints(weight_root)
    ]
    atomic_write_json(report_root / "checkpoint_hashes.json", {"checkpoints": records})
    return records


def verify_resume_checkpoint(checkpoint_path: Path, report_root: Path) -> dict[str, Any]:
    manifest_path = report_root / "checkpoint_hashes.json"
    if not manifest_path.is_file():
        raise RuntimeError("checkpoint hash manifest is required before resume")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    epoch = checkpoint_epoch(checkpoint_path)
    records = manifest.get("checkpoints")
    if not isinstance(records, list):
        raise ValueError("checkpoint hash manifest must contain a checkpoints list")
    record = next(
        (
            item
            for item in records
            if isinstance(item, dict) and int(item.get("epoch", -1)) == epoch
        ),
        None,
    )
    if record is None:
        raise RuntimeError(f"checkpoint epoch {epoch} is absent from the hash manifest")
    actual_sha = sha256_file(checkpoint_path)
    if actual_sha != record.get("sha256"):
        raise RuntimeError(f"resume checkpoint hash mismatch at epoch {epoch}")
    if int(record.get("size_bytes", -1)) != checkpoint_path.stat().st_size:
        raise RuntimeError(f"resume checkpoint size mismatch at epoch {epoch}")
    if str(record.get("path")) != logical_path(checkpoint_path):
        raise RuntimeError(f"resume checkpoint path mismatch at epoch {epoch}")
    return {
        "epoch": epoch,
        "path": logical_path(checkpoint_path),
        "size_bytes": checkpoint_path.stat().st_size,
        "sha256": actual_sha,
    }


def save_checkpoint_atomic(trainer: Any, epoch: int, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    trainer.save_checkpoint(epoch, str(temporary))
    os.replace(temporary, path)


def load_checkpoint_secure(trainer: Any, checkpoint_path: Path) -> int:
    """Load the upstream checkpoint structure with restricted PyTorch unpickling."""
    checkpoint = torch.load(
        checkpoint_path,
        map_location=trainer.device,
        weights_only=True,
    )
    required = {
        "epoch",
        "model_state_dict",
        "discriminator_state_dict",
        "optimizer_model_state_dict",
        "optimizer_discriminator_state_dict",
    }
    if not isinstance(checkpoint, dict) or not required.issubset(checkpoint):
        raise ValueError("checkpoint does not match the LIDMark Stage-1 schema")
    if trainer.configs.sep_model:
        model_state = checkpoint["model_state_dict"]
        encoder = trainer.encoder.module if trainer.num_gpus > 1 else trainer.encoder
        decoder = trainer.decoder.module if trainer.num_gpus > 1 else trainer.decoder
        encoder.load_state_dict(model_state["encoder_state_dict"], strict=True)
        decoder.load_state_dict(model_state["decoder_state_dict"], strict=True)
    else:
        model = trainer.model.module if trainer.num_gpus > 1 else trainer.model
        model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    discriminator = (
        trainer.discriminator.module
        if trainer.num_gpus > 1
        else trainer.discriminator
    )
    discriminator.load_state_dict(checkpoint["discriminator_state_dict"], strict=True)
    trainer.opt_model.load_state_dict(checkpoint["optimizer_model_state_dict"])
    trainer.opt_discriminator.load_state_dict(
        checkpoint["optimizer_discriminator_state_dict"]
    )
    epoch = int(checkpoint["epoch"])
    if epoch < 1:
        raise ValueError("checkpoint epoch must be positive")
    return epoch


def strict_reload_checkpoint(
    trainer_class: Any,
    configs: Any,
    checkpoint_path: Path,
    epoch: int,
    logger: logging.Logger,
) -> dict[str, Any]:
    probe = trainer_class(configs, torch.device("cpu"), logger)
    loaded_epoch = load_checkpoint_secure(probe, checkpoint_path)
    if loaded_epoch != epoch:
        raise RuntimeError(f"strict reload returned epoch {loaded_epoch}, expected {epoch}")
    del probe
    gc.collect()
    return {
        "strict_reload": True,
        "loaded_epoch": loaded_epoch,
        "checkpoint_sha256": sha256_file(checkpoint_path),
    }


def configure_logger(report_root: Path) -> logging.Logger:
    logger = logging.getLogger("lidmark-stage1")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    file_handler = logging.FileHandler(report_root / "trainer.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--target-epoch", type=int, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--seed", type=int, default=20260603)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--image-size", type=int, choices=(128,), default=128)
    parser.add_argument("--expected-physical-gpu", type=int, default=2)
    parser.add_argument("--source-commit", default=DEFAULT_SOURCE_COMMIT)
    return parser.parse_args(argv)


def prepare_config(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    validate_run_id(args.run_id)
    config_path = (
        args.config.expanduser().resolve()
        if args.config is not None
        else (REPORT_ROOT / args.run_id / "config.yaml").resolve()
    )
    if config_path.is_file():
        config = load_structured_config(config_path)
    else:
        config = build_stage1_config(
            args.run_id,
            seed=args.seed,
            batch_size=args.batch_size,
            epochs=args.epochs,
            num_workers=args.num_workers,
            image_size=args.image_size,
            physical_gpu=args.expected_physical_gpu,
            source_commit=args.source_commit,
        )
        atomic_write_json(config_path, config)
    validate_stage1_config(config)
    if str(config["experiment_id"]) != args.run_id:
        raise ValueError("run-id does not match config experiment_id")
    return config_path, config


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path, portable_config = prepare_config(args)
    if args.target_epoch < 1 or args.target_epoch > int(portable_config["epochs"]):
        raise ValueError("target-epoch must be between 1 and config epochs")
    configured_gpu = int(str(portable_config["gpu_ids"]))
    if configured_gpu != args.expected_physical_gpu:
        raise RuntimeError("config gpu_ids does not match --expected-physical-gpu")
    physical_gpu = require_visible_gpu(configured_gpu)

    materialized = materialize_config(portable_config)
    source_root = Path(materialized["source_root"])
    report_root = Path(materialized["report_root"])
    weight_root = Path(materialized["weight_path"])
    dataset_manifest_path = Path(materialized["dataset_manifest"])
    report_root.mkdir(parents=True, exist_ok=True)
    weight_root.mkdir(parents=True, exist_ok=True)
    canonical_config_path = report_root / "config.yaml"
    if config_path != canonical_config_path:
        atomic_write_bytes(canonical_config_path, config_path.read_bytes())
        config_path = canonical_config_path

    sys.dont_write_bytecode = True
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    load_training_dependencies()
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError(
            "expected exactly one CUDA device after applying CUDA_VISIBLE_DEVICES; "
            f"count={torch.cuda.device_count()}"
        )

    sys.path.insert(0, str(source_root))
    os.chdir(source_root)
    from trainer import TrainerImg
    from utils import Config, ImageDataset, seed_worker

    logger = configure_logger(report_root)
    script_path = Path(__file__).resolve()
    source_state = capture_source_state(
        source_root, report_root, str(portable_config["source_commit"])
    )
    dataset_evidence = copy_dataset_evidence(
        dataset_manifest_path,
        report_root,
        bool(portable_config.get("verify_dataset_files", True)),
    )
    configure_reproducibility(int(portable_config["seed"]))

    configs = Config()
    configs.load_dict(materialized)
    device = torch.device("cuda:0")
    trainer = TrainerImg(configs, device, logger)
    checkpoints = available_checkpoints(weight_root)
    start_epoch = 1
    resumed_from: str | None = None
    if args.resume and checkpoints:
        latest = checkpoints[-1]
        latest_epoch = checkpoint_epoch(latest)
        if latest_epoch < args.target_epoch:
            verify_resume_checkpoint(latest, report_root)
            loaded_epoch = load_checkpoint_secure(trainer, latest)
            if loaded_epoch != latest_epoch:
                raise RuntimeError("resume checkpoint epoch mismatch")
            start_epoch = loaded_epoch + 1
            resumed_from = logical_path(latest)
        else:
            start_epoch = args.target_epoch + 1
    elif checkpoints and not args.resume:
        raise RuntimeError("checkpoints exist; pass --resume to continue")

    runtime = {
        "script_version": SCRIPT_VERSION,
        "script_path": logical_path(script_path),
        "script_sha256": sha256_file(script_path),
        "config_path": logical_path(config_path),
        "config_sha256": sha256_file(config_path),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
        "physical_gpu": physical_gpu,
        "visible_cuda_index": 0,
        "gpu_name": torch.cuda.get_device_name(0),
        "seed": int(portable_config["seed"]),
        "batch_size": int(portable_config["batch_size"]),
        "target_epoch": args.target_epoch,
        "resumed_from": resumed_from,
        "source": source_state,
        "dataset": dataset_evidence,
    }
    atomic_write_json(report_root / "runtime.json", runtime)

    history_path = report_root / "history.json"
    if history_path.is_file():
        history = json.loads(history_path.read_text(encoding="utf-8"))
    else:
        history = {"epochs": []}
    run_state_path = report_root / "run_state.json"
    run_state = {
        "status": "running",
        "pid": os.getpid(),
        "target_epoch": args.target_epoch,
        "start_epoch": start_epoch,
        "resumed_from": resumed_from,
        "started_unix": time.time(),
    }
    atomic_write_json(run_state_path, run_state)

    try:
        for epoch in range(start_epoch, args.target_epoch + 1):
            torch.cuda.reset_peak_memory_stats()
            configure_reproducibility(
                epoch_seed(int(portable_config["seed"]), epoch, "train")
            )
            train_loader = build_loader(
                ImageDataset, seed_worker, materialized, "train", epoch
            )
            train_rows: list[tuple[int, dict[str, float]]] = []
            gradient_norms: list[float] = []
            epoch_started = time.perf_counter()
            for batch_index, (images, payloads) in enumerate(train_loader, start=1):
                result = trainer.train_batch_common(images, payloads)
                metrics = scalar_metrics(result)
                gradients = gradient_stats((trainer.model, trainer.discriminator))
                train_rows.append((int(images.shape[0]), metrics))
                gradient_norms.append(gradients["total_l2_norm"])
                event = {
                    "phase": "train",
                    "epoch": epoch,
                    "batch": batch_index,
                    "sample_count": int(images.shape[0]),
                    "metrics": metrics,
                    "gradients": gradients,
                }
                append_jsonl(report_root / "batches.jsonl", event)
                if (
                    batch_index == 1
                    or batch_index % 20 == 0
                    or batch_index == len(train_loader)
                ):
                    print(json.dumps(event, sort_keys=True), flush=True)

            configure_reproducibility(
                epoch_seed(int(portable_config["seed"]), epoch, "val")
            )
            val_loader = build_loader(ImageDataset, seed_worker, materialized, "val", epoch)
            val_rows: list[tuple[int, dict[str, float]]] = []
            for batch_index, (images, payloads) in enumerate(val_loader, start=1):
                result, _ = trainer.val_batch_common(images, payloads)
                metrics = scalar_metrics(result)
                val_rows.append((int(images.shape[0]), metrics))
                append_jsonl(
                    report_root / "batches.jsonl",
                    {
                        "phase": "val",
                        "epoch": epoch,
                        "batch": batch_index,
                        "sample_count": int(images.shape[0]),
                        "metrics": metrics,
                    },
                )

            checkpoint_path = weight_root / f"checkpoint_epoch_{epoch}.pth"
            save_checkpoint_atomic(trainer, epoch, checkpoint_path)
            reload_result = strict_reload_checkpoint(
                TrainerImg, configs, checkpoint_path, epoch, logger
            )
            checkpoint_records = write_checkpoint_hashes(weight_root, report_root)
            epoch_record = {
                "epoch": epoch,
                "train_samples": sum(weight for weight, _ in train_rows),
                "val_samples": sum(weight for weight, _ in val_rows),
                "train": weighted_average(train_rows),
                "val": weighted_average(val_rows),
                "gradient_finite_all_batches": True,
                "gradient_norm_min": min(gradient_norms),
                "gradient_norm_max": max(gradient_norms),
                "loss_metric_finite_all_batches": True,
                "strict_reload": reload_result,
                "checkpoint": checkpoint_records[-1],
                "elapsed_seconds": time.perf_counter() - epoch_started,
                "peak_gpu_allocated_mib": torch.cuda.max_memory_allocated() / 1024**2,
                "peak_gpu_reserved_mib": torch.cuda.max_memory_reserved() / 1024**2,
            }
            history["epochs"] = [
                item for item in history["epochs"] if int(item["epoch"]) != epoch
            ]
            history["epochs"].append(epoch_record)
            history["epochs"].sort(key=lambda item: int(item["epoch"]))
            atomic_write_json(history_path, history)
            atomic_write_json(report_root / f"epoch_{epoch:03d}.json", epoch_record)
            run_state.update(
                {
                    "last_completed_epoch": epoch,
                    "last_checkpoint": logical_path(checkpoint_path),
                    "last_checkpoint_sha256": reload_result["checkpoint_sha256"],
                }
            )
            atomic_write_json(run_state_path, run_state)
            print(json.dumps(epoch_record, sort_keys=True), flush=True)

        run_state.update(
            {
                "status": "complete",
                "completed_unix": time.time(),
                "completed_epoch": args.target_epoch,
            }
        )
        atomic_write_json(run_state_path, run_state)
        return 0
    except BaseException as error:
        run_state.update(
            {
                "status": "failed",
                "failed_unix": time.time(),
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        )
        atomic_write_json(run_state_path, run_state)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
