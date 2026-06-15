from __future__ import annotations
import re
from pathlib import Path

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .artifacts import artifacts_status_payload
from .benchmarks import (
    PROJECTS,
    aggregate_benchmark_payload,
    competition_report_payload,
    hidden_lfw_full_payload,
    lidmark_lfw_eval_payload,
    modules_payload,
    sepmark_benchmark_payload,
    waveguard_benchmark_payload,
    kadnet_benchmark_payload,
    mea_matrix_payload,
)
from .demo import demo_run_payload, ensure_sample, real_evals_payload, report_payload, samples_payload
from .evidence import evidence_audit_payload
from .config import DATASETS, REPORTS
from .signing import MANIFEST_PATH, PUBLIC_KEY_PATH, SIGNATURE_PATH, verify_evidence_bundle
from .runtime import runtime_health
from .schemas import DemoRunRequest


router = APIRouter()

# 安全：sample_id / task_id 标识符白名单，防路径穿越（仅字母数字、下划线、连字符，长度 1-64）
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_id(value: str, field: str) -> str:
    """校验路径参数标识符，拦截 ../、绝对路径、空字节等穿越载荷。失败抛 400。"""
    if not value or not _SAFE_ID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"非法的 {field}，仅允许字母、数字、下划线和连字符（长度 1-64）")
    return value


@router.get("/api/health")
def health() -> dict[str, Any]:
    return runtime_health()


@router.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    return PROJECTS


@router.get("/api/artifacts/status")
def artifacts_status() -> dict[str, Any]:
    return artifacts_status_payload()


@router.get("/api/samples")
def samples() -> list[dict[str, str]]:
    return samples_payload()


@router.get("/api/samples/{sample_id}/image")
def sample_image(sample_id: str):
    _validate_id(sample_id, "sample_id")
    path = ensure_sample(sample_id).resolve()
    # 安全：确认解析后的路径仍落在样本目录内（双重保险，防穿越）
    if not path.is_relative_to(DATASETS.resolve()):
        raise HTTPException(status_code=400, detail="非法的 sample_id")
    return FileResponse(path)


@router.post("/api/tasks/demo-run")
def demo_run(request: DemoRunRequest) -> dict[str, Any]:
    _validate_id(request.sample_id, "sample_id")
    return demo_run_payload(request)


@router.get("/api/reports/{task_id}")
def report(task_id: str) -> dict[str, Any]:
    _validate_id(task_id, "task_id")
    payload = report_payload(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="report not found")
    return payload


@router.get("/api/real-evals")
def real_evals() -> list[dict[str, Any]]:
    return real_evals_payload()


@router.get("/api/benchmark/hidden-lfw-full")
def hidden_lfw_full() -> dict[str, Any]:
    return hidden_lfw_full_payload()


@router.get("/api/benchmark/lidmark-lfw-eval")
def lidmark_lfw_eval() -> dict[str, Any]:
    return lidmark_lfw_eval_payload()


@router.get("/api/benchmark/sepmark")
def sepmark_benchmark() -> dict[str, Any]:
    return sepmark_benchmark_payload()


@router.get("/api/benchmark/waveguard")
def waveguard_benchmark() -> dict[str, Any]:
    return waveguard_benchmark_payload()


@router.get("/api/benchmark/mea-matrix")
def mea_matrix_benchmark() -> dict[str, Any]:
    return mea_matrix_payload()


@router.get("/api/benchmark/kadnet")
def kadnet_benchmark() -> dict[str, Any]:
    return kadnet_benchmark_payload()


@router.get("/api/benchmark/aggregate")
def aggregate_benchmark() -> dict[str, Any]:
    return aggregate_benchmark_payload()


@router.get("/api/competition-report")
def competition_report() -> dict[str, Any]:
    return competition_report_payload()


@router.get("/api/evidence/audit")
def evidence_audit() -> dict[str, Any]:
    return evidence_audit_payload()


@router.get("/api/evidence/signature")
def evidence_signature() -> dict[str, Any]:
    return verify_evidence_bundle()


