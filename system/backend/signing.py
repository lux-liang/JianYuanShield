from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .config import REPORTS, ROOT


SIGNATURE_DIR = REPORTS / "evidence_signature"
MANIFEST_PATH = SIGNATURE_DIR / "manifest.json"
SIGNATURE_PATH = SIGNATURE_DIR / "manifest.sig"
PUBLIC_KEY_PATH = SIGNATURE_DIR / "public_key.pem"


def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def default_evidence_files() -> list[Path]:
    paths = [
        ROOT / "configs" / "evaluation_protocol.v1.json",
        REPORTS / "protocol_audit" / "audit.json",
        REPORTS / "diagnostics" / "hidden" / "diagnostic.json",
        REPORTS / "diagnostics" / "waveguard" / "diagnostic.json",
        REPORTS / "statistical_analysis" / "analysis.json",
        REPORTS / "lidmark_training" / "readiness.json",
        REPORTS / "kadnet_integration" / "audit.json",
        REPORTS / "multi_embedding_matrix" / "plan.json",
        REPORTS / "attack_library_smoke" / "report.json",
        REPORTS / "hidden_lfw_full_benchmark" / "summary.json",
        REPORTS / "sepmark_lfw_benchmark" / "summary.json",
        REPORTS / "waveguard_lfw_full_benchmark" / "summary.json",
        ROOT / "runs" / "lidmark_lfw_eval_full" / "summary.json",
        REPORTS / "aggregate_real_benchmarks" / "summary.json",
        REPORTS / "jianyuanshield_competition_report" / "report.json",
        REPORTS / "jianyuanshield_competition_report" / "report.csv",
        REPORTS / "jianyuanshield_competition_report" / "report.md",
    ]
    return [path for path in paths if path.is_file()]


def _checkpoint_paths(summary_paths: Iterable[Path]) -> list[Path]:
    checkpoints: list[Path] = []
    for path in summary_paths:
        if not path.is_file() or path.suffix != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidates = [
            payload.get("checkpoint"),
            payload.get("run_metadata", {}).get("checkpoint"),
        ]
        for candidate in candidates:
            if candidate:
                checkpoint = Path(candidate)
                if checkpoint.is_file() and checkpoint not in checkpoints:
                    checkpoints.append(checkpoint)
    return checkpoints


def build_evidence_manifest(files: Iterable[Path] | None = None) -> dict[str, Any]:
    evidence_files = list(files or default_evidence_files())
    checkpoint_files = _checkpoint_paths(evidence_files)
    return {
        "schema_version": "evidence-manifest.v1",
        "generated_at": int(time.time()),
        "hash_algorithm": "sha256",
        "signature_algorithm": "ed25519",
        "project_root": str(ROOT),
        "files": [
            {
                "path": _relative(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "role": "checkpoint" if path in checkpoint_files else "evidence",
            }
            for path in [*evidence_files, *checkpoint_files]
        ],
    }


def generate_private_key(path: Path) -> Path:
    path = path.expanduser()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing private key: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return path


def sign_evidence(private_key_path: Path, files: Iterable[Path] | None = None) -> dict[str, Any]:
    private_key = serialization.load_pem_private_key(private_key_path.expanduser().read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError("private key is not Ed25519")
    manifest = build_evidence_manifest(files)
    signature = private_key.sign(canonical_json(manifest))
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    SIGNATURE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    SIGNATURE_PATH.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="ascii")
    PUBLIC_KEY_PATH.write_bytes(public_bytes)
    return verify_evidence_bundle()


def verify_evidence_bundle(
    *,
    manifest_path: Path = MANIFEST_PATH,
    signature_path: Path = SIGNATURE_PATH,
    public_key_path: Path = PUBLIC_KEY_PATH,
) -> dict[str, Any]:
    required = [manifest_path, signature_path, public_key_path]
    if not all(path.is_file() for path in required):
        return {
            "schema_version": "evidence-signature-status.v1",
            "status": "not_generated",
            "verified": False,
            "missing": [str(path) for path in required if not path.is_file()],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        signature = base64.b64decode(signature_path.read_text(encoding="ascii").strip(), validate=True)
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("public key is not Ed25519")
        public_key.verify(signature, canonical_json(manifest))
        mismatches = []
        for item in manifest.get("files", []):
            path = Path(item["path"])
            if not path.is_absolute():
                path = ROOT / path
            actual = sha256_file(path) if path.is_file() else None
            if actual != item.get("sha256"):
                mismatches.append({
                    "path": item["path"],
                    "expected": item.get("sha256"),
                    "actual": actual,
                })
        public_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return {
            "schema_version": "evidence-signature-status.v1",
            "status": "verified" if not mismatches else "content_mismatch",
            "verified": not mismatches,
            "signature_valid": True,
            "file_count": len(manifest.get("files", [])),
            "mismatches": mismatches,
            "public_key_fingerprint_sha256": hashlib.sha256(public_der).hexdigest(),
            "manifest_path": str(manifest_path),
            "signature_path": str(signature_path),
            "public_key_path": str(public_key_path),
        }
    except (InvalidSignature, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "evidence-signature-status.v1",
            "status": "invalid_signature",
            "verified": False,
            "signature_valid": False,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
