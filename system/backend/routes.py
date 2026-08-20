from __future__ import annotations
import asyncio
from functools import partial
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

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
    simswap_lfw_payload,
)
from .demo import demo_run_payload, ensure_sample, real_evals_payload, report_payload, samples_payload
from .evidence import evidence_audit_payload
from .config import ASSETS, REPORTS
from .infer import (
    InferenceCapabilityError,
    expire_inference_task,
    is_inference_task_expired,
    run_compliance_batch,
    run_single_infer,
)
from .signing import (
    CORE_MANIFEST_PATH,
    CORE_PUBLIC_KEY_PATH,
    CORE_SIGNATURE_PATH,
    MANIFEST_PATH,
    PUBLIC_KEY_PATH,
    SIGNATURE_PATH,
    verify_evidence_bundle,
)
from .runtime import runtime_health
from .schemas import (
    CollaborationRecommendationRequest,
    CollaborationRecommendationResponse,
    DemoRunRequest,
)
from .security import (
    read_validated_upload,
    require_api_key,
    resolve_path_within,
    safe_display_filename,
    validate_identifier,
)
from .settings import settings
from .logging_config import logger
from .claims import claims_payload
from .collaboration import CollaborationPolicyError, recommend_collaboration
from .provenance import (
    ProvenanceCapabilityError,
    build_source_credential,
    create_creator_challenge,
    create_revocation_intent,
    get_provenance_record,
    provenance_audit_status,
    provenance_model_status,
    protect_content,
    revoke_content,
    verify_content,
)
from .aigc_labeling import inspect_aigc_png
from system.evaluation.attacks import ATTACKS as EVALUATION_ATTACKS


router = APIRouter()
_inference_slots = asyncio.Semaphore(settings.max_concurrent_inference)
_inference_capacity = asyncio.Semaphore(
    settings.max_concurrent_inference + settings.max_queued_inference
)


def _release_worker_resources(
    worker: asyncio.Task,
    *,
    slots: asyncio.Semaphore,
    capacity: asyncio.Semaphore,
) -> None:
    try:
        error = worker.exception()
    except asyncio.CancelledError:
        error = None
    if error is not None:
        logger.warning(
            "inference worker completed after response timeout error=%s",
            error.__class__.__name__,
        )
    slots.release()
    capacity.release()


