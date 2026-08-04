from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import math

from fastapi.testclient import TestClient

from system.backend.app import app
from system.backend import collaboration
from system.backend.collaboration import (
    CollaborationPolicyError,
    MODEL_NAMES,
    build_recommendation as build_recommendation_engine,
)
from system.backend import routes
from system.backend import signing
from system.backend.schemas import CollaborationRecommendationResponse


ROOT = Path(__file__).resolve().parents[1]


SOURCE_ACCURACY = {
    "LIDMark": {"LIDMark": 0.5068, "KAD-Net": 0.7324, "SepMark": 0.7351, "WaveGuard": 0.7332},
    "KAD-Net": {"LIDMark": 0.9995, "KAD-Net": 0.5038, "SepMark": 0.9979, "WaveGuard": 0.9993},
    "SepMark": {"LIDMark": 0.9153, "KAD-Net": 0.9720, "SepMark": 0.9901, "WaveGuard": 0.9866},
    "WaveGuard": {"LIDMark": 0.6552, "KAD-Net": 1.0, "SepMark": 1.0, "WaveGuard": 1.0},
}
ATTACKER_ACCURACY = {
    "LIDMark": 0.738,
    "KAD-Net": 0.999,
    "SepMark": 0.975,
    "WaveGuard": 1.0,
}
SAME_MODEL_ATTACKER_ACCURACY = {
    "LIDMark": 0.735,
    "KAD-Net": 0.995,
    "SepMark": 0.504,
    "WaveGuard": 0.503,
}
INITIAL_PSNR = {
    "LIDMark": 27.16,
    "KAD-Net": 34.43,
    "SepMark": 38.31,
    "WaveGuard": 33.23,
}
POST_PSNR = {
    "LIDMark": {"LIDMark": 24.48, "KAD-Net": 26.60, "SepMark": 26.84, "WaveGuard": 26.41},
    "KAD-Net": {"LIDMark": 26.56, "KAD-Net": 31.94, "SepMark": 33.07, "WaveGuard": 30.72},
    "SepMark": {"LIDMark": 26.87, "KAD-Net": 33.11, "SepMark": 23.61, "WaveGuard": 32.03},
    "WaveGuard": {"LIDMark": 27.26, "KAD-Net": 33.07, "SepMark": 32.02, "WaveGuard": 30.83},
}


def policy_config() -> dict:
    config = json.loads(
        (ROOT / "configs" / "collaboration_policy.v2.json").read_text(encoding="utf-8")
    )
    config["uncertainty"]["resamples"] = 256
    return config


def metric(mean: float, *, std: float = 0.01, bounded: bool = False) -> dict[str, float]:
    lower = max(0.0, mean - std)
    upper = mean + std
    if bounded:
        upper = min(1.0, upper)
    return {
        "mean": mean,
        "std": std,
        "median": mean,
        "min": lower,
        "max": upper,
    }


