from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import MODEL_SOURCE_ROOT, REPORT_ROOT, WEIGHT_ROOT  # noqa: E402


def main() -> None:
    source = MODEL_SOURCE_ROOT / "KAD-Net"
    requirements = source / "requirements.yml"
    test_script = source / "test.py"
    requirement_text = requirements.read_text(encoding="utf-8") if requirements.is_file() else ""
    test_text = test_script.read_text(encoding="utf-8") if test_script.is_file() else ""
    checkpoints = sorted((WEIGHT_ROOT / "kadnet").rglob("*.pth"))
    hardcoded_paths = sorted(set(re.findall(r'''/(?:root|home|data1)/[^\s'"]+''', test_text)))
    required_modules = ["torch", "torchvision", "kornia", "lpips", "einops", "yaml", "easydict"]
    modules = {name: importlib.util.find_spec(name) is not None for name in required_modules}
    blockers = []
    if not source.is_dir():
        blockers.append("source_missing")
    if not checkpoints:
        blockers.append("checkpoint_missing")
    if hardcoded_paths:
        blockers.append("test_script_hardcoded_paths")
    if "torch==1.11.0+cu113" in requirement_text:
        blockers.append("legacy_torch_cuda_environment")
    missing_modules = [name for name, present in modules.items() if not present]
    if missing_modules:
        blockers.append("missing_runtime_modules:" + ",".join(missing_modules))

    payload = {
        "schema_version": "kadnet-integration-audit.v1",
        "status": "blocked" if blockers else "ready_for_smoke",
        "source": str(source),
        "source_exists": source.is_dir(),
        "checkpoint_root": str(WEIGHT_ROOT / "kadnet"),
        "checkpoint_count": len(checkpoints),
        "checkpoints": [str(path) for path in checkpoints],
        "declared_environment": {
            "python": "3.8.20" if "python=3.8.20" in requirement_text else None,
            "torch": "1.11.0+cu113" if "torch==1.11.0+cu113" in requirement_text else None,
            "torchvision": "0.12.0+cu113" if "torchvision==0.12.0+cu113" in requirement_text else None,
        },
        "current_modules": modules,
        "hardcoded_paths": hardcoded_paths,
        "blockers": blockers,
        "required_next_actions": [
            "Obtain the team-approved ST and FD pretrained checkpoints with hashes.",
            "Replace hardcoded config/result/checkpoint paths with CLI arguments.",
            "Validate model construction and strict checkpoint coverage in an isolated compatibility environment.",
            "Run 16-image negative-control smoke before adding KAD-Net to ranking tables.",
        ],
    }
    output = REPORT_ROOT / "kadnet_integration"
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
