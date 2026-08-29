"""Create softened reference assets for the deployed visual shell."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter


DEFAULT_FILES = {
    "background": ("统一背景.png", "unified-background-blur.png"),
    "logo_candidate_1": ("LOGO候选1.png", "logo-candidate-1-soft.png"),
    "logo_candidate_2": ("LOGO候选2.png", "logo-candidate-2-soft.png"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def soften(path: Path, output: Path, radius: float) -> dict[str, Any]:
    with Image.open(path) as source:
        image = source.convert("RGBA")
        softened = image.filter(ImageFilter.GaussianBlur(radius=radius))
        output.parent.mkdir(parents=True, exist_ok=True)
        softened.save(output, format="PNG", optimize=True)
        return {
            "source": path.name,
            "source_sha256": sha256_file(path),
            "source_dimensions": list(image.size),
            "output": output.name,
            "output_sha256": sha256_file(output),
            "blur_radius": radius,
        }


def generate(input_dir: Path, output_dir: Path, *, background_radius: float = 18.0, icon_radius: float = 3.0) -> Path:
    entries: dict[str, Any] = {}
    for key, (source_name, output_name) in DEFAULT_FILES.items():
        source = input_dir / source_name
        if not source.is_file():
            raise FileNotFoundError(f"reference asset not found: {source}")
        radius = background_radius if key == "background" else icon_radius
        entries[key] = soften(source, output_dir / output_name, radius)
    manifest = {
        "schema_version": "reference-assets-blur.v1",
        "source_directory": str(input_dir),
        "processing": "Pillow ImageFilter.GaussianBlur",
        "purpose": "decorative_visual_layer_only",
        "assets": entries,
        "original_assets_preserved": True,
    }
    manifest_path = output_dir / "reference-assets-blur-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--background-radius", type=float, default=18.0)
    parser.add_argument("--icon-radius", type=float, default=3.0)
    args = parser.parse_args()
    manifest = generate(args.input_dir, args.output_dir, background_radius=args.background_radius, icon_radius=args.icon_radius)
    print(f"MANIFEST: {manifest} ({manifest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
