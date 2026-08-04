from __future__ import annotations

from pathlib import Path
from typing import Any

from .benchmark_evidence import benchmark_claim_status
from .config import ASSETS, REPORTS, ROOT
from .mea_evidence import MEA_RUN_ID, validate_mea_matrix_evidence
from .simswap_evidence import (
    SIMSWAP_ARTIFACT_LIMIT,
    SIMSWAP_CALIBRATION_PAIRS,
    SIMSWAP_MODELS,
    SIMSWAP_NUM_PAIRS,
    SIMSWAP_RUN_ID,
    validate_simswap_lfw_evidence,
)
from .normalization import normalize_benchmark
from .utils import asset_if_exists, load_json, numeric, path_status, read_csv_records


PROJECTS = [
    {
        "id": "LIDMark",
        "role": "mainline",
        "title": "Creator-bound active provenance candidate",
        "status": "implementation_available_evidence_review_required",
    },
    {
        "id": "MEA",
        "role": "attack_evaluation",
        "title": "Multi-Embedding Attack red-team protocol",
        "status": "formal_n256_evidence_signature_gated",
    },
    {
        "id": "WaveGuard",
        "role": "baseline",
        "title": "Frequency-domain proactive watermark baseline",
        "status": "adapter_available_evidence_review_required",
    },
    {
        "id": "KAD-Net",
        "role": "baseline",
        "title": "Kolmogorov-Arnold proactive forensics baseline",
        "status": "adapter_available_checkpoint_required",
    },
]


def _public_path(path: Path) -> str:
    """Return a repository-relative diagnostic path without leaking the host root."""
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return path.name


def _artifact_claim_status(
    summary: dict[str, Any],
    summary_path: Path,
    results_path: Path,
) -> dict[str, Any]:
    return benchmark_claim_status(
        summary,
        summary_path=summary_path,
        results_path=results_path,
    )


def summarize_hidden_results(path: Path) -> dict[str, Any] | None:
    rows = read_csv_records(path, limit=1_000_000)
    if not rows:
        return None
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get("attack_type", "unknown"), []).append(row)
    attacks: dict[str, Any] = {}
    for attack, attack_rows in grouped.items():
        def mean(key: str) -> float | None:
            vals = [numeric(row.get(key)) for row in attack_rows]
            vals = [v for v in vals if v is not None]
            return round(sum(vals) / len(vals), 6) if vals else None

        success_vals = [numeric(row.get("success")) for row in attack_rows]
        success_vals = [v for v in success_vals if v is not None]
        attacks[attack] = {
            "status": "partial",
            "count": len(attack_rows),
            "mean_bit_error": mean("bit_error"),
            "mean_bit_accuracy": mean("bit_accuracy"),
            "mean_psnr": mean("psnr"),
            "mean_ssim": mean("ssim"),
            "success_rate": round(sum(success_vals) / len(success_vals), 6) if success_vals else None,
        }
    return {
        "method": "MEA/HiDDeN",
        "mode": "real_checkpoint",
        "data_type": "real_lfw_images",
        "status": "running_partial",
        "evaluated_rows": len(rows),
        "num_images": len({row.get("image_id") for row in rows if row.get("image_id")}),
        "attacks": attacks,
        "success_definition": "bit_accuracy >= 0.9",
    }


def benchmark_payload(summary_path: Path, progress_path: Path, results_path: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = load_json(summary_path)
    progress = load_json(progress_path)
    if results_path.name == "results.csv" and "hidden_lfw_full_benchmark" in str(results_path):
        partial = summarize_hidden_results(results_path)
        if partial and progress.get("status") != "complete":
            partial["progress"] = progress
            summary = partial
    payload = {
        "summary": summary,
        "progress": progress,
        "results_csv_path": _public_path(results_path),
        "results_csv_exists": results_path.exists(),
        "sample_results": read_csv_records(results_path, limit=40),
    }
    payload.update(_artifact_claim_status(
        summary if isinstance(summary, dict) else {},
        summary_path,
        results_path,
    ))
    if extra:
        payload.update(extra)
    payload["normalized"] = normalize_benchmark(
        summary=summary if isinstance(summary, dict) else {},
        progress=progress if isinstance(progress, dict) else {},
        method=str(payload.get("method") or "unknown"),
        checkpoint_type=str(payload.get("checkpoint_type") or "unknown"),
        data_type=str(payload.get("data_type") or "unknown"),
        results_csv_exists=results_path.exists(),
    )
    return payload


def hidden_lfw_full_payload() -> dict[str, Any]:
    report_dir = REPORTS / "hidden_lfw_full_benchmark"
    return benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "MEA/HiDDeN",
            "checkpoint_type": "configured_checkpoint_identity_unverified",
            "data_type": "real_lfw_images",
            "grid_image": asset_if_exists("real_hidden_benchmark/grid.png"),
            "asset_dir": _public_path(ASSETS / "real_hidden_benchmark"),
        },
    )


