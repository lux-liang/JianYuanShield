#!/usr/bin/env python3
"""
MEA 4×4 Multi-Embedding Attack Matrix Runner（正式评分入口）.
Tests all (source, attacker) model pairs.
Run AFTER LIDMark and KAD-Net training completes (epoch >= 80 recommended).

Usage:
    PYTHONPATH=. python scripts/run_mea_matrix_4x4.py [--images-per-cell N] [--output DIR] [--seed N]

环境变量（可选，均有 /data1 fallback）:
    JYS_LFW_DIR          LFW 图像目录，默认 /data1/luxliang/.../lfw_full_upload/unknown
    JYS_MODEL_SOURCE_ROOT 模型/运行根目录，默认 /data1/luxliang/.../vpsg_competition_candidates
"""
import argparse, json, os, sys, time
import numpy as np
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from system.evaluation.adapters import get_available_adapters
from system.evaluation.adapters.multi_embedding import evaluate_double_embedding

# ── 路径：优先读环境变量，不设则回退 /data1 默认值 ──────────────────────────
_DATA1_ROOT = Path("/data1/luxliang/work/vpsg_competition_candidates")

LFW_DIR = Path(
    os.environ.get("JYS_LFW_DIR",
                   str(_DATA1_ROOT / "datasets/lfw_full_upload/unknown"))
)
OUT_ROOT = Path(
    os.environ.get("JYS_MODEL_SOURCE_ROOT",
                   str(_DATA1_ROOT))
) / "runs/mea"

EMOJI = {"PASS": "✅", "MARGINAL": "⚠️", "FAIL": "❌"}

# ── 从协议文件读阈值（不硬编码） ──────────────────────────────────────────────
_PROTOCOL_PATH = Path(__file__).parent.parent / "configs" / "evaluation_protocol.v1.json"

def _load_thresholds():
    """从 evaluation_protocol.v1.json 读取 success_threshold，并据此推导 MARGINAL 门槛。

    PASS    门槛 = success_threshold（协议值，当前 0.9）
    MARGINAL门槛 = random_baseline + (success_threshold - random_baseline) / 2
                 = 0.5 + (0.9 - 0.5) / 2 = 0.70（随机基线 0.5，均分区间中点）
    FAIL    门槛 = 其余（< MARGINAL 门槛）

    阈值来源注记写入 report["metric_definitions"]["grade_thresholds_source"]。
    """
    random_baseline = 0.5
    try:
        with open(_PROTOCOL_PATH, encoding="utf-8") as f:
            proto = json.load(f)
        success_threshold = float(proto["success_threshold"])
        source_note = f"evaluation_protocol.v1.json::success_threshold={success_threshold}"
    except Exception as e:
        # fallback：如果协议文件不可读，使用兼容旧值并记录 fallback 原因
        success_threshold = 0.9
        source_note = f"fallback_hardcoded_0.9 (protocol file unreadable: {e})"
    marginal_threshold = random_baseline + (success_threshold - random_baseline) / 2
    return success_threshold, marginal_threshold, random_baseline, source_note

PASS_THRESHOLD, MARGINAL_THRESHOLD, RANDOM_BASELINE, THRESHOLD_SOURCE = _load_thresholds()


def load_images(n: int) -> list[np.ndarray]:
    paths = sorted(LFW_DIR.glob("lfw_*.jpg"))[:n]
    assert paths, f"No images found in {LFW_DIR}"
    return [np.array(Image.open(p).convert("RGB")) for p in paths]


def grade(acc: float) -> str:
    """三档评级，阈值来自 evaluation_protocol.v1.json（不硬编码）。"""
    if acc >= PASS_THRESHOLD:
        return "PASS"
    if acc >= MARGINAL_THRESHOLD:
        return "MARGINAL"
    return "FAIL"


