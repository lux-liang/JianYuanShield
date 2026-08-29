from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

from scripts.check_deployment import validate_competition, validate_production


ROOT = Path(__file__).resolve().parents[1]
DIGEST_IMAGE = "ghcr.io/lux-liang/jianyuanshield@sha256:" + "a" * 64


def hardened_service(*, api: bool, gateway: bool = False) -> dict:
    service = {
        "image": DIGEST_IMAGE,
        "read_only": True,
        "init": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 128,
        "ports": [{"host_ip": "127.0.0.1", "published": "8026", "target": 8026}],
        "logging": {"driver": "json-file", "options": {"max-size": "10m"}},
    }
    if api:
        service.update({
            "environment": {
                "JYS_MODE": "production",
                "JYS_ENABLE_DEMO": "false",
                "JYS_REQUIRE_API_KEY": "true",
                "JYS_API_KEY_FILE": "/run/secrets/jys_api_key",
                "JYS_PROVENANCE_SECRET_FILE": "/run/secrets/jys_provenance_secret",
                "JYS_EVIDENCE_PRIVATE_KEY": "/run/secrets/jys_evidence_private_key",
                "JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT": "b" * 64,
                "JYS_CORS_ORIGINS": "https://console.example",
            },
            "secrets": [
                {"target": "/run/secrets/jys_api_key"},
                {"target": "/run/secrets/jys_provenance_secret"},
                {"target": "/run/secrets/jys_evidence_private_key"},
            ],
            "volumes": [
                {
                    "type": "bind",
                    "target": "/app/weights",
                    "read_only": True,
                    "bind": {"create_host_path": False},
                },
                {
                    "type": "bind",
                    "target": "/app/model-sources",
                    "read_only": True,
                    "bind": {"create_host_path": False},
                },
            ],
        })
    if gateway:
        service.update({
            "command": ["python", "-m", "system.gateway"],
            "environment": {
                "JYS_GATEWAY_UPSTREAM": "http://api:8026",
                "JYS_GATEWAY_API_KEY_FILE": "/run/secrets/jys_api_key",
                "JYS_GATEWAY_REQUIRE_API_KEY": "true",
                "JYS_GATEWAY_STATIC_ROOT": "/app/system/frontend",
                "JYS_GATEWAY_REQUIRE_UI_SESSION": "true",
                "JYS_GATEWAY_UI_USERNAME": "jianyuanshield-admin",
                "JYS_GATEWAY_UI_PASSWORD_FILE": "/run/secrets/jys_ui_password",
                "JYS_GATEWAY_SESSION_SECRET_FILE": "/run/secrets/jys_session_secret",
            },
            "secrets": [
                {"target": "/run/secrets/jys_api_key"},
                {"target": "/run/secrets/jys_ui_password"},
                {"target": "/run/secrets/jys_session_secret"},
            ],
        })
    return service


def production_payload() -> dict:
    return {
        "services": {
            "api": hardened_service(api=True),
            "web": hardened_service(api=False, gateway=True),
        },
        "networks": {"private": {"internal": True}},
    }