def lidmark_lfw_eval_payload() -> dict[str, Any]:
    report_dir = REPORTS / "lidmark_lfw_identity_test_epoch20_protocol_v1"
    return benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "raw_results.csv",
        {
            "method": "LIDMark",
            "checkpoint_type": "selected_epoch20_identity_disjoint",
            "data_type": "lfw_identity_disjoint_test",
        },
    )


def sepmark_benchmark_payload() -> dict[str, Any]:
    report_dir = REPORTS / "sepmark_lfw_benchmark"
    return benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "SepMark",
            "checkpoint_type": "configured_checkpoint_identity_unverified",
            "data_type": "real_lfw_images",
            "grid_image": asset_if_exists("sepmark_lfw_benchmark/grid.png"),
            "asset_dir": _public_path(ASSETS / "sepmark_lfw_benchmark"),
        },
    )


def waveguard_benchmark_payload() -> dict[str, Any]:
    report_dir = REPORTS / "waveguard_lfw_benchmark"
    payload = benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "WaveGuard",
            "checkpoint_type": "official_checkpoint_strict",
            "data_type": "real_lfw_images",
            "grid_image": asset_if_exists("waveguard_lfw_benchmark/grid.png"),
        },
    )
    payload["full_benchmark"] = dict(payload)
    return payload



def mea_matrix_payload() -> dict[str, Any]:
    mea_dir = REPORTS / MEA_RUN_ID
    summary = load_json(mea_dir / "summary.json", default={})
    validation = validate_mea_matrix_evidence(
        directory=mea_dir,
        require_signature=True,
    )
    claim_valid = validation.get("valid") is True
    return {
        "method": "MEA",
        "run_id": MEA_RUN_ID,
        "images_per_cell": summary.get("images_per_cell"),
        "models": summary.get("models", []),
        "matrix": summary.get("matrix", {}),
        "markdown_table": summary.get("markdown_table", ""),
        "coverage": summary.get("coverage", {}),
        "checkpoint_evidence": summary.get("checkpoint_evidence", {}),
        "generated_at": summary.get("generated_at"),
        "status": "verified" if claim_valid else "review_required",
        "claim_valid": claim_valid,
        "claim_status": (
            "evidence_verified" if claim_valid else "mea_evidence_review_required"
        ),
        "evidence_validation": validation,
    }