async def _run_inference(callable_, /, *args, **kwargs):
    # A cancelled thread-pool await does not stop the underlying GPU call. Keep
    # the slot reserved until that worker really exits so a timeout cannot turn
    # into concurrent, unbounded CUDA work.
    slots = _inference_slots
    capacity = _inference_capacity
    if capacity.locked():
        raise HTTPException(
            status_code=503,
            detail="inference queue is full",
            headers={"Retry-After": "1"},
        )
    await capacity.acquire()
    timeout = float(settings.inference_timeout_seconds)
    deadline = asyncio.get_running_loop().time() + timeout
    slot_acquired = False
    release_when_done = False
    worker: asyncio.Task | None = None
    try:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        await asyncio.wait_for(slots.acquire(), timeout=remaining)
        slot_acquired = True

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        worker = asyncio.create_task(run_in_threadpool(partial(callable_, *args, **kwargs)))
        return await asyncio.wait_for(
            asyncio.shield(worker),
            timeout=remaining,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if worker is not None:
            worker.add_done_callback(
                partial(
                    _release_worker_resources,
                    slots=slots,
                    capacity=capacity,
                )
            )
            release_when_done = True
        raise
    finally:
        if not release_when_done:
            if slot_acquired:
                slots.release()
            capacity.release()


def health() -> dict[str, Any] | JSONResponse:
    payload = runtime_health(detailed=settings.mode != "production")
    if payload.get("ok") is not True:
        return JSONResponse(status_code=503, content=payload)
    return payload


@router.get("/api/health", response_model=None)
async def health_endpoint() -> dict[str, Any] | JSONResponse:
    """Keep liveness independent from the worker pool used by evidence audits."""

    return health()


@router.get("/api/health/details", dependencies=[Depends(require_api_key)])
def health_details() -> dict[str, Any]:
    return runtime_health(detailed=True)


def projects() -> list[dict[str, Any]]:
    return PROJECTS


@router.get("/api/projects")
async def projects_endpoint() -> list[dict[str, Any]]:
    return projects()


@router.get("/api/artifacts/status", dependencies=[Depends(require_api_key)])
def artifacts_status() -> dict[str, Any]:
    return artifacts_status_payload()


@router.get("/api/artifacts/{artifact_path:path}", dependencies=[Depends(require_api_key)])
def artifact_file(artifact_path: str):
    task_id = artifact_path.split("/", 1)[0]
    if is_inference_task_expired(task_id):
        expire_inference_task(task_id)
        raise HTTPException(status_code=404, detail="artifact not found")
    candidate = resolve_path_within(ASSETS, artifact_path)
    if candidate is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    if not candidate.is_file() or candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(
        candidate,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/samples", dependencies=[Depends(require_api_key)])
def samples() -> list[dict[str, str]]:
    if not settings.enable_demo:
        return []
    return samples_payload()


@router.get("/api/samples/{sample_id}/image", dependencies=[Depends(require_api_key)])
def sample_image(sample_id: str):
    if not settings.enable_demo:
        raise HTTPException(status_code=404, detail="demo samples are disabled")
    validate_identifier(sample_id, field="sample_id")
    return FileResponse(
        ensure_sample(sample_id),
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/api/tasks/demo-run", dependencies=[Depends(require_api_key)])
async def demo_run(request: DemoRunRequest) -> dict[str, Any]:
    if not settings.enable_demo:
        raise HTTPException(status_code=404, detail="demo endpoint is disabled")
    try:
        return await _run_inference(demo_run_payload, request)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="demo inference timed out") from exc


@router.get("/api/reports/{task_id}", dependencies=[Depends(require_api_key)])
def report(task_id: str) -> dict[str, Any]:
    validate_identifier(task_id, field="task_id")
    if is_inference_task_expired(task_id):
        expire_inference_task(task_id)
        raise HTTPException(status_code=404, detail="report not found")
    payload = report_payload(task_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="report not found")
    return payload


@router.get("/api/real-evals", dependencies=[Depends(require_api_key)])
def real_evals() -> list[dict[str, Any]]:
    return real_evals_payload()


@router.get("/api/benchmark/hidden-lfw-full", dependencies=[Depends(require_api_key)])
def hidden_lfw_full() -> dict[str, Any]:
    return hidden_lfw_full_payload()


@router.get("/api/benchmark/lidmark-lfw-eval", dependencies=[Depends(require_api_key)])
def lidmark_lfw_eval() -> dict[str, Any]:
    return lidmark_lfw_eval_payload()


@router.get("/api/benchmark/lidmark", dependencies=[Depends(require_api_key)])
def lidmark_benchmark() -> dict[str, Any]:
    return lidmark_lfw_eval_payload()


@router.get("/api/benchmark/sepmark", dependencies=[Depends(require_api_key)])
def sepmark_benchmark() -> dict[str, Any]:
    return sepmark_benchmark_payload()


@router.get("/api/benchmark/waveguard", dependencies=[Depends(require_api_key)])
def waveguard_benchmark() -> dict[str, Any]:
    return waveguard_benchmark_payload()


@router.get("/api/benchmark/mea-matrix", dependencies=[Depends(require_api_key)])
def mea_matrix_benchmark() -> dict[str, Any]:
    return mea_matrix_payload()


@router.get("/api/benchmark/simswap-lfw", dependencies=[Depends(require_api_key)])
def simswap_lfw_benchmark() -> dict[str, Any]:
    return simswap_lfw_payload()


@router.post(
    "/api/collaboration/recommend",
    dependencies=[Depends(require_api_key)],
    response_model=CollaborationRecommendationResponse,
)
def collaboration_recommend(
    request: CollaborationRecommendationRequest,
) -> dict[str, Any]:
    try:
        return recommend_collaboration(
            request.model_dump(mode="python", exclude_none=True)
        )
    except CollaborationPolicyError as exc:
        raise HTTPException(
            status_code=503,
            detail="collaboration policy evidence verification failed",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/benchmark/kadnet", dependencies=[Depends(require_api_key)])
def kadnet_benchmark() -> dict[str, Any]:
    return kadnet_benchmark_payload()


@router.get("/api/benchmark/aggregate", dependencies=[Depends(require_api_key)])
def aggregate_benchmark() -> dict[str, Any]:
    return aggregate_benchmark_payload()


@router.get("/api/competition-report", dependencies=[Depends(require_api_key)])
def competition_report() -> dict[str, Any]:
    return competition_report_payload()


@router.get("/api/evidence/audit", dependencies=[Depends(require_api_key)])
def evidence_audit() -> dict[str, Any]:
    return evidence_audit_payload()


@router.get("/api/claims")
def claims() -> dict[str, Any]:
    return claims_payload()


@router.get("/api/evidence/signature", dependencies=[Depends(require_api_key)])
def evidence_signature() -> dict[str, Any]:
    return verify_evidence_bundle()


@router.get("/api/evidence/signature/download/{file_name}", dependencies=[Depends(require_api_key)])
def evidence_signature_download(file_name: str):
    files = {
        "manifest": (MANIFEST_PATH, "manifest.json", "application/json"),
        "signature": (SIGNATURE_PATH, "manifest.sig", "application/octet-stream"),
        "public-key": (PUBLIC_KEY_PATH, "public_key.pem", "application/x-pem-file"),
        "core-manifest": (CORE_MANIFEST_PATH, "release-core-manifest.json", "application/json"),
        "core-signature": (CORE_SIGNATURE_PATH, "release-core-manifest.sig", "application/octet-stream"),
        "core-public-key": (CORE_PUBLIC_KEY_PATH, "release-core-public_key.pem", "application/x-pem-file"),
    }
    if file_name not in files:
        raise HTTPException(status_code=404, detail="signature file not found")
    path, download_name, media_type = files[file_name]
    try:
        path.resolve().relative_to(REPORTS.resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="signature file not found") from exc
    if path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="signature file not generated")
    return FileResponse(
        path,
        filename=download_name,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/competition-report/download/{format_name}", dependencies=[Depends(require_api_key)])
def competition_report_download(format_name: str):
    names = {
        "json": ("report.json", "application/json"),
        "csv": ("report.csv", "text/csv"),
        "markdown": ("report.md", "text/markdown"),
    }
    if format_name not in names:
        raise HTTPException(status_code=404, detail="report format not found")
    filename, media_type = names[format_name]
    path = resolve_path_within(
        REPORTS,
        f"jianyuanshield_competition_report/{filename}",
    )
    if path is None or path.is_symlink() or not path.is_file():
        raise HTTPException(status_code=404, detail="report file not found")
    return FileResponse(
        path,
        filename=filename,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/modules", dependencies=[Depends(require_api_key)])
def modules() -> list[dict[str, Any]]:
    return modules_payload()


# ── new inference & compliance endpoints ──────────────────────────────────────


SUPPORTED_MODELS = frozenset({"SepMark", "WaveGuard", "LIDMark", "KAD-Net"})
LEGACY_ATTACK_ALIASES = {
    "resize": "resize_0.5x",
    "noise": "gaussian_noise_sigma_3",
    "blur": "gaussian_blur_5",
}
SUPPORTED_ATTACKS = frozenset(EVALUATION_ATTACKS) | frozenset(LEGACY_ATTACK_ALIASES)


def _validate_model(model: str) -> str:
    if model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=422, detail="unsupported model")
    return model


def _validate_attack(attack: str) -> str:
    if attack not in SUPPORTED_ATTACKS:
        raise HTTPException(status_code=422, detail="unsupported attack")
    return attack


@router.post('/api/infer/single', dependencies=[Depends(require_api_key)])
async def infer_single(
    file: UploadFile = File(...),
    model: str = Form('SepMark'),
    attack: str = Form('clean'),
    return_b64: bool = Form(False),
) -> dict[str, Any]:
    _validate_model(model)
    _validate_attack(attack)
    data = await read_validated_upload(file)
    try:
        return await _run_inference(
            run_single_infer,
            data,
            model=model,
            attack=attack,
            return_b64=return_b64,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="inference timed out") from exc
    except InferenceCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post('/api/compliance/batch', dependencies=[Depends(require_api_key)])
async def compliance_batch(
    files: list[UploadFile] = File(...),
    model: str = Form('SepMark'),
) -> dict[str, Any]:
    _validate_model(model)
    if not files:
        raise HTTPException(status_code=422, detail="batch must contain at least one image")
    if len(files) > settings.max_batch_files:
        raise HTTPException(
            status_code=413,
            detail=f"batch exceeds {settings.max_batch_files} file limit",
        )
    images = [
        (
            safe_display_filename(upload.filename, fallback=f"image_{index}"),
            await read_validated_upload(upload),
        )
        for index, upload in enumerate(files)
    ]
    return run_compliance_batch(images, model=model)


@router.post('/api/provenance/protect', dependencies=[Depends(require_api_key)])
async def provenance_protect(
    file: UploadFile = File(...),
    creator_ref: str = Form(..., min_length=1, max_length=128),
    model: str = Form('KAD-Net'),
    challenge_id: str | None = Form(None, pattern=r'^[a-f0-9]{32}$'),
    creator_signature_base64: str | None = Form(None, max_length=256),
    aigc_label: str | None = Form(None, pattern=r'^[123]$'),
) -> dict[str, Any]:
    _validate_model(model)
    data = await read_validated_upload(file)
    try:
        return await _run_inference(
            protect_content,
            data,
            creator_ref=creator_ref,
            model=model,
            challenge_id=challenge_id,
            creator_signature_base64=creator_signature_base64,
            aigc_label=aigc_label,
        )
    except ProvenanceCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="protection timed out") from exc


@router.post('/api/creator/challenges', dependencies=[Depends(require_api_key)])
def creator_challenge(
    creator_public_key_pem: str = Form(..., min_length=1, max_length=2048),
    creator_ref: str = Form(..., min_length=1, max_length=128),
    model: str = Form('KAD-Net'),
    image_sha256: str = Form(..., pattern=r'^[a-f0-9]{64}$'),
) -> dict[str, Any]:
    _validate_model(model)
    try:
        return create_creator_challenge(
            creator_public_key_pem=creator_public_key_pem,
            creator_ref=creator_ref,
            model=model,
            image_sha256=image_sha256,
        )
    except (ProvenanceCapabilityError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post('/api/provenance/verify', dependencies=[Depends(require_api_key)])
async def provenance_verify(
    file: UploadFile = File(...),
    content_id: str | None = Form(None, pattern=r'^[a-f0-9]{32}$'),
    source_credential: UploadFile | None = File(None),
) -> dict[str, Any]:
    data = await read_validated_upload(file)
    credential_bytes = None
    if source_credential is not None:
        credential_bytes = await source_credential.read(256 * 1024 + 1)
        if len(credential_bytes) > 256 * 1024:
            raise HTTPException(status_code=413, detail="source credential exceeds 256 KiB")
    try:
        return await _run_inference(
            verify_content,
            data,
            content_id=content_id,
            source_credential_bytes=credential_bytes,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="provenance record not found") from exc
    except ProvenanceCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="verification timed out") from exc


@router.post('/api/compliance/aigc/inspect', dependencies=[Depends(require_api_key)])
async def aigc_inspect(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await read_validated_upload(file)
    return inspect_aigc_png(data)


@router.get('/api/provenance/audit', dependencies=[Depends(require_api_key)])
def provenance_audit() -> dict[str, Any]:
    return provenance_audit_status()


@router.post(
    '/api/provenance/records/{content_id}/revocation-intents',
    dependencies=[Depends(require_api_key)],
)
def provenance_revocation_intent(
    content_id: str,
    reason_code: str = Form(...),
) -> dict[str, Any]:
    if len(content_id) != 32 or any(char not in '0123456789abcdef' for char in content_id):
        raise HTTPException(status_code=422, detail="invalid content_id")
    try:
        return create_revocation_intent(content_id, reason_code=reason_code)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="provenance record not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProvenanceCapabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    '/api/provenance/records/{content_id}/revoke',
    dependencies=[Depends(require_api_key)],
)
def provenance_revoke(
    content_id: str,
    intent_id: str = Form(..., pattern=r'^[a-f0-9]{32}$'),
    creator_signature_base64: str = Form(..., min_length=1, max_length=256),
) -> dict[str, Any]:
    if len(content_id) != 32 or any(char not in '0123456789abcdef' for char in content_id):
        raise HTTPException(status_code=422, detail="invalid content_id")
    try:
        return revoke_content(
            content_id,
            intent_id=intent_id,
            creator_signature_base64=creator_signature_base64,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="provenance record not found") from exc
    except ProvenanceCapabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    '/api/provenance/credentials/{content_id}',
    dependencies=[Depends(require_api_key)],
)
def provenance_credential(content_id: str):
    if len(content_id) != 32 or any(char not in '0123456789abcdef' for char in content_id):
        raise HTTPException(status_code=422, detail="invalid content_id")
    try:
        credential = build_source_credential(content_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="provenance record not found") from exc
    except ProvenanceCapabilityError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse(
        credential,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{content_id}.jys-credential.json"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get('/api/provenance/records/{content_id}', dependencies=[Depends(require_api_key)])
def provenance_record(content_id: str) -> dict[str, Any]:
    if len(content_id) != 32 or any(char not in '0123456789abcdef' for char in content_id):
        raise HTTPException(status_code=422, detail="invalid content_id")
    payload = get_provenance_record(content_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="provenance record not found")
    return payload


@router.get('/api/models/status', dependencies=[Depends(require_api_key)])
def models_status() -> dict[str, Any]:
    from .model_adapters import (
        KADNET_CKPT,
        KADNET_CKPT_SHA256,
        KADNetAdapter,
        LIDMARK_CKPT,
        LIDMARK_CKPT_SHA256,
        LIDMarkAdapter,
        SEPMARK_CKPT,
        SEPMARK_CKPT_SHA256,
        SepMarkAdapter,
        WAVEGUARD_CKPT,
        WAVEGUARD_CKPT_SHA256,
        WaveGuardAdapter,
    )

    descriptors = (
        ('LIDMark', LIDMarkAdapter, LIDMARK_CKPT, LIDMARK_CKPT_SHA256),
        ('KAD-Net', KADNetAdapter, KADNET_CKPT, KADNET_CKPT_SHA256),
        ('SepMark', SepMarkAdapter, SEPMARK_CKPT, SEPMARK_CKPT_SHA256),
        ('WaveGuard', WaveGuardAdapter, WAVEGUARD_CKPT, WAVEGUARD_CKPT_SHA256),
    )
    statuses = {
        model: provenance_model_status(
            model,
            checkpoint,
            checkpoint_sha256,
            available=adapter.available(),
            loaded=adapter._instance is not None,
        )
        for model, adapter, checkpoint, checkpoint_sha256 in descriptors
    }
    preferred_model = next(
        (model for model, *_ in descriptors if statuses[model]['provenance_ready']),
        None,
    )
    return {
        'schema_version': 'model-provenance-status.v1',
        'preferred_model': preferred_model,
        **statuses,
    }