@router.get("/api/evidence/signature/download/{file_name}")
def evidence_signature_download(file_name: str):
    files = {
        "manifest": (MANIFEST_PATH, "manifest.json", "application/json"),
        "signature": (SIGNATURE_PATH, "manifest.sig", "application/octet-stream"),
        "public-key": (PUBLIC_KEY_PATH, "public_key.pem", "application/x-pem-file"),
    }
    if file_name not in files:
        raise HTTPException(status_code=404, detail="signature file not found")
    path, download_name, media_type = files[file_name]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="signature file not generated")
    return FileResponse(path, filename=download_name, media_type=media_type)


@router.get("/api/competition-report/download/{format_name}")
def competition_report_download(format_name: str):
    names = {
        "json": ("report.json", "application/json"),
        "csv": ("report.csv", "text/csv"),
        "markdown": ("report.md", "text/markdown"),
    }
    if format_name not in names:
        raise HTTPException(status_code=404, detail="report format not found")
    filename, media_type = names[format_name]
    path = REPORTS / "jianyuanshield_competition_report" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="report file not found")
    return FileResponse(path, filename=filename, media_type=media_type)


@router.get("/api/modules")
def modules() -> list[dict[str, Any]]:
    return modules_payload()


# ── new inference & compliance endpoints ──────────────────────────────────────

from fastapi import UploadFile, File, Form, Request
from .infer import MAX_BATCH_FILES, MAX_UPLOAD_BYTES, run_single_infer, run_compliance_batch


def _guard_content_length(request: Request, limit: int) -> None:
    """安全：根据 Content-Length 头在读取请求体前先拒绝超大上传，降低内存 DoS 面。"""
    raw = request.headers.get("content-length")
    if raw is None:
        return
    try:
        declared = int(raw)
    except (TypeError, ValueError):
        return
    if declared > limit:
        raise HTTPException(
            status_code=413,
            detail=f"请求体超过上限（{limit // (1024 * 1024)} MB），请减小上传体积",
        )


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    """安全：流式读取并在超过上限时立即中断，避免恶意 Content-Length 绕过。"""
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"图片体积超过上限（{limit // (1024 * 1024)} MB），请压缩后重试",
        )
    return data


@router.post('/api/infer/single')
async def infer_single(
    request: Request,
    file: UploadFile = File(...),
    model: str = Form('SepMark'),
    attack: str = Form('clean'),
    return_b64: bool = Form(True),
) -> dict[str, Any]:
    # 单张上传：体积上限 = MAX_UPLOAD_BYTES（含表单开销留余量，按声明长度预拒绝）
    _guard_content_length(request, MAX_UPLOAD_BYTES + 1024 * 1024)
    data = await _read_capped(file, MAX_UPLOAD_BYTES)
    return run_single_infer(data, model=model, attack=attack, return_b64=return_b64)


@router.post('/api/compliance/batch')
async def compliance_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    model: str = Form('SepMark'),
) -> dict[str, Any]:
    # 批量上传：张数上限 + 总体积上限（单张 5MB × 张数上限）+ 逐张体积上限
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"单次批量检测最多 {MAX_BATCH_FILES} 张图片，请分批提交",
        )
    _guard_content_length(request, MAX_UPLOAD_BYTES * MAX_BATCH_FILES + 1024 * 1024)
    images = [(f.filename or f'image_{i}', await _read_capped(f, MAX_UPLOAD_BYTES))
              for i, f in enumerate(files)]
    return run_compliance_batch(images, model=model)


@router.get('/api/models/status')
def models_status() -> dict[str, Any]:
    from .model_adapters import SepMarkAdapter, WaveGuardAdapter, LIDMarkAdapter, KADNetAdapter
    return {
        'SepMark':   {'available': SepMarkAdapter.available(),  'loaded': SepMarkAdapter._instance is not None},
        'WaveGuard': {'available': WaveGuardAdapter.available(), 'loaded': WaveGuardAdapter._instance is not None},
        'LIDMark':   {'available': LIDMarkAdapter.available(), 'loaded': LIDMarkAdapter._instance is not None},
        'KAD-Net':   {'available': KADNetAdapter.available(), 'loaded': KADNetAdapter._instance is not None},
    }