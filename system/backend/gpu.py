from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import os
import socket
import subprocess
import threading
import time
from typing import Any


_QUERY_FIELDS = (
    "index",
    "uuid",
    "name",
    "memory.total",
    "memory.used",
    "memory.free",
    "utilization.gpu",
    "temperature.gpu",
    "power.draw",
    "power.limit",
)
_CACHE_TTL_SECONDS = 1.0
_cache_lock = threading.Lock()
_cached_at = 0.0
_cached_devices: list[dict[str, Any]] | None = None


class GpuStatusError(RuntimeError):
    """Raised when the NVIDIA runtime cannot provide a trustworthy sample."""


def _number(
    value: str,
    *,
    integer: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float | None:
    normalized = value.strip()
    if not normalized or normalized.lower() in {"n/a", "[n/a]", "not supported"}:
        return None
    try:
        parsed = float(normalized)
    except ValueError as exc:
        raise GpuStatusError(f"invalid nvidia-smi value: {normalized}") from exc
    if not math.isfinite(parsed):
        raise GpuStatusError("nvidia-smi returned a non-finite value")
    if integer and not parsed.is_integer():
        raise GpuStatusError("nvidia-smi returned a fractional integer field")
    if minimum is not None and parsed < minimum:
        raise GpuStatusError("nvidia-smi value is below the accepted range")
    if maximum is not None and parsed > maximum:
        raise GpuStatusError("nvidia-smi value is above the accepted range")
    return int(parsed) if integer else round(parsed, 2)


def _parse_devices(output: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        values = [value.strip() for value in line.split(",")]
        if len(values) != len(_QUERY_FIELDS):
            raise GpuStatusError("unexpected nvidia-smi response shape")
        (
            index,
            uuid,
            name,
            memory_total,
            memory_used,
            memory_free,
            utilization,
            temperature,
            power_draw,
            power_limit,
        ) = values
        device_index = _number(index, integer=True, minimum=0)
        total_mib = _number(memory_total, integer=True, minimum=1)
        used_mib = _number(memory_used, integer=True, minimum=0)
        free_mib = _number(memory_free, integer=True, minimum=0)
        if total_mib is None or used_mib is None or free_mib is None:
            raise GpuStatusError("nvidia-smi did not report GPU memory")
        if (
            used_mib > total_mib
            or free_mib > total_mib
            or abs((used_mib + free_mib) - total_mib) > max(2, total_mib * 0.01)
        ):
            raise GpuStatusError("nvidia-smi reported inconsistent GPU memory")
        if (
            device_index is None
            or not uuid.startswith("GPU-")
            or not name
            or len(uuid) > 128
            or len(name) > 128
            or any(ord(character) < 32 for character in uuid + name)
        ):
            raise GpuStatusError("nvidia-smi reported an invalid GPU identity")
        devices.append(
            {
                "index": device_index,
                "uuid": uuid,
                "name": name,
                "memory": {
                    "total_mib": total_mib,
                    "used_mib": used_mib,
                    "free_mib": free_mib,
                    "used_percent": round((used_mib / total_mib) * 100, 1),
                },
                "utilization_percent": _number(
                    utilization,
                    integer=True,
                    minimum=0,
                    maximum=100,
                ),
                "temperature_c": _number(
                    temperature,
                    integer=True,
                    minimum=-100,
                    maximum=200,
                ),
                "power": {
                    "draw_w": _number(power_draw, minimum=0),
                    "limit_w": _number(power_limit, minimum=0),
                },
            }
        )
    if not devices:
        raise GpuStatusError("nvidia-smi returned no GPU devices")
    return devices


def _sample_devices() -> list[dict[str, Any]]:
    global _cached_at, _cached_devices

    now = time.monotonic()
    with _cache_lock:
        if _cached_devices is not None and now - _cached_at < _CACHE_TTL_SECONDS:
            return deepcopy(_cached_devices)
        try:
            completed = subprocess.run(
                [
                    "nvidia-smi",
                    f"--query-gpu={','.join(_QUERY_FIELDS)}",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GpuStatusError("NVIDIA runtime status is unavailable") from exc
        devices = _parse_devices(completed.stdout)
        _cached_devices = deepcopy(devices)
        _cached_at = time.monotonic()
        return deepcopy(devices)


def _selected_device(devices: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    visible = os.getenv("CUDA_VISIBLE_DEVICES", "").strip()
    selector = visible.split(",", 1)[0].strip() if visible else ""
    if selector:
        for device in devices:
            if selector.isdigit() and device["index"] == int(selector):
                return device, selector
            uuid = str(device["uuid"])
            if selector == uuid or uuid.startswith(selector):
                return device, selector
        raise GpuStatusError("configured CUDA device was not reported by nvidia-smi")
    return devices[0], str(devices[0]["index"])


def gpu_status_payload(*, inference: dict[str, Any]) -> dict[str, Any]:
    devices = _sample_devices()
    device, selector = _selected_device(devices)
    return {
        "schema_version": "h100-runtime-status.v1",
        "ok": True,
        "state": "online",
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "node": socket.gethostname(),
        "device_mapping": {
            "cuda_visible_devices": selector,
            "runtime_device": "cuda:0",
            "physical_index": device["index"],
        },
        "gpu": device,
        "inference": inference,
    }


def public_gpu_status_payload(*, inference: dict[str, Any]) -> dict[str, Any]:
    """Return UI telemetry without host, UUID or device-selection details."""

    payload = gpu_status_payload(inference=inference)
    device = payload["gpu"]
    return {
        "schema_version": payload["schema_version"],
        "ok": payload["ok"],
        "state": payload["state"],
        "sampled_at": payload["sampled_at"],
        "gpu": {
            "name": device["name"],
            "memory": device["memory"],
            "utilization_percent": device["utilization_percent"],
            "temperature_c": device["temperature_c"],
            "power": device["power"],
        },
        "inference": payload["inference"],
    }