def competition_payload() -> dict:
    api = hardened_service(api=True)
    api.update({
        "pull_policy": "never",
        "cpus": 8,
        "mem_limit": "24g",
        "shm_size": "4g",
        "healthcheck": {"test": ["CMD", "true"]},
        "ports": [],
        "networks": {"backend": None},
        "deploy": {
            "resources": {
                "reservations": {
                    "devices": [
                        {"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}
                    ]
                }
            }
        },
    })
    api["environment"].update({
        "JYS_PROVENANCE_DB": "/app/runtime/state/provenance.sqlite3",
        "JYS_AUDIT_ANCHOR": "/app/runtime/audit-anchor/provenance-audit-anchor.json",
        "JYS_WARMUP_MODELS": "true",
        "JYS_INFER_DEVICE": "cuda:0",
    })
    api["volumes"].extend([
        {
            "type": "bind",
            "target": "/app/data",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
        {
            "type": "bind",
            "target": "/app/runtime/reports",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
        {"type": "volume", "source": "assets", "target": "/app/runtime/assets"},
        {"type": "volume", "source": "state", "target": "/app/runtime/state"},
        {"type": "volume", "source": "anchor", "target": "/app/runtime/audit-anchor"},
    ])
    gateway = hardened_service(api=False, gateway=True)
    gateway.update({
        "pull_policy": "never",
        "cpus": 1,
        "mem_limit": "512m",
        "healthcheck": {"test": ["CMD", "true"]},
        "networks": {"backend": None, "edge": None},
    })
    return {
        "services": {"api": api, "gateway": gateway},
        "networks": {"backend": {"internal": True}, "edge": {}},
    }


class DeploymentContractTests(unittest.TestCase):
    def test_development_compose_uses_only_the_loopback_ui_bypass(self) -> None:
        compose_path = ROOT / "docker-compose.yml"
        source = compose_path.read_text(encoding="utf-8")
        self.assertIn('JYS_GATEWAY_DEVELOPMENT_UI_BYPASS: "true"', source)
        self.assertIn('JYS_GATEWAY_REQUIRE_UI_SESSION: "false"', source)
        self.assertIn('JYS_GATEWAY_REQUIRE_API_KEY: "false"', source)
        self.assertIn(
            '"127.0.0.1:${JYS_FRONTEND_PORT:-8027}:8027"',
            source,
        )

        for compose_name in (
            "docker-compose.production.yml",
            "docker-compose.competition.yml",
        ):
            production_source = (ROOT / compose_name).read_text(encoding="utf-8")
            self.assertNotIn("JYS_GATEWAY_DEVELOPMENT_UI_BYPASS", production_source)

        if not shutil.which("docker"):
            return
        compose_available = subprocess.run(
            ["docker", "compose", "version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if compose_available.returncode != 0:
            return
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_path),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        gateway = payload["services"]["web"]
        environment = gateway["environment"]

        self.assertEqual(environment["JYS_GATEWAY_DEVELOPMENT_UI_BYPASS"], "true")
        self.assertEqual(environment["JYS_GATEWAY_REQUIRE_UI_SESSION"], "false")
        self.assertEqual(environment["JYS_GATEWAY_REQUIRE_API_KEY"], "false")
        self.assertNotIn("JYS_GATEWAY_API_KEY_FILE", environment)
        self.assertEqual(
            {binding["host_ip"] for binding in gateway["ports"]},
            {"127.0.0.1"},
        )

    def test_caddy_serves_only_the_atomic_current_release(self) -> None:
        source = (ROOT / "deployment" / "Caddyfile.jianyuanshield").read_text(
            encoding="utf-8"
        )
        self.assertIn("root * /opt/JianYuanShield/current/system/frontend", source)
        self.assertIn("root * /opt/JianYuanShield/current/system/edge-api", source)
        self.assertNotIn("root * /opt/JianYuanShield/system/frontend", source)
        self.assertNotIn("root * /opt/JianYuanShield/system/edge-api", source)

    def test_caddy_recursively_denies_private_release_paths(self) -> None:
        source = (ROOT / "deployment" / "Caddyfile.jianyuanshield").read_text(
            encoding="utf-8"
        )
        self.assertIn("@private_frontend path_regexp", source)
        self.assertIn(r"\.[^/]+", source)
        for marker in (
            "backups?",
            "credentials?",
            "passwords?",
            "tokens?",
            "secrets?",
            "private[-_]?keys?",
            "pem|key|p12|pfx|pkcs8|jks|keystore|der|pub",
        ):
            self.assertIn(marker, source)
        private_handle = source.index("handle @private_frontend {")
        private_response = source.index("respond 404", private_handle)
        spa_fallback = source.index("handle_path /jianyuanshield/*")
        self.assertLess(private_handle, private_response)
        self.assertLess(private_response, spa_fallback)
        self.assertNotIn("respond @private_frontend 404", source)

    def test_caddy_pins_short_lived_public_ip_certificate_issuer(self) -> None:
        source = (ROOT / "deployment" / "Caddyfile.jianyuanshield").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://81.70.178.203 {", source)
        self.assertIn(
            "issuer acme https://acme-v02.api.letsencrypt.org/directory {",
            source,
        )
        self.assertIn("profile shortlived", source)
        self.assertIn("default_sni 81.70.178.203", source)

    def test_caddy_normalizes_proxy_security_headers(self) -> None:
        source = (ROOT / "deployment" / "Caddyfile.jianyuanshield").read_text(
            encoding="utf-8"
        )
        for header in (
            "Server",
            "Date",
            "Via",
            "Content-Security-Policy",
            "Cross-Origin-Opener-Policy",
            "Permissions-Policy",
            "Referrer-Policy",
            "X-Content-Type-Options",
            "X-Frame-Options",
        ):
            self.assertEqual(source.count(f"header_down -{header}"), 2)

    def test_frontend_uses_same_origin_api_gateway_in_browser_mode(self) -> None:
        source = (ROOT / "system" / "frontend" / "app.js").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"location\.hostname[^\n]{0,80}:8026")
        self.assertIn("configured || window.location.origin", source)
        self.assertIn('API.endsWith("/api")', source)
        self.assertIn("fetchWithTimeout(apiURL(path)", source)

    def test_hardened_production_contract_is_accepted(self) -> None:
        self.assertEqual(validate_production(production_payload()), [])

    def test_hardened_competition_contract_is_accepted(self) -> None:
        self.assertEqual(validate_competition(competition_payload()), [])

    def test_mutable_release_image_and_public_bind_are_rejected(self) -> None:
        payload = production_payload()
        payload["services"]["api"]["image"] = "jianyuanshield:latest"
        payload["services"]["api"]["ports"][0]["host_ip"] = "0.0.0.0"
        failures = validate_production(payload)
        self.assertTrue(any("sha256 digest" in failure for failure in failures))
        self.assertTrue(any("loopback-bound" in failure for failure in failures))

    def test_plaintext_secret_environment_is_rejected(self) -> None:
        payload = production_payload()
        payload["services"]["api"]["environment"]["JYS_API_KEY"] = "do-not-store-here"
        failures = validate_production(payload)
        self.assertTrue(any("plaintext secret environment" in failure for failure in failures))

    def test_missing_model_mount_safety_is_rejected(self) -> None:
        payload = deepcopy(production_payload())
        payload["services"]["api"]["volumes"][0]["read_only"] = False
        failures = validate_production(payload)
        self.assertTrue(any("/app/weights" in failure for failure in failures))

    def test_competition_rejects_published_backend_and_shared_audit_volume(self) -> None:
        payload = competition_payload()
        payload["services"]["api"]["ports"] = [
            {"host_ip": "127.0.0.1", "published": "8026", "target": 8026}
        ]
        payload["services"]["api"]["volumes"][-1]["source"] = "state"
        failures = validate_competition(payload)
        self.assertTrue(any("must not be directly published" in failure for failure in failures))
        self.assertTrue(any("distinct volumes" in failure for failure in failures))


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "requires a POSIX bash runtime")
class PublicReleaseDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base = Path(self.temp_dir.name)
        self.source = self.base / "source"
        self.frontend = self.source / "system" / "frontend"
        self.public_root = self.base / "public"
        self.script = ROOT / "deployment" / "deploy-public-release.sh"
        self.frontend.mkdir(parents=True)
        for name in ("index.html", "app.js", "styles.css", "trust-contracts.js"):
            (self.frontend / name).write_text(f"{name} v1\n", encoding="utf-8")

    def run_deploy(
        self,
        *arguments: str,
        release_id: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PUBLIC_ROOT": str(self.public_root),
                "PUBLIC_OWNER": f"{os.getuid()}:{os.getgid()}",
                "LARGE_PNG_BYTES": "16",
            }
        )
        if release_id is not None:
            environment.update({"SOURCE_ROOT": str(self.source), "RELEASE_ID": release_id})
        return subprocess.run(
            ["bash", str(self.script), *arguments],
            cwd=ROOT,
            env=environment,
            check=check,
            capture_output=True,
            text=True,
        )

    def test_publish_filters_files_writes_manifest_and_rolls_back(self) -> None:
        assets = self.frontend / "assets"
        assets.mkdir()
        (assets / "hero.png").write_bytes(b"p" * 17)
        (assets / "hero.webp").write_bytes(b"webp")
        (assets / "small.png").write_bytes(b"small")
        (assets / "debug.js.map").write_text("not for production", encoding="utf-8")
        backups = self.frontend / "backups"
        backups.mkdir()
        (backups / "old.js").write_text("old", encoding="utf-8")
        (self.frontend / "app.js.bak-2026").write_text("old", encoding="utf-8")

        self.run_deploy(release_id="release-a1")
        first_release = self.public_root / "releases" / "release-a1"
        current = self.public_root / "current"

        self.assertTrue(current.is_symlink())
        self.assertEqual(os.readlink(current), "releases/release-a1")
        self.assertTrue((first_release / "system/frontend/assets/hero.webp").is_file())
        self.assertTrue((first_release / "system/frontend/assets/small.png").is_file())
        self.assertFalse((first_release / "system/frontend/assets/hero.png").exists())
        self.assertFalse((first_release / "system/frontend/backups").exists())
        self.assertFalse((first_release / "system/frontend/app.js.bak-2026").exists())
        self.assertFalse((first_release / "system/frontend/assets/debug.js.map").exists())
        self.assertFalse((first_release / "system/edge-api/models-status.json").exists())

        manifest = first_release / "RELEASE-MANIFEST.sha256"
        entries = manifest.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(entries), 5)
        for entry in entries:
            expected, relative = entry.split(maxsplit=1)
            relative = relative.lstrip("*")
            actual = hashlib.sha256((first_release / relative).read_bytes()).hexdigest()
            self.assertEqual(actual, expected)
        self.assertEqual(stat.S_IMODE(first_release.stat().st_mode), 0o555)
        self.assertEqual(
            stat.S_IMODE((first_release / "system/frontend/index.html").stat().st_mode),
            0o444,
        )
        self.assertEqual(first_release.stat().st_uid, os.getuid())
        self.assertEqual(first_release.stat().st_gid, os.getgid())
        current_lstat = current.lstat()
        self.assertEqual(current_lstat.st_uid, os.getuid())
        self.assertEqual(current_lstat.st_gid, os.getgid())

        (self.frontend / "app.js").write_text("app.js v2\n", encoding="utf-8")
        self.run_deploy(release_id="release-b2")
        self.assertEqual(os.readlink(current), "releases/release-b2")
        self.assertTrue(first_release.is_dir(), "publishing must retain old releases")

        self.run_deploy("--rollback", "release-a1")
        self.assertEqual(os.readlink(current), "releases/release-a1")
        self.assertTrue((self.public_root / "releases/release-b2").is_dir())

    def test_models_status_is_copied_when_present(self) -> None:
        edge_api = self.source / "system" / "edge-api"
        edge_api.mkdir(parents=True)
        snapshot = edge_api / "models-status.json"
        snapshot.write_text('{"models": []}\n', encoding="utf-8")

        self.run_deploy(release_id="abc1234")

        released = self.public_root / "releases/abc1234/system/edge-api/models-status.json"
        self.assertEqual(released.read_text(encoding="utf-8"), snapshot.read_text(encoding="utf-8"))

    def test_unsafe_release_ids_are_rejected_without_creating_a_release(self) -> None:
        for unsafe_id in ("../escape", "/absolute", "bad id", ".", "..", "a..b", "bad/name"):
            with self.subTest(release_id=unsafe_id):
                result = self.run_deploy(release_id=unsafe_id, check=False)
                self.assertNotEqual(result.returncode, 0)
        releases = self.public_root / "releases"
        self.assertFalse(releases.exists() and any(releases.iterdir()))

    def test_rollback_refuses_a_tampered_release(self) -> None:
        self.run_deploy(release_id="release-clean")
        released_app = self.public_root / "releases/release-clean/system/frontend/app.js"
        released_app.chmod(0o644)
        released_app.write_text("tampered\n", encoding="utf-8")
        released_app.chmod(0o444)

        result = self.run_deploy("--rollback", "release-clean", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed checksum verification", result.stderr)

    def test_rollback_refuses_a_release_containing_symlinks(self) -> None:
        self.run_deploy(release_id="release-no-links")
        release = self.public_root / "releases/release-no-links"
        (release / "system/frontend").chmod(0o755)
        (release / "system/frontend/index.html").unlink()
        (release / "system/frontend/index.html").symlink_to("app.js")

        result = self.run_deploy("--rollback", "release-no-links", check=False)

        self.assertNotEqual(result.returncode, 0)

    def test_sensitive_paths_and_unrecognised_types_are_filtered_at_every_depth(self) -> None:
        candidates = {
            ".env": "root env",
            "assets/nested/.env.production": "nested env",
            "assets/nested/.git/config": "git config",
            "assets/backups/old.json": "backup",
            "assets/credentials/browser.json": "credential directory",
            "assets/nested/api-token.json": "token file",
            "assets/nested/operator-password.txt": "password file",
            "assets/nested/signing-secret.js": "secret file",
            "assets/nested/private-key.pem": "private key",
            "assets/nested/id_ed25519": "ssh private key",
            "assets/nested/archive.sqlite3": "unrecognised database",
        }
        for relative, content in candidates.items():
            target = self.frontend / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        safe = self.frontend / "assets/nested/public-data.json"
        safe.write_text('{"public": true}\n', encoding="utf-8")

        self.run_deploy(release_id="filtered-release")

        released_frontend = (
            self.public_root / "releases/filtered-release/system/frontend"
        )
        for relative in candidates:
            self.assertFalse((released_frontend / relative).exists(), relative)
        self.assertTrue((released_frontend / "assets/nested/public-data.json").is_file())

    def test_source_symlink_is_rejected_before_a_release_is_created(self) -> None:
        linked = self.frontend / "assets" / "nested" / "public.json"
        linked.parent.mkdir(parents=True)
        linked.symlink_to(self.frontend / "manifest.json")

        result = self.run_deploy(release_id="link-source", check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains a symbolic link", result.stderr)
        self.assertFalse((self.public_root / "releases/link-source").exists())


if __name__ == "__main__":
    unittest.main()
