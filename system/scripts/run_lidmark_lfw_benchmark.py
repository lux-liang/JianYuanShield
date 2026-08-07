#!/usr/bin/env python3
"""Evidence-grade LIDMark evaluation on the identity-disjoint LFW test split."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterable, Mapping

import numpy as np
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

from system.evaluation.attacks import ATTACKS, apply_attack, derived_seed  # noqa: E402
from system.evaluation.evidence import finalize_benchmark_summary  # noqa: E402
from system.evaluation.protocol import load_protocol  # noqa: E402
from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.evaluation.runtime import (  # noqa: E402
    DATA_ROOT,
    MODEL_SOURCE_ROOT,
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
)


SCHEMA_VERSION = "lidmark-identity-test.v1"
CANONICAL_ATTACK_COUNT = 15
IMG_SIZE = 128
PAYLOAD_LENGTH = 152
LANDMARK_LENGTH = 136
IDENTITY_LENGTH = 16
EXPECTED_TEST_SAMPLES = 1324
EXPECTED_SOURCE_COMMIT = "fc1c8f93e3ce496d273dde866f3e5ec191e4d0e4"
EXPECTED_SOURCE_TREE_SHA256 = (
    "20584e345ae30eda6c9124b5c15fc82ff1e80ab31dfb5f49b23fc2f2df2b6d97"
)
EXPECTED_CHECKPOINT_SHA256 = (
    "762369c8e4e881c8d72fde08ebaf7fea3fd7a26354aa344aed288cb780ad3436"
)
EXPECTED_CHECKPOINT_SIZE = 71_132_941
EXPECTED_SELECTION_SHA256 = (
    "abed4af229d09c831636cb2e217bdcee424ed31d935c3c9f193ee71cf5faa8c8"
)
EXPECTED_TRAINING_CONFIG_SHA256 = (
    "f25d2077287ce0a30821a2f4c6e38470431305f2891684bb266cc09c1bcbac6e"
)
EXPECTED_DATASET_MANIFEST_SHA256 = (
    "29931a0cc5aabbe67b9feb7a0cb7b24e4267c54ed30beab2bcf2af5cdaf0129f"
)
EXPECTED_SPLITS_SHA256 = (
    "fb3d174d8a54603955baf8537487565b384f6f4e0d9fb73a575226db7d539932"
)
EXPECTED_IDENTITY_MAP_SHA256 = (
    "1c51d47e37bbfc9478ede0c856ec6a789f8a7531ce0324927792f82810c46bf4"
)
EXPECTED_FILES_MANIFEST_SHA256 = (
    "dcc65ba0d9060a3641892376b9df731c4c46f716a9ecdd84ed39b31a779177ea"
)
INPUT_MANIFEST_SCHEMA = "jys.lidmark.evaluation-inputs.v1"
ACTIVE_INPUT_EXPECTATIONS: dict[str, Any] | None = None

DEFAULT_DATASET_ROOT = DATA_ROOT / "lfw" / "lidmark_identity_disjoint"
DEFAULT_CHECKPOINT = (
    WEIGHT_ROOT / "lidmark" / "lfw-id-s20260603-128" / "checkpoint_epoch_20.pth"
)
DEFAULT_TRAIN_REPORT = REPORT_ROOT / "lidmark-train-lfw-id-s20260603-128"
DEFAULT_SELECTION_REPORT = DEFAULT_TRAIN_REPORT / "model_selection.json"
DEFAULT_TRAINING_CONFIG = DEFAULT_TRAIN_REPORT / "config.yaml"
DEFAULT_SOURCE_ROOT = MODEL_SOURCE_ROOT / "LIDMark"
DEFAULT_REPORT_DIR = REPORT_ROOT / "lidmark_lfw_identity_test_epoch20_protocol_v1"

EVALUATOR_SOURCE_FILES = (
    Path(__file__).resolve(),
    PROJECT_DIR / "system" / "evaluation" / "attacks.py",
    PROJECT_DIR / "system" / "evaluation" / "evidence.py",
    PROJECT_DIR / "system" / "evaluation" / "protocol.py",
    PROJECT_DIR / "system" / "evaluation" / "run_metadata.py",
    PROJECT_DIR / "system" / "evaluation" / "runtime.py",
)

RAW_RESULT_FIELDS = [
    "sample_id",
    "image_id",
    "identity",
    "source_path",
    "payload_path",
    "attack",
    "attack_type",
    "attack_transform",
    "severity",
    "attack_parameters_json",
    "attack_config_sha256",
    "protocol_attack_sha256",
    "evidence_level",
    "attack_seed",
    "payload_sha256",
    "message_sha256",
    "identity_bit_length",
    "bit_errors",
    "ber",
    "bit_accuracy",
    "identity_exact_match",
    "landmark_aed_px",
    "watermarked_psnr",
    "watermarked_ssim",
    "psnr",
    "ssim",
    "success",
    "error",
]

_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_LFW_FILENAME = re.compile(r"(?P<identity>.+)_[0-9]{4}\.jpg", re.IGNORECASE)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SINGLE_GPU = re.compile(r"[0-9]+")

_PROTOCOL_PARAMETER_EXTENSIONS: dict[str, dict[str, Any]] = {
    "resize_0.5x": {"down": "area", "up": "linear"},
    "platform_wechat_v1": {"evidence_level": "documented_proxy"},
    "platform_douyin_v1": {"evidence_level": "documented_proxy"},
    "deepfake_proxy_v1": {"evidence_level": "proxy_not_real_deepfake"},
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    protocol = load_protocol()
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the selected LIDMark epoch-20 checkpoint on the frozen "
            "identity-disjoint LFW test split and all canonical attacks."
        )
    )
    parser.add_argument("--num-images", type=int, default=EXPECTED_TEST_SAMPLES)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument(
        "--selection-report", type=Path, default=DEFAULT_SELECTION_REPORT
    )
    parser.add_argument("--training-config", type=Path, default=DEFAULT_TRAINING_CONFIG)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--expected-physical-gpu", type=int, default=2)
    parser.add_argument("--seed", type=int, default=int(protocol["seed"]))
    parser.add_argument("--flush-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--input-manifest",
        type=Path,
        help="content-bound candidate inputs; omitted for the frozen release baseline",
    )
    return parser.parse_args(argv)


def configure_input_expectations(path: Path | None) -> None:
    """Activate an explicit candidate manifest without weakening frozen defaults."""
    global ACTIVE_INPUT_EXPECTATIONS
    if path is None:
        ACTIVE_INPUT_EXPECTATIONS = None
        return
    document = _read_json(path.expanduser().resolve())
    if document.get("schema_version") != INPUT_MANIFEST_SCHEMA:
        raise ValueError("invalid LIDMark evaluation input manifest schema")
    required = {
        "selection_sha256": str,
        "checkpoint_sha256": str,
        "checkpoint_size_bytes": int,
        "selected_epoch": int,
        "training_config_sha256": str,
        "training_seed": int,
    }
    for field, expected_type in required.items():
        value = document.get(field)
        if isinstance(value, bool) or not isinstance(value, expected_type):
            raise ValueError(f"invalid input manifest field: {field}")
    for field in ("selection_sha256", "checkpoint_sha256", "training_config_sha256"):
        if not _SHA256.fullmatch(document[field]):
            raise ValueError(f"invalid SHA-256 in input manifest: {field}")
    if document["checkpoint_size_bytes"] <= 0 or document["selected_epoch"] <= 0:
        raise ValueError("input manifest sizes and epochs must be positive")
    ACTIVE_INPUT_EXPECTATIONS = document


def input_expectation(name: str, frozen_value: Any) -> Any:
    if ACTIVE_INPUT_EXPECTATIONS is None:
        return frozen_value
    return ACTIVE_INPUT_EXPECTATIONS.get(name, frozen_value)


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    content = json.dumps(
        payload, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False
    ) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _atomic_write_csv(
    path: Path,
    fieldnames: list[str],
    rows: Iterable[Mapping[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _is_absolute_host_path(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and (
        Path(stripped).is_absolute() or bool(_WINDOWS_ABSOLUTE.match(stripped))
    )


def _assert_no_absolute_paths(payload: Any, context: str) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            _assert_no_absolute_paths(value, f"{context}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _assert_no_absolute_paths(value, f"{context}[{index}]")
    elif isinstance(payload, str) and _is_absolute_host_path(payload):
        raise ValueError(f"absolute host path forbidden in {context}")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {logical_path(path)}")
    return value


def evaluator_source_evidence() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in EVALUATOR_SOURCE_FILES:
        actual_sha = sha256_file(path)
        if actual_sha is None:
            raise FileNotFoundError(f"evaluation source missing: {logical_path(path)}")
        files.append(
            {
                "path": logical_path(path),
                "size_bytes": path.stat().st_size,
                "sha256": actual_sha,
            }
        )
    evidence = {
        "schema_version": "evaluation-source-manifest.v1",
        "files": files,
        "files_digest_sha256": _canonical_json_hash(files),
    }
    _assert_no_absolute_paths(evidence, "evaluator_source_evidence")
    return evidence


def software_environment_evidence() -> dict[str, Any]:
    import cv2
    import PIL
    import skimage
    import torch

    evidence = {
        "schema_version": "lidmark-evaluation-software.v1",
        "python": sys.version,
        "numpy": np.__version__,
        "pillow": PIL.__version__,
        "scikit_image": skimage.__version__,
        "opencv": cv2.__version__,
        "opencv_build_sha256": hashlib.sha256(
            cv2.getBuildInformation().encode("utf-8")
        ).hexdigest(),
        "torch": str(torch.__version__),
        "torch_cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
    }
    _assert_no_absolute_paths(evidence, "software_environment_evidence")
    return evidence


def identity_from_filename(filename: str) -> str:
    match = _LFW_FILENAME.fullmatch(filename)
    if match is None:
        raise ValueError(f"not a canonical LFW filename: {filename}")
    return match.group("identity")


def parse_visible_gpu(value: str | None) -> int:
    if value is None or not _SINGLE_GPU.fullmatch(value.strip()):
        raise RuntimeError(
            "CUDA_VISIBLE_DEVICES must contain exactly one non-negative GPU index"
        )
    return int(value.strip())


def require_device_contract(device: str, expected_physical_gpu: int) -> None:
    if device != "cuda:0":
        raise ValueError("formal LIDMark evaluation device must be cuda:0")
    physical_gpu = parse_visible_gpu(os.environ.get("CUDA_VISIBLE_DEVICES"))
    if physical_gpu != expected_physical_gpu:
        raise RuntimeError(
            "CUDA_VISIBLE_DEVICES does not match --expected-physical-gpu: "
            f"{physical_gpu} != {expected_physical_gpu}"
        )


def resolve_attacks(protocol: Mapping[str, Any]) -> list[str]:
    entries = protocol.get("attacks")
    if not isinstance(entries, list):
        raise ValueError("protocol attacks must be a list")
    attack_ids = [str(entry["id"]) for entry in entries]
    declared_ids = [str(value) for value in protocol.get("attack_ids", [])]
    if len(attack_ids) != CANONICAL_ATTACK_COUNT:
        raise ValueError(f"protocol must contain {CANONICAL_ATTACK_COUNT} attacks")
    if len(attack_ids) != len(set(attack_ids)):
        raise ValueError("protocol attack IDs must be unique")
    if set(attack_ids) != set(declared_ids) or len(declared_ids) != len(attack_ids):
        raise ValueError("protocol attacks and attack_ids differ")
    missing = [attack_id for attack_id in attack_ids if attack_id not in ATTACKS]
    if missing:
        raise ValueError("canonical attacks missing implementations: " + ", ".join(missing))
    by_id = {str(entry["id"]): entry for entry in entries}
    for attack_id in attack_ids:
        protocol_entry = by_id[attack_id]
        shared = ATTACKS[attack_id]
        if protocol_entry.get("type") != shared.type:
            raise ValueError(f"attack type drift for {attack_id}")
        expected_parameters = {
            **shared.parameters,
            **_PROTOCOL_PARAMETER_EXTENSIONS.get(attack_id, {}),
        }
        if protocol_entry.get("parameters") != expected_parameters:
            raise ValueError(f"attack parameter drift for {attack_id}")
    return attack_ids


def protocol_attack_record(
    attack_id: str, protocol: Mapping[str, Any]
) -> dict[str, Any]:
    for entry in protocol["attacks"]:
        if entry["id"] == attack_id:
            return dict(entry)
    raise KeyError(attack_id)


def attack_contract_hash(attacks: list[str], protocol: Mapping[str, Any]) -> str:
    return _canonical_json_hash(
        [
            {
                "protocol": protocol_attack_record(attack_id, protocol),
                "shared_config_sha256": ATTACKS[attack_id].config_hash,
            }
            for attack_id in attacks
        ]
    )


def attack_parameters_json(attack_id: str, protocol: Mapping[str, Any]) -> str:
    return _canonical_json_bytes(
        protocol_attack_record(attack_id, protocol).get("parameters", {})
    ).decode("utf-8")


def attack_severity(attack_id: str, protocol: Mapping[str, Any]) -> str:
    parameters = protocol_attack_record(attack_id, protocol).get("parameters", {})
    if not parameters:
        return "identity"
    return ";".join(
        f"{key}={json.dumps(value, ensure_ascii=False, sort_keys=True)}"
        for key, value in sorted(parameters.items())
    )


def protocol_attack_sha256(attack_id: str, protocol: Mapping[str, Any]) -> str:
    return _canonical_json_hash(protocol_attack_record(attack_id, protocol))


def source_tree_sha256(source_root: Path) -> tuple[str, int]:
    tracked = subprocess.run(
        ["git", "-C", str(source_root), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.split(b"\0")
    digest = hashlib.sha256()
    count = 0
    for raw_relative in sorted(item for item in tracked if item):
        relative = raw_relative.decode("utf-8")
        path = source_root / relative
        file_sha = sha256_file(path)
        if file_sha is None:
            raise FileNotFoundError(path)
        digest.update(relative.encode("utf-8") + b"\0" + file_sha.encode("ascii") + b"\n")
        count += 1
    return digest.hexdigest(), count


def verify_source(source_root: Path) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"LIDMark source missing: {logical_path(source_root)}")
    commit = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(source_root), "status", "--porcelain=v1"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout
    tree_sha, tracked_count = source_tree_sha256(source_root)
    if commit != EXPECTED_SOURCE_COMMIT:
        raise RuntimeError(f"source commit mismatch: {commit}")
    if status.strip():
        raise RuntimeError("LIDMark source worktree must be clean")
    if tree_sha != EXPECTED_SOURCE_TREE_SHA256:
        raise RuntimeError("LIDMark tracked source SHA-256 mismatch")
    return {
        "path": logical_path(source_root),
        "commit": commit,
        "clean": True,
        "tracked_file_count": tracked_count,
        "tracked_tree_sha256": tree_sha,
    }


def verify_training_config(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    actual_sha = sha256_file(path)
    if actual_sha != input_expectation(
        "training_config_sha256", EXPECTED_TRAINING_CONFIG_SHA256
    ):
        raise RuntimeError("training config SHA-256 mismatch")
    try:
        import yaml

        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except ImportError:
        config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "img_size": IMG_SIZE,
        "watermark_length": PAYLOAD_LENGTH,
        "encoder_channels": 64,
        "encoder_blocks": 3,
        "decoder_channels": 64,
        "decoder_blocks": 1,
        "sep_model": False,
        "seed": input_expectation("training_seed", 20260603),
    }
    if not isinstance(config, Mapping):
        raise ValueError("training config must be a mapping")
    for key, expected in required.items():
        if config.get(key) != expected:
            raise RuntimeError(f"training config mismatch for {key}")
    return {
        "path": logical_path(path),
        "sha256": actual_sha,
        "architecture": required,
    }


def verify_checkpoint_selection(
    checkpoint: Path, selection_report: Path
) -> dict[str, Any]:
    checkpoint = checkpoint.expanduser().resolve()
    selection_report = selection_report.expanduser().resolve()
    selection_sha = sha256_file(selection_report)
    expected_selection_sha = input_expectation(
        "selection_sha256", EXPECTED_SELECTION_SHA256
    )
    expected_checkpoint_sha = input_expectation(
        "checkpoint_sha256", EXPECTED_CHECKPOINT_SHA256
    )
    expected_checkpoint_size = input_expectation(
        "checkpoint_size_bytes", EXPECTED_CHECKPOINT_SIZE
    )
    expected_epoch = input_expectation("selected_epoch", 20)
    if selection_sha != expected_selection_sha:
        raise RuntimeError("model-selection report SHA-256 mismatch")
    selection = _read_json(selection_report)
    selected = selection.get("selected")
    if not isinstance(selected, Mapping) or int(selected.get("epoch", -1)) != expected_epoch:
        raise RuntimeError("model-selection report selected an unexpected epoch")
    record = selected.get("checkpoint")
    if not isinstance(record, Mapping) or record.get("verified") is not True:
        raise RuntimeError("selected checkpoint lacks integrity verification")
    actual_sha = sha256_file(checkpoint)
    actual_size = checkpoint.stat().st_size if checkpoint.is_file() else -1
    if actual_sha != expected_checkpoint_sha or actual_sha != record.get("sha256"):
        raise RuntimeError("selected checkpoint SHA-256 mismatch")
    if actual_size != expected_checkpoint_size or actual_size != int(
        record.get("size_bytes", -1)
    ):
        raise RuntimeError("selected checkpoint size mismatch")
    if logical_path(checkpoint) != record.get("path"):
        raise RuntimeError("selected checkpoint logical path mismatch")
    if selection.get("all_checkpoint_integrity_verified") is not True:
        raise RuntimeError("model-selection integrity gate is not complete")
    return {
        "selection_report": logical_path(selection_report),
        "selection_report_sha256": selection_sha,
        "selected_epoch": expected_epoch,
        "checkpoint": logical_path(checkpoint),
        "checkpoint_sha256": actual_sha,
        "checkpoint_size_bytes": actual_size,
    }


def _parse_file_hashes(path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        digest, separator, relative = line.partition("  ")
        if not separator or not _SHA256.fullmatch(digest):
            raise ValueError(f"invalid files.sha256 line {line_number}")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"unsafe files.sha256 path at line {line_number}")
        if relative in hashes:
            raise ValueError(f"duplicate files.sha256 path: {relative}")
        hashes[relative] = digest
    return hashes


def identity_disjoint_proof(
    splits: Mapping[str, Any],
    identities: list[Mapping[str, Any]],
    selected_identities: set[str],
) -> dict[str, Any]:
    split_records = splits.get("splits")
    if splits.get("identity_disjoint") is not True or not isinstance(
        split_records, Mapping
    ):
        raise RuntimeError("source split manifest is not identity-disjoint")
    identity_sets: dict[str, set[str]] = {}
    for split in ("train", "val", "test"):
        record = split_records.get(split)
        if not isinstance(record, Mapping) or not isinstance(record.get("identities"), list):
            raise ValueError(f"invalid source split record: {split}")
        values = {str(value) for value in record["identities"]}
        if len(values) != int(record.get("identity_count", -1)):
            raise RuntimeError(f"identity count mismatch for {split}")
        identity_sets[split] = values
    overlaps = {
        "train_val": sorted(identity_sets["train"] & identity_sets["val"]),
        "train_test": sorted(identity_sets["train"] & identity_sets["test"]),
        "val_test": sorted(identity_sets["val"] & identity_sets["test"]),
    }
    if any(overlaps.values()):
        raise RuntimeError("source identity splits overlap")
    if not selected_identities <= identity_sets["test"]:
        raise RuntimeError("selected samples include a non-test identity")
    identity_map = {str(item["identity"]): str(item["split"]) for item in identities}
    if len(identity_map) != len(identities):
        raise RuntimeError("identity map contains duplicates")
    split_identity_union = set().union(*identity_sets.values())
    if set(identity_map) != split_identity_union:
        raise RuntimeError("identity map and split manifest cover different identities")
    for split, values in identity_sets.items():
        if any(identity_map.get(identity) != split for identity in values):
            raise RuntimeError(f"identity map disagrees with {split} split")
    return {
        "identity_disjoint": True,
        "overlap_counts": {key: len(value) for key, value in overlaps.items()},
        "source_identity_counts": {
            split: len(values) for split, values in identity_sets.items()
        },
        "selected_test_identity_count": len(selected_identities),
        "selected_identities_subset_of_test": True,
        "identity_map_matches_split_union": True,
    }


def prepare_dataset(
    dataset_root: Path, num_images: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dataset_root = dataset_root.expanduser().resolve()
    if num_images < 0:
        raise ValueError("num-images must be non-negative")
    manifests = dataset_root / "manifests"
    source_paths = {
        "dataset_manifest": manifests / "dataset_manifest.json",
        "splits": manifests / "splits.json",
        "identity_map": manifests / "identity_map.json",
        "files": manifests / "files.sha256",
    }
    expected_hashes = {
        "dataset_manifest": EXPECTED_DATASET_MANIFEST_SHA256,
        "splits": EXPECTED_SPLITS_SHA256,
        "identity_map": EXPECTED_IDENTITY_MAP_SHA256,
        "files": EXPECTED_FILES_MANIFEST_SHA256,
    }
    actual_hashes: dict[str, str] = {}
    for name, path in source_paths.items():
        actual = sha256_file(path)
        if actual != expected_hashes[name]:
            raise RuntimeError(f"frozen dataset {name} SHA-256 mismatch")
        actual_hashes[name] = actual

    source_manifest = _read_json(source_paths["dataset_manifest"])
    splits = _read_json(source_paths["splits"])
    identity_map_payload = _read_json(source_paths["identity_map"])
    if source_manifest.get("identity_disjoint") is not True or int(
        source_manifest.get("failure_count", -1)
    ) != 0:
        raise RuntimeError("frozen dataset manifest failed its generation gates")
    hash_record = source_manifest.get("file_hash_manifest")
    if not isinstance(hash_record, Mapping) or hash_record.get("sha256") != actual_hashes[
        "files"
    ]:
        raise RuntimeError("dataset manifest does not bind files.sha256")
    file_hashes = _parse_file_hashes(source_paths["files"])
    if len(file_hashes) != int(hash_record.get("entry_count", -1)):
        raise RuntimeError("files.sha256 entry count mismatch")

    identity_records = identity_map_payload.get("identities")
    if identity_map_payload.get("collision_free") is not True or not isinstance(
        identity_records, list
    ):
        raise RuntimeError("identity map collision-free gate failed")
    identity_by_name = {str(item["identity"]): item for item in identity_records}
    if len(identity_by_name) != len(identity_records):
        raise RuntimeError("identity map contains duplicate identities")

    image_root = dataset_root / "image" / "lfw_128" / "test"
    payload_root = dataset_root / "watermark_152" / "lfw" / "128" / "test"
    images = sorted(image_root.glob("*.jpg"), key=lambda path: path.name)
    payload_names = {path.stem for path in payload_root.glob("*.npy")}
    if len(images) != EXPECTED_TEST_SAMPLES or len(payload_names) != EXPECTED_TEST_SAMPLES:
        raise RuntimeError("frozen LFW test split sample count mismatch")
    if {path.stem for path in images} != payload_names:
        raise RuntimeError("test image/payload pairing mismatch")
    selected = images if num_images == 0 else images[:num_images]
    if num_images > len(images):
        raise RuntimeError(
            f"requested {num_images} images but test split contains {len(images)}"
        )
    if not selected:
        raise RuntimeError("selected LFW test split is empty")

    samples: list[dict[str, Any]] = []
    selected_identities: set[str] = set()
    for image_path in selected:
        identity = identity_from_filename(image_path.name)
        selected_identities.add(identity)
        identity_record = identity_by_name.get(identity)
        if not isinstance(identity_record, Mapping) or identity_record.get("split") != "test":
            raise RuntimeError(f"identity is not assigned to test: {identity}")
        payload_path = payload_root / f"{image_path.stem}.npy"
        image_relative = image_path.relative_to(dataset_root).as_posix()
        payload_relative = payload_path.relative_to(dataset_root).as_posix()
        image_sha = sha256_file(image_path)
        payload_sha = sha256_file(payload_path)
        if image_sha != file_hashes.get(image_relative):
            raise RuntimeError(f"frozen image SHA-256 mismatch: {image_path.name}")
        if payload_sha != file_hashes.get(payload_relative):
            raise RuntimeError(f"frozen payload SHA-256 mismatch: {payload_path.name}")
        payload = np.load(payload_path, allow_pickle=False)
        if (
            payload.shape != (PAYLOAD_LENGTH,)
            or payload.dtype != np.float32
            or not np.isfinite(payload).all()
        ):
            raise RuntimeError(f"invalid LIDMark payload: {payload_path.name}")
        if np.any(payload[:LANDMARK_LENGTH] < 0.0) or np.any(
            payload[:LANDMARK_LENGTH] > 1.0
        ):
            raise RuntimeError(f"landmarks outside [0,1]: {payload_path.name}")
        identity_values = payload[LANDMARK_LENGTH:]
        if not np.all(np.isin(identity_values, (-1.0, 1.0))):
            raise RuntimeError(f"identity payload is not bipolar: {payload_path.name}")
        expected_code = np.asarray(identity_record["bipolar_code"], dtype=np.float32)
        if expected_code.shape != (IDENTITY_LENGTH,) or not np.array_equal(
            identity_values, expected_code
        ):
            raise RuntimeError(f"identity payload/code mismatch: {payload_path.name}")
        message = (identity_values > 0).astype(np.uint8)
        samples.append(
            {
                "sample_id": f"test/{image_path.name}",
                "identity": identity,
                "image_path": image_path,
                "payload_path": payload_path,
                "source_path": image_relative,
                "payload_relative": payload_relative,
                "image_sha256": image_sha,
                "image_size_bytes": image_path.stat().st_size,
                "payload_sha256": payload_sha,
                "payload_size_bytes": payload_path.stat().st_size,
                "message_sha256": hashlib.sha256(message.tobytes()).hexdigest(),
            }
        )
    if len({sample["sample_id"] for sample in samples}) != len(samples):
        raise RuntimeError("dataset sample IDs are not unique")

    proof = identity_disjoint_proof(splits, identity_records, selected_identities)
    proof.update(
        {
            "source_manifests": {
                name: {"path": logical_path(path), "sha256": actual_hashes[name]}
                for name, path in source_paths.items()
            },
            "frozen_test_sample_count": len(images),
        }
    )
    return samples, proof


def dataset_manifest_payload(
    dataset_root: Path,
    samples: list[Mapping[str, Any]],
    proof: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    files = [
        {
            "sample_id": sample["sample_id"],
            "identity": sample["identity"],
            "path": sample["source_path"],
            "size_bytes": sample["image_size_bytes"],
            "sha256": sample["image_sha256"],
            "payload_path": sample["payload_relative"],
            "payload_size_bytes": sample["payload_size_bytes"],
            "payload_sha256": sample["payload_sha256"],
            "message_sha256": sample["message_sha256"],
            "split": "test",
        }
        for sample in samples
    ]
    payload = {
        "schema_version": "dataset-manifest.v1",
        "extension_schema": "lidmark-identity-test-dataset.v1",
        "dataset_root": logical_path(dataset_root),
        "selection": "sorted_filename:first:N; zero means complete test split",
        "seed": seed,
        "sample_count": len(files),
        "identity_count": len({record["identity"] for record in files}),
        "identity_disjoint_proof": dict(proof),
        "files": files,
        "files_digest_sha256": _canonical_json_hash(files),
    }
    _assert_no_absolute_paths(payload, "dataset_manifest")
    return payload


def ensure_dataset_manifest(
    path: Path, expected: Mapping[str, Any], resume: bool
) -> dict[str, Any]:
    if path.exists():
        current = _read_json(path)
        _assert_no_absolute_paths(current, "existing_dataset_manifest")
        if current != expected:
            raise RuntimeError("existing dataset_manifest.json does not match frozen inputs")
        if not resume:
            raise RuntimeError("dataset manifest exists; pass --resume to continue")
        return current
    _atomic_write_json(path, expected)
    return dict(expected)


def _ensure_run_config(
    path: Path,
    expected: Mapping[str, Any],
    *,
    resume: bool,
    result_state_exists: bool,
) -> None:
    _assert_no_absolute_paths(expected, "run_config")
    if path.exists():
        current = _read_json(path)
        _assert_no_absolute_paths(current, "existing_run_config")
        if current != expected:
            raise RuntimeError("existing run_config.json does not match requested run")
        if not resume:
            raise RuntimeError("run configuration exists; pass --resume to continue")
        return
    if result_state_exists:
        raise RuntimeError("result state exists without run_config.json")
    _atomic_write_json(path, expected)


def verify_postflight_inputs(
    *,
    source_root: Path,
    expected_source: Mapping[str, Any],
    training_config: Path,
    expected_training: Mapping[str, Any],
    checkpoint: Path,
    selection_report: Path,
    expected_checkpoint: Mapping[str, Any],
    dataset_root: Path,
    num_images: int,
    expected_dataset_manifest: Mapping[str, Any],
    dataset_manifest_path: Path,
    expected_run_config: Mapping[str, Any],
    run_config_path: Path,
    expected_protocol_sha256: str,
    expected_attacks: list[str],
    expected_attack_contract_sha256: str,
    expected_evaluator_source: Mapping[str, Any],
    expected_software_environment: Mapping[str, Any],
    seed: int,
) -> dict[str, Any]:
    """Re-hash every frozen input after inference before claiming completion."""

    protocol = load_protocol()
    protocol_path = Path(str(protocol["_source_path"])).resolve()
    protocol_sha = sha256_file(protocol_path)
    attacks = resolve_attacks(protocol)
    if protocol_sha != expected_protocol_sha256:
        raise RuntimeError("evaluation protocol changed during the run")
    if attacks != expected_attacks:
        raise RuntimeError("canonical attack order changed during the run")
    if attack_contract_hash(attacks, protocol) != expected_attack_contract_sha256:
        raise RuntimeError("canonical attack contract changed during the run")
    evaluator_source = evaluator_source_evidence()
    if evaluator_source != dict(expected_evaluator_source):
        raise RuntimeError("evaluation implementation changed during the run")
    software_environment = software_environment_evidence()
    if software_environment != dict(expected_software_environment):
        raise RuntimeError("evaluation software environment changed during the run")

    source = verify_source(source_root)
    training = verify_training_config(training_config)
    checkpoint_evidence = verify_checkpoint_selection(checkpoint, selection_report)
    if source != dict(expected_source):
        raise RuntimeError("LIDMark source evidence changed during the run")
    if training != dict(expected_training):
        raise RuntimeError("training configuration evidence changed during the run")
    if checkpoint_evidence != dict(expected_checkpoint):
        raise RuntimeError("checkpoint-selection evidence changed during the run")

    samples, identity_proof = prepare_dataset(dataset_root, num_images)
    regenerated_manifest = dataset_manifest_payload(
        dataset_root,
        samples,
        identity_proof,
        seed,
    )
    if regenerated_manifest != dict(expected_dataset_manifest):
        raise RuntimeError("frozen dataset contents changed during the run")
    if _read_json(dataset_manifest_path) != dict(expected_dataset_manifest):
        raise RuntimeError("dataset_manifest.json changed during the run")
    if _read_json(run_config_path) != dict(expected_run_config):
        raise RuntimeError("run_config.json changed during the run")

    result = {
        "status": "verified",
        "preflight_postflight_match": True,
        "source_tree_sha256": source["tracked_tree_sha256"],
        "training_config_sha256": training["sha256"],
        "selection_report_sha256": checkpoint_evidence["selection_report_sha256"],
        "checkpoint_sha256": checkpoint_evidence["checkpoint_sha256"],
        "protocol_sha256": protocol_sha,
        "attack_contract_sha256": expected_attack_contract_sha256,
        "evaluator_source_files_digest_sha256": evaluator_source[
            "files_digest_sha256"
        ],
        "software_environment_sha256": _canonical_json_hash(software_environment),
        "dataset_manifest_sha256": sha256_file(dataset_manifest_path),
        "dataset_files_digest_sha256": regenerated_manifest[
            "files_digest_sha256"
        ],
        "run_config_sha256": sha256_file(run_config_path),
        "sample_count": len(samples),
        "identity_disjoint": identity_proof["identity_disjoint"],
        "identity_overlap_counts": identity_proof["overlap_counts"],
    }
    _assert_no_absolute_paths(result, "postflight_input_audit")
    return result


def load_image(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        image = np.asarray(source.convert("RGB"), dtype=np.uint8).copy()
    if image.shape != (IMG_SIZE, IMG_SIZE, 3):
        raise ValueError(f"expected {IMG_SIZE}x{IMG_SIZE} RGB image, got {image.shape}")
    return image


def compute_quality(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float]:
    if reference.shape != candidate.shape or reference.shape != (IMG_SIZE, IMG_SIZE, 3):
        raise ValueError("quality inputs must be matching 128x128 RGB images")
    if reference.dtype != np.uint8 or candidate.dtype != np.uint8:
        raise ValueError("quality inputs must be uint8")
    psnr = float(peak_signal_noise_ratio(reference, candidate, data_range=255))
    ssim = float(
        structural_similarity(reference, candidate, channel_axis=2, data_range=255)
    )
    if not math.isfinite(psnr) or not math.isfinite(ssim):
        raise FloatingPointError("quality metrics must be finite")
    if not -1.0 <= ssim <= 1.0:
        raise ValueError("SSIM is outside [-1,1]")
    return psnr, ssim


def _metric_text(value: float) -> str:
    if not math.isfinite(value):
        raise FloatingPointError("non-finite metric cannot enter raw evidence")
    return f"{value:.10f}"


def _safe_error(stage: str, error: BaseException) -> str:
    return f"{stage}:{type(error).__name__}"


def wilson95(successes: int, total: int) -> dict[str, Any]:
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("Wilson interval requires 0 <= successes <= total and total > 0")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return {
        "successes": successes,
        "total": total,
        "estimate": proportion,
        "lower": 0.0 if successes == 0 else max(0.0, center - margin),
        "upper": 1.0 if successes == total else min(1.0, center + margin),
        "confidence_level": 0.95,
        "method": "Wilson score interval",
    }


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RAW_RESULT_FIELDS:
            raise ValueError(f"raw_results.csv schema mismatch: {logical_path(path)}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError("raw_results.csv contains fields outside the declared schema")
    _assert_no_absolute_paths(rows, "raw_results")
    return rows


def _parse_finite(row: Mapping[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid numeric field {field}") from error
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric field {field}")
    return value


def load_result_rows(
    path: Path,
    samples: list[Mapping[str, Any]],
    attacks: list[str],
    protocol: Mapping[str, Any],
    seed: int,
    success_threshold: float,
) -> dict[tuple[str, str], dict[str, str]]:
    sample_by_id = {str(sample["sample_id"]): sample for sample in samples}
    expected_keys = {
        (sample_id, attack) for sample_id in sample_by_id for attack in attacks
    }
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    quality_by_sample: dict[str, tuple[str, str]] = {}
    metric_fields = (
        "bit_errors",
        "ber",
        "bit_accuracy",
        "identity_exact_match",
        "landmark_aed_px",
        "watermarked_psnr",
        "watermarked_ssim",
        "psnr",
        "ssim",
    )
    for row in _load_csv(path):
        key = (row["sample_id"], row["attack"])
        if key in indexed:
            raise ValueError(f"duplicate raw result key: {key}")
        if key not in expected_keys:
            raise ValueError(f"unexpected raw result key: {key}")
        sample = sample_by_id[key[0]]
        expected_values = {
            "identity": sample["identity"],
            "image_id": sample["sample_id"],
            "source_path": sample["source_path"],
            "payload_path": sample["payload_relative"],
            "payload_sha256": sample["payload_sha256"],
            "message_sha256": sample["message_sha256"],
            "identity_bit_length": str(IDENTITY_LENGTH),
            "attack_type": key[1],
            "attack_transform": ATTACKS[key[1]].type,
            "severity": attack_severity(key[1], protocol),
            "attack_parameters_json": attack_parameters_json(key[1], protocol),
            "attack_config_sha256": ATTACKS[key[1]].config_hash,
            "protocol_attack_sha256": protocol_attack_sha256(key[1], protocol),
            "evidence_level": ATTACKS[key[1]].evidence_level,
            "attack_seed": str(derived_seed(seed, key[0], key[1])),
        }
        for field, expected in expected_values.items():
            if row[field] != str(expected):
                raise ValueError(f"raw result {field} mismatch: {key}")
        if row["error"]:
            if any(row[field] for field in metric_fields):
                raise ValueError(f"error row contains metrics: {key}")
            if row["success"] != "0":
                raise ValueError(f"error row marked successful: {key}")
        else:
            bit_errors = _parse_finite(row, "bit_errors")
            ber = _parse_finite(row, "ber")
            accuracy = _parse_finite(row, "bit_accuracy")
            exact = _parse_finite(row, "identity_exact_match")
            landmark_aed = _parse_finite(row, "landmark_aed_px")
            watermarked_psnr = _parse_finite(row, "watermarked_psnr")
            watermarked_ssim = _parse_finite(row, "watermarked_ssim")
            psnr = _parse_finite(row, "psnr")
            ssim = _parse_finite(row, "ssim")
            if bit_errors != int(bit_errors) or not 0 <= bit_errors <= IDENTITY_LENGTH:
                raise ValueError(f"invalid bit_errors: {key}")
            expected_ber = int(bit_errors) / IDENTITY_LENGTH
            if abs(ber - expected_ber) > 1e-9 or abs(accuracy - (1.0 - ber)) > 1e-9:
                raise ValueError(f"BER/accuracy identity failed: {key}")
            if exact not in (0.0, 1.0) or exact != float(bit_errors == 0):
                raise ValueError(f"identity_exact_match mismatch: {key}")
            if landmark_aed < 0.0:
                raise ValueError(f"negative landmark AED: {key}")
            if not -1.0 <= watermarked_ssim <= 1.0 or not -1.0 <= ssim <= 1.0:
                raise ValueError(f"SSIM outside [-1,1]: {key}")
            if not math.isfinite(watermarked_psnr) or not math.isfinite(psnr):
                raise ValueError(f"non-finite PSNR: {key}")
            expected_success = "1" if accuracy >= success_threshold else "0"
            if row["success"] != expected_success:
                raise ValueError(f"success threshold mismatch: {key}")
            quality = (row["watermarked_psnr"], row["watermarked_ssim"])
            previous_quality = quality_by_sample.setdefault(key[0], quality)
            if previous_quality != quality:
                raise ValueError(f"watermarked quality changed across attacks: {key[0]}")
        indexed[key] = row
    return indexed


def _mean(rows: Iterable[Mapping[str, str]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if not row["error"]]
    if not values:
        return None
    if not all(math.isfinite(value) for value in values):
        raise FloatingPointError(f"non-finite summary input: {field}")
    return round(float(np.mean(values)), 10)


def build_summary(
    result_rows: Mapping[tuple[str, str], Mapping[str, str]],
    samples: list[Mapping[str, Any]],
    attacks: list[str],
    success_threshold: float,
    raw_results_path: Path,
) -> dict[str, Any]:
    expected_keys = {
        (str(sample["sample_id"]), attack) for sample in samples for attack in attacks
    }
    missing = expected_keys - set(result_rows)
    errors = [row for row in result_rows.values() if row["error"]]
    attack_summaries: dict[str, Any] = {}
    for attack in attacks:
        rows = [
            result_rows[(str(sample["sample_id"]), attack)]
            for sample in samples
            if (str(sample["sample_id"]), attack) in result_rows
        ]
        valid = [row for row in rows if not row["error"]]
        success_count = sum(row["success"] == "1" for row in valid)
        exact_count = sum(row["identity_exact_match"] == "1" for row in valid)
        attack_summaries[attack] = {
            "status": "complete" if len(valid) == len(samples) else "incomplete",
            "row_count": len(rows),
            "valid_count": len(valid),
            "error_count": len(rows) - len(valid),
            "mean_ber": _mean(valid, "ber"),
            "mean_bit_accuracy": _mean(valid, "bit_accuracy"),
            "mean_landmark_aed_px": _mean(valid, "landmark_aed_px"),
            "mean_psnr": _mean(valid, "psnr"),
            "mean_ssim": _mean(valid, "ssim"),
            "success_rate": round(success_count / len(valid), 10)
            if valid
            else None,
            "identity_exact_match_rate": round(exact_count / len(valid), 10)
            if valid
            else None,
            "success_rate_wilson95": wilson95(success_count, len(valid))
            if valid
            else None,
            "identity_exact_match_rate_wilson95": wilson95(exact_count, len(valid))
            if valid
            else None,
        }
    valid_all = [row for row in result_rows.values() if not row["error"]]
    complete = not missing and not errors and len(result_rows) == len(expected_keys)
    success_all = sum(row["success"] == "1" for row in valid_all)
    exact_all = sum(row["identity_exact_match"] == "1" for row in valid_all)
    summary = {
        "schema_version": "lidmark-identity-test-summary.v1",
        "project": "鉴源盾",
        "method": "LIDMark",
        "mode": "selected_checkpoint_identity_disjoint_test",
        "status": "complete" if complete else "incomplete",
        "sample_count": len(samples),
        "identity_count": len({sample["identity"] for sample in samples}),
        "attack_count": len(attacks),
        "attack_ids": attacks,
        "expected_result_rows": len(expected_keys),
        "result_rows": len(result_rows),
        "valid_rows": len(valid_all),
        "error_rows": len(errors),
        "missing_rows": len(missing),
        "identity_bit_length": IDENTITY_LENGTH,
        "message_length": IDENTITY_LENGTH,
        "success_threshold": success_threshold,
        "success_definition": f"bit_accuracy >= {success_threshold}",
        "overall": {
            "mean_ber": _mean(valid_all, "ber"),
            "mean_bit_accuracy": _mean(valid_all, "bit_accuracy"),
            "mean_landmark_aed_px": _mean(valid_all, "landmark_aed_px"),
            "mean_psnr": _mean(valid_all, "psnr"),
            "mean_ssim": _mean(valid_all, "ssim"),
            "success_rate_wilson95": wilson95(success_all, len(valid_all))
            if valid_all
            else None,
            "identity_exact_match_rate_wilson95": wilson95(
                exact_all, len(valid_all)
            )
            if valid_all
            else None,
        },
        "watermarked_quality": {
            "mean_psnr": _mean(valid_all, "watermarked_psnr"),
            "mean_ssim": _mean(valid_all, "watermarked_ssim"),
            "reference": "original",
        },
        "attacks": attack_summaries,
        "raw_results_path": logical_path(raw_results_path),
        "raw_results_sha256": sha256_file(raw_results_path),
    }
    _assert_no_absolute_paths(summary, "summary")
    return summary


def ordered_rows(
    rows: Mapping[tuple[str, str], Mapping[str, str]],
    samples: list[Mapping[str, Any]],
    attacks: list[str],
) -> list[Mapping[str, str]]:
    return [
        rows[key]
        for sample in samples
        for attack in attacks
        if (key := (str(sample["sample_id"]), attack)) in rows
    ]


class LIDMarkInference:
    def __init__(
        self,
        encoder: Any,
        decoder: Any,
        device: Any,
        torch_module: Any,
        checkpoint: Path,
    ) -> None:
        self.encoder = encoder
        self.decoder = decoder
        self.device = device
        self.torch = torch_module
        self.checkpoint = checkpoint

    def _image_tensor(self, image: np.ndarray) -> Any:
        tensor = self.torch.from_numpy(image.transpose(2, 0, 1).copy()).float()
        return (tensor.div(127.5).sub(1.0)).unsqueeze(0).to(self.device)

    def encode(self, image: np.ndarray, payload: np.ndarray) -> np.ndarray:
        image_tensor = self._image_tensor(image)
        payload_tensor = self.torch.from_numpy(payload.copy()).float().unsqueeze(0).to(
            self.device
        )
        with self.torch.inference_mode():
            encoded = self.encoder(image_tensor, payload_tensor)
        output = (
            encoded.detach()
            .clamp(-1.0, 1.0)
            .add(1.0)
            .mul(127.5)
            .round()
            .to(device="cpu", dtype=self.torch.uint8)[0]
            .permute(1, 2, 0)
            .numpy()
        )
        return np.ascontiguousarray(output)

    def decode(self, image: np.ndarray) -> dict[str, np.ndarray]:
        tensor = self._image_tensor(image)
        with self.torch.inference_mode():
            landmarks, identity_logits = self.decoder(tensor)
        return {
            "landmarks": landmarks.detach().float().cpu().numpy()[0],
            "identity_logits": identity_logits.detach().float().cpu().numpy()[0],
        }


def build_model(source_root: Path, checkpoint: Path, device_name: str, seed: int) -> Any:
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError(
            "expected exactly one visible CUDA device; "
            f"count={torch.cuda.device_count()}"
        )
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)
    sys.dont_write_bytecode = True
    source_text = str(source_root)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    from model.lidmark import FHD, LIDMarkEncoder

    device = torch.device(device_name)
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if not isinstance(state, Mapping) or not isinstance(state.get("model_state_dict"), Mapping):
        raise ValueError("checkpoint does not contain model_state_dict")
    model_state = state["model_state_dict"]
    encoder_state = {
        key[len("encoder.") :]: value
        for key, value in model_state.items()
        if key.startswith("encoder.")
    }
    decoder_state = {
        key[len("decoder.") :]: value
        for key, value in model_state.items()
        if key.startswith("decoder.")
    }
    unexpected = [
        key
        for key in model_state
        if not key.startswith(("encoder.", "decoder.", "manipulation."))
    ]
    if not encoder_state or not decoder_state or unexpected:
        raise RuntimeError("checkpoint component contract mismatch")
    encoder = LIDMarkEncoder(IMG_SIZE, 64, 3, PAYLOAD_LENGTH)
    decoder = FHD(IMG_SIZE, 64, 1, PAYLOAD_LENGTH)
    encoder.load_state_dict(encoder_state, strict=True)
    decoder.load_state_dict(decoder_state, strict=True)
    encoder = encoder.to(device).eval()
    decoder = decoder.to(device).eval()
    return LIDMarkInference(encoder, decoder, device, torch, checkpoint)


def _base_row(
    sample: Mapping[str, Any],
    attack: str,
    protocol: Mapping[str, Any],
    seed: int,
) -> dict[str, str]:
    return {
        "sample_id": str(sample["sample_id"]),
        "image_id": str(sample["sample_id"]),
        "identity": str(sample["identity"]),
        "source_path": str(sample["source_path"]),
        "payload_path": str(sample["payload_relative"]),
        "attack": attack,
        "attack_type": attack,
        "attack_transform": ATTACKS[attack].type,
        "severity": attack_severity(attack, protocol),
        "attack_parameters_json": attack_parameters_json(attack, protocol),
        "attack_config_sha256": ATTACKS[attack].config_hash,
        "protocol_attack_sha256": protocol_attack_sha256(attack, protocol),
        "evidence_level": ATTACKS[attack].evidence_level,
        "attack_seed": str(derived_seed(seed, str(sample["sample_id"]), attack)),
        "payload_sha256": str(sample["payload_sha256"]),
        "message_sha256": str(sample["message_sha256"]),
        "identity_bit_length": str(IDENTITY_LENGTH),
        "bit_errors": "",
        "ber": "",
        "bit_accuracy": "",
        "identity_exact_match": "",
        "landmark_aed_px": "",
        "watermarked_psnr": "",
        "watermarked_ssim": "",
        "psnr": "",
        "ssim": "",
        "success": "0",
        "error": "",
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_input_expectations(getattr(args, "input_manifest", None))
    if args.flush_every <= 0:
        raise ValueError("flush-every must be positive")
    if args.expected_physical_gpu < 0:
        raise ValueError("expected-physical-gpu must be non-negative")
    require_device_contract(args.device, args.expected_physical_gpu)
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in {":4096:8", ":16:8"}:
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 or :16:8")

    protocol = load_protocol()
    attacks = resolve_attacks(protocol)
    attack_contract_sha = attack_contract_hash(attacks, protocol)
    evaluator_evidence = evaluator_source_evidence()
    software_evidence = software_environment_evidence()
    success_threshold = float(protocol["success_threshold"])
    if args.seed != int(protocol["seed"]):
        raise ValueError("formal LIDMark evaluation seed must equal the protocol seed")
    dataset_root = args.dataset_root.expanduser().resolve()
    checkpoint = args.checkpoint.expanduser().resolve()
    selection_report = args.selection_report.expanduser().resolve()
    training_config = args.training_config.expanduser().resolve()
    source_root = args.source_root.expanduser().resolve()
    report_dir = args.report_dir.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    source_evidence = verify_source(source_root)
    training_evidence = verify_training_config(training_config)
    checkpoint_evidence = verify_checkpoint_selection(checkpoint, selection_report)
    samples, identity_proof = prepare_dataset(dataset_root, args.num_images)

    raw_results_path = report_dir / "raw_results.csv"
    dataset_manifest_path = report_dir / "dataset_manifest.json"
    run_config_path = report_dir / "run_config.json"
    summary_path = report_dir / "summary.json"
    progress_path = report_dir / "progress.json"
    result_state_exists = any(
        path.exists() for path in (raw_results_path, summary_path, progress_path)
    )
    expected_dataset_manifest = dataset_manifest_payload(
        dataset_root, samples, identity_proof, args.seed
    )
    if dataset_manifest_path.exists():
        dataset_manifest = ensure_dataset_manifest(
            dataset_manifest_path, expected_dataset_manifest, args.resume
        )
    else:
        if result_state_exists:
            raise RuntimeError("result state exists without dataset_manifest.json")
        dataset_manifest = ensure_dataset_manifest(
            dataset_manifest_path, expected_dataset_manifest, True
        )
    dataset_manifest_sha = sha256_file(dataset_manifest_path)
    protocol_path = Path(str(protocol["_source_path"])).resolve()
    protocol_sha = sha256_file(protocol_path)
    if dataset_manifest_sha is None or protocol_sha is None:
        raise RuntimeError("evidence input hash unavailable")

    run_config = {
        "schema_version": "lidmark-identity-test-config.v1",
        "method": "LIDMark",
        "mode": "selected_checkpoint_identity_disjoint_test",
        "protocol_version": protocol["schema_version"],
        "protocol_path": logical_path(protocol_path),
        "protocol_sha256": protocol_sha,
        "attack_ids": attacks,
        "attack_count": len(attacks),
        "attack_contract_sha256": attack_contract_sha,
        "evaluation_implementation": evaluator_evidence,
        "software_environment": software_evidence,
        "success_threshold": success_threshold,
        "seed": args.seed,
        "model_input_size": IMG_SIZE,
        "payload_length": PAYLOAD_LENGTH,
        "landmark_length": LANDMARK_LENGTH,
        "identity_bit_length": IDENTITY_LENGTH,
        "bit_decision": "decoder identity logit > 0",
        "message_sha256_definition": (
            "SHA256 of 16 uint8 identity bits derived as payload[136:] > 0"
        ),
        "payload_sha256_definition": "SHA256 of exact NumPy .npy file bytes",
        "uint8_roundtrip_before_attacks": True,
        "quality_metric_references": {
            "watermarked_psnr_ssim": "original vs uint8 watermarked",
            "attacked_psnr_ssim": "original vs attacked watermarked",
            "landmark_aed_px": (
                "mean Euclidean distance over 68 points after multiplying "
                "normalized coordinates by 128"
            ),
        },
        "source": source_evidence,
        "training": training_evidence,
        "checkpoint_selection": checkpoint_evidence,
        "dataset_root": logical_path(dataset_root),
        "dataset_manifest": logical_path(dataset_manifest_path),
        "dataset_manifest_sha256": dataset_manifest_sha,
        "dataset_files_digest_sha256": dataset_manifest["files_digest_sha256"],
        "identity_disjoint_proof": identity_proof,
        "sample_count": len(samples),
        "expected_result_rows": len(samples) * len(attacks),
        "raw_result_schema": RAW_RESULT_FIELDS,
        "device_contract": {
            "logical_device": args.device,
            "physical_gpu_index": args.expected_physical_gpu,
            "cuda_visible_devices": str(args.expected_physical_gpu),
        },
        "determinism": {
            "torch_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cudnn_deterministic": True,
            "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
            "attack_seed_scope": "SHA256(global_seed,sample_id,attack)",
        },
    }
    _ensure_run_config(
        run_config_path,
        run_config,
        resume=args.resume,
        result_state_exists=result_state_exists,
    )

    result_rows = load_result_rows(
        raw_results_path,
        samples,
        attacks,
        protocol,
        args.seed,
        success_threshold,
    )
    expected_keys = {
        (str(sample["sample_id"]), attack) for sample in samples for attack in attacks
    }
    model = build_model(source_root, checkpoint, args.device, args.seed)
    if Path(model.checkpoint).resolve() != checkpoint:
        raise RuntimeError("inference model did not bind the selected checkpoint")
    started = time.time()

    def flush(processed: int, status: str) -> None:
        _atomic_write_csv(
            raw_results_path,
            RAW_RESULT_FIELDS,
            ordered_rows(result_rows, samples, attacks),
        )
        summary = build_summary(
            result_rows,
            samples,
            attacks,
            success_threshold,
            raw_results_path,
        )
        if summary["status"] == "complete" and status != "complete":
            summary["status"] = "auditing"
        summary["dataset_manifest_path"] = logical_path(dataset_manifest_path)
        summary["dataset_manifest_sha256"] = sha256_file(dataset_manifest_path)
        summary["run_config_path"] = logical_path(run_config_path)
        summary["run_config_sha256"] = sha256_file(run_config_path)
        _assert_no_absolute_paths(summary, "progress_summary")
        _atomic_write_json(summary_path, summary)
        elapsed = max(0.0, time.time() - started)
        remaining = len(samples) - processed
        eta = elapsed / processed * remaining if processed else None
        _atomic_write_json(
            progress_path,
            {
                "schema_version": "lidmark-identity-test-progress.v1",
                "status": status,
                "processed_samples": processed,
                "total_samples": len(samples),
                "result_rows": len(result_rows),
                "expected_result_rows": len(expected_keys),
                "error_rows": sum(bool(row["error"]) for row in result_rows.values()),
                "elapsed_seconds": round(elapsed, 3),
                "eta_seconds": round(eta, 3) if eta is not None else None,
            },
        )

    for index, sample in enumerate(samples):
        sample_id = str(sample["sample_id"])
        pending_attacks = [
            attack
            for attack in attacks
            if (sample_id, attack) not in result_rows
            or bool(result_rows[(sample_id, attack)]["error"])
        ]
        if not pending_attacks:
            if (index + 1) % args.flush_every == 0:
                flush(index + 1, "running")
            continue
        payload = np.load(sample["payload_path"], allow_pickle=False)
        try:
            original = load_image(sample["image_path"])
            encoded = np.asarray(model.encode(original, payload), dtype=np.uint8)
            if encoded.shape != original.shape:
                raise ValueError("encoder changed image shape")
            watermarked_psnr, watermarked_ssim = compute_quality(original, encoded)
        except Exception as error:
            safe_error = _safe_error("encode", error)
            for attack in pending_attacks:
                row = _base_row(sample, attack, protocol, args.seed)
                row["error"] = safe_error
                result_rows[(sample_id, attack)] = row
            if (index + 1) % args.flush_every == 0:
                flush(index + 1, "running")
            continue

        truth_landmarks = payload[:LANDMARK_LENGTH].reshape(68, 2)
        truth_identity = payload[LANDMARK_LENGTH:] > 0
        for attack in pending_attacks:
            row = _base_row(sample, attack, protocol, args.seed)
            try:
                attacked, attack_metadata = apply_attack(
                    encoded,
                    attack,
                    image_id=sample_id,
                    global_seed=args.seed,
                )
                expected_attack_metadata = {
                    "attack_id": attack,
                    "attack_type": ATTACKS[attack].type,
                    "parameters": ATTACKS[attack].parameters,
                    "category": ATTACKS[attack].category,
                    "evidence_level": ATTACKS[attack].evidence_level,
                    "config_hash": ATTACKS[attack].config_hash,
                    "global_seed": args.seed,
                    "derived_seed": derived_seed(args.seed, sample_id, attack),
                }
                if attack_metadata != expected_attack_metadata:
                    raise RuntimeError("shared attack metadata contract mismatch")
                decoded = model.decode(attacked)
                landmarks = np.asarray(decoded["landmarks"], dtype=np.float32).reshape(-1)
                identity_logits = np.asarray(
                    decoded["identity_logits"], dtype=np.float32
                ).reshape(-1)
                if landmarks.shape != (LANDMARK_LENGTH,) or identity_logits.shape != (
                    IDENTITY_LENGTH,
                ):
                    raise ValueError("decoder output shape mismatch")
                if not np.isfinite(landmarks).all() or not np.isfinite(
                    identity_logits
                ).all():
                    raise FloatingPointError("decoder output is non-finite")
                prediction = identity_logits > 0
                bit_errors = int(np.count_nonzero(prediction != truth_identity))
                ber = bit_errors / IDENTITY_LENGTH
                accuracy = 1.0 - ber
                landmark_aed = float(
                    np.linalg.norm(
                        (landmarks.reshape(68, 2) - truth_landmarks) * IMG_SIZE,
                        axis=1,
                    ).mean()
                )
                attacked_psnr, attacked_ssim = compute_quality(original, attacked)
                metrics = (
                    ber,
                    accuracy,
                    landmark_aed,
                    watermarked_psnr,
                    watermarked_ssim,
                    attacked_psnr,
                    attacked_ssim,
                )
                if not all(math.isfinite(value) for value in metrics):
                    raise FloatingPointError("computed metric is non-finite")
                row.update(
                    {
                        "bit_errors": str(bit_errors),
                        "ber": _metric_text(ber),
                        "bit_accuracy": _metric_text(accuracy),
                        "identity_exact_match": "1" if bit_errors == 0 else "0",
                        "landmark_aed_px": _metric_text(landmark_aed),
                        "watermarked_psnr": _metric_text(watermarked_psnr),
                        "watermarked_ssim": _metric_text(watermarked_ssim),
                        "psnr": _metric_text(attacked_psnr),
                        "ssim": _metric_text(attacked_ssim),
                        "success": "1" if accuracy >= success_threshold else "0",
                    }
                )
            except Exception as error:
                row["error"] = _safe_error("attack_or_decode", error)
            result_rows[(sample_id, attack)] = row

        if (index + 1) % args.flush_every == 0:
            flush(index + 1, "running")
            print(
                f"[{index + 1}/{len(samples)}] rows={len(result_rows)}/{len(expected_keys)} "
                f"errors={sum(bool(row['error']) for row in result_rows.values())}",
                flush=True,
            )

    flush(len(samples), "auditing")
    result_rows = load_result_rows(
        raw_results_path,
        samples,
        attacks,
        protocol,
        args.seed,
        success_threshold,
    )
    summary = build_summary(
        result_rows, samples, attacks, success_threshold, raw_results_path
    )
    summary["input_integrity_audit"] = verify_postflight_inputs(
        source_root=source_root,
        expected_source=source_evidence,
        training_config=training_config,
        expected_training=training_evidence,
        checkpoint=checkpoint,
        selection_report=selection_report,
        expected_checkpoint=checkpoint_evidence,
        dataset_root=dataset_root,
        num_images=args.num_images,
        expected_dataset_manifest=expected_dataset_manifest,
        dataset_manifest_path=dataset_manifest_path,
        expected_run_config=run_config,
        run_config_path=run_config_path,
        expected_protocol_sha256=protocol_sha,
        expected_attacks=attacks,
        expected_attack_contract_sha256=attack_contract_sha,
        expected_evaluator_source=evaluator_evidence,
        expected_software_environment=software_evidence,
        seed=args.seed,
    )
    summary["dataset_manifest_path"] = logical_path(dataset_manifest_path)
    summary["dataset_manifest_sha256"] = sha256_file(dataset_manifest_path)
    summary["run_config_path"] = logical_path(run_config_path)
    summary["run_config_sha256"] = sha256_file(run_config_path)
    if summary["status"] != "complete":
        _assert_no_absolute_paths(summary, "incomplete_summary")
        _atomic_write_json(summary_path, summary)
        _atomic_write_json(
            progress_path,
            {
                "schema_version": "lidmark-identity-test-progress.v1",
                "status": "incomplete",
                "processed_samples": len(samples),
                "total_samples": len(samples),
                "result_rows": len(result_rows),
                "expected_result_rows": len(expected_keys),
                "error_rows": summary["error_rows"],
            },
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
        return 2

    summary = finalize_benchmark_summary(
        summary,
        model="LIDMark",
        checkpoint=checkpoint,
        results_path=raw_results_path,
        dataset_manifest_path=dataset_manifest_path,
        sample_count=len(samples),
        seed=args.seed,
        attack_ids=attacks,
        command=sys.argv if argv is None else [str(Path(__file__).name), *argv],
    )
    summary["run_config_path"] = logical_path(run_config_path)
    summary["run_config_sha256"] = sha256_file(run_config_path)
    summary["selection_report_path"] = logical_path(selection_report)
    selection_sha256 = input_expectation("selection_sha256", EXPECTED_SELECTION_SHA256)
    summary["selection_report_sha256"] = selection_sha256
    summary["checkpoint_manifest_path"] = logical_path(selection_report)
    summary["checkpoint_manifest_sha256"] = selection_sha256
    summary["identity_disjoint_proof"] = identity_proof
    _assert_no_absolute_paths(summary, "final_summary")
    _atomic_write_json(summary_path, summary)
    _atomic_write_json(
        progress_path,
        {
            "schema_version": "lidmark-identity-test-progress.v1",
            "status": "complete",
            "processed_samples": len(samples),
            "total_samples": len(samples),
            "result_rows": len(result_rows),
            "expected_result_rows": len(expected_keys),
            "error_rows": 0,
        },
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
