#!/usr/bin/env python3
"""Generate identity-disjoint LFW samples and 152-D LIDMark payloads.

Payload dimensions 0..135 contain 68 normalized 2-D facial landmarks. The
remaining 16 dimensions contain a deterministic collision-free bipolar code
shared by every image of the same identity. Heavy ML dependencies are loaded
only after the process GPU mask has been validated, which also keeps the pure
partition/configuration helpers importable in CPU-only test environments.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
from typing import Any, Iterable


PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.runtime import DATA_ROOT, logical_path  # noqa: E402


SCRIPT_VERSION = "1.1.0"
SPLIT_ORDER = ("train", "val", "test")
SPLIT_RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}
SPLIT_DOMAIN = "JianYuanShield-LFW-identity-disjoint-v1"
RESOLUTIONS = (128, 256)
PAYLOAD_LENGTH = 152
IDENTITY_BITS = 16
_SINGLE_GPU_PATTERN = re.compile(r"[0-9]+")


def parse_visible_gpu(value: str | None) -> int:
    """Return the one physical GPU exposed through CUDA_VISIBLE_DEVICES."""
    if value is None or not _SINGLE_GPU_PATTERN.fullmatch(value.strip()):
        raise RuntimeError(
            "CUDA_VISIBLE_DEVICES must contain exactly one non-negative GPU index"
        )
    return int(value.strip())


def require_visible_gpu(expected_physical_gpu: int | None) -> int:
    physical_gpu = parse_visible_gpu(os.environ.get("CUDA_VISIBLE_DEVICES"))
    if expected_physical_gpu is not None and physical_gpu != expected_physical_gpu:
        raise RuntimeError(
            "CUDA_VISIBLE_DEVICES does not match --expected-physical-gpu: "
            f"{physical_gpu} != {expected_physical_gpu}"
        )
    return physical_gpu


def load_ml_dependencies() -> None:
    """Import GPU/image packages after validating the external device mask."""
    global Image, crop, face_alignment, get_preds_fromhm, np, pil_to_tensor, torch

    import numpy as np_module
    import torch as torch_module
    from PIL import Image as image_module
    from torchvision.transforms.functional import pil_to_tensor as pil_to_tensor_function
    import face_alignment as face_alignment_module
    from face_alignment.utils import crop as crop_function
    from face_alignment.utils import get_preds_fromhm as get_preds_function

    np = np_module
    torch = torch_module
    Image = image_module
    pil_to_tensor = pil_to_tensor_function
    face_alignment = face_alignment_module
    crop = crop_function
    get_preds_fromhm = get_preds_function


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    atomic_write_bytes(path, (payload + "\n").encode("utf-8"))


def atomic_write_npy(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        np.save(stream, value, allow_pickle=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def image_inventory(raw_root: Path, processed_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not raw_root.is_dir():
        raise FileNotFoundError(f"LFW identity directory does not exist: {raw_root}")
    for identity_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        for raw_path in sorted(identity_dir.glob("*.jpg")):
            paths = {
                resolution: processed_root / f"lfw_{resolution}" / "test" / raw_path.name
                for resolution in RESOLUTIONS
            }
            missing = [logical_path(path) for path in paths.values() if not path.is_file()]
            if missing:
                raise FileNotFoundError(f"missing preprocessed image(s): {missing}")
            records.append(
                {
                    "identity": identity_dir.name,
                    "filename": raw_path.name,
                    "raw_path": raw_path,
                    "processed_paths": paths,
                }
            )
    if not records:
        raise RuntimeError(f"no LFW images found below {logical_path(raw_root)}")
    filenames = [record["filename"] for record in records]
    if len(filenames) != len(set(filenames)):
        raise RuntimeError("flattened LFW filenames are not unique")
    return records


def identity_partition(
    records: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, int]]:
    """Partition complete identities while closely matching image-count ratios."""
    counts: dict[str, int] = {}
    for record in records:
        identity = str(record["identity"])
        counts[identity] = counts.get(identity, 0) + 1
    if not counts:
        raise ValueError("records must contain at least one identity")

    def identity_digest(identity: str) -> bytes:
        message = f"{SPLIT_DOMAIN}\0{identity}".encode("utf-8")
        return hashlib.sha256(message).digest()

    ordered = sorted(
        counts,
        key=lambda identity: (-counts[identity], identity_digest(identity), identity),
    )
    total = sum(counts.values())
    targets = {split: total * SPLIT_RATIOS[split] for split in SPLIT_ORDER}
    assigned_counts = {split: 0 for split in SPLIT_ORDER}
    partition: dict[str, str] = {}
    for identity in ordered:
        split = min(
            SPLIT_ORDER,
            key=lambda name: (
                assigned_counts[name] / targets[name],
                SPLIT_ORDER.index(name),
            ),
        )
        partition[identity] = split
        assigned_counts[split] += counts[identity]
    return partition, counts


def identity_codes(identities: Iterable[str]) -> dict[str, int]:
    ordered = sorted(set(identities))
    if len(ordered) > 2**IDENTITY_BITS:
        raise RuntimeError("more identities than the 16-bit code space")
    return {identity: code for code, identity in enumerate(ordered)}


def bipolar_code_values(code: int) -> tuple[int, ...]:
    if not 0 <= code < 2**IDENTITY_BITS:
        raise ValueError(f"identity code is outside uint16: {code}")
    return tuple(1 if (code >> shift) & 1 else -1 for shift in range(15, -1, -1))


def bipolar_code(code: int) -> Any:
    return np.asarray(bipolar_code_values(code), dtype=np.float32)


def load_image_batch(records: list[dict[str, Any]]) -> Any:
    tensors = []
    for record in records:
        with Image.open(record["processed_paths"][256]) as image:
            rgb = image.convert("RGB")
            if rgb.size != (256, 256):
                raise ValueError(
                    f"unexpected image size {rgb.size}: {record['filename']}"
                )
            tensors.append(pil_to_tensor(rgb))
    return torch.stack(tensors, dim=0)


def select_face_boxes(boxes: list[Any]) -> tuple[list[Any], list[int]]:
    selected: list[Any] = []
    missing: list[int] = []
    for index, candidates in enumerate(boxes):
        if candidates is None or len(candidates) == 0:
            selected.append([])
            missing.append(index)
            continue
        best = max(
            candidates,
            key=lambda box: (
                float(box[4]),
                float((box[2] - box[0]) * (box[3] - box[1])),
            ),
        )
        selected.append([best])
    return selected, missing


def detect_batch(aligner: Any, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    image_batch = load_image_batch(records)
    detected_boxes = aligner.face_detector.detect_from_batch(image_batch)
    selected_boxes, missing = select_face_boxes(detected_boxes)
    missing_set = set(missing)
    results: list[dict[str, Any]] = [
        {"ok": False, "reason": "face_not_detected", "bbox_count": 0}
        if index in missing_set
        else {}
        for index in range(len(records))
    ]

    valid_indices = [index for index in range(len(records)) if index not in missing_set]
    if not valid_indices:
        return results
    centers: list[Any] = []
    scales: list[float] = []
    cropped_faces: list[Any] = []
    for record_index in valid_indices:
        box = selected_boxes[record_index][0]
        center = torch.tensor(
            [box[2] - (box[2] - box[0]) / 2.0, box[3] - (box[3] - box[1]) / 2.0],
            dtype=torch.float32,
        )
        center[1] -= (box[3] - box[1]) * 0.12
        scale = float(
            (box[2] - box[0] + box[3] - box[1])
            / aligner.face_detector.reference_scale
        )
        image = image_batch[record_index].numpy().transpose(1, 2, 0)
        cropped = crop(image, center, scale)
        centers.append(center)
        scales.append(scale)
        cropped_faces.append(torch.from_numpy(cropped.transpose(2, 0, 1)))

    face_batch = torch.stack(cropped_faces).to(device=aligner.device, dtype=aligner.dtype)
    face_batch.div_(255.0)
    with torch.inference_mode():
        heatmaps = aligner.face_alignment_net(face_batch).detach()
    heatmaps_numpy = heatmaps.to(device="cpu", dtype=torch.float32).numpy()
    for valid_position, record_index in enumerate(valid_indices):
        _, points_original, _ = get_preds_fromhm(
            heatmaps_numpy[valid_position : valid_position + 1],
            centers[valid_position].numpy(),
            scales[valid_position],
        )
        points = np.asarray(points_original, dtype=np.float32).reshape(68, 2)
        if points.shape != (68, 2):
            results[record_index] = {
                "ok": False,
                "reason": "unexpected_landmark_shape",
                "shape": list(points.shape),
                "bbox_count": len(detected_boxes[record_index]),
            }
            continue
        if not np.isfinite(points).all():
            results[record_index] = {
                "ok": False,
                "reason": "non_finite_landmarks",
                "bbox_count": len(detected_boxes[record_index]),
            }
            continue
        normalized = points / np.asarray([256.0, 256.0], dtype=np.float32)
        clipped_coordinate_count = int(
            np.count_nonzero((normalized < 0.0) | (normalized > 1.0))
        )
        normalized = np.clip(normalized, 0.0, 1.0).astype(np.float32, copy=False)
        results[record_index] = {
            "ok": True,
            "landmarks": normalized.reshape(136),
            "bbox_count": len(detected_boxes[record_index]),
            "selected_bbox_score": float(selected_boxes[record_index][0][4]),
            "clipped_coordinate_count": clipped_coordinate_count,
        }
    return results


def initialize_aligner() -> Any:
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError(
            "expected exactly one CUDA device after applying CUDA_VISIBLE_DEVICES; "
            f"count={torch.cuda.device_count()}"
        )
    return face_alignment.FaceAlignment(
        face_alignment.LandmarksType.TWO_D,
        device="cuda:0",
        flip_input=False,
        face_detector="sfd",
        verbose=True,
    )


def detector_artifacts() -> list[dict[str, Any]]:
    checkpoint_root = Path(torch.hub.get_dir()) / "checkpoints"
    records = []
    for pattern in ("s3fd-*", "2DFAN4-*"):
        for path in sorted(checkpoint_root.glob(pattern)):
            if path.is_file():
                records.append(
                    {
                        "path": logical_path(path),
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    return records


def runtime_metadata(script_path: Path, physical_gpu: int) -> dict[str, Any]:
    return {
        "script_version": SCRIPT_VERSION,
        "script_path": logical_path(script_path),
        "script_sha256": sha256_file(script_path),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "torch": torch.__version__,
        "torchvision": package_version("torchvision"),
        "face_alignment": package_version("face-alignment"),
        "cuda_runtime": torch.version.cuda,
        "physical_gpu": physical_gpu,
        "visible_cuda_index": 0,
        "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
        "gpu_name": torch.cuda.get_device_name(0),
        "detector_artifacts": detector_artifacts(),
    }


def smoke_test(
    aligner: Any,
    inventory: list[dict[str, Any]],
    count: int,
    batch_size: int,
    report_path: Path,
    script_path: Path,
    physical_gpu: int,
) -> dict[str, Any]:
    ordered = sorted(
        inventory,
        key=lambda record: hashlib.sha256(
            f"{SPLIT_DOMAIN}\0smoke\0{record['filename']}".encode("utf-8")
        ).digest(),
    )[:count]
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    for offset in range(0, len(ordered), batch_size):
        batch = ordered[offset : offset + batch_size]
        detected = detect_batch(aligner, batch)
        for record, result in zip(batch, detected, strict=True):
            outcomes.append(
                {
                    "identity": record["identity"],
                    "filename": record["filename"],
                    "ok": result["ok"],
                    "bbox_count": result.get("bbox_count", 0),
                    "reason": result.get("reason"),
                    "clipped_coordinate_count": result.get(
                        "clipped_coordinate_count", 0
                    ),
                }
            )
    success_count = sum(int(outcome["ok"]) for outcome in outcomes)
    report = {
        "schema_version": 1,
        "mode": "smoke",
        "requested_count": count,
        "processed_count": len(outcomes),
        "success_count": success_count,
        "failure_count": len(outcomes) - success_count,
        "success_rate": success_count / len(outcomes),
        "elapsed_seconds": time.perf_counter() - started,
        "outcomes": outcomes,
        "runtime": runtime_metadata(script_path, physical_gpu),
    }
    atomic_write_json(report_path, report)
    return report


def ensure_hardlink(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if (
            destination.stat().st_size != source.stat().st_size
            or sha256_file(destination) != sha256_file(source)
        ):
            raise RuntimeError(
                f"existing output differs from source: {logical_path(destination)}"
            )
        return
    os.link(source, destination)


def file_manifest(output_root: Path, manifests_root: Path) -> tuple[Path, int, str]:
    data_paths: list[Path] = []
    for top_level in ("image", "watermark_152"):
        root = output_root / top_level
        data_paths.extend(path for path in root.rglob("*") if path.is_file())
    lines = []
    for path in sorted(
        data_paths, key=lambda value: value.relative_to(output_root).as_posix()
    ):
        relative = path.relative_to(output_root).as_posix()
        lines.append(f"{sha256_file(path)}  {relative}\n")
    content = "".join(lines).encode("utf-8")
    target = manifests_root / "files.sha256"
    atomic_write_bytes(target, content)
    return target, len(lines), hashlib.sha256(content).hexdigest()


def generate_dataset(
    aligner: Any,
    inventory: list[dict[str, Any]],
    output_root: Path,
    batch_size: int,
    script_path: Path,
    physical_gpu: int,
) -> dict[str, Any]:
    partition, identity_image_counts = identity_partition(inventory)
    codes = identity_codes(record["identity"] for record in inventory)
    manifests_root = output_root / "manifests"
    manifests_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    failures: list[dict[str, Any]] = []
    generated = {
        resolution: {split: 0 for split in SPLIT_ORDER}
        for resolution in RESOLUTIONS
    }
    clipped_coordinates = 0
    multiple_face_images = 0

    for offset in range(0, len(inventory), batch_size):
        batch = inventory[offset : offset + batch_size]
        outcomes = detect_batch(aligner, batch)
        for record, outcome in zip(batch, outcomes, strict=True):
            split = partition[record["identity"]]
            if not outcome["ok"]:
                failures.append(
                    {
                        "identity": record["identity"],
                        "filename": record["filename"],
                        "split": split,
                        "reason": outcome.get("reason", "unknown"),
                        "bbox_count": outcome.get("bbox_count", 0),
                        "shape": outcome.get("shape"),
                    }
                )
                continue
            clipped_coordinates += int(outcome["clipped_coordinate_count"])
            multiple_face_images += int(outcome["bbox_count"] > 1)
            payload = np.concatenate(
                (outcome["landmarks"], bipolar_code(codes[record["identity"]])),
                dtype=np.float32,
            )
            if (
                payload.shape != (PAYLOAD_LENGTH,)
                or payload.dtype != np.float32
                or not np.isfinite(payload).all()
            ):
                raise RuntimeError(f"invalid payload generated for {record['filename']}")
            for resolution in RESOLUTIONS:
                image_destination = (
                    output_root
                    / "image"
                    / f"lfw_{resolution}"
                    / split
                    / record["filename"]
                )
                payload_destination = (
                    output_root
                    / "watermark_152"
                    / "lfw"
                    / str(resolution)
                    / split
                    / record["filename"].replace(".jpg", ".npy")
                )
                ensure_hardlink(record["processed_paths"][resolution], image_destination)
                atomic_write_npy(payload_destination, payload)
                generated[resolution][split] += 1
        processed = min(offset + len(batch), len(inventory))
        print(
            json.dumps(
                {
                    "progress": processed,
                    "total": len(inventory),
                    "failures": len(failures),
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                },
                sort_keys=True,
            ),
            flush=True,
        )

    identity_records = [
        {
            "identity": identity,
            "uint16_code": codes[identity],
            "bipolar_code": list(bipolar_code_values(codes[identity])),
            "split": partition[identity],
            "source_image_count": identity_image_counts[identity],
        }
        for identity in sorted(codes)
    ]
    atomic_write_json(
        manifests_root / "identity_map.json",
        {
            "schema_version": 1,
            "encoding": (
                "lexicographically sorted identity -> uint16 big-endian bits -> {-1,+1}"
            ),
            "collision_free": len(set(codes.values())) == len(codes),
            "identities": identity_records,
        },
    )
    split_summary = {
        split: {
            "identity_count": sum(int(value == split) for value in partition.values()),
            "source_image_count": sum(
                identity_image_counts[identity]
                for identity, assigned_split in partition.items()
                if assigned_split == split
            ),
            "successful_image_count": generated[256][split],
            "failed_image_count": sum(int(item["split"] == split) for item in failures),
            "identities": sorted(
                identity for identity, value in partition.items() if value == split
            ),
        }
        for split in SPLIT_ORDER
    }
    atomic_write_json(
        manifests_root / "splits.json",
        {
            "schema_version": 1,
            "algorithm": (
                "sort identities by descending image count with SHA-256 domain tie-break; "
                "greedily assign to the split with the lowest target fill ratio"
            ),
            "domain": SPLIT_DOMAIN,
            "ratios": SPLIT_RATIOS,
            "identity_disjoint": True,
            "splits": split_summary,
        },
    )
    failure_lines = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
        for item in failures
    )
    atomic_write_bytes(manifests_root / "failures.jsonl", failure_lines.encode("utf-8"))
    file_manifest_path, file_count, file_manifest_sha256 = file_manifest(
        output_root, manifests_root
    )

    raw_root = Path(inventory[0]["raw_path"]).parents[1]
    source_archive = raw_root.parent / "lfw.tgz"
    source = {
        "raw_root": logical_path(raw_root),
        "source_image_count": len(inventory),
        "identity_count": len(codes),
    }
    if source_archive.is_file():
        source["archive"] = {
            "path": logical_path(source_archive),
            "size_bytes": source_archive.stat().st_size,
            "sha256": sha256_file(source_archive),
        }
    report = {
        "schema_version": 1,
        "mode": "generate",
        "source": source,
        "output_root": logical_path(output_root),
        "payload": {
            "shape": [PAYLOAD_LENGTH],
            "dtype": "float32",
            "landmarks": "68 (x,y) points divided by [256,256] and clipped to [0,1]",
            "identity": "collision-free uint16 bipolar identity code shared by an identity",
        },
        "generated_counts": generated,
        "failure_count": len(failures),
        "clipped_coordinate_count": clipped_coordinates,
        "multiple_face_image_count": multiple_face_images,
        "elapsed_seconds": time.perf_counter() - started,
        "identity_disjoint": True,
        "split_summary": split_summary,
        "file_hash_manifest": {
            "path": logical_path(file_manifest_path),
            "entry_count": file_count,
            "sha256": file_manifest_sha256,
        },
        "runtime": runtime_metadata(script_path, physical_gpu),
    }
    atomic_write_json(manifests_root / "dataset_manifest.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "generate"), required=True)
    parser.add_argument("--raw-root", type=Path, default=DATA_ROOT / "lfw" / "lfw")
    parser.add_argument(
        "--processed-root",
        type=Path,
        default=DATA_ROOT / "lfw" / "processed" / "image",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DATA_ROOT / "lfw" / "lidmark_identity_disjoint",
    )
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--smoke-count", type=int, default=32)
    parser.add_argument("--expected-physical-gpu", type=int, default=2)
    return parser.parse_args(argv)


def resolve_data_path(path: Path, field: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(DATA_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"{field} must be below JYS_DATA_ROOT") from error
    return resolved


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size < 1 or args.smoke_count < 1:
        raise ValueError("batch-size and smoke-count must be positive")
    if args.expected_physical_gpu < 0:
        raise ValueError("expected-physical-gpu must be non-negative")
    physical_gpu = require_visible_gpu(args.expected_physical_gpu)
    raw_root = resolve_data_path(args.raw_root, "raw-root")
    processed_root = resolve_data_path(args.processed_root, "processed-root")
    output_root = resolve_data_path(args.output_root, "output-root")
    sys.dont_write_bytecode = True
    load_ml_dependencies()
    inventory = image_inventory(raw_root, processed_root)
    aligner = initialize_aligner()
    script_path = Path(__file__).resolve()
    if args.mode == "smoke":
        report_path = output_root / "manifests" / "smoke_report.json"
        report = smoke_test(
            aligner,
            inventory,
            min(args.smoke_count, len(inventory)),
            args.batch_size,
            report_path,
            script_path,
            physical_gpu,
        )
    else:
        report = generate_dataset(
            aligner,
            inventory,
            output_root,
            args.batch_size,
            script_path,
            physical_gpu,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    if int(report["failure_count"]) != 0:
        raise RuntimeError(f"LIDMark data generation recorded {report['failure_count']} failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
