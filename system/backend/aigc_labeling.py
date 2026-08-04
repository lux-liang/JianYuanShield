from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import math
import struct
import zlib
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from .settings import settings
from .signing import canonical_json


AIGC_SCHEMA = "gb45438-2025-aigc-metadata.v1"
AIGC_KEY = "AIGC"
AIGC_LABELS = frozenset({"1", "2", "3"})
AIGC_FIELDS = (
    "Label",
    "ContentProducer",
    "ProduceID",
    "ReservedCode1",
    "ContentPropagator",
    "PropagateID",
    "ReservedCode2",
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class AigcLabelError(ValueError):
    pass


def _is_standard_value(value: Any, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, str) or (not value and not allow_empty):
        return False
    return all(
        character == '"'
        or ord(character) == 0x21
        or 0x23 <= ord(character) <= 0x5B
        or 0x5D <= ord(character) <= 0x7E
        for character in value
    )


def _service_provider() -> str:
    value = str(
        getattr(settings, "content_producer", None) or "JianYuanShield-VPSG"
    ).strip()
    if len(value) > 128 or not _is_standard_value(value):
        raise AigcLabelError("JYS_CONTENT_PRODUCER must use printable GB 45438 ASCII")
    return value


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.b64decode(
        value + "=" * (-len(value) % 4),
        altchars=b"-_",
        validate=True,
    )


def _producer_seal_payload(fields: dict[str, str]) -> dict[str, str]:
    return {
        "schema_version": AIGC_SCHEMA,
        "Label": fields["Label"],
        "ContentProducer": fields["ContentProducer"],
        "ProduceID": fields["ProduceID"],
        "ContentPropagator": fields["ContentPropagator"],
        "PropagateID": fields["PropagateID"],
    }


def _create_producer_seal(fields: dict[str, str]) -> str:
    configured = getattr(settings, "evidence_private_key", None)
    if not configured:
        return ""
    key_path = Path(str(configured)).expanduser()
    if not key_path.is_file():
        raise AigcLabelError("configured evidence private key does not exist")
    private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise AigcLabelError("evidence private key must be Ed25519")
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature = private_key.sign(canonical_json(_producer_seal_payload(fields)))
    return f"JYS1.{_b64url(raw_public)}.{_b64url(signature)}"


def build_aigc_fields(
    *,
    label: str,
    content_id: str,
    producer: str | None = None,
    propagator: str | None = None,
    propagate_id: str | None = None,
) -> dict[str, str]:
    if label not in AIGC_LABELS:
        raise AigcLabelError("AIGC Label must be one of 1, 2 or 3")
    if (
        len(content_id) != 32
        or any(character not in "0123456789abcdef" for character in content_id)
    ):
        raise AigcLabelError("ProduceID must be a 32-character lowercase content_id")
    producer_value = producer or _service_provider()
    propagator_value = propagator or producer_value
    propagate_value = propagate_id or content_id
    for name, value in (
        ("ContentProducer", producer_value),
        ("ContentPropagator", propagator_value),
        ("PropagateID", propagate_value),
    ):
        if len(value) > 128 or not _is_standard_value(value):
            raise AigcLabelError(f"{name} contains unsupported characters")
    fields = {
        "Label": label,
        "ContentProducer": producer_value,
        "ProduceID": content_id,
        "ReservedCode1": "",
        "ContentPropagator": propagator_value,
        "PropagateID": propagate_value,
        "ReservedCode2": "",
    }
    fields["ReservedCode1"] = _create_producer_seal(fields)
    return fields


def metadata_value(fields: dict[str, str]) -> str:
    if tuple(fields) != AIGC_FIELDS:
        raise AigcLabelError("AIGC metadata fields or order do not match GB 45438-2025")
    if fields["Label"] not in AIGC_LABELS:
        raise AigcLabelError("AIGC Label must be one of 1, 2 or 3")
    for name in AIGC_FIELDS[1:]:
        if not _is_standard_value(
            fields[name], allow_empty=name in {"ReservedCode1", "ReservedCode2"}
        ):
            raise AigcLabelError(f"{name} contains unsupported characters")
    return json.dumps(
        {AIGC_KEY: fields},
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_chinese_glyph(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    size: int,
    glyph: str,
    *,
    fill: str,
    width: int,
) -> None:
    """Draw two dependency-free stroke glyphs used by the mandated label."""

    x, y = origin
    scale = size / 10.0

    def point(raw: tuple[float, float]) -> tuple[int, int]:
        return (round(x + raw[0] * scale), round(y + raw[1] * scale))

    strokes: dict[str, tuple[tuple[tuple[float, float], ...], ...]] = {
        "生": (
            ((5, 0.5), (5, 9.5)),
            ((2, 2.3), (8.5, 2.3)),
            ((1.2, 5.2), (8.8, 5.2)),
            ((0.4, 9.1), (9.6, 9.1)),
            ((2.2, 0.8), (1.2, 3.1)),
        ),
        "成": (
            ((1.2, 2), (8.7, 2)),
            ((2, 2), (1.4, 8.8), (4.4, 8.8), (5.1, 7.7)),
            ((6.6, 0.6), (7.4, 5.8), (8.7, 8.8), (9.5, 7.2)),
            ((8.8, 3), (6.8, 6.1), (4.2, 8.4)),
            ((8.2, 0.7), (9.1, 1.5)),
        ),
    }
    for stroke in strokes[glyph]:
        draw.line([point(raw) for raw in stroke], fill=fill, width=width, joint="curve")


def _draw_visible_label(image: Image.Image) -> dict[str, Any]:
    shortest = min(image.size)
    glyph_height = max(12, math.ceil(shortest * 0.06))
    # The normative minimum is 5% of the shortest side. Use 6% to retain a
    # measurable margin after integer rasterization.
    minimum_height = math.ceil(shortest * 0.05)
    padding = max(3, glyph_height // 5)
    latin_font = _font(glyph_height)
    probe = ImageDraw.Draw(image)
    latin_box = probe.textbbox((0, 0), "AI", font=latin_font, stroke_width=1)
    latin_width = latin_box[2] - latin_box[0]
    gap = max(2, glyph_height // 6)
    label_width = latin_width + gap + glyph_height * 2 + padding * 2
    label_height = glyph_height + padding * 2
    x0 = max(0, image.width - label_width)
    y0 = max(0, image.height - label_height)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((x0, y0, image.width, image.height), fill=(0, 0, 0, 210))
    baseline_y = y0 + padding - latin_box[1]
    draw.text(
        (x0 + padding, baseline_y),
        "AI",
        font=latin_font,
        fill="white",
        stroke_width=1,
        stroke_fill="black",
    )
    chinese_x = x0 + padding + latin_width + gap
    stroke_width = max(1, glyph_height // 10)
    _draw_chinese_glyph(
        draw,
        (chinese_x, y0 + padding),
        glyph_height,
        "生",
        fill="white",
        width=stroke_width,
    )
    _draw_chinese_glyph(
        draw,
        (chinese_x + glyph_height, y0 + padding),
        glyph_height,
        "成",
        fill="white",
        width=stroke_width,
    )
    composited = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    image.paste(composited)
    return {
        "text": "AI生成",
        "position": "bottom_right_corner",
        "glyph_height_pixels": glyph_height,
        "minimum_required_height_pixels": minimum_height,
        "shortest_side_pixels": shortest,
        "height_ratio": glyph_height / shortest,
        "meets_minimum_height": glyph_height >= minimum_height,
    }


def apply_aigc_labels(
    png_bytes: bytes,
    *,
    fields: dict[str, str],
    visible: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    try:
        with Image.open(io.BytesIO(png_bytes)) as opened:
            opened.load()
            image = opened.convert("RGB")
    except Exception as exc:
        raise AigcLabelError("AIGC labeling requires a decodable image") from exc
    visible_report = _draw_visible_label(image) if visible else {
        "text": None,
        "position": None,
        "meets_minimum_height": False,
    }
    info = PngImagePlugin.PngInfo()
    value = metadata_value(fields)
    info.add_text(AIGC_KEY, value)
    output = io.BytesIO()
    image.save(output, format="PNG", pnginfo=info)
    encoded = output.getvalue()
    inspection = inspect_aigc_png(encoded, expected_content_id=fields["ProduceID"])
    if not inspection["metadata_valid"] or inspection["metadata_chunk_count"] != 1:
        raise AigcLabelError("written AIGC metadata did not pass self-verification")
    return encoded, {
        "standard": "GB 45438-2025",
        "metadata_keyword": AIGC_KEY,
        "metadata_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        "metadata": fields,
        "producer_seal_trusted": inspection["producer_seal_trusted"],
        "visible_label": visible_report,
    }


def _png_aigc_keywords(data: bytes) -> list[str]:
    if not data.startswith(PNG_SIGNATURE):
        return []
    position = len(PNG_SIGNATURE)
    keywords: list[str] = []
    while position + 12 <= len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        start = position + 8
        end = start + length
        if end + 4 > len(data):
            return []
        payload = data[start:end]
        expected_crc = struct.unpack(">I", data[end : end + 4])[0]
        if zlib.crc32(chunk_type + payload) & 0xFFFFFFFF != expected_crc:
            return []
        if chunk_type in {b"tEXt", b"zTXt", b"iTXt"}:
            raw_keyword = payload.split(b"\0", 1)[0]
            try:
                keyword = raw_keyword.decode("latin-1")
            except UnicodeDecodeError:
                keyword = ""
            if "AIGC" in keyword.upper():
                keywords.append(keyword)
        position = end + 4
        if chunk_type == b"IEND":
            break
    return keywords


def _verify_producer_seal(fields: dict[str, str]) -> dict[str, Any]:
    value = fields.get("ReservedCode1", "")
    parts = value.split(".")
    if len(parts) != 3 or parts[0] != "JYS1":
        return {"present": bool(value), "cryptographically_valid": False, "trusted": False}
    try:
        raw_public = _b64url_decode(parts[1])
        signature = _b64url_decode(parts[2])
        public_key = Ed25519PublicKey.from_public_bytes(raw_public)
        public_key.verify(signature, canonical_json(_producer_seal_payload(fields)))
        public_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fingerprint = hashlib.sha256(public_der).hexdigest()
    except (InvalidSignature, TypeError, ValueError):
        return {"present": True, "cryptographically_valid": False, "trusted": False}
    pinned = str(
        getattr(settings, "evidence_public_key_fingerprint", None) or ""
    ).strip().lower()
    trusted = len(pinned) == 64 and hmac.compare_digest(pinned, fingerprint)
    return {
        "present": True,
        "cryptographically_valid": True,
        "public_key_fingerprint_sha256": fingerprint,
        "trusted": trusted,
    }


def inspect_aigc_png(
    image_bytes: bytes,
    *,
    expected_content_id: str | None = None,
) -> dict[str, Any]:
    keywords = _png_aigc_keywords(image_bytes)
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            value = image.info.get(AIGC_KEY)
    except Exception:
        value = None
    errors: list[str] = []
    fields: dict[str, str] | None = None
    if len(keywords) != 1 or keywords[0] != AIGC_KEY:
        errors.append("aigc_metadata_must_exist_exactly_once")
    if not isinstance(value, str):
        errors.append("aigc_metadata_value_missing")
    else:
        try:
            payload = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = None
            errors.append("aigc_metadata_json_invalid")
        if isinstance(payload, dict) and set(payload) == {AIGC_KEY}:
            candidate = payload[AIGC_KEY]
            if isinstance(candidate, dict):
                fields = candidate
        if fields is None:
            errors.append("aigc_metadata_shape_invalid")
    if fields is not None:
        if tuple(fields) != AIGC_FIELDS:
            errors.append("aigc_metadata_fields_invalid")
        elif fields.get("Label") not in AIGC_LABELS:
            errors.append("aigc_label_invalid")
        else:
            for name in AIGC_FIELDS[1:]:
                if not _is_standard_value(
                    fields.get(name),
                    allow_empty=name in {"ReservedCode1", "ReservedCode2"},
                ):
                    errors.append(f"aigc_value_invalid:{name}")
        if expected_content_id is not None and (
            fields.get("ProduceID") != expected_content_id
            or fields.get("PropagateID") != expected_content_id
        ):
            errors.append("aigc_content_id_mismatch")
    seal = _verify_producer_seal(fields) if fields is not None else {
        "present": False,
        "cryptographically_valid": False,
        "trusted": False,
    }
    if fields is not None and fields.get("ReservedCode1") and not seal["cryptographically_valid"]:
        errors.append("aigc_producer_seal_invalid")
    return {
        "schema_version": "gb45438-aigc-inspection.v1",
        "standard": "GB 45438-2025",
        "metadata_keyword": AIGC_KEY,
        "metadata_chunk_count": len(keywords),
        "metadata_present": isinstance(value, str),
        "metadata_valid": not errors,
        "removed_or_missing": not isinstance(value, str),
        "fields": fields,
        "producer_seal": seal,
        "producer_seal_trusted": seal["trusted"],
        "errors": errors,
    }

