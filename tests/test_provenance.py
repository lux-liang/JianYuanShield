from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from system.backend import provenance
from system.evaluation.adapters.base import DecodeResult, EmbeddingResult
from system.scripts import calibrate_provenance_threshold as calibration


class FakeAdapter:
    name = "FakeMark"
    message_length = 8
    checkpoint = None
    available = True
    blocker = None

    def encode(self, image: np.ndarray, message: np.ndarray) -> EmbeddingResult:
        output = image.copy()
        flat = output[:, :, 0].reshape(-1)
        flat[: self.message_length] = (flat[: self.message_length] & 0xFE) | message
        return EmbeddingResult(output, message, {"model": self.name})

    def decode(self, image: np.ndarray) -> DecodeResult:
        bits = (image[:, :, 0].reshape(-1)[: self.message_length] & 1).astype(np.uint8)
        return DecodeResult(bits, {"model": self.name, "decoder": "lsb-test"})


def sample_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def complete_calibration_payload(
    checkpoint_sha256: str,
    verification_threshold: float = 0.9,
) -> dict[str, object]:
    model = "FakeMark"
    seed = 17
    attacks = ["clean"]
    identifiers = ["alice/a.png", "bob/b.png"]
    assignments = {identifiers[0]: "calibration", identifiers[1]: "holdout"}
    negative_below_threshold = np.nextafter(verification_threshold, 0.0).item()
    rows: list[dict[str, object]] = []
    for identifier in identifiers:
        split = assignments[identifier]
        identity = calibration.identity_sha256(identifier)
        scores = {
            "registered_roundtrip": 1.0,
            "unwatermarked": negative_below_threshold if split == "calibration" else 0.5,
            "wrong_message": negative_below_threshold if split == "calibration" else 0.5,
        }
        for control in calibration.CONTROLS:
            rows.append(calibration._make_sample(
                model=model,
                seed=seed,
                identifier=identifier,
                identity_hash=identity,
                split=split,
                attack_id="clean",
                control=control,
                score=scores[control],
                registered_hash="1" * 64,
                embedded_hash=None if control == "unwatermarked" else "2" * 64,
            ))
    rows.sort(key=lambda row: (row["image_id"], row["attack_id"], calibration.CONTROLS.index(row["control"])))
    threshold, selection, calibration_metrics = calibration.select_threshold(rows, 0.0)
    assert threshold == verification_threshold
    dataset_files = [
        {
            "image_id": identifier,
            "identity_sha256": calibration.identity_sha256(identifier),
            "split": assignments[identifier],
            "size_bytes": 128,
            "sha256": ("3" if index == 0 else "4") * 64,
        }
        for index, identifier in enumerate(identifiers)
    ]
    dataset = {
        "schema_version": "threshold-calibration-dataset.v1",
        "image_root": "data/test",
        "selection": "fixture",
        "identity_derivation": calibration.IDENTITY_DERIVATION,
        "split_policy": "identity-disjoint-fixture",
        "seed": seed,
        "sample_count": len(dataset_files),
        "files_digest_sha256": calibration.canonical_sha256(dataset_files),
        "files": dataset_files,
    }
    return {
        "schema_version": "threshold-calibration.v1",
        "status": "complete",
        "model": model,
        "checkpoint": "weights/fake.ckpt",
        "checkpoint_sha256": checkpoint_sha256,
        "protocol_version": "evaluation-protocol.v1",
        "protocol_path": "configs/evaluation_protocol.v1.json",
        "protocol_sha256": "5" * 64,
        "attack_ids": attacks,
        "attack_contract_sha256": "6" * 64,
        "seed": seed,
        "target_false_accept_rate": 0.0,
        "dataset_manifest": dataset,
        "dataset_manifest_sha256": calibration.canonical_sha256(dataset),
        "threshold": threshold,
        "threshold_selection": selection,
        "calibration_metrics": calibration_metrics,
        "metrics": calibration._decision_metrics(rows, threshold, "holdout"),
        "coverage": calibration.coverage_report(rows, identifiers, assignments, attacks),
        "errors": [],
        "samples": rows,
    }


