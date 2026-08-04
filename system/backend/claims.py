from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .benchmark_evidence import benchmark_claim_status
from .collaboration import load_policy_evidence
from .config import ROOT
from .mea_evidence import MEA_RUN_ID, validate_mea_matrix_evidence
from .simswap_evidence import (
    SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE,
    SIMSWAP_RUN_ID,
    validate_simswap_lfw_evidence,
)
from .signing import sha256_file
from system.evaluation.runtime import resolve_logical_path


CLAIMS_MANIFEST = ROOT / "configs" / "claims_manifest.v1.json"
CLAIMS_SCHEMA_VERSION = "claims-manifest.v1"
PERFORMANCE_CLAIM_ID = "performance_results"
PUBLISHABLE_STATUSES = {"implemented", "verified", "publishable"}


FORMAL_BENCHMARKS: dict[str, dict[str, Any]] = {
    "lidmark": {
        "method": "LIDMark",
        "summary_path": (
            "reports/lidmark_lfw_identity_test_epoch20_protocol_v1/summary.json"
        ),
        "results_path": (
            "reports/lidmark_lfw_identity_test_epoch20_protocol_v1/raw_results.csv"
        ),
        "sample_count": 1324,
    },
    "kadnet": {
        "method": "KAD-Net",
        "summary_path": "reports/kadnet_lfw_benchmark/summary.json",
        "results_path": "reports/kadnet_lfw_benchmark/results.csv",
        "sample_count": 13233,
    },
    "sepmark": {
        "method": "SepMark",
        "summary_path": "reports/sepmark_lfw_benchmark/summary.json",
        "results_path": "reports/sepmark_lfw_benchmark/results.csv",
        "sample_count": 13233,
    },
    "waveguard_full": {
        "method": "WaveGuard",
        "summary_path": "reports/waveguard_lfw_benchmark/summary.json",
        "results_path": "reports/waveguard_lfw_benchmark/results.csv",
        "sample_count": 13233,
    },
}

