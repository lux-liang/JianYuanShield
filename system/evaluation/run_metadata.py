from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import torch

from .protocol import load_protocol
from .runtime import PROJECT_ROOT


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


def build_run_metadata(
    *,
    model: str,
    checkpoint: Path | None,
    seed: int,
    command: list[str] | None = None,
) -> dict[str, Any]:
    protocol = load_protocol()
    deployed_commit = PROJECT_ROOT / ".deployed_commit"
    return {
        "schema_version": "run-metadata.v1",
        "generated_at": int(time.time()),
        "model": model,
        "seed": seed,
        "command": command or sys.argv,
        "project_root": str(PROJECT_ROOT),
        "git_commit": _git(["rev-parse", "HEAD"]),
        "deployed_commit": deployed_commit.read_text(encoding="utf-8").strip() if deployed_commit.is_file() else None,
        "evaluation_protocol": protocol["schema_version"],
        "protocol_path": protocol["_source_path"],
        "protocol_sha256": sha256_file(Path(protocol["_source_path"])),
        "checkpoint": str(checkpoint) if checkpoint else None,
        "checkpoint_sha256": sha256_file(checkpoint) if checkpoint else None,
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"),
        "gpu_names": [
            torch.cuda.get_device_name(index)
            for index in range(torch.cuda.device_count())
        ] if torch.cuda.is_available() else [],
    }
