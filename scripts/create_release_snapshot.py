from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_PROJECT_ROOT))
from system.evaluation.runtime import PROJECT_ROOT, REPORT_ROOT, logical_path  # noqa: E402
from system.backend.utils import atomic_write_json  # noqa: E402


ROOT = PROJECT_ROOT
DEFAULT_OUTPUT = REPORT_ROOT / "release_snapshot.json"
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "jianyuanshield-matplotlib"))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)


def run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def sanitized_remote_origin() -> str | None:
    remote = run_git(["remote", "get-url", "origin"])
    if not remote:
        return remote
    if "://" not in remote:
        if "@" in remote and not remote.startswith("git@"):
            return "<redacted>@" + remote.split("@", 1)[1]
        return remote
    parsed = urlsplit(remote)
    hostname = parsed.hostname or ""
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def git_snapshot() -> dict[str, Any]:
    status = run_git(["status", "--short"])
    return {
        "commit": run_git(["rev-parse", "HEAD"]),
        "short_commit": run_git(["rev-parse", "--short", "HEAD"]),
        "branch": run_git(["branch", "--show-current"]),
        "dirty": True if status is None else bool(status),
        "status_available": status is not None,
        "status_short": status.splitlines() if status is not None else [],
        "remote_origin": sanitized_remote_origin(),
    }


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_snapshot(path: Path) -> dict[str, Any]:
    exists = path.exists()
    relative_path = logical_path(path)
    return {
        "path": relative_path,
        "relative_path": relative_path,
        "exists": exists,
        "size_bytes": path.stat().st_size if exists and path.is_file() else None,
        "sha256": sha256_file(path),
    }


def tracked_report_files() -> dict[str, Path]:
    tracked = {
        "release_core_manifest": REPORT_ROOT / "evidence_signature/release-core/manifest.json",
        "release_core_signature": REPORT_ROOT / "evidence_signature/release-core/manifest.sig",
        "release_core_public_key": REPORT_ROOT / "evidence_signature/release-core/public_key.pem",
        "mea_dataset_manifest": REPORT_ROOT / "mea-4x4-protocol-v1-s20260603-n256/dataset_manifest.json",
        "mea_run_config": REPORT_ROOT / "mea-4x4-protocol-v1-s20260603-n256/run_config.json",
        "mea_raw_results": REPORT_ROOT / "mea-4x4-protocol-v1-s20260603-n256/raw_results.csv",
        "mea_progress": REPORT_ROOT / "mea-4x4-protocol-v1-s20260603-n256/progress.json",
        "mea_summary": REPORT_ROOT / "mea-4x4-protocol-v1-s20260603-n256/summary.json",
        "collaboration_policy": ROOT / "configs/collaboration_policy.v2.json",
        "supply_chain_requirements_lock": ROOT / "requirements.lock",
        "supply_chain_build_manifest": ROOT / "supply-chain/build-manifest.json",
        "supply_chain_python_sbom": ROOT / "supply-chain/python-dependencies.cdx.json",
        "competition_report_json": REPORT_ROOT / "jianyuanshield_competition_report/report.json",
        "competition_report_csv": REPORT_ROOT / "jianyuanshield_competition_report/report.csv",
        "competition_report_markdown": REPORT_ROOT / "jianyuanshield_competition_report/report.md",
        "aggregate_summary": REPORT_ROOT / "aggregate_real_benchmarks/summary.json",
        "aggregate_comparison_csv": REPORT_ROOT / "aggregate_real_benchmarks/method_comparison.csv",
        "aggregate_report_markdown": REPORT_ROOT / "aggregate_real_benchmarks/aggregate_report.md",
        "protocol_audit_json": REPORT_ROOT / "protocol_audit/audit.json",
        "protocol_audit_statistics": REPORT_ROOT / "protocol_audit/statistics.csv",
        "protocol_audit_markdown": REPORT_ROOT / "protocol_audit/audit.md",
        "statistical_analysis_json": REPORT_ROOT / "statistical_analysis/analysis.json",
        "statistical_comparisons": REPORT_ROOT / "statistical_analysis/comparisons.csv",
        "sepmark_summary": REPORT_ROOT / "sepmark_lfw_benchmark/summary.json",
        "sepmark_raw_results": REPORT_ROOT / "sepmark_lfw_benchmark/results.csv",
        "sepmark_watermarked_quality": REPORT_ROOT / "sepmark_lfw_benchmark/watermarked_quality.csv",
        "lidmark_summary": REPORT_ROOT / "lidmark_lfw_identity_test_epoch20_protocol_v1/summary.json",
        "lidmark_raw_results": REPORT_ROOT / "lidmark_lfw_identity_test_epoch20_protocol_v1/raw_results.csv",
        "waveguard_summary": REPORT_ROOT / "waveguard_lfw_benchmark/summary.json",
        "waveguard_raw_results": REPORT_ROOT / "waveguard_lfw_benchmark/results.csv",
        "waveguard_watermarked_quality": REPORT_ROOT / "waveguard_lfw_benchmark/watermarked_quality.csv",
        "kadnet_summary": REPORT_ROOT / "kadnet_lfw_benchmark/summary.json",
        "kadnet_raw_results": REPORT_ROOT / "kadnet_lfw_benchmark/results.csv",
        "kadnet_watermarked_quality": REPORT_ROOT / "kadnet_lfw_benchmark/watermarked_quality.csv",
    }
    from system.backend.simswap_evidence import (
        SIMSWAP_ASSET_PATHS,
        SIMSWAP_EVIDENCE_DIR,
        SIMSWAP_EVIDENCE_NAMES,
    )

    tracked.update(
        {
            f"simswap_{Path(name).stem}": SIMSWAP_EVIDENCE_DIR / name
            for name in SIMSWAP_EVIDENCE_NAMES
        }
    )
    tracked.update(
        {
            f"simswap_visual_{index:03d}": path
            for index, path in enumerate(SIMSWAP_ASSET_PATHS, start=1)
        }
    )
    return tracked


