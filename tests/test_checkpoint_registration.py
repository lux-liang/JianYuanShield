from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.register_calibrated_checkpoint import register_checkpoint
from system.backend import provenance
from tests.test_provenance import complete_calibration_payload


class CheckpointRegistrationTests(unittest.TestCase):
    def test_registers_only_a_strict_checkpoint_bound_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "fake.ckpt"
            checkpoint.write_bytes(b"registered-checkpoint")
            checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            calibration = root / "calibration.json"
            calibration.write_text(
                json.dumps(complete_calibration_payload(checkpoint_hash)),
                encoding="utf-8",
            )
            output = root / "WEIGHT_MANIFEST.json"
            args = argparse.Namespace(
                model="FakeMark",
                checkpoint=checkpoint,
                calibration=calibration,
                output=output,
                reviewed_by="reviewer-1",
                source_revision="a" * 40,
                replace_model=False,
            )
            manifest = register_checkpoint(args, weight_root=root)
            item = manifest["items"][0]
            self.assertEqual(item["file"], "fake.ckpt")
            self.assertEqual(item["calibration_artifact"], "calibration.json")
            self.assertEqual(item["sha256"], checkpoint_hash)
            self.assertEqual(item["status"], "verified")
            with patch.object(provenance, "MANIFEST", output):
                self.assertTrue(provenance._checkpoint_registered("FakeMark", checkpoint_hash))
                self.assertTrue(
                    provenance._checkpoint_calibrated(
                        "FakeMark",
                        checkpoint_hash,
                        item["verification_threshold"],
                    )
                )
            with self.assertRaises(FileExistsError):
                register_checkpoint(args, weight_root=root)

    def test_rejects_calibration_bound_to_different_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "fake.ckpt"
            checkpoint.write_bytes(b"registered-checkpoint")
            calibration = root / "calibration.json"
            calibration.write_text(
                json.dumps(complete_calibration_payload("f" * 64)),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                model="FakeMark",
                checkpoint=checkpoint,
                calibration=calibration,
                output=root / "WEIGHT_MANIFEST.json",
                reviewed_by="reviewer-1",
                source_revision="a" * 40,
                replace_model=False,
            )
            with self.assertRaisesRegex(ValueError, "does not bind"):
                register_checkpoint(args, weight_root=root)


if __name__ == "__main__":
    unittest.main()
