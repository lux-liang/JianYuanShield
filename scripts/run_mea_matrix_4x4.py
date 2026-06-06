#!/usr/bin/env python3
"""
MEA 4×4 Multi-Embedding Attack Matrix Runner.
Tests all (source, attacker) model pairs.
Run AFTER LIDMark and KAD-Net training completes (epoch >= 80 recommended).

Usage:
    PYTHONPATH=. python scripts/run_mea_matrix_4x4.py [--images-per-cell N] [--output DIR]
"""
import argparse, json, os, sys, time
import numpy as np
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from system.evaluation.adapters import get_available_adapters
from system.evaluation.adapters.multi_embedding import evaluate_double_embedding

LFW_DIR = Path("/data1/luxliang/work/vpsg_competition_candidates/datasets/lfw_full_upload/unknown")
OUT_ROOT = Path("/data1/luxliang/work/vpsg_competition_candidates/runs/mea")

EMOJI = {"PASS": "✅", "MARGINAL": "⚠️", "FAIL": "❌"}


def load_images(n: int) -> list[np.ndarray]:
    paths = sorted(LFW_DIR.glob("lfw_*.jpg"))[:n]
    assert paths, f"No images found in {LFW_DIR}"
    return [np.array(Image.open(p).convert("RGB")) for p in paths]


def grade(acc: float) -> str:
    if acc >= 0.85:
        return "PASS"
    if acc >= 0.65:
        return "MARGINAL"
    return "FAIL"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images-per-cell", type=int, default=16,
                        help="Images per (source, attacker) cell (default 16)")
    parser.add_argument("--output", type=str, default=str(OUT_ROOT / "mea_4x4"),
                        help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[MEA-4x4] Loading {args.images_per_cell} images...")
    images = load_images(args.images_per_cell)

    print("[MEA-4x4] Loading adapters...")
    adapter_classes = get_available_adapters()
    adapters = {}
    for name, cls in adapter_classes.items():
        a = cls()
        if a.available:
            adapters[name] = a
            print(f"  ✅ {name}: {a.checkpoint}")
        else:
            print(f"  ❌ {name}: UNAVAILABLE ({a.blocker})")

    if len(adapters) < 2:
        print("[MEA-4x4] Need at least 2 available adapters. Exiting.")
        sys.exit(1)

    model_names = list(adapters.keys())
    print(f"\n[MEA-4x4] Matrix: {model_names} ({len(model_names)}×{len(model_names)})")
    print("=" * 70)

    results_grid = {}
    t0 = time.time()

    for src_name in model_names:
        results_grid[src_name] = {}
        src_adapter = adapters[src_name]

        for atk_name in model_names:
            atk_adapter = adapters[atk_name]
            cell_key = f"{src_name}→{atk_name}"
            print(f"\n[{cell_key}] ({len(images)} images)...")

            first_accs, second_accs = [], []
            errors = 0

            rng = np.random.default_rng(seed=42)
            for img in images:
                try:
                    msg1 = rng.integers(0, 2, src_adapter.message_length, dtype=np.uint8)
                    msg2 = rng.integers(0, 2, atk_adapter.message_length, dtype=np.uint8)
                    result = evaluate_double_embedding(img, src_adapter, atk_adapter, msg1, msg2)
                    fa = result.first_message_metrics.get("accuracy", 0)
                    sa = result.second_message_metrics.get("accuracy", 0)
                    first_accs.append(fa)
                    second_accs.append(sa)
                except Exception as e:
                    print(f"  WARN: {e}")
                    errors += 1

            if not first_accs:
                print(f"  ALL FAILED ({errors} errors)")
                results_grid[src_name][atk_name] = {"error": "all_failed"}
                continue

            fa_mean = float(np.mean(first_accs))
            sa_mean = float(np.mean(second_accs))
            cell = {
                "source": src_name,
                "attacker": atk_name,
                "first_acc": round(fa_mean, 4),
                "second_acc": round(sa_mean, 4),
                "first_grade": grade(fa_mean),
                "second_grade": grade(sa_mean),
                "n_images": len(first_accs),
                "errors": errors,
            }
            results_grid[src_name][atk_name] = cell
            print(f"  first={fa_mean*100:.1f}% [{grade(fa_mean)}]  "
                  f"second={sa_mean*100:.1f}% [{grade(sa_mean)}]")

    elapsed = time.time() - t0
    print(f"\n{'='*70}")
    print(f"[MEA-4x4] Done in {elapsed/60:.1f} min\n")

    # Markdown table
    header = "| Source → Attacker |" + "".join(f" {n} first | {n} second |" for n in model_names)
    sep = "|---|" + "".join("---|---|" for _ in model_names)
    rows = []
    for src in model_names:
        row = f"| **{src}** |"
        for atk in model_names:
            cell = results_grid[src].get(atk, {})
            if "error" in cell:
                row += " — | — |"
            else:
                fa = cell.get("first_acc", 0)
                sa = cell.get("second_acc", 0)
                row += f" {fa*100:.0f}% {EMOJI[grade(fa)]} | {sa*100:.0f}% {EMOJI[grade(sa)]} |"
        rows.append(row)

    table = "\n".join([header, sep] + rows)

    report = {
        "schema": "mea-4x4.v1",
        "generated_at": int(time.time()),
        "models": model_names,
        "images_per_cell": args.images_per_cell,
        "elapsed_seconds": round(elapsed, 1),
        "matrix": results_grid,
        "markdown_table": table,
    }

    report_path = out_dir / f"mea_4x4_{int(time.time())}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[MEA-4x4] Saved → {report_path}\n")
    print("Markdown table:\n")
    print(table)


if __name__ == "__main__":
    main()
