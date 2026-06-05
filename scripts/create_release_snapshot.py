from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "system/reports/release_snapshot.json"

sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
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


def git_snapshot() -> dict[str, Any]:
    status = run_git(["status", "--short"]) or ""
    return {
        "commit": run_git(["rev-parse", "HEAD"]),
        "short_commit": run_git(["rev-parse", "--short", "HEAD"]),
        "branch": run_git(["branch", "--show-current"]),
        "dirty": bool(status),
        "status_short": status.splitlines(),
        "remote_origin": run_git(["remote", "get-url", "origin"]),
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
    try:
        relative_path = path.relative_to(ROOT).as_posix()
    except ValueError:
        relative_path = str(path)
    return {
        "path": str(path),
        "relative_path": relative_path,
        "exists": exists,
        "size_bytes": path.stat().st_size if exists and path.is_file() else None,
        "sha256": sha256_file(path),
    }


def tracked_report_files() -> dict[str, Path]:
    return {
        "competition_report_json": ROOT / "system/reports/jianyuanshield_competition_report/report.json",
        "competition_report_csv": ROOT / "system/reports/jianyuanshield_competition_report/report.csv",
        "competition_report_markdown": ROOT / "system/reports/jianyuanshield_competition_report/report.md",
        "aggregate_summary": ROOT / "system/reports/aggregate_real_benchmarks/summary.json",
        "aggregate_comparison_csv": ROOT / "system/reports/aggregate_real_benchmarks/method_comparison.csv",
        "aggregate_report_markdown": ROOT / "system/reports/aggregate_real_benchmarks/aggregate_report.md",
        "hidden_summary": ROOT / "system/reports/hidden_lfw_full_benchmark/summary.json",
        "sepmark_summary": ROOT / "system/reports/sepmark_lfw_benchmark/summary.json",
        "lidmark_summary": ROOT / "runs/lidmark_lfw_eval_full/summary.json",
        "waveguard_summary": ROOT / "system/reports/waveguard_lfw_benchmark/summary.json",
        "waveguard_full_summary": ROOT / "system/reports/waveguard_lfw_full_benchmark/summary.json",
        "waveguard_small_summary": ROOT / "system/reports/waveguard_lfw_small_benchmark/summary.json",
    }


def build_snapshot() -> dict[str, Any]:
    from system.backend.artifacts import artifacts_status_payload
    from system.backend.runtime import runtime_health

    artifacts = artifacts_status_payload()
    runtime = runtime_health()
    return {
        "schema_version": "release_snapshot.v1",
        "generated_at": int(time.time()),
        "generated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(ROOT),
        "git": git_snapshot(),
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
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
