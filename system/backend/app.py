from __future__ import annotations

import io
import json
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image, ImageDraw
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "datasets" / "samples"
REPORTS = ROOT / "system" / "reports"
ASSETS = ROOT / "system" / "assets"
MANIFEST = ROOT / "weights" / "WEIGHT_MANIFEST.json"

for directory in (DATASETS, REPORTS, ASSETS):
    directory.mkdir(parents=True, exist_ok=True)


class DemoRunRequest(BaseModel):
    sample_id: str = "sample_face_001"
    project: str = "LIDMark"
    attack: str = "multi_embedding+jpeg_50+blur"


app = FastAPI(title="VPSG Deepfake Active Forensics Competition System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/artifacts", StaticFiles(directory=str(ASSETS)), name="artifacts")


PROJECTS = [
    {
        "id": "LIDMark",
        "role": "mainline",
        "title": "Deepfake detection, tampering localization, and source tracing",
        "status": "training_pending",
    },
    {
        "id": "MEA",
        "role": "attack_evaluation",
        "title": "Multi-Embedding Attack and AIS mitigation benchmark",
        "status": "integration_pending",
    },
    {
        "id": "WaveGuard",
        "role": "baseline",
        "title": "Frequency-domain proactive watermark baseline",
        "status": "checkpoint_pending",
    },
    {
        "id": "KAD-Net",
        "role": "baseline",
        "title": "Kolmogorov-Arnold proactive forensics baseline",
        "status": "syntax_smoke_fixed",
    },
]


def _artifact_url(path: Path) -> str:
    return f"/artifacts/{path.relative_to(ASSETS).as_posix()}"


def _load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "read_failed", "path": str(path), "error": str(exc)}


def _read_csv_records(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    import csv

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for idx, row in enumerate(csv.DictReader(handle)):
            if idx >= limit:
                break
            records.append(dict(row))
    return records


def _numeric(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _summarize_hidden_results(path: Path) -> dict[str, Any] | None:
    rows = _read_csv_records(path, limit=1_000_000)
    if not rows:
        return None
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get("attack_type", "unknown"), []).append(row)
    attacks: dict[str, Any] = {}
    for attack, attack_rows in grouped.items():
        def mean(key: str) -> float | None:
            vals = [_numeric(row.get(key)) for row in attack_rows]
            vals = [v for v in vals if v is not None]
            return round(sum(vals) / len(vals), 6) if vals else None

        success_vals = [_numeric(row.get("success")) for row in attack_rows]
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


def _path_status(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "files": count_files(path) if path.is_dir() else int(path.exists()),
    }


def _asset_if_exists(relative: str) -> str | None:
    path = ASSETS / relative
    return f"/artifacts/{relative}" if path.exists() else None


def _benchmark_payload(summary_path: Path, progress_path: Path, results_path: Path, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = _load_json(summary_path)
    progress = _load_json(progress_path)
    if results_path.name == "results.csv" and "hidden_lfw_full_benchmark" in str(results_path):
        partial = _summarize_hidden_results(results_path)
        if partial and progress.get("status") != "complete":
            partial["progress"] = progress
            summary = partial
    payload = {
        "summary": summary,
        "progress": progress,
        "results_csv_path": str(results_path),
        "results_csv_exists": results_path.exists(),
        "sample_results": _read_csv_records(results_path, limit=40),
    }
    if extra:
        payload.update(extra)
    return payload


def _sample_path(sample_id: str) -> Path:
    return DATASETS / f"{sample_id}.png"


def ensure_sample(sample_id: str = "sample_face_001") -> Path:
    path = _sample_path(sample_id)
    if path.exists():
        return path

    size = 512
    img = Image.new("RGB", (size, size), (238, 241, 244))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size, size), fill=(235, 238, 242))
    draw.ellipse((132, 78, 380, 410), fill=(232, 190, 162), outline=(54, 68, 82), width=4)
    draw.ellipse((190, 190, 230, 228), fill=(28, 35, 45))
    draw.ellipse((292, 190, 332, 228), fill=(28, 35, 45))
    draw.arc((214, 222, 318, 330), 20, 160, fill=(121, 62, 64), width=5)
    draw.polygon([(160, 92), (260, 30), (370, 96), (382, 170), (128, 174)], fill=(45, 45, 54))
    draw.rectangle((0, 438, size, size), fill=(38, 78, 102))
    img.save(path)
    return path


