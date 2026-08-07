from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.evaluation.runtime import REPORT_ROOT, logical_path, resolve_logical_path  # noqa: E402
from system.backend.utils import atomic_write_bytes, atomic_write_json  # noqa: E402


DEFAULT_OUT = REPORT_ROOT / "protocol_audit"

SOURCES = {
    "SepMark": REPORT_ROOT / "sepmark_lfw_benchmark/results.csv",
    "WaveGuard": REPORT_ROOT / "waveguard_lfw_benchmark/results.csv",
    "LIDMark": REPORT_ROOT / "lidmark_lfw_identity_test_epoch20_protocol_v1/raw_results.csv",
    "KAD-Net": REPORT_ROOT / "kadnet_lfw_benchmark/results.csv",
}

PAIR_FIELDS = [
    ("bit_error", "bit_accuracy"),
    ("bit_error_c", "bit_accuracy_c"),
    ("bit_error_rf", "bit_accuracy_rf"),
    ("bit_error_detector", "bit_accuracy_detector"),
    ("bit_error_tracer", "bit_accuracy_tracer"),
    ("ber", "bit_accuracy"),
]

METRIC_HINTS = ("bit_error", "bit_accuracy", "ber", "acc", "psnr", "ssim", "success", "aed")
PRIMARY_METRICS = {
    "SepMark": ("bit_accuracy_c",),
    "WaveGuard": ("bit_accuracy_tracer",),
    "LIDMark": ("bit_accuracy",),
    "KAD-Net": ("bit_accuracy",),
}


