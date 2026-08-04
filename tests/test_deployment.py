from __future__ import annotations

from copy import deepcopy
from pathlib import Path
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
            },
            "secrets": [{"target": "/run/secrets/jys_api_key"}],
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


if __name__ == "__main__":
    unittest.main()
