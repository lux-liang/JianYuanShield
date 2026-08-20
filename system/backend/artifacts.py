from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .config import ASSETS, IMAGE_SUFFIXES, MANIFEST, REPORTS, WEIGHT_SUFFIXES
from .security import resolve_path_within, safe_display_filename
from .utils import count_files, csv_row_count, load_json, safe_relative
from system.evaluation.runtime import DATA_ROOT, WEIGHT_ROOT


def _resolves_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def dataset_status(name: str, path: Path) -> dict[str, Any]:
    path_valid = _resolves_within(DATA_ROOT, path)
    images = count_files(path, IMAGE_SUFFIXES, root=DATA_ROOT) if path_valid else 0
    files = count_files(path, root=DATA_ROOT) if path_valid else 0
    return {
        "name": name,
        "path": safe_relative(path),
        "relative_path": safe_relative(path),
        "path_valid": path_valid,
        "exists": path_valid and path.exists(),
        "files": files,
        "image_count": images,
        "ready": images > 0,
        "status": "ready" if images > 0 else "missing",
    }


def weight_status(name: str, path: Path) -> dict[str, Any]:
    path_valid = _resolves_within(WEIGHT_ROOT, path)
    checkpoints = count_files(path, WEIGHT_SUFFIXES, root=WEIGHT_ROOT) if path_valid else 0
    files = count_files(path, root=WEIGHT_ROOT) if path_valid else 0
    return {
        "name": name,
        "path": safe_relative(path),
        "relative_path": safe_relative(path),
        "path_valid": path_valid,
        "exists": path_valid and path.exists(),
        "files": files,
        "checkpoint_count": checkpoints,
        "ready": checkpoints > 0,
        "status": "ready" if checkpoints > 0 else "missing",
    }


def benchmark_status(
    name: str,
    directory: Path,
    summary_name: str = "summary.json",
    results_name: str = "results.csv",
) -> dict[str, Any]:
    summary_path = directory / summary_name
    progress_path = directory / "progress.json"
    results_path = directory / results_name
    directory_safe = _resolves_within(REPORTS, directory)
    summary_safe = (
        directory_safe
        and _resolves_within(REPORTS, summary_path)
        and not summary_path.is_symlink()
    )
    progress_safe = (
        directory_safe
        and _resolves_within(REPORTS, progress_path)
        and not progress_path.is_symlink()
    )
    results_safe = (
        directory_safe
        and _resolves_within(REPORTS, results_path)
        and not results_path.is_symlink()
    )
    summary = load_json(summary_path, default={}) if summary_safe else {}
    progress = load_json(progress_path, default={}) if progress_safe else {}
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(progress, dict):
        progress = {}
    result_rows = csv_row_count(results_path, limit=200_000) if results_safe else 0
    summary_exists = summary_safe and summary_path.is_file()
    progress_exists = progress_safe and progress_path.is_file()
    results_exists = results_safe and results_path.is_file()
    benchmark_state = summary.get("status") or progress.get("status")
    if not benchmark_state:
        benchmark_state = "ready" if summary_exists or results_exists else "missing"
    ready = summary_exists or results_exists
    # Progress is operational state only. A release-complete benchmark needs
    # the final summary and raw result table; progress cannot promote it.
    complete = bool(
        summary_exists
        and results_exists
        and summary.get("status") == "complete"
    )
    return {
        "name": name,
        "path": safe_relative(directory),
        "relative_path": safe_relative(directory),
        "exists": directory_safe and directory.exists(),
        "files": count_files(directory, root=REPORTS) if directory_safe else 0,
        "summary_exists": summary_exists,
        "progress_exists": progress_exists,
        "results_csv_exists": results_exists,
        "results_file": results_name,
        "result_rows": result_rows,
        "status": benchmark_state,
        "complete": complete,
        "ready": ready,
        "num_images": summary.get("num_images") or summary.get("images") or summary.get("requested_images") or progress.get("num_images") or progress.get("processed_images"),
        "mode": summary.get("mode"),
        "data_type": summary.get("data_type"),
    }


