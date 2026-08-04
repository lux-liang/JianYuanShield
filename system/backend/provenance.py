from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import math
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from system.evaluation.protocol import load_protocol
from system.evaluation.identity import IDENTITY_DERIVATION, calibration_identity_sha256
from system.evaluation.runtime import logical_path

from .config import ASSETS, MANIFEST, REPORTS
from . import audit_ledger
from .aigc_labeling import (
    AIGC_LABELS,
    apply_aigc_labels,
    build_aigc_fields,
    inspect_aigc_png,
)
from .creator_identity import (
    CreatorIdentityError,
    consume_challenge,
    ensure_schema as ensure_creator_identity_schema,
    issue_challenge,
    verify_creator_proof,
)
from .settings import settings
from .signing import (
    MANIFEST_PATH as EVIDENCE_MANIFEST_PATH,
    canonical_json,
    sha256_file,
    sign_payload,
    signature_public_key_fingerprint,
    verify_evidence_bundle,
    verify_payload_signature,
)
from .utils import atomic_write_bytes, atomic_write_json


_DB_LOCK = threading.Lock()


class ProvenanceCapabilityError(RuntimeError):
    pass


def _database_path() -> Path:
    if not settings.provenance_db:
        return REPORTS / "provenance.sqlite3"
    configured = Path(settings.provenance_db).expanduser()
    return configured if configured.is_absolute() else REPORTS / configured


