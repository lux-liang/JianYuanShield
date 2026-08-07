from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from system.evaluation.runtime import resolve_logical_path  # noqa: E402


MANIFEST_PATH = ROOT / "configs" / "claims_manifest.v1.json"
EXPECTED_SCHEMA = "claims-manifest.v1"
EXPECTED_PUBLISHABLE_STATUSES = {"implemented", "verified", "publishable"}
REQUIRED_CLAIM_FIELDS = {
    "claim_id",
    "statement",
    "claim_type",
    "status",
    "requested_for_submission",
    "evidence",
    "limitations",
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
RUNTIME_PREFIXES = {"data", "weights", "reports", "assets", "model-sources"}


def _inside_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _evidence_path(reference: str) -> Path | None:
    raw = Path(reference)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    if raw.parts and raw.parts[0] in RUNTIME_PREFIXES:
        return resolve_logical_path(raw)
    candidate = (ROOT / raw).resolve()
    return candidate if _inside_root(candidate) else None


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _local_link_target(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = target.split(maxsplit=1)[0]
    target = target.split("#", 1)[0]
    if not target or target.startswith(("#", "/", "http://", "https://", "mailto:")):
        return None
    return (document.parent / target).resolve()


def main() -> int:
    violations: list[dict[str, Any]] = []

    def fail(check: str, detail: str, *, path: str | None = None, line: int | None = None) -> None:
        item: dict[str, Any] = {"check": check, "detail": detail}
        if path is not None:
            item["path"] = path
        if line is not None:
            item["line"] = line
        violations.append(item)

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        manifest = {}
        fail("manifest_loaded", "claims manifest is missing", path=str(MANIFEST_PATH.relative_to(ROOT)))
    except json.JSONDecodeError as exc:
        manifest = {}
        fail(
            "manifest_loaded",
            f"invalid JSON: {exc.msg}",
            path=str(MANIFEST_PATH.relative_to(ROOT)),
            line=exc.lineno,
        )

    if manifest.get("schema_version") != EXPECTED_SCHEMA:
        fail("manifest_schema", f"schema_version must be {EXPECTED_SCHEMA}")

    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        policy = {}
        fail("manifest_policy", "policy must be an object")

    publishable_statuses = policy.get("publishable_statuses")
    if not isinstance(publishable_statuses, list) or set(publishable_statuses) != EXPECTED_PUBLISHABLE_STATUSES:
        fail(
            "manifest_policy",
            "publishable_statuses must match the backend claim gate",
        )
        active_publishable_statuses = EXPECTED_PUBLISHABLE_STATUSES
    else:
        active_publishable_statuses = set(publishable_statuses)

    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims:
        claims = []
        fail("claims_valid", "claims must be a non-empty list")

    claim_ids: list[str] = []
    evaluated_claims: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        label = f"claims[{index}]"
        if not isinstance(claim, dict):
            fail("claims_valid", f"{label} must be an object")
            continue
        missing_fields = sorted(REQUIRED_CLAIM_FIELDS - set(claim))
        if missing_fields:
            fail("claims_valid", f"{label} is missing fields: {', '.join(missing_fields)}")

        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", claim_id):
            fail("claims_valid", f"{label}.claim_id must be stable snake_case")
            claim_id = label
        claim_ids.append(claim_id)

        if not isinstance(claim.get("statement"), str) or not claim.get("statement", "").strip():
            fail("claims_valid", f"{claim_id}.statement must be non-empty")
        if not isinstance(claim.get("claim_type"), str) or not claim.get("claim_type", "").strip():
            fail("claims_valid", f"{claim_id}.claim_type must be non-empty")
        if not isinstance(claim.get("status"), str) or not claim.get("status", "").strip():
            fail("claims_valid", f"{claim_id}.status must be non-empty")
        if not isinstance(claim.get("requested_for_submission"), bool):
            fail("claims_valid", f"{claim_id}.requested_for_submission must be boolean")

        evidence_entries = claim.get("evidence")
        if not isinstance(evidence_entries, list):
            evidence_entries = []
            fail("claims_valid", f"{claim_id}.evidence must be a list")
        evidence_complete = bool(evidence_entries)
        for relative in evidence_entries:
            if not isinstance(relative, str) or not relative.strip():
                evidence_complete = False
                fail("evidence_paths", f"{claim_id} contains an invalid evidence path")
                continue
            candidate = _evidence_path(relative)
            raw = Path(relative)
            is_runtime_reference = bool(
                raw.parts and raw.parts[0] in RUNTIME_PREFIXES
            )
            if candidate is None:
                evidence_complete = False
                fail("evidence_paths", f"{claim_id} evidence escapes approved roots", path=relative)
            elif not is_runtime_reference and not candidate.is_file():
                evidence_complete = False
                fail("evidence_paths", f"{claim_id} evidence file is missing", path=relative)

        limitations = claim.get("limitations")
        if not isinstance(limitations, list) or not limitations or not all(
            isinstance(item, str) and item.strip() for item in limitations
        ):
            fail("claims_valid", f"{claim_id}.limitations must be a non-empty string list")

        # Runtime gates are evaluated by /api/claims; this static check never
        # assumes that mutable benchmark artifacts have passed verification.
        runtime_gate_required = claim.get("gate") is not None
        publishable = (
            str(claim.get("status")) in active_publishable_statuses
            and evidence_complete
            and not runtime_gate_required
        )
        evaluated_claims.append({
            "claim_id": claim_id,
            "status": claim.get("status"),
            "requested_for_submission": claim.get("requested_for_submission") is True,
            "evidence_complete": evidence_complete,
            "runtime_gate_required": runtime_gate_required,
            "publishable": publishable,
        })

    if len(claim_ids) != len(set(claim_ids)):
        duplicates = sorted({claim_id for claim_id in claim_ids if claim_ids.count(claim_id) > 1})
        fail("claim_ids_unique", "duplicate claim ids: " + ", ".join(duplicates))

    required_claims = [item for item in evaluated_claims if item["requested_for_submission"]]
    computed_ready = bool(required_claims) and all(item["publishable"] for item in required_claims)
    expected_ready = policy.get("expected_ready_for_claims")
    if not isinstance(expected_ready, bool):
        fail("claim_gate_state", "expected_ready_for_claims must be boolean")
    elif computed_ready != expected_ready:
        fail(
            "claim_gate_state",
            f"computed ready_for_claims={computed_ready} does not match policy={expected_ready}",
        )

    performance_claim_id = policy.get("performance_claim_id")
    performance_claim = next(
        (item for item in evaluated_claims if item["claim_id"] == performance_claim_id),
        None,
    )
    if performance_claim is None:
        fail("performance_claim_blocked", "performance claim is missing")
    elif performance_claim["publishable"] or not performance_claim["requested_for_submission"]:
        fail(
            "performance_claim_blocked",
            "performance claim must remain required and runtime-gated in the static documentation check",
        )

    deepfake_boundary = next(
        (claim for claim in claims if isinstance(claim, dict) and claim.get("claim_id") == "deepfake_robustness"),
        None,
    )
    if (
        not isinstance(deepfake_boundary, dict)
        or deepfake_boundary.get("status") != "verified"
        or deepfake_boundary.get("requested_for_submission") is not True
        or not isinstance(deepfake_boundary.get("gate"), dict)
        or deepfake_boundary["gate"].get("type") != "simswap_lfw_evidence.v1"
        or deepfake_boundary["gate"].get("run_id")
        != "simswap-lfw-robustness-n256-s20260603"
        or deepfake_boundary["gate"].get("num_pairs") != 256
        or deepfake_boundary["gate"].get("calibration_pairs") != 64
        or deepfake_boundary["gate"].get("holdout_pairs") != 192
    ):
        fail(
            "deepfake_boundary",
            "deepfake_robustness must remain bound to the signed official-SimSwap/LFW n256 gate",
        )

    document_entries = policy.get("submission_documents")
    if not isinstance(document_entries, list) or not document_entries:
        document_entries = []
        fail("documents_exist", "submission_documents must be a non-empty list")

    documents: dict[str, tuple[Path, str]] = {}
    for relative in document_entries:
        if not isinstance(relative, str) or not relative.strip():
            fail("documents_exist", "submission_documents contains an invalid path")
            continue
        path = (ROOT / relative).resolve()
        if Path(relative).is_absolute() or not _inside_root(path):
            fail("documents_exist", "document escapes the repository", path=relative)
        elif not path.is_file():
            fail("documents_exist", "required document is missing", path=relative)
        else:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                fail("documents_exist", "required document is empty", path=relative)
            documents[relative] = (path, text)

    markers = policy.get("required_document_markers")
    if not isinstance(markers, dict):
        markers = {}
        fail("required_markers", "required_document_markers must be an object")
    for relative, required_markers in markers.items():
        document = documents.get(relative)
        if document is None:
            continue
        if not isinstance(required_markers, list):
            fail("required_markers", "markers must be a list", path=relative)
            continue
        text = document[1]
        for marker in required_markers:
            if not isinstance(marker, str) or marker not in text:
                fail("required_markers", f"missing conservative marker: {marker!r}", path=relative)

    forbidden_patterns = policy.get("forbidden_document_patterns")
    if not isinstance(forbidden_patterns, list):
        forbidden_patterns = []
        fail("forbidden_patterns", "forbidden_document_patterns must be a list")
    for entry in forbidden_patterns:
        if not isinstance(entry, dict) or not isinstance(entry.get("pattern"), str):
            fail("forbidden_patterns", "invalid forbidden pattern entry")
            continue
        try:
            pattern = re.compile(entry["pattern"], re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            fail("forbidden_patterns", f"invalid regex {entry.get('id')}: {exc}")
            continue
        for relative, (_, text) in documents.items():
            match = pattern.search(text)
            if match:
                fail(
                    "forbidden_patterns",
                    f"{entry.get('id', 'unnamed')}: {entry.get('reason', 'forbidden claim')}",
                    path=relative,
                    line=_line_number(text, match.start()),
                )

    link_documents = dict(documents)
    ignored_markdown_dirs = {".git", ".venv", "node_modules"}
    for path in ROOT.rglob("*.md"):
        relative_path = path.relative_to(ROOT)
        if any(part in ignored_markdown_dirs for part in relative_path.parts):
            continue
        relative = relative_path.as_posix()
        if relative not in link_documents:
            link_documents[relative] = (path, path.read_text(encoding="utf-8"))

    for relative, (path, text) in link_documents.items():
        for match in MARKDOWN_LINK.finditer(text):
            target = _local_link_target(path, match.group(1))
            if target is None:
                continue
            if not _inside_root(target):
                fail(
                    "local_links",
                    "local Markdown link escapes the repository",
                    path=relative,
                    line=_line_number(text, match.start()),
                )
            elif not target.exists():
                fail(
                    "local_links",
                    f"local Markdown link target is missing: {match.group(1)}",
                    path=relative,
                    line=_line_number(text, match.start()),
                )

    check_names = [
        "manifest_loaded",
        "manifest_schema",
        "manifest_policy",
        "claims_valid",
        "claim_ids_unique",
        "evidence_paths",
        "claim_gate_state",
        "performance_claim_blocked",
        "deepfake_boundary",
        "documents_exist",
        "required_markers",
        "forbidden_patterns",
        "local_links",
    ]
    checks = {
        name: not any(item["check"] == name for item in violations)
        for name in check_names
    }
    status = "verified" if all(checks.values()) else "failed"
    payload = {
        "schema_version": "documentation-check.v2",
        "status": status,
        "claims": {
            "computed_ready_for_claims": computed_ready,
            "expected_ready_for_claims": expected_ready,
            "required": len(required_claims),
            "publishable": sum(1 for item in evaluated_claims if item["publishable"]),
            "blocked_required": sum(1 for item in required_claims if not item["publishable"]),
        },
        "checks": checks,
        "violations": violations,
        "files": sorted(documents),
        "markdown_links_scanned": sorted(link_documents),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if status == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
