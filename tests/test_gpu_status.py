from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from system.backend import gpu
from system.backend.security import ApiKeyAuthMiddleware


NVIDIA_SMI_OUTPUT = (
    "5, GPU-5555, NVIDIA H100 80GB HBM3, 81559, 14137, 67422, 64, 67, 311.40, 700.00\n"
    "6, GPU-6666, NVIDIA H100 80GB HBM3, 81559, 1251, 80308, 0, 40, 211.62, 700.00\n"
)


class GpuStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        gpu._cached_devices = None
        gpu._cached_at = 0.0

    def test_payload_selects_configured_physical_gpu(self) -> None:
        completed = SimpleNamespace(stdout=NVIDIA_SMI_OUTPUT)
        with (
            patch.object(gpu.subprocess, "run", return_value=completed) as run,
            patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "6"}),
            patch.object(gpu.socket, "gethostname", return_value="h100-node"),
        ):
            payload = gpu.gpu_status_payload(
                inference={
                    "state": "ready",
                    "running": 0,
                    "queued": 0,
                    "max_concurrent": 1,
                    "max_queue": 4,
                }
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["node"], "h100-node")
        self.assertEqual(payload["device_mapping"]["physical_index"], 6)
        self.assertEqual(payload["device_mapping"]["runtime_device"], "cuda:0")
        self.assertEqual(payload["gpu"]["memory"]["used_mib"], 1251)
        self.assertEqual(payload["gpu"]["memory"]["used_percent"], 1.5)
        self.assertEqual(payload["gpu"]["temperature_c"], 40)
        run.assert_called_once()

    def test_samples_are_cached_for_short_poll_bursts(self) -> None:
        completed = SimpleNamespace(stdout=NVIDIA_SMI_OUTPUT)
        with (
            patch.object(gpu.subprocess, "run", return_value=completed) as run,
            patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "GPU-6666"}),
        ):
            first = gpu.gpu_status_payload(inference={})
            second = gpu.gpu_status_payload(inference={})

        self.assertEqual(first["gpu"]["uuid"], "GPU-6666")
        self.assertEqual(second["gpu"]["uuid"], "GPU-6666")
        run.assert_called_once()

    def test_missing_selected_device_fails_closed(self) -> None:
        completed = SimpleNamespace(stdout=NVIDIA_SMI_OUTPUT)
        with (
            patch.object(gpu.subprocess, "run", return_value=completed),
            patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "7"}),
        ):
            with self.assertRaises(gpu.GpuStatusError):
                gpu.gpu_status_payload(inference={})

    def test_nonfinite_fractional_and_inconsistent_telemetry_fail_closed(self) -> None:
        invalid_rows = (
            NVIDIA_SMI_OUTPUT.replace("0, 40", "nan, 40"),
            NVIDIA_SMI_OUTPUT.replace("6, GPU-6666", "6.5, GPU-6666"),
            NVIDIA_SMI_OUTPUT.replace("1251, 80308", "90000, -8441"),
        )
        for output in invalid_rows:
            with self.subTest(output=output.splitlines()[-1]):
                with self.assertRaises(gpu.GpuStatusError):
                    gpu._parse_devices(output)

    def test_gpu_identity_and_load_are_not_public_without_api_auth(self) -> None:
        self.assertNotIn("/api/system/gpu", ApiKeyAuthMiddleware.PUBLIC_API_PATHS)


if __name__ == "__main__":
    unittest.main()
