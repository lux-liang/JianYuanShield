from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import ASSET_ROOT, REPORT_ROOT  # noqa: E402
from system.backend.benchmark_evidence import benchmark_claim_status  # noqa: E402
from system.backend.signing import verify_evidence_bundle  # noqa: E402
from system.backend.utils import atomic_write_bytes, atomic_write_json  # noqa: E402


OUT = REPORT_ROOT / "aggregate_real_benchmarks"
ASSETS = ASSET_ROOT / "aggregate_real_benchmarks"


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite,
        )
    except (OSError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def flatten_method(summary: dict | None, method: str, mode: str, data_type: str) -> list[dict]:
    rows = []
    if not summary:
        rows.append({"method": method, "mode": mode, "data_type": data_type, "attack": "all", "status": "pending", "can_defense": "no"})
        return rows
    for attack, metrics in summary.get("attacks", {}).items():
        row = {
            "method": method,
            "mode": summary.get("mode", mode),
            "data_type": summary.get("data_type", data_type),
            "attack": attack,
            "status": metrics.get("status", "unknown"),
            "can_defense": (
                "yes"
                if summary.get("status") == "complete"
                and metrics.get("status") == "complete"
                else "no"
            ),
        }
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                row[k] = v
        rows.append(row)
    return rows


def complete_summary(path: Path, results_path: Path) -> tuple[dict | None, dict]:
    payload = load_json(path)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "benchmark-summary.v2"
        or payload.get("status") != "complete"
    ):
        return None, {"status": "missing_or_incomplete", "failed_requirements": ["summary_v2_complete"]}
    try:
        validation = benchmark_claim_status(
            payload,
            summary_path=path,
            results_path=results_path,
        )
    except Exception as exc:
        return None, {
            "status": "integrity_failed",
            "failed_requirements": [f"validator_error:{exc.__class__.__name__}"],
        }
    # Aggregate generation is downstream of the archived release-core bundle.
    # A self-declared complete summary must never bypass that signature chain.
    requirements = validation.get("evidence_requirements", {})
    failed = sorted(name for name, passed in requirements.items() if not passed)
    if failed:
        return None, {"status": "integrity_failed", "failed_requirements": failed}
    return payload, {"status": "complete", "failed_requirements": []}


def _logical_summary_path(directory: str) -> str:
    return f"reports/{directory}/summary.json"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    definitions = {
        "SepMark": ("sepmark_lfw_benchmark", "results.csv", "real_checkpoint", "lfw_full"),
        "WaveGuard": ("waveguard_lfw_benchmark", "results.csv", "official_checkpoint_strict", "lfw_full"),
        "LIDMark": (
            "lidmark_lfw_identity_test_epoch20_protocol_v1",
            "raw_results.csv",
            "selected_epoch20_identity_disjoint_test",
            "lfw_identity_disjoint_test",
        ),
        "KAD-Net": ("kadnet_lfw_benchmark", "results.csv", "official_epoch100_strict", "lfw_full"),
    }
    signature = verify_evidence_bundle()
    summaries: dict[str, dict | None] = {}
    sources: dict[str, dict] = {}
    for method, (directory, result_name, mode, data_type) in definitions.items():
        summary_path = REPORT_ROOT / directory / "summary.json"
        summary, validation = complete_summary(
            summary_path,
            REPORT_ROOT / directory / result_name,
        )
        summaries[method] = summary
        sources[method] = {
            "status": validation["status"],
            "summary_path": _logical_summary_path(directory),
            "summary_sha256": sha256_file(summary_path),
            "failed_requirements": validation["failed_requirements"],
        }
    rows = []
    for method, (_, _, mode, data_type) in definitions.items():
        rows += flatten_method(summaries[method], method, mode, data_type)
    fields = sorted({k for row in rows for k in row.keys()})
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write_bytes(
        OUT / "method_comparison.csv",
        csv_buffer.getvalue().encode("utf-8"),
    )
    complete_methods = [method for method, summary in summaries.items() if summary]
    aggregate_status = "complete" if len(complete_methods) == len(definitions) else "incomplete"
    aggregate = {
        "schema_version": "aggregate-benchmark-summary.v1",
        "status": aggregate_status,
        "required_methods": list(definitions),
        "complete_methods": complete_methods,
        "evidence_signature": {
            "status": signature.get("status", "not_generated"),
            "profile": signature.get("profile"),
            "verified": signature.get("verified") is True,
            "signer_pinned": signature.get("signer_pinned") is True,
            "manifest_sha256": signature.get("manifest_sha256"),
            "public_key_fingerprint_sha256": signature.get(
                "public_key_fingerprint_sha256"
            ),
        },
        "sources": sources,
        "rows": rows,
    }
    atomic_write_json(OUT / "summary.json", aggregate)
    # degradation curves for real-checkpoint baselines when available
    curves = []
    for method in definitions:
        summary = summaries[method]
        if summary and summary.get("attacks"):
            curves.append((method, summary["attacks"]))
    primary_accuracy = {
        "SepMark": "mean_bit_accuracy_c",
        "WaveGuard": "mean_bit_accuracy_tracer",
        "LIDMark": "mean_bit_accuracy",
        "KAD-Net": "mean_bit_accuracy",
    }
    curve_path = ASSETS / "attack_degradation.png"
    if aggregate_status == "complete":
        plt.figure(figsize=(8, 4))
        for label, attack_map in curves:
            attacks = list(attack_map.keys())
            metric = primary_accuracy[label]
            vals = [attack_map[a][metric] for a in attacks]
            plt.plot(attacks, vals, marker="o", label=label)
        plt.ylim(0, 1)
        plt.ylabel("Mean bit accuracy")
        plt.title("Four-model LFW attack robustness")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        image_buffer = io.BytesIO()
        plt.savefig(image_buffer, format="png", dpi=160)
        plt.close()
        atomic_write_bytes(curve_path, image_buffer.getvalue())
    else:
        curve_path.unlink(missing_ok=True)
    md = [
        "# 鉴源盾真实评测聚合报告",
        "",
        f"- Aggregate status: `{aggregate_status}`",
        "",
        "## 方法状态",
        "",
    ]
    for row in rows:
        md.append(f"- {row.get('method')} / {row.get('attack')}: {row.get('status')} ({row.get('mode')}, defense={row.get('can_defense')})")
    atomic_write_bytes(
        OUT / "aggregate_report.md",
        ("\n".join(md) + "\n").encode("utf-8"),
    )
    print(json.dumps(aggregate, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if aggregate_status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