def wilson95(rate: float, sample_count: int = 256) -> list[float]:
    successes = round(rate * sample_count)
    z = 1.959963984540054
    proportion = successes / sample_count
    denominator = 1.0 + z * z / sample_count
    center = (proportion + z * z / (2.0 * sample_count)) / denominator
    half = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / sample_count
            + z * z / (4.0 * sample_count * sample_count)
        )
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def complete_summary() -> dict:
    config = policy_config()
    evidence = config["evidence"]
    matrix: dict[str, dict] = {}
    for source in MODEL_NAMES:
        matrix[source] = {}
        for attacker in MODEL_NAMES:
            source_accuracy = SOURCE_ACCURACY[source][attacker]
            attacker_accuracy = (
                SAME_MODEL_ATTACKER_ACCURACY[source]
                if source == attacker
                else ATTACKER_ACCURACY[attacker]
            )
            source_success_rate = 1.0 if source_accuracy >= 0.9 else 0.0
            attacker_success_rate = 1.0 if attacker_accuracy >= 0.9 else 0.0
            matrix[source][attacker] = {
                "cell_id": f"{source}::{attacker}",
                "status": "complete",
                "expected_rows": 256,
                "observed_rows": 256,
                "valid_rows": 256,
                "error_rows": 0,
                "missing_rows": 0,
                "aggregates": {
                    "source_bit_accuracy": metric(source_accuracy, bounded=True),
                    "attacker_bit_accuracy": metric(attacker_accuracy, bounded=True),
                    "source_success_rate": source_success_rate,
                    "source_success_rate_wilson95": wilson95(source_success_rate),
                    "attacker_success_rate": attacker_success_rate,
                    "attacker_success_rate_wilson95": wilson95(attacker_success_rate),
                    "first_embedding_psnr": metric(INITIAL_PSNR[source]),
                    "first_embedding_ssim": metric(0.95, bounded=True),
                    "second_vs_original_psnr": metric(POST_PSNR[source][attacker]),
                    "second_vs_original_ssim": metric(0.85, bounded=True),
                    "second_vs_first_psnr": metric(30.0),
                    "second_vs_first_ssim": metric(0.9, bounded=True),
                },
            }
    checkpoints = {
        model: {
            "status": "available",
            "integrity_verified": True,
            "checkpoint_sha256": str(index) * 64,
            "expected_checkpoint_sha256": str(index) * 64,
        }
        for index, model in enumerate(MODEL_NAMES, start=1)
    }
    return {
        "schema_version": "mea-matrix-summary.v1",
        "status": "complete",
        "models": list(MODEL_NAMES),
        "model_count": 4,
        "images_per_cell": 256,
        "preflight_errors": [],
        "postflight_input_audit": {
            "checkpoint_sha256_unchanged": True,
            "dataset_files_unchanged": True,
            "implementation_sha256_unchanged": True,
            "protocol_sha256_unchanged": True,
            "verified": True,
            "errors": [],
        },
        "coverage": {
            "complete_cells": 16,
            "expected_cells": 16,
            "expected_rows": 4096,
            "observed_unique_expected_rows": 4096,
            "valid_rows": 4096,
            "duplicate_rows": 0,
            "error_rows": 0,
            "missing_rows": 0,
            "unexpected_rows": 0,
        },
        "protocol": {
            "sha256": evidence["protocol_sha256"],
            "success_threshold": 0.9,
        },
        "artifacts": {
            "dataset_manifest": {
                "path": "dataset_manifest.json",
                "sha256": evidence["dataset_manifest_sha256"],
            },
            "raw_results": {
                "path": "raw_results.csv",
                "sha256": evidence["raw_results_sha256"],
            },
            "run_config": {
                "path": "run_config.json",
                "sha256": evidence["run_config_sha256"],
            },
        },
        "checkpoint_evidence": checkpoints,
        "matrix": matrix,
    }


def complete_cluster_input(summary: dict | None = None) -> dict:
    summary = summary or complete_summary()
    identity_count = 217
    cells: dict[str, dict[str, dict[str, list[float]]]] = {
        source: {} for source in MODEL_NAMES
    }
    threshold = float(summary["protocol"]["success_threshold"])
    for source in MODEL_NAMES:
        for attacker in MODEL_NAMES:
            aggregates = summary["matrix"][source][attacker]["aggregates"]
            source_accuracy = float(aggregates["source_bit_accuracy"]["mean"])
            attacker_accuracy = float(aggregates["attacker_bit_accuracy"]["mean"])
            values = {
                "source_bit_accuracy_diagnostic": source_accuracy,
                "attacker_bit_accuracy_diagnostic": attacker_accuracy,
                "source_protocol_normalized_margin": collaboration._protocol_normalized_margin(
                    source_accuracy, threshold
                ),
                "source_protocol_success": float(
                    aggregates["source_success_rate"]
                ),
                "attacker_protocol_normalized_margin": collaboration._protocol_normalized_margin(
                    attacker_accuracy, threshold
                ),
                "attacker_protocol_success": float(
                    aggregates["attacker_success_rate"]
                ),
                "first_embedding_psnr": float(
                    aggregates["first_embedding_psnr"]["mean"]
                ),
                "second_vs_original_psnr": float(
                    aggregates["second_vs_original_psnr"]["mean"]
                ),
                "second_vs_original_ssim": float(
                    aggregates["second_vs_original_ssim"]["mean"]
                ),
            }
            cells[source][attacker] = {
                name: [value] * identity_count for name, value in values.items()
            }
    return {
        "schema_version": "mea-identity-cluster-input.v1",
        "image_count": 256,
        "identity_count": identity_count,
        "repeated_identity_count": 24,
        "images_in_repeated_identities": 63,
        "max_cluster_size": 10,
        "identities": [f"identity_{index:03d}" for index in range(identity_count)],
        "identity_sizes": {},
        "raw_rows": 4096,
        "cells": cells,
    }


