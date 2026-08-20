from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))

from system.backend.claims import claims_payload  # noqa: E402
from system.backend.artifacts import artifacts_status_payload  # noqa: E402
from system.backend.evidence import evidence_audit_payload  # noqa: E402
from system.evaluation.protocol import protocol_summary  # noqa: E402
from system.evaluation.runtime import REPORT_ROOT, logical_path  # noqa: E402


DEFAULT_OUTPUT = REPORT_ROOT / "jianyuanshield_competition_report"
BENCHMARK_SOURCES = {
    "sepmark": REPORT_ROOT / "sepmark_lfw_benchmark" / "summary.json",
    "waveguard_full": REPORT_ROOT / "waveguard_lfw_benchmark" / "summary.json",
    "lidmark": REPORT_ROOT / "lidmark_lfw_identity_test_epoch20_protocol_v1" / "summary.json",
    "kadnet": REPORT_ROOT / "kadnet_lfw_benchmark" / "summary.json",
}
METRIC_TOKENS = ("accuracy", "ber", "success_rate", "psnr", "ssim")
UPSTREAM_ARTIFACT_CHECKS = (
    "formal_dataset_ready",
    "weights_ready",
    "benchmark_ready",
    "aggregate_ready",
)


class EvidenceGateError(RuntimeError):
    def __init__(self, blockers: list[dict[str, Any]]):
        super().__init__("competition report evidence gate is closed")
        self.blockers = blockers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a competition report only after claims and evidence gates are verified."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory (default: JYS_REPORT_ROOT/jianyuanshield_competition_report).",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate all inputs without writing report files.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def public_path(path: Path) -> str:
    return logical_path(path)


def upstream_evidence_ready(evidence: dict[str, Any], artifacts: dict[str, Any] | None) -> bool:
    if artifacts is None:
        return False
    artifact_checks = artifacts.get("checks", {})
    return all([
        all(artifact_checks.get(name) is True for name in UPSTREAM_ARTIFACT_CHECKS),
        bool(evidence.get("benchmark_complete")) and all(evidence["benchmark_complete"].values()),
        evidence.get("protocol_audit", {}).get("status") == "verified",
        evidence.get("signature", {}).get("verified") is True,
        not evidence.get("blocking_findings"),
    ])


