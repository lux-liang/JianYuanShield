#!/usr/bin/env python3
"""Build a commit-tagged OCI image with provenance, SBOM and digest records."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

try:
    from . import supply_chain
except ImportError:  # Executed directly as ``python scripts/build_release_image.py``.
    import supply_chain


ROOT = Path(__file__).resolve().parents[1]
IMAGE_RE = re.compile(
    r"^(?P<repository>[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+)"
    r":(?P<tag>[0-9a-f]{40})$"
)
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ReleaseBuildError(RuntimeError):
    pass


def _run(command: list[str], *, cwd: Path = ROOT) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ReleaseBuildError(f"command failed: {command[0]}: {detail.strip()}") from exc
    return completed.stdout.strip()


def _run_visible(command: list[str], *, cwd: Path = ROOT) -> None:
    """Run a long-lived command without buffering its potentially large output."""
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseBuildError(f"command failed: {command[0]}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    data = (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_copy(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def validate_image_reference(reference: str, commit: str) -> str:
    match = IMAGE_RE.fullmatch(reference)
    if match is None:
        raise ReleaseBuildError("release image must use a registry/repository:<40-char-git-commit> reference")
    if match.group("tag") != commit:
        raise ReleaseBuildError("release image tag must equal the checked-out Git commit")
    return reference


def validate_digest(value: str) -> str:
    normalized = value.strip().lower()
    if DIGEST_RE.fullmatch(normalized) is None:
        raise ReleaseBuildError("BuildKit did not return a valid sha256 image digest")
    return normalized


def image_digest_from_metadata(path: Path) -> str:
    """Read the exported image/manifest digest from BuildKit metadata."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError("BuildKit metadata is missing or invalid") from exc
    if not isinstance(payload, dict):
        raise ReleaseBuildError("BuildKit metadata must be a JSON object")
    digest = payload.get("containerimage.digest")
    if not isinstance(digest, str):
        descriptor = payload.get("containerimage.descriptor")
        digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    if not isinstance(digest, str):
        raise ReleaseBuildError("BuildKit metadata does not contain the exported image digest")
    return validate_digest(digest)


