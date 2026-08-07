from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .protocol import load_protocol
from .runtime import PROJECT_ROOT, logical_path


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(args: list[str]) -> str | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return None


def sanitize_command(command: list[str]) -> list[str]:
    """Redact credential arguments and collapse absolute paths to logical paths."""
    sanitized: list[str] = []
    redact_next = False
    sensitive = ("token", "password", "secret", "api-key", "api_key")
    for raw in command:
        value = str(raw)
        if redact_next:
            sanitized.append("<redacted>")
            redact_next = False
            continue
        lowered = value.lower()
        contains_sensitive_name = any(marker in lowered for marker in sensitive)
        if contains_sensitive_name and "=" in value:
            sanitized.append(value.split("=", 1)[0] + "=<redacted>")
            continue
        if value.startswith("-") and contains_sensitive_name:
            sanitized.append(value)
            redact_next = True
            continue
        if "=" in value:
            name, raw_candidate = value.split("=", 1)
            candidate = Path(raw_candidate).expanduser()
            if candidate.is_absolute():
                sanitized.append(f"{name}={logical_path(candidate)}")
                continue
        candidate = Path(value).expanduser()
        sanitized.append(logical_path(candidate) if candidate.is_absolute() else value)
    return sanitized


def _torch_environment() -> dict[str, Any]:
    """Collect accelerator metadata without making hashing utilities depend on torch."""
    try:
        import torch
    except ModuleNotFoundError:
        return {
            "torch": None,
            "cuda_available": False,
            "cuda_version": None,
            "gpu_names": [],
        }
    cuda_available = bool(torch.cuda.is_available())
    return {
        "torch": torch.__version__,
        "cuda_available": cuda_available,
        "cuda_version": torch.version.cuda,
        "gpu_names": [
            torch.cuda.get_device_name(index)
            for index in range(torch.cuda.device_count())
        ] if cuda_available else [],
    }


def build_run_metadata(
    *,
    model: str,
    checkpoint: Path | None,
    seed: int,
    command: list[str] | None = None,
) -> dict[str, Any]:
    protocol = load_protocol()
    deployed_commit = PROJECT_ROOT / ".deployed_commit"
    metadata = {
        "schema_version": "run-metadata.v1",
        "generated_at": int(time.time()),
        "model": model,
        "seed": seed,
        "command": sanitize_command(command or sys.argv),
        "project_root": ".",
        "git_commit": _git(["rev-parse", "HEAD"]),
        "deployed_commit": deployed_commit.read_text(encoding="utf-8").strip() if deployed_commit.is_file() else None,
        "evaluation_protocol": protocol["schema_version"],
        "protocol_path": logical_path(protocol["_source_path"]),
        "protocol_sha256": sha256_file(Path(protocol["_source_path"])),
        "checkpoint": logical_path(checkpoint) if checkpoint else None,
        "checkpoint_sha256": sha256_file(checkpoint) if checkpoint else None,
        "python": sys.version,
        "python_executable": Path(sys.executable).name,
        "platform": platform.platform(),
        "visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"),
    }
    metadata.update(_torch_environment())
    return metadata
