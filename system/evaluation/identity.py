from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath


IDENTITY_DERIVATION = "dataset_parent_or_lfw_filename_suffix.v2"
_GENERIC_DATASET_PARTS = frozenset({
    "data",
    "dataset",
    "datasets",
    "image",
    "images",
    "lfw",
    "train",
    "training",
    "val",
    "valid",
    "validation",
    "test",
    "testing",
    "unknown",
})
_LFW_INDEX_SUFFIX = re.compile(r"^(?P<identity>.+)_(?P<index>[0-9]{4})$")


def identity_label(identifier: str) -> str:
    """Derive one stable identity label from nested or flat LFW paths."""

    path = PurePosixPath(identifier)
    if not identifier or path.is_absolute() or ".." in path.parts:
        raise ValueError("identity source must be a dataset-relative path")

    directories = path.parts[:-1]
    for part in directories:
        if part and part.lower() not in _GENERIC_DATASET_PARTS:
            return part

    match = _LFW_INDEX_SUFFIX.fullmatch(path.stem)
    label = match.group("identity") if match else path.stem
    if not label:
        raise ValueError("identity label is empty")
    return label


def calibration_identity_sha256(identifier: str) -> str:
    label = identity_label(identifier)
    payload = f"threshold-calibration.identity.v2\0{label}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
