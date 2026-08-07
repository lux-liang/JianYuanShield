"""Deterministic geometry search for creator-bound registered-message checks.

Using a message retrieved from a pre-existing registration is operational
template matching, not hidden evaluation-label access. Supplying an experiment's
unregistered ground-truth message would be leakage and is explicitly outside
this interface's permitted use. Because the maximum of several candidate scores
has a higher null tail than a single decode, no score from this prototype is a
formal verification claim until the exact search is recalibrated on unwatermarked,
wrong-message, and cross-record-watermarked negative controls.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


SCHEMA_VERSION = "registered-message-synchronization.prototype.v1"
REQUIRED_FAR_NEGATIVE_CONTROLS = (
    "unwatermarked",
    "wrong_message",
    "cross_record_watermarked",
)


@dataclass(frozen=True)
class SynchronizationCandidate:
    """One deterministic geometry hypothesis in declared tie-break order."""

    id: str
    operation: str
    value: float | None = None


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    decoded_bits: tuple[int, ...]
    bit_errors: int
    bit_accuracy: float


@dataclass(frozen=True)
class RegisteredMessageSearchResult:
    schema_version: str
    selected_candidate_id: str
    selected_decoded_bits: tuple[int, ...]
    selected_bit_errors: int
    selected_bit_accuracy: float
    candidate_scores: tuple[CandidateScore, ...]
    candidate_contract_sha256: str
    selection_rule: str
    tie_breaker: str
    search_space_size: int
    multiple_hypothesis_search: bool
    selection_uses_registered_message: bool
    registered_message_source_requirement: str
    benchmark_ground_truth_selection_permitted: bool
    far_calibration_required: bool
    far_calibration_reason: str
    required_far_negative_controls: tuple[str, ...]
    formal_claim_eligible: bool


DEFAULT_CANDIDATES = (
    SynchronizationCandidate("identity", "identity"),
    SynchronizationCandidate(
        "inverse_rotate_for_plus_5",
        "rotate",
        -5.0,
    ),
    SynchronizationCandidate(
        "inverse_rotate_for_minus_5",
        "rotate",
        5.0,
    ),
    SynchronizationCandidate(
        "inverse_crop_center_0.8_approx",
        "inverse_center_crop_approx",
        0.8,
    ),
)


def _image(value: Any) -> np.ndarray:
    image = np.asarray(value)
    if image.dtype != np.uint8:
        raise ValueError(f"synchronization image must be uint8, got {image.dtype}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(
            f"synchronization image must be HxWx3 RGB, got {image.shape}"
        )
    if min(image.shape[:2]) < 2:
        raise ValueError("synchronization image sides must be at least two pixels")
    return np.ascontiguousarray(image)


def _bits(value: Any, *, role: str) -> np.ndarray:
    if hasattr(value, "bits"):
        value = value.bits
    elif isinstance(value, Mapping) and "bits" in value:
        value = value["bits"]
    bits = np.asarray(value).reshape(-1)
    if bits.size == 0:
        raise ValueError(f"{role} must not be empty")
    if not np.isin(bits, (0, 1)).all():
        raise ValueError(f"{role} must contain only binary decisions")
    return bits.astype(np.uint8, copy=False)


def _validate_candidates(
    candidates: Sequence[SynchronizationCandidate],
) -> tuple[SynchronizationCandidate, ...]:
    selected = tuple(candidates)
    if not selected:
        raise ValueError("at least one synchronization candidate is required")
    identifiers = [candidate.id for candidate in selected]
    if any(not identifier for identifier in identifiers):
        raise ValueError("synchronization candidate IDs must not be empty")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("synchronization candidate IDs must be unique")
    for candidate in selected:
        if candidate.operation == "identity":
            if candidate.value is not None:
                raise ValueError("identity candidate must not have a value")
        elif candidate.operation == "rotate":
            if candidate.value is None or not math.isfinite(candidate.value):
                raise ValueError("rotation candidate requires finite degrees")
        elif candidate.operation == "inverse_center_crop_approx":
            if (
                candidate.value is None
                or not math.isfinite(candidate.value)
                or not 0.0 < candidate.value < 1.0
            ):
                raise ValueError("inverse-crop candidate requires a ratio in (0,1)")
        else:
            raise ValueError(
                f"unsupported synchronization operation: {candidate.operation}"
            )
    return selected


def candidate_contract(
    candidates: Sequence[SynchronizationCandidate] = DEFAULT_CANDIDATES,
) -> dict[str, Any]:
    """Describe the exact multiple-hypothesis search that FAR must calibrate."""

    selected = _validate_candidates(candidates)
    entries: list[dict[str, Any]] = []
    for candidate in selected:
        entry: dict[str, Any] = {
            "id": candidate.id,
            "operation": candidate.operation,
        }
        if candidate.operation == "rotate":
            entry["parameters"] = {
                "correction_degrees": candidate.value,
                "interpolation": "opencv_linear",
                "border_mode": "reflect_101",
            }
        elif candidate.operation == "inverse_center_crop_approx":
            entry["parameters"] = {
                "retained_ratio": candidate.value,
                "resize_interpolation": "opencv_area",
                "missing_border_approximation": "edge_pad",
            }
        else:
            entry["parameters"] = {}
        entries.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "selection_rule": "maximum_registered_message_bit_accuracy",
        "tie_breaker": "first_in_declared_candidate_order",
        "candidates": entries,
    }


def candidate_contract_sha256(
    candidates: Sequence[SynchronizationCandidate] = DEFAULT_CANDIDATES,
) -> str:
    payload = json.dumps(
        candidate_contract(candidates),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def apply_synchronization_candidate(
    image: np.ndarray,
    candidate: SynchronizationCandidate,
) -> np.ndarray:
    """Apply one fixed-size inverse-geometry hypothesis without mutating input."""

    source = _image(image)
    _validate_candidates((candidate,))
    height, width = source.shape[:2]
    if candidate.operation == "identity":
        output = source.copy()
    elif candidate.operation == "rotate":
        matrix = cv2.getRotationMatrix2D(
            (width / 2.0, height / 2.0),
            float(candidate.value),
            1.0,
        )
        output = cv2.warpAffine(
            source,
            matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )
    elif candidate.operation == "inverse_center_crop_approx":
        ratio = float(candidate.value)
        inner_height = max(1, round(height * ratio))
        inner_width = max(1, round(width * ratio))
        inner = cv2.resize(
            source,
            (inner_width, inner_height),
            interpolation=cv2.INTER_AREA,
        )
        top = (height - inner_height) // 2
        bottom = height - inner_height - top
        left = (width - inner_width) // 2
        right = width - inner_width - left
        output = np.pad(
            inner,
            ((top, bottom), (left, right), (0, 0)),
            mode="edge",
        )
    else:  # pragma: no cover - candidate validation owns this branch.
        raise AssertionError(candidate.operation)
    output = np.ascontiguousarray(output)
    if output.dtype != np.uint8 or output.shape != source.shape:
        raise RuntimeError("synchronization candidate violated image contract")
    return output


def registered_message_bit_accuracy(
    decoded_bits: Any,
    registered_message: Any,
) -> float:
    decoded = _bits(decoded_bits, role="decoded bits")
    registered = _bits(registered_message, role="registered message")
    if decoded.shape != registered.shape:
        raise ValueError(
            "decoded bits and registered message must have identical lengths"
        )
    return float(np.mean(decoded == registered))


def search_registered_message_alignment(
    image: np.ndarray,
    *,
    registered_message: Any,
    decode_bits: Callable[[np.ndarray], Any],
    candidates: Sequence[SynchronizationCandidate] = DEFAULT_CANDIDATES,
) -> RegisteredMessageSearchResult:
    """Select geometry using a message retrieved from an existing registration.

    The registered message is an operational verification template, not hidden
    benchmark ground truth. This prototype deliberately returns no pass/fail
    decision: maximizing over several candidates changes the null distribution,
    so the exact candidate contract must first be calibrated and held out with
    all controls in ``REQUIRED_FAR_NEGATIVE_CONTROLS``.

    KAD/SepMark adapters can call this pure interface directly, for example
    ``decode_bits=lambda candidate: adapter.decode(candidate).bits``. A dual
    decoder caller must explicitly select the protocol-registered decoder in its
    lambda rather than selecting whichever decoder scores highest.
    """

    source = _image(image)
    registered = _bits(registered_message, role="registered message")
    selected_candidates = _validate_candidates(candidates)
    scores: list[CandidateScore] = []
    for candidate in selected_candidates:
        aligned = apply_synchronization_candidate(source, candidate)
        try:
            decoded = _bits(
                decode_bits(aligned.copy()),
                role=f"decoded bits for {candidate.id}",
            )
        except Exception as exc:
            raise RuntimeError(
                f"decoder failed for synchronization candidate {candidate.id}"
            ) from exc
        if decoded.shape != registered.shape:
            raise ValueError(
                f"decoder length mismatch for synchronization candidate {candidate.id}"
            )
        bit_errors = int(np.count_nonzero(decoded != registered))
        scores.append(CandidateScore(
            candidate_id=candidate.id,
            decoded_bits=tuple(int(bit) for bit in decoded),
            bit_errors=bit_errors,
            bit_accuracy=(registered.size - bit_errors) / registered.size,
        ))

    best_index = max(
        range(len(scores)),
        key=lambda index: scores[index].bit_accuracy,
    )
    best = scores[best_index]
    return RegisteredMessageSearchResult(
        schema_version=SCHEMA_VERSION,
        selected_candidate_id=best.candidate_id,
        selected_decoded_bits=best.decoded_bits,
        selected_bit_errors=best.bit_errors,
        selected_bit_accuracy=best.bit_accuracy,
        candidate_scores=tuple(scores),
        candidate_contract_sha256=candidate_contract_sha256(selected_candidates),
        selection_rule="maximum_registered_message_bit_accuracy",
        tie_breaker="first_in_declared_candidate_order",
        search_space_size=len(scores),
        multiple_hypothesis_search=True,
        selection_uses_registered_message=True,
        registered_message_source_requirement="pre_existing_registration_record_only",
        benchmark_ground_truth_selection_permitted=False,
        far_calibration_required=True,
        far_calibration_reason=(
            "maximum_over_candidates_expands_the_null_score_distribution; "
            "calibrate_the_exact_candidate_contract_per_model_checkpoint_domain_and_attack"
        ),
        required_far_negative_controls=REQUIRED_FAR_NEGATIVE_CONTROLS,
        formal_claim_eligible=False,
    )
