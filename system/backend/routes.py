from __future__ import annotations
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
)
from .demo import demo_run_payload, ensure_sample, real_evals_payload, report_payload, samples_payload
from .evidence import evidence_audit_payload
from .config import REPORTS
from .signing import MANIFEST_PATH, PUBLIC_KEY_PATH, SIGNATURE_PATH, verify_evidence_bundle
from .runtime import runtime_health
from .schemas import DemoRunRequest


router = APIRouter()


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
    return FileResponse(ensure_sample(sample_id))


@router.post("/api/tasks/demo-run")
def demo_run(request: DemoRunRequest) -> dict[str, Any]:
    return demo_run_payload(request)


@router.get("/api/reports/{task_id}")
def report(task_id: str) -> dict[str, Any]:
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

from fastapi import UploadFile, File, Form
from .infer import run_single_infer, run_compliance_batch


@router.post('/api/infer/single')
async def infer_single(
    file: UploadFile = File(...),
    model: str = Form('SepMark'),
    attack: str = Form('clean'),
    return_b64: bool = Form(True),
) -> dict[str, Any]:
    data = await file.read()
    return run_single_infer(data, model=model, attack=attack, return_b64=return_b64)


@router.post('/api/compliance/batch')
async def compliance_batch(
    files: list[UploadFile] = File(...),
    model: str = Form('SepMark'),
) -> dict[str, Any]:
    images = [(f.filename or f'image_{i}', await f.read())
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