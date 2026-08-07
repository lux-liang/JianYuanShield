from __future__ import annotations

import csv
import hashlib
import hmac
import json
import math
import re
from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any

from system.evaluation.run_metadata import sha256_file
from system.evaluation.runtime import logical_path, resolve_logical_path
from system.evaluation.attacks import ATTACKS

from .signing import MANIFEST_PATH, verify_evidence_bundle
from .settings import settings


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_tree(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_tree(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_finite_tree(item) for item in value)
    return value is None or isinstance(value, (str, int, bool))


def _wilson95(successes: int, total: int) -> dict[str, Any]:
    """Recompute the exact interval emitted by the LIDMark evaluator."""

    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("Wilson interval requires 0 <= successes <= total")
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return {
        "successes": successes,
        "total": total,
        "estimate": proportion,
        "lower": 0.0 if successes == 0 else max(0.0, center - margin),
        "upper": 1.0 if successes == total else min(1.0, center + margin),
        "confidence_level": 0.95,
        "method": "Wilson score interval",
    }


def _wilson_matches(value: Any, *, successes: int, total: int) -> bool:
    if not isinstance(value, dict) or total <= 0:
        return False
    expected = _wilson95(successes, total)
    if value.get("successes") != successes or value.get("total") != total:
        return False
    if value.get("method") != expected["method"]:
        return False
    for field in ("estimate", "lower", "upper", "confidence_level"):
        try:
            actual = float(value[field])
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isfinite(actual) or abs(actual - float(expected[field])) > 1e-12:
            return False
    return True


def _hash_matches(path: Path | None, expected: Any) -> bool:
    return bool(
        path
        and path.is_file()
        and isinstance(expected, str)
        and _SHA256_RE.fullmatch(expected)
        and sha256_file(path) == expected.lower()
    )


def _resolve(reference: Any) -> Path | None:
    if not isinstance(reference, str) or not reference:
        return None
    return resolve_logical_path(reference)


def _load_dataset_manifest(path: Path | None, sample_count: Any) -> bool:
    if path is None or not path.is_file() or not isinstance(sample_count, int):
        return False
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    files = payload.get("files")
    schema_version = payload.get("schema_version")
    if (
        schema_version not in {"dataset-manifest.v1", "waveguard-dataset-manifest.v1"}
        or payload.get("sample_count") != sample_count
        or not isinstance(files, list)
        or len(files) != sample_count
        or payload.get("files_digest_sha256") != _canonical_sha256(files)
    ):
        return False
    paths = [item.get("path") for item in files if isinstance(item, dict)]
    files_valid = (
        len(paths) == sample_count
        and len(set(paths)) == sample_count
        and all(
            isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and not Path(item["path"]).is_absolute()
            and ".." not in Path(item["path"]).parts
            and isinstance(item.get("size_bytes"), int)
            and item["size_bytes"] >= 0
            and isinstance(item.get("sha256"), str)
            and bool(_SHA256_RE.fullmatch(item["sha256"]))
            for item in files
        )
    )
    if not files_valid or schema_version == "dataset-manifest.v1":
        return files_valid

    distribution = payload.get("identity_distribution")
    if (
        not isinstance(distribution, list)
        or payload.get("unique_identity_count") != len(distribution)
        or payload.get("identity_distribution_sha256") != _canonical_sha256(distribution)
    ):
        return False
    declared: Counter[str] = Counter()
    for item in distribution:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("identity_sha256"), str)
            or not _SHA256_RE.fullmatch(item["identity_sha256"])
            or not isinstance(item.get("image_count"), int)
            or item["image_count"] <= 0
            or item["identity_sha256"] in declared
        ):
            return False
        declared[item["identity_sha256"]] = item["image_count"]
    observed = Counter(item.get("identity_sha256") for item in files)
    return declared == observed and sum(declared.values()) == sample_count


