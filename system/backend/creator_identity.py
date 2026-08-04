from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .settings import settings
from .signing import (
    canonical_json,
    sign_payload,
    signature_public_key_fingerprint,
    verify_payload_signature,
)


CHALLENGE_SCHEMA = "creator-identity-challenge.v1"
PROOF_SCHEMA = "creator-identity-proof.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")


class CreatorIdentityError(ValueError):
    pass


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS creator_identity_challenges (
            challenge_id TEXT PRIMARY KEY,
            creator_key_fingerprint TEXT NOT NULL,
            creator_public_key_pem TEXT NOT NULL,
            creator_ref TEXT NOT NULL,
            owner_scope TEXT NOT NULL,
            model TEXT NOT NULL,
            image_sha256 TEXT NOT NULL,
            nonce_base64 TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            used_at INTEGER,
            challenge_json TEXT NOT NULL
        )
        """
    )


def _load_public_key(public_key_pem: str) -> tuple[Ed25519PublicKey, str, str]:
    if not isinstance(public_key_pem, str) or len(public_key_pem.encode("utf-8")) > 2048:
        raise CreatorIdentityError("creator public key is invalid")
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise CreatorIdentityError("creator public key must be Ed25519 PEM") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise CreatorIdentityError("creator public key must be Ed25519")
    canonical_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return public_key, canonical_pem, hashlib.sha256(public_der).hexdigest()


def _server_signature(payload: dict[str, Any]) -> dict[str, Any]:
    configured = getattr(settings, "evidence_private_key", None)
    if not configured:
        return {"status": "not_configured", "signed": False}
    from pathlib import Path

    key_path = Path(str(configured)).expanduser()
    if not key_path.is_file():
        return {"status": "key_missing", "signed": False}
    return {"status": "signed", "signed": True, **sign_payload(payload, key_path)}


def _server_signature_trusted(payload: dict[str, Any], signature: Any) -> bool:
    if not isinstance(signature, dict) or signature.get("signed") is not True:
        return False
    pinned = str(
        getattr(settings, "evidence_public_key_fingerprint", None) or ""
    ).strip().lower()
    actual = signature_public_key_fingerprint(signature)
    return bool(
        _SHA256_RE.fullmatch(pinned)
        and isinstance(actual, str)
        and hmac.compare_digest(pinned, actual.lower())
        and verify_payload_signature(payload, signature)
    )


def _creator_ref(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 128
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise CreatorIdentityError("creator_ref must be 1-128 printable characters")
    return normalized


def issue_challenge(
    connection: sqlite3.Connection,
    *,
    creator_public_key_pem: str,
    creator_ref: str,
    model: str,
    image_sha256: str,
    now: int | None = None,
) -> dict[str, Any]:
    ensure_schema(connection)
    _, canonical_pem, fingerprint = _load_public_key(creator_public_key_pem)
    creator_ref = _creator_ref(creator_ref)
    if not _MODEL_RE.fullmatch(model):
        raise CreatorIdentityError("model is invalid")
    if not _SHA256_RE.fullmatch(image_sha256):
        raise CreatorIdentityError("image_sha256 must be lowercase SHA-256")
    created_at = int(time.time()) if now is None else int(now)
    ttl = int(getattr(settings, "creator_challenge_ttl_seconds", 300))
    if ttl <= 0 or ttl > 900:
        raise CreatorIdentityError("creator challenge TTL must be 1-900 seconds")
    challenge = {
        "schema_version": CHALLENGE_SCHEMA,
        "challenge_id": uuid.uuid4().hex,
        "nonce_base64": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        "creator_ref": creator_ref,
        "creator_key_fingerprint_sha256": fingerprint,
        "owner_scope": f"ed25519:{fingerprint}",
        "model": model,
        "image_sha256": image_sha256,
        "created_at": created_at,
        "expires_at": created_at + ttl,
    }
    server_signature = _server_signature(challenge)
    stored = {**challenge, "server_signature": server_signature}
    connection.execute(
        """
        INSERT INTO creator_identity_challenges (
            challenge_id, creator_key_fingerprint, creator_public_key_pem,
            creator_ref, owner_scope, model, image_sha256, nonce_base64,
            created_at, expires_at, used_at, challenge_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        (
            challenge["challenge_id"],
            fingerprint,
            canonical_pem,
            creator_ref,
            challenge["owner_scope"],
            model,
            image_sha256,
            challenge["nonce_base64"],
            created_at,
            challenge["expires_at"],
            json.dumps(stored, ensure_ascii=False, sort_keys=True),
        ),
    )
    return {
        **stored,
        "signing_message_base64": base64.b64encode(canonical_json(challenge)).decode("ascii"),
        "server_signature_trusted": _server_signature_trusted(challenge, server_signature),
    }


