from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
from statistics import NormalDist
from typing import Any, Mapping, Sequence

import numpy as np

from .config import REPORTS, ROOT
from .mea_evidence import validate_mea_matrix_evidence
from system.evaluation.runtime import resolve_logical_path


POLICY_CONFIG_PATH = ROOT / "configs" / "collaboration_policy.v2.json"
POLICY_SCHEMA = "collaboration-policy.v2"
RESPONSE_SCHEMA = "collaboration-recommendation.v2"
SUMMARY_SCHEMA = "mea-matrix-summary.v1"
MODEL_NAMES = ("LIDMark", "KAD-Net", "SepMark", "WaveGuard")
POLICY_ID = "mea-identity-cluster-deployment-s20260603"
MODEL_SEMANTICS = {
    "LIDMark": {
        "message_length": 16,
        "primary_decoder": "FHD_id_head",
        "success_threshold": 0.9,
    },
    "KAD-Net": {
        "message_length": 30,
        "primary_decoder": "ST_Decoder_C",
        "success_threshold": 0.9,
    },
    "SepMark": {
        "message_length": 128,
        "primary_decoder": "decoder_C",
        "success_threshold": 0.9,
    },
    "WaveGuard": {
        "message_length": 30,
        "primary_decoder": "tracer",
        "success_threshold": 0.9,
    },
}
ARTIFACT_HASH_FIELDS = {
    "dataset_manifest": "dataset_manifest_sha256",
    "raw_results": "raw_results_sha256",
    "run_config": "run_config_sha256",
}
_POLICY_FIELDS = {
    "schema_version",
    "policy_id",
    "model_order",
    "model_semantics",
    "evidence",
    "uncertainty",
    "scoring",
}
_EVIDENCE_FIELDS = {
    "summary_path",
    "summary_sha256",
    "dataset_manifest_sha256",
    "raw_results_sha256",
    "run_config_sha256",
    "progress_sha256",
    "protocol_sha256",
    "images_per_cell",
    "expected_cells",
    "expected_rows",
}
_SCORING_FIELDS = {
    "fidelity_psnr_floor_db",
    "fidelity_psnr_ceiling_db",
    "minimum_allowed_worst_case_protocol_normalized_margin",
    "minimum_source_protocol_success_rate_lcb",
    "minimum_post_attack_psnr_lcb_db",
    "minimum_post_attack_ssim_lcb",
    "default_risk_aversion",
    "default_fidelity_weight",
    "default_minimum_worst_case_protocol_normalized_margin",
}
_MODEL_SEMANTIC_FIELDS = {"message_length", "primary_decoder", "success_threshold"}
_UNCERTAINTY_FIELDS = {
    "method",
    "cluster_key",
    "estimand",
    "normalized_margin_transform",
    "rng",
    "seed",
    "resamples",
    "quantile_method",
    "confidence_level",
    "multiplicity_adjustment",
    "family_metrics",
    "family_size",
    "expected_image_count",
    "expected_identity_count",
    "expected_repeated_identity_count",
    "expected_images_in_repeated_identities",
    "expected_max_cluster_size",
}
CLUSTER_METRICS = (
    "source_protocol_normalized_margin",
    "source_protocol_success",
    "attacker_protocol_normalized_margin",
    "attacker_protocol_success",
    "second_vs_original_psnr",
    "second_vs_original_ssim",
)
_LFW_IDENTITY_RE = re.compile(r"^(?P<identity>.+)_(?P<index>[0-9]{4})$")
_MAX_POLICY_BYTES = 1024 * 1024
_MAX_SUMMARY_BYTES = 16 * 1024 * 1024
_MAX_PROGRESS_BYTES = 8 * 1024 * 1024
_MAX_DATASET_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_RAW_RESULTS_BYTES = 128 * 1024 * 1024