def report_bundle_status() -> dict[str, Any]:
    directory = REPORTS / "jianyuanshield_competition_report"
    directory_safe = _resolves_within(REPORTS, directory)
    files = {
        "json": directory / "report.json",
        "csv": directory / "report.csv",
        "markdown": directory / "report.md",
    }
    exists = {
        key: (
            directory_safe
            and _resolves_within(REPORTS, path)
            and path.is_file()
            and not path.is_symlink()
        )
        for key, path in files.items()
    }
    ready = all(exists.values())
    return {
        "name": "competition_report",
        "path": safe_relative(directory),
        "relative_path": safe_relative(directory),
        "exists": directory_safe and directory.exists(),
        "files": count_files(directory, root=REPORTS) if directory_safe else 0,
        "required_files": {key: safe_relative(path) for key, path in files.items()},
        "required_exists": exists,
        "ready": ready,
        "status": "ready" if ready else "missing",
    }


def artifacts_status_payload() -> dict[str, Any]:
    legacy_groups = {
        "lidmark_smoke_checkpoints": (WEIGHT_ROOT / "lidmark/smoke_128", WEIGHT_ROOT),
        "lidmark_official_or_small_data": (DATA_ROOT / "celeba_hq_small", DATA_ROOT),
        "mea_weights": (WEIGHT_ROOT / "mea", WEIGHT_ROOT),
        "waveguard_weights": (WEIGHT_ROOT / "waveguard", WEIGHT_ROOT),
        "kadnet_weights": (WEIGHT_ROOT / "kadnet", WEIGHT_ROOT),
        "reports": (REPORTS, REPORTS),
    }
    groups = {}
    for key, (path, root) in legacy_groups.items():
        path_valid = _resolves_within(root, path)
        file_count = count_files(path, root=root) if path_valid else 0
        groups[key] = {
            "path": safe_relative(path),
            "files": file_count,
            "path_valid": path_valid,
            "ready": file_count > 0,
        }

    datasets = {
        "lfw_full": dataset_status("lfw_full", DATA_ROOT / "lfw_full_upload"),
        "lfw_unknown": dataset_status("lfw_unknown", DATA_ROOT / "lfw_full_upload/unknown"),
        "lfw_protocol_full": dataset_status(
            "lfw_protocol_full",
            DATA_ROOT / "lfw/processed/image/lfw_128",
        ),
        "lidmark_identity_disjoint": dataset_status(
            "lidmark_identity_disjoint",
            DATA_ROOT / "lfw/lidmark_identity_disjoint/image/lfw_128/test",
        ),
        "samples": dataset_status("samples", DATA_ROOT / "samples"),
        "celeba_hq_small": dataset_status("celeba_hq_small", DATA_ROOT / "celeba_hq_small"),
    }
    weights = {
        "mea": weight_status("mea", WEIGHT_ROOT / "mea"),
        "hidden": weight_status("hidden", WEIGHT_ROOT / "mea/HiDDeN"),
        "sepmark": weight_status("sepmark", WEIGHT_ROOT / "mea/SepMark"),
        "waveguard": weight_status("waveguard", WEIGHT_ROOT / "mea/WaveGuard"),
        "lidmark_smoke": weight_status("lidmark_smoke", WEIGHT_ROOT / "lidmark/smoke_128"),
        "kadnet": weight_status("kadnet", WEIGHT_ROOT / "kadnet"),
    }
    benchmarks = {
        "hidden_lfw_full": benchmark_status("hidden_lfw_full", REPORTS / "hidden_lfw_full_benchmark"),
        "sepmark_lfw": benchmark_status("sepmark_lfw", REPORTS / "sepmark_lfw_benchmark"),
        "lidmark_lfw_eval": benchmark_status(
            "lidmark_lfw_eval",
            REPORTS / "lidmark_lfw_identity_test_epoch20_protocol_v1",
            results_name="raw_results.csv",
        ),
        "kadnet_lfw": benchmark_status("kadnet_lfw", REPORTS / "kadnet_lfw_benchmark"),
        "waveguard_lfw": benchmark_status(
            "waveguard_lfw",
            REPORTS / "waveguard_lfw_benchmark",
        ),
        "aggregate": benchmark_status(
            "aggregate",
            REPORTS / "aggregate_real_benchmarks",
            results_name="method_comparison.csv",
        ),
    }
    reports = {
        "competition": report_bundle_status(),
    }
    asset_file_count = count_files(ASSETS, root=ASSETS)
    assets = {
        "root": {
            "path": safe_relative(ASSETS),
            "relative_path": safe_relative(ASSETS),
            "exists": ASSETS.exists(),
            "files": asset_file_count,
            "ready": asset_file_count > 0,
            "status": "ready" if asset_file_count > 0 else "missing",
        },
        "hidden_grid": asset_status("hidden_grid", ASSETS / "real_hidden_benchmark/grid.png", "system/assets/real_hidden_benchmark/grid.png"),
        "sepmark_grid": asset_status("sepmark_grid", ASSETS / "sepmark_lfw_benchmark/grid.png", "system/assets/sepmark_lfw_benchmark/grid.png"),
        "degradation_curve": asset_status("degradation_curve", ASSETS / "aggregate_real_benchmarks/attack_degradation.png", "system/assets/aggregate_real_benchmarks/attack_degradation.png"),
    }

    manifest_items = []
    try:
        manifest_relative = MANIFEST.relative_to(WEIGHT_ROOT)
    except ValueError:
        manifest_path = None
    else:
        manifest_path = resolve_path_within(WEIGHT_ROOT, manifest_relative)
    if manifest_path is not None and not manifest_path.is_symlink() and manifest_path.is_file():
        manifest = load_json(manifest_path, default={})
        raw_items = manifest.get("items", []) if isinstance(manifest, dict) else []
        if not isinstance(raw_items, list):
            raw_items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            relative = str(item.get("target_dir") or item.get("file") or "")
            weight_relative = relative.removeprefix("weights/")
            target = resolve_path_within(WEIGHT_ROOT, weight_relative)
            path_valid = bool(weight_relative and target is not None)
            logical_target = f"weights/{weight_relative}" if path_valid else None
            manifest_items.append({
                "project": item.get("model") or item.get("project"),
                "name": safe_display_filename(
                    str(item.get("name") or relative),
                    fallback="unnamed-weight",
                ),
                "provider": item.get("provider") or item.get("reviewed_by"),
                "target_dir": logical_target,
                "path_valid": path_valid,
                "files": (
                    count_files(target, root=WEIGHT_ROOT)
                    if target is not None and path_valid else 0
                ),
                "status": item.get("status", "unreviewed") if path_valid else "invalid_path",
                "hash_registered": bool(item.get("sha256") or item.get("checkpoint_sha256")),
            })

    formal_dataset_ready = (
        datasets["lfw_protocol_full"]["ready"]
        and datasets["lidmark_identity_disjoint"]["ready"]
    )
    checks = {
        "dataset_ready": (
            formal_dataset_ready
            or datasets["lfw_full"]["ready"]
            or datasets["lfw_unknown"]["ready"]
            or datasets["samples"]["ready"]
        ),
        "formal_dataset_ready": formal_dataset_ready,
        "weights_ready": weights["mea"]["ready"] or weights["hidden"]["ready"] or weights["sepmark"]["ready"] or weights["waveguard"]["ready"] or weights["lidmark_smoke"]["ready"],
        "benchmark_ready": (
            benchmarks["hidden_lfw_full"]["complete"]
            or benchmarks["sepmark_lfw"]["complete"]
            or benchmarks["lidmark_lfw_eval"]["complete"]
            or benchmarks["kadnet_lfw"]["complete"]
            or benchmarks["waveguard_lfw"]["complete"]
        ),
        "aggregate_ready": benchmarks["aggregate"]["complete"],
        "report_ready": reports["competition"]["ready"],
        "assets_ready": assets["root"]["ready"],
    }
    required_for_demo = ["dataset_ready", "weights_ready", "benchmark_ready", "aggregate_ready", "report_ready"]
    missing = [key for key in required_for_demo if not checks[key]]
    ready_for_demo = not missing

    return {
        "generated_at": int(time.time()),
        "root": ".",
        "ready_for_demo": ready_for_demo,
        "checks": checks,
        "missing": missing,
        "summary": {
            "dataset_images": max(item["image_count"] for item in datasets.values()),
            "checkpoint_files": sum(item["checkpoint_count"] for item in weights.values()),
            "benchmark_outputs": sum(1 for item in benchmarks.values() if item["ready"]),
            "asset_files": asset_file_count,
            "status": "ready" if ready_for_demo else "incomplete",
        },
        "groups": groups,
        "datasets": datasets,
        "weights": weights,
        "benchmarks": benchmarks,
        "reports": reports,
        "assets": assets,
        "manifest": manifest_items,
    }


def asset_status(name: str, path: Path, relative_path: str) -> dict[str, Any]:
    exists = _resolves_within(ASSETS, path) and path.is_file() and not path.is_symlink()
    return {
        "name": name,
        "path": safe_relative(path),
        "relative_path": relative_path,
        "exists": exists,
        "ready": exists,
        "status": "ready" if exists else "missing",
    }