def load_rgb(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


def save_rgb(array: np.ndarray, path: Path) -> Path:
    Image.fromarray(np.clip(array, 0, 255).astype(np.uint8)).save(path)
    return path


def simulate_lidmark_embed(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(152)
    pattern = rng.integers(-2, 3, size=image.shape, dtype=np.int16)
    grid = np.zeros_like(image, dtype=np.int16)
    grid[::16, :, 1] = 3
    grid[:, ::16, 2] = -3
    watermarked = np.clip(image.astype(np.int16) + pattern + grid, 0, 255).astype(np.uint8)
    residual = np.clip(np.abs(watermarked.astype(np.int16) - image.astype(np.int16)) * 32, 0, 255).astype(np.uint8)
    return watermarked, residual


def apply_attack(image: np.ndarray, attack: str) -> np.ndarray:
    attacked = image.copy()
    if "multi_embedding" in attack:
        rng = np.random.default_rng(2026)
        attacked = np.clip(attacked.astype(np.int16) + rng.integers(-6, 7, attacked.shape), 0, 255).astype(np.uint8)
    if "jpeg" in attack:
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 50]
        ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(attacked, cv2.COLOR_RGB2BGR), encode_param)
        if ok:
            attacked = cv2.cvtColor(cv2.imdecode(encoded, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    if "blur" in attack:
        attacked = cv2.GaussianBlur(attacked, (5, 5), 0)
    if "resize" in attack:
        h, w = attacked.shape[:2]
        attacked = cv2.resize(attacked, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        attacked = cv2.resize(attacked, (w, h), interpolation=cv2.INTER_LINEAR)
    return attacked


def make_heatmap(reference: np.ndarray, attacked: np.ndarray) -> np.ndarray:
    diff = np.mean(np.abs(reference.astype(np.float32) - attacked.astype(np.float32)), axis=2)
    diff = np.clip(diff / max(float(diff.max()), 1.0) * 255, 0, 255).astype(np.uint8)
    heat = cv2.applyColorMap(diff, cv2.COLORMAP_JET)
    return cv2.cvtColor(heat, cv2.COLOR_BGR2RGB)


def metrics(reference: np.ndarray, candidate: np.ndarray, residual: np.ndarray) -> dict[str, Any]:
    psnr = peak_signal_noise_ratio(reference, candidate, data_range=255)
    ssim = structural_similarity(reference, candidate, channel_axis=2, data_range=255)
    energy = float(np.mean(residual) / 255.0)
    ber = min(1.0, max(0.0, energy * 0.42))
    source_id_acc = max(0.0, 1.0 - ber * 1.8)
    return {
        "psnr": round(float(psnr), 4),
        "ssim": round(float(ssim), 4),
        "ber": round(float(ber), 4),
        "bit_accuracy": round(float(1.0 - ber), 4),
        "source_id_acc": round(float(source_id_acc), 4),
        "landmark_error": round(float(ber * 12.0), 4),
        "attack_success": bool(ber > 0.18 or source_id_acc < 0.75),
    }


def count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "root": str(ROOT),
        "mode": "demo_simulation",
        "timestamp": int(time.time()),
    }


@app.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    return PROJECTS


@app.get("/api/artifacts/status")
def artifacts_status() -> dict[str, Any]:
    groups = {
        "lidmark_smoke_checkpoints": ROOT / "weights/lidmark/smoke_128",
        "lidmark_official_or_small_data": ROOT / "datasets/celeba_hq_small",
        "mea_weights": ROOT / "weights/mea",
        "waveguard_weights": ROOT / "weights/waveguard",
        "kadnet_weights": ROOT / "weights/kadnet",
        "reports": REPORTS,
    }
    status = {
        key: {"path": str(path), "files": count_files(path), "ready": count_files(path) > 0}
        for key, path in groups.items()
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
    return {"groups": status, "manifest": manifest_items}


@app.get("/api/samples")
def samples() -> list[dict[str, str]]:
    path = ensure_sample()
    return [{"id": path.stem, "name": "Demo face sample", "url": f"/api/samples/{path.stem}/image"}]


@app.get("/api/samples/{sample_id}/image")
def sample_image(sample_id: str):
    path = ensure_sample(sample_id)
    return FileResponse(path)


@app.post("/api/tasks/demo-run")
def demo_run(request: DemoRunRequest) -> dict[str, Any]:
    sample_path = ensure_sample(request.sample_id)
    original = load_rgb(sample_path)
    watermarked, residual = simulate_lidmark_embed(original)
    attacked = apply_attack(watermarked, request.attack)
    heatmap = make_heatmap(watermarked, attacked)
    attack_residual = np.clip(np.abs(attacked.astype(np.int16) - watermarked.astype(np.int16)) * 12, 0, 255).astype(np.uint8)

    task_id = uuid.uuid4().hex[:12]
    out_dir = ASSETS / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "original": save_rgb(original, out_dir / "original.png"),
        "watermarked": save_rgb(watermarked, out_dir / "watermarked.png"),
        "attacked": save_rgb(attacked, out_dir / "attacked.png"),
        "heatmap": save_rgb(heatmap, out_dir / "heatmap.png"),
        "residual": save_rgb(residual, out_dir / "residual.png"),
        "attack_residual": save_rgb(attack_residual, out_dir / "attack_residual.png"),
    }

    result = {
        "task_id": task_id,
        "mode": "demo_simulation",
        "project": request.project,
        "sample_id": request.sample_id,
        "attack": request.attack,
        "security_conclusion": "attack_degraded_traceability" if request.attack else "protected",
        "metrics": metrics(watermarked, attacked, attack_residual),
        "artifacts": {key: _artifact_url(value) for key, value in paths.items()},
        "notes": [
            "This is a competition system scaffold using deterministic simulation.",
            "Replace this task with real LIDMark/MEA checkpoints as training artifacts become available.",
        ],
    }
    (REPORTS / f"{task_id}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


@app.get("/api/reports/{task_id}")
def report(task_id: str) -> dict[str, Any]:
    path = REPORTS / f"{task_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="report not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/real-evals")
def real_evals() -> list[dict[str, Any]]:
    reports = []
    for path in sorted((REPORTS / "real_hidden").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            reports.append({
                "task_id": item.get("task_id"),
                "project": item.get("project"),
                "mode": item.get("mode"),
                "checkpoint": item.get("checkpoint"),
                "metrics": item.get("metrics", {}),
                "artifacts": item.get("artifacts", {}),
                "report_path": str(path),
            })
        except Exception:
            continue
    return reports


@app.get("/api/benchmark/hidden-lfw-full")
def hidden_lfw_full() -> dict[str, Any]:
    report_dir = REPORTS / "hidden_lfw_full_benchmark"
    return _benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "MEA/HiDDeN",
            "checkpoint_type": "official_mea_checkpoint",
            "data_type": "real_lfw_images",
            "grid_image": _asset_if_exists("real_hidden_benchmark/grid.png"),
            "asset_dir": str(ASSETS / "real_hidden_benchmark"),
        },
    )


@app.get("/api/benchmark/lidmark-lfw-eval")
def lidmark_lfw_eval() -> dict[str, Any]:
    report_dir = ROOT / "runs" / "lidmark_lfw_eval_full"
    return _benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "LIDMark",
            "checkpoint_type": "smoke_checkpoint",
            "data_type": "real_lfw_images_with_official_watermark_vectors",
            "note": "smoke checkpoint only; not official full model",
        },
    )


