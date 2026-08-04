from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from system.backend import audit_ledger
from system.backend.signing import _public_key_fingerprint


class AuditLedgerTests(unittest.TestCase):
    def configured(self, root: Path) -> SimpleNamespace:
        private = Ed25519PrivateKey.generate()
        key_path = root / "audit-key.pem"
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
            audit_anchor=str(root / "independent" / "anchor.json"),
        )

    def database(self, path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    def test_signed_chain_and_anchor_detect_middle_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = self.configured(root)
            database = root / "records.sqlite3"
            with patch.object(audit_ledger, "settings", configured):
                connection = self.database(database)
                with connection:
                    audit_ledger.ensure_schema(connection)
                anchor = Path(configured.audit_anchor)
                audit_ledger.initialize_anchor(connection, path=anchor)
                with connection:
                    audit_ledger.append_event(
                        connection,
                        event_type="protect",
                        object_id="a" * 32,
                        object_payload={"content_id": "a" * 32},
                    )
                    audit_ledger.append_event(
                        connection,
                        event_type="verify",
                        object_id="b" * 32,
                        object_payload={"event_id": "b" * 32},
                    )
                audit_ledger.synchronize_anchor(connection, path=anchor)
                self.assertTrue(audit_ledger.verify_anchor(connection, path=anchor)["trusted"])

                with connection:
                    connection.execute("DELETE FROM audit_events WHERE sequence = 1")
                compromised = audit_ledger.verify_anchor(connection, path=anchor)
                self.assertFalse(compromised["trusted"])
                self.assertTrue(compromised["rollback_detected"])
                self.assertIn("sequence_gap:1:2", compromised["errors"])
                connection.close()

    def test_anchor_detects_tail_deletion_and_database_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = self.configured(root)
            anchor = Path(configured.audit_anchor)
            database = root / "records.sqlite3"
            with patch.object(audit_ledger, "settings", configured):
                connection = self.database(database)
                with connection:
                    audit_ledger.ensure_schema(connection)
                audit_ledger.initialize_anchor(connection, path=anchor)
                with connection:
                    first = audit_ledger.append_event(
                        connection,
                        event_type="protect",
                        object_id="a" * 32,
                        object_payload={"version": 1},
                    )
                audit_ledger.synchronize_anchor(connection, path=anchor)
                snapshot = root / "snapshot.sqlite3"
                connection.backup(sqlite3.connect(snapshot))
                with connection:
                    audit_ledger.append_event(
                        connection,
                        event_type="verify",
                        object_id="b" * 32,
                        object_payload={"version": 2},
                    )
                audit_ledger.synchronize_anchor(connection, path=anchor)
                with connection:
                    connection.execute("DELETE FROM audit_events WHERE sequence = 2")
                status = audit_ledger.verify_anchor(connection, path=anchor)
                self.assertFalse(status["trusted"])
                self.assertTrue(status["rollback_detected"])
                self.assertEqual(status["root_event_hash"], first["event_hash"])
                connection.close()

                restored = self.database(snapshot)
                restored_status = audit_ledger.verify_anchor(restored, path=anchor)
                self.assertFalse(restored_status["trusted"])
                self.assertTrue(restored_status["rollback_detected"])
                restored.close()

    def test_only_signed_database_ahead_can_advance_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = self.configured(root)
            anchor = Path(configured.audit_anchor)
            with patch.object(audit_ledger, "settings", configured):
                connection = self.database(root / "records.sqlite3")
                with connection:
                    audit_ledger.ensure_schema(connection)
                audit_ledger.initialize_anchor(connection, path=anchor)
                with connection:
                    audit_ledger.append_event(
                        connection,
                        event_type="protect",
                        object_id="a" * 32,
                        object_payload={"content_id": "a" * 32},
                    )
                recoverable = audit_ledger.verify_anchor(connection, path=anchor)
                self.assertEqual(recoverable["status"], "database_ahead_recoverable")
                self.assertTrue(recoverable["database_ahead_recoverable"])
                self.assertTrue(audit_ledger.synchronize_anchor(connection, path=anchor)["trusted"])

                with connection:
                    row = connection.execute(
                        "SELECT event_json FROM audit_events WHERE sequence = 1"
                    ).fetchone()
                    stored = json.loads(row[0])
                    stored["object_id"] = "forged"
                    connection.execute(
                        "UPDATE audit_events SET event_json = ? WHERE sequence = 1",
                        (json.dumps(stored),),
                    )
                forged = audit_ledger.verify_anchor(connection, path=anchor)
                self.assertFalse(forged["trusted"])
                self.assertIn("column_binding_mismatch:1", forged["errors"])
                connection.close()

    def test_missing_anchor_for_non_empty_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configured = self.configured(root)
            anchor = Path(configured.audit_anchor)
            with patch.object(audit_ledger, "settings", configured):
                connection = self.database(root / "records.sqlite3")
                with connection:
                    audit_ledger.append_event(
                        connection,
                        event_type="protect",
                        object_id="a" * 32,
                        object_payload={"content_id": "a" * 32},
                    )
                with self.assertRaisesRegex(audit_ledger.AuditLedgerError, "anchor is missing"):
                    audit_ledger.initialize_anchor(connection, path=anchor)
                status = audit_ledger.verify_anchor(connection, path=anchor)
                self.assertTrue(status["rollback_detected"])
                connection.close()


if __name__ == "__main__":
    unittest.main()