def numeric(value: str | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return center - margin, center + margin


def metric_summary(values: list[float], is_success: bool = False) -> dict[str, Any]:
    count = len(values)
    if not count:
        return {"count": 0}
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if count > 1 else 0.0
    ci_margin = 1.959963984540054 * std / math.sqrt(count) if count > 1 else 0.0
    result: dict[str, Any] = {
        "count": count,
        "mean": mean,
        "std": std,
        "ci95_low": mean - ci_margin,
        "ci95_high": mean + ci_margin,
        "min": min(values),
        "p05": percentile(values, 0.05),
        "median": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "max": max(values),
        "constant": max(values) == min(values),
    }
    if is_success:
        low, high = wilson(sum(value >= 0.5 for value in values), count)
        result["wilson95_low"] = low
        result["wilson95_high"] = high
    return result


def analyze_csv(model: str, path: Path) -> dict[str, Any]:
    summary_path = path.parent / "summary.json"
    if not path.is_file():
        return {
            "model": model,
            "path": logical_path(path),
            "status": "missing",
            "findings": [{"severity": "error", "code": "results_missing"}],
        }
    if not summary_path.is_file():
        return {
            "model": model,
            "path": logical_path(path),
            "status": "missing_summary",
            "findings": [{"severity": "error", "code": "summary_missing"}],
        }
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return {
            "model": model,
            "path": logical_path(path),
            "status": "invalid_summary",
            "findings": [{"severity": "error", "code": "summary_invalid"}],
        }
    if not isinstance(summary, dict):
        return {
            "model": model,
            "path": logical_path(path),
            "status": "invalid_summary",
            "findings": [{"severity": "error", "code": "summary_invalid"}],
        }
    sample_count = summary.get("num_images") or summary.get("sample_count")
    attack_ids = summary.get("attack_ids")
    results_reference = summary.get("results_csv_path")
    declared_results = (
        resolve_logical_path(results_reference)
        if isinstance(results_reference, str)
        else None
    )
    summary_valid = bool(
        summary.get("schema_version") == "benchmark-summary.v2"
        and summary.get("status") == "complete"
        and isinstance(sample_count, int)
        and sample_count > 0
        and isinstance(attack_ids, list)
        and attack_ids
        and declared_results is not None
        and declared_results.resolve() == path.resolve()
        and summary.get("results_csv_sha256") == sha256_file(path)
    )
    expected_rows = (
        sample_count * len(attack_ids)
        if isinstance(sample_count, int) and isinstance(attack_ids, list)
        else None
    )
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[str, str]] = set()
    duplicate_keys = 0
    invalid_numeric = 0
    pair_checks = 0
    pair_mismatches = 0
    error_rows = 0
    unexpected_attacks = 0
    image_id_errors = 0
    primary_metric_errors = 0
    success_errors = 0
    primary_metric: str | None = None
    metric_schema_missing = False
    image_ids_by_attack: dict[str, set[str]] = defaultdict(set)
    rows = 0
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames or []
            metric_fields = [field for field in fields if any(hint in field.lower() for hint in METRIC_HINTS)]
            primary_candidates = PRIMARY_METRICS.get(model, ("bit_accuracy",))
            primary_metric = next(
                (field for field in primary_candidates if field in fields),
                None,
            )
            required_fields = {"image_id", "attack_type", "error", "success"}
            metric_schema_missing = (
                not metric_fields
                or primary_metric is None
                or not required_fields.issubset(fields)
                or len(fields) != len(set(fields))
            )
            for row in reader:
                rows += 1
                attack = row.get("attack_type") or row.get("attack") or "unknown"
                image_id = row.get("image_id")
                if not image_id:
                    image_id_errors += 1
                else:
                    image_ids_by_attack[attack].add(image_id)
                error_rows += int(bool(str(row.get("error") or "").strip()))
                unexpected_attacks += int(
                    isinstance(attack_ids, list) and attack not in attack_ids
                )
                key = (image_id or f"__missing_image_id_{rows}", attack)
                if key in seen:
                    duplicate_keys += 1
                seen.add(key)
                for field in metric_fields:
                    value = numeric(row.get(field))
                    if value is None:
                        if row.get(field) not in (None, ""):
                            invalid_numeric += 1
                        continue
                    lowered = field.lower()
                    if (
                        any(token in lowered for token in ("bit_error", "bit_accuracy", "ber", "acc", "success"))
                        and not 0 <= value <= 1
                    ) or ("ssim" in lowered and not -1 <= value <= 1) or (
                        "psnr" in lowered and value < 0
                    ):
                        invalid_numeric += 1
                        continue
                    grouped[attack][field].append(value)
                if primary_metric is not None:
                    primary_value = numeric(row.get(primary_metric))
                    if (
                        primary_value is None
                        or not 0 <= primary_value <= 1
                    ):
                        primary_metric_errors += 1
                success_errors += int(str(row.get("success") or "") not in {"0", "1"})
                for ber_field, acc_field in PAIR_FIELDS:
                    ber = numeric(row.get(ber_field))
                    acc = numeric(row.get(acc_field))
                    if ber is None or acc is None:
                        continue
                    pair_checks += 1
                    if abs((ber + acc) - 1.0) > 1e-5:
                        pair_mismatches += 1
    except (OSError, UnicodeError, csv.Error):
        return {
            "model": model,
            "path": logical_path(path),
            "status": "invalid_results",
            "findings": [{"severity": "error", "code": "results_invalid"}],
        }
    attacks = {
        attack: {
            field: metric_summary(values, is_success=field == "success")
            for field, values in metrics.items()
        }
        for attack, metrics in grouped.items()
    }
    findings = []
    if not summary_valid:
        findings.append({"severity": "error", "code": "summary_not_release_complete"})
    if metric_schema_missing:
        findings.append({"severity": "error", "code": "primary_metric_schema_missing"})
    if primary_metric_errors:
        findings.append({
            "severity": "error",
            "code": "invalid_primary_metric",
            "count": primary_metric_errors,
        })
    if success_errors:
        findings.append({
            "severity": "error",
            "code": "invalid_success",
            "count": success_errors,
        })
    if image_id_errors:
        findings.append({
            "severity": "error",
            "code": "missing_image_id",
            "count": image_id_errors,
        })
    if expected_rows is None or rows != expected_rows or len(seen) != expected_rows:
        findings.append({
            "severity": "error",
            "code": "raw_coverage_mismatch",
            "expected": expected_rows,
            "actual": rows,
        })
    if error_rows:
        findings.append({"severity": "error", "code": "error_rows", "count": error_rows})
    if invalid_numeric:
        findings.append({"severity": "error", "code": "invalid_numeric", "count": invalid_numeric})
    if unexpected_attacks:
        findings.append({"severity": "error", "code": "unexpected_attacks", "count": unexpected_attacks})
    sample_sets = [
        image_ids_by_attack.get(str(attack_id), set())
        for attack_id in (attack_ids if isinstance(attack_ids, list) else [])
    ]
    per_attack_coverage_valid = bool(sample_sets) and all(
        isinstance(sample_count, int)
        and len(sample_ids) == sample_count
        and sample_ids == sample_sets[0]
        for sample_ids in sample_sets
    )
    if not per_attack_coverage_valid:
        findings.append({
            "severity": "error",
            "code": "per_attack_sample_set_mismatch",
            "counts": {
                str(attack_id): len(image_ids_by_attack.get(str(attack_id), set()))
                for attack_id in (attack_ids if isinstance(attack_ids, list) else [])
            },
        })
    if duplicate_keys:
        findings.append({"severity": "error", "code": "duplicate_result_keys", "count": duplicate_keys})
    if pair_mismatches:
        findings.append({"severity": "error", "code": "ber_accuracy_mismatch", "count": pair_mismatches})
    constant_quality = [
        f"{attack}.{metric}"
        for attack, metrics in attacks.items()
        for metric, summary in metrics.items()
        if metric in {"psnr", "ssim"} and summary.get("constant")
    ]
    if constant_quality:
        findings.append({"severity": "warning", "code": "constant_quality_metric", "fields": constant_quality})
    return {
        "model": model,
        "path": logical_path(path),
        "status": "verified" if not any(
            finding["severity"] == "error" for finding in findings
        ) else "review_required",
        "rows": rows,
        "expected_rows": expected_rows,
        "summary_path": logical_path(summary_path),
        "results_sha256": sha256_file(path),
        "summary_sha256": sha256_file(summary_path),
        "error_rows": error_rows,
        "unique_keys": len(seen),
        "duplicate_keys": duplicate_keys,
        "invalid_numeric_values": invalid_numeric,
        "primary_metric": primary_metric,
        "primary_metric_errors": primary_metric_errors,
        "per_attack_sample_set_valid": per_attack_coverage_valid,
        "ber_accuracy_pair_checks": pair_checks,
        "ber_accuracy_pair_mismatches": pair_mismatches,
        "attacks": attacks,
        "findings": findings,
    }