@app.get("/api/benchmark/sepmark")
def sepmark_benchmark() -> dict[str, Any]:
    report_dir = REPORTS / "sepmark_lfw_benchmark"
    return _benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "SepMark",
            "checkpoint_type": "official_mea_checkpoint",
            "data_type": "real_lfw_images",
            "grid_image": _asset_if_exists("sepmark_lfw_benchmark/grid.png"),
            "asset_dir": str(ASSETS / "sepmark_lfw_benchmark"),
        },
    )


@app.get("/api/benchmark/waveguard")
def waveguard_benchmark() -> dict[str, Any]:
    report_dir = REPORTS / "waveguard_lfw_benchmark"
    payload = _benchmark_payload(
        report_dir / "summary.json",
        report_dir / "progress.json",
        report_dir / "results.csv",
        {
            "method": "WaveGuard",
            "checkpoint_type": "official_mea_checkpoint_load_or_pending",
            "data_type": "real_lfw_images",
        },
    )
    small_dir = REPORTS / "waveguard_lfw_small_benchmark"
    full_dir = REPORTS / "waveguard_lfw_full_benchmark"
    payload["full_benchmark"] = _benchmark_payload(
        full_dir / "summary.json",
        full_dir / "progress.json",
        full_dir / "results.csv",
        {
            "method": "WaveGuard-full",
            "checkpoint_type": "official_mea_checkpoint",
            "data_type": "real_lfw_images_full",
            "grid_image": _asset_if_exists("waveguard_lfw_full_benchmark/grid.png"),
        },
    )
    payload["small_benchmark"] = _benchmark_payload(
        small_dir / "summary.json",
        small_dir / "progress.json",
        small_dir / "results.csv",
        {
            "method": "WaveGuard-small",
            "checkpoint_type": "official_mea_checkpoint",
            "data_type": "real_lfw_images_small",
            "grid_image": _asset_if_exists("waveguard_lfw_small_benchmark/grid.png"),
        },
    )
    return payload


