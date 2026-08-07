from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import types
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator

import numpy as np
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


# Must be fixed before Torch initializes CUDA/cuBLAS.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.identity import IDENTITY_DERIVATION, identity_label  # noqa: E402
from system.evaluation.run_metadata import sha256_file  # noqa: E402
from system.evaluation.runtime import (  # noqa: E402
    ASSET_ROOT,
    DATA_ROOT,
    MODEL_SOURCE_ROOT,
    REPORT_ROOT,
    WEIGHT_ROOT,
    logical_path,
)


PROTOCOL_PATH = PROJECT_DIR / "configs/simswap_lfw_robustness.v1.json"
DEFAULT_IMAGE_ROOT = DATA_ROOT / "lfw/lfw"
DEFAULT_SIMSWAP_SOURCE = MODEL_SOURCE_ROOT / "SimSwap"
DEFAULT_ARCFACE_CHECKPOINT = WEIGHT_ROOT / "SimSwap/downloads/arcface_checkpoint.tar"
DEFAULT_CHECKPOINT_ARCHIVE = WEIGHT_ROOT / "SimSwap/downloads/checkpoints.zip"
DEFAULT_GENERATOR_CHECKPOINT = (
    WEIGHT_ROOT / "SimSwap/checkpoints/people/latest_net_G.pth"
)
DEFAULT_REPORT_DIR = REPORT_ROOT / "simswap-lfw-robustness-n256-s20260603"
DEFAULT_ASSET_DIR = ASSET_ROOT / "simswap-lfw-robustness-n256-s20260603"

MODEL_ORDER = ("LIDMark", "KAD-Net", "SepMark", "WaveGuard")
SIMSWAP_COMMIT = "bd7b7686a17f41dd11cfcd5d82f7e4c5eb94b780"
SIMSWAP_TREE = "20f6a41da5de682dcf3237398ef9376371c4002f"
SIMSWAP_TRACKED_FILES_SHA256 = (
    "26db6e77be8962a7fafec791af0b7e618d88a432df3c5fbf13a9ffe9516b4c4c"
)
ARCFACE_SHA256 = "52ea5ce4902017b77a2bb811dd9a82f57dee3883e06c18a42d288437263c7a20"
CHECKPOINT_ARCHIVE_SHA256 = (
    "0593544d9401d6bf28247932466b54e98a79139e328e3ab3ec1c541c5efc6ee8"
)
GENERATOR_SHA256 = "24caf144e9aabd5acd1127b06f13ed3528240adb9e747d77a94ac3f33e672330"
GENERATOR_ARCHIVE_MEMBER = "people/latest_net_G.pth"
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_Z_95 = 1.959963984540054
_MISSING_MODULE = object()


@contextmanager
def _kadnet_optional_import_stubs(model: str) -> Iterator[None]:
    """Scope KAD-Net's unused pyplot import to this benchmark runner.

    The canonical MEA adapter is content-pinned by completed evidence and must
    remain byte-for-byte stable. The official KAD-Net ``kanarchs`` module
    imports pyplot but never uses it during inference, so a temporary stub is
    installed only while that module is first imported.
    """

    if model != "KAD-Net":
        yield
        return
    try:
        import matplotlib.pyplot  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name not in {"matplotlib", "matplotlib.pyplot"}:
            raise
        previous = {
            name: sys.modules.get(name, _MISSING_MODULE)
            for name in ("matplotlib", "matplotlib.pyplot")
        }
        matplotlib_stub = types.ModuleType("matplotlib")
        matplotlib_stub.__path__ = []
        pyplot_stub = types.ModuleType("matplotlib.pyplot")
        matplotlib_stub.pyplot = pyplot_stub
        sys.modules["matplotlib"] = matplotlib_stub
        sys.modules["matplotlib.pyplot"] = pyplot_stub
        try:
            yield
        finally:
            for name, module in previous.items():
                if module is _MISSING_MODULE:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
    else:
        yield

REAL_N64_COMMAND = " ".join(
    (
        "python3 system/scripts/run_simswap_lfw_robustness.py",
        "--num-pairs 64 --calibration-pairs 16 --seed 20260603",
        "--device cuda:0 --artifact-limit 8 --flush-every 1",
        '--report-dir "${JYS_REPORT_ROOT:?set JYS_REPORT_ROOT}/simswap-lfw-robustness-n64-s20260603"',
        '--asset-dir "${JYS_ASSET_ROOT:?set JYS_ASSET_ROOT}/simswap-lfw-robustness-n64-s20260603"',
    )
)
REAL_N256_COMMAND = " ".join(
    (
        "python3 system/scripts/run_simswap_lfw_robustness.py",
        "--num-pairs 256 --calibration-pairs 64 --seed 20260603",
        "--device cuda:0 --artifact-limit 16 --flush-every 1",
        '--report-dir "${JYS_REPORT_ROOT:?set JYS_REPORT_ROOT}/simswap-lfw-robustness-n256-s20260603"',
        '--asset-dir "${JYS_ASSET_ROOT:?set JYS_ASSET_ROOT}/simswap-lfw-robustness-n256-s20260603"',
    )
)

RESULT_FIELDS = [
    "pair_id",
    "split",
    "model",
    "source_id",
    "target_id",
    "source_identity",
    "target_identity",
    "source_sha256",
    "target_sha256",
    "registry_record_sha256",
    "message_bits",
    "message_sha256",
    "wrong_message_bits",
    "wrong_message_sha256",
    "cross_record_pair_id",
    "cross_message_bits",
    "cross_message_sha256",
    "decoded_watermarked_bits",
    "decoded_watermarked_sha256",
    "decoded_unwatermarked_bits",
    "decoded_unwatermarked_sha256",
    "target_watermarked_rgb_sha256",
    "swapped_clean_rgb_sha256",
    "swapped_watermarked_rgb_sha256",
    "primary_decoder",
    "registered_positive_score",
    "unwatermarked_negative_score",
    "wrong_message_negative_score",
    "cross_record_negative_score",
    "target_watermarked_psnr",
    "target_watermarked_ssim",
    "swapped_clean_vs_watermarked_psnr",
    "swapped_clean_vs_watermarked_ssim",
    "swapped_clean_vs_target_psnr",
    "swapped_clean_vs_target_ssim",
    "swapped_watermarked_vs_target_psnr",
    "swapped_watermarked_vs_target_ssim",
    "arcface_source_target_cosine",
    "arcface_clean_source_cosine",
    "arcface_clean_target_cosine",
    "arcface_clean_identity_margin",
    "arcface_clean_identity_migrated",
    "arcface_watermarked_source_cosine",
    "arcface_watermarked_target_cosine",
    "arcface_watermarked_identity_margin",
    "arcface_watermarked_identity_migrated",
    "source_embedding_sha256",
    "target_embedding_sha256",
    "swapped_clean_embedding_sha256",
    "swapped_watermarked_embedding_sha256",
    "error",
]

IDENTITY_FIELDS = [
    "pair_id",
    "model",
    "variant",
    "embedding_dim",
    "embedding_json",
    "embedding_sha256",
]

