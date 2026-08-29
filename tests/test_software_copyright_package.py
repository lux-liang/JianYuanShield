from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts import build_software_copyright_package as package


class SoftwareCopyrightPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self._scaffold_required_files()
        self.write("system/backend/app.py", "print('first-party backend')\n")
        self.write("system/frontend/app.js", "export const ready = true;\n")
        self.write("android/app/src/main/App.kt", "class App\n")
        self.write(".env.example", "JYS_API_KEY=replace-me\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str | bytes = "fixture\n") -> Path:
        path = self.root / Path(*Path(relative).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def _scaffold_required_files(self) -> None:
        for relative in package.REQUIRED_FILES:
            if relative == "THIRD_PARTY_NOTICES.md":
                content = "# third party\n"
            elif relative == "README.md":
                content = "# fixture project\n"
            elif relative == "COPYRIGHT":
                content = (
                    f"{package.SOFTWARE_NAME}\n"
                    "本仓库的权利人尚未选定统一对外开源许可。\n"
                )
            else:
                content = f"# {package.SOFTWARE_NAME}\n"
            self.write(relative, content)

    def test_default_policy_excludes_upstream_models_runtime_and_private_media(self) -> None:
        self.write("KAD-Net/network.py", "upstream = True\n")
        self.write("model-sources/WaveGuard/model.py", "upstream = True\n")
        self.write("system/frontend/vendor/library.js", "thirdParty();\n")
        self.write("weights/model.pth", b"checkpoint")
        self.write("datasets/LFW/person.jpg", b"portrait")
        self.write("fixtures/experiment.csv", "subject,score\n1,0.9\n")
        self.write("system/data/provenance.sqlite3", b"database")
        self.write("system/reports/results.json", "{}\n")
        self.write(".venv/lib/site.py", "installed = True\n")
        self.write("logs/runtime.log", "secret runtime path\n")
        self.write(".code_backup_20260830/old.py", "old = True\n")
        self.write(".env", "PASSWORD=not-for-a-package\n")
        windows_home = "C:" + "\\Users\\filing-user\\Documents\\JianYuanShield"
        h100_home = "/root/" + "filing-user/projects/JianYuanShield"
        self.write(".git", f"gitdir: {windows_home}/.git/worktrees/filing\n")
        self.write("android/gradlew", f"#!/bin/sh\nGRADLE_USER_HOME={h100_home}/.gradle\n")
        self.write("android/gradlew.bat", f"@set GRADLE_USER_HOME={windows_home}\\.gradle\n")
        self.write("android/gradle/wrapper/gradle-wrapper.properties", "distributionUrl=fixture\n")
        self.write("android/gradle/wrapper/gradle-wrapper.jar", b"third-party binary")
        self.write("deployment/run-h100-api.sh", f"cd {h100_home}\n")
        self.write(
            "system/frontend/assets/heatmap_watermark_recovery_editable.svg",
            "<svg><title>presentation reconstruction</title></svg>\n",
        )
        self.write(
            "system/frontend/assets/heatmap_watermark_recovery_manifest.json",
            '{"font":{"path":"/mnt/c/Windows/Fonts/msyh.ttc"}}\n',
        )
        self.write("configs/credentials.json", '{"token":"not-for-a-package"}\n')
        self.write("keys/private.pem", "-----BEGIN PRIVATE KEY-----\nfixture\n")
        self.write("miniprogram/assets/faces/person.jpg", b"portrait")
        self.write("miniprogram/assets/logo.png", b"binary-logo")
        self.write("miniprogram/assets/sound.mp3", b"audio")

        collection = package.collect_source_files(self.root)
        paths = {entry.relative_path for entry in collection.entries}

        self.assertIn("system/backend/app.py", paths)
        self.assertIn("system/frontend/app.js", paths)
        self.assertIn("android/app/src/main/App.kt", paths)
        self.assertIn(".env.example", paths)
        for forbidden in (
            "KAD-Net/network.py",
            "model-sources/WaveGuard/model.py",
            "system/frontend/vendor/library.js",
            "weights/model.pth",
            "datasets/LFW/person.jpg",
            "fixtures/experiment.csv",
            "system/data/provenance.sqlite3",
            "system/reports/results.json",
            ".venv/lib/site.py",
            "logs/runtime.log",
            ".code_backup_20260830/old.py",
            ".env",
            ".git",
            "android/gradlew",
            "android/gradlew.bat",
            "android/gradle/wrapper/gradle-wrapper.properties",
            "android/gradle/wrapper/gradle-wrapper.jar",
            "deployment/run-h100-api.sh",
            "system/frontend/assets/heatmap_watermark_recovery_editable.svg",
            "system/frontend/assets/heatmap_watermark_recovery_manifest.json",
            "configs/credentials.json",
            "keys/private.pem",
            "miniprogram/assets/faces/person.jpg",
            "miniprogram/assets/logo.png",
            "miniprogram/assets/sound.mp3",
        ):
            self.assertNotIn(forbidden, paths)
        manifest = package._manifest_bytes(collection.entries)
        self.assertNotIn(windows_home.encode("utf-8"), manifest)
        self.assertNotIn(h100_home.encode("utf-8"), manifest)
        self.assertGreater(collection.exclusions.get("third_party_model_source", 0), 0)
        self.assertGreater(collection.exclusions.get("third_party_build_tool", 0), 0)
        self.assertGreater(collection.exclusions.get("deployment_topology", 0), 0)
        self.assertGreater(collection.exclusions.get("presentation_generated_output", 0), 0)
        self.assertGreater(collection.exclusions.get("personal_or_media_file", 0), 0)
        self.assertGreater(collection.exclusions.get("secrets", 0), 0)

    def test_build_outputs_archive_source_inventory_and_verifiable_hashes(self) -> None:
        output = self.base / "delivery/JianYuanShield-V1.0-source.zip"
        result = package.build_package(self.root, output)
        manifest_path = Path(result["source_manifest"])
        sums_path = Path(result["sha256_manifest"])
        package_hash_path = Path(result["archive_sha256_file"])

        self.assertTrue(output.is_file())
        self.assertTrue(manifest_path.is_file())
        self.assertTrue(sums_path.is_file())
        self.assertTrue(package_hash_path.is_file())
        self.assertIn(package.SOFTWARE_NAME, manifest_path.read_text(encoding="utf-8"))
        self.assertIn("system/backend/app.py", manifest_path.read_text(encoding="utf-8"))

        package_hash, package_name = package_hash_path.read_text(encoding="ascii").split()
        self.assertEqual(package_name, output.name)
        self.assertEqual(package_hash, hashlib.sha256(output.read_bytes()).hexdigest())

        with zipfile.ZipFile(output, "r") as archive:
            names = set(archive.namelist())
            self.assertIn(f"{package.ARCHIVE_ROOT}/SOURCE_MANIFEST.tsv", names)
            self.assertIn(f"{package.ARCHIVE_ROOT}/SHA256SUMS", names)
            self.assertIn(f"{package.ARCHIVE_ROOT}/source/system/backend/app.py", names)
            self.assertNotIn(f"{package.ARCHIVE_ROOT}/source/.env", names)
            sums = archive.read(f"{package.ARCHIVE_ROOT}/SHA256SUMS").decode("utf-8")
            for line in sums.splitlines():
                digest, relative = line.split("  ", 1)
                payload = archive.read(f"{package.ARCHIVE_ROOT}/{relative}")
                self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)

        with zipfile.ZipFile(output, "r") as archive:
            self.assertEqual(
                sums_path.read_bytes(),
                archive.read(f"{package.ARCHIVE_ROOT}/SHA256SUMS"),
            )

    def test_check_mode_validates_without_writing_output(self) -> None:
        output = self.base / "must-not-exist.zip"
        return_code = package.main(
            ["--root", str(self.root), "--output", str(output), "--check"]
        )
        self.assertEqual(return_code, 0)
        self.assertFalse(output.exists())
        self.assertFalse(output.with_name(f"{output.name}.sha256").exists())

    def test_missing_filing_document_fails_validation(self) -> None:
        (self.root / "docs/software-copyright/用户手册.md").unlink()
        with self.assertRaisesRegex(package.PackageError, "required filing files are missing"):
            package.check_project(self.root)

    def test_copyright_cannot_silently_grant_an_open_source_license(self) -> None:
        self.write(
            "COPYRIGHT",
            f"{package.SOFTWARE_NAME}\n"
            "本仓库的权利人尚未选定统一对外开源许可。\n"
            "SPDX-License-Identifier: MIT\n",
        )
        with self.assertRaisesRegex(package.PackageError, "must not silently grant"):
            package.check_project(self.root)

    def test_private_key_file_is_excluded_even_with_an_innocent_name(self) -> None:
        self.write(
            "configs/runtime.txt",
            "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----\n",
        )
        collection = package.collect_source_files(self.root)
        paths = {entry.relative_path for entry in collection.entries}
        self.assertNotIn("configs/runtime.txt", paths)
        self.assertEqual(collection.exclusions.get("private_key_material"), 1)

    def test_included_source_with_a_personal_absolute_path_fails_closed(self) -> None:
        personal_path = "C:" + "\\Users\\alice\\Documents\\JianYuanShield"
        self.write("system/backend/local_config.py", f'ROOT = r"{personal_path}"\n')
        with self.assertRaisesRegex(
            package.PackageError,
            "apparent personal absolute path",
        ):
            package.collect_source_files(self.root)

    def test_existing_outputs_require_force(self) -> None:
        output = self.base / "delivery/source.zip"
        package.build_package(self.root, output)
        with self.assertRaisesRegex(package.PackageError, "refusing to overwrite"):
            package.build_package(self.root, output)
        rebuilt = package.build_package(self.root, output, force=True)
        self.assertEqual(rebuilt["status"], "built")


if __name__ == "__main__":
    unittest.main()
