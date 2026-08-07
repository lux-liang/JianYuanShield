from __future__ import annotations

import csv
import io
import json
import math
import sys
from itertools import combinations
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.backend.utils import atomic_write_bytes, atomic_write_json  # noqa: E402
from system.backend.signing import verify_evidence_bundle  # noqa: E402
from system.evaluation.runtime import (  # noqa: E402
    REPORT_ROOT,
    logical_path,
    resolve_logical_path,
)
from system.evaluation.statistics import (  # noqa: E402
    bootstrap_ci,
    holm_adjust,
    paired_bootstrap_difference,
    paired_effect_size,
    paired_sign_flip_test,
)


SOURCES = {
    "SepMark": (
        REPORT_ROOT / "sepmark_lfw_benchmark" / "results.csv",
        ("bit_accuracy_c",),  # protocol v1: decoder_C is primary
    ),
    "WaveGuard": (
        REPORT_ROOT / "waveguard_lfw_benchmark" / "results.csv",
        ("bit_accuracy_tracer",),
    ),
    "LIDMark": (
        REPORT_ROOT
        / "lidmark_lfw_identity_test_epoch20_protocol_v1"
        / "raw_results.csv",
        ("bit_accuracy",),
    ),
    "KAD-Net": (
        REPORT_ROOT / "kadnet_lfw_benchmark" / "results.csv",
        ("bit_accuracy",),
    ),
}

def load_source(
    path: Path,
    metric_candidates: tuple[str, ...],
) -> tuple[dict[tuple[str, str], float], dict[str, object]]:
    summary_path = path.parent / "summary.json"
    if not path.is_file() or not summary_path.is_file():
        raise FileNotFoundError(logical_path(path if not path.is_file() else summary_path))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError(f"summary must be an object: {logical_path(summary_path)}")
    sample_count = summary.get("num_images") or summary.get("sample_count")
    attack_ids = summary.get("attack_ids")
    results_reference = summary.get("results_csv_path")
    declared_results = (
        resolve_logical_path(results_reference)
        if isinstance(results_reference, str)
        else None
    )
    if (
        not isinstance(summary, dict)
        or summary.get("schema_version") != "benchmark-summary.v2"
        or summary.get("status") != "complete"
        or not isinstance(sample_count, int)
        or sample_count <= 0
        or not isinstance(attack_ids, list)
        or not attack_ids
        or any(not isinstance(attack_id, str) or not attack_id for attack_id in attack_ids)
        or len(attack_ids) != len(set(attack_ids))
        or declared_results is None
        or declared_results.resolve() != path.resolve()
        or summary.get("results_csv_sha256") != sha256_file(path)
    ):
        raise ValueError(f"incomplete or hash-mismatched summary: {logical_path(summary_path)}")
    expected_rows = sample_count * len(attack_ids)
    values: dict[tuple[str, str], float] = {}
    image_ids_by_attack: dict[str, set[str]] = {
        str(attack_id): set() for attack_id in attack_ids
    }
    rows = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        primary_metric = next(
            (name for name in metric_candidates if name in fieldnames),
            None,
        )
        if primary_metric is None:
            raise ValueError(f"primary metric column missing in {logical_path(path)}")
        for row in reader:
            rows += 1
            image_id = row.get("image_id")
            attack = row.get("attack_type")
            if not image_id or attack not in attack_ids or row.get("error"):
                raise ValueError(f"invalid evidence row in {logical_path(path)}")
            raw = row.get(primary_metric)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"invalid primary metric in {logical_path(path)}")
            key = (image_id, attack)
            if not math.isfinite(value) or not 0 <= value <= 1 or key in values:
                raise ValueError(f"invalid or duplicate evidence row in {logical_path(path)}")
            values[key] = value
            image_ids_by_attack[str(attack)].add(image_id)
    if rows != expected_rows or len(values) != expected_rows:
        raise ValueError(
            f"raw coverage mismatch for {logical_path(path)}: {rows}/{expected_rows}"
        )
    sample_sets = [image_ids_by_attack[str(attack_id)] for attack_id in attack_ids]
    if (
        not sample_sets
        or any(len(sample_ids) != sample_count for sample_ids in sample_sets)
        or any(sample_ids != sample_sets[0] for sample_ids in sample_sets[1:])
    ):
        raise ValueError(
            f"per-attack sample set mismatch for {logical_path(path)}"
        )
    return values, {
        "path": logical_path(path),
        "summary_path": logical_path(summary_path),
        "rows": rows,
        "sha256": sha256_file(path),
        "summary_sha256": sha256_file(summary_path),
        "sample_count": sample_count,
        "attack_count": len(attack_ids),
        "primary_metric": primary_metric,
        "per_attack_sample_set_valid": True,
    }