def _stored_challenge(row: sqlite3.Row) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        stored = json.loads(row["challenge_json"])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise CreatorIdentityError("stored creator challenge is invalid") from exc
    if not isinstance(stored, dict):
        raise CreatorIdentityError("stored creator challenge is invalid")
    signature = stored.get("server_signature")
    challenge = {key: value for key, value in stored.items() if key != "server_signature"}
    bindings = {
        "schema_version": CHALLENGE_SCHEMA,
        "challenge_id": row["challenge_id"],
        "nonce_base64": row["nonce_base64"],
        "creator_ref": row["creator_ref"],
        "creator_key_fingerprint_sha256": row["creator_key_fingerprint"],
        "owner_scope": row["owner_scope"],
        "model": row["model"],
        "image_sha256": row["image_sha256"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }
    if challenge != bindings or not isinstance(signature, dict):
        raise CreatorIdentityError("creator challenge database binding is invalid")
    return challenge, signature


def consume_challenge(
    connection: sqlite3.Connection,
    *,
    challenge_id: str,
    creator_signature_base64: str,
    creator_ref: str,
    model: str,
    image_sha256: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify key possession and atomically burn a one-time protect intent."""

    ensure_schema(connection)
    if len(challenge_id) != 32 or any(c not in "0123456789abcdef" for c in challenge_id):
        raise CreatorIdentityError("challenge_id is invalid")
    row = connection.execute(
        "SELECT * FROM creator_identity_challenges WHERE challenge_id = ?",
        (challenge_id,),
    ).fetchone()
    if row is None:
        raise CreatorIdentityError("creator challenge not found")
    challenge, server_signature = _stored_challenge(row)
    current_time = int(time.time()) if now is None else int(now)
    if row["used_at"] is not None:
        raise CreatorIdentityError("creator challenge was already used")
    if current_time > int(row["expires_at"]):
        raise CreatorIdentityError("creator challenge expired")
    if (
        challenge["creator_ref"] != _creator_ref(creator_ref)
        or challenge["model"] != model
        or challenge["image_sha256"] != image_sha256
    ):
        raise CreatorIdentityError("protect intent does not match creator challenge")
    if getattr(settings, "mode", "real_inference").strip().lower() == "production" and not (
        _server_signature_trusted(challenge, server_signature)
    ):
        raise CreatorIdentityError("creator challenge server signature is not trusted")
    public_key, canonical_pem, fingerprint = _load_public_key(row["creator_public_key_pem"])
    if not hmac.compare_digest(fingerprint, row["creator_key_fingerprint"]):
        raise CreatorIdentityError("creator public key fingerprint mismatch")
    try:
        signature = base64.b64decode(creator_signature_base64, validate=True)
        if len(signature) != 64:
            raise ValueError
        public_key.verify(signature, canonical_json(challenge))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise CreatorIdentityError("creator signature is invalid") from exc
    updated = connection.execute(
        """
        UPDATE creator_identity_challenges
        SET used_at = ?
        WHERE challenge_id = ? AND used_at IS NULL
        """,
        (current_time, challenge_id),
    )
    if updated.rowcount != 1:
        raise CreatorIdentityError("creator challenge was already used")
    proof_payload = {
        "schema_version": PROOF_SCHEMA,
        "challenge": challenge,
        "creator_public_key_pem": canonical_pem,
        "creator_signature_base64": creator_signature_base64,
        "verified_at": current_time,
    }
    return {
        **proof_payload,
        "owner_scope": challenge["owner_scope"],
        "creator_key_fingerprint_sha256": fingerprint,
        "challenge_sha256": hashlib.sha256(canonical_json(challenge)).hexdigest(),
        "proof_sha256": hashlib.sha256(canonical_json(proof_payload)).hexdigest(),
        "key_possession_verified": True,
        "natural_person_identity_verified": False,
    }


def verify_creator_proof(proof: Any) -> bool:
    if not isinstance(proof, dict) or proof.get("schema_version") != PROOF_SCHEMA:
        return False
    challenge = proof.get("challenge")
    if not isinstance(challenge, dict) or challenge.get("schema_version") != CHALLENGE_SCHEMA:
        return False
    try:
        public_key, canonical_pem, fingerprint = _load_public_key(
            proof["creator_public_key_pem"]
        )
        signature = base64.b64decode(proof["creator_signature_base64"], validate=True)
        public_key.verify(signature, canonical_json(challenge))
    except (KeyError, InvalidSignature, CreatorIdentityError, ValueError, TypeError):
        return False
    return bool(
        canonical_pem == proof["creator_public_key_pem"]
        and fingerprint == challenge.get("creator_key_fingerprint_sha256")
        and proof.get("owner_scope") == challenge.get("owner_scope")
        and proof.get("creator_key_fingerprint_sha256") == fingerprint
        and proof.get("challenge_sha256")
        == hashlib.sha256(canonical_json(challenge)).hexdigest()
    )

