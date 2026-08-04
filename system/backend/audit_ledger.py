from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .config import REPORTS
from .settings import settings
from .signing import (
    canonical_json,
    sign_payload,
    signature_public_key_fingerprint,
    verify_payload_signature,
)
from .utils import atomic_write_json


ZERO_HASH = "0" * 64
EVENT_SCHEMA = "provenance-audit-event.v1"
ANCHOR_SCHEMA = "provenance-audit-anchor.v1"


class AuditLedgerError(RuntimeError):
    """Raised when the append-only provenance ledger cannot be trusted."""


def anchor_path() -> Path:
    configured = getattr(settings, "audit_anchor", None)
    if configured:
        candidate = Path(str(configured)).expanduser()
        return candidate if candidate.is_absolute() else REPORTS / candidate
    return REPORTS / "provenance-audit-anchor.json"


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _signature(payload: dict[str, Any]) -> dict[str, Any]:
    configured = getattr(settings, "evidence_private_key", None)
    if not configured:
        return {"status": "not_configured", "signed": False}
    key_path = Path(str(configured)).expanduser()
    if not key_path.is_file():
        return {"status": "key_missing", "signed": False}
    return {"status": "signed", "signed": True, **sign_payload(payload, key_path)}


def _signature_trusted(payload: dict[str, Any], signature: Any) -> bool:
    if not isinstance(signature, dict) or signature.get("signed") is not True:
        return False
    configured = str(
        getattr(settings, "evidence_public_key_fingerprint", None) or ""
    ).strip().lower()
    actual = signature_public_key_fingerprint(signature)
    return bool(
        _is_sha256(configured)
        and _is_sha256(actual)
        and hmac.compare_digest(configured, str(actual).lower())
        and verify_payload_signature(payload, signature)
    )


