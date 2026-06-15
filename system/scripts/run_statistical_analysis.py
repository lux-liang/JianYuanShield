from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import PROJECT_ROOT, REPORT_ROOT  # noqa: E402
from system.evaluation.statistics import (  # noqa: E402
    bootstrap_ci,
    seed_level_summary,
)


# 统计口径说明（P1-6/P1-7 修正）：
# 1) 每个模型上报的「量」语义不同，必须单独成表、禁止互相 paired 比较：
#      - HiDDeN / KAD-Net    : message_bit_acc（30-bit 消息解码逐位准确率）
#      - SepMark             : message_bit_acc（128-bit，RF decoder 为主）
#      - WaveGuard           : detector_bit_acc（检测器存在性，非溯源 tracer）
#      - LIDMark             : id_bit_acc（16-bit ID；注：landmark 定位成功率
#                              是另一指标，不在此处当 bit-acc 报）
#    landmark_success_rate / id_bit_acc / detector_bit_acc / message_bit_acc
#    是不同量，跨指标的 "99.98% > 91.2%" 式比较与跨指标 paired 检验一律禁止。
# 2) 不确定性分两类、分开报，不混：
#      - within-seed image-sampling CI：固定单 seed，bootstrap 量化图像采样噪声；
#      - between-seed CI：用 n 个 seed-level 均值（本项目 LIDMark n=3，仅供参考）。
#    旧实现把 3 seed × 512 图拍平成 1536 个「独立样本」做 bootstrap 属
#    pseudoreplication，会严重低估区间（[99.94%,100%]），此处已废弃该做法。

# 每个来源标注其真实指标名（metric），下游分指标成表、不跨指标比较。
SOURCES = {
    "HiDDeN": (
        REPORT_ROOT / "hidden_lfw_full_benchmark" / "results.csv",
        ("bit_accuracy",),
        "message_bit_acc",
    ),
    "SepMark": (
        REPORT_ROOT / "sepmark_lfw_benchmark" / "results.csv",
        ("bit_accuracy_rf", "bit_accuracy_c"),  # RF decoder is primary metric
        "message_bit_acc",
    ),
    "WaveGuard": (
        REPORT_ROOT / "waveguard_lfw_full_benchmark" / "results.csv",
        ("bit_accuracy_detector", "bit_accuracy"),
        "detector_bit_acc",  # 检测器存在性，非溯源 tracer
    ),
}




LIDMARK_SEEDS = [
    Path("/data1/luxliang/work/vpsg_competition_candidates/runs/lidmark")
    / f"lidmark_lfw_eval_seed{seed}/results.csv"
    for seed in ("20260603", "20260604", "20260605")
]


