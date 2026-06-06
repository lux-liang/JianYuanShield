from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from system.backend import signing


class SigningTests(unittest.TestCase):
    def test_canonical_json_is_order_independent(self) -> None:
        self.assertEqual(signing.canonical_json({"b": 2, "a": 1}), signing.canonical_json({"a": 1, "b": 2}))

    def test_signature_detects_content_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "report.json"
            evidence.write_text('{"value":1}', encoding="utf-8")
            private = Ed25519PrivateKey.generate()
            manifest = {
                "schema_version": "evidence-manifest.v1",
                "files": [{
                    "path": "report.json",
                    "size_bytes": evidence.stat().st_size,
                    "sha256": signing.sha256_file(evidence),
                    "role": "evidence",
                }],
            }
            manifest_path = root / "manifest.json"
            signature_path = root / "manifest.sig"
            public_path = root / "public.pem"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            import base64
            signature_path.write_text(
                base64.b64encode(private.sign(signing.canonical_json(manifest))).decode("ascii"),
                encoding="ascii",
            )
            public_path.write_bytes(private.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))
            with patch.object(signing, "ROOT", root):
                valid = signing.verify_evidence_bundle(
                    manifest_path=manifest_path,
                    signature_path=signature_path,
                    public_key_path=public_path,
                )
                self.assertTrue(valid["verified"])
                evidence.write_text('{"value":2}', encoding="utf-8")
                invalid = signing.verify_evidence_bundle(
                    manifest_path=manifest_path,
                    signature_path=signature_path,
                    public_key_path=public_path,
                )
                self.assertFalse(invalid["verified"])
                self.assertEqual(invalid["status"], "content_mismatch")


if __name__ == "__main__":
    unittest.main()