def simswap_lfw_payload() -> dict[str, Any]:
    report_dir = REPORTS / SIMSWAP_RUN_ID
    summary = load_json(report_dir / "summary.json", default={})
    validation = validate_simswap_lfw_evidence(
        directory=report_dir,
        require_signature=True,
    )
    expected_holdout_pairs = SIMSWAP_NUM_PAIRS - SIMSWAP_CALIBRATION_PAIRS
    expected_result_rows = SIMSWAP_NUM_PAIRS * len(SIMSWAP_MODELS)
    expected_identity_rows = SIMSWAP_NUM_PAIRS * (3 + len(SIMSWAP_MODELS))
    expected_asset_count = SIMSWAP_ARTIFACT_LIMIT * (3 + 2 * len(SIMSWAP_MODELS))
    expected_controls = (
        "registered_positive",
        "unwatermarked_negative",
        "wrong_message_negative",
        "cross_record_negative",
    )
    signature = validation.get("signature")
    signature = signature if isinstance(signature, dict) else {}
    coverage = {
        "num_pairs": summary.get("num_pairs"),
        "calibration_pairs": summary.get("calibration_pairs"),
        "holdout_pairs": summary.get("holdout_pairs"),
        "result_rows": summary.get("result_rows"),
        "expected_result_rows": summary.get("expected_result_rows"),
        "identity_embedding_rows": summary.get("identity_embedding_rows"),
        "expected_identity_embedding_rows": summary.get(
            "expected_identity_embedding_rows"
        ),
        "error_rows": summary.get("error_rows"),
        "identity_overlap_count": summary.get("identity_overlap_count"),
        "asset_count": validation.get("asset_count"),
        "expected_asset_count": expected_asset_count,
    }
    schema_verified = (
        summary.get("schema_version") == "simswap-lfw-robustness-summary.v1"
        and summary.get("run_class") == "real_n256_evidence"
        and validation.get("schema_version")
        == "simswap-lfw-evidence-status.v1"
    )
    run_id_verified = validation.get("run_id") == SIMSWAP_RUN_ID
    coverage_verified = coverage == {
        "num_pairs": SIMSWAP_NUM_PAIRS,
        "calibration_pairs": SIMSWAP_CALIBRATION_PAIRS,
        "holdout_pairs": expected_holdout_pairs,
        "result_rows": expected_result_rows,
        "expected_result_rows": expected_result_rows,
        "identity_embedding_rows": expected_identity_rows,
        "expected_identity_embedding_rows": expected_identity_rows,
        "error_rows": 0,
        "identity_overlap_count": 0,
        "asset_count": expected_asset_count,
        "expected_asset_count": expected_asset_count,
    } and all(
        (
            validation.get("num_pairs") == SIMSWAP_NUM_PAIRS,
            validation.get("calibration_pairs") == SIMSWAP_CALIBRATION_PAIRS,
            validation.get("holdout_pairs") == expected_holdout_pairs,
            validation.get("result_rows") == expected_result_rows,
            validation.get("identity_embedding_rows") == expected_identity_rows,
            validation.get("identity_overlap_count") == 0,
        )
    )
    model_contract_verified = (
        summary.get("models") == list(SIMSWAP_MODELS)
        and summary.get("controls") == list(expected_controls)
        and isinstance(summary.get("model_results"), dict)
        and set(summary["model_results"]) == set(SIMSWAP_MODELS)
    )
    engine = summary.get("engine")
    official_engine_verified = (
        isinstance(engine, dict)
        and engine.get("engine") == "SimSwap"
        and engine.get("mode") == "official_release_checkpoint"
    )
    signature_verified = (
        signature.get("schema_version") == "evidence-signature-status.v1"
        and signature.get("verified") is True
        and signature.get("signature_valid") is True
        and signature.get("status") == "verified"
        and signature.get("profile") in {"release-core", "release"}
        and signature.get("mismatches") == []
    )
    signer_pinned = signature.get("signer_pinned") is True
    # The strict validator reaches ``valid=True`` only after recomputing and
    # comparing the complete implementation manifest.  Expose that gate
    # explicitly so clients never infer implementation trust from ``status``.
    implementation_hashes_verified = validation.get("valid") is True
    release_gate = {
        "schema_verified": schema_verified,
        "run_id_verified": run_id_verified,
        "coverage_verified": coverage_verified,
        "model_contract_verified": model_contract_verified,
        "official_engine_verified": official_engine_verified,
        "implementation_hashes_verified": implementation_hashes_verified,
        "signature_verified": signature_verified,
        "signer_pinned": signer_pinned,
    }
    claim_valid = (
        validation.get("valid") is True
        and validation.get("status") == "verified"
        and all(value is True for value in release_gate.values())
    )
    return {
        "schema_version": "simswap-lfw-benchmark.v1",
        "method": "official SimSwap",
        "run_id": SIMSWAP_RUN_ID,
        "run_class": summary.get("run_class"),
        "evidence_schema_version": summary.get("schema_version"),
        "scope": {
            "dataset": "LFW",
            "num_pairs": summary.get("num_pairs"),
            "calibration_pairs": summary.get("calibration_pairs"),
            "holdout_pairs": summary.get("holdout_pairs"),
            "identity_overlap_count": summary.get("identity_overlap_count"),
        },
        "models": summary.get("models", []),
        "model_results": summary.get("model_results", {}),
        "controls": summary.get("controls", []),
        "engine": engine if isinstance(engine, dict) else {},
        "coverage": coverage,
        "release_gate": release_gate,
        "status": "verified" if claim_valid else "review_required",
        "claim_valid": claim_valid,
        "claim_status": (
            "evidence_verified"
            if claim_valid
            else "simswap_evidence_review_required"
        ),
        "evidence_validation": validation,
    }

def kadnet_benchmark_payload() -> dict[str, Any]:
    report_dir = REPORTS / "kadnet_lfw_benchmark"
    return benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "KAD-Net",
            "checkpoint_type": "official_epoch100_strict",
            "data_type": "real_lfw_images",
        },
    )

