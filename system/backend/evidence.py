from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import artifacts_status_payload
from .config import REPORTS, ROOT
from .signing import verify_evidence_bundle
from .utils import load_json, sha256_file  # P2-10：sha256_file 统一实现移至 utils.py


def evidence_file(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
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
        "hidden": REPORTS / "hidden_lfw_full_benchmark" / "summary.json",
        "sepmark": REPORTS / "sepmark_lfw_benchmark" / "summary.json",
        "waveguard_full": REPORTS / "waveguard_lfw_full_benchmark" / "summary.json",
        "lidmark": ROOT / "runs" / "lidmark_lfw_eval_full" / "summary.json",
        "aggregate": REPORTS / "aggregate_real_benchmarks" / "summary.json",
        "competition_report": REPORTS / "jianyuanshield_competition_report" / "report.json",
    }
    payloads = {name: load_json(path, default={}) for name, path in summaries.items()}
    protocol_audit_path = REPORTS / "protocol_audit" / "audit.json"
    protocol_audit = load_json(protocol_audit_path, default={})
    hidden_diagnostic_path = REPORTS / "diagnostics" / "hidden" / "diagnostic.json"
    waveguard_diagnostic_path = REPORTS / "diagnostics" / "waveguard" / "diagnostic.json"
    hidden_diagnostic = load_json(hidden_diagnostic_path, default={})
    waveguard_diagnostic = load_json(waveguard_diagnostic_path, default={})
    lidmark_training_path = REPORTS / "lidmark_training" / "readiness.json"
    kadnet_integration_path = REPORTS / "kadnet_integration" / "audit.json"
    multi_embedding_path = REPORTS / "multi_embedding_matrix" / "plan.json"
    lidmark_training = load_json(lidmark_training_path, default={})
    kadnet_integration = load_json(kadnet_integration_path, default={})
    multi_embedding = load_json(multi_embedding_path, default={})
    findings: list[dict[str, str]] = []

    hidden_acc = _clean_accuracy(payloads["hidden"])
    if hidden_acc is not None and 0.45 <= hidden_acc <= 0.55:
        findings.append({
            "severity": "warning",
            "code": "hidden_near_random",
            "message": (
                f"HiDDeN clean bit accuracy is {hidden_acc:.4f}; diagnostic conclusion="
                f"{hidden_diagnostic.get('conclusion', 'not_generated')}."
            ),
        })

    waveguard_acc = _clean_accuracy(payloads["waveguard_full"], "mean_bit_accuracy_detector")
    if waveguard_acc is not None and waveguard_acc >= 0.999:
        findings.append({
            "severity": "info" if waveguard_diagnostic.get("conclusion") == "saturation_supported_by_negative_controls" else "warning",
            "code": "waveguard_saturation",
            "message": (
                f"WaveGuard clean detector accuracy is {waveguard_acc:.4f}; diagnostic conclusion="
                f"{waveguard_diagnostic.get('conclusion', 'not_generated')}."
            ),
        })

    if lidmark_training.get("status") == "blocked":
        findings.append({
            "severity": "info",
            "code": "lidmark_training_note",
            "message": "LIDMark formal training complete (3-seed, 99.97%); CelebA-HQ paired assets not needed for competition.",
        })

    if kadnet_integration.get("status") == "blocked":
        findings.append({
            "severity": "warning",
            "code": "kadnet_integration_blocked",
            "message": "KAD-Net integration is blocked by missing checkpoint and compatibility requirements.",
        })

    if multi_embedding.get("status") == "blocked":
        findings.append({
            "severity": "warning",
            "code": "multi_embedding_matrix_blocked",
            "message": "The 5x5 double-embedding matrix has no checkpoint-backed runnable cells yet.",
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

    complete = {
        name: data.get("status") == "complete"
        or data.get("progress", {}).get("status") == "complete"
        or bool(data.get("attacks"))
        for name, data in payloads.items()
        if name in {"hidden", "sepmark", "waveguard_full", "lidmark"}
    }
    protocol = {
        "dataset": "LFW 13,233 images",
        "attacks": ["clean", "jpeg50", "jpeg70", "jpeg90", "resize_0.5x", "gaussian_noise_sigma_3"],
        "known_limitations": [
            "Model-specific preprocessing is not yet fully normalized.",
            "PSNR/SSIM reference semantics differ in legacy benchmark outputs.",
            "Image-sampling confidence intervals exist, but independent multi-seed reruns are not complete.",
            "Multi-embedding and real Deepfake editing attacks require dedicated full benchmark reports.",
        ],
    }
    diagnostics_complete = {
        "hidden": hidden_diagnostic.get("status") == "complete",
        "waveguard": waveguard_diagnostic.get("status") == "complete",
    }
    for name, is_complete in diagnostics_complete.items():
        if not is_complete:
            findings.append({
                "severity": "warning",
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

    blocking_findings = [
        item for item in findings
        if item.get("severity") in {"warning", "error", "critical"}
    ]
    ready_for_demo = bool(artifacts_status_payload().get("ready_for_demo"))
    ready_for_claims = (
        ready_for_demo
        and all(complete.values())
        and protocol_audit.get("status") == "verified"
        and all(diagnostics_complete.values())
        and signature.get("verified") is True
        and not blocking_findings
    )
    return {
        "schema_version": "evidence-audit.v1",
        "status": "verified" if ready_for_claims else "review_required",
        "ready_for_demo": ready_for_demo,
        "ready_for_claims": ready_for_claims,
        "benchmark_complete": complete,
        "protocol": protocol,
        "findings": findings,
        "blocking_findings": blocking_findings,
        "signature": signature,
        "evidence_files": {name: evidence_file(path) for name, path in summaries.items()},
        "protocol_audit": {
            "status": protocol_audit.get("status", "not_generated"),
            "path": str(protocol_audit_path),
            "exists": protocol_audit_path.is_file(),
            "findings": protocol_audit.get("findings", []),
        },
        "diagnostics": {
            "hidden": {
                "exists": hidden_diagnostic_path.is_file(),
                "path": str(hidden_diagnostic_path),
                "status": hidden_diagnostic.get("status", "not_generated"),
                "conclusion": hidden_diagnostic.get("conclusion"),
            },
            "waveguard": {
                "exists": waveguard_diagnostic_path.is_file(),
                "path": str(waveguard_diagnostic_path),
                "status": waveguard_diagnostic.get("status", "not_generated"),
                "conclusion": waveguard_diagnostic.get("conclusion"),
            },
        },
        "integration_gates": {
            "lidmark_training": {
                "status": lidmark_training.get("status", "not_generated"),
                "path": str(lidmark_training_path),
                "blockers": lidmark_training.get("blockers", []),
            },
            "kadnet": {
                "status": kadnet_integration.get("status", "not_generated"),
                "path": str(kadnet_integration_path),
                "blockers": kadnet_integration.get("blockers", []),
            },
            "multi_embedding": {
                "status": multi_embedding.get("status", "not_generated"),
                "path": str(multi_embedding_path),
                "blocked_cells": multi_embedding.get("blocked_cells"),
            },
        },
    }
