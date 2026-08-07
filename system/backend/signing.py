from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .utils import _fsync_directory, atomic_write_bytes, atomic_write_json
from .mea_evidence import (
    MEA_EVIDENCE_DIR,
    MEA_EVIDENCE_NAMES,
    MEA_CHECKPOINT_PATHS,
    MEA_IMPLEMENTATION_PATHS,
    validate_mea_matrix_evidence,
)
from .simswap_evidence import (
    SIMSWAP_ASSET_PATHS,
    SIMSWAP_ENGINE_ARTIFACT_PATHS,
    SIMSWAP_EVIDENCE_DIR,
    SIMSWAP_EVIDENCE_NAMES,
    SIMSWAP_IMPLEMENTATION_PATHS,
    validate_simswap_lfw_evidence,
)

from .config import ASSETS, REPORTS, ROOT
from system.evaluation.runtime import WEIGHT_ROOT, logical_path, resolve_logical_path


SIGNATURE_DIR = REPORTS / "evidence_signature"
MANIFEST_PATH = SIGNATURE_DIR / "manifest.json"
SIGNATURE_PATH = SIGNATURE_DIR / "manifest.sig"
PUBLIC_KEY_PATH = SIGNATURE_DIR / "public_key.pem"
CORE_SIGNATURE_DIR = SIGNATURE_DIR / "release-core"
CORE_MANIFEST_PATH = CORE_SIGNATURE_DIR / "manifest.json"
CORE_SIGNATURE_PATH = CORE_SIGNATURE_DIR / "manifest.sig"
CORE_PUBLIC_KEY_PATH = CORE_SIGNATURE_DIR / "public_key.pem"

FORMAL_SUMMARIES = {
    "SepMark": REPORTS / "sepmark_lfw_benchmark" / "summary.json",
    "WaveGuard": REPORTS / "waveguard_lfw_benchmark" / "summary.json",
    "LIDMark": REPORTS
    / "lidmark_lfw_identity_test_epoch20_protocol_v1"
    / "summary.json",
    "KAD-Net": REPORTS / "kadnet_lfw_benchmark" / "summary.json",
}
FORMAL_SAMPLE_COUNTS = {
    "SepMark": 13_233,
    "WaveGuard": 13_233,
    "LIDMark": 1_324,
    "KAD-Net": 13_233,
}
FORMAL_RUNNERS = {
    "SepMark": ROOT / "system" / "scripts" / "run_sepmark_lfw_benchmark.py",
    "WaveGuard": ROOT / "system" / "scripts" / "run_waveguard_lfw_benchmark.py",
    "LIDMark": ROOT / "system" / "scripts" / "run_lidmark_lfw_benchmark.py",
    "KAD-Net": ROOT / "system" / "scripts" / "run_kadnet_lfw_benchmark.py",
}
FORMAL_RESULTS = {
    "SepMark": REPORTS / "sepmark_lfw_benchmark" / "results.csv",
    "WaveGuard": REPORTS / "waveguard_lfw_benchmark" / "results.csv",
    "LIDMark": REPORTS
    / "lidmark_lfw_identity_test_epoch20_protocol_v1"
    / "raw_results.csv",
    "KAD-Net": REPORTS / "kadnet_lfw_benchmark" / "results.csv",
}
DERIVED_EVIDENCE_GENERATORS = [
    ROOT / "system" / "scripts" / "audit_benchmark_results.py",
    ROOT / "system" / "scripts" / "run_statistical_analysis.py",
    ROOT / "system" / "scripts" / "aggregate_real_benchmarks.py",
    ROOT / "system" / "scripts" / "export_competition_report.py",
    ROOT / "scripts" / "create_release_snapshot.py",
    ROOT / "system" / "evaluation" / "statistics.py",
]
CORE_GATE_SOURCES = [
    ROOT / "system" / "backend" / "signing.py",
    ROOT / "system" / "backend" / "benchmark_evidence.py",
    ROOT / "system" / "backend" / "claims.py",
    ROOT / "system" / "backend" / "mea_evidence.py",
    ROOT / "system" / "backend" / "simswap_evidence.py",
    ROOT / "tests" / "test_simswap_conditioned_migration.py",
    ROOT / "system" / "backend" / "settings.py",
    ROOT / "system" / "backend" / "utils.py",
    ROOT / "system" / "evaluation" / "attacks.py",
    ROOT / "system" / "evaluation" / "run_metadata.py",
    ROOT / "system" / "evaluation" / "runtime.py",
]
COLLABORATION_POLICY_SOURCES = [
    ROOT / "configs" / "collaboration_policy.v2.json",
    ROOT / "system" / "backend" / "collaboration.py",
    ROOT / "system" / "backend" / "routes.py",
    ROOT / "system" / "backend" / "schemas.py",
    ROOT / "tests" / "test_collaboration_policy.py",
]
SUPPLY_CHAIN_SOURCES = [
    ROOT / "requirements.lock",
    ROOT / "supply-chain" / "build-manifest.json",
    ROOT / "supply-chain" / "python-dependencies.cdx.json",
    ROOT / "requirements.txt",
    ROOT / "Dockerfile",
    ROOT / "scripts" / "supply_chain.py",
    ROOT / "scripts" / "build_release_image.py",
    ROOT / "scripts" / "check_deployment.py",
    ROOT / "scripts" / "offline_bundle.py",
    ROOT / "offline_deploy.sh",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "system" / "gateway.py",
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.production.yml",
    ROOT / "docker-compose.competition.yml",
    ROOT / "tests" / "test_deployment.py",
    ROOT / "tests" / "test_gateway.py",
    ROOT / "tests" / "test_offline_bundle.py",
    ROOT / "tests" / "test_supply_chain.py",
]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(public_der).hexdigest()


def _require_pinned_release_signer(
    public_key: Ed25519PublicKey,
    *,
    profile: str,
) -> None:
    """Reject a formal release signed by an unregistered or changed key."""

    if profile not in {"release-core", "release"}:
        return
    # Import lazily: benchmark_evidence imports this module while it also uses
    # settings for claim verification.
    from .settings import settings

    configured = (settings.evidence_public_key_fingerprint or "").strip().lower()
    actual = _public_key_fingerprint(public_key)
    if not _SHA256_RE.fullmatch(configured) or not hmac.compare_digest(
        configured,
        actual,
    ):
        raise ValueError(
            f"{profile} signer does not match JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT"
        )


