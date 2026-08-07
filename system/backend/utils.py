from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid

from .config import ASSETS, ROOT
from .logging_config import logger


EPHEMERAL_ARTIFACT_MARKER = ".jys-ephemeral-v1"
_EPHEMERAL_ARTIFACT_MARKER_CONTENT = b"jianyuanshield-ephemeral-artifact-v1\n"


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Durably replace a generated artifact without exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        if mode is not None:
            os.fchmod(descriptor, mode)
        handle = os.fdopen(descriptor, "wb")
        descriptor = -1
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_bytes(
        path,
        (
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8"),
    )


def create_ephemeral_artifact_directory(root: Path) -> tuple[str, Path]:
    """Create a collision-safe generated-artifact directory with a deletion marker."""

    root.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        task_id = uuid.uuid4().hex[:12]
        path = root / task_id
        try:
            path.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileExistsError:
            continue
        try:
            atomic_write_bytes(
                path / EPHEMERAL_ARTIFACT_MARKER,
                _EPHEMERAL_ARTIFACT_MARKER_CONTENT,
                mode=0o600,
            )
        except Exception:
            shutil.rmtree(path, ignore_errors=True)
            raise
        return task_id, path
    raise RuntimeError("unable to allocate a unique artifact directory")


def is_ephemeral_artifact_directory(path: Path) -> bool:
    marker = path / EPHEMERAL_ARTIFACT_MARKER
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        if marker.stat().st_size != len(_EPHEMERAL_ARTIFACT_MARKER_CONTENT):
            return False
        return marker.read_bytes() == _EPHEMERAL_ARTIFACT_MARKER_CONTENT
    except OSError:
        return False


def artifact_url(path: Path) -> str:
    resolved_assets = ASSETS.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_assets)
    except ValueError as exc:
        raise ValueError("artifact path is outside the configured asset root") from exc
    return f"/api/artifacts/{relative.as_posix()}"


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except Exception as exc:
        logger.warning(
            "failed to read json path=%s error=%s",
            safe_relative(path),
            exc.__class__.__name__,
        )
        return {"status": "read_failed", "path": safe_relative(path), "error": exc.__class__.__name__}


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
        logger.warning(
            "failed to read csv path=%s error=%s",
            safe_relative(path),
            exc.__class__.__name__,
        )
    return records


def numeric(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def count_files(
    path: Path,
    suffixes: set[str] | None = None,
    *,
    root: Path | None = None,
) -> int:
    resolved_root: Path | None = None
    if root is not None:
        try:
            resolved_root = root.resolve()
            path.resolve().relative_to(resolved_root)
        except (OSError, RuntimeError, ValueError):
            return 0

    def eligible(item: Path) -> bool:
        if resolved_root is not None:
            try:
                item.resolve().relative_to(resolved_root)
            except (OSError, RuntimeError, ValueError):
                return False
        return suffixes is None or item.suffix.lower() in suffixes

    try:
        if not path.exists():
            return 0
        if path.is_file():
            return int(eligible(path))
        return sum(
            1
            for item in path.rglob("*")
            if item.is_file() and eligible(item)
        )
    except (OSError, RuntimeError) as exc:
        logger.warning("failed to count files path=%s error=%s", safe_relative(path), exc.__class__.__name__)
        return 0


def safe_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return path.name or "external"


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
        logger.warning(
            "failed to count csv rows path=%s error=%s",
            safe_relative(path),
            exc.__class__.__name__,
        )
    return count


def path_status(path: Path) -> dict[str, Any]:
    return {
        "path": safe_relative(path),
        "exists": path.exists(),
        "files": count_files(path) if path.is_dir() else int(path.exists()),
    }


def asset_if_exists(relative: str) -> str | None:
    from .security import resolve_path_within

    path = resolve_path_within(ASSETS, relative)
    if path is None or not path.is_file():
        return None
    return artifact_url(path)
