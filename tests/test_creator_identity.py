from __future__ import annotations

import base64
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from system.backend import creator_identity
from system.backend.signing import _public_key_fingerprint, canonical_json


class CreatorIdentityTests(unittest.TestCase):
    def configured(self, root: Path, *, mode: str = "production") -> tuple[SimpleNamespace, Ed25519PrivateKey]:
        server_private = Ed25519PrivateKey.generate()
        server_path = root / "server.pem"
        server_path.write_bytes(
            server_private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        return SimpleNamespace(
            evidence_private_key=str(server_path),
            evidence_public_key_fingerprint=_public_key_fingerprint(server_private.public_key()),
            creator_challenge_ttl_seconds=300,
            mode=mode,
        ), Ed25519PrivateKey.generate()

    def connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        return connection

    def public_pem(self, private: Ed25519PrivateKey) -> str:
        return private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def test_challenge_proves_key_possession_and_is_one_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configured, creator_private = self.configured(Path(directory))
            connection = self.connection()
            with patch.object(creator_identity, "settings", configured):
                with connection:
                    issued = creator_identity.issue_challenge(
                        connection,
                        creator_public_key_pem=self.public_pem(creator_private),
                        creator_ref="creator-001",
                        model="KAD-Net",
                        image_sha256="a" * 64,
                        now=100,
                    )
                self.assertTrue(issued["server_signature_trusted"])
                creator_signature = base64.b64encode(
                    creator_private.sign(base64.b64decode(issued["signing_message_base64"]))
                ).decode("ascii")
                with connection:
                    proof = creator_identity.consume_challenge(
                        connection,
                        challenge_id=issued["challenge_id"],
                        creator_signature_base64=creator_signature,
                        creator_ref="creator-001",
                        model="KAD-Net",
                        image_sha256="a" * 64,
                        now=101,
                    )
                self.assertTrue(proof["key_possession_verified"])
                self.assertFalse(proof["natural_person_identity_verified"])
                self.assertTrue(creator_identity.verify_creator_proof(proof))
                with self.assertRaisesRegex(creator_identity.CreatorIdentityError, "already used"):
                    with connection:
                        creator_identity.consume_challenge(
                            connection,
                            challenge_id=issued["challenge_id"],
                            creator_signature_base64=creator_signature,
                            creator_ref="creator-001",
                            model="KAD-Net",
                            image_sha256="a" * 64,
                            now=102,
                        )
            connection.close()

    def test_forged_creator_ref_and_wrong_key_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configured, creator_private = self.configured(Path(directory))
            attacker = Ed25519PrivateKey.generate()
            connection = self.connection()
            with patch.object(creator_identity, "settings", configured):
                with connection:
                    issued = creator_identity.issue_challenge(
                        connection,
                        creator_public_key_pem=self.public_pem(creator_private),
                        creator_ref="creator-001",
                        model="KAD-Net",
                        image_sha256="b" * 64,
                        now=100,
                    )
                attacker_signature = base64.b64encode(
                    attacker.sign(canonical_json({
                        key: value
                        for key, value in issued.items()
                        if key not in {"server_signature", "signing_message_base64", "server_signature_trusted"}
                    }))
                ).decode("ascii")
                with self.assertRaisesRegex(creator_identity.CreatorIdentityError, "intent does not match"):
                    with connection:
                        creator_identity.consume_challenge(
                            connection,
                            challenge_id=issued["challenge_id"],
                            creator_signature_base64=attacker_signature,
                            creator_ref="impersonated",
                            model="KAD-Net",
                            image_sha256="b" * 64,
                            now=101,
                        )
                with self.assertRaisesRegex(creator_identity.CreatorIdentityError, "signature is invalid"):
                    with connection:
                        creator_identity.consume_challenge(
                            connection,
                            challenge_id=issued["challenge_id"],
                            creator_signature_base64=attacker_signature,
                            creator_ref="creator-001",
                            model="KAD-Net",
                            image_sha256="b" * 64,
                            now=101,
                        )
            connection.close()

    def test_expired_challenge_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configured, creator_private = self.configured(Path(directory))
            configured.creator_challenge_ttl_seconds = 5
            connection = self.connection()
            with patch.object(creator_identity, "settings", configured):
                with connection:
                    issued = creator_identity.issue_challenge(
                        connection,
                        creator_public_key_pem=self.public_pem(creator_private),
                        creator_ref="creator-001",
                        model="KAD-Net",
                        image_sha256="c" * 64,
                        now=100,
                    )
                creator_signature = base64.b64encode(
                    creator_private.sign(base64.b64decode(issued["signing_message_base64"]))
                ).decode("ascii")
                with self.assertRaisesRegex(creator_identity.CreatorIdentityError, "expired"):
                    with connection:
                        creator_identity.consume_challenge(
                            connection,
                            challenge_id=issued["challenge_id"],
                            creator_signature_base64=creator_signature,
                            creator_ref="creator-001",
                            model="KAD-Net",
                            image_sha256="c" * 64,
                            now=106,
                        )
            connection.close()

    def test_proof_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            configured, creator_private = self.configured(Path(directory))
            connection = self.connection()
            with patch.object(creator_identity, "settings", configured):
                with connection:
                    issued = creator_identity.issue_challenge(
                        connection,
                        creator_public_key_pem=self.public_pem(creator_private),
                        creator_ref="creator-001",
                        model="KAD-Net",
                        image_sha256="d" * 64,
                        now=100,
                    )
                signature = base64.b64encode(
                    creator_private.sign(base64.b64decode(issued["signing_message_base64"]))
                ).decode("ascii")
                with connection:
                    proof = creator_identity.consume_challenge(
                        connection,
                        challenge_id=issued["challenge_id"],
                        creator_signature_base64=signature,
                        creator_ref="creator-001",
                        model="KAD-Net",
                        image_sha256="d" * 64,
                        now=101,
                    )
                proof["challenge"]["creator_ref"] = "forged"
                self.assertFalse(creator_identity.verify_creator_proof(proof))
            connection.close()


if __name__ == "__main__":
    unittest.main()

