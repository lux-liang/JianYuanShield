from __future__ import annotations

import json
import sys
from pathlib import Path

import torch


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.run_metadata import build_run_metadata  # noqa: E402
from system.evaluation.runtime import PROJECT_ROOT  # noqa: E402


ROOT = PROJECT_ROOT
REPORT_DIR = ROOT / "system/reports/waveguard_lfw_benchmark"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted((ROOT / "weights/mea/WaveGuard").rglob("*.pth"))
    report = {
        "method": "WaveGuard",
        "mode": "real_checkpoint_smoke",
        "status": "pending",
        "checkpoint_candidates": [str(p) for p in candidates],
        "attempts": [],
        "note": "This first stage checks real checkpoint availability and torch-load integrity. Full model inference is pending explicit WaveGuard model wiring.",
    }
    for path in candidates:
        try:
            obj = torch.load(path, map_location="cpu")
            report["attempts"].append({
                "checkpoint": str(path),
                "load_ok": True,
                "type": type(obj).__name__,
                "num_keys": len(obj) if hasattr(obj, "__len__") else None,
                "first_keys": list(obj.keys())[:10] if isinstance(obj, dict) else [],
            })
            report["status"] = "checkpoint_load_ok"
        except Exception as exc:
            report["attempts"].append({"checkpoint": str(path), "load_ok": False, "error": repr(exc)})
    report["run_metadata"] = build_run_metadata(
        model="WaveGuard",
        checkpoint=candidates[0] if candidates else None,
        seed=2026,
        command=sys.argv,
    )
    (REPORT_DIR / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORT_DIR / "progress.json").write_text(json.dumps({"status": report["status"]}, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
