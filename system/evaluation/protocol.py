from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = ROOT / "configs" / "evaluation_protocol.v1.json"
REQUIRED_MODELS = {"LIDMark", "HiDDeN", "SepMark", "WaveGuard", "KAD-Net"}


def protocol_path() -> Path:
    return Path(os.getenv("JYS_EVALUATION_PROTOCOL", DEFAULT_PROTOCOL)).expanduser().resolve()


def validate_protocol(protocol: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if protocol.get("schema_version") != "evaluation_protocol.v1":
        errors.append("schema_version must be evaluation_protocol.v1")
    threshold = protocol.get("success_threshold")
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        errors.append("success_threshold must be between 0 and 1")
    attacks = protocol.get("attacks")
    if not isinstance(attacks, list) or not attacks:
        errors.append("attacks must be a non-empty list")
    else:
        attack_ids = [item.get("id") for item in attacks if isinstance(item, dict)]
        if len(attack_ids) != len(set(attack_ids)):
            errors.append("attack ids must be unique")
        if any(not item for item in attack_ids):
            errors.append("every attack must have an id")
    models = protocol.get("models")
    if not isinstance(models, dict):
        errors.append("models must be an object")
    else:
        missing = sorted(REQUIRED_MODELS - set(models))
        if missing:
            errors.append("missing model registrations: " + ", ".join(missing))
    image = protocol.get("image", {})
    if image.get("canonical_color_space") != "RGB":
        errors.append("canonical_color_space must be RGB")
    return errors


@lru_cache(maxsize=4)
def load_protocol(path: str | None = None) -> dict[str, Any]:
    target = Path(path).resolve() if path else protocol_path()
    protocol = json.loads(target.read_text(encoding="utf-8"))
    errors = validate_protocol(protocol)
    if errors:
        raise ValueError("invalid evaluation protocol: " + "; ".join(errors))
    protocol["_source_path"] = str(target)
    return protocol


def attack_spec(attack_id: str, protocol: dict[str, Any] | None = None) -> dict[str, Any]:
    active = protocol or load_protocol()
    for attack in active["attacks"]:
        if attack["id"] == attack_id:
            return attack
    raise KeyError(f"unknown attack id: {attack_id}")


def model_spec(model_name: str, protocol: dict[str, Any] | None = None) -> dict[str, Any]:
    active = protocol or load_protocol()
    try:
        return active["models"][model_name]
    except KeyError as exc:
        raise KeyError(f"unknown model: {model_name}") from exc


def protocol_summary(protocol: dict[str, Any] | None = None) -> dict[str, Any]:
    active = protocol or load_protocol()
    return {
        "schema_version": active["schema_version"],
        "source_path": active["_source_path"],
        "seed": active["seed"],
        "success_threshold": active["success_threshold"],
        "attack_ids": [item["id"] for item in active["attacks"]],
        "models": {
            name: {
                "native_color_space": spec["native_color_space"],
                "native_range": spec["native_range"],
                "input_size": spec["input_size"],
                "adapter_status": spec["adapter_status"],
            }
            for name, spec in active["models"].items()
        },
        "metric_semantics": {
            "ber": active["message_metrics"]["ber"],
            "accuracy": active["message_metrics"]["accuracy"],
            "success": active["message_metrics"]["success"],
            "watermarked_quality": "original vs watermarked",
            "attacked_quality": "original vs attacked",
        },
    }