def sign_payload(payload: dict[str, Any], private_key_path: Path) -> dict[str, Any]:
    """Create a detached, self-verifiable Ed25519 signature for one record."""

    private_key = serialization.load_pem_private_key(private_key_path.expanduser().read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private key is not Ed25519")
    signature = private_key.sign(canonical_json(payload))
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return {
        "algorithm": "ed25519",
        "signature_base64": base64.b64encode(signature).decode("ascii"),
        "public_key_pem": public_pem.decode("ascii"),
        "public_key_fingerprint_sha256": hashlib.sha256(public_der).hexdigest(),
    }


def verify_payload_signature(payload: dict[str, Any], signature: dict[str, Any]) -> bool:
    try:
        public_key = serialization.load_pem_public_key(signature["public_key_pem"].encode("ascii"))
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        public_key.verify(
            base64.b64decode(signature["signature_base64"], validate=True),
            canonical_json(payload),
        )
        return True
    except (InvalidSignature, KeyError, TypeError, ValueError):
        return False


def signature_public_key_fingerprint(signature: dict[str, Any]) -> str | None:
    """Derive the signer fingerprint from the embedded public key.

    The separately supplied ``public_key_fingerprint_sha256`` field is only a
    convenience value and must not be trusted on its own.
    """

    try:
        public_key = serialization.load_pem_public_key(
            signature["public_key_pem"].encode("ascii")
        )
        if not isinstance(public_key, Ed25519PublicKey):
            return None
        public_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(public_der).hexdigest()
    except (KeyError, TypeError, ValueError):
        return None


@lru_cache(maxsize=4096)
def _sha256_stable_file_identity(
    path_text: str,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    ctime_ns: int,
) -> str:
    """Hash one immutable stat identity and reuse it across evidence probes."""

    del device, inode, size, mtime_ns, ctime_ns
    digest = hashlib.sha256()
    with Path(path_text).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    metadata = path.stat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def sha256_file(path: Path) -> str:
    """Return a digest cached by stable file identity, never by path alone.

    Device, inode, size, mtime and ctime invalidate the cache after replacement
    or in-place mutation.  The second stat rejects files that changed while the
    digest was being read.
    """

    resolved = path.expanduser().resolve(strict=True)
    for _attempt in range(3):
        before = _file_identity(resolved)
        digest = _sha256_stable_file_identity(str(resolved), *before)
        after = _file_identity(resolved)
        if before == after:
            return digest
    raise OSError(f"file changed while hashing: {resolved}")


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return logical_path(path)


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _csv_rows(path: Path, label: str) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f"{label} has no CSV header")
            return list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"{label} is not valid CSV") from exc


def _csv_matches_records(
    path: Path,
    label: str,
    *,
    fields: list[str],
    records: list[dict[str, Any]],
) -> bool:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if list(reader.fieldnames or []) != fields:
                return False
            actual = list(reader)
    except (OSError, UnicodeError, csv.Error):
        return False

    def normalize(record: dict[str, Any]) -> dict[str, str]:
        return {
            field: "" if record.get(field) is None else str(record.get(field))
            for field in fields
        }

    return actual == [normalize(record) for record in records]


def _validate_progress(
    path: Path,
    method: str,
    sample_count: int,
    attack_count: int,
) -> None:
    payload = _json_object(path, f"{method} progress")
    expected_rows = sample_count * attack_count
    if method == "LIDMark":
        schema = "lidmark-identity-test-progress.v1"
        processed = payload.get("processed_samples")
        total = payload.get("total_samples")
    else:
        schema = "benchmark-progress.v1"
        processed = payload.get("processed_images")
        total = payload.get("total_images")
    if (
        payload.get("schema_version") != schema
        or payload.get("status") != "complete"
        or processed != sample_count
        or total != sample_count
        or payload.get("result_rows") != expected_rows
        or payload.get("expected_result_rows") != expected_rows
        or payload.get("error_rows") != 0
    ):
        raise ValueError(f"{method} progress is not release-complete")


def _validate_weight_manifest(path: Path) -> None:
    payload = _json_object(path, "weight manifest")
    items = payload.get("items")
    if payload.get("schema_version") != "weight-manifest.v1" or not isinstance(items, list):
        raise ValueError("weight manifest schema is invalid")
    seen: set[str] = set()
    verified_models: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("weight manifest item must be an object")
        model = item.get("model")
        if not isinstance(model, str) or not model or model in seen:
            raise ValueError("weight manifest model identifiers must be unique")
        seen.add(model)
        checkpoint = _resolve_manifest_reference(
            f"weights/{item.get('file')}" if isinstance(item.get("file"), str) else None
        )
        calibration = _resolve_manifest_reference(
            f"weights/{item.get('calibration_artifact')}"
            if isinstance(item.get("calibration_artifact"), str)
            else None
        )
        if (
            item.get("status") != "verified"
            or checkpoint is None
            or calibration is None
            or not checkpoint.is_file()
            or not calibration.is_file()
            or item.get("sha256") != sha256_file(checkpoint)
            or item.get("calibration_artifact_sha256") != sha256_file(calibration)
        ):
            raise ValueError(f"weight manifest item is not verified: {model}")
        verified_models.add(model)
    if "KAD-Net" not in verified_models:
        raise ValueError("KAD-Net calibrated checkpoint registration is required")


