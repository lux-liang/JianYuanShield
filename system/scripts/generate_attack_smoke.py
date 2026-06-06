from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

PROJECT_DIR = Path(__file__).resolve().parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from system.evaluation.attacks import ATTACKS, apply_attack  # noqa: E402
from system.evaluation.metrics import image_quality  # noqa: E402
from system.evaluation.runtime import ASSET_ROOT, DATA_ROOT, REPORT_ROOT  # noqa: E402


def finite_mean(values: list[float]) -> float | None:
    value = float(np.mean(values))
    return value if math.isfinite(value) else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the unified attack library on real images.")
    parser.add_argument("--image-root", type=Path, default=DATA_ROOT / "lfw_full_upload" / "unknown")
    parser.add_argument("--num-images", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260603)
    parser.add_argument("--attacks", nargs="+", default=list(ATTACKS))
    args = parser.parse_args()

    images = sorted(
        path for path in args.image_root.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    )[:args.num_images]
    if not images:
        raise RuntimeError(f"no images found under {args.image_root}")

    rows: list[dict] = []
    samples: list[tuple[str, np.ndarray]] = []
    for image_path in images:
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        source = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        for attack_id in args.attacks:
            attacked, metadata = apply_attack(source, attack_id, image_id=image_path.stem, global_seed=args.seed)
            metrics = image_quality(source, attacked)
            rows.append({"image_id": image_path.stem, **metadata, **metrics})
            if image_path == images[0]:
                samples.append((attack_id, attacked))

    report_dir = REPORT_ROOT / "attack_library_smoke"
    asset_dir = ASSET_ROOT / "attack_library_smoke"
    report_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "attack-library-smoke.v1",
        "status": "complete",
        "images": len(images),
        "attacks": args.attacks,
        "rows": len(rows),
        "seed": args.seed,
        "attack_hashes": {attack_id: ATTACKS[attack_id].config_hash for attack_id in args.attacks},
        "metrics": {
            attack_id: {
                "mean_psnr": finite_mean([row["psnr"] for row in rows if row["attack_id"] == attack_id]),
                "mean_ssim": finite_mean([row["ssim"] for row in rows if row["attack_id"] == attack_id]),
            }
            for attack_id in args.attacks
        },
    }
    (report_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    tile = 160
    columns = 4
    rows_count = (len(samples) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * tile, rows_count * (tile + 24)), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (name, array) in enumerate(samples):
        x, y = (index % columns) * tile, (index // columns) * (tile + 24)
        canvas.paste(Image.fromarray(array).resize((tile, tile)), (x, y))
        draw.text((x + 4, y + tile + 4), name, fill="black")
    canvas.save(asset_dir / "attack_grid.jpg", quality=92)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