def image_config_digest_from_metadata(path: Path) -> str:
    """Read the immutable image-config digest used as an offline image ID."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseBuildError("BuildKit metadata is missing or invalid") from exc
    digest = payload.get("containerimage.config.digest") if isinstance(payload, dict) else None
    if not isinstance(digest, str):
        descriptor = payload.get("containerimage.config") if isinstance(payload, dict) else None
        digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    if not isinstance(digest, str):
        raise ReleaseBuildError("BuildKit metadata does not contain the image config digest")
    return validate_digest(digest)


def deployment_reference(image: str, digest: str) -> str:
    match = IMAGE_RE.fullmatch(image)
    if match is None:
        raise ReleaseBuildError("invalid release image reference")
    return f"{match.group('repository')}@{validate_digest(digest)}"


def release_source_state(root: Path = ROOT) -> tuple[str, str]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=root).lower()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ReleaseBuildError("unable to resolve a full Git commit")
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
    )
    if status:
        raise ReleaseBuildError("release image builds require a clean Git worktree")
    tree = _run(["git", "rev-parse", "HEAD^{tree}"], cwd=root).lower()
    if re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise ReleaseBuildError("unable to resolve the Git tree")
    return commit, tree


def build_release_record(
    *,
    image: str,
    image_digest: str,
    image_config_digest: str,
    commit: str,
    tree: str,
    output_type: str,
    build_metadata_path: Path,
    supply_manifest_path: Path,
    python_sbom_path: Path,
    oci_archive: Path | None,
    load_archive: Path | None,
) -> dict[str, Any]:
    normalized_digest = validate_digest(image_digest)
    normalized_config_digest = validate_digest(image_config_digest)
    record: dict[str, Any] = {
        "build": {
            "metadata_path": build_metadata_path.name,
            "metadata_sha256": _sha256_file(build_metadata_path),
            "output_type": output_type,
            "provenance": "mode=max",
            "sbom_attestation": True,
        },
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "image": {
            "config_digest": normalized_config_digest,
            "deployment_reference": deployment_reference(image, normalized_digest),
            "digest": normalized_digest,
            "immutable_reference": deployment_reference(image, normalized_digest),
            "offline_runtime_reference": normalized_config_digest,
            "tagged_reference": image,
        },
        "schema_version": "jianyuanshield-release-image.v1",
        "source": {"git_commit": commit, "git_tree": tree},
        "supply_chain_manifest": {
            "path": supply_manifest_path.name,
            "sha256": _sha256_file(supply_manifest_path),
        },
        "python_dependency_sbom": {
            "format": "CycloneDX",
            "path": python_sbom_path.name,
            "sha256": _sha256_file(python_sbom_path),
        },
    }
    if oci_archive is not None:
        record["build"]["oci_archive"] = {
            "path": oci_archive.name,
            "sha256": _sha256_file(oci_archive),
            "size_bytes": oci_archive.stat().st_size,
        }
    if load_archive is not None:
        record["build"]["load_archive"] = {
            "format": "docker-image-layout-with-oci-media-types",
            "path": load_archive.name,
            "sha256": _sha256_file(load_archive),
            "size_bytes": load_archive.stat().st_size,
        }
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="registry/repository:<full-git-commit>")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ROOT / "dist" / "supply-chain",
    )
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--push", action="store_true", help="push the immutable commit tag")
    output.add_argument(
        "--oci-output",
        type=Path,
        help="write an attested OCI archive and a Docker-loadable companion archive",
    )
    parser.add_argument(
        "--load-output",
        type=Path,
        help="Docker-loadable companion path (defaults beside --oci-output)",
    )
    args = parser.parse_args()

    failures = supply_chain.check_outputs(ROOT)
    if failures:
        for failure in failures:
            print(f"release build blocked: {failure}", file=sys.stderr)
        return 2
    try:
        commit, tree = release_source_state(ROOT)
        image = validate_image_reference(args.image, commit)
        artifact_dir = args.artifact_dir.expanduser().resolve()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = artifact_dir / "buildkit-metadata.json"
        command = [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/amd64",
            "--tag",
            image,
            "--label",
            f"org.opencontainers.image.revision={commit}",
            "--label",
            "org.opencontainers.image.source=https://github.com/lux-liang/JianYuanShield",
            "--provenance=mode=max",
            "--sbom=true",
            "--metadata-file",
            str(metadata_path),
        ]
        output_type: str
        oci_archive: Path | None = None
        load_archive: Path | None = None
        if args.push:
            if args.load_output is not None:
                raise ReleaseBuildError("--load-output is only valid with --oci-output")
            command.append("--push")
            output_type = "registry"
        else:
            oci_archive = args.oci_output.expanduser().resolve()
            load_archive = (
                args.load_output.expanduser().resolve()
                if args.load_output is not None
                else oci_archive.with_name(f"{oci_archive.stem}.docker.tar")
            )
            if load_archive == oci_archive:
                raise ReleaseBuildError("OCI and Docker-loadable archives must be distinct")
            oci_archive.parent.mkdir(parents=True, exist_ok=True)
            load_archive.parent.mkdir(parents=True, exist_ok=True)
            command.extend([
                "--output",
                f"type=oci,dest={oci_archive}",
                "--output",
                f"type=docker,oci-mediatypes=true,dest={load_archive}",
            ])
            output_type = "offline-dual-archive"
        command.append(str(ROOT))
        _run_visible(command)
        image_digest = image_digest_from_metadata(metadata_path)
        image_config_digest = image_config_digest_from_metadata(metadata_path)
        supply_manifest_path = artifact_dir / supply_chain.OUTPUT_MANIFEST.name
        python_sbom_path = artifact_dir / supply_chain.OUTPUT_SBOM.name
        _atomic_copy(ROOT / supply_chain.OUTPUT_MANIFEST, supply_manifest_path)
        _atomic_copy(ROOT / supply_chain.OUTPUT_SBOM, python_sbom_path)
        record = build_release_record(
            image=image,
            image_digest=image_digest,
            image_config_digest=image_config_digest,
            commit=commit,
            tree=tree,
            output_type=output_type,
            build_metadata_path=metadata_path,
            supply_manifest_path=supply_manifest_path,
            python_sbom_path=python_sbom_path,
            oci_archive=oci_archive,
            load_archive=load_archive,
        )
        _atomic_json(artifact_dir / "release-image.json", record)
    except (OSError, UnicodeError, ReleaseBuildError) as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        return 2
    print(f"release image built: {record['image']['deployment_reference']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