def _dataset_manifest_bindings(path: Path | None) -> dict[str, str | None]:
    if path is None or not path.is_file():
        return {"sample_path_sha256": None, "message_sha256": None}
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, ValueError, TypeError):
        return {"sample_path_sha256": None, "message_sha256": None}
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return {"sample_path_sha256": None, "message_sha256": None}
    sample_paths: list[dict[str, str]] = []
    messages: list[dict[str, str]] = []
    messages_complete = True
    for item in files:
        if not isinstance(item, dict):
            return {"sample_path_sha256": None, "message_sha256": None}
        source_path = item.get("path")
        image_id = item.get("sample_id", source_path)
        if not isinstance(image_id, str) or not isinstance(source_path, str):
            return {"sample_path_sha256": None, "message_sha256": None}
        sample_paths.append({"image_id": image_id, "source_path": source_path})
        message_hash = item.get("message_sha256")
        if isinstance(message_hash, str) and _SHA256_RE.fullmatch(message_hash):
            messages.append({
                "image_id": image_id,
                "message_sha256": message_hash.lower(),
            })
        else:
            messages_complete = False
    sample_paths.sort(key=lambda item: item["image_id"])
    messages.sort(key=lambda item: item["image_id"])
    return {
        "sample_path_sha256": _canonical_sha256(sample_paths),
        "message_sha256": _canonical_sha256(messages) if messages_complete else None,
    }


