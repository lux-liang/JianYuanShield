from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
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

    def init_git_repository(self) -> str:
        commands = (
            ("init",),
            ("config", "user.name", "Package Test"),
            ("config", "user.email", "package-test@example.invalid"),
            ("add", "--all"),
            ("commit", "-m", "fixture"),
        )
        for command in commands:
            completed = subprocess.run(
                ["git", *command],
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if completed.returncode != 0:
                self.fail(f"git {' '.join(command)} failed: {completed.stderr}")
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            text=True,
            encoding="ascii",
        ).strip()

    def test_default_policy_excludes_upstream_models_runtime_and_private_media(self) -> None:
        self.write("KAD-Net/network.py", "upstream = True\n")
        self.write("model-sources/WaveGuard/model.py", "upstream = True\n")
        self.write("third_party/KAD-Net/nested.py", "upstream = True\n")
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
            "third_party/KAD-Net/nested.py",
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
        manifest = package._manifest_bytes(
            collection.entries,
            source_state=package.SourceState(
                kind="exported_tree",
                source_commit=None,
                working_tree_clean=None,
                dirty_override_used=False,
            ),
            final=False,
        )
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
        metadata_path = Path(result["build_metadata"])
        manifest_path = Path(result["source_manifest"])
        sums_path = Path(result["sha256_manifest"])
        package_hash_path = Path(result["archive_sha256_file"])

        self.assertTrue(output.is_file())
        self.assertTrue(metadata_path.is_file())
        self.assertTrue(manifest_path.is_file())
        self.assertTrue(sums_path.is_file())
        self.assertTrue(package_hash_path.is_file())
        self.assertIn(package.SOFTWARE_NAME, manifest_path.read_text(encoding="utf-8"))
        self.assertIn("system/backend/app.py", manifest_path.read_text(encoding="utf-8"))
        self.assertIn(
            "# source_commit\tnot_available_exported_tree",
            manifest_path.read_text(encoding="utf-8"),
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_kind"], "exported_tree")
        self.assertIsNone(metadata["source_commit"])
        self.assertIsNone(metadata["working_tree_clean"])
        self.assertEqual(result["source_kind"], "exported_tree")
        self.assertIsNone(result["source_commit"])

        package_hash, package_name = package_hash_path.read_text(encoding="ascii").split()
        self.assertEqual(package_name, output.name)
        self.assertEqual(package_hash, hashlib.sha256(output.read_bytes()).hexdigest())

        with zipfile.ZipFile(output, "r") as archive:
            names = set(archive.namelist())
            self.assertIn(f"{package.ARCHIVE_ROOT}/BUILD_METADATA.json", names)
            self.assertIn(f"{package.ARCHIVE_ROOT}/SOURCE_MANIFEST.tsv", names)
            self.assertIn(f"{package.ARCHIVE_ROOT}/SHA256SUMS", names)
            self.assertIn(f"{package.ARCHIVE_ROOT}/source/system/backend/app.py", names)
            self.assertNotIn(f"{package.ARCHIVE_ROOT}/source/.env", names)
            self.assertEqual(
                metadata,
                json.loads(
                    archive.read(f"{package.ARCHIVE_ROOT}/BUILD_METADATA.json").decode(
                        "utf-8"
                    )
                ),
            )
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

    def test_appdata_and_root_runtime_absolute_paths_fail_closed(self) -> None:
        cases = {
            "Windows AppData": (
                "C:" + "\\Users\\alice\\AppData\\Local\\JianYuanShield"
            ),
            "root runtime": "/root/" + "jialiang_liang/runtime/JianYuanShield",
        }
        for label, absolute_path in cases.items():
            with self.subTest(label=label):
                path = self.write(
                    "system/backend/local_runtime.py",
                    f'LOCAL_RUNTIME = r"{absolute_path}"\n',
                )
                with self.assertRaisesRegex(
                    package.PackageError,
                    "apparent personal absolute path",
                ):
                    package.collect_source_files(self.root)
                path.unlink()

    def test_plaintext_secret_assignments_fail_but_placeholders_are_allowed(self) -> None:
        self.write("configs/runtime.yaml", 'api_key: "sk-live-secret-value"\n')
        with self.assertRaisesRegex(package.PackageError, "apparent plaintext"):
            package.collect_source_files(self.root)

        self.write("configs/runtime.yaml", 'api_key: "${JYS_API_KEY}"\n')
        collection = package.collect_source_files(self.root)
        self.assertIn(
            "configs/runtime.yaml",
            {entry.relative_path for entry in collection.entries},
        )

        self.write(
            "tests/test_fixture.py",
            'api_key = "a" * 32\ntoken = "expected-test-key"\n'
            "session_secret = session_secret\n",
        )
        package.collect_source_files(self.root)

        self.write("configs/runtime.yaml", "SESSION_SECRET=Abc!1234-secret\n")
        with self.assertRaisesRegex(package.PackageError, "apparent plaintext"):
            package.collect_source_files(self.root)

    def test_final_gate_rejects_unresolved_placeholders_but_draft_allows_them(self) -> None:
        self.write(
            "docs/software-copyright/申请信息清单.md",
            f"# {package.SOFTWARE_NAME}\n申请人：[待填写]\n",
        )
        draft = package.check_project(self.root)
        self.assertEqual(draft["build_mode"], "draft")
        with self.assertRaisesRegex(package.PackageError, r"unresolved \[待…\]"):
            package.check_project(self.root, final=True)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(
                package.main(["--root", str(self.root), "--check", "--final"]),
                2,
            )

    def test_dependency_lock_and_sbom_are_evidence_not_first_party_source(self) -> None:
        self.write("requirements.lock", "dependency==1.0 --hash=sha256:fixture\n")
        self.write(
            "supply-chain/python-dependencies.cdx.json",
            '{"bomFormat":"CycloneDX"}\n',
        )
        categories = {
            entry.relative_path: entry.category
            for entry in package.collect_source_files(self.root).entries
        }
        self.assertEqual(
            categories["requirements.lock"],
            "第三方依赖清单/证据",
        )
        self.assertEqual(
            categories["supply-chain/python-dependencies.cdx.json"],
            "第三方依赖清单/证据",
        )

    def test_clean_git_commit_and_state_are_recorded_in_manifest_and_json(self) -> None:
        self.write(".gitignore", "dist/\n")
        commit = self.init_git_repository()
        self.write("dist/prior-package.zip", b"ignored output")
        output = self.base / "delivery/clean-source.zip"

        result = package.build_package(self.root, output)

        self.assertEqual(result["source_commit"], commit)
        self.assertTrue(result["working_tree_clean"])
        manifest = Path(result["source_manifest"]).read_text(encoding="utf-8")
        self.assertIn(f"# source_commit\t{commit}", manifest)
        self.assertIn("# working_tree_clean\ttrue", manifest)
        metadata = json.loads(Path(result["build_metadata"]).read_text(encoding="utf-8"))
        self.assertEqual(metadata["source_commit"], commit)
        self.assertTrue(metadata["working_tree_clean"])
        self.assertFalse(metadata["dirty_override_used"])

    def test_dirty_git_tree_is_rejected_except_development_check_override(self) -> None:
        commit = self.init_git_repository()
        self.write("system/backend/app.py", "print('dirty change')\n")
        self.write("untracked.py", "untracked = True\n")

        with self.assertRaisesRegex(package.PackageError, "Git worktree is dirty"):
            package.check_project(self.root)
        with self.assertRaisesRegex(package.PackageError, "Git worktree is dirty"):
            package.build_package(self.root, self.base / "dirty.zip")

        result = package.check_project(self.root, allow_dirty=True)
        self.assertEqual(result["source_commit"], commit)
        self.assertFalse(result["working_tree_clean"])
        self.assertTrue(result["dirty_override_used"])
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            self.assertEqual(
                package.main(
                    ["--root", str(self.root), "--check", "--allow-dirty"]
                ),
                0,
            )
        cli_result = json.loads(stdout.getvalue())
        self.assertFalse(cli_result["working_tree_clean"])
        self.assertTrue(cli_result["dirty_override_used"])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(
                package.main(["--root", str(self.root), "--allow-dirty"]),
                2,
            )
        with self.assertRaisesRegex(package.PackageError, "cannot be combined"):
            package.check_project(self.root, allow_dirty=True, final=True)

    def test_existing_outputs_require_force(self) -> None:
        output = self.base / "delivery/source.zip"
        package.build_package(self.root, output)
        with self.assertRaisesRegex(package.PackageError, "refusing to overwrite"):
            package.build_package(self.root, output)
        rebuilt = package.build_package(self.root, output, force=True)
        self.assertEqual(rebuilt["status"], "built")


if __name__ == "__main__":
    unittest.main()