def build_snapshot() -> dict[str, Any]:
    from system.backend.artifacts import artifacts_status_payload
    from system.backend.runtime import runtime_health

    artifacts = artifacts_status_payload()
    runtime = runtime_health()
    git = git_snapshot()
    release_ready = bool(
        git.get("commit")
        and git.get("status_available") is True
        and git.get("dirty") is False
        and artifacts.get("ready_for_demo") is True
    )
    return {
        "schema_version": "release_snapshot.v1",
        "generated_at": int(time.time()),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": ".",
        "release_ready": release_ready,
        "git": git,
        "runtime": {
            "version": runtime.get("version"),
            "mode": runtime.get("mode"),
            "settings": runtime.get("settings"),
        },
        "artifacts": {
            "ready_for_demo": artifacts.get("ready_for_demo"),
            "checks": artifacts.get("checks"),
            "missing": artifacts.get("missing"),
            "summary": artifacts.get("summary"),
        },
        "reports": {name: file_snapshot(path) for name, path in tracked_report_files().items()},
    }


def write_snapshot(output: Path) -> dict[str, Any]:
    snapshot = build_snapshot()
    atomic_write_json(output, snapshot)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a reproducibility snapshot for the current JianYuanShield release state.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON path.")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    snapshot = write_snapshot(output)
    print(json.dumps({
        "output": str(output),
        "schema_version": snapshot["schema_version"],
        "commit": snapshot["git"]["short_commit"],
        "branch": snapshot["git"]["branch"],
        "dirty": snapshot["git"]["dirty"],
        "ready_for_demo": snapshot["artifacts"]["ready_for_demo"],
    }, indent=2, ensure_ascii=False))
    return 0 if snapshot["release_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
