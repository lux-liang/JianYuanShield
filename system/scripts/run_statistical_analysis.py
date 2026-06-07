from __future__ import annotations

import csv
import json
import math
import sys
from itertools import combinations
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import PROJECT_ROOT, REPORT_ROOT  # noqa: E402
from system.evaluation.statistics import (  # noqa: E402
    bootstrap_ci,
    holm_adjust,
    paired_bootstrap_difference,
    paired_effect_size,
    paired_sign_flip_test,
)


SOURCES = {
    "HiDDeN": (
        REPORT_ROOT / "hidden_lfw_full_benchmark" / "results.csv",
        ("bit_accuracy",),
    ),
    "SepMark": (
        REPORT_ROOT / "sepmark_lfw_benchmark" / "results.csv",
        ("bit_accuracy_rf", "bit_accuracy_c"),  # RF decoder is primary metric
    ),
    "WaveGuard": (
        REPORT_ROOT / "waveguard_lfw_full_benchmark" / "results.csv",
        ("bit_accuracy_detector", "bit_accuracy"),
    ),
}




LIDMARK_SEEDS = [
    Path("/data1/luxliang/work/vpsg_competition_candidates/runs/lidmark")
    / f"lidmark_lfw_eval_seed{seed}/results.csv"
    for seed in ("20260603", "20260604", "20260605")
]


def load_lidmark_multi_seed(paths):
    """Load LIDMark 3-seed CSVs; converts id_ber -> bit_accuracy."""
    import math as _math
    values = {}
    for seed_idx, path in enumerate(paths):
        if not path.is_file():
            print(f"  [warn] LIDMark seed path not found: {path}", file=sys.stderr)
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                index = row.get("index")
                attack = row.get("attack_type")
                if index is None or not attack:
                    continue
                raw = row.get("id_ber")
                try:
                    value = 1.0 - float(raw)
                except (TypeError, ValueError):
                    continue
                if _math.isfinite(value):
                    values[(f"s{seed_idx}_{index}", attack)] = value
    return values

def load_source(path: Path, metric_candidates: tuple[str, ...]) -> dict[tuple[str, str], float]:
    if not path.is_file():
        return {}
    values: dict[tuple[str, str], float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            image_id = row.get("image_id")
            attack = row.get("attack_type")
            if not image_id or not attack:
                continue
            raw = next((row.get(name) for name in metric_candidates if row.get(name) not in ("", None)), None)
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values[(image_id, attack)] = value
    return values



KADNET_PATH = (
    Path("/data1/luxliang/work/vpsg_competition_candidates")
    / "runs/kadnet_lfw_eval_full/results.csv"
)


def load_kadnet_source(path: Path) -> dict:
    """Load KAD-Net CSV (columns: img, attack, bit_accuracy)."""
    import math as _math
    values = {}
    if not path.is_file():
        return values
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            image_id = row.get("img")
            attack = row.get("attack")
            if not image_id or not attack:
                continue
            raw = row.get("bit_accuracy")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if _math.isfinite(value):
                values[(image_id, attack)] = value
    return values

def main() -> None:
    data = {name: load_source(path, candidates) for name, (path, candidates) in SOURCES.items()}
    lidmark_data = load_lidmark_multi_seed(LIDMARK_SEEDS)
    if lidmark_data:
        data["LIDMark"] = lidmark_data
    kadnet_data = load_kadnet_source(KADNET_PATH)
    if kadnet_data:
        data["KAD-Net"] = kadnet_data
    attacks = sorted({attack for values in data.values() for _, attack in values})
    summaries = []
    for method, values in data.items():
        for attack in attacks:
            sample = [value for (image_id, attack_id), value in values.items() if attack_id == attack]
            if not sample:
                continue
            interval = bootstrap_ci(sample)
            summaries.append({
                "method": method,
                "attack": attack,
                "count": interval.samples,
                "mean": interval.mean,
                "ci95_low": interval.low,
                "ci95_high": interval.high,
            })

    comparisons = []
    for attack in attacks:
        for first_name, second_name in combinations(data, 2):
            first = data[first_name]
            second = data[second_name]
            common = sorted(
                key for key in first.keys() & second.keys()
                if key[1] == attack
            )
            if len(common) < 2:
                continue
            first_values = [first[key] for key in common]
            second_values = [second[key] for key in common]
            interval = paired_bootstrap_difference(first_values, second_values)
            comparisons.append({
                "attack": attack,
                "first": first_name,
                "second": second_name,
                "pairs": len(common),
                "mean_difference": interval.mean,
                "ci95_low": interval.low,
                "ci95_high": interval.high,
                "effect_size_dz": paired_effect_size(first_values, second_values),
                "p_value": paired_sign_flip_test(first_values, second_values),
            })
    adjusted = holm_adjust(item["p_value"] for item in comparisons)
    for item, value in zip(comparisons, adjusted):
        item["p_value_holm"] = value
        item["significant_0_05"] = value < 0.05

    payload = {
        "schema_version": "statistical-analysis.v1",
        "status": "complete",
        "metric": "bit_accuracy",
        "seed_count": {name: 3 if name == "LIDMark" else 1 for name in data},  # KAD-Net: 1 seed (100ep checkpoint)
        "seed_status": "multi_seed_lidmark_available",
        "bootstrap_resamples": 5000,
        "sign_flip_permutations": 20000,
        "project_root": str(PROJECT_ROOT),
        "sources": {
            **{name: {"path": str(path), "rows": len(data[name])}
               for name, (path, _) in SOURCES.items() if name in data},
            **({"LIDMark": {"paths": [str(p) for p in LIDMARK_SEEDS],
                            "seeds": sum(1 for p in LIDMARK_SEEDS if p.is_file()),
                            "rows": len(data["LIDMark"])}}
               if "LIDMark" in data else {}),
            **({"KAD-Net": {"path": str(KADNET_PATH), "rows": len(data["KAD-Net"])}}
               if "KAD-Net" in data else {}),
        },
        "summaries": summaries,
        "comparisons": comparisons,
        "limitations": [
            "LIDMark: 3 independently trained seeds (20260603/04/05) — between-seed variance available.",
            "HiDDeN/SepMark/WaveGuard: single seed — intervals quantify image-sampling uncertainty only.",
            "For between-seed variance claims on those models, additional reruns are required.",
        ],
    }
    output = REPORT_ROOT / "statistical_analysis"
    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with (output / "comparisons.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = list(comparisons[0]) if comparisons else ["attack", "first", "second"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(comparisons)
    print(json.dumps({
        "status": payload["status"],
        "summaries": len(summaries),
        "comparisons": len(comparisons),
        "seed_status": payload["seed_status"],
        "output": str(output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
