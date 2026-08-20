from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import inspect
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from system.backend import benchmark_evidence, routes


class BenchmarkEvidenceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        benchmark_evidence._cached_benchmark_claim_status.cache_clear()

    def tearDown(self) -> None:
        benchmark_evidence._cached_benchmark_claim_status.cache_clear()

    def test_cache_coalesces_concurrent_audits_and_returns_copies(self) -> None:
        calls = 0

        def validate(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            time.sleep(0.05)
            return {"claim_valid": True, "nested": {"value": 1}}

        with (
            patch.object(
                benchmark_evidence,
                "_benchmark_dependency_token",
                return_value=(("stable", 1),),
            ),
            patch.object(
                benchmark_evidence,
                "_benchmark_claim_status_uncached",
                side_effect=validate,
            ),
        ):
            with ThreadPoolExecutor(max_workers=12) as pool:
                results = list(
                    pool.map(
                        lambda _index: benchmark_evidence.benchmark_claim_status(
                            {"status": "complete"},
                            summary_path=Path("summary.json"),
                            results_path=Path("results.csv"),
                        ),
                        range(12),
                    )
                )

        self.assertEqual(calls, 1)
        self.assertTrue(all(item["claim_valid"] for item in results))
        results[0]["nested"]["value"] = 99
        self.assertEqual(results[1]["nested"]["value"], 1)

    def test_dependency_identity_change_invalidates_cached_result(self) -> None:
        tokens = [
            (("stable", 1),),
            (("stable", 1),),
            (("stable", 2),),
            (("stable", 2),),
        ]
        with (
            patch.object(
                benchmark_evidence,
                "_benchmark_dependency_token",
                side_effect=tokens,
            ),
            patch.object(
                benchmark_evidence,
                "_benchmark_claim_status_uncached",
                side_effect=[{"generation": 1}, {"generation": 2}],
            ) as validate,
        ):
            first = benchmark_evidence.benchmark_claim_status(
                {}, summary_path=Path("summary.json"), results_path=Path("results.csv")
            )
            second = benchmark_evidence.benchmark_claim_status(
                {}, summary_path=Path("summary.json"), results_path=Path("results.csv")
            )

        self.assertEqual(first["generation"], 1)
        self.assertEqual(second["generation"], 2)
        self.assertEqual(validate.call_count, 2)

    def test_continuous_dependency_drift_fails_closed(self) -> None:
        tokens = [(("drift", index),) for index in range(6)]
        with (
            patch.object(
                benchmark_evidence,
                "_benchmark_dependency_token",
                side_effect=tokens,
            ),
            patch.object(
                benchmark_evidence,
                "_benchmark_claim_status_uncached",
                return_value={"claim_valid": True},
            ),
        ):
            result = benchmark_evidence.benchmark_claim_status(
                {}, summary_path=Path("summary.json"), results_path=Path("results.csv")
            )

        self.assertFalse(result["claim_valid"])
        self.assertEqual(
            result["claim_status"],
            "benchmark_artifacts_changed_during_validation",
        )

    def test_public_liveness_route_does_not_use_sync_worker_pool(self) -> None:
        endpoints = {
            route.path: route.endpoint
            for route in routes.router.routes
            if route.path in {"/api/health", "/api/projects"}
        }
        self.assertEqual(set(endpoints), {"/api/health", "/api/projects"})
        self.assertTrue(all(inspect.iscoroutinefunction(value) for value in endpoints.values()))


if __name__ == "__main__":
    unittest.main()
