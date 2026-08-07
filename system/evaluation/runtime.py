from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(os.getenv("JYS_PROJECT_ROOT", Path(__file__).resolve().parents[2])).expanduser().resolve()
MODEL_SOURCE_ROOT = Path(os.getenv("JYS_MODEL_SOURCE_ROOT", PROJECT_ROOT)).expanduser().resolve()
DATA_ROOT = Path(os.getenv("JYS_DATA_ROOT", PROJECT_ROOT / "datasets")).expanduser().resolve()
WEIGHT_ROOT = Path(os.getenv("JYS_WEIGHT_ROOT", PROJECT_ROOT / "weights")).expanduser().resolve()
REPORT_ROOT = Path(os.getenv("JYS_REPORT_ROOT", PROJECT_ROOT / "system" / "reports")).expanduser().resolve()
ASSET_ROOT = Path(os.getenv("JYS_ASSET_ROOT", PROJECT_ROOT / "system" / "assets")).expanduser().resolve()


def logical_path(path: str | Path) -> str:
    """Return a stable deployment-relative path without exposing a host root."""
    resolved = Path(path).expanduser().resolve()
    try:
        relative = resolved.relative_to(PROJECT_ROOT)
        return relative.as_posix() or "."
    except ValueError:
        pass
    for label, root in (
        ("data", DATA_ROOT),
        ("weights", WEIGHT_ROOT),
        ("reports", REPORT_ROOT),
        ("assets", ASSET_ROOT),
        ("model-sources", MODEL_SOURCE_ROOT),
    ):
        try:
            relative = resolved.relative_to(root)
            suffix = relative.as_posix()
            return f"{label}/{suffix}" if suffix else label
        except ValueError:
            continue
    return resolved.name


def resolve_logical_path(reference: str | Path) -> Path | None:
    """Resolve a manifest path inside an approved runtime root.

    Absolute paths and traversal are rejected so repository artifacts remain
    portable and cannot make a verifier read arbitrary host files.
    """
    raw = Path(reference)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    parts = raw.parts
    roots = {
        "data": DATA_ROOT,
        "weights": WEIGHT_ROOT,
        "reports": REPORT_ROOT,
        "assets": ASSET_ROOT,
        "model-sources": MODEL_SOURCE_ROOT,
    }
    if parts and parts[0] in roots:
        root = roots[parts[0]]
        candidate = root.joinpath(*parts[1:]).resolve()
    else:
        root = PROJECT_ROOT
        candidate = root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate
