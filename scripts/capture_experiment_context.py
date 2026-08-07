#!/usr/bin/env python3
"""Freeze source, checkpoint and environment identities for a benchmark run."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))

from system.evaluation.run_metadata import sanitize_command, sha256_file  # noqa: E402
from system.evaluation.runtime import (  # noqa: E402
    MODEL_SOURCE_ROOT,
    PROJECT_ROOT,
    REPORT_ROOT,
    logical_path,
)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def run(command: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def sanitize_remote(remote: str | None) -> str | None:
    if not remote:
        return remote
    if "://" not in remote:
        if "@" in remote and ":" in remote:
            host_path = remote.split("@", 1)[1]
            return f"ssh://{host_path.replace(':', '/', 1)}"
        return remote
    parsed = urlsplit(remote)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def repository_files(repo: Path) -> list[dict[str, Any]]:
    listing = run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=repo)
    if listing is None:
        return []
    records: list[dict[str, Any]] = []
    for relative in sorted(value for value in listing.split("\0") if value):
        path = (repo / relative).resolve()
        try:
            path.relative_to(repo.resolve())
        except ValueError:
            continue
        if path.is_file():
            records.append({
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return records


def repository_record(repo: Path) -> dict[str, Any]:
    repo = repo.expanduser().resolve()
    files = repository_files(repo)
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    licenses = sorted([
        path for path in repo.iterdir()
        if path.is_file() and path.name.lower().startswith(("license", "copying"))
    ]) if repo.is_dir() else []
    status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repo)
    return {
        "name": repo.name,
        "path": logical_path(repo),
        "remote": sanitize_remote(run(["git", "remote", "get-url", "origin"], cwd=repo)),
        "commit": run(["git", "rev-parse", "HEAD"], cwd=repo),
        "branch": run(["git", "branch", "--show-current"], cwd=repo),
        "dirty": bool(status),
        "file_count": len(files),
        "source_tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "licenses": [
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in licenses
        ],
    }


def checkpoint_record(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    return {
        "path": logical_path(target),
        "size_bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def installed_packages() -> list[dict[str, str]]:
    packages = {
        (distribution.metadata.get("Name") or distribution.name).lower(): {
            "name": distribution.metadata.get("Name") or distribution.name,
            "version": distribution.version,
        }
        for distribution in importlib.metadata.distributions()
    }
    return [packages[name] for name in sorted(packages)]


def gpu_inventory() -> list[dict[str, str]]:
    output = run([
        "nvidia-smi",
        "--query-gpu=index,name,uuid,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if not output:
        return []
    fields = ("index", "name", "uuid", "driver_version", "memory_total_mib")
    return [
        dict(zip(fields, (value.strip() for value in line.split(",", maxsplit=4))))
        for line in output.splitlines()
        if line.strip()
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_ROOT / "experiment_context")
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--checkpoint", type=Path, action="append", default=[])
    parser.add_argument("--dataset-manifest", type=Path)
    parser.add_argument(
        "--summary",
        type=Path,
        help="Completed benchmark summary to bind to the captured context.",
    )
    parser.add_argument("--benchmark-command", nargs=argparse.REMAINDER, default=[])
    return parser.parse_args()


def attach_context_to_summary(
    summary_path: Path,
    output: Path,
    outputs: dict[str, Any],
) -> dict[str, Any]:
    """Attach hash-bound context files to an already completed summary."""

    summary_path = summary_path.expanduser().resolve()
    if not summary_path.is_file():
        raise FileNotFoundError(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if (
        not isinstance(summary, dict)
        or summary.get("schema_version") != "benchmark-summary.v2"
        or summary.get("status") != "complete"
    ):
        raise ValueError("context can only attach to a complete benchmark-summary.v2")

    checkpoint_records = outputs["checkpoint_manifest.json"].get("checkpoints", [])
    if not any(
        isinstance(record, dict)
        and record.get("path") == summary.get("checkpoint")
        and record.get("sha256") == summary.get("checkpoint_sha256")
        for record in checkpoint_records
    ):
        raise ValueError("captured checkpoint does not match benchmark summary")
    environment_dataset = outputs["environment.json"].get("dataset_manifest")
    if not isinstance(environment_dataset, dict) or (
        environment_dataset.get("path") != summary.get("dataset_manifest_path")
        or environment_dataset.get("sha256") != summary.get("dataset_manifest_sha256")
    ):
        raise ValueError("captured dataset manifest does not match benchmark summary")

    references = {
        "source_manifest": output / "source_manifest.json",
        "checkpoint_manifest": output / "checkpoint_manifest.json",
        "environment": output / "environment.json",
        "experiment_context_hashes": output / "hashes.sha256",
    }
    for field, path in references.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        summary[f"{field}_path"] = logical_path(path)
        summary[f"{field}_sha256"] = sha256_file(path)
    atomic_json(summary_path, summary)
    return summary


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    sources = args.source or [
        path for path in (
            MODEL_SOURCE_ROOT / "LIDMark",
            MODEL_SOURCE_ROOT / "KAD-Net",
            MODEL_SOURCE_ROOT / "MEA",
        )
        if path.is_dir()
    ]
    for source in sources:
        if not (source / ".git").is_dir():
            raise SystemExit(f"source is not a Git repository: {source}")

    generated_at = int(time.time())
    source_manifest = {
        "schema_version": "source-manifest.v1",
        "generated_at": generated_at,
        "project": repository_record(PROJECT_ROOT),
        "dependencies": [repository_record(path) for path in sources],
    }
    checkpoint_manifest = {
        "schema_version": "checkpoint-manifest.v1",
        "generated_at": generated_at,
        "checkpoints": [checkpoint_record(path) for path in args.checkpoint],
    }
    dataset = None
    if args.dataset_manifest:
        dataset_path = args.dataset_manifest.expanduser().resolve()
        if not dataset_path.is_file():
            raise SystemExit(f"dataset manifest not found: {dataset_path}")
        dataset = {
            "path": logical_path(dataset_path),
            "size_bytes": dataset_path.stat().st_size,
            "sha256": sha256_file(dataset_path),
        }
    usage = shutil.disk_usage(output.parent if output.parent.exists() else PROJECT_ROOT)
    environment = {
        "schema_version": "environment-manifest.v1",
        "generated_at": generated_at,
        "python": sys.version,
        "python_executable": Path(sys.executable).name,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"),
        "gpus": gpu_inventory(),
        "disk": {
            "root": logical_path(output.parent),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
        },
        "packages": installed_packages(),
        "dataset_manifest": dataset,
        "benchmark_command": sanitize_command(args.benchmark_command),
    }

    output.mkdir(parents=True, exist_ok=True)
    outputs = {
        "source_manifest.json": source_manifest,
        "checkpoint_manifest.json": checkpoint_manifest,
        "environment.json": environment,
    }
    for name, payload in outputs.items():
        atomic_json(output / name, payload)
    hashes = [
        f"{sha256_file(output / name)}  {name}"
        for name in sorted(outputs)
    ]
    atomic_bytes(
        output / "hashes.sha256",
        ("\n".join(hashes) + "\n").encode("utf-8"),
    )
    if args.summary:
        attach_context_to_summary(args.summary, output, outputs)
    print(json.dumps({
        "status": "captured",
        "output": logical_path(output),
        "sources": len(sources) + 1,
        "checkpoints": len(args.checkpoint),
        "summary_attached": logical_path(args.summary) if args.summary else None,
        "files": sorted([*outputs, "hashes.sha256"]),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
