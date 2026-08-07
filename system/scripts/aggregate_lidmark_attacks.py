#!/usr/bin/env python3
"""Aggregate complete, identity-disjoint LIDMark attack reports across seeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "jys.lidmark.multiseed-attacks.v1"


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def finite(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def parse_report(document: Mapping[str, Any], source: Path) -> dict[str, Any]:
    if document.get("status") != "complete" or document.get("error_rows") != 0:
        raise ValueError(f"report has not completed cleanly: {source}")
    proof = document.get("identity_disjoint_proof")
    audit = document.get("input_integrity_audit")
    if not isinstance(proof, Mapping) or proof.get("identity_disjoint") is not True:
        raise ValueError(f"identity-disjoint proof failed: {source}")
    if not isinstance(audit, Mapping) or audit.get("status") != "verified":
        raise ValueError(f"input integrity audit failed: {source}")
    attacks = document.get("attacks")
    attack_ids = document.get("attack_ids")
    if not isinstance(attacks, Mapping) or not isinstance(attack_ids, list):
        raise ValueError(f"attack results missing: {source}")
    if set(attacks) != set(attack_ids) or len(attack_ids) != 15:
        raise ValueError(f"attack protocol closure failed: {source}")
    parsed = {}
    for attack_id in attack_ids:
        row = attacks[attack_id]
        fields = ("mean_bit_accuracy", "identity_exact_match_rate", "success_rate", "mean_ber")
        if not isinstance(row, Mapping) or any(not finite(row.get(field)) for field in fields):
            raise ValueError(f"invalid attack metrics for {attack_id}: {source}")
        if row.get("status") != "complete" or row.get("error_count") != 0:
            raise ValueError(f"attack did not complete cleanly for {attack_id}: {source}")
        parsed[attack_id] = {field: float(row[field]) for field in fields}
    checkpoint_sha = document.get("checkpoint_sha256")
    if not isinstance(checkpoint_sha, str) or len(checkpoint_sha) != 64:
        raise ValueError(f"checkpoint digest missing: {source}")
    return {
        "run_id": source.parent.name,
        "checkpoint_sha256": checkpoint_sha,
        "sample_count": int(document["sample_count"]),
        "result_rows": int(document["result_rows"]),
        "attack_ids": list(attack_ids),
        "attacks": parsed,
        "summary_sha256": canonical_hash(document),
    }


def summarize(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not reports:
        raise ValueError("at least one report is required")
    ordered = sorted(reports, key=lambda row: str(row["run_id"]))
    attack_ids = ordered[0]["attack_ids"]
    if any(row["attack_ids"] != attack_ids for row in ordered[1:]):
        raise ValueError("attack order differs across reports")
    digests = [row["checkpoint_sha256"] for row in ordered]
    if len(digests) != len(set(digests)):
        raise ValueError("candidate checkpoints must be distinct")
    attacks = {}
    for attack_id in attack_ids:
        metric_summary = {}
        for metric in ("mean_bit_accuracy", "identity_exact_match_rate", "success_rate", "mean_ber"):
            values = [row["attacks"][attack_id][metric] for row in ordered]
            metric_summary[metric] = {
                "mean": statistics.fmean(values),
                "population_stddev": statistics.pstdev(values),
                "min": min(values),
                "max": max(values),
            }
        attacks[attack_id] = metric_summary
    weakest = min(attack_ids, key=lambda name: attacks[name]["success_rate"]["mean"])
    output = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "run_count": len(ordered),
        "sample_count_per_run": ordered[0]["sample_count"],
        "total_result_rows": sum(row["result_rows"] for row in ordered),
        "attack_ids": attack_ids,
        "attacks": attacks,
        "weakest_attack_by_mean_success": weakest,
        "runs": ordered,
    }
    output["evidence_sha256"] = canonical_hash(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summaries", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reports = [parse_report(json.loads(path.read_text()), path) for path in args.summaries]
    summary = summarize(reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
