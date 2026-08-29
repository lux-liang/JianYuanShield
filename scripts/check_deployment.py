#!/usr/bin/env python3
"""Validate rendered Docker Compose security contracts, not just YAML syntax."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
IMMUTABLE_IMAGE_RE = re.compile(r"^[^\s:@]+(?:/[^\s:@]+)+@sha256:[0-9a-f]{64}$")
LOCAL_IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
LOOPBACKS = frozenset({"127.0.0.1", "::1"})


def _source_no_create_targets(path: Path) -> set[str]:
    """Read explicit bind safeguards lost by some Compose config versions."""
    targets: set[str] = set()
    block: list[str] = []
    for line in [*path.read_text(encoding="utf-8").splitlines(), "- end"]:
        stripped = line.lstrip()
        if stripped.startswith("- ") and block:
            text = "\n".join(block)
            target = re.search(r"^\s*target:\s*(\S+)\s*$", text, re.MULTILINE)
            if (
                re.search(r"^\s*- type:\s*bind\s*$", text, re.MULTILINE)
                and target
                and re.search(r"^\s*create_host_path:\s*false\s*$", text, re.MULTILINE)
            ):
                targets.add(target.group(1))
            block = []
        if stripped.startswith("- type:") or block:
            block.append(line)
    return targets


def _render(path: Path, env: dict[str, str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["docker", "compose", "-f", str(path), "config", "--format", "json"],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ValueError(f"unable to render {path.name}: {detail.strip()}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"rendered {path.name} is not an object")
    # Compose releases before the current spec may omit create_host_path from
    # normalized JSON. Preserve only safeguards explicitly present in source;
    # a missing YAML declaration still fails the deployment contract.
    source_targets = _source_no_create_targets(path)
    for service in payload.get("services", {}).values():
        for mount in service.get("volumes", []):
            if mount.get("type") == "bind" and mount.get("target") in source_targets:
                mount.setdefault("bind", {}).setdefault("create_host_path", False)
    return payload


def _service_hardening(service: dict[str, Any], name: str) -> list[str]:
    failures = []
    if service.get("read_only") is not True:
        failures.append(f"{name}: root filesystem is not read-only")
    if service.get("init") is not True:
        failures.append(f"{name}: init process is not enabled")
    if "ALL" not in service.get("cap_drop", []):
        failures.append(f"{name}: Linux capabilities are not fully dropped")
    if "no-new-privileges:true" not in service.get("security_opt", []):
        failures.append(f"{name}: no-new-privileges is missing")
    if not isinstance(service.get("pids_limit"), int) or service["pids_limit"] <= 0:
        failures.append(f"{name}: pids_limit is missing")
    logging = service.get("logging")
    if not isinstance(logging, dict) or logging.get("options", {}).get("max-size") is None:
        failures.append(f"{name}: bounded container logging is missing")
    for port in service.get("ports", []):
        if port.get("host_ip") not in LOOPBACKS:
            failures.append(f"{name}: published port is not loopback-bound")
    return failures


def _immutable_service(
    service: dict[str, Any],
    name: str,
    *,
    allow_local_digest: bool = False,
) -> list[str]:
    failures = []
    image = str(service.get("image") or "")
    if IMMUTABLE_IMAGE_RE.fullmatch(image) is None and not (
        allow_local_digest and LOCAL_IMAGE_RE.fullmatch(image) is not None
    ):
        failures.append(f"{name}: image is not pinned by sha256 digest")
    if service.get("build") is not None:
        failures.append(f"{name}: release deployment must not rebuild locally")
    return failures


def _secret_targets(service: dict[str, Any]) -> set[str | None]:
    return {
        item.get("target")
        for item in service.get("secrets", [])
        if isinstance(item, dict)
    }


def _mounts_by_target(service: dict[str, Any]) -> dict[str | None, dict[str, Any]]:
    return {
        item.get("target"): item
        for item in service.get("volumes", [])
        if isinstance(item, dict)
    }


def _validate_api_environment(
    service: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    failures = []
    environment = service.get("environment", {})
    expected_environment = {
        "JYS_MODE": "production",
        "JYS_ENABLE_DEMO": "false",
        "JYS_REQUIRE_API_KEY": "true",
        "JYS_API_KEY_FILE": "/run/secrets/jys_api_key",
        "JYS_PROVENANCE_SECRET_FILE": "/run/secrets/jys_provenance_secret",
        "JYS_EVIDENCE_PRIVATE_KEY": "/run/secrets/jys_evidence_private_key",
    }
    for key, expected in expected_environment.items():
        if environment.get(key) != expected:
            failures.append(f"{label}: {key} is not fail-closed")
    for forbidden in ("JYS_API_KEY", "JYS_PROVENANCE_SECRET"):
        if forbidden in environment:
            failures.append(f"{label}: plaintext secret environment {forbidden} is forbidden")
    cors_origins = str(environment.get("JYS_CORS_ORIGINS") or "")
    if not cors_origins or any(
        not origin.startswith("https://") for origin in cors_origins.split(",")
    ):
        failures.append(f"{label}: CORS origins must be explicit HTTPS origins")
    fingerprint = str(environment.get("JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT") or "")
    if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        failures.append(f"{label}: evidence signer fingerprint is not pinned")

    expected_secret_targets = {
        "/run/secrets/jys_api_key",
        "/run/secrets/jys_provenance_secret",
        "/run/secrets/jys_evidence_private_key",
    }
    if _secret_targets(service) != expected_secret_targets:
        failures.append(f"{label}: required secret mounts are incomplete")
    return failures


def _validate_read_only_binds(
    service: dict[str, Any],
    *,
    label: str,
    targets: tuple[str, ...],
) -> list[str]:
    failures = []
    mounts = _mounts_by_target(service)
    for target in targets:
        mount = mounts.get(target)
        if not mount or mount.get("type") != "bind" or mount.get("read_only") is not True:
            failures.append(f"{label}: {target} is not a read-only bind mount")
        elif mount.get("bind", {}).get("create_host_path") is not False:
            failures.append(f"{label}: {target} may create a missing host path")
    return failures


def _validate_gateway(service: dict[str, Any], *, label: str) -> list[str]:
    failures = []
    command = service.get("command", [])
    if not isinstance(command, list) or "system.gateway" not in command:
        failures.append(f"{label}: hardened same-origin gateway command is missing")
    environment = service.get("environment", {})
    expected = {
        "JYS_GATEWAY_UPSTREAM": "http://api:8026",
        "JYS_GATEWAY_API_KEY_FILE": "/run/secrets/jys_api_key",
        "JYS_GATEWAY_REQUIRE_API_KEY": "true",
        "JYS_GATEWAY_STATIC_ROOT": "/app/system/frontend",
        "JYS_GATEWAY_REQUIRE_UI_SESSION": "true",
        "JYS_GATEWAY_UI_PASSWORD_FILE": "/run/secrets/jys_ui_password",
        "JYS_GATEWAY_SESSION_SECRET_FILE": "/run/secrets/jys_session_secret",
    }
    for key, value in expected.items():
        if environment.get(key) != value:
            failures.append(f"{label}: {key} is not fail-closed")
    if "JYS_API_KEY" in environment:
        failures.append(f"{label}: browser gateway contains a plaintext API key")
    if not str(environment.get("JYS_GATEWAY_UI_USERNAME") or "").strip():
        failures.append(f"{label}: UI administrator username is missing")
    if _secret_targets(service) != {
        "/run/secrets/jys_api_key",
        "/run/secrets/jys_ui_password",
        "/run/secrets/jys_session_secret",
    }:
        failures.append(f"{label}: gateway file-secret mounts are incomplete")
    return failures


def validate_development(payload: dict[str, Any]) -> list[str]:
    services = payload.get("services", {})
    failures = []
    for name in ("api", "web"):
        service = services.get(name)
        if not isinstance(service, dict):
            failures.append(f"development: missing service {name}")
            continue
        failures.extend(_service_hardening(service, f"development/{name}"))
        if str(service.get("image") or "").endswith(":latest"):
            failures.append(f"development/{name}: mutable latest image tag is forbidden")
    return failures


def validate_production(payload: dict[str, Any]) -> list[str]:
    services = payload.get("services", {})
    failures = []
    for name in ("api", "web"):
        service = services.get(name)
        if not isinstance(service, dict):
            failures.append(f"production: missing service {name}")
            continue
        failures.extend(_service_hardening(service, f"production/{name}"))
        failures.extend(_immutable_service(service, f"production/{name}"))

    api = services.get("api", {})
    if isinstance(api, dict):
        failures.extend(_validate_api_environment(api, label="production/api"))
        failures.extend(
            _validate_read_only_binds(
                api,
                label="production/api",
                targets=("/app/weights", "/app/model-sources"),
            )
        )
    web = services.get("web", {})
    if isinstance(web, dict):
        failures.extend(_validate_gateway(web, label="production/web"))
    networks = payload.get("networks", {})
    if not any(isinstance(item, dict) and item.get("internal") is True for item in networks.values()):
        failures.append("production: service network is not isolated")
    return failures


def validate_competition(payload: dict[str, Any]) -> list[str]:
    """Validate the offline, no-development-fallback competition contract."""

    services = payload.get("services", {})
    failures: list[str] = []
    for name in ("api", "gateway"):
        service = services.get(name)
        if not isinstance(service, dict):
            failures.append(f"competition: missing service {name}")
            continue
        label = f"competition/{name}"
        failures.extend(_service_hardening(service, label))
        failures.extend(_immutable_service(service, label, allow_local_digest=True))
        if service.get("pull_policy") != "never":
            failures.append(f"{label}: offline deployment must set pull_policy=never")
        if not service.get("cpus") or not service.get("mem_limit"):
            failures.append(f"{label}: CPU or memory limit is missing")
        if not isinstance(service.get("healthcheck"), dict):
            failures.append(f"{label}: healthcheck is missing")

    api = services.get("api", {})
    if isinstance(api, dict):
        failures.extend(_validate_api_environment(api, label="competition/api"))
        environment = api.get("environment", {})
        exact_runtime = {
            "JYS_PROVENANCE_DB": "/app/runtime/state/provenance.sqlite3",
            "JYS_AUDIT_ANCHOR": "/app/runtime/audit-anchor/provenance-audit-anchor.json",
            "JYS_WARMUP_MODELS": "true",
            "JYS_INFER_DEVICE": "cuda:0",
        }
        for key, value in exact_runtime.items():
            if environment.get(key) != value:
                failures.append(f"competition/api: {key} is not fixed for real inference")
        failures.extend(
            _validate_read_only_binds(
                api,
                label="competition/api",
                targets=(
                    "/app/weights",
                    "/app/model-sources",
                    "/app/data",
                    "/app/runtime/reports",
                ),
            )
        )
        mounts = _mounts_by_target(api)
        runtime_targets = (
            "/app/runtime/assets",
            "/app/runtime/state",
            "/app/runtime/audit-anchor",
        )
        runtime_sources = []
        for target in runtime_targets:
            mount = mounts.get(target)
            if not mount or mount.get("type") != "volume" or mount.get("read_only") is True:
                failures.append(f"competition/api: {target} is not a writable named volume")
            else:
                runtime_sources.append(mount.get("source"))
        if len(runtime_sources) != len(set(runtime_sources)):
            failures.append("competition/api: state, assets and audit anchor must use distinct volumes")
        if api.get("ports"):
            failures.append("competition/api: backend API must not be directly published")
        reservations = api.get("deploy", {}).get("resources", {}).get("reservations", {})
        devices = reservations.get("devices", []) if isinstance(reservations, dict) else []
        if not any(
            isinstance(device, dict)
            and device.get("count") == 1
            and "gpu" in device.get("capabilities", [])
            for device in devices
        ):
            failures.append("competition/api: exactly one GPU reservation is missing")
        if not api.get("shm_size"):
            failures.append("competition/api: shared-memory limit is missing")

    gateway = services.get("gateway", {})
    if isinstance(gateway, dict):
        failures.extend(_validate_gateway(gateway, label="competition/gateway"))
        if not gateway.get("ports"):
            failures.append("competition/gateway: loopback console port is not published")

    networks = payload.get("networks", {})
    backend = networks.get("backend") if isinstance(networks, dict) else None
    if not isinstance(backend, dict) or backend.get("internal") is not True:
        failures.append("competition: backend network is not internal")
    if isinstance(api, dict) and set(api.get("networks", {})) != {"backend"}:
        failures.append("competition/api: API must attach only to the internal backend network")
    if isinstance(gateway, dict) and "backend" not in gateway.get("networks", {}):
        failures.append("competition/gateway: gateway cannot reach the internal API network")
    return failures


def main() -> int:
    environment = os.environ.copy()
    dummy_digest = "a" * 64
    defaults = {
        "JYS_RELEASE_IMAGE": f"ghcr.io/lux-liang/jianyuanshield@sha256:{dummy_digest}",
        "JYS_WEIGHT_HOST": "/tmp",
        "JYS_MODEL_SOURCE_HOST": "/tmp",
        "JYS_API_KEY_SECRET_FILE": "/dev/null",
        "JYS_PROVENANCE_SECRET_FILE": "/dev/null",
        "JYS_EVIDENCE_PRIVATE_KEY_FILE": "/dev/null",
        "JYS_UI_PASSWORD_SECRET_FILE": "/dev/null",
        "JYS_SESSION_SECRET_FILE": "/dev/null",
        "JYS_GATEWAY_UI_USERNAME": "jianyuanshield-admin",
        "JYS_EVIDENCE_PUBLIC_KEY_FINGERPRINT": "b" * 64,
        "JYS_CORS_ORIGINS": "https://console.example",
        "JYS_COMPOSE_PROJECT_NAME": "jys-competition-check",
        "JYS_DATA_HOST": "/tmp",
        "JYS_REPORT_HOST": "/tmp",
    }
    for key, value in defaults.items():
        environment.setdefault(key, value)
    try:
        development = _render(ROOT / "docker-compose.yml", environment)
        production = _render(ROOT / "docker-compose.production.yml", environment)
        competition = _render(ROOT / "docker-compose.competition.yml", environment)
    except ValueError as exc:
        print(f"deployment check failed: {exc}", file=sys.stderr)
        return 2
    failures = (
        validate_development(development)
        + validate_production(production)
        + validate_competition(competition)
    )
    if failures:
        for failure in failures:
            print(f"deployment check failed: {failure}", file=sys.stderr)
        return 2
    print("deployment contracts passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
