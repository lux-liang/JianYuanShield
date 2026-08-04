from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from system.evaluation.runtime import (
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
    resolve_logical_path,
)


MEA_RUN_ID = "mea-4x4-protocol-v1-s20260603-n256"
MEA_EVIDENCE_DIR = REPORT_ROOT / MEA_RUN_ID
MEA_EVIDENCE_NAMES = (
    "dataset_manifest.json",
    "run_config.json",
    "raw_results.csv",
    "progress.json",
    "summary.json",
)
MEA_MODELS = ("LIDMark", "KAD-Net", "SepMark", "WaveGuard")
MEA_IMAGES_PER_CELL = 256
MEA_CHECKPOINT_PATHS = {
    "LIDMark": WEIGHT_ROOT / "lidmark/lfw-id-s20260603-128/checkpoint_epoch_20.pth",
    "KAD-Net": WEIGHT_ROOT / "KAD-Net/ST/128/models/EC_100.pth",
    "SepMark": (
        WEIGHT_ROOT
        / "MEA/models/SepMark/results/FullFineTuningWithOnlyMessage/models/EC_108.pth"
    ),
    "WaveGuard": (
        WEIGHT_ROOT
        / "MEA/models/WaveGuard/exp_highpass/2025.07.24-20.10.50/model_state_16.pth"
    ),
}
MEA_IMPLEMENTATION_PATHS = (
    Path("scripts/run_mea_matrix_4x4.py"),
    Path("system/evaluation/adapters/base.py"),
    Path("system/evaluation/adapters/multi_embedding.py"),
    Path("system/evaluation/adapters/lidmark_adapter.py"),
    Path("system/evaluation/adapters/kadnet_adapter.py"),
    Path("system/evaluation/adapters/sepmark_adapter.py"),
    Path("system/evaluation/adapters/waveguard_adapter.py"),
    Path("system/evaluation/metrics.py"),
    Path("system/evaluation/protocol.py"),
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _json_exact_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(
            left,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ) == json.dumps(
            right,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False


def _resolve_reference(reference: Any, evidence_dir: Path) -> Path | None:
    if not isinstance(reference, str) or not reference:
        return None
    raw = Path(reference)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    candidates = [
        resolve_logical_path(raw),
        (evidence_dir / raw).resolve(),
        (evidence_dir.parent / raw).resolve(),
    ]
    return next((candidate for candidate in candidates if candidate and candidate.is_file()), None)


def _coverage_complete(value: Any, expected_rows: int) -> bool:
    if not isinstance(value, dict):
        return False
    expected = {
        "expected_rows": expected_rows,
        "observed_unique_expected_rows": expected_rows,
        "valid_rows": expected_rows,
        "error_rows": 0,
        "missing_rows": 0,
        "duplicate_rows": 0,
        "unexpected_rows": 0,
        "expected_cells": 16,
        "complete_cells": 16,
    }
    return all(
        isinstance(value.get(field), int)
        and not isinstance(value.get(field), bool)
        and value[field] == expected_value
        for field, expected_value in expected.items()
    )


def validate_mea_matrix_evidence(
    directory: Path = MEA_EVIDENCE_DIR,
    *,
    images_per_cell: int = MEA_IMAGES_PER_CELL,
    require_cuda_determinism: bool = True,
    require_signature: bool = False,
    enforce_canonical_checkpoints: bool = True,
) -> dict[str, Any]:
    """Validate the exact ordered 4x4 MEA evidence matrix and its hash closure."""

    directory = directory.expanduser().resolve()
    errors: list[str] = []
    try:
        actual_names = {path.name for path in directory.iterdir()}
        if actual_names != set(MEA_EVIDENCE_NAMES):
            raise ValueError("MEA evidence directory membership is not exact")
        paths = {name: directory / name for name in MEA_EVIDENCE_NAMES}
        if any(path.is_symlink() or not path.is_file() for path in paths.values()):
            raise ValueError("MEA evidence members must be regular files")
        identities_before = {
            name: (
                path.stat().st_dev,
                path.stat().st_ino,
                path.stat().st_size,
                path.stat().st_mtime_ns,
                path.stat().st_ctime_ns,
            )
            for name, path in paths.items()
        }

        manifest = _json_object(paths["dataset_manifest.json"])
        config = _json_object(paths["run_config.json"])
        progress = _json_object(paths["progress.json"])
        summary = _json_object(paths["summary.json"])
        from scripts import run_mea_matrix_4x4 as runner

        for label, payload in (
            ("dataset_manifest", manifest),
            ("run_config", config),
            ("progress", progress),
            ("summary", summary),
        ):
            runner.assert_no_absolute_paths(payload, label)

        expected_rows = 16 * images_per_cell
        files = manifest.get("files")
        if (
            manifest.get("schema_version") != runner.MANIFEST_SCHEMA
            or manifest.get("selection_method")
            != "lowest_sha256_content_score_without_replacement"
            or manifest.get("selection_domain") != runner.SAMPLE_DOMAIN
            or not isinstance(manifest.get("dataset_root"), str)
            or not manifest["dataset_root"]
            or Path(manifest["dataset_root"]).is_absolute()
            or ".." in Path(manifest["dataset_root"]).parts
            or manifest.get("seed") != 20260603
            or manifest.get("sample_count") != images_per_cell
            or not isinstance(manifest.get("candidate_count"), int)
            or isinstance(manifest.get("candidate_count"), bool)
            or manifest["candidate_count"] < images_per_cell
            or not _is_sha256(manifest.get("candidate_digest_sha256"))
            or not isinstance(files, list)
            or len(files) != images_per_cell
            or manifest.get("files_digest_sha256") != runner.canonical_sha256(files)
        ):
            raise ValueError("MEA dataset manifest contract mismatch")
        image_ids: set[str] = set()
        source_paths: set[str] = set()
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                raise ValueError("MEA dataset item is not an object")
            image_id = item.get("image_id")
            source_path = item.get("path")
            if (
                item.get("sample_index") != index
                or isinstance(item.get("sample_index"), bool)
                or not isinstance(image_id, str)
                or not _is_sha256(image_id)
                or not isinstance(source_path, str)
                or not source_path
                or Path(source_path).is_absolute()
                or ".." in Path(source_path).parts
                or image_id in image_ids
                or source_path in source_paths
                or any(
                    not _is_sha256(item.get(field))
                    for field in (
                        "file_sha256",
                        "canonical_rgb_sha256",
                        "selection_score_sha256",
                    )
                )
                or not isinstance(item.get("size_bytes"), int)
                or isinstance(item.get("size_bytes"), bool)
                or item["size_bytes"] <= 0
                or not isinstance(item.get("width"), int)
                or isinstance(item.get("width"), bool)
                or item["width"] <= 0
                or not isinstance(item.get("height"), int)
                or isinstance(item.get("height"), bool)
                or item["height"] <= 0
                or item.get("color_space") != "RGB"
                or item.get("dtype") != "uint8"
            ):
                raise ValueError(f"MEA dataset item contract mismatch: {index}")
            expected_selection_score = runner.sha256_bytes(
                (
                    f"{runner.SAMPLE_DOMAIN}\0{manifest['seed']}\0"
                    f"{source_path}\0{item['file_sha256']}"
                ).encode("utf-8")
            )
            expected_image_id = runner.sha256_bytes(
                (
                    f"{runner.IMAGE_ID_DOMAIN}\0{source_path}\0"
                    f"{item['file_sha256']}\0{item['canonical_rgb_sha256']}"
                ).encode("utf-8")
            )
            if (
                item["selection_score_sha256"] != expected_selection_score
                or image_id != expected_image_id
            ):
                raise ValueError(f"MEA dataset digest semantics mismatch: {index}")
            image_ids.add(image_id)
            source_paths.add(source_path)

        manifest_sha = _sha256_file(paths["dataset_manifest.json"])
        config_sha = _sha256_file(paths["run_config.json"])
        raw_sha = _sha256_file(paths["raw_results.csv"])
        matrix_contract = config.get("matrix")
        if (
            config.get("schema_version") != runner.CONFIG_SCHEMA
            or not isinstance(matrix_contract, dict)
            or matrix_contract.get("ordered_models") != list(MEA_MODELS)
            or matrix_contract.get("expected_model_count") != 4
            or matrix_contract.get("expected_cell_count") != 16
            or matrix_contract.get("images_per_cell") != images_per_cell
            or matrix_contract.get("expected_row_count") != expected_rows
            or config.get("dataset_manifest")
            != {"path": "dataset_manifest.json", "sha256": manifest_sha}
            or config.get("raw_results", {}).get("path") != "raw_results.csv"
            or config.get("raw_results", {}).get("schema_version") != runner.RAW_SCHEMA
            or config.get("raw_results", {}).get("fields") != runner.RAW_FIELDS
        ):
            raise ValueError("MEA run config contract mismatch")

        implementation = config.get("implementation")
        if implementation != runner.implementation_manifest():
            raise ValueError("MEA implementation manifest drift")
        determinism = config.get("determinism")
        if (
            not isinstance(determinism, dict)
            or determinism.get("verified") is not True
            or determinism.get("errors") != []
            or determinism.get("message_rng") != "stateless_SHAKE256"
            or determinism.get("sample_selection") != "content_addressed_SHA256"
        ):
            raise ValueError("MEA determinism contract mismatch")
        if require_cuda_determinism and (
            determinism.get("runtime_configuration") != "applied"
            or determinism.get("torch_deterministic_algorithms") is not True
            or determinism.get("cuda_available") is not True
            or not str(determinism.get("requested_device", "")).startswith("cuda")
        ):
            raise ValueError("MEA formal CUDA determinism was not verified")

        protocol_record = config.get("protocol")
        if not isinstance(protocol_record, dict):
            raise ValueError("MEA protocol record is missing")
        protocol_path = _resolve_reference(protocol_record.get("path"), directory)
        if protocol_path is None:
            raise ValueError("MEA protocol path is unresolved")
        protocol = _json_object(protocol_path)
        protocol_sha = _sha256_file(protocol_path)
        if (
            protocol_record.get("schema_version") != "evaluation_protocol.v1"
            or protocol_record.get("sha256") != protocol_sha
            or protocol_record.get("seed") != protocol.get("seed")
            or protocol_record.get("success_threshold")
            != protocol.get("success_threshold")
            or not _json_exact_equal(summary.get("protocol"), protocol_record)
        ):
            raise ValueError("MEA protocol hash or semantics drift")

        checkpoints = config.get("models")
        if (
            not isinstance(checkpoints, dict)
            or set(checkpoints) != set(MEA_MODELS)
            or not _json_exact_equal(summary.get("checkpoint_evidence"), checkpoints)
        ):
            raise ValueError("MEA checkpoint evidence membership mismatch")
        for model in MEA_MODELS:
            record = checkpoints[model]
            checkpoint = _resolve_reference(record.get("checkpoint"), directory)
            if (
                not isinstance(record, dict)
                or record.get("status") != "available"
                or record.get("integrity_verified") is not True
                or record.get("checkpoint_sha256")
                != record.get("expected_checkpoint_sha256")
                or checkpoint is None
                or (
                    enforce_canonical_checkpoints
                    and checkpoint.resolve() != MEA_CHECKPOINT_PATHS[model].resolve()
                )
                or _sha256_file(checkpoint) != record.get("checkpoint_sha256")
                or checkpoint.stat().st_size != record.get("checkpoint_size_bytes")
                or not isinstance(record.get("message_length"), int)
                or record["message_length"] <= 0
                or not isinstance(record.get("primary_decoder"), str)
                or not record["primary_decoder"]
            ):
                raise ValueError(f"MEA checkpoint evidence mismatch: {model}")

        with paths["raw_results.csv"].open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != runner.RAW_FIELDS:
                raise ValueError("MEA raw CSV header mismatch")
            rows = [dict(row) for row in reader]
        if len(rows) != expected_rows:
            raise ValueError("MEA raw CSV row count mismatch")
        manifest_by_id = {str(item["image_id"]): item for item in files}
        for row in rows:
            runner.validate_raw_row(
                row,
                manifest_by_id=manifest_by_id,
                protocol=protocol,
                protocol_sha=protocol_sha,
                manifest_sha=manifest_sha,
                config_sha=config_sha,
                checkpoints=checkpoints,
            )
        coverage, matrix = runner.coverage_and_matrix(rows, manifest)
        if not _coverage_complete(coverage, expected_rows):
            raise ValueError("MEA raw matrix coverage is incomplete")
        expected_cells = {
            cell["cell_id"]: {
                key: value
                for key, value in cell.items()
                if key != "aggregates"
            }
            for source_cells in matrix.values()
            for cell in source_cells.values()
        }
        if (
            progress.get("schema_version") != runner.PROGRESS_SCHEMA
            or progress.get("status") != "complete"
            or not isinstance(progress.get("updated_at"), int)
            or isinstance(progress.get("updated_at"), bool)
            or progress["updated_at"] <= 0
            or not _json_exact_equal(progress.get("coverage"), coverage)
            or not _json_exact_equal(progress.get("cells"), expected_cells)
            or not _json_exact_equal(
                progress.get("raw_results"),
                {"path": "raw_results.csv", "sha256": raw_sha},
            )
        ):
            raise ValueError("MEA progress does not match raw evidence")
        postflight = summary.get("postflight_input_audit")
        if (
            summary.get("schema_version") != runner.SUMMARY_SCHEMA
            or summary.get("status") != "complete"
            or summary.get("evidence_status") != "complete_unsigned"
            or summary.get("claim_valid") is not False
            or summary.get("claim_status") != "review_and_signature_required"
            or not isinstance(summary.get("generated_at"), int)
            or isinstance(summary.get("generated_at"), bool)
            or summary["generated_at"] <= 0
            or summary.get("models") != list(MEA_MODELS)
            or summary.get("model_count") != 4
            or summary.get("images_per_cell") != images_per_cell
            or not _json_exact_equal(summary.get("coverage"), coverage)
            or not _json_exact_equal(summary.get("matrix"), matrix)
            or summary.get("markdown_table") != runner.markdown_table(matrix)
            or summary.get("preflight_errors") != []
            or not isinstance(postflight, dict)
            or postflight.get("verified") is not True
            or postflight.get("errors") != []
            or any(
                postflight.get(field) is not True
                for field in (
                    "checkpoint_sha256_unchanged",
                    "dataset_files_unchanged",
                    "implementation_sha256_unchanged",
                    "protocol_sha256_unchanged",
                )
            )
            or not _json_exact_equal(
                summary.get("artifacts"),
                {
                    "dataset_manifest": {
                        "path": "dataset_manifest.json",
                        "sha256": manifest_sha,
                    },
                    "run_config": {
                        "path": "run_config.json",
                        "sha256": config_sha,
                    },
                    "raw_results": {
                        "path": "raw_results.csv",
                        "sha256": raw_sha,
                    },
                },
            )
        ):
            raise ValueError("MEA summary does not match validated raw evidence")
        elapsed = summary.get("elapsed_seconds")
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed))
            or float(elapsed) < 0
        ):
            raise ValueError("MEA elapsed time is invalid")

        identities_after = {
            name: (
                path.stat().st_dev,
                path.stat().st_ino,
                path.stat().st_size,
                path.stat().st_mtime_ns,
                path.stat().st_ctime_ns,
            )
            for name, path in paths.items()
        }
        if identities_after != identities_before:
            raise ValueError("MEA evidence changed during validation")

        signature: dict[str, Any] | None = None
        if require_signature:
            from .signing import MANIFEST_PATH, sha256_file, verify_evidence_bundle

            signature = verify_evidence_bundle()
            if (
                signature.get("verified") is not True
                or signature.get("profile") not in {"release-core", "release"}
                or signature.get("signer_pinned") is not True
            ):
                raise ValueError("MEA evidence signature is not trusted")
            signed_manifest_bytes = MANIFEST_PATH.read_bytes()
            if hashlib.sha256(signed_manifest_bytes).hexdigest() != signature.get(
                "manifest_sha256"
            ):
                raise ValueError("MEA signature manifest changed during validation")
            signed_manifest = json.loads(
                signed_manifest_bytes.decode("utf-8"),
                parse_constant=_reject_nonfinite,
            )
            if not isinstance(signed_manifest, dict):
                raise ValueError("MEA signature manifest is not an object")
            covered = {
                (item.get("path"), item.get("sha256"))
                for item in signed_manifest.get("files", [])
                if isinstance(item, dict)
            }
            expected = {
                (logical_path(path), sha256_file(path)) for path in paths.values()
            }
            if not expected.issubset(covered):
                raise ValueError("MEA evidence is not covered by the release signature")

        return {
            "schema_version": "mea-matrix-evidence-status.v1",
            "valid": True,
            "status": "verified" if require_signature else "validated_unsigned",
            "run_id": directory.name,
            "images_per_cell": images_per_cell,
            "cell_count": 16,
            "row_count": expected_rows,
            "evidence_files": {
                name: {"path": logical_path(path), "sha256": _sha256_file(path)}
                for name, path in paths.items()
            },
            "signature": signature,
            "errors": [],
        }
    except Exception as exc:
        errors.append(f"{exc.__class__.__name__}:{exc}")
        return {
            "schema_version": "mea-matrix-evidence-status.v1",
            "valid": False,
            "status": "review_required",
            "run_id": directory.name,
            "images_per_cell": images_per_cell,
            "cell_count": 16,
            "row_count": 16 * images_per_cell,
            "errors": errors,
        }
