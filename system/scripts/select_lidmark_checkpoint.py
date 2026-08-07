#!/usr/bin/env python3
"""Select and integrity-audit the best LIDMark Stage-1 checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import (  # noqa: E402
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
    resolve_logical_path,
)


SCHEMA_VERSION = "jys.lidmark.model-selection.v1"
DEFAULT_RUN_ID = "lidmark-lfw-id-s20260603-128"
ID_BER_LIMIT = 0.01
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_CHECKPOINT_PATTERN = re.compile(r"checkpoint_epoch_([1-9][0-9]*)\.pth")
SELECTION_POLICY = {
    "eligibility": {
        "strict_reload": True,
        "all_epoch_numeric_values_finite": True,
        "all_train_and_val_metrics_finite": True,
        "gradient_finite_all_batches": True,
        "loss_metric_finite_all_batches": True,
        "val.id_ber_max": ID_BER_LIMIT,
    },
    "ranking": [
        "min(val.g_loss)",
        "max(val.psnr)",
        "min(val.landmark_aed)",
        "min(epoch)",
    ],
}


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def checkpoint_epoch(path: Path) -> int:
    match = _CHECKPOINT_PATTERN.fullmatch(path.name)
    if match is None:
        raise ValueError(f"invalid checkpoint filename: {path.name}")
    return int(match.group(1))


def finite_metric_mapping(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    for metric in value.values():
        if isinstance(metric, bool) or not isinstance(metric, (int, float)):
            return False
        if not math.isfinite(float(metric)):
            return False
    return True


def all_numeric_values_finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, Mapping):
        return all(all_numeric_values_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(all_numeric_values_finite(item) for item in value)
    return False


def evaluate_epoch(record: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    try:
        epoch = int(record["epoch"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("epoch record has no valid epoch") from error
    if epoch < 1:
        raise ValueError("epoch must be positive")
    if not all_numeric_values_finite(record):
        reasons.append("epoch_contains_nonfinite_numeric_value")

    train = record.get("train")
    val = record.get("val")
    if not finite_metric_mapping(train):
        reasons.append("train_metrics_not_all_finite")
    if not finite_metric_mapping(val):
        reasons.append("val_metrics_not_all_finite")
    if record.get("gradient_finite_all_batches") is not True:
        reasons.append("gradient_finite_gate_failed")
    if record.get("loss_metric_finite_all_batches") is not True:
        reasons.append("loss_metric_finite_gate_failed")
    strict_reload = record.get("strict_reload")
    if not isinstance(strict_reload, Mapping) or strict_reload.get("strict_reload") is not True:
        reasons.append("strict_reload_gate_failed")

    required_val_metrics = ("id_ber", "g_loss", "psnr", "landmark_aed")
    if isinstance(val, Mapping):
        for name in required_val_metrics:
            if name not in val:
                reasons.append(f"missing_val_{name}")
        id_ber = val.get("id_ber")
        if (
            isinstance(id_ber, bool)
            or not isinstance(id_ber, (int, float))
            or not math.isfinite(float(id_ber))
            or float(id_ber) > ID_BER_LIMIT
        ):
            reasons.append("val_id_ber_above_limit")

    eligible = not reasons
    selection_key: tuple[float, float, float, int] | None = None
    if eligible:
        selection_key = (
            float(val["g_loss"]),
            -float(val["psnr"]),
            float(val["landmark_aed"]),
            epoch,
        )
    return {
        "epoch": epoch,
        "eligible": eligible,
        "exclusion_reasons": reasons,
        "selection_key": selection_key,
        "val": (
            {
                "id_ber": float(val["id_ber"]),
                "g_loss": float(val["g_loss"]),
                "psnr": float(val["psnr"]),
                "landmark_aed": float(val["landmark_aed"]),
            }
            if eligible
            else None
        ),
    }


def select_best_epoch(
    epoch_records: list[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assessments = [evaluate_epoch(record) for record in epoch_records]
    epochs = [item["epoch"] for item in assessments]
    if len(epochs) != len(set(epochs)):
        raise ValueError("history contains duplicate epoch records")
    eligible = [item for item in assessments if item["eligible"]]
    if not eligible:
        raise RuntimeError("no checkpoint satisfies the model-selection eligibility gate")
    selected = min(eligible, key=lambda item: item["selection_key"])
    return selected, sorted(assessments, key=lambda item: item["epoch"])


def resolve_manifest_checkpoint_path(
    reference: str, expected_path: Path, weight_root: Path
) -> Path:
    raw = Path(reference)
    if raw.is_absolute():
        resolved = raw.expanduser().resolve()
    else:
        resolved_from_runtime = resolve_logical_path(raw)
        if resolved_from_runtime is None:
            raise ValueError(f"invalid checkpoint logical path: {reference}")
        resolved = resolved_from_runtime.resolve()
    try:
        resolved.relative_to(weight_root.resolve())
    except ValueError as error:
        raise ValueError(f"checkpoint path escapes the run weight root: {reference}") from error
    if resolved != expected_path.resolve():
        raise RuntimeError(
            f"checkpoint manifest path mismatch for {expected_path.name}"
        )
    return resolved


def audit_checkpoints(
    history_records: list[Mapping[str, Any]],
    checkpoint_records: list[Mapping[str, Any]],
    weight_root: Path,
) -> dict[int, dict[str, Any]]:
    history_by_epoch = {int(record["epoch"]): record for record in history_records}
    if len(history_by_epoch) != len(history_records):
        raise ValueError("history contains duplicate epoch records")
    manifest_by_epoch: dict[int, Mapping[str, Any]] = {}
    for record in checkpoint_records:
        epoch = int(record["epoch"])
        if epoch in manifest_by_epoch:
            raise ValueError("checkpoint hash manifest contains duplicate epochs")
        manifest_by_epoch[epoch] = record
    if set(history_by_epoch) != set(manifest_by_epoch):
        raise RuntimeError("history epochs and checkpoint hash manifest epochs differ")

    audits: dict[int, dict[str, Any]] = {}
    for epoch in sorted(history_by_epoch):
        expected_path = weight_root / f"checkpoint_epoch_{epoch}.pth"
        if not expected_path.is_file():
            raise FileNotFoundError(f"checkpoint is missing: {logical_path(expected_path)}")
        manifest_record = manifest_by_epoch[epoch]
        resolve_manifest_checkpoint_path(
            str(manifest_record.get("path", "")), expected_path, weight_root
        )
        actual_size = expected_path.stat().st_size
        actual_sha = sha256_file(expected_path)
        if int(manifest_record.get("size_bytes", -1)) != actual_size:
            raise RuntimeError(f"checkpoint size mismatch at epoch {epoch}")
        if str(manifest_record.get("sha256")) != actual_sha:
            raise RuntimeError(f"checkpoint SHA-256 mismatch at epoch {epoch}")

        history_checkpoint = history_by_epoch[epoch].get("checkpoint")
        if not isinstance(history_checkpoint, Mapping):
            raise ValueError(f"history epoch {epoch} has no checkpoint record")
        if int(history_checkpoint.get("epoch", -1)) != epoch:
            raise RuntimeError(f"history checkpoint epoch mismatch at epoch {epoch}")
        resolve_manifest_checkpoint_path(
            str(history_checkpoint.get("path", "")), expected_path, weight_root
        )
        if int(history_checkpoint.get("size_bytes", -1)) != actual_size:
            raise RuntimeError(f"history checkpoint size mismatch at epoch {epoch}")
        if str(history_checkpoint.get("sha256")) != actual_sha:
            raise RuntimeError(f"history checkpoint SHA-256 mismatch at epoch {epoch}")
        strict_reload = history_by_epoch[epoch].get("strict_reload")
        if isinstance(strict_reload, Mapping) and str(
            strict_reload.get("checkpoint_sha256")
        ) != actual_sha:
            raise RuntimeError(f"strict-reload SHA-256 mismatch at epoch {epoch}")
        audits[epoch] = {
            "verified": True,
            "path": logical_path(expected_path),
            "size_bytes": actual_size,
            "sha256": actual_sha,
        }
    return audits


def build_selection_report(
    run_id: str,
    history_path: Path,
    checkpoint_manifest_path: Path,
    run_state_path: Path,
    weight_root: Path,
    expected_epochs: int,
) -> dict[str, Any]:
    history = json.loads(history_path.read_text(encoding="utf-8"))
    checkpoint_manifest = json.loads(
        checkpoint_manifest_path.read_text(encoding="utf-8")
    )
    run_state = json.loads(run_state_path.read_text(encoding="utf-8"))
    if run_state.get("status") != "complete":
        raise RuntimeError("training run_state is not complete")
    if int(run_state.get("completed_epoch", -1)) != expected_epochs:
        raise RuntimeError("run_state completed_epoch does not match expected-epochs")
    history_records = history.get("epochs")
    checkpoint_records = checkpoint_manifest.get("checkpoints")
    if not isinstance(history_records, list) or not isinstance(checkpoint_records, list):
        raise ValueError("history/checkpoint manifests have invalid top-level records")
    expected_epoch_set = set(range(1, expected_epochs + 1))
    actual_epoch_set = {int(record["epoch"]) for record in history_records}
    if actual_epoch_set != expected_epoch_set:
        raise RuntimeError("history does not contain the complete expected epoch range")

    audits = audit_checkpoints(history_records, checkpoint_records, weight_root)
    selected, assessments = select_best_epoch(history_records)
    for assessment in assessments:
        assessment["checkpoint"] = audits[assessment["epoch"]]
        if assessment["selection_key"] is not None:
            assessment["selection_key"] = list(assessment["selection_key"])
    selected_epoch = int(selected["epoch"])
    selected_assessment = next(
        item for item in assessments if int(item["epoch"]) == selected_epoch
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "selected",
        "policy": SELECTION_POLICY,
        "policy_sha256": canonical_sha256(SELECTION_POLICY),
        "inputs": {
            "history": {
                "path": logical_path(history_path),
                "sha256": sha256_file(history_path),
            },
            "checkpoint_hashes": {
                "path": logical_path(checkpoint_manifest_path),
                "sha256": sha256_file(checkpoint_manifest_path),
            },
            "run_state": {
                "path": logical_path(run_state_path),
                "sha256": sha256_file(run_state_path),
            },
        },
        "expected_epochs": expected_epochs,
        "audited_checkpoint_count": len(audits),
        "all_checkpoint_integrity_verified": True,
        "eligible_epoch_count": sum(item["eligible"] for item in assessments),
        "selected": {
            "epoch": selected_epoch,
            "checkpoint": selected_assessment["checkpoint"],
            "val": selected_assessment["val"],
            "ranking": SELECTION_POLICY["ranking"],
        },
        "epochs": assessments,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--weight-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-epochs", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not _RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("invalid run-id")
    if args.expected_epochs < 1:
        raise ValueError("expected-epochs must be positive")
    report_root = (
        args.report_root.expanduser().resolve()
        if args.report_root is not None
        else (REPORT_ROOT / args.run_id).resolve()
    )
    weight_root = (
        args.weight_root.expanduser().resolve()
        if args.weight_root is not None
        else (WEIGHT_ROOT / "lidmark" / args.run_id).resolve()
    )
    output = (
        args.output.expanduser().resolve()
        if args.output is not None
        else report_root / "model_selection.json"
    )
    try:
        output.relative_to(report_root)
    except ValueError as error:
        raise ValueError("output must be inside the run report root") from error
    report = build_selection_report(
        args.run_id,
        report_root / "history.json",
        report_root / "checkpoint_hashes.json",
        report_root / "run_state.json",
        weight_root,
        args.expected_epochs,
    )
    atomic_write_json(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