SIMSWAP_N256_HOLDOUT_METRICS = {
    "LIDMark": {
        "tar": 0.8125,
        "tar_wilson_95_low": 0.75136283,
        "far": 0.23611111,
        "far_wilson_95_high": 0.27247097,
    },
    "KAD-Net": {
        "tar": 0.99479167,
        "tar_wilson_95_low": 0.9710925,
        "far": 0.0,
        "far_wilson_95_high": 0.00662502,
    },
    "SepMark": {
        "tar": 0.94791667,
        "tar_wilson_95_low": 0.90679489,
        "far": 0.01215278,
        "far_wilson_95_high": 0.02487054,
    },
    "WaveGuard": {
        "tar": 0.546875,
        "tar_wilson_95_low": 0.47623085,
        "far": 0.57465278,
        "far_wilson_95_high": 0.61440217,
    },
}
SIMSWAP_N256_FAR_BY_NEGATIVE_CONTROL = {
    "LIDMark": {
        "unwatermarked": {
            "successes": 46,
            "total": 192,
            "estimate": 0.23958333,
            "wilson_95_low": 0.18469443,
            "wilson_95_high": 0.30468846,
        },
        "wrong_message": {
            "successes": 48,
            "total": 192,
            "estimate": 0.25,
            "wilson_95_low": 0.19406065,
            "wilson_95_high": 0.31574692,
        },
        "cross_record": {
            "successes": 42,
            "total": 192,
            "estimate": 0.21875,
            "wilson_95_low": 0.16610636,
            "wilson_95_high": 0.28242716,
        },
    },
    "KAD-Net": {
        control: {
            "successes": 0,
            "total": 192,
            "estimate": 0.0,
            "wilson_95_low": 0.0,
            "wilson_95_high": 0.01961515,
        }
        for control in ("unwatermarked", "wrong_message", "cross_record")
    },
    "SepMark": {
        "unwatermarked": {
            "successes": 0,
            "total": 192,
            "estimate": 0.0,
            "wilson_95_low": 0.0,
            "wilson_95_high": 0.01961515,
        },
        "wrong_message": {
            "successes": 2,
            "total": 192,
            "estimate": 0.01041667,
            "wilson_95_low": 0.00286129,
            "wilson_95_high": 0.03717854,
        },
        "cross_record": {
            "successes": 5,
            "total": 192,
            "estimate": 0.02604167,
            "wilson_95_low": 0.01117361,
            "wilson_95_high": 0.05950325,
        },
    },
    "WaveGuard": {
        "unwatermarked": {
            "successes": 117,
            "total": 192,
            "estimate": 0.609375,
            "wilson_95_low": 0.53886487,
            "wilson_95_high": 0.67559432,
        },
        "wrong_message": {
            "successes": 117,
            "total": 192,
            "estimate": 0.609375,
            "wilson_95_low": 0.53886487,
            "wilson_95_high": 0.67559432,
        },
        "cross_record": {
            "successes": 97,
            "total": 192,
            "estimate": 0.50520833,
            "wilson_95_low": 0.43508285,
            "wilson_95_high": 0.57512949,
        },
    },
}
SIMSWAP_N256_CONDITIONED_REGISTERED_POSITIVE = {
    "LIDMark": {
        "clean_swap_migrated": {
            "successes": 128,
            "total": 161,
            "estimate": 0.79503106,
            "wilson_95_low": 0.72614916,
            "wilson_95_high": 0.85016217,
        },
        "clean_and_watermarked_swap_migrated": {
            "successes": 123,
            "total": 150,
            "estimate": 0.82,
            "wilson_95_low": 0.75077672,
            "wilson_95_high": 0.87324232,
        },
    },
    "KAD-Net": {
        "clean_swap_migrated": {
            "successes": 160,
            "total": 161,
            "estimate": 0.99378882,
            "wilson_95_low": 0.96566044,
            "wilson_95_high": 0.99890273,
        },
        "clean_and_watermarked_swap_migrated": {
            "successes": 153,
            "total": 154,
            "estimate": 0.99350649,
            "wilson_95_low": 0.96413879,
            "wilson_95_high": 0.99885282,
        },
    },
    "SepMark": {
        "clean_swap_migrated": {
            "successes": 151,
            "total": 161,
            "estimate": 0.9378882,
            "wilson_95_low": 0.88945175,
            "wilson_95_high": 0.96591559,
        },
        "clean_and_watermarked_swap_migrated": {
            "successes": 150,
            "total": 159,
            "estimate": 0.94339623,
            "wilson_95_low": 0.89593484,
            "wilson_95_high": 0.96993802,
        },
    },
    "WaveGuard": {
        "clean_swap_migrated": {
            "successes": 82,
            "total": 161,
            "estimate": 0.50931677,
            "wilson_95_low": 0.43278442,
            "wilson_95_high": 0.58541488,
        },
        "clean_and_watermarked_swap_migrated": {
            "successes": 78,
            "total": 156,
            "estimate": 0.5,
            "wilson_95_low": 0.42248721,
            "wilson_95_high": 0.57751279,
        },
    },
}
SIMSWAP_N256_IDENTITY_MIGRATION = {
    "clean_swap_estimate": 0.83854167,
    "clean_swap_wilson_95_low": 0.77994169,
}


