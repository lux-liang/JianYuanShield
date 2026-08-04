#!/usr/bin/env python3
"""Create, verify and restore a signed JianYuanShield competition bundle."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable
import uuid


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCHEMA = "jianyuanshield-competition-bundle.v1"
RELEASE_SCHEMA = "jianyuanshield-release-image.v1"
EVIDENCE_SCHEMA = "evidence-manifest.v1"
CONTROL_FILES = frozenset(
    {
        "SHA256SUMS",
        "bundle-manifest.json",
        "bundle-manifest.sig",
        "bundle-public-key.pem",
    }
)
LOGICAL_ROOTS = frozenset({"assets", "data", "model-sources", "reports", "weights"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMMUTABLE_IMAGE_RE = re.compile(r"^[^\s:@]+(?:/[^\s:@]+)+@sha256:[0-9a-f]{64}$")
LOCAL_IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
PRIVATE_KEY_MARKER = b"-----BEGIN PRIVATE KEY-----"


class BundleError(RuntimeError):
    """Raised when an offline release fails a security or integrity gate."""


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value: {value}")
            ),
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise BundleError(f"{label} is missing or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise BundleError(f"{label} must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BundleError(f"unable to hash {path}") from exc
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BundleError("bundle contains an invalid relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise BundleError(f"unsafe bundle path: {value!r}")
    normalized = pure.as_posix()
    if normalized != value:
        raise BundleError(f"non-canonical bundle path: {value!r}")
    return Path(*pure.parts)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _copy_entry(
    source: Path,
    destination: Path,
    *,
    allowed_root: Path,
    active_directories: frozenset[Path] = frozenset(),
) -> None:
    """Copy one entry while dereferencing only contained, acyclic symlinks."""

    try:
        metadata = source.lstat()
    except OSError as exc:
        raise BundleError(f"bundle source is unreadable: {source}") from exc
    actual = source
    if stat.S_ISLNK(metadata.st_mode):
        try:
            actual = source.resolve(strict=True)
        except OSError as exc:
            raise BundleError(f"bundle source contains a broken symlink: {source}") from exc
        if not _within(actual, allowed_root):
            raise BundleError(f"bundle source symlink escapes its root: {source}")
        metadata = actual.stat()

    if stat.S_ISDIR(metadata.st_mode):
        resolved = actual.resolve()
        if resolved in active_directories:
            raise BundleError(f"bundle source contains a directory symlink cycle: {source}")
        destination.mkdir(parents=True, exist_ok=True)
        next_active = active_directories | {resolved}
        try:
            children = sorted(actual.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise BundleError(f"bundle source directory is unreadable: {source}") from exc
        for child in children:
            _copy_entry(
                child,
                destination / child.name,
                allowed_root=allowed_root,
                active_directories=next_active,
            )
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise BundleError(f"bundle source contains a special file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(actual, destination)
        os.chmod(destination, stat.S_IMODE(metadata.st_mode) & 0o755 or 0o644)
    except OSError as exc:
        raise BundleError(f"unable to copy bundle source: {source}") from exc


def _copy_tree(source: Path, destination: Path) -> None:
    try:
        allowed_root = source.expanduser().resolve(strict=True)
    except OSError as exc:
        raise BundleError(f"required bundle source is missing: {source}") from exc
    if not allowed_root.is_dir():
        raise BundleError(f"required bundle source is not a directory: {source}")
    _copy_entry(source, destination, allowed_root=allowed_root)


def _entry_size(
    source: Path,
    *,
    allowed_root: Path,
    active_directories: frozenset[Path] = frozenset(),
) -> int:
    """Estimate the exact dereferenced bytes that ``_copy_entry`` will write."""

    metadata = source.lstat()
    actual = source
    if stat.S_ISLNK(metadata.st_mode):
        actual = source.resolve(strict=True)
        if not _within(actual, allowed_root):
            raise BundleError(f"bundle source symlink escapes its root: {source}")
        metadata = actual.stat()
    if stat.S_ISREG(metadata.st_mode):
        return metadata.st_size
    if not stat.S_ISDIR(metadata.st_mode):
        raise BundleError(f"bundle source contains a special file: {source}")
    resolved = actual.resolve()
    if resolved in active_directories:
        raise BundleError(f"bundle source contains a directory symlink cycle: {source}")
    next_active = active_directories | {resolved}
    return sum(
        _entry_size(child, allowed_root=allowed_root, active_directories=next_active)
        for child in actual.iterdir()
    )


def _copy_file(source: Path, destination: Path, *, allowed_root: Path) -> None:
    root = allowed_root.expanduser().resolve(strict=True)
    _copy_entry(source, destination, allowed_root=root)
    if not destination.is_file():
        raise BundleError(f"expected a regular file while copying {source}")


def _iter_bundle_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for name in sorted(names):
            path = directory_path / name
            if path.is_symlink():
                raise BundleError(f"offline bundle must not contain symlinks: {path}")
            if not path.is_dir():
                raise BundleError(f"offline bundle contains a special entry: {path}")
        for name in sorted(filenames):
            path = directory_path / name
            if path.is_symlink() or not path.is_file():
                raise BundleError(f"offline bundle contains a non-regular file: {path}")
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _file_records(root: Path, files: Iterable[Path]) -> list[dict[str, Any]]:
    records = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        _safe_relative(relative)
        records.append(
            {
                "path": relative,
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def _load_private_key(path: Path):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (ImportError, OSError, TypeError, ValueError) as exc:
        raise BundleError("bundle signing key is not a readable Ed25519 private key") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise BundleError("bundle signing key is not Ed25519")
    return private_key


def _public_key_der(public_key) -> bytes:
    try:
        from cryptography.hazmat.primitives import serialization

        return public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (ImportError, TypeError, ValueError) as exc:
        raise BundleError("unable to serialize Ed25519 public key") from exc


def _public_key_pem(public_key) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _fingerprint_public_pem(path: Path) -> str:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_key = serialization.load_pem_public_key(path.read_bytes())
    except (ImportError, OSError, TypeError, ValueError) as exc:
        raise BundleError("bundle public key is not a readable Ed25519 key") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise BundleError("bundle public key is not Ed25519")
    return hashlib.sha256(_public_key_der(public_key)).hexdigest()


def _verify_signature(manifest: dict[str, Any], signature_path: Path, public_path: Path) -> str:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        signature = base64.b64decode(
            signature_path.read_text(encoding="ascii").strip(),
            validate=True,
        )
        public_key = serialization.load_pem_public_key(public_path.read_bytes())
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("not Ed25519")
        public_key.verify(signature, _canonical_json(manifest))
        return hashlib.sha256(_public_key_der(public_key)).hexdigest()
    except ImportError:
        return _verify_signature_with_openssl(manifest, signature_path, public_path)
    except (InvalidSignature, OSError, UnicodeError, TypeError, ValueError) as exc:
        raise BundleError("Ed25519 manifest signature is invalid") from exc


def _verify_signature_with_openssl(
    manifest: dict[str, Any],
    signature_path: Path,
    public_path: Path,
) -> str:
    try:
        signature = base64.b64decode(
            signature_path.read_text(encoding="ascii").strip(),
            validate=True,
        )
        with tempfile.TemporaryDirectory(prefix="jys-signature-") as directory:
            temporary = Path(directory)
            content_path = temporary / "manifest.canonical.json"
            signature_raw_path = temporary / "manifest.sig.raw"
            der_path = temporary / "public.der"
            content_path.write_bytes(_canonical_json(manifest))
            signature_raw_path.write_bytes(signature)
            subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(public_path),
                    "-sigfile",
                    str(signature_raw_path),
                    "-rawin",
                    "-in",
                    str(content_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            der = subprocess.run(
                [
                    "openssl",
                    "pkey",
                    "-pubin",
                    "-in",
                    str(public_path),
                    "-outform",
                    "DER",
                    "-out",
                    str(der_path),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            del der
            return hashlib.sha256(der_path.read_bytes()).hexdigest()
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        raise BundleError("Ed25519 verification requires cryptography or OpenSSL 3") from exc


def _require_fingerprint(value: str) -> str:
    normalized = value.strip().lower()
    if SHA256_RE.fullmatch(normalized) is None:
        raise BundleError("signer fingerprint must contain exactly 64 lowercase hex characters")
    return normalized


def _release_record(path: Path, *, oci_archive: Path | None = None) -> dict[str, Any]:
    record = _load_json(path, "release-image record")
    if record.get("schema_version") != RELEASE_SCHEMA:
        raise BundleError("release-image record schema is unsupported")
    source = record.get("source")
    image = record.get("image")
    build = record.get("build")
    if (
        not isinstance(source, dict)
        or COMMIT_RE.fullmatch(str(source.get("git_commit") or "")) is None
        or COMMIT_RE.fullmatch(str(source.get("git_tree") or "")) is None
        or not isinstance(image, dict)
        or IMMUTABLE_IMAGE_RE.fullmatch(str(image.get("deployment_reference") or "")) is None
        or LOCAL_IMAGE_RE.fullmatch(str(image.get("digest") or "")) is None
        or not isinstance(image.get("tagged_reference"), str)
        or not image["tagged_reference"]
        or not isinstance(build, dict)
        or build.get("output_type") != "offline-dual-archive"
        or not isinstance(build.get("oci_archive"), dict)
        or not isinstance(build.get("load_archive"), dict)
        or LOCAL_IMAGE_RE.fullmatch(str(image.get("offline_runtime_reference") or "")) is None
        or image.get("config_digest") != image.get("offline_runtime_reference")
    ):
        raise BundleError("release-image record is not an immutable OCI release")
    archive_record = build["oci_archive"]
    load_record = build["load_archive"]
    for label, item in (("OCI", archive_record), ("Docker-loadable", load_record)):
        if (
            not isinstance(item.get("path"), str)
            or not item["path"]
            or SHA256_RE.fullmatch(str(item.get("sha256") or "")) is None
            or not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item["size_bytes"] <= 0
        ):
            raise BundleError(f"release-image record has an invalid {label} archive")
    if load_record.get("format") != "docker-image-layout-with-oci-media-types":
        raise BundleError("release-image load archive format is unsupported")
    if oci_archive is not None:
        if (
            not oci_archive.is_file()
            or oci_archive.is_symlink()
            or archive_record.get("sha256") != _sha256_file(oci_archive)
            or archive_record.get("size_bytes") != oci_archive.stat().st_size
        ):
            raise BundleError("OCI archive does not match the signed release record")
    return record


def _release_artifact_path(root: Path, reference: Any, *, label: str) -> Path:
    if not isinstance(reference, str):
        raise BundleError(f"release record {label} path is invalid")
    relative = _safe_relative(reference)
    raw = root / relative
    if raw.is_symlink():
        raise BundleError(f"release record {label} path must not be a symlink")
    candidate = raw.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if not _within(candidate, resolved_root) or not candidate.is_file():
        raise BundleError(f"release record {label} path is unsafe")
    return candidate


def verify_release_metadata(record: dict[str, Any], root: Path) -> None:
    """Verify BuildKit metadata, generated SBOM and supply-chain manifest bindings."""

    bindings = (
        (record.get("build"), "metadata_path", "metadata_sha256", "BuildKit metadata"),
        (
            record.get("supply_chain_manifest"),
            "path",
            "sha256",
            "supply-chain manifest",
        ),
        (
            record.get("python_dependency_sbom"),
            "path",
            "sha256",
            "Python dependency SBOM",
        ),
    )
    for container, path_field, digest_field, label in bindings:
        if not isinstance(container, dict):
            raise BundleError(f"release record {label} binding is missing")
        expected = str(container.get(digest_field) or "")
        if SHA256_RE.fullmatch(expected) is None:
            raise BundleError(f"release record {label} digest is invalid")
        path = _release_artifact_path(root, container.get(path_field), label=label)
        if _sha256_file(path) != expected:
            raise BundleError(f"release record {label} hash mismatch")


def _tar_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for item in archive.getmembers():
        name = item.name.rstrip("/")
        if not name:
            continue
        _safe_relative(name)
        if item.issym() or item.islnk() or not (item.isfile() or item.isdir()):
            raise BundleError("container archive contains a link or special entry")
        if name in members:
            raise BundleError("container archive contains duplicate members")
        members[name] = item
    return members


def _tar_json(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    name: str,
    *,
    label: str,
) -> Any:
    member = members.get(name)
    if member is None or not member.isfile() or member.size > 32 * 1024 * 1024:
        raise BundleError(f"container archive {label} is missing or oversized")
    handle = archive.extractfile(member)
    if handle is None:
        raise BundleError(f"container archive {label} is unreadable")
    try:
        return json.loads(handle.read().decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise BundleError(f"container archive {label} is invalid JSON") from exc


def inspect_oci_archive(
    path: Path,
    *,
    expected_manifest_digest: str,
    expected_config_digest: str,
) -> dict[str, Any]:
    """Validate the OCI layout and require both provenance and SBOM attestations."""

    try:
        archive = tarfile.open(path, mode="r:*")
    except (OSError, tarfile.TarError) as exc:
        raise BundleError("OCI archive is unreadable") from exc
    with archive:
        members = _tar_members(archive)
        layout = _tar_json(archive, members, "oci-layout", label="layout marker")
        index = _tar_json(archive, members, "index.json", label="index")
        if not isinstance(layout, dict) or layout.get("imageLayoutVersion") != "1.0.0":
            raise BundleError("OCI archive layout version is unsupported")
        descriptors = index.get("manifests") if isinstance(index, dict) else None
        if (
            not isinstance(index, dict)
            or index.get("schemaVersion") != 2
            or not isinstance(descriptors, list)
        ):
            raise BundleError("OCI archive index is invalid")

        seen_descriptors: set[str] = set()
        config_found = False
        predicates: set[str] = set()
        pending = list(descriptors)
        while pending:
            descriptor = pending.pop()
            if not isinstance(descriptor, dict):
                raise BundleError("OCI archive contains an invalid descriptor")
            digest = str(descriptor.get("digest") or "")
            if not digest.startswith("sha256:") or SHA256_RE.fullmatch(digest[7:]) is None:
                raise BundleError("OCI archive descriptor digest is invalid")
            if digest in seen_descriptors:
                continue
            seen_descriptors.add(digest)
            blob_name = f"blobs/sha256/{digest[7:]}"
            manifest = _tar_json(archive, members, blob_name, label="manifest blob")
            if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 2:
                raise BundleError("OCI archive manifest blob is invalid")
            nested = manifest.get("manifests")
            if isinstance(nested, list):
                pending.extend(nested)
                continue
            config = manifest.get("config")
            layers = manifest.get("layers")
            if not isinstance(config, dict) or not isinstance(layers, list):
                raise BundleError("OCI archive image manifest is incomplete")
            config_digest = str(config.get("digest") or "")
            if config_digest == expected_config_digest:
                config_found = True
            if config_digest.startswith("sha256:"):
                config_blob = f"blobs/sha256/{config_digest[7:]}"
                if config_blob not in members:
                    raise BundleError("OCI archive config blob is missing")
            for layer in layers:
                if not isinstance(layer, dict):
                    raise BundleError("OCI archive layer descriptor is invalid")
                layer_digest = str(layer.get("digest") or "")
                if not layer_digest.startswith("sha256:"):
                    raise BundleError("OCI archive layer digest is invalid")
                layer_blob = f"blobs/sha256/{layer_digest[7:]}"
                if layer_blob not in members:
                    raise BundleError("OCI archive layer blob is missing")
                media_type = str(layer.get("mediaType") or "")
                if media_type.startswith("application/vnd.in-toto"):
                    statement = _tar_json(
                        archive,
                        members,
                        layer_blob,
                        label="attestation statement",
                    )
                    if isinstance(statement, dict) and isinstance(
                        statement.get("predicateType"), str
                    ):
                        predicates.add(statement["predicateType"])

        if expected_manifest_digest not in seen_descriptors:
            raise BundleError("OCI archive does not contain the recorded image manifest")
        if not config_found:
            raise BundleError("OCI archive does not contain the recorded image config")
        if not any(value.startswith("https://slsa.dev/provenance/") for value in predicates):
            raise BundleError("OCI archive is missing SLSA provenance attestation")
        if "https://spdx.dev/Document" not in predicates:
            raise BundleError("OCI archive is missing SPDX SBOM attestation")
        return {
            "manifest_digest": expected_manifest_digest,
            "config_digest": expected_config_digest,
            "predicate_types": sorted(predicates),
        }


def inspect_docker_archive(
    path: Path,
    *,
    expected_config_digest: str,
    expected_tag: str,
) -> dict[str, Any]:
    """Validate the Docker-loadable companion and its immutable image ID."""

    try:
        archive = tarfile.open(path, mode="r:*")
    except (OSError, tarfile.TarError) as exc:
        raise BundleError("Docker-loadable archive is unreadable") from exc
    with archive:
        members = _tar_members(archive)
        manifest = _tar_json(archive, members, "manifest.json", label="load manifest")
        if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
            raise BundleError("Docker-loadable archive must contain exactly one image")
        item = manifest[0]
        tags = item.get("RepoTags")
        config_name = item.get("Config")
        layers = item.get("Layers")
        if (
            not isinstance(tags, list)
            or expected_tag not in tags
            or not isinstance(config_name, str)
            or not isinstance(layers, list)
        ):
            raise BundleError("Docker-loadable archive tag/config contract is invalid")
        config_member = members.get(config_name)
        if config_member is None or not config_member.isfile():
            raise BundleError("Docker-loadable archive config is missing")
        config_handle = archive.extractfile(config_member)
        if config_handle is None:
            raise BundleError("Docker-loadable archive config is unreadable")
        config_digest = "sha256:" + hashlib.sha256(config_handle.read()).hexdigest()
        if config_digest != expected_config_digest:
            raise BundleError("Docker-loadable archive image ID does not match release metadata")
        for layer in layers:
            if not isinstance(layer, str) or layer not in members or not members[layer].isfile():
                raise BundleError("Docker-loadable archive layer is missing")
        return {
            "config_digest": config_digest,
            "tag": expected_tag,
            "layer_count": len(layers),
        }


def _resolve_evidence_reference(
    reference: str,
    *,
    project_root: Path,
    runtime_root: Path,
) -> Path:
    relative = _safe_relative(reference)
    parts = relative.parts
    if parts[0] in LOGICAL_ROOTS:
        candidate_root = runtime_root / parts[0]
        candidate = candidate_root.joinpath(*parts[1:])
    else:
        candidate_root = project_root
        candidate = candidate_root / relative
    resolved_root = candidate_root.resolve(strict=True)
    resolved = candidate.resolve(strict=True)
    if not _within(resolved, resolved_root) or not resolved.is_file():
        raise BundleError(f"release-core member escapes its approved root: {reference}")
    return resolved


def verify_release_core(
    *,
    manifest_path: Path,
    signature_path: Path,
    public_key_path: Path,
    project_root: Path,
    runtime_root: Path,
    expected_fingerprint: str,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path, "release-core manifest")
    if (
        manifest.get("schema_version") != EVIDENCE_SCHEMA
        or manifest.get("profile") != "release-core"
        or manifest.get("hash_algorithm") != "sha256"
        or manifest.get("signature_algorithm") != "ed25519"
        or not isinstance(manifest.get("files"), list)
        or not manifest["files"]
    ):
        raise BundleError("release-core manifest is not a complete release-core profile")
    fingerprint = _verify_signature(manifest, signature_path, public_key_path)
    if fingerprint != _require_fingerprint(expected_fingerprint):
        raise BundleError("release-core signer does not match the externally pinned fingerprint")
    seen: set[str] = set()
    for item in manifest["files"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or SHA256_RE.fullmatch(str(item.get("sha256") or "")) is None
            or not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item["size_bytes"] < 0
        ):
            raise BundleError("release-core manifest contains an invalid member")
        reference = item["path"]
        if reference in seen:
            raise BundleError("release-core manifest contains duplicate members")
        seen.add(reference)
        path = _resolve_evidence_reference(
            reference,
            project_root=project_root,
            runtime_root=runtime_root,
        )
        if path.stat().st_size != item["size_bytes"] or _sha256_file(path) != item["sha256"]:
            raise BundleError(f"release-core member hash mismatch: {reference}")
    return {
        "file_count": len(seen),
        "fingerprint": fingerprint,
        "manifest_sha256": _sha256_file(manifest_path),
        "manifest": manifest,
    }


def _git_release_state(source_root: Path, release_record: dict[str, Any]) -> None:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip().lower()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=source_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip().lower()
        status_output = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=source_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BundleError("unable to verify the release Git state") from exc
    if status_output:
        raise BundleError("competition bundle creation requires a clean Git worktree")
    source = release_record["source"]
    if commit != source.get("git_commit") or tree != source.get("git_tree"):
        raise BundleError("release image does not match the checked-out Git commit and tree")


def _copy_project_members(
    manifest: dict[str, Any],
    *,
    source_root: Path,
    runtime_root: Path,
    project_destination: Path,
) -> None:
    source_root_resolved = source_root.resolve(strict=True)
    for item in manifest["files"]:
        reference = item["path"]
        relative = _safe_relative(reference)
        if relative.parts[0] in LOGICAL_ROOTS:
            continue
        source = _resolve_evidence_reference(
            reference,
            project_root=source_root,
            runtime_root=runtime_root,
        )
        _copy_file(
            source,
            project_destination / relative,
            allowed_root=source_root_resolved,
        )


def _reject_private_keys(root: Path) -> None:
    for path in _iter_bundle_files(root):
        try:
            with path.open("rb") as handle:
                prefix = handle.read(4096)
        except OSError as exc:
            raise BundleError(f"unable to inspect bundled file: {path}") from exc
        if PRIVATE_KEY_MARKER in prefix:
            raise BundleError(f"refusing to package a private key: {path.relative_to(root)}")


def _sign_bundle_manifest(
    manifest: dict[str, Any],
    *,
    signing_key_path: Path,
    destination: Path,
    expected_fingerprint: str,
) -> None:
    private_key = _load_private_key(signing_key_path)
    public_key = private_key.public_key()
    fingerprint = hashlib.sha256(_public_key_der(public_key)).hexdigest()
    if fingerprint != _require_fingerprint(expected_fingerprint):
        raise BundleError("bundle signing key does not match the externally pinned fingerprint")
    signature = private_key.sign(_canonical_json(manifest))
    _atomic_write(destination / "bundle-manifest.json", _json_bytes(manifest))
    _atomic_write(
        destination / "bundle-manifest.sig",
        base64.b64encode(signature) + b"\n",
    )
    _atomic_write(destination / "bundle-public-key.pem", _public_key_pem(public_key))


def _write_sha256sums(
    root: Path,
    *,
    known_records: Iterable[dict[str, Any]] | None = None,
) -> None:
    known = {
        str(record["path"]): str(record["sha256"])
        for record in (known_records or [])
    }
    records = []
    for path in _iter_bundle_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == "SHA256SUMS":
            continue
        records.append(
            {
                "path": relative,
                "sha256": known.get(relative) or _sha256_file(path),
            }
        )
    lines = [f"{record['sha256']}  {record['path']}" for record in records]
    _atomic_write(root / "SHA256SUMS", ("\n".join(lines) + "\n").encode("utf-8"))


def create_bundle(
    *,
    output: Path,
    source_root: Path,
    runtime_root: Path,
    release_dir: Path,
    oci_archive: Path | None,
    load_archive: Path | None,
    signing_key: Path,
    signer_fingerprint: str,
) -> dict[str, Any]:
    """Create one atomically published, fully signed competition directory."""

    fingerprint = _require_fingerprint(signer_fingerprint)
    source_root = source_root.expanduser().resolve(strict=True)
    runtime_root = runtime_root.expanduser().resolve(strict=True)
    release_dir = release_dir.expanduser().resolve(strict=True)
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise BundleError("refusing to overwrite an existing bundle path")
    if _within(output, source_root) or _within(output, runtime_root):
        raise BundleError("bundle output must be outside source and runtime roots")

    release_path = release_dir / "release-image.json"
    provisional = _release_record(release_path)
    archive_record = provisional["build"]["oci_archive"]
    archive = (
        oci_archive.expanduser().resolve(strict=True)
        if oci_archive is not None
        else _release_artifact_path(
            release_dir,
            archive_record.get("path"),
            label="OCI archive",
        )
    )
    load_archive_record = provisional["build"]["load_archive"]
    load_archive_path = (
        load_archive.expanduser().resolve(strict=True)
        if load_archive is not None
        else _release_artifact_path(
            release_dir,
            load_archive_record.get("path"),
            label="Docker-loadable archive",
        )
    )
    release = _release_record(release_path, oci_archive=archive)
    verify_release_metadata(release, release_dir)
    if (
        not load_archive_path.is_file()
        or load_archive_path.is_symlink()
        or load_archive_record.get("sha256") != _sha256_file(load_archive_path)
        or load_archive_record.get("size_bytes") != load_archive_path.stat().st_size
    ):
        raise BundleError("Docker-loadable archive does not match the release record")
    inspect_oci_archive(
        archive,
        expected_manifest_digest=release["image"]["digest"],
        expected_config_digest=release["image"]["config_digest"],
    )
    inspect_docker_archive(
        load_archive_path,
        expected_config_digest=release["image"]["config_digest"],
        expected_tag=release["image"]["tagged_reference"],
    )
    _git_release_state(source_root, release)

    core_dir = runtime_root / "reports" / "evidence_signature" / "release-core"
    core = verify_release_core(
        manifest_path=core_dir / "manifest.json",
        signature_path=core_dir / "manifest.sig",
        public_key_path=core_dir / "public_key.pem",
        project_root=source_root,
        runtime_root=runtime_root,
        expected_fingerprint=fingerprint,
    )

    estimated_bytes = archive.stat().st_size + load_archive_path.stat().st_size
    for name in ("assets", "data", "model-sources", "reports", "weights"):
        source = runtime_root / name
        allowed = source.resolve(strict=True)
        estimated_bytes += _entry_size(source, allowed_root=allowed)
    reserve = max(1024 * 1024 * 1024, estimated_bytes // 20)
    free_bytes = shutil.disk_usage(output.parent).free
    if free_bytes < estimated_bytes + reserve:
        raise BundleError(
            "insufficient free disk for competition bundle "
            f"required={estimated_bytes + reserve} available={free_bytes}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o755)
    try:
        deployment = staging / "deployment"
        deployment.mkdir()
        for source, name in (
            (source_root / "docker-compose.competition.yml", "docker-compose.competition.yml"),
            (source_root / "offline_deploy.sh", "offline_deploy.sh"),
            (source_root / "scripts" / "offline_bundle.py", "offline_bundle.py"),
        ):
            _copy_file(source, deployment / name, allowed_root=source_root)

        image_dir = staging / "image"
        image_dir.mkdir()
        _copy_file(archive, image_dir / "release-image.oci.tar", allowed_root=archive.parent)
        _copy_file(
            load_archive_path,
            image_dir / "release-image.docker.tar",
            allowed_root=load_archive_path.parent,
        )
        for name in (
            "release-image.json",
            "buildkit-metadata.json",
            "build-manifest.json",
            "python-dependencies.cdx.json",
        ):
            _copy_file(release_dir / name, image_dir / name, allowed_root=release_dir)

        payload = staging / "payload"
        for name in ("assets", "data", "model-sources", "reports", "weights"):
            _copy_tree(runtime_root / name, payload / name)
        _copy_project_members(
            core["manifest"],
            source_root=source_root,
            runtime_root=runtime_root,
            project_destination=payload / "project",
        )
        notices = source_root / "THIRD_PARTY_NOTICES.md"
        if not notices.is_file():
            raise BundleError("THIRD_PARTY_NOTICES.md is required for the competition bundle")
        _copy_file(
            notices,
            payload / "licenses" / "THIRD_PARTY_NOTICES.md",
            allowed_root=source_root,
        )

        _reject_private_keys(staging)
        signed_files = _iter_bundle_files(staging)
        records = _file_records(staging, signed_files)
        total_bytes = sum(record["size_bytes"] for record in records)
        manifest = {
            "schema_version": BUNDLE_SCHEMA,
            "bundle_id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "files": records,
            "inventory": {
                "file_count": len(records),
                "size_bytes": total_bytes,
            },
            "release_core": {
                "file_count": core["file_count"],
                "manifest_path": "payload/reports/evidence_signature/release-core/manifest.json",
                "manifest_sha256": core["manifest_sha256"],
                "public_key_fingerprint_sha256": fingerprint,
                "signature_path": "payload/reports/evidence_signature/release-core/manifest.sig",
            },
            "release_image": {
                "deployment_reference": release["image"]["deployment_reference"],
                "git_commit": release["source"]["git_commit"],
                "git_tree": release["source"]["git_tree"],
                "oci_archive_path": "image/release-image.oci.tar",
                "oci_archive_sha256": archive_record["sha256"],
                "load_archive_path": "image/release-image.docker.tar",
                "load_archive_sha256": load_archive_record["sha256"],
                "offline_runtime_reference": release["image"]["offline_runtime_reference"],
                "release_record_path": "image/release-image.json",
            },
            "runtime": {
                "demo_enabled": False,
                "mode": "production",
                "network_dependency": "none",
                "secrets_packaged": False,
            },
        }
        _sign_bundle_manifest(
            manifest,
            signing_key_path=signing_key,
            destination=staging,
            expected_fingerprint=fingerprint,
        )
        _write_sha256sums(staging, known_records=records)
        verified = preflight_bundle(staging, expected_fingerprint=fingerprint)
        os.replace(staging, output)
        return {**verified, "bundle": str(output)}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _parse_sha256sums(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BundleError("SHA256SUMS is missing or unreadable") from exc
    records: dict[str, str] = {}
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise BundleError("SHA256SUMS has invalid syntax")
        digest, reference = line[:64], line[66:]
        if SHA256_RE.fullmatch(digest) is None:
            raise BundleError("SHA256SUMS contains an invalid digest")
        _safe_relative(reference)
        if reference == "SHA256SUMS" or reference in records:
            raise BundleError("SHA256SUMS contains a duplicate or recursive entry")
        records[reference] = digest
    if not records:
        raise BundleError("SHA256SUMS is empty")
    return records


def preflight_bundle(bundle: Path, *, expected_fingerprint: str) -> dict[str, Any]:
    """Strictly verify signature, exact inventory, evidence and OCI closure."""

    fingerprint = _require_fingerprint(expected_fingerprint)
    bundle = bundle.expanduser().resolve(strict=True)
    if not bundle.is_dir() or bundle.is_symlink():
        raise BundleError("bundle path must be a real directory")
    files = _iter_bundle_files(bundle)
    actual_paths = {path.relative_to(bundle).as_posix(): path for path in files}
    if not CONTROL_FILES.issubset(actual_paths):
        raise BundleError("bundle control files are incomplete")

    manifest = _load_json(actual_paths["bundle-manifest.json"], "bundle manifest")
    if (
        manifest.get("schema_version") != BUNDLE_SCHEMA
        or not isinstance(manifest.get("files"), list)
        or not manifest["files"]
        or not isinstance(manifest.get("inventory"), dict)
        or not isinstance(manifest.get("release_core"), dict)
        or not isinstance(manifest.get("release_image"), dict)
    ):
        raise BundleError("bundle manifest schema is unsupported")
    actual_fingerprint = _verify_signature(
        manifest,
        actual_paths["bundle-manifest.sig"],
        actual_paths["bundle-public-key.pem"],
    )
    if actual_fingerprint != fingerprint:
        raise BundleError("bundle signer does not match the externally pinned fingerprint")

    declared: dict[str, dict[str, Any]] = {}
    for item in manifest["files"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or SHA256_RE.fullmatch(str(item.get("sha256") or "")) is None
            or not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item["size_bytes"] < 0
        ):
            raise BundleError("bundle manifest contains an invalid file record")
        reference = item["path"]
        _safe_relative(reference)
        if reference in CONTROL_FILES or reference in declared:
            raise BundleError("bundle manifest contains a control or duplicate member")
        declared[reference] = item
    expected_paths = set(declared) | CONTROL_FILES
    if set(actual_paths) != expected_paths:
        missing = sorted(expected_paths - set(actual_paths))
        extra = sorted(set(actual_paths) - expected_paths)
        raise BundleError(f"bundle exact membership mismatch missing={missing} extra={extra}")

    total_bytes = 0
    computed_digests: dict[str, str] = {}
    for reference, item in declared.items():
        path = actual_paths[reference]
        total_bytes += path.stat().st_size
        computed = _sha256_file(path)
        computed_digests[reference] = computed
        if path.stat().st_size != item["size_bytes"] or computed != item["sha256"]:
            raise BundleError(f"bundle member hash mismatch: {reference}")
        with path.open("rb") as handle:
            if PRIVATE_KEY_MARKER in handle.read(4096):
                raise BundleError(f"bundle contains a private key: {reference}")
    inventory = manifest["inventory"]
    if inventory.get("file_count") != len(declared) or inventory.get("size_bytes") != total_bytes:
        raise BundleError("bundle inventory totals do not match its file records")

    sums = _parse_sha256sums(actual_paths["SHA256SUMS"])
    expected_sum_paths = set(actual_paths) - {"SHA256SUMS"}
    if set(sums) != expected_sum_paths:
        raise BundleError("SHA256SUMS exact membership does not match the bundle")
    for reference, expected_digest in sums.items():
        computed = computed_digests.get(reference)
        if computed is None:
            computed = _sha256_file(actual_paths[reference])
            computed_digests[reference] = computed
        if computed != expected_digest:
            raise BundleError(f"SHA256SUMS mismatch: {reference}")

    release_image = manifest["release_image"]
    reference = str(release_image.get("deployment_reference") or "")
    if IMMUTABLE_IMAGE_RE.fullmatch(reference) is None:
        raise BundleError("bundle release image reference is mutable")
    runtime_reference = str(release_image.get("offline_runtime_reference") or "")
    if LOCAL_IMAGE_RE.fullmatch(runtime_reference) is None:
        raise BundleError("bundle offline image ID is not immutable")
    archive_reference = str(release_image.get("oci_archive_path") or "")
    archive_path = actual_paths.get(archive_reference)
    if (
        archive_path is None
        or computed_digests.get(archive_reference)
        != release_image.get("oci_archive_sha256")
    ):
        raise BundleError("bundle OCI archive does not match the signed bundle manifest")
    load_reference = str(release_image.get("load_archive_path") or "")
    load_path = actual_paths.get(load_reference)
    if (
        load_path is None
        or computed_digests.get(load_reference)
        != release_image.get("load_archive_sha256")
    ):
        raise BundleError("bundle Docker-loadable archive does not match its manifest")
    record_reference = str(release_image.get("release_record_path") or "")
    record_path = actual_paths.get(record_reference)
    if record_path is None:
        raise BundleError("bundle release-image record is missing")
    release = _release_record(record_path)
    verify_release_metadata(release, record_path.parent)
    archive_record = release["build"]["oci_archive"]
    load_archive_record = release["build"]["load_archive"]
    if (
        release["image"]["deployment_reference"] != reference
        or release["image"]["offline_runtime_reference"] != runtime_reference
        or release["source"]["git_commit"] != release_image.get("git_commit")
        or release["source"]["git_tree"] != release_image.get("git_tree")
        or archive_record.get("sha256") != computed_digests.get(archive_reference)
        or archive_record.get("size_bytes") != archive_path.stat().st_size
        or load_archive_record.get("sha256") != computed_digests.get(load_reference)
        or load_archive_record.get("size_bytes") != load_path.stat().st_size
    ):
        raise BundleError("release-image record disagrees with the signed bundle manifest")
    inspect_oci_archive(
        archive_path,
        expected_manifest_digest=release["image"]["digest"],
        expected_config_digest=release["image"]["config_digest"],
    )
    inspect_docker_archive(
        load_path,
        expected_config_digest=release["image"]["config_digest"],
        expected_tag=release["image"]["tagged_reference"],
    )

    core = manifest["release_core"]
    core_manifest_reference = str(core.get("manifest_path") or "")
    core_manifest_path = actual_paths.get(core_manifest_reference)
    if (
        core_manifest_path is None
        or _sha256_file(core_manifest_path) != core.get("manifest_sha256")
        or core.get("public_key_fingerprint_sha256") != fingerprint
    ):
        raise BundleError("release-core binding in the bundle manifest is invalid")
    verified_core = verify_release_core(
        manifest_path=core_manifest_path,
        signature_path=bundle / "payload/reports/evidence_signature/release-core/manifest.sig",
        public_key_path=bundle / "payload/reports/evidence_signature/release-core/public_key.pem",
        project_root=bundle / "payload/project",
        runtime_root=bundle / "payload",
        expected_fingerprint=fingerprint,
    )
    if verified_core["file_count"] != core.get("file_count"):
        raise BundleError("release-core file count does not match the bundle manifest")

    required_paths = (
        "deployment/docker-compose.competition.yml",
        "deployment/offline_deploy.sh",
        "deployment/offline_bundle.py",
        "image/build-manifest.json",
        "image/python-dependencies.cdx.json",
        "payload/licenses/THIRD_PARTY_NOTICES.md",
    )
    if any(reference not in actual_paths for reference in required_paths):
        raise BundleError("bundle is missing a required deployment, SBOM or license artifact")
    for directory in ("assets", "data", "model-sources", "reports", "weights"):
        path = bundle / "payload" / directory
        if not path.is_dir() or path.is_symlink():
            raise BundleError(f"bundle runtime component is missing: {directory}")
    return {
        "schema_version": "jianyuanshield-competition-preflight.v1",
        "status": "verified",
        "verified": True,
        "bundle_id": manifest.get("bundle_id"),
        "file_count": len(actual_paths),
        "size_bytes": total_bytes,
        "release_image": reference,
        "runtime_image": runtime_reference,
        "release_core_manifest_sha256": verified_core["manifest_sha256"],
        "signer_fingerprint_sha256": fingerprint,
    }


def _secret_files(secret_dir: Path, *, expected_fingerprint: str) -> dict[str, Path]:
    secret_dir = secret_dir.expanduser().resolve(strict=True)
    if not secret_dir.is_dir() or secret_dir.is_symlink():
        raise BundleError("secret directory must be a real directory")
    names = {
        "api_key": secret_dir / "api_key",
        "provenance_secret": secret_dir / "provenance_secret",
        "evidence_private_key": secret_dir / "evidence_ed25519.pem",
    }
    for label, path in names.items():
        if path.is_symlink() or not path.is_file():
            raise BundleError(f"required secret file is missing: {path.name}")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise BundleError(f"secret file permissions must be 0600 or stricter: {path.name}")
        if label != "evidence_private_key":
            try:
                value = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError) as exc:
                raise BundleError(f"secret file is unreadable: {path.name}") from exc
            if len(value) < 32:
                raise BundleError(f"secret must contain at least 32 characters: {path.name}")
    private_key = _load_private_key(names["evidence_private_key"])
    actual = hashlib.sha256(_public_key_der(private_key.public_key())).hexdigest()
    if actual != _require_fingerprint(expected_fingerprint):
        raise BundleError("runtime evidence private key does not match the release signer")
    return names


def _run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise BundleError(f"command failed: {command[0]}: {detail.strip()}") from exc
    return completed.stdout.strip() if capture and completed.stdout else ""


def _safe_env_value(value: str, *, label: str) -> str:
    if not value or any(character.isspace() for character in value) or any(
        character in value for character in "'\"#$=\\"
    ):
        raise BundleError(f"{label} contains characters unsupported by the strict env writer")
    return value


def _write_runtime_environment(
    path: Path,
    *,
    bundle: Path,
    secrets: dict[str, Path],
    preflight: dict[str, Any],
    project_name: str,
    frontend_port: int,
) -> None:
    values = {
        "JYS_COMPOSE_PROJECT_NAME": project_name,
        "JYS_RELEASE_IMAGE": preflight["runtime_image"],
        "JYS_WEIGHT_HOST": str(bundle / "payload/weights"),
        "JYS_MODEL_SOURCE_HOST": str(bundle / "payload/model-sources"),
        "JYS_DATA_HOST": str(bundle / "payload/data"),
        "JYS_REPORT_HOST": str(bundle / "payload/reports"),
        "JYS_API_KEY_SECRET_FILE": str(secrets["api_key"]),
        "JYS_PROVENANCE_SECRET_FILE": str(secrets["provenance_secret"]),
        "JYS_EVIDENCE_PRIVATE_KEY_FILE": str(secrets["evidence_private_key"]),
        "JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT": preflight["signer_fingerprint_sha256"],
        "JYS_CORS_ORIGINS": f"https://127.0.0.1:{frontend_port}",
        "JYS_BIND_ADDRESS": "127.0.0.1",
        "JYS_FRONTEND_PORT": str(frontend_port),
    }
    lines = [
        f"{key}={_safe_env_value(str(value), label=key)}"
        for key, value in sorted(values.items())
    ]
    _atomic_write(path, ("\n".join(lines) + "\n").encode("utf-8"), mode=0o600)


def restore_bundle(
    *,
    bundle: Path,
    expected_fingerprint: str,
    secret_dir: Path,
    state_dir: Path,
    frontend_port: int,
) -> dict[str, Any]:
    """Verify, load, GPU-test and start the production-only offline stack."""

    if not 1024 <= frontend_port <= 65535:
        raise BundleError("frontend port must be between 1024 and 65535")
    bundle = bundle.expanduser().resolve(strict=True)
    preflight = preflight_bundle(bundle, expected_fingerprint=expected_fingerprint)
    secrets = _secret_files(
        secret_dir,
        expected_fingerprint=preflight["signer_fingerprint_sha256"],
    )
    state_dir = state_dir.expanduser().resolve()
    if state_dir.exists() or state_dir.is_symlink():
        raise BundleError("restore state directory must not already exist")
    if _within(state_dir, bundle):
        raise BundleError("restore state directory must be outside the read-only bundle")
    state_dir.mkdir(parents=True, mode=0o700)

    project_name = f"jys-{str(preflight['bundle_id'])[:12]}-{uuid.uuid4().hex[:6]}"
    if SAFE_PROJECT_RE.fullmatch(project_name) is None:
        raise BundleError("generated Compose project name is invalid")
    environment_path = state_dir / "competition.env"
    _write_runtime_environment(
        environment_path,
        bundle=bundle,
        secrets=secrets,
        preflight=preflight,
        project_name=project_name,
        frontend_port=frontend_port,
    )
    compose_path = bundle / "deployment/docker-compose.competition.yml"
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(environment_path),
        "-f",
        str(compose_path),
    ]
    archive = bundle / "image/release-image.docker.tar"
    try:
        _run(["docker", "info"], capture=True)
        _run(["docker", "compose", "version"], capture=True)
        _run(["docker", "load", "--input", str(archive)])
        _run(["docker", "image", "inspect", preflight["runtime_image"]], capture=True)
        _run([*compose, "config", "--quiet"], capture=True)
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--gpus",
                "all",
                "--entrypoint",
                "python",
                preflight["runtime_image"],
                "-c",
                (
                    "import torch; assert torch.cuda.is_available(); "
                    "print(torch.cuda.get_device_name(0))"
                ),
            ]
        )
        _run([*compose, "up", "-d", "--wait", "--wait-timeout", "360"])
    except BundleError:
        metadata = {
            "bundle": str(bundle),
            "compose": str(compose_path),
            "environment": str(environment_path),
            "project_name": project_name,
            "release_image": preflight["release_image"],
            "runtime_image": preflight["runtime_image"],
            "status": "restore_failed",
        }
        _atomic_write(state_dir / "deployment.json", _json_bytes(metadata), mode=0o600)
        raise

    metadata = {
        "bundle": str(bundle),
        "compose": str(compose_path),
        "environment": str(environment_path),
        "frontend": f"http://127.0.0.1:{frontend_port}",
        "project_name": project_name,
        "release_image": preflight["release_image"],
        "runtime_image": preflight["runtime_image"],
        "status": "running",
    }
    _atomic_write(state_dir / "deployment.json", _json_bytes(metadata), mode=0o600)
    return {**metadata, "verified": True}


def _deployment_metadata(state_dir: Path) -> dict[str, Any]:
    state_dir = state_dir.expanduser().resolve(strict=True)
    metadata = _load_json(state_dir / "deployment.json", "deployment metadata")
    required = ("bundle", "compose", "environment", "project_name", "release_image")
    if any(not isinstance(metadata.get(name), str) or not metadata[name] for name in required):
        raise BundleError("deployment metadata is incomplete")
    if SAFE_PROJECT_RE.fullmatch(metadata["project_name"]) is None:
        raise BundleError("deployment metadata contains an invalid project name")
    compose = Path(metadata["compose"]).resolve(strict=True)
    bundle = Path(metadata["bundle"]).resolve(strict=True)
    environment = Path(metadata["environment"]).resolve(strict=True)
    if not _within(compose, bundle) or not _within(environment, state_dir):
        raise BundleError("deployment metadata paths escape their approved roots")
    return metadata


def deployment_command(*, state_dir: Path, action: str) -> dict[str, Any]:
    metadata = _deployment_metadata(state_dir)
    compose = [
        "docker",
        "compose",
        "--env-file",
        metadata["environment"],
        "-f",
        metadata["compose"],
    ]
    if action == "stop":
        _run([*compose, "down", "--remove-orphans"])
        status = "stopped"
    elif action == "status":
        output = _run([*compose, "ps", "--format", "json"], capture=True)
        return {**metadata, "compose_status": output}
    else:
        raise BundleError("unsupported deployment action")
    return {**metadata, "status": status}


def _resolve_fingerprint(argument: str | None) -> str:
    value = argument or os.getenv("JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT", "")
    return _require_fingerprint(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create a signed offline bundle")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--source-root", type=Path, default=ROOT)
    create.add_argument("--runtime-root", type=Path, required=True)
    create.add_argument("--release-dir", type=Path, required=True)
    create.add_argument("--oci-archive", type=Path)
    create.add_argument("--load-archive", type=Path)
    create.add_argument("--signing-key", type=Path, required=True)
    create.add_argument("--signer-fingerprint")

    preflight = subparsers.add_parser("preflight", help="verify without changing host state")
    preflight.add_argument("--bundle", type=Path, required=True)
    preflight.add_argument("--signer-fingerprint")

    restore = subparsers.add_parser("restore", help="verify and start a fresh production stack")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--signer-fingerprint")
    restore.add_argument("--secret-dir", type=Path, required=True)
    restore.add_argument("--state-dir", type=Path, required=True)
    restore.add_argument("--frontend-port", type=int, default=8027)

    for name in ("status", "stop"):
        command = subparsers.add_parser(name)
        command.add_argument("--state-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "create":
            result = create_bundle(
                output=args.output,
                source_root=args.source_root,
                runtime_root=args.runtime_root,
                release_dir=args.release_dir,
                oci_archive=args.oci_archive,
                load_archive=args.load_archive,
                signing_key=args.signing_key,
                signer_fingerprint=_resolve_fingerprint(args.signer_fingerprint),
            )
        elif args.command == "preflight":
            result = preflight_bundle(
                args.bundle,
                expected_fingerprint=_resolve_fingerprint(args.signer_fingerprint),
            )
        elif args.command == "restore":
            result = restore_bundle(
                bundle=args.bundle,
                expected_fingerprint=_resolve_fingerprint(args.signer_fingerprint),
                secret_dir=args.secret_dir,
                state_dir=args.state_dir,
                frontend_port=args.frontend_port,
            )
        else:
            result = deployment_command(state_dir=args.state_dir, action=args.command)
    except (BundleError, OSError, ValueError) as exc:
        print(f"offline deployment failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