def main() -> int:
    data: dict[str, dict[tuple[str, str], float]] = {}
    source_audit: dict[str, dict[str, object]] = {}
    signature = verify_evidence_bundle()
    signature_ready = bool(
        signature.get("verified") is True
        and signature.get("profile") in {"release-core", "release"}
        and signature.get("signer_pinned") is True
    )
    for name, (path, candidates) in SOURCES.items():
        if not signature_ready:
            source_audit[name] = {
                "status": "blocked",
                "path": logical_path(path),
                "error": "evidence_signature_unverified",
            }
            continue
        try:
            values, audit = load_source(path, candidates)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as error:
            source_audit[name] = {
                "status": "blocked",
                "path": logical_path(path),
                "error": error.__class__.__name__,
            }
        else:
            data[name] = values
            source_audit[name] = {"status": "verified", **audit}
    attacks = sorted({attack for values in data.values() for _, attack in values})
    summaries = []
    for method, values in data.items():
        for attack in attacks:
            sample = [value for (image_id, attack_id), value in values.items() if attack_id == attack]
            if not sample:
                continue
            interval = bootstrap_ci(sample)
            summaries.append({
                "method": method,
                "attack": attack,
                "count": interval.samples,
                "mean": interval.mean,
                "ci95_low": interval.low,
                "ci95_high": interval.high,
            })

    comparisons = []
    for attack in attacks:
        for first_name, second_name in combinations(data, 2):
            first = data[first_name]
            second = data[second_name]
            common = sorted(
                key for key in first.keys() & second.keys()
                if key[1] == attack
            )
            if len(common) < 2:
                continue
            first_values = [first[key] for key in common]
            second_values = [second[key] for key in common]
            interval = paired_bootstrap_difference(first_values, second_values)
            effect_size = paired_effect_size(first_values, second_values)
            comparisons.append({
                "attack": attack,
                "first": first_name,
                "second": second_name,
                "pairs": len(common),
                "mean_difference": interval.mean,
                "ci95_low": interval.low,
                "ci95_high": interval.high,
                "effect_size_dz": effect_size if math.isfinite(effect_size) else None,
                "p_value": paired_sign_flip_test(first_values, second_values),
            })
    adjusted = holm_adjust(item["p_value"] for item in comparisons)
    for item, value in zip(comparisons, adjusted):
        item["p_value_holm"] = value
        item["significant_0_05"] = value < 0.05

    if not SOURCES or len(data) != len(SOURCES):
        status = "blocked_incomplete_sources"
    elif not summaries or not comparisons:
        status = "blocked_incomplete_analysis"
    else:
        status = "complete"
    payload = {
        "schema_version": "statistical-analysis.v1",
        "status": status,
        "metric": "bit_accuracy",
        "seed_count": {name: 1 for name in data},
        "seed_status": "single_frozen_protocol_run_per_available_method",
        "bootstrap_resamples": 5000,
        "sign_flip_permutations": 20000,
        "project_root": ".",
        "evidence_signature": {
            "status": signature.get("status", "not_generated"),
            "profile": signature.get("profile"),
            "verified": signature.get("verified") is True,
            "signer_pinned": signature.get("signer_pinned") is True,
            "manifest_sha256": signature.get("manifest_sha256"),
            "public_key_fingerprint_sha256": signature.get(
                "public_key_fingerprint_sha256"
            ),
        },
        "sources": source_audit,
        "summaries": summaries,
        "comparisons": comparisons,
        "limitations": [
            "Each method contributes one frozen protocol run; intervals quantify image-sampling uncertainty only.",
            "The identity-disjoint LIDMark test set differs from the other methods; paired tests are emitted only for overlapping image IDs.",
            "Independent reruns are required before making between-seed variance claims.",
        ],
    }
    output = REPORT_ROOT / "statistical_analysis"
    output.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output / "analysis.json", payload)
    fields = list(comparisons[0]) if comparisons else ["attack", "first", "second"]
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(comparisons)
    atomic_write_bytes(
        output / "comparisons.csv",
        csv_buffer.getvalue().encode("utf-8"),
    )
    print(json.dumps({
        "status": payload["status"],
        "summaries": len(summaries),
        "comparisons": len(comparisons),
        "seed_status": payload["seed_status"],
        "output": str(output),
    }, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