def _json_exact_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(
            left,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) == json.dumps(
            right,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _evaluate_benchmark_gate(
    gate: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one gate from one summary read and detect concurrent replacement."""

    summary_reference = gate.get("summary_path")
    results_reference = gate.get("results_path")
    if not isinstance(summary_reference, str) or not isinstance(results_reference, str):
        return ({
            "claim_valid": False,
            "claim_status": "benchmark_gate_invalid",
            "error": "summary_path and results_path must be strings",
        }, {})
    summary_path = resolve_logical_path(summary_reference)
    results_path = resolve_logical_path(results_reference)
    if (
        summary_path is None
        or results_path is None
        or not summary_path.is_file()
        or not results_path.is_file()
    ):
        return ({
            "claim_valid": False,
            "claim_status": "benchmark_artifacts_missing",
            "summary_path": summary_reference,
            "results_path": results_reference,
            "summary_exists": bool(summary_path and summary_path.is_file()),
            "results_exists": bool(results_path and results_path.is_file()),
        }, {})
    try:
        summary_identity = _file_identity(summary_path)
        results_identity = _file_identity(results_path)
        summary_bytes = summary_path.read_bytes()
        summary = json.loads(
            summary_bytes.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return ({
            "claim_valid": False,
            "claim_status": "benchmark_summary_invalid",
            "summary_path": summary_reference,
            "results_path": results_reference,
            "error": exc.__class__.__name__,
        }, {})
    if not isinstance(summary, dict):
        return ({
            "claim_valid": False,
            "claim_status": "benchmark_summary_invalid",
            "summary_path": summary_reference,
            "results_path": results_reference,
            "error": "summary must be an object",
        }, {})
    try:
        result = benchmark_claim_status(
            summary,
            summary_path=summary_path,
            results_path=results_path,
        )
        stable = (
            _file_identity(summary_path) == summary_identity
            and _file_identity(results_path) == results_identity
            and sha256_file(summary_path) == hashlib.sha256(summary_bytes).hexdigest()
        )
    except Exception as exc:
        return ({
            "claim_valid": False,
            "claim_status": "benchmark_gate_error",
            "summary_path": summary_reference,
            "results_path": results_reference,
            "error": exc.__class__.__name__,
        }, summary)
    if not stable:
        return ({
            "claim_valid": False,
            "claim_status": "benchmark_artifacts_changed_during_validation",
            "summary_path": summary_reference,
            "results_path": results_reference,
        }, summary)
    return result, summary


def _benchmark_gate_result(gate: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one benchmark gate without trusting manifest-provided metadata."""

    result, _summary = _evaluate_benchmark_gate(gate)
    return result


def _benchmark_evidence_set_result(gate: dict[str, Any]) -> dict[str, Any]:
    """Require the complete, canonical four-method competition evidence set."""

    configured = gate.get("benchmarks")
    expected_ids = list(FORMAL_BENCHMARKS)
    configuration_errors: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    if not isinstance(configured, list):
        configured = []
        configuration_errors.append("benchmarks must be a list")
    for index, item in enumerate(configured):
        if not isinstance(item, dict):
            configuration_errors.append(f"benchmarks[{index}] must be an object")
            continue
        benchmark_id = item.get("benchmark_id")
        if not isinstance(benchmark_id, str) or not benchmark_id:
            configuration_errors.append(
                f"benchmarks[{index}].benchmark_id must be a non-empty string"
            )
            continue
        if benchmark_id in records:
            configuration_errors.append(f"duplicate benchmark_id: {benchmark_id}")
            continue
        records[benchmark_id] = item

    configured_ids = set(records)
    expected_id_set = set(expected_ids)
    for benchmark_id in sorted(expected_id_set - configured_ids):
        configuration_errors.append(f"missing formal benchmark: {benchmark_id}")
    for benchmark_id in sorted(configured_ids - expected_id_set):
        configuration_errors.append(f"unexpected formal benchmark: {benchmark_id}")

    benchmark_results: dict[str, dict[str, Any]] = {}
    for benchmark_id in expected_ids:
        expected = FORMAL_BENCHMARKS[benchmark_id]
        item = records.get(benchmark_id)
        if item is None:
            benchmark_results[benchmark_id] = {
                "claim_valid": False,
                "claim_status": "benchmark_gate_missing",
            }
            continue
        path_contract = (
            item.get("summary_path") == expected["summary_path"]
            and item.get("results_path") == expected["results_path"]
        )
        if not path_contract:
            configuration_errors.append(
                f"non-canonical paths for formal benchmark: {benchmark_id}"
            )
            benchmark_results[benchmark_id] = {
                "claim_valid": False,
                "claim_status": "benchmark_path_contract_mismatch",
                "path_contract": False,
                "expected_summary_path": expected["summary_path"],
                "expected_results_path": expected["results_path"],
            }
            continue

        strict_result, summary = _evaluate_benchmark_gate(item)
        sample_count = (
            summary.get("num_images")
            if "num_images" in summary
            else summary.get("sample_count")
        )
        summary_contract = {
            "schema_v2": summary.get("schema_version") == "benchmark-summary.v2",
            "complete": summary.get("status") == "complete",
            "method": summary.get("method") == expected["method"],
            "sample_count": sample_count == expected["sample_count"],
        }
        strict_valid = strict_result.get("claim_valid") is True
        summary_valid = all(summary_contract.values())
        combined_valid = strict_valid and summary_valid
        if not strict_valid:
            member_status = strict_result.get(
                "claim_status",
                "benchmark_evidence_invalid",
            )
        elif not summary_valid:
            member_status = "benchmark_summary_contract_mismatch"
        else:
            member_status = strict_result.get("claim_status", "evidence_verified")
        benchmark_results[benchmark_id] = {
            **strict_result,
            "claim_valid": combined_valid,
            "claim_status": member_status,
            "path_contract": True,
            "summary_contract": summary_contract,
            "expected_method": expected["method"],
            "expected_sample_count": expected["sample_count"],
        }

    failed = [
        benchmark_id
        for benchmark_id in expected_ids
        if benchmark_results.get(benchmark_id, {}).get("claim_valid") is not True
    ]
    claim_valid = not configuration_errors and not failed
    return {
        "schema_version": "benchmark-evidence-set-status.v1",
        "claim_valid": claim_valid,
        "claim_status": (
            "evidence_set_verified" if claim_valid else "evidence_set_review_required"
        ),
        "expected_benchmark_ids": expected_ids,
        "configuration_valid": not configuration_errors,
        "configuration_errors": configuration_errors,
        "failed_benchmarks": failed,
        "benchmarks": benchmark_results,
    }


def _mea_matrix_evidence_result(gate: dict[str, Any]) -> dict[str, Any]:
    """Evaluate only the canonical formal n256 MEA matrix and its signature."""

    expected_directory = f"reports/{MEA_RUN_ID}"
    if (
        gate.get("run_id") != MEA_RUN_ID
        or gate.get("directory_path") != expected_directory
        or set(gate) != {"type", "run_id", "directory_path"}
    ):
        return {
            "schema_version": "mea-matrix-claim-status.v1",
            "claim_valid": False,
            "claim_status": "mea_gate_contract_mismatch",
            "expected_run_id": MEA_RUN_ID,
            "expected_directory_path": expected_directory,
        }
    validation = validate_mea_matrix_evidence(require_signature=True)
    valid = validation.get("valid") is True
    return {
        "schema_version": "mea-matrix-claim-status.v1",
        "claim_valid": valid,
        "claim_status": (
            "evidence_verified" if valid else "mea_evidence_review_required"
        ),
        "validation": validation,
    }


def _collaboration_policy_evidence_result(gate: dict[str, Any]) -> dict[str, Any]:
    """Require the canonical policy and the signed MEA evidence it consumes."""

    expected_policy_id = "mea-identity-cluster-deployment-s20260603"
    if (
        gate.get("policy_id") != expected_policy_id
        or set(gate) != {"type", "policy_id"}
    ):
        return {
            "schema_version": "collaboration-policy-claim-status.v2",
            "claim_valid": False,
            "claim_status": "collaboration_policy_gate_contract_mismatch",
            "expected_policy_id": expected_policy_id,
        }
    try:
        config, _summary, evidence, cluster_input = load_policy_evidence()
    except Exception as exc:
        return {
            "schema_version": "collaboration-policy-claim-status.v2",
            "claim_valid": False,
            "claim_status": "collaboration_policy_evidence_review_required",
            "error": exc.__class__.__name__,
        }
    mea_validation = evidence.get("matrix_validation", {})
    valid = bool(
        config.get("policy_id") == expected_policy_id
        and evidence.get("content_verified") is True
        and evidence.get("cells") == 16
        and evidence.get("rows") == 4096
        and evidence.get("signature_verified") is True
        and evidence.get("signer_pinned") is True
        and evidence.get("image_count") == 256
        and evidence.get("identity_count") == 217
        and evidence.get("repeated_identity_count") == 24
        and evidence.get("images_in_repeated_identities") == 63
        and evidence.get("max_cluster_size") == 10
        and cluster_input.get("image_count") == 256
        and cluster_input.get("identity_count") == 217
        and cluster_input.get("repeated_identity_count") == 24
        and cluster_input.get("images_in_repeated_identities") == 63
        and cluster_input.get("max_cluster_size") == 10
        and mea_validation.get("valid") is True
    )
    return {
        "schema_version": "collaboration-policy-claim-status.v2",
        "claim_valid": valid,
        "claim_status": (
            "evidence_verified"
            if valid
            else "collaboration_policy_evidence_review_required"
        ),
        "policy_id": expected_policy_id,
        "evidence": evidence,
        "mea_validation": mea_validation,
    }


def _simswap_lfw_evidence_result(gate: dict[str, Any]) -> dict[str, Any]:
    """Require the exact signed official-SimSwap/LFW n256 scoped evidence."""

    expected = {
        "type": "simswap_lfw_evidence.v1",
        "run_id": SIMSWAP_RUN_ID,
        "directory_path": f"reports/{SIMSWAP_RUN_ID}",
        "num_pairs": 256,
        "calibration_pairs": 64,
        "holdout_pairs": 192,
        "holdout_metrics": SIMSWAP_N256_HOLDOUT_METRICS,
        "far_by_negative_control": SIMSWAP_N256_FAR_BY_NEGATIVE_CONTROL,
        "identity_migration": SIMSWAP_N256_IDENTITY_MIGRATION,
        "identity_migration_evidence_scope": (
            SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE
        ),
        "registered_positive_conditioned_on_identity_migration": (
            SIMSWAP_N256_CONDITIONED_REGISTERED_POSITIVE
        ),
    }
    if not _json_exact_equal(gate, expected):
        return {
            "schema_version": "simswap-lfw-claim-status.v1",
            "claim_valid": False,
            "claim_status": "simswap_gate_contract_mismatch",
            "expected": expected,
        }
    validation = validate_simswap_lfw_evidence(require_signature=True)
    model_results = validation.get("model_results", {})
    observed_metrics = {
        model: {
            "tar": model_results.get(model, {}).get("holdout_tar", {}).get(
                "estimate"
            ),
            "tar_wilson_95_low": model_results.get(model, {}).get(
                "holdout_tar", {}
            ).get("wilson_95_low"),
            "far": model_results.get(model, {}).get("holdout_far", {}).get(
                "estimate"
            ),
            "far_wilson_95_high": model_results.get(model, {}).get(
                "holdout_far", {}
            ).get("wilson_95_high"),
        }
        for model in SIMSWAP_N256_HOLDOUT_METRICS
    }
    clean_migration = model_results.get("KAD-Net", {}).get(
        "identity_migration", {}
    ).get("clean_swap", {})
    observed_identity = {
        "clean_swap_estimate": clean_migration.get("estimate"),
        "clean_swap_wilson_95_low": clean_migration.get("wilson_95_low"),
    }
    observed_far_by_negative_control = {
        model: model_results.get(model, {}).get(
            "holdout_far_by_negative_control", {}
        )
        for model in SIMSWAP_N256_FAR_BY_NEGATIVE_CONTROL
    }
    observed_conditioned_registered_positive = {
        model: model_results.get(model, {}).get(
            "registered_positive_conditioned_on_identity_migration", {}
        )
        for model in SIMSWAP_N256_CONDITIONED_REGISTERED_POSITIVE
    }
    observed_identity_scope = validation.get("identity_migration_evidence_scope")
    valid = bool(
        validation.get("valid") is True
        and _json_exact_equal(observed_metrics, SIMSWAP_N256_HOLDOUT_METRICS)
        and _json_exact_equal(
            observed_far_by_negative_control,
            SIMSWAP_N256_FAR_BY_NEGATIVE_CONTROL,
        )
        and _json_exact_equal(
            observed_conditioned_registered_positive,
            SIMSWAP_N256_CONDITIONED_REGISTERED_POSITIVE,
        )
        and _json_exact_equal(
            observed_identity_scope,
            SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE,
        )
        and _json_exact_equal(
            observed_identity,
            SIMSWAP_N256_IDENTITY_MIGRATION,
        )
    )
    return {
        "schema_version": "simswap-lfw-claim-status.v1",
        "claim_valid": valid,
        "claim_status": (
            "evidence_verified"
            if valid
            else "simswap_evidence_review_required"
        ),
        "observed_holdout_metrics": observed_metrics,
        "observed_far_by_negative_control": observed_far_by_negative_control,
        "observed_registered_positive_conditioned_on_identity_migration": (
            observed_conditioned_registered_positive
        ),
        "observed_identity_migration_evidence_scope": observed_identity_scope,
        "observed_identity_migration": observed_identity,
        "validation": validation,
    }


def _claim_gate_result(gate: Any) -> dict[str, Any] | None:
    if gate is None:
        return None
    if not isinstance(gate, dict):
        return {"claim_valid": False, "claim_status": "unsupported_claim_gate"}
    gate_type = gate.get("type")
    if gate_type == "benchmark_evidence.v1":
        return _benchmark_gate_result(gate)
    if gate_type == "benchmark_evidence_set.v1":
        return _benchmark_evidence_set_result(gate)
    if gate_type == "mea_matrix_evidence.v1":
        return _mea_matrix_evidence_result(gate)
    if gate_type == "collaboration_policy_evidence.v2":
        return _collaboration_policy_evidence_result(gate)
    if gate_type == "simswap_lfw_evidence.v1":
        return _simswap_lfw_evidence_result(gate)
    return {"claim_valid": False, "claim_status": "unsupported_claim_gate"}


def claims_payload() -> dict[str, Any]:
    if not CLAIMS_MANIFEST.is_file():
        return {
            "schema_version": "claims-status.v1",
            "ready_for_claims": False,
            "status": "manifest_missing",
            "claims": [],
        }
    try:
        manifest_bytes = CLAIMS_MANIFEST.read_bytes()
        manifest = json.loads(
            manifest_bytes.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return {
            "schema_version": "claims-status.v1",
            "ready_for_claims": False,
            "status": "manifest_invalid",
            "error": exc.__class__.__name__,
            "claims": [],
        }
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != CLAIMS_SCHEMA_VERSION
        or not isinstance(manifest.get("policy"), dict)
        or not isinstance(manifest.get("claims"), list)
    ):
        return {
            "schema_version": "claims-status.v1",
            "ready_for_claims": False,
            "status": "manifest_invalid",
            "error": "claims manifest schema, policy or claims collection is invalid",
            "claims": [],
        }
    raw_claims = manifest["claims"]
    if (
        not all(isinstance(claim, dict) for claim in raw_claims)
        or any(
            not isinstance(claim.get("claim_id"), str)
            or not claim.get("claim_id")
            or not isinstance(claim.get("evidence"), list)
            or not all(
                isinstance(reference, str) and bool(reference)
                for reference in claim.get("evidence", [])
            )
            for claim in raw_claims
        )
        or len({claim["claim_id"] for claim in raw_claims}) != len(raw_claims)
    ):
        return {
            "schema_version": "claims-status.v1",
            "ready_for_claims": False,
            "status": "manifest_invalid",
            "error": "claims must be unique objects with string evidence paths",
            "claims": [],
        }
    performance_claim = next(
        (
            claim
            for claim in raw_claims
            if claim.get("claim_id") == PERFORMANCE_CLAIM_ID
        ),
        None,
    )
    if (
        manifest["policy"].get("performance_claim_id") != PERFORMANCE_CLAIM_ID
        or not isinstance(performance_claim, dict)
        or performance_claim.get("requested_for_submission") is not True
        or not isinstance(performance_claim.get("gate"), dict)
        or performance_claim["gate"].get("type") != "benchmark_evidence_set.v1"
    ):
        return {
            "schema_version": "claims-status.v1",
            "ready_for_claims": False,
            "status": "manifest_invalid",
            "error": "canonical performance evidence-set claim is required",
            "claims": [],
        }
    claims = []
    for claim in raw_claims:
        evidence = []
        for relative in claim.get("evidence", []):
            try:
                path = resolve_logical_path(relative)
                exists = path is not None and path.is_file()
                digest = (
                    sha256_file(path)
                    if exists and path is not None
                    else None
                )
            except Exception:
                exists = False
                digest = None
            evidence.append({
                "path": relative,
                "exists": exists,
                "sha256": digest,
            })
        evidence_complete = bool(evidence) and all(item["exists"] for item in evidence)
        status = str(claim.get("status", "review_required"))
        gate = claim.get("gate")
        try:
            gate_result = _claim_gate_result(gate)
        except Exception as exc:
            gate_result = {
                "claim_valid": False,
                "claim_status": "claim_gate_error",
                "error": exc.__class__.__name__,
            }
        gate_valid = gate_result is None or gate_result.get("claim_valid") is True
        publishable = status in PUBLISHABLE_STATUSES and evidence_complete and gate_valid
        claims.append({
            **claim,
            "evidence": evidence,
            "evidence_complete": evidence_complete,
            "gate_valid": gate_valid,
            "gate_result": gate_result,
            "publishable": publishable,
        })
    required = [claim for claim in claims if claim.get("requested_for_submission")]
    ready = bool(required) and all(claim["publishable"] for claim in required)
    return {
        "schema_version": "claims-status.v1",
        "manifest_schema_version": manifest.get("schema_version"),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "ready_for_claims": ready,
        "status": "verified" if ready else "review_required",
        "policy": manifest.get("policy", {}),
        "summary": {
            "total": len(claims),
            "required": len(required),
            "publishable": sum(1 for claim in claims if claim["publishable"]),
            "blocked_required": sum(1 for claim in required if not claim["publishable"]),
        },
        "claims": claims,
    }
