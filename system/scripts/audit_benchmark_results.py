from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(os.getenv("JYS_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
DEFAULT_OUT = ROOT / "system" / "reports" / "protocol_audit"

SOURCES = {
    "HiDDeN": ROOT / "system/reports/hidden_lfw_full_benchmark/results.csv",
    "SepMark": ROOT / "system/reports/sepmark_lfw_benchmark/results.csv",
    "WaveGuard": ROOT / "system/reports/waveguard_lfw_full_benchmark/results.csv",
    "LIDMark": ROOT / "runs/lidmark_lfw_eval_full/results.csv",
}

PAIR_FIELDS = [
    ("bit_error", "bit_accuracy"),
    ("bit_error_c", "bit_accuracy_c"),
    ("bit_error_rf", "bit_accuracy_rf"),
    ("bit_error_detector", "bit_accuracy_detector"),
    ("bit_error_tracer", "bit_accuracy_tracer"),
]

METRIC_HINTS = ("bit_error", "bit_accuracy", "ber", "acc", "psnr", "ssim", "success", "aed")


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
    if not path.is_file():
        return {"model": model, "path": str(path), "status": "missing"}
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    seen: set[tuple[str, str]] = set()
    duplicate_keys = 0
    invalid_numeric = 0
    pair_checks = 0
    pair_mismatches = 0
    rows = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        metric_fields = [field for field in fields if any(hint in field.lower() for hint in METRIC_HINTS)]
        for row in reader:
            rows += 1
            attack = row.get("attack_type") or row.get("attack") or "unknown"
            key = (row.get("image_id") or str(rows), attack)
            if key in seen:
                duplicate_keys += 1
            seen.add(key)
            for field in metric_fields:
                value = numeric(row.get(field))
                if value is None:
                    if row.get(field) not in (None, ""):
                        invalid_numeric += 1
                    continue
                grouped[attack][field].append(value)
            for ber_field, acc_field in PAIR_FIELDS:
                ber = numeric(row.get(ber_field))
                acc = numeric(row.get(acc_field))
                if ber is None or acc is None:
                    continue
                pair_checks += 1
                if abs((ber + acc) - 1.0) > 1e-5:
                    pair_mismatches += 1
    attacks = {
        attack: {
            field: metric_summary(values, is_success=field == "success")
            for field, values in metrics.items()
        }
        for attack, metrics in grouped.items()
    }
    findings = []
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
        "path": str(path),
        "status": "audited",
        "rows": rows,
        "unique_keys": len(seen),
        "duplicate_keys": duplicate_keys,
        "invalid_numeric_values": invalid_numeric,
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


def write_report(output: Path, results: dict[str, Any]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    findings = [
        {"model": model, **finding}
        for model, result in results.items()
        for finding in result.get("findings", [])
    ]
    audit = {
        "schema_version": "benchmark-audit.v1",
        "generated_at": int(time.time()),
        "project_root": str(ROOT),
        "status": "review_required" if findings else "verified",
        "models": results,
        "findings": findings,
        "limitations": [
            "Confidence intervals describe row-level variation in existing CSV files.",
            "Existing full benchmark files come from legacy model-specific preprocessing.",
            "PSNR/SSIM cross-model ranking remains blocked until protocol-v1 reruns are complete.",
        ],
    }
    (output / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")

    stats = flatten_statistics(results)
    fields = [
        "model", "attack", "metric", "count", "mean", "std", "ci95_low", "ci95_high",
        "min", "p05", "median", "p95", "max", "constant", "wilson95_low", "wilson95_high",
    ]
    with (output / "statistics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(stats)

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
    (output / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit existing benchmark CSV files without rerunning models.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    results = {model: analyze_csv(model, path) for model, path in SOURCES.items()}
    audit = write_report(args.output.resolve(), results)
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
