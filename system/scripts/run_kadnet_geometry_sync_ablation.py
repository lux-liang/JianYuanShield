#!/usr/bin/env python3
"""Run a non-claim KAD-Net direct-vs-geometry-synchronization ablation."""

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
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

# Required before Torch initializes deterministic CUDA matrix multiplication.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
from PIL import Image, ImageOps


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.attacks import ATTACKS, apply_attack  # noqa: E402
from system.evaluation.protocol import load_protocol  # noqa: E402
from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.evaluation.runtime import (  # noqa: E402
    ASSET_ROOT,
    DATA_ROOT,
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
)
from system.evaluation.synchronization import (  # noqa: E402
    DEFAULT_CANDIDATES,
    REQUIRED_FAR_NEGATIVE_CONTROLS,
    apply_synchronization_candidate,
    candidate_contract,
    candidate_contract_sha256,
    search_registered_message_alignment,
)


SCHEMA_VERSION = "kadnet-geometry-sync-ablation.v1"
ATTACK_IDS = ("clean", "crop_center_0.8", "rotate_5")
POSITIVE_CONTROL = "registered_roundtrip"
NEGATIVE_CONTROLS = REQUIRED_FAR_NEGATIVE_CONTROLS
CONTROLS = (POSITIVE_CONTROL, *NEGATIVE_CONTROLS)
DEFAULT_IMAGE_ROOT = DATA_ROOT / "lfw/processed/image/lfw_128"
DEFAULT_CHECKPOINT = WEIGHT_ROOT / "KAD-Net/ST/128/models/EC_100.pth"
DEFAULT_REPORT_DIR = REPORT_ROOT / "kadnet_geometry_sync_ablation"
DEFAULT_ASSET_DIR = ASSET_ROOT / "kadnet_geometry_sync_ablation"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
LFW_IMAGE_NAME = re.compile(r"^(?P<identity>.+)_\d{4}$")
WILSON_Z_95 = 1.959963984540054
RESULT_FIELDS = [
    "sample_id",
    "image_id",
    "source_path",
    "identity_sha256",
    "split",
    "attack_type",
    "attack_config_sha256",
    "control",
    "label",
    "source_record_image_id",
    "source_record_identity_sha256",
    "registered_message_bits",
    "registered_message_sha256",
    "embedded_message_bits",
    "embedded_message_sha256",
    "direct_decoded_bits",
    "direct_decoded_message_sha256",
    "direct_bit_errors",
    "direct_bit_accuracy",
    "sync_selected_candidate",
    "sync_decoded_bits",
    "sync_decoded_message_sha256",
    "sync_bit_errors",
    "sync_bit_accuracy",
    "sync_candidate_scores_json",
    "search_contract_sha256",
    "error",
]
SCORE_FIELDS = {
    "direct": "direct_bit_accuracy",
    "sync": "sync_bit_accuracy",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    protocol = load_protocol()
    parser = argparse.ArgumentParser(
        description=(
            "Run the independent KAD-Net geometry synchronization ablation; "
            "this does not modify the canonical benchmark."
        ),
    )
    parser.add_argument("--num-images", type=int, default=256)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=int(protocol["seed"]))
    parser.add_argument("--target-far", type=float, default=0.01)
    parser.add_argument("--artifact-limit", type=int, default=8)
    parser.add_argument("--flush-every", type=int, default=16)
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
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_write_csv(
    path: Path,
    rows: Iterable[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=RESULT_FIELDS,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


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


def image_id(path: Path, image_root: Path) -> str:
    identifier = path.expanduser().resolve().relative_to(
        image_root.expanduser().resolve()
    ).as_posix()
    if not identifier or identifier.startswith("../") or Path(identifier).is_absolute():
        raise ValueError("image identifier must be dataset-relative")
    return identifier


def identity_label(identifier: str) -> str:
    parts = PurePosixPath(identifier).parts
    stem = PurePosixPath(identifier).stem
    matched = LFW_IMAGE_NAME.fullmatch(stem)
    if matched:
        return matched.group("identity")
    if len(parts) > 1 and parts[-2].lower() not in {
        "train",
        "test",
        "validation",
        "val",
        "unknown",
    }:
        return parts[-2]
    return stem


def identity_sha256(identifier: str) -> str:
    label = identity_label(identifier)
    return hashlib.sha256(
        f"kadnet-sync.identity.v1\0{label}".encode("utf-8")
    ).hexdigest()


def select_images(image_root: Path, num_images: int, seed: int) -> list[Path]:
    root = image_root.expanduser().resolve()
    if num_images < 4:
        raise ValueError("num-images must be at least four")
    if not root.is_dir():
        raise FileNotFoundError(f"image root not found: {logical_path(root)}")
    images = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if len(images) < num_images:
        raise RuntimeError(
            f"requested {num_images} images but dataset contains {len(images)}"
        )
    images.sort(key=lambda path: (
        hashlib.sha256(
            (
                "kadnet-sync.image-selection.v1\0"
                f"{seed}\0{image_id(path, root)}"
            ).encode("utf-8")
        ).hexdigest(),
        image_id(path, root),
    ))
    return images[:num_images]


def deterministic_identity_splits(
    identifiers: Sequence[str],
    seed: int,
) -> dict[str, str]:
    groups: dict[str, list[str]] = defaultdict(list)
    for identifier in identifiers:
        groups[identity_sha256(identifier)].append(identifier)
    if len(groups) < 4:
        raise ValueError(
            "at least four identities are required for isolated calibration/holdout controls"
        )
    ranked = sorted(groups, key=lambda identity: (
        hashlib.sha256(
            f"kadnet-sync.identity-split.v1\0{seed}\0{identity}".encode("utf-8")
        ).hexdigest(),
        identity,
    ))
    counts = {"calibration": 0, "holdout": 0}
    identity_counts = {"calibration": 0, "holdout": 0}
    assignments: dict[str, str] = {}
    seeded_splits = ("calibration", "holdout", "calibration", "holdout")
    for index, identity in enumerate(ranked):
        if index < len(seeded_splits):
            split = seeded_splits[index]
        else:
            split = (
                "calibration"
                if counts["calibration"] <= counts["holdout"]
                else "holdout"
            )
        for identifier in groups[identity]:
            assignments[identifier] = split
        counts[split] += len(groups[identity])
        identity_counts[split] += 1
    if min(identity_counts.values()) < 2:
        raise RuntimeError("each split must contain at least two identities")
    calibration_identities = {
        identity_sha256(identifier)
        for identifier, split in assignments.items()
        if split == "calibration"
    }
    holdout_identities = {
        identity_sha256(identifier)
        for identifier, split in assignments.items()
        if split == "holdout"
    }
    if calibration_identities & holdout_identities:
        raise RuntimeError("identity leakage detected between calibration and holdout")
    return assignments


def cross_record_sources(
    identifiers: Sequence[str],
    assignments: dict[str, str],
    seed: int,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for split in ("calibration", "holdout"):
        members = sorted(
            (identifier for identifier in identifiers if assignments[identifier] == split),
            key=lambda identifier: (
                hashlib.sha256(
                    f"kadnet-sync.cross-source.v1\0{seed}\0{identifier}".encode("utf-8")
                ).hexdigest(),
                identifier,
            ),
        )
        for target in members:
            eligible = [
                source
                for source in members
                if identity_sha256(source) != identity_sha256(target)
            ]
            if not eligible:
                raise RuntimeError(
                    f"split {split} lacks a cross-identity negative source"
                )
            source = min(eligible, key=lambda candidate: (
                hashlib.sha256(
                    (
                        "kadnet-sync.cross-pair.v1\0"
                        f"{seed}\0{target}\0{candidate}"
                    ).encode("utf-8")
                ).hexdigest(),
                candidate,
            ))
            mapping[target] = source
    return mapping


def derive_message(
    seed: int,
    identifier: str,
    length: int,
    purpose: str,
) -> np.ndarray:
    if length <= 0:
        raise ValueError("message length must be positive")
    payload = f"kadnet-sync.message.v1\0{purpose}\0{seed}\0{identifier}".encode(
        "utf-8"
    )
    packed = hashlib.shake_256(payload).digest((length + 7) // 8)
    return np.unpackbits(
        np.frombuffer(packed, dtype=np.uint8),
        bitorder="big",
    )[:length].astype(np.uint8)


def wrong_message(
    seed: int,
    identifier: str,
    registered: np.ndarray,
) -> np.ndarray:
    wrong = derive_message(seed, identifier, registered.size, "wrong")
    if np.array_equal(wrong, registered):
        wrong = wrong.copy()
        wrong[0] ^= np.uint8(1)
    return wrong


def bits_text(bits: np.ndarray) -> str:
    values = np.asarray(bits, dtype=np.uint8).reshape(-1)
    if not np.isin(values, (0, 1)).all():
        raise ValueError("message contains non-binary values")
    return "".join(str(int(bit)) for bit in values)


def bits_from_text(value: str, length: int) -> np.ndarray:
    if len(value) != length or any(character not in "01" for character in value):
        raise ValueError("binary message text violates length or alphabet contract")
    return np.fromiter((int(character) for character in value), dtype=np.uint8)


def message_sha256(bits: np.ndarray) -> str:
    values = np.asarray(bits, dtype=np.uint8).reshape(-1)
    return hashlib.sha256(values.tobytes()).hexdigest()


def _sample_id(seed: int, identifier: str, attack_id: str, control: str) -> str:
    payload = f"kadnet-sync.sample.v1\0{seed}\0{identifier}\0{attack_id}\0{control}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["image_id"], row["attack_type"], row["control"]


def _expected_source(
    identifier: str,
    control: str,
    cross_sources: dict[str, str],
) -> str:
    return cross_sources[identifier] if control == "cross_record_watermarked" else identifier


def _expected_embedded_message(
    identifier: str,
    control: str,
    registered: dict[str, np.ndarray],
    wrong: dict[str, np.ndarray],
    cross_sources: dict[str, str],
) -> np.ndarray | None:
    if control == "unwatermarked":
        return None
    if control == "wrong_message":
        return wrong[identifier]
    source = _expected_source(identifier, control, cross_sources)
    return registered[source]


def _base_row(
    *,
    seed: int,
    identifier: str,
    attack_id: str,
    control: str,
    assignments: dict[str, str],
    registered: dict[str, np.ndarray],
    wrong: dict[str, np.ndarray],
    cross_sources: dict[str, str],
) -> dict[str, str]:
    source = _expected_source(identifier, control, cross_sources)
    expected = registered[identifier]
    embedded = _expected_embedded_message(
        identifier,
        control,
        registered,
        wrong,
        cross_sources,
    )
    return {
        "sample_id": _sample_id(seed, identifier, attack_id, control),
        "image_id": identifier,
        "source_path": identifier,
        "identity_sha256": identity_sha256(identifier),
        "split": assignments[identifier],
        "attack_type": attack_id,
        "attack_config_sha256": ATTACKS[attack_id].config_hash,
        "control": control,
        "label": "positive" if control == POSITIVE_CONTROL else "negative",
        "source_record_image_id": source,
        "source_record_identity_sha256": identity_sha256(source),
        "registered_message_bits": bits_text(expected),
        "registered_message_sha256": message_sha256(expected),
        "embedded_message_bits": bits_text(embedded) if embedded is not None else "",
        "embedded_message_sha256": message_sha256(embedded) if embedded is not None else "",
        "direct_decoded_bits": "",
        "direct_decoded_message_sha256": "",
        "direct_bit_errors": "",
        "direct_bit_accuracy": "",
        "sync_selected_candidate": "",
        "sync_decoded_bits": "",
        "sync_decoded_message_sha256": "",
        "sync_bit_errors": "",
        "sync_bit_accuracy": "",
        "sync_candidate_scores_json": "",
        "search_contract_sha256": candidate_contract_sha256(),
        "error": "",
    }


def _decoded_bits(value: Any, message_length: int) -> np.ndarray:
    if hasattr(value, "bits"):
        value = value.bits
    bits = np.asarray(value).reshape(-1)
    if bits.shape != (message_length,) or not np.isin(bits, (0, 1)).all():
        raise ValueError("decoder output violates KAD-Net binary message contract")
    return bits.astype(np.uint8, copy=False)


def _score(bits: np.ndarray, expected: np.ndarray) -> tuple[int, float]:
    if bits.shape != expected.shape:
        raise ValueError("decoded and registered messages have different lengths")
    errors = int(np.count_nonzero(bits != expected))
    return errors, (expected.size - errors) / expected.size


def _metric_text(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("non-finite score is not auditable")
    return f"{value:.8f}"


def _candidate_scores_json(result: Any) -> str:
    payload = []
    for score in result.candidate_scores:
        decoded = np.asarray(score.decoded_bits, dtype=np.uint8)
        payload.append({
            "candidate_id": score.candidate_id,
            "decoded_bits": bits_text(decoded),
            "decoded_message_sha256": message_sha256(decoded),
            "bit_errors": int(score.bit_errors),
            "bit_accuracy": round(float(score.bit_accuracy), 8),
        })
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _scored_row(
    base: dict[str, str],
    direct: np.ndarray,
    sync_result: Any,
    expected: np.ndarray,
) -> dict[str, str]:
    direct_errors, direct_accuracy = _score(direct, expected)
    identity_score = next(
        score
        for score in sync_result.candidate_scores
        if score.candidate_id == "identity"
    )
    if tuple(int(bit) for bit in direct) != identity_score.decoded_bits:
        raise RuntimeError("direct decode diverged from synchronization identity candidate")
    synchronized = np.asarray(sync_result.selected_decoded_bits, dtype=np.uint8)
    sync_errors, sync_accuracy = _score(synchronized, expected)
    if sync_errors != sync_result.selected_bit_errors:
        raise RuntimeError("synchronization selected-score error count drift")
    if sync_accuracy + 1e-15 < direct_accuracy:
        raise RuntimeError("synchronization maximum scored below direct identity decode")
    row = dict(base)
    row.update({
        "direct_decoded_bits": bits_text(direct),
        "direct_decoded_message_sha256": message_sha256(direct),
        "direct_bit_errors": str(direct_errors),
        "direct_bit_accuracy": _metric_text(direct_accuracy),
        "sync_selected_candidate": sync_result.selected_candidate_id,
        "sync_decoded_bits": bits_text(synchronized),
        "sync_decoded_message_sha256": message_sha256(synchronized),
        "sync_bit_errors": str(sync_errors),
        "sync_bit_accuracy": _metric_text(sync_accuracy),
        "sync_candidate_scores_json": _candidate_scores_json(sync_result),
    })
    return row


def _error_row(base: dict[str, str], stage: str, error: BaseException) -> dict[str, str]:
    row = dict(base)
    row["error"] = f"{stage}:{type(error).__name__}"
    return row


def _ordered_rows(
    rows: dict[tuple[str, str, str], dict[str, str]],
    identifiers: Sequence[str],
) -> list[dict[str, str]]:
    return [
        rows[key]
        for identifier in identifiers
        for attack_id in ATTACK_IDS
        for control in CONTROLS
        if (key := (identifier, attack_id, control)) in rows
    ]


def _validate_scored_row(
    row: dict[str, str],
    expected: np.ndarray,
    message_length: int,
) -> None:
    direct = bits_from_text(row["direct_decoded_bits"], message_length)
    if row["direct_decoded_message_sha256"] != message_sha256(direct):
        raise ValueError("direct decoded-message hash mismatch")
    direct_errors, direct_accuracy = _score(direct, expected)
    if int(row["direct_bit_errors"]) != direct_errors:
        raise ValueError("direct bit-error count mismatch")
    reported_direct_accuracy = float(row["direct_bit_accuracy"])
    if (
        not math.isfinite(reported_direct_accuracy)
        or abs(reported_direct_accuracy - direct_accuracy) > 1e-7
    ):
        raise ValueError("direct bit-accuracy mismatch")

    synchronized = bits_from_text(row["sync_decoded_bits"], message_length)
    if row["sync_decoded_message_sha256"] != message_sha256(synchronized):
        raise ValueError("sync decoded-message hash mismatch")
    sync_errors, sync_accuracy = _score(synchronized, expected)
    if int(row["sync_bit_errors"]) != sync_errors:
        raise ValueError("sync bit-error count mismatch")
    reported_sync_accuracy = float(row["sync_bit_accuracy"])
    if (
        not math.isfinite(reported_sync_accuracy)
        or abs(reported_sync_accuracy - sync_accuracy) > 1e-7
    ):
        raise ValueError("sync bit-accuracy mismatch")

    try:
        candidate_scores = json.loads(row["sync_candidate_scores_json"])
    except json.JSONDecodeError as exc:
        raise ValueError("sync candidate score JSON is invalid") from exc
    candidate_ids = [candidate.id for candidate in DEFAULT_CANDIDATES]
    if not isinstance(candidate_scores, list) or [
        entry.get("candidate_id") for entry in candidate_scores
    ] != candidate_ids:
        raise ValueError("sync candidate score coverage mismatch")
    verified_scores: list[float] = []
    for entry in candidate_scores:
        if set(entry) != {
            "candidate_id",
            "decoded_bits",
            "decoded_message_sha256",
            "bit_errors",
            "bit_accuracy",
        }:
            raise ValueError("sync candidate score schema mismatch")
        decoded = bits_from_text(str(entry.get("decoded_bits", "")), message_length)
        if entry.get("decoded_message_sha256") != message_sha256(decoded):
            raise ValueError("sync candidate decoded-message hash mismatch")
        errors, accuracy = _score(decoded, expected)
        if entry.get("bit_errors") != errors:
            raise ValueError("sync candidate bit-error count mismatch")
        reported_accuracy = float(entry.get("bit_accuracy"))
        if (
            not math.isfinite(reported_accuracy)
            or abs(reported_accuracy - accuracy) > 1e-7
        ):
            raise ValueError("sync candidate bit-accuracy mismatch")
        verified_scores.append(accuracy)
    best_index = max(range(len(verified_scores)), key=verified_scores.__getitem__)
    if row["sync_selected_candidate"] != candidate_ids[best_index]:
        raise ValueError("sync selected-candidate tie-break mismatch")
    if row["sync_decoded_bits"] != candidate_scores[best_index]["decoded_bits"]:
        raise ValueError("sync selected decoded bits mismatch")
    identity_index = candidate_ids.index("identity")
    if row["direct_decoded_bits"] != candidate_scores[identity_index]["decoded_bits"]:
        raise ValueError("direct decode and sync identity candidate mismatch")
    if sync_accuracy + 1e-15 < direct_accuracy:
        raise ValueError("sync maximum is below direct identity score")


def load_result_rows(
    path: Path,
    *,
    expected_keys: set[tuple[str, str, str]],
    assignments: dict[str, str],
    registered: dict[str, np.ndarray],
    wrong: dict[str, np.ndarray],
    cross_sources: dict[str, str],
    seed: int,
    message_length: int,
) -> dict[tuple[str, str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RESULT_FIELDS:
            raise ValueError("geometry-sync results CSV schema mismatch")
        raw_rows = list(reader)
    _assert_no_absolute_paths(raw_rows, "results")
    indexed: dict[tuple[str, str, str], dict[str, str]] = {}
    result_fields = RESULT_FIELDS[
        RESULT_FIELDS.index("direct_decoded_bits"):
        RESULT_FIELDS.index("search_contract_sha256")
    ]
    for row in raw_rows:
        key = _row_key(row)
        if key in indexed:
            raise ValueError(f"duplicate geometry-sync result key: {key}")
        if key not in expected_keys:
            raise ValueError(f"unexpected geometry-sync result key: {key}")
        identifier, attack_id, control = key
        base = _base_row(
            seed=seed,
            identifier=identifier,
            attack_id=attack_id,
            control=control,
            assignments=assignments,
            registered=registered,
            wrong=wrong,
            cross_sources=cross_sources,
        )
        for field in RESULT_FIELDS[:RESULT_FIELDS.index("direct_decoded_bits")]:
            if row[field] != base[field]:
                raise ValueError(f"geometry-sync row contract mismatch: {key}:{field}")
        if row["search_contract_sha256"] != candidate_contract_sha256():
            raise ValueError(f"geometry-sync search contract mismatch: {key}")
        if row["error"]:
            if any(row[field] for field in result_fields):
                raise ValueError(f"geometry-sync error row contains scores: {key}")
        else:
            _validate_scored_row(row, registered[identifier], message_length)
        indexed[key] = row
    return indexed


def wilson_interval(successes: int, total: int) -> dict[str, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("Wilson interval requires 0 <= successes <= total")
    proportion = successes / total
    z2 = WILSON_Z_95 * WILSON_Z_95
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    margin = (
        WILSON_Z_95
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z2 / (4.0 * total * total)
        )
        / denominator
    )
    return {
        "confidence_level": 0.95,
        "lower": 0.0 if successes == 0 else max(0.0, center - margin),
        "upper": 1.0 if successes == total else min(1.0, center + margin),
    }


def decision_metrics(
    rows: Sequence[dict[str, str]],
    score_field: str,
    threshold: float,
    split: str,
    attack_id: str | None = None,
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["split"] == split
        and not row["error"]
        and (attack_id is None or row["attack_type"] == attack_id)
    ]
    positives = [row for row in selected if row["label"] == "positive"]
    negatives = [row for row in selected if row["label"] == "negative"]
    if not positives or not negatives:
        raise ValueError(f"{split} lacks positive or negative samples")
    missing_controls = [
        control
        for control in NEGATIVE_CONTROLS
        if not any(row["control"] == control for row in negatives)
    ]
    if missing_controls:
        raise ValueError(
            f"{split} lacks FAR negative controls: {', '.join(missing_controls)}"
        )
    true_accepts = sum(float(row[score_field]) >= threshold for row in positives)
    false_rejects = len(positives) - true_accepts
    false_accepts = sum(float(row[score_field]) >= threshold for row in negatives)
    rates = {
        "TAR": true_accepts / len(positives),
        "FRR": false_rejects / len(positives),
        "FAR": false_accepts / len(negatives),
    }
    control_metrics: dict[str, Any] = {}
    for control in NEGATIVE_CONTROLS:
        control_rows = [row for row in negatives if row["control"] == control]
        control_false_accepts = sum(
            float(row[score_field]) >= threshold for row in control_rows
        )
        control_metrics[control] = {
            "samples": len(control_rows),
            "false_accepts": control_false_accepts,
            "FAR": control_false_accepts / len(control_rows),
            "FAR_wilson_95": wilson_interval(
                control_false_accepts,
                len(control_rows),
            ),
        }
    input_rows = [
        {
            "sample_id": row["sample_id"],
            "label": row["label"],
            "control": row["control"],
            "attack_type": row["attack_type"],
            "score": float(row[score_field]),
        }
        for row in selected
    ]
    input_rows.sort(key=lambda row: row["sample_id"])
    return {
        "split": split,
        "attack_type": attack_id or "all",
        "score_field": score_field,
        "threshold": threshold,
        "comparison_operator": ">=",
        "positive_samples": len(positives),
        "negative_samples": len(negatives),
        "unique_identities": len({row["identity_sha256"] for row in selected}),
        "true_accepts": true_accepts,
        "false_rejects": false_rejects,
        "false_accepts": false_accepts,
        "rates": rates,
        "wilson_95": {
            "TAR": wilson_interval(true_accepts, len(positives)),
            "FRR": wilson_interval(false_rejects, len(positives)),
            "FAR": wilson_interval(false_accepts, len(negatives)),
        },
        "negative_control_metrics": control_metrics,
        "input_sha256": canonical_sha256(input_rows),
    }


def select_threshold(
    rows: Sequence[dict[str, str]],
    score_field: str,
    target_far: float,
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    if not 0.0 <= target_far <= 1.0:
        raise ValueError("target-FAR must be between zero and one")
    calibration = [
        row for row in rows if row["split"] == "calibration" and not row["error"]
    ]
    if not calibration:
        raise ValueError("calibration split is empty")
    scores = {float(row[score_field]) for row in calibration}
    candidates = {0.0, 1.0}
    for score in scores:
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("calibration score outside [0,1]")
        candidates.add(score)
        above = math.nextafter(score, math.inf)
        if above <= 1.0:
            candidates.add(above)
    eligible: list[tuple[float, dict[str, Any]]] = []
    for threshold in sorted(candidates):
        metrics = decision_metrics(
            calibration,
            score_field,
            threshold,
            "calibration",
        )
        if metrics["rates"]["FAR"] <= target_far + 1e-15:
            eligible.append((threshold, metrics))
    if not eligible:
        raise RuntimeError("no calibration threshold satisfies target FAR")
    threshold, metrics = min(
        eligible,
        key=lambda item: (
            -float(item[1]["rates"]["TAR"]),
            float(item[1]["rates"]["FAR"]),
            float(item[0]),
        ),
    )
    selection_input = [
        {
            "sample_id": row["sample_id"],
            "label": row["label"],
            "control": row["control"],
            "attack_type": row["attack_type"],
            "score": float(row[score_field]),
        }
        for row in calibration
    ]
    selection_input.sort(key=lambda row: row["sample_id"])
    selection = {
        "split": "calibration",
        "holdout_used_for_selection": False,
        "objective": "maximize_TAR_subject_to_calibration_FAR_lte_target",
        "target_FAR": target_far,
        "candidate_generation": "zero_one_observed_scores_and_nextafter_above",
        "candidate_count": len(candidates),
        "eligible_candidate_count": len(eligible),
        "tie_breaker": "minimum_FAR_then_minimum_threshold",
        "selected_threshold": threshold,
        "calibration_input_sha256": canonical_sha256(selection_input),
        "required_negative_controls": list(NEGATIVE_CONTROLS),
    }
    return threshold, selection, metrics


def _coverage(
    rows: dict[tuple[str, str, str], dict[str, str]],
    expected_keys: set[tuple[str, str, str]],
) -> dict[str, Any]:
    missing = expected_keys - set(rows)
    unexpected = set(rows) - expected_keys
    errors = [row for row in rows.values() if row["error"]]
    counts = Counter(
        f"{row['split']}:{row['control']}" for row in rows.values()
    )
    return {
        "expected_rows": len(expected_keys),
        "actual_rows": len(rows),
        "missing_key_sha256": [canonical_sha256(key) for key in sorted(missing)],
        "unexpected_key_sha256": [
            canonical_sha256(key) for key in sorted(unexpected)
        ],
        "error_rows": len(errors),
        "error_sample_id_sha256": [
            hashlib.sha256(row["sample_id"].encode("utf-8")).hexdigest()
            for row in errors
        ],
        "rows_by_split_control": dict(sorted(counts.items())),
        "complete": not missing and not unexpected and not errors,
    }


def _dataset_manifest(
    image_root: Path,
    images: Sequence[Path],
    assignments: dict[str, str],
    cross_sources: dict[str, str],
    seed: int,
) -> dict[str, Any]:
    files = []
    for path in sorted(images, key=lambda path: image_id(path, image_root)):
        identifier = image_id(path, image_root)
        digest = sha256_file(path)
        if digest is None:
            raise FileNotFoundError(identifier)
        files.append({
            "image_id": identifier,
            "identity_sha256": identity_sha256(identifier),
            "split": assignments[identifier],
            "cross_record_source_image_id": cross_sources[identifier],
            "size_bytes": path.stat().st_size,
            "sha256": digest,
        })
    return {
        "schema_version": "kadnet-sync-dataset-manifest.v1",
        "image_root": logical_path(image_root),
        "selection": "lowest_sha256(kadnet-sync.image-selection.v1,seed,image_id)",
        "split_policy": "identity_grouped_seeded_balance_with_two_identities_per_split",
        "cross_record_policy": "same_split_different_identity_seeded_pair",
        "seed": seed,
        "sample_count": len(files),
        "files_digest_sha256": canonical_sha256(files),
        "files": files,
    }


def _ensure_json_contract(
    path: Path,
    expected: dict[str, Any],
    state_exists: bool,
    role: str,
) -> None:
    _assert_no_absolute_paths(expected, role)
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        _assert_no_absolute_paths(current, role)
        if current != expected:
            raise RuntimeError(f"existing {role} does not match requested run")
        return
    if state_exists:
        raise RuntimeError(f"existing result rows have no {role}; refusing to mix runs")
    _atomic_write_json(path, expected)


def _configure_determinism(seed: int, device_name: str) -> None:
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in {":4096:8", ":16:8"}:
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 or :16:8")
    os.environ["JYS_INFER_DEVICE"] = device_name
    import torch

    device = torch.device(device_name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA device requested but CUDA is unavailable")
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)


def build_adapter(checkpoint: Path) -> Any:
    from system.scripts.run_kadnet_lfw_benchmark import build_adapter as build

    return build(checkpoint)


def _validate_image(value: Any) -> np.ndarray:
    image = np.asarray(value)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("adapter image must be HxWx3 uint8 RGB")
    return np.ascontiguousarray(image)


def _load_image(path: Path) -> np.ndarray:
    with Image.open(path) as opened:
        return np.asarray(
            ImageOps.exif_transpose(opened).convert("RGB"),
            dtype=np.uint8,
        ).copy()


def _save_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(_validate_image(image)).save(path)


def _attack_contract(protocol: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    registered = {str(entry["id"]): entry for entry in protocol["attacks"]}
    missing = [attack_id for attack_id in ATTACK_IDS if attack_id not in registered]
    if missing:
        raise ValueError("fixed ablation attacks missing from protocol")
    contract = []
    for attack_id in ATTACK_IDS:
        shared = ATTACKS[attack_id]
        protocol_attack = registered[attack_id]
        if protocol_attack.get("type") != shared.type:
            raise ValueError(f"attack type drift for {attack_id}")
        for key, value in shared.parameters.items():
            if protocol_attack.get("parameters", {}).get(key) != value:
                raise ValueError(f"attack parameter drift for {attack_id}.{key}")
        contract.append({
            "protocol": protocol_attack,
            "shared_config_sha256": shared.config_hash,
        })
    return contract, canonical_sha256(contract)


def run_ablation(args: argparse.Namespace) -> dict[str, Any]:
    if int(args.num_images) < 4:
        raise ValueError("num-images must be at least four")
    if not 0.0 <= float(args.target_far) <= 1.0:
        raise ValueError("target-FAR must be between zero and one")
    if int(args.artifact_limit) < 0:
        raise ValueError("artifact-limit must be non-negative")
    if int(args.flush_every) <= 0:
        raise ValueError("flush-every must be positive")
    _configure_determinism(int(args.seed), str(args.device))

    protocol = load_protocol()
    attack_contract, attack_contract_hash = _attack_contract(protocol)
    protocol_path = Path(str(protocol["_source_path"])).resolve()
    protocol_hash = sha256_file(protocol_path)
    if protocol_hash is None:
        raise RuntimeError("protocol hash unavailable")
    image_root = Path(args.image_root).expanduser().resolve()
    images = select_images(image_root, int(args.num_images), int(args.seed))
    identifiers = [image_id(path, image_root) for path in images]
    assignments = deterministic_identity_splits(identifiers, int(args.seed))
    cross_sources = cross_record_sources(identifiers, assignments, int(args.seed))

    checkpoint = Path(args.checkpoint).expanduser().resolve()
    checkpoint_hash = sha256_file(checkpoint)
    if checkpoint_hash is None:
        raise FileNotFoundError(f"checkpoint not found: {logical_path(checkpoint)}")
    adapter = build_adapter(checkpoint)
    if not adapter.available or not adapter.checkpoint:
        raise RuntimeError(f"KAD-Net adapter unavailable: {adapter.blocker}")
    if Path(str(adapter.checkpoint)).expanduser().resolve() != checkpoint:
        raise RuntimeError("KAD-Net adapter did not bind the requested checkpoint")
    message_length = int(adapter.message_length)
    if message_length <= 0:
        raise ValueError("KAD-Net adapter message length must be positive")

    registered = {
        identifier: derive_message(
            int(args.seed),
            identifier,
            message_length,
            "registered",
        )
        for identifier in identifiers
    }
    wrong = {
        identifier: wrong_message(int(args.seed), identifier, registered[identifier])
        for identifier in identifiers
    }
    report_dir = Path(args.report_dir).expanduser().resolve()
    asset_dir = Path(args.asset_dir).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    results_path = report_dir / "results.csv"
    manifest_path = report_dir / "dataset_manifest.json"
    config_path = report_dir / "run_config.json"
    summary_path = report_dir / "summary.json"
    progress_path = report_dir / "progress.json"
    result_state_exists = results_path.exists()

    manifest = _dataset_manifest(
        image_root,
        images,
        assignments,
        cross_sources,
        int(args.seed),
    )
    _ensure_json_contract(
        manifest_path,
        manifest,
        result_state_exists,
        "dataset_manifest.json",
    )
    manifest_hash = sha256_file(manifest_path)
    if manifest_hash is None:
        raise RuntimeError("dataset manifest hash unavailable")
    search_contract = candidate_contract()
    search_contract_hash = candidate_contract_sha256()
    run_config = {
        "schema_version": "kadnet-geometry-sync-ablation-config.v1",
        "mode": "experimental_non_claim_ablation",
        "model": "KAD-Net",
        "checkpoint": logical_path(checkpoint),
        "checkpoint_sha256": checkpoint_hash,
        "protocol_version": protocol["schema_version"],
        "protocol_path": logical_path(protocol_path),
        "protocol_sha256": protocol_hash,
        "attack_ids": list(ATTACK_IDS),
        "attack_contract": attack_contract,
        "attack_contract_sha256": attack_contract_hash,
        "controls": list(CONTROLS),
        "negative_controls": list(NEGATIVE_CONTROLS),
        "seed": int(args.seed),
        "target_FAR": float(args.target_far),
        "message_length": message_length,
        "message_derivation": "SHAKE256(kadnet-sync.message.v1,purpose,seed,image_id)",
        "sample_count": len(images),
        "image_root": logical_path(image_root),
        "dataset_manifest_path": logical_path(manifest_path),
        "dataset_manifest_sha256": manifest_hash,
        "identity_split_policy": manifest["split_policy"],
        "search_contract": search_contract,
        "search_contract_sha256": search_contract_hash,
        "threshold_selection_split": "calibration_only",
        "holdout_used_for_threshold_selection": False,
        "device": str(args.device),
        "asset_dir": logical_path(asset_dir),
        "artifact_limit": int(args.artifact_limit),
        "result_schema": RESULT_FIELDS,
        "determinism": {
            "torch_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cudnn_deterministic": True,
            "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        },
    }
    _ensure_json_contract(
        config_path,
        run_config,
        result_state_exists,
        "run_config.json",
    )

    expected_keys = {
        (identifier, attack_id, control)
        for identifier in identifiers
        for attack_id in ATTACK_IDS
        for control in CONTROLS
    }
    rows = load_result_rows(
        results_path,
        expected_keys=expected_keys,
        assignments=assignments,
        registered=registered,
        wrong=wrong,
        cross_sources=cross_sources,
        seed=int(args.seed),
        message_length=message_length,
    )

    originals: dict[str, np.ndarray] = {}
    load_errors: dict[str, BaseException] = {}
    for path, identifier in zip(images, identifiers):
        try:
            originals[identifier] = _validate_image(_load_image(path))
        except Exception as exc:
            load_errors[identifier] = exc
    encoded_registered: dict[str, np.ndarray] = {}
    encoded_wrong: dict[str, np.ndarray] = {}
    encode_errors: dict[tuple[str, str], BaseException] = {}
    for identifier in identifiers:
        if identifier in load_errors:
            encode_errors[(identifier, POSITIVE_CONTROL)] = load_errors[identifier]
            encode_errors[(identifier, "wrong_message")] = load_errors[identifier]
            continue
        for control, message, destination in (
            (POSITIVE_CONTROL, registered[identifier], encoded_registered),
            ("wrong_message", wrong[identifier], encoded_wrong),
        ):
            try:
                encoded = adapter.encode(originals[identifier], message)
                image = _validate_image(encoded.image)
                if Path(str(adapter.checkpoint)).expanduser().resolve() != checkpoint:
                    raise RuntimeError("adapter checkpoint changed during ablation")
                metadata_checkpoint = encoded.metadata.get("checkpoint")
                if metadata_checkpoint and (
                    Path(str(metadata_checkpoint)).expanduser().resolve() != checkpoint
                ):
                    raise RuntimeError("encoded artifact reports another checkpoint")
                destination[identifier] = image
            except Exception as exc:
                encode_errors[(identifier, control)] = exc

    started = time.time()

    def flush(processed_images: int, status: str = "running") -> None:
        _atomic_write_csv(results_path, _ordered_rows(rows, identifiers))
        elapsed = max(0.0, time.time() - started)
        remaining = len(images) - processed_images
        eta = elapsed / processed_images * remaining if processed_images else None
        _atomic_write_json(progress_path, {
            "schema_version": "kadnet-sync-progress.v1",
            "status": status,
            "processed_images": processed_images,
            "total_images": len(images),
            "result_rows": len(rows),
            "expected_result_rows": len(expected_keys),
            "error_rows": sum(bool(row["error"]) for row in rows.values()),
            "elapsed_s": round(elapsed, 3),
            "eta_s": round(eta, 3) if eta is not None else None,
            "updated_at": int(time.time()),
        })

    for image_index, identifier in enumerate(identifiers):
        for attack_id in ATTACK_IDS:
            for control in CONTROLS:
                key = (identifier, attack_id, control)
                if key in rows and not rows[key]["error"]:
                    continue
                base = _base_row(
                    seed=int(args.seed),
                    identifier=identifier,
                    attack_id=attack_id,
                    control=control,
                    assignments=assignments,
                    registered=registered,
                    wrong=wrong,
                    cross_sources=cross_sources,
                )
                stage = "source"
                try:
                    source_identifier = base["source_record_image_id"]
                    if control == "unwatermarked":
                        if source_identifier in load_errors:
                            raise load_errors[source_identifier]
                        source_image = originals[source_identifier]
                    elif control == "wrong_message":
                        if (source_identifier, control) in encode_errors:
                            raise encode_errors[(source_identifier, control)]
                        source_image = encoded_wrong[source_identifier]
                    else:
                        if (source_identifier, POSITIVE_CONTROL) in encode_errors:
                            raise encode_errors[(source_identifier, POSITIVE_CONTROL)]
                        source_image = encoded_registered[source_identifier]

                    stage = "attack"
                    attacked, attack_metadata = apply_attack(
                        source_image,
                        attack_id,
                        image_id=identifier,
                        global_seed=int(args.seed),
                    )
                    if attack_metadata.get("config_hash") != ATTACKS[attack_id].config_hash:
                        raise RuntimeError("shared attack metadata hash mismatch")
                    stage = "direct_decode"
                    direct = _decoded_bits(adapter.decode(attacked), message_length)
                    stage = "synchronization_search"
                    sync_result = search_registered_message_alignment(
                        attacked,
                        registered_message=registered[identifier],
                        decode_bits=adapter.decode,
                    )
                    if sync_result.candidate_contract_sha256 != search_contract_hash:
                        raise RuntimeError("synchronization search contract drift")
                    if sync_result.formal_claim_eligible:
                        raise RuntimeError("prototype synchronization became claim-eligible")
                    rows[key] = _scored_row(
                        base,
                        direct,
                        sync_result,
                        registered[identifier],
                    )

                    if (
                        control == POSITIVE_CONTROL
                        and image_index < int(args.artifact_limit)
                    ):
                        sample_dir = asset_dir / f"sample_{image_index + 1:05d}"
                        if attack_id == "clean":
                            _save_image(sample_dir / "original.png", originals[identifier])
                            _save_image(
                                sample_dir / "watermarked.png",
                                encoded_registered[identifier],
                            )
                        _save_image(sample_dir / f"{attack_id}_attacked.png", attacked)
                        selected_candidate = next(
                            candidate
                            for candidate in DEFAULT_CANDIDATES
                            if candidate.id == sync_result.selected_candidate_id
                        )
                        aligned = apply_synchronization_candidate(
                            attacked,
                            selected_candidate,
                        )
                        _save_image(sample_dir / f"{attack_id}_selected.png", aligned)
                except Exception as exc:
                    rows[key] = _error_row(base, stage, exc)
        if (image_index + 1) % int(args.flush_every) == 0:
            flush(image_index + 1)

    flush(len(images), "auditing")
    rows = load_result_rows(
        results_path,
        expected_keys=expected_keys,
        assignments=assignments,
        registered=registered,
        wrong=wrong,
        cross_sources=cross_sources,
        seed=int(args.seed),
        message_length=message_length,
    )
    coverage = _coverage(rows, expected_keys)
    ordered = _ordered_rows(rows, identifiers)
    analysis: dict[str, Any] = {}
    analysis_error: dict[str, str] | None = None
    if coverage["complete"]:
        try:
            for method, score_field in SCORE_FIELDS.items():
                threshold, selection, calibration_metrics = select_threshold(
                    ordered,
                    score_field,
                    float(args.target_far),
                )
                holdout_metrics = decision_metrics(
                    ordered,
                    score_field,
                    threshold,
                    "holdout",
                )
                analysis[method] = {
                    "threshold": threshold,
                    "threshold_selection": selection,
                    "calibration_metrics": calibration_metrics,
                    "holdout_metrics": holdout_metrics,
                    "holdout_by_attack": {
                        attack_id: decision_metrics(
                            ordered,
                            score_field,
                            threshold,
                            "holdout",
                            attack_id,
                        )
                        for attack_id in ATTACK_IDS
                    },
                }
        except Exception as exc:
            analysis_error = {
                "stage": "threshold_or_holdout_analysis",
                "error_type": type(exc).__name__,
            }

    complete = coverage["complete"] and analysis_error is None and set(analysis) == set(
        SCORE_FIELDS
    )
    results_hash = sha256_file(results_path)
    config_hash = sha256_file(config_path)
    calibration_identities = {
        identity_sha256(identifier)
        for identifier in identifiers
        if assignments[identifier] == "calibration"
    }
    holdout_identities = {
        identity_sha256(identifier)
        for identifier in identifiers
        if assignments[identifier] == "holdout"
    }
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete" if complete else "incomplete",
        "mode": "experimental_non_claim_ablation",
        "formal_claim_eligible": False,
        "claim_valid": False,
        "model": "KAD-Net",
        "checkpoint": logical_path(checkpoint),
        "checkpoint_sha256": checkpoint_hash,
        "dataset_manifest_path": logical_path(manifest_path),
        "dataset_manifest_sha256": manifest_hash,
        "protocol_version": protocol["schema_version"],
        "protocol_path": logical_path(protocol_path),
        "protocol_sha256": protocol_hash,
        "attack_ids": list(ATTACK_IDS),
        "attack_contract_sha256": attack_contract_hash,
        "search_contract_sha256": search_contract_hash,
        "results_csv_path": logical_path(results_path),
        "results_csv_sha256": results_hash,
        "run_config_path": logical_path(config_path),
        "run_config_sha256": config_hash,
        "sample_count": len(images),
        "expected_result_rows": len(expected_keys),
        "message_length": message_length,
        "seed": int(args.seed),
        "target_FAR": float(args.target_far),
        "identity_split": {
            "calibration_identities": len(calibration_identities),
            "holdout_identities": len(holdout_identities),
            "identity_overlap": len(
                calibration_identities & holdout_identities
            ),
        },
        "coverage": coverage,
        "analysis": analysis,
        "analysis_error": analysis_error,
    }
    if complete:
        direct_holdout = analysis["direct"]["holdout_metrics"]["rates"]
        sync_holdout = analysis["sync"]["holdout_metrics"]["rates"]
        summary["holdout_ablation_delta_sync_minus_direct"] = {
            metric: sync_holdout[metric] - direct_holdout[metric]
            for metric in ("TAR", "FAR", "FRR")
        }
    if any(
        value is None
        for value in (
            results_hash,
            config_hash,
            manifest_hash,
            protocol_hash,
            checkpoint_hash,
        )
    ):
        summary["status"] = "incomplete"
        summary["analysis_error"] = {
            "stage": "evidence_hashing",
            "error_type": "MissingEvidenceHash",
        }
        complete = False
    _assert_no_absolute_paths(summary, "summary")
    _atomic_write_json(summary_path, summary)
    _atomic_write_json(progress_path, {
        "schema_version": "kadnet-sync-progress.v1",
        "status": "complete" if complete else "incomplete",
        "processed_images": len(images),
        "total_images": len(images),
        "result_rows": len(rows),
        "expected_result_rows": len(expected_keys),
        "error_rows": coverage["error_rows"],
        "updated_at": int(time.time()),
    })
    return summary


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    summary = run_ablation(args)
    print(json.dumps({
        "status": summary["status"],
        "mode": summary["mode"],
        "sample_count": summary["sample_count"],
        "coverage": summary["coverage"],
        "analysis": summary["analysis"],
        "output": logical_path(Path(args.report_dir).expanduser().resolve()),
    }, indent=2, ensure_ascii=False, allow_nan=False))
    if summary["status"] != "complete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
