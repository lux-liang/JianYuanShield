from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import ASSETS, IMAGE_SUFFIXES, MANIFEST, REPORTS, ROOT, WEIGHT_SUFFIXES
from .utils import count_files, csv_row_count, load_json, safe_relative


def dataset_status(name: str, path: Path) -> dict[str, Any]:
    images = count_files(path, IMAGE_SUFFIXES)
    return {
        "name": name,
        "path": str(path),
        "relative_path": safe_relative(path),
        "exists": path.exists(),
        "files": count_files(path),
        "image_count": images,
        "ready": images > 0,
        "status": "ready" if images > 0 else "missing",
    }


def weight_status(name: str, path: Path) -> dict[str, Any]:
    checkpoints = count_files(path, WEIGHT_SUFFIXES)
    return {
        "name": name,
        "path": str(path),
        "relative_path": safe_relative(path),
        "exists": path.exists(),
        "files": count_files(path),
        "checkpoint_count": checkpoints,
        "ready": checkpoints > 0,
        "status": "ready" if checkpoints > 0 else "missing",
    }


def benchmark_status(name: str, directory: Path, summary_name: str = "summary.json") -> dict[str, Any]:
    summary_path = directory / summary_name
    progress_path = directory / "progress.json"
    results_path = directory / "results.csv"
    summary = load_json(summary_path, default={})
    progress = load_json(progress_path, default={})
    result_rows = csv_row_count(results_path, limit=200_000)
    benchmark_state = summary.get("status") or progress.get("status")
    if not benchmark_state:
        benchmark_state = "ready" if summary_path.exists() or results_path.exists() else "missing"
    ready = summary_path.exists() or results_path.exists()
    complete = benchmark_state == "complete" or progress.get("status") == "complete"
    return {
        "name": name,
        "path": str(directory),
        "relative_path": safe_relative(directory),
        "exists": directory.exists(),
        "files": count_files(directory),
        "summary_exists": summary_path.exists(),
        "progress_exists": progress_path.exists(),
        "results_csv_exists": results_path.exists(),
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
    files = {
        "json": directory / "report.json",
        "csv": directory / "report.csv",
        "markdown": directory / "report.md",
    }
    exists = {key: path.exists() for key, path in files.items()}
    ready = all(exists.values())
    return {
        "name": "competition_report",
        "path": str(directory),
        "relative_path": safe_relative(directory),
        "exists": directory.exists(),
        "files": count_files(directory),
        "required_files": {key: str(path) for key, path in files.items()},
        "required_exists": exists,
        "ready": ready,
        "status": "ready" if ready else "missing",
    }


def artifacts_status_payload() -> dict[str, Any]:
    legacy_groups = {
        "lidmark_smoke_checkpoints": ROOT / "weights/lidmark/smoke_128",
        "lidmark_official_or_small_data": ROOT / "datasets/celeba_hq_small",
        "mea_weights": ROOT / "weights/mea",
        "waveguard_weights": ROOT / "weights/waveguard",
        "kadnet_weights": ROOT / "weights/kadnet",
        "reports": REPORTS,
    }
    groups = {
        key: {"path": str(path), "files": count_files(path), "ready": count_files(path) > 0}
        for key, path in legacy_groups.items()
    }

    datasets = {
        "lfw_full": dataset_status("lfw_full", ROOT / "datasets/lfw_full_upload"),
        "lfw_unknown": dataset_status("lfw_unknown", ROOT / "datasets/lfw_full_upload/unknown"),
        "samples": dataset_status("samples", ROOT / "datasets/samples"),
        "celeba_hq_small": dataset_status("celeba_hq_small", ROOT / "datasets/celeba_hq_small"),
    }
    weights = {
        "mea": weight_status("mea", ROOT / "weights/mea"),
        "hidden": weight_status("hidden", ROOT / "weights/mea/HiDDeN"),
        "sepmark": weight_status("sepmark", ROOT / "weights/mea/SepMark"),
        "waveguard": weight_status("waveguard", ROOT / "weights/mea/WaveGuard"),
        "lidmark_smoke": weight_status("lidmark_smoke", ROOT / "weights/lidmark/smoke_128"),
        "kadnet": weight_status("kadnet", ROOT / "weights/kadnet"),
    }
    benchmarks = {
        "hidden_lfw_full": benchmark_status("hidden_lfw_full", REPORTS / "hidden_lfw_full_benchmark"),
        "sepmark_lfw": benchmark_status("sepmark_lfw", REPORTS / "sepmark_lfw_benchmark"),
        "lidmark_lfw_eval": benchmark_status("lidmark_lfw_eval", ROOT / "runs/lidmark_lfw_eval_full"),
        "waveguard_smoke": benchmark_status("waveguard_smoke", REPORTS / "waveguard_lfw_benchmark"),
        "waveguard_small": benchmark_status("waveguard_small", REPORTS / "waveguard_lfw_small_benchmark"),
        "waveguard_full": benchmark_status("waveguard_full", REPORTS / "waveguard_lfw_full_benchmark"),
        "aggregate": benchmark_status("aggregate", REPORTS / "aggregate_real_benchmarks"),
    }
    reports = {
        "competition": report_bundle_status(),
    }
    assets = {
        "root": {
            "path": str(ASSETS),
            "relative_path": safe_relative(ASSETS),
            "exists": ASSETS.exists(),
            "files": count_files(ASSETS),
            "ready": count_files(ASSETS) > 0,
            "status": "ready" if count_files(ASSETS) > 0 else "missing",
        },
        "hidden_grid": asset_status("hidden_grid", ASSETS / "real_hidden_benchmark/grid.png", "system/assets/real_hidden_benchmark/grid.png"),
        "sepmark_grid": asset_status("sepmark_grid", ASSETS / "sepmark_lfw_benchmark/grid.png", "system/assets/sepmark_lfw_benchmark/grid.png"),
        "degradation_curve": asset_status("degradation_curve", ASSETS / "aggregate_real_benchmarks/hidden_attack_degradation.png", "system/assets/aggregate_real_benchmarks/hidden_attack_degradation.png"),
    }

    manifest_items = []
    if MANIFEST.exists():
        for item in json.loads(MANIFEST.read_text(encoding="utf-8"))["items"]:
            target = ROOT / item["target_dir"]
            manifest_items.append({
                "project": item["project"],
                "name": item["name"],
                "provider": item["provider"],
                "target_dir": item["target_dir"],
                "files": count_files(target),
                "status": "ready" if count_files(target) else item["status"],
            })

    checks = {
        "dataset_ready": datasets["lfw_full"]["ready"] or datasets["lfw_unknown"]["ready"] or datasets["samples"]["ready"],
        "weights_ready": weights["mea"]["ready"] or weights["hidden"]["ready"] or weights["sepmark"]["ready"] or weights["waveguard"]["ready"] or weights["lidmark_smoke"]["ready"],
        "benchmark_ready": benchmarks["hidden_lfw_full"]["ready"] or benchmarks["sepmark_lfw"]["ready"] or benchmarks["waveguard_full"]["ready"] or benchmarks["waveguard_small"]["ready"],
        "aggregate_ready": benchmarks["aggregate"]["ready"],
        "report_ready": reports["competition"]["ready"],
        "assets_ready": assets["root"]["ready"],
    }
    required_for_demo = ["dataset_ready", "weights_ready", "benchmark_ready", "aggregate_ready", "report_ready"]
    missing = [key for key in required_for_demo if not checks[key]]
    ready_for_demo = not missing

    return {
        "generated_at": int(time.time()),
        "root": str(ROOT),
        "ready_for_demo": ready_for_demo,
        "checks": checks,
        "missing": missing,
        "summary": {
            "dataset_images": max(item["image_count"] for item in datasets.values()),
            "checkpoint_files": sum(item["checkpoint_count"] for item in weights.values()),
            "benchmark_outputs": sum(1 for item in benchmarks.values() if item["ready"]),
            "asset_files": count_files(ASSETS),
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
    exists = path.exists()
    return {
        "name": name,
        "path": str(path),
        "relative_path": relative_path,
        "exists": exists,
        "ready": exists,
        "status": "ready" if exists else "missing",
    }
