from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from system.backend.utils import atomic_write_bytes, atomic_write_json
from system.evaluation.runtime import REPORT_ROOT


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "common_intersection_protocol.v1.json"
DEFAULT_OUTPUT = REPORT_ROOT / "common_intersection_benchmark"
_SHA256_LENGTH = 64


class CommonIntersectionError(ValueError):
    pass


@dataclass(frozen=True)
class ModelInput:
    name: str
    summary_path: Path
    results_path: Path
    image_field: str
    attack_field: str
    bit_accuracy_field: str
    success_field: str
    error_field: str
    identity_field: str | None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                CommonIntersectionError(f"non-finite JSON value: {token}")
            ),
        )
    except OSError as exc:
        raise CommonIntersectionError(f"required file is unavailable: {path}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CommonIntersectionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CommonIntersectionError(f"JSON root must be an object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CommonIntersectionError(f"required file is unavailable: {path}") from exc
    return digest.hexdigest()


def _resolve_under(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise CommonIntersectionError(f"path escapes evidence root: {relative}") from exc
    return candidate


def _logical_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root.resolve()))
    except ValueError:
        return resolved.name


def _parse_model_inputs(config: Mapping[str, Any], evidence_root: Path) -> list[ModelInput]:
    raw_models = config.get("models")
    if not isinstance(raw_models, dict) or len(raw_models) != 4:
        raise CommonIntersectionError("protocol must define exactly four models")
    parsed: list[ModelInput] = []
    for name, raw in raw_models.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            raise CommonIntersectionError("model contract is invalid")
        required = (
            "summary",
            "results",
            "image_field",
            "attack_field",
            "bit_accuracy_field",
            "success_field",
            "error_field",
        )
        if any(not isinstance(raw.get(field), str) or not raw[field] for field in required):
            raise CommonIntersectionError(f"model contract is incomplete: {name}")
        parsed.append(
            ModelInput(
                name=name,
                summary_path=_resolve_under(evidence_root, raw["summary"]),
                results_path=_resolve_under(evidence_root, raw["results"]),
                image_field=raw["image_field"],
                attack_field=raw["attack_field"],
                bit_accuracy_field=raw["bit_accuracy_field"],
                success_field=raw["success_field"],
                error_field=raw["error_field"],
                identity_field=raw.get("identity_field"),
            )
        )
    return parsed


def _summary_results_hash(summary: Mapping[str, Any]) -> str | None:
    for field in ("results_csv_sha256", "raw_results_sha256"):
        value = summary.get(field)
        if isinstance(value, str) and len(value) == _SHA256_LENGTH:
            return value
    return None


def _validate_summary(model: ModelInput, attacks: list[str]) -> tuple[dict[str, Any], str]:
    summary = _load_json(model.summary_path)
    if summary.get("status") != "complete":
        raise CommonIntersectionError(f"{model.name} summary is not complete")
    if summary.get("error_rows") not in (0, None):
        raise CommonIntersectionError(f"{model.name} summary contains error rows")
    if summary.get("missing_rows") not in (0, None):
        raise CommonIntersectionError(f"{model.name} summary contains missing rows")
    if summary.get("attack_ids") != attacks:
        raise CommonIntersectionError(f"{model.name} attack contract mismatch")
    results_hash = _sha256_file(model.results_path)
    if _summary_results_hash(summary) != results_hash:
        raise CommonIntersectionError(f"{model.name} results hash mismatch")
    expected_rows = summary.get("expected_result_rows")
    observed_rows = summary.get("result_rows", summary.get("evaluated_rows"))
    if not isinstance(expected_rows, int) or observed_rows != expected_rows:
        raise CommonIntersectionError(f"{model.name} summary coverage is incomplete")
    return summary, results_hash