def _csv_structure_valid(
    results_path: Path,
    *,
    sample_count: int,
    attack_ids: list[str],
    summary: dict[str, Any] | None = None,
    success_threshold: float | None = None,
    attack_config_hashes: dict[str, str] | None = None,
    protocol_attack_hashes: dict[str, str] | None = None,
) -> tuple[bool, dict[str, Any]]:
    try:
        with results_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, csv.Error, UnicodeError):
        return False, {"rows": 0, "duplicates": 0, "errors": 0, "attack_counts": {}}

    attack_counts: Counter[str] = Counter()
    keys: set[tuple[str, str]] = set()
    duplicates = 0
    errors = 0
    path_errors = 0
    row_shape_errors = 0
    numeric_errors = 0
    message_errors = 0
    success_errors = 0
    relation_errors = 0
    contract_errors = 0
    summary_mismatches: list[str] = []
    message_by_image: dict[str, str] = {}
    source_by_image: dict[str, str] = {}
    attack_hash_by_attack: dict[str, str] = {}
    images_by_attack: dict[str, set[str]] = defaultdict(set)
    values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    success_counts: Counter[str] = Counter()
    method = str((summary or {}).get("method") or "").lower()
    if method == "sepmark":
        primary_accuracy, primary_error = "bit_accuracy_c", "bit_error_c"
    elif method == "waveguard":
        primary_accuracy, primary_error = "bit_accuracy_tracer", "bit_error_tracer"
    elif method == "lidmark":
        primary_accuracy, primary_error = "bit_accuracy", "ber"
    else:
        primary_accuracy, primary_error = "bit_accuracy", "bit_error"
    metric_fields = {
        "bit_error": ("mean_bit_error", 0.0, 1.0),
        "bit_accuracy": ("mean_bit_accuracy", 0.0, 1.0),
        "bit_error_c": ("mean_bit_error_c", 0.0, 1.0),
        "bit_accuracy_c": ("mean_bit_accuracy_c", 0.0, 1.0),
        "bit_error_rf": ("mean_bit_error_rf", 0.0, 1.0),
        "bit_accuracy_rf": ("mean_bit_accuracy_rf", 0.0, 1.0),
        "bit_error_tracer": ("mean_bit_error_tracer", 0.0, 1.0),
        "bit_accuracy_tracer": ("mean_bit_accuracy_tracer", 0.0, 1.0),
        "bit_error_detector": ("mean_bit_error_detector", 0.0, 1.0),
        "bit_accuracy_detector": ("mean_bit_accuracy_detector", 0.0, 1.0),
        "ber": ("mean_ber", 0.0, 1.0),
        "psnr": ("mean_psnr", 0.0, None),
        "ssim": ("mean_ssim", -1.0, 1.0),
        "landmark_aed_px": ("mean_landmark_aed_px", 0.0, None),
    }
    metric_columns = [field for field in metric_fields if field in fieldnames]
    required_columns = {
        "image_id",
        "source_path",
        "attack_type",
        "attack_config_sha256",
        "message_sha256",
        "error",
        primary_accuracy,
        primary_error,
        "success",
    }
    schema_valid = (
        len(fieldnames) == len(set(fieldnames))
        and required_columns.issubset(fieldnames)
    )
    for index, row in enumerate(rows):
        row_shape_errors += int(None in row)
        attack = str(row.get("attack_type") or "")
        image_id = str(row.get("image_id") or "")
        source_path = str(row.get("source_path") or "")
        row_shape_errors += int(not attack or not image_id or not source_path)
        key = (image_id, attack)
        duplicates += int(key in keys)
        keys.add(key)
        attack_counts[attack] += 1
        images_by_attack[attack].add(image_id)
        errors += int(bool(str(row.get("error") or "").strip()))
        for field in ("image_id", "source_path", "payload_path"):
            raw_path = str(row.get(field) or "")
            if raw_path and (Path(raw_path).is_absolute() or ".." in Path(raw_path).parts):
                path_errors += 1
        previous_source = source_by_image.setdefault(image_id, source_path)
        path_errors += int(previous_source != source_path)

        parsed: dict[str, float] = {}
        for field in metric_columns:
            raw = row.get(field)
            if raw in (None, ""):
                numeric_errors += 1
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                numeric_errors += 1
                continue
            lower, upper = metric_fields[field][1:]
            if (
                not math.isfinite(number)
                or number < lower
                or (upper is not None and number > upper)
            ):
                numeric_errors += 1
                continue
            parsed[field] = number
            values[attack][field].append(number)

        for error_field, accuracy_field in (
            ("bit_error", "bit_accuracy"),
            ("bit_error_c", "bit_accuracy_c"),
            ("bit_error_rf", "bit_accuracy_rf"),
            ("bit_error_tracer", "bit_accuracy_tracer"),
            ("bit_error_detector", "bit_accuracy_detector"),
            ("ber", "bit_accuracy"),
        ):
            if error_field in parsed and accuracy_field in parsed:
                relation_errors += int(
                    abs(parsed[accuracy_field] + parsed[error_field] - 1.0) > 1e-6
                )
        if "bit_errors" in fieldnames or "identity_bit_length" in fieldnames:
            try:
                bit_errors = int(str(row.get("bit_errors") or ""))
                bit_length = int(str(row.get("identity_bit_length") or ""))
            except (TypeError, ValueError):
                relation_errors += 1
            else:
                if bit_errors < 0 or bit_length <= 0 or bit_errors > bit_length:
                    relation_errors += 1
                elif "ber" in parsed:
                    relation_errors += int(
                        abs(parsed["ber"] - bit_errors / bit_length) > 1e-9
                    )
                if "identity_exact_match" in fieldnames:
                    exact = str(row.get("identity_exact_match") or "")
                    relation_errors += int(
                        exact not in {"0", "1"} or (exact == "1") != (bit_errors == 0)
                    )
        raw_success = str(row.get("success") or "")
        if raw_success not in {"0", "1"} or primary_accuracy not in parsed:
            success_errors += 1
        else:
            success_counts[attack] += int(raw_success)
            if success_threshold is not None:
                success_errors += int(
                    (parsed[primary_accuracy] >= success_threshold) != (raw_success == "1")
                )

        message_bits = row.get("message_bits")
        message_hash = str(row.get("message_sha256") or "")
        if message_bits not in (None, ""):
            bits = str(message_bits)
            expected_length = (summary or {}).get("message_length")
            if (
                any(bit not in "01" for bit in bits)
                or not isinstance(expected_length, int)
                or len(bits) != expected_length
                or not _SHA256_RE.fullmatch(message_hash)
                or hashlib.sha256(bytes(int(bit) for bit in bits)).hexdigest() != message_hash.lower()
            ):
                message_errors += 1
        elif not _SHA256_RE.fullmatch(message_hash):
            message_errors += 1
        if message_hash:
            previous = message_by_image.setdefault(image_id, message_hash.lower())
            message_errors += int(previous != message_hash.lower())

        attack_hash = str(row.get("attack_config_sha256") or "").lower()
        if not _SHA256_RE.fullmatch(attack_hash):
            message_errors += 1
        else:
            previous_hash = attack_hash_by_attack.setdefault(attack, attack_hash)
            message_errors += int(previous_hash != attack_hash)
            if attack_config_hashes is not None:
                contract_errors += int(
                    attack_hash != attack_config_hashes.get(attack, "").lower()
                )

        if "protocol_attack_sha256" in fieldnames:
            protocol_attack_hash = str(
                row.get("protocol_attack_sha256") or ""
            ).lower()
            if not _SHA256_RE.fullmatch(protocol_attack_hash):
                contract_errors += 1
            elif protocol_attack_hashes is not None:
                contract_errors += int(
                    protocol_attack_hash
                    != protocol_attack_hashes.get(attack, "").lower()
                )

        if "identity_sha256" in fieldnames and not _SHA256_RE.fullmatch(
            str(row.get("identity_sha256") or "")
        ):
            message_errors += 1

        if "primary_decoder" in fieldnames:
            declared_decoder = str((summary or {}).get("primary_decoder") or "")
            row_decoder = str(row.get("primary_decoder") or "")
            relation_errors += int(
                not row_decoder
                or (bool(declared_decoder) and row_decoder != declared_decoder)
            )

    if attack_ids:
        expected_images = images_by_attack.get(attack_ids[0], set())
        if len(expected_images) != sample_count:
            summary_mismatches.append("sample_coverage")
        for attack in attack_ids:
            if images_by_attack.get(attack, set()) != expected_images:
                summary_mismatches.append(f"{attack}:sample_coverage")

    attacks_summary = (summary or {}).get("attacks")
    if not isinstance(attacks_summary, dict) or set(attacks_summary) != set(attack_ids):
        summary_mismatches.append("attack_set")
    else:
        for attack in attack_ids:
            reported = attacks_summary.get(attack)
            if not isinstance(reported, dict):
                summary_mismatches.append(f"{attack}:record")
                continue
            if reported.get("status") != "complete":
                summary_mismatches.append(f"{attack}:status")
            reported_count = reported.get("count", reported.get("row_count"))
            if reported_count != attack_counts[attack]:
                summary_mismatches.append(f"{attack}:count")
            if reported.get("valid_count") != attack_counts[attack]:
                summary_mismatches.append(f"{attack}:valid_count")
            if reported.get("error_count") != 0:
                summary_mismatches.append(f"{attack}:error_count")
            for field in metric_columns:
                summary_field = metric_fields[field][0]
                if summary_field not in reported:
                    summary_mismatches.append(f"{attack}:{summary_field}:missing")
                    continue
                field_values = values[attack][field]
                expected_mean = sum(field_values) / len(field_values) if field_values else None
                try:
                    actual_mean = float(reported[summary_field])
                except (TypeError, ValueError):
                    summary_mismatches.append(f"{attack}:{summary_field}")
                    continue
                if (
                    expected_mean is None
                    or not math.isfinite(actual_mean)
                    or abs(actual_mean - expected_mean) > 1e-7
                ):
                    summary_mismatches.append(f"{attack}:{summary_field}")
            if "mean_bit_accuracy" not in reported:
                summary_mismatches.append(f"{attack}:mean_bit_accuracy:missing")
            elif primary_accuracy in values[attack]:
                expected_primary = sum(values[attack][primary_accuracy]) / len(
                    values[attack][primary_accuracy]
                )
                try:
                    actual_primary = float(reported["mean_bit_accuracy"])
                except (TypeError, ValueError):
                    actual_primary = math.nan
                if not math.isfinite(actual_primary) or abs(actual_primary - expected_primary) > 1e-7:
                    summary_mismatches.append(f"{attack}:mean_bit_accuracy_primary")
            generic_error_required = method != "lidmark"
            if generic_error_required and "mean_bit_error" not in reported:
                summary_mismatches.append(f"{attack}:mean_bit_error:missing")
            elif "mean_bit_error" in reported and primary_error in values[attack]:
                expected_primary_error = sum(values[attack][primary_error]) / len(
                    values[attack][primary_error]
                )
                try:
                    actual_primary_error = float(reported["mean_bit_error"])
                except (TypeError, ValueError):
                    actual_primary_error = math.nan
                if (
                    not math.isfinite(actual_primary_error)
                    or abs(actual_primary_error - expected_primary_error) > 1e-7
                ):
                    summary_mismatches.append(f"{attack}:mean_bit_error_primary")
            if method == "lidmark":
                if not _wilson_matches(
                    reported.get("success_rate_wilson95"),
                    successes=success_counts[attack],
                    total=attack_counts[attack],
                ):
                    summary_mismatches.append(f"{attack}:success_rate_wilson95")
            elif "success_rate" in reported:
                expected_rate = success_counts[attack] / attack_counts[attack]
                try:
                    actual_rate = float(reported["success_rate"])
                except (TypeError, ValueError):
                    actual_rate = math.nan
                if not math.isfinite(actual_rate) or abs(actual_rate - expected_rate) > 1e-7:
                    summary_mismatches.append(f"{attack}:success_rate")
            else:
                summary_mismatches.append(f"{attack}:success_rate:missing")

    if method == "lidmark":
        overall = (summary or {}).get("overall")
        if not isinstance(overall, dict):
            summary_mismatches.append("overall")
        else:
            for field in metric_columns:
                summary_field = metric_fields[field][0]
                flat_values = [
                    value
                    for attack in attack_ids
                    for value in values[attack][field]
                ]
                if summary_field not in overall or not flat_values:
                    summary_mismatches.append(f"overall:{summary_field}")
                    continue
                try:
                    actual_mean = float(overall[summary_field])
                except (TypeError, ValueError):
                    actual_mean = math.nan
                expected_mean = sum(flat_values) / len(flat_values)
                if not math.isfinite(actual_mean) or abs(actual_mean - expected_mean) > 1e-7:
                    summary_mismatches.append(f"overall:{summary_field}")
            total_rows = sum(attack_counts.values())
            if not _wilson_matches(
                overall.get("success_rate_wilson95"),
                successes=sum(success_counts.values()),
                total=total_rows,
            ):
                summary_mismatches.append("overall:success_rate_wilson95")

    expected_rows = sample_count * len(attack_ids)
    valid = all([
        schema_valid,
        len(rows) == expected_rows,
        duplicates == 0,
        errors == 0,
        path_errors == 0,
        row_shape_errors == 0,
        numeric_errors == 0,
        message_errors == 0,
        success_errors == 0,
        relation_errors == 0,
        contract_errors == 0,
        not summary_mismatches,
        set(attack_counts) == set(attack_ids),
        all(attack_counts[attack] == sample_count for attack in attack_ids),
    ])
    return valid, {
        "rows": len(rows),
        "expected_rows": expected_rows,
        "duplicates": duplicates,
        "errors": errors,
        "schema_valid": schema_valid,
        "path_errors": path_errors,
        "row_shape_errors": row_shape_errors,
        "numeric_errors": numeric_errors,
        "message_errors": message_errors,
        "success_errors": success_errors,
        "relation_errors": relation_errors,
        "contract_errors": contract_errors,
        "summary_mismatches": summary_mismatches,
        "primary_accuracy_field": primary_accuracy,
        "sample_binding_sha256": _canonical_sha256([
            {
                "image_id": image_id,
                "source_path": source_by_image.get(image_id, ""),
                "message_sha256": message_by_image.get(image_id, ""),
            }
            for image_id in sorted(source_by_image)
        ]),
        "sample_path_binding_sha256": _canonical_sha256([
            {
                "image_id": image_id,
                "source_path": source_by_image.get(image_id, ""),
            }
            for image_id in sorted(source_by_image)
        ]),
        "message_binding_sha256": _canonical_sha256([
            {
                "image_id": image_id,
                "message_sha256": message_by_image.get(image_id, ""),
            }
            for image_id in sorted(message_by_image)
        ]),
        "attack_counts": dict(sorted(attack_counts.items())),
    }