def ensure_schema(connection: sqlite3.Connection) -> str:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_ledger_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            sequence INTEGER PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            object_sha256 TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            prev_event_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL UNIQUE,
            event_json TEXT NOT NULL
        );
        """
    )
    row = connection.execute(
        "SELECT value FROM audit_ledger_metadata WHERE key = 'ledger_id'"
    ).fetchone()
    if row is None:
        existing = int(
            connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        )
        if existing:
            raise AuditLedgerError("audit ledger has events but no ledger identity")
        ledger_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO audit_ledger_metadata (key, value) VALUES ('ledger_id', ?)",
            (ledger_id,),
        )
        return ledger_id
    ledger_id = str(row[0])
    if len(ledger_id) != 32 or any(c not in "0123456789abcdef" for c in ledger_id):
        raise AuditLedgerError("audit ledger identity is invalid")
    return ledger_id


def _row_payload(row: sqlite3.Row) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        stored = json.loads(row["event_json"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AuditLedgerError("audit event JSON is invalid") from exc
    if not isinstance(stored, dict):
        raise AuditLedgerError("audit event JSON is invalid")
    signature = stored.get("event_signature")
    payload = {key: value for key, value in stored.items() if key != "event_signature"}
    if not isinstance(signature, dict):
        raise AuditLedgerError("audit event signature is missing")
    return payload, signature


def append_event(
    connection: sqlite3.Connection,
    *,
    event_type: str,
    object_id: str,
    object_payload: dict[str, Any],
    created_at: int | None = None,
) -> dict[str, Any]:
    """Append one signed event inside the caller's SQLite transaction."""

    if not event_type or len(event_type) > 64:
        raise ValueError("event_type must be 1-64 characters")
    if not object_id or len(object_id) > 128:
        raise ValueError("object_id must be 1-128 characters")
    ledger_id = ensure_schema(connection)
    previous = connection.execute(
        "SELECT sequence, event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    sequence = 1 if previous is None else int(previous["sequence"]) + 1
    previous_hash = ZERO_HASH if previous is None else str(previous["event_hash"])
    if not _is_sha256(previous_hash):
        raise AuditLedgerError("previous audit event hash is invalid")
    event = {
        "schema_version": EVENT_SCHEMA,
        "ledger_id": ledger_id,
        "sequence": sequence,
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "object_id": object_id,
        "object_sha256": _sha256_payload(object_payload),
        "created_at": int(time.time()) if created_at is None else int(created_at),
        "prev_event_hash": previous_hash,
    }
    signature = _signature(event)
    stored = {**event, "event_signature": signature}
    event_hash = _sha256_payload(stored)
    connection.execute(
        """
        INSERT INTO audit_events (
            sequence, event_id, event_type, object_id, object_sha256,
            created_at, prev_event_hash, event_hash, event_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sequence,
            event["event_id"],
            event_type,
            object_id,
            event["object_sha256"],
            event["created_at"],
            previous_hash,
            event_hash,
            json.dumps(stored, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {**stored, "event_hash": event_hash}


def verify_chain(connection: sqlite3.Connection) -> dict[str, Any]:
    ledger_id = ensure_schema(connection)
    rows = connection.execute(
        "SELECT * FROM audit_events ORDER BY sequence ASC"
    ).fetchall()
    expected_sequence = 1
    expected_previous = ZERO_HASH
    errors: list[str] = []
    untrusted_sequences: list[int] = []
    root_hash = ZERO_HASH

    for row in rows:
        sequence = int(row["sequence"])
        if sequence != expected_sequence:
            errors.append(f"sequence_gap:{expected_sequence}:{sequence}")
            expected_sequence = sequence
        try:
            payload, signature = _row_payload(row)
        except AuditLedgerError as exc:
            errors.append(f"event_json_invalid:{sequence}:{exc}")
            break
        column_bindings = {
            "schema_version": EVENT_SCHEMA,
            "ledger_id": ledger_id,
            "sequence": sequence,
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "object_id": row["object_id"],
            "object_sha256": row["object_sha256"],
            "created_at": row["created_at"],
            "prev_event_hash": row["prev_event_hash"],
        }
        if payload != column_bindings:
            errors.append(f"column_binding_mismatch:{sequence}")
        if row["prev_event_hash"] != expected_previous:
            errors.append(f"previous_hash_mismatch:{sequence}")
        stored = {**payload, "event_signature": signature}
        calculated_hash = _sha256_payload(stored)
        if not hmac.compare_digest(str(row["event_hash"]), calculated_hash):
            errors.append(f"event_hash_mismatch:{sequence}")
        if not _signature_trusted(payload, signature):
            untrusted_sequences.append(sequence)
        root_hash = str(row["event_hash"])
        expected_previous = root_hash
        expected_sequence = sequence + 1

    return {
        "schema_version": "provenance-audit-chain-status.v1",
        "ledger_id": ledger_id,
        "event_count": len(rows),
        "last_sequence": len(rows),
        "root_event_hash": root_hash,
        "structural_valid": not errors,
        "all_event_signatures_trusted": not untrusted_sequences,
        "trusted": not errors and not untrusted_sequences,
        "errors": errors,
        "untrusted_sequences": untrusted_sequences,
    }


def _anchor_payload(chain: dict[str, Any], *, updated_at: int | None = None) -> dict[str, Any]:
    return {
        "schema_version": ANCHOR_SCHEMA,
        "ledger_id": chain["ledger_id"],
        "sequence": chain["last_sequence"],
        "root_event_hash": chain["root_event_hash"],
        "updated_at": int(time.time()) if updated_at is None else int(updated_at),
    }


def _read_anchor(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AuditLedgerError("audit anchor is unreadable") from exc
    if not isinstance(stored, dict):
        raise AuditLedgerError("audit anchor is invalid")
    signature = stored.get("anchor_signature")
    payload = {key: value for key, value in stored.items() if key != "anchor_signature"}
    if not isinstance(signature, dict):
        raise AuditLedgerError("audit anchor signature is missing")
    return payload, signature


def initialize_anchor(
    connection: sqlite3.Connection,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Create the independent signed genesis anchor for an empty ledger."""

    target = path or anchor_path()
    chain = verify_chain(connection)
    if target.exists():
        return verify_anchor(connection, path=target)
    if chain["event_count"] != 0:
        raise AuditLedgerError("audit anchor is missing for a non-empty ledger")
    payload = _anchor_payload(chain)
    signature = _signature(payload)
    atomic_write_json(target, {**payload, "anchor_signature": signature})
    return verify_anchor(connection, path=target)


def verify_anchor(
    connection: sqlite3.Connection,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    target = path or anchor_path()
    chain = verify_chain(connection)
    if not target.is_file():
        return {
            **chain,
            "status": "anchor_missing",
            "anchor_path": target.name,
            "anchor_trusted": False,
            "anchor_matches_database": False,
            "rollback_detected": chain["event_count"] > 0,
            "trusted": False,
        }
    try:
        payload, signature = _read_anchor(target)
    except AuditLedgerError as exc:
        return {
            **chain,
            "status": "anchor_invalid",
            "anchor_path": target.name,
            "anchor_trusted": False,
            "anchor_matches_database": False,
            "rollback_detected": True,
            "trusted": False,
            "errors": [*chain["errors"], str(exc)],
        }

    anchor_trusted = _signature_trusted(payload, signature)
    same_ledger = payload.get("ledger_id") == chain["ledger_id"]
    try:
        anchor_sequence = int(payload["sequence"])
    except (KeyError, TypeError, ValueError):
        anchor_sequence = -1
    anchor_root = payload.get("root_event_hash")
    exact_match = bool(
        payload.get("schema_version") == ANCHOR_SCHEMA
        and same_ledger
        and anchor_sequence == chain["last_sequence"]
        and _is_sha256(anchor_root)
        and hmac.compare_digest(str(anchor_root), chain["root_event_hash"])
    )
    prefix_match = False
    if (
        same_ledger
        and 0 <= anchor_sequence < chain["last_sequence"]
        and _is_sha256(anchor_root)
    ):
        expected_root = ZERO_HASH
        if anchor_sequence:
            row = connection.execute(
                "SELECT event_hash FROM audit_events WHERE sequence = ?",
                (anchor_sequence,),
            ).fetchone()
            expected_root = str(row[0]) if row is not None else ""
        prefix_match = hmac.compare_digest(str(anchor_root), expected_root)
    prefix_consistent = prefix_match and chain["structural_valid"]
    database_ahead = prefix_consistent and chain["trusted"] and anchor_trusted
    rollback_detected = bool(
        not same_ledger
        or anchor_sequence > chain["last_sequence"]
        or (
            0 <= anchor_sequence <= chain["last_sequence"]
            and not exact_match
            and not prefix_consistent
        )
    )
    trusted = bool(chain["trusted"] and anchor_trusted and exact_match)
    status = (
        "trusted"
        if trusted
        else "database_ahead_recoverable"
        if database_ahead
        else "rollback_or_replacement_detected"
        if rollback_detected
        else "untrusted_signature"
    )
    return {
        **chain,
        "status": status,
        "anchor_path": target.name,
        "anchor_sequence": anchor_sequence,
        "anchor_root_event_hash": anchor_root,
        "anchor_trusted": anchor_trusted,
        "anchor_matches_database": exact_match,
        "database_ahead_recoverable": database_ahead,
        "database_ahead_structurally_consistent": prefix_consistent,
        "rollback_detected": rollback_detected,
        "trusted": trusted,
    }


def synchronize_anchor(
    connection: sqlite3.Connection,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Advance an existing valid anchor after a committed signed append."""

    target = path or anchor_path()
    status = verify_anchor(connection, path=target)
    if status["trusted"]:
        return status
    if not status.get("database_ahead_recoverable"):
        raise AuditLedgerError(f"audit anchor cannot be advanced: {status['status']}")
    chain = verify_chain(connection)
    if not chain["trusted"]:
        raise AuditLedgerError("audit chain is not fully signature-trusted")
    payload = _anchor_payload(chain)
    signature = _signature(payload)
    if not _signature_trusted(payload, signature):
        raise AuditLedgerError("new audit anchor signature is not trusted")
    atomic_write_json(target, {**payload, "anchor_signature": signature})
    result = verify_anchor(connection, path=target)
    if not result["trusted"]:
        raise AuditLedgerError("new audit anchor did not verify")
    return result