def parse_args() -> argparse.Namespace:
    protocol = load_protocol()
    parser = argparse.ArgumentParser(
        description=(
            "Run the fail-closed four-watermark x official-SimSwap LFW "
            "identity-disjoint robustness track."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Real n64 smoke:\n  "
            + REAL_N64_COMMAND
            + "\n\nReal n256 evidence run:\n  "
            + REAL_N256_COMMAND
        ),
    )
    parser.add_argument("--num-pairs", type=int, default=256)
    parser.add_argument("--calibration-pairs", type=int, default=64)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--simswap-source", type=Path, default=DEFAULT_SIMSWAP_SOURCE)
    parser.add_argument(
        "--arcface-checkpoint", type=Path, default=DEFAULT_ARCFACE_CHECKPOINT
    )
    parser.add_argument(
        "--checkpoint-archive", type=Path, default=DEFAULT_CHECKPOINT_ARCHIVE
    )
    parser.add_argument(
        "--generator-checkpoint", type=Path, default=DEFAULT_GENERATOR_CHECKPOINT
    )
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--asset-dir", type=Path, default=DEFAULT_ASSET_DIR)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--seed", type=int, default=int(protocol["seed"]))
    parser.add_argument("--artifact-limit", type=int, default=8)
    parser.add_argument("--flush-every", type=int, default=1)
    return parser.parse_args()


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _atomic_write_json(path: Path, payload: Any) -> None:
    _assert_no_absolute_paths(payload, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_write_csv(
    path: Path,
    fieldnames: list[str],
    rows: Iterable[Mapping[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            _assert_no_absolute_paths(row, path.name)
            writer.writerow(row)
    temporary.replace(path)


def _atomic_save_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    Image.fromarray(_validate_rgb(image)).save(temporary, format="PNG")
    temporary.replace(path)


def _is_absolute_host_path(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped) and (
        Path(stripped).is_absolute() or bool(_WINDOWS_ABSOLUTE.match(stripped))
    )


def _assert_no_absolute_paths(payload: Any, context: str) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            _assert_no_absolute_paths(value, f"{context}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            _assert_no_absolute_paths(value, f"{context}[{index}]")
    elif isinstance(payload, str) and _is_absolute_host_path(payload):
        raise ValueError(f"absolute host path forbidden in {context}")


def _strict_sha256(path: Path) -> str:
    digest = sha256_file(path.expanduser().resolve())
    if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
        raise FileNotFoundError(f"file missing or unreadable: {logical_path(path)}")
    return digest


def _validate_rgb(image: np.ndarray) -> np.ndarray:
    value = np.asarray(image)
    if value.ndim != 3 or value.shape[2] != 3 or value.dtype != np.uint8:
        raise ValueError(f"expected HxWx3 uint8 RGB image, got {value.shape}/{value.dtype}")
    return value


def _rgb_sha256(image: np.ndarray) -> str:
    value = np.ascontiguousarray(_validate_rgb(image))
    digest = hashlib.sha256()
    digest.update(b"rgb-uint8.v1\0")
    digest.update(f"{value.shape[0]}x{value.shape[1]}x3\0".encode("ascii"))
    digest.update(value.tobytes())
    return digest.hexdigest()


def _implementation_manifest() -> list[dict[str, str]]:
    """Bind every project-owned inference component used by this run."""

    relative_paths = (
        "system/scripts/run_simswap_lfw_robustness.py",
        "system/evaluation/identity.py",
        "system/evaluation/runtime.py",
        "system/evaluation/adapters/__init__.py",
        "system/evaluation/adapters/base.py",
        "system/evaluation/adapters/lidmark_adapter.py",
        "system/evaluation/adapters/kadnet_adapter.py",
        "system/evaluation/adapters/sepmark_adapter.py",
        "system/evaluation/adapters/waveguard_adapter.py",
        "system/backend/model_adapters.py",
    )
    manifest: list[dict[str, str]] = []
    for relative in relative_paths:
        path = (PROJECT_DIR / relative).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"implementation file missing: {relative}")
        manifest.append({"path": relative, "sha256": _strict_sha256(path)})
    return manifest


def _safe_error(stage: str, error: BaseException) -> str:
    return f"{stage}:{type(error).__name__}"


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SimSwap robustness protocol must be an object")
    if payload.get("schema_version") != "simswap-lfw-robustness-protocol.v1":
        raise ValueError("SimSwap robustness protocol schema mismatch")
    if tuple(payload.get("watermark_models", [])) != MODEL_ORDER:
        raise ValueError("SimSwap robustness protocol model registry drift")
    if payload.get("pairing", {}).get("identity_derivation") != IDENTITY_DERIVATION:
        raise ValueError("identity derivation drift")
    simswap = payload.get("simswap")
    if not isinstance(simswap, dict):
        raise ValueError("SimSwap provenance policy missing")
    expected = {
        "commit": SIMSWAP_COMMIT,
        "tree": SIMSWAP_TREE,
        "tracked_files_sha256": SIMSWAP_TRACKED_FILES_SHA256,
    }
    if any(simswap.get(key) != value for key, value in expected.items()):
        raise ValueError("pinned SimSwap source provenance drift")
    archives = simswap.get("release_archives")
    if archives != {
        "arcface_checkpoint.tar": ARCFACE_SHA256,
        "checkpoints.zip": CHECKPOINT_ARCHIVE_SHA256,
        GENERATOR_ARCHIVE_MEMBER: GENERATOR_SHA256,
    }:
        raise ValueError("pinned SimSwap release weight provenance drift")
    _assert_no_absolute_paths(payload, "protocol")
    return payload


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    relative = resolved.relative_to(root.expanduser().resolve()).as_posix()
    if _is_absolute_host_path(relative) or relative.startswith("../"):
        raise ValueError("dataset path must be root-relative")
    return {
        "path": relative,
        "identity": identity_label(relative),
        "size_bytes": resolved.stat().st_size,
        "sha256": _strict_sha256(resolved),
    }


def select_content_addressed_pairs(
    image_root: Path,
    *,
    num_pairs: int,
    calibration_pairs: int,
    seed: int,
) -> dict[str, Any]:
    """Select distinct-identity LFW pairs without traversal-order dependence."""

    if calibration_pairs < 2:
        raise ValueError("calibration-pairs must be at least 2")
    if num_pairs - calibration_pairs < 2:
        raise ValueError("holdout must contain at least 2 pairs")
    root = image_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"LFW image root not found: {logical_path(root)}")
    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    if not paths:
        raise RuntimeError("LFW image root is empty")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        record = _file_record(path, root)
        grouped.setdefault(record["identity"], []).append(record)

    representatives: list[dict[str, Any]] = []
    for identity, records in grouped.items():
        representative = min(
            records,
            key=lambda item: hashlib.sha256(
                (
                    f"simswap-image-choice.v1\0{seed}\0{identity}\0"
                    f"{item['path']}\0{item['sha256']}"
                ).encode("utf-8")
            ).hexdigest(),
        )
        ranked = dict(representative)
        ranked["selection_rank"] = hashlib.sha256(
            (
                f"simswap-identity-rank.v1\0{seed}\0{identity}\0"
                f"{representative['path']}\0{representative['sha256']}"
            ).encode("utf-8")
        ).hexdigest()
        representatives.append(ranked)
    representatives.sort(key=lambda item: (item["selection_rank"], item["identity"]))
    required_identities = num_pairs * 2
    if len(representatives) < required_identities:
        raise RuntimeError(
            f"requested {num_pairs} pairs require {required_identities} identities; "
            f"dataset provides {len(representatives)}"
        )
    selected = representatives[:required_identities]

    pairs: list[dict[str, Any]] = []
    for index in range(num_pairs):
        source = selected[index]
        target = selected[index + num_pairs]
        split = "calibration" if index < calibration_pairs else "holdout"
        pair_core = {
            "index": index,
            "split": split,
            "source_id": source["path"],
            "target_id": target["path"],
            "source_identity": source["identity"],
            "target_identity": target["identity"],
            "source_size_bytes": source["size_bytes"],
            "target_size_bytes": target["size_bytes"],
            "source_sha256": source["sha256"],
            "target_sha256": target["sha256"],
        }
        pair = {"pair_id": _canonical_hash(pair_core), **pair_core}
        pairs.append(pair)

    calibration_ids = {
        value
        for pair in pairs
        if pair["split"] == "calibration"
        for value in (pair["source_identity"], pair["target_identity"])
    }
    holdout_ids = {
        value
        for pair in pairs
        if pair["split"] == "holdout"
        for value in (pair["source_identity"], pair["target_identity"])
    }
    all_ids = [
        value
        for pair in pairs
        for value in (pair["source_identity"], pair["target_identity"])
    ]
    if len(all_ids) != len(set(all_ids)):
        raise RuntimeError("pair selector reused an identity")
    if calibration_ids & holdout_ids:
        raise RuntimeError("calibration and holdout identities overlap")

    selected_files = [
        {
            "path": item["path"],
            "identity": item["identity"],
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
        }
        for item in selected
    ]
    manifest = {
        "schema_version": "simswap-pair-manifest.v1",
        "dataset_root": logical_path(root),
        "selection": "content-addressed-distinct-identity-halves.v1",
        "identity_derivation": IDENTITY_DERIVATION,
        "seed": seed,
        "candidate_file_count": len(paths),
        "candidate_identity_count": len(grouped),
        "num_pairs": num_pairs,
        "calibration_pairs": calibration_pairs,
        "holdout_pairs": num_pairs - calibration_pairs,
        "identity_count": len(all_ids),
        "calibration_identity_count": len(calibration_ids),
        "holdout_identity_count": len(holdout_ids),
        "identity_overlap_count": 0,
        "selected_files": selected_files,
        "selected_files_sha256": _canonical_hash(selected_files),
        "pairs": pairs,
        "pairs_sha256": _canonical_hash(pairs),
    }
    _assert_no_absolute_paths(manifest, "pair_manifest")
    return manifest


def _ensure_exact_json(
    path: Path,
    expected: dict[str, Any],
    *,
    state_exists: bool,
    role: str,
) -> None:
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid existing {role}") from exc
        _assert_no_absolute_paths(current, role)
        if current != expected:
            raise RuntimeError(f"existing {role} does not match requested run")
        return
    if state_exists:
        raise RuntimeError(f"benchmark state exists without {role}; refusing to mix evidence")
    _atomic_write_json(path, expected)


def _load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as source:
        return np.asarray(source.convert("RGB"), dtype=np.uint8).copy()


def _resize_rgb(image: np.ndarray, size: int = 224) -> np.ndarray:
    value = _validate_rgb(image)
    return np.asarray(
        Image.fromarray(value).resize((size, size), Image.Resampling.BICUBIC),
        dtype=np.uint8,
    ).copy()


def _metric_text(value: float) -> str:
    if math.isnan(value) or value == -math.inf:
        raise ValueError("non-finite evidence metric")
    return "inf" if value == math.inf else f"{value:.8f}"


def compute_quality(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, float]:
    left = _validate_rgb(reference)
    right = _validate_rgb(candidate)
    if left.shape != right.shape:
        raise ValueError("quality metric shape mismatch")
    side = min(left.shape[:2])
    if side < 3:
        raise ValueError("quality metrics require image sides >= 3")
    window = min(7, side if side % 2 else side - 1)
    return (
        float(peak_signal_noise_ratio(left, right, data_range=255)),
        float(
            structural_similarity(
                left,
                right,
                channel_axis=2,
                data_range=255,
                win_size=window,
            )
        ),
    )


def _run_git(source: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"unable to verify SimSwap git provenance: {' '.join(args)}")
    return completed.stdout.strip()


def _tracked_source_manifest(source: Path) -> tuple[list[dict[str, Any]], str]:
    completed = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("unable to enumerate tracked SimSwap source files")
    entries: list[dict[str, Any]] = []
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            relative = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("non-UTF-8 path in SimSwap source tree") from exc
        candidate = (source / relative).resolve()
        try:
            candidate.relative_to(source.resolve())
        except ValueError as exc:
            raise ValueError("tracked SimSwap path escapes source root") from exc
        if not candidate.is_file():
            raise FileNotFoundError(f"tracked SimSwap file missing: {relative}")
        entries.append(
            {
                "path": relative,
                "size_bytes": candidate.stat().st_size,
                "sha256": _strict_sha256(candidate),
            }
        )
    entries.sort(key=lambda item: item["path"])
    return entries, _canonical_hash(entries)


def _zip_member_sha256(archive: Path, member: str) -> str:
    digest = hashlib.sha256()
    try:
        with zipfile.ZipFile(archive) as handle:
            info = handle.getinfo(member)
            if info.is_dir() or Path(info.filename).is_absolute() or ".." in Path(info.filename).parts:
                raise ValueError("unsafe SimSwap checkpoint archive member")
            with handle.open(info, "r") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise ValueError("invalid SimSwap checkpoint archive") from exc
    return digest.hexdigest()


@contextmanager
def _verified_checkpoint_handle(
    path: Path,
    *,
    trusted_sha256: str,
) -> Iterator[BinaryIO]:
    if not _HEX64.fullmatch(trusted_sha256):
        raise ValueError("trusted checkpoint hash must be a lowercase SHA-256")
    resolved = path.expanduser().resolve()
    with resolved.open("rb") as handle:
        actual = _sha256_stream(handle)
        if actual != trusted_sha256:
            raise RuntimeError(
                f"checkpoint hash mismatch: {logical_path(resolved)} expected "
                f"{trusted_sha256}, got {actual}"
            )
        handle.seek(0)
        yield handle


def _load_weights_only_checkpoint(path: Path, *, trusted_sha256: str) -> Any:
    import torch

    with _verified_checkpoint_handle(path, trusted_sha256=trusted_sha256) as handle:
        return torch.load(handle, map_location="cpu", weights_only=True)


def _load_official_arcface_checkpoint(path: Path) -> Any:
    """Load the one legacy full-Module artifact in the evidence track.

    The upstream release cannot be represented by ``weights_only=True``. This
    compatibility path has no caller-supplied allowlist: it accepts only the
    repository-pinned official ArcFace SHA-256, verified on the same open file
    handle immediately before deserialization. Any other artifact is rejected
    before pickle execution.
    """

    import torch

    with _verified_checkpoint_handle(path, trusted_sha256=ARCFACE_SHA256) as handle:
        return torch.load(handle, map_location="cpu", weights_only=False)


def _sha256_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


class OfficialSimSwapEngine:
    """Torch-2.x-safe adapter around the exact official SimSwap release."""

    identity_dim = 512

    def __init__(
        self,
        *,
        source: Path,
        arcface_checkpoint: Path,
        checkpoint_archive: Path,
        generator_checkpoint: Path,
        device: str,
    ) -> None:
        self.source = source.expanduser().resolve()
        self.arcface_checkpoint = arcface_checkpoint.expanduser().resolve()
        self.checkpoint_archive = checkpoint_archive.expanduser().resolve()
        self.generator_checkpoint = generator_checkpoint.expanduser().resolve()
        self.device_name = device
        self.provenance = self._verify_provenance()
        self._load_models()

    def _verify_provenance(self) -> dict[str, Any]:
        if not self.source.is_dir():
            raise FileNotFoundError(
                f"official SimSwap source missing: {logical_path(self.source)}"
            )
        commit = _run_git(self.source, "rev-parse", "HEAD")
        tree = _run_git(self.source, "rev-parse", "HEAD^{tree}")
        dirty = _run_git(self.source, "status", "--porcelain", "--untracked-files=no")
        if commit != SIMSWAP_COMMIT or tree != SIMSWAP_TREE or dirty:
            raise RuntimeError("official SimSwap source checkout is not the pinned clean tree")
        entries, tracked_digest = _tracked_source_manifest(self.source)
        if tracked_digest != SIMSWAP_TRACKED_FILES_SHA256:
            raise RuntimeError("SimSwap tracked source SHA-256 manifest mismatch")

        archive_hash = _strict_sha256(self.checkpoint_archive)
        arcface_hash = _strict_sha256(self.arcface_checkpoint)
        generator_hash = _strict_sha256(self.generator_checkpoint)
        if archive_hash != CHECKPOINT_ARCHIVE_SHA256:
            raise RuntimeError("SimSwap official checkpoints.zip hash mismatch")
        if arcface_hash != ARCFACE_SHA256:
            raise RuntimeError("SimSwap official ArcFace checkpoint hash mismatch")
        if generator_hash != GENERATOR_SHA256:
            raise RuntimeError("SimSwap materialized generator hash mismatch")
        member_hash = _zip_member_sha256(
            self.checkpoint_archive, GENERATOR_ARCHIVE_MEMBER
        )
        if member_hash != GENERATOR_SHA256:
            raise RuntimeError("SimSwap generator does not match official release archive")
        return {
            "engine": "SimSwap",
            "mode": "official_release_checkpoint",
            "source_path": logical_path(self.source),
            "source_commit": commit,
            "source_tree": tree,
            "source_tracked_file_count": len(entries),
            "source_tracked_files_sha256": tracked_digest,
            "checkpoint_archive_path": logical_path(self.checkpoint_archive),
            "checkpoint_archive_sha256": archive_hash,
            "generator_archive_member": GENERATOR_ARCHIVE_MEMBER,
            "generator_checkpoint_path": logical_path(self.generator_checkpoint),
            "generator_checkpoint_sha256": generator_hash,
            "arcface_checkpoint_path": logical_path(self.arcface_checkpoint),
            "arcface_checkpoint_sha256": arcface_hash,
            "generator_load_policy": "weights_only_true_after_exact_sha256",
            "arcface_load_policy": (
                "weights_only_false_after_exact_official_sha256_allowlist"
            ),
            "input_size": 224,
            "identity_embedding_dim": self.identity_dim,
        }

    def _load_models(self) -> None:
        import torch

        if self.device_name.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA device requested but unavailable")
        self._device = torch.device(self.device_name)
        torch.manual_seed(0)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(0)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.use_deterministic_algorithms(True)

        source_text = str(self.source)
        existing_models = sys.modules.get("models")
        existing_file = Path(str(getattr(existing_models, "__file__", ""))).resolve()
        if existing_models is not None and self.source not in existing_file.parents:
            raise RuntimeError("Python module namespace 'models' is already occupied")
        if source_text not in sys.path:
            sys.path.insert(0, source_text)

        # Register the class names required by the official full-Module ArcFace
        # pickle before performing its exact-hash-constrained load.
        import models.arcface_models  # type: ignore[import-not-found]  # noqa: F401

        arcface = _load_official_arcface_checkpoint(self.arcface_checkpoint)
        if not isinstance(arcface, torch.nn.Module):
            raise TypeError("official ArcFace checkpoint is not a torch Module")

        from models.fs_networks import (  # type: ignore[import-not-found]
            Generator_Adain_Upsample,
        )

        generator = Generator_Adain_Upsample(
            input_nc=3,
            output_nc=3,
            latent_size=512,
            n_blocks=9,
            deep=False,
        )
        state = _load_weights_only_checkpoint(
            self.generator_checkpoint,
            trusted_sha256=GENERATOR_SHA256,
        )
        if not isinstance(state, Mapping) or not state:
            raise TypeError("official SimSwap generator state is not a non-empty mapping")
        generator.load_state_dict(dict(state), strict=True)
        self._arcface = arcface.to(self._device).eval()
        self._generator = generator.to(self._device).eval()

    def _image_tensor(self, image: np.ndarray, *, arcface: bool) -> Any:
        import torch

        resized = _resize_rgb(image, 112 if arcface else 224)
        array = resized.astype(np.float32) / 255.0
        tensor = torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0)
        if arcface:
            mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
            std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
            tensor = (tensor - mean) / std
        return tensor.to(self._device)

    def identity_embedding(self, image: np.ndarray) -> np.ndarray:
        import torch

        with torch.inference_mode():
            raw = self._arcface(self._image_tensor(image, arcface=True))
            raw = raw.reshape(raw.shape[0], -1)
            normalized = torch.nn.functional.normalize(raw, dim=1)
        vector = normalized[0].detach().cpu().to(torch.float32).numpy()
        if vector.shape != (self.identity_dim,) or not np.isfinite(vector).all():
            raise RuntimeError("invalid ArcFace identity embedding")
        return vector

    def swap(self, source: np.ndarray, target: np.ndarray) -> np.ndarray:
        import torch

        source_tensor = self._image_tensor(source, arcface=True)
        target_tensor = self._image_tensor(target, arcface=False)
        with torch.inference_mode():
            source_identity = self._arcface(source_tensor)
            source_identity = torch.nn.functional.normalize(source_identity, dim=1)
            output = self._generator(target_tensor, source_identity)
        if output.shape != (1, 3, 224, 224):
            raise RuntimeError(f"unexpected SimSwap output shape: {tuple(output.shape)}")
        array = (
            output[0]
            .detach()
            .cpu()
            .to(torch.float32)
            .clamp(0.0, 1.0)
            .permute(1, 2, 0)
            .numpy()
        )
        return np.clip(array * 255.0 + 0.5, 0, 255).astype(np.uint8)


def build_simswap_engine(args: argparse.Namespace) -> OfficialSimSwapEngine:
    return OfficialSimSwapEngine(
        source=args.simswap_source,
        arcface_checkpoint=args.arcface_checkpoint,
        checkpoint_archive=args.checkpoint_archive,
        generator_checkpoint=args.generator_checkpoint,
        device=args.device,
    )


@dataclass(frozen=True)
class WatermarkBinding:
    name: str
    adapter: Any
    message_length: int
    checkpoint_path: Path
    checkpoint_sha256: str
    primary_decoder: str


def build_watermark_bindings(device: str) -> dict[str, WatermarkBinding]:
    os.environ["JYS_INFER_DEVICE"] = device
    from system.evaluation.adapters import get_mea_adapter_classes

    classes = get_mea_adapter_classes()
    if tuple(classes) != MODEL_ORDER:
        raise RuntimeError("four-model watermark registry order drift")
    bindings: dict[str, WatermarkBinding] = {}
    for name in MODEL_ORDER:
        adapter_class = classes[name]
        checkpoint_raw = getattr(adapter_class, "checkpoint", None)
        expected_hash = getattr(adapter_class, "expected_checkpoint_sha256", None)
        primary_decoder = getattr(adapter_class, "primary_decoder", None)
        message_length = getattr(adapter_class, "message_length", None)
        if not isinstance(checkpoint_raw, str) or not checkpoint_raw:
            raise RuntimeError(f"{name} has no pinned checkpoint")
        if not isinstance(expected_hash, str) or not _HEX64.fullmatch(expected_hash):
            raise RuntimeError(f"{name} has no pinned checkpoint SHA-256")
        if not isinstance(primary_decoder, str) or not primary_decoder:
            raise RuntimeError(f"{name} has no frozen primary decoder")
        if not isinstance(message_length, int) or message_length <= 0:
            raise RuntimeError(f"{name} has invalid message length")
        checkpoint = Path(checkpoint_raw).expanduser().resolve()
        actual_hash = _strict_sha256(checkpoint)
        if actual_hash != expected_hash:
            raise RuntimeError(f"{name} checkpoint SHA-256 mismatch")
        adapter = adapter_class()
        if not adapter.available:
            raise RuntimeError(f"{name} adapter unavailable: {adapter.blocker}")
        if adapter.name != name or adapter.message_length != message_length:
            raise RuntimeError(f"{name} adapter contract drift")
        bindings[name] = WatermarkBinding(
            name=name,
            adapter=adapter,
            message_length=message_length,
            checkpoint_path=checkpoint,
            checkpoint_sha256=actual_hash,
            primary_decoder=primary_decoder,
        )
    return bindings


def _validate_engine_provenance(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("SimSwap engine provenance must be an object")
    expected = {
        "engine": "SimSwap",
        "mode": "official_release_checkpoint",
        "source_commit": SIMSWAP_COMMIT,
        "source_tree": SIMSWAP_TREE,
        "source_tracked_files_sha256": SIMSWAP_TRACKED_FILES_SHA256,
        "checkpoint_archive_sha256": CHECKPOINT_ARCHIVE_SHA256,
        "generator_archive_member": GENERATOR_ARCHIVE_MEMBER,
        "generator_checkpoint_sha256": GENERATOR_SHA256,
        "arcface_checkpoint_sha256": ARCFACE_SHA256,
        "generator_load_policy": "weights_only_true_after_exact_sha256",
        "arcface_load_policy": (
            "weights_only_false_after_exact_official_sha256_allowlist"
        ),
        "input_size": 224,
        "identity_embedding_dim": 512,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"SimSwap engine provenance mismatch: {key}")
    for key in (
        "source_path",
        "checkpoint_archive_path",
        "generator_checkpoint_path",
        "arcface_checkpoint_path",
    ):
        value = payload.get(key)
        if not isinstance(value, str) or not value or _is_absolute_host_path(value):
            raise ValueError(f"invalid logical provenance path: {key}")
    count = payload.get("source_tracked_file_count")
    if not isinstance(count, int) or count <= 0:
        raise ValueError("invalid SimSwap tracked file count")
    _assert_no_absolute_paths(payload, "engine_provenance")
    return dict(payload)


def message_for_record(
    seed: int,
    model: str,
    pair_id: str,
    length: int,
    *,
    domain: str = "registered",
) -> np.ndarray:
    if model not in MODEL_ORDER or not _HEX64.fullmatch(pair_id):
        raise ValueError("invalid registered message scope")
    if length <= 0:
        raise ValueError("message length must be positive")
    if domain not in {"registered", "wrong"}:
        raise ValueError("invalid message derivation domain")
    prefix = (
        "simswap-registered-message.v1"
        if domain == "registered"
        else "simswap-wrong-message.v1"
    )
    packed = hashlib.shake_256(
        f"{prefix}\0{seed}\0{model}\0{pair_id}".encode("utf-8")
    ).digest((length + 7) // 8)
    return np.unpackbits(
        np.frombuffer(packed, dtype=np.uint8), bitorder="big"
    )[:length].astype(np.uint8)


def _bits_text(bits: np.ndarray) -> str:
    values = np.asarray(bits).reshape(-1)
    if not np.isin(values, [0, 1]).all():
        raise ValueError("bit vector contains values outside {0,1}")
    return "".join(str(int(value)) for value in values.tolist())


def _bits_hash(bits: np.ndarray) -> str:
    values = np.asarray(bits, dtype=np.uint8).reshape(-1)
    if not np.isin(values, [0, 1]).all():
        raise ValueError("bit vector contains values outside {0,1}")
    return hashlib.sha256(values.tobytes()).hexdigest()


def _bits_from_text(value: str, length: int) -> np.ndarray:
    if len(value) != length or set(value) - {"0", "1"}:
        raise ValueError("invalid serialized bit vector")
    return np.fromiter((int(bit) for bit in value), dtype=np.uint8, count=length)


def bit_accuracy(decoded: np.ndarray, candidate: np.ndarray) -> float:
    left = np.asarray(decoded, dtype=np.uint8).reshape(-1)
    right = np.asarray(candidate, dtype=np.uint8).reshape(-1)
    if left.shape != right.shape or not np.isin(left, [0, 1]).all():
        raise ValueError("bit-accuracy vectors are incompatible")
    return float(np.mean(left == right))


def build_message_registry(
    pairs: Sequence[dict[str, Any]],
    bindings: Mapping[str, WatermarkBinding],
    *,
    seed: int,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for pair in pairs:
        for model in MODEL_ORDER:
            binding = bindings[model]
            bits = message_for_record(
                seed, model, pair["pair_id"], binding.message_length
            )
            core = {
                "pair_id": pair["pair_id"],
                "split": pair["split"],
                "model": model,
                "message_length": binding.message_length,
                "message_bits": _bits_text(bits),
                "message_sha256": _bits_hash(bits),
            }
            records.append({**core, "record_sha256": _canonical_hash(core)})
    return {
        "schema_version": "simswap-message-registry.v1",
        "derivation": "SHAKE256(simswap-registered-message.v1, seed, model, pair_id)",
        "seed": seed,
        "record_count": len(records),
        "records": records,
        "records_sha256": _canonical_hash(records),
    }


def _registry_index(registry: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    if registry.get("schema_version") != "simswap-message-registry.v1":
        raise ValueError("message registry schema mismatch")
    records = registry.get("records")
    if not isinstance(records, list) or registry.get("record_count") != len(records):
        raise ValueError("message registry count mismatch")
    if registry.get("records_sha256") != _canonical_hash(records):
        raise ValueError("message registry digest mismatch")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("message registry record must be an object")
        key = (str(record.get("pair_id", "")), str(record.get("model", "")))
        if key in indexed:
            raise ValueError(f"duplicate message registry record: {key}")
        core = {key_name: value for key_name, value in record.items() if key_name != "record_sha256"}
        if record.get("record_sha256") != _canonical_hash(core):
            raise ValueError(f"message registry record digest mismatch: {key}")
        length = record.get("message_length")
        if not isinstance(length, int):
            raise ValueError("invalid registry message length")
        bits = _bits_from_text(str(record.get("message_bits", "")), length)
        if record.get("message_sha256") != _bits_hash(bits):
            raise ValueError(f"message registry bit hash mismatch: {key}")
        indexed[key] = record
    return indexed


def _cross_record(
    pair: dict[str, Any],
    model: str,
    pairs: Sequence[dict[str, Any]],
    registry: Mapping[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    same_split = [candidate for candidate in pairs if candidate["split"] == pair["split"]]
    position = next(
        index for index, candidate in enumerate(same_split) if candidate["pair_id"] == pair["pair_id"]
    )
    current_bits = registry[(pair["pair_id"], model)]["message_bits"]
    for offset in range(1, len(same_split)):
        candidate = same_split[(position + offset) % len(same_split)]
        record = registry[(candidate["pair_id"], model)]
        if record["message_bits"] != current_bits:
            return record
    raise RuntimeError(f"{model} {pair['split']} split has no distinct cross-record message")


def _embedding_row(
    pair_id: str,
    model: str,
    variant: str,
    embedding: np.ndarray,
) -> dict[str, str]:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.size <= 0 or not np.isfinite(vector).all():
        raise ValueError("identity embedding is empty or non-finite")
    norm = float(np.linalg.norm(vector))
    if abs(norm - 1.0) > 1e-4:
        raise ValueError(f"identity embedding is not L2-normalized: {norm}")
    serialized = json.dumps(
        [float(value) for value in vector],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return {
        "pair_id": pair_id,
        "model": model,
        "variant": variant,
        "embedding_dim": str(vector.size),
        "embedding_json": serialized,
        "embedding_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }


def _identity_expected_keys(
    pairs: Sequence[dict[str, Any]],
) -> set[tuple[str, str, str]]:
    expected: set[tuple[str, str, str]] = set()
    for pair in pairs:
        pair_id = pair["pair_id"]
        expected.update(
            {
                (pair_id, "SimSwap", "source"),
                (pair_id, "SimSwap", "target"),
                (pair_id, "SimSwap", "swapped_clean"),
            }
        )
        expected.update(
            (pair_id, model, "swapped_watermarked") for model in MODEL_ORDER
        )
    return expected


def _load_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != fields:
                raise ValueError(f"CSV schema mismatch: {logical_path(path)}")
            rows = list(reader)
    except UnicodeError as exc:
        raise ValueError(f"invalid UTF-8 CSV: {logical_path(path)}") from exc
    _assert_no_absolute_paths(rows, path.name)
    return rows


def load_identity_rows(
    path: Path,
    expected_keys: set[tuple[str, str, str]],
    *,
    expected_dim: int,
) -> dict[tuple[str, str, str], dict[str, str]]:
    indexed: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in _load_csv(path, IDENTITY_FIELDS):
        key = (row["pair_id"], row["model"], row["variant"])
        if key in indexed:
            raise ValueError(f"duplicate identity embedding key: {key}")
        if key not in expected_keys:
            raise ValueError(f"unexpected identity embedding key: {key}")
        try:
            dimension = int(row["embedding_dim"])
            vector_payload = json.loads(row["embedding_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid identity embedding row: {key}") from exc
        if dimension != expected_dim or not isinstance(vector_payload, list):
            raise ValueError(f"identity embedding dimension mismatch: {key}")
        try:
            vector = np.asarray(vector_payload, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid identity embedding vector: {key}") from exc
        if vector.shape != (dimension,) or not np.isfinite(vector).all():
            raise ValueError(f"invalid identity embedding values: {key}")
        if abs(float(np.linalg.norm(vector)) - 1.0) > 1e-4:
            raise ValueError(f"identity embedding is not normalized: {key}")
        if row["embedding_sha256"] != hashlib.sha256(
            row["embedding_json"].encode("utf-8")
        ).hexdigest():
            raise ValueError(f"identity embedding hash mismatch: {key}")
        indexed[key] = row
    return indexed


def _identity_vector(row: Mapping[str, str]) -> np.ndarray:
    return np.asarray(json.loads(row["embedding_json"]), dtype=np.float64)


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    left_value = np.asarray(left, dtype=np.float64).reshape(-1)
    right_value = np.asarray(right, dtype=np.float64).reshape(-1)
    if left_value.shape != right_value.shape:
        raise ValueError("identity embedding dimensions differ")
    denominator = float(np.linalg.norm(left_value) * np.linalg.norm(right_value))
    if denominator <= 0:
        raise ValueError("zero-norm identity embedding")
    value = float(np.dot(left_value, right_value) / denominator)
    return float(np.clip(value, -1.0, 1.0))


def _float_field(row: Mapping[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric field {field}") from exc
    if math.isnan(value) or value == -math.inf:
        raise ValueError(f"invalid numeric field {field}")
    return value


def _static_result_values(
    pair: dict[str, Any],
    model: str,
    controls: Mapping[str, str],
) -> dict[str, str]:
    return {
        "pair_id": pair["pair_id"],
        "split": pair["split"],
        "model": model,
        "source_id": pair["source_id"],
        "target_id": pair["target_id"],
        "source_identity": pair["source_identity"],
        "target_identity": pair["target_identity"],
        "source_sha256": pair["source_sha256"],
        "target_sha256": pair["target_sha256"],
        **dict(controls),
    }


def _error_result_row(
    pair: dict[str, Any],
    model: str,
    controls: Mapping[str, str],
    error: str,
) -> dict[str, str]:
    row = {field: "" for field in RESULT_FIELDS}
    row.update(_static_result_values(pair, model, controls))
    row["error"] = error
    return row


def _expected_result_keys(
    pairs: Sequence[dict[str, Any]],
) -> set[tuple[str, str]]:
    return {(pair["pair_id"], model) for pair in pairs for model in MODEL_ORDER}


def load_result_rows(
    path: Path,
    *,
    pairs: Sequence[dict[str, Any]],
    registry: Mapping[tuple[str, str], dict[str, Any]],
    identities: Mapping[tuple[str, str, str], dict[str, str]],
    binding_lengths: Mapping[str, int],
    primary_decoders: Mapping[str, str],
    seed: int,
) -> dict[tuple[str, str], dict[str, str]]:
    pair_index = {pair["pair_id"]: pair for pair in pairs}
    expected_keys = _expected_result_keys(pairs)
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in _load_csv(path, RESULT_FIELDS):
        key = (row["pair_id"], row["model"])
        if key in indexed:
            raise ValueError(f"duplicate SimSwap result key: {key}")
        if key not in expected_keys:
            raise ValueError(f"unexpected SimSwap result key: {key}")
        pair = pair_index[key[0]]
        controls = _control_metadata_with_seed(pair, key[1], pairs, registry, seed)
        expected_static = _static_result_values(pair, key[1], controls)
        for field, expected in expected_static.items():
            if row[field] != expected:
                raise ValueError(f"result provenance mismatch {key}: {field}")
        if pair["source_identity"] == pair["target_identity"]:
            raise ValueError(f"same-identity SimSwap pair: {key}")
        if row["error"]:
            if any(row[field] for field in RESULT_FIELDS if field not in {*expected_static, "error"}):
                raise ValueError(f"error row contains result evidence: {key}")
            indexed[key] = row
            continue

        length = binding_lengths[key[1]]
        registered = _bits_from_text(row["message_bits"], length)
        wrong = _bits_from_text(row["wrong_message_bits"], length)
        cross = _bits_from_text(row["cross_message_bits"], length)
        decoded_wm = _bits_from_text(row["decoded_watermarked_bits"], length)
        decoded_clean = _bits_from_text(row["decoded_unwatermarked_bits"], length)
        if row["decoded_watermarked_sha256"] != _bits_hash(decoded_wm):
            raise ValueError(f"watermarked decoded-bit hash mismatch: {key}")
        if row["decoded_unwatermarked_sha256"] != _bits_hash(decoded_clean):
            raise ValueError(f"unwatermarked decoded-bit hash mismatch: {key}")
        expected_scores = {
            "registered_positive_score": bit_accuracy(decoded_wm, registered),
            "unwatermarked_negative_score": bit_accuracy(decoded_clean, registered),
            "wrong_message_negative_score": bit_accuracy(decoded_wm, wrong),
            "cross_record_negative_score": bit_accuracy(decoded_wm, cross),
        }
        for field, expected in expected_scores.items():
            actual = _float_field(row, field)
            if not 0.0 <= actual <= 1.0 or abs(actual - expected) > 5e-8:
                raise ValueError(f"control score mismatch {key}: {field}")
        if row["primary_decoder"] != primary_decoders[key[1]]:
            raise ValueError(f"primary decoder mismatch: {key}")
        for field in (
            "target_watermarked_rgb_sha256",
            "swapped_clean_rgb_sha256",
            "swapped_watermarked_rgb_sha256",
        ):
            if not _HEX64.fullmatch(row[field]):
                raise ValueError(f"invalid generated RGB hash {key}: {field}")

        for field in (
            "target_watermarked_psnr",
            "swapped_clean_vs_watermarked_psnr",
            "swapped_clean_vs_target_psnr",
            "swapped_watermarked_vs_target_psnr",
        ):
            if _float_field(row, field) == -math.inf:
                raise ValueError(f"invalid PSNR: {key}")
        for field in (
            "target_watermarked_ssim",
            "swapped_clean_vs_watermarked_ssim",
            "swapped_clean_vs_target_ssim",
            "swapped_watermarked_vs_target_ssim",
        ):
            if not -1.0 <= _float_field(row, field) <= 1.0:
                raise ValueError(f"invalid SSIM: {key}")

        identity_keys = {
            "source": (pair["pair_id"], "SimSwap", "source"),
            "target": (pair["pair_id"], "SimSwap", "target"),
            "clean": (pair["pair_id"], "SimSwap", "swapped_clean"),
            "watermarked": (pair["pair_id"], key[1], "swapped_watermarked"),
        }
        if any(value not in identities for value in identity_keys.values()):
            raise ValueError(f"result references missing identity embedding: {key}")
        vectors = {
            name: _identity_vector(identities[value])
            for name, value in identity_keys.items()
        }
        expected_identity = {
            "arcface_source_target_cosine": _cosine(vectors["source"], vectors["target"]),
            "arcface_clean_source_cosine": _cosine(vectors["clean"], vectors["source"]),
            "arcface_clean_target_cosine": _cosine(vectors["clean"], vectors["target"]),
            "arcface_watermarked_source_cosine": _cosine(
                vectors["watermarked"], vectors["source"]
            ),
            "arcface_watermarked_target_cosine": _cosine(
                vectors["watermarked"], vectors["target"]
            ),
        }
        expected_identity["arcface_clean_identity_margin"] = (
            expected_identity["arcface_clean_source_cosine"]
            - expected_identity["arcface_clean_target_cosine"]
        )
        expected_identity["arcface_watermarked_identity_margin"] = (
            expected_identity["arcface_watermarked_source_cosine"]
            - expected_identity["arcface_watermarked_target_cosine"]
        )
        for field, expected in expected_identity.items():
            if abs(_float_field(row, field) - expected) > 5e-7:
                raise ValueError(f"ArcFace identity proof mismatch {key}: {field}")
        expected_flags = {
            "arcface_clean_identity_migrated": (
                "1" if expected_identity["arcface_clean_identity_margin"] > 0 else "0"
            ),
            "arcface_watermarked_identity_migrated": (
                "1"
                if expected_identity["arcface_watermarked_identity_margin"] > 0
                else "0"
            ),
        }
        for field, expected in expected_flags.items():
            if row[field] != expected:
                raise ValueError(f"identity migration flag mismatch {key}: {field}")
        expected_hashes = {
            "source_embedding_sha256": identities[identity_keys["source"]]["embedding_sha256"],
            "target_embedding_sha256": identities[identity_keys["target"]]["embedding_sha256"],
            "swapped_clean_embedding_sha256": identities[identity_keys["clean"]]["embedding_sha256"],
            "swapped_watermarked_embedding_sha256": identities[identity_keys["watermarked"]]["embedding_sha256"],
        }
        for field, expected in expected_hashes.items():
            if row[field] != expected:
                raise ValueError(f"identity embedding hash reference mismatch {key}: {field}")
        indexed[key] = row
    return indexed


def _control_metadata_with_seed(
    pair: dict[str, Any],
    model: str,
    pairs: Sequence[dict[str, Any]],
    registry: Mapping[tuple[str, str], dict[str, Any]],
    seed: int,
) -> dict[str, str]:
    record = registry[(pair["pair_id"], model)]
    length = int(record["message_length"])
    registered = _bits_from_text(record["message_bits"], length)
    wrong = message_for_record(seed, model, pair["pair_id"], length, domain="wrong")
    if np.array_equal(wrong, registered):
        wrong = wrong.copy()
        wrong[0] ^= 1
    cross = _cross_record(pair, model, pairs, registry)
    return {
        "registry_record_sha256": str(record["record_sha256"]),
        "message_bits": str(record["message_bits"]),
        "message_sha256": str(record["message_sha256"]),
        "wrong_message_bits": _bits_text(wrong),
        "wrong_message_sha256": _bits_hash(wrong),
        "cross_record_pair_id": str(cross["pair_id"]),
        "cross_message_bits": str(cross["message_bits"]),
        "cross_message_sha256": str(cross["message_sha256"]),
    }


def wilson_interval(successes: int, total: int, z: float = _Z_95) -> dict[str, Any]:
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("invalid Wilson interval counts")
    estimate = successes / total
    denominator = 1.0 + z * z / total
    center = (estimate + z * z / (2.0 * total)) / denominator
    radius = (
        z
        * math.sqrt(
            estimate * (1.0 - estimate) / total + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return {
        "successes": successes,
        "total": total,
        "estimate": round(estimate, 8),
        "wilson_95_low": round(max(0.0, center - radius), 8),
        "wilson_95_high": round(min(1.0, center + radius), 8),
    }


def calibrate_threshold(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("threshold calibration split is empty")
    positives = [_float_field(row, "registered_positive_score") for row in rows]
    negative_fields = (
        "unwatermarked_negative_score",
        "wrong_message_negative_score",
        "cross_record_negative_score",
    )
    negatives = [
        _float_field(row, field) for row in rows for field in negative_fields
    ]
    if not negatives:
        raise ValueError("threshold calibration negatives are empty")
    candidates = sorted(
        {
            0.0,
            math.nextafter(1.0, math.inf),
            *positives,
            *negatives,
        }
    )
    best: tuple[tuple[float, float, float, float], float, int, int] | None = None
    for threshold in candidates:
        false_rejects = sum(score < threshold for score in positives)
        false_accepts = sum(score >= threshold for score in negatives)
        frr = false_rejects / len(positives)
        far = false_accepts / len(negatives)
        objective = (max(far, frr), (far + frr) / 2.0, far, -threshold)
        candidate = (objective, threshold, false_accepts, false_rejects)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        raise RuntimeError("no calibration threshold candidate")
    _, threshold, false_accepts, false_rejects = best
    return {
        "objective": "lexicographic_minimax_far_frr.v1",
        "threshold": threshold,
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "false_accept_count": false_accepts,
        "false_reject_count": false_rejects,
        "far": round(false_accepts / len(negatives), 8),
        "frr": round(false_rejects / len(positives), 8),
        "tar": round(1.0 - false_rejects / len(positives), 8),
    }


def _mean_metric(rows: Sequence[Mapping[str, str]], field: str) -> float | str:
    values = [_float_field(row, field) for row in rows]
    if not values:
        raise ValueError(f"cannot average empty metric: {field}")
    if any(value == math.inf for value in values):
        return "inf"
    return round(float(np.mean(values)), 8)


def summarize_model(
    rows: Sequence[Mapping[str, str]],
    *,
    calibration_pairs: int,
    holdout_pairs: int,
) -> dict[str, Any]:
    calibration = [row for row in rows if row["split"] == "calibration"]
    holdout = [row for row in rows if row["split"] == "holdout"]
    if len(calibration) != calibration_pairs or len(holdout) != holdout_pairs:
        raise ValueError("per-model split coverage mismatch")
    threshold_info = calibrate_threshold(calibration)
    threshold = float(threshold_info["threshold"])

    positive_accepts = sum(
        _float_field(row, "registered_positive_score") >= threshold for row in holdout
    )
    false_rejects = len(holdout) - positive_accepts
    negative_fields = {
        "unwatermarked": "unwatermarked_negative_score",
        "wrong_message": "wrong_message_negative_score",
        "cross_record": "cross_record_negative_score",
    }
    per_control: dict[str, Any] = {}
    false_accept_total = 0
    for control, field in negative_fields.items():
        accepted = sum(_float_field(row, field) >= threshold for row in holdout)
        false_accept_total += accepted
        per_control[control] = wilson_interval(accepted, len(holdout))
    negative_total = len(holdout) * len(negative_fields)

    return {
        "status": "complete",
        "calibration": threshold_info,
        "holdout": {
            "pair_count": len(holdout),
            "tar": wilson_interval(positive_accepts, len(holdout)),
            "frr": wilson_interval(false_rejects, len(holdout)),
            "far": wilson_interval(false_accept_total, negative_total),
            "far_by_negative_control": per_control,
        },
        "identity_migration": {
            "clean_swap": wilson_interval(
                sum(row["arcface_clean_identity_migrated"] == "1" for row in holdout),
                len(holdout),
            ),
            "watermarked_swap": wilson_interval(
                sum(
                    row["arcface_watermarked_identity_migrated"] == "1"
                    for row in holdout
                ),
                len(holdout),
            ),
            "mean_clean_source_margin": _mean_metric(
                holdout, "arcface_clean_identity_margin"
            ),
            "mean_watermarked_source_margin": _mean_metric(
                holdout, "arcface_watermarked_identity_margin"
            ),
        },
        "holdout_quality": {
            "mean_target_watermarked_psnr": _mean_metric(
                holdout, "target_watermarked_psnr"
            ),
            "mean_target_watermarked_ssim": _mean_metric(
                holdout, "target_watermarked_ssim"
            ),
            "mean_swapped_clean_vs_watermarked_psnr": _mean_metric(
                holdout, "swapped_clean_vs_watermarked_psnr"
            ),
            "mean_swapped_clean_vs_watermarked_ssim": _mean_metric(
                holdout, "swapped_clean_vs_watermarked_ssim"
            ),
            "mean_swapped_clean_vs_target_psnr": _mean_metric(
                holdout, "swapped_clean_vs_target_psnr"
            ),
            "mean_swapped_clean_vs_target_ssim": _mean_metric(
                holdout, "swapped_clean_vs_target_ssim"
            ),
            "mean_swapped_watermarked_vs_target_psnr": _mean_metric(
                holdout, "swapped_watermarked_vs_target_psnr"
            ),
            "mean_swapped_watermarked_vs_target_ssim": _mean_metric(
                holdout, "swapped_watermarked_vs_target_ssim"
            ),
        },
    }


def _run_class(num_pairs: int, calibration_pairs: int) -> str:
    if (num_pairs, calibration_pairs) == (64, 16):
        return "real_n64_smoke"
    if (num_pairs, calibration_pairs) == (256, 64):
        return "real_n256_evidence"
    return "custom_real_run"


def _build_asset_manifest(asset_dir: Path, output_path: Path) -> dict[str, Any]:
    root = asset_dir.expanduser().resolve()
    files: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*.png"), key=lambda item: item.relative_to(root).as_posix()):
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": _strict_sha256(path),
                }
            )
    payload = {
        "schema_version": "simswap-robustness-assets.v1",
        "asset_root": logical_path(root),
        "file_count": len(files),
        "files": files,
        "files_sha256": _canonical_hash(files),
    }
    _atomic_write_json(output_path, payload)
    return payload


def _partial_summary(
    *,
    results_path: Path,
    identities_path: Path,
    result_rows: Mapping[tuple[str, str], Mapping[str, str]],
    identity_rows: Mapping[tuple[str, str, str], Mapping[str, str]],
    expected_results: int,
    expected_identities: int,
    run_class: str,
    status: str,
) -> dict[str, Any]:
    errors = sum(bool(row["error"]) for row in result_rows.values())
    return {
        "schema_version": "simswap-lfw-robustness-summary.v1",
        "status": status,
        "run_class": run_class,
        "models": list(MODEL_ORDER),
        "result_rows": len(result_rows),
        "expected_result_rows": expected_results,
        "missing_result_rows": expected_results - len(result_rows),
        "error_rows": errors,
        "identity_embedding_rows": len(identity_rows),
        "expected_identity_embedding_rows": expected_identities,
        "missing_identity_embedding_rows": expected_identities - len(identity_rows),
        "results_csv_path": logical_path(results_path),
        "results_csv_sha256": _strict_sha256(results_path),
        "identity_embeddings_csv_path": logical_path(identities_path),
        "identity_embeddings_csv_sha256": _strict_sha256(identities_path),
    }


def _complete_summary(
    *,
    args: argparse.Namespace,
    protocol: dict[str, Any],
    engine_provenance: dict[str, Any],
    bindings: Mapping[str, WatermarkBinding],
    pairs: Sequence[dict[str, Any]],
    results: Mapping[tuple[str, str], Mapping[str, str]],
    results_path: Path,
    identities_path: Path,
    pair_manifest_path: Path,
    registry_path: Path,
    run_config_path: Path,
    asset_manifest_path: Path,
) -> dict[str, Any]:
    model_summaries: dict[str, Any] = {}
    for model in MODEL_ORDER:
        model_rows = [results[(pair["pair_id"], model)] for pair in pairs]
        model_summaries[model] = summarize_model(
            model_rows,
            calibration_pairs=args.calibration_pairs,
            holdout_pairs=args.num_pairs - args.calibration_pairs,
        )
        model_summaries[model]["checkpoint"] = logical_path(
            bindings[model].checkpoint_path
        )
        model_summaries[model]["checkpoint_sha256"] = bindings[
            model
        ].checkpoint_sha256
        model_summaries[model]["message_length"] = bindings[model].message_length
        model_summaries[model]["primary_decoder"] = bindings[model].primary_decoder
    summary = {
        "schema_version": "simswap-lfw-robustness-summary.v1",
        "status": "complete",
        "project": "鉴源盾",
        "track": "real_face_swap_robustness",
        "run_class": _run_class(args.num_pairs, args.calibration_pairs),
        "engine": engine_provenance,
        "protocol_path": logical_path(PROTOCOL_PATH),
        "protocol_sha256": _strict_sha256(PROTOCOL_PATH),
        "protocol_id": protocol["protocol_id"],
        "seed": args.seed,
        "models": list(MODEL_ORDER),
        "num_pairs": args.num_pairs,
        "calibration_pairs": args.calibration_pairs,
        "holdout_pairs": args.num_pairs - args.calibration_pairs,
        "identity_overlap_count": 0,
        "result_rows": len(results),
        "expected_result_rows": args.num_pairs * len(MODEL_ORDER),
        "error_rows": 0,
        "identity_embedding_rows": args.num_pairs * (3 + len(MODEL_ORDER)),
        "expected_identity_embedding_rows": args.num_pairs * (3 + len(MODEL_ORDER)),
        "controls": list(protocol["controls"]),
        "confidence_interval": protocol["confidence_intervals"],
        "pair_manifest_path": logical_path(pair_manifest_path),
        "pair_manifest_sha256": _strict_sha256(pair_manifest_path),
        "message_registry_path": logical_path(registry_path),
        "message_registry_sha256": _strict_sha256(registry_path),
        "run_config_path": logical_path(run_config_path),
        "run_config_sha256": _strict_sha256(run_config_path),
        "results_csv_path": logical_path(results_path),
        "results_csv_sha256": _strict_sha256(results_path),
        "identity_embeddings_csv_path": logical_path(identities_path),
        "identity_embeddings_csv_sha256": _strict_sha256(identities_path),
        "assets_manifest_path": logical_path(asset_manifest_path),
        "assets_manifest_sha256": _strict_sha256(asset_manifest_path),
        "model_results": model_summaries,
    }
    _assert_no_absolute_paths(summary, "summary")
    return summary


def _ordered_result_rows(
    rows: Mapping[tuple[str, str], dict[str, str]],
    pairs: Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    return [
        rows[key]
        for pair in pairs
        for model in MODEL_ORDER
        if (key := (pair["pair_id"], model)) in rows
    ]


def _ordered_identity_rows(
    rows: Mapping[tuple[str, str, str], dict[str, str]],
    pairs: Sequence[dict[str, Any]],
) -> list[dict[str, str]]:
    ordered: list[dict[str, str]] = []
    for pair in pairs:
        pair_id = pair["pair_id"]
        keys = [
            (pair_id, "SimSwap", "source"),
            (pair_id, "SimSwap", "target"),
            (pair_id, "SimSwap", "swapped_clean"),
            *((pair_id, model, "swapped_watermarked") for model in MODEL_ORDER),
        ]
        ordered.extend(rows[key] for key in keys if key in rows)
    return ordered


def _resolve_dataset_member(root: Path, identifier: str) -> Path:
    raw = Path(identifier)
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("dataset member must be root-relative")
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("dataset member escapes image root") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"dataset member missing: {identifier}")
    return candidate


def _decoder_name(decoded: Any, expected: str) -> str:
    metadata = getattr(decoded, "metadata", None)
    if not isinstance(metadata, Mapping):
        raise ValueError("watermark decoder metadata missing")
    reported = metadata.get("primary_decoder") or metadata.get("decoder")
    if reported != expected:
        raise RuntimeError(
            f"watermark primary decoder drift: expected {expected}, got {reported}"
        )
    return str(reported)


def main() -> int:
    args = parse_args()
    if args.num_pairs <= 0:
        raise ValueError("num-pairs must be positive")
    if args.calibration_pairs < 2 or args.num_pairs - args.calibration_pairs < 2:
        raise ValueError("calibration and holdout splits must each contain at least 2 pairs")
    if args.flush_every <= 0:
        raise ValueError("flush-every must be positive")
    if args.artifact_limit < 0:
        raise ValueError("artifact-limit must be non-negative")
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in {":4096:8", ":16:8"}:
        raise ValueError("CUBLAS_WORKSPACE_CONFIG must be :4096:8 or :16:8")

    protocol = load_protocol()
    image_root = args.image_root.expanduser().resolve()
    pair_manifest = select_content_addressed_pairs(
        image_root,
        num_pairs=args.num_pairs,
        calibration_pairs=args.calibration_pairs,
        seed=args.seed,
    )
    pairs = pair_manifest["pairs"]

    report_dir = args.report_dir.expanduser().resolve()
    asset_dir = args.asset_dir.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    pair_manifest_path = report_dir / "pair_manifest.json"
    registry_path = report_dir / "message_registry.json"
    run_config_path = report_dir / "run_config.json"
    identities_path = report_dir / "identity_embeddings.csv"
    results_path = report_dir / "results.csv"
    summary_path = report_dir / "summary.json"
    progress_path = report_dir / "progress.json"
    asset_manifest_path = report_dir / "assets_manifest.json"

    state_without_pair_manifest = any(
        path.exists()
        for path in (
            registry_path,
            run_config_path,
            identities_path,
            results_path,
            summary_path,
            progress_path,
            asset_manifest_path,
        )
    )
    _ensure_exact_json(
        pair_manifest_path,
        pair_manifest,
        state_exists=state_without_pair_manifest,
        role="pair_manifest.json",
    )

    engine = build_simswap_engine(args)
    engine_provenance = _validate_engine_provenance(engine.provenance)
    bindings = build_watermark_bindings(args.device)
    if tuple(bindings) != MODEL_ORDER:
        raise RuntimeError("watermark binding registry is not the exact four-model order")

    registry_payload = build_message_registry(pairs, bindings, seed=args.seed)
    registry_state_exists = any(
        path.exists()
        for path in (
            run_config_path,
            identities_path,
            results_path,
            summary_path,
            progress_path,
            asset_manifest_path,
        )
    )
    _ensure_exact_json(
        registry_path,
        registry_payload,
        state_exists=registry_state_exists,
        role="message_registry.json",
    )
    registry = _registry_index(registry_payload)

    watermark_provenance = []
    for model in MODEL_ORDER:
        binding = bindings[model]
        watermark_provenance.append(
            {
                "model": model,
                "checkpoint": logical_path(binding.checkpoint_path),
                "checkpoint_sha256": binding.checkpoint_sha256,
                "message_length": binding.message_length,
                "primary_decoder": binding.primary_decoder,
            }
        )
    run_config = {
        "schema_version": "simswap-lfw-robustness-run.v1",
        "protocol_path": logical_path(PROTOCOL_PATH),
        "protocol_sha256": _strict_sha256(PROTOCOL_PATH),
        "protocol_id": protocol["protocol_id"],
        "seed": args.seed,
        "num_pairs": args.num_pairs,
        "calibration_pairs": args.calibration_pairs,
        "holdout_pairs": args.num_pairs - args.calibration_pairs,
        "device": args.device,
        "artifact_limit": args.artifact_limit,
        "models": list(MODEL_ORDER),
        "dataset_root": logical_path(image_root),
        "pair_manifest_path": logical_path(pair_manifest_path),
        "pair_manifest_sha256": _strict_sha256(pair_manifest_path),
        "message_registry_path": logical_path(registry_path),
        "message_registry_sha256": _strict_sha256(registry_path),
        "engine": engine_provenance,
        "watermarks": watermark_provenance,
        "implementation_files": _implementation_manifest(),
        "result_schema": RESULT_FIELDS,
        "identity_embedding_schema": IDENTITY_FIELDS,
        "determinism": {
            "numpy_seed": args.seed,
            "torch_seed": args.seed,
            "torch_deterministic_algorithms": True,
            "cudnn_benchmark": False,
            "cudnn_deterministic": True,
            "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
        },
    }
    run_state_exists = any(
        path.exists()
        for path in (
            identities_path,
            results_path,
            summary_path,
            progress_path,
            asset_manifest_path,
        )
    )
    _ensure_exact_json(
        run_config_path,
        run_config,
        state_exists=run_state_exists,
        role="run_config.json",
    )

    np.random.seed(args.seed % (2**32))
    try:
        import torch

        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.use_deterministic_algorithms(True)
    except ImportError as exc:
        raise RuntimeError("Torch is required for the real SimSwap track") from exc

    identity_expected = _identity_expected_keys(pairs)
    identity_dim = int(engine_provenance["identity_embedding_dim"])
    identity_rows = load_identity_rows(
        identities_path, identity_expected, expected_dim=identity_dim
    )
    binding_lengths = {model: bindings[model].message_length for model in MODEL_ORDER}
    primary_decoders = {model: bindings[model].primary_decoder for model in MODEL_ORDER}
    result_rows = load_result_rows(
        results_path,
        pairs=pairs,
        registry=registry,
        identities=identity_rows,
        binding_lengths=binding_lengths,
        primary_decoders=primary_decoders,
        seed=args.seed,
    )
    expected_results = args.num_pairs * len(MODEL_ORDER)
    expected_identities = args.num_pairs * (3 + len(MODEL_ORDER))
    started = time.time()

    def flush(processed_pairs: int, status: str) -> None:
        _atomic_write_csv(
            identities_path,
            IDENTITY_FIELDS,
            _ordered_identity_rows(identity_rows, pairs),
        )
        _atomic_write_csv(
            results_path,
            RESULT_FIELDS,
            _ordered_result_rows(result_rows, pairs),
        )
        partial = _partial_summary(
            results_path=results_path,
            identities_path=identities_path,
            result_rows=result_rows,
            identity_rows=identity_rows,
            expected_results=expected_results,
            expected_identities=expected_identities,
            run_class=_run_class(args.num_pairs, args.calibration_pairs),
            status=status,
        )
        _atomic_write_json(summary_path, partial)
        elapsed = max(0.0, time.time() - started)
        remaining = max(0, args.num_pairs - processed_pairs)
        eta = elapsed / processed_pairs * remaining if processed_pairs else None
        progress = {
            "schema_version": "simswap-lfw-robustness-progress.v1",
            "status": status,
            "processed_pairs": processed_pairs,
            "total_pairs": args.num_pairs,
            "result_rows": len(result_rows),
            "expected_result_rows": expected_results,
            "identity_embedding_rows": len(identity_rows),
            "expected_identity_embedding_rows": expected_identities,
            "error_rows": sum(bool(row["error"]) for row in result_rows.values()),
            "elapsed_s": round(elapsed, 3),
            "eta_s": round(eta, 3) if eta is not None else None,
            "updated_at": int(time.time()),
        }
        _atomic_write_json(progress_path, progress)

    for pair_index, pair in enumerate(pairs):
        pair_id = pair["pair_id"]
        result_keys = [(pair_id, model) for model in MODEL_ORDER]
        identity_keys = {
            (pair_id, "SimSwap", "source"),
            (pair_id, "SimSwap", "target"),
            (pair_id, "SimSwap", "swapped_clean"),
            *((pair_id, model, "swapped_watermarked") for model in MODEL_ORDER),
        }
        if all(
            key in result_rows and not result_rows[key]["error"] for key in result_keys
        ) and identity_keys <= set(identity_rows):
            if (pair_index + 1) % args.flush_every == 0:
                flush(pair_index + 1, "running")
            continue

        source_path = _resolve_dataset_member(image_root, pair["source_id"])
        target_path = _resolve_dataset_member(image_root, pair["target_id"])
        try:
            if _strict_sha256(source_path) != pair["source_sha256"]:
                raise RuntimeError("source image changed after pair manifest creation")
            if _strict_sha256(target_path) != pair["target_sha256"]:
                raise RuntimeError("target image changed after pair manifest creation")
            source = _load_rgb(source_path)
            target = _load_rgb(target_path)
            swapped_clean = _validate_rgb(engine.swap(source, target))
            if swapped_clean.shape != (224, 224, 3):
                raise ValueError("SimSwap clean output must be 224x224 RGB")

            shared_vectors: dict[str, np.ndarray] = {}
            for variant, image in (
                ("source", source),
                ("target", target),
                ("swapped_clean", swapped_clean),
            ):
                key = (pair_id, "SimSwap", variant)
                if key not in identity_rows:
                    identity_rows[key] = _embedding_row(
                        pair_id,
                        "SimSwap",
                        variant,
                        engine.identity_embedding(image),
                    )
                shared_vectors[variant] = _identity_vector(identity_rows[key])

            if pair_index < args.artifact_limit:
                sample_dir = asset_dir / f"pair_{pair_index + 1:05d}"
                _atomic_save_png(sample_dir / "source.png", _resize_rgb(source))
                _atomic_save_png(sample_dir / "target.png", _resize_rgb(target))
                _atomic_save_png(sample_dir / "swapped_clean.png", swapped_clean)
        except Exception as exc:
            for model in MODEL_ORDER:
                key = (pair_id, model)
                if key in result_rows and not result_rows[key]["error"]:
                    continue
                controls = _control_metadata_with_seed(
                    pair, model, pairs, registry, args.seed
                )
                result_rows[key] = _error_result_row(
                    pair, model, controls, _safe_error("simswap_clean", exc)
                )
            if (pair_index + 1) % args.flush_every == 0:
                flush(pair_index + 1, "running")
            continue

        target_224 = _resize_rgb(target)
        source_target_cosine = _cosine(
            shared_vectors["source"], shared_vectors["target"]
        )
        clean_source_cosine = _cosine(
            shared_vectors["swapped_clean"], shared_vectors["source"]
        )
        clean_target_cosine = _cosine(
            shared_vectors["swapped_clean"], shared_vectors["target"]
        )
        clean_margin = clean_source_cosine - clean_target_cosine

        for model in MODEL_ORDER:
            key = (pair_id, model)
            wm_identity_key = (pair_id, model, "swapped_watermarked")
            if (
                key in result_rows
                and not result_rows[key]["error"]
                and wm_identity_key in identity_rows
            ):
                continue
            result_rows.pop(key, None)
            controls = _control_metadata_with_seed(
                pair, model, pairs, registry, args.seed
            )
            binding = bindings[model]
            registered = _bits_from_text(
                controls["message_bits"], binding.message_length
            )
            wrong = _bits_from_text(
                controls["wrong_message_bits"], binding.message_length
            )
            cross = _bits_from_text(
                controls["cross_message_bits"], binding.message_length
            )
            try:
                with _kadnet_optional_import_stubs(model):
                    embedded = binding.adapter.encode(target, registered)
                target_watermarked = _validate_rgb(embedded.image)
                embedded_message = np.asarray(embedded.message, dtype=np.uint8).reshape(-1)
                if not np.array_equal(embedded_message, registered):
                    raise RuntimeError("watermark adapter changed the registered message")
                swapped_watermarked = _validate_rgb(
                    engine.swap(source, target_watermarked)
                )
                if swapped_watermarked.shape != swapped_clean.shape:
                    raise ValueError("clean and watermarked SimSwap output shapes differ")

                decoded_watermarked = binding.adapter.decode(swapped_watermarked)
                decoded_clean = binding.adapter.decode(swapped_clean)
                decoder_name = _decoder_name(decoded_watermarked, binding.primary_decoder)
                _decoder_name(decoded_clean, binding.primary_decoder)
                decoded_wm_bits = np.asarray(
                    decoded_watermarked.bits, dtype=np.uint8
                ).reshape(-1)
                decoded_clean_bits = np.asarray(decoded_clean.bits, dtype=np.uint8).reshape(-1)
                if decoded_wm_bits.size != binding.message_length:
                    raise ValueError("watermarked decoded message length mismatch")
                if decoded_clean_bits.size != binding.message_length:
                    raise ValueError("unwatermarked decoded message length mismatch")
                if not np.isin(decoded_wm_bits, [0, 1]).all() or not np.isin(
                    decoded_clean_bits, [0, 1]
                ).all():
                    raise ValueError("decoder returned non-binary values")

                wm_embedding = engine.identity_embedding(swapped_watermarked)
                identity_rows[wm_identity_key] = _embedding_row(
                    pair_id,
                    model,
                    "swapped_watermarked",
                    wm_embedding,
                )
                wm_vector = _identity_vector(identity_rows[wm_identity_key])
                wm_source_cosine = _cosine(wm_vector, shared_vectors["source"])
                wm_target_cosine = _cosine(wm_vector, shared_vectors["target"])
                wm_margin = wm_source_cosine - wm_target_cosine

                target_watermarked_psnr, target_watermarked_ssim = compute_quality(
                    target, target_watermarked
                )
                swap_comparison_psnr, swap_comparison_ssim = compute_quality(
                    swapped_clean, swapped_watermarked
                )
                clean_target_psnr, clean_target_ssim = compute_quality(
                    target_224, swapped_clean
                )
                wm_target_psnr, wm_target_ssim = compute_quality(
                    target_224, swapped_watermarked
                )

                row = {field: "" for field in RESULT_FIELDS}
                row.update(_static_result_values(pair, model, controls))
                row.update(
                    {
                        "decoded_watermarked_bits": _bits_text(decoded_wm_bits),
                        "decoded_watermarked_sha256": _bits_hash(decoded_wm_bits),
                        "decoded_unwatermarked_bits": _bits_text(decoded_clean_bits),
                        "decoded_unwatermarked_sha256": _bits_hash(decoded_clean_bits),
                        "target_watermarked_rgb_sha256": _rgb_sha256(
                            target_watermarked
                        ),
                        "swapped_clean_rgb_sha256": _rgb_sha256(swapped_clean),
                        "swapped_watermarked_rgb_sha256": _rgb_sha256(
                            swapped_watermarked
                        ),
                        "primary_decoder": decoder_name,
                        "registered_positive_score": _metric_text(
                            bit_accuracy(decoded_wm_bits, registered)
                        ),
                        "unwatermarked_negative_score": _metric_text(
                            bit_accuracy(decoded_clean_bits, registered)
                        ),
                        "wrong_message_negative_score": _metric_text(
                            bit_accuracy(decoded_wm_bits, wrong)
                        ),
                        "cross_record_negative_score": _metric_text(
                            bit_accuracy(decoded_wm_bits, cross)
                        ),
                        "target_watermarked_psnr": _metric_text(
                            target_watermarked_psnr
                        ),
                        "target_watermarked_ssim": _metric_text(
                            target_watermarked_ssim
                        ),
                        "swapped_clean_vs_watermarked_psnr": _metric_text(
                            swap_comparison_psnr
                        ),
                        "swapped_clean_vs_watermarked_ssim": _metric_text(
                            swap_comparison_ssim
                        ),
                        "swapped_clean_vs_target_psnr": _metric_text(
                            clean_target_psnr
                        ),
                        "swapped_clean_vs_target_ssim": _metric_text(
                            clean_target_ssim
                        ),
                        "swapped_watermarked_vs_target_psnr": _metric_text(
                            wm_target_psnr
                        ),
                        "swapped_watermarked_vs_target_ssim": _metric_text(
                            wm_target_ssim
                        ),
                        "arcface_source_target_cosine": _metric_text(
                            source_target_cosine
                        ),
                        "arcface_clean_source_cosine": _metric_text(
                            clean_source_cosine
                        ),
                        "arcface_clean_target_cosine": _metric_text(
                            clean_target_cosine
                        ),
                        "arcface_clean_identity_margin": _metric_text(clean_margin),
                        "arcface_clean_identity_migrated": "1" if clean_margin > 0 else "0",
                        "arcface_watermarked_source_cosine": _metric_text(
                            wm_source_cosine
                        ),
                        "arcface_watermarked_target_cosine": _metric_text(
                            wm_target_cosine
                        ),
                        "arcface_watermarked_identity_margin": _metric_text(wm_margin),
                        "arcface_watermarked_identity_migrated": (
                            "1" if wm_margin > 0 else "0"
                        ),
                        "source_embedding_sha256": identity_rows[
                            (pair_id, "SimSwap", "source")
                        ]["embedding_sha256"],
                        "target_embedding_sha256": identity_rows[
                            (pair_id, "SimSwap", "target")
                        ]["embedding_sha256"],
                        "swapped_clean_embedding_sha256": identity_rows[
                            (pair_id, "SimSwap", "swapped_clean")
                        ]["embedding_sha256"],
                        "swapped_watermarked_embedding_sha256": identity_rows[
                            wm_identity_key
                        ]["embedding_sha256"],
                        "error": "",
                    }
                )
                result_rows[key] = row

                if pair_index < args.artifact_limit:
                    model_slug = model.lower().replace("-", "_")
                    sample_dir = asset_dir / f"pair_{pair_index + 1:05d}"
                    _atomic_save_png(
                        sample_dir / f"{model_slug}_target_watermarked.png",
                        _resize_rgb(target_watermarked),
                    )
                    _atomic_save_png(
                        sample_dir / f"{model_slug}_swapped_watermarked.png",
                        swapped_watermarked,
                    )
            except Exception as exc:
                result_rows[key] = _error_result_row(
                    pair, model, controls, _safe_error("model_pipeline", exc)
                )

        if (pair_index + 1) % args.flush_every == 0:
            flush(pair_index + 1, "running")

    flush(args.num_pairs, "auditing")
    reloaded_identities = load_identity_rows(
        identities_path, identity_expected, expected_dim=identity_dim
    )
    reloaded_results = load_result_rows(
        results_path,
        pairs=pairs,
        registry=registry,
        identities=reloaded_identities,
        binding_lengths=binding_lengths,
        primary_decoders=primary_decoders,
        seed=args.seed,
    )
    errors = sum(bool(row["error"]) for row in reloaded_results.values())
    complete = (
        len(reloaded_results) == expected_results
        and len(reloaded_identities) == expected_identities
        and errors == 0
    )
    if not complete:
        incomplete = _partial_summary(
            results_path=results_path,
            identities_path=identities_path,
            result_rows=reloaded_results,
            identity_rows=reloaded_identities,
            expected_results=expected_results,
            expected_identities=expected_identities,
            run_class=_run_class(args.num_pairs, args.calibration_pairs),
            status="incomplete",
        )
        _atomic_write_json(summary_path, incomplete)
        progress = {
            "schema_version": "simswap-lfw-robustness-progress.v1",
            "status": "incomplete",
            "processed_pairs": args.num_pairs,
            "total_pairs": args.num_pairs,
            "result_rows": len(reloaded_results),
            "expected_result_rows": expected_results,
            "identity_embedding_rows": len(reloaded_identities),
            "expected_identity_embedding_rows": expected_identities,
            "error_rows": errors,
            "updated_at": int(time.time()),
        }
        _atomic_write_json(progress_path, progress)
        print(json.dumps(incomplete, indent=2, ensure_ascii=False, allow_nan=False))
        return 2

    _build_asset_manifest(asset_dir, asset_manifest_path)
    complete_summary = _complete_summary(
        args=args,
        protocol=protocol,
        engine_provenance=engine_provenance,
        bindings=bindings,
        pairs=pairs,
        results=reloaded_results,
        results_path=results_path,
        identities_path=identities_path,
        pair_manifest_path=pair_manifest_path,
        registry_path=registry_path,
        run_config_path=run_config_path,
        asset_manifest_path=asset_manifest_path,
    )
    _atomic_write_json(summary_path, complete_summary)
    _atomic_write_json(
        progress_path,
        {
            "schema_version": "simswap-lfw-robustness-progress.v1",
            "status": "complete",
            "processed_pairs": args.num_pairs,
            "total_pairs": args.num_pairs,
            "result_rows": len(reloaded_results),
            "expected_result_rows": expected_results,
            "identity_embedding_rows": len(reloaded_identities),
            "expected_identity_embedding_rows": expected_identities,
            "error_rows": 0,
            "updated_at": int(time.time()),
        },
    )
    print(json.dumps(complete_summary, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
