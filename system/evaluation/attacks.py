from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class AttackSpec:
    id: str
    type: str
    parameters: dict[str, Any]
    category: str = "propagation"
    evidence_level: str = "deterministic_transform"

    @property
    def config_hash(self) -> str:
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


ATTACKS: dict[str, AttackSpec] = {
    "clean": AttackSpec("clean", "identity", {}),
    "jpeg50": AttackSpec("jpeg50", "jpeg", {"quality": 50}),
    "jpeg70": AttackSpec("jpeg70", "jpeg", {"quality": 70}),
    "jpeg90": AttackSpec("jpeg90", "jpeg", {"quality": 90}),
    "webp50": AttackSpec("webp50", "webp", {"quality": 50}),
    "resize_0.5x": AttackSpec("resize_0.5x", "resize_roundtrip", {"scale": 0.5}),
    "crop_center_0.8": AttackSpec("crop_center_0.8", "crop_roundtrip", {"ratio": 0.8}),
    "rotate_5": AttackSpec("rotate_5", "rotate", {"degrees": 5.0}),
    "gaussian_blur_5": AttackSpec("gaussian_blur_5", "gaussian_blur", {"kernel": 5, "sigma": 1.2}),
    "gaussian_noise_sigma_3": AttackSpec(
        "gaussian_noise_sigma_3",
        "gaussian_noise",
        {"sigma": 3.0, "seed_scope": "per_image"},
    ),
    "brightness_0.85": AttackSpec("brightness_0.85", "brightness", {"factor": 0.85}),
    "contrast_1.2": AttackSpec("contrast_1.2", "contrast", {"factor": 1.2}),
    "platform_wechat_v1": AttackSpec(
        "platform_wechat_v1",
        "platform_transcode",
        {"long_edge": 1280, "jpeg_quality": 75},
        category="platform",
        evidence_level="documented_proxy",
    ),
    "platform_douyin_v1": AttackSpec(
        "platform_douyin_v1",
        "platform_transcode",
        {"long_edge": 1080, "jpeg_quality": 70},
        category="platform",
        evidence_level="documented_proxy",
    ),
    "deepfake_proxy_v1": AttackSpec(
        "deepfake_proxy_v1",
        "localized_face_edit_proxy",
        {"radius_ratio": 0.27, "blur_kernel": 21, "hue_shift": 6},
        category="editing",
        evidence_level="proxy_not_real_deepfake",
    ),
}


def attack_spec(attack_id: str) -> AttackSpec:
    try:
        return ATTACKS[attack_id]
    except KeyError as exc:
        raise ValueError(f"unknown attack id: {attack_id}") from exc


def derived_seed(global_seed: int, image_id: str, attack_id: str) -> int:
    payload = f"{global_seed}:{image_id}:{attack_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**32)


def _validate_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"expected HxWx3 RGB image, got {image.shape}")
    if image.dtype != np.uint8:
        raise ValueError(f"expected uint8 image, got {image.dtype}")
    return image


def _codec_roundtrip(image: np.ndarray, extension: str, quality: int) -> np.ndarray:
    code = cv2.IMWRITE_JPEG_QUALITY if extension == ".jpg" else cv2.IMWRITE_WEBP_QUALITY
    ok, encoded = cv2.imencode(
        extension,
        cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
        [int(code), int(quality)],
    )
    if not ok:
        raise RuntimeError(f"{extension} encode failed")
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if decoded is None:
        raise RuntimeError(f"{extension} decode failed")
    return cv2.cvtColor(decoded, cv2.COLOR_BGR2RGB)


