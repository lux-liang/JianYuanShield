"""
MEA 多水印矩阵——计划/预检入口（不算分）。

⚠️  本脚本仅输出矩阵执行计划（adapter 状态、checkpoint 可用性、blocked cell 统计），
    不执行真实的双嵌水印评测，**不产生任何评分数字**。

正式评分入口（算分）：
    scripts/run_mea_matrix_4x4.py

本脚本适合在正式运行前确认环境（checkpoint 是否就位、adapter 是否 ready）；
如与 run_mea_matrix_4x4.py 有功能重复，以后者为准。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.protocol import load_protocol  # noqa: E402
from system.evaluation.runtime import MODEL_SOURCE_ROOT, REPORT_ROOT, WEIGHT_ROOT  # noqa: E402


MODEL_INVENTORY = {
    "LIDMark": {
        "source": MODEL_SOURCE_ROOT / "LIDMark",
        "checkpoints": [WEIGHT_ROOT / "lidmark" / "smoke_128" / "checkpoints_distortions" / "checkpoint_epoch_2.pth"],
        "adapter_status": "pending_formal_checkpoint",
    },
    "HiDDeN": {
        "source": MODEL_SOURCE_ROOT / "MEA" / "codes" / "HiDDeN",
        "checkpoints": list((WEIGHT_ROOT / "mea" / "HiDDeN").rglob("*.pyt")),
        "adapter_status": "benchmark_script_only",
    },
    "SepMark": {
        "source": MODEL_SOURCE_ROOT / "MEA" / "codes" / "SepMark",
        "checkpoints": list((WEIGHT_ROOT / "mea" / "SepMark").rglob("EC_*.pth")),
        "adapter_status": "benchmark_script_only",
    },
    "WaveGuard": {
        "source": MODEL_SOURCE_ROOT / "MEA" / "codes" / "WaveGuard",
        "checkpoints": list((WEIGHT_ROOT / "mea" / "WaveGuard").rglob("*.pth")),
        "adapter_status": "benchmark_script_only",
    },
    "KAD-Net": {
        "source": MODEL_SOURCE_ROOT / "KAD-Net",
        "checkpoints": list((WEIGHT_ROOT / "kadnet").rglob("*.pth")),
        "adapter_status": "blocked_missing_checkpoint",
    },
}


def main() -> None:
    models = list(load_protocol()["models"])
    inventory = {}
    for name in models:
        item = MODEL_INVENTORY[name]
        inventory[name] = {
            "source": str(item["source"]),
            "source_exists": item["source"].is_dir(),
            "checkpoint_count": len(item["checkpoints"]),
            "checkpoints": [str(path) for path in item["checkpoints"][:10]],
            "adapter_status": item["adapter_status"],
            "runnable": item["adapter_status"] == "ready" and bool(item["checkpoints"]),
        }

    cells = []
    for source in models:
        for attacker in models:
            source_ready = inventory[source]["runnable"]
            attacker_ready = inventory[attacker]["runnable"]
            blockers = []
            if not source_ready:
                blockers.append(f"source:{inventory[source]['adapter_status']}")
            if not attacker_ready:
                blockers.append(f"attacker:{inventory[attacker]['adapter_status']}")
            cells.append({
                "source": source,
                "attacker": attacker,
                "status": "ready" if not blockers else "blocked",
                "blockers": blockers,
                "required_outputs": [
                    "first_message_retention",
                    "second_message_success",
                    "psnr_original_to_first",
                    "psnr_original_to_second",
                    "ssim_original_to_second",
                ],
            })

    payload = {
        "schema_version": "multi-embedding-matrix-plan.v1",
        "status": "ready" if all(cell["status"] == "ready" for cell in cells) else "blocked",
        "models": models,
        "matrix_size": [len(models), len(models)],
        "inventory": inventory,
        "cells": cells,
        "runnable_cells": sum(cell["status"] == "ready" for cell in cells),
        "blocked_cells": sum(cell["status"] == "blocked" for cell in cells),
        "note": "No matrix score is emitted until both adapters load real checkpoints and pass single-embedding controls.",
    }
    output = REPORT_ROOT / "multi_embedding_matrix"
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "matrix_size": payload["matrix_size"],
        "runnable_cells": payload["runnable_cells"],
        "blocked_cells": payload["blocked_cells"],
        "output": str(output / "plan.json"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