def flatten_statistics(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for model, result in results.items():
        for attack, metrics in result.get("attacks", {}).items():
            for metric, summary in metrics.items():
                rows.append({"model": model, "attack": attack, "metric": metric, **summary})
    return rows


def write_report(
    output: Path,
    results: dict[str, Any],
    *,
    evidence_signature: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    findings = [
        {"model": model, **finding}
        for model, result in results.items()
        for finding in result.get("findings", [])
    ]
    audit = {
        "schema_version": "benchmark-audit.v1",
        "generated_at": int(time.time()),
        "project_root": ".",
        "status": "review_required" if findings else "verified",
        "evidence_signature": evidence_signature or {
            "status": "not_checked",
            "verified": False,
        },
        "models": results,
        "findings": findings,
        "limitations": [
            "Confidence intervals describe image-row variation within one frozen run per method.",
            "LIDMark uses an identity-disjoint 128px test split; cross-model quality ranking is not paired unless image IDs and references match.",
            "Deepfake proxy results do not establish robustness against every real generative editor.",
        ],
    }
    atomic_write_json(output / "audit.json", audit)

    stats = flatten_statistics(results)
    fields = [
        "model", "attack", "metric", "count", "mean", "std", "ci95_low", "ci95_high",
        "min", "p05", "median", "p95", "max", "constant", "wilson95_low", "wilson95_high",
    ]
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=fields,
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(stats)
    atomic_write_bytes(
        output / "statistics.csv",
        csv_buffer.getvalue().encode("utf-8"),
    )

    lines = [
        "# Benchmark Protocol Audit",
        "",
        f"- Status: `{audit['status']}`",
        f"- Generated at: `{audit['generated_at']}`",
        "",
        "## Coverage",
        "",
    ]
    for model, result in results.items():
        lines.append(
            f"- {model}: status={result.get('status')}, rows={result.get('rows', 0)}, "
            f"duplicates={result.get('duplicate_keys', 0)}, pair_mismatches={result.get('ber_accuracy_pair_mismatches', 0)}"
        )
    lines.extend(["", "## Findings", ""])
    lines.extend(
        f"- [{item['severity']}] {item['model']}: {item['code']} ({item.get('count', item.get('fields', ''))})"
        for item in findings
    )
    if not findings:
        lines.append("- No structural CSV errors detected.")
    lines.extend(["", "## Interpretation Limits", ""])
    lines.extend(f"- {item}" for item in audit["limitations"])
    atomic_write_bytes(
        output / "audit.md",
        ("\n".join(lines) + "\n").encode("utf-8"),
    )
    return audit


def main() -> int:
    # Keep dependency-free CSV analysis importable in lightweight CI. The
    # cryptographic dependency is required only for the executable audit path.
    from system.backend.signing import verify_evidence_bundle

    parser = argparse.ArgumentParser(description="Audit existing benchmark CSV files without rerunning models.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    results = {model: analyze_csv(model, path) for model, path in SOURCES.items()}
    signature = verify_evidence_bundle()
    if not (
        signature.get("verified") is True
        and signature.get("profile") in {"release-core", "release"}
        and signature.get("signer_pinned") is True
    ):
        for result in results.values():
            result["status"] = "review_required"
            result.setdefault("findings", []).append({
                "severity": "error",
                "code": "evidence_signature_unverified",
            })
    audit = write_report(
        args.output.resolve(),
        results,
        evidence_signature={
            "status": signature.get("status", "not_generated"),
            "profile": signature.get("profile"),
            "verified": signature.get("verified") is True,
            "signer_pinned": signature.get("signer_pinned") is True,
            "manifest_sha256": signature.get("manifest_sha256"),
            "public_key_fingerprint_sha256": signature.get(
                "public_key_fingerprint_sha256"
            ),
        },
    )
    print(json.dumps({
        "status": audit["status"],
        "output": str(args.output.resolve()),
        "models": {name: result.get("rows", 0) for name, result in results.items()},
        "findings": len(audit["findings"]),
    }, indent=2))
    structural_errors = [
        item for item in audit["findings"]
        if item["severity"] == "error"
    ]
    return 2 if structural_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
