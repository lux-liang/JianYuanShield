"""Short-lived, coalesced snapshots for expensive public evidence views.

The validators remain the source of truth and still run at least once per TTL.
The cache only keeps their already-validated JSON payload in process so UI
polling cannot repeatedly parse and hash the same immutable release evidence.
"""

from __future__ import annotations

from .claims import claims_payload
from .evidence import evidence_audit_payload
from .settings import settings
from .snapshot_cache import SnapshotCache


claims_snapshot = SnapshotCache(
    claims_payload,
    ttl_seconds=settings.public_snapshot_ttl_seconds,
    name="claims",
)
evidence_audit_snapshot = SnapshotCache(
    lambda: evidence_audit_payload(claims_snapshot=claims_snapshot.get()),
    ttl_seconds=settings.public_snapshot_ttl_seconds,
    name="evidence_audit",
)


def warm_public_snapshots() -> None:
    """Populate the two UI snapshots after startup without blocking liveness."""

    claims_snapshot.get()
    evidence_audit_snapshot.get()
