from __future__ import annotations

from typing import Any

from .utils import numeric
from system.evaluation.protocol import protocol_summary


BENCHMARK_SCHEMA_VERSION = "benchmark.v1"


def _first_present(values: list[Any], fallback: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return fallback


def _metric_value(value: Any) -> Any:
    number = numeric(value)
    return number if number is not None else value


def _metric_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _metric_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_metric_tree(item) for item in value]
    return _metric_value(value)


def _normalize_attack_record(attack: str, values: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key, value in values.items():
        if key in {"status", "count", "row_count", "attack", "attack_type"}:
            continue
        if isinstance(value, (int, float, str, dict, list)) and value not in ("", None):
            metrics[key] = _metric_tree(value)

    return {
        "attack": attack,
        "status": values.get("status", "unknown"),
        "count": _metric_value(values.get("count", values.get("row_count"))),
        "metrics": metrics,
    }


def _attack_items(summary: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    attacks = summary.get("attacks")
    if isinstance(attacks, dict):
        return [(str(name), values if isinstance(values, dict) else {}) for name, values in attacks.items()]

    attack_summaries = summary.get("attack_summaries")
    if isinstance(attack_summaries, list):
        items = []
        for item in attack_summaries:
            if not isinstance(item, dict):
                continue
            attack = str(item.get("attack_type") or item.get("attack") or "unknown")
            items.append((attack, item))
        return items

    return []


def normalize_benchmark(
    *,
    summary: dict[str, Any],
    progress: dict[str, Any],
    method: str,
    checkpoint_type: str,
    data_type: str,
    results_csv_exists: bool,
) -> dict[str, Any]:
    status = _first_present(
        [
            summary.get("status"),
            progress.get("status"),
            "ready" if results_csv_exists else None,
        ],
        "missing",
    )
    num_images = _first_present(
        [
            summary.get("num_images"),
            summary.get("sample_count"),
            summary.get("images"),
            summary.get("requested_images"),
            progress.get("total_samples"),
            progress.get("processed_samples"),
            progress.get("num_images"),
            progress.get("processed_images"),
            progress.get("completed_images"),
        ]
    )

    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "method": _first_present([summary.get("method"), method], method),
        "mode": _first_present([summary.get("mode"), checkpoint_type], checkpoint_type),
        "status": status,
        "checkpoint_type": checkpoint_type,
        "data_type": _first_present([summary.get("data_type"), data_type], data_type),
        "num_images": _metric_value(num_images),
        "results_csv_exists": results_csv_exists,
        "attacks": [_normalize_attack_record(attack, values) for attack, values in _attack_items(summary)],
        "metric_semantics": protocol_summary()["metric_semantics"],
        "evaluation_protocol": protocol_summary()["schema_version"],
    }
