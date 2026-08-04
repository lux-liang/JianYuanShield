from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PIL import Image, PngImagePlugin

from system.backend import aigc_labeling
from system.backend.signing import _public_key_fingerprint


def sample_png(size: tuple[int, int] = (256, 192)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (32, 64, 96)).save(output, format="PNG")
    return output.getvalue()


class AigcLabelingTests(unittest.TestCase):
    def configured(self, root: Path) -> SimpleNamespace:
        private = Ed25519PrivateKey.generate()
        key_path = root / "key.pem"
        key_path.write_bytes(
            private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        return SimpleNamespace(
            evidence_private_key=str(key_path),
            evidence_public_key_fingerprint=_public_key_fingerprint(private.public_key()),
            content_producer="JianYuanShield-VPSG",
        )

    def test_writes_exact_standard_metadata_and_visible_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configured = self.configured(Path(directory))
            with patch.object(aigc_labeling, "settings", configured):
                fields = aigc_labeling.build_aigc_fields(
                    label="1", content_id="a" * 32
                )
                encoded, report = aigc_labeling.apply_aigc_labels(
                    sample_png(), fields=fields
                )
                inspection = aigc_labeling.inspect_aigc_png(
                    encoded, expected_content_id="a" * 32
                )
        self.assertTrue(inspection["metadata_valid"])
        self.assertEqual(inspection["metadata_chunk_count"], 1)
        self.assertEqual(inspection["fields"]["Label"], "1")
        self.assertEqual(inspection["fields"]["ContentProducer"], "JianYuanShield-VPSG")
        self.assertEqual(inspection["fields"]["ProduceID"], "a" * 32)
        self.assertEqual(inspection["fields"]["ContentPropagator"], "JianYuanShield-VPSG")
        self.assertEqual(inspection["fields"]["PropagateID"], "a" * 32)
        self.assertTrue(inspection["producer_seal_trusted"])
        self.assertEqual(report["visible_label"]["text"], "AI生成")
        self.assertTrue(report["visible_label"]["meets_minimum_height"])
        self.assertGreaterEqual(report["visible_label"]["height_ratio"], 0.05)

    def test_metadata_tampering_breaks_producer_seal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configured = self.configured(Path(directory))
            with patch.object(aigc_labeling, "settings", configured):
                fields = aigc_labeling.build_aigc_fields(
                    label="1", content_id="b" * 32
                )
                encoded, _ = aigc_labeling.apply_aigc_labels(
                    sample_png(), fields=fields
                )
                with Image.open(io.BytesIO(encoded)) as opened:
                    image = opened.convert("RGB")
                    stored = json.loads(opened.info["AIGC"])
                stored["AIGC"]["ProduceID"] = "c" * 32
                info = PngImagePlugin.PngInfo()
                info.add_text("AIGC", json.dumps(stored, separators=(",", ":")))
                output = io.BytesIO()
                image.save(output, format="PNG", pnginfo=info)
                inspection = aigc_labeling.inspect_aigc_png(output.getvalue())
        self.assertFalse(inspection["metadata_valid"])
        self.assertFalse(inspection["producer_seal"]["cryptographically_valid"])
        self.assertIn("aigc_producer_seal_invalid", inspection["errors"])

    def test_metadata_removal_is_explicitly_detected(self) -> None:
        inspection = aigc_labeling.inspect_aigc_png(sample_png())
        self.assertFalse(inspection["metadata_valid"])
        self.assertTrue(inspection["removed_or_missing"])
        self.assertIn("aigc_metadata_must_exist_exactly_once", inspection["errors"])

    def test_content_id_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configured = self.configured(Path(directory))
            with patch.object(aigc_labeling, "settings", configured):
                fields = aigc_labeling.build_aigc_fields(
                    label="2", content_id="d" * 32
                )
                encoded, _ = aigc_labeling.apply_aigc_labels(
                    sample_png(), fields=fields, visible=False
                )
                inspection = aigc_labeling.inspect_aigc_png(
                    encoded, expected_content_id="e" * 32
                )
        self.assertFalse(inspection["metadata_valid"])
        self.assertIn("aigc_content_id_mismatch", inspection["errors"])

    def test_nonstandard_values_are_rejected(self) -> None:
        with self.assertRaises(aigc_labeling.AigcLabelError):
            aigc_labeling.build_aigc_fields(
                label="4", content_id="f" * 32
            )
        with self.assertRaises(aigc_labeling.AigcLabelError):
            aigc_labeling.build_aigc_fields(
                label="1", content_id="f" * 32, producer="含中文"
            )


if __name__ == "__main__":
    unittest.main()

