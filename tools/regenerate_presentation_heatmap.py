"""Generate a high-resolution, editable presentation heatmap."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "configs" / "presentation_heatmap.v1.json"
DEFAULT_OUTPUT = ROOT / "system" / "frontend" / "assets"
WIDTH, HEIGHT = 3840, 2400


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def choose_font(explicit: str | None = None) -> tuple[Path, bool]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    configured = os.environ.get("JYS_HEATMAP_FONT", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path("/mnt/c/Windows/Fonts/msyh.ttc"),
            Path("/mnt/c/Windows/Fonts/NotoSansSC-VF.ttf"),
            Path("/mnt/c/Windows/Fonts/simhei.ttf"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        ]
    )
    try:
        matched = subprocess.run(
            ["fc-match", "-f", "%{file}\n", "Noto Sans CJK SC"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        matched = ""
    if matched:
        candidates.append(Path(matched))
    for candidate in candidates:
        if candidate.is_file():
            name = candidate.name.lower()
            supports_cjk = any(token in name for token in ("msyh", "simhei", "simsun", "noto", "cjk", "sourcehan"))
            return candidate, supports_cjk
    return Path("DejaVuSans.ttf"), False


def load_font(path: Path, size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        if bold and path.name.lower() == "msyh.ttc":
            return ImageFont.truetype(path, size, index=1)
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype("DejaVuSans.ttf", size)


def interpolate_color(value: float) -> tuple[int, int, int]:
    stops = (
        (0.00, (68, 1, 84)),
        (0.20, (59, 82, 139)),
        (0.40, (33, 145, 140)),
        (0.60, (94, 201, 98)),
        (0.80, (184, 222, 41)),
        (1.00, (253, 231, 37)),
    )
    t = max(0.0, min(1.0, value / 100.0))
    for (left_t, left), (right_t, right) in zip(stops, stops[1:]):
        if t <= right_t:
            ratio = (t - left_t) / (right_t - left_t)
            return tuple(round(a + ratio * (b - a)) for a, b in zip(left, right))
    return stops[-1][1]


def load_spec(path: Path = DEFAULT_SPEC) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    columns = spec.get("columns")
    rows = spec.get("rows")
    metric = spec.get("metric")
    if not isinstance(columns, list) or not columns:
        raise ValueError("heatmap spec must contain columns")
    if not isinstance(rows, list) or not rows:
        raise ValueError("heatmap spec must contain rows")
    lower, upper = metric.get("range", [0, 100]) if isinstance(metric, dict) else (0, 100)
    for row in rows:
        values = row.get("values") if isinstance(row, dict) else None
        if not isinstance(values, list) or len(values) != len(columns):
            raise ValueError("each heatmap row must match the column count")
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper for value in values):
            raise ValueError("heatmap values must be finite and within the metric range")
    return spec


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _paste_rotated_label(canvas: Image.Image, center_x: int, top_y: int, label: str, font: ImageFont.FreeTypeFont) -> None:
    lines = label.split("\n")
    line_heights = [font.getbbox(line)[3] - font.getbbox(line)[1] for line in lines]
    text_width = max(font.getlength(line) for line in lines)
    text_height = sum(line_heights) + max(0, len(lines) - 1) * 8
    layer = Image.new("RGBA", (math.ceil(text_width) + 64, math.ceil(text_height) + 48), (255, 255, 255, 0))
    draw = ImageDraw.Draw(layer)
    y = 24
    for line, line_height in zip(lines, line_heights):
        draw.text((layer.width // 2, y), line, font=font, fill="#111827", anchor="ma")
        y += line_height + 8
    rotated = layer.rotate(32, expand=True, resample=Image.Resampling.BICUBIC)
    canvas.alpha_composite(rotated, (center_x - rotated.width // 2, top_y))


def render(spec: dict[str, Any], output_dir: Path, *, font_path: str | None = None, source_image: Path | None = None) -> dict[str, Path]:
    source = dict(spec.get("source", {}))
    expected_source_hash = source.get("sha256")
    actual_source_hash = sha256_file(source_image) if source_image and source_image.is_file() else expected_source_hash
    if source_image and source_image.is_file() and expected_source_hash and actual_source_hash != expected_source_hash:
        raise ValueError("source image hash does not match the heatmap spec")
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = [str(value) for value in spec["columns"]]
    rows = spec["rows"]
    metric = spec.get("metric", {})
    lower, upper = metric.get("range", [0, 100])
    font_file, cjk_font = choose_font(font_path)
    title_font = load_font(font_file, 108, bold=True)
    subtitle_font = load_font(font_file, 54)
    axis_font = load_font(font_file, 48, bold=True)
    value_font = load_font(font_file, 60, bold=True)
    tick_font = load_font(font_file, 40)
    note_font = load_font(font_file, 30)

    left, top, right, bottom = 520, 460, 3260, 1780
    cell_width = (right - left) / len(columns)
    cell_height = (bottom - top) / len(rows)
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(canvas)
    muted = "#4b5563"
    draw.text((WIDTH // 2, 96), spec["title"], font=title_font, fill="#111827", anchor="ma")
    draw.text((WIDTH // 2, 236), spec["subtitle"], font=subtitle_font, fill=muted, anchor="ma")
    draw.text((WIDTH - 110, 105), "PRESENTATION RECONSTRUCTION", font=note_font, fill="#64748b", anchor="ra")

    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row["values"]):
            x0 = round(left + column_index * cell_width)
            y0 = round(top + row_index * cell_height)
            x1 = round(left + (column_index + 1) * cell_width)
            y1 = round(top + (row_index + 1) * cell_height)
            fill = interpolate_color(float(value))
            draw.rectangle((x0, y0, x1, y1), fill=fill, outline="white", width=8)
            luminance = 0.2126 * fill[0] + 0.7152 * fill[1] + 0.0722 * fill[2]
            text_fill = "#111827" if luminance >= 150 else "#ffffff"
            draw.text(((x0 + x1) // 2, (y0 + y1) // 2), f"{float(value):.1f}", font=value_font, fill=text_fill, anchor="mm")

    for row_index, row in enumerate(rows):
        draw.multiline_text((left - 38, round(top + (row_index + 0.5) * cell_height)), str(row["label"]), font=axis_font, fill="#111827", anchor="rm", align="right", spacing=8)
    for column_index, label in enumerate(columns):
        _paste_rotated_label(canvas, round(left + (column_index + 0.5) * cell_width), bottom + 70, label, axis_font)

    draw.text((WIDTH // 2, 2140), spec["x_axis"], font=axis_font, fill="#111827", anchor="ma")
    draw.text((120, (top + bottom) // 2), spec["y_axis"], font=axis_font, fill="#111827", anchor="mm")
    bar_x0, bar_x1 = 3420, 3495
    for y in range(top, bottom + 1):
        value = upper - (upper - lower) * (y - top) / (bottom - top)
        draw.line((bar_x0, y, bar_x1, y), fill=interpolate_color(value), width=2)
    for value in (0, 20, 40, 60, 80, 100):
        y = round(bottom - (bottom - top) * value / 100)
        draw.text((3560, y), str(value), font=tick_font, fill="#111827", anchor="lm")
    draw.text((3650, (top + bottom) // 2), metric.get("label", "恢复率 (%)"), font=axis_font, fill="#111827", anchor="mm")
    draw.text((WIDTH // 2, 2290), spec.get("presentation_note", ""), font=note_font, fill=muted, anchor="ma")

    png_path = output_dir / "heatmap_watermark_recovery_4k.png"
    svg_path = output_dir / "heatmap_watermark_recovery_editable.svg"
    manifest_path = output_dir / "heatmap_watermark_recovery_manifest.json"
    canvas.convert("RGB").save(png_path, dpi=(300, 300), optimize=True)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f"<title>{_escape(spec['title'])}</title>",
        f"<desc>{_escape(spec.get('presentation_note', ''))}</desc>",
        '<rect width="100%" height="100%" fill="white"/>',
        '<defs><linearGradient id="viridis" x1="0" y1="1" x2="0" y2="0"><stop offset="0%" stop-color="#440154"/><stop offset="20%" stop-color="#3b528b"/><stop offset="40%" stop-color="#21918c"/><stop offset="60%" stop-color="#5ec962"/><stop offset="80%" stop-color="#b8de29"/><stop offset="100%" stop-color="#fde725"/></linearGradient></defs>',
        '<g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" fill="#111827">',
        f'<text x="{WIDTH / 2:.1f}" y="180" text-anchor="middle" font-size="108" font-weight="700">{_escape(spec["title"])}</text>',
        f'<text x="{WIDTH / 2:.1f}" y="310" text-anchor="middle" font-size="54" fill="{muted}">{_escape(spec["subtitle"])}</text>',
        f'<text x="{WIDTH - 110}" y="105" text-anchor="end" font-size="30" fill="#64748b">PRESENTATION RECONSTRUCTION</text>',
    ]
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row["values"]):
            x0 = left + column_index * cell_width
            y0 = top + row_index * cell_height
            fill = interpolate_color(float(value))
            rgb = f"rgb({fill[0]},{fill[1]},{fill[2]})"
            text_fill = "#111827" if sum(fill) / 3 >= 150 else "#ffffff"
            svg.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{cell_width:.1f}" height="{cell_height:.1f}" fill="{rgb}" stroke="white" stroke-width="8"/>')
            svg.append(f'<text x="{x0 + cell_width / 2:.1f}" y="{y0 + cell_height / 2 + 20:.1f}" text-anchor="middle" font-size="60" font-weight="700" fill="{text_fill}">{float(value):.1f}</text>')
    for row_index, row in enumerate(rows):
        center_y = top + (row_index + 0.5) * cell_height
        lines = str(row["label"]).split("\n")
        start_y = center_y - (len(lines) - 1) * 30
        svg.append(f'<text x="{left - 38}" y="{start_y:.1f}" text-anchor="end" font-size="48" font-weight="700">')
        for line_index, line in enumerate(lines):
            svg.append(f'<tspan x="{left - 38}" dy="{0 if line_index == 0 else 58}">{_escape(line)}</tspan>')
        svg.append("</text>")
    for column_index, label in enumerate(columns):
        center_x = left + (column_index + 0.5) * cell_width
        svg.append(f'<text x="{center_x:.1f}" y="1900" text-anchor="middle" font-size="48" font-weight="700" transform="rotate(-32 {center_x:.1f} 1900)">{_escape(label)}</text>')
    svg.extend([
        f'<text x="{WIDTH / 2:.1f}" y="2140" text-anchor="middle" font-size="48" font-weight="700">{_escape(spec["x_axis"])}</text>',
        f'<text x="120" y="1120" text-anchor="middle" font-size="48" font-weight="700" transform="rotate(-90 120 1120)">{_escape(spec["y_axis"])}</text>',
        f'<rect x="{bar_x0}" y="{top}" width="{bar_x1 - bar_x0}" height="{bottom - top}" fill="url(#viridis)"/>',
    ])
    for value in (0, 20, 40, 60, 80, 100):
        y = bottom - (bottom - top) * value / 100
        svg.append(f'<text x="3560" y="{y + 14:.1f}" font-size="40">{value}</text>')
    svg.extend([
        f'<text x="3650" y="1120" text-anchor="middle" font-size="48" font-weight="700" transform="rotate(-90 3650 1120)">{_escape(metric.get("label", "恢复率 (%)"))}</text>',
        f'<text x="{WIDTH / 2:.1f}" y="2310" text-anchor="middle" font-size="30" fill="{muted}">{_escape(spec.get("presentation_note", ""))}</text>',
        "</g></svg>",
    ])
    svg_path.write_text("".join(svg), encoding="utf-8")

    manifest = {
        "schema_version": "presentation-heatmap-manifest.v1",
        "spec": str(DEFAULT_SPEC.relative_to(ROOT)),
        "source": source,
        "source_image_sha256": actual_source_hash,
        "font": {"path": str(font_file), "name": font_file.name, "cjk_capable": cjk_font},
        "dimensions": {"width": WIDTH, "height": HEIGHT, "dpi": 300},
        "outputs": {"png": png_path.name, "svg": svg_path.name},
        "scope": "presentation_only_not_signed_benchmark_evidence",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"png": png_path, "svg": svg_path, "manifest": manifest_path}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--font", type=str, default=None)
    parser.add_argument("--source-image", type=Path, default=None)
    args = parser.parse_args()
    outputs = render(load_spec(args.spec), args.out_dir, font_path=args.font, source_image=args.source_image)
    for kind, path in outputs.items():
        print(f"{kind.upper()}: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
