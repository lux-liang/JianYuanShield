from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from scripts import promote_benchmark_run as promotion
from system.evaluation import runtime
from system.evaluation.attacks import ATTACKS
from system.evaluation.run_metadata import sha256_file


SOURCE_PROTOCOL = (
    Path(__file__).resolve().parents[1] / "configs" / "evaluation_protocol.v1.json"
).read_bytes()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


@contextmanager
def patched_runtime(root: Path) -> Iterator[dict[str, Path]]:
    paths = {
        "project": root / "project",
        "models": root / "runtime" / "model-sources",
        "data": root / "runtime" / "data",
        "weights": root / "runtime" / "weights",
        "reports": root / "runtime" / "reports",
        "assets": root / "runtime" / "assets",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    with mock.patch.multiple(
        runtime,
        PROJECT_ROOT=paths["project"],
        MODEL_SOURCE_ROOT=paths["models"],
        DATA_ROOT=paths["data"],
        WEIGHT_ROOT=paths["weights"],
        REPORT_ROOT=paths["reports"],
        ASSET_ROOT=paths["assets"],
    ):
        yield paths


def metric_fields(model: str) -> tuple[list[str], str, str]:
    if model == "sepmark":
        return (
            [
                "bit_error_c",
                "bit_accuracy_c",
                "bit_error_rf",
                "bit_accuracy_rf",
                "psnr",
                "ssim",
            ],
            "bit_accuracy_c",
            "bit_error_c",
        )
    if model == "waveguard":
        return (
            [
                "bit_error_tracer",
                "bit_accuracy_tracer",
                "bit_error_detector",
                "bit_accuracy_detector",
                "psnr",
                "ssim",
            ],
            "bit_accuracy_tracer",
            "bit_error_tracer",
        )
    return (["bit_error", "bit_accuracy", "psnr", "ssim"], "bit_accuracy", "bit_error")


def result_fields(model: str) -> list[str]:
    common = [
        "image_id",
        "source_path",
    ]
    if model == "waveguard":
        common.append("identity_sha256")
    common.extend(["attack_type", "attack_config_sha256"])
    if model == "waveguard":
        common.append("attack_derived_seed")
    common.extend(["message_bits", "message_sha256"])
    if model in {"sepmark", "waveguard"}:
        common.append("primary_decoder")
    common.extend(metric_fields(model)[0])
    common.extend(["success", "error"])
    return common


def quality_fields(model: str) -> list[str]:
    fields = ["image_id", "source_path"]
    if model == "waveguard":
        fields.append("identity_sha256")
    fields.extend([
        "message_bits",
        "message_sha256",
        "watermarked_psnr",
        "watermarked_ssim",
        "error",
    ])
    return fields


def build_fixture(paths: dict[str, Path], model: str) -> tuple[str, Path, Path]:
    spec = promotion.SPECS[model]
    run_id = f"{spec.run_prefix}test-run-0001"
    report_run = paths["reports"] / run_id
    asset_run = paths["assets"] / run_id
    report_run.mkdir()
    (asset_run / "sample_00001").mkdir(parents=True)
    asset_file = asset_run / "sample_00001" / "original.png"
    asset_file.write_bytes(b"fixture-png")

    protocol_path = paths["project"] / "configs" / "evaluation_protocol.v1.json"
    protocol_path.parent.mkdir(parents=True)
    protocol_path.write_bytes(SOURCE_PROTOCOL)
    protocol = json.loads(SOURCE_PROTOCOL)
    attacks = [str(item["id"]) for item in protocol["attacks"]]
    protocol_hash = sha256_file(protocol_path)
    assert protocol_hash is not None

    checkpoint = paths["weights"] / model / "checkpoint.pth"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(f"{model}-checkpoint".encode("utf-8"))
    checkpoint_hash = sha256_file(checkpoint)
    assert checkpoint_hash is not None

    image_id = "person/face.jpg"
    dataset_files = [{
        "path": image_id,
        "size_bytes": 17,
        "sha256": hashlib.sha256(b"source-image").hexdigest(),
    }]
    if model == "waveguard":
        dataset_files[0]["identity_sha256"] = hashlib.sha256(b"person").hexdigest()
    dataset = {
        "schema_version": "dataset-manifest.v1",
        "sample_count": 1,
        "files": dataset_files,
        "files_digest_sha256": promotion._canonical_sha256(dataset_files),
    }
    dataset_path = report_run / "dataset_manifest.json"
    write_json(dataset_path, dataset)
    dataset_hash = sha256_file(dataset_path)
    assert dataset_hash is not None

    message_length = 128 if model == "sepmark" else 30
    bits = "0" * message_length
    message_hash = hashlib.sha256(bytes(int(bit) for bit in bits)).hexdigest()
    identity_hash = hashlib.sha256(b"person").hexdigest()
    fields = result_fields(model)
    rows: list[dict[str, str]] = []
    metrics, primary_accuracy, primary_error = metric_fields(model)
    for index, attack_id in enumerate(attacks):
        row = {field: "" for field in fields}
        row.update({
            "image_id": image_id,
            "source_path": image_id,
            "attack_type": attack_id,
            "attack_config_sha256": ATTACKS[attack_id].config_hash,
            "message_bits": bits,
            "message_sha256": message_hash,
            "psnr": "40.00000000",
            "ssim": "0.90000000",
            "success": "1",
            "error": "",
        })
        if model == "waveguard":
            row["identity_sha256"] = identity_hash
            row["attack_derived_seed"] = str(index + 1)
            row["primary_decoder"] = "tracer"
        elif model == "sepmark":
            row["primary_decoder"] = "decoder_C"
        for field in metrics:
            if field.startswith("bit_error"):
                row[field] = "0.00000000"
            elif field.startswith("bit_accuracy"):
                row[field] = "1.00000000"
        rows.append(row)
    results_path = report_run / "results.csv"
    write_csv(results_path, fields, rows)
    results_hash = sha256_file(results_path)
    assert results_hash is not None

    quality_header = quality_fields(model)
    quality_row = {field: "" for field in quality_header}
    quality_row.update({
        "image_id": image_id,
        "source_path": image_id,
        "message_bits": bits,
        "message_sha256": message_hash,
        "watermarked_psnr": "42.00000000",
        "watermarked_ssim": "0.95000000",
        "error": "",
    })
    if model == "waveguard":
        quality_row["identity_sha256"] = identity_hash
    quality_path = report_run / "watermarked_quality.csv"
    write_csv(quality_path, quality_header, [quality_row])
    quality_hash = sha256_file(quality_path)
    assert quality_hash is not None

    attack_contract = promotion._canonical_sha256([
        {
            "protocol": next(item for item in protocol["attacks"] if item["id"] == attack_id),
            "shared_config_sha256": ATTACKS[attack_id].config_hash,
        }
        for attack_id in attacks
    ])
    config: dict[str, Any] = {
        "schema_version": spec.run_config_schema,
        "method": spec.method,
        "mode": "real_checkpoint",
        "protocol_version": protocol["schema_version"],
        "protocol_path": runtime.logical_path(protocol_path),
        "protocol_sha256": protocol_hash,
        "attack_ids": attacks,
        "attack_contract_sha256": attack_contract,
        "success_threshold": protocol["success_threshold"],
        "seed": protocol["seed"],
        "message_length": message_length,
        "message_derivation": f"{model}-fixture-message-v1",
        "sample_count": 1,
        "dataset_files_digest_sha256": dataset["files_digest_sha256"],
        "dataset_manifest_path": runtime.logical_path(dataset_path),
        "dataset_manifest_sha256": dataset_hash,
        "checkpoint": runtime.logical_path(checkpoint),
        "checkpoint_sha256": checkpoint_hash,
        "result_schema": fields,
        "watermarked_quality_schema": quality_header,
    }
    if spec.primary_decoder is not None:
        config.update({
            "primary_decoder": spec.primary_decoder,
            "secondary_decoder": spec.secondary_decoder,
            "model_contract_sha256": promotion._canonical_sha256(
                protocol["models"][spec.model]
            ),
            "asset_dir": runtime.logical_path(asset_run),
        })
    config_path = report_run / "run_config.json"
    write_json(config_path, config)
    config_hash = sha256_file(config_path)
    assert config_hash is not None

    progress_path = report_run / "progress.json"
    write_json(progress_path, {
        "schema_version": "benchmark-progress.v1",
        "status": "complete",
        "processed_images": 1,
        "total_images": 1,
        "result_rows": len(attacks),
        "expected_result_rows": len(attacks),
        "error_rows": 0,
    })

    context_dir = paths["reports"] / "experiment_context" / run_id
    context_dir.mkdir(parents=True)
    source_manifest = {
        "schema_version": "source-manifest.v1",
        "project": {"source_tree_sha256": hashlib.sha256(b"project").hexdigest()},
        "dependencies": [{"name": model, "source_tree_sha256": hashlib.sha256(model.encode()).hexdigest()}],
    }
    checkpoint_manifest = {
        "schema_version": "checkpoint-manifest.v1",
        "checkpoints": [{
            "path": runtime.logical_path(checkpoint),
            "size_bytes": checkpoint.stat().st_size,
            "sha256": checkpoint_hash,
        }],
    }
    environment = {
        "schema_version": "environment-manifest.v1",
        "dataset_manifest": {
            "path": runtime.logical_path(dataset_path),
            "size_bytes": dataset_path.stat().st_size,
            "sha256": dataset_hash,
        },
        "benchmark_command": ["python", spec.runner_path],
    }
    for name, payload in (
        ("source_manifest.json", source_manifest),
        ("checkpoint_manifest.json", checkpoint_manifest),
        ("environment.json", environment),
    ):
        write_json(context_dir / name, payload)
    hash_lines = [
        f"{sha256_file(context_dir / name)}  {name}"
        for name in ("checkpoint_manifest.json", "environment.json", "source_manifest.json")
    ]
    (context_dir / "hashes.sha256").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")

    attack_summaries: dict[str, dict[str, Any]] = {}
    for attack_id in attacks:
        record: dict[str, Any] = {
            "status": "complete",
            "count": 1,
            "valid_count": 1,
            "error_count": 0,
            "success_rate": 1.0,
            "mean_bit_accuracy": 1.0,
            "mean_bit_error": 0.0,
            "mean_psnr": 40.0,
            "mean_ssim": 0.9,
        }
        for field in metrics:
            summary_field = {
                "bit_error": "mean_bit_error",
                "bit_accuracy": "mean_bit_accuracy",
                "bit_error_c": "mean_bit_error_c",
                "bit_accuracy_c": "mean_bit_accuracy_c",
                "bit_error_rf": "mean_bit_error_rf",
                "bit_accuracy_rf": "mean_bit_accuracy_rf",
                "bit_error_tracer": "mean_bit_error_tracer",
                "bit_accuracy_tracer": "mean_bit_accuracy_tracer",
                "bit_error_detector": "mean_bit_error_detector",
                "bit_accuracy_detector": "mean_bit_accuracy_detector",
                "psnr": "mean_psnr",
                "ssim": "mean_ssim",
            }[field]
            record[summary_field] = 0.0 if "error" in field else (
                1.0 if "accuracy" in field else (40.0 if field == "psnr" else 0.9)
            )
        record["mean_bit_accuracy"] = 1.0
        record["mean_bit_error"] = 0.0
        attack_summaries[attack_id] = record

    summary: dict[str, Any] = {
        "schema_version": "benchmark-summary.v2",
        "status": "complete",
        "method": spec.method,
        "mode": "real_checkpoint",
        "sample_count": 1,
        "num_images": 1,
        "requested_images": 1,
        "evaluated_rows": len(attacks),
        "data_type": "real_lfw_images",
        "message_length": message_length,
        "message_derivation": config["message_derivation"],
        "attack_ids": attacks,
        "expected_result_rows": len(attacks),
        "result_rows": len(attacks),
        "error_rows": 0,
        "missing_rows": 0,
        "attacks": attack_summaries,
        "watermarked_quality": {
            "status": "complete",
            "count": 1,
            "valid_count": 1,
            "error_count": 0,
            "missing_count": 0,
            "mean_psnr": 42.0,
            "mean_ssim": 0.95,
            "csv_path": runtime.logical_path(quality_path),
            "csv_sha256": quality_hash,
        },
        "results_csv_path": runtime.logical_path(results_path),
        "results_csv_sha256": results_hash,
        "watermarked_quality_csv_path": runtime.logical_path(quality_path),
        "watermarked_quality_csv_sha256": quality_hash,
        "dataset_manifest_path": runtime.logical_path(dataset_path),
        "dataset_manifest_sha256": dataset_hash,
        "run_config_path": runtime.logical_path(config_path),
        "run_config_sha256": config_hash,
        "checkpoint": runtime.logical_path(checkpoint),
        "checkpoint_sha256": checkpoint_hash,
        "protocol_version": protocol["schema_version"],
        "protocol_path": runtime.logical_path(protocol_path),
        "protocol_sha256": protocol_hash,
        "seed": protocol["seed"],
        "run_metadata": {
            "schema_version": "run-metadata.v1",
            "model": spec.model,
            "seed": protocol["seed"],
            "evaluation_protocol": protocol["schema_version"],
            "protocol_path": runtime.logical_path(protocol_path),
            "protocol_sha256": protocol_hash,
            "checkpoint": runtime.logical_path(checkpoint),
            "checkpoint_sha256": checkpoint_hash,
            "command": ["python", spec.runner_path],
        },
    }
    if spec.primary_decoder is not None:
        summary["primary_decoder"] = spec.primary_decoder
        summary["secondary_decoder"] = spec.secondary_decoder
    for field, filename in promotion.CONTEXT_FILES.items():
        path = context_dir / filename
        summary[f"{field}_path"] = runtime.logical_path(path)
        summary[f"{field}_sha256"] = sha256_file(path)

    if model == "waveguard":
        artifact_files = [{
            "path": "sample_00001/original.png",
            "size_bytes": asset_file.stat().st_size,
            "sha256": sha256_file(asset_file),
        }]
        artifact_digest = promotion._canonical_sha256(artifact_files)
        artifact_path = report_run / "artifact_manifest.json"
        write_json(artifact_path, {
            "schema_version": "benchmark-artifact-manifest.v1",
            "asset_root": runtime.logical_path(asset_run),
            "file_count": len(artifact_files),
            "files": artifact_files,
            "files_digest_sha256": artifact_digest,
        })
        summary.update({
            "artifact_manifest_path": runtime.logical_path(artifact_path),
            "artifact_manifest_sha256": sha256_file(artifact_path),
            "artifact_files_digest_sha256": artifact_digest,
            "progress_path": runtime.logical_path(progress_path),
            "progress_sha256": sha256_file(progress_path),
        })

    write_json(report_run / "summary.json", summary)
    return run_id, report_run, asset_run


class PromoteBenchmarkRunTests(unittest.TestCase):
    def test_dry_run_audits_every_supported_model_without_writes(self) -> None:
        for model in promotion.SPECS:
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                with patched_runtime(Path(directory)) as paths:
                    run_id, _, _ = build_fixture(paths, model)
                    result = promotion.promote_run(model, run_id, dry_run=True)
                    self.assertEqual(result["status"], "dry_run_verified")
                    self.assertEqual(result["relative_symlink_target"], run_id)
                    self.assertTrue(all(result["checks"].values()))
                    spec = promotion.SPECS[model]
                    self.assertFalse(os.path.lexists(paths["reports"] / spec.canonical_name))
                    self.assertFalse(os.path.lexists(paths["assets"] / spec.canonical_name))
                    self.assertFalse((paths["reports"] / ".promote_benchmark_run.lock").exists())

    def test_promotion_creates_relative_links_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)) as paths:
                run_id, report_run, asset_run = build_fixture(paths, "kadnet")
                first = promotion.promote_run("kadnet", run_id)
                self.assertEqual(first["status"], "promoted")
                report_link = paths["reports"] / promotion.SPECS["kadnet"].canonical_name
                asset_link = paths["assets"] / promotion.SPECS["kadnet"].canonical_name
                self.assertEqual(os.readlink(report_link), run_id)
                self.assertEqual(os.readlink(asset_link), run_id)
                self.assertEqual(report_link.resolve(), report_run)
                self.assertEqual(asset_link.resolve(), asset_run)

                second = promotion.promote_run("kadnet", run_id)
                self.assertEqual(second["status"], "already_current")
                self.assertEqual(os.readlink(report_link), run_id)
                self.assertEqual(os.readlink(asset_link), run_id)

    def test_raw_result_tamper_blocks_without_partial_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)) as paths:
                run_id, report_run, _ = build_fixture(paths, "sepmark")
                with (report_run / "results.csv").open("a", encoding="utf-8") as handle:
                    handle.write("tampered\n")
                with self.assertRaisesRegex(promotion.PromotionError, "raw results SHA-256 mismatch"):
                    promotion.promote_run("sepmark", run_id)
                spec = promotion.SPECS["sepmark"]
                self.assertFalse(os.path.lexists(paths["reports"] / spec.canonical_name))
                self.assertFalse(os.path.lexists(paths["assets"] / spec.canonical_name))

    def test_context_manifest_internal_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)) as paths:
                run_id, report_run, _ = build_fixture(paths, "kadnet")
                context_hashes = paths["reports"] / "experiment_context" / run_id / "hashes.sha256"
                context_hashes.write_text(f"{'0' * 64}  source_manifest.json\n", encoding="utf-8")
                summary_path = report_run / "summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["experiment_context_hashes_sha256"] = sha256_file(context_hashes)
                write_json(summary_path, summary)
                with self.assertRaisesRegex(promotion.PromotionError, "does not bind the context files"):
                    promotion.promote_run("kadnet", run_id, dry_run=True)

    def test_real_canonical_directory_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)) as paths:
                run_id, _, _ = build_fixture(paths, "waveguard")
                spec = promotion.SPECS["waveguard"]
                report_canonical = paths["reports"] / spec.canonical_name
                asset_canonical = paths["assets"] / spec.canonical_name
                report_canonical.mkdir()
                asset_canonical.mkdir()
                marker = report_canonical / "keep.txt"
                marker.write_text("keep", encoding="utf-8")
                with self.assertRaisesRegex(promotion.PromotionError, "will not be overwritten"):
                    promotion.promote_run("waveguard", run_id)
                self.assertTrue(marker.is_file())
                self.assertTrue(asset_canonical.is_dir())

    def test_partial_canonical_pair_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)) as paths:
                run_id, _, _ = build_fixture(paths, "kadnet")
                spec = promotion.SPECS["kadnet"]
                os.symlink(run_id, paths["reports"] / spec.canonical_name)
                with self.assertRaisesRegex(promotion.PromotionError, "partial state"):
                    promotion.promote_run("kadnet", run_id, dry_run=True)

    def test_second_link_failure_rolls_back_first_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)) as paths:
                run_id, _, _ = build_fixture(paths, "sepmark")
                spec = promotion.SPECS["sepmark"]
                real_replace = os.replace
                replace_calls = 0

                def fail_report_switch(source: Path, destination: Path) -> None:
                    nonlocal replace_calls
                    replace_calls += 1
                    if replace_calls == 2:
                        raise OSError("injected report switch failure")
                    real_replace(source, destination)

                with (
                    mock.patch.object(promotion.os, "replace", side_effect=fail_report_switch),
                    self.assertRaisesRegex(OSError, "injected report switch failure"),
                ):
                    promotion.promote_run("sepmark", run_id)

                self.assertFalse(os.path.lexists(paths["reports"] / spec.canonical_name))
                self.assertFalse(os.path.lexists(paths["assets"] / spec.canonical_name))
                self.assertFalse(any(paths["reports"].glob(f".{spec.canonical_name}.promote-*")))
                self.assertFalse(any(paths["assets"].glob(f".{spec.canonical_name}.promote-*")))

    def test_report_pollution_and_waveguard_asset_tamper_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)) as paths:
                run_id, report_run, asset_run = build_fixture(paths, "waveguard")
                (report_run / ".partial.tmp").write_text("partial", encoding="utf-8")
                with self.assertRaisesRegex(promotion.PromotionError, "unregistered entries"):
                    promotion.promote_run("waveguard", run_id, dry_run=True)
                (report_run / ".partial.tmp").unlink()
                (asset_run / "sample_00001" / "original.png").write_bytes(b"changed")
                with self.assertRaisesRegex(promotion.PromotionError, "artifact manifest file records mismatch"):
                    promotion.promote_run("waveguard", run_id, dry_run=True)

    def test_run_id_cannot_cross_model_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patched_runtime(Path(directory)):
                with self.assertRaisesRegex(promotion.PromotionError, "must start with sepmark-"):
                    promotion.promote_run(
                        "sepmark",
                        "waveguard-test-run-0001",
                        dry_run=True,
                    )


if __name__ == "__main__":
    unittest.main()
