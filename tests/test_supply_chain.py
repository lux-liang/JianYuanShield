from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_release_image, supply_chain


ROOT = Path(__file__).resolve().parents[1]
PINNED_FROM = (
    "FROM example.invalid/runtime:1.0@sha256:"
    + "a" * 64
    + "\n"
)


def create_fixture(root: Path) -> None:
    (root / "scripts").mkdir(parents=True)
    (root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (root / "Dockerfile").write_text(
        PINNED_FROM
        + "RUN sed '[snapshot=yes]' /etc/apt/sources.list \\\n"
        + " && apt-get update --snapshot 20260804T000000Z \\\n"
        + " && apt-get install --snapshot 20260804T000000Z libgl1 libglib2.0-0\n"
        + "COPY docker-compose.yml docker-compose.production.yml docker-compose.competition.yml ./\n"
        + "COPY offline_deploy.sh ./\n"
        + "COPY THIRD_PARTY_NOTICES.md ./\n"
        + "COPY VERSION ./\n"
        + "COPY scripts/supply_chain.py scripts/build_release_image.py scripts/check_deployment.py scripts/offline_bundle.py ./scripts/\n"
        + "COPY system/gateway.py ./system/gateway.py\n"
        + "COPY deployment/ ./deployment/\n"
        + "RUN python scripts/supply_chain.py check \\\n"
        + " && pip install --require-hashes --only-binary=:all: -r requirements.lock \\\n"
        + " && python scripts/supply_chain.py verify-environment\n",
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text("demo>=1.0,<2\n", encoding="utf-8")
    (root / "requirements.lock").write_text(
        "# generated\n"
        + supply_chain.LOCK_HEADER
        + "\n"
        + "demo==1.2.3 \\\n"
        + "    --hash=sha256:"
        + "b" * 64
        + "\n",
        encoding="utf-8",
    )
    (root / "scripts" / "supply_chain.py").write_text("# fixture\n", encoding="utf-8")
    (root / "scripts" / "build_release_image.py").write_text("# fixture\n", encoding="utf-8")
    (root / "scripts" / "check_deployment.py").write_text("# fixture\n", encoding="utf-8")
    (root / "scripts" / "offline_bundle.py").write_text("# fixture\n", encoding="utf-8")
    (root / "system").mkdir(parents=True)
    (root / "system" / "gateway.py").write_text("# fixture\n", encoding="utf-8")
    (root / "offline_deploy.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.md").write_text("fixture notices\n", encoding="utf-8")
    (root / "deployment").mkdir()
    for name in (
        "Caddyfile.jianyuanshield",
        "deploy-public-release.sh",
        "run-h100-api.sh",
        "run-h100-gateway.sh",
        "run-h100-tunnel.sh",
        "supervisor-jianyuanshield.conf",
    ):
        (root / "deployment" / name).write_text(f"# {name}\n", encoding="utf-8")
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "docker-compose.production.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "docker-compose.competition.yml").write_text("services: {}\n", encoding="utf-8")


class SupplyChainTests(unittest.TestCase):
    def test_repository_supply_chain_artifacts_are_current(self) -> None:
        self.assertEqual(supply_chain.check_outputs(ROOT), [])
        manifest = json.loads((ROOT / supply_chain.OUTPUT_MANIFEST).read_text(encoding="utf-8"))
        sbom = json.loads((ROOT / supply_chain.OUTPUT_SBOM).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "verified")
        self.assertRegex(manifest["base_image"]["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertEqual(manifest["software"]["version"], "1.0.0")
        self.assertEqual(sbom["metadata"]["component"]["version"], "1.0.0")
        self.assertEqual(len(sbom["components"]), manifest["dependencies"]["locked_package_count"])

    def test_mutable_base_image_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dockerfile = Path(directory) / "Dockerfile"
            dockerfile.write_text("FROM example.invalid/runtime:latest\n", encoding="utf-8")
            with self.assertRaisesRegex(supply_chain.SupplyChainError, "immutable sha256"):
                supply_chain.parse_base_image(dockerfile)

    def test_version_must_be_copied_before_the_supply_chain_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_fixture(root)
            dockerfile = root / "Dockerfile"
            source = dockerfile.read_text(encoding="utf-8")
            source = source.replace("COPY VERSION ./\n", "") + "COPY VERSION ./\n"
            dockerfile.write_text(source, encoding="utf-8")
            with self.assertRaisesRegex(
                supply_chain.SupplyChainError,
                "copy VERSION before",
            ):
                supply_chain.validate_docker_install_contract(dockerfile)

    def test_missing_distribution_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "requirements.lock"
            lock.write_text(
                "# generated\n" + supply_chain.LOCK_HEADER + "\n" + "demo==1.2.3\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(supply_chain.SupplyChainError, "missing or duplicate hashes"):
                supply_chain.parse_lock(lock)

    def test_generated_outputs_fail_closed_when_an_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_fixture(root)
            supply_chain.write_outputs(root)
            self.assertEqual(supply_chain.check_outputs(root), [])
            (root / "requirements.txt").write_text("demo>=1.1,<2\n", encoding="utf-8")
            self.assertTrue(supply_chain.check_outputs(root))

    def test_release_closure_rejects_lock_manifest_and_sbom_tampering(self) -> None:
        targets = (
            Path("requirements.lock"),
            supply_chain.OUTPUT_MANIFEST,
            supply_chain.OUTPUT_SBOM,
        )
        for target in targets:
            with self.subTest(target=target.as_posix()):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    create_fixture(root)
                    supply_chain.write_outputs(root)
                    self.assertEqual(supply_chain.check_outputs(root), [])
                    path = root / target
                    path.write_bytes(path.read_bytes() + b"\n")
                    self.assertTrue(supply_chain.check_outputs(root))

    def test_environment_verifier_requires_exact_locked_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_fixture(root)
            distributions = [SimpleNamespace(metadata={"Name": "demo"}, version="1.2.4")]
            with patch.object(supply_chain.metadata, "distributions", return_value=distributions):
                failures = supply_chain.verify_environment(root)
            self.assertEqual(
                failures,
                ["installed dependency mismatch: demo expected=1.2.3 actual=1.2.4"],
            )

    def test_release_image_reference_must_use_exact_commit_tag(self) -> None:
        commit = "c" * 40
        self.assertEqual(
            build_release_image.validate_image_reference(
                f"ghcr.io/lux-liang/jianyuanshield:{commit}",
                commit,
            ),
            f"ghcr.io/lux-liang/jianyuanshield:{commit}",
        )
        for reference in (
            "jianyuanshield:latest",
            "ghcr.io/lux-liang/jianyuanshield:latest",
            f"ghcr.io/lux-liang/jianyuanshield:{'d' * 40}",
        ):
            with self.subTest(reference=reference), self.assertRaises(
                build_release_image.ReleaseBuildError
            ):
                build_release_image.validate_image_reference(reference, commit)

    def test_release_digest_validation_is_fail_closed(self) -> None:
        digest = "sha256:" + "d" * 64
        self.assertEqual(build_release_image.validate_digest(digest), digest)
        for value in ("latest", "sha256:1234", "sha512:" + "d" * 64):
            with self.subTest(value=value), self.assertRaises(
                build_release_image.ReleaseBuildError
            ):
                build_release_image.validate_digest(value)

    def test_buildkit_metadata_supplies_deployment_digest(self) -> None:
        digest = "sha256:" + "e" * 64
        config_digest = "sha256:" + "f" * 64
        commit = "c" * 40
        image = f"ghcr.io/lux-liang/jianyuanshield:{commit}"
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text(
                json.dumps({
                    "containerimage.digest": digest,
                    "containerimage.config.digest": config_digest,
                }),
                encoding="utf-8",
            )
            self.assertEqual(
                build_release_image.image_digest_from_metadata(metadata_path),
                digest,
            )
            self.assertEqual(
                build_release_image.image_config_digest_from_metadata(metadata_path),
                config_digest,
            )
        self.assertEqual(
            build_release_image.deployment_reference(image, digest),
            f"ghcr.io/lux-liang/jianyuanshield@{digest}",
        )

    def test_buildkit_metadata_without_export_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(
                build_release_image.ReleaseBuildError,
                "exported image digest",
            ):
                build_release_image.image_digest_from_metadata(metadata_path)

    def test_offline_release_record_pins_manifest_config_and_both_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {}
            for name in (
                "metadata.json",
                "build-manifest.json",
                "sbom.json",
                "release.oci.tar",
                "release.docker.tar",
            ):
                path = root / name
                path.write_bytes(name.encode("ascii"))
                files[name] = path
            commit = "c" * 40
            manifest_digest = "sha256:" + "d" * 64
            config_digest = "sha256:" + "e" * 64
            record = build_release_image.build_release_record(
                image=f"ghcr.io/lux-liang/jianyuanshield:{commit}",
                image_digest=manifest_digest,
                image_config_digest=config_digest,
                commit=commit,
                tree="f" * 40,
                output_type="offline-dual-archive",
                build_metadata_path=files["metadata.json"],
                supply_manifest_path=files["build-manifest.json"],
                python_sbom_path=files["sbom.json"],
                oci_archive=files["release.oci.tar"],
                load_archive=files["release.docker.tar"],
            )
            self.assertEqual(record["image"]["offline_runtime_reference"], config_digest)
            self.assertEqual(
                record["image"]["immutable_reference"],
                f"ghcr.io/lux-liang/jianyuanshield@{manifest_digest}",
            )
            self.assertIn("oci_archive", record["build"])
            self.assertIn("load_archive", record["build"])


if __name__ == "__main__":
    unittest.main()
