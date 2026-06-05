from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .config import ASSETS, ROOT
from .logging_config import logger


def artifact_url(path: Path) -> str:
    return f"/artifacts/{path.relative_to(ASSETS).as_posix()}"


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to read json path=%s error=%s", path, exc)
        return {"status": "read_failed", "path": str(path), "error": str(exc)}


def read_csv_records(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for idx, row in enumerate(csv.DictReader(handle)):
                if idx >= limit:
                    break
                records.append(dict(row))
    except Exception as exc:
        logger.warning("failed to read csv path=%s error=%s", path, exc)
    return records


def numeric(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def count_files(path: Path, suffixes: set[str] | None = None) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return int(suffixes is None or path.suffix.lower() in suffixes)
    return sum(1 for item in path.rglob("*") if item.is_file() and (suffixes is None or item.suffix.lower() in suffixes))


def safe_relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def csv_row_count(path: Path, limit: int = 1_000_000) -> int:
    if not path.exists():
        return 0
    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            next(handle, None)
            for count, _ in enumerate(handle, start=1):
                if count >= limit:
                    break
    except Exception as exc:
        logger.warning("failed to count csv rows path=%s error=%s", path, exc)
    return count


def path_status(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "files": count_files(path) if path.is_dir() else int(path.exists()),
    }


def asset_if_exists(relative: str) -> str | None:
    path = ASSETS / relative
    return f"/artifacts/{relative}" if path.exists() else None