def _resize_long_edge(image: np.ndarray, long_edge: int) -> np.ndarray:
    height, width = image.shape[:2]
    scale = min(1.0, long_edge / max(height, width))
    if scale == 1.0:
        return image
    resized = cv2.resize(
        image,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    return cv2.resize(resized, (width, height), interpolation=cv2.INTER_LINEAR)


def _localized_edit_proxy(image: np.ndarray, parameters: dict[str, Any]) -> np.ndarray:
    height, width = image.shape[:2]
    radius = max(2, round(min(height, width) * float(parameters["radius_ratio"])))
    center = (width // 2, round(height * 0.45))
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(mask, center, (radius, round(radius * 1.18)), 0, 0, 360, 255, -1)
    kernel = int(parameters["blur_kernel"])
    kernel += 1 - kernel % 2
    mask_float = cv2.GaussianBlur(mask, (kernel, kernel), 0).astype(np.float32)[..., None] / 255.0
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    hsv[..., 0] = (hsv[..., 0].astype(np.int16) + int(parameters["hue_shift"])) % 180
    edited = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    edited = cv2.bilateralFilter(edited, 7, 35, 35)
    return np.clip(image * (1.0 - mask_float) + edited * mask_float, 0, 255).astype(np.uint8)


def apply_attack(
    image: np.ndarray,
    attack: str | AttackSpec,
    *,
    image_id: str = "image",
    global_seed: int = 20260603,
) -> tuple[np.ndarray, dict[str, Any]]:
    source = _validate_rgb(image)
    spec = attack_spec(attack) if isinstance(attack, str) else attack
    params = spec.parameters
    height, width = source.shape[:2]

    if spec.type == "identity":
        output = source.copy()
    elif spec.type == "jpeg":
        output = _codec_roundtrip(source, ".jpg", int(params["quality"]))
    elif spec.type == "webp":
        output = _codec_roundtrip(source, ".webp", int(params["quality"]))
    elif spec.type == "resize_roundtrip":
        scale = float(params["scale"])
        small = cv2.resize(
            source,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        output = cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)
    elif spec.type == "crop_roundtrip":
        ratio = float(params["ratio"])
        crop_h, crop_w = max(1, round(height * ratio)), max(1, round(width * ratio))
        top, left = (height - crop_h) // 2, (width - crop_w) // 2
        output = cv2.resize(source[top:top + crop_h, left:left + crop_w], (width, height), interpolation=cv2.INTER_LINEAR)
    elif spec.type == "rotate":
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), float(params["degrees"]), 1.0)
        output = cv2.warpAffine(source, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    elif spec.type == "gaussian_blur":
        kernel = int(params["kernel"])
        output = cv2.GaussianBlur(source, (kernel, kernel), float(params["sigma"]))
    elif spec.type == "gaussian_noise":
        seed = derived_seed(global_seed, image_id, spec.id)
        rng = np.random.default_rng(seed)
        output = np.clip(source.astype(np.float32) + rng.normal(0, float(params["sigma"]), source.shape), 0, 255).astype(np.uint8)
    elif spec.type == "brightness":
        output = np.clip(source.astype(np.float32) * float(params["factor"]), 0, 255).astype(np.uint8)
    elif spec.type == "contrast":
        output = np.clip((source.astype(np.float32) - 127.5) * float(params["factor"]) + 127.5, 0, 255).astype(np.uint8)
    elif spec.type == "platform_transcode":
        output = _codec_roundtrip(_resize_long_edge(source, int(params["long_edge"])), ".jpg", int(params["jpeg_quality"]))
    elif spec.type == "localized_face_edit_proxy":
        output = _localized_edit_proxy(source, params)
    else:
        raise ValueError(f"unsupported attack type: {spec.type}")

    output = _validate_rgb(output)
    if output.shape != source.shape:
        raise RuntimeError(f"attack changed image shape: {source.shape} -> {output.shape}")
    return output, {
        "attack_id": spec.id,
        "attack_type": spec.type,
        "parameters": params,
        "category": spec.category,
        "evidence_level": spec.evidence_level,
        "config_hash": spec.config_hash,
        "global_seed": global_seed,
        "derived_seed": derived_seed(global_seed, image_id, spec.id),
    }
