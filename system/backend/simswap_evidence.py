from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Mapping

from system.evaluation.runtime import (
    ASSET_ROOT,
    DATA_ROOT,
    MODEL_SOURCE_ROOT,
    PROJECT_ROOT,
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
)


SIMSWAP_RUN_ID = "simswap-lfw-robustness-n256-s20260603"
SIMSWAP_EVIDENCE_DIR = REPORT_ROOT / SIMSWAP_RUN_ID
SIMSWAP_ASSET_DIR = ASSET_ROOT / SIMSWAP_RUN_ID
SIMSWAP_EVIDENCE_NAMES = (
    "pair_manifest.json",
    "message_registry.json",
    "run_config.json",
    "identity_embeddings.csv",
    "results.csv",
    "progress.json",
    "assets_manifest.json",
    "summary.json",
)
SIMSWAP_MODELS = ("LIDMark", "KAD-Net", "SepMark", "WaveGuard")
SIMSWAP_NUM_PAIRS = 256
SIMSWAP_CALIBRATION_PAIRS = 64
SIMSWAP_ARTIFACT_LIMIT = 16
SIMSWAP_MESSAGE_LENGTHS = {
    "LIDMark": 16,
    "KAD-Net": 30,
    "SepMark": 128,
    "WaveGuard": 30,
}
SIMSWAP_PRIMARY_DECODERS = {
    "LIDMark": "FHD_id_head",
    "KAD-Net": "ST_Decoder_C",
    "SepMark": "decoder_C",
    "WaveGuard": "tracer",
}
SIMSWAP_WATERMARK_CHECKPOINT_PATHS = {
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
SIMSWAP_WATERMARK_CHECKPOINT_SHA256 = {
    "LIDMark": "762369c8e4e881c8d72fde08ebaf7fea3fd7a26354aa344aed288cb780ad3436",
    "KAD-Net": "3b298493ae3510e73fc85a5fcae2f470d8e6892e9e058aa9cca3a0d8d35f5079",
    "SepMark": "433992186176483bd92341fd033cf3c2fa2682f159aea7fe4542c4a6b88b5e55",
    "WaveGuard": "cd093467a834cde47a0abed1d90a3ed62120092a2affcbcb1ed2f7d72b346377",
}
SIMSWAP_ENGINE_ARTIFACT_PATHS = {
    "checkpoint_archive": WEIGHT_ROOT / "SimSwap/downloads/checkpoints.zip",
    "generator_checkpoint": WEIGHT_ROOT / "SimSwap/checkpoints/people/latest_net_G.pth",
    "arcface_checkpoint": WEIGHT_ROOT / "SimSwap/downloads/arcface_checkpoint.tar",
}
SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE = {
    "schema_version": "simswap-identity-migration-evidence-scope.v1",
    "scope": "pipeline_internal_identity_migration_evidence",
    "method": "source_cosine_greater_than_target_cosine",
    "arcface_checkpoint_path": "weights/SimSwap/downloads/arcface_checkpoint.tar",
    "arcface_checkpoint_sha256": (
        "52ea5ce4902017b77a2bb811dd9a82f57dee3883e06c18a42d288437263c7a20"
    ),
    "same_arcface_checkpoint_used_for_generation_and_measurement": True,
    "independent_identity_verifier": False,
}
SIMSWAP_IMPLEMENTATION_PATHS = (
    Path("configs/simswap_lfw_robustness.v1.json"),
    Path("system/scripts/run_simswap_lfw_robustness.py"),
    Path("system/evaluation/identity.py"),
    Path("system/evaluation/runtime.py"),
    Path("system/evaluation/adapters/__init__.py"),
    Path("system/evaluation/adapters/base.py"),
    Path("system/evaluation/adapters/lidmark_adapter.py"),
    Path("system/evaluation/adapters/kadnet_adapter.py"),
    Path("system/evaluation/adapters/sepmark_adapter.py"),
    Path("system/evaluation/adapters/waveguard_adapter.py"),
    Path("system/backend/model_adapters.py"),
    Path("tests/test_simswap_lfw_robustness.py"),
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ENGINE_KEYS = {
    "engine",
    "mode",
    "source_path",
    "source_commit",
    "source_tree",
    "source_tracked_file_count",
    "source_tracked_files_sha256",
    "checkpoint_archive_path",
    "checkpoint_archive_sha256",
    "generator_archive_member",
    "generator_checkpoint_path",
    "generator_checkpoint_sha256",
    "arcface_checkpoint_path",
    "arcface_checkpoint_sha256",
    "generator_load_policy",
    "arcface_load_policy",
    "input_size",
    "identity_embedding_dim",
}


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


def _file_identity(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _json_exact_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(
            left,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) == json.dumps(
            right,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False


def _conditioned_registered_positive_metrics(
    *,
    pairs: list[dict[str, Any]],
    result_rows: Mapping[tuple[str, str], Mapping[str, str]],
    recomputed_summary: Mapping[str, Any],
    runner: Any,
    models: tuple[str, ...] = SIMSWAP_MODELS,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Recompute holdout TAR within pipeline-internal migration subsets."""

    holdout_pair_ids = [
        str(pair["pair_id"]) for pair in pairs if pair.get("split") == "holdout"
    ]
    if not holdout_pair_ids:
        raise ValueError("SimSwap conditioned migration holdout is empty")

    def interval(rows: list[Mapping[str, str]], threshold: float) -> dict[str, Any]:
        successes = sum(
            float(row["registered_positive_score"]) >= threshold for row in rows
        )
        if not rows:
            return {
                "successes": 0,
                "total": 0,
                "estimate": None,
                "wilson_95_low": None,
                "wilson_95_high": None,
            }
        return runner.wilson_interval(successes, len(rows))

    conditioned: dict[str, dict[str, dict[str, Any]]] = {}
    summary_models = recomputed_summary.get("model_results")
    if not isinstance(summary_models, Mapping):
        raise ValueError("SimSwap recomputed model summary is missing")
    for model in models:
        model_summary = summary_models.get(model)
        if not isinstance(model_summary, Mapping):
            raise ValueError(f"SimSwap recomputed model summary is missing: {model}")
        calibration = model_summary.get("calibration")
        if not isinstance(calibration, Mapping):
            raise ValueError(f"SimSwap calibration summary is missing: {model}")
        threshold_raw = calibration.get("threshold")
        if isinstance(threshold_raw, bool) or not isinstance(threshold_raw, (int, float)):
            raise ValueError(f"SimSwap calibration threshold is invalid: {model}")
        threshold = float(threshold_raw)
        rows = [result_rows[(pair_id, model)] for pair_id in holdout_pair_ids]
        clean_migrated = [
            row for row in rows if row["arcface_clean_identity_migrated"] == "1"
        ]
        clean_and_watermarked_migrated = [
            row
            for row in clean_migrated
            if row["arcface_watermarked_identity_migrated"] == "1"
        ]
        conditioned[model] = {
            "clean_swap_migrated": interval(clean_migrated, threshold),
            "clean_and_watermarked_swap_migrated": interval(
                clean_and_watermarked_migrated,
                threshold,
            ),
        }
    return conditioned


def _asset_relative_names(artifact_limit: int) -> tuple[str, ...]:
    names: list[str] = []
    for index in range(1, artifact_limit + 1):
        directory = f"pair_{index:05d}"
        names.extend(
            f"{directory}/{name}"
            for name in ("source.png", "target.png", "swapped_clean.png")
        )
        for model in SIMSWAP_MODELS:
            slug = model.lower().replace("-", "_")
            names.extend(
                (
                    f"{directory}/{slug}_target_watermarked.png",
                    f"{directory}/{slug}_swapped_watermarked.png",
                )
            )
    return tuple(sorted(names))


SIMSWAP_ASSET_RELATIVE_NAMES = _asset_relative_names(SIMSWAP_ARTIFACT_LIMIT)
SIMSWAP_ASSET_PATHS = tuple(
    SIMSWAP_ASSET_DIR / name for name in SIMSWAP_ASSET_RELATIVE_NAMES
)


def _validate_asset_manifest(
    payload: dict[str, Any],
    asset_directory: Path,
    *,
    artifact_limit: int,
    runner: Any,
) -> list[Path]:
    if not asset_directory.is_dir() or asset_directory.is_symlink():
        raise ValueError("SimSwap asset directory must be a regular directory")
    relative_names = _asset_relative_names(artifact_limit)
    expected_paths = [asset_directory / name for name in relative_names]
    actual_files = sorted(
        (
            path
            for path in asset_directory.rglob("*")
            if path.is_file() or path.is_symlink()
        ),
        key=lambda path: path.relative_to(asset_directory).as_posix(),
    )
    if any(path.is_symlink() or not path.is_file() for path in actual_files):
        raise ValueError("SimSwap visual assets must be regular files")
    if [path.relative_to(asset_directory).as_posix() for path in actual_files] != list(
        relative_names
    ):
        raise ValueError("SimSwap visual asset membership is not exact")
    records = [
        {
            "path": path.relative_to(asset_directory).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in expected_paths
    ]
    expected = {
        "schema_version": "simswap-robustness-assets.v1",
        "asset_root": logical_path(asset_directory),
        "file_count": len(records),
        "files": records,
        "files_sha256": runner._canonical_hash(records),
    }
    if not _json_exact_equal(payload, expected):
        raise ValueError("SimSwap visual asset manifest mismatch")
    return expected_paths


def _validate_formal_engine(engine: dict[str, Any], runner: Any) -> list[Path]:
    source = (MODEL_SOURCE_ROOT / "SimSwap").resolve()
    archive = SIMSWAP_ENGINE_ARTIFACT_PATHS["checkpoint_archive"].resolve()
    generator = SIMSWAP_ENGINE_ARTIFACT_PATHS["generator_checkpoint"].resolve()
    arcface = SIMSWAP_ENGINE_ARTIFACT_PATHS["arcface_checkpoint"].resolve()
    if any(path.is_symlink() or not path.is_file() for path in (archive, generator, arcface)):
        raise ValueError("SimSwap official engine artifacts must be regular files")
    if not source.is_dir() or source.is_symlink():
        raise ValueError("SimSwap official source checkout is missing")
    commit = runner._run_git(source, "rev-parse", "HEAD")
    tree = runner._run_git(source, "rev-parse", "HEAD^{tree}")
    dirty = runner._run_git(source, "status", "--porcelain", "--untracked-files=no")
    entries, tracked_digest = runner._tracked_source_manifest(source)
    expected = {
        "engine": "SimSwap",
        "mode": "official_release_checkpoint",
        "source_path": logical_path(source),
        "source_commit": commit,
        "source_tree": tree,
        "source_tracked_file_count": len(entries),
        "source_tracked_files_sha256": tracked_digest,
        "checkpoint_archive_path": logical_path(archive),
        "checkpoint_archive_sha256": _sha256_file(archive),
        "generator_archive_member": runner.GENERATOR_ARCHIVE_MEMBER,
        "generator_checkpoint_path": logical_path(generator),
        "generator_checkpoint_sha256": _sha256_file(generator),
        "arcface_checkpoint_path": logical_path(arcface),
        "arcface_checkpoint_sha256": _sha256_file(arcface),
        "generator_load_policy": "weights_only_true_after_exact_sha256",
        "arcface_load_policy": (
            "weights_only_false_after_exact_official_sha256_allowlist"
        ),
        "input_size": 224,
        "identity_embedding_dim": 512,
    }
    if (
        commit != runner.SIMSWAP_COMMIT
        or tree != runner.SIMSWAP_TREE
        or dirty
        or tracked_digest != runner.SIMSWAP_TRACKED_FILES_SHA256
        or expected["checkpoint_archive_sha256"] != runner.CHECKPOINT_ARCHIVE_SHA256
        or expected["generator_checkpoint_sha256"] != runner.GENERATOR_SHA256
        or expected["arcface_checkpoint_sha256"] != runner.ARCFACE_SHA256
        or runner._zip_member_sha256(archive, runner.GENERATOR_ARCHIVE_MEMBER)
        != runner.GENERATOR_SHA256
        or not _json_exact_equal(engine, expected)
    ):
        raise ValueError("SimSwap official engine provenance mismatch")
    return [archive, generator, arcface]


def validate_simswap_lfw_evidence(
    directory: Path = SIMSWAP_EVIDENCE_DIR,
    *,
    asset_directory: Path = SIMSWAP_ASSET_DIR,
    dataset_root: Path | None = None,
    checkpoint_paths: Mapping[str, Path] | None = None,
    num_pairs: int = SIMSWAP_NUM_PAIRS,
    calibration_pairs: int = SIMSWAP_CALIBRATION_PAIRS,
    artifact_limit: int = SIMSWAP_ARTIFACT_LIMIT,
    require_signature: bool = False,
    enforce_canonical_runtime: bool = True,
) -> dict[str, Any]:
    """Validate the fixed real SimSwap/LFW n256 evidence and its full hash closure."""

    directory = directory.expanduser().resolve()
    asset_directory = asset_directory.expanduser().resolve()
    dataset_root = (
        DATA_ROOT / "lfw/lfw" if dataset_root is None else dataset_root
    ).expanduser().resolve()
    selected_checkpoints = {
        model: Path(path).expanduser().resolve()
        for model, path in (
            SIMSWAP_WATERMARK_CHECKPOINT_PATHS
            if checkpoint_paths is None
            else checkpoint_paths
        ).items()
    }
    errors: list[str] = []
    try:
        if set(selected_checkpoints) != set(SIMSWAP_MODELS):
            raise ValueError("SimSwap watermark checkpoint membership mismatch")
        actual_names = {path.name for path in directory.iterdir()}
        if actual_names != set(SIMSWAP_EVIDENCE_NAMES):
            raise ValueError("SimSwap evidence directory membership is not exact")
        paths = {name: directory / name for name in SIMSWAP_EVIDENCE_NAMES}
        if any(path.is_symlink() or not path.is_file() for path in paths.values()):
            raise ValueError("SimSwap evidence members must be regular files")
        evidence_identities = {
            path: _file_identity(path) for path in paths.values()
        }

        pair_manifest = _json_object(paths["pair_manifest.json"])
        registry_payload = _json_object(paths["message_registry.json"])
        run_config = _json_object(paths["run_config.json"])
        progress = _json_object(paths["progress.json"])
        assets_manifest = _json_object(paths["assets_manifest.json"])
        summary = _json_object(paths["summary.json"])

        from system.scripts import run_simswap_lfw_robustness as runner

        for label, payload in (
            ("pair_manifest", pair_manifest),
            ("message_registry", registry_payload),
            ("run_config", run_config),
            ("progress", progress),
            ("assets_manifest", assets_manifest),
            ("summary", summary),
        ):
            runner._assert_no_absolute_paths(payload, label)

        if enforce_canonical_runtime:
            if directory != SIMSWAP_EVIDENCE_DIR.resolve():
                raise ValueError("SimSwap evidence directory is not the canonical n256 path")
            if asset_directory != SIMSWAP_ASSET_DIR.resolve():
                raise ValueError("SimSwap asset directory is not the canonical n256 path")
            if dataset_root != runner.DEFAULT_IMAGE_ROOT.resolve():
                raise ValueError("SimSwap dataset root is not the canonical LFW path")
            if num_pairs != 256 or calibration_pairs != 64 or artifact_limit != 16:
                raise ValueError("SimSwap formal n256 scope drift")

        protocol = runner.load_protocol()
        expected_pair_manifest = runner.select_content_addressed_pairs(
            dataset_root,
            num_pairs=num_pairs,
            calibration_pairs=calibration_pairs,
            seed=20260603,
        )
        if not _json_exact_equal(pair_manifest, expected_pair_manifest):
            raise ValueError("SimSwap pair manifest does not match the frozen selector")
        pairs = pair_manifest["pairs"]
        selected_dataset_paths = [
            dataset_root / item["path"] for item in pair_manifest["selected_files"]
        ]
        if any(path.is_symlink() or not path.is_file() for path in selected_dataset_paths):
            raise ValueError("SimSwap selected dataset members must be regular files")

        checkpoint_records: list[dict[str, Any]] = []
        binding_objects: dict[str, SimpleNamespace] = {}
        for model in SIMSWAP_MODELS:
            checkpoint = selected_checkpoints[model]
            if checkpoint.is_symlink() or not checkpoint.is_file():
                raise ValueError(f"SimSwap watermark checkpoint missing: {model}")
            checkpoint_sha = _sha256_file(checkpoint)
            if enforce_canonical_runtime and (
                checkpoint != SIMSWAP_WATERMARK_CHECKPOINT_PATHS[model].resolve()
                or checkpoint_sha != SIMSWAP_WATERMARK_CHECKPOINT_SHA256[model]
            ):
                raise ValueError(f"SimSwap watermark checkpoint mismatch: {model}")
            record = {
                "model": model,
                "checkpoint": logical_path(checkpoint),
                "checkpoint_sha256": checkpoint_sha,
                "message_length": SIMSWAP_MESSAGE_LENGTHS[model],
                "primary_decoder": SIMSWAP_PRIMARY_DECODERS[model],
            }
            checkpoint_records.append(record)
            binding_objects[model] = SimpleNamespace(
                checkpoint_path=checkpoint,
                checkpoint_sha256=checkpoint_sha,
                message_length=record["message_length"],
                primary_decoder=record["primary_decoder"],
            )

        engine = runner._validate_engine_provenance(run_config.get("engine"))
        if set(engine) != _ENGINE_KEYS:
            raise ValueError("SimSwap engine provenance schema mismatch")
        engine_artifacts: list[Path] = []
        if enforce_canonical_runtime:
            engine_artifacts = _validate_formal_engine(engine, runner)

        expected_registry = runner.build_message_registry(
            pairs,
            binding_objects,
            seed=20260603,
        )
        if not _json_exact_equal(registry_payload, expected_registry):
            raise ValueError("SimSwap registered-message derivation mismatch")
        registry = runner._registry_index(registry_payload)

        protocol_sha = _sha256_file(runner.PROTOCOL_PATH)
        pair_manifest_sha = _sha256_file(paths["pair_manifest.json"])
        registry_sha = _sha256_file(paths["message_registry.json"])
        device = run_config.get("device")
        if enforce_canonical_runtime and device != "cuda:0":
            raise ValueError("SimSwap formal evidence was not executed on cuda:0")
        expected_config = {
            "schema_version": "simswap-lfw-robustness-run.v1",
            "protocol_path": logical_path(runner.PROTOCOL_PATH),
            "protocol_sha256": protocol_sha,
            "protocol_id": protocol["protocol_id"],
            "seed": 20260603,
            "num_pairs": num_pairs,
            "calibration_pairs": calibration_pairs,
            "holdout_pairs": num_pairs - calibration_pairs,
            "device": device,
            "artifact_limit": artifact_limit,
            "models": list(SIMSWAP_MODELS),
            "dataset_root": logical_path(dataset_root),
            "pair_manifest_path": logical_path(paths["pair_manifest.json"]),
            "pair_manifest_sha256": pair_manifest_sha,
            "message_registry_path": logical_path(paths["message_registry.json"]),
            "message_registry_sha256": registry_sha,
            "engine": engine,
            "watermarks": checkpoint_records,
            "implementation_files": runner._implementation_manifest(),
            "result_schema": runner.RESULT_FIELDS,
            "identity_embedding_schema": runner.IDENTITY_FIELDS,
            "determinism": {
                "numpy_seed": 20260603,
                "torch_seed": 20260603,
                "torch_deterministic_algorithms": True,
                "cudnn_benchmark": False,
                "cudnn_deterministic": True,
                "cublas_workspace_config": ":4096:8",
            },
        }
        if not _json_exact_equal(run_config, expected_config):
            raise ValueError("SimSwap run configuration contract mismatch")

        asset_paths = _validate_asset_manifest(
            assets_manifest,
            asset_directory,
            artifact_limit=artifact_limit,
            runner=runner,
        )
        expected_identity_keys = runner._identity_expected_keys(pairs)
        identity_rows = runner.load_identity_rows(
            paths["identity_embeddings.csv"],
            expected_identity_keys,
            expected_dim=512,
        )
        if set(identity_rows) != expected_identity_keys:
            raise ValueError("SimSwap ArcFace embedding coverage is incomplete")
        if runner._load_csv(paths["identity_embeddings.csv"], runner.IDENTITY_FIELDS) != list(
            runner._ordered_identity_rows(identity_rows, pairs)
        ):
            raise ValueError("SimSwap ArcFace embedding row order is not canonical")

        result_rows = runner.load_result_rows(
            paths["results.csv"],
            pairs=pairs,
            registry=registry,
            identities=identity_rows,
            binding_lengths=SIMSWAP_MESSAGE_LENGTHS,
            primary_decoders=SIMSWAP_PRIMARY_DECODERS,
            seed=20260603,
        )
        expected_result_keys = runner._expected_result_keys(pairs)
        if (
            set(result_rows) != expected_result_keys
            or any(row["error"] for row in result_rows.values())
        ):
            raise ValueError("SimSwap result coverage is incomplete")
        if runner._load_csv(paths["results.csv"], runner.RESULT_FIELDS) != list(
            runner._ordered_result_rows(result_rows, pairs)
        ):
            raise ValueError("SimSwap result row order is not canonical")

        summary_args = SimpleNamespace(
            num_pairs=num_pairs,
            calibration_pairs=calibration_pairs,
            seed=20260603,
        )
        expected_summary = runner._complete_summary(
            args=summary_args,
            protocol=protocol,
            engine_provenance=engine,
            bindings=binding_objects,
            pairs=pairs,
            results=result_rows,
            results_path=paths["results.csv"],
            identities_path=paths["identity_embeddings.csv"],
            pair_manifest_path=paths["pair_manifest.json"],
            registry_path=paths["message_registry.json"],
            run_config_path=paths["run_config.json"],
            asset_manifest_path=paths["assets_manifest.json"],
        )
        if not _json_exact_equal(summary, expected_summary):
            raise ValueError("SimSwap summary does not match recomputed raw evidence")
        conditioned_registered_positive = _conditioned_registered_positive_metrics(
            pairs=pairs,
            result_rows=result_rows,
            recomputed_summary=expected_summary,
            runner=runner,
        )
        identity_migration_evidence_scope = {
            **SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE,
            "arcface_checkpoint_path": engine["arcface_checkpoint_path"],
            "arcface_checkpoint_sha256": engine["arcface_checkpoint_sha256"],
        }
        if enforce_canonical_runtime and not _json_exact_equal(
            identity_migration_evidence_scope,
            SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE,
        ):
            raise ValueError("SimSwap identity migration evidence scope mismatch")

        expected_progress = {
            "schema_version": "simswap-lfw-robustness-progress.v1",
            "status": "complete",
            "processed_pairs": num_pairs,
            "total_pairs": num_pairs,
            "result_rows": num_pairs * len(SIMSWAP_MODELS),
            "expected_result_rows": num_pairs * len(SIMSWAP_MODELS),
            "identity_embedding_rows": num_pairs * (3 + len(SIMSWAP_MODELS)),
            "expected_identity_embedding_rows": num_pairs * (3 + len(SIMSWAP_MODELS)),
            "error_rows": 0,
        }
        if (
            set(progress) != {*expected_progress, "updated_at"}
            or not _json_exact_equal(
                {key: progress.get(key) for key in expected_progress},
                expected_progress,
            )
            or not isinstance(progress.get("updated_at"), int)
            or isinstance(progress.get("updated_at"), bool)
            or progress["updated_at"] <= 0
        ):
            raise ValueError("SimSwap completion progress contract mismatch")

        watched_paths = [
            *paths.values(),
            *asset_paths,
            *selected_dataset_paths,
            *selected_checkpoints.values(),
            *engine_artifacts,
            runner.PROTOCOL_PATH,
            *(PROJECT_ROOT / item["path"] for item in run_config["implementation_files"]),
        ]
        watched_before = {path.resolve(): _file_identity(path) for path in watched_paths}
        if any(
            _sha256_file(path) != item["sha256"]
            or path.stat().st_size != item["size_bytes"]
            for path, item in zip(
                selected_dataset_paths,
                pair_manifest["selected_files"],
                strict=True,
            )
        ):
            raise ValueError("SimSwap selected LFW content changed after selection")
        if any(
            _sha256_file(selected_checkpoints[model])
            != binding_objects[model].checkpoint_sha256
            for model in SIMSWAP_MODELS
        ):
            raise ValueError("SimSwap watermark checkpoint changed during validation")
        if enforce_canonical_runtime and any(
            _sha256_file(path)
            != {
                "checkpoint_archive": runner.CHECKPOINT_ARCHIVE_SHA256,
                "generator_checkpoint": runner.GENERATOR_SHA256,
                "arcface_checkpoint": runner.ARCFACE_SHA256,
            }[role]
            for role, path in SIMSWAP_ENGINE_ARTIFACT_PATHS.items()
        ):
            raise ValueError("SimSwap official engine artifact changed during validation")
        if _sha256_file(runner.PROTOCOL_PATH) != protocol_sha:
            raise ValueError("SimSwap protocol changed during validation")
        if not _json_exact_equal(
            runner._implementation_manifest(),
            run_config["implementation_files"],
        ):
            raise ValueError("SimSwap implementation changed during validation")
        if {
            path: _file_identity(path) for path in paths.values()
        } != evidence_identities:
            raise ValueError("SimSwap evidence changed during validation")
        watched_after = {path.resolve(): _file_identity(path) for path in watched_paths}
        if watched_after != watched_before:
            raise ValueError("SimSwap evidence dependency changed during validation")

        signature: dict[str, Any] | None = None
        if require_signature:
            from .signing import MANIFEST_PATH, sha256_file, verify_evidence_bundle

            signature = verify_evidence_bundle()
            if (
                signature.get("verified") is not True
                or signature.get("profile") not in {"release-core", "release"}
                or signature.get("signer_pinned") is not True
            ):
                raise ValueError("SimSwap evidence signature is not trusted")
            manifest_bytes = MANIFEST_PATH.read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != signature.get(
                "manifest_sha256"
            ):
                raise ValueError("SimSwap signature manifest changed during validation")
            manifest = json.loads(
                manifest_bytes.decode("utf-8"),
                parse_constant=_reject_nonfinite,
            )
            if not isinstance(manifest, dict):
                raise ValueError("SimSwap signature manifest is not an object")
            covered = {
                (item.get("path"), item.get("sha256"))
                for item in manifest.get("files", [])
                if isinstance(item, dict)
            }
            signature_paths = [
                *paths.values(),
                *asset_paths,
                *selected_checkpoints.values(),
                *engine_artifacts,
                *(PROJECT_ROOT / path for path in SIMSWAP_IMPLEMENTATION_PATHS),
                Path(__file__),
            ]
            expected_coverage = {
                (logical_path(path), sha256_file(path)) for path in signature_paths
            }
            if not expected_coverage.issubset(covered):
                raise ValueError("SimSwap evidence closure is not covered by the release signature")

        scoped_results = {
            model: {
                "holdout_tar": summary["model_results"][model]["holdout"]["tar"],
                "holdout_far": summary["model_results"][model]["holdout"]["far"],
                "holdout_far_by_negative_control": summary["model_results"][model][
                    "holdout"
                ]["far_by_negative_control"],
                "identity_migration": summary["model_results"][model][
                    "identity_migration"
                ],
                "registered_positive_conditioned_on_identity_migration": (
                    conditioned_registered_positive[model]
                ),
            }
            for model in SIMSWAP_MODELS
        }
        return {
            "schema_version": "simswap-lfw-evidence-status.v1",
            "valid": True,
            "status": "verified" if require_signature else "validated_unsigned",
            "run_id": directory.name,
            "num_pairs": num_pairs,
            "calibration_pairs": calibration_pairs,
            "holdout_pairs": num_pairs - calibration_pairs,
            "result_rows": len(result_rows),
            "identity_embedding_rows": len(identity_rows),
            "identity_overlap_count": pair_manifest["identity_overlap_count"],
            "asset_count": len(asset_paths),
            "identity_migration_evidence_scope": identity_migration_evidence_scope,
            "model_results": scoped_results,
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
            "schema_version": "simswap-lfw-evidence-status.v1",
            "valid": False,
            "status": "review_required",
            "run_id": directory.name,
            "num_pairs": num_pairs,
            "calibration_pairs": calibration_pairs,
            "holdout_pairs": num_pairs - calibration_pairs,
            "result_rows": num_pairs * len(SIMSWAP_MODELS),
            "identity_embedding_rows": num_pairs * (3 + len(SIMSWAP_MODELS)),
            "errors": errors,
        }