def complete_dataset_and_raw_results() -> tuple[dict, str]:
    identity_sizes = [10] + [3] * 7 + [2] * 16 + [1] * 193
    files = []
    sample_index = 0
    for identity_index, size in enumerate(identity_sizes):
        identity = f"identity_{identity_index:03d}"
        for image_index in range(1, size + 1):
            files.append({
                "image_id": hashlib.sha256(
                    f"image-{sample_index}".encode("utf-8")
                ).hexdigest(),
                "path": f"data/lfw/{identity}/{identity}_{image_index:04d}.jpg",
                "sample_index": sample_index,
            })
            sample_index += 1
    dataset = {
        "schema_version": "mea-shared-dataset-manifest.v1",
        "sample_count": 256,
        "files": files,
    }
    fields = [
        "cell_id", "source_model", "attacker_model", "sample_index",
        "image_id", "source_path", "success_threshold",
        "source_primary_decoder", "attacker_primary_decoder",
        "source_message_length", "attacker_message_length",
        "source_bit_accuracy", "source_success", "attacker_bit_accuracy",
        "attacker_success", "first_embedding_psnr",
        "second_vs_original_psnr", "second_vs_original_ssim", "status",
        "error_stage", "error_type", "error",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    semantics = policy_config()["model_semantics"]
    for source in MODEL_NAMES:
        for attacker in MODEL_NAMES:
            for image in files:
                writer.writerow({
                    "cell_id": f"{source}::{attacker}",
                    "source_model": source,
                    "attacker_model": attacker,
                    "sample_index": image["sample_index"],
                    "image_id": image["image_id"],
                    "source_path": image["path"],
                    "success_threshold": 0.9,
                    "source_primary_decoder": semantics[source]["primary_decoder"],
                    "attacker_primary_decoder": semantics[attacker]["primary_decoder"],
                    "source_message_length": semantics[source]["message_length"],
                    "attacker_message_length": semantics[attacker]["message_length"],
                    "source_bit_accuracy": 0.95,
                    "source_success": 1,
                    "attacker_bit_accuracy": 0.95,
                    "attacker_success": 1,
                    "first_embedding_psnr": 35.0,
                    "second_vs_original_psnr": 30.0,
                    "second_vs_original_ssim": 0.9,
                    "status": "ok",
                    "error_stage": "",
                    "error_type": "",
                    "error": "",
                })
    return dataset, stream.getvalue()


def build_recommendation(
    summary: dict,
    request: dict,
    config: dict,
    *,
    evidence: dict | None = None,
    cluster_input: dict | None = None,
) -> dict:
    return build_recommendation_engine(
        summary,
        request,
        config,
        cluster_input=cluster_input or complete_cluster_input(summary),
        evidence=evidence,
    )


def uniform_request(**updates) -> dict:
    payload = {
        "threats": [
            {"model": model, "exposure": 1.0}
            for model in MODEL_NAMES
        ],
        "candidate_models": list(MODEL_NAMES),
        "risk_aversion": 0.6,
        "fidelity_weight": 0.2,
        "minimum_worst_case_protocol_normalized_margin": 0.45,
    }
    payload.update(updates)
    return payload


def signed_evidence() -> dict:
    artifact = {"path": "artifact", "sha256": "1" * 64, "size_bytes": 1}
    signature = {
        "verified": True,
        "signer_pinned": True,
        "profile": "release-core",
        "manifest_sha256": "2" * 64,
        "public_key_fingerprint_sha256": "3" * 64,
        "policy_path": "configs/collaboration_policy.v2.json",
        "policy_sha256": "4" * 64,
    }
    return {
        "summary_path": "reports/mea/summary.json",
        "summary_sha256": "5" * 64,
        "policy_path": "configs/collaboration_policy.v2.json",
        "policy_sha256": "4" * 64,
        "source_evidence_status": "complete_unsigned",
        "source_claim_status": "review_and_signature_required",
        "protocol_sha256": "6" * 64,
        "images_per_cell": 256,
        "image_count": 256,
        "identity_count": 217,
        "repeated_identity_count": 24,
        "images_in_repeated_identities": 63,
        "max_cluster_size": 10,
        "cells": 16,
        "rows": 4096,
        "artifacts": {
            "dataset_manifest": dict(artifact),
            "raw_results": dict(artifact),
            "run_config": dict(artifact),
            "progress": dict(artifact),
        },
        "matrix_validation": {"valid": True},
        "release_signature": signature,
        "signature_verified": True,
        "signer_pinned": True,
        "content_verified": True,
    }


class CollaborationPolicyTests(unittest.TestCase):
    def test_policy_loader_requires_the_signed_full_matrix_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "reports" / "formal-mea"
            report.mkdir(parents=True)
            summary = complete_summary()
            summary_path = report / "summary.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            config = policy_config()
            config["evidence"]["summary_path"] = "reports/formal-mea/summary.json"
            config["evidence"]["summary_sha256"] = hashlib.sha256(
                summary_path.read_bytes()
            ).hexdigest()
            config_path = root / "collaboration-policy.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            with (
                patch.object(collaboration, "REPORTS", root / "reports"),
                patch.object(
                    collaboration,
                    "resolve_logical_path",
                    return_value=summary_path,
                ),
                patch.object(
                    collaboration,
                    "validate_mea_matrix_evidence",
                    return_value={"valid": False, "status": "review_required"},
                ) as validator,
            ):
                with self.assertRaisesRegex(
                    CollaborationPolicyError,
                    "hash closure is invalid",
                ):
                    collaboration.load_policy_evidence(config_path)
            validator.assert_called_once_with(
                directory=report,
                require_signature=True,
            )

    def test_deployment_entrypoint_rejects_unsigned_loader_output(self) -> None:
        with patch.object(
            collaboration,
            "load_policy_evidence",
            return_value=(
                policy_config(),
                complete_summary(),
                {
                    "content_verified": True,
                    "signature_verified": False,
                    "signer_pinned": False,
                },
                complete_cluster_input(),
            ),
        ):
            with self.assertRaisesRegex(
                CollaborationPolicyError,
                "requires signed, pinned evidence",
            ):
                collaboration.recommend_collaboration(uniform_request())

    def test_uniform_threat_selects_sepmark(self) -> None:
        result = build_recommendation(
            complete_summary(),
            uniform_request(),
            policy_config(),
            evidence={"content_verified": True},
        )
        self.assertEqual(result["status"], "recommendation_ready")
        self.assertEqual(result["recommendation"]["model"], "SepMark")
        self.assertTrue(result["recommendation"]["pareto_optimal"])
        self.assertTrue(result["evidence"]["content_verified"])
        self.assertEqual(
            result["scoring"]["pareto_scope"],
            "hard_constraint_feasible_candidates_only",
        )
        self.assertGreaterEqual(
            result["recommendation"][
                "worst_case_source_protocol_normalized_margin"
            ],
            result["recommendation"][
                "worst_case_source_protocol_normalized_margin_cluster_lcb"
            ],
        )
        self.assertAlmostEqual(
            sum(result["request"]["threat_probabilities"].values()),
            1.0,
        )
        self.assertEqual(result["scoring"]["identity_count"], 217)
        self.assertEqual(result["scoring"]["family_size"], 96)
        self.assertEqual(
            result["scoring"]["raw_bit_accuracy_use"],
            "diagnostic_only_not_cross_model_ranked",
        )

    def test_lidmark_reembedding_threat_selects_kadnet(self) -> None:
        result = build_recommendation(
            complete_summary(),
            uniform_request(threats=[{"model": "LIDMark", "exposure": 7.0}]),
            policy_config(),
        )
        self.assertEqual(result["recommendation"]["model"], "KAD-Net")
        self.assertEqual(result["request"]["threat_probabilities"], {"LIDMark": 1.0})

    def test_interaction_plan_classifies_coexistence_and_source_dominance(self) -> None:
        result = build_recommendation(
            complete_summary(),
            uniform_request(),
            policy_config(),
        )
        classes = {
            row["attacker_model"]: row["class"]
            for row in result["interaction_plan"]
        }
        self.assertEqual(classes["LIDMark"], "source_dominant")
        self.assertEqual(classes["KAD-Net"], "coexistence")
        self.assertEqual(classes["WaveGuard"], "coexistence")
        self.assertEqual(
            result["recommendation"]["low_risk_interaction_models"],
            ["KAD-Net", "WaveGuard"],
        )

    def test_impossible_constraint_returns_no_recommendation(self) -> None:
        result = build_recommendation(
            complete_summary(),
            uniform_request(
                minimum_worst_case_protocol_normalized_margin=1.0
            ),
            policy_config(),
        )
        self.assertEqual(result["status"], "constraint_unsatisfied")
        self.assertIsNone(result["recommendation"])
        self.assertTrue(all(not row["feasible"] for row in result["ranking"]))
        self.assertTrue(all(not row["pareto_optimal"] for row in result["ranking"]))

    def test_point_estimate_cannot_bypass_confidence_bound_hard_constraint(self) -> None:
        summary = complete_summary()
        cell = summary["matrix"]["SepMark"]["LIDMark"]
        cell["aggregates"]["source_bit_accuracy"] = metric(
            0.905,
            std=0.08,
            bounded=True,
        )
        cluster_input = complete_cluster_input(summary)
        cluster_input["cells"]["SepMark"]["LIDMark"][
            "source_protocol_normalized_margin"
        ] = [0.9] * 109 + [0.1] * 108
        result = build_recommendation(
            summary,
            uniform_request(
                threats=[{"model": "LIDMark", "exposure": 1.0}],
                candidate_models=["SepMark"],
            ),
            policy_config(),
            cluster_input=cluster_input,
        )
        self.assertEqual(result["status"], "constraint_unsatisfied")
        self.assertEqual(
            result["ranking"][0]["constraint_violations"],
            [
                "worst_case_protocol_normalized_margin_cluster_lcb_below_floor"
            ],
        )

    def test_repeated_identities_can_make_naive_pass_but_cluster_gate_fail(self) -> None:
        summary = complete_summary()
        cluster_input = complete_cluster_input(summary)
        repeated_sizes = [10] + [3] * 7 + [2] * 16
        identity_sizes = repeated_sizes + [1] * (217 - len(repeated_sizes))
        margins = [0.9] * 116 + [0.1] * 101
        self.assertEqual(sum(identity_sizes), 256)
        naive_image_weighted = sum(
            margin * size for margin, size in zip(margins, identity_sizes)
        ) / 256
        self.assertGreater(naive_image_weighted, 0.55)
        cluster_input["cells"]["SepMark"]["LIDMark"][
            "source_protocol_normalized_margin"
        ] = margins
        result = build_recommendation(
            summary,
            uniform_request(
                threats=[{"model": "LIDMark", "exposure": 1.0}],
                candidate_models=["SepMark"],
                minimum_worst_case_protocol_normalized_margin=0.55,
            ),
            policy_config(),
            cluster_input=cluster_input,
        )
        self.assertEqual(result["status"], "constraint_unsatisfied")
        self.assertIn(
            "worst_case_protocol_normalized_margin_cluster_lcb_below_floor",
            result["ranking"][0]["constraint_violations"],
        )

    def test_raw_rows_reconstruct_the_fixed_identity_cluster_estimand(self) -> None:
        dataset, raw_results = complete_dataset_and_raw_results()
        cluster_input = collaboration.build_identity_cluster_input(
            dataset,
            raw_results,
            policy_config(),
        )
        self.assertEqual(
            (
                cluster_input["image_count"],
                cluster_input["identity_count"],
                cluster_input["repeated_identity_count"],
                cluster_input["images_in_repeated_identities"],
                cluster_input["max_cluster_size"],
                cluster_input["raw_rows"],
            ),
            (256, 217, 24, 63, 10, 4096),
        )
        self.assertEqual(
            len(
                cluster_input["cells"]["SepMark"]["WaveGuard"]
                ["source_protocol_normalized_margin"]
            ),
            217,
        )

        tampered_dataset = copy.deepcopy(dataset)
        tampered_dataset["files"][0]["path"] = (
            "data/lfw/unregistered_identity/unregistered_identity_0001.jpg"
        )
        with self.assertRaisesRegex(
            CollaborationPolicyError,
            "identity cluster audit mismatch",
        ):
            collaboration.build_identity_cluster_input(
                tampered_dataset,
                raw_results,
                policy_config(),
            )

        reader = csv.DictReader(io.StringIO(raw_results, newline=""))
        rows = list(reader)
        rows[0]["source_message_length"] = "30"
        tampered_stream = io.StringIO(newline="")
        writer = csv.DictWriter(tampered_stream, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        with self.assertRaisesRegex(
            CollaborationPolicyError,
            "raw source message/decoder semantic mismatch",
        ):
            collaboration.build_identity_cluster_input(
                dataset,
                tampered_stream.getvalue(),
                policy_config(),
            )

    def test_signed_policy_floor_cannot_be_weakened_by_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "signed policy floor"):
            build_recommendation(
                complete_summary(),
                uniform_request(
                    minimum_worst_case_protocol_normalized_margin=0.4
                ),
                policy_config(),
            )

    def test_pareto_frontier_excludes_hard_constraint_failures(self) -> None:
        result = build_recommendation(
            complete_summary(),
            uniform_request(),
            policy_config(),
        )
        self.assertTrue(result["recommendation"]["pareto_optimal"])
        self.assertTrue(
            all(
                not row["pareto_optimal"]
                for row in result["ranking"]
                if not row["feasible"]
            )
        )

    def test_scalar_score_tie_cannot_select_a_dominated_candidate(self) -> None:
        summary = complete_summary()
        lidmark_cell = summary["matrix"]["LIDMark"]["SepMark"]
        kadnet_cell = summary["matrix"]["KAD-Net"]["SepMark"]
        lidmark_cell["aggregates"]["source_bit_accuracy"] = metric(
            0.95, bounded=True
        )
        lidmark_cell["aggregates"]["source_success_rate"] = 1.0
        lidmark_cell["aggregates"]["source_success_rate_wilson95"] = wilson95(1.0)
        lidmark_cell["aggregates"]["second_vs_original_psnr"] = copy.deepcopy(
            kadnet_cell["aggregates"]["second_vs_original_psnr"]
        )
        lidmark_cell["aggregates"]["second_vs_original_ssim"] = copy.deepcopy(
            kadnet_cell["aggregates"]["second_vs_original_ssim"]
        )
        result = build_recommendation(
            summary,
            uniform_request(
                threats=[{"model": "SepMark", "exposure": 1.0}],
                candidate_models=["LIDMark", "KAD-Net"],
                fidelity_weight=1.0,
            ),
            policy_config(),
        )
        self.assertEqual(result["ranking"][0]["model"], "KAD-Net")
        self.assertEqual(result["recommendation"]["model"], "KAD-Net")
        self.assertFalse(result["ranking"][1]["pareto_optimal"])

    def test_duplicate_threat_is_rejected(self) -> None:
        request = uniform_request(threats=[
            {"model": "SepMark", "exposure": 1.0},
            {"model": "SepMark", "exposure": 2.0},
        ])
        with self.assertRaisesRegex(ValueError, "duplicate threat model"):
            build_recommendation(complete_summary(), request, policy_config())

    def test_direct_policy_input_rejects_coercion_and_nested_unknown_fields(self) -> None:
        request = uniform_request(
            threats=[{"model": "SepMark", "exposure": "1", "extra": True}]
        )
        with self.assertRaisesRegex(ValueError, "only model and exposure"):
            build_recommendation(complete_summary(), request, policy_config())

    def test_incomplete_or_tampered_summary_fails_closed(self) -> None:
        summary = complete_summary()
        summary["coverage"]["missing_rows"] = 1
        with self.assertRaisesRegex(CollaborationPolicyError, "coverage mismatch"):
            build_recommendation(summary, uniform_request(), policy_config())

    def test_api_route_is_registered_and_uses_uniform_error_boundary(self) -> None:
        with TestClient(app) as client:
            with patch.object(
                routes,
                "recommend_collaboration",
                side_effect=CollaborationPolicyError("internal evidence path"),
            ):
                response = client.post(
                    "/api/collaboration/recommend",
                    json={"threats": [{"model": "SepMark", "exposure": 1.0}]},
                )
        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertNotIn("internal evidence path", json.dumps(payload))

    def test_response_schema_accepts_the_real_recommendation_shape(self) -> None:
        result = build_recommendation(
            complete_summary(),
            uniform_request(),
            policy_config(),
            evidence=signed_evidence(),
        )
        validated = CollaborationRecommendationResponse.model_validate(result)
        payload = validated.model_dump(mode="json", by_alias=True)
        self.assertEqual(payload["interaction_plan"][0]["class"], "source_dominant")
        self.assertTrue(payload["evidence"]["signature_verified"])
        with TestClient(app) as client:
            with patch.object(routes, "recommend_collaboration", return_value=result):
                response = client.post(
                    "/api/collaboration/recommend",
                    json={"threats": [{"model": "SepMark", "exposure": 1.0}]},
                )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["interaction_plan"][0]["class"], "source_dominant")
        blocked = build_recommendation(
            complete_summary(),
            uniform_request(
                minimum_worst_case_protocol_normalized_margin=1.0
            ),
            policy_config(),
            evidence=signed_evidence(),
        )
        blocked_payload = CollaborationRecommendationResponse.model_validate(blocked)
        self.assertEqual(blocked_payload.status, "constraint_unsatisfied")
        self.assertIsNone(blocked_payload.recommendation)

    def test_policy_input_rejects_unknown_fields(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/collaboration/recommend",
                json={
                    "threats": [{"model": "SepMark", "exposure": 1.0}],
                    "unreviewed_override": True,
                },
            )
        self.assertEqual(response.status_code, 422)

    def test_api_rejects_bool_numeric_and_duplicate_candidates(self) -> None:
        with TestClient(app) as client:
            bool_response = client.post(
                "/api/collaboration/recommend",
                json={"threats": [{"model": "SepMark", "exposure": True}]},
            )
            duplicate_response = client.post(
                "/api/collaboration/recommend",
                json={
                    "threats": [{"model": "SepMark", "exposure": 1.0}],
                    "candidate_models": ["SepMark", "SepMark"],
                },
            )
        self.assertEqual(bool_response.status_code, 422)
        self.assertEqual(duplicate_response.status_code, 422)

    def test_snapshot_guard_detects_post_read_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text('{"value":1}', encoding="utf-8")
            _payload, snapshot = collaboration._read_json_snapshot(
                path,
                label="test policy",
                maximum_bytes=1024,
            )
            path.write_text('{"value":2}', encoding="utf-8")
            with self.assertRaisesRegex(
                CollaborationPolicyError,
                "changed during policy evaluation",
            ):
                collaboration._assert_snapshot_unchanged(
                    snapshot,
                    label="test policy",
                )

    def test_validator_closure_must_match_the_snapshots_used_for_scoring(self) -> None:
        validation = {
            "evidence_files": {
                "summary.json": {"sha256": "a" * 64},
            }
        }
        with self.assertRaisesRegex(
            CollaborationPolicyError,
            "validator snapshot mismatch",
        ):
            collaboration._require_matrix_snapshot_binding(
                validation,
                {"summary.json": {"sha256": "b" * 64}},
            )

    def test_exact_policy_bytes_must_be_covered_by_verified_release_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "configs" / "collaboration_policy.v2.json"
            policy_path.parent.mkdir(parents=True)
            policy_path.write_text('{"policy":"bound"}', encoding="utf-8")
            _payload, policy_snapshot = collaboration._read_json_snapshot(
                policy_path,
                label="test policy",
                maximum_bytes=1024,
            )
            manifest_path = root / "reports" / "evidence_signature" / "manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest = {
                "schema_version": "evidence-manifest.v1",
                "profile": "release-core",
                "files": [{
                    "path": "configs/collaboration_policy.v2.json",
                    "sha256": policy_snapshot["sha256"],
                    "size_bytes": policy_snapshot["size_bytes"],
                    "role": "evidence",
                }],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            validation = {
                "signature": {
                    "verified": True,
                    "signer_pinned": True,
                    "profile": "release-core",
                    "manifest_sha256": manifest_sha,
                    "public_key_fingerprint_sha256": "a" * 64,
                }
            }
            with (
                patch.object(collaboration, "ROOT", root),
                patch.object(collaboration, "POLICY_CONFIG_PATH", policy_path),
                patch.object(signing, "MANIFEST_PATH", manifest_path),
            ):
                signature, _manifest_snapshot = collaboration._verified_policy_signature(
                    policy_path,
                    policy_snapshot,
                    validation,
                )
                self.assertTrue(signature["verified"])
                tampered = dict(policy_snapshot, sha256="b" * 64)
                with self.assertRaisesRegex(
                    CollaborationPolicyError,
                    "policy bytes are not covered",
                ):
                    collaboration._verified_policy_signature(
                        policy_path,
                        tampered,
                        validation,
                    )

    def test_policy_config_rejects_unknown_scoring_fields(self) -> None:
        config = policy_config()
        config["scoring"]["unreviewed_metric"] = 1.0
        with self.assertRaisesRegex(
            CollaborationPolicyError,
            "scoring field membership",
        ):
            build_recommendation(complete_summary(), uniform_request(), config)

    def test_policy_config_rejects_model_semantic_or_cluster_audit_drift(self) -> None:
        semantic_drift = policy_config()
        semantic_drift["model_semantics"]["SepMark"]["message_length"] = 30
        with self.assertRaisesRegex(
            CollaborationPolicyError,
            "model_semantics mismatch",
        ):
            build_recommendation(
                complete_summary(), uniform_request(), semantic_drift
            )

        cluster_drift = policy_config()
        cluster_drift["uncertainty"]["expected_identity_count"] = 256
        with self.assertRaisesRegex(
            CollaborationPolicyError,
            "fixed identity cluster audit mismatch",
        ):
            build_recommendation(
                complete_summary(), uniform_request(), cluster_drift
            )


if __name__ == "__main__":
    unittest.main()