class CollaborationPolicyError(RuntimeError):
    """Raised when the evidence-bound collaboration policy cannot be trusted."""


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _snapshot_regular_file(
    path: Path,
    *,
    label: str,
    capture_bytes: bool = False,
    maximum_bytes: int | None = None,
) -> dict[str, Any]:
    """Read/hash one regular file through a single descriptor and bind its identity."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CollaborationPolicyError(f"{label} is not a regular file") from exc
    digest = hashlib.sha256()
    chunks: list[bytes] | None = [] if capture_bytes else None
    total_bytes = 0
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CollaborationPolicyError(f"{label} is not a regular file")
        if maximum_bytes is not None and before.st_size > maximum_bytes:
            raise CollaborationPolicyError(f"{label} exceeds its size limit")
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            total_bytes += len(block)
            if maximum_bytes is not None and total_bytes > maximum_bytes:
                raise CollaborationPolicyError(f"{label} exceeds its size limit")
            digest.update(block)
            if chunks is not None:
                chunks.append(block)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise CollaborationPolicyError(f"{label} could not be read") from exc
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after):
        raise CollaborationPolicyError(f"{label} changed while it was read")
    try:
        current = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise CollaborationPolicyError(f"{label} disappeared after it was read") from exc
    if not stat.S_ISREG(current.st_mode) or _identity(current) != _identity(after):
        raise CollaborationPolicyError(f"{label} changed while it was read")
    return {
        "path": path,
        "identity": _identity(after),
        "sha256": digest.hexdigest(),
        "size_bytes": after.st_size,
        "bytes": b"".join(chunks) if chunks is not None else None,
    }


def _json_from_snapshot(snapshot: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    raw = snapshot.get("bytes")
    if not isinstance(raw, bytes):
        raise CollaborationPolicyError(f"{label} was not captured")
    try:
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_nonfinite)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CollaborationPolicyError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CollaborationPolicyError(f"{label} must be a JSON object")
    return payload


def _read_json_snapshot(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _snapshot_regular_file(
        path,
        label=label,
        capture_bytes=True,
        maximum_bytes=maximum_bytes,
    )
    return _json_from_snapshot(snapshot, label=label), snapshot


def _assert_snapshot_unchanged(snapshot: Mapping[str, Any], *, label: str) -> None:
    current = _snapshot_regular_file(Path(snapshot["path"]), label=label)
    if (
        current["identity"] != snapshot["identity"]
        or current["sha256"] != snapshot["sha256"]
    ):
        raise CollaborationPolicyError(f"{label} changed during policy evaluation")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CollaborationPolicyError(message)


def _number(
    value: Any,
    *,
    label: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CollaborationPolicyError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CollaborationPolicyError(f"{label} must be a finite number")
    if minimum is not None and result < minimum:
        raise CollaborationPolicyError(f"{label} is below its minimum")
    if maximum is not None and result > maximum:
        raise CollaborationPolicyError(f"{label} exceeds its maximum")
    return result


def _exact_positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CollaborationPolicyError(f"{label} must be a positive integer")
    return value


def _validate_policy_config(config: Mapping[str, Any]) -> None:
    _require(set(config) == _POLICY_FIELDS, "policy field membership mismatch")
    _require(config.get("schema_version") == POLICY_SCHEMA, "policy schema mismatch")
    _require(config.get("policy_id") == POLICY_ID, "policy_id mismatch")
    model_order = config.get("model_order")
    _require(
        isinstance(model_order, list)
        and tuple(model_order) == MODEL_NAMES,
        "policy model_order mismatch",
    )
    model_semantics = config.get("model_semantics")
    evidence = config.get("evidence")
    uncertainty = config.get("uncertainty")
    scoring = config.get("scoring")
    _require(
        isinstance(model_semantics, dict)
        and model_semantics == MODEL_SEMANTICS,
        "policy model_semantics mismatch",
    )
    _require(isinstance(evidence, dict), "policy evidence configuration is missing")
    _require(
        isinstance(uncertainty, dict),
        "policy uncertainty configuration is missing",
    )
    _require(isinstance(scoring, dict), "policy scoring configuration is missing")
    _require(set(evidence) == _EVIDENCE_FIELDS, "policy evidence field membership mismatch")
    _require(
        set(uncertainty) == _UNCERTAINTY_FIELDS,
        "policy uncertainty field membership mismatch",
    )
    _require(set(scoring) == _SCORING_FIELDS, "policy scoring field membership mismatch")
    for model in MODEL_NAMES:
        semantic = model_semantics[model]
        _require(
            isinstance(semantic, dict)
            and set(semantic) == _MODEL_SEMANTIC_FIELDS,
            f"policy model semantic mismatch: {model}",
        )
        _exact_positive_int(
            semantic.get("message_length"),
            label=f"{model} message_length",
        )
        _require(
            isinstance(semantic.get("primary_decoder"), str)
            and bool(semantic["primary_decoder"]),
            f"{model} primary_decoder is missing",
        )
        _number(
            semantic.get("success_threshold"),
            label=f"{model} success_threshold",
            minimum=0.5,
            maximum=0.999999,
        )
    summary_path = evidence.get("summary_path")
    _require(
        isinstance(summary_path, str)
        and summary_path.startswith("reports/")
        and not Path(summary_path).is_absolute()
        and ".." not in Path(summary_path).parts,
        "invalid MEA summary path",
    )
    for field in (
        "summary_sha256",
        "dataset_manifest_sha256",
        "raw_results_sha256",
        "run_config_sha256",
        "progress_sha256",
        "protocol_sha256",
    ):
        value = evidence.get(field)
        _require(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            f"invalid evidence hash: {field}",
        )
    images_per_cell = _exact_positive_int(
        evidence.get("images_per_cell"), label="images_per_cell"
    )
    expected_cells = _exact_positive_int(
        evidence.get("expected_cells"), label="expected_cells"
    )
    expected_rows = _exact_positive_int(
        evidence.get("expected_rows"), label="expected_rows"
    )
    _require(expected_cells == len(MODEL_NAMES) ** 2, "expected cell count mismatch")
    _require(
        expected_rows == expected_cells * images_per_cell,
        "expected row count mismatch",
    )
    _require(
        uncertainty.get("method")
        == "deterministic_identity_cluster_bootstrap_percentile",
        "cluster bootstrap method mismatch",
    )
    _require(
        uncertainty.get("cluster_key") == "lfw_filename_identity_prefix_v1",
        "identity cluster key mismatch",
    )
    _require(
        uncertainty.get("estimand")
        == "equal_identity_weighted_mean_of_within_identity_image_means",
        "cluster estimand mismatch",
    )
    _require(
        uncertainty.get("normalized_margin_transform")
        == "piecewise_linear_protocol_threshold_centered_at_0_5",
        "protocol-normalized margin transform mismatch",
    )
    _require(
        uncertainty.get("rng") == "numpy_pcg64_multinomial",
        "cluster bootstrap RNG mismatch",
    )
    _require(
        uncertainty.get("quantile_method") == "lower",
        "cluster bootstrap quantile method mismatch",
    )
    _require(
        uncertainty.get("multiplicity_adjustment")
        == "bonferroni_one_sided_fixed_full_selection_family",
        "cluster multiplicity adjustment mismatch",
    )
    _require(
        uncertainty.get("family_metrics") == list(CLUSTER_METRICS),
        "cluster family metric membership mismatch",
    )
    family_size = _exact_positive_int(
        uncertainty.get("family_size"), label="cluster family_size"
    )
    _require(
        family_size == len(MODEL_NAMES) ** 2 * len(CLUSTER_METRICS),
        "cluster family size mismatch",
    )
    seed = uncertainty.get("seed")
    _require(
        isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0,
        "cluster bootstrap seed must be a non-negative integer",
    )
    _require(seed == 20260603, "cluster bootstrap seed mismatch")
    resamples = _exact_positive_int(
        uncertainty.get("resamples"), label="cluster bootstrap resamples"
    )
    _require(
        128 <= resamples <= 1_000_000,
        "cluster bootstrap resamples must be between 128 and 1000000",
    )
    confidence = _number(
        uncertainty.get("confidence_level"),
        label="confidence level",
        minimum=0.5,
        maximum=0.999,
    )
    _require(confidence == 0.95, "confidence level mismatch")
    expected_image_count = _exact_positive_int(
        uncertainty.get("expected_image_count"),
        label="expected image count",
    )
    _require(expected_image_count == images_per_cell, "cluster image count mismatch")
    expected_identity_count = _exact_positive_int(
        uncertainty.get("expected_identity_count"),
        label="expected identity count",
    )
    for field in (
        "expected_repeated_identity_count",
        "expected_images_in_repeated_identities",
        "expected_max_cluster_size",
    ):
        _exact_positive_int(uncertainty.get(field), label=field)
    _require(
        expected_identity_count <= expected_image_count,
        "identity count exceeds image count",
    )
    _require(
        (
            expected_image_count,
            expected_identity_count,
            uncertainty["expected_repeated_identity_count"],
            uncertainty["expected_images_in_repeated_identities"],
            uncertainty["expected_max_cluster_size"],
        )
        == (256, 217, 24, 63, 10),
        "fixed identity cluster audit mismatch",
    )
    floor = _number(
        scoring.get("fidelity_psnr_floor_db"),
        label="PSNR floor",
        minimum=0.0,
        maximum=100.0,
    )
    ceiling = _number(
        scoring.get("fidelity_psnr_ceiling_db"),
        label="PSNR ceiling",
        minimum=0.0,
        maximum=100.0,
    )
    _require(ceiling > floor, "PSNR ceiling must exceed floor")
    _require((floor, ceiling) == (20.0, 45.0), "PSNR normalization range mismatch")
    minimum_allowed = _number(
        scoring.get("minimum_allowed_worst_case_protocol_normalized_margin"),
        label="minimum allowed worst-case protocol-normalized margin",
        minimum=0.0,
        maximum=1.0,
    )
    _require(minimum_allowed == 0.45, "normalized-margin policy floor mismatch")
    minimum_post_psnr = _number(
        scoring.get("minimum_post_attack_psnr_lcb_db"),
        label="minimum post-attack PSNR LCB",
        minimum=0.0,
        maximum=100.0,
    )
    _require(
        floor <= minimum_post_psnr <= ceiling,
        "minimum post-attack PSNR LCB must be inside the scoring range",
    )
    minimum_source_success = _number(
        scoring.get("minimum_source_protocol_success_rate_lcb"),
        label="minimum source protocol success-rate LCB",
        minimum=0.0,
        maximum=1.0,
    )
    minimum_ssim = _number(
        scoring.get("minimum_post_attack_ssim_lcb"),
        label="minimum post-attack SSIM LCB",
        minimum=0.0,
        maximum=1.0,
    )
    _require(
        (minimum_source_success, minimum_post_psnr, minimum_ssim)
        == (0.5, 20.0, 0.6),
        "fixed collaboration hard constraints mismatch",
    )
    for field in (
        "default_risk_aversion",
        "default_fidelity_weight",
        "default_minimum_worst_case_protocol_normalized_margin",
    ):
        _number(scoring.get(field), label=field, minimum=0.0, maximum=1.0)
    _require(
        float(scoring["default_minimum_worst_case_protocol_normalized_margin"])
        >= minimum_allowed,
        "default minimum normalized margin weakens the policy floor",
    )
    _require(
        (
            float(scoring["default_risk_aversion"]),
            float(scoring["default_fidelity_weight"]),
            float(scoring["default_minimum_worst_case_protocol_normalized_margin"]),
        )
        == (0.6, 0.2, 0.45),
        "default collaboration decision profile mismatch",
    )


def _validate_artifact(
    summary_dir: Path,
    entry: Mapping[str, Any],
    *,
    expected_sha256: str,
    label: str,
    capture_bytes: bool = False,
    maximum_bytes: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = entry.get("path")
    embedded_hash = entry.get("sha256")
    _require(
        isinstance(reference, str)
        and reference
        and not Path(reference).is_absolute()
        and ".." not in Path(reference).parts,
        f"invalid {label} path",
    )
    _require(embedded_hash == expected_sha256, f"{label} embedded hash mismatch")
    unresolved = summary_dir / reference
    _require(not unresolved.is_symlink(), f"{label} must not be a symlink")
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(summary_dir.resolve())
    except ValueError as exc:
        raise CollaborationPolicyError(f"{label} escapes its evidence directory") from exc
    snapshot = _snapshot_regular_file(
        candidate,
        label=label,
        capture_bytes=capture_bytes,
        maximum_bytes=maximum_bytes,
    )
    _require(snapshot["sha256"] == expected_sha256, f"{label} content hash mismatch")
    return {
        "path": reference,
        "sha256": snapshot["sha256"],
        "size_bytes": snapshot["size_bytes"],
    }, snapshot


def _validate_progress(
    progress: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    expected = config["evidence"]
    _require(
        progress.get("schema_version") == "mea-matrix-progress.v1",
        "MEA progress schema mismatch",
    )
    _require(progress.get("status") == "complete", "MEA progress is not complete")
    coverage = progress.get("coverage")
    _require(isinstance(coverage, dict), "MEA progress coverage is missing")
    expected_coverage = {
        "complete_cells": expected["expected_cells"],
        "expected_cells": expected["expected_cells"],
        "expected_rows": expected["expected_rows"],
        "observed_unique_expected_rows": expected["expected_rows"],
        "valid_rows": expected["expected_rows"],
        "duplicate_rows": 0,
        "error_rows": 0,
        "missing_rows": 0,
        "unexpected_rows": 0,
    }
    for field, value in expected_coverage.items():
        _require(coverage.get(field) == value, f"MEA progress mismatch: {field}")
    raw_results = progress.get("raw_results")
    _require(isinstance(raw_results, dict), "MEA progress raw-result evidence is missing")
    _require(raw_results.get("path") == "raw_results.csv", "MEA progress raw path mismatch")
    _require(
        raw_results.get("sha256") == expected["raw_results_sha256"],
        "MEA progress raw hash mismatch",
    )
    cells = progress.get("cells")
    expected_cell_ids = {
        f"{source}::{attacker}"
        for source in MODEL_NAMES
        for attacker in MODEL_NAMES
    }
    _require(
        isinstance(cells, dict) and set(cells) == expected_cell_ids,
        "MEA progress cell membership mismatch",
    )
    for cell_id, cell in cells.items():
        _require(isinstance(cell, dict), f"invalid MEA progress cell: {cell_id}")
        _require(cell.get("cell_id") == cell_id, "MEA progress cell id mismatch")
        for field, value in (
            ("status", "complete"),
            ("expected_rows", expected["images_per_cell"]),
            ("observed_rows", expected["images_per_cell"]),
            ("valid_rows", expected["images_per_cell"]),
            ("error_rows", 0),
            ("missing_rows", 0),
        ):
            _require(cell.get(field) == value, f"MEA progress cell mismatch: {field}")


def _validate_mean_stats(
    payload: Any,
    *,
    label: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    _require(
        isinstance(payload, dict)
        and set(payload) == {"mean", "std", "median", "min", "max"},
        f"MEA metric summary mismatch: {label}",
    )
    values = {
        field: _number(payload.get(field), label=f"{label} {field}")
        for field in ("mean", "std", "median", "min", "max")
    }
    _require(values["std"] >= 0.0, f"MEA metric standard deviation is negative: {label}")
    _require(
        values["min"] <= values["median"] <= values["max"]
        and values["min"] <= values["mean"] <= values["max"],
        f"MEA metric order mismatch: {label}",
    )
    if minimum is not None:
        _require(values["min"] >= minimum, f"MEA metric is below range: {label}")
    if maximum is not None:
        _require(values["max"] <= maximum, f"MEA metric exceeds range: {label}")


def _wilson_interval(successes: int, total: int, z_score: float) -> tuple[float, float]:
    proportion = successes / total
    denominator = 1.0 + z_score * z_score / total
    center = (proportion + z_score * z_score / (2.0 * total)) / denominator
    half = (
        z_score
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z_score * z_score / (4.0 * total * total)
        )
        / denominator
    )
    return max(0.0, center - half), min(1.0, center + half)


def _validate_success_rate(
    aggregates: Mapping[str, Any],
    *,
    prefix: str,
    sample_count: int,
    label: str,
) -> None:
    rate = _number(
        aggregates.get(f"{prefix}_success_rate"),
        label=f"{label} {prefix} success rate",
        minimum=0.0,
        maximum=1.0,
    )
    successes = round(rate * sample_count)
    _require(
        math.isclose(rate, successes / sample_count, rel_tol=0.0, abs_tol=1e-12),
        f"MEA success rate is not an exact sample proportion: {label}",
    )
    interval = aggregates.get(f"{prefix}_success_rate_wilson95")
    _require(
        isinstance(interval, list) and len(interval) == 2,
        f"MEA Wilson interval is missing: {label}",
    )
    observed = tuple(
        _number(value, label=f"{label} Wilson95", minimum=0.0, maximum=1.0)
        for value in interval
    )
    expected = _wilson_interval(successes, sample_count, 1.959963984540054)
    _require(
        all(
            math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
            for left, right in zip(observed, expected)
        ),
        f"MEA Wilson interval mismatch: {label}",
    )


def validate_mea_summary(
    summary: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    """Validate all semantics used by the policy engine before scoring."""

    _validate_policy_config(config)
    expected = config["evidence"]
    _require(summary.get("schema_version") == SUMMARY_SCHEMA, "MEA summary schema mismatch")
    _require(summary.get("status") == "complete", "MEA summary is not complete")
    _require(summary.get("preflight_errors") == [], "MEA preflight contains errors")
    postflight = summary.get("postflight_input_audit")
    _require(isinstance(postflight, dict), "MEA postflight audit is missing")
    for field in (
        "checkpoint_sha256_unchanged",
        "dataset_files_unchanged",
        "implementation_sha256_unchanged",
        "protocol_sha256_unchanged",
        "verified",
    ):
        _require(postflight.get(field) is True, f"MEA postflight failed: {field}")
    _require(postflight.get("errors") == [], "MEA postflight contains errors")

    _require(summary.get("models") == list(MODEL_NAMES), "MEA model list mismatch")
    _require(summary.get("model_count") == len(MODEL_NAMES), "MEA model count mismatch")
    images_per_cell = _exact_positive_int(
        summary.get("images_per_cell"), label="MEA images_per_cell"
    )
    _require(images_per_cell == expected["images_per_cell"], "MEA sample count mismatch")

    coverage = summary.get("coverage")
    _require(isinstance(coverage, dict), "MEA coverage is missing")
    exact_coverage = {
        "complete_cells": expected["expected_cells"],
        "expected_cells": expected["expected_cells"],
        "expected_rows": expected["expected_rows"],
        "observed_unique_expected_rows": expected["expected_rows"],
        "valid_rows": expected["expected_rows"],
        "duplicate_rows": 0,
        "error_rows": 0,
        "missing_rows": 0,
        "unexpected_rows": 0,
    }
    for field, value in exact_coverage.items():
        _require(coverage.get(field) == value, f"MEA coverage mismatch: {field}")

    protocol = summary.get("protocol")
    _require(isinstance(protocol, dict), "MEA protocol evidence is missing")
    _require(
        protocol.get("sha256") == expected["protocol_sha256"],
        "MEA protocol hash mismatch",
    )
    protocol_threshold = _number(
        protocol.get("success_threshold"),
        label="MEA success threshold",
        minimum=0.0,
        maximum=1.0,
    )
    _require(
        all(
            math.isclose(
                float(config["model_semantics"][model]["success_threshold"]),
                protocol_threshold,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for model in MODEL_NAMES
        ),
        "model semantic thresholds differ from the signed protocol",
    )

    artifacts = summary.get("artifacts")
    _require(isinstance(artifacts, dict), "MEA artifact evidence is missing")
    for artifact_name, config_field in ARTIFACT_HASH_FIELDS.items():
        entry = artifacts.get(artifact_name)
        _require(isinstance(entry, dict), f"MEA artifact is missing: {artifact_name}")
        _require(
            entry.get("sha256") == expected[config_field],
            f"MEA artifact hash mismatch: {artifact_name}",
        )

    checkpoints = summary.get("checkpoint_evidence")
    _require(
        isinstance(checkpoints, dict) and set(checkpoints) == set(MODEL_NAMES),
        "MEA checkpoint evidence mismatch",
    )
    for model in MODEL_NAMES:
        checkpoint = checkpoints[model]
        _require(isinstance(checkpoint, dict), f"invalid checkpoint evidence: {model}")
        _require(checkpoint.get("status") == "available", f"checkpoint unavailable: {model}")
        _require(
            checkpoint.get("integrity_verified") is True,
            f"checkpoint integrity is unverified: {model}",
        )
        _require(
            checkpoint.get("checkpoint_sha256")
            == checkpoint.get("expected_checkpoint_sha256"),
            f"checkpoint hash mismatch: {model}",
        )

    matrix = summary.get("matrix")
    _require(
        isinstance(matrix, dict) and set(matrix) == set(MODEL_NAMES),
        "MEA source matrix mismatch",
    )
    for source in MODEL_NAMES:
        attackers = matrix[source]
        _require(
            isinstance(attackers, dict) and set(attackers) == set(MODEL_NAMES),
            f"MEA attacker matrix mismatch: {source}",
        )
        source_psnr: float | None = None
        source_ssim: float | None = None
        for attacker in MODEL_NAMES:
            cell = attackers[attacker]
            _require(isinstance(cell, dict), f"invalid MEA cell: {source}::{attacker}")
            _require(cell.get("cell_id") == f"{source}::{attacker}", "MEA cell id mismatch")
            _require(cell.get("status") == "complete", "MEA cell is incomplete")
            for field, value in (
                ("expected_rows", images_per_cell),
                ("observed_rows", images_per_cell),
                ("valid_rows", images_per_cell),
                ("error_rows", 0),
                ("missing_rows", 0),
            ):
                _require(cell.get(field) == value, f"MEA cell coverage mismatch: {field}")
            aggregates = cell.get("aggregates")
            _require(isinstance(aggregates, dict), "MEA cell aggregates are missing")
            for metric in (
                "source_bit_accuracy",
                "attacker_bit_accuracy",
                "first_embedding_ssim",
                "second_vs_original_ssim",
            ):
                _validate_mean_stats(
                    aggregates.get(metric),
                    label=f"{source}::{attacker} {metric}",
                    minimum=0.0,
                    maximum=1.0,
                )
                if metric == "first_embedding_ssim":
                    value = float(aggregates[metric]["mean"])
                    if source_ssim is None:
                        source_ssim = value
                    _require(
                        math.isclose(source_ssim, value, rel_tol=0.0, abs_tol=1e-12),
                        f"first-embedding SSIM drift across {source} cells",
                    )
            for metric in (
                "first_embedding_psnr",
                "second_vs_original_psnr",
                "second_vs_first_psnr",
            ):
                metric_payload = aggregates.get(metric)
                _validate_mean_stats(
                    metric_payload,
                    label=f"{source}::{attacker} {metric}",
                    minimum=0.0,
                )
                if metric == "first_embedding_psnr":
                    value = float(metric_payload["mean"])
                    if source_psnr is None:
                        source_psnr = value
                    _require(
                        math.isclose(source_psnr, value, rel_tol=0.0, abs_tol=1e-9),
                        f"first-embedding PSNR drift across {source} cells",
                    )
            _validate_mean_stats(
                aggregates.get("second_vs_first_ssim"),
                label=f"{source}::{attacker} second_vs_first_ssim",
                minimum=0.0,
                maximum=1.0,
            )
            for prefix in ("source", "attacker"):
                _validate_success_rate(
                    aggregates,
                    prefix=prefix,
                    sample_count=images_per_cell,
                    label=f"{source}::{attacker}",
                )


def _protocol_normalized_margin(value: float, threshold: float) -> float:
    """Map each model's registered pass threshold to the common value 0.5.

    Raw bit accuracies remain available as diagnostics, but never enter
    cross-model ranking because message capacities and decoder semantics differ.
    """

    bounded = min(1.0, max(0.0, value))
    if bounded <= threshold:
        return 0.5 * bounded / threshold
    return 0.5 + 0.5 * (bounded - threshold) / (1.0 - threshold)


def _lfw_identity(reference: str) -> str:
    path = Path(reference)
    _require(
        isinstance(reference, str)
        and bool(reference)
        and not path.is_absolute()
        and ".." not in path.parts,
        "dataset path is invalid for identity clustering",
    )
    matched = _LFW_IDENTITY_RE.fullmatch(path.stem)
    _require(matched is not None, "dataset path does not encode an LFW identity")
    return str(matched.group("identity"))


def _csv_integer(row: Mapping[str, str], field: str, *, minimum: int = 0) -> int:
    raw = row.get(field)
    try:
        value = int(str(raw))
    except (TypeError, ValueError) as exc:
        raise CollaborationPolicyError(f"raw result integer is invalid: {field}") from exc
    _require(value >= minimum and str(value) == str(raw), f"raw result integer is invalid: {field}")
    return value


def _csv_number(
    row: Mapping[str, str],
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = row.get(field)
    try:
        value = float(str(raw))
    except (TypeError, ValueError) as exc:
        raise CollaborationPolicyError(f"raw result number is invalid: {field}") from exc
    _require(math.isfinite(value), f"raw result number is non-finite: {field}")
    if minimum is not None:
        _require(value >= minimum, f"raw result number is below range: {field}")
    if maximum is not None:
        _require(value <= maximum, f"raw result number exceeds range: {field}")
    return value


def build_identity_cluster_input(
    dataset_manifest: Mapping[str, Any],
    raw_results_csv: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct the fixed identity-cluster estimand from signed raw inputs."""

    _validate_policy_config(config)
    uncertainty = config["uncertainty"]
    expected_images = int(uncertainty["expected_image_count"])
    _require(
        dataset_manifest.get("schema_version") == "mea-shared-dataset-manifest.v1",
        "dataset manifest schema mismatch for clustering",
    )
    _require(
        dataset_manifest.get("sample_count") == expected_images,
        "dataset manifest sample count mismatch for clustering",
    )
    files = dataset_manifest.get("files")
    _require(
        isinstance(files, list) and len(files) == expected_images,
        "dataset manifest files mismatch for clustering",
    )
    images: dict[str, dict[str, Any]] = {}
    sample_indices: set[int] = set()
    for item in files:
        _require(isinstance(item, dict), "dataset manifest file record is invalid")
        image_id = item.get("image_id")
        reference = item.get("path")
        sample_index = item.get("sample_index")
        _require(
            isinstance(image_id, str)
            and len(image_id) == 64
            and all(character in "0123456789abcdef" for character in image_id),
            "dataset image_id is invalid",
        )
        _require(
            isinstance(sample_index, int)
            and not isinstance(sample_index, bool)
            and 0 <= sample_index < expected_images,
            "dataset sample_index is invalid",
        )
        _require(image_id not in images, "dataset image_id is duplicated")
        _require(sample_index not in sample_indices, "dataset sample_index is duplicated")
        identity = _lfw_identity(reference)
        images[image_id] = {
            "path": reference,
            "sample_index": sample_index,
            "identity": identity,
        }
        sample_indices.add(sample_index)
    _require(
        sample_indices == set(range(expected_images)),
        "dataset sample indices are incomplete",
    )

    identity_sizes: dict[str, int] = {}
    for item in images.values():
        identity = str(item["identity"])
        identity_sizes[identity] = identity_sizes.get(identity, 0) + 1
    identities = sorted(identity_sizes)
    repeated_identity_count = sum(size > 1 for size in identity_sizes.values())
    images_in_repeated_identities = sum(
        size for size in identity_sizes.values() if size > 1
    )
    max_cluster_size = max(identity_sizes.values())
    for actual, field in (
        (len(identities), "expected_identity_count"),
        (repeated_identity_count, "expected_repeated_identity_count"),
        (images_in_repeated_identities, "expected_images_in_repeated_identities"),
        (max_cluster_size, "expected_max_cluster_size"),
    ):
        _require(actual == uncertainty[field], f"identity cluster audit mismatch: {field}")

    try:
        reader = csv.DictReader(io.StringIO(raw_results_csv, newline=""))
        raw_rows = list(reader)
    except (csv.Error, UnicodeError) as exc:
        raise CollaborationPolicyError("raw results CSV could not be parsed") from exc
    required_fields = {
        "cell_id",
        "source_model",
        "attacker_model",
        "sample_index",
        "image_id",
        "source_path",
        "success_threshold",
        "source_primary_decoder",
        "attacker_primary_decoder",
        "source_message_length",
        "attacker_message_length",
        "source_bit_accuracy",
        "source_success",
        "attacker_bit_accuracy",
        "attacker_success",
        "first_embedding_psnr",
        "second_vs_original_psnr",
        "second_vs_original_ssim",
        "status",
        "error_stage",
        "error_type",
        "error",
    }
    _require(
        reader.fieldnames is not None and required_fields.issubset(reader.fieldnames),
        "raw results CSV schema is incomplete for clustering",
    )
    _require(
        len(raw_rows) == config["evidence"]["expected_rows"],
        "raw results row count mismatch for clustering",
    )

    cell_rows: dict[tuple[str, str], dict[str, dict[str, float]]] = {
        (source, attacker): {}
        for source in MODEL_NAMES
        for attacker in MODEL_NAMES
    }
    for row in raw_rows:
        source = row.get("source_model")
        attacker = row.get("attacker_model")
        _require(
            source in MODEL_NAMES and attacker in MODEL_NAMES,
            "raw result model is outside the fixed registry",
        )
        _require(row.get("cell_id") == f"{source}::{attacker}", "raw result cell_id mismatch")
        _require(
            row.get("status") == "ok"
            and row.get("error_stage") == ""
            and row.get("error_type") == ""
            and row.get("error") == "",
            "raw result contains an error row",
        )
        image_id = row.get("image_id")
        _require(image_id in images, "raw result image is absent from dataset manifest")
        image = images[str(image_id)]
        _require(row.get("source_path") == image["path"], "raw result source path mismatch")
        _require(
            _csv_integer(row, "sample_index") == image["sample_index"],
            "raw result sample_index mismatch",
        )
        source_semantic = config["model_semantics"][str(source)]
        attacker_semantic = config["model_semantics"][str(attacker)]
        _require(
            _csv_integer(row, "source_message_length", minimum=1)
            == source_semantic["message_length"]
            and row.get("source_primary_decoder") == source_semantic["primary_decoder"],
            "raw source message/decoder semantic mismatch",
        )
        _require(
            _csv_integer(row, "attacker_message_length", minimum=1)
            == attacker_semantic["message_length"]
            and row.get("attacker_primary_decoder")
            == attacker_semantic["primary_decoder"],
            "raw attacker message/decoder semantic mismatch",
        )
        threshold = _csv_number(
            row,
            "success_threshold",
            minimum=0.0,
            maximum=1.0,
        )
        _require(
            math.isclose(
                threshold,
                float(source_semantic["success_threshold"]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and math.isclose(
                threshold,
                float(attacker_semantic["success_threshold"]),
                rel_tol=0.0,
                abs_tol=1e-12,
            ),
            "raw result threshold differs from registered model semantics",
        )
        source_accuracy = _csv_number(
            row, "source_bit_accuracy", minimum=0.0, maximum=1.0
        )
        attacker_accuracy = _csv_number(
            row, "attacker_bit_accuracy", minimum=0.0, maximum=1.0
        )
        source_success = _csv_integer(row, "source_success")
        attacker_success = _csv_integer(row, "attacker_success")
        _require(source_success in {0, 1} and attacker_success in {0, 1}, "raw success flag is invalid")
        _require(
            source_success == int(source_accuracy >= threshold)
            and attacker_success == int(attacker_accuracy >= threshold),
            "raw success flag is not reproducible from the registered threshold",
        )
        metrics = {
            "source_bit_accuracy_diagnostic": source_accuracy,
            "attacker_bit_accuracy_diagnostic": attacker_accuracy,
            "source_protocol_normalized_margin": _protocol_normalized_margin(
                source_accuracy,
                float(source_semantic["success_threshold"]),
            ),
            "source_protocol_success": float(source_success),
            "attacker_protocol_normalized_margin": _protocol_normalized_margin(
                attacker_accuracy,
                float(attacker_semantic["success_threshold"]),
            ),
            "attacker_protocol_success": float(attacker_success),
            "first_embedding_psnr": _csv_number(
                row, "first_embedding_psnr", minimum=0.0
            ),
            "second_vs_original_psnr": _csv_number(
                row, "second_vs_original_psnr", minimum=0.0
            ),
            "second_vs_original_ssim": _csv_number(
                row, "second_vs_original_ssim", minimum=0.0, maximum=1.0
            ),
        }
        target = cell_rows[(str(source), str(attacker))]
        _require(image_id not in target, "raw result duplicates a cell/image row")
        target[str(image_id)] = metrics

    cluster_cells: dict[str, dict[str, Any]] = {model: {} for model in MODEL_NAMES}
    expected_image_ids = set(images)
    for source in MODEL_NAMES:
        for attacker in MODEL_NAMES:
            rows_by_image = cell_rows[(source, attacker)]
            _require(
                set(rows_by_image) == expected_image_ids,
                f"raw result cell image membership mismatch: {source}::{attacker}",
            )
            by_identity: dict[str, list[dict[str, float]]] = {
                identity: [] for identity in identities
            }
            for image_id, values in rows_by_image.items():
                by_identity[str(images[image_id]["identity"])].append(values)
            metric_names = tuple(next(iter(rows_by_image.values())))
            vectors: dict[str, list[float]] = {name: [] for name in metric_names}
            for identity in identities:
                identity_rows = by_identity[identity]
                _require(
                    len(identity_rows) == identity_sizes[identity],
                    "identity cluster row count mismatch",
                )
                for name in metric_names:
                    vectors[name].append(
                        math.fsum(row[name] for row in identity_rows)
                        / len(identity_rows)
                    )
            cluster_cells[source][attacker] = vectors

    return {
        "schema_version": "mea-identity-cluster-input.v1",
        "image_count": expected_images,
        "identity_count": len(identities),
        "repeated_identity_count": repeated_identity_count,
        "images_in_repeated_identities": images_in_repeated_identities,
        "max_cluster_size": max_cluster_size,
        "identities": identities,
        "identity_sizes": identity_sizes,
        "raw_rows": len(raw_rows),
        "cells": cluster_cells,
    }


def _verified_policy_signature(
    config_path: Path,
    config_snapshot: Mapping[str, Any],
    matrix_validation: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prove that the exact policy bytes used are in the verified release bundle."""

    _require(
        config_path.resolve() == POLICY_CONFIG_PATH.resolve(),
        "signed decisions require the canonical policy path",
    )
    signature = matrix_validation.get("signature")
    _require(isinstance(signature, dict), "release signature status is missing")
    _require(signature.get("verified") is True, "release signature is unverified")
    _require(signature.get("signer_pinned") is True, "release signer is not pinned")
    _require(
        signature.get("profile") in {"release-core", "release"},
        "release signature profile mismatch",
    )
    for field in ("manifest_sha256", "public_key_fingerprint_sha256"):
        value = signature.get(field)
        _require(
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value),
            f"release signature {field} is invalid",
        )

    from .signing import MANIFEST_PATH

    manifest, manifest_snapshot = _read_json_snapshot(
        MANIFEST_PATH,
        label="release signature manifest",
        maximum_bytes=16 * 1024 * 1024,
    )
    _require(
        manifest_snapshot["sha256"] == signature.get("manifest_sha256"),
        "release signature manifest changed during policy evaluation",
    )
    _require(
        manifest.get("schema_version") == "evidence-manifest.v1"
        and manifest.get("profile") == signature.get("profile")
        and isinstance(manifest.get("files"), list),
        "release signature manifest contract mismatch",
    )
    try:
        policy_reference = config_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise CollaborationPolicyError("policy path is outside the project root") from exc
    records = [
        item
        for item in manifest.get("files", [])
        if isinstance(item, dict) and item.get("path") == policy_reference
    ]
    _require(len(records) == 1, "policy is not uniquely covered by the release signature")
    record = records[0]
    _require(
        record.get("sha256") == config_snapshot["sha256"]
        and record.get("size_bytes") == config_snapshot["size_bytes"]
        and record.get("role") == "evidence",
        "policy bytes are not covered by the release signature",
    )
    return {
        "verified": True,
        "signer_pinned": True,
        "profile": signature["profile"],
        "manifest_sha256": signature["manifest_sha256"],
        "public_key_fingerprint_sha256": signature.get(
            "public_key_fingerprint_sha256"
        ),
        "policy_path": policy_reference,
        "policy_sha256": config_snapshot["sha256"],
    }, manifest_snapshot


def _require_matrix_snapshot_binding(
    matrix_validation: Mapping[str, Any],
    snapshots: Mapping[str, Mapping[str, Any]],
) -> None:
    """Bind every locally consumed snapshot to the exact validated matrix closure."""

    evidence_files = matrix_validation.get("evidence_files")
    _require(
        isinstance(evidence_files, dict)
        and set(evidence_files) == set(snapshots),
        "MEA validator file membership mismatch",
    )
    for name, snapshot in snapshots.items():
        record = evidence_files.get(name)
        _require(
            isinstance(record, dict)
            and record.get("sha256") == snapshot.get("sha256"),
            f"MEA validator snapshot mismatch: {name}",
        )


def load_policy_evidence(
    config_path: Path = POLICY_CONFIG_PATH,
    *,
    require_signature: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load and content-verify the policy, summary, and every bound MEA input."""

    config, config_snapshot = _read_json_snapshot(
        config_path,
        label="collaboration policy",
        maximum_bytes=_MAX_POLICY_BYTES,
    )
    _validate_policy_config(config)
    evidence = config["evidence"]
    summary_reference = evidence.get("summary_path")
    _require(isinstance(summary_reference, str), "MEA summary path is missing")
    summary_path = resolve_logical_path(summary_reference)
    _require(summary_path is not None, "MEA summary path is outside runtime roots")
    try:
        summary_path.resolve().relative_to(REPORTS.resolve())
    except (OSError, ValueError) as exc:
        raise CollaborationPolicyError("MEA summary is outside the report root") from exc
    summary, summary_snapshot = _read_json_snapshot(
        summary_path,
        label="MEA summary",
        maximum_bytes=_MAX_SUMMARY_BYTES,
    )
    summary_sha256 = summary_snapshot["sha256"]
    _require(summary_sha256 == evidence["summary_sha256"], "MEA summary hash mismatch")
    validate_mea_summary(summary, config)
    matrix_validation = validate_mea_matrix_evidence(
        directory=summary_path.parent,
        require_signature=require_signature,
    )
    _require(
        matrix_validation.get("valid") is True,
        "MEA matrix hash closure is invalid",
    )
    release_signature: dict[str, Any] | None = None
    manifest_snapshot: dict[str, Any] | None = None
    if require_signature:
        release_signature, manifest_snapshot = _verified_policy_signature(
            config_path,
            config_snapshot,
            matrix_validation,
        )

    verified_artifacts: dict[str, Any] = {}
    artifact_snapshots: dict[str, dict[str, Any]] = {}
    for artifact_name, config_field in ARTIFACT_HASH_FIELDS.items():
        capture_bytes = artifact_name in {"dataset_manifest", "raw_results"}
        maximum_bytes = {
            "dataset_manifest": _MAX_DATASET_MANIFEST_BYTES,
            "raw_results": _MAX_RAW_RESULTS_BYTES,
        }.get(artifact_name)
        artifact, snapshot = _validate_artifact(
            summary_path.parent,
            summary["artifacts"][artifact_name],
            expected_sha256=evidence[config_field],
            label=artifact_name,
            capture_bytes=capture_bytes,
            maximum_bytes=maximum_bytes,
        )
        verified_artifacts[artifact_name] = artifact
        artifact_snapshots[artifact_name] = snapshot
    progress_path = summary_path.parent / "progress.json"
    progress, progress_snapshot = _read_json_snapshot(
        progress_path,
        label="MEA progress",
        maximum_bytes=_MAX_PROGRESS_BYTES,
    )
    _require(
        progress_snapshot["sha256"] == evidence["progress_sha256"],
        "progress content hash mismatch",
    )
    verified_artifacts["progress"] = {
        "path": "progress.json",
        "sha256": progress_snapshot["sha256"],
        "size_bytes": progress_snapshot["size_bytes"],
    }
    _validate_progress(progress, config)

    dataset_manifest = _json_from_snapshot(
        artifact_snapshots["dataset_manifest"],
        label="dataset_manifest",
    )
    raw_results_bytes = artifact_snapshots["raw_results"].get("bytes")
    _require(isinstance(raw_results_bytes, bytes), "raw_results was not captured")
    try:
        raw_results_csv = raw_results_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise CollaborationPolicyError("raw_results is not UTF-8") from exc
    cluster_input = build_identity_cluster_input(
        dataset_manifest,
        raw_results_csv,
        config,
    )

    _require_matrix_snapshot_binding(
        matrix_validation,
        {
            "dataset_manifest.json": artifact_snapshots["dataset_manifest"],
            "raw_results.csv": artifact_snapshots["raw_results"],
            "run_config.json": artifact_snapshots["run_config"],
            "progress.json": progress_snapshot,
            "summary.json": summary_snapshot,
        },
    )

    _assert_snapshot_unchanged(config_snapshot, label="collaboration policy")
    _assert_snapshot_unchanged(summary_snapshot, label="MEA summary")
    for artifact_name, snapshot in artifact_snapshots.items():
        _assert_snapshot_unchanged(snapshot, label=artifact_name)
    _assert_snapshot_unchanged(progress_snapshot, label="MEA progress")
    if manifest_snapshot is not None:
        _assert_snapshot_unchanged(
            manifest_snapshot,
            label="release signature manifest",
        )
    descriptor = {
        "summary_path": summary_reference,
        "summary_sha256": summary_sha256,
        "policy_path": (
            config_path.resolve().relative_to(ROOT.resolve()).as_posix()
            if config_path.resolve().is_relative_to(ROOT.resolve())
            else str(config_path)
        ),
        "policy_sha256": config_snapshot["sha256"],
        "source_evidence_status": summary.get("evidence_status"),
        "source_claim_status": summary.get("claim_status"),
        "protocol_sha256": summary["protocol"]["sha256"],
        "images_per_cell": summary["images_per_cell"],
        "image_count": cluster_input["image_count"],
        "identity_count": cluster_input["identity_count"],
        "repeated_identity_count": cluster_input["repeated_identity_count"],
        "images_in_repeated_identities": cluster_input[
            "images_in_repeated_identities"
        ],
        "max_cluster_size": cluster_input["max_cluster_size"],
        "cells": summary["coverage"]["complete_cells"],
        "rows": summary["coverage"]["valid_rows"],
        "artifacts": verified_artifacts,
        "matrix_validation": matrix_validation,
        "release_signature": release_signature,
        "signature_verified": bool(
            release_signature and release_signature.get("verified") is True
        ),
        "signer_pinned": bool(
            release_signature and release_signature.get("signer_pinned") is True
        ),
        "content_verified": True,
    }
    return config, summary, descriptor, cluster_input


def _normalize_request(
    request: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise ValueError("request must be an object")
    allowed_fields = {
        "threats",
        "candidate_models",
        "risk_aversion",
        "fidelity_weight",
        "minimum_worst_case_protocol_normalized_margin",
    }
    if set(request) - allowed_fields:
        raise ValueError("request contains unknown fields")
    scoring = config["scoring"]
    threats = request.get("threats")
    if not isinstance(threats, list) or not threats:
        raise ValueError("threats must contain between one and four model exposures")
    if len(threats) > len(MODEL_NAMES):
        raise ValueError("threats must contain between one and four model exposures")
    exposure_by_model: dict[str, float] = {}
    for item in threats:
        if not isinstance(item, Mapping):
            raise ValueError("each threat must be an object")
        if set(item) != {"model", "exposure"}:
            raise ValueError("each threat must contain only model and exposure")
        model = item.get("model")
        if model not in MODEL_NAMES:
            raise ValueError("unsupported threat model")
        if model in exposure_by_model:
            raise ValueError(f"duplicate threat model: {model}")
        exposure = item.get("exposure")
        if isinstance(exposure, bool) or not isinstance(exposure, (int, float)):
            raise ValueError("threat exposure must be a positive finite number")
        parsed = float(exposure)
        if not math.isfinite(parsed) or not 0 < parsed <= 1_000_000:
            raise ValueError("threat exposure must be a positive finite number")
        exposure_by_model[str(model)] = parsed
    total = sum(exposure_by_model.values())
    probabilities = {
        model: exposure / total for model, exposure in exposure_by_model.items()
    }

    candidates = request.get("candidate_models", list(MODEL_NAMES))
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidate_models must not be empty")
    if len(candidates) > len(MODEL_NAMES):
        raise ValueError("candidate_models may contain at most four models")
    candidate_models = list(candidates)
    if any(not isinstance(model, str) for model in candidate_models):
        raise ValueError("candidate_models contains an unsupported model")
    if len(candidate_models) != len(set(candidate_models)):
        raise ValueError("candidate_models must not contain duplicates")
    if any(model not in MODEL_NAMES for model in candidate_models):
        raise ValueError("candidate_models contains an unsupported model")

    def bounded(name: str, default_name: str) -> float:
        raw_value = request.get(name, scoring[default_name])
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"{name} must be between 0 and 1")
        value = float(raw_value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
        return value

    minimum = bounded(
        "minimum_worst_case_protocol_normalized_margin",
        "default_minimum_worst_case_protocol_normalized_margin",
    )
    policy_floor = float(
        scoring["minimum_allowed_worst_case_protocol_normalized_margin"]
    )
    if minimum < policy_floor:
        raise ValueError(
            "minimum_worst_case_protocol_normalized_margin is below the signed policy floor"
        )

    return {
        "threat_probabilities": probabilities,
        "candidate_models": candidate_models,
        "risk_aversion": bounded("risk_aversion", "default_risk_aversion"),
        "fidelity_weight": bounded("fidelity_weight", "default_fidelity_weight"),
        "minimum_worst_case_protocol_normalized_margin": minimum,
    }


def _metric(cell: Mapping[str, Any], name: str) -> float:
    return float(cell["aggregates"][name]["mean"])


def _metric_lcb(
    cell: Mapping[str, Any],
    name: str,
    *,
    sample_count: int,
    z_score: float,
    lower_bound: float = 0.0,
    upper_bound: float | None = None,
) -> float:
    metric = cell["aggregates"][name]
    value = float(metric["mean"]) - z_score * float(metric["std"]) / math.sqrt(
        sample_count
    )
    value = max(lower_bound, value)
    return min(upper_bound, value) if upper_bound is not None else value


def _success_rate_lcb(
    cell: Mapping[str, Any],
    prefix: str,
    *,
    sample_count: int,
    z_score: float,
) -> float:
    rate = float(cell["aggregates"][f"{prefix}_success_rate"])
    successes = round(rate * sample_count)
    lower, _upper = _wilson_interval(successes, sample_count, z_score)
    return lower


def _simultaneous_z_score(confidence: float, comparisons: int) -> float:
    """Two-sided Bonferroni critical value for the active threat family."""

    alpha = 1.0 - confidence
    return NormalDist().inv_cdf(1.0 - alpha / (2.0 * comparisons))


def _normalized_psnr(value: float, config: Mapping[str, Any]) -> float:
    scoring = config["scoring"]
    floor = float(scoring["fidelity_psnr_floor_db"])
    ceiling = float(scoring["fidelity_psnr_ceiling_db"])
    return min(1.0, max(0.0, (value - floor) / (ceiling - floor)))


def _rounded(value: float) -> float:
    return round(float(value), 8)



def _pareto_frontier(
    rows: Sequence[Mapping[str, Any]],
    dimensions: Sequence[str],
) -> set[str]:
    frontier: set[str] = set()
    for candidate in rows:
        dominated = False
        for other in rows:
            if other["model"] == candidate["model"]:
                continue
            no_worse = all(float(other[key]) >= float(candidate[key]) for key in dimensions)
            strictly_better = any(float(other[key]) > float(candidate[key]) for key in dimensions)
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.add(str(candidate["model"]))
    return frontier


def _cluster_bootstrap_statistics(
    cluster_input: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    uncertainty = config["uncertainty"]
    identity_count = int(uncertainty["expected_identity_count"])
    _require(
        cluster_input.get("schema_version") == "mea-identity-cluster-input.v1"
        and cluster_input.get("image_count") == uncertainty["expected_image_count"]
        and cluster_input.get("identity_count") == identity_count
        and cluster_input.get("raw_rows") == config["evidence"]["expected_rows"],
        "identity cluster input contract mismatch",
    )
    cells = cluster_input.get("cells")
    _require(
        isinstance(cells, dict) and set(cells) == set(MODEL_NAMES),
        "identity cluster source cells mismatch",
    )
    descriptors: list[tuple[str, str, str]] = []
    columns: list[list[float]] = []
    for source in MODEL_NAMES:
        attackers = cells[source]
        _require(
            isinstance(attackers, dict) and set(attackers) == set(MODEL_NAMES),
            f"identity cluster attacker cells mismatch: {source}",
        )
        for attacker in MODEL_NAMES:
            metrics = attackers[attacker]
            _require(isinstance(metrics, dict), "identity cluster metrics are missing")
            for metric in CLUSTER_METRICS:
                vector = metrics.get(metric)
                _require(
                    isinstance(vector, list) and len(vector) == identity_count,
                    f"identity cluster vector mismatch: {source}::{attacker}::{metric}",
                )
                parsed = [
                    _number(value, label=f"cluster metric {metric}")
                    for value in vector
                ]
                if metric != "second_vs_original_psnr":
                    _require(
                        all(0.0 <= value <= 1.0 for value in parsed),
                        f"identity cluster unit metric out of range: {metric}",
                    )
                else:
                    _require(
                        all(value >= 0.0 for value in parsed),
                        "identity cluster PSNR is negative",
                    )
                descriptors.append((source, attacker, metric))
                columns.append(parsed)
    family_size = int(uncertainty["family_size"])
    _require(
        len(descriptors) == family_size,
        "identity cluster bootstrap family size mismatch",
    )

    metric_matrix = np.asarray(columns, dtype=np.float64).T
    _require(
        metric_matrix.shape == (identity_count, family_size)
        and bool(np.isfinite(metric_matrix).all()),
        "identity cluster metric matrix is invalid",
    )
    resamples = int(uncertainty["resamples"])
    generator = np.random.Generator(np.random.PCG64(int(uncertainty["seed"])))
    counts = generator.multinomial(
        identity_count,
        np.full(identity_count, 1.0 / identity_count, dtype=np.float64),
        size=resamples,
    )
    draws = counts @ metric_matrix / identity_count
    confidence = float(uncertainty["confidence_level"])
    per_comparison_alpha = (1.0 - confidence) / family_size
    lcbs = np.quantile(
        draws,
        per_comparison_alpha,
        axis=0,
        method="lower",
    )
    estimates = metric_matrix.mean(axis=0)
    lookup = {descriptor: index for index, descriptor in enumerate(descriptors)}
    statistics: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        source: {attacker: {} for attacker in MODEL_NAMES}
        for source in MODEL_NAMES
    }
    for index, (source, attacker, metric) in enumerate(descriptors):
        lower = max(0.0, float(lcbs[index]))
        if metric != "second_vs_original_psnr":
            lower = min(1.0, lower)
        statistics[source][attacker][metric] = {
            "estimate": float(estimates[index]),
            "lcb": lower,
        }
    return {
        "statistics": statistics,
        "draws": draws,
        "lookup": lookup,
        "per_comparison_alpha": per_comparison_alpha,
    }


def _cluster_point_metric(
    cluster_input: Mapping[str, Any],
    source: str,
    attacker: str,
    metric: str,
) -> float:
    vector = cluster_input["cells"][source][attacker][metric]
    return math.fsum(float(value) for value in vector) / len(vector)


def _selection_stability(
    bootstrap: Mapping[str, Any],
    normalized: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    draws = bootstrap["draws"]
    lookup = bootstrap["lookup"]
    probabilities = normalized["threat_probabilities"]
    candidates = normalized["candidate_models"]
    minimum_margin = normalized[
        "minimum_worst_case_protocol_normalized_margin"
    ]
    scoring = config["scoring"]
    minimum_success = float(
        scoring["minimum_source_protocol_success_rate_lcb"]
    )
    minimum_psnr = float(scoring["minimum_post_attack_psnr_lcb_db"])
    minimum_ssim = float(scoring["minimum_post_attack_ssim_lcb"])
    risk = float(normalized["risk_aversion"])
    fidelity_weight = float(normalized["fidelity_weight"])
    selection_counts = {model: 0 for model in MODEL_NAMES}
    selection_counts["none"] = 0
    for resample_index in range(draws.shape[0]):
        best_model: str | None = None
        best_score = -math.inf
        for model in candidates:
            margins = {
                attacker: float(
                    draws[
                        resample_index,
                        lookup[(model, attacker, "source_protocol_normalized_margin")],
                    ]
                )
                for attacker in probabilities
            }
            successes = [
                float(
                    draws[
                        resample_index,
                        lookup[(model, attacker, "source_protocol_success")],
                    ]
                )
                for attacker in probabilities
            ]
            psnrs = [
                float(
                    draws[
                        resample_index,
                        lookup[(model, attacker, "second_vs_original_psnr")],
                    ]
                )
                for attacker in probabilities
            ]
            ssims = [
                float(
                    draws[
                        resample_index,
                        lookup[(model, attacker, "second_vs_original_ssim")],
                    ]
                )
                for attacker in probabilities
            ]
            if (
                min(margins.values()) < minimum_margin
                or min(successes) < minimum_success
                or min(psnrs) < minimum_psnr
                or min(ssims) < minimum_ssim
            ):
                continue
            expected_margin = sum(
                probabilities[attacker] * margins[attacker]
                for attacker in probabilities
            )
            survival = (1.0 - risk) * expected_margin + risk * min(margins.values())
            expected_psnr = sum(
                probabilities[attacker]
                * float(
                    draws[
                        resample_index,
                        lookup[(model, attacker, "second_vs_original_psnr")],
                    ]
                )
                for attacker in probabilities
            )
            score = (
                (1.0 - fidelity_weight) * survival
                + fidelity_weight * _normalized_psnr(expected_psnr, config)
            )
            if score > best_score + 1e-15:
                best_model = model
                best_score = score
        selection_counts[best_model or "none"] += 1
    resamples = int(draws.shape[0])
    return {
        "method": "cluster_resample_point_policy_selection_frequency",
        "resamples": resamples,
        "selection_frequency": {
            model: _rounded(selection_counts[model] / resamples)
            for model in (*MODEL_NAMES, "none")
        },
    }


def _legacy_iid_reference_selection(
    summary: Mapping[str, Any],
    normalized: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Diagnostic-only ablation of the superseded raw-accuracy i.i.d. rule."""

    probabilities = normalized["threat_probabilities"]
    confidence = float(config["uncertainty"]["confidence_level"])
    z_score = _simultaneous_z_score(confidence, len(probabilities))
    sample_count = int(summary["images_per_cell"])
    feasible: list[tuple[float, str]] = []
    for model in normalized["candidate_models"]:
        cells = summary["matrix"][model]
        accuracy_lcbs = [
            _metric_lcb(
                cells[attacker],
                "source_bit_accuracy",
                sample_count=sample_count,
                z_score=z_score,
                upper_bound=1.0,
            )
            for attacker in probabilities
        ]
        success_lcbs = [
            _success_rate_lcb(
                cells[attacker],
                "source",
                sample_count=sample_count,
                z_score=z_score,
            )
            for attacker in probabilities
        ]
        psnr_lcbs = [
            _metric_lcb(
                cells[attacker],
                "second_vs_original_psnr",
                sample_count=sample_count,
                z_score=z_score,
            )
            for attacker in probabilities
        ]
        ssim_lcbs = [
            _metric_lcb(
                cells[attacker],
                "second_vs_original_ssim",
                sample_count=sample_count,
                z_score=z_score,
                upper_bound=1.0,
            )
            for attacker in probabilities
        ]
        if (
            min(accuracy_lcbs) < float(summary["protocol"]["success_threshold"])
            or min(success_lcbs)
            < float(config["scoring"]["minimum_source_protocol_success_rate_lcb"])
            or min(psnr_lcbs)
            < float(config["scoring"]["minimum_post_attack_psnr_lcb_db"])
            or min(ssim_lcbs)
            < float(config["scoring"]["minimum_post_attack_ssim_lcb"])
        ):
            continue
        expected = sum(
            probabilities[attacker]
            * _metric_lcb(
                cells[attacker],
                "source_bit_accuracy",
                sample_count=sample_count,
                z_score=z_score,
                upper_bound=1.0,
            )
            for attacker in probabilities
        )
        survival = (
            (1.0 - float(normalized["risk_aversion"])) * expected
            + float(normalized["risk_aversion"]) * min(accuracy_lcbs)
        )
        fidelity = _normalized_psnr(
            sum(
                probabilities[attacker] * psnr_lcbs[index]
                for index, attacker in enumerate(probabilities)
            ),
            config,
        )
        score = (
            (1.0 - float(normalized["fidelity_weight"])) * survival
            + float(normalized["fidelity_weight"]) * fidelity
        )
        feasible.append((score, model))
    order = {model: index for index, model in enumerate(MODEL_NAMES)}
    feasible.sort(key=lambda item: (-item[0], order[item[1]]))
    return {
        "method": "legacy_raw_bit_accuracy_iid_normal_wilson_diagnostic_only",
        "selected_model": feasible[0][1] if feasible else None,
        "feasible_models": [model for _score, model in feasible],
    }



def build_recommendation(
    summary: Mapping[str, Any],
    request: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    cluster_input: Mapping[str, Any],
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v2 deployment recommendation from identity-cluster evidence."""

    validate_mea_summary(summary, config)
    normalized = _normalize_request(request, config)
    bootstrap = _cluster_bootstrap_statistics(cluster_input, config)
    statistics = bootstrap["statistics"]
    probabilities = normalized["threat_probabilities"]
    risk_aversion = float(normalized["risk_aversion"])
    fidelity_weight = float(normalized["fidelity_weight"])
    minimum_margin = float(
        normalized["minimum_worst_case_protocol_normalized_margin"]
    )
    scoring = config["scoring"]
    minimum_success_lcb = float(
        scoring["minimum_source_protocol_success_rate_lcb"]
    )
    minimum_post_psnr_lcb = float(scoring["minimum_post_attack_psnr_lcb_db"])
    minimum_post_ssim_lcb = float(scoring["minimum_post_attack_ssim_lcb"])

    rows: list[dict[str, Any]] = []
    for model in normalized["candidate_models"]:
        margins = {
            attacker: statistics[model][attacker][
                "source_protocol_normalized_margin"
            ]["estimate"]
            for attacker in probabilities
        }
        margin_lcbs = {
            attacker: statistics[model][attacker][
                "source_protocol_normalized_margin"
            ]["lcb"]
            for attacker in probabilities
        }
        success_lcbs = {
            attacker: statistics[model][attacker]["source_protocol_success"][
                "lcb"
            ]
            for attacker in probabilities
        }
        psnr_points = {
            attacker: statistics[model][attacker]["second_vs_original_psnr"][
                "estimate"
            ]
            for attacker in probabilities
        }
        psnr_lcbs = {
            attacker: statistics[model][attacker]["second_vs_original_psnr"][
                "lcb"
            ]
            for attacker in probabilities
        }
        ssim_lcbs = {
            attacker: statistics[model][attacker]["second_vs_original_ssim"][
                "lcb"
            ]
            for attacker in probabilities
        }
        expected_margin = sum(
            probabilities[attacker] * margins[attacker]
            for attacker in probabilities
        )
        worst_margin = min(margins.values())
        expected_margin_lcb = sum(
            probabilities[attacker] * margin_lcbs[attacker]
            for attacker in probabilities
        )
        worst_margin_lcb = min(margin_lcbs.values())
        worst_success_lcb = min(success_lcbs.values())
        survival = (
            (1.0 - risk_aversion) * expected_margin_lcb
            + risk_aversion * worst_margin_lcb
        )
        expected_psnr = sum(
            probabilities[attacker] * psnr_points[attacker]
            for attacker in probabilities
        )
        expected_psnr_lcb = sum(
            probabilities[attacker] * psnr_lcbs[attacker]
            for attacker in probabilities
        )
        worst_psnr_lcb = min(psnr_lcbs.values())
        worst_ssim_lcb = min(ssim_lcbs.values())
        fidelity_score = _normalized_psnr(expected_psnr_lcb, config)
        score = (
            (1.0 - fidelity_weight) * survival
            + fidelity_weight * fidelity_score
        )
        violations: list[str] = []
        if worst_margin_lcb < minimum_margin:
            violations.append(
                "worst_case_protocol_normalized_margin_cluster_lcb_below_floor"
            )
        if worst_success_lcb < minimum_success_lcb:
            violations.append(
                "worst_case_protocol_success_rate_cluster_lcb_below_floor"
            )
        if worst_psnr_lcb < minimum_post_psnr_lcb:
            violations.append("worst_case_post_attack_psnr_cluster_lcb_below_floor")
        if worst_ssim_lcb < minimum_post_ssim_lcb:
            violations.append("worst_case_post_attack_ssim_cluster_lcb_below_floor")
        first_attacker = next(iter(probabilities))
        rows.append({
            "model": model,
            "feasible": not violations,
            "constraint_violations": violations,
            "score": _rounded(score),
            "expected_source_bit_accuracy_diagnostic": _rounded(sum(
                probabilities[attacker]
                * _cluster_point_metric(
                    cluster_input,
                    model,
                    attacker,
                    "source_bit_accuracy_diagnostic",
                )
                for attacker in probabilities
            )),
            "worst_case_source_bit_accuracy_diagnostic": _rounded(min(
                _cluster_point_metric(
                    cluster_input,
                    model,
                    attacker,
                    "source_bit_accuracy_diagnostic",
                )
                for attacker in probabilities
            )),
            "expected_source_protocol_normalized_margin": _rounded(
                expected_margin
            ),
            "worst_case_source_protocol_normalized_margin": _rounded(
                worst_margin
            ),
            "expected_source_protocol_normalized_margin_cluster_lcb": _rounded(
                expected_margin_lcb
            ),
            "worst_case_source_protocol_normalized_margin_cluster_lcb": _rounded(
                worst_margin_lcb
            ),
            "worst_case_source_protocol_success_rate_cluster_lcb": _rounded(
                worst_success_lcb
            ),
            "risk_adjusted_survival_cluster_lcb": _rounded(survival),
            "initial_embedding_psnr_db": _rounded(_cluster_point_metric(
                cluster_input,
                model,
                first_attacker,
                "first_embedding_psnr",
            )),
            "expected_post_attack_psnr_db": _rounded(expected_psnr),
            "expected_post_attack_psnr_cluster_lcb_db": _rounded(
                expected_psnr_lcb
            ),
            "worst_case_post_attack_psnr_cluster_lcb_db": _rounded(
                worst_psnr_lcb
            ),
            "worst_case_post_attack_ssim_cluster_lcb": _rounded(
                worst_ssim_lcb
            ),
            "fidelity_score": _rounded(fidelity_score),
        })

    pareto_dimensions = (
        "expected_source_protocol_normalized_margin_cluster_lcb",
        "worst_case_source_protocol_success_rate_cluster_lcb",
        "fidelity_score",
    )
    feasible_rows = [row for row in rows if row["feasible"]]
    frontier = _pareto_frontier(feasible_rows, pareto_dimensions)
    for row in rows:
        row["pareto_optimal"] = row["model"] in frontier
    order = {model: index for index, model in enumerate(MODEL_NAMES)}
    rows.sort(key=lambda row: (
        not bool(row["feasible"]),
        not bool(row["pareto_optimal"]),
        -float(row["score"]),
        order[str(row["model"])],
    ))
    eligible = [row for row in rows if row["feasible"] and row["pareto_optimal"]]
    selected = eligible[0] if eligible else None

    interactions: list[dict[str, Any]] = []
    low_risk_models: list[str] = []
    if selected is not None:
        selected_model = str(selected["model"])
        for attacker in MODEL_NAMES:
            cell_stats = statistics[selected_model][attacker]
            source_margin = cell_stats["source_protocol_normalized_margin"]
            attacker_margin = cell_stats["attacker_protocol_normalized_margin"]
            source_success = cell_stats["source_protocol_success"]
            attacker_success = cell_stats["attacker_protocol_success"]
            source_survives = (
                source_margin["lcb"] >= 0.5
                and source_success["lcb"] >= minimum_success_lcb
            )
            attacker_survives = (
                attacker_margin["lcb"] >= 0.5
                and attacker_success["lcb"] >= minimum_success_lcb
            )
            if source_survives and attacker_survives:
                interaction_class = "coexistence"
                policy_hint = "planned_dual_provenance_before_allow"
                low_risk_models.append(attacker)
            elif source_survives:
                interaction_class = "source_dominant"
                policy_hint = "planned_reject_unverifiable_second_embedding"
            elif attacker_survives:
                interaction_class = "source_overwritten"
                policy_hint = "planned_block_or_isolate_second_embedding"
            else:
                interaction_class = "destructive_collision"
                policy_hint = "planned_block_second_embedding"
            interactions.append({
                "source_model": selected_model,
                "attacker_model": attacker,
                "threat_probability": _rounded(probabilities.get(attacker, 0.0)),
                "class": interaction_class,
                "policy_hint": policy_hint,
                "source_bit_accuracy_diagnostic": _rounded(
                    _cluster_point_metric(
                        cluster_input,
                        selected_model,
                        attacker,
                        "source_bit_accuracy_diagnostic",
                    )
                ),
                "source_protocol_normalized_margin": _rounded(
                    source_margin["estimate"]
                ),
                "source_protocol_normalized_margin_cluster_lcb": _rounded(
                    source_margin["lcb"]
                ),
                "attacker_bit_accuracy_diagnostic": _rounded(
                    _cluster_point_metric(
                        cluster_input,
                        selected_model,
                        attacker,
                        "attacker_bit_accuracy_diagnostic",
                    )
                ),
                "attacker_protocol_normalized_margin": _rounded(
                    attacker_margin["estimate"]
                ),
                "attacker_protocol_normalized_margin_cluster_lcb": _rounded(
                    attacker_margin["lcb"]
                ),
                "source_protocol_success_rate": _rounded(source_success["estimate"]),
                "source_protocol_success_rate_cluster_lcb": _rounded(
                    source_success["lcb"]
                ),
                "attacker_protocol_success_rate": _rounded(
                    attacker_success["estimate"]
                ),
                "attacker_protocol_success_rate_cluster_lcb": _rounded(
                    attacker_success["lcb"]
                ),
                "second_vs_original_psnr_db": _rounded(
                    cell_stats["second_vs_original_psnr"]["estimate"]
                ),
            })
        recommendation: dict[str, Any] | None = {
            **selected,
            "low_risk_interaction_models": low_risk_models,
            "rationale_codes": [
                "highest_feasible_confidence_adjusted_score",
                "content_addressed_mea_evidence",
                "feasible_domain_pareto_frontier",
                "identity_cluster_bootstrap_simultaneous_bounds",
                "protocol_normalized_cross_model_estimand",
            ],
        }
        status = "recommendation_ready"
    else:
        recommendation = None
        status = "constraint_unsatisfied"

    stability = _selection_stability(bootstrap, normalized, config)
    legacy = _legacy_iid_reference_selection(summary, normalized, config)
    selected_model = recommendation["model"] if recommendation else None
    stability["selected_model_frequency"] = _rounded(
        stability["selection_frequency"].get(selected_model or "none", 0.0)
    )
    return {
        "schema_version": RESPONSE_SCHEMA,
        "policy_id": config["policy_id"],
        "status": status,
        "recommendation": recommendation,
        "ranking": rows,
        "interaction_plan": interactions,
        "request": {
            "threat_probabilities": {
                model: _rounded(probability)
                for model, probability in probabilities.items()
            },
            "candidate_models": normalized["candidate_models"],
            "risk_aversion": _rounded(risk_aversion),
            "fidelity_weight": _rounded(fidelity_weight),
            "minimum_worst_case_protocol_normalized_margin": _rounded(
                minimum_margin
            ),
        },
        "scoring": {
            "confidence_level": _rounded(
                config["uncertainty"]["confidence_level"]
            ),
            "uncertainty_method": config["uncertainty"]["method"],
            "cluster_key": config["uncertainty"]["cluster_key"],
            "estimand": config["uncertainty"]["estimand"],
            "normalized_margin_transform": config["uncertainty"][
                "normalized_margin_transform"
            ],
            "raw_bit_accuracy_use": "diagnostic_only_not_cross_model_ranked",
            "bootstrap_rng": config["uncertainty"]["rng"],
            "bootstrap_seed": config["uncertainty"]["seed"],
            "bootstrap_resamples": config["uncertainty"]["resamples"],
            "bootstrap_quantile_method": config["uncertainty"]["quantile_method"],
            "multiplicity_adjustment": config["uncertainty"][
                "multiplicity_adjustment"
            ],
            "family_scope": "all_4_candidates_x_all_4_attackers_x_6_metrics_including_post_selection",
            "family_metrics": list(CLUSTER_METRICS),
            "family_size": config["uncertainty"]["family_size"],
            "per_comparison_alpha": _rounded(
                bootstrap["per_comparison_alpha"]
            ),
            "image_count": cluster_input["image_count"],
            "identity_count": cluster_input["identity_count"],
            "repeated_identity_count": cluster_input["repeated_identity_count"],
            "images_in_repeated_identities": cluster_input[
                "images_in_repeated_identities"
            ],
            "max_cluster_size": cluster_input["max_cluster_size"],
            "model_semantics": config["model_semantics"],
            "survival_formula": "(1-risk_aversion)*expected_normalized_margin_cluster_lcb+risk_aversion*worst_normalized_margin_cluster_lcb",
            "fidelity_formula": "normalize(expected_post_attack_psnr_cluster_lcb)",
            "overall_formula": "(1-fidelity_weight)*survival+fidelity_weight*fidelity",
            "pareto_scope": "hard_constraint_feasible_candidates_only",
            "pareto_dimensions": list(pareto_dimensions),
            "ranking_order": [
                "feasible_first",
                "pareto_optimal_first",
                "score_descending",
                "fixed_model_order",
            ],
            "tie_break_model_order": list(MODEL_NAMES),
            "hard_constraints": {
                "minimum_worst_case_protocol_normalized_margin_cluster_lcb": _rounded(
                    minimum_margin
                ),
                "minimum_worst_case_source_protocol_success_rate_cluster_lcb": _rounded(
                    minimum_success_lcb
                ),
                "minimum_worst_case_post_attack_psnr_cluster_lcb_db": _rounded(
                    minimum_post_psnr_lcb
                ),
                "minimum_worst_case_post_attack_ssim_cluster_lcb": _rounded(
                    minimum_post_ssim_lcb
                ),
            },
            "selection_stability": stability,
        },
        "ablation": {
            "legacy_iid_raw_accuracy": legacy,
            "identity_cluster_normalized_policy_selected_model": selected_model,
            "selection_changed": legacy["selected_model"] != selected_model,
        },
        "evidence": dict(evidence or {}),
    }


def recommend_collaboration(request: Mapping[str, Any]) -> dict[str, Any]:
    config, summary, evidence, cluster_input = load_policy_evidence()
    _require(
        evidence.get("content_verified") is True
        and evidence.get("signature_verified") is True
        and evidence.get("signer_pinned") is True,
        "deployment recommendation requires signed, pinned evidence",
    )
    return build_recommendation(
        summary,
        request,
        config,
        cluster_input=cluster_input,
        evidence=evidence,
    )
