from __future__ import annotations

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


@router.get("/api/modules")
def modules() -> list[dict[str, Any]]:
    return modules_payload()