def load_lidmark_per_seed(paths):
    """加载 LIDMark 3-seed CSV，**按 seed 分桶**保留结构（不拍平）。

    返回 list[dict[(image_id, attack)->id_bit_acc]]，每个元素对应一个独立
    训练 seed。保留 per-seed 结构是为了正确区分 between-seed 与 within-seed
    两类不确定性（见文件头说明），不再把 3×512 拍平成 1536 个伪独立样本。
    id_ber -> id_bit_acc(=1-id_ber)。
    """
    import math as _math
    per_seed = []
    for path in paths:
        if not path.is_file():
            print(f"  [warn] LIDMark seed path not found: {path}", file=sys.stderr)
            continue
        seed_values = {}
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
                    seed_values[(index, attack)] = value
        if seed_values:
            per_seed.append(seed_values)
    return per_seed

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
    # ---- 单 seed 来源：每个 method 携带其真实指标名（metric），分指标成表 ----
    # data[name] = {"metric": <真实指标名>, "values": {(image_id, attack): val}}
    data: dict[str, dict] = {}
    for name, (path, candidates, metric) in SOURCES.items():
        values = load_source(path, candidates)
        if values:
            data[name] = {"metric": metric, "values": values}
    kadnet_values = load_kadnet_source(KADNET_PATH)
    if kadnet_values:
        data["KAD-Net"] = {"metric": "message_bit_acc", "values": kadnet_values}

    # ---- LIDMark：保留 per-seed 结构，区分 between-seed 与 within-seed ----
    lidmark_per_seed = load_lidmark_per_seed(LIDMARK_SEEDS)

    attacks = sorted(
        {attack for entry in data.values() for _, attack in entry["values"]}
        | {attack for seed in lidmark_per_seed for _, attack in seed}
    )

    # within-seed image-sampling CI：固定单 seed，bootstrap 量化图像采样噪声。
    # 不同 method 的 metric 语义不同（见文件头），各自单独成行，禁止互相比较。
    image_sampling = []
    for method, entry in data.items():
        values = entry["values"]
        for attack in attacks:
            sample = [v for (image_id, attack_id), v in values.items() if attack_id == attack]
            if not sample:
                continue
            interval = bootstrap_ci(sample)
            image_sampling.append({
                "method": method,
                "metric": entry["metric"],
                "attack": attack,
                "uncertainty": "within_seed_image_sampling",
                "n_images": interval.samples,
                "mean": interval.mean,
                "ci95_low": interval.low,
                "ci95_high": interval.high,
            })

    # LIDMark id_bit_acc 的两类不确定性，分开报：
    #   between-seed：用 n 个 seed-level 图像均值（n=3，仅供参考）；
    #   within-seed ：固定第一个 seed 做图像采样 bootstrap。
    between_seed = []
    for attack in attacks:
        seed_means = []
        for seed in lidmark_per_seed:
            per_image = [v for (image_id, attack_id), v in seed.items() if attack_id == attack]
            if per_image:
                seed_means.append(sum(per_image) / len(per_image))
        if not seed_means:
            continue
        summary = seed_level_summary(seed_means)
        between_seed.append({
            "method": "LIDMark",
            "metric": "id_bit_acc",
            "attack": attack,
            "uncertainty": "between_seed",
            "n_seeds": summary.n_seeds,
            "seed_means": seed_means,
            "mean": summary.mean,
            "std": summary.std,
            "ci95_low": summary.low,
            "ci95_high": summary.high,
            "note": "n=3，t-CI 仅供参考；非严格统计结论",
        })
        # within-seed：仅取第一个 seed，避免把跨 seed 拍平成伪独立样本。
        first_seed = lidmark_per_seed[0]
        per_image = [v for (image_id, attack_id), v in first_seed.items() if attack_id == attack]
        if len(per_image) >= 2:
            interval = bootstrap_ci(per_image)
            image_sampling.append({
                "method": "LIDMark",
                "metric": "id_bit_acc",
                "attack": attack,
                "uncertainty": "within_seed_image_sampling",
                "seed": "seed0",
                "n_images": interval.samples,
                "mean": interval.mean,
                "ci95_low": interval.low,
                "ci95_high": interval.high,
            })

    payload = {
        "schema_version": "statistical-analysis.v2",
        "status": "complete",
        # 指标语义不同，按 method 标注真实指标名；不存在统一的单一 metric。
        "metrics_by_method": {
            **{name: entry["metric"] for name, entry in data.items()},
            **({"LIDMark": "id_bit_acc"} if lidmark_per_seed else {}),
        },
        "seed_count": {
            **{name: 1 for name in data},  # 单 seed 来源
            **({"LIDMark": len(lidmark_per_seed)} if lidmark_per_seed else {}),
        },
        "seed_status": "lidmark_between_seed_available" if lidmark_per_seed else "single_seed_only",
        "bootstrap_resamples": 5000,
        "project_root": str(PROJECT_ROOT),
        "sources": {
            **{name: {"path": str(path), "metric": data[name]["metric"],
                      "rows": len(data[name]["values"])}
               for name, (path, _, _) in SOURCES.items() if name in data},
            **({"LIDMark": {"paths": [str(p) for p in LIDMARK_SEEDS],
                            "metric": "id_bit_acc",
                            "seeds": len(lidmark_per_seed),
                            "rows": sum(len(s) for s in lidmark_per_seed)}}
               if lidmark_per_seed else {}),
            **({"KAD-Net": {"path": str(KADNET_PATH), "metric": "message_bit_acc",
                            "rows": len(kadnet_values)}}
               if kadnet_values else {}),
        },
        # within-seed（图像采样）与 between-seed 两张表分开，不混。
        "image_sampling_ci": image_sampling,
        "between_seed_ci": between_seed,
        # 跨指标配对检验已禁用（P1-7）：landmark_success_rate / id_bit_acc /
        # detector_bit_acc / message_bit_acc 是不同量，互相 paired 检验无意义；
        # paired 检验仅允许「同一指标、同一攻击」内部进行，当前各 method 各自
        # 为单一指标/单 seed，不存在合法的跨 method 配对，故为空。
        "comparisons": [],
        "comparisons_note": (
            "Cross-metric paired tests disabled: landmark_success_rate / id_bit_acc / "
            "detector_bit_acc / message_bit_acc are different quantities and must not be "
            "paired or compared across methods. Paired tests are only valid within the "
            "same metric and same attack."
        ),
        "limitations": [
            "LIDMark id_bit_acc: 3 independently trained seeds (20260603/04/05); "
            "between-seed interval uses n=3 seed-level means (Student-t) and is indicative only.",
            "within-seed image-sampling CI fixes a single seed and quantifies image-sampling "
            "noise only; it is NOT a between-seed (model retraining) variance.",
            "HiDDeN/SepMark/WaveGuard/KAD-Net: single seed — only within-seed image-sampling CI; "
            "between-seed variance requires additional reruns.",
            "Each method reports a distinct metric (see metrics_by_method); cross-metric "
            "comparisons (e.g. '99.98% > 91.2%') are invalid and intentionally omitted.",
        ],
    }
    output = REPORT_ROOT / "statistical_analysis"
    output.mkdir(parents=True, exist_ok=True)
    (output / "analysis.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # within-seed 图像采样 CI 表（含 metric 列，分指标可读）。
    with (output / "image_sampling_ci.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["method", "metric", "attack", "uncertainty", "seed", "n_images",
                  "mean", "ci95_low", "ci95_high"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(image_sampling)
    # between-seed CI 表（仅 LIDMark，n=3 仅供参考）。
    with (output / "between_seed_ci.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["method", "metric", "attack", "uncertainty", "n_seeds",
                  "mean", "std", "ci95_low", "ci95_high", "note"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(between_seed)
    print(json.dumps({
        "status": payload["status"],
        "image_sampling_ci": len(image_sampling),
        "between_seed_ci": len(between_seed),
        "seed_status": payload["seed_status"],
        "output": str(output),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
