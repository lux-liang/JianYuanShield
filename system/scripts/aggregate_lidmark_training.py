#!/usr/bin/env python3
"""Aggregate independently selected LIDMark training runs.

The command consumes selector outputs, preserves their integrity boundary, and
emits a compact evidence document suitable for reports and exhibition clients.
It never reads checkpoint tensors and never promotes incomplete runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "jys.lidmark.multiseed-summary.v1"
METRICS = ("id_ber", "psnr", "landmark_aed", "g_loss")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def validate_selection(document: Mapping[str, Any], source: Path) -> dict[str, Any]:
    if document.get("status") != "selected":
        raise ValueError(f"selection is not complete: {source}")
    if document.get("all_checkpoint_integrity_verified") is not True:
        raise ValueError(f"checkpoint integrity is not verified: {source}")
    selected = document.get("selected")
    if not isinstance(selected, Mapping):
        raise ValueError(f"missing selected checkpoint: {source}")
    val = selected.get("val")
    checkpoint = selected.get("checkpoint")
    if not isinstance(val, Mapping) or not isinstance(checkpoint, Mapping):
        raise ValueError(f"malformed selected checkpoint: {source}")
    if checkpoint.get("verified") is not True:
        raise ValueError(f"selected checkpoint is not verified: {source}")
    for metric in METRICS:
        if not finite_number(val.get(metric)):
            raise ValueError(f"invalid {metric} in {source}")
    epoch = selected.get("epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
        raise ValueError(f"invalid selected epoch in {source}")
    sha256 = checkpoint.get("sha256")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise ValueError(f"invalid checkpoint digest in {source}")
    return {
        "run_id": source.parent.name,
        "epoch": epoch,
        "checkpoint_sha256": sha256,
        "checkpoint_size_bytes": checkpoint.get("size_bytes"),
        "val": {metric: float(val[metric]) for metric in METRICS},
        "selection_sha256": canonical_sha256(document),
    }


def summarize(selections: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not selections:
        raise ValueError("at least one selection is required")
    run_ids = [str(item["run_id"]) for item in selections]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("duplicate run_id")
    metric_summary = {}
    for metric in METRICS:
        values = [float(item["val"][metric]) for item in selections]
        metric_summary[metric] = {
            "mean": statistics.fmean(values),
            "population_stddev": statistics.pstdev(values),
            "min": min(values),
            "max": max(values),
        }
    ordered = sorted(selections, key=lambda item: str(item["run_id"]))
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "completed_run_count": len(ordered),
        "all_selected_checkpoints_verified": True,
        "aggregate": metric_summary,
        "identity_bit_accuracy": {
            "mean": 1.0 - metric_summary["id_ber"]["mean"],
            "zero_ber_run_count": sum(item["val"]["id_ber"] == 0 for item in ordered),
        },
        "runs": ordered,
    }
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def render_markdown(summary: Mapping[str, Any]) -> str:
    aggregate = summary["aggregate"]
    lines = [
        "# LIDMark 多种子训练证据摘要",
        "",
        f"- 完整独立训练：{summary['completed_run_count']} 组",
        f"- 平均身份比特准确率：{summary['identity_bit_accuracy']['mean'] * 100:.6f}%",
        f"- 平均 BER：{aggregate['id_ber']['mean'] * 100:.6f}%",
        f"- 平均 PSNR：{aggregate['psnr']['mean']:.3f} dB",
        f"- 平均关键点 AED：{aggregate['landmark_aed']['mean']:.3f} px",
        f"- 零 BER 训练：{summary['identity_bit_accuracy']['zero_ber_run_count']} 组",
        f"- 证据摘要 SHA-256：`{summary['evidence_sha256']}`",
        "",
        "| 运行 | 入选轮次 | BER | PSNR / dB | AED / px | 权重 SHA-256 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for run in summary["runs"]:
        val = run["val"]
        lines.append(
            f"| {run['run_id']} | {run['epoch']} | {val['id_ber']:.8f} | "
            f"{val['psnr']:.3f} | {val['landmark_aed']:.3f} | "
            f"`{run['checkpoint_sha256']}` |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("selections", nargs="+", type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    records = []
    for path in args.selections:
        document = json.loads(path.read_text(encoding="utf-8"))
        records.append(validate_selection(document, path))
    summary = summarize(records)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
