from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from .run_metadata import build_run_metadata, sha256_file
from .runtime import logical_path


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_dataset_manifest(
    *,
    image_root: Path,
    images: Sequence[Path],
    output_path: Path,
    seed: int,
    selection: str,
) -> dict[str, Any]:
    """Write the exact, content-addressed input set used by a benchmark."""

    root = image_root.expanduser().resolve()
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in images:
        path = raw_path.expanduser().resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"dataset member is outside image root: {path}") from exc
        if relative in seen:
            raise ValueError(f"duplicate dataset member: {relative}")
        if not path.is_file():
            raise FileNotFoundError(path)
        seen.add(relative)
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })

    payload = {
        "schema_version": "dataset-manifest.v1",
        "generated_at": int(time.time()),
        "dataset_root": logical_path(root),
        "selection": selection,
        "seed": seed,
        "sample_count": len(entries),
        "files": entries,
        "files_digest_sha256": hashlib.sha256(_canonical_json(entries)).hexdigest(),
    }
    _atomic_write_json(output_path, payload)
    return payload


def finalize_benchmark_summary(
    summary: dict[str, Any],
    *,
    model: str,
    checkpoint: Path,
    results_path: Path,
    dataset_manifest_path: Path,
    sample_count: int,
    seed: int,
    attack_ids: Iterable[str],
    command: list[str] | None = None,
) -> dict[str, Any]:
    """Attach the minimum independently verifiable evidence envelope.

    This function intentionally refuses to finalize missing artifacts. A caller
    may still write a partial progress summary, but a completed benchmark must
    have concrete input, checkpoint, protocol and raw-result hashes.
    """

    checkpoint = checkpoint.expanduser().resolve()
    results_path = results_path.expanduser().resolve()
    dataset_manifest_path = dataset_manifest_path.expanduser().resolve()
    for role, path in (
        ("checkpoint", checkpoint),
        ("results CSV", results_path),
        ("dataset manifest", dataset_manifest_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{role} not found: {path}")
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")

    metadata = build_run_metadata(
        model=model,
        checkpoint=checkpoint,
        seed=seed,
        command=command or sys.argv,
    )
    attacks = list(dict.fromkeys(str(value) for value in attack_ids))
    if not attacks:
        raise ValueError("attack_ids must not be empty")

    finalized = dict(summary)
    finalized.update({
        "schema_version": "benchmark-summary.v2",
        "status": "complete",
        "checkpoint": logical_path(checkpoint),
        "checkpoint_sha256": sha256_file(checkpoint),
        "dataset_manifest_path": logical_path(dataset_manifest_path),
        "dataset_manifest_sha256": sha256_file(dataset_manifest_path),
        "results_csv_path": logical_path(results_path),
        "results_csv_sha256": sha256_file(results_path),
        "protocol_version": metadata["evaluation_protocol"],
        "protocol_path": metadata["protocol_path"],
        "protocol_sha256": metadata["protocol_sha256"],
        "seed": seed,
        "sample_count": sample_count,
        "num_images": sample_count,
        "attack_ids": attacks,
        "expected_result_rows": sample_count * len(attacks),
        "run_metadata": metadata,
    })
    return finalized
