from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from system.backend import claims
from system.backend import benchmark_evidence


def formal_gate() -> dict:
    return {
        "type": "benchmark_evidence_set.v1",
        "benchmarks": [
            {
                "benchmark_id": benchmark_id,
                "summary_path": contract["summary_path"],
                "results_path": contract["results_path"],
            }
            for benchmark_id, contract in claims.FORMAL_BENCHMARKS.items()
        ],
    }


class BenchmarkEvidenceSetGateTests(unittest.TestCase):
    def create_formal_artifacts(self, root: Path) -> None:
        for contract in claims.FORMAL_BENCHMARKS.values():
            summary_path = root / contract["summary_path"]
            results_path = root / contract["results_path"]
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            results_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps({
                    "schema_version": "benchmark-summary.v2",
                    "status": "complete",
                    "method": contract["method"],
                    "sample_count": contract["sample_count"],
                }),
                encoding="utf-8",
            )
            results_path.write_text("image_id,attack_type,error\n", encoding="utf-8")

    def resolver(self, root: Path):
        def resolve(reference: str | Path) -> Path | None:
            raw = Path(reference)
            if raw.is_absolute() or ".." in raw.parts:
                return None
            return root / raw

        return resolve

    def test_complete_canonical_four_method_set_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_formal_artifacts(root)
            with (
                patch.object(claims, "resolve_logical_path", side_effect=self.resolver(root)),
                patch.object(
                    claims,
                    "benchmark_claim_status",
                    return_value={
                        "claim_valid": True,
                        "claim_status": "evidence_verified",
                    },
                ) as strict_gate,
            ):
                result = claims._benchmark_evidence_set_result(formal_gate())

        self.assertTrue(result["claim_valid"])
        self.assertTrue(result["configuration_valid"])
        self.assertEqual(result["failed_benchmarks"], [])
        self.assertEqual(strict_gate.call_count, 4)
        self.assertTrue(
            all(item["summary_contract"]["complete"] for item in result["benchmarks"].values())
        )

    def test_set_fails_closed_when_member_missing_or_extra(self) -> None:
        gate = formal_gate()
        gate["benchmarks"] = gate["benchmarks"][1:] + [{
            "benchmark_id": "unexpected",
            "summary_path": "reports/unexpected/summary.json",
            "results_path": "reports/unexpected/results.csv",
        }]
        result = claims._benchmark_evidence_set_result(gate)

        self.assertFalse(result["claim_valid"])
        self.assertFalse(result["configuration_valid"])
        self.assertIn("lidmark", result["failed_benchmarks"])
        self.assertIn("missing formal benchmark: lidmark", result["configuration_errors"])
        self.assertIn("unexpected formal benchmark: unexpected", result["configuration_errors"])

    def test_set_rejects_noncanonical_path_even_if_strict_gate_would_pass(self) -> None:
        gate = formal_gate()
        gate["benchmarks"][0]["results_path"] = "reports/copied-lidmark/results.csv"
        with (
            patch.object(claims, "resolve_logical_path", return_value=None),
            patch.object(
                claims,
                "benchmark_claim_status",
                return_value={"claim_valid": True},
            ) as strict_gate,
        ):
            result = claims._benchmark_evidence_set_result(gate)

        self.assertFalse(result["claim_valid"])
        self.assertIn("lidmark", result["failed_benchmarks"])
        self.assertFalse(result["benchmarks"]["lidmark"]["path_contract"])
        strict_gate.assert_not_called()

    def test_set_requires_strict_gate_and_summary_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_formal_artifacts(root)
            waveguard = root / claims.FORMAL_BENCHMARKS["waveguard_full"]["summary_path"]
            summary = json.loads(waveguard.read_text(encoding="utf-8"))
            summary["sample_count"] = 256
            waveguard.write_text(json.dumps(summary), encoding="utf-8")

            def strict_result(_summary, *, summary_path: Path, results_path: Path):
                del _summary, results_path
                return {
                    "claim_valid": "sepmark" not in summary_path.as_posix(),
                    "claim_status": "evidence_verified",
                }

            with (
                patch.object(claims, "resolve_logical_path", side_effect=self.resolver(root)),
                patch.object(claims, "benchmark_claim_status", side_effect=strict_result),
            ):
                result = claims._benchmark_evidence_set_result(formal_gate())

        self.assertFalse(result["claim_valid"])
        self.assertEqual(set(result["failed_benchmarks"]), {"sepmark", "waveguard_full"})
        self.assertFalse(result["benchmarks"]["sepmark"]["claim_valid"])
        self.assertEqual(
            result["benchmarks"]["waveguard_full"]["claim_status"],
            "benchmark_summary_contract_mismatch",
        )
        self.assertFalse(
            result["benchmarks"]["waveguard_full"]["summary_contract"]["sample_count"]
        )

    def test_claims_payload_publishes_umbrella_only_after_set_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_formal_artifacts(root)
            evidence = root / "policy.txt"
            evidence.write_text("reviewed", encoding="utf-8")
            manifest = root / "claims.json"
            manifest.write_text(
                json.dumps({
                    "schema_version": "claims-manifest.v1",
                    "policy": {"performance_claim_id": "performance_results"},
                    "claims": [{
                        "claim_id": "performance_results",
                        "status": "verified",
                        "requested_for_submission": True,
                        "evidence": ["policy.txt"],
                        "gate": formal_gate(),
                    }],
                }),
                encoding="utf-8",
            )
            with (
                patch.object(claims, "CLAIMS_MANIFEST", manifest),
                patch.object(claims, "resolve_logical_path", side_effect=self.resolver(root)),
                patch.object(
                    claims,
                    "benchmark_claim_status",
                    return_value={"claim_valid": True, "claim_status": "evidence_verified"},
                ),
            ):
                payload = claims.claims_payload()

        self.assertTrue(payload["ready_for_claims"])
        performance = payload["claims"][0]
        self.assertTrue(performance["publishable"])
        self.assertTrue(performance["gate_valid"])
        self.assertEqual(
            performance["gate_result"]["schema_version"],
            "benchmark-evidence-set-status.v1",
        )

    def test_repository_n256_claim_is_pinned_to_run_specific_artifacts(self) -> None:
        manifest = json.loads(claims.CLAIMS_MANIFEST.read_text(encoding="utf-8"))
        claim = next(
            item
            for item in manifest["claims"]
            if item.get("claim_id") == "kadnet_protocol_v1_n256"
        )
        prefix = "reports/kadnet-lfw-protocol-v1-n256-s20260603/"
        self.assertTrue(claim["gate"]["summary_path"].startswith(prefix))
        self.assertTrue(claim["gate"]["results_path"].startswith(prefix))
        self.assertTrue(all(path.startswith(prefix) for path in claim["evidence"][:4]))

    def test_repository_performance_claim_uses_canonical_evidence_set(self) -> None:
        manifest = json.loads(claims.CLAIMS_MANIFEST.read_text(encoding="utf-8"))
        claim = next(
            item
            for item in manifest["claims"]
            if item.get("claim_id") == "performance_results"
        )

        self.assertEqual(claim["status"], "verified")
        self.assertTrue(claim["requested_for_submission"])
        self.assertEqual(claim["gate"], formal_gate())

    def test_mea_claim_gate_requires_canonical_signed_n256_matrix(self) -> None:
        gate = {
            "type": "mea_matrix_evidence.v1",
            "run_id": claims.MEA_RUN_ID,
            "directory_path": f"reports/{claims.MEA_RUN_ID}",
        }
        with patch.object(
            claims,
            "validate_mea_matrix_evidence",
            return_value={"valid": True, "status": "verified"},
        ) as validator:
            result = claims._claim_gate_result(gate)
        self.assertTrue(result["claim_valid"])
        self.assertEqual(result["claim_status"], "evidence_verified")
        validator.assert_called_once_with(require_signature=True)

        with patch.object(claims, "validate_mea_matrix_evidence") as validator:
            tampered = claims._claim_gate_result({
                **gate,
                "directory_path": "reports/copied-mea-matrix",
            })
        self.assertFalse(tampered["claim_valid"])
        self.assertEqual(tampered["claim_status"], "mea_gate_contract_mismatch")
        validator.assert_not_called()

    def test_repository_mea_claim_is_bound_to_formal_five_file_bundle(self) -> None:
        manifest = json.loads(claims.CLAIMS_MANIFEST.read_text(encoding="utf-8"))
        claim = next(
            item
            for item in manifest["claims"]
            if item.get("claim_id") == "mea_red_team_protocol"
        )
        prefix = f"reports/{claims.MEA_RUN_ID}/"
        formal = [path for path in claim["evidence"] if path.startswith(prefix)]
        self.assertEqual(
            formal,
            [
                prefix + "dataset_manifest.json",
                prefix + "run_config.json",
                prefix + "raw_results.csv",
                prefix + "progress.json",
                prefix + "summary.json",
            ],
        )
        self.assertEqual(claim["status"], "verified")
        self.assertEqual(
            claim["gate"],
            {
                "type": "mea_matrix_evidence.v1",
                "run_id": claims.MEA_RUN_ID,
                "directory_path": f"reports/{claims.MEA_RUN_ID}",
            },
        )

    def test_collaboration_claim_requires_policy_and_signed_mea_evidence(self) -> None:
        gate = {
            "type": "collaboration_policy_evidence.v2",
            "policy_id": "mea-identity-cluster-deployment-s20260603",
        }
        with (
            patch.object(
                claims,
                "load_policy_evidence",
                return_value=(
                    {"policy_id": gate["policy_id"]},
                    {},
                    {
                        "content_verified": True,
                        "signature_verified": True,
                        "signer_pinned": True,
                        "cells": 16,
                        "rows": 4096,
                        "image_count": 256,
                        "identity_count": 217,
                        "repeated_identity_count": 24,
                        "images_in_repeated_identities": 63,
                        "max_cluster_size": 10,
                        "matrix_validation": {"valid": True, "status": "verified"},
                    },
                    {
                        "image_count": 256,
                        "identity_count": 217,
                        "repeated_identity_count": 24,
                        "images_in_repeated_identities": 63,
                        "max_cluster_size": 10,
                    },
                ),
            ) as policy_validator,
        ):
            result = claims._claim_gate_result(gate)
        self.assertTrue(result["claim_valid"])
        self.assertEqual(result["claim_status"], "evidence_verified")
        policy_validator.assert_called_once_with()

        with patch.object(claims, "load_policy_evidence") as policy_validator:
            tampered = claims._claim_gate_result({
                **gate,
                "policy_id": "unreviewed-policy",
            })
        self.assertFalse(tampered["claim_valid"])
        policy_validator.assert_not_called()

    def test_repository_collaboration_claim_binds_policy_engine_and_api(self) -> None:
        manifest = json.loads(claims.CLAIMS_MANIFEST.read_text(encoding="utf-8"))
        claim = next(
            item
            for item in manifest["claims"]
            if item.get("claim_id") == "collaboration_policy_engine"
        )
        self.assertEqual(claim["status"], "verified")
        self.assertTrue(claim["requested_for_submission"])
        self.assertEqual(
            claim["evidence"][:5],
            [
                "configs/collaboration_policy.v2.json",
                "system/backend/collaboration.py",
                "system/backend/routes.py",
                "system/backend/schemas.py",
                "tests/test_collaboration_policy.py",
            ],
        )
        self.assertEqual(
            claim["gate"],
            {
                "type": "collaboration_policy_evidence.v2",
                "policy_id": "mea-identity-cluster-deployment-s20260603",
            },
        )
        limitations = " ".join(claim["limitations"])
        self.assertIn("fixed LFW n256 MEA sample", limitations)
        self.assertIn("four registered checkpoints", limitations)
        self.assertIn("secondary-embedding threat matrix", limitations)
        self.assertIn("not a cross-dataset generalization claim", limitations)
        self.assertIn("independent deepfake evidence gate", limitations)
        self.assertIn("not combined with MEA scores", limitations)

    def test_simswap_claim_gate_requires_exact_signed_n256_scope(self) -> None:
        gate = {
            "type": "simswap_lfw_evidence.v1",
            "run_id": claims.SIMSWAP_RUN_ID,
            "directory_path": f"reports/{claims.SIMSWAP_RUN_ID}",
            "num_pairs": 256,
            "calibration_pairs": 64,
            "holdout_pairs": 192,
            "holdout_metrics": claims.SIMSWAP_N256_HOLDOUT_METRICS,
            "far_by_negative_control": (
                claims.SIMSWAP_N256_FAR_BY_NEGATIVE_CONTROL
            ),
            "identity_migration": claims.SIMSWAP_N256_IDENTITY_MIGRATION,
            "identity_migration_evidence_scope": (
                claims.SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE
            ),
            "registered_positive_conditioned_on_identity_migration": (
                claims.SIMSWAP_N256_CONDITIONED_REGISTERED_POSITIVE
            ),
        }
        validation = {
            "valid": True,
            "status": "verified",
            "identity_migration_evidence_scope": (
                claims.SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE
            ),
            "model_results": {
                model: {
                    "holdout_tar": {
                        "estimate": metrics["tar"],
                        "wilson_95_low": metrics["tar_wilson_95_low"],
                    },
                    "holdout_far": {
                        "estimate": metrics["far"],
                        "wilson_95_high": metrics["far_wilson_95_high"],
                    },
                    "holdout_far_by_negative_control": (
                        claims.SIMSWAP_N256_FAR_BY_NEGATIVE_CONTROL[model]
                    ),
                    "registered_positive_conditioned_on_identity_migration": (
                        claims.SIMSWAP_N256_CONDITIONED_REGISTERED_POSITIVE[model]
                    ),
                    "identity_migration": {
                        "clean_swap": {
                            "estimate": claims.SIMSWAP_N256_IDENTITY_MIGRATION[
                                "clean_swap_estimate"
                            ],
                            "wilson_95_low": claims.SIMSWAP_N256_IDENTITY_MIGRATION[
                                "clean_swap_wilson_95_low"
                            ],
                        }
                    },
                }
                for model, metrics in claims.SIMSWAP_N256_HOLDOUT_METRICS.items()
            },
        }
        with patch.object(
            claims,
            "validate_simswap_lfw_evidence",
            return_value=validation,
        ) as validator:
            result = claims._claim_gate_result(gate)
        self.assertTrue(result["claim_valid"])
        self.assertEqual(result["claim_status"], "evidence_verified")
        validator.assert_called_once_with(require_signature=True)

        with patch.object(claims, "validate_simswap_lfw_evidence") as validator:
            tampered = claims._claim_gate_result({**gate, "num_pairs": 64})
        self.assertFalse(tampered["claim_valid"])
        self.assertEqual(tampered["claim_status"], "simswap_gate_contract_mismatch")
        validator.assert_not_called()

        metric_tampered = json.loads(json.dumps(validation))
        metric_tampered["model_results"]["KAD-Net"]["holdout_far"][
            "estimate"
        ] = 0.01
        with patch.object(
            claims,
            "validate_simswap_lfw_evidence",
            return_value=metric_tampered,
        ) as validator:
            tampered = claims._claim_gate_result(gate)
        self.assertFalse(tampered["claim_valid"])
        self.assertEqual(tampered["claim_status"], "simswap_evidence_review_required")
        validator.assert_called_once_with(require_signature=True)

        conditioned_tampered = json.loads(json.dumps(validation))
        conditioned_tampered["model_results"]["KAD-Net"][
            "registered_positive_conditioned_on_identity_migration"
        ]["clean_swap_migrated"]["successes"] = 161
        with patch.object(
            claims,
            "validate_simswap_lfw_evidence",
            return_value=conditioned_tampered,
        ) as validator:
            tampered = claims._claim_gate_result(gate)
        self.assertFalse(tampered["claim_valid"])
        self.assertEqual(tampered["claim_status"], "simswap_evidence_review_required")
        validator.assert_called_once_with(require_signature=True)

        scope_tampered = json.loads(json.dumps(validation))
        scope_tampered["identity_migration_evidence_scope"][
            "independent_identity_verifier"
        ] = True
        with patch.object(
            claims,
            "validate_simswap_lfw_evidence",
            return_value=scope_tampered,
        ) as validator:
            tampered = claims._claim_gate_result(gate)
        self.assertFalse(tampered["claim_valid"])
        self.assertEqual(tampered["claim_status"], "simswap_evidence_review_required")
        validator.assert_called_once_with(require_signature=True)

        control_tampered = json.loads(json.dumps(validation))
        control_tampered["model_results"]["KAD-Net"][
            "holdout_far_by_negative_control"
        ]["wrong_message"]["wilson_95_high"] = 0.00662502
        with patch.object(
            claims,
            "validate_simswap_lfw_evidence",
            return_value=control_tampered,
        ) as validator:
            tampered = claims._claim_gate_result(gate)
        self.assertFalse(tampered["claim_valid"])
        self.assertEqual(tampered["claim_status"], "simswap_evidence_review_required")
        validator.assert_called_once_with(require_signature=True)

    def test_repository_deepfake_claim_binds_real_n256_evidence_closure(self) -> None:
        manifest = json.loads(claims.CLAIMS_MANIFEST.read_text(encoding="utf-8"))
        claim = next(
            item
            for item in manifest["claims"]
            if item.get("claim_id") == "deepfake_robustness"
        )
        prefix = f"reports/{claims.SIMSWAP_RUN_ID}/"
        formal = [path for path in claim["evidence"] if path.startswith(prefix)]
        self.assertEqual(
            formal,
            [
                prefix + "pair_manifest.json",
                prefix + "message_registry.json",
                prefix + "run_config.json",
                prefix + "identity_embeddings.csv",
                prefix + "results.csv",
                prefix + "progress.json",
                prefix + "assets_manifest.json",
                prefix + "summary.json",
            ],
        )
        self.assertEqual(claim["status"], "verified")
        self.assertTrue(claim["requested_for_submission"])
        self.assertEqual(claim["gate"]["num_pairs"], 256)
        self.assertEqual(claim["gate"]["holdout_pairs"], 192)
        self.assertEqual(
            claim["gate"]["holdout_metrics"],
            claims.SIMSWAP_N256_HOLDOUT_METRICS,
        )
        self.assertEqual(
            claim["gate"]["far_by_negative_control"],
            claims.SIMSWAP_N256_FAR_BY_NEGATIVE_CONTROL,
        )
        self.assertEqual(
            claim["gate"][
                "registered_positive_conditioned_on_identity_migration"
            ],
            claims.SIMSWAP_N256_CONDITIONED_REGISTERED_POSITIVE,
        )
        self.assertEqual(
            claim["gate"]["identity_migration_evidence_scope"],
            claims.SIMSWAP_IDENTITY_MIGRATION_EVIDENCE_SCOPE,
        )
        smoke = next(
            item
            for item in manifest["claims"]
            if item.get("claim_id") == "deepfake_robustness_n64_smoke"
        )
        self.assertFalse(smoke["requested_for_submission"])
        self.assertEqual(smoke["status"], "superseded_smoke")

    def test_claims_payload_rejects_wrong_schema_and_missing_umbrella(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "claims.json"
            manifest.write_text(
                json.dumps({
                    "schema_version": "attacker.v0",
                    "policy": {},
                    "claims": [{
                        "claim_id": "forged",
                        "status": "verified",
                        "requested_for_submission": True,
                        "evidence": [],
                    }],
                }),
                encoding="utf-8",
            )
            with patch.object(claims, "CLAIMS_MANIFEST", manifest):
                payload = claims.claims_payload()
        self.assertFalse(payload["ready_for_claims"])
        self.assertEqual(payload["status"], "manifest_invalid")

    def test_claims_payload_rejects_non_object_claim_and_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "claims.json"
            manifest.write_text(
                json.dumps({
                    "schema_version": "claims-manifest.v1",
                    "policy": {"performance_claim_id": "performance_results"},
                    "claims": [None],
                }),
                encoding="utf-8",
            )
            with patch.object(claims, "CLAIMS_MANIFEST", manifest):
                malformed = claims.claims_payload()
            self.assertEqual(malformed["status"], "manifest_invalid")

            manifest.write_bytes(b"\xff\xfe\x00")
            with patch.object(claims, "CLAIMS_MANIFEST", manifest):
                invalid_encoding = claims.claims_payload()
            self.assertEqual(invalid_encoding["status"], "manifest_invalid")

            manifest.write_text(
                '{"schema_version":"claims-manifest.v1","metric":NaN}',
                encoding="utf-8",
            )
            with patch.object(claims, "CLAIMS_MANIFEST", manifest):
                nonfinite = claims.claims_payload()
            self.assertEqual(nonfinite["status"], "manifest_invalid")

    def test_claims_payload_contains_read_failures_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "claims.json"
            manifest.write_text(json.dumps({
                "schema_version": "claims-manifest.v1",
                "policy": {"performance_claim_id": "performance_results"},
                "claims": [{
                    "claim_id": "performance_results",
                    "status": "verified",
                    "requested_for_submission": True,
                    "evidence": ["reports/policy.txt"],
                    "gate": formal_gate(),
                }],
            }), encoding="utf-8")
            with (
                patch.object(claims, "CLAIMS_MANIFEST", manifest),
                patch.object(
                    claims,
                    "resolve_logical_path",
                    side_effect=OSError("simulated I/O failure"),
                ),
            ):
                payload = claims.claims_payload()
        self.assertFalse(payload["ready_for_claims"])
        self.assertEqual(payload["status"], "review_required")
        self.assertFalse(payload["claims"][0]["evidence_complete"])
        self.assertFalse(payload["claims"][0]["gate_valid"])

    def test_benchmark_gate_detects_artifact_replacement_during_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.json"
            results = root / "results.csv"
            summary.write_text('{"status":"complete"}', encoding="utf-8")
            results.write_text("image_id,attack_type\n", encoding="utf-8")
            calls: dict[Path, int] = {}

            def identity(path: Path) -> tuple[int, int, int, int, int]:
                resolved = path.resolve()
                calls[resolved] = calls.get(resolved, 0) + 1
                marker = 1 if resolved == results.resolve() and calls[resolved] > 1 else 0
                return (1, 1 + marker, path.stat().st_size, 1, 1)

            with (
                patch.object(claims, "resolve_logical_path", side_effect=[summary, results]),
                patch.object(claims, "_file_identity", side_effect=identity),
                patch.object(
                    claims,
                    "benchmark_claim_status",
                    return_value={"claim_valid": True, "claim_status": "evidence_verified"},
                ),
            ):
                result = claims._benchmark_gate_result({
                    "summary_path": "reports/summary.json",
                    "results_path": "reports/results.csv",
                })
        self.assertFalse(result["claim_valid"])
        self.assertEqual(
            result["claim_status"],
            "benchmark_artifacts_changed_during_validation",
        )

    def test_list_dataset_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "dataset.json"
            manifest.write_text("[]", encoding="utf-8")
            self.assertFalse(
                benchmark_evidence._load_dataset_manifest(manifest, 1)
            )


if __name__ == "__main__":
    unittest.main()