def gate_blockers(
    claims: dict[str, Any],
    evidence: dict[str, Any],
    artifacts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if claims.get("status") == "manifest_missing":
        blockers.append({"code": "claims_manifest_missing", "detail": "claims manifest is unavailable"})
    if claims.get("ready_for_claims") is not True:
        blockers.append({
            "code": "claims_not_publishable",
            "detail": f"blocked_required={claims.get('summary', {}).get('blocked_required', 'unknown')}",
        })

    performance_claim = next(
        (claim for claim in claims.get("claims", []) if claim.get("claim_id") == "performance_results"),
        None,
    )
    if performance_claim is None:
        blockers.append({"code": "performance_claim_missing", "detail": "performance_results is absent"})
    elif performance_claim.get("publishable") is not True:
        blockers.append({
            "code": "performance_claim_blocked",
            "detail": f"status={performance_claim.get('status', 'unknown')}",
        })

    strict_evidence_ready = (
        evidence.get("status") == "verified" and evidence.get("ready_for_claims") is True
    )
    bootstrap_evidence_ready = upstream_evidence_ready(evidence, artifacts)
    if not strict_evidence_ready and not bootstrap_evidence_ready:
        blockers.append({
            "code": "evidence_gate_closed",
            "detail": (
                f"status={evidence.get('status', 'unknown')}; "
                f"ready_for_claims={evidence.get('ready_for_claims')}"
            ),
        })
    if not evidence.get("benchmark_complete") or not all(evidence["benchmark_complete"].values()):
        incomplete = [
            name for name, complete in evidence.get("benchmark_complete", {}).items() if not complete
        ]
        blockers.append({
            "code": "benchmark_evidence_incomplete",
            "detail": ",".join(incomplete) or "benchmark completion map is missing",
        })

    evidence_claims = evidence.get("claims", {})
    if evidence_claims.get("manifest_sha256") != claims.get("manifest_sha256"):
        blockers.append({
            "code": "claims_manifest_mismatch",
            "detail": "claims payload and evidence audit reference different manifest hashes",
        })
    for finding in evidence.get("blocking_findings", []):
        blockers.append({
            "code": str(finding.get("code", "evidence_finding")),
            "detail": str(finding.get("message", "blocking evidence finding")),
        })

    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (str(blocker["code"]), str(blocker["detail"]))
        if key not in seen:
            seen.add(key)
            deduplicated.append(blocker)
    return deduplicated


def read_required_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise EvidenceGateError([{"code": "summary_missing", "detail": public_path(path)}])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceGateError([{
            "code": "summary_invalid",
            "detail": f"{public_path(path)}: {exc.__class__.__name__}",
        }]) from exc
    if not isinstance(payload, dict) or payload.get("status") != "complete":
        raise EvidenceGateError([{
            "code": "summary_not_complete",
            "detail": f"{public_path(path)}: status={payload.get('status') if isinstance(payload, dict) else 'invalid'}",
        }])
    return payload


def metric_rows(benchmark: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    attacks = summary.get("attacks")
    if not isinstance(attacks, dict):
        return rows
    for attack, values in sorted(attacks.items()):
        if not isinstance(values, dict):
            continue
        for metric, raw_value in sorted(values.items()):
            if not any(token in metric.lower() for token in METRIC_TOKENS):
                continue
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                continue
            value = float(raw_value)
            if not math.isfinite(value):
                continue
            rows.append({
                "benchmark": benchmark,
                "attack": str(attack),
                "metric": str(metric),
                "value": value,
            })
    return rows


def collect_performance(evidence: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artifacts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for benchmark, complete in evidence["benchmark_complete"].items():
        if not complete:
            continue
        source_path = BENCHMARK_SOURCES.get(benchmark)
        if source_path is None:
            raise EvidenceGateError([{
                "code": "benchmark_source_unmapped",
                "detail": benchmark,
            }])
        summary = read_required_summary(source_path)
        benchmark_rows = metric_rows(benchmark, summary)
        if not benchmark_rows:
            raise EvidenceGateError([{
                "code": "performance_metrics_missing",
                "detail": public_path(source_path),
            }])
        sample_count = summary.get("num_images") or summary.get("sample_count")
        artifact = {
            "benchmark": benchmark,
            "summary_path": public_path(source_path),
            "summary_sha256": sha256_file(source_path),
            "checkpoint_sha256": summary.get("checkpoint_sha256"),
            "dataset_manifest_sha256": summary.get("dataset_manifest_sha256"),
            "protocol_version": summary.get("protocol_version"),
            "sample_count": sample_count,
            "metric_count": len(benchmark_rows),
        }
        artifacts.append(artifact)
        for row in benchmark_rows:
            rows.append({**row, **artifact})
    if not artifacts:
        raise EvidenceGateError([{
            "code": "no_verified_performance_artifacts",
            "detail": "evidence gate did not expose any completed benchmark",
        }])
    return artifacts, rows


def build_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 鉴源盾竞赛证据报告",
        "",
        "本报告仅包含 claims manifest 允许发布、且通过证据门禁的声明与性能指标。",
        "",
        "## 门禁状态",
        "",
        f"- Claims manifest: `{payload['claims_gate']['manifest_sha256']}`",
        f"- Evidence status: `{payload['evidence_gate']['status']}`",
        f"- Claim valid: `{str(payload['claim_valid']).lower()}`",
        "",
        "## 可发布声明",
        "",
    ]
    lines.extend(f"- {claim['statement']}" for claim in payload["published_claims"])
    lines.extend([
        "",
        "## 已验证性能指标",
        "",
        "| Benchmark | Attack | Metric | Value | Samples |",
        "|---|---|---|---:|---:|",
    ])
    for row in payload["performance_results"]:
        lines.append(
            f"| {row['benchmark']} | {row['attack']} | {row['metric']} | "
            f"{row['value']:.6g} | {row['sample_count']} |"
        )
    lines.extend(["", "## 适用边界", ""])
    limitations = payload.get("limitations", [])
    lines.extend(f"- {item}" for item in limitations)
    if not limitations:
        lines.append("- 以 claims manifest 与各评测产物记录的边界为准。")
    return "\n".join(lines) + "\n"


def build_csv(rows: list[dict[str, Any]]) -> str:
    fields = [
        "benchmark",
        "attack",
        "metric",
        "value",
        "sample_count",
        "summary_path",
        "summary_sha256",
        "checkpoint_sha256",
        "dataset_manifest_sha256",
        "protocol_version",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def build_report(
    claims: dict[str, Any],
    evidence: dict[str, Any],
    artifacts_status: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, str]:
    blockers = gate_blockers(claims, evidence, artifacts_status)
    if blockers:
        raise EvidenceGateError(blockers)

    artifacts, rows = collect_performance(evidence)
    published_claims = [
        {
            "claim_id": claim.get("claim_id"),
            "claim_type": claim.get("claim_type"),
            "statement": claim.get("statement"),
            "status": claim.get("status"),
            "evidence": claim.get("evidence", []),
            "limitations": claim.get("limitations", []),
        }
        for claim in claims.get("claims", [])
        if claim.get("publishable") is True
    ]
    limitations = list(dict.fromkeys(
        limitation
        for claim in published_claims
        for limitation in claim.get("limitations", [])
        if limitation
    ))
    protocol = protocol_summary()
    protocol["source_path"] = public_path(Path(protocol["source_path"]))
    strict_evidence_ready = (
        evidence.get("status") == "verified"
        and evidence.get("ready_for_claims") is True
        and evidence.get("signature", {}).get("profile") == "release"
    )
    gate_mode = "strict" if strict_evidence_ready else "release_core_signed_bootstrap"
    payload = {
        "schema_version": "competition-report.v3",
        "generated_at": int(time.time()),
        "project_name": "鉴源盾",
        "claim_valid": True,
        "claim_status": "evidence_verified",
        "claims_gate": {
            "status": claims["status"],
            "ready_for_claims": claims["ready_for_claims"],
            "manifest_schema_version": claims.get("manifest_schema_version"),
            "manifest_sha256": claims.get("manifest_sha256"),
            "summary": claims.get("summary", {}),
        },
        "evidence_gate": {
            "status": "verified" if strict_evidence_ready else "verified_upstream",
            "mode": gate_mode,
            "ready_for_demo": evidence.get("ready_for_demo"),
            "ready_for_claims_before_export": evidence["ready_for_claims"],
            "upstream_artifact_checks": {
                name: artifacts_status.get("checks", {}).get(name) if artifacts_status else None
                for name in UPSTREAM_ARTIFACT_CHECKS
            },
            "benchmark_complete": evidence["benchmark_complete"],
            "signature": evidence.get("signature", {}),
            "protocol_audit": evidence.get("protocol_audit", {}),
            "diagnostics": evidence.get("diagnostics", {}),
        },
        "evaluation_protocol": protocol,
        "published_claims": published_claims,
        "performance_claim": next(
            claim for claim in published_claims if claim.get("claim_id") == "performance_results"
        ),
        "performance_artifacts": artifacts,
        "performance_results": rows,
        "limitations": limitations,
    }
    return payload, build_markdown(payload), build_csv(rows)


def main() -> int:
    args = parse_args()
    claims = claims_payload()
    evidence = evidence_audit_payload()
    artifacts_status = artifacts_status_payload()
    try:
        payload, markdown, csv_text = build_report(claims, evidence, artifacts_status)
    except EvidenceGateError as exc:
        print(json.dumps({
            "status": "blocked",
            "claim_valid": False,
            "reason": "evidence_gate_closed",
            "output_written": False,
            "blockers": exc.blockers,
        }, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    if args.check_only:
        print(json.dumps({
            "status": "verified",
            "claim_valid": True,
            "output_written": False,
            "performance_metrics": len(payload["performance_results"]),
        }, indent=2, ensure_ascii=False))
        return 0

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output / "report.json", json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(output / "report.md", markdown)
    atomic_write_text(output / "report.csv", csv_text)
    print(json.dumps({
        "status": "verified",
        "claim_valid": True,
        "output": str(output),
        "performance_metrics": len(payload["performance_results"]),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
