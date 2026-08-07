#!/usr/bin/env python3
"""Atomically register one strictly validated checkpoint calibration."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system.backend import provenance  # noqa: E402
from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.evaluation.runtime import WEIGHT_ROOT, logical_path  # noqa: E402


SCHEMA_VERSION = "weight-manifest.v1"
REVISION_RE = re.compile(r"^[A-Za-z0-9._-]{7,128}$")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=WEIGHT_ROOT / "WEIGHT_MANIFEST.json",
    )
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--replace-model", action="store_true")
    return parser.parse_args(argv)


def _strict_json(path: Path) -> dict[str, Any]:
    def reject(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    payload = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {logical_path(path)}")
    return payload


def _relative_file(path: Path, root: Path, label: str) -> str:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(root.expanduser().resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the configured weight root") from exc
    if not resolved.is_file() or ".." in relative.parts:
        raise FileNotFoundError(f"{label} not found: {logical_path(resolved)}")
    return relative.as_posix()


def _reviewer(value: str) -> str:
    reviewed_by = value.strip()
    if not reviewed_by or len(reviewed_by) > 128 or any(ord(char) < 32 for char in reviewed_by):
        raise ValueError("reviewed-by must contain 1-128 printable characters")
    return reviewed_by


def register_checkpoint(
    args: argparse.Namespace,
    *,
    weight_root: Path = WEIGHT_ROOT,
) -> dict[str, Any]:
    weight_root = weight_root.expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if output.parent != weight_root or output.name != "WEIGHT_MANIFEST.json":
        raise ValueError("output must be WEIGHT_MANIFEST.json at the configured weight root")
    if Path(args.output).expanduser().is_symlink():
        raise ValueError("weight manifest must not be a symbolic link")
    checkpoint = Path(args.checkpoint).expanduser().resolve()
    calibration_path = Path(args.calibration).expanduser().resolve()
    checkpoint_relative = _relative_file(checkpoint, weight_root, "checkpoint")
    calibration_relative = _relative_file(calibration_path, weight_root, "calibration")
    checkpoint_hash = sha256_file(checkpoint)
    calibration_hash = sha256_file(calibration_path)
    if checkpoint_hash is None or calibration_hash is None:
        raise RuntimeError("checkpoint or calibration hash unavailable")

    calibration = _strict_json(calibration_path)
    model = str(args.model).strip()
    if (
        not model
        or calibration.get("schema_version") != "threshold-calibration.v1"
        or calibration.get("status") != "complete"
        or str(calibration.get("model") or "").lower() != model.lower()
        or str(calibration.get("checkpoint_sha256") or "").lower() != checkpoint_hash
    ):
        raise ValueError("calibration does not bind the requested model and checkpoint")
    try:
        threshold = float(calibration["threshold"])
        metrics = calibration["metrics"]
        positive_samples = int(metrics["positive_samples"])
        negative_samples = int(metrics["negative_samples"])
        false_accept_rate = float(metrics["false_accept_rate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("calibration holdout metrics are incomplete") from exc
    if (
        not math.isfinite(threshold)
        or not 0.0 <= threshold <= 1.0
        or positive_samples <= 0
        or negative_samples <= 0
        or not math.isfinite(false_accept_rate)
        or not 0.0 <= false_accept_rate <= 1.0
    ):
        raise ValueError("calibration holdout metrics are invalid")
    revision = str(args.source_revision).strip()
    if not REVISION_RE.fullmatch(revision):
        raise ValueError("source-revision must be a 7-128 character revision identifier")

    item = {
        "model": model,
        "file": checkpoint_relative,
        "sha256": checkpoint_hash,
        "status": "verified",
        "verification_threshold": threshold,
        "calibration_artifact": calibration_relative,
        "calibration_artifact_sha256": calibration_hash,
        "calibration_positive_samples": positive_samples,
        "calibration_negative_samples": negative_samples,
        "calibration_false_accept_rate": false_accept_rate,
        "calibration_true_accept_rate": float(metrics["true_accept_rate"]),
        "calibration_false_reject_rate": float(metrics["false_reject_rate"]),
        "calibration_false_accept_rate_wilson_95": metrics[
            "false_accept_rate_wilson_95"
        ],
        "calibration_attack_ids": list(calibration["attack_ids"]),
        "calibration_dataset_manifest_sha256": calibration[
            "dataset_manifest_sha256"
        ],
        "reviewed_by": _reviewer(str(args.reviewed_by)),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": revision,
    }

    existing_items: list[dict[str, Any]] = []
    if output.exists():
        existing = _strict_json(output)
        if existing.get("schema_version") != SCHEMA_VERSION or not isinstance(
            existing.get("items"), list
        ):
            raise ValueError("existing weight manifest has an invalid schema")
        existing_items = [dict(value) for value in existing["items"] if isinstance(value, dict)]
        if len(existing_items) != len(existing["items"]):
            raise ValueError("existing weight manifest contains a non-object item")

    matches = [
        index
        for index, value in enumerate(existing_items)
        if str(value.get("model") or "").lower() == model.lower()
    ]
    if matches and not bool(args.replace_model):
        raise FileExistsError(f"model already registered: {model}")
    if len(matches) > 1:
        raise ValueError(f"existing weight manifest has duplicate model entries: {model}")
    if matches:
        existing_items[matches[0]] = item
    else:
        existing_items.append(item)
    existing_items.sort(key=lambda value: str(value.get("model") or "").lower())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": existing_items,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    encoded = (
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    previous_manifest = provenance.MANIFEST
    provenance.MANIFEST = temporary
    try:
        if not provenance._checkpoint_registered(model, checkpoint_hash):
            raise ValueError("candidate manifest does not bind the checkpoint bytes")
        if not provenance._checkpoint_calibrated(model, checkpoint_hash, threshold):
            raise ValueError("candidate calibration failed strict semantic validation")
        os.replace(temporary, output)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(output.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        provenance.MANIFEST = previous_manifest
        if temporary.exists():
            temporary.unlink()
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = register_checkpoint(args)
    selected = next(
        item for item in manifest["items"]
        if str(item.get("model") or "").lower() == str(args.model).lower()
    )
    print(json.dumps({
        "status": "verified",
        "model": selected["model"],
        "checkpoint_sha256": selected["sha256"],
        "verification_threshold": selected["verification_threshold"],
        "manifest": logical_path(Path(args.output).expanduser().resolve()),
    }, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
