"""证据完整性自校验 + 来源数字签名（演示级）。

诚实定位（请勿对外夸大为"司法级防篡改证据链"）：
  - 完整性：对一份 canonical evidence manifest（覆盖协议/诊断/统计/报告/checkpoint
    等文件的 SHA-256）做一次 Ed25519 签名，任意被覆盖文件改动都会触发
    ``content_mismatch``，实现"是否被篡改"的自校验。
  - 来源签名：Ed25519 私钥由运行方现场生成（``generate_private_key``，``chmod 600``）、
    绝不入库，对外只导出公钥，用于核验 manifest 出自持私钥的一方。
  - 追加式弱链：``build_evidence_manifest`` 写入 ``prev_hash`` / ``record_seq``，
    新 manifest 携带上一份 manifest 的哈希，构成轻量 append-only 链，便于检测
    历史 manifest 是否被整体替换；但这**不是** Merkle 树，也无外部锚定。

明确的非目标（演示级局限，须在答辩中诚实说明）：
  - 时间戳取本机 ``time.time()``（``time_source='local_clock'``），**非 RFC3161
    可信时间戳机构（TSA）背书**，可被持机者伪造，不具备法庭证明力。
  - 私钥与验签器同机生成、无 HSM/密钥托管，仅作演示。
  - prev_hash 链只防"局部篡改/历史替换"的弱场景，无分布式见证、无可信锚点。
"""

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


def _previous_manifest_chain() -> tuple[str | None, int]:
    """读取上一份 manifest，派生 prev_hash 与下一条 record_seq。

    构成轻量 append-only 链：新 manifest 携带上一份 manifest 文件内容的
    SHA-256（prev_hash），便于检测历史 manifest 是否被整体替换。
    首条 manifest 的 prev_hash 为 None（genesis），record_seq 从 0 起。
    注意：这不是 Merkle 树，也无外部可信锚定，仅为演示级弱链。
    """
    if not MANIFEST_PATH.is_file():
        return None, 0
    prev_hash = sha256_file(MANIFEST_PATH)
    try:
        prev = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        prev_seq = int(prev.get("record_seq", 0))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        prev_seq = 0
    return prev_hash, prev_seq + 1


def build_evidence_manifest(files: Iterable[Path] | None = None) -> dict[str, Any]:
    evidence_files = list(files or default_evidence_files())
    checkpoint_files = _checkpoint_paths(evidence_files)
    prev_hash, record_seq = _previous_manifest_chain()
    return {
        "schema_version": "evidence-manifest.v2",
        "generated_at": int(time.time()),
        # 诚实标注：时间戳取本机时钟，非 RFC3161 可信时间戳机构（TSA）背书，可被伪造。
        "time_source": "local_clock",
        "hash_algorithm": "sha256",
        "signature_algorithm": "ed25519",
        # 追加式弱链：prev_hash 指向上一份 manifest 的 SHA-256，record_seq 单调递增。
        "prev_hash": prev_hash,
        "record_seq": record_seq,
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
            # 追加式弱链字段（演示级，非 Merkle/无外部锚定）。
            "record_seq": manifest.get("record_seq"),
            "prev_hash": manifest.get("prev_hash"),
            # 诚实标注：本机时钟时间戳，非可信 TSA。
            "time_source": manifest.get("time_source", "local_clock"),
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
