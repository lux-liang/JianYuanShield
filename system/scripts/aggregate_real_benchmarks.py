from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import PROJECT_ROOT  # noqa: E402


ROOT = PROJECT_ROOT
OUT = ROOT / "system/reports/aggregate_real_benchmarks"
ASSETS = ROOT / "system/assets/aggregate_real_benchmarks"


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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
            "can_defense": "yes" if summary.get("mode") in {"real_checkpoint", "real_checkpoint_small_benchmark", "real_checkpoint_full_benchmark"} and metrics.get("status") in {"complete", "partial"} else "smoke" if summary.get("mode") == "smoke_checkpoint" else "no",
        }
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                row[k] = v
        rows.append(row)
    return rows


def summarize_hidden_from_csv(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    if not records:
        return None
    attacks = {}
    for record in records:
        attacks.setdefault(record.get("attack_type", "unknown"), []).append(record)

    def number(value):
        try:
            if value in ("", None):
                return None
            return float(value)
        except ValueError:
            return None

    attack_summary = {}
    for attack, rows in attacks.items():
        def mean(key):
            values = [number(row.get(key)) for row in rows]
            values = [v for v in values if v is not None]
            return round(sum(values) / len(values), 6) if values else None

        successes = [number(row.get("success")) for row in rows]
        successes = [v for v in successes if v is not None]
        attack_summary[attack] = {
            "status": "partial",
            "count": len(rows),
            "mean_bit_error": mean("bit_error"),
            "mean_bit_accuracy": mean("bit_accuracy"),
            "mean_psnr": mean("psnr"),
            "mean_ssim": mean("ssim"),
            "success_rate": round(sum(successes) / len(successes), 6) if successes else None,
        }
    return {
        "method": "MEA/HiDDeN",
        "mode": "real_checkpoint",
        "data_type": "real_lfw_images",
        "status": "running_partial",
        "evaluated_rows": len(records),
        "num_images": len({row.get("image_id") for row in records if row.get("image_id")}),
        "attacks": attack_summary,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    hidden = load_json(ROOT / "system/reports/hidden_lfw_full_benchmark/summary.json")
    progress = load_json(ROOT / "system/reports/hidden_lfw_full_benchmark/progress.json") or {}
    if progress.get("status") != "complete":
        hidden = summarize_hidden_from_csv(ROOT / "system/reports/hidden_lfw_full_benchmark/results.csv") or hidden
    lidmark = load_json(ROOT / "runs/lidmark_lfw_eval_full/summary.json")
    sepmark = load_json(ROOT / "system/reports/sepmark_lfw_benchmark/summary.json")
    waveguard = load_json(ROOT / "system/reports/waveguard_lfw_benchmark/summary.json")
    waveguard_full = load_json(ROOT / "system/reports/waveguard_lfw_full_benchmark/summary.json")
    waveguard_small = load_json(ROOT / "system/reports/waveguard_lfw_small_benchmark/summary.json")
    waveguard_jpeg_ste = load_json(ROOT / "system/reports/kadnet_lfw_benchmark/../waveguard_lfw_benchmark/summary.json")
    kadnet = load_json(ROOT / "system/reports/kadnet_lfw_benchmark/summary.json")
    rows = []
    rows += flatten_method(hidden, "MEA/HiDDeN", "real_checkpoint", "lfw_full")
    rows += flatten_method(sepmark, "SepMark", "real_checkpoint", "lfw_full")
    rows += flatten_method(waveguard_full, "WaveGuard-full", "real_checkpoint_full_benchmark", "lfw_full")
    rows += flatten_method(waveguard_small, "WaveGuard-small", "real_checkpoint_small_benchmark", "lfw_small")
    rows += flatten_method(lidmark, "LIDMark", "real_checkpoint_3seed", "lfw_512")
    rows += flatten_method(kadnet, "KAD-Net", "real_checkpoint_100ep", "lfw_512")
    if waveguard:
        rows.append({"method": "WaveGuard", "mode": waveguard.get("mode", "real_checkpoint_smoke"), "data_type": "lfw_full", "attack": "checkpoint_load", "status": waveguard.get("status"), "can_defense": "smoke"})
    else:
        rows.append({"method": "WaveGuard", "mode": "real_checkpoint", "data_type": "lfw_full", "attack": "all", "status": "pending", "can_defense": "no"})
    fields = sorted({k for row in rows for k in row.keys()})
    with (OUT / "method_comparison.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "summary.json").write_text(json.dumps({"rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    # degradation curves for real-checkpoint baselines when available
    curves = []
    if sepmark and sepmark.get("attacks"):
        curves.append(("SepMark", sepmark["attacks"]))
    if lidmark and lidmark.get("attacks"):
        curves.append(("LIDMark", lidmark["attacks"]))
    if kadnet and kadnet.get("attacks"):
        curves.append(("KAD-Net", kadnet["attacks"]))
    if curves:
        plt.figure(figsize=(8, 4))
        for label, attack_map in curves:
            attacks = list(attack_map.keys())
            vals = [attack_map[a].get("mean_bit_accuracy", 0) for a in attacks]
            plt.plot(attacks, vals, marker="o", label=label)
        plt.ylim(0, 1)
        plt.ylabel("Mean bit accuracy")
        plt.title("LFW attack robustness — SepMark / LIDMark / KAD-Net")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(ASSETS / "hidden_attack_degradation.png", dpi=160)
    md = ["# 鉴源盾真实评测聚合报告", "", "## 方法状态", ""]
    for row in rows:
        md.append(f"- {row.get('method')} / {row.get('attack')}: {row.get('status')} ({row.get('mode')}, defense={row.get('can_defense')})")
    (OUT / "aggregate_report.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"rows": rows, "assets": str(ASSETS)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
