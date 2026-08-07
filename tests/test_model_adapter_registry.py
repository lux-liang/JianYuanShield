from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from system.backend import model_adapters
from system.evaluation.adapters.kadnet_adapter import (
    KADNET_CHECKPOINT,
    KADNET_CHECKPOINT_SHA256,
)
from system.evaluation.adapters.lidmark_adapter import (
    LIDMARK_CHECKPOINT,
    LIDMARK_CHECKPOINT_SHA256,
)


class ModelAdapterRegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        model_adapters._checkpoint_digest.cache_clear()

    def test_online_lidmark_and_kadnet_match_formal_checkpoint_registry(self) -> None:
        self.assertEqual(model_adapters.LIDMARK_CKPT, LIDMARK_CHECKPOINT)
        self.assertEqual(model_adapters.LIDMARK_CKPT_SHA256, LIDMARK_CHECKPOINT_SHA256)
        self.assertEqual(model_adapters.KADNET_CKPT, KADNET_CHECKPOINT)
        self.assertEqual(model_adapters.KADNET_CKPT_SHA256, KADNET_CHECKPOINT_SHA256)

    def test_fixed_checkpoint_selectors_reject_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "checkpoint.pth"
            checkpoint.write_bytes(b"frozen-checkpoint")
            expected = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            with (
                mock.patch.object(model_adapters, "LIDMARK_CKPT", checkpoint),
                mock.patch.object(model_adapters, "LIDMARK_CKPT_SHA256", expected),
            ):
                self.assertEqual(model_adapters.LIDMarkAdapter._find_ckpt(), checkpoint)
                checkpoint.write_bytes(b"tampered-checkpoint")
                self.assertIsNone(model_adapters.LIDMarkAdapter._find_ckpt())

            checkpoint.write_bytes(b"frozen-checkpoint")
            model_adapters._checkpoint_digest.cache_clear()
            with (
                mock.patch.object(model_adapters, "KADNET_CKPT", checkpoint),
                mock.patch.object(model_adapters, "KADNET_CKPT_SHA256", expected),
            ):
                self.assertEqual(
                    model_adapters.KADNetAdapter._find_ckpt(),
                    (checkpoint, "se", "se"),
                )
                checkpoint.write_bytes(b"tampered-checkpoint")
                self.assertEqual(
                    model_adapters.KADNetAdapter._find_ckpt(),
                    (None, None, None),
                )

    def test_checkpoint_loader_hashes_the_same_handle_before_deserialization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "checkpoint.pth"
            checkpoint.write_bytes(b"checkpoint-fixture")
            expected = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            with mock.patch.object(
                model_adapters.torch,
                "load",
                return_value={"weight": object()},
            ) as loader:
                result = model_adapters._load_pinned_checkpoint(
                    checkpoint,
                    expected,
                    map_location=model_adapters.torch.device("cpu"),
                )
            self.assertIn("weight", result)
            self.assertTrue(loader.call_args.kwargs["weights_only"])
            self.assertIs(loader.call_args.args[0].closed, True)

            checkpoint.write_bytes(b"tampered")
            with mock.patch.object(model_adapters.torch, "load") as loader:
                with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                    model_adapters._load_pinned_checkpoint(
                        checkpoint,
                        expected,
                        map_location=model_adapters.torch.device("cpu"),
                    )
            loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
