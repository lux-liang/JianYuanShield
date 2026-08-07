from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
API_KEY = "a" * 32


class ProductionApiTests(unittest.TestCase):
    def _run(self, source: str, **updates: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        python_path = environment.get("PYTHONPATH")
        environment.update({
            "JYS_MODE": "production",
            "JYS_API_KEY": API_KEY,
            "JYS_CORS_ORIGINS": "https://console.example",
            "JYS_RATE_LIMIT_REQUESTS": "2",
            "JYS_RATE_LIMIT_WINDOW_SECONDS": "60",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": "." + (os.pathsep + python_path if python_path else ""),
        })
        environment.pop("JYS_API_KEY_FILE", None)
        environment.update(updates)
        return subprocess.run(
            [sys.executable, "-c", source],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_production_disables_schema_discovery_and_minimizes_public_health(self) -> None:
        completed = self._run(
            """
import json
from fastapi.testclient import TestClient
from system.backend.app import app
with TestClient(app, base_url='https://testserver') as client:
    docs = client.get('/docs')
    schema = client.get('/openapi.json')
    health = client.get('/api/health')
    details_denied = client.get('/api/health/details')
    print(json.dumps({
        'docs': docs.status_code,
        'schema': schema.status_code,
        'health': health.json(),
        'health_headers': dict(health.headers),
        'details_denied': details_denied.status_code,
    }))
"""
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.splitlines()[-1])
        self.assertEqual(payload["docs"], 404)
        self.assertEqual(payload["schema"], 404)
        self.assertEqual(
            set(payload["health"]),
            {"ok", "mode", "version", "timestamp"},
        )
        self.assertEqual(payload["details_denied"], 401)
        self.assertEqual(payload["health_headers"]["cache-control"], "no-store")
        self.assertEqual(payload["health_headers"]["strict-transport-security"], "max-age=31536000")

    def test_production_rate_limit_covers_public_endpoints(self) -> None:
        completed = self._run(
            """
import json
from fastapi.testclient import TestClient
from system.backend.app import app
with TestClient(app) as client:
    statuses = [
        client.get('/api/health').status_code,
        client.get('/api/projects').status_code,
        client.get('/api/claims').status_code,
    ]
    print(json.dumps(statuses))
"""
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout.splitlines()[-1]), [200, 200, 429])

    def test_production_startup_rejects_weak_api_key(self) -> None:
        completed = self._run("from system.backend.app import app", JYS_API_KEY="weak")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("at least 32 characters", completed.stderr)

    def test_production_startup_rejects_insecure_cors(self) -> None:
        completed = self._run(
            "from system.backend.app import app",
            JYS_CORS_ORIGINS="http://console.example",
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("must use HTTPS", completed.stderr)


if __name__ == "__main__":
    unittest.main()