def _validate_final_release_outputs() -> None:
    core_signature = verify_evidence_bundle(
        manifest_path=CORE_MANIFEST_PATH,
        signature_path=CORE_SIGNATURE_PATH,
        public_key_path=CORE_PUBLIC_KEY_PATH,
    )
    from .settings import settings

    configured_fingerprint = (
        settings.evidence_public_key_fingerprint or ""
    ).strip().lower()
    core_fingerprint = str(
        core_signature.get("public_key_fingerprint_sha256") or ""
    ).lower()
    if (
        core_signature.get("verified") is not True
        or core_signature.get("profile") != "release-core"
        or not _SHA256_RE.fullmatch(configured_fingerprint)
        or not _SHA256_RE.fullmatch(core_fingerprint)
        or not hmac.compare_digest(configured_fingerprint, core_fingerprint)
    ):
        raise ValueError("archived release-core signature is not trusted and verified")

    audit = _json_object(REPORTS / "protocol_audit" / "audit.json", "protocol audit")
    audit_models = audit.get("models")
    audit_signature = audit.get("evidence_signature")
    if (
        audit.get("schema_version") != "benchmark-audit.v1"
        or audit.get("status") != "verified"
        or not isinstance(audit_models, dict)
        or set(audit_models) != set(FORMAL_SUMMARIES)
        or any(
            not isinstance(value, dict) or value.get("status") != "verified"
            for value in audit_models.values()
        )
        or audit.get("findings") != []
        or not isinstance(audit_signature, dict)
        or audit_signature.get("verified") is not True
        or audit_signature.get("profile") != "release-core"
        or audit_signature.get("signer_pinned") is not True
        or audit_signature.get("manifest_sha256")
        != sha256_file(CORE_MANIFEST_PATH)
        or audit_signature.get("public_key_fingerprint_sha256")
        != core_fingerprint
    ):
        raise ValueError("protocol audit is not release-verified")
    audit_statistics: list[dict[str, Any]] = []
    for method, model in audit_models.items():
        summary_path = FORMAL_SUMMARIES[method]
        results_path = FORMAL_RESULTS[method]
        summary = _json_object(summary_path, f"{method} summary")
        sample_count = summary.get("num_images") or summary.get("sample_count")
        attack_ids = summary.get("attack_ids")
        expected_rows = (
            sample_count * len(attack_ids)
            if isinstance(sample_count, int) and isinstance(attack_ids, list)
            else None
        )
        if (
            model.get("path") != _relative(results_path)
            or model.get("summary_path") != _relative(summary_path)
            or model.get("results_sha256") != sha256_file(results_path)
            or model.get("summary_sha256") != sha256_file(summary_path)
            or model.get("rows") != expected_rows
            or model.get("expected_rows") != expected_rows
            or model.get("per_attack_sample_set_valid") is not True
            or not isinstance(model.get("attacks"), dict)
            or set(model["attacks"]) != set(attack_ids or [])
        ):
            raise ValueError(f"protocol audit source binding mismatch: {method}")
        for attack, metrics in model["attacks"].items():
            if not isinstance(metrics, dict):
                raise ValueError(f"protocol audit metrics are invalid: {method}.{attack}")
            for metric, statistics in metrics.items():
                if not isinstance(statistics, dict):
                    raise ValueError(
                        f"protocol audit statistics are invalid: {method}.{attack}.{metric}"
                    )
                audit_statistics.append({
                    "model": method,
                    "attack": attack,
                    "metric": metric,
                    **statistics,
                })
        for attack in attack_ids or []:
            primary = model["attacks"].get(attack, {}).get(model.get("primary_metric"), {})
            reported = summary.get("attacks", {}).get(attack, {})
            try:
                primary_mean = float(primary["mean"])
                summary_mean = float(reported["mean_bit_accuracy"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"protocol audit primary metric is missing: {method}.{attack}"
                ) from exc
            if (
                not math.isfinite(primary_mean)
                or abs(primary_mean - summary_mean) > 1e-7
                or primary.get("count") != sample_count
            ):
                raise ValueError(
                    f"protocol audit primary metric mismatch: {method}.{attack}"
                )
    audit_fields = [
        "model", "attack", "metric", "count", "mean", "std", "ci95_low",
        "ci95_high", "min", "p05", "median", "p95", "max", "constant",
        "wilson95_low", "wilson95_high",
    ]
    if not audit_statistics or not _csv_matches_records(
        REPORTS / "protocol_audit" / "statistics.csv",
        "protocol statistics",
        fields=audit_fields,
        records=audit_statistics,
    ):
        raise ValueError("protocol statistics do not match the audit JSON")

    analysis = _json_object(
        REPORTS / "statistical_analysis" / "analysis.json",
        "statistical analysis",
    )
    sources = analysis.get("sources")
    comparisons = analysis.get("comparisons")
    analysis_signature = analysis.get("evidence_signature")
    if (
        analysis.get("schema_version") != "statistical-analysis.v1"
        or analysis.get("status") != "complete"
        or not isinstance(sources, dict)
        or set(sources) != set(FORMAL_SUMMARIES)
        or any(
            not isinstance(value, dict) or value.get("status") != "verified"
            for value in sources.values()
        )
        or not isinstance(analysis.get("summaries"), list)
        or not analysis["summaries"]
        or not isinstance(comparisons, list)
        or not comparisons
        or not isinstance(analysis_signature, dict)
        or analysis_signature.get("verified") is not True
        or analysis_signature.get("profile") != "release-core"
        or analysis_signature.get("signer_pinned") is not True
        or analysis_signature.get("manifest_sha256")
        != sha256_file(CORE_MANIFEST_PATH)
        or analysis_signature.get("public_key_fingerprint_sha256")
        != core_fingerprint
    ):
        raise ValueError("statistical analysis is not release-complete")
    formal_attack_ids: list[str] | None = None
    formal_summaries: dict[str, dict[str, Any]] = {}
    for method, source in sources.items():
        summary_path = FORMAL_SUMMARIES[method]
        results_path = FORMAL_RESULTS[method]
        summary = _json_object(summary_path, f"{method} summary")
        formal_summaries[method] = summary
        attack_ids = summary.get("attack_ids")
        sample_count = summary.get("num_images") or summary.get("sample_count")
        if formal_attack_ids is None:
            formal_attack_ids = list(attack_ids or [])
        if (
            source.get("path") != _relative(results_path)
            or source.get("summary_path") != _relative(summary_path)
            or source.get("sha256") != sha256_file(results_path)
            or source.get("summary_sha256") != sha256_file(summary_path)
            or source.get("rows")
            != sample_count * len(attack_ids or [])
            or source.get("sample_count") != sample_count
            or source.get("attack_count") != len(attack_ids or [])
            or source.get("per_attack_sample_set_valid") is not True
        ):
            raise ValueError(f"statistical source binding mismatch: {method}")
    summary_keys: set[tuple[str, str]] = set()
    for item in analysis["summaries"]:
        if not isinstance(item, dict):
            raise ValueError("statistical summary record is invalid")
        method = item.get("method")
        attack = item.get("attack")
        key = (str(method), str(attack))
        if key in summary_keys or method not in FORMAL_SUMMARIES:
            raise ValueError("statistical summaries contain duplicates or unknown methods")
        summary_keys.add(key)
        formal = formal_summaries[str(method)]
        sample_count = formal.get("num_images") or formal.get("sample_count")
        try:
            mean = float(item["mean"])
            low = float(item["ci95_low"])
            high = float(item["ci95_high"])
            expected_mean = float(formal["attacks"][str(attack)]["mean_bit_accuracy"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("statistical summary is not bound to a formal metric") from exc
        if (
            item.get("count") != sample_count
            or not all(math.isfinite(value) for value in (mean, low, high))
            or not 0 <= low <= mean <= high <= 1
            or abs(mean - expected_mean) > 1e-7
        ):
            raise ValueError(f"statistical summary mismatch: {method}.{attack}")
    expected_summary_keys = {
        (method, str(attack))
        for method, summary in formal_summaries.items()
        for attack in summary.get("attack_ids", [])
    }
    if summary_keys != expected_summary_keys:
        raise ValueError("statistical summaries do not cover the formal matrix")
    comparison_keys: set[tuple[str, str, str]] = set()
    for item in comparisons:
        if not isinstance(item, dict):
            raise ValueError("statistical comparison record is invalid")
        first = str(item.get("first"))
        second = str(item.get("second"))
        key = (str(item.get("attack")), first, second)
        if (
            key in comparison_keys
            or first not in FORMAL_SUMMARIES
            or second not in FORMAL_SUMMARIES
            or first == second
            or not isinstance(item.get("pairs"), int)
            or item["pairs"] < 2
        ):
            raise ValueError("statistical comparison identity is invalid")
        comparison_keys.add(key)
        for field in (
            "mean_difference", "ci95_low", "ci95_high", "p_value",
            "p_value_holm",
        ):
            value = item.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"statistical comparison field is invalid: {field}")
        if not 0 <= item["p_value"] <= 1 or not 0 <= item["p_value_holm"] <= 1:
            raise ValueError("statistical comparison p-value is invalid")
    comparison_fields = list(comparisons[0])
    if not _csv_matches_records(
        REPORTS / "statistical_analysis" / "comparisons.csv",
        "statistical comparisons",
        fields=comparison_fields,
        records=comparisons,
    ):
        raise ValueError("statistical comparison CSV does not match analysis")

    aggregate = _json_object(
        REPORTS / "aggregate_real_benchmarks" / "summary.json",
        "aggregate benchmark",
    )
    aggregate_methods = list(FORMAL_SUMMARIES)
    aggregate_sources = aggregate.get("sources")
    aggregate_rows = aggregate.get("rows")
    aggregate_signature = aggregate.get("evidence_signature")
    if (
        aggregate.get("schema_version") != "aggregate-benchmark-summary.v1"
        or aggregate.get("status") != "complete"
        or aggregate.get("required_methods") != aggregate_methods
        or aggregate.get("complete_methods") != aggregate_methods
        or not isinstance(aggregate_sources, dict)
        or set(aggregate_sources) != set(aggregate_methods)
        or not isinstance(aggregate_rows, list)
        or len(aggregate_rows)
        != sum(
            len(summary.get("attack_ids", []))
            for summary in formal_summaries.values()
        )
        or not isinstance(aggregate_signature, dict)
        or aggregate_signature.get("verified") is not True
        or aggregate_signature.get("profile") != "release-core"
        or aggregate_signature.get("signer_pinned") is not True
        or aggregate_signature.get("manifest_sha256")
        != sha256_file(CORE_MANIFEST_PATH)
        or aggregate_signature.get("public_key_fingerprint_sha256")
        != core_fingerprint
        or any(
            not isinstance(row, dict)
            or row.get("status") != "complete"
            or row.get("can_defense") != "yes"
            for row in aggregate_rows
        )
    ):
        raise ValueError("aggregate benchmark is not release-complete")
    for method, summary_path in FORMAL_SUMMARIES.items():
        source = aggregate_sources.get(method)
        if (
            not isinstance(source, dict)
            or source.get("status") != "complete"
            or source.get("summary_sha256") != sha256_file(summary_path)
        ):
            raise ValueError(f"aggregate source hash mismatch: {method}")
    aggregate_defaults = {
        "SepMark": ("real_checkpoint", "lfw_full"),
        "WaveGuard": ("official_checkpoint_strict", "lfw_full"),
        "LIDMark": (
            "selected_epoch20_identity_disjoint_test",
            "lfw_identity_disjoint_test",
        ),
        "KAD-Net": ("official_epoch100_strict", "lfw_full"),
    }
    expected_aggregate_rows: list[dict[str, Any]] = []
    for method, summary in formal_summaries.items():
        mode, data_type = aggregate_defaults[method]
        attacks = summary.get("attacks")
        if not isinstance(attacks, dict):
            raise ValueError(f"aggregate formal attacks are invalid: {method}")
        for attack, metrics in attacks.items():
            if not isinstance(metrics, dict):
                raise ValueError(f"aggregate formal metrics are invalid: {method}.{attack}")
            expected_aggregate_rows.append({
                "method": method,
                "mode": summary.get("mode", mode),
                "data_type": summary.get("data_type", data_type),
                "attack": attack,
                "status": metrics.get("status", "unknown"),
                "can_defense": (
                    "yes"
                    if summary.get("status") == "complete"
                    and metrics.get("status") == "complete"
                    else "no"
                ),
                **{
                    key: value
                    for key, value in metrics.items()
                    if isinstance(value, (int, float))
                },
            })
    if aggregate_rows != expected_aggregate_rows:
        raise ValueError("aggregate rows do not match the formal summaries")
    aggregate_fields = sorted({key for row in aggregate_rows for key in row})
    if not _csv_matches_records(
        REPORTS / "aggregate_real_benchmarks" / "method_comparison.csv",
        "aggregate comparison",
        fields=aggregate_fields,
        records=aggregate_rows,
    ):
        raise ValueError("aggregate CSV does not match aggregate summary")
    curve = ASSETS / "aggregate_real_benchmarks" / "attack_degradation.png"
    if curve.stat().st_size < 100 or not curve.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("aggregate degradation curve is not a valid PNG")

    report = _json_object(
        REPORTS / "jianyuanshield_competition_report" / "report.json",
        "competition report",
    )
    artifacts = report.get("performance_artifacts")
    report_signature = report.get("evidence_gate", {}).get("signature", {})
    if (
        report.get("schema_version") != "competition-report.v3"
        or report.get("claim_valid") is not True
        or report.get("claim_status") != "evidence_verified"
        or report.get("performance_claim", {}).get("claim_id") != "performance_results"
        or report.get("evidence_gate", {}).get("mode")
        != "release_core_signed_bootstrap"
        or not isinstance(report_signature, dict)
        or report_signature.get("profile") != "release-core"
        or report_signature.get("verified") is not True
        or report_signature.get("manifest_sha256")
        != sha256_file(CORE_MANIFEST_PATH)
        or report_signature.get("public_key_fingerprint_sha256")
        != core_fingerprint
        or not isinstance(artifacts, list)
        or len(artifacts) != len(FORMAL_SUMMARIES)
    ):
        raise ValueError("competition report is not release-valid")
    if report.get("claims_gate", {}).get("manifest_sha256") != sha256_file(
        ROOT / "configs" / "claims_manifest.v1.json"
    ):
        raise ValueError("competition report claims manifest hash mismatch")
    benchmark_ids = {
        "SepMark": "sepmark",
        "WaveGuard": "waveguard_full",
        "LIDMark": "lidmark",
        "KAD-Net": "kadnet",
    }
    metric_tokens = ("accuracy", "ber", "success_rate", "psnr", "ssim")
    expected_artifacts: list[dict[str, Any]] = []
    expected_performance_rows: list[dict[str, Any]] = []
    for method, summary_path in FORMAL_SUMMARIES.items():
        summary = formal_summaries[method]
        benchmark_id = benchmark_ids[method]
        metric_rows: list[dict[str, Any]] = []
        for attack, values in sorted(summary.get("attacks", {}).items()):
            if not isinstance(values, dict):
                raise ValueError(f"competition report attack record is invalid: {method}")
            for metric, raw_value in sorted(values.items()):
                if not any(token in metric.lower() for token in metric_tokens):
                    continue
                if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                    continue
                value = float(raw_value)
                if not math.isfinite(value):
                    raise ValueError("competition report contains a non-finite metric")
                metric_rows.append({
                    "benchmark": benchmark_id,
                    "attack": str(attack),
                    "metric": str(metric),
                    "value": value,
                })
        sample_count = summary.get("num_images") or summary.get("sample_count")
        artifact = {
            "benchmark": benchmark_id,
            "summary_path": _relative(summary_path),
            "summary_sha256": sha256_file(summary_path),
            "checkpoint_sha256": summary.get("checkpoint_sha256"),
            "dataset_manifest_sha256": summary.get("dataset_manifest_sha256"),
            "protocol_version": summary.get("protocol_version"),
            "sample_count": sample_count,
            "metric_count": len(metric_rows),
        }
        expected_artifacts.append(artifact)
        expected_performance_rows.extend({**row, **artifact} for row in metric_rows)
    if artifacts != expected_artifacts:
        raise ValueError("competition report artifacts do not match formal summaries")
    if report.get("performance_results") != expected_performance_rows:
        raise ValueError("competition report metrics do not match formal summaries")
    report_fields = [
        "benchmark", "attack", "metric", "value", "sample_count",
        "summary_path", "summary_sha256", "checkpoint_sha256",
        "dataset_manifest_sha256", "protocol_version",
    ]
    if not _csv_matches_records(
        REPORTS / "jianyuanshield_competition_report" / "report.csv",
        "competition report CSV",
        fields=report_fields,
        records=expected_performance_rows,
    ):
        raise ValueError("competition report CSV does not match report JSON")
    if not (REPORTS / "jianyuanshield_competition_report" / "report.md").read_text(
        encoding="utf-8"
    ).strip():
        raise ValueError("competition report Markdown is empty")

    snapshot = _json_object(REPORTS / "release_snapshot.json", "release snapshot")
    git = snapshot.get("git")
    if (
        snapshot.get("schema_version") != "release_snapshot.v1"
        or snapshot.get("release_ready") is not True
        or not isinstance(git, dict)
        or git.get("status_available") is not True
        or git.get("dirty") is not False
        or not isinstance(git.get("commit"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", git["commit"])
    ):
        raise ValueError("release snapshot is not clean and release-ready")
    from scripts.create_release_snapshot import git_snapshot, tracked_report_files

    current_git = git_snapshot()
    if (
        current_git.get("status_available") is not True
        or current_git.get("dirty") is not False
        or current_git.get("commit") != git.get("commit")
        or current_git.get("branch") != git.get("branch")
    ):
        raise ValueError("release snapshot does not match the current clean Git state")
    snapshot_reports = snapshot.get("reports")
    expected_snapshot_reports = tracked_report_files()
    if (
        not isinstance(snapshot_reports, dict)
        or set(snapshot_reports) != set(expected_snapshot_reports)
    ):
        raise ValueError("release snapshot report membership is not exact")
    for name, path in expected_snapshot_reports.items():
        record = snapshot_reports.get(name)
        if (
            not isinstance(record, dict)
            or record.get("exists") is not True
            or record.get("path") != _relative(path)
            or record.get("relative_path") != _relative(path)
            or record.get("size_bytes") != path.stat().st_size
            or record.get("sha256") != sha256_file(path)
        ):
            raise ValueError(f"release snapshot file binding mismatch: {name}")


def _release_evidence_files(
    profile: str = "release",
    *,
    validate: bool = True,
) -> list[Path]:
    if profile not in {"release-core", "release"}:
        raise ValueError("release evidence profile must be release-core or release")
    core_required = [
        ROOT / "configs" / "evaluation_protocol.v1.json",
        ROOT / "configs" / "claims_manifest.v1.json",
        *CORE_GATE_SOURCES,
        *COLLABORATION_POLICY_SOURCES,
        *SUPPLY_CHAIN_SOURCES,
        *(ROOT / path for path in MEA_IMPLEMENTATION_PATHS),
        *MEA_CHECKPOINT_PATHS.values(),
        *(MEA_EVIDENCE_DIR / name for name in MEA_EVIDENCE_NAMES),
        *(ROOT / path for path in SIMSWAP_IMPLEMENTATION_PATHS),
        *SIMSWAP_ENGINE_ARTIFACT_PATHS.values(),
        *(SIMSWAP_EVIDENCE_DIR / name for name in SIMSWAP_EVIDENCE_NAMES),
        *SIMSWAP_ASSET_PATHS,
        WEIGHT_ROOT / "WEIGHT_MANIFEST.json",
        *FORMAL_SUMMARIES.values(),
        *(path.parent / "progress.json" for path in FORMAL_SUMMARIES.values()),
        *FORMAL_RUNNERS.values(),
        REPORTS / "waveguard_lfw_benchmark" / "artifact_manifest.json",
        ROOT / "system" / "scripts" / "run_waveguard_lfw_small_benchmark.py",
    ]
    final_required = [
        CORE_MANIFEST_PATH,
        CORE_SIGNATURE_PATH,
        CORE_PUBLIC_KEY_PATH,
        *DERIVED_EVIDENCE_GENERATORS,
        REPORTS / "protocol_audit" / "audit.json",
        REPORTS / "protocol_audit" / "statistics.csv",
        REPORTS / "protocol_audit" / "audit.md",
        REPORTS / "statistical_analysis" / "analysis.json",
        REPORTS / "statistical_analysis" / "comparisons.csv",
        REPORTS / "aggregate_real_benchmarks" / "summary.json",
        REPORTS / "aggregate_real_benchmarks" / "method_comparison.csv",
        REPORTS / "aggregate_real_benchmarks" / "aggregate_report.md",
        ASSETS / "aggregate_real_benchmarks" / "attack_degradation.png",
        REPORTS / "jianyuanshield_competition_report" / "report.json",
        REPORTS / "jianyuanshield_competition_report" / "report.csv",
        REPORTS / "jianyuanshield_competition_report" / "report.md",
        REPORTS / "release_snapshot.json",
    ]
    required = list(
        dict.fromkeys(core_required + (final_required if profile == "release" else []))
    )
    if not validate:
        return required
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "release evidence is missing required files: "
            + ", ".join(_relative(path) for path in missing)
        )

    protocol = _json_object(required[0], "release protocol")
    protocol_attacks = [
        str(item.get("id"))
        for item in protocol.get("attacks", [])
        if isinstance(item, dict)
    ]
    protocol_seed = protocol.get("seed")
    if not protocol_attacks or not isinstance(protocol_seed, int):
        raise ValueError("release protocol is missing its frozen attack/seed contract")
    _validate_weight_manifest(WEIGHT_ROOT / "WEIGHT_MANIFEST.json")
    from scripts import supply_chain

    supply_chain_failures = supply_chain.check_outputs(ROOT)
    if supply_chain_failures:
        raise ValueError(
            "release supply-chain evidence failed validation: "
            + ", ".join(supply_chain_failures)
        )
    mea_validation = validate_mea_matrix_evidence()
    if mea_validation.get("valid") is not True:
        raise ValueError(
            "formal MEA matrix evidence failed validation: "
            + ", ".join(str(error) for error in mea_validation.get("errors", []))
        )
    simswap_validation = validate_simswap_lfw_evidence()
    if simswap_validation.get("valid") is not True:
        raise ValueError(
            "formal SimSwap/LFW n256 evidence failed validation: "
            + ", ".join(
                str(error) for error in simswap_validation.get("errors", [])
            )
        )
    from .collaboration import load_policy_evidence

    _policy, _mea_summary, collaboration_evidence, cluster_input = load_policy_evidence(
        require_signature=False
    )
    if (
        collaboration_evidence.get("content_verified") is not True
        or collaboration_evidence.get("rows") != 4096
        or collaboration_evidence.get("cells") != 16
        or cluster_input.get("image_count") != 256
        or cluster_input.get("identity_count") != 217
        or cluster_input.get("repeated_identity_count") != 24
        or cluster_input.get("images_in_repeated_identities") != 63
        or cluster_input.get("max_cluster_size") != 10
    ):
        raise ValueError("collaboration policy evidence failed validation")
    from .benchmark_evidence import benchmark_claim_status

    for expected_method, summary_path in FORMAL_SUMMARIES.items():
        summary = _json_object(summary_path, f"{expected_method} summary")
        sample_count = summary.get("num_images") or summary.get("sample_count")
        attack_metrics = summary.get("attacks")
        if (
            not isinstance(summary, dict)
            or summary.get("schema_version") != "benchmark-summary.v2"
            or summary.get("status") != "complete"
            or summary.get("method") != expected_method
            or summary.get("attack_ids") != protocol_attacks
            or summary.get("seed") != protocol_seed
            or sample_count != FORMAL_SAMPLE_COUNTS[expected_method]
            or not isinstance(attack_metrics, dict)
            or len(attack_metrics) != len(protocol_attacks)
            or set(attack_metrics) != set(protocol_attacks)
            or any(
                not isinstance(attack_metrics.get(attack_id), dict)
                or attack_metrics[attack_id].get("status") != "complete"
                or attack_metrics[attack_id].get(
                    "count", attack_metrics[attack_id].get("row_count")
                ) != sample_count
                for attack_id in protocol_attacks
            )
        ):
            raise ValueError(
                f"formal benchmark is not release-complete: {expected_method}"
            )
        required_references = {
            "checkpoint": "checkpoint_sha256",
            "dataset_manifest_path": "dataset_manifest_sha256",
            "results_csv_path": "results_csv_sha256",
            "protocol_path": "protocol_sha256",
            "run_config_path": "run_config_sha256",
            "source_manifest_path": "source_manifest_sha256",
            "checkpoint_manifest_path": "checkpoint_manifest_sha256",
            "environment_path": "environment_sha256",
            "experiment_context_hashes_path": "experiment_context_hashes_sha256",
        }
        if expected_method != "LIDMark":
            required_references["watermarked_quality_csv_path"] = (
                "watermarked_quality_csv_sha256"
            )
        if expected_method == "WaveGuard":
            required_references.update({
                "artifact_manifest_path": "artifact_manifest_sha256",
                "progress_path": "progress_sha256",
                "runner_path": "runner_sha256",
                "compatibility_entrypoint_path": (
                    "compatibility_entrypoint_sha256"
                ),
            })
        for path_field, hash_field in required_references.items():
            candidate = _resolve_manifest_reference(summary.get(path_field))
            expected_hash = summary.get(hash_field)
            if (
                candidate is None
                or not candidate.is_file()
                or not isinstance(expected_hash, str)
                or sha256_file(candidate) != expected_hash.lower()
            ):
                raise ValueError(
                    f"formal benchmark reference is invalid: "
                    f"{expected_method}.{path_field}"
                )

        results_path = _resolve_manifest_reference(summary.get("results_csv_path"))
        if results_path is None:
            raise ValueError(f"formal benchmark result path is invalid: {expected_method}")
        scientific = benchmark_claim_status(
            summary,
            summary_path=summary_path,
            results_path=results_path,
        )
        requirements = scientific.get("evidence_requirements")
        if not isinstance(requirements, dict):
            raise ValueError(f"formal benchmark audit is unavailable: {expected_method}")
        ignored = (
            {"signature_verified", "signature_covers_artifacts", "signer_pinned"}
            if profile == "release-core"
            else set()
        )
        failed = sorted(
            name
            for name, passed in requirements.items()
            if name not in ignored and passed is not True
        )
        if failed:
            raise ValueError(
                f"formal benchmark scientific gate failed: {expected_method}: "
                + ", ".join(failed)
            )
        _validate_progress(
            summary_path.parent / "progress.json",
            expected_method,
            sample_count,
            len(protocol_attacks),
        )

    if profile == "release":
        _validate_final_release_outputs()
    return required


def default_evidence_files(
    profile: str = "release",
    *,
    validate: bool = True,
) -> list[Path]:
    """Return the fixed core or final four-model release membership set."""

    return _release_evidence_files(profile, validate=validate)


def _referenced_weight_paths(manifest_paths: Iterable[Path]) -> dict[Path, str]:
    """Bind each approved checkpoint and calibration artifact to the signature."""

    references: dict[Path, str] = {}
    weight_root = WEIGHT_ROOT.resolve()
    for manifest_path in manifest_paths:
        if manifest_path.name != "WEIGHT_MANIFEST.json" or not manifest_path.is_file():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
            continue
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field, role in (
                ("file", "checkpoint"),
                ("calibration_artifact", "calibration"),
            ):
                value = item.get(field)
                if not isinstance(value, str) or not value:
                    continue
                raw = Path(value)
                if raw.is_absolute() or ".." in raw.parts:
                    continue
                candidate = (weight_root / raw).resolve()
                try:
                    candidate.relative_to(weight_root)
                except ValueError:
                    continue
                if candidate.is_file():
                    references[candidate] = role
    return references


def _resolve_manifest_reference(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    raw = Path(value)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    if raw.parts and raw.parts[0] in {"data", "weights", "reports", "assets", "model-sources"}:
        return resolve_logical_path(raw)
    candidate = (ROOT / raw).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return candidate


def _referenced_evidence_paths(summary_paths: Iterable[Path]) -> dict[Path, str]:
    references: dict[Path, str] = {}
    reference_fields = {
        "checkpoint": "checkpoint",
        "dataset_manifest_path": "dataset_manifest",
        "results_csv_path": "raw_results",
        "protocol_path": "protocol",
        "watermarked_quality_csv_path": "raw_quality_results",
        "run_config_path": "run_configuration",
        "failures_csv_path": "raw_failures",
        "calibration_path": "calibration",
        "source_manifest_path": "source_manifest",
        "checkpoint_manifest_path": "checkpoint_manifest",
        "environment_path": "environment_manifest",
        "experiment_context_hashes_path": "context_hashes",
        "artifact_manifest_path": "artifact_manifest",
        "progress_path": "progress",
        "runner_path": "evaluation_runner",
        "compatibility_entrypoint_path": "compatibility_entrypoint",
        "selection_report_path": "checkpoint_selection",
    }
    for path in summary_paths:
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        metadata = payload.get("run_metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        for field, role in reference_fields.items():
            candidate = _resolve_manifest_reference(payload.get(field) or metadata.get(field))
            if candidate and candidate.is_file():
                references[candidate.resolve()] = role
    return references


def _expanded_evidence_roles(evidence_files: Iterable[Path]) -> dict[Path, str]:
    roles: dict[Path, str] = {
        path.expanduser().resolve(): "evidence" for path in evidence_files
    }
    roles.update(_referenced_evidence_paths(roles))
    roles.update(_referenced_weight_paths(roles))
    for checkpoint in MEA_CHECKPOINT_PATHS.values():
        resolved = checkpoint.expanduser().resolve()
        if resolved in roles:
            roles[resolved] = "checkpoint"
    for checkpoint in SIMSWAP_ENGINE_ARTIFACT_PATHS.values():
        resolved = checkpoint.expanduser().resolve()
        if resolved in roles:
            roles[resolved] = "checkpoint"
    for asset in SIMSWAP_ASSET_PATHS:
        resolved = asset.expanduser().resolve()
        if resolved in roles:
            roles[resolved] = "visual_artifact"
    return roles


def build_evidence_manifest(
    files: Iterable[Path] | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    selected_profile = profile or ("release" if files is None else "scoped")
    if selected_profile not in {"release-core", "release", "scoped"}:
        raise ValueError("evidence profile must be release-core, release or scoped")
    if selected_profile in {"release-core", "release"} and files is not None:
        raise ValueError("release profile membership is fixed and cannot accept --file")
    if selected_profile == "scoped" and files is None:
        raise ValueError("scoped profile requires explicit files")
    selected = (
        default_evidence_files(selected_profile)
        if files is None
        else list(files)
    )
    evidence_files = [path.expanduser().resolve() for path in selected]
    if not evidence_files:
        raise ValueError("evidence manifest must contain at least one explicit file")
    missing = [path for path in evidence_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "evidence files are missing: "
            + ", ".join(_relative(path) for path in missing)
        )
    roles = _expanded_evidence_roles(evidence_files)
    ordered = sorted(roles, key=lambda path: _relative(path))
    return {
        "schema_version": "evidence-manifest.v1",
        "generated_at": int(time.time()),
        "hash_algorithm": "sha256",
        "signature_algorithm": "ed25519",
        "profile": selected_profile,
        "project_root": ".",
        "files": [
            {
                "path": _relative(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "role": roles[path],
            }
            for path in ordered
        ],
    }


def generate_private_key(path: Path) -> Path:
    path = path.expanduser()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing private key: {path}")
    key = Ed25519PrivateKey.generate()
    atomic_write_bytes(
        path,
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        mode=0o600,
    )
    return path


def _write_bundle_files(
    manifest_path: Path,
    signature_path: Path,
    public_key_path: Path,
    *,
    manifest: dict[str, Any],
    signature: bytes,
    public_key: bytes,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(manifest_path, manifest)
    atomic_write_bytes(signature_path, base64.b64encode(signature) + b"\n")
    atomic_write_bytes(public_key_path, public_key)


def _archived_core_bundle_bytes() -> tuple[bytes, bytes, bytes]:
    archive_dir = CORE_SIGNATURE_DIR.resolve(strict=True)
    try:
        archive_dir.relative_to(CORE_SIGNATURE_DIR.parent.resolve())
    except ValueError as exc:
        raise ValueError("release-core archive pointer escapes its signature root") from exc
    return (
        (archive_dir / CORE_MANIFEST_PATH.name).read_bytes(),
        (archive_dir / CORE_SIGNATURE_PATH.name).read_bytes(),
        (archive_dir / CORE_PUBLIC_KEY_PATH.name).read_bytes(),
    )


def _publish_archived_core_as_current() -> None:
    manifest_bytes, signature_bytes, public_key_bytes = _archived_core_bundle_bytes()
    atomic_write_bytes(MANIFEST_PATH, manifest_bytes)
    atomic_write_bytes(SIGNATURE_PATH, signature_bytes)
    atomic_write_bytes(PUBLIC_KEY_PATH, public_key_bytes)


def _archive_core_bundle_atomically(
    *,
    manifest: dict[str, Any],
    signature: bytes,
    public_key: bytes,
) -> None:
    """Publish a complete core trio through one atomic directory-pointer swap."""

    storage = CORE_SIGNATURE_DIR.parent
    storage.mkdir(parents=True, exist_ok=True)
    if CORE_SIGNATURE_DIR.exists() and not CORE_SIGNATURE_DIR.is_symlink():
        raise FileExistsError(
            "release-core archive path must be an atomic symlink, not a directory"
        )
    manifest_bytes = (
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    generation_name = f".release-core-{hashlib.sha256(manifest_bytes).hexdigest()}"
    generation_dir = storage / generation_name
    temporary_dir = storage / f".{generation_name}.tmp-{uuid.uuid4().hex}"
    temporary_link = storage / f".release-core-link-{uuid.uuid4().hex}"
    expected_bundle = (
        manifest_bytes,
        base64.b64encode(signature) + b"\n",
        public_key,
    )

    def require_matching_generation() -> None:
        if generation_dir.is_symlink() or not generation_dir.is_dir():
            raise FileExistsError("release-core content-address collision")
        try:
            actual = tuple(
                (generation_dir / name).read_bytes()
                for name in (
                    CORE_MANIFEST_PATH.name,
                    CORE_SIGNATURE_PATH.name,
                    CORE_PUBLIC_KEY_PATH.name,
                )
            )
        except OSError as exc:
            raise FileExistsError(
                "release-core content-address collision"
            ) from exc
        if actual != expected_bundle:
            raise FileExistsError("release-core content-address collision")

    temporary_dir.mkdir(mode=0o700)
    try:
        _write_bundle_files(
            temporary_dir / CORE_MANIFEST_PATH.name,
            temporary_dir / CORE_SIGNATURE_PATH.name,
            temporary_dir / CORE_PUBLIC_KEY_PATH.name,
            manifest=manifest,
            signature=signature,
            public_key=public_key,
        )
        candidate = verify_evidence_bundle(
            manifest_path=temporary_dir / CORE_MANIFEST_PATH.name,
            signature_path=temporary_dir / CORE_SIGNATURE_PATH.name,
            public_key_path=temporary_dir / CORE_PUBLIC_KEY_PATH.name,
        )
        if (
            candidate.get("verified") is not True
            or candidate.get("profile") != "release-core"
        ):
            raise ValueError("new release-core archive failed self-verification")
        if generation_dir.exists():
            require_matching_generation()
        else:
            try:
                os.replace(temporary_dir, generation_dir)
            except OSError:
                if not generation_dir.exists():
                    raise
                require_matching_generation()
        temporary_link.symlink_to(generation_name, target_is_directory=True)
        os.replace(temporary_link, CORE_SIGNATURE_DIR)
        _fsync_directory(storage)
    finally:
        temporary_link.unlink(missing_ok=True)
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)


def sign_evidence(
    private_key_path: Path,
    files: Iterable[Path] | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    private_key = serialization.load_pem_private_key(private_key_path.expanduser().read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private key is not Ed25519")
    selected_profile = profile or ("release" if files is None else "scoped")
    _require_pinned_release_signer(
        private_key.public_key(),
        profile=selected_profile,
    )
    if selected_profile == "release-core":
        archived = verify_evidence_bundle(
            manifest_path=CORE_MANIFEST_PATH,
            signature_path=CORE_SIGNATURE_PATH,
            public_key_path=CORE_PUBLIC_KEY_PATH,
        )
        if (
            archived.get("verified") is True
            and archived.get("profile") == "release-core"
            and archived.get("public_key_fingerprint_sha256")
            == _public_key_fingerprint(private_key.public_key())
        ):
            current = verify_evidence_bundle(
                manifest_path=MANIFEST_PATH,
                signature_path=SIGNATURE_PATH,
                public_key_path=PUBLIC_KEY_PATH,
            )
            if (
                current.get("verified") is not True
                or current.get("profile") != "release-core"
                or current.get("manifest_sha256") != archived.get("manifest_sha256")
            ):
                _publish_archived_core_as_current()
            return verify_evidence_bundle(
                manifest_path=MANIFEST_PATH,
                signature_path=SIGNATURE_PATH,
                public_key_path=PUBLIC_KEY_PATH,
            )
    manifest = build_evidence_manifest(files, profile=profile)
    signature = private_key.sign(canonical_json(manifest))
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if selected_profile == "release-core":
        _archive_core_bundle_atomically(
            manifest=manifest,
            signature=signature,
            public_key=public_bytes,
        )
    _write_bundle_files(
        MANIFEST_PATH,
        SIGNATURE_PATH,
        PUBLIC_KEY_PATH,
        manifest=manifest,
        signature=signature,
        public_key=public_bytes,
    )
    return verify_evidence_bundle(
        manifest_path=MANIFEST_PATH,
        signature_path=SIGNATURE_PATH,
        public_key_path=PUBLIC_KEY_PATH,
    )


def verify_evidence_bundle(
    *,
    manifest_path: Path = MANIFEST_PATH,
    signature_path: Path = SIGNATURE_PATH,
    public_key_path: Path = PUBLIC_KEY_PATH,
) -> dict[str, Any]:
    required = [manifest_path, signature_path, public_key_path]
    if not all(path.is_file() for path in required):
        return {
            "schema_version": "evidence-signature-status.v1",
            "status": "not_generated",
            "verified": False,
            "missing": [_relative(path) for path in required if not path.is_file()],
        }
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(
            manifest_bytes.decode("utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != "evidence-manifest.v1"
            or manifest.get("hash_algorithm") != "sha256"
            or manifest.get("signature_algorithm") != "ed25519"
            or manifest.get("profile") not in {"release-core", "release", "scoped"}
            or not isinstance(manifest.get("files"), list)
            or not manifest["files"]
        ):
            raise ValueError("invalid evidence manifest schema")
        signature = base64.b64decode(signature_path.read_text(encoding="ascii").strip(), validate=True)
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("public key is not Ed25519")
        public_key.verify(signature, canonical_json(manifest))
        mismatches = []
        seen_paths: set[str] = set()
        declared_roles: dict[str, str] = {}
        for item in manifest.get("files", []):
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"]
                or not isinstance(item.get("sha256"), str)
                or not _SHA256_RE.fullmatch(item["sha256"])
                or not isinstance(item.get("size_bytes"), int)
                or isinstance(item.get("size_bytes"), bool)
                or item["size_bytes"] < 0
                or not isinstance(item.get("role"), str)
                or not item["role"]
            ):
                mismatches.append({"path": None, "expected": None, "actual": "invalid_record"})
                continue
            reference = item["path"]
            if reference in seen_paths:
                mismatches.append({"path": reference, "expected": "unique", "actual": "duplicate"})
                continue
            seen_paths.add(reference)
            declared_roles[reference] = item["role"]
            path = _resolve_manifest_reference(reference)
            if path is None:
                mismatches.append({"path": reference, "expected": item.get("sha256"), "actual": "invalid_path"})
                continue
            actual = sha256_file(path) if path.is_file() else None
            actual_size = path.stat().st_size if path.is_file() else None
            if actual != item.get("sha256") or actual_size != item.get("size_bytes"):
                mismatches.append({
                    "path": reference,
                    "expected": item.get("sha256"),
                    "actual": actual,
                    "expected_size_bytes": item.get("size_bytes"),
                    "actual_size_bytes": actual_size,
                })
        if manifest.get("profile") in {"release-core", "release"}:
            try:
                release_roles = {
                    _relative(path): role
                    for path, role in _expanded_evidence_roles(
                        default_evidence_files(
                            str(manifest["profile"]), validate=False
                        )
                    ).items()
                }
            except (
                AttributeError,
                OSError,
                UnicodeError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                mismatches.append({
                    "path": None,
                    "expected": "release_membership_resolvable",
                    "actual": exc.__class__.__name__,
                })
            else:
                release_paths = set(release_roles)
                missing_members = sorted(release_paths - seen_paths)
                extra_members = sorted(seen_paths - release_paths)
                mismatches.extend(
                    {
                        "path": path,
                        "expected": "release_membership",
                        "actual": "missing_from_manifest",
                    }
                    for path in missing_members
                )
                mismatches.extend(
                    {
                        "path": path,
                        "expected": "fixed_release_membership",
                        "actual": "unexpected_manifest_member",
                    }
                    for path in extra_members
                )
                mismatches.extend(
                    {
                        "path": path,
                        "expected": release_roles[path],
                        "actual": declared_roles.get(path),
                    }
                    for path in sorted(release_paths & seen_paths)
                    if declared_roles.get(path) != release_roles[path]
                )
        fingerprint = _public_key_fingerprint(public_key)
        signer_pinned: bool | None = None
        if manifest.get("profile") in {"release-core", "release"}:
            from .settings import settings

            configured = (
                settings.evidence_public_key_fingerprint or ""
            ).strip().lower()
            signer_pinned = bool(
                _SHA256_RE.fullmatch(configured)
                and hmac.compare_digest(configured, fingerprint)
            )
            if not signer_pinned:
                mismatches.append({
                    "path": None,
                    "expected": "pinned_release_signer",
                    "actual": fingerprint,
                })
        return {
            "schema_version": "evidence-signature-status.v1",
            "status": "verified" if not mismatches else "content_mismatch",
            "verified": not mismatches,
            "signature_valid": True,
            "file_count": len(manifest.get("files", [])),
            "profile": manifest.get("profile"),
            "mismatches": mismatches,
            "public_key_fingerprint_sha256": fingerprint,
            "signer_pinned": signer_pinned,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "manifest_path": _relative(manifest_path),
            "signature_path": _relative(signature_path),
            "public_key_path": _relative(public_key_path),
        }
    except (
        AttributeError,
        InvalidSignature,
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        return {
            "schema_version": "evidence-signature-status.v1",
            "status": "invalid_signature",
            "verified": False,
            "signature_valid": False,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