def _connect() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS provenance_records (
            content_id TEXT PRIMARY KEY,
            creator_ref TEXT NOT NULL,
            model TEXT NOT NULL,
            message_bits TEXT NOT NULL,
            original_sha256 TEXT NOT NULL,
            protected_sha256 TEXT NOT NULL,
            checkpoint TEXT,
            checkpoint_sha256 TEXT,
            created_at INTEGER NOT NULL,
            record_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS verification_events (
            event_id TEXT PRIMARY KEY,
            content_id TEXT NOT NULL,
            observed_sha256 TEXT NOT NULL,
            bit_accuracy REAL NOT NULL,
            verified INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            FOREIGN KEY(content_id) REFERENCES provenance_records(content_id)
        );
        CREATE TABLE IF NOT EXISTS revocation_intents (
            intent_id TEXT PRIMARY KEY,
            content_id TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            nonce_base64 TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            used_at INTEGER,
            intent_json TEXT NOT NULL,
            FOREIGN KEY(content_id) REFERENCES provenance_records(content_id)
        );
        CREATE TABLE IF NOT EXISTS provenance_revocations (
            content_id TEXT PRIMARY KEY,
            revocation_id TEXT NOT NULL UNIQUE,
            reason_code TEXT NOT NULL,
            revoked_at INTEGER NOT NULL,
            revocation_json TEXT NOT NULL,
            FOREIGN KEY(content_id) REFERENCES provenance_records(content_id)
        );
        """
    )
    ensure_creator_identity_schema(connection)
    audit_ledger.ensure_schema(connection)
    return connection


@contextmanager
def _database():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _audit_anchor_path() -> Path:
    configured = getattr(settings, "audit_anchor", None)
    if configured:
        candidate = Path(str(configured)).expanduser()
        return candidate if candidate.is_absolute() else REPORTS / candidate
    return _database_path().with_name("provenance-audit-anchor.json")


def _prepare_audit_ledger(connection: sqlite3.Connection) -> dict[str, Any]:
    status = audit_ledger.initialize_anchor(
        connection,
        path=_audit_anchor_path(),
    )
    if status.get("rollback_detected") or not status.get("structural_valid"):
        raise ProvenanceCapabilityError(
            f"provenance audit ledger rejected: {status.get('status')}"
        )
    if settings.mode.strip().lower() == "production" and not status.get("trusted"):
        raise ProvenanceCapabilityError(
            f"production provenance audit anchor is not trusted: {status.get('status')}"
        )
    return status


def _synchronize_audit_ledger() -> dict[str, Any]:
    with _DB_LOCK, _database() as connection:
        status = audit_ledger.verify_anchor(
            connection,
            path=_audit_anchor_path(),
        )
        if status.get("database_ahead_recoverable"):
            return audit_ledger.synchronize_anchor(
                connection,
                path=_audit_anchor_path(),
            )
        if settings.mode.strip().lower() == "production" and not status.get("trusted"):
            raise ProvenanceCapabilityError(
                f"production provenance audit anchor is not trusted: {status.get('status')}"
            )
        return status


def provenance_audit_status() -> dict[str, Any]:
    with _DB_LOCK, _database() as connection:
        return audit_ledger.verify_anchor(connection, path=_audit_anchor_path())


def create_creator_challenge(
    *,
    creator_public_key_pem: str,
    creator_ref: str,
    model: str,
    image_sha256: str,
) -> dict[str, Any]:
    with _DB_LOCK, _database() as connection:
        _prepare_audit_ledger(connection)
        return issue_challenge(
            connection,
            creator_public_key_pem=creator_public_key_pem,
            creator_ref=creator_ref,
            model=model,
            image_sha256=image_sha256,
        )


def _adapter_checkpoint_identity(adapter: Any) -> tuple[str | None, str | None]:
    checkpoint = adapter.checkpoint
    if not checkpoint:
        return None, None
    checkpoint_path = Path(str(checkpoint)).expanduser()
    if not checkpoint_path.is_file():
        return str(checkpoint), None
    return str(checkpoint), sha256_file(checkpoint_path)


def _rgb(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > settings.max_image_pixels:
            raise ValueError("decoded image exceeds configured pixel limit")
        return np.array(ImageOps.exif_transpose(image).convert("RGB"))


def _png_bytes(image: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(image.astype(np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def _validate_creator_ref(creator_ref: str) -> str:
    value = creator_ref.strip()
    if not value or len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ValueError("creator_ref must be 1-128 printable characters")
    return value


def _get_adapter(model: str):
    from system.evaluation.adapters import get_available_adapters

    adapters = get_available_adapters()
    adapter_type = adapters.get(model)
    if adapter_type is None:
        raise ProvenanceCapabilityError(f"model adapter unavailable: {model}")
    try:
        adapter = adapter_type()
    except Exception as exc:
        raise ProvenanceCapabilityError(f"model adapter failed to initialize: {model}") from exc
    if not adapter.available:
        raise ProvenanceCapabilityError(f"model adapter unavailable: {model}: {adapter.blocker}")
    return adapter


def _signature(payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.evidence_private_key:
        return {
            "status": "not_configured",
            "signed": False,
            "warning": "JYS_EVIDENCE_PRIVATE_KEY is not configured",
        }
    key_path = Path(settings.evidence_private_key).expanduser()
    if not key_path.is_file():
        return {
            "status": "key_missing",
            "signed": False,
            "warning": "configured evidence private key does not exist",
        }
    return {"status": "signed", "signed": True, **sign_payload(payload, key_path)}


def _checkpoint_entry(model: str, checkpoint_sha256: str | None) -> dict[str, Any] | None:
    if not checkpoint_sha256 or not MANIFEST.is_file():
        return None
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        item_model = str(item.get("model") or item.get("project") or "")
        item_hash = str(item.get("sha256") or item.get("checkpoint_sha256") or "")
        status = str(item.get("status") or "").lower()
        if (
            item_model.lower() == model.lower()
            and item_hash.lower() == checkpoint_sha256.lower()
            and status in {"approved", "verified"}
        ):
            return item
    return None


def _manifest_entry_path(entry: dict[str, Any], field: str) -> Path | None:
    value = entry.get(field)
    if not isinstance(value, str) or not value:
        return None
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    candidate = (MANIFEST.parent / raw).resolve()
    try:
        candidate.relative_to(MANIFEST.parent.resolve())
    except ValueError:
        return None
    return candidate


def _checkpoint_file_bound(entry: dict[str, Any]) -> bool:
    checkpoint = _manifest_entry_path(entry, "file")
    expected = str(entry.get("sha256") or entry.get("checkpoint_sha256") or "").lower()
    return bool(
        checkpoint
        and checkpoint.is_file()
        and _is_sha256(expected)
        and hmac.compare_digest(sha256_file(checkpoint), expected)
    )


def _checkpoint_registered(model: str, checkpoint_sha256: str | None) -> bool:
    entry = _checkpoint_entry(model, checkpoint_sha256)
    return entry is not None and _checkpoint_file_bound(entry)


def _weight_manifest_trusted(model: str, checkpoint_sha256: str | None) -> bool:
    """Require manifest, active checkpoint and calibration in the pinned bundle."""

    if not MANIFEST.is_file():
        return False
    entry = _checkpoint_entry(model, checkpoint_sha256)
    if entry is None or not _checkpoint_file_bound(entry):
        return False
    checkpoint = _manifest_entry_path(entry, "file")
    calibration = _manifest_entry_path(entry, "calibration_artifact")
    if checkpoint is None or calibration is None or not calibration.is_file():
        return False
    signature = verify_evidence_bundle()
    configured_fingerprint = (settings.evidence_public_key_fingerprint or "").strip().lower()
    actual_fingerprint = str(signature.get("public_key_fingerprint_sha256") or "").lower()
    if (
        signature.get("verified") is not True
        or not _is_sha256(configured_fingerprint)
        or not _is_sha256(actual_fingerprint)
        or not hmac.compare_digest(configured_fingerprint, actual_fingerprint)
    ):
        return False
    try:
        evidence_manifest = json.loads(EVIDENCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    covered = {
        (item.get("path"), item.get("size_bytes"), item.get("sha256"))
        for item in evidence_manifest.get("files", [])
        if isinstance(item, dict)
    }
    required = {
        (logical_path(path), path.stat().st_size, sha256_file(path))
        for path in (MANIFEST, checkpoint, calibration)
    }
    return required.issubset(covered)


_CALIBRATION_CONTROLS = ("registered_roundtrip", "unwatermarked", "wrong_message")
_NEGATIVE_CALIBRATION_CONTROLS = ("unwatermarked", "wrong_message")
_WILSON_Z_95 = 1.959963984540054


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _wilson_interval(successes: int, total: int) -> dict[str, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("invalid Wilson interval inputs")
    proportion = successes / total
    z2 = _WILSON_Z_95 * _WILSON_Z_95
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    margin = (
        _WILSON_Z_95
        * math.sqrt(proportion * (1.0 - proportion) / total + z2 / (4.0 * total * total))
        / denominator
    )
    return {
        "confidence_level": 0.95,
        "lower": 0.0 if successes == 0 else max(0.0, center - margin),
        "upper": 1.0 if successes == total else min(1.0, center + margin),
    }


def _calibration_metrics(
    samples: list[dict[str, Any]],
    threshold: float,
    split: str,
) -> dict[str, Any]:
    selected = [sample for sample in samples if sample["split"] == split]
    positives = [sample for sample in selected if sample["label"] == "positive"]
    negatives = [sample for sample in selected if sample["label"] == "negative"]
    if not positives or not negatives:
        raise ValueError("both calibration labels are required")
    true_accepts = sum(sample["bit_accuracy"] >= threshold for sample in positives)
    false_accepts = sum(sample["bit_accuracy"] >= threshold for sample in negatives)
    false_rejects = len(positives) - true_accepts
    true_rejects = len(negatives) - false_accepts
    negative_control_metrics: dict[str, Any] = {}
    for control in _NEGATIVE_CALIBRATION_CONTROLS:
        controls = [sample for sample in negatives if sample["control"] == control]
        if not controls:
            raise ValueError("both negative controls are required")
        control_false_accepts = sum(sample["bit_accuracy"] >= threshold for sample in controls)
        negative_control_metrics[control] = {
            "samples": len(controls),
            "false_accepts": control_false_accepts,
            "false_accept_rate": control_false_accepts / len(controls),
            "false_accept_rate_wilson_95": _wilson_interval(control_false_accepts, len(controls)),
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
        "true_accept_rate_wilson_95": _wilson_interval(true_accepts, len(positives)),
        "false_accept_rate_wilson_95": _wilson_interval(false_accepts, len(negatives)),
        "false_reject_rate_wilson_95": _wilson_interval(false_rejects, len(positives)),
        "negative_control_metrics": negative_control_metrics,
    }


def _metrics_match(reported: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(reported, dict):
        return False
    for key, expected_value in expected.items():
        actual = reported.get(key)
        if isinstance(expected_value, dict):
            if not _metrics_match(actual, expected_value):
                return False
        elif isinstance(expected_value, float):
            try:
                actual_value = float(actual)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(actual_value) or abs(actual_value - expected_value) > 1e-12:
                return False
        elif actual != expected_value:
            return False
    return True


def _selected_calibration_threshold(
    samples: list[dict[str, Any]],
    target_far: float,
) -> tuple[float, dict[str, Any], int, int]:
    calibration = [sample for sample in samples if sample["split"] == "calibration"]
    candidates = {0.0, 1.0}
    for score in {sample["bit_accuracy"] for sample in calibration}:
        candidates.add(score)
        above = math.nextafter(score, math.inf)
        if above <= 1.0:
            candidates.add(above)
    eligible: list[tuple[float, dict[str, Any]]] = []
    for candidate in sorted(candidates):
        metrics = _calibration_metrics(samples, candidate, "calibration")
        if metrics["false_accept_rate"] <= target_far + 1e-15:
            eligible.append((candidate, metrics))
    if not eligible:
        raise ValueError("calibration has no eligible threshold")
    threshold, metrics = min(
        eligible,
        key=lambda item: (
            -float(item[1]["true_accept_rate"]),
            float(item[1]["false_accept_rate"]),
            float(item[0]),
        ),
    )
    return threshold, metrics, len(candidates), len(eligible)


def _checkpoint_calibrated(
    model: str,
    checkpoint_sha256: str | None,
    threshold: Any,
) -> bool:
    """Require a hash-verified positive/negative threshold calibration artifact."""
    entry = _checkpoint_entry(model, checkpoint_sha256)
    if entry is None:
        return False
    try:
        registered_threshold = float(entry["verification_threshold"])
        active_threshold = float(threshold)
        positive_samples = int(entry["calibration_positive_samples"])
        negative_samples = int(entry["calibration_negative_samples"])
        false_accept_rate = float(entry["calibration_false_accept_rate"])
    except (KeyError, TypeError, ValueError):
        return False
    artifact_name = entry.get("calibration_artifact")
    artifact_hash = str(entry.get("calibration_artifact_sha256") or "").lower()
    if (
        abs(registered_threshold - active_threshold) > 1e-12
        or positive_samples <= 0
        or negative_samples <= 0
        or not 0 <= false_accept_rate <= 1
        or not isinstance(artifact_name, str)
        or len(artifact_hash) != 64
        or any(char not in "0123456789abcdef" for char in artifact_hash)
    ):
        return False
    artifact = (MANIFEST.parent / artifact_name).resolve()
    try:
        artifact.relative_to(MANIFEST.parent.resolve())
    except ValueError:
        return False
    if not artifact.is_file() or not hmac.compare_digest(sha256_file(artifact), artifact_hash):
        return False
    try:
        calibration = json.loads(
            artifact.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, ValueError, TypeError):
        return False
    samples = calibration.get("samples") if isinstance(calibration, dict) else None
    if (
        calibration.get("schema_version") != "threshold-calibration.v1"
        or calibration.get("status") != "complete"
        or str(calibration.get("model") or "").lower() != model.lower()
        or str(calibration.get("checkpoint_sha256") or "").lower() != checkpoint_sha256.lower()
        or not isinstance(samples, list)
        or not samples
        or calibration.get("errors") != []
    ):
        return False
    try:
        artifact_threshold = float(calibration["threshold"])
        target_far = float(calibration["target_false_accept_rate"])
        seed = int(calibration["seed"])
    except (KeyError, TypeError, ValueError):
        return False
    if (
        not math.isfinite(artifact_threshold)
        or not 0 <= artifact_threshold <= 1
        or not math.isfinite(target_far)
        or not 0 <= target_far <= 1
        or abs(artifact_threshold - registered_threshold) > 1e-12
    ):
        return False

    attack_ids = calibration.get("attack_ids")
    dataset = calibration.get("dataset_manifest")
    if (
        not isinstance(attack_ids, list)
        or not attack_ids
        or len(attack_ids) != len(set(attack_ids))
        or not all(isinstance(attack_id, str) and attack_id for attack_id in attack_ids)
        or not isinstance(dataset, dict)
        or dataset.get("schema_version") != "threshold-calibration-dataset.v1"
        or dataset.get("identity_derivation") != IDENTITY_DERIVATION
        or calibration.get("dataset_manifest_sha256") != _canonical_sha256(dataset)
    ):
        return False
    files = dataset.get("files")
    if not isinstance(files, list) or not files or dataset.get("sample_count") != len(files):
        return False
    if dataset.get("files_digest_sha256") != _canonical_sha256(files):
        return False
    dataset_rows: dict[str, tuple[str, str]] = {}
    for item in files:
        if not isinstance(item, dict):
            return False
        image_id = item.get("image_id")
        identity = item.get("identity_sha256")
        split = item.get("split")
        if (
            not isinstance(image_id, str)
            or not image_id
            or image_id.startswith("/")
            or ".." in Path(image_id).parts
            or image_id in dataset_rows
            or not _is_sha256(identity)
            or identity != calibration_identity_sha256(image_id)
            or split not in {"calibration", "holdout"}
            or not _is_sha256(item.get("sha256"))
            or not isinstance(item.get("size_bytes"), int)
            or item["size_bytes"] <= 0
        ):
            return False
        dataset_rows[image_id] = (identity, split)
    if {split for _, split in dataset_rows.values()} != {"calibration", "holdout"}:
        return False

    normalized_samples: list[dict[str, Any]] = []
    seen_sample_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    identity_splits: dict[str, str] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            return False
        sample_id = sample.get("sample_id")
        image_id = sample.get("image_id")
        identity = sample.get("identity_sha256")
        split = sample.get("split")
        attack_id = sample.get("attack_id")
        control = sample.get("control")
        label = sample.get("label")
        try:
            score = float(sample["bit_accuracy"])
        except (KeyError, TypeError, ValueError):
            return False
        expected_label = "positive" if control == "registered_roundtrip" else "negative"
        key = (str(image_id or ""), str(attack_id or ""), str(control or ""))
        expected_sample_id = hashlib.sha256(
            (
                f"threshold-calibration.sample.v1\0{calibration['model']}\0{seed}\0"
                f"{image_id}\0{attack_id}\0{control}"
            ).encode("utf-8")
        ).hexdigest()
        if (
            not _is_sha256(sample_id)
            or sample_id != expected_sample_id
            or sample_id in seen_sample_ids
            or key in seen_keys
            or image_id not in dataset_rows
            or identity != dataset_rows[image_id][0]
            or split != dataset_rows[image_id][1]
            or attack_id not in attack_ids
            or not _is_sha256(sample.get("attack_config_sha256"))
            or control not in _CALIBRATION_CONTROLS
            or label != expected_label
            or not _is_sha256(sample.get("registered_message_sha256"))
            or (
                control == "unwatermarked"
                and sample.get("embedded_message_sha256") is not None
            )
            or (
                control != "unwatermarked"
                and not _is_sha256(sample.get("embedded_message_sha256"))
            )
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            return False
        if identity in identity_splits and identity_splits[identity] != split:
            return False
        identity_splits[identity] = split
        seen_sample_ids.add(sample_id)
        seen_keys.add(key)
        normalized_samples.append({**sample, "bit_accuracy": score})

    expected_keys = {
        (image_id, attack_id, control)
        for image_id in dataset_rows
        for attack_id in attack_ids
        for control in _CALIBRATION_CONTROLS
    }
    coverage = calibration.get("coverage")
    expected_counts: dict[str, int] = {}
    for image_id, (_identity, split) in dataset_rows.items():
        for _attack_id in attack_ids:
            for control in _CALIBRATION_CONTROLS:
                counter = f"{split}:{control}"
                expected_counts[counter] = expected_counts.get(counter, 0) + 1
    if (
        seen_keys != expected_keys
        or not isinstance(coverage, dict)
        or coverage.get("complete") is not True
        or coverage.get("expected_rows") != len(expected_keys)
        or coverage.get("actual_rows") != len(normalized_samples)
        or coverage.get("expected_by_split_control") != dict(sorted(expected_counts.items()))
        or coverage.get("actual_by_split_control") != dict(sorted(expected_counts.items()))
        or coverage.get("missing_sample_key_sha256") != []
        or coverage.get("unexpected_sample_key_sha256") != []
        or coverage.get("duplicate_sample_key_sha256") != []
    ):
        return False

    try:
        selected_threshold, selected_metrics, candidate_count, eligible_count = (
            _selected_calibration_threshold(normalized_samples, target_far)
        )
        calibration_metrics = _calibration_metrics(
            normalized_samples, artifact_threshold, "calibration",
        )
        holdout_metrics = _calibration_metrics(normalized_samples, artifact_threshold, "holdout")
    except (KeyError, TypeError, ValueError):
        return False
    selection = calibration.get("threshold_selection")
    selection_expected = {
        "split": "calibration",
        "objective": "maximize_tpr_subject_to_empirical_far_lte_target",
        "comparison_operator": ">=",
        "target_false_accept_rate": target_far,
        "candidate_generation": "zero_one_observed_scores_and_nextafter_above",
        "candidate_count": candidate_count,
        "eligible_candidate_count": eligible_count,
        "tie_breaker": "minimum_far_then_minimum_threshold",
        "selected_threshold": selected_threshold,
        "calibration_positive_samples": selected_metrics["positive_samples"],
        "calibration_negative_samples": selected_metrics["negative_samples"],
        "calibration_negative_controls": list(_NEGATIVE_CALIBRATION_CONTROLS),
        "selected_true_accept_rate": selected_metrics["true_accept_rate"],
        "selected_false_accept_rate": selected_metrics["false_accept_rate"],
        "selected_false_reject_rate": selected_metrics["false_reject_rate"],
    }
    return all((
        abs(selected_threshold - artifact_threshold) <= 1e-12,
        _metrics_match(selection, selection_expected),
        _metrics_match(calibration.get("calibration_metrics"), calibration_metrics),
        _metrics_match(calibration.get("metrics"), holdout_metrics),
        holdout_metrics["positive_samples"] == positive_samples,
        holdout_metrics["negative_samples"] == negative_samples,
        abs(holdout_metrics["false_accept_rate"] - false_accept_rate) <= 1e-12,
    ))


def _calibrated_verification_threshold(
    model: str,
    checkpoint_sha256: str | None,
) -> float | None:
    """Return the model-specific threshold only after full artifact validation."""

    entry = _checkpoint_entry(model, checkpoint_sha256)
    if entry is None or not _checkpoint_registered(model, checkpoint_sha256):
        return None
    try:
        threshold = float(entry["verification_threshold"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        return None
    return threshold if _checkpoint_calibrated(model, checkpoint_sha256, threshold) else None


def provenance_model_status(
    model: str,
    checkpoint_path: str | Path,
    checkpoint_sha256: str,
    *,
    available: bool,
    loaded: bool,
) -> dict[str, Any]:
    """Return the strict, read-only provenance readiness of one live adapter.

    ``available`` alone only proves that an adapter can see its expected
    checkpoint.  A source-protection claim additionally requires the exact
    checkpoint to be registered, its threshold calibration to be fully
    recomputable, and the weight manifest/calibration/checkpoint closure to be
    covered by a pinned evidence signature.  Keeping these booleans separate
    lets clients explain a disabled model without weakening the final gate.
    """

    expected_sha256 = str(checkpoint_sha256 or "").lower()
    checkpoint = Path(checkpoint_path).expanduser()
    checkpoint_matches = False
    if _is_sha256(expected_sha256):
        try:
            before = checkpoint.stat()
            actual_sha256 = sha256_file(checkpoint)
            after = checkpoint.stat()
            stable_identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            checkpoint_matches = stable_identity and hmac.compare_digest(
                actual_sha256,
                expected_sha256,
            )
        except OSError:
            checkpoint_matches = False

    checkpoint_available = available is True and checkpoint_matches
    registered = checkpoint_available and _checkpoint_registered(
        model,
        expected_sha256,
    )
    threshold = (
        _calibrated_verification_threshold(model, expected_sha256)
        if registered
        else None
    )
    calibrated = threshold is not None
    trusted = calibrated and _weight_manifest_trusted(model, expected_sha256)
    provenance_ready = checkpoint_available and registered and calibrated and trusted

    reason_codes: list[str] = []
    if not checkpoint_available:
        reason_codes.append("checkpoint_unavailable_or_hash_mismatch")
    if not registered:
        reason_codes.append("checkpoint_unregistered")
    if not calibrated:
        reason_codes.append("calibration_unverified")
    if not trusted:
        reason_codes.append("weight_manifest_untrusted")

    return {
        "available": checkpoint_available,
        "loaded": loaded is True,
        "checkpoint_sha256": expected_sha256 if _is_sha256(expected_sha256) else None,
        "registered": registered,
        "calibrated": calibrated,
        "trusted": trusted,
        "provenance_ready": provenance_ready,
        "verification_threshold": threshold,
        "reason_codes": reason_codes,
    }


def _provenance_secret_ready() -> bool:
    return bool(settings.provenance_secret and len(settings.provenance_secret) >= 32)


def _message_for_record(content_id: str, model: str, length: int) -> tuple[np.ndarray, str]:
    if not _provenance_secret_ready():
        return (
            np.fromiter(
                (secrets.randbelow(2) for _ in range(length)),
                dtype=np.uint8,
                count=length,
            ),
            "stored-random-v1",
        )
    key = settings.provenance_secret.encode("utf-8")
    material = bytearray()
    counter = 0
    while len(material) * 8 < length:
        material.extend(
            hmac.new(
                key,
                f"jianyuanshield:{content_id}:{model}:{counter}".encode("utf-8"),
                hashlib.sha256,
            ).digest()
        )
        counter += 1
    return np.unpackbits(np.frombuffer(bytes(material), dtype=np.uint8))[:length], "hmac-sha256-v1"


def _claim_valid(payload: dict[str, Any], signature: dict[str, Any]) -> bool:
    """Fail closed unless model, payload and a pinned signer are all bound."""
    model = str(payload.get("model") or "")
    checkpoint_sha256 = payload.get("checkpoint_sha256")
    verification_threshold = payload.get("verification_threshold", payload.get("success_threshold"))
    checkpoint_bound = (
        isinstance(checkpoint_sha256, str)
        and len(checkpoint_sha256) == 64
        and all(char in "0123456789abcdef" for char in checkpoint_sha256.lower())
    )
    trusted_fingerprint = (settings.evidence_public_key_fingerprint or "").strip().lower()
    actual_fingerprint = signature_public_key_fingerprint(signature)
    signer_bound = (
        len(trusted_fingerprint) == 64
        and actual_fingerprint is not None
        and hmac.compare_digest(trusted_fingerprint, actual_fingerprint.lower())
    )
    return (
        checkpoint_bound
        and _checkpoint_registered(model, checkpoint_sha256)
        and _checkpoint_calibrated(model, checkpoint_sha256, verification_threshold)
        and _weight_manifest_trusted(model, checkpoint_sha256)
        and _provenance_secret_ready()
        and signature.get("signed") is True
        and verify_payload_signature(payload, signature)
        and signer_bound
    )


def _creator_identity_valid(payload: dict[str, Any]) -> bool:
    proof = payload.get("creator_identity")
    return bool(
        verify_creator_proof(proof)
        and proof.get("key_possession_verified") is True
        and proof.get("challenge", {}).get("creator_ref") == payload.get("creator_ref")
        and proof.get("challenge", {}).get("model") == payload.get("model")
        and proof.get("challenge", {}).get("image_sha256")
        == payload.get("original_sha256")
    )


def _record_claim_valid(payload: dict[str, Any], signature: dict[str, Any]) -> bool:
    if payload.get("schema_version") != "provenance-record.v2":
        return False
    if not _creator_identity_valid(payload):
        return False
    labeling = payload.get("aigc_labeling")
    if labeling is not None and (
        not isinstance(labeling, dict)
        or labeling.get("standard") != "GB 45438-2025"
        or labeling.get("metadata", {}).get("ProduceID") != payload.get("content_id")
        or labeling.get("metadata", {}).get("PropagateID") != payload.get("content_id")
        or labeling.get("producer_seal_trusted") is not True
        or labeling.get("visible_label", {}).get("meets_minimum_height") is not True
    ):
        return False
    return _claim_valid(payload, signature)


def protect_content(
    image_bytes: bytes,
    *,
    creator_ref: str,
    model: str,
    challenge_id: str | None = None,
    creator_signature_base64: str | None = None,
    aigc_label: str | None = None,
) -> dict[str, Any]:
    if settings.mode.strip().lower() == "production" and not _provenance_secret_ready():
        raise ProvenanceCapabilityError("JYS_PROVENANCE_SECRET must contain at least 32 characters")
    creator_ref = _validate_creator_ref(creator_ref)
    original_sha256 = _sha256_bytes(image_bytes)
    if bool(challenge_id) != bool(creator_signature_base64):
        raise ValueError("challenge_id and creator_signature_base64 must be supplied together")
    if challenge_id and creator_signature_base64:
        try:
            with _DB_LOCK, _database() as connection:
                _prepare_audit_ledger(connection)
                creator_identity = consume_challenge(
                    connection,
                    challenge_id=challenge_id,
                    creator_signature_base64=creator_signature_base64,
                    creator_ref=creator_ref,
                    model=model,
                    image_sha256=original_sha256,
                )
        except CreatorIdentityError as exc:
            raise ProvenanceCapabilityError(str(exc)) from exc
    elif settings.mode.strip().lower() == "production":
        raise ProvenanceCapabilityError(
            "production protection requires a one-time Ed25519 creator challenge"
        )
    else:
        creator_identity = {
            "schema_version": "creator-reference-declaration.v1",
            "creator_ref": creator_ref,
            "key_possession_verified": False,
            "natural_person_identity_verified": False,
        }
    if aigc_label is not None and aigc_label not in AIGC_LABELS:
        raise ValueError("aigc_label must be one of 1, 2 or 3")
    adapter = _get_adapter(model)
    image = _rgb(image_bytes)
    content_id = uuid.uuid4().hex
    message, message_protection = _message_for_record(
        content_id,
        model,
        adapter.message_length,
    )
    checkpoint, checkpoint_sha256 = _adapter_checkpoint_identity(adapter)
    embedded = adapter.encode(image, message)
    checkpoint_after, checkpoint_sha256_after = _adapter_checkpoint_identity(adapter)
    if (checkpoint_after, checkpoint_sha256_after) != (checkpoint, checkpoint_sha256):
        raise ProvenanceCapabilityError("adapter checkpoint changed during protection")
    protected_bytes = _png_bytes(embedded.image)
    aigc_labeling = None
    if aigc_label is not None:
        fields = build_aigc_fields(label=aigc_label, content_id=content_id)
        protected_bytes, aigc_labeling = apply_aigc_labels(
            protected_bytes,
            fields=fields,
            visible=True,
        )
    created_at = int(time.time())
    checkpoint_registered = _checkpoint_registered(model, checkpoint_sha256)

    asset_dir = ASSETS / "provenance" / content_id
    asset_dir.mkdir(parents=True, exist_ok=False)
    protected_path = asset_dir / "protected.png"
    atomic_write_bytes(protected_path, protected_bytes)

    protocol = load_protocol()
    calibrated_threshold = _calibrated_verification_threshold(model, checkpoint_sha256)
    verification_threshold = (
        calibrated_threshold
        if calibrated_threshold is not None
        else float(protocol["success_threshold"])
    )
    record = {
        "schema_version": "provenance-record.v2",
        "content_id": content_id,
        "creator_ref": creator_ref,
        "creator_identity": creator_identity,
        "owner_scope": creator_identity.get("owner_scope"),
        "model": model,
        "created_at": created_at,
        "original_sha256": original_sha256,
        "protected_sha256": _sha256_bytes(protected_bytes),
        "checkpoint_sha256": checkpoint_sha256,
        "checkpoint_registered": checkpoint_registered,
        "checkpoint_calibrated": calibrated_threshold is not None,
        "weight_manifest_sha256": sha256_file(MANIFEST) if MANIFEST.is_file() else None,
        "message_length": int(adapter.message_length),
        "message_sha256": hashlib.sha256(
            np.asarray(message, dtype=np.uint8).reshape(-1).tobytes()
        ).hexdigest(),
        "message_protection": message_protection,
        "protocol": protocol["schema_version"],
        "verification_threshold": verification_threshold,
        "aigc_labeling": aigc_labeling,
    }
    signature = _signature(record)
    claim_valid = _record_claim_valid(record, signature)
    stored_record = {**record, "evidence_signature": signature}

    try:
        with _DB_LOCK, _database() as connection:
            _prepare_audit_ledger(connection)
            connection.execute(
                """
                INSERT INTO provenance_records (
                    content_id, creator_ref, model, message_bits, original_sha256,
                    protected_sha256, checkpoint, checkpoint_sha256, created_at, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_id,
                    creator_ref,
                    model,
                    (
                        "derived:hmac-sha256-v1"
                        if message_protection == "hmac-sha256-v1"
                        else "".join(str(int(bit)) for bit in message)
                    ),
                    record["original_sha256"],
                    record["protected_sha256"],
                    checkpoint,
                    checkpoint_sha256,
                    created_at,
                    json.dumps(stored_record, ensure_ascii=False, sort_keys=True),
                ),
            )
            audit_event = audit_ledger.append_event(
                connection,
                event_type="provenance_record_created",
                object_id=content_id,
                object_payload=stored_record,
                created_at=created_at,
            )
    except Exception:
        protected_path.unlink(missing_ok=True)
        asset_dir.rmdir()
        raise

    audit_status = _synchronize_audit_ledger()
    source_credential = build_source_credential(content_id)
    credential_path = asset_dir / "source-credential.json"
    atomic_write_json(credential_path, source_credential)

    return {
        **stored_record,
        "mode": "real_checkpoint",
        "result_provenance": "registered_protection_record",
        "claim_valid": claim_valid,
        "evidence_status": "signed_checkpoint_bound" if claim_valid else "operational_unverified",
        "creator_identity_verified": _creator_identity_valid(record),
        "audit_event": audit_event,
        "audit_ledger": audit_status,
        "source_credential": {
            "schema_version": source_credential["schema_version"],
            "url": f"/api/provenance/credentials/{content_id}",
            "sha256": sha256_file(credential_path),
            "json_base64": base64.b64encode(credential_path.read_bytes()).decode("ascii"),
            "signature_trusted": source_credential["credential_signature_trusted"],
        },
        "protected_image": {
            "url": f"/api/artifacts/provenance/{content_id}/protected.png",
            "png_base64": base64.b64encode(protected_bytes).decode("ascii"),
        },
        "privacy": {
            "original_persisted": False,
            "creator_ref_persisted": True,
            "creator_public_key_persisted": bool(
                creator_identity.get("creator_public_key_pem")
            ),
        },
    }


