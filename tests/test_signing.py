from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from system.backend import signing


class SigningTests(unittest.TestCase):
    def test_private_key_creation_is_atomic_private_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "keys" / "evidence.pem"
            self.assertEqual(signing.generate_private_key(key_path), key_path)
            self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                signing.generate_private_key(key_path)

            dangling = root / "dangling.pem"
            dangling.symlink_to(root / "missing-target.pem")
            with self.assertRaises(FileExistsError):
                signing.generate_private_key(dangling)

    def test_canonical_json_is_order_independent(self) -> None:
        self.assertEqual(signing.canonical_json({"b": 2, "a": 1}), signing.canonical_json({"a": 1, "b": 2}))

    def test_signature_detects_content_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "report.json"
            evidence.write_text('{"value":1}', encoding="utf-8")
            private = Ed25519PrivateKey.generate()
            manifest = {
                "schema_version": "evidence-manifest.v1",
                "profile": "scoped",
                "hash_algorithm": "sha256",
                "signature_algorithm": "ed25519",
                "files": [{
                    "path": "report.json",
                    "size_bytes": evidence.stat().st_size,
                    "sha256": signing.sha256_file(evidence),
                    "role": "evidence",
                }],
            }
            manifest_path = root / "manifest.json"
            signature_path = root / "manifest.sig"
            public_path = root / "public.pem"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            import base64
            signature_path.write_text(
                base64.b64encode(private.sign(signing.canonical_json(manifest))).decode("ascii"),
                encoding="ascii",
            )
            public_path.write_bytes(private.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            with patch.object(signing, "ROOT", root):
                valid = signing.verify_evidence_bundle(
                    manifest_path=manifest_path,
                    signature_path=signature_path,
                    public_key_path=public_path,
                )
                self.assertTrue(valid["verified"])
                evidence.write_text('{"value":2}', encoding="utf-8")
                invalid = signing.verify_evidence_bundle(
                    manifest_path=manifest_path,
                    signature_path=signature_path,
                    public_key_path=public_path,
                )
                self.assertFalse(invalid["verified"])
                self.assertEqual(invalid["status"], "content_mismatch")

    def test_release_signature_rejects_incomplete_membership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            included = root / "included.json"
            omitted = root / "required.json"
            included.write_text("{}", encoding="utf-8")
            omitted.write_text("{}", encoding="utf-8")
            private = Ed25519PrivateKey.generate()
            manifest = {
                "schema_version": "evidence-manifest.v1",
                "profile": "release",
                "hash_algorithm": "sha256",
                "signature_algorithm": "ed25519",
                "files": [{
                    "path": "included.json",
                    "size_bytes": included.stat().st_size,
                    "sha256": signing.sha256_file(included),
                    "role": "evidence",
                }],
            }
            manifest_path = root / "manifest.json"
            signature_path = root / "manifest.sig"
            public_path = root / "public.pem"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            import base64
            signature_path.write_text(
                base64.b64encode(private.sign(signing.canonical_json(manifest))).decode("ascii"),
                encoding="ascii",
            )
            public_path.write_bytes(private.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            with (
                patch.object(signing, "ROOT", root),
                patch.object(
                    signing,
                    "default_evidence_files",
                    return_value=[included, omitted],
                ),
            ):
                result = signing.verify_evidence_bundle(
                    manifest_path=manifest_path,
                    signature_path=signature_path,
                    public_key_path=public_path,
                )
            self.assertFalse(result["verified"])
            self.assertEqual(result["status"], "content_mismatch")
            self.assertIn(
                "required.json",
                {item.get("path") for item in result["mismatches"]},
            )

    def test_release_signature_rejects_extra_member_and_wrong_role(self) -> None:
        import base64

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            required = root / "required.json"
            extra = root / "extra.json"
            required.write_text("{}", encoding="utf-8")
            extra.write_text("{}", encoding="utf-8")
            private = Ed25519PrivateKey.generate()
            manifest_path = root / "manifest.json"
            signature_path = root / "manifest.sig"
            public_path = root / "public.pem"
            public_path.write_bytes(private.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))

            def verify(items: list[dict]) -> dict:
                manifest = {
                    "schema_version": "evidence-manifest.v1",
                    "profile": "release-core",
                    "hash_algorithm": "sha256",
                    "signature_algorithm": "ed25519",
                    "files": items,
                }
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                signature_path.write_text(
                    base64.b64encode(
                        private.sign(signing.canonical_json(manifest))
                    ).decode("ascii"),
                    encoding="ascii",
                )
                with (
                    patch.object(signing, "ROOT", root),
                    patch.object(
                        signing,
                        "default_evidence_files",
                        return_value=[required],
                    ),
                ):
                    return signing.verify_evidence_bundle(
                        manifest_path=manifest_path,
                        signature_path=signature_path,
                        public_key_path=public_path,
                    )

            required_item = {
                "path": "required.json",
                "size_bytes": required.stat().st_size,
                "sha256": signing.sha256_file(required),
                "role": "evidence",
            }
            extra_item = {
                "path": "extra.json",
                "size_bytes": extra.stat().st_size,
                "sha256": signing.sha256_file(extra),
                "role": "evidence",
            }
            extra_result = verify([required_item, extra_item])
            self.assertFalse(extra_result["verified"])
            self.assertIn(
                "unexpected_manifest_member",
                {item.get("actual") for item in extra_result["mismatches"]},
            )

            wrong_role_result = verify([
                {**required_item, "role": "checkpoint"},
            ])
            self.assertFalse(wrong_role_result["verified"])
            self.assertIn(
                {"path": "required.json", "expected": "evidence", "actual": "checkpoint"},
                wrong_role_result["mismatches"],
            )

    def test_formal_signing_requires_pinned_key_and_preserves_core_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            key_path = root / "key.pem"
            private = Ed25519PrivateKey.generate()
            key_path.write_bytes(private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            fingerprint = signing._public_key_fingerprint(private.public_key())
            current_dir = root / "current"
            core_dir = root / "core"
            path_patches = (
                patch.object(signing, "ROOT", root),
                patch.object(signing, "MANIFEST_PATH", current_dir / "manifest.json"),
                patch.object(signing, "SIGNATURE_PATH", current_dir / "manifest.sig"),
                patch.object(signing, "PUBLIC_KEY_PATH", current_dir / "public.pem"),
                patch.object(signing, "CORE_MANIFEST_PATH", core_dir / "manifest.json"),
                patch.object(signing, "CORE_SIGNATURE_PATH", core_dir / "manifest.sig"),
                patch.object(signing, "CORE_PUBLIC_KEY_PATH", core_dir / "public.pem"),
                patch.object(signing, "CORE_SIGNATURE_DIR", core_dir),
                patch.object(signing, "default_evidence_files", return_value=[evidence]),
                patch(
                    "system.backend.settings.settings",
                    SimpleNamespace(evidence_public_key_fingerprint=fingerprint),
                ),
            )
            with ExitStack() as stack:
                for path_patch in path_patches:
                    stack.enter_context(path_patch)
                core_result = signing.sign_evidence(key_path, profile="release-core")
                self.assertTrue(core_result["verified"])
                self.assertTrue(core_dir.is_symlink())
                archived = {
                    path.name: path.read_bytes()
                    for path in (
                        core_dir / "manifest.json",
                        core_dir / "manifest.sig",
                        core_dir / "public.pem",
                    )
                }
                archive_target = core_dir.readlink()
                second_core = signing.sign_evidence(key_path, profile="release-core")
                self.assertTrue(second_core["verified"])
                self.assertEqual(core_dir.readlink(), archive_target)
                self.assertEqual(
                    (core_dir / "manifest.json").read_bytes(),
                    archived["manifest.json"],
                )
                current_before_failed_swap = (
                    current_dir / "manifest.json"
                ).read_bytes()
                evidence.write_text('{"changed":true}', encoding="utf-8")
                original_replace = signing.os.replace

                def fail_core_pointer_swap(source, destination) -> None:
                    if Path(destination) == core_dir:
                        raise OSError("simulated pointer swap failure")
                    original_replace(source, destination)

                with patch.object(
                    signing.os,
                    "replace",
                    side_effect=fail_core_pointer_swap,
                ):
                    with self.assertRaisesRegex(OSError, "pointer swap failure"):
                        signing.sign_evidence(key_path, profile="release-core")
                self.assertEqual(core_dir.readlink(), archive_target)
                self.assertEqual(
                    (current_dir / "manifest.json").read_bytes(),
                    current_before_failed_swap,
                )
                evidence.write_text("{}", encoding="utf-8")
                release_result = signing.sign_evidence(key_path, profile="release")
                self.assertTrue(release_result["verified"])
                self.assertEqual(release_result["profile"], "release")
                self.assertEqual(
                    archived,
                    {
                        path.name: path.read_bytes()
                        for path in (
                            core_dir / "manifest.json",
                            core_dir / "manifest.sig",
                            core_dir / "public.pem",
                        )
                    },
                )
                (core_dir / "manifest.json").write_text("{}", encoding="utf-8")
                tampered = signing.verify_evidence_bundle(
                    manifest_path=core_dir / "manifest.json",
                    signature_path=core_dir / "manifest.sig",
                    public_key_path=core_dir / "public.pem",
                )
                self.assertFalse(tampered["verified"])

            wrong_key = root / "wrong.pem"
            wrong_private = Ed25519PrivateKey.generate()
            wrong_key.write_bytes(wrong_private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            with (
                patch(
                    "system.backend.settings.settings",
                    SimpleNamespace(evidence_public_key_fingerprint=fingerprint),
                ),
                patch.object(signing, "build_evidence_manifest") as build_manifest,
                patch.object(signing, "atomic_write_json") as write_json,
                patch.object(signing, "atomic_write_bytes") as write_bytes,
            ):
                for profile in ("release-core", "release"):
                    with self.subTest(profile=profile):
                        with self.assertRaisesRegex(ValueError, "does not match"):
                            signing.sign_evidence(wrong_key, profile=profile)
            build_manifest.assert_not_called()
            write_json.assert_not_called()
            write_bytes.assert_not_called()

    def test_final_membership_archives_release_core_signature(self) -> None:
        core = signing.default_evidence_files("release-core", validate=False)
        final = signing.default_evidence_files("release", validate=False)
        for name in signing.MEA_EVIDENCE_NAMES:
            path = signing.MEA_EVIDENCE_DIR / name
            self.assertIn(path, core)
            self.assertIn(path, final)
        for relative in signing.MEA_IMPLEMENTATION_PATHS:
            path = signing.ROOT / relative
            self.assertIn(path, core)
            self.assertIn(path, final)
        for name in signing.SIMSWAP_EVIDENCE_NAMES:
            path = signing.SIMSWAP_EVIDENCE_DIR / name
            self.assertIn(path, core)
            self.assertIn(path, final)
        for relative in signing.SIMSWAP_IMPLEMENTATION_PATHS:
            path = signing.ROOT / relative
            self.assertIn(path, core)
            self.assertIn(path, final)
        conditioned_test = (
            signing.ROOT / "tests" / "test_simswap_conditioned_migration.py"
        )
        self.assertIn(conditioned_test, core)
        self.assertIn(conditioned_test, final)
        for path in signing.SIMSWAP_ASSET_PATHS:
            self.assertIn(path, core)
            self.assertIn(path, final)
        roles = signing._expanded_evidence_roles(core)
        for path in signing.MEA_CHECKPOINT_PATHS.values():
            self.assertIn(path, core)
            self.assertIn(path, final)
            self.assertEqual(roles[path.resolve()], "checkpoint")
        for path in signing.SIMSWAP_ENGINE_ARTIFACT_PATHS.values():
            self.assertIn(path, core)
            self.assertIn(path, final)
            self.assertEqual(roles[path.resolve()], "checkpoint")
        for path in signing.SIMSWAP_ASSET_PATHS:
            self.assertEqual(roles[path.resolve()], "visual_artifact")
        for path in signing.COLLABORATION_POLICY_SOURCES:
            self.assertIn(path, core)
            self.assertIn(path, final)
        for path in signing.SUPPLY_CHAIN_SOURCES:
            self.assertIn(path, core)
            self.assertIn(path, final)
        for path in (
            signing.CORE_MANIFEST_PATH,
            signing.CORE_SIGNATURE_PATH,
            signing.CORE_PUBLIC_KEY_PATH,
        ):
            self.assertNotIn(path, core)
            self.assertIn(path, final)

    def test_detached_payload_signature_is_independently_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "evidence.pem"
            private = Ed25519PrivateKey.generate()
            key_path.write_bytes(private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            payload = {"content_id": "abc", "sha256": "123"}
            signature = signing.sign_payload(payload, key_path)
            self.assertTrue(signing.verify_payload_signature(payload, signature))
            self.assertEqual(
                signing.signature_public_key_fingerprint(signature),
                signature["public_key_fingerprint_sha256"],
            )
            self.assertFalse(signing.verify_payload_signature({**payload, "sha256": "tampered"}, signature))
            forged = {**signature, "public_key_fingerprint_sha256": "0" * 64}
            self.assertNotEqual(
                signing.signature_public_key_fingerprint(forged),
                forged["public_key_fingerprint_sha256"],
            )

    def test_manifest_expands_summary_references_to_raw_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            for name in (
                "checkpoint.pth",
                "dataset.json",
                "results.csv",
                "protocol.json",
                "source.json",
                "checkpoint-manifest.json",
                "environment.json",
                "context.sha256",
            ):
                (root / "configs" / name).write_text(name, encoding="utf-8")
            summary = root / "summary.json"
            summary.write_text(json.dumps({
                "checkpoint": "configs/checkpoint.pth",
                "dataset_manifest_path": "configs/dataset.json",
                "results_csv_path": "configs/results.csv",
                "protocol_path": "configs/protocol.json",
                "source_manifest_path": "configs/source.json",
                "checkpoint_manifest_path": "configs/checkpoint-manifest.json",
                "environment_path": "configs/environment.json",
                "experiment_context_hashes_path": "configs/context.sha256",
            }), encoding="utf-8")
            with patch.object(signing, "ROOT", root):
                manifest = signing.build_evidence_manifest([summary])
            self.assertEqual(manifest["profile"], "scoped")
            roles = {item["path"]: item["role"] for item in manifest["files"]}
            self.assertEqual(roles["summary.json"], "evidence")
            self.assertEqual(roles["configs/checkpoint.pth"], "checkpoint")
            self.assertEqual(roles["configs/dataset.json"], "dataset_manifest")
            self.assertEqual(roles["configs/results.csv"], "raw_results")
            self.assertEqual(roles["configs/protocol.json"], "protocol")
            self.assertEqual(roles["configs/source.json"], "source_manifest")
            self.assertEqual(roles["configs/checkpoint-manifest.json"], "checkpoint_manifest")
            self.assertEqual(roles["configs/environment.json"], "environment_manifest")
            self.assertEqual(roles["configs/context.sha256"], "context_hashes")

    def test_manifest_profiles_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                signing.build_evidence_manifest(None, profile="scoped")
            with self.assertRaises(ValueError):
                signing.build_evidence_manifest([evidence], profile="release")
            with self.assertRaises(ValueError):
                signing.build_evidence_manifest([evidence], profile="release-core")
            with self.assertRaises(FileNotFoundError):
                signing.build_evidence_manifest([root / "missing.json"])

            with patch.object(
                signing,
                "default_evidence_files",
                return_value=[evidence],
            ):
                core = signing.build_evidence_manifest(
                    None,
                    profile="release-core",
                )
                release = signing.build_evidence_manifest(
                    None,
                    profile="release",
                )
            self.assertEqual(core["profile"], "release-core")
            self.assertEqual(release["profile"], "release")

    def test_manifest_binds_weight_manifest_checkpoint_and_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weights = root / "weights"
            calibration = weights / "KAD-Net" / "threshold_calibration.json"
            checkpoint = weights / "KAD-Net" / "EC_100.pth"
            calibration.parent.mkdir(parents=True)
            calibration.write_text('{"status":"complete"}', encoding="utf-8")
            checkpoint.write_bytes(b"checkpoint")
            manifest_path = weights / "WEIGHT_MANIFEST.json"
            manifest_path.write_text(json.dumps({
                "schema_version": "weight-manifest.v1",
                "items": [{
                    "model": "KAD-Net",
                    "file": "KAD-Net/EC_100.pth",
                    "calibration_artifact": "KAD-Net/threshold_calibration.json",
                }, {
                    "model": "invalid",
                    "file": "../outside.pth",
                    "calibration_artifact": "/absolute/calibration.json",
                }],
            }), encoding="utf-8")
            with (
                patch.object(signing, "ROOT", root),
                patch.object(signing, "WEIGHT_ROOT", weights),
            ):
                manifest = signing.build_evidence_manifest([manifest_path])
            roles = {item["path"]: item["role"] for item in manifest["files"]}
            self.assertEqual(roles["weights/WEIGHT_MANIFEST.json"], "evidence")
            self.assertEqual(roles["weights/KAD-Net/EC_100.pth"], "checkpoint")
            self.assertEqual(
                roles["weights/KAD-Net/threshold_calibration.json"],
                "calibration",
            )
            self.assertEqual(len(roles), 3)


if __name__ == "__main__":
    unittest.main()