def _quality_csv_structure_valid(
    quality_path: Path,
    *,
    sample_count: int,
    summary: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    try:
        with quality_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
    except (OSError, csv.Error, UnicodeError):
        return False, {"rows": 0, "expected_rows": sample_count}

    required = {
        "image_id",
        "source_path",
        "message_sha256",
        "watermarked_psnr",
        "watermarked_ssim",
        "error",
    }
    schema_valid = (
        len(fieldnames) == len(set(fieldnames))
        and required.issubset(fieldnames)
    )
    seen: set[str] = set()
    duplicates = 0
    errors = 0
    row_errors = 0
    path_errors = 0
    message_errors = 0
    psnr_values: list[float] = []
    ssim_values: list[float] = []
    bindings: list[dict[str, str]] = []
    expected_length = summary.get("message_length")
    for row in rows:
        row_errors += int(None in row)
        image_id = str(row.get("image_id") or "")
        source_path = str(row.get("source_path") or "")
        message_hash = str(row.get("message_sha256") or "").lower()
        row_errors += int(not image_id or not source_path)
        duplicates += int(image_id in seen)
        seen.add(image_id)
        errors += int(bool(str(row.get("error") or "").strip()))
        for raw_path in (image_id, source_path):
            if raw_path and (
                Path(raw_path).is_absolute() or ".." in Path(raw_path).parts
            ):
                path_errors += 1
        if not _SHA256_RE.fullmatch(message_hash):
            message_errors += 1
        message_bits = row.get("message_bits")
        if message_bits not in (None, ""):
            bits = str(message_bits)
            if (
                any(bit not in "01" for bit in bits)
                or not isinstance(expected_length, int)
                or len(bits) != expected_length
                or hashlib.sha256(bytes(int(bit) for bit in bits)).hexdigest()
                != message_hash
            ):
                message_errors += 1
        if "identity_sha256" in fieldnames and not _SHA256_RE.fullmatch(
            str(row.get("identity_sha256") or "")
        ):
            message_errors += 1
        try:
            psnr = float(row.get("watermarked_psnr") or "")
            ssim = float(row.get("watermarked_ssim") or "")
        except (TypeError, ValueError):
            row_errors += 1
        else:
            if not math.isfinite(psnr) or psnr < 0:
                row_errors += 1
            else:
                psnr_values.append(psnr)
            if not math.isfinite(ssim) or not -1 <= ssim <= 1:
                row_errors += 1
            else:
                ssim_values.append(ssim)
        bindings.append({
            "image_id": image_id,
            "source_path": source_path,
            "message_sha256": message_hash,
        })

    quality_summary = summary.get("watermarked_quality")
    summary_mismatches: list[str] = []
    if not isinstance(quality_summary, dict):
        summary_mismatches.append("record")
    else:
        expected_summary = {
            "status": "complete",
            "count": sample_count,
            "valid_count": sample_count,
            "error_count": 0,
            "missing_count": 0,
        }
        for field, expected in expected_summary.items():
            if quality_summary.get(field) != expected:
                summary_mismatches.append(field)
        for field, values in (
            ("mean_psnr", psnr_values),
            ("mean_ssim", ssim_values),
        ):
            try:
                actual = float(quality_summary[field])
            except (KeyError, TypeError, ValueError):
                summary_mismatches.append(field)
                continue
            expected = sum(values) / len(values) if values else math.nan
            if not math.isfinite(actual) or abs(actual - expected) > 1e-7:
                summary_mismatches.append(field)
        if quality_summary.get("csv_path") != logical_path(quality_path):
            summary_mismatches.append("csv_path")
        if quality_summary.get("csv_sha256") != sha256_file(quality_path):
            summary_mismatches.append("csv_sha256")

    bindings.sort(key=lambda item: item["image_id"])
    valid = all([
        schema_valid,
        len(rows) == sample_count,
        len(seen) == sample_count,
        duplicates == 0,
        errors == 0,
        row_errors == 0,
        path_errors == 0,
        message_errors == 0,
        len(psnr_values) == sample_count,
        len(ssim_values) == sample_count,
        not summary_mismatches,
    ])
    return valid, {
        "rows": len(rows),
        "expected_rows": sample_count,
        "schema_valid": schema_valid,
        "duplicates": duplicates,
        "errors": errors,
        "row_errors": row_errors,
        "path_errors": path_errors,
        "message_errors": message_errors,
        "summary_mismatches": summary_mismatches,
        "sample_binding_sha256": _canonical_sha256(bindings),
    }


def _signature_covers(paths: list[Path]) -> tuple[bool, dict[str, Any]]:
    signature = verify_evidence_bundle()
    if signature.get("verified") is not True:
        return False, signature
    try:
        manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, ValueError, TypeError):
        return False, signature
    if manifest.get("profile") not in {"release-core", "release"}:
        return False, signature
    covered = {
        (item.get("path"), item.get("sha256"))
        for item in manifest.get("files", [])
        if isinstance(item, dict)
    }
    expected = {
        (logical_path(path), sha256_file(path))
        for path in paths
        if path.is_file()
    }
    return bool(expected) and expected.issubset(covered), signature