def main():
    parser = argparse.ArgumentParser(
        description="MEA 4×4 Multi-Embedding Attack Matrix Runner（正式评分入口）"
    )
    parser.add_argument("--images-per-cell", type=int, default=16,
                        help="Images per (source, attacker) cell (default 16)")
    parser.add_argument("--output", type=str, default=str(OUT_ROOT / "mea_4x4"),
                        help="Output directory")
    parser.add_argument("--seed", type=int, default=20260609,
                        help="RNG seed for message generation (default 20260609)")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[MEA-4x4] Loading {args.images_per_cell} images from {LFW_DIR}...")
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
    print(f"[MEA-4x4] Seed={args.seed}  PASS≥{PASS_THRESHOLD}  "
          f"MARGINAL≥{MARGINAL_THRESHOLD:.2f}  (source: {THRESHOLD_SOURCE})")
    print("=" * 70)

    results_grid = {}
    t0 = time.time()

    for src_name in model_names:
        results_grid[src_name] = {}
        src_adapter = adapters[src_name]

        for atk_name in model_names:
            atk_adapter = adapters[atk_name]
            cell_key = f"{src_name}→{atk_name}"
            print(f"\n[{cell_key}] ({len(images)} images)  "
                  f"src_msg_len={src_adapter.message_length} "
                  f"atk_msg_len={atk_adapter.message_length}...")

            first_accs, second_accs = [], []
            errors = 0

            # seed 来自 --seed 参数（默认 20260609），不再硬编码 42
            rng = np.random.default_rng(seed=args.seed)
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
                # first_acc：先嵌水印被第二模型二次嵌入后的残留可解比特率
                # ≈0.5 表示先水印已被覆盖，是预期的红队发现，不是 bug
                "first_acc": round(fa_mean, 4),
                "second_acc": round(sa_mean, 4),
                "first_grade": grade(fa_mean),
                "second_grade": grade(sa_mean),
                "n_images": len(first_accs),
                "errors": errors,
                # 每格标注：消息位数与解码器语义
                "source_msg_len": src_adapter.message_length,
                "attacker_msg_len": atk_adapter.message_length,
                "source_decoder": getattr(src_adapter, "primary_decoder", "decode"),
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
        "schema": "mea-4x4.v2",
        "generated_at": int(time.time()),
        "models": model_names,
        "images_per_cell": args.images_per_cell,
        "seed": args.seed,
        "elapsed_seconds": round(elapsed, 1),
        # ── 指标定义（P0-5 / P1-4 / P1-5 口径修正） ────────────────────────
        "metric_definitions": {
            "first_acc": (
                "先嵌水印(source)被第二模型(attacker)二次嵌入覆盖后，"
                "由 source.decode(双嵌图) 读出的残留可解比特率。"
                "≈0.5 表示先水印已被完全覆盖，是多水印并存下的预期红队发现，"
                "不是 bug，也不与单模型 clean 100% 矛盾（两者度量不同量）。"
            ),
            "second_acc": (
                "第二(攻击者)水印在双嵌图上由 attacker.decode 读出的可解比特率，"
                "反映攻击者水印的嵌入质量。"
            ),
            "random_baseline": RANDOM_BASELINE,
            "grade_thresholds": {
                "PASS": f">= {PASS_THRESHOLD}",
                "MARGINAL": f">= {MARGINAL_THRESHOLD:.2f} and < {PASS_THRESHOLD}",
                "FAIL": f"< {MARGINAL_THRESHOLD:.2f}",
                "MARGINAL_formula": (
                    f"random_baseline({RANDOM_BASELINE}) + "
                    f"(success_threshold({PASS_THRESHOLD}) - random_baseline({RANDOM_BASELINE})) / 2"
                ),
            },
            "grade_thresholds_source": THRESHOLD_SOURCE,
            "msg_len_note": (
                "各模型消息位数不同（LIDMark 16-bit / KAD-Net & WaveGuard 30-bit / "
                "SepMark 128-bit），且解码器语义不同（detector / decoder_C / decoder_RF / "
                "identity）。跨行列比较 first_acc / second_acc 时须考虑随机基线均为 0.5，"
                "但长消息（128-bit）与短消息（16-bit）的统计噪声不同，不可直接排序比较。"
                "每格 source_msg_len / attacker_msg_len / source_decoder 已标注。"
            ),
        },
        "matrix": results_grid,
        "markdown_table": table,
    }

    report_path = out_dir / f"mea_4x4_{int(time.time())}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"[MEA-4x4] Saved → {report_path}\n")
    print("Markdown table:\n")
    print(table)


if __name__ == "__main__":
    main()
