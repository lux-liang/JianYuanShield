from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import offline_bundle


class OfflineBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "bundle"
        self.root.mkdir()
        self.private_key = Ed25519PrivateKey.generate()
        public = self.private_key.public_key()
        self.public_pem = public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        public_der = public.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.fingerprint = hashlib.sha256(public_der).hexdigest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, data: bytes = b"fixture\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def sign(self, payload: dict, signature_path: Path, public_path: Path) -> None:
        signature_path.write_bytes(
            base64.b64encode(self.private_key.sign(offline_bundle._canonical_json(payload)))
            + b"\n"
        )
        public_path.write_bytes(self.public_pem)

    @staticmethod
    def tar_bytes(files: dict[str, bytes]) -> bytes:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            for name, content in sorted(files.items()):
                item = tarfile.TarInfo(name)
                item.mode = 0o644
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        return output.getvalue()

    def image_archives(self, *, commit: str) -> tuple[bytes, bytes, str, str, str]:
        def encoded(payload: object) -> bytes:
            return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

        config = encoded({"architecture": "amd64", "os": "linux"})
        config_digest = "sha256:" + hashlib.sha256(config).hexdigest()
        image_manifest = encoded({
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": config_digest,
                "size": len(config),
            },
            "layers": [],
        })
        manifest_digest = "sha256:" + hashlib.sha256(image_manifest).hexdigest()
        blobs = {
            f"blobs/sha256/{config_digest[7:]}": config,
            f"blobs/sha256/{manifest_digest[7:]}": image_manifest,
        }
        descriptors = [{
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "digest": manifest_digest,
            "size": len(image_manifest),
            "platform": {"architecture": "amd64", "os": "linux"},
        }]
        for predicate in (
            "https://slsa.dev/provenance/v1",
            "https://spdx.dev/Document",
        ):
            statement = encoded({"_type": "https://in-toto.io/Statement/v1", "predicateType": predicate})
            statement_digest = "sha256:" + hashlib.sha256(statement).hexdigest()
            attestation = encoded({
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "digest": config_digest,
                    "size": len(config),
                },
                "layers": [{
                    "mediaType": "application/vnd.in-toto+json",
                    "digest": statement_digest,
                    "size": len(statement),
                }],
            })
            attestation_digest = "sha256:" + hashlib.sha256(attestation).hexdigest()
            blobs[f"blobs/sha256/{statement_digest[7:]}"] = statement
            blobs[f"blobs/sha256/{attestation_digest[7:]}"] = attestation
            descriptors.append({
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": attestation_digest,
                "size": len(attestation),
                "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
                "platform": {"architecture": "unknown", "os": "unknown"},
            })
        index = encoded({"schemaVersion": 2, "manifests": descriptors})
        oci = self.tar_bytes({
            "oci-layout": encoded({"imageLayoutVersion": "1.0.0"}),
            "index.json": index,
            **blobs,
        })
        tagged_reference = f"ghcr.io/lux-liang/jianyuanshield:{commit}"
        docker_manifest = encoded([{
            "Config": f"{config_digest[7:]}.json",
            "RepoTags": [tagged_reference],
            "Layers": [],
        }])
        load = self.tar_bytes({
            "manifest.json": docker_manifest,
            f"{config_digest[7:]}.json": config,
        })
        return oci, load, manifest_digest, config_digest, tagged_reference

    def build_valid_bundle(self, *, include_private_key: bool = False) -> None:
        for relative in (
            "deployment/docker-compose.competition.yml",
            "deployment/offline_deploy.sh",
            "deployment/offline_bundle.py",
            "image/build-manifest.json",
            "image/buildkit-metadata.json",
            "image/python-dependencies.cdx.json",
            "payload/licenses/THIRD_PARTY_NOTICES.md",
            "payload/assets/.keep",
            "payload/data/.keep",
            "payload/model-sources/.keep",
            "payload/reports/.keep",
            "payload/weights/.keep",
        ):
            self.write(relative)
        project_member = self.write("payload/project/configs/protocol.json", b'{"ok":true}\n')
        core_manifest = {
            "schema_version": offline_bundle.EVIDENCE_SCHEMA,
            "profile": "release-core",
            "hash_algorithm": "sha256",
            "signature_algorithm": "ed25519",
            "files": [
                {
                    "path": "configs/protocol.json",
                    "role": "evidence",
                    "sha256": offline_bundle._sha256_file(project_member),
                    "size_bytes": project_member.stat().st_size,
                }
            ],
        }
        core_dir = self.root / "payload/reports/evidence_signature/release-core"
        core_dir.mkdir(parents=True)
        core_manifest_path = core_dir / "manifest.json"
        core_manifest_path.write_bytes(offline_bundle._json_bytes(core_manifest))
        self.sign(core_manifest, core_dir / "manifest.sig", core_dir / "public_key.pem")

        commit = "c" * 40
        oci_bytes, load_bytes, manifest_digest, config_digest, tagged_reference = (
            self.image_archives(commit=commit)
        )
        archive = self.write("image/release-image.oci.tar", oci_bytes)
        load_archive = self.write(
            "image/release-image.docker.tar",
            load_bytes,
        )
        tree = "d" * 40
        deployment_reference = (
            "ghcr.io/lux-liang/jianyuanshield@" + manifest_digest
        )
        metadata_path = self.root / "image/buildkit-metadata.json"
        supply_path = self.root / "image/build-manifest.json"
        sbom_path = self.root / "image/python-dependencies.cdx.json"
        release_record = {
            "schema_version": offline_bundle.RELEASE_SCHEMA,
            "source": {"git_commit": commit, "git_tree": tree},
            "image": {
                "config_digest": config_digest,
                "deployment_reference": deployment_reference,
                "digest": manifest_digest,
                "offline_runtime_reference": config_digest,
                "tagged_reference": tagged_reference,
            },
            "build": {
                "output_type": "offline-dual-archive",
                "metadata_path": metadata_path.name,
                "metadata_sha256": offline_bundle._sha256_file(metadata_path),
                "oci_archive": {
                    "path": "original.oci.tar",
                    "sha256": offline_bundle._sha256_file(archive),
                    "size_bytes": archive.stat().st_size,
                },
                "load_archive": {
                    "format": "docker-image-layout-with-oci-media-types",
                    "path": "original.docker.tar",
                    "sha256": offline_bundle._sha256_file(load_archive),
                    "size_bytes": load_archive.stat().st_size,
                },
            },
            "supply_chain_manifest": {
                "path": supply_path.name,
                "sha256": offline_bundle._sha256_file(supply_path),
            },
            "python_dependency_sbom": {
                "path": sbom_path.name,
                "sha256": offline_bundle._sha256_file(sbom_path),
            },
        }
        self.write("image/release-image.json", offline_bundle._json_bytes(release_record))
        if include_private_key:
            self.write("payload/project/leaked.pem", b"-----BEGIN PRIVATE KEY-----\nleak\n")

        signed_files = offline_bundle._iter_bundle_files(self.root)
        records = offline_bundle._file_records(self.root, signed_files)
        manifest = {
            "schema_version": offline_bundle.BUNDLE_SCHEMA,
            "bundle_id": "b" * 32,
            "created_at": "2026-08-04T00:00:00Z",
            "files": records,
            "inventory": {
                "file_count": len(records),
                "size_bytes": sum(record["size_bytes"] for record in records),
            },
            "release_core": {
                "file_count": 1,
                "manifest_path": "payload/reports/evidence_signature/release-core/manifest.json",
                "manifest_sha256": offline_bundle._sha256_file(core_manifest_path),
                "public_key_fingerprint_sha256": self.fingerprint,
                "signature_path": "payload/reports/evidence_signature/release-core/manifest.sig",
            },
            "release_image": {
                "deployment_reference": deployment_reference,
                "git_commit": commit,
                "git_tree": tree,
                "oci_archive_path": "image/release-image.oci.tar",
                "oci_archive_sha256": offline_bundle._sha256_file(archive),
                "load_archive_path": "image/release-image.docker.tar",
                "load_archive_sha256": offline_bundle._sha256_file(load_archive),
                "offline_runtime_reference": config_digest,
                "release_record_path": "image/release-image.json",
            },
            "runtime": {
                "demo_enabled": False,
                "mode": "production",
                "network_dependency": "none",
                "secrets_packaged": False,
            },
        }
        self.write("bundle-manifest.json", offline_bundle._json_bytes(manifest))
        self.sign(
            manifest,
            self.root / "bundle-manifest.sig",
            self.root / "bundle-public-key.pem",
        )
        offline_bundle._write_sha256sums(self.root)

    def test_signed_bundle_preflight_closes_image_evidence_and_inventory(self) -> None:
        self.build_valid_bundle()
        result = offline_bundle.preflight_bundle(
            self.root,
            expected_fingerprint=self.fingerprint,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["status"], "verified")
        self.assertRegex(result["release_image"], r"@sha256:[0-9a-f]{64}$")

    def test_payload_tampering_is_rejected(self) -> None:
        self.build_valid_bundle()
        self.write("payload/project/configs/protocol.json", b"tampered")
        with self.assertRaisesRegex(offline_bundle.BundleError, "hash mismatch"):
            offline_bundle.preflight_bundle(
                self.root,
                expected_fingerprint=self.fingerprint,
            )

    def test_unsigned_extra_file_is_rejected(self) -> None:
        self.build_valid_bundle()
        self.write("payload/project/rogue.py")
        with self.assertRaisesRegex(offline_bundle.BundleError, "membership mismatch"):
            offline_bundle.preflight_bundle(
                self.root,
                expected_fingerprint=self.fingerprint,
            )

    def test_private_key_material_is_never_accepted_in_bundle(self) -> None:
        self.build_valid_bundle(include_private_key=True)
        with self.assertRaisesRegex(offline_bundle.BundleError, "contains a private key"):
            offline_bundle.preflight_bundle(
                self.root,
                expected_fingerprint=self.fingerprint,
            )

    def test_wrong_external_signer_pin_is_rejected(self) -> None:
        self.build_valid_bundle()
        with self.assertRaisesRegex(offline_bundle.BundleError, "externally pinned"):
            offline_bundle.preflight_bundle(
                self.root,
                expected_fingerprint="f" * 64,
            )

    def test_runtime_secrets_require_strict_permissions_and_matching_key(self) -> None:
        secret_dir = Path(self.temporary.name) / "secrets"
        secret_dir.mkdir()
        (secret_dir / "api_key").write_text("a" * 40, encoding="utf-8")
        (secret_dir / "provenance_secret").write_text("p" * 40, encoding="utf-8")
        private_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        (secret_dir / "evidence_ed25519.pem").write_bytes(private_pem)
        for path in secret_dir.iterdir():
            os.chmod(path, 0o600)
        result = offline_bundle._secret_files(
            secret_dir,
            expected_fingerprint=self.fingerprint,
        )
        self.assertEqual(set(result), {"api_key", "provenance_secret", "evidence_private_key"})
        os.chmod(secret_dir / "api_key", 0o644)
        with self.assertRaisesRegex(offline_bundle.BundleError, "permissions"):
            offline_bundle._secret_files(
                secret_dir,
                expected_fingerprint=self.fingerprint,
            )

    def test_create_builds_an_atomic_preflight_verified_bundle(self) -> None:
        base = Path(self.temporary.name)
        source = base / "source"
        runtime = base / "runtime"
        release_dir = base / "release"
        output = base / "published-bundle"
        for path in (
            source / "scripts",
            source / "configs",
            runtime / "assets",
            runtime / "data/samples",
            runtime / "model-sources",
            runtime / "reports/evidence_signature/release-core",
            runtime / "weights",
            release_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for path, content in (
            (source / "docker-compose.competition.yml", "services: {}\n"),
            (source / "offline_deploy.sh", "#!/bin/sh\n"),
            (source / "scripts/offline_bundle.py", "# fixture\n"),
            (source / "THIRD_PARTY_NOTICES.md", "fixture licenses\n"),
            (source / "configs/protocol.json", '{"protocol":1}\n'),
        ):
            path.write_text(content, encoding="utf-8")
        for path in (
            runtime / "assets/.keep",
            runtime / "data/.keep",
            runtime / "model-sources/.keep",
            runtime / "weights/.keep",
        ):
            path.write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=source, check=True)
        subprocess.run(["git", "config", "user.name", "JYS Test"], cwd=source, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=source, check=True)
        subprocess.run(["git", "add", "."], cwd=source, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=source, check=True)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=source,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

        project_member = source / "configs/protocol.json"
        core_manifest = {
            "schema_version": offline_bundle.EVIDENCE_SCHEMA,
            "profile": "release-core",
            "hash_algorithm": "sha256",
            "signature_algorithm": "ed25519",
            "files": [{
                "path": "configs/protocol.json",
                "role": "evidence",
                "sha256": offline_bundle._sha256_file(project_member),
                "size_bytes": project_member.stat().st_size,
            }],
        }
        core_dir = runtime / "reports/evidence_signature/release-core"
        (core_dir / "manifest.json").write_bytes(offline_bundle._json_bytes(core_manifest))
        self.sign(core_manifest, core_dir / "manifest.sig", core_dir / "public_key.pem")

        oci, load, manifest_digest, config_digest, tagged_reference = self.image_archives(
            commit=commit
        )
        oci_path = release_dir / "release-image.oci.tar"
        load_path = release_dir / "release-image.docker.tar"
        oci_path.write_bytes(oci)
        load_path.write_bytes(load)
        metadata = release_dir / "buildkit-metadata.json"
        supply = release_dir / "build-manifest.json"
        sbom = release_dir / "python-dependencies.cdx.json"
        metadata.write_text("{}\n", encoding="utf-8")
        supply.write_text("{}\n", encoding="utf-8")
        sbom.write_text("{}\n", encoding="utf-8")
        release_record = {
            "schema_version": offline_bundle.RELEASE_SCHEMA,
            "source": {"git_commit": commit, "git_tree": tree},
            "image": {
                "config_digest": config_digest,
                "deployment_reference": (
                    "ghcr.io/lux-liang/jianyuanshield@" + manifest_digest
                ),
                "digest": manifest_digest,
                "offline_runtime_reference": config_digest,
                "tagged_reference": tagged_reference,
            },
            "build": {
                "metadata_path": metadata.name,
                "metadata_sha256": offline_bundle._sha256_file(metadata),
                "output_type": "offline-dual-archive",
                "oci_archive": {
                    "path": oci_path.name,
                    "sha256": offline_bundle._sha256_file(oci_path),
                    "size_bytes": oci_path.stat().st_size,
                },
                "load_archive": {
                    "format": "docker-image-layout-with-oci-media-types",
                    "path": load_path.name,
                    "sha256": offline_bundle._sha256_file(load_path),
                    "size_bytes": load_path.stat().st_size,
                },
            },
            "supply_chain_manifest": {
                "path": supply.name,
                "sha256": offline_bundle._sha256_file(supply),
            },
            "python_dependency_sbom": {
                "path": sbom.name,
                "sha256": offline_bundle._sha256_file(sbom),
            },
        }
        (release_dir / "release-image.json").write_bytes(
            offline_bundle._json_bytes(release_record)
        )
        signing_key = base / "signer.pem"
        signing_key.write_bytes(self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        result = offline_bundle.create_bundle(
            output=output,
            source_root=source,
            runtime_root=runtime,
            release_dir=release_dir,
            oci_archive=None,
            load_archive=None,
            signing_key=signing_key,
            signer_fingerprint=self.fingerprint,
        )
        self.assertTrue(result["verified"])
        self.assertTrue(output.is_dir())
        self.assertFalse(any(path.is_symlink() for path in output.rglob("*")))
        verified = offline_bundle.preflight_bundle(
            output,
            expected_fingerprint=self.fingerprint,
        )
        self.assertEqual(verified["bundle_id"], result["bundle_id"])


if __name__ == "__main__":
    unittest.main()