def benchmark_claim_status(
    summary: dict[str, Any],
    *,
    summary_path: Path,
    results_path: Path,
) -> dict[str, Any]:
    """Verify hashes, raw-row coverage and the detached evidence signature."""

    sample_count = summary.get("num_images") or summary.get("sample_count")
    attack_ids = summary.get("attack_ids")
    if not isinstance(attack_ids, list):
        attack_ids = []
    attack_ids = [str(value) for value in attack_ids if value]

    declared_results = _resolve(summary.get("results_csv_path"))
    checkpoint = _resolve(summary.get("checkpoint"))
    dataset_manifest = _resolve(summary.get("dataset_manifest_path"))
    protocol = _resolve(summary.get("protocol_path"))
    auxiliary_fields = {
        "watermarked_quality_csv_path": "watermarked_quality_csv_sha256",
        "run_config_path": "run_config_sha256",
        "failures_csv_path": "failures_csv_sha256",
        "calibration_path": "calibration_sha256",
        "source_manifest_path": "source_manifest_sha256",
        "checkpoint_manifest_path": "checkpoint_manifest_sha256",
        "environment_path": "environment_sha256",
        "experiment_context_hashes_path": "experiment_context_hashes_sha256",
        "artifact_manifest_path": "artifact_manifest_sha256",
        "progress_path": "progress_sha256",
        "runner_path": "runner_sha256",
        "compatibility_entrypoint_path": "compatibility_entrypoint_sha256",
        "selection_report_path": "selection_report_sha256",
    }
    auxiliary_paths: list[Path] = []
    auxiliary_identity = True
    for path_field, hash_field in auxiliary_fields.items():
        reference = summary.get(path_field)
        expected_hash = summary.get(hash_field)
        if reference is None and expected_hash is None:
            continue
        auxiliary = _resolve(reference)
        auxiliary_identity = auxiliary_identity and _hash_matches(auxiliary, expected_hash)
        if auxiliary is not None:
            auxiliary_paths.append(auxiliary)
    context_fields = (
        ("source_manifest_path", "source_manifest_sha256"),
        ("checkpoint_manifest_path", "checkpoint_manifest_sha256"),
        ("environment_path", "environment_sha256"),
        ("experiment_context_hashes_path", "experiment_context_hashes_sha256"),
    )
    reproducibility_context_complete = all(
        isinstance(summary.get(path_field), str)
        and bool(summary.get(path_field))
        and isinstance(summary.get(hash_field), str)
        and bool(_SHA256_RE.fullmatch(str(summary.get(hash_field))))
        for path_field, hash_field in context_fields
    )
    actual_results = results_path.expanduser().resolve()
    actual_summary = summary_path.expanduser().resolve()

    results_identity = bool(
        declared_results
        and declared_results.resolve() == actual_results
        and _hash_matches(actual_results, summary.get("results_csv_sha256"))
    )
    checkpoint_identity = _hash_matches(checkpoint, summary.get("checkpoint_sha256"))
    dataset_identity = (
        _hash_matches(dataset_manifest, summary.get("dataset_manifest_sha256"))
        and _load_dataset_manifest(dataset_manifest, sample_count)
    )
    protocol_payload: dict[str, Any] | None = None
    success_threshold: float | None = None
    if protocol is not None and protocol.is_file():
        try:
            loaded_protocol = json.loads(
                protocol.read_text(encoding="utf-8"),
                parse_constant=_reject_nonfinite_json,
            )
            if not isinstance(loaded_protocol, dict):
                raise TypeError("protocol must be a JSON object")
            protocol_payload = loaded_protocol
            success_threshold = float(protocol_payload["success_threshold"])
            if not math.isfinite(success_threshold) or not 0 <= success_threshold <= 1:
                success_threshold = None
        except (OSError, ValueError, TypeError, KeyError):
            protocol_payload = None
            success_threshold = None
    protocol_identity = bool(
        protocol_payload is not None
        and protocol_payload.get("schema_version") == "evaluation_protocol.v1"
        and summary.get("protocol_version") == protocol_payload.get("schema_version")
        and _hash_matches(protocol, summary.get("protocol_sha256"))
    )
    protocol_attack_ids = (
        protocol_payload.get("attack_ids") if protocol_payload is not None else None
    )
    protocol_attacks = (
        protocol_payload.get("attacks") if protocol_payload is not None else None
    )
    protocol_attack_contract = bool(
        isinstance(protocol_attack_ids, list)
        and len(protocol_attack_ids) == len(set(protocol_attack_ids))
        and set(protocol_attack_ids) == set(attack_ids)
        and isinstance(protocol_attacks, list)
        and [item.get("id") for item in protocol_attacks if isinstance(item, dict)]
        == attack_ids
        and len(protocol_attacks) == len(attack_ids)
        and all(attack_id in ATTACKS for attack_id in attack_ids)
    )
    protocol_seed_bound = bool(
        protocol_payload is not None
        and isinstance(protocol_payload.get("seed"), int)
        and summary.get("seed") == protocol_payload.get("seed")
    )
    csv_valid, csv_audit = (
        _csv_structure_valid(
            actual_results,
            sample_count=sample_count,
            attack_ids=attack_ids,
            summary=summary,
            success_threshold=success_threshold,
            attack_config_hashes={
                attack_id: ATTACKS[attack_id].config_hash
                for attack_id in attack_ids
                if attack_id in ATTACKS
            },
            protocol_attack_hashes={
                str(item["id"]): _canonical_sha256(item)
                for item in (protocol_attacks or [])
                if isinstance(item, dict) and item.get("id")
            },
        )
        if actual_results.is_file() and isinstance(sample_count, int) and sample_count > 0 and attack_ids
        else (False, {"rows": 0, "expected_rows": None, "duplicates": 0, "errors": 0, "attack_counts": {}})
    )
    method = str(summary.get("method") or "").lower()
    quality_path = _resolve(summary.get("watermarked_quality_csv_path"))
    quality_required = method in {"kad-net", "sepmark", "waveguard"}
    quality_valid, quality_audit = (
        _quality_csv_structure_valid(
            quality_path,
            sample_count=sample_count,
            summary=summary,
        )
        if quality_path is not None
        and quality_path.is_file()
        and isinstance(sample_count, int)
        and sample_count > 0
        else (not quality_required, {"rows": 0, "expected_rows": sample_count})
    )
    sample_bindings_match = bool(
        not quality_required
        or (
            csv_audit.get("sample_binding_sha256")
            and csv_audit.get("sample_binding_sha256")
            == quality_audit.get("sample_binding_sha256")
        )
    )
    dataset_bindings = _dataset_manifest_bindings(dataset_manifest)
    raw_dataset_sample_bindings = bool(
        dataset_bindings["sample_path_sha256"]
        and dataset_bindings["sample_path_sha256"]
        == csv_audit.get("sample_path_binding_sha256")
    )
    raw_dataset_message_bindings = bool(
        dataset_bindings["message_sha256"] is None
        or dataset_bindings["message_sha256"]
        == csv_audit.get("message_binding_sha256")
    )
    signed_paths = [
        actual_summary,
        actual_results,
        *(path for path in (checkpoint, dataset_manifest, protocol) if path is not None),
        *auxiliary_paths,
    ]
    signature_covers, signature = _signature_covers(signed_paths)
    configured_fingerprint = (settings.evidence_public_key_fingerprint or "").strip().lower()
    actual_fingerprint = str(signature.get("public_key_fingerprint_sha256") or "").lower()
    signer_pinned = bool(
        _SHA256_RE.fullmatch(configured_fingerprint)
        and _SHA256_RE.fullmatch(actual_fingerprint)
        and hmac.compare_digest(configured_fingerprint, actual_fingerprint)
    )
    requirements = {
        "summary_v2_complete": (
            summary.get("schema_version") == "benchmark-summary.v2"
            and summary.get("status") == "complete"
        ),
        "summary_finite": _finite_tree(summary),
        "sample_count": isinstance(sample_count, int) and sample_count > 0,
        "attack_ids": bool(attack_ids) and len(attack_ids) == len(set(attack_ids)),
        "results_identity": results_identity,
        "checkpoint_identity": checkpoint_identity,
        "dataset_identity": dataset_identity,
        "protocol_identity": protocol_identity,
        "protocol_attack_contract": protocol_attack_contract,
        "protocol_seed_bound": protocol_seed_bound,
        "success_threshold": success_threshold is not None,
        "auxiliary_artifact_identity": auxiliary_identity,
        "reproducibility_context_complete": reproducibility_context_complete,
        "raw_rows_complete": csv_valid,
        "raw_dataset_sample_bindings": raw_dataset_sample_bindings,
        "raw_dataset_message_bindings": raw_dataset_message_bindings,
        "watermarked_quality_rows_complete": quality_valid,
        "raw_quality_sample_bindings": sample_bindings_match,
        "signature_verified": signature.get("verified") is True,
        "signature_covers_artifacts": signature_covers,
        "signer_pinned": signer_pinned,
    }
    claim_valid = all(requirements.values())
    return {
        "claim_valid": claim_valid,
        "claim_status": "evidence_verified" if claim_valid else "evidence_review_required",
        "evidence_requirements": requirements,
        "raw_results_audit": csv_audit,
        "watermarked_quality_audit": quality_audit,
        "signature_status": signature.get("status", "not_generated"),
    }
