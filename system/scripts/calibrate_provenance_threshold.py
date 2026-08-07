#!/usr/bin/env python3
"""Calibrate a checkpoint-bound provenance threshold with held-out controls."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageOps


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Required by deterministic CUDA matrix multiplication on recent NVIDIA GPUs.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

from system.evaluation.adapters import get_available_adapters  # noqa: E402
from system.evaluation.attacks import ATTACKS, apply_attack  # noqa: E402
from system.evaluation.identity import (  # noqa: E402
    IDENTITY_DERIVATION,
    calibration_identity_sha256,
)
from system.evaluation.protocol import load_protocol  # noqa: E402
from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.evaluation.runtime import logical_path  # noqa: E402


SCHEMA_VERSION = "threshold-calibration.v1"
CONTROLS = ("registered_roundtrip", "unwatermarked", "wrong_message")
NEGATIVE_CONTROLS = ("unwatermarked", "wrong_message")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
WILSON_Z_95 = 1.959963984540054


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    protocol = load_protocol()
    parser = argparse.ArgumentParser(
        description="Calibrate provenance verification on disjoint calibration and holdout identities.",
    )
    parser.add_argument("--model", required=True, help="Name registered by get_available_adapters().")
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-images", type=int, default=16)
    parser.add_argument(
        "--attacks",
        nargs="+",
        default=[str(item["id"]) for item in protocol["attacks"]],
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=int(protocol["seed"]))
    parser.add_argument("--target-far", type=float, default=0.01)
    parser.add_argument("--flush-every", type=int, default=8)
    return parser.parse_args(argv)


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _assert_no_absolute_paths(payload: Any, context: str = "artifact") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            _assert_no_absolute_paths(value, f"{context}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _assert_no_absolute_paths(value, f"{context}[{index}]")
    elif isinstance(payload, str):
        if Path(payload).is_absolute() or WINDOWS_ABSOLUTE.match(payload):
            raise ValueError(f"absolute host path forbidden in {context}")


def resolve_attacks(requested: Sequence[str], protocol: dict[str, Any]) -> list[str]:
    selected = [str(value) for value in requested]
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("attacks must contain unique canonical IDs")
    registered = {str(item["id"]): item for item in protocol["attacks"]}
    unknown = [attack_id for attack_id in selected if attack_id not in registered]
    if unknown:
        raise ValueError("non-canonical attack IDs: " + ", ".join(unknown))
    unavailable = [attack_id for attack_id in selected if attack_id not in ATTACKS]
    if unavailable:
        raise ValueError("canonical attack implementations missing: " + ", ".join(unavailable))
    for attack_id in selected:
        shared = ATTACKS[attack_id]
        protocol_attack = registered[attack_id]
        if protocol_attack.get("type") != shared.type:
            raise ValueError(f"attack type drift: {attack_id}")
        for key, value in shared.parameters.items():
            if protocol_attack.get("parameters", {}).get(key) != value:
                raise ValueError(f"attack parameter drift: {attack_id}.{key}")
    return selected


def _image_identifier(path: Path, root: Path) -> str:
    identifier = path.resolve().relative_to(root.resolve()).as_posix()
    if not identifier or identifier.startswith("../") or Path(identifier).is_absolute():
        raise ValueError("image identifier must be dataset-relative")
    return identifier


def select_images(image_root: Path, num_images: int, seed: int) -> list[Path]:
    root = image_root.expanduser().resolve()
    if num_images < 2:
        raise ValueError("num-images must be at least two")
    if not root.is_dir():
        raise FileNotFoundError(f"image root not found: {logical_path(root)}")
    images = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if len(images) < num_images:
        raise RuntimeError(f"requested {num_images} images but dataset contains {len(images)}")
    images.sort(key=lambda path: (
        hashlib.sha256(
            f"threshold-calibration.image-selection.v1\0{seed}\0{_image_identifier(path, root)}".encode("utf-8")
        ).hexdigest(),
        _image_identifier(path, root),
    ))
    return images[:num_images]


def identity_sha256(identifier: str) -> str:
    return calibration_identity_sha256(identifier)


def deterministic_splits(identifiers: Sequence[str], seed: int) -> dict[str, str]:
    """Split whole identities while keeping image counts approximately balanced."""

    groups: dict[str, list[str]] = defaultdict(list)
    for identifier in identifiers:
        groups[identity_sha256(identifier)].append(identifier)
    if len(groups) < 2:
        raise ValueError("at least two identities/images are required for disjoint splits")
    ranked = sorted(
        groups,
        key=lambda identity: (
            hashlib.sha256(
                f"threshold-calibration.identity-split.v1\0{seed}\0{identity}".encode("utf-8")
            ).hexdigest(),
            identity,
        ),
    )
    counts = {"calibration": 0, "holdout": 0}
    assignment: dict[str, str] = {}
    for identity in ranked:
        split = "calibration" if counts["calibration"] <= counts["holdout"] else "holdout"
        for identifier in groups[identity]:
            assignment[identifier] = split
        counts[split] += len(groups[identity])
    if not counts["calibration"] or not counts["holdout"]:
        raise RuntimeError("deterministic split did not produce both partitions")
    return assignment


def derive_message(seed: int, identifier: str, length: int, purpose: str) -> np.ndarray:
    if length <= 0:
        raise ValueError("adapter message length must be positive")
    payload = f"threshold-calibration.message.v1\0{purpose}\0{seed}\0{identifier}".encode("utf-8")
    packed = hashlib.shake_256(payload).digest((length + 7) // 8)
    return np.unpackbits(np.frombuffer(packed, dtype=np.uint8), bitorder="big")[:length].astype(np.uint8)


def message_sha256(message: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(message, dtype=np.uint8).reshape(-1).tobytes()).hexdigest()


def wrong_message(seed: int, identifier: str, registered: np.ndarray) -> np.ndarray:
    wrong = derive_message(seed, identifier, registered.size, "wrong")
    if np.array_equal(wrong, registered):
        wrong = wrong.copy()
        wrong[0] ^= np.uint8(1)
    return wrong


def bit_accuracy(decoded: np.ndarray, expected: np.ndarray) -> float:
    bits = np.asarray(decoded, dtype=np.uint8).reshape(-1)
    target = np.asarray(expected, dtype=np.uint8).reshape(-1)
    if bits.shape != target.shape or not np.isin(bits, (0, 1)).all():
        raise ValueError("decoder output does not match the binary message contract")
    return float(np.mean(bits == target))


def wilson_interval(successes: int, total: int) -> dict[str, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("Wilson interval requires 0 <= successes <= total and total > 0")
    proportion = successes / total
    z2 = WILSON_Z_95 * WILSON_Z_95
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    margin = (
        WILSON_Z_95
        * math.sqrt(proportion * (1.0 - proportion) / total + z2 / (4.0 * total * total))
        / denominator
    )
    return {
        "confidence_level": 0.95,
        "lower": 0.0 if successes == 0 else max(0.0, center - margin),
        "upper": 1.0 if successes == total else min(1.0, center + margin),
    }


def _decision_metrics(samples: Sequence[dict[str, Any]], threshold: float, split: str) -> dict[str, Any]:
    selected = [sample for sample in samples if sample["split"] == split]
    positives = [sample for sample in selected if sample["label"] == "positive"]
    negatives = [sample for sample in selected if sample["label"] == "negative"]
    if not positives or not negatives:
        raise ValueError(f"{split} must contain positive and negative samples")
    true_accepts = sum(float(sample["bit_accuracy"]) >= threshold for sample in positives)
    false_accepts = sum(float(sample["bit_accuracy"]) >= threshold for sample in negatives)
    false_rejects = len(positives) - true_accepts
    true_rejects = len(negatives) - false_accepts
    negative_control_metrics: dict[str, Any] = {}
    for control in NEGATIVE_CONTROLS:
        controls = [sample for sample in negatives if sample["control"] == control]
        if not controls:
            raise ValueError(f"{split} is missing negative control {control}")
        control_false_accepts = sum(float(sample["bit_accuracy"]) >= threshold for sample in controls)
        negative_control_metrics[control] = {
            "samples": len(controls),
            "false_accepts": control_false_accepts,
            "false_accept_rate": control_false_accepts / len(controls),
            "false_accept_rate_wilson_95": wilson_interval(control_false_accepts, len(controls)),
        }
    return {
        "split": split,
        "comparison_operator": ">=",
        "positive_samples": len(positives),
        "negative_samples": len(negatives),
        "true_accepts": true_accepts,
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "true_rejects": true_rejects,
        "true_accept_rate": true_accepts / len(positives),
        "false_accept_rate": false_accepts / len(negatives),
        "false_reject_rate": false_rejects / len(positives),
        "true_reject_rate": true_rejects / len(negatives),
        "true_accept_rate_wilson_95": wilson_interval(true_accepts, len(positives)),
        "false_accept_rate_wilson_95": wilson_interval(false_accepts, len(negatives)),
        "false_reject_rate_wilson_95": wilson_interval(false_rejects, len(positives)),
        "negative_control_metrics": negative_control_metrics,
    }


def select_threshold(
    samples: Sequence[dict[str, Any]],
    target_far: float,
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    """Maximize calibration TPR subject to empirical calibration FAR."""

    if not 0.0 <= target_far <= 1.0:
        raise ValueError("target-FAR must be between zero and one")
    calibration = [sample for sample in samples if sample["split"] == "calibration"]
    scores = {float(sample["bit_accuracy"]) for sample in calibration}
    candidates = {0.0, 1.0}
    for score in scores:
        candidates.add(score)
        above = math.nextafter(score, math.inf)
        if above <= 1.0:
            candidates.add(above)
    evaluated: list[tuple[float, dict[str, Any]]] = []
    for threshold in sorted(candidates):
        metrics = _decision_metrics(samples, threshold, "calibration")
        if metrics["false_accept_rate"] <= target_far + 1e-15:
            evaluated.append((threshold, metrics))
    if not evaluated:
        raise RuntimeError("no threshold in [0,1] satisfies target FAR on calibration split")
    threshold, metrics = min(
        evaluated,
        key=lambda item: (
            -float(item[1]["true_accept_rate"]),
            float(item[1]["false_accept_rate"]),
            float(item[0]),
        ),
    )
    metadata = {
        "split": "calibration",
        "objective": "maximize_tpr_subject_to_empirical_far_lte_target",
        "comparison_operator": ">=",
        "target_false_accept_rate": target_far,
        "candidate_generation": "zero_one_observed_scores_and_nextafter_above",
        "candidate_count": len(candidates),
        "eligible_candidate_count": len(evaluated),
        "tie_breaker": "minimum_far_then_minimum_threshold",
        "selected_threshold": threshold,
        "calibration_positive_samples": metrics["positive_samples"],
        "calibration_negative_samples": metrics["negative_samples"],
        "calibration_negative_controls": list(NEGATIVE_CONTROLS),
        "selected_true_accept_rate": metrics["true_accept_rate"],
        "selected_false_accept_rate": metrics["false_accept_rate"],
        "selected_false_reject_rate": metrics["false_reject_rate"],
    }
    return threshold, metadata, metrics


def _sample_key(identifier: str, attack_id: str, control: str) -> tuple[str, str, str]:
    return identifier, attack_id, control


def _sample_id(model: str, seed: int, identifier: str, attack_id: str, control: str) -> str:
    payload = f"threshold-calibration.sample.v1\0{model}\0{seed}\0{identifier}\0{attack_id}\0{control}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def coverage_report(
    samples: Sequence[dict[str, Any]],
    identifiers: Sequence[str],
    assignments: dict[str, str],
    attacks: Sequence[str],
    *,
    model: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    expected = {
        _sample_key(identifier, attack_id, control)
        for identifier in identifiers
        for attack_id in attacks
        for control in CONTROLS
    }
    actual: set[tuple[str, str, str]] = set()
    duplicates: list[str] = []
    contract_errors: list[str] = []
    for sample in samples:
        key = _sample_key(str(sample["image_id"]), str(sample["attack_id"]), str(sample["control"]))
        if key in actual:
            duplicates.append(canonical_sha256(key))
        actual.add(key)
        if model is not None and seed is not None:
            identifier, attack_id, control = key
            embedded_hash = sample.get("embedded_message_sha256")
            registered_hash = str(sample.get("registered_message_sha256") or "")
            try:
                score = float(sample["bit_accuracy"])
            except (KeyError, TypeError, ValueError):
                score = math.nan
            checks = {
                "sample_id": sample.get("sample_id") == _sample_id(model, seed, *key),
                "identity": sample.get("identity_sha256") == identity_sha256(identifier),
                "split": sample.get("split") == assignments.get(identifier),
                "attack_hash": sample.get("attack_config_sha256") == (
                    ATTACKS[attack_id].config_hash if attack_id in ATTACKS else None
                ),
                "label": sample.get("label") == (
                    "positive" if control == "registered_roundtrip" else "negative"
                ),
                "registered_hash": len(registered_hash) == 64 and all(
                    character in "0123456789abcdef" for character in registered_hash
                ),
                "embedded_hash": embedded_hash is None if control == "unwatermarked" else (
                    isinstance(embedded_hash, str)
                    and len(embedded_hash) == 64
                    and all(character in "0123456789abcdef" for character in embedded_hash)
                ),
                "score": math.isfinite(score) and 0.0 <= score <= 1.0,
            }
            for name, valid in checks.items():
                if not valid:
                    contract_errors.append(canonical_sha256([key, name]))
    expected_counts: Counter[str] = Counter()
    actual_counts: Counter[str] = Counter()
    for identifier, attack_id, control in expected:
        expected_counts[f"{assignments[identifier]}:{control}"] += 1
    for sample in samples:
        actual_counts[f"{sample['split']}:{sample['control']}"] += 1
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    return {
        "expected_rows": len(expected),
        "actual_rows": len(samples),
        "expected_by_split_control": dict(sorted(expected_counts.items())),
        "actual_by_split_control": dict(sorted(actual_counts.items())),
        "missing_sample_key_sha256": [canonical_sha256(key) for key in missing],
        "unexpected_sample_key_sha256": [canonical_sha256(key) for key in unexpected],
        "duplicate_sample_key_sha256": duplicates,
        "row_contract_error_sha256": contract_errors,
        "complete": (
            not missing
            and not unexpected
            and not duplicates
            and not contract_errors
            and len(samples) == len(expected)
        ),
    }


def _safe_error(
    model: str,
    seed: int,
    identifier: str,
    attack_id: str,
    control: str,
    stage: str,
    exc: BaseException,
) -> dict[str, str]:
    return {
        "sample_id": _sample_id(model, seed, identifier, attack_id, control),
        "image_id": identifier,
        "attack_id": attack_id,
        "control": control,
        "stage": stage,
        "error_type": type(exc).__name__,
    }


def _make_sample(
    *,
    model: str,
    seed: int,
    identifier: str,
    identity_hash: str,
    split: str,
    attack_id: str,
    control: str,
    score: float,
    registered_hash: str,
    embedded_hash: str | None,
) -> dict[str, Any]:
    return {
        "sample_id": _sample_id(model, seed, identifier, attack_id, control),
        "image_id": identifier,
        "identity_sha256": identity_hash,
        "split": split,
        "attack_id": attack_id,
        "attack_config_sha256": ATTACKS[attack_id].config_hash,
        "control": control,
        "label": "positive" if control == "registered_roundtrip" else "negative",
        "registered_message_sha256": registered_hash,
        "embedded_message_sha256": embedded_hash,
        "bit_accuracy": score,
    }


def _process_control(
    *,
    adapter: Any,
    source_image: np.ndarray,
    expected_message: np.ndarray,
    embedded_message: np.ndarray | None,
    model: str,
    seed: int,
    identifier: str,
    identity_hash: str,
    split: str,
    attack_id: str,
    control: str,
) -> dict[str, Any]:
    attacked, metadata = apply_attack(
        source_image,
        attack_id,
        image_id=identifier,
        global_seed=seed,
    )
    if metadata.get("config_hash") != ATTACKS[attack_id].config_hash:
        raise RuntimeError("attack metadata hash mismatch")
    decoded = adapter.decode(attacked)
    score = bit_accuracy(decoded.bits, expected_message)
    return _make_sample(
        model=model,
        seed=seed,
        identifier=identifier,
        identity_hash=identity_hash,
        split=split,
        attack_id=attack_id,
        control=control,
        score=score,
        registered_hash=message_sha256(expected_message),
        embedded_hash=message_sha256(embedded_message) if embedded_message is not None else None,
    )


def _dataset_manifest(
    image_root: Path,
    images: Sequence[Path],
    assignments: dict[str, str],
    seed: int,
) -> dict[str, Any]:
    root = image_root.resolve()
    files: list[dict[str, Any]] = []
    for path in sorted(images, key=lambda item: _image_identifier(item, root)):
        identifier = _image_identifier(path, root)
        digest = sha256_file(path)
        if digest is None:
            raise FileNotFoundError(identifier)
        files.append({
            "image_id": identifier,
            "identity_sha256": identity_sha256(identifier),
            "split": assignments[identifier],
            "size_bytes": path.stat().st_size,
            "sha256": digest,
        })
    return {
        "schema_version": "threshold-calibration-dataset.v1",
        "image_root": logical_path(root),
        "selection": "lowest_sha256(threshold-calibration.image-selection.v1,seed,image_id)",
        "identity_derivation": IDENTITY_DERIVATION,
        "split_policy": "identity_grouped_greedy_balance_after_seeded_identity_hash_order",
        "seed": seed,
        "sample_count": len(files),
        "files_digest_sha256": canonical_sha256(files),
        "files": files,
    }


def _configure_determinism(seed: int, device: str) -> None:
    os.environ["JYS_INFER_DEVICE"] = device
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in {":4096:8", ":16:8"}:
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 or :16:8")
    import torch

    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)


def _resolve_adapter(model: str) -> Any:
    adapters = get_available_adapters()
    matches = [name for name in adapters if name.lower() == model.lower()]
    if len(matches) != 1:
        raise RuntimeError(f"model adapter unavailable: {model}")
    adapter = adapters[matches[0]]()
    if not adapter.available or not adapter.checkpoint:
        raise RuntimeError(f"model adapter unavailable: {model}: {adapter.blocker}")
    return adapter


def run_calibration(args: argparse.Namespace) -> dict[str, Any]:
    if not 0.0 <= float(args.target_far) <= 1.0:
        raise ValueError("target-FAR must be between zero and one")
    flush_every = int(getattr(args, "flush_every", 8))
    if flush_every <= 0:
        raise ValueError("flush-every must be positive")
    _configure_determinism(int(args.seed), str(args.device))
    protocol = load_protocol()
    attacks = resolve_attacks(args.attacks, protocol)
    image_root = Path(args.image_root).expanduser().resolve()
    images = select_images(image_root, int(args.num_images), int(args.seed))
    identifiers = [_image_identifier(path, image_root) for path in images]
    assignments = deterministic_splits(identifiers, int(args.seed))
    adapter = _resolve_adapter(str(args.model))
    canonical_model = str(adapter.name)
    checkpoint = Path(str(adapter.checkpoint)).expanduser().resolve()
    checkpoint_hash = sha256_file(checkpoint)
    protocol_path = Path(str(protocol["_source_path"])).resolve()
    protocol_hash = sha256_file(protocol_path)
    if checkpoint_hash is None or protocol_hash is None:
        raise RuntimeError("checkpoint or protocol hash unavailable")
    dataset = _dataset_manifest(image_root, images, assignments, int(args.seed))
    registered_attacks = {str(item["id"]): item for item in protocol["attacks"]}
    attack_contract = [
        {
            "protocol": registered_attacks[attack_id],
            "shared_config_sha256": ATTACKS[attack_id].config_hash,
        }
        for attack_id in attacks
    ]

    resume_contract = {
        "schema_version": "threshold-calibration-resume.v1",
        "model": canonical_model,
        "checkpoint_sha256": checkpoint_hash,
        "protocol_sha256": protocol_hash,
        "attack_ids": attacks,
        "attack_contract_sha256": canonical_sha256(attack_contract),
        "seed": int(args.seed),
        "target_false_accept_rate": float(args.target_far),
        "dataset_manifest_sha256": canonical_sha256(dataset),
    }
    resume_contract_sha256 = canonical_sha256(resume_contract)
    output_path = Path(args.output).expanduser().resolve()
    samples: list[dict[str, Any]] = []
    if output_path.exists():
        try:
            existing = json.loads(
                output_path.read_text(encoding="utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite JSON constant: {value}")
                ),
            )
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("existing calibration artifact is invalid") from exc
        if existing.get("status") == "complete":
            raise FileExistsError("refusing to overwrite a complete calibration artifact")
        if (
            existing.get("resume_contract") != resume_contract
            or existing.get("resume_contract_sha256") != resume_contract_sha256
            or not isinstance(existing.get("samples"), list)
        ):
            raise RuntimeError("existing calibration artifact does not match this run")
        samples = list(existing["samples"])
        try:
            partial_coverage = coverage_report(
                samples,
                identifiers,
                assignments,
                attacks,
                model=canonical_model,
                seed=int(args.seed),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("existing calibration rows are invalid") from exc
        if (
            partial_coverage["unexpected_sample_key_sha256"]
            or partial_coverage["duplicate_sample_key_sha256"]
            or partial_coverage["row_contract_error_sha256"]
        ):
            raise RuntimeError("existing calibration rows violate the run contract")

    errors: list[dict[str, str]] = []
    sample_keys = {
        _sample_key(str(row["image_id"]), str(row["attack_id"]), str(row["control"]))
        for row in samples
    }

    def current_artifact() -> dict[str, Any]:
        ordered_samples = sorted(
            samples,
            key=lambda row: (
                row["image_id"],
                row["attack_id"],
                CONTROLS.index(row["control"]),
            ),
        )
        ordered_errors = sorted(
            errors,
            key=lambda row: (
                row["image_id"],
                row["attack_id"],
                CONTROLS.index(row["control"]),
            ),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "incomplete",
            "model": canonical_model,
            "checkpoint": logical_path(checkpoint),
            "checkpoint_sha256": checkpoint_hash,
            "protocol_version": protocol["schema_version"],
            "protocol_path": logical_path(protocol_path),
            "protocol_sha256": protocol_hash,
            "attack_ids": attacks,
            "attack_contract_sha256": canonical_sha256(attack_contract),
            "seed": int(args.seed),
            "target_false_accept_rate": float(args.target_far),
            "dataset_manifest": dataset,
            "dataset_manifest_sha256": canonical_sha256(dataset),
            "resume_contract": resume_contract,
            "resume_contract_sha256": resume_contract_sha256,
            "threshold": None,
            "threshold_selection": None,
            "calibration_metrics": None,
            "metrics": None,
            "coverage": coverage_report(
                ordered_samples,
                identifiers,
                assignments,
                attacks,
                model=canonical_model,
                seed=int(args.seed),
            ),
            "errors": ordered_errors,
            "samples": ordered_samples,
        }

    def flush_partial() -> dict[str, Any]:
        artifact = current_artifact()
        _assert_no_absolute_paths(artifact)
        _atomic_write_json(output_path, artifact)
        return artifact

    for image_index, (path, identifier) in enumerate(zip(images, identifiers), start=1):
        expected_image_keys = {
            _sample_key(identifier, attack_id, control)
            for attack_id in attacks
            for control in CONTROLS
        }
        if expected_image_keys.issubset(sample_keys):
            if image_index % flush_every == 0:
                flush_partial()
            continue
        split = assignments[identifier]
        identity_hash = identity_sha256(identifier)
        registered = derive_message(int(args.seed), identifier, int(adapter.message_length), "registered")
        wrong = wrong_message(int(args.seed), identifier, registered)
        try:
            with Image.open(path) as opened:
                original = np.array(ImageOps.exif_transpose(opened).convert("RGB"), dtype=np.uint8)
            adapter.validate_image(original)
        except Exception as exc:
            for attack_id in attacks:
                for control in CONTROLS:
                    errors.append(_safe_error(
                        canonical_model, int(args.seed), identifier, attack_id, control, "load_image", exc,
                    ))
            continue

        encoded_registered: np.ndarray | None = None
        encoded_wrong: np.ndarray | None = None
        encode_errors: dict[str, BaseException] = {}
        for control, message in (("registered_roundtrip", registered), ("wrong_message", wrong)):
            try:
                encoded = adapter.encode(original, message)
                adapter.validate_image(encoded.image)
                if Path(str(adapter.checkpoint)).expanduser().resolve() != checkpoint:
                    raise RuntimeError("adapter checkpoint changed during calibration")
                if control == "registered_roundtrip":
                    encoded_registered = np.asarray(encoded.image, dtype=np.uint8)
                else:
                    encoded_wrong = np.asarray(encoded.image, dtype=np.uint8)
            except Exception as exc:
                encode_errors[control] = exc

        for attack_id in attacks:
            sources = {
                "registered_roundtrip": (encoded_registered, registered),
                "unwatermarked": (original, None),
                "wrong_message": (encoded_wrong, wrong),
            }
            for control in CONTROLS:
                key = _sample_key(identifier, attack_id, control)
                if key in sample_keys:
                    continue
                source, embedded = sources[control]
                if source is None:
                    errors.append(_safe_error(
                        canonical_model,
                        int(args.seed),
                        identifier,
                        attack_id,
                        control,
                        "encode",
                        encode_errors[control],
                    ))
                    continue
                try:
                    sample = _process_control(
                        adapter=adapter,
                        source_image=source,
                        expected_message=registered,
                        embedded_message=embedded,
                        model=canonical_model,
                        seed=int(args.seed),
                        identifier=identifier,
                        identity_hash=identity_hash,
                        split=split,
                        attack_id=attack_id,
                        control=control,
                    )
                    samples.append(sample)
                    sample_keys.add(key)
                except Exception as exc:
                    errors.append(_safe_error(
                        canonical_model,
                        int(args.seed),
                        identifier,
                        attack_id,
                        control,
                        "attack_or_decode",
                        exc,
                    ))

        if image_index % flush_every == 0:
            flush_partial()

    artifact = current_artifact()
    if artifact["coverage"]["complete"] and not artifact["errors"]:
        try:
            threshold, selection, calibration_metrics = select_threshold(
                artifact["samples"],
                float(args.target_far),
            )
            holdout_metrics = _decision_metrics(artifact["samples"], threshold, "holdout")
            artifact.update({
                "status": "complete",
                "threshold": threshold,
                "threshold_selection": selection,
                "calibration_metrics": calibration_metrics,
                "metrics": holdout_metrics,
            })
        except Exception as exc:
            artifact["errors"].append({
                "sample_id": "threshold-selection",
                "image_id": "",
                "attack_id": "",
                "control": "",
                "stage": "threshold_selection",
                "error_type": type(exc).__name__,
            })
    _assert_no_absolute_paths(artifact)
    _atomic_write_json(output_path, artifact)
    return artifact


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    artifact = run_calibration(args)
    print(json.dumps({
        "status": artifact["status"],
        "model": artifact["model"],
        "threshold": artifact["threshold"],
        "coverage": artifact["coverage"],
        "metrics": artifact["metrics"],
        "output": logical_path(Path(args.output).expanduser().resolve()),
    }, ensure_ascii=False, indent=2, allow_nan=False))
    if artifact["status"] != "complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