def _record(content_id: str) -> sqlite3.Row | None:
    with _DB_LOCK, _database() as connection:
        return connection.execute(
            "SELECT * FROM provenance_records WHERE content_id = ?",
            (content_id,),
        ).fetchone()


def _payload_signature_trusted(payload: dict[str, Any], signature: Any) -> bool:
    if not isinstance(signature, dict) or signature.get("signed") is not True:
        return False
    pinned = str(settings.evidence_public_key_fingerprint or "").strip().lower()
    actual = signature_public_key_fingerprint(signature)
    return bool(
        _is_sha256(pinned)
        and _is_sha256(actual)
        and hmac.compare_digest(pinned, str(actual).lower())
        and verify_payload_signature(payload, signature)
    )


_REVOCATION_REASONS = frozenset({
    "creator_request",
    "key_compromise",
    "mislabeling",
    "policy_violation",
})


def _record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        record = json.loads(row["record_json"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProvenanceCapabilityError("stored provenance record is invalid") from exc
    if not isinstance(record, dict):
        raise ProvenanceCapabilityError("stored provenance record is invalid")
    return record


def _creator_public_key(record: dict[str, Any]) -> Ed25519PublicKey:
    proof = record.get("creator_identity")
    if not verify_creator_proof(proof):
        raise ProvenanceCapabilityError("record has no verified creator key binding")
    try:
        public_key = serialization.load_pem_public_key(
            proof["creator_public_key_pem"].encode("ascii")
        )
    except (KeyError, TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProvenanceCapabilityError("record creator key is invalid") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ProvenanceCapabilityError("record creator key is invalid")
    return public_key


def create_revocation_intent(
    content_id: str,
    *,
    reason_code: str,
) -> dict[str, Any]:
    if reason_code not in _REVOCATION_REASONS:
        raise ValueError("unsupported revocation reason_code")
    now = int(time.time())
    with _DB_LOCK, _database() as connection:
        _prepare_audit_ledger(connection)
        row = connection.execute(
            "SELECT * FROM provenance_records WHERE content_id = ?",
            (content_id,),
        ).fetchone()
        if row is None:
            raise KeyError("provenance record not found")
        record = _record_from_row(row)
        _creator_public_key(record)
        if connection.execute(
            "SELECT 1 FROM provenance_revocations WHERE content_id = ?",
            (content_id,),
        ).fetchone() is not None:
            raise ProvenanceCapabilityError("provenance record is already revoked")
        payload = {
            "schema_version": "provenance-revocation-intent.v1",
            "intent_id": uuid.uuid4().hex,
            "content_id": content_id,
            "reason_code": reason_code,
            "nonce_base64": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
            "created_at": now,
            "expires_at": now + min(
                int(getattr(settings, "creator_challenge_ttl_seconds", 300)),
                900,
            ),
            "creator_key_fingerprint_sha256": record["creator_identity"][
                "creator_key_fingerprint_sha256"
            ],
        }
        server_signature = _signature(payload)
        stored = {**payload, "server_signature": server_signature}
        connection.execute(
            """
            INSERT INTO revocation_intents (
                intent_id, content_id, reason_code, nonce_base64,
                created_at, expires_at, used_at, intent_json
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                payload["intent_id"],
                content_id,
                reason_code,
                payload["nonce_base64"],
                now,
                payload["expires_at"],
                json.dumps(stored, ensure_ascii=False, sort_keys=True),
            ),
        )
    return {
        **stored,
        "signing_message_base64": base64.b64encode(canonical_json(payload)).decode("ascii"),
        "server_signature_trusted": _payload_signature_trusted(payload, server_signature),
    }


def _revocation_from_connection(
    connection: sqlite3.Connection,
    content_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM provenance_revocations WHERE content_id = ?",
        (content_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        stored = json.loads(row["revocation_json"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProvenanceCapabilityError("stored revocation event is invalid") from exc
    if not isinstance(stored, dict):
        raise ProvenanceCapabilityError("stored revocation event is invalid")
    signature = stored.get("evidence_signature")
    payload = {key: value for key, value in stored.items() if key != "evidence_signature"}
    if (
        payload.get("content_id") != row["content_id"]
        or payload.get("revocation_id") != row["revocation_id"]
        or payload.get("reason_code") != row["reason_code"]
        or payload.get("revoked_at") != row["revoked_at"]
        or not _payload_signature_trusted(payload, signature)
    ):
        raise ProvenanceCapabilityError("stored revocation event failed integrity validation")
    return {
        **stored,
        "revoked": True,
        "signature_trusted": True,
    }


def provenance_revocation_status(content_id: str) -> dict[str, Any]:
    with _DB_LOCK, _database() as connection:
        revocation = _revocation_from_connection(connection, content_id)
    return revocation or {"revoked": False}


def revoke_content(
    content_id: str,
    *,
    intent_id: str,
    creator_signature_base64: str,
) -> dict[str, Any]:
    now = int(time.time())
    with _DB_LOCK, _database() as connection:
        _prepare_audit_ledger(connection)
        row = connection.execute(
            "SELECT * FROM provenance_records WHERE content_id = ?",
            (content_id,),
        ).fetchone()
        if row is None:
            raise KeyError("provenance record not found")
        record = _record_from_row(row)
        public_key = _creator_public_key(record)
        intent_row = connection.execute(
            "SELECT * FROM revocation_intents WHERE intent_id = ? AND content_id = ?",
            (intent_id, content_id),
        ).fetchone()
        if intent_row is None:
            raise ProvenanceCapabilityError("revocation intent not found")
        if intent_row["used_at"] is not None:
            raise ProvenanceCapabilityError("revocation intent was already used")
        if now > int(intent_row["expires_at"]):
            raise ProvenanceCapabilityError("revocation intent expired")
        try:
            stored_intent = json.loads(intent_row["intent_json"])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ProvenanceCapabilityError("stored revocation intent is invalid") from exc
        server_signature = stored_intent.get("server_signature")
        intent = {
            key: value for key, value in stored_intent.items() if key != "server_signature"
        }
        if (
            intent.get("intent_id") != intent_row["intent_id"]
            or intent.get("content_id") != content_id
            or intent.get("reason_code") != intent_row["reason_code"]
            or intent.get("nonce_base64") != intent_row["nonce_base64"]
            or intent.get("created_at") != intent_row["created_at"]
            or intent.get("expires_at") != intent_row["expires_at"]
            or not _payload_signature_trusted(intent, server_signature)
        ):
            raise ProvenanceCapabilityError("revocation intent failed integrity validation")
        try:
            creator_signature = base64.b64decode(
                creator_signature_base64,
                validate=True,
            )
            public_key.verify(creator_signature, canonical_json(intent))
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise ProvenanceCapabilityError("revocation creator signature is invalid") from exc
        if connection.execute(
            "SELECT 1 FROM provenance_revocations WHERE content_id = ?",
            (content_id,),
        ).fetchone() is not None:
            raise ProvenanceCapabilityError("provenance record is already revoked")
        updated = connection.execute(
            "UPDATE revocation_intents SET used_at = ? WHERE intent_id = ? AND used_at IS NULL",
            (now, intent_id),
        )
        if updated.rowcount != 1:
            raise ProvenanceCapabilityError("revocation intent was already used")
        record_payload = {
            key: value for key, value in record.items() if key != "evidence_signature"
        }
        revocation = {
            "schema_version": "provenance-revocation.v1",
            "revocation_id": uuid.uuid4().hex,
            "content_id": content_id,
            "reason_code": intent["reason_code"],
            "revoked_at": now,
            "creator_key_fingerprint_sha256": intent[
                "creator_key_fingerprint_sha256"
            ],
            "creator_signature_base64": creator_signature_base64,
            "intent_sha256": hashlib.sha256(canonical_json(intent)).hexdigest(),
            "parent_record_sha256": hashlib.sha256(
                canonical_json(record_payload)
            ).hexdigest(),
        }
        signature = _signature(revocation)
        if not _payload_signature_trusted(revocation, signature):
            raise ProvenanceCapabilityError("revocation server signature is not trusted")
        stored_revocation = {**revocation, "evidence_signature": signature}
        connection.execute(
            """
            INSERT INTO provenance_revocations (
                content_id, revocation_id, reason_code, revoked_at, revocation_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                content_id,
                revocation["revocation_id"],
                revocation["reason_code"],
                now,
                json.dumps(stored_revocation, ensure_ascii=False, sort_keys=True),
            ),
        )
        audit_event = audit_ledger.append_event(
            connection,
            event_type="provenance_record_revoked",
            object_id=revocation["revocation_id"],
            object_payload=stored_revocation,
            created_at=now,
        )
    audit_status = _synchronize_audit_ledger()
    credential = build_source_credential(content_id)
    credential_path = ASSETS / "provenance" / content_id / "source-credential.json"
    atomic_write_json(credential_path, credential)
    return {
        **stored_revocation,
        "revoked": True,
        "claim_valid": False,
        "audit_event": audit_event,
        "audit_ledger": audit_status,
        "source_credential_sha256": sha256_file(credential_path),
    }


def build_source_credential(content_id: str) -> dict[str, Any]:
    with _DB_LOCK, _database() as connection:
        row = connection.execute(
            "SELECT * FROM provenance_records WHERE content_id = ?",
            (content_id,),
        ).fetchone()
        if row is None:
            raise KeyError("provenance record not found")
        try:
            record = json.loads(row["record_json"])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ProvenanceCapabilityError("stored provenance record is invalid") from exc
        event_row = connection.execute(
            """
            SELECT event_hash, event_json FROM audit_events
            WHERE event_type = 'provenance_record_created' AND object_id = ?
            ORDER BY sequence ASC LIMIT 1
            """,
            (content_id,),
        ).fetchone()
        if event_row is None:
            raise ProvenanceCapabilityError("provenance record has no append-only audit event")
        try:
            audit_event = json.loads(event_row["event_json"])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ProvenanceCapabilityError("stored audit event is invalid") from exc
        audit_event["event_hash"] = event_row["event_hash"]
        audit_status = audit_ledger.verify_anchor(
            connection,
            path=_audit_anchor_path(),
        )
        revocation = _revocation_from_connection(connection, content_id)
    anchor = None
    anchor_file = _audit_anchor_path()
    if anchor_file.is_file():
        try:
            anchor = json.loads(anchor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            anchor = None
    payload = {
        "schema_version": "jianyuanshield-source-credential.v1",
        "content_id": content_id,
        "record": record,
        "record_audit_event": audit_event,
        "revocation": revocation or {"revoked": False},
        "ledger_anchor": anchor,
        "ledger_status": {
            "ledger_id": audit_status.get("ledger_id"),
            "last_sequence": audit_status.get("last_sequence"),
            "root_event_hash": audit_status.get("root_event_hash"),
            "trusted": audit_status.get("trusted"),
            "status": audit_status.get("status"),
        },
    }
    signature = _signature(payload)
    return {
        **payload,
        "credential_signature": signature,
        "credential_signature_trusted": _payload_signature_trusted(payload, signature),
    }


def _parse_source_credential(data: bytes) -> tuple[str, dict[str, Any]]:
    if not data or len(data) > 256 * 1024:
        raise ProvenanceCapabilityError("source credential exceeds the 256 KiB limit")
    try:
        credential = json.loads(
            data.decode("utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ProvenanceCapabilityError("source credential is invalid") from exc
    if not isinstance(credential, dict):
        raise ProvenanceCapabilityError("source credential is invalid")
    signature = credential.get("credential_signature")
    payload = {
        key: value
        for key, value in credential.items()
        if key not in {"credential_signature", "credential_signature_trusted"}
    }
    content_id = payload.get("content_id")
    if (
        payload.get("schema_version") != "jianyuanshield-source-credential.v1"
        or not isinstance(content_id, str)
        or len(content_id) != 32
        or any(character not in "0123456789abcdef" for character in content_id)
        or payload.get("record", {}).get("content_id") != content_id
    ):
        raise ProvenanceCapabilityError("source credential contract is invalid")
    if not _payload_signature_trusted(payload, signature):
        raise ProvenanceCapabilityError("source credential signature is not trusted")
    return content_id, credential


def _resolve_content_id(
    image_bytes: bytes,
    *,
    content_id: str | None,
    source_credential_bytes: bytes | None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any], str]:
    supplied = content_id.strip() if isinstance(content_id, str) else ""
    if supplied and (
        len(supplied) != 32
        or any(character not in "0123456789abcdef" for character in supplied)
    ):
        raise ProvenanceCapabilityError("content_id is invalid")
    credential = None
    credential_id = ""
    if source_credential_bytes is not None:
        credential_id, credential = _parse_source_credential(source_credential_bytes)
    metadata = inspect_aigc_png(image_bytes, expected_content_id=supplied or None)
    metadata_id = ""
    fields = metadata.get("fields")
    if (
        isinstance(fields, dict)
        and metadata.get("metadata_valid") is True
        and metadata.get("producer_seal_trusted") is True
    ):
        metadata_id = str(fields.get("ProduceID") or "")
    candidates = {candidate for candidate in (supplied, credential_id, metadata_id) if candidate}
    if len(candidates) > 1:
        raise ProvenanceCapabilityError("content locators disagree")
    if not candidates:
        raise ProvenanceCapabilityError(
            "content_id, trusted AIGC metadata or a signed source credential is required"
        )
    resolved = candidates.pop()
    locator = (
        "explicit_content_id"
        if supplied
        else "signed_sidecar"
        if credential_id
        else "trusted_gb45438_metadata"
    )
    return resolved, credential, metadata, locator


def verify_content(
    image_bytes: bytes,
    *,
    content_id: str | None = None,
    source_credential_bytes: bytes | None = None,
) -> dict[str, Any]:
    if settings.mode.strip().lower() == "production" and not _provenance_secret_ready():
        raise ProvenanceCapabilityError("JYS_PROVENANCE_SECRET must contain at least 32 characters")
    content_id, source_credential, aigc_inspection, source_locator = _resolve_content_id(
        image_bytes,
        content_id=content_id,
        source_credential_bytes=source_credential_bytes,
    )
    row = _record(content_id)
    if row is None:
        raise KeyError("provenance record not found")
    try:
        stored_record = json.loads(row["record_json"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProvenanceCapabilityError("stored provenance record is invalid") from exc
    if not isinstance(stored_record, dict):
        raise ProvenanceCapabilityError("stored provenance record is invalid")
    row_bindings = {
        "content_id": row["content_id"],
        "creator_ref": row["creator_ref"],
        "model": row["model"],
        "original_sha256": row["original_sha256"],
        "protected_sha256": row["protected_sha256"],
        "checkpoint_sha256": row["checkpoint_sha256"],
        "created_at": row["created_at"],
    }
    if any(stored_record.get(key) != value for key, value in row_bindings.items()):
        raise ProvenanceCapabilityError("database columns do not match the stored provenance record")
    try:
        message_length = int(stored_record["message_length"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProvenanceCapabilityError("stored message contract is invalid") from exc
    if message_length <= 0:
        raise ProvenanceCapabilityError("stored message contract is invalid")
    stored_signature = stored_record.get("evidence_signature", {})
    parent_payload = {
        key: value for key, value in stored_record.items() if key != "evidence_signature"
    }
    revocation = provenance_revocation_status(content_id)
    parent_claim_valid = (
        _record_claim_valid(parent_payload, stored_signature)
        and revocation.get("revoked") is not True
    )
    if source_credential is not None and source_credential.get("record") != stored_record:
        raise ProvenanceCapabilityError(
            "source credential record does not match the active provenance database"
        )

    adapter = _get_adapter(str(stored_record["model"]))
    runtime_checkpoint, runtime_checkpoint_sha256 = _adapter_checkpoint_identity(adapter)
    if runtime_checkpoint_sha256 != stored_record.get("checkpoint_sha256"):
        raise ProvenanceCapabilityError(
            "runtime adapter checkpoint does not match the registered provenance record"
        )
    observed = _rgb(image_bytes)
    decoded = adapter.decode(observed)
    checkpoint_after, checkpoint_sha256_after = _adapter_checkpoint_identity(adapter)
    if (checkpoint_after, checkpoint_sha256_after) != (
        runtime_checkpoint,
        runtime_checkpoint_sha256,
    ):
        raise ProvenanceCapabilityError("adapter checkpoint changed during verification")
    if row["message_bits"] == "derived:hmac-sha256-v1":
        if stored_record.get("message_protection") != "hmac-sha256-v1":
            raise ProvenanceCapabilityError("stored message binding is inconsistent")
        expected, message_protection = _message_for_record(
            content_id,
            str(stored_record["model"]),
            message_length,
        )
    else:
        message_bits = str(row["message_bits"])
        if (
            stored_record.get("message_protection") != "stored-random-v1"
            or len(message_bits) != message_length
            or any(bit not in "01" for bit in message_bits)
        ):
            raise ProvenanceCapabilityError("stored message binding is inconsistent")
        expected = np.fromiter((int(bit) for bit in message_bits), dtype=np.uint8)
        message_protection = "stored-random-v1"
    expected_message_sha256 = hashlib.sha256(
        np.asarray(expected, dtype=np.uint8).reshape(-1).tobytes()
    ).hexdigest()
    if not hmac.compare_digest(
        str(stored_record.get("message_sha256") or ""),
        expected_message_sha256,
    ):
        raise ProvenanceCapabilityError("stored message digest does not match the expected message")
    recovered = np.asarray(decoded.bits, dtype=np.uint8).reshape(-1)
    if recovered.size != expected.size:
        raise ProvenanceCapabilityError("decoder returned an unexpected message length")
    bit_accuracy = float(np.mean(recovered == expected))
    calibrated_threshold = _calibrated_verification_threshold(
        str(stored_record["model"]),
        stored_record["checkpoint_sha256"],
    )
    threshold = (
        calibrated_threshold
        if calibrated_threshold is not None
        else float(load_protocol()["success_threshold"])
    )
    verified = bit_accuracy >= threshold
    observed_sha256 = _sha256_bytes(image_bytes)
    event = {
        "schema_version": "provenance-verification.v1",
        "event_id": uuid.uuid4().hex,
        "content_id": content_id,
        "creator_ref": stored_record["creator_ref"],
        "model": stored_record["model"],
        "created_at": int(time.time()),
        "observed_sha256": observed_sha256,
        "exact_protected_file_match": observed_sha256 == stored_record["protected_sha256"],
        "bit_accuracy": round(bit_accuracy, 6),
        "success_threshold": threshold,
        "verification_threshold": threshold,
        "verified": verified,
        "checkpoint_sha256": stored_record["checkpoint_sha256"],
        "runtime_checkpoint_sha256": runtime_checkpoint_sha256,
        "message_sha256": expected_message_sha256,
        "checkpoint_registered": _checkpoint_registered(
            stored_record["model"], stored_record["checkpoint_sha256"]
        ),
        "checkpoint_calibrated": calibrated_threshold is not None,
        "message_protection": message_protection,
        "creator_key_fingerprint_sha256": stored_record.get("creator_identity", {}).get(
            "creator_key_fingerprint_sha256"
        ),
        "owner_scope": stored_record.get("owner_scope"),
        "source_locator": source_locator,
        "aigc_metadata": aigc_inspection,
        "aigc_metadata_intact": bool(
            stored_record.get("aigc_labeling") is None
            or (
                aigc_inspection.get("metadata_valid") is True
                and aigc_inspection.get("producer_seal_trusted") is True
            )
        ),
        "parent_record_revoked": revocation.get("revoked") is True,
        "revocation": revocation,
        "parent_record_claim_valid": parent_claim_valid,
        "parent_record_sha256": hashlib.sha256(
            json.dumps(
                parent_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    signature = _signature(event)
    claim_valid = parent_claim_valid and _claim_valid(event, signature)
    stored_event = {**event, "evidence_signature": signature}
    with _DB_LOCK, _database() as connection:
        _prepare_audit_ledger(connection)
        connection.execute(
            """
            INSERT INTO verification_events (
                event_id, content_id, observed_sha256, bit_accuracy,
                verified, created_at, event_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                content_id,
                observed_sha256,
                bit_accuracy,
                int(verified),
                event["created_at"],
                json.dumps(stored_event, ensure_ascii=False, sort_keys=True),
            ),
        )
        audit_event = audit_ledger.append_event(
            connection,
            event_type="provenance_verification_created",
            object_id=event["event_id"],
            object_payload=stored_event,
            created_at=event["created_at"],
        )
    audit_status = _synchronize_audit_ledger()
    return {
        **stored_event,
        "mode": "real_checkpoint",
        "result_provenance": "registered_blind_verification",
        "claim_valid": claim_valid,
        "evidence_status": "signed_checkpoint_bound" if claim_valid else "operational_unverified",
        "decoder": decoded.metadata,
        "audit_event": audit_event,
        "audit_ledger": audit_status,
    }


def get_provenance_record(content_id: str) -> dict[str, Any] | None:
    row = _record(content_id)
    if row is None:
        return None
    record = json.loads(row["record_json"])
    record["checkpoint_registered"] = _checkpoint_registered(
        row["model"], row["checkpoint_sha256"]
    )
    record["checkpoint_calibrated"] = _checkpoint_calibrated(
        row["model"],
        row["checkpoint_sha256"],
        record.get("verification_threshold"),
    )
    signature = record.pop("evidence_signature", {})
    revocation = provenance_revocation_status(content_id)
    record["claim_valid"] = (
        _record_claim_valid(record, signature)
        and revocation.get("revoked") is not True
    )
    record["creator_identity_verified"] = _creator_identity_valid(record)
    record["evidence_signature"] = signature
    record["evidence_status"] = (
        "signed_checkpoint_bound" if record["claim_valid"] else "operational_unverified"
    )
    record["mode"] = "real_checkpoint"
    record["result_provenance"] = "registered_protection_record"
    record["revocation"] = revocation
    record["audit_ledger"] = provenance_audit_status()
    credential_path = ASSETS / "provenance" / content_id / "source-credential.json"
    record["source_credential"] = {
        "url": f"/api/provenance/credentials/{content_id}",
        "available": credential_path.is_file(),
        "sha256": sha256_file(credential_path) if credential_path.is_file() else None,
    }
    return record