def _parse_unit_float(value: str, *, field: str, model: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CommonIntersectionError(f"{model} has invalid {field}") from exc
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        raise CommonIntersectionError(f"{model} has out-of-range {field}")
    return parsed


def _parse_success(value: str, *, model: str) -> int:
    if value == "1":
        return 1
    if value == "0":
        return 0
    raise CommonIntersectionError(f"{model} has non-binary success value")


def _load_rows(
    model: ModelInput,
    attacks: list[str],
    attack_config_field: str,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, str], dict[str, str]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    identities: dict[str, str] = {}
    attack_hashes: dict[str, str] = {}
    try:
        handle = model.results_path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise CommonIntersectionError(f"unable to read {model.name} results") from exc
    with handle:
        reader = csv.DictReader(handle)
        required_fields = {
            model.image_field,
            model.attack_field,
            model.bit_accuracy_field,
            model.success_field,
            model.error_field,
            attack_config_field,
        }
        if model.identity_field:
            required_fields.add(model.identity_field)
        if reader.fieldnames is None or not required_fields.issubset(reader.fieldnames):
            raise CommonIntersectionError(f"{model.name} CSV schema mismatch")
        for raw in reader:
            image_id = raw[model.image_field]
            attack = raw[model.attack_field]
            if not image_id or attack not in attacks:
                raise CommonIntersectionError(f"{model.name} contains an unexpected row key")
            if raw[model.error_field].strip():
                raise CommonIntersectionError(f"{model.name} contains an error row")
            key = (image_id, attack)
            if key in rows:
                raise CommonIntersectionError(f"{model.name} contains a duplicate row")
            attack_hash = raw[attack_config_field]
            if len(attack_hash) != _SHA256_LENGTH:
                raise CommonIntersectionError(f"{model.name} attack hash is invalid")
            previous_hash = attack_hashes.setdefault(attack, attack_hash)
            if previous_hash != attack_hash:
                raise CommonIntersectionError(f"{model.name} attack hash changes within an attack")
            rows[key] = {
                "success": _parse_success(raw[model.success_field], model=model.name),
                "bit_accuracy": _parse_unit_float(
                    raw[model.bit_accuracy_field],
                    field=model.bit_accuracy_field,
                    model=model.name,
                ),
            }
            if model.identity_field:
                identity = raw[model.identity_field].strip()
                if not identity:
                    raise CommonIntersectionError(f"{model.name} identity is empty")
                previous_identity = identities.setdefault(image_id, identity)
                if previous_identity != identity:
                    raise CommonIntersectionError(f"{model.name} identity mapping changes by attack")
    if set(attack_hashes) != set(attacks):
        raise CommonIntersectionError(f"{model.name} attack coverage is incomplete")
    return rows, identities, attack_hashes


def _wilson(successes: int, total: int) -> dict[str, float]:
    if total <= 0:
        raise CommonIntersectionError("Wilson interval requires a positive sample count")
    z = 1.959963984540054
    estimate = successes / total
    denominator = 1.0 + z * z / total
    center = (estimate + z * z / (2.0 * total)) / denominator
    spread = (
        z
        * math.sqrt(estimate * (1.0 - estimate) / total + z * z / (4.0 * total * total))
        / denominator
    )
    return {
        "estimate": estimate,
        "lower": max(0.0, center - spread),
        "upper": min(1.0, center + spread),
    }


def _cluster_bootstrap(
    metric_columns: np.ndarray,
    image_identities: list[str],
    *,
    repetitions: int,
    seed: int,
    confidence_level: float,
) -> tuple[np.ndarray, np.ndarray]:
    identities = sorted(set(image_identities))
    if repetitions < 128 or not 0.0 < confidence_level < 1.0:
        raise CommonIntersectionError("bootstrap contract is invalid")
    identity_index = {identity: index for index, identity in enumerate(identities)}
    cluster_sizes = np.zeros(len(identities), dtype=np.float64)
    cluster_sums = np.zeros((len(identities), metric_columns.shape[1]), dtype=np.float64)
    for row_index, identity in enumerate(image_identities):
        cluster_index = identity_index[identity]
        cluster_sizes[cluster_index] += 1.0
        cluster_sums[cluster_index] += metric_columns[row_index]
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(
        len(identities),
        np.full(len(identities), 1.0 / len(identities)),
        size=repetitions,
    ).astype(np.float64, copy=False)
    denominators = draws @ cluster_sizes
    replicates = (draws @ cluster_sums) / denominators[:, None]
    alpha = 1.0 - confidence_level
    lower = np.quantile(replicates, alpha / 2.0, axis=0)
    upper = np.quantile(replicates, 1.0 - alpha / 2.0, axis=0)
    return lower, upper


def aggregate(
    *,
    config_path: Path,
    evidence_root: Path,
) -> tuple[dict[str, Any], bytes, bytes]:
    config = _load_json(config_path)
    if config.get("schema_version") != "common-intersection-protocol.v1":
        raise CommonIntersectionError("unsupported common-intersection protocol")
    attacks = config.get("attack_ids")
    if not isinstance(attacks, list) or len(attacks) != len(set(attacks)) or not attacks:
        raise CommonIntersectionError("attack contract is invalid")
    if any(not isinstance(attack, str) or not attack for attack in attacks):
        raise CommonIntersectionError("attack contract is invalid")
    attack_config_field = config.get("attack_config_field")
    if not isinstance(attack_config_field, str) or not attack_config_field:
        raise CommonIntersectionError("attack hash field is invalid")
    models = _parse_model_inputs(config, evidence_root)
    reference_name = config.get("reference_model")
    reference = next((model for model in models if model.name == reference_name), None)
    if reference is None or not reference.identity_field:
        raise CommonIntersectionError("reference model identity contract is missing")

    summaries: dict[str, dict[str, Any]] = {}
    result_hashes: dict[str, str] = {}
    model_rows: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    identity_maps: dict[str, dict[str, str]] = {}
    attack_hashes_by_model: dict[str, dict[str, str]] = {}
    for model in models:
        summary, result_hash = _validate_summary(model, attacks)
        rows, identities, attack_hashes = _load_rows(model, attacks, attack_config_field)
        if len(rows) != summary["expected_result_rows"]:
            raise CommonIntersectionError(f"{model.name} CSV row coverage mismatch")
        summaries[model.name] = summary
        result_hashes[model.name] = result_hash
        model_rows[model.name] = rows
        identity_maps[model.name] = identities
        attack_hashes_by_model[model.name] = attack_hashes

    for attack in attacks:
        values = {mapping[attack] for mapping in attack_hashes_by_model.values()}
        if len(values) != 1:
            raise CommonIntersectionError(f"attack transform mismatch across models: {attack}")

    image_sets = {
        name: {image_id for image_id, _attack in rows}
        for name, rows in model_rows.items()
    }
    common_images = set.intersection(*image_sets.values())
    reference_images = image_sets[reference.name]
    if common_images != reference_images:
        missing = sorted(reference_images - common_images)
        raise CommonIntersectionError(
            f"reference intersection is incomplete; missing={len(missing)}"
        )
    expected_images = config.get("expected_common_images")
    expected_identities = config.get("expected_identity_clusters")
    identities = identity_maps[reference.name]
    if len(common_images) != expected_images or set(identities) != common_images:
        raise CommonIntersectionError("common image contract mismatch")
    if len(set(identities.values())) != expected_identities:
        raise CommonIntersectionError("identity cluster contract mismatch")
    for model in models:
        for image_id in common_images:
            for attack in attacks:
                if (image_id, attack) not in model_rows[model.name]:
                    raise CommonIntersectionError(
                        f"common row missing: {model.name}/{image_id}/{attack}"
                    )

    ordered_images = sorted(common_images)
    metric_names: list[tuple[str, str, str]] = []
    columns: list[np.ndarray] = []
    for attack in attacks:
        success_vectors = []
        for model in models:
            success = np.asarray(
                [model_rows[model.name][(image, attack)]["success"] for image in ordered_images],
                dtype=np.float64,
            )
            accuracy = np.asarray(
                [model_rows[model.name][(image, attack)]["bit_accuracy"] for image in ordered_images],
                dtype=np.float64,
            )
            success_vectors.append(success)
            metric_names.extend(
                ((attack, model.name, "success_rate"), (attack, model.name, "mean_bit_accuracy"))
            )
            columns.extend((success, accuracy))
        joint = np.prod(np.column_stack(success_vectors), axis=1)
        metric_names.append((attack, "ALL_MODELS", "joint_success_rate"))
        columns.append(joint)
    metric_matrix = np.column_stack(columns)
    statistics = config.get("statistics")
    if not isinstance(statistics, dict):
        raise CommonIntersectionError("statistics contract is missing")
    repetitions = statistics.get("bootstrap_repetitions")
    seed = statistics.get("seed")
    confidence = statistics.get("confidence_level")
    if not isinstance(repetitions, int) or not isinstance(seed, int) or not isinstance(confidence, (int, float)):
        raise CommonIntersectionError("statistics contract is invalid")
    lower, upper = _cluster_bootstrap(
        metric_matrix,
        [identities[image] for image in ordered_images],
        repetitions=repetitions,
        seed=seed,
        confidence_level=float(confidence),
    )

    metric_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index, key in enumerate(metric_names):
        point = float(metric_matrix[:, index].mean())
        metric_lookup[key] = {
            "estimate": point,
            "cluster_bootstrap_95": {
                "lower": float(lower[index]),
                "upper": float(upper[index]),
            },
        }

    report_rows: list[dict[str, Any]] = []
    by_attack: dict[str, Any] = {}
    for attack in attacks:
        model_metrics: dict[str, Any] = {}
        for model in models:
            success_key = (attack, model.name, "success_rate")
            accuracy_key = (attack, model.name, "mean_bit_accuracy")
            success_count = int(
                sum(model_rows[model.name][(image, attack)]["success"] for image in ordered_images)
            )
            success_metric = metric_lookup[success_key]
            accuracy_metric = metric_lookup[accuracy_key]
            model_metrics[model.name] = {
                "sample_count": len(ordered_images),
                "identity_clusters": len(set(identities.values())),
                "successes": success_count,
                "success_rate": success_metric["estimate"],
                "success_rate_wilson_95": _wilson(success_count, len(ordered_images)),
                "success_rate_identity_cluster_bootstrap_95": success_metric[
                    "cluster_bootstrap_95"
                ],
                "mean_bit_accuracy": accuracy_metric["estimate"],
                "mean_bit_accuracy_identity_cluster_bootstrap_95": accuracy_metric[
                    "cluster_bootstrap_95"
                ],
            }
            report_rows.append(
                {
                    "attack": attack,
                    "model": model.name,
                    **model_metrics[model.name],
                }
            )
        joint_count = sum(
            all(model_rows[model.name][(image, attack)]["success"] for model in models)
            for image in ordered_images
        )
        joint_metric = metric_lookup[(attack, "ALL_MODELS", "joint_success_rate")]
        joint = {
            "sample_count": len(ordered_images),
            "identity_clusters": len(set(identities.values())),
            "successes": joint_count,
            "success_rate": joint_metric["estimate"],
            "success_rate_wilson_95": _wilson(joint_count, len(ordered_images)),
            "success_rate_identity_cluster_bootstrap_95": joint_metric[
                "cluster_bootstrap_95"
            ],
        }
        by_attack[attack] = {"models": model_metrics, "all_models_joint": joint}
        report_rows.append({"attack": attack, "model": "ALL_MODELS", **joint})

    sources = {
        model.name: {
            "summary_path": str(model.summary_path.relative_to(evidence_root.resolve())),
            "summary_sha256": _sha256_file(model.summary_path),
            "results_path": str(model.results_path.relative_to(evidence_root.resolve())),
            "results_sha256": result_hashes[model.name],
            "checkpoint_sha256": summaries[model.name].get("checkpoint_sha256"),
        }
        for model in models
    }
    summary = {
        "schema_version": "common-intersection-benchmark.v1",
        "status": "complete",
        "protocol_id": config["protocol_id"],
        "protocol_path": _logical_path(config_path, PROJECT_ROOT),
        "protocol_sha256": _sha256_file(config_path),
        "models": [model.name for model in models],
        "attack_ids": attacks,
        "common_images": len(ordered_images),
        "identity_clusters": len(set(identities.values())),
        "expected_metric_cells": len(attacks) * (len(models) + 1),
        "statistics": statistics,
        "comparison_policy": config.get("comparison_policy"),
        "attack_config_sha256": {
            attack: next(iter(attack_hashes_by_model.values()))[attack] for attack in attacks
        },
        "sources": sources,
        "attacks": by_attack,
    }

    fields = sorted({key for row in report_rows for key in row})
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=fields)
    writer.writeheader()
    for row in report_rows:
        flattened = dict(row)
        for key, value in list(flattened.items()):
            if isinstance(value, dict):
                flattened[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        writer.writerow(flattened)

    markdown = [
        "# 四模型固定公共交集报告",
        "",
        f"- 公共图片：{len(ordered_images)}",
        f"- 身份聚类：{len(set(identities.values()))}",
        f"- 攻击：{len(attacks)}",
        f"- bootstrap：{repetitions} 次，seed={seed}",
        "",
        "| Attack | LIDMark | KAD-Net | SepMark | WaveGuard | 四模型联合通过 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for attack in attacks:
        metrics = by_attack[attack]
        values = [metrics["models"][model.name]["success_rate"] for model in models]
        markdown.append(
            "| "
            + attack
            + " | "
            + " | ".join(f"{value:.8f}" for value in values)
            + f" | {metrics['all_models_joint']['success_rate']:.8f} |"
        )
    markdown.extend(
        (
            "",
            "> 跨模型只比较各自协议阈值下的 success；原始 bit accuracy 因消息长度和 decoder 语义不同不直接排名。",
            "",
        )
    )
    return (
        summary,
        csv_buffer.getvalue().encode("utf-8"),
        "\n".join(markdown).encode("utf-8"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate four watermark models on the exact LFW image/attack intersection."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--evidence-root", type=Path, default=REPORT_ROOT.parent)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        summary, csv_bytes, markdown_bytes = aggregate(
            config_path=args.config,
            evidence_root=args.evidence_root,
        )
    except CommonIntersectionError as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "comparison.csv").unlink(missing_ok=True)
        (args.output / "report.md").unlink(missing_ok=True)
        atomic_write_json(
            args.output / "summary.json",
            {
                "schema_version": "common-intersection-benchmark.v1",
                "status": "failed",
                "error": str(exc),
            },
        )
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(args.output / "comparison.csv", csv_bytes)
    atomic_write_bytes(args.output / "report.md", markdown_bytes)
    summary["artifacts"] = {
        "comparison_csv": "reports/common_intersection_benchmark/comparison.csv",
        "comparison_csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "report": "reports/common_intersection_benchmark/report.md",
        "report_sha256": hashlib.sha256(markdown_bytes).hexdigest(),
    }
    atomic_write_json(args.output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