@app.get("/api/benchmark/aggregate")
def aggregate_benchmark() -> dict[str, Any]:
    report_dir = REPORTS / "aggregate_real_benchmarks"
    return {
        "summary": _load_json(report_dir / "summary.json"),
        "comparison_csv_path": str(report_dir / "method_comparison.csv"),
        "comparison": _read_csv_records(report_dir / "method_comparison.csv", limit=100),
        "report_md_path": str(report_dir / "aggregate_report.md"),
        "degradation_curve": _asset_if_exists("aggregate_real_benchmarks/hidden_attack_degradation.png"),
        "paths": {
            "hidden": _path_status(REPORTS / "hidden_lfw_full_benchmark"),
            "sepmark": _path_status(REPORTS / "sepmark_lfw_benchmark"),
            "lidmark": _path_status(ROOT / "runs" / "lidmark_lfw_eval_full"),
            "waveguard": _path_status(REPORTS / "waveguard_lfw_benchmark"),
        },
    }


@app.get("/api/competition-report")
def competition_report() -> dict[str, Any]:
    report_dir = REPORTS / "jianyuanshield_competition_report"
    return {
        "report": _load_json(report_dir / "report.json"),
        "json_path": str(report_dir / "report.json"),
        "csv_path": str(report_dir / "report.csv"),
        "markdown_path": str(report_dir / "report.md"),
        "exists": {
            "json": (report_dir / "report.json").exists(),
            "csv": (report_dir / "report.csv").exists(),
            "markdown": (report_dir / "report.md").exists(),
        },
    }


@app.get("/api/modules")
def modules() -> list[dict[str, Any]]:
    hidden = _load_json(REPORTS / "hidden_lfw_full_benchmark" / "summary.json")
    sepmark = _load_json(REPORTS / "sepmark_lfw_benchmark" / "summary.json")
    lidmark = _load_json(ROOT / "runs" / "lidmark_lfw_eval_full" / "summary.json")
    waveguard = _load_json(REPORTS / "waveguard_lfw_benchmark" / "summary.json")
    return [
        {
            "name": "内容保护",
            "function": "使用主动水印/主动取证模型生成可验证保护信号。",
            "model_status": "LIDMark smoke checkpoint; HiDDeN official checkpoint available",
            "result": "real" if hidden else "pending",
            "sample": _asset_if_exists("real_hidden_benchmark/grid.png"),
            "metrics": "BER, bit accuracy, PSNR, SSIM",
            "defense_ready": bool(hidden),
        },
        {
            "name": "Deepfake 攻击模拟",
            "function": "对受保护内容执行 JPEG、resize、noise 等传播链路扰动。",
            "model_status": "controlled attacks implemented",
            "result": "real_lfw_benchmark" if hidden else "pending",
            "sample": _asset_if_exists("real_hidden_benchmark/grid.png"),
            "metrics": "attack degradation and success rate",
            "defense_ready": bool(hidden),
        },
        {
            "name": "MEA 多重嵌入攻击",
            "function": "评测多种主动水印 baseline 在攻击下的鲁棒性。",
            "model_status": "HiDDeN and SepMark connected; WaveGuard checkpoint load smoke complete",
            "result": "real" if sepmark or hidden else "pending",
            "sample": _asset_if_exists("sepmark_lfw_benchmark/grid.png") or _asset_if_exists("aggregate_real_benchmarks/hidden_attack_degradation.png"),
            "metrics": "method comparison by attack type",
            "defense_ready": bool(sepmark or hidden),
        },
        {
            "name": "取证恢复",
            "function": "从攻击后图像恢复消息/身份信号并输出取证指标。",
            "model_status": "SepMark decoder_C/decoder_RF and HiDDeN decoder connected; LIDMark smoke eval complete",
            "result": "real" if sepmark or hidden else ("smoke" if lidmark else "pending"),
            "sample": _asset_if_exists("sepmark_lfw_benchmark/grid.png"),
            "metrics": "decoded bit accuracy, LIDMark ID BER, landmark AED",
            "defense_ready": bool(sepmark or hidden),
        },
        {
            "name": "安全评测",
            "function": "统一聚合真实 checkpoint、真实 LFW 数据和攻击退化曲线。",
            "model_status": "aggregate script available",
            "result": "real" if hidden or sepmark or lidmark or waveguard else "pending",
            "sample": _asset_if_exists("aggregate_real_benchmarks/hidden_attack_degradation.png"),
            "metrics": "cross-method comparison",
            "defense_ready": bool(sepmark or hidden),
        },
        {
            "name": "取证报告",
            "function": "导出 JSON、CSV、Markdown 格式的答辩取证报告。",
            "model_status": "report exporter available",
            "result": "ready" if (REPORTS / "jianyuanshield_competition_report" / "report.json").exists() else "pending",
            "sample": None,
            "metrics": "report completeness and evidence paths",
            "defense_ready": (REPORTS / "jianyuanshield_competition_report" / "report.json").exists(),
        },
    ]
