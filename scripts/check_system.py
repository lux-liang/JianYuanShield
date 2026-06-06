from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)


@dataclass
class Check:
    name: str
    status: str
    detail: str
    critical: bool = False


def add(checks: list[Check], name: str, ok: bool, detail: str, critical: bool = False, warn: bool = False) -> None:
    status = "OK" if ok else ("WARN" if warn else "FAIL")
    checks.append(Check(name=name, status=status, detail=detail, critical=critical))


def check_imports(checks: list[Check]) -> None:
    modules = [
        "fastapi",
        "uvicorn",
        "cv2",
        "numpy",
        "PIL",
        "skimage",
        "matplotlib",
        "torch",
        "torchvision",
    ]
    missing: list[str] = []
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as exc:
            missing.append(f"{module} ({exc.__class__.__name__})")
    add(
        checks,
        "python imports",
        not missing,
        "all required packages import" if not missing else "missing: " + ", ".join(missing),
        critical=True,
    )


def check_backend(checks: list[Check]) -> None:
    try:
        module = importlib.import_module("system.backend.app")
        title = getattr(module, "app").title
        add(checks, "backend import", True, title, critical=True)
    except Exception as exc:
        add(checks, "backend import", False, repr(exc), critical=True)


def check_frontend(checks: list[Check]) -> None:
    files = [
        ROOT / "system/frontend/index.html",
        ROOT / "system/frontend/app.js",
        ROOT / "system/frontend/styles.css",
    ]
    missing = [str(path.relative_to(ROOT)) for path in files if not path.exists()]
    add(
        checks,
        "frontend files",
        not missing,
        "index/app/styles present" if not missing else "missing: " + ", ".join(missing),
        critical=True,
    )


def artifact_detail(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    missing = payload.get("missing", [])
    detail = (
        f"status={summary.get('status', 'unknown')}; "
        f"images={summary.get('dataset_images', 0)}; "
        f"checkpoints={summary.get('checkpoint_files', 0)}; "
        f"benchmark_outputs={summary.get('benchmark_outputs', 0)}; "
        f"asset_files={summary.get('asset_files', 0)}"
    )
    if missing:
        detail += "; missing=" + ",".join(missing)
    return detail


def append_artifact_checks(checks: list[Check], payload: dict[str, Any]) -> None:
    add(checks, "artifacts status", bool(payload.get("ready_for_demo")), artifact_detail(payload), warn=True)
    labels = {
        "dataset_ready": "datasets",
        "weights_ready": "weights",
        "benchmark_ready": "benchmark outputs",
        "aggregate_ready": "aggregate report",
        "report_ready": "competition report",
        "assets_ready": "visual assets",
    }
    artifact_checks = payload.get("checks", {})
    for key, label in labels.items():
        add(checks, label, bool(artifact_checks.get(key)), key, warn=True)


def check_artifacts(checks: list[Check]) -> dict[str, Any]:
    try:
        from system.backend.artifacts import artifacts_status_payload

        payload = artifacts_status_payload()
        append_artifact_checks(checks, payload)
        return payload
    except Exception as exc:
        add(checks, "artifacts status", False, repr(exc), critical=True)
        return {"ready_for_demo": False, "checks": {}, "missing": ["artifacts_status_failed"], "summary": {}}


def check_claims(checks: list[Check]) -> dict[str, Any]:
    try:
        from system.backend.evidence import evidence_audit_payload

        payload = evidence_audit_payload()
        blockers = payload.get("blocking_findings", [])
        add(
            checks,
            "research claims",
            bool(payload.get("ready_for_claims")),
            (
                f"status={payload.get('status')}; "
                f"blocking_findings={len(blockers)}"
            ),
            warn=True,
        )
        return payload
    except Exception as exc:
        add(checks, "research claims", False, repr(exc), critical=True)
        return {"ready_for_claims": False, "blocking_findings": [{"code": "claims_check_failed"}]}


def check_api(checks: list[Check], api: str) -> None:
    url = api.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        add(checks, "api health", bool(payload.get("ok")), url, warn=True)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        add(checks, "api health", False, f"{url}; {exc.__class__.__name__}", warn=True)


def print_report(checks: list[Check], ready_for_demo: bool, ready_for_claims: bool) -> None:
    width = max(len(check.name) for check in checks)
    for check in checks:
        print(f"[{check.status:<4}] {check.name:<{width}}  {check.detail}")
    print()
    print(f"ready_for_demo: {'yes' if ready_for_demo else 'no'}")
    print(f"ready_for_claims: {'yes' if ready_for_claims else 'no'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check JianYuanShield runtime, assets, and reports.")
    parser.add_argument("--api", default="http://127.0.0.1:8026", help="Backend base URL for optional health check.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when demo assets/reports are not ready.")
    parser.add_argument("--strict-claims", action="store_true", help="Return non-zero when research claims are blocked.")
    args = parser.parse_args()

    checks: list[Check] = []
    check_imports(checks)
    check_backend(checks)
    check_frontend(checks)
    artifacts = check_artifacts(checks)
    claims = check_claims(checks)
    check_api(checks, args.api)

    core_ok = all(check.status == "OK" for check in checks if check.critical)
    ready_for_demo = core_ok and bool(artifacts.get("ready_for_demo"))
    ready_for_claims = core_ok and bool(claims.get("ready_for_claims"))

    print_report(checks, ready_for_demo, ready_for_claims)
    if not core_ok:
        return 1
    if args.strict and not ready_for_demo:
        return 2
    if args.strict_claims and not ready_for_claims:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