def aggregate_benchmark_payload() -> dict[str, Any]:
    report_dir = REPORTS / "aggregate_real_benchmarks"
    return {
        "claim_valid": False,
        "claim_status": "evidence_review_required",
        "summary": load_json(report_dir / "summary.json"),
        "comparison_csv_path": _public_path(report_dir / "method_comparison.csv"),
        "comparison": read_csv_records(report_dir / "method_comparison.csv", limit=100),
        "report_md_path": _public_path(report_dir / "aggregate_report.md"),
        "degradation_curve": asset_if_exists("aggregate_real_benchmarks/attack_degradation.png"),
        "paths": {
            "hidden": path_status(REPORTS / "hidden_lfw_full_benchmark"),
            "sepmark": path_status(REPORTS / "sepmark_lfw_benchmark"),
            "lidmark": path_status(
                REPORTS / "lidmark_lfw_identity_test_epoch20_protocol_v1"
            ),
            "waveguard": path_status(REPORTS / "waveguard_lfw_benchmark"),
            "kadnet": path_status(REPORTS / "kadnet_lfw_benchmark"),
        },
    }


def competition_report_payload() -> dict[str, Any]:
    report_dir = REPORTS / "jianyuanshield_competition_report"
    return {
        "claim_valid": False,
        "claim_status": "evidence_review_required",
        "report": load_json(report_dir / "report.json"),
        "json_path": _public_path(report_dir / "report.json"),
        "csv_path": _public_path(report_dir / "report.csv"),
        "markdown_path": _public_path(report_dir / "report.md"),
        "exists": {
            "json": (report_dir / "report.json").exists(),
            "csv": (report_dir / "report.csv").exists(),
            "markdown": (report_dir / "report.md").exists(),
        },
    }


def modules_payload() -> list[dict[str, Any]]:
    hidden = load_json(REPORTS / "hidden_lfw_full_benchmark" / "summary.json")
    sepmark = load_json(REPORTS / "sepmark_lfw_benchmark" / "summary.json")
    report_exists = (REPORTS / "jianyuanshield_competition_report" / "report.json").exists()
    return [
        {
            "name": "内容保护",
            "function": "使用主动水印/主动取证模型生成可验证保护信号。",
            "model_status": "provenance lifecycle implemented; checkpoint-backed validation required",
            "result": "implemented_pending_validation",
            "sample": asset_if_exists("real_hidden_benchmark/grid.png"),
            "metrics": "BER, bit accuracy, PSNR, SSIM",
            "defense_ready": False,
        },
        {
            "name": "Deepfake 攻击模拟",
            "function": "使用固定官方 SimSwap 与 ArcFace 对四种水印执行身份不重叠的人脸交换评测。",
            "model_status": "official SimSwap/LFW n256 evidence is signature gated",
            "result": "real_n256_evidence_available",
            "sample": asset_if_exists(
                f"{SIMSWAP_RUN_ID}/pair_00001/swapped_clean.png"
            ),
            "metrics": "holdout TAR, FRR, FAR, ArcFace identity migration, PSNR and SSIM",
            "defense_ready": True,
        },
        {
            "name": "MEA 多重嵌入攻击",
            "function": "评测多种主动水印 baseline 在攻击下的鲁棒性。",
            "model_status": "protocol and adapter contract implemented; repository-tracked checkpoint matrix required",
            "result": "protocol_ready_results_pending",
            "sample": asset_if_exists("sepmark_lfw_benchmark/grid.png") or asset_if_exists("aggregate_real_benchmarks/attack_degradation.png"),
            "metrics": "method comparison by attack type",
            "defense_ready": False,
        },
        {
            "name": "取证恢复",
            "function": "从攻击后图像恢复消息/身份信号并输出取证指标。",
            "model_status": "decode-only provenance API implemented; unavailable checkpoints fail closed",
            "result": "implemented_pending_validation",
            "sample": asset_if_exists("sepmark_lfw_benchmark/grid.png"),
            "metrics": "decoded bit accuracy, LIDMark ID BER, landmark AED",
            "defense_ready": False,
        },
        {
            "name": "安全评测",
            "function": "按统一协议聚合 checkpoint、数据清单和逐图攻击结果。",
            "model_status": "claim-as-code gate blocks unverified performance claims",
            "result": "evidence_review_required",
            "sample": asset_if_exists("aggregate_real_benchmarks/attack_degradation.png"),
            "metrics": "cross-method comparison",
            "defense_ready": False,
        },
        {
            "name": "取证报告",
            "function": "导出 JSON、CSV、Markdown 格式的答辩取证报告。",
            "model_status": "report exporter available",
            "result": "artifact_present_unreviewed" if report_exists else "pending",
            "sample": None,
            "metrics": "report completeness and evidence paths",
            "defense_ready": False,
        },
    ]
