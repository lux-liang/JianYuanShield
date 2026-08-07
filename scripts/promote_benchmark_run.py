#!/usr/bin/env python3
"""Audit and atomically promote one benchmark run to its canonical paths."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.backend import benchmark_evidence  # noqa: E402
from system.evaluation import runtime  # noqa: E402
from system.evaluation.attacks import ATTACKS  # noqa: E402
from system.evaluation.run_metadata import sha256_file  # noqa: E402


RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{6,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAMPLE_DIR_RE = re.compile(r"^sample_[0-9]{5}$")
CONTEXT_FILES = {
    "source_manifest": "source_manifest.json",
    "checkpoint_manifest": "checkpoint_manifest.json",
    "environment": "environment.json",
    "experiment_context_hashes": "hashes.sha256",
}
BASE_REPORT_FILES = {
    "summary.json",
    "results.csv",
    "watermarked_quality.csv",
    "dataset_manifest.json",
    "run_config.json",
    "progress.json",
}
OPTIONAL_REPORT_FILES = {"stdout.log"}


class PromotionError(RuntimeError):
    """The candidate run cannot become the canonical benchmark."""


@dataclass(frozen=True)
class BenchmarkSpec:
    cli_name: str
    model: str
    method: str
    canonical_name: str
    run_prefix: str
    runner_path: str
    run_config_schema: str
    primary_decoder: str | None = None
    secondary_decoder: str | None = None
    artifact_manifest_required: bool = False


SPECS = {
    "kadnet": BenchmarkSpec(
        cli_name="kadnet",
        model="KAD-Net",
        method="KAD-Net",
        canonical_name="kadnet_lfw_benchmark",
        run_prefix="kadnet-",
        runner_path="system/scripts/run_kadnet_lfw_benchmark.py",
        run_config_schema="kadnet-benchmark-config.v1",
    ),
    "sepmark": BenchmarkSpec(
        cli_name="sepmark",
        model="SepMark",
        method="SepMark",
        canonical_name="sepmark_lfw_benchmark",
        run_prefix="sepmark-",
        runner_path="system/scripts/run_sepmark_lfw_benchmark.py",
        run_config_schema="sepmark-benchmark-config.v1",
        primary_decoder="decoder_C",
        secondary_decoder="decoder_RF",
    ),
    "waveguard": BenchmarkSpec(
        cli_name="waveguard",
        model="WaveGuard",
        method="WaveGuard",
        canonical_name="waveguard_lfw_benchmark",
        run_prefix="waveguard-",
        runner_path="system/scripts/run_waveguard_lfw_benchmark.py",
        run_config_schema="waveguard-benchmark-config.v1",
        primary_decoder="tracer",
        secondary_decoder="detector",
        artifact_manifest_required=True,
    ),
}


@dataclass(frozen=True)
class FileStamp:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class RunAudit:
    spec: BenchmarkSpec
    run_id: str
    report_run: Path
    asset_run: Path
    report_canonical: Path
    asset_canonical: Path
    checks: Mapping[str, bool]
    snapshot: Mapping[Path, FileStamp]
    validation_snapshot_sha256: str
    asset_files_digest_sha256: str


def _fail(message: str) -> None:
    raise PromotionError(message)


def _require(condition: Any, message: str) -> None:
    if not condition:
        _fail(message)


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    _require_regular(path, label)
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise PromotionError(f"{label} is not strict JSON") from exc
    _require(isinstance(payload, dict), f"{label} must be a JSON object")
    return payload


def _canonical_sha256(payload: Any) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PromotionError("evidence contains a non-canonical JSON value") from exc
    return hashlib.sha256(encoded).hexdigest()


def _stamp(path: Path) -> FileStamp:
    try:
        value = path.lstat()
    except OSError as exc:
        raise PromotionError(f"evidence path disappeared: {path}") from exc
    return FileStamp(
        device=value.st_dev,
        inode=value.st_ino,
        mode=value.st_mode,
        size=value.st_size,
        mtime_ns=value.st_mtime_ns,
    )


def _require_regular(path: Path, label: str) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise PromotionError(f"{label} is missing: {path}") from exc
    _require(
        stat.S_ISREG(value.st_mode) and not path.is_symlink(),
        f"{label} must be a regular non-symlink file: {path}",
    )


def _require_real_directory(path: Path, label: str) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise PromotionError(f"{label} is missing: {path}") from exc
    _require(
        stat.S_ISDIR(value.st_mode) and not path.is_symlink(),
        f"{label} must be a real directory: {path}",
    )


def _logical(path: Path) -> str:
    return runtime.logical_path(path)


def _resolve(reference: Any, label: str) -> Path:
    _require(isinstance(reference, str) and bool(reference), f"{label} path is missing")
    candidate = runtime.resolve_logical_path(reference)
    _require(candidate is not None, f"{label} path is outside approved roots")
    return candidate.resolve()


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _sha256(path: Path, label: str) -> str:
    _require_regular(path, label)
    digest = sha256_file(path)
    _require(isinstance(digest, str) and SHA256_RE.fullmatch(digest), f"{label} SHA-256 unavailable")
    return digest


def _bound_file(
    payload: Mapping[str, Any],
    *,
    path_field: str,
    hash_field: str,
    expected_path: Path | None,
    label: str,
) -> tuple[Path, str]:
    path = _resolve(payload.get(path_field), label)
    if expected_path is not None:
        _require(path == expected_path.resolve(), f"{label} does not point into the selected run")
    actual = _sha256(path, label)
    declared = str(payload.get(hash_field) or "").lower()
    _require(SHA256_RE.fullmatch(declared) is not None, f"{label} has no valid declared SHA-256")
    _require(actual == declared, f"{label} SHA-256 mismatch")
    return path, actual


def _validate_run_id(spec: BenchmarkSpec, run_id: str) -> None:
    _require(RUN_ID_RE.fullmatch(run_id) is not None, "run-id must be a lowercase safe directory name")
    _require(run_id.startswith(spec.run_prefix), f"run-id must start with {spec.run_prefix}")
    _require(run_id != spec.canonical_name, "run-id must not be a canonical directory name")


def _validate_report_inventory(report_run: Path, spec: BenchmarkSpec) -> list[Path]:
    required = set(BASE_REPORT_FILES)
    if spec.artifact_manifest_required:
        required.add("artifact_manifest.json")
    entries = {entry.name: entry for entry in report_run.iterdir()}
    missing = sorted(required - set(entries))
    unexpected = sorted(set(entries) - required - OPTIONAL_REPORT_FILES)
    _require(not missing, "run report is missing: " + ", ".join(missing))
    _require(not unexpected, "run report contains unregistered entries: " + ", ".join(unexpected))
    for name, path in entries.items():
        _require_regular(path, f"report entry {name}")
    return [entries[name] for name in sorted(entries)]


def _asset_files(asset_run: Path) -> list[Path]:
    files: list[Path] = []
    for root, directory_names, file_names in os.walk(asset_run, followlinks=False):
        current = Path(root)
        for name in sorted(directory_names):
            path = current / name
            _require(not path.is_symlink(), f"asset directory must not be a symlink: {path}")
            _require_real_directory(path, "asset directory")
            relative = path.relative_to(asset_run)
            _require(
                len(relative.parts) == 1 and SAMPLE_DIR_RE.fullmatch(name) is not None,
                f"asset directory is outside the registered layout: {relative.as_posix()}",
            )
        for name in sorted(file_names):
            path = current / name
            _require_regular(path, "asset file")
            relative = path.relative_to(asset_run)
            _require(not name.startswith("."), f"temporary or hidden asset is forbidden: {relative.as_posix()}")
            _require(path.suffix.lower() == ".png", f"non-PNG asset is forbidden: {relative.as_posix()}")
            valid_layout = relative.as_posix() == "grid.png" or (
                len(relative.parts) == 2
                and SAMPLE_DIR_RE.fullmatch(relative.parts[0]) is not None
            )
            _require(valid_layout, f"asset file is outside the registered layout: {relative.as_posix()}")
            files.append(path)
    _require(files, "run asset directory contains no auditable PNG artifacts")
    return sorted(files, key=lambda path: path.relative_to(asset_run).as_posix())


def _csv_header(path: Path, label: str) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            header = list(csv.DictReader(handle).fieldnames or [])
    except (OSError, UnicodeError, csv.Error) as exc:
        raise PromotionError(f"{label} header cannot be read") from exc
    _require(header and len(header) == len(set(header)), f"{label} header is invalid")
    return header


def _protocol_contract(protocol: Mapping[str, Any]) -> tuple[list[str], str]:
    _require(protocol.get("schema_version") == "evaluation_protocol.v1", "protocol schema mismatch")
    attacks = protocol.get("attacks")
    attack_ids = protocol.get("attack_ids")
    _require(isinstance(attacks, list) and bool(attacks), "protocol attacks are missing")
    derived_ids = [entry.get("id") for entry in attacks if isinstance(entry, dict)]
    _require(len(derived_ids) == len(attacks), "protocol contains a malformed attack")
    _require(
        all(isinstance(attack_id, str) and bool(attack_id) for attack_id in derived_ids),
        "protocol contains an invalid attack ID",
    )
    _require(
        isinstance(attack_ids, list)
        and len(attack_ids) == len(set(attack_ids))
        and set(attack_ids) == set(derived_ids)
        and len(attack_ids) == len(derived_ids),
        "protocol attack_ids do not match the attack registry",
    )
    entries = {str(entry["id"]): entry for entry in attacks}
    for attack_id in derived_ids:
        _require(attack_id in ATTACKS, f"attack implementation is missing: {attack_id}")
        shared = ATTACKS[attack_id]
        registered = entries[attack_id]
        _require(registered.get("type") == shared.type, f"attack type drift: {attack_id}")
        for key, value in shared.parameters.items():
            _require(
                registered.get("parameters", {}).get(key) == value,
                f"attack parameter drift: {attack_id}.{key}",
            )
    contract_hash = _canonical_sha256([
        {
            "protocol": entries[attack_id],
            "shared_config_sha256": ATTACKS[attack_id].config_hash,
        }
        for attack_id in derived_ids
    ])
    return [str(value) for value in derived_ids], contract_hash


def _validate_context(
    summary: Mapping[str, Any],
    *,
    spec: BenchmarkSpec,
    run_id: str,
    checkpoint: Path,
    checkpoint_sha256: str,
    dataset_manifest: Path,
    dataset_manifest_sha256: str,
) -> list[Path]:
    context_dir = runtime.REPORT_ROOT.resolve() / "experiment_context" / run_id
    _require_real_directory(context_dir, "run-specific experiment context")
    _require(
        context_dir.parent == runtime.REPORT_ROOT.resolve() / "experiment_context",
        "context directory is not a direct run-specific child",
    )
    entries = {entry.name: entry for entry in context_dir.iterdir()}
    _require(
        set(entries) == set(CONTEXT_FILES.values()),
        "context directory must contain exactly source, checkpoint, environment and hashes files",
    )

    paths: dict[str, Path] = {}
    for field, filename in CONTEXT_FILES.items():
        path, _ = _bound_file(
            summary,
            path_field=f"{field}_path",
            hash_field=f"{field}_sha256",
            expected_path=context_dir / filename,
            label=f"context {field}",
        )
        paths[field] = path

    expected_hash_lines = {
        filename: _sha256(context_dir / filename, f"context {filename}")
        for filename in ("checkpoint_manifest.json", "environment.json", "source_manifest.json")
    }
    parsed_hash_lines: dict[str, str] = {}
    try:
        lines = paths["experiment_context_hashes"].read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise PromotionError("context hashes.sha256 cannot be read") from exc
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        _require(match is not None, "context hashes.sha256 has a malformed line")
        digest, filename = match.groups()
        _require(filename not in parsed_hash_lines, "context hashes.sha256 has a duplicate filename")
        parsed_hash_lines[filename] = digest
    _require(parsed_hash_lines == expected_hash_lines, "context hashes.sha256 does not bind the context files")

    source = _load_json(paths["source_manifest"], "source manifest")
    _require(source.get("schema_version") == "source-manifest.v1", "source manifest schema mismatch")
    project = source.get("project")
    dependencies = source.get("dependencies")
    _require(isinstance(project, dict), "source manifest project record is missing")
    _require(
        SHA256_RE.fullmatch(str(project.get("source_tree_sha256") or "")) is not None,
        "source manifest project tree hash is missing",
    )
    _require(isinstance(dependencies, list) and bool(dependencies), "source dependency records are missing")
    _require(
        all(
            isinstance(record, dict)
            and SHA256_RE.fullmatch(str(record.get("source_tree_sha256") or "")) is not None
            for record in dependencies
        ),
        "source dependency tree hash is missing",
    )

    checkpoint_manifest = _load_json(paths["checkpoint_manifest"], "checkpoint manifest")
    records = checkpoint_manifest.get("checkpoints")
    _require(
        checkpoint_manifest.get("schema_version") == "checkpoint-manifest.v1"
        and isinstance(records, list)
        and len(records) == 1,
        "checkpoint context must contain exactly one checkpoint",
    )
    checkpoint_record = records[0]
    _require(isinstance(checkpoint_record, dict), "checkpoint context record is malformed")
    _require(
        checkpoint_record.get("path") == _logical(checkpoint)
        and checkpoint_record.get("sha256") == checkpoint_sha256
        and checkpoint_record.get("size_bytes") == checkpoint.stat().st_size,
        "checkpoint context does not bind the benchmark checkpoint",
    )

    environment = _load_json(paths["environment"], "environment manifest")
    dataset_record = environment.get("dataset_manifest")
    command = environment.get("benchmark_command")
    _require(environment.get("schema_version") == "environment-manifest.v1", "environment schema mismatch")
    _require(isinstance(dataset_record, dict), "environment dataset record is missing")
    _require(
        dataset_record.get("path") == _logical(dataset_manifest)
        and dataset_record.get("sha256") == dataset_manifest_sha256
        and dataset_record.get("size_bytes") == dataset_manifest.stat().st_size,
        "environment context does not bind the benchmark dataset manifest",
    )
    _require(isinstance(command, list) and bool(command), "benchmark command is missing from context")
    _require(
        any(str(value).endswith(spec.runner_path) for value in command),
        "context benchmark command does not name the selected model runner",
    )
    return [paths[field] for field in CONTEXT_FILES]


def _validate_progress(progress_path: Path, sample_count: int, expected_rows: int) -> None:
    progress = _load_json(progress_path, "progress")
    _require(progress.get("schema_version") == "benchmark-progress.v1", "progress schema mismatch")
    _require(progress.get("status") == "complete", "progress is not complete")
    _require(progress.get("processed_images") == sample_count, "progress processed image count mismatch")
    _require(progress.get("total_images") == sample_count, "progress total image count mismatch")
    _require(progress.get("result_rows") == expected_rows, "progress raw row count mismatch")
    _require(progress.get("expected_result_rows") == expected_rows, "progress expected row count mismatch")
    _require(progress.get("error_rows") == 0, "progress contains error rows")


def _validate_artifact_manifest(
    summary: Mapping[str, Any],
    *,
    report_run: Path,
    asset_run: Path,
    asset_records: Sequence[Mapping[str, Any]],
    asset_files_digest_sha256: str,
) -> Path:
    manifest_path, _ = _bound_file(
        summary,
        path_field="artifact_manifest_path",
        hash_field="artifact_manifest_sha256",
        expected_path=report_run / "artifact_manifest.json",
        label="artifact manifest",
    )
    manifest = _load_json(manifest_path, "artifact manifest")
    _require(manifest.get("schema_version") == "benchmark-artifact-manifest.v1", "artifact manifest schema mismatch")
    _require(manifest.get("asset_root") == _logical(asset_run), "artifact manifest targets another asset run")
    _require(manifest.get("file_count") == len(asset_records), "artifact manifest file count mismatch")
    _require(manifest.get("files") == list(asset_records), "artifact manifest file records mismatch")
    _require(
        manifest.get("files_digest_sha256") == asset_files_digest_sha256,
        "artifact manifest digest mismatch",
    )
    _require(
        summary.get("artifact_files_digest_sha256") == asset_files_digest_sha256,
        "summary artifact digest mismatch",
    )
    return manifest_path


def _snapshot_fingerprint(snapshot: Mapping[Path, FileStamp]) -> str:
    records = [
        {
            "path": _logical(path),
            "device": value.device,
            "inode": value.inode,
            "mode": value.mode,
            "size": value.size,
            "mtime_ns": value.mtime_ns,
        }
        for path, value in sorted(snapshot.items(), key=lambda item: str(item[0]))
    ]
    return _canonical_sha256(records)


def audit_run(model: str, run_id: str) -> RunAudit:
    try:
        spec = SPECS[model]
    except KeyError as exc:
        raise PromotionError(f"unsupported model: {model}") from exc
    _validate_run_id(spec, run_id)

    report_root = runtime.REPORT_ROOT.resolve()
    asset_root = runtime.ASSET_ROOT.resolve()
    _require_real_directory(report_root, "report root")
    _require_real_directory(asset_root, "asset root")
    report_run = report_root / run_id
    asset_run = asset_root / run_id
    _require_real_directory(report_run, "run-specific report")
    _require_real_directory(asset_run, "run-specific assets")
    _require(report_run.parent == report_root, "report run must be a direct child of report root")
    _require(asset_run.parent == asset_root, "asset run must be a direct child of asset root")

    report_files = _validate_report_inventory(report_run, spec)
    asset_files = _asset_files(asset_run)
    asset_records = [
        {
            "path": path.relative_to(asset_run).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path, "asset file"),
        }
        for path in asset_files
    ]
    asset_files_digest = _canonical_sha256(asset_records)
    summary_path = report_run / "summary.json"
    results_path = report_run / "results.csv"
    quality_path = report_run / "watermarked_quality.csv"
    dataset_path = report_run / "dataset_manifest.json"
    config_path = report_run / "run_config.json"
    progress_path = report_run / "progress.json"

    summary = _load_json(summary_path, "summary")
    config = _load_json(config_path, "run config")
    dataset = _load_json(dataset_path, "dataset manifest")
    protocol_path = runtime.PROJECT_ROOT.resolve() / "configs" / "evaluation_protocol.v1.json"
    protocol = _load_json(protocol_path, "evaluation protocol")
    protocol_hash = _sha256(protocol_path, "evaluation protocol")
    attack_ids, attack_contract_hash = _protocol_contract(protocol)

    _require(summary.get("schema_version") == "benchmark-summary.v2", "summary schema mismatch")
    _require(summary.get("status") == "complete", "summary is not complete")
    _require(summary.get("method") == spec.method, "summary method does not match selected model")
    _require(summary.get("mode") == "real_checkpoint", "summary is not a real-checkpoint run")
    _require(config.get("schema_version") == spec.run_config_schema, "run config schema mismatch")
    _require(config.get("method") == spec.method, "run config method mismatch")
    _require(config.get("mode") == "real_checkpoint", "run config is not a real-checkpoint run")

    sample_count = summary.get("sample_count")
    _require(
        isinstance(sample_count, int) and not isinstance(sample_count, bool) and sample_count > 0,
        "summary sample_count is invalid",
    )
    _require(summary.get("num_images") == sample_count, "summary num_images mismatch")
    expected_rows = sample_count * len(attack_ids)
    _require(summary.get("attack_ids") == attack_ids, "summary does not use the complete protocol attack order")
    _require(config.get("attack_ids") == attack_ids, "run config does not use the complete protocol attack order")
    _require(summary.get("expected_result_rows") == expected_rows, "summary expected row count mismatch")
    _require(summary.get("result_rows") == expected_rows, "summary raw row count mismatch")
    _require(summary.get("requested_images") == sample_count, "summary requested image count mismatch")
    _require(summary.get("evaluated_rows") == expected_rows, "summary evaluated row count mismatch")
    _require(summary.get("error_rows") == 0, "summary contains error rows")
    _require(summary.get("missing_rows") == 0, "summary contains missing rows")
    _require(summary.get("data_type") == "real_lfw_images", "summary data type mismatch")
    _require(config.get("sample_count") == sample_count, "run config sample count mismatch")

    protocol_version = protocol.get("schema_version")
    seed = protocol.get("seed")
    threshold = protocol.get("success_threshold")
    _require(isinstance(seed, int) and not isinstance(seed, bool), "protocol seed is invalid")
    _require(
        isinstance(threshold, (int, float))
        and not isinstance(threshold, bool)
        and math.isfinite(float(threshold)),
        "protocol threshold is invalid",
    )
    _require(0 <= float(threshold) <= 1, "protocol threshold is outside [0,1]")
    for payload, label in ((summary, "summary"), (config, "run config")):
        _require(payload.get("protocol_version") == protocol_version, f"{label} protocol version mismatch")
        _require(_resolve(payload.get("protocol_path"), f"{label} protocol") == protocol_path, f"{label} protocol path mismatch")
        _require(payload.get("protocol_sha256") == protocol_hash, f"{label} protocol hash mismatch")
        _require(payload.get("seed") == seed, f"{label} seed mismatch")
    configured_threshold = config.get("success_threshold")
    _require(
        isinstance(configured_threshold, (int, float))
        and not isinstance(configured_threshold, bool)
        and math.isfinite(float(configured_threshold))
        and float(configured_threshold) == float(threshold),
        "run config threshold mismatch",
    )
    if "success_threshold" in summary:
        summary_threshold = summary.get("success_threshold")
        _require(
            isinstance(summary_threshold, (int, float))
            and not isinstance(summary_threshold, bool)
            and math.isfinite(float(summary_threshold))
            and float(summary_threshold) == float(threshold),
            "summary threshold mismatch",
        )
    _require(config.get("attack_contract_sha256") == attack_contract_hash, "run config attack contract mismatch")

    models = protocol.get("models")
    _require(isinstance(models, dict) and isinstance(models.get(spec.model), dict), "model contract is missing")
    model_contract = models[spec.model]
    if spec.primary_decoder is not None:
        _require(model_contract.get("primary_decoder") == spec.primary_decoder, "protocol primary decoder mismatch")
        _require(model_contract.get("secondary_decoder") == spec.secondary_decoder, "protocol secondary decoder mismatch")
        for payload, label in ((summary, "summary"), (config, "run config")):
            _require(payload.get("primary_decoder") == spec.primary_decoder, f"{label} primary decoder mismatch")
            _require(payload.get("secondary_decoder") == spec.secondary_decoder, f"{label} secondary decoder mismatch")
        _require(config.get("model_contract_sha256") == _canonical_sha256(model_contract), "run config model contract mismatch")

    _bound_file(
        summary,
        path_field="results_csv_path",
        hash_field="results_csv_sha256",
        expected_path=results_path,
        label="raw results",
    )
    _bound_file(
        summary,
        path_field="watermarked_quality_csv_path",
        hash_field="watermarked_quality_csv_sha256",
        expected_path=quality_path,
        label="watermarked quality",
    )
    _, dataset_hash = _bound_file(
        summary,
        path_field="dataset_manifest_path",
        hash_field="dataset_manifest_sha256",
        expected_path=dataset_path,
        label="dataset manifest",
    )
    _bound_file(
        summary,
        path_field="run_config_path",
        hash_field="run_config_sha256",
        expected_path=config_path,
        label="run config",
    )
    checkpoint, checkpoint_hash = _bound_file(
        summary,
        path_field="checkpoint",
        hash_field="checkpoint_sha256",
        expected_path=None,
        label="checkpoint",
    )
    _require(_within(checkpoint, runtime.WEIGHT_ROOT), "checkpoint is outside the configured weight root")

    for field, expected in (
        ("protocol_path", _logical(protocol_path)),
        ("protocol_sha256", protocol_hash),
        ("dataset_manifest_path", _logical(dataset_path)),
        ("dataset_manifest_sha256", dataset_hash),
        ("checkpoint", _logical(checkpoint)),
        ("checkpoint_sha256", checkpoint_hash),
    ):
        _require(config.get(field) == expected, f"run config {field} mismatch")
    _require(config.get("dataset_files_digest_sha256") == dataset.get("files_digest_sha256"), "run config dataset digest mismatch")
    if spec.primary_decoder is not None:
        _require("asset_dir" in config, "run config asset directory binding is missing")
    if "asset_dir" in config:
        _require(config.get("asset_dir") == _logical(asset_run), "run config targets another asset run")

    message_length = summary.get("message_length")
    _require(isinstance(message_length, int) and message_length > 0, "summary message length is invalid")
    _require(config.get("message_length") == message_length, "run config message length mismatch")
    _require(
        summary.get("message_derivation") == config.get("message_derivation"),
        "summary message derivation mismatch",
    )
    _require(config.get("result_schema") == _csv_header(results_path, "raw results"), "raw result schema drift")
    _require(
        config.get("watermarked_quality_schema") == _csv_header(quality_path, "watermarked quality"),
        "watermarked quality schema drift",
    )

    run_metadata = summary.get("run_metadata")
    _require(isinstance(run_metadata, dict), "summary run metadata is missing")
    for field, expected in (
        ("schema_version", "run-metadata.v1"),
        ("model", spec.model),
        ("seed", seed),
        ("evaluation_protocol", protocol_version),
        ("protocol_path", _logical(protocol_path)),
        ("protocol_sha256", protocol_hash),
        ("checkpoint", _logical(checkpoint)),
        ("checkpoint_sha256", checkpoint_hash),
    ):
        _require(run_metadata.get(field) == expected, f"run metadata {field} mismatch")
    metadata_command = run_metadata.get("command")
    _require(isinstance(metadata_command, list) and bool(metadata_command), "run metadata command is missing")
    _require(
        any(str(value).endswith(spec.runner_path) for value in metadata_command),
        "run metadata command does not name the selected model runner",
    )

    _require(
        benchmark_evidence._load_dataset_manifest(dataset_path, sample_count),
        "dataset manifest failed structural audit",
    )
    attack_config_hashes = {attack_id: ATTACKS[attack_id].config_hash for attack_id in attack_ids}
    protocol_attack_hashes = {
        str(item["id"]): _canonical_sha256(item)
        for item in protocol["attacks"]
    }
    raw_valid, raw_audit = benchmark_evidence._csv_structure_valid(
        results_path,
        sample_count=sample_count,
        attack_ids=attack_ids,
        summary=summary,
        success_threshold=float(threshold),
        attack_config_hashes=attack_config_hashes,
        protocol_attack_hashes=protocol_attack_hashes,
    )
    _require(raw_valid, "raw result audit failed: " + json.dumps(raw_audit, sort_keys=True))
    quality_valid, quality_audit = benchmark_evidence._quality_csv_structure_valid(
        quality_path,
        sample_count=sample_count,
        summary=summary,
    )
    _require(quality_valid, "watermarked quality audit failed: " + json.dumps(quality_audit, sort_keys=True))
    _require(
        raw_audit.get("sample_binding_sha256") == quality_audit.get("sample_binding_sha256"),
        "raw and quality rows bind different samples or messages",
    )
    dataset_bindings = benchmark_evidence._dataset_manifest_bindings(dataset_path)
    _require(
        dataset_bindings.get("sample_path_sha256") == raw_audit.get("sample_path_binding_sha256"),
        "dataset manifest and raw rows bind different samples",
    )
    if dataset_bindings.get("message_sha256") is not None:
        _require(
            dataset_bindings.get("message_sha256") == raw_audit.get("message_binding_sha256"),
            "dataset manifest and raw rows bind different messages",
        )

    _validate_progress(progress_path, sample_count, expected_rows)
    if "progress_path" in summary or "progress_sha256" in summary:
        _bound_file(
            summary,
            path_field="progress_path",
            hash_field="progress_sha256",
            expected_path=progress_path,
            label="progress",
        )

    context_paths = _validate_context(
        summary,
        spec=spec,
        run_id=run_id,
        checkpoint=checkpoint,
        checkpoint_sha256=checkpoint_hash,
        dataset_manifest=dataset_path,
        dataset_manifest_sha256=dataset_hash,
    )
    if spec.artifact_manifest_required:
        _validate_artifact_manifest(
            summary,
            report_run=report_run,
            asset_run=asset_run,
            asset_records=asset_records,
            asset_files_digest_sha256=asset_files_digest,
        )

    snapshot_paths = {
        *report_files,
        *asset_files,
        *context_paths,
        protocol_path,
        checkpoint,
    }
    snapshot = {path: _stamp(path) for path in snapshot_paths}
    checks = {
        "run_layout_clean": True,
        "summary_complete": True,
        "protocol_bound": True,
        "checkpoint_bound": True,
        "dataset_bound": True,
        "raw_rows_complete": True,
        "quality_rows_complete": True,
        "progress_complete": True,
        "context_complete": True,
        "assets_clean": True,
        "artifact_manifest_bound_or_not_required": True,
    }
    return RunAudit(
        spec=spec,
        run_id=run_id,
        report_run=report_run,
        asset_run=asset_run,
        report_canonical=report_root / spec.canonical_name,
        asset_canonical=asset_root / spec.canonical_name,
        checks=checks,
        snapshot=snapshot,
        validation_snapshot_sha256=_snapshot_fingerprint(snapshot),
        asset_files_digest_sha256=asset_files_digest,
    )


def _managed_link_target(path: Path, root: Path, spec: BenchmarkSpec) -> str | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PromotionError(f"cannot inspect canonical path: {path}") from exc
    _require(path.is_symlink(), f"canonical path is not a symlink and will not be overwritten: {path}")
    raw = os.readlink(path)
    target = Path(raw)
    _require(not target.is_absolute() and len(target.parts) == 1, f"canonical symlink is not a managed relative link: {path}")
    name = target.parts[0]
    _require(RUN_ID_RE.fullmatch(name) is not None, f"canonical symlink target has an unsafe run ID: {path}")
    _require(name.startswith(spec.run_prefix), f"canonical symlink targets another model namespace: {path}")
    resolved = (root / target).resolve()
    _require(resolved.parent == root.resolve(), f"canonical symlink escapes its runtime root: {path}")
    _require_real_directory(resolved, "existing canonical target")
    return name


def _canonical_state(audit: RunAudit) -> tuple[str | None, str | None]:
    report_target = _managed_link_target(
        audit.report_canonical,
        runtime.REPORT_ROOT.resolve(),
        audit.spec,
    )
    asset_target = _managed_link_target(
        audit.asset_canonical,
        runtime.ASSET_ROOT.resolve(),
        audit.spec,
    )
    _require(
        (report_target is None) == (asset_target is None),
        "report and asset canonical links are in a partial state",
    )
    if report_target is not None:
        _require(report_target == asset_target, "report and asset canonical links target different runs")
    return report_target, asset_target


def _verify_snapshot(snapshot: Mapping[Path, FileStamp]) -> None:
    for path, expected in snapshot.items():
        _require(_stamp(path) == expected, f"evidence changed after validation: {path}")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _temporary_link(canonical: Path, target: str, token: str) -> Path:
    temporary = canonical.with_name(f".{canonical.name}.promote-{token}")
    _require(not os.path.lexists(temporary), f"temporary promotion path already exists: {temporary}")
    os.symlink(target, temporary)
    return temporary


def _restore_link(canonical: Path, previous: str | None, token: str) -> None:
    if previous is None:
        try:
            canonical.unlink()
        except FileNotFoundError:
            return
        return
    temporary = canonical.with_name(f".{canonical.name}.rollback-{token}")
    temporary.unlink(missing_ok=True)
    os.symlink(previous, temporary)
    os.replace(temporary, canonical)


@contextmanager
def _promotion_lock() -> Iterator[None]:
    lock_path = runtime.REPORT_ROOT.resolve() / ".promote_benchmark_run.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def promote_run(model: str, run_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        audit = audit_run(model, run_id)
        previous_report, _ = _canonical_state(audit)
        return {
            "status": "dry_run_verified",
            "model": audit.spec.model,
            "run_id": run_id,
            "report_canonical": _logical(audit.report_canonical),
            "asset_canonical": _logical(audit.asset_canonical),
            "relative_symlink_target": run_id,
            "previous_run_id": previous_report,
            "validation_snapshot_sha256": audit.validation_snapshot_sha256,
            "asset_files_digest_sha256": audit.asset_files_digest_sha256,
            "checks": dict(audit.checks),
        }

    with _promotion_lock():
        audit = audit_run(model, run_id)
        previous_report, previous_asset = _canonical_state(audit)
        if previous_report == run_id:
            return {
                "status": "already_current",
                "model": audit.spec.model,
                "run_id": run_id,
                "report_canonical": _logical(audit.report_canonical),
                "asset_canonical": _logical(audit.asset_canonical),
                "relative_symlink_target": run_id,
                "validation_snapshot_sha256": audit.validation_snapshot_sha256,
                "asset_files_digest_sha256": audit.asset_files_digest_sha256,
                "checks": dict(audit.checks),
            }

        _verify_snapshot(audit.snapshot)
        token = f"{os.getpid()}-{uuid.uuid4().hex}"
        report_temporary: Path | None = None
        asset_temporary: Path | None = None
        report_replaced = False
        asset_replaced = False
        try:
            report_temporary = _temporary_link(audit.report_canonical, run_id, token)
            asset_temporary = _temporary_link(audit.asset_canonical, run_id, token)
            _require(report_temporary.resolve() == audit.report_run, "temporary report link resolution mismatch")
            _require(asset_temporary.resolve() == audit.asset_run, "temporary asset link resolution mismatch")
            _verify_snapshot(audit.snapshot)

            os.replace(asset_temporary, audit.asset_canonical)
            asset_temporary = None
            asset_replaced = True
            os.replace(report_temporary, audit.report_canonical)
            report_temporary = None
            report_replaced = True
            _fsync_directory(audit.asset_canonical.parent)
            _fsync_directory(audit.report_canonical.parent)

            current_report, current_asset = _canonical_state(audit)
            _require(
                current_report == run_id and current_asset == run_id,
                "canonical links did not resolve to the promoted run",
            )
        except Exception:
            if report_replaced:
                _restore_link(audit.report_canonical, previous_report, token)
            if asset_replaced:
                _restore_link(audit.asset_canonical, previous_asset, token)
            _fsync_directory(audit.asset_canonical.parent)
            _fsync_directory(audit.report_canonical.parent)
            raise
        finally:
            if report_temporary is not None:
                report_temporary.unlink(missing_ok=True)
            if asset_temporary is not None:
                asset_temporary.unlink(missing_ok=True)

        return {
            "status": "promoted",
            "model": audit.spec.model,
            "run_id": run_id,
            "report_canonical": _logical(audit.report_canonical),
            "asset_canonical": _logical(audit.asset_canonical),
            "relative_symlink_target": run_id,
            "previous_run_id": previous_report,
            "validation_snapshot_sha256": audit.validation_snapshot_sha256,
            "asset_files_digest_sha256": audit.asset_files_digest_sha256,
            "checks": dict(audit.checks),
        }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=tuple(SPECS), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = promote_run(args.model, args.run_id, dry_run=bool(args.dry_run))
    except (PromotionError, OSError) as exc:
        print(json.dumps({
            "status": "blocked",
            "model": args.model,
            "run_id": args.run_id,
            "error": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
