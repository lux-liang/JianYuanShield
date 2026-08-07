from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .artifacts import artifacts_status_payload
from .benchmark_evidence import benchmark_claim_status
from .config import REPORTS, ROOT
from .mea_evidence import MEA_EVIDENCE_DIR, validate_mea_matrix_evidence
from .signing import verify_evidence_bundle
from .claims import claims_payload
from .utils import load_json
from system.evaluation.protocol import protocol_summary


def _public_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return path.name


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_file(path: Path) -> dict[str, Any]:
    return {
        "path": _public_path(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
        "sha256": sha256_file(path),
    }


def _clean_accuracy(summary: dict[str, Any], key: str = "mean_bit_accuracy") -> float | None:
    value = summary.get("attacks", {}).get("clean", {}).get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evidence_audit_payload() -> dict[str, Any]:
    summaries = {
        "sepmark": REPORTS / "sepmark_lfw_benchmark" / "summary.json",
        "waveguard_full": REPORTS / "waveguard_lfw_benchmark" / "summary.json",
        "lidmark": REPORTS / "lidmark_lfw_identity_test_epoch20_protocol_v1" / "summary.json",
        "kadnet": REPORTS / "kadnet_lfw_benchmark" / "summary.json",
        "aggregate": REPORTS / "aggregate_real_benchmarks" / "summary.json",
        "competition_report": REPORTS / "jianyuanshield_competition_report" / "report.json",
    }
    payloads = {name: load_json(path, default={}) for name, path in summaries.items()}
    hidden_summary = load_json(
        REPORTS / "hidden_lfw_full_benchmark" / "summary.json",
        default={},
    )
    protocol_audit_path = REPORTS / "protocol_audit" / "audit.json"
    protocol_audit = load_json(protocol_audit_path, default={})
    hidden_diagnostic_path = REPORTS / "diagnostics" / "hidden" / "diagnostic.json"
    waveguard_diagnostic_path = REPORTS / "diagnostics" / "waveguard" / "diagnostic.json"
    hidden_diagnostic = load_json(hidden_diagnostic_path, default={})
    waveguard_diagnostic = load_json(waveguard_diagnostic_path, default={})
    lidmark_training_path = REPORTS / "lidmark_training" / "readiness.json"
    kadnet_integration_path = REPORTS / "kadnet_integration" / "audit.json"
    lidmark_training = load_json(lidmark_training_path, default={})
    kadnet_integration = load_json(kadnet_integration_path, default={})
    mea_validation = validate_mea_matrix_evidence(require_signature=True)
    findings: list[dict[str, str]] = []

    hidden_acc = _clean_accuracy(hidden_summary)
    if hidden_acc is not None and 0.45 <= hidden_acc <= 0.55:
        findings.append({
            "severity": "info",
            "code": "hidden_near_random",
            "message": (
                f"HiDDeN clean bit accuracy is {hidden_acc:.4f}; diagnostic conclusion="
                f"{hidden_diagnostic.get('conclusion', 'not_generated')}."
            ),
        })

    waveguard_acc = _clean_accuracy(payloads["waveguard_full"], "mean_bit_accuracy_detector")
    if waveguard_acc is not None and waveguard_acc >= 0.999:
        findings.append({
            "severity": "info",
            "code": "waveguard_saturation",
            "message": (
                f"WaveGuard clean detector accuracy is {waveguard_acc:.4f}; diagnostic conclusion="
                f"{waveguard_diagnostic.get('conclusion', 'not_generated')}."
            ),
        })

    if lidmark_training.get("status") == "blocked":
        findings.append({
            "severity": "info",
            "code": "lidmark_training_blocked",
            "message": "LIDMark validation remains blocked until checkpoint, dataset manifest and raw result evidence pass the release gate.",
        })

    if kadnet_integration.get("status") == "blocked":
        findings.append({
            "severity": "info",
            "code": "kadnet_integration_blocked",
            "message": "KAD-Net integration is blocked by missing checkpoint and compatibility requirements.",
        })

    if mea_validation.get("valid") is not True:
        findings.append({
            "severity": "warning",
            "code": "mea_matrix_evidence_unverified",
            "message": "The canonical MEA 4x4 n256 evidence bundle has not passed its signed hash-closure gate.",
        })

    if protocol_audit.get("status") != "verified":
        findings.append({
            "severity": "warning",
            "code": "protocol_audit_incomplete",
            "message": f"Protocol audit status is {protocol_audit.get('status', 'not_generated')}.",
        })

    if protocol_audit.get("interpretation_limits"):
        findings.append({
            "severity": "warning",
            "code": "legacy_protocol_results",
            "message": "Legacy benchmark outputs require a fair rerun before cross-model quality claims.",
        })

    result_paths = {
        "sepmark": REPORTS / "sepmark_lfw_benchmark" / "results.csv",
        "waveguard_full": REPORTS / "waveguard_lfw_benchmark" / "results.csv",
        "lidmark": REPORTS / "lidmark_lfw_identity_test_epoch20_protocol_v1" / "raw_results.csv",
        "kadnet": REPORTS / "kadnet_lfw_benchmark" / "results.csv",
    }
    benchmark_validation: dict[str, dict[str, Any]] = {}
    complete: dict[str, bool] = {}
    for name, results_path in result_paths.items():
        validation = benchmark_claim_status(
            payloads[name],
            summary_path=summaries[name],
            results_path=results_path,
        )
        benchmark_validation[name] = validation
        complete[name] = validation["claim_valid"] is True
        if not complete[name]:
            failed = [
                requirement
                for requirement, passed in validation.get("evidence_requirements", {}).items()
                if not passed
            ]
            findings.append({
                "severity": "warning",
                "code": f"{name}_benchmark_evidence_incomplete",
                "message": "failed requirements: " + ", ".join(failed),
            })
    frozen_protocol = protocol_summary()
    protocol = {
        "dataset": "LFW evaluation target; validated sample count must come from a signed dataset manifest",
        "schema_version": frozen_protocol["schema_version"],
        "attacks": frozen_protocol["attack_ids"],
        "known_limitations": [
            "LIDMark uses its frozen identity-disjoint 128px test split; cross-model paired statistics are emitted only where image IDs overlap.",
            "Current confidence intervals quantify image-sampling uncertainty from one frozen run per method.",
            "deepfake_proxy_v1 is a reproducible protocol transform and is not evidence of robustness against every real generative editor.",
        ],
    }
    diagnostics_complete = {
        "hidden": hidden_diagnostic.get("status") == "complete",
        "waveguard": waveguard_diagnostic.get("status") == "complete",
    }
    for name, is_complete in diagnostics_complete.items():
        if not is_complete:
            findings.append({
                "severity": "info",
                "code": f"{name}_diagnostic_incomplete",
                "message": f"{name} diagnostic is not complete.",
            })

    signature = verify_evidence_bundle()
    if not signature.get("verified"):
        findings.append({
            "severity": "warning",
            "code": "evidence_signature_unverified",
            "message": f"Evidence signature status is {signature.get('status', 'not_generated')}.",
        })

    claims = claims_payload()
    if not claims.get("ready_for_claims"):
        findings.append({
            "severity": "warning",
            "code": "claims_manifest_review_required",
            "message": (
                f"Machine-readable claims gate has "
                f"{claims.get('summary', {}).get('blocked_required', 0)} blocked required claims."
            ),
        })

    blocking_findings = [
        item for item in findings
        if item.get("severity") in {"warning", "error", "critical"}
    ]
    ready_for_demo = bool(artifacts_status_payload().get("ready_for_demo"))
    ready_for_claims = (
        ready_for_demo
        and all(complete.values())
        and protocol_audit.get("status") == "verified"
        and signature.get("verified") is True
        and claims.get("ready_for_claims") is True
        and not blocking_findings
    )
    return {
        "schema_version": "evidence-audit.v1",
        "status": "verified" if ready_for_claims else "review_required",
        "ready_for_demo": ready_for_demo,
        "ready_for_claims": ready_for_claims,
        "benchmark_complete": complete,
        "benchmark_validation": benchmark_validation,
        "protocol": protocol,
        "findings": findings,
        "blocking_findings": blocking_findings,
        "signature": signature,
        "claims": claims,
        "evidence_files": {name: evidence_file(path) for name, path in summaries.items()},
        "protocol_audit": {
            "status": protocol_audit.get("status", "not_generated"),
            "path": _public_path(protocol_audit_path),
            "exists": protocol_audit_path.is_file(),
            "findings": protocol_audit.get("findings", []),
        },
        "diagnostics": {
            "hidden": {
                "exists": hidden_diagnostic_path.is_file(),
                "path": _public_path(hidden_diagnostic_path),
                "status": hidden_diagnostic.get("status", "not_generated"),
                "conclusion": hidden_diagnostic.get("conclusion"),
            },
            "waveguard": {
                "exists": waveguard_diagnostic_path.is_file(),
                "path": _public_path(waveguard_diagnostic_path),
                "status": waveguard_diagnostic.get("status", "not_generated"),
                "conclusion": waveguard_diagnostic.get("conclusion"),
            },
        },
        "integration_gates": {
            "lidmark_training": {
                "status": lidmark_training.get("status", "not_generated"),
                "path": _public_path(lidmark_training_path),
                "blockers": lidmark_training.get("blockers", []),
            },
            "kadnet": {
                "status": kadnet_integration.get("status", "not_generated"),
                "path": _public_path(kadnet_integration_path),
                "blockers": kadnet_integration.get("blockers", []),
            },
            "multi_embedding": {
                "status": mea_validation.get("status", "review_required"),
                "path": _public_path(MEA_EVIDENCE_DIR),
                "run_id": mea_validation.get("run_id"),
                "row_count": mea_validation.get("row_count"),
                "cell_count": mea_validation.get("cell_count"),
                "validation": mea_validation,
            },
        },
    }
