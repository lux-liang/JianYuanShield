#!/usr/bin/env python3
"""Build a reviewable source package for the JianYuanShield V1.0 filing.

The default package deliberately contains only readable first-party-facing
source, configuration, tests and documentation.  It excludes mounted upstream
model repositories, third-party build wrappers, private deployment topology,
presentation-only generated outputs, checkpoints, datasets, runtime state,
virtual environments, logs, backups, secrets and common image/audio/video
formats.  The filtering is conservative because an automatic tool cannot
determine portrait rights.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from typing import Iterable
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOFTWARE_NAME = "鉴源盾内容来源可信取证系统 V1.0"
SOFTWARE_VERSION = "V1.0"
ARCHIVE_ROOT = "JianYuanShield-V1.0"
DEFAULT_OUTPUT = ROOT / "dist/software-copyright/JianYuanShield-V1.0-source.zip"
MAX_TEXT_FILE_BYTES = 4 * 1024 * 1024

REQUIRED_SOFTWARE_COPYRIGHT_DOCS = (
    "docs/software-copyright/软件说明书.md",
    "docs/software-copyright/用户手册.md",
    "docs/software-copyright/设计说明书.md",
    "docs/software-copyright/申请信息清单.md",
    "docs/software-copyright/原创与第三方边界说明.md",
)
REQUIRED_ROOT_FILES = (
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "ARCHITECTURE.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "COPYRIGHT",
)
REQUIRED_FILES = REQUIRED_ROOT_FILES + REQUIRED_SOFTWARE_COPYRIGHT_DOCS

THIRD_PARTY_MODEL_ROOTS = frozenset(
    {
        "kad-net",
        "kad_net",
        "lidmark",
        "mea",
        "sepmark",
        "waveguard",
        "simswap",
        "model-sources",
        "model_sources",
    }
)
TOP_LEVEL_RUNTIME_ROOTS = frozenset(
    {"assets", "data", "datasets", "reports", "runs", "weights"}
)
TOP_LEVEL_PRIVATE_DEPLOYMENT_ROOTS = frozenset({"deployment"})
THIRD_PARTY_BUILD_TOOL_PREFIXES = (("android", "gradle", "wrapper"),)
THIRD_PARTY_BUILD_TOOL_FILES = frozenset(
    {
        ("android", "gradlew"),
        ("android", "gradlew.bat"),
    }
)
PRESENTATION_GENERATED_FILES = frozenset(
    {
        (
            "system",
            "frontend",
            "assets",
            "heatmap_watermark_recovery_editable.svg",
        ),
        (
            "system",
            "frontend",
            "assets",
            "heatmap_watermark_recovery_manifest.json",
        ),
    }
)
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".cache",
        ".gradle",
        ".idea",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".venvs",
        ".vscode",
        "__pycache__",
        "backup",
        "backups",
        "build",
        "captures",
        "dist",
        "env",
        "htmlcov",
        "log",
        "logs",
        "node_modules",
        "out",
        "secrets",
        "target",
        "tmp",
        "temp",
        "vendor",
        "venv",
        "venvs",
        ".cxx",
        ".externalnativebuild",
    }
)
RUNTIME_PREFIXES = (
    ("system", "assets"),
    ("system", "data"),
    ("system", "reports"),
)
PERSONAL_MEDIA_PREFIXES = (
    ("miniprogram", "assets", "faces"),
    ("system", "frontend", "assets", "reference"),
)
BACKUP_COMPONENT_RE = re.compile(r"(?:^|[._-])backup(?:[._-]|$)", re.IGNORECASE)
SENSITIVE_FILE_RE = re.compile(
    r"(?:^|[._-])(?:credentials?|password|private[-_]?key|secrets?|tokens?)(?:[._-]|$)",
    re.IGNORECASE,
)

MEDIA_SUFFIXES = frozenset(
    {
        ".apng",
        ".avif",
        ".bmp",
        ".flac",
        ".gif",
        ".heic",
        ".heif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".m4a",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".png",
        ".tif",
        ".tiff",
        ".wav",
        ".webm",
        ".webp",
    }
)
MODEL_AND_DATA_SUFFIXES = frozenset(
    {
        ".arrow",
        ".bin",
        ".ckpt",
        ".csv",
        ".db",
        ".feather",
        ".h5",
        ".hdf5",
        ".jsonl",
        ".mdb",
        ".npy",
        ".npz",
        ".onnx",
        ".parquet",
        ".pt",
        ".pth",
        ".pyt",
        ".safetensors",
        ".sqlite",
        ".sqlite3",
        ".tfrecord",
        ".tsv",
    }
)
ARCHIVE_AND_BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".a",
        ".aab",
        ".apk",
        ".class",
        ".dll",
        ".dylib",
        ".exe",
        ".gz",
        ".jar",
        ".msi",
        ".o",
        ".obj",
        ".pdf",
        ".rar",
        ".so",
        ".tar",
        ".tgz",
        ".xz",
        ".zip",
    }
)
SECRET_SUFFIXES = frozenset(
    {".der", ".jks", ".key", ".keystore", ".p12", ".pfx", ".pem", ".pkcs12"}
)
EXCLUDED_EXACT_FILES = frozenset(
    {
        # In a linked Git worktree, .git is a text file containing an absolute
        # administrative path rather than a directory. It is local VCS state,
        # not source material, and must never enter a filing package.
        ".git",
        ".deployed_commit",
        ".npmrc",
        ".pypirc",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "local.properties",
    }
)
PRIVATE_KEY_RE = re.compile(
    rb"(?m)^\s*-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s*$"
)
PERSONAL_ABSOLUTE_PATH_RE = re.compile(
    rb"(?i)(?:"
    rb"[a-z]:[\\/]+users[\\/]+[a-z0-9._ -]+[\\/]+"
    rb"(?:desktop|documents|downloads|projects?|workspaces?)[\\/]"
    rb"|/(?:home|users)/[a-z0-9._-]+/"
    rb"(?:desktop|documents|downloads|projects?|workspaces?)/"
    rb"|/root/[a-z0-9._-]+/(?:desktop|documents|downloads|projects?|workspaces?)/"
    rb")"
)

SOURCE_SUFFIX_LABELS = {
    ".bat": "Windows 脚本",
    ".c": "C 源码",
    ".cc": "C++ 源码",
    ".cmd": "Windows 脚本",
    ".cpp": "C++ 源码",
    ".css": "CSS 样式",
    ".gradle": "Gradle 构建脚本",
    ".h": "C/C++ 头文件",
    ".hpp": "C++ 头文件",
    ".html": "HTML 页面",
    ".java": "Java 源码",
    ".js": "JavaScript 源码",
    ".kt": "Kotlin 源码",
    ".kts": "Kotlin/Gradle 脚本",
    ".mjs": "JavaScript 源码",
    ".ps1": "PowerShell 脚本",
    ".py": "Python 源码",
    ".pyi": "Python 类型源码",
    ".scss": "SCSS 样式",
    ".sh": "Shell 脚本",
    ".sql": "SQL 源码",
    ".svg": "SVG 矢量源码",
    ".ts": "TypeScript 源码",
    ".tsx": "TypeScript/JSX 源码",
    ".wxml": "微信小程序模板",
    ".wxs": "微信小程序脚本",
    ".wxss": "微信小程序样式",
}
CONFIG_SUFFIXES = frozenset(
    {
        ".cfg",
        ".conf",
        ".dockerignore",
        ".editorconfig",
        ".gitignore",
        ".ini",
        ".json",
        ".lock",
        ".properties",
        ".toml",
        ".xml",
        ".yaml",
        ".yml",
    }
)


class PackageError(RuntimeError):
    """Raised when the source snapshot is unsafe or incomplete."""


@dataclass(frozen=True)
class SourceEntry:
    relative_path: str
    source_path: Path
    category: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Collection:
    entries: tuple[SourceEntry, ...]
    exclusions: dict[str, int]


def _has_prefix(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    return len(parts) >= len(prefix) and parts[: len(prefix)] == prefix


def _safe_relative(path: Path, root: Path) -> tuple[str, tuple[str, ...]]:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PackageError(f"path escapes the project root: {path}") from exc
    value = relative.as_posix()
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or any(character in value for character in "\t\r\n\0")
    ):
        raise PackageError(f"unsafe or non-canonical relative path: {value!r}")
    return value, tuple(part.lower() for part in pure.parts)


def _directory_exclusion(parts: tuple[str, ...]) -> str | None:
    if not parts:
        return None
    leaf = parts[-1]
    if len(parts) == 1 and leaf in THIRD_PARTY_MODEL_ROOTS:
        return "third_party_model_source"
    if len(parts) == 1 and leaf in TOP_LEVEL_RUNTIME_ROOTS:
        return "runtime_or_data"
    if len(parts) == 1 and leaf in TOP_LEVEL_PRIVATE_DEPLOYMENT_ROOTS:
        return "deployment_topology"
    if any(_has_prefix(parts, prefix) for prefix in THIRD_PARTY_BUILD_TOOL_PREFIXES):
        return "third_party_build_tool"
    if any(_has_prefix(parts, prefix) for prefix in RUNTIME_PREFIXES):
        return "runtime_or_data"
    if any(_has_prefix(parts, prefix) for prefix in PERSONAL_MEDIA_PREFIXES):
        return "personal_media"
    if leaf in EXCLUDED_DIRECTORY_NAMES:
        if leaf == "vendor":
            return "third_party_vendor"
        if leaf in {"venv", "venvs", ".venv", ".venvs", "env"}:
            return "virtual_environment"
        if leaf in {"log", "logs"}:
            return "logs"
        if leaf in {"backup", "backups"}:
            return "backups"
        return "generated_or_tool_state"
    if BACKUP_COMPONENT_RE.search(leaf):
        return "backups"
    if leaf in {"secret", "secrets", ".secrets", "keys"}:
        return "secrets"
    return None


def _file_exclusion(relative_path: str, parts: tuple[str, ...]) -> str | None:
    name = parts[-1]
    path = PurePosixPath(relative_path)
    suffix = path.suffix.lower()
    if parts in THIRD_PARTY_BUILD_TOOL_FILES:
        return "third_party_build_tool"
    if parts in PRESENTATION_GENERATED_FILES:
        return "presentation_generated_output"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "secrets"
    if name in EXCLUDED_EXACT_FILES:
        return "secrets_or_local_state"
    if suffix in SECRET_SUFFIXES:
        return "secrets"
    if SENSITIVE_FILE_RE.search(name) and suffix not in SOURCE_SUFFIX_LABELS:
        return "secrets"
    if suffix in MEDIA_SUFFIXES:
        return "personal_or_media_file"
    if suffix in MODEL_AND_DATA_SUFFIXES:
        return "model_weight_or_data"
    if suffix in ARCHIVE_AND_BINARY_SUFFIXES:
        return "archive_or_binary"
    if suffix in {".log", ".out", ".trace"}:
        return "logs"
    if name.endswith(("~", ".bak", ".backup", ".orig", ".rej", ".swp", ".tmp")):
        return "backups_or_temporary"
    return None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_stable_text(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        before = path.stat()
    except OSError as exc:
        raise PackageError(f"unable to stat source file: {path}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise PackageError(f"source entry is not a regular file: {path}")
    if before.st_size > MAX_TEXT_FILE_BYTES:
        raise PackageError(
            f"candidate text file exceeds {MAX_TEXT_FILE_BYTES} bytes: {path}"
        )
    try:
        data = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise PackageError(f"unable to read source file: {path}") from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(data) != before.st_size:
        raise PackageError(f"source file changed while it was being read: {path}")
    if b"\0" in data:
        raise PackageError(f"candidate source file contains binary NUL bytes: {path}")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PackageError(f"candidate source file is not UTF-8 text: {path}") from exc
    return data, after


def _source_category(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    suffix = path.suffix.lower()
    if suffix in SOURCE_SUFFIX_LABELS:
        return SOURCE_SUFFIX_LABELS[suffix]
    if suffix in {".md", ".rst", ".txt"} or path.name == "COPYRIGHT":
        return "说明文档"
    if suffix in CONFIG_SUFFIXES or path.name in {"Dockerfile", "gradlew", "gradlew.bat"}:
        return "配置/构建文件"
    return "其他可读工程文件"


def validate_required_files(root: Path) -> None:
    missing: list[str] = []
    for relative in REQUIRED_FILES:
        path = root / Path(*PurePosixPath(relative).parts)
        if not path.is_file() or path.is_symlink():
            missing.append(relative)
    if missing:
        raise PackageError("required filing files are missing: " + ", ".join(missing))

    for relative in REQUIRED_SOFTWARE_COPYRIGHT_DOCS + (
        "ARCHITECTURE.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "COPYRIGHT",
    ):
        path = root / Path(*PurePosixPath(relative).parts)
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise PackageError(f"required filing file is not readable UTF-8: {relative}") from exc
        if SOFTWARE_NAME not in content:
            raise PackageError(
                f"required filing file does not use the canonical software name: {relative}"
            )

    copyright_text = (root / "COPYRIGHT").read_text(encoding="utf-8-sig")
    if "尚未选定统一对外开源许可" not in copyright_text:
        raise PackageError("COPYRIGHT must state that no unified open-source license is selected")
    if "Permission is hereby granted" in copyright_text or "SPDX-License-Identifier:" in copyright_text:
        raise PackageError("COPYRIGHT must not silently grant an open-source license")


def collect_source_files(root: Path) -> Collection:
    """Collect a stable, filtered, UTF-8 source snapshot."""

    try:
        root = root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise PackageError(f"project root is missing or unreadable: {root}") from exc
    if not root.is_dir():
        raise PackageError(f"project root is not a directory: {root}")
    validate_required_files(root)

    exclusions: Counter[str] = Counter()
    entries: list[SourceEntry] = []
    seen_casefold: dict[str, str] = {}
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        retained: list[str] = []
        for name in sorted(names):
            path = directory_path / name
            relative, parts = _safe_relative(path, root)
            reason = _directory_exclusion(parts)
            if reason is not None:
                exclusions[reason] += 1
                continue
            if path.is_symlink():
                raise PackageError(f"included directory must not be a symlink: {relative}")
            retained.append(name)
        names[:] = retained

        for name in sorted(filenames):
            path = directory_path / name
            relative, parts = _safe_relative(path, root)
            reason = _file_exclusion(relative, parts)
            if reason is not None:
                exclusions[reason] += 1
                continue
            if path.is_symlink():
                raise PackageError(f"included file must not be a symlink: {relative}")
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise PackageError(f"unable to stat candidate file: {relative}") from exc
            if size > MAX_TEXT_FILE_BYTES:
                exclusions["oversized_text_or_generated"] += 1
                continue
            try:
                data, metadata = _read_stable_text(path)
            except PackageError as exc:
                message = str(exc)
                if "binary NUL" in message or "not UTF-8 text" in message:
                    exclusions["binary_or_non_utf8"] += 1
                    continue
                raise
            if PRIVATE_KEY_RE.search(data[: 64 * 1024]):
                exclusions["private_key_material"] += 1
                continue
            if PERSONAL_ABSOLUTE_PATH_RE.search(data):
                raise PackageError(
                    "candidate source file contains an apparent personal absolute path: "
                    f"{relative}"
                )
            folded = relative.casefold()
            previous = seen_casefold.get(folded)
            if previous is not None:
                raise PackageError(
                    f"case-insensitive archive path collision: {previous!r} and {relative!r}"
                )
            seen_casefold[folded] = relative
            entries.append(
                SourceEntry(
                    relative_path=relative,
                    source_path=path,
                    category=_source_category(relative),
                    size_bytes=metadata.st_size,
                    sha256=_sha256_bytes(data),
                )
            )

    entries.sort(key=lambda item: item.relative_path)
    if not entries:
        raise PackageError("no source files remain after applying the default exclusions")
    required_set = set(REQUIRED_FILES)
    packaged_set = {entry.relative_path for entry in entries}
    omitted_required = sorted(required_set - packaged_set)
    if omitted_required:
        raise PackageError(
            "required filing files were excluded unexpectedly: " + ", ".join(omitted_required)
        )
    if not any(entry.relative_path.endswith(".py") for entry in entries):
        raise PackageError("source snapshot contains no Python implementation files")
    return Collection(entries=tuple(entries), exclusions=dict(sorted(exclusions.items())))


def _manifest_bytes(entries: Iterable[SourceEntry]) -> bytes:
    lines = [
        f"# 软件名称\t{SOFTWARE_NAME}",
        f"# 版本\t{SOFTWARE_VERSION}",
        "# 说明\t默认排除第三方模型/构建工具、部署拓扑、演示生成物、权重/数据、运行环境、日志、备份、密钥和常见媒体文件",
        "序号\t相对路径\t类型\t字节数\tSHA256",
    ]
    for index, entry in enumerate(entries, start=1):
        lines.append(
            f"{index}\t{entry.relative_path}\t{entry.category}\t"
            f"{entry.size_bytes}\t{entry.sha256}"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _package_readme_bytes(collection: Collection) -> bytes:
    exclusion_summary = "、".join(
        f"{reason}={count}" for reason, count in sorted(collection.exclusions.items())
    ) or "无"
    return (
        f"{SOFTWARE_NAME} 软件著作权源码交付包\n"
        "\n"
        "包体结构：\n"
        "- source/：经默认安全过滤的可读源码、配置、测试和说明文档；\n"
        "- SOURCE_MANIFEST.tsv：源码清单、类型、大小和 SHA-256；\n"
        "- SHA256SUMS：对 source/、本说明和源码清单的标准 SHA-256 清单。\n"
        "\n"
        "默认不包含：第三方模型源码、vendor 与 Gradle wrapper，部署拓扑，演示生成物，权重、数据集、运行时资产/"
        "报告，venv，缓存与构建产物，日志，备份，密钥/本地凭据，常见图片、音频和视频。\n"
        "该排除策略用于减少权利与隐私误交付，不构成对剩余文件权利状态的法律保证。\n"
        "本项目尚未选定统一对外开源许可；包体可见性不授予额外使用权。\n"
        "本包用于软件著作权源程序审查，不是可运行离线发行包或完整模型复现包。\n"
        "\n"
        f"源文件数：{len(collection.entries)}\n"
        f"源文件字节数：{sum(item.size_bytes for item in collection.entries)}\n"
        f"构建时排除统计：{exclusion_summary}\n"
    ).encode("utf-8")


def _sha256sums_bytes(
    entries: Iterable[SourceEntry],
    *,
    readme_bytes: bytes,
    manifest_bytes: bytes,
) -> bytes:
    records = [
        (_sha256_bytes(readme_bytes), "PACKAGE_README.txt"),
        (_sha256_bytes(manifest_bytes), "SOURCE_MANIFEST.tsv"),
    ]
    records.extend((entry.sha256, f"source/{entry.relative_path}") for entry in entries)
    records.sort(key=lambda item: item[1])
    return ("".join(f"{digest}  {path}\n" for digest, path in records)).encode("utf-8")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    return info


def _write_zip(
    path: Path,
    collection: Collection,
    *,
    readme_bytes: bytes,
    manifest_bytes: bytes,
    sha256sums_bytes: bytes,
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        generated = {
            f"{ARCHIVE_ROOT}/PACKAGE_README.txt": readme_bytes,
            f"{ARCHIVE_ROOT}/SHA256SUMS": sha256sums_bytes,
            f"{ARCHIVE_ROOT}/SOURCE_MANIFEST.tsv": manifest_bytes,
        }
        for name, data in sorted(generated.items()):
            archive.writestr(_zip_info(name), data)
        for entry in collection.entries:
            data, metadata = _read_stable_text(entry.source_path)
            if metadata.st_size != entry.size_bytes or _sha256_bytes(data) != entry.sha256:
                raise PackageError(
                    f"source changed after inventory creation: {entry.relative_path}"
                )
            archive.writestr(
                _zip_info(f"{ARCHIVE_ROOT}/source/{entry.relative_path}"),
                data,
            )


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sidecar_paths(output: Path) -> tuple[Path, Path, Path]:
    stem = output.name[:-4] if output.name.lower().endswith(".zip") else output.name
    return (
        output.with_name(f"{stem}.SOURCE_MANIFEST.tsv"),
        output.with_name(f"{stem}.SHA256SUMS"),
        output.with_name(f"{output.name}.sha256"),
    )


def _verify_built_archive(
    archive_path: Path,
    entries: Iterable[SourceEntry],
    *,
    readme_bytes: bytes,
    manifest_bytes: bytes,
    sha256sums_bytes: bytes,
) -> None:
    expected: dict[str, str] = {
        f"{ARCHIVE_ROOT}/PACKAGE_README.txt": _sha256_bytes(readme_bytes),
        f"{ARCHIVE_ROOT}/SOURCE_MANIFEST.tsv": _sha256_bytes(manifest_bytes),
        f"{ARCHIVE_ROOT}/SHA256SUMS": _sha256_bytes(sha256sums_bytes),
    }
    expected.update(
        {
            f"{ARCHIVE_ROOT}/source/{entry.relative_path}": entry.sha256
            for entry in entries
        }
    )
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise PackageError("archive membership differs from the source inventory")
        for name in names:
            if name.startswith("/") or ".." in PurePosixPath(name).parts or "\\" in name:
                raise PackageError(f"archive contains an unsafe path: {name!r}")
            if _sha256_bytes(archive.read(name)) != expected[name]:
                raise PackageError(f"archive member hash mismatch: {name}")


def check_project(root: Path) -> dict[str, object]:
    collection = collect_source_files(root)
    return {
        "status": "valid",
        "mode": "check",
        "software_name": SOFTWARE_NAME,
        "source_file_count": len(collection.entries),
        "source_size_bytes": sum(item.size_bytes for item in collection.entries),
        "excluded": collection.exclusions,
        "writes_performed": False,
    }


def build_package(root: Path, output: Path, *, force: bool = False) -> dict[str, object]:
    collection = collect_source_files(root)
    output = output.expanduser().resolve()
    if output.suffix.lower() != ".zip":
        raise PackageError("output path must end in .zip")
    manifest_path, sums_path, package_hash_path = _sidecar_paths(output)
    destinations = (output, manifest_path, sums_path, package_hash_path)
    existing = [str(path) for path in destinations if path.exists()]
    if existing and not force:
        raise PackageError(
            "refusing to overwrite existing output without --force: " + ", ".join(existing)
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    manifest_bytes = _manifest_bytes(collection.entries)
    readme_bytes = _package_readme_bytes(collection)
    sums_bytes = _sha256sums_bytes(
        collection.entries,
        readme_bytes=readme_bytes,
        manifest_bytes=manifest_bytes,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        _write_zip(
            temporary,
            collection,
            readme_bytes=readme_bytes,
            manifest_bytes=manifest_bytes,
            sha256sums_bytes=sums_bytes,
        )
        _verify_built_archive(
            temporary,
            collection.entries,
            readme_bytes=readme_bytes,
            manifest_bytes=manifest_bytes,
            sha256sums_bytes=sums_bytes,
        )
        archive_hash = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    _atomic_write(manifest_path, manifest_bytes)
    _atomic_write(sums_path, sums_bytes)
    _atomic_write(
        package_hash_path,
        f"{archive_hash}  {output.name}\n".encode("ascii"),
    )
    return {
        "status": "built",
        "software_name": SOFTWARE_NAME,
        "archive": str(output),
        "archive_sha256": archive_hash,
        "source_manifest": str(manifest_path),
        "sha256_manifest": str(sums_path),
        "archive_sha256_file": str(package_hash_path),
        "source_file_count": len(collection.entries),
        "source_size_bytes": sum(item.size_bytes for item in collection.entries),
        "excluded": collection.exclusions,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"构建{SOFTWARE_NAME}软著源码交付包"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="项目根目录")
    parser.add_argument("--output", type=Path, default=None, help="输出 ZIP（默认位于 dist/software-copyright）")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只验证必要文档、路径与默认排除，不创建任何文件",
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的输出和清单")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root = args.root.expanduser().resolve(strict=True)
        if args.check:
            result = check_project(root)
        else:
            output = args.output
            if output is None:
                output = root / "dist/software-copyright/JianYuanShield-V1.0-source.zip"
            elif not output.is_absolute():
                output = Path.cwd() / output
            result = build_package(root, output, force=args.force)
    except (OSError, PackageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
