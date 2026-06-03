from __future__ import annotations

import json
from pathlib import Path

import torch


ROOT = Path("/home/luxliang/work/vpsg_competition_candidates")
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
    (REPORT_DIR / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORT_DIR / "progress.json").write_text(json.dumps({"status": report["status"]}, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

