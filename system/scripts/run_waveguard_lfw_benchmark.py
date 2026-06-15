"""
已废弃：此脚本仅做 torch.load 存活检查（status=checkpoint_load_ok），
不执行真实的 encode → attack → decode 推理，数值结果无效。

正式评测入口（真实推理）：
  - 小样本快速验证：system/scripts/run_waveguard_lfw_small_benchmark.py
  - 全量 LFW（13,233 图）：在算力服务器上直接调用
    run_waveguard_lfw_small_benchmark.py --num-images 13233

本文件保留仅供历史参考和 CI 语法检查，请勿将其输出用作正式 benchmark 数值。
若需更新 WaveGuard 全量评测结果，请运行上述正式入口脚本并将 summary.json
写入 system/reports/waveguard_lfw_full_benchmark/。
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import torch


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.run_metadata import build_run_metadata  # noqa: E402
from system.evaluation.runtime import PROJECT_ROOT  # noqa: E402


ROOT = PROJECT_ROOT
REPORT_DIR = ROOT / "system/reports/waveguard_lfw_benchmark"

# 正式推理入口：system/scripts/run_waveguard_lfw_small_benchmark.py
CANONICAL_ENTRY = "system/scripts/run_waveguard_lfw_small_benchmark.py"


def main() -> None:
    warnings.warn(
        f"[已废弃] {__file__} 仅做 checkpoint 存活检查，不产生有效推理结果。"
        f"请使用正式入口：{CANONICAL_ENTRY}",
        DeprecationWarning,
        stacklevel=1,
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted((ROOT / "weights/mea/WaveGuard").rglob("*.pth"))
    report: dict = {
        "method": "WaveGuard",
        "mode": "deprecated_smoke_only",
        "status": "deprecated",
        "deprecated": True,
        "canonical_entry": CANONICAL_ENTRY,
        "warning": (
            "此脚本已废弃，仅做 torch.load 存活检查，不执行真实推理。"
            f"正式评测入口：{CANONICAL_ENTRY}"
        ),
        "checkpoint_candidates": [str(p) for p in candidates],
        "attempts": [],
    }

    for path in candidates:
        try:
            obj = torch.load(path, map_location="cpu", weights_only=True)
            report["attempts"].append({
                "checkpoint": str(path),
                "load_ok": True,
                "type": type(obj).__name__,
                "num_keys": len(obj) if hasattr(obj, "__len__") else None,
                "first_keys": list(obj.keys())[:10] if isinstance(obj, dict) else [],
            })
        except Exception as exc:
            report["attempts"].append({"checkpoint": str(path), "load_ok": False, "error": repr(exc)})

    report["run_metadata"] = build_run_metadata(
        model="WaveGuard",
        checkpoint=candidates[0] if candidates else None,
        seed=2026,
        command=sys.argv,
    )
    (REPORT_DIR / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (REPORT_DIR / "progress.json").write_text(
        json.dumps({"status": "deprecated", "canonical_entry": CANONICAL_ENTRY}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