def calibration_gate(payload: dict[str, object]) -> bool:
    """Re-hash a supplied artifact so tests exercise semantic validation."""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        artifact = root / "threshold_calibration.json"
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        metrics = payload["metrics"]
        assert isinstance(metrics, dict)
        manifest = root / "WEIGHT_MANIFEST.json"
        manifest.write_text(json.dumps({
            "items": [{
                "model": payload["model"],
                "sha256": payload["checkpoint_sha256"],
                "status": "verified",
                "verification_threshold": payload["threshold"],
                "calibration_artifact": artifact.name,
                "calibration_artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "calibration_positive_samples": metrics["positive_samples"],
                "calibration_negative_samples": metrics["negative_samples"],
                "calibration_false_accept_rate": metrics["false_accept_rate"],
            }],
        }), encoding="utf-8")
        with patch.object(provenance, "MANIFEST", manifest):
            return provenance._checkpoint_calibrated(
                str(payload["model"]),
                str(payload["checkpoint_sha256"]),
                payload["threshold"],
            )


class ProvenanceTests(unittest.TestCase):
    def test_checkpoint_must_be_explicitly_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "fake.ckpt"
            checkpoint.write_bytes(b"registered-checkpoint")
            checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            manifest = root / "WEIGHT_MANIFEST.json"
            manifest.write_text(
                '{"items":[{"model":"FakeMark","file":"fake.ckpt","sha256":"'
                + checkpoint_sha256
                + '","status":"verified"}]}',
                encoding="utf-8",
            )
            with patch.object(provenance, "MANIFEST", manifest):
                self.assertTrue(provenance._checkpoint_registered("FakeMark", checkpoint_sha256))
                self.assertFalse(provenance._checkpoint_registered("FakeMark", "b" * 64))
                self.assertFalse(provenance._checkpoint_registered("OtherMark", checkpoint_sha256))
                checkpoint.write_bytes(b"tampered")
                self.assertFalse(provenance._checkpoint_registered("FakeMark", checkpoint_sha256))

    def test_production_requires_provenance_secret(self) -> None:
        production = SimpleNamespace(mode="production", provenance_secret=None)
        with patch.object(provenance, "settings", production):
            with self.assertRaises(provenance.ProvenanceCapabilityError):
                provenance.protect_content(sample_png(), creator_ref="creator", model="FakeMark")

    def test_secret_derived_message_is_stable_and_content_scoped(self) -> None:
        configured = SimpleNamespace(provenance_secret="s" * 32)
        with patch.object(provenance, "settings", configured):
            first, scheme = provenance._message_for_record("a" * 32, "FakeMark", 64)
            repeated, _ = provenance._message_for_record("a" * 32, "FakeMark", 64)
            other, _ = provenance._message_for_record("b" * 32, "FakeMark", 64)
        self.assertEqual(scheme, "hmac-sha256-v1")
        np.testing.assert_array_equal(first, repeated)
        self.assertFalse(np.array_equal(first, other))

    def test_complete_calibration_fixture_passes_semantic_gate(self) -> None:
        payload = complete_calibration_payload("a" * 64)
        self.assertTrue(calibration_gate(payload))

    def test_claim_requires_pinned_signed_weight_manifest(self) -> None:
        payload = {
            "model": "FakeMark",
            "checkpoint_sha256": "a" * 64,
            "verification_threshold": 0.9,
        }
        signature = {"signed": True}
        configured = SimpleNamespace(evidence_public_key_fingerprint="b" * 64)
        def evaluate(weight_manifest_trusted: bool) -> bool:
            with (
                patch.object(provenance, "settings", configured),
                patch.object(provenance, "_checkpoint_registered", return_value=True),
                patch.object(provenance, "_checkpoint_calibrated", return_value=True),
                patch.object(provenance, "_weight_manifest_trusted", return_value=weight_manifest_trusted),
                patch.object(provenance, "_provenance_secret_ready", return_value=True),
                patch.object(provenance, "verify_payload_signature", return_value=True),
                patch.object(provenance, "signature_public_key_fingerprint", return_value="b" * 64),
            ):
                return provenance._claim_valid(payload, signature)

        self.assertFalse(evaluate(False))
        self.assertTrue(evaluate(True))

    def test_weight_manifest_trust_requires_checkpoint_and_calibration_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "fake.ckpt"
            calibration_artifact = root / "calibration.json"
            checkpoint.write_bytes(b"checkpoint")
            calibration_artifact.write_text("{}", encoding="utf-8")
            checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            manifest = root / "WEIGHT_MANIFEST.json"
            manifest.write_text(json.dumps({
                "items": [{
                    "model": "FakeMark",
                    "file": checkpoint.name,
                    "sha256": checkpoint_sha256,
                    "status": "verified",
                    "calibration_artifact": calibration_artifact.name,
                }],
            }), encoding="utf-8")
            evidence_manifest = root / "evidence-manifest.json"

            def record(path: Path) -> dict[str, object]:
                return {
                    "path": provenance.logical_path(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            records = [record(path) for path in (manifest, checkpoint, calibration_artifact)]
            evidence_manifest.write_text(json.dumps({"files": records}), encoding="utf-8")
            fingerprint = "d" * 64
            configured = SimpleNamespace(evidence_public_key_fingerprint=fingerprint)
            signature = {
                "verified": True,
                "public_key_fingerprint_sha256": fingerprint,
            }
            with (
                patch.object(provenance, "MANIFEST", manifest),
                patch.object(provenance, "EVIDENCE_MANIFEST_PATH", evidence_manifest),
                patch.object(provenance, "settings", configured),
                patch.object(provenance, "verify_evidence_bundle", return_value=signature),
            ):
                self.assertTrue(
                    provenance._weight_manifest_trusted("FakeMark", checkpoint_sha256)
                )
                evidence_manifest.write_text(
                    json.dumps({"files": records[:-1]}),
                    encoding="utf-8",
                )
                self.assertFalse(
                    provenance._weight_manifest_trusted("FakeMark", checkpoint_sha256)
                )

    def test_calibration_identity_split_leakage_fails_closed(self) -> None:
        payload = copy.deepcopy(complete_calibration_payload("a" * 64))
        dataset = payload["dataset_manifest"]
        assert isinstance(dataset, dict)
        files = dataset["files"]
        assert isinstance(files, list)
        calibration_identity = files[0]["identity_sha256"]
        leaked_image = files[1]["image_id"]
        files[1]["identity_sha256"] = calibration_identity
        for sample in payload["samples"]:
            if sample["image_id"] == leaked_image:
                sample["identity_sha256"] = calibration_identity
        dataset["files_digest_sha256"] = calibration.canonical_sha256(files)
        payload["dataset_manifest_sha256"] = calibration.canonical_sha256(dataset)
        self.assertFalse(calibration_gate(payload))

    def test_calibration_forged_identity_hash_fails_closed(self) -> None:
        payload = copy.deepcopy(complete_calibration_payload("a" * 64))
        dataset = payload["dataset_manifest"]
        assert isinstance(dataset, dict)
        files = dataset["files"]
        assert isinstance(files, list)
        target_image = files[0]["image_id"]
        files[0]["identity_sha256"] = "f" * 64
        for sample in payload["samples"]:
            if sample["image_id"] == target_image:
                sample["identity_sha256"] = "f" * 64
        dataset["files_digest_sha256"] = calibration.canonical_sha256(files)
        payload["dataset_manifest_sha256"] = calibration.canonical_sha256(dataset)
        self.assertFalse(calibration_gate(payload))

    def test_calibration_forged_holdout_metrics_fail_closed(self) -> None:
        payload = copy.deepcopy(complete_calibration_payload("a" * 64))
        metrics = payload["metrics"]
        assert isinstance(metrics, dict)
        metrics["false_accepts"] = 1
        metrics["true_rejects"] = 1
        metrics["false_accept_rate"] = 0.5
        self.assertFalse(calibration_gate(payload))

    def test_calibration_missing_sample_with_forged_coverage_fails_closed(self) -> None:
        payload = copy.deepcopy(complete_calibration_payload("a" * 64))
        removed = payload["samples"].pop()
        coverage = payload["coverage"]
        assert isinstance(coverage, dict)
        coverage["expected_rows"] -= 1
        coverage["actual_rows"] -= 1
        counter = f"{removed['split']}:{removed['control']}"
        coverage["expected_by_split_control"][counter] -= 1
        coverage["actual_by_split_control"][counter] -= 1
        coverage["complete"] = True
        self.assertFalse(calibration_gate(payload))

    def test_calibration_tampered_threshold_selection_fails_closed(self) -> None:
        payload = copy.deepcopy(complete_calibration_payload("a" * 64))
        selection = payload["threshold_selection"]
        assert isinstance(selection, dict)
        selection["eligible_candidate_count"] += 1
        selection["selected_false_accept_rate"] = 0.25
        self.assertFalse(calibration_gate(payload))

    def test_calibration_nonfinite_json_constant_fails_closed(self) -> None:
        payload = copy.deepcopy(complete_calibration_payload("a" * 64))
        dataset = payload["dataset_manifest"]
        assert isinstance(dataset, dict)
        files = dataset["files"]
        assert isinstance(files, list)
        files[0]["size_bytes"] = float("nan")
        self.assertFalse(calibration_gate(payload))

    def test_protect_then_verify_persists_identity_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            database = root / "provenance.sqlite3"
            with (
                patch.object(provenance, "ASSETS", assets),
                patch.object(provenance, "_database_path", return_value=database),
                patch.object(provenance, "_get_adapter", return_value=FakeAdapter()),
                patch.object(
                    provenance,
                    "_signature",
                    return_value={"status": "not_configured", "signed": False},
                ),
            ):
                protected = provenance.protect_content(
                    sample_png(),
                    creator_ref="creator-001",
                    model="FakeMark",
                )
                self.assertFalse(protected["claim_valid"])
                self.assertEqual(protected["evidence_status"], "operational_unverified")
                self.assertEqual(protected["creator_ref"], "creator-001")
                self.assertRegex(protected["message_sha256"], r"^[0-9a-f]{64}$")
                self.assertFalse(protected["privacy"]["original_persisted"])
                protected_bytes = base64.b64decode(protected["protected_image"]["png_base64"])

                verified = provenance.verify_content(
                    protected_bytes,
                    content_id=protected["content_id"],
                )
                self.assertTrue(verified["verified"])
                self.assertFalse(verified["claim_valid"])
                self.assertEqual(verified["bit_accuracy"], 1.0)
                self.assertEqual(verified["creator_ref"], "creator-001")
                self.assertEqual(
                    verified["message_sha256"],
                    protected["message_sha256"],
                )

                record = provenance.get_provenance_record(protected["content_id"])
                self.assertIsNotNone(record)
                self.assertEqual(record["protected_sha256"], protected["protected_sha256"])

    def test_signed_checkpoint_binding_unlocks_formal_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "fake.ckpt"
            checkpoint.write_bytes(b"test-only-checkpoint")
            checkpoint_sha256 = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            private_key = Ed25519PrivateKey.generate()
            private_key_path = root / "evidence-private.pem"
            private_key_path.write_bytes(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            public_der = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            fingerprint = hashlib.sha256(public_der).hexdigest()
            calibration = root / "threshold_calibration.json"
            calibration_payload = complete_calibration_payload(
                checkpoint_sha256,
                verification_threshold=0.875,
            )
            calibration_text = json.dumps(calibration_payload)
            calibration.write_text(calibration_text, encoding="utf-8")
            calibration_sha256 = hashlib.sha256(calibration.read_bytes()).hexdigest()
            manifest = root / "WEIGHT_MANIFEST.json"
            manifest.write_text(
                '{"items":[{"model":"FakeMark","sha256":"'
                + checkpoint_sha256
                + '","file":"fake.ckpt","status":"verified","verification_threshold":0.875,'
                + '"calibration_artifact":"threshold_calibration.json",'
                + '"calibration_artifact_sha256":"'
                + calibration_sha256
                + '","calibration_positive_samples":1,'
                + '"calibration_negative_samples":2,'
                + '"calibration_false_accept_rate":0.0}]}',
                encoding="utf-8",
            )
            adapter = FakeAdapter()
            adapter.checkpoint = str(checkpoint)
            configured = SimpleNamespace(
                mode="real_inference",
                provenance_secret="s" * 32,
                evidence_private_key=str(private_key_path),
                evidence_public_key_fingerprint=fingerprint,
                max_image_pixels=16_000_000,
                provenance_db=None,
                audit_anchor=None,
                content_producer="JianYuanShield-VPSG",
                creator_challenge_ttl_seconds=300,
            )
            creator_private = Ed25519PrivateKey.generate()
            creator_public_pem = creator_private.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("ascii")
            formal_sample_buffer = io.BytesIO()
            Image.new("RGB", (256, 256), (20, 40, 60)).save(
                formal_sample_buffer,
                format="PNG",
            )
            formal_sample = formal_sample_buffer.getvalue()
            with (
                patch.object(provenance, "ASSETS", root / "assets"),
                patch.object(provenance, "_database_path", return_value=root / "provenance.sqlite3"),
                patch.object(provenance, "_get_adapter", return_value=adapter),
                patch.object(provenance, "MANIFEST", manifest),
                patch.object(provenance, "settings", configured),
                patch.object(provenance.audit_ledger, "settings", configured),
                patch("system.backend.creator_identity.settings", configured),
                patch("system.backend.aigc_labeling.settings", configured),
                patch.object(provenance, "_weight_manifest_trusted", return_value=True),
            ):
                challenge = provenance.create_creator_challenge(
                    creator_public_key_pem=creator_public_pem,
                    creator_ref="creator-signed",
                    model="FakeMark",
                    image_sha256=hashlib.sha256(formal_sample).hexdigest(),
                )
                creator_signature = base64.b64encode(
                    creator_private.sign(
                        base64.b64decode(challenge["signing_message_base64"])
                    )
                ).decode("ascii")
                protected = provenance.protect_content(
                    formal_sample,
                    creator_ref="creator-signed",
                    model="FakeMark",
                    challenge_id=challenge["challenge_id"],
                    creator_signature_base64=creator_signature,
                    aigc_label="1",
                )
                self.assertTrue(protected["claim_valid"])
                self.assertTrue(protected["creator_identity_verified"])
                self.assertTrue(protected["aigc_labeling"]["producer_seal_trusted"])
                self.assertTrue(protected["audit_ledger"]["trusted"])
                self.assertTrue(protected["checkpoint_calibrated"])
                self.assertEqual(protected["verification_threshold"], 0.875)
                protected_bytes = base64.b64decode(protected["protected_image"]["png_base64"])
                verified = provenance.verify_content(protected_bytes, content_id=protected["content_id"])
                self.assertTrue(verified["verified"])
                self.assertTrue(verified["claim_valid"])
                self.assertEqual(verified["verification_threshold"], 0.875)
                self.assertTrue(verified["aigc_metadata_intact"])

                metadata_located = provenance.verify_content(protected_bytes)
                self.assertEqual(
                    metadata_located["source_locator"],
                    "trusted_gb45438_metadata",
                )
                self.assertTrue(metadata_located["claim_valid"])

                credential_bytes = base64.b64decode(
                    protected["source_credential"]["json_base64"]
                )
                sidecar_located = provenance.verify_content(
                    protected_bytes,
                    source_credential_bytes=credential_bytes,
                )
                self.assertEqual(sidecar_located["source_locator"], "signed_sidecar")
                self.assertTrue(sidecar_located["claim_valid"])

                tampered_credential = json.loads(credential_bytes)
                tampered_credential["content_id"] = "f" * 32
                with self.assertRaisesRegex(
                    provenance.ProvenanceCapabilityError,
                    "contract|signature",
                ):
                    provenance.verify_content(
                        protected_bytes,
                        source_credential_bytes=json.dumps(tampered_credential).encode("utf-8"),
                    )

                record = provenance.get_provenance_record(protected["content_id"])
                self.assertTrue(record["claim_valid"])
                self.assertTrue(record["creator_identity_verified"])
                self.assertTrue(record["audit_ledger"]["trusted"])

                calibration.write_text("tampered", encoding="utf-8")
                self.assertFalse(
                    provenance.get_provenance_record(protected["content_id"])["claim_valid"]
                )
                degraded = provenance.verify_content(
                    protected_bytes,
                    content_id=protected["content_id"],
                )
                self.assertFalse(degraded["parent_record_claim_valid"])
                self.assertFalse(degraded["claim_valid"])
                calibration.write_text(calibration_text, encoding="utf-8")
                self.assertTrue(
                    provenance.get_provenance_record(protected["content_id"])["claim_valid"]
                )

                checkpoint.write_bytes(b"different-checkpoint-bytes")
                with self.assertRaisesRegex(
                    provenance.ProvenanceCapabilityError,
                    "runtime adapter checkpoint",
                ):
                    provenance.verify_content(
                        protected_bytes,
                        content_id=protected["content_id"],
                    )
                checkpoint.write_bytes(b"test-only-checkpoint")

                revocation_intent = provenance.create_revocation_intent(
                    protected["content_id"],
                    reason_code="creator_request",
                )
                revocation_signature = base64.b64encode(
                    creator_private.sign(
                        base64.b64decode(
                            revocation_intent["signing_message_base64"]
                        )
                    )
                ).decode("ascii")
                revoked = provenance.revoke_content(
                    protected["content_id"],
                    intent_id=revocation_intent["intent_id"],
                    creator_signature_base64=revocation_signature,
                )
                self.assertTrue(revoked["revoked"])
                self.assertFalse(revoked["claim_valid"])
                revoked_record = provenance.get_provenance_record(
                    protected["content_id"]
                )
                self.assertTrue(revoked_record["revocation"]["revoked"])
                self.assertFalse(revoked_record["claim_valid"])
                verified_after_revocation = provenance.verify_content(
                    protected_bytes,
                    content_id=protected["content_id"],
                )
                self.assertTrue(verified_after_revocation["verified"])
                self.assertTrue(verified_after_revocation["parent_record_revoked"])
                self.assertFalse(verified_after_revocation["claim_valid"])
                with self.assertRaisesRegex(
                    provenance.ProvenanceCapabilityError,
                    "already revoked|already used",
                ):
                    provenance.revoke_content(
                        protected["content_id"],
                        intent_id=revocation_intent["intent_id"],
                        creator_signature_base64=revocation_signature,
                    )

                # A valid-looking database flag cannot replace signature verification.
                with provenance._database() as connection:
                    stored = connection.execute(
                        "SELECT record_json FROM provenance_records WHERE content_id = ?",
                        (protected["content_id"],),
                    ).fetchone()[0]
                    tampered = json.loads(stored)
                    tampered["creator_ref"] = "different-creator"
                    connection.execute(
                        "UPDATE provenance_records SET record_json = ? WHERE content_id = ?",
                        (json.dumps(tampered), protected["content_id"]),
                    )
                self.assertFalse(
                    provenance.get_provenance_record(protected["content_id"])["claim_valid"]
                )
                with self.assertRaises(provenance.ProvenanceCapabilityError):
                    provenance.verify_content(
                        protected_bytes,
                        content_id=protected["content_id"],
                    )

    def test_unknown_content_is_not_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                provenance,
                "_database_path",
                return_value=Path(directory) / "provenance.sqlite3",
            ):
                with self.assertRaises(KeyError):
                    provenance.verify_content(sample_png(), content_id="0" * 32)


if __name__ == "__main__":
    unittest.main()
