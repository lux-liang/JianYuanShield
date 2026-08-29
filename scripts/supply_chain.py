#!/usr/bin/env python3
"""Generate and verify deterministic release supply-chain artifacts.

The checked-in lock file is platform-specific (CPython 3.11, Linux x86-64,
CUDA 12.8).  Docker builds consume it with ``pip --require-hashes``.  This
script fails closed when the base image is not digest-pinned, a dependency is
not exactly locked and hashed, the direct requirements are not represented,
or the generated CycloneDX/manifest files are stale.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parents[1]
LOCK_COMMAND = (
    "uv pip compile requirements.txt --output-file requirements.lock "
    "--python-version 3.11 --python-platform x86_64-manylinux_2_28 "
    "--torch-backend cu128 --only-binary :all: --generate-hashes --no-annotate"
)
LOCK_HEADER = f"#    {LOCK_COMMAND}"
BASE_IMAGE_RE = re.compile(
    r"^FROM\s+(?P<reference>[^@\s]+)@sha256:(?P<digest>[0-9a-f]{64})\s*$",
    re.IGNORECASE,
)
LOCK_ENTRY_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)\s*\\?$"
)
HASH_RE = re.compile(r"^\s+--hash=sha256:(?P<digest>[0-9a-f]{64})\s*\\?$")
DIRECT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^]]+\])?\s*(?P<constraints>.+)$"
)
CONSTRAINT_RE = re.compile(r"(==|>=|<=|<|>|~=)\s*([0-9]+(?:\.[0-9]+)*)")
OUTPUT_SBOM = Path("supply-chain/python-dependencies.cdx.json")
OUTPUT_MANIFEST = Path("supply-chain/build-manifest.json")
APT_SNAPSHOT_RE = re.compile(r"--snapshot\s+(?P<snapshot>[0-9]{8}T[0-9]{6}Z)")
REQUIRED_OS_PACKAGES = ("libgl1", "libglib2.0-0")


class SupplyChainError(ValueError):
    pass


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
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


def parse_base_image(dockerfile: Path) -> dict[str, str]:
    matches = []
    for raw_line in dockerfile.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("FROM "):
            match = BASE_IMAGE_RE.fullmatch(line)
            if match is None:
                raise SupplyChainError("Dockerfile base image must include an immutable sha256 digest")
            matches.append(match.groupdict())
    if len(matches) != 1:
        raise SupplyChainError("Dockerfile must contain exactly one digest-pinned FROM instruction")
    reference = matches[0]["reference"]
    if ":" not in reference or reference.endswith(":latest"):
        raise SupplyChainError("Dockerfile base image must use an explicit non-latest tag")
    return {
        "reference": reference,
        "digest": f"sha256:{matches[0]['digest'].lower()}",
        "immutable_reference": f"{reference}@sha256:{matches[0]['digest'].lower()}",
    }


def parse_lock(lock_path: Path) -> list[dict[str, Any]]:
    text = lock_path.read_text(encoding="utf-8")
    if LOCK_HEADER not in text.splitlines()[:5]:
        raise SupplyChainError("requirements.lock was not generated with the pinned release command")

    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    seen: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        entry_match = LOCK_ENTRY_RE.fullmatch(raw_line)
        if entry_match:
            normalized = _normalized_name(entry_match.group("name"))
            if normalized in seen:
                raise SupplyChainError(f"duplicate locked dependency: {normalized}")
            current = {
                "name": normalized,
                "version": entry_match.group("version"),
                "hashes": [],
            }
            entries.append(current)
            seen.add(normalized)
            continue
        hash_match = HASH_RE.fullmatch(raw_line)
        if hash_match and current is not None:
            current["hashes"].append(hash_match.group("digest"))
            continue
        raise SupplyChainError(f"unsupported requirements.lock syntax at line {line_number}")

    if not entries:
        raise SupplyChainError("requirements.lock contains no dependencies")
    for entry in entries:
        hashes = entry["hashes"]
        if not hashes or len(hashes) != len(set(hashes)):
            raise SupplyChainError(f"locked dependency has missing or duplicate hashes: {entry['name']}")
        hashes.sort()
    return entries


def _version_tuple(value: str) -> tuple[tuple[int, ...], int, int]:
    public = value.split("+", 1)[0]
    match = re.fullmatch(
        r"(?P<release>[0-9]+(?:\.[0-9]+)*)(?:(?P<pre>a|b|rc)(?P<pre_number>[0-9]+)|\.post(?P<post_number>[0-9]+))?",
        public,
    )
    if match is None:
        raise SupplyChainError(f"unsupported direct dependency version: {value}")
    release = tuple(int(part) for part in match.group("release").split("."))
    if match.group("pre"):
        return release, -1, int(match.group("pre_number"))
    if match.group("post_number"):
        return release, 1, int(match.group("post_number"))
    return release, 0, 0


def _compare_versions(
    left: tuple[tuple[int, ...], int, int],
    right: tuple[tuple[int, ...], int, int],
) -> int:
    left_release, left_stage, left_stage_number = left
    right_release, right_stage, right_stage_number = right
    width = max(len(left_release), len(right_release))
    padded_left = left_release + (0,) * (width - len(left_release))
    padded_right = right_release + (0,) * (width - len(right_release))
    left_key = (padded_left, left_stage, left_stage_number)
    right_key = (padded_right, right_stage, right_stage_number)
    return (left_key > right_key) - (left_key < right_key)


def _constraint_satisfied(version: str, operator: str, requested: str) -> bool:
    current = _version_tuple(version)
    target = _version_tuple(requested)
    comparison = _compare_versions(current, target)
    if operator == "==":
        return comparison == 0
    if operator == ">=":
        return comparison >= 0
    if operator == "<=":
        return comparison <= 0
    if operator == ">":
        return comparison > 0
    if operator == "<":
        return comparison < 0
    if operator == "~=":
        release = target[0]
        upper_release = (
            release[:-1] + (release[-1] + 1,)
            if len(release) == 2
            else release[:-2] + (release[-2] + 1, 0)
        )
        return comparison >= 0 and _compare_versions(current, (upper_release, 0, 0)) < 0
    raise SupplyChainError(f"unsupported dependency operator: {operator}")


def validate_direct_requirements(requirements_path: Path, entries: list[dict[str, Any]]) -> None:
    locked = {entry["name"]: entry["version"] for entry in entries}
    direct_count = 0
    for line_number, raw_line in enumerate(
        requirements_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = DIRECT_RE.fullmatch(line)
        if match is None:
            raise SupplyChainError(f"unsupported direct requirement at line {line_number}")
        name = _normalized_name(match.group("name"))
        version = locked.get(name)
        if version is None:
            raise SupplyChainError(f"direct requirement is absent from lock: {name}")
        constraints = CONSTRAINT_RE.findall(match.group("constraints"))
        if not constraints:
            raise SupplyChainError(f"direct requirement is not version-constrained: {name}")
        if not all(_constraint_satisfied(version, operator, requested) for operator, requested in constraints):
            raise SupplyChainError(f"locked version violates direct requirement: {name}=={version}")
        direct_count += 1
    if direct_count == 0:
        raise SupplyChainError("requirements.txt contains no direct dependencies")


def validate_docker_install_contract(dockerfile: Path) -> None:
    source = dockerfile.read_text(encoding="utf-8")
    required_fragments = (
        "--require-hashes",
        "--only-binary=:all:",
        "-r requirements.lock",
        "COPY docker-compose.yml docker-compose.production.yml docker-compose.competition.yml ./",
        "COPY scripts/supply_chain.py scripts/build_release_image.py scripts/check_deployment.py scripts/offline_bundle.py ./scripts/",
        "COPY offline_deploy.sh ./",
        "COPY THIRD_PARTY_NOTICES.md ./",
        "COPY system/gateway.py ./system/gateway.py",
        "scripts/supply_chain.py check",
        "scripts/supply_chain.py verify-environment",
    )
    missing = [fragment for fragment in required_fragments if fragment not in source]
    if missing:
        raise SupplyChainError("Dockerfile is missing fail-closed dependency controls: " + ", ".join(missing))

    logical_instructions: list[str] = []
    current = ""
    for raw_line in source.splitlines():
        stripped = raw_line.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        current = f"{current} {stripped}".strip() if current else stripped
        if current.endswith("\\"):
            current = current[:-1].rstrip()
            continue
        logical_instructions.append(current)
        current = ""
    if current:
        logical_instructions.append(current)

    version_copies = [
        index
        for index, instruction in enumerate(logical_instructions)
        if re.fullmatch(r"COPY\s+VERSION\s+\./", instruction, re.IGNORECASE)
    ]
    supply_checks = [
        index
        for index, instruction in enumerate(logical_instructions)
        if instruction.upper().startswith("RUN ")
        and re.search(r"\bscripts/supply_chain\.py\s+check\b", instruction)
    ]
    if len(version_copies) != 1:
        raise SupplyChainError(
            "Dockerfile must copy the root VERSION file exactly once with 'COPY VERSION ./'"
        )
    if len(supply_checks) != 1:
        raise SupplyChainError("Dockerfile must run supply_chain.py check exactly once")
    if version_copies[0] > supply_checks[0]:
        raise SupplyChainError("Dockerfile must copy VERSION before running supply_chain.py check")


def parse_os_dependencies(dockerfile: Path) -> dict[str, Any]:
    source = dockerfile.read_text(encoding="utf-8")
    snapshots = APT_SNAPSHOT_RE.findall(source)
    if len(snapshots) < 2 or len(set(snapshots)) != 1:
        raise SupplyChainError("APT update and install must use one immutable Ubuntu snapshot")
    if "[snapshot=yes]" not in source:
        raise SupplyChainError("Ubuntu 22.04 APT sources must explicitly enable snapshots")
    missing = [package for package in REQUIRED_OS_PACKAGES if package not in source]
    if missing:
        raise SupplyChainError("Dockerfile is missing required OS packages: " + ", ".join(missing))
    return {
        "distribution": "ubuntu-22.04",
        "packages": list(REQUIRED_OS_PACKAGES),
        "snapshot": snapshots[0],
    }


def _component(entry: dict[str, Any]) -> dict[str, Any]:
    purl_name = entry["name"]
    purl = f"pkg:pypi/{purl_name}@{entry['version']}"
    return {
        "bom-ref": purl,
        "name": entry["name"],
        "purl": purl,
        "type": "library",
        "version": entry["version"],
    }


def build_outputs(root: Path = ROOT) -> dict[Path, bytes]:
    version_path = root / "VERSION"
    dockerfile = root / "Dockerfile"
    requirements_path = root / "requirements.txt"
    lock_path = root / "requirements.lock"
    generator_path = root / "scripts" / "supply_chain.py"
    release_builder_path = root / "scripts" / "build_release_image.py"
    deployment_checker_path = root / "scripts" / "check_deployment.py"
    development_compose_path = root / "docker-compose.yml"
    production_compose_path = root / "docker-compose.production.yml"
    competition_compose_path = root / "docker-compose.competition.yml"
    offline_entrypoint_path = root / "offline_deploy.sh"
    offline_bundle_path = root / "scripts" / "offline_bundle.py"
    gateway_path = root / "system" / "gateway.py"
    third_party_notices_path = root / "THIRD_PARTY_NOTICES.md"
    caddy_path = root / "deployment" / "Caddyfile.jianyuanshield"
    h100_api_path = root / "deployment" / "run-h100-api.sh"
    h100_gateway_path = root / "deployment" / "run-h100-gateway.sh"
    h100_tunnel_path = root / "deployment" / "run-h100-tunnel.sh"
    supervisor_path = root / "deployment" / "supervisor-jianyuanshield.conf"
    public_release_path = root / "deployment" / "deploy-public-release.sh"
    for path in (
        dockerfile,
        requirements_path,
        lock_path,
        generator_path,
        release_builder_path,
        deployment_checker_path,
        development_compose_path,
        production_compose_path,
        competition_compose_path,
        offline_entrypoint_path,
        offline_bundle_path,
        gateway_path,
        third_party_notices_path,
        version_path,
        caddy_path,
        h100_api_path,
        h100_gateway_path,
        h100_tunnel_path,
        supervisor_path,
        public_release_path,
    ):
        if not path.is_file() or path.is_symlink():
            raise SupplyChainError(f"required supply-chain input is missing or unsafe: {path.name}")

    base_image = parse_base_image(dockerfile)
    os_dependencies = parse_os_dependencies(dockerfile)
    entries = parse_lock(lock_path)
    validate_direct_requirements(requirements_path, entries)
    validate_docker_install_contract(dockerfile)
    lock_sha256 = _sha256_file(lock_path)
    project_version = version_path.read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[1-9][0-9]*\.[0-9]+\.[0-9]+", project_version) is None:
        raise SupplyChainError("VERSION must contain a semantic release version")
    root_component = f"pkg:generic/jianyuanshield@{project_version}"
    serial = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"jianyuanshield:{project_version}:{lock_sha256}",
    )
    sbom = {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "components": [_component(entry) for entry in entries],
        "dependencies": [
            {"ref": root_component, "dependsOn": [f"pkg:pypi/{entry['name']}@{entry['version']}" for entry in entries]},
            *[
                {"ref": f"pkg:pypi/{entry['name']}@{entry['version']}", "dependsOn": []}
                for entry in entries
            ],
        ],
        "metadata": {
            "component": {
                "bom-ref": root_component,
                "name": "JianYuanShield",
                "type": "application",
                "version": project_version,
            },
            "properties": [
                {
                    "name": "jianyuanshield:requirements-lock-sha256",
                    "value": lock_sha256,
                }
            ],
            "tools": {
                "components": [
                    {
                        "name": "scripts/supply_chain.py",
                        "type": "application",
                        "version": "1",
                    }
                ]
            },
        },
        "serialNumber": f"urn:uuid:{serial}",
        "specVersion": "1.6",
        "version": 1,
    }
    sbom_bytes = _json_bytes(sbom)
    manifest = {
        "base_image": base_image,
        "dependencies": {
            "direct_requirements_path": "requirements.txt",
            "direct_requirements_sha256": _sha256_file(requirements_path),
            "install_mode": "pip --require-hashes --only-binary=:all:",
            "lock_command": LOCK_COMMAND,
            "lock_path": "requirements.lock",
            "lock_sha256": lock_sha256,
            "locked_package_count": len(entries),
            "target": {
                "accelerator": "cuda12.8",
                "architecture": "x86_64",
                "operating_system": "linux-manylinux_2_28",
                "python": "3.11",
            },
        },
        "deployment": {
            "caddy_sha256": _sha256_file(caddy_path),
            "checker_sha256": _sha256_file(deployment_checker_path),
            "competition_compose_sha256": _sha256_file(competition_compose_path),
            "development_compose_sha256": _sha256_file(development_compose_path),
            "gateway_sha256": _sha256_file(gateway_path),
            "h100_api_launcher_sha256": _sha256_file(h100_api_path),
            "h100_gateway_launcher_sha256": _sha256_file(h100_gateway_path),
            "h100_tunnel_launcher_sha256": _sha256_file(h100_tunnel_path),
            "offline_bundle_sha256": _sha256_file(offline_bundle_path),
            "offline_entrypoint_sha256": _sha256_file(offline_entrypoint_path),
            "production_compose_sha256": _sha256_file(production_compose_path),
            "public_release_sha256": _sha256_file(public_release_path),
            "supervisor_sha256": _sha256_file(supervisor_path),
        },
        "dockerfile": {
            "path": "Dockerfile",
            "sha256": _sha256_file(dockerfile),
        },
        "licensing": {
            "third_party_notices_path": "THIRD_PARTY_NOTICES.md",
            "third_party_notices_sha256": _sha256_file(third_party_notices_path),
        },
        "generator": {
            "path": "scripts/supply_chain.py",
            "sha256": _sha256_file(generator_path),
        },
        "release_image_builder": {
            "path": "scripts/build_release_image.py",
            "sha256": _sha256_file(release_builder_path),
        },
        "os_dependencies": os_dependencies,
        "sbom": {
            "format": "CycloneDX",
            "path": OUTPUT_SBOM.as_posix(),
            "sha256": _sha256_bytes(sbom_bytes),
            "spec_version": "1.6",
        },
        "schema_version": "jianyuanshield-supply-chain.v1",
        "software": {
            "name": "鉴源盾内容来源可信取证系统",
            "version": project_version,
            "version_file_sha256": _sha256_file(version_path),
        },
        "status": "verified",
    }
    return {
        OUTPUT_SBOM: sbom_bytes,
        OUTPUT_MANIFEST: _json_bytes(manifest),
    }


def write_outputs(root: Path = ROOT) -> None:
    for relative, data in build_outputs(root).items():
        _atomic_write(root / relative, data)


def check_outputs(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    try:
        expected = build_outputs(root)
    except (OSError, UnicodeError, SupplyChainError) as exc:
        return [str(exc)]
    for relative, data in expected.items():
        path = root / relative
        try:
            actual = path.read_bytes()
        except OSError:
            failures.append(f"missing generated artifact: {relative.as_posix()}")
            continue
        if path.is_symlink() or actual != data:
            failures.append(f"stale or unsafe generated artifact: {relative.as_posix()}")
    return failures


def verify_environment(root: Path = ROOT) -> list[str]:
    try:
        entries = parse_lock(root / "requirements.lock")
    except (OSError, UnicodeError, SupplyChainError) as exc:
        return [str(exc)]
    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            installed[_normalized_name(name)] = distribution.version
    failures = []
    for entry in entries:
        actual = installed.get(entry["name"])
        if actual != entry["version"]:
            failures.append(
                f"installed dependency mismatch: {entry['name']} expected={entry['version']} actual={actual or 'missing'}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "write", "verify-environment"))
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "write":
        try:
            write_outputs(root)
        except (OSError, UnicodeError, SupplyChainError) as exc:
            print(f"supply-chain generation failed: {exc}", file=sys.stderr)
            return 2
        print("supply-chain artifacts generated")
        return 0
    failures = check_outputs(root) if args.command == "check" else verify_environment(root)
    if failures:
        for failure in failures:
            print(f"supply-chain check failed: {failure}", file=sys.stderr)
        return 2
    print(f"supply-chain {args.command} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
