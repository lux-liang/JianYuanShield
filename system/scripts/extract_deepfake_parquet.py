#!/usr/bin/env python3
"""把 HF parquet 版 deepfake/real 人脸数据集解出成图像目录，供水印/检测实验消费。

数据源: Hemg/deepfake-and-real-images (HF), 5 个 parquet 分片, schema:
    image: struct<bytes: binary, path: string>   # JPEG 原始字节
    label: int64                                   # ClassLabel, 名字从 schema metadata 读

输出:
    <out>/real/real_000000.jpg ...
    <out>/fake/fake_000000.jpg ...
    <out>/manifest.json   # 标签名映射 + 计数 + 分辨率统计

用法:
    PYTHONPATH=. python system/scripts/extract_deepfake_parquet.py \
        --parquet-dir /home/luxliang/jys_datasets/deepfake_images/data \
        --out /data1/luxliang/datasets/deepfake_images_extracted \
        --per-class 12000 --seed 20260616
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--parquet-dir", type=Path,
                   default=Path("/home/luxliang/jys_datasets/deepfake_images/data"))
    p.add_argument("--out", type=Path,
                   default=Path("/data1/luxliang/datasets/deepfake_images_extracted"))
    p.add_argument("--per-class", type=int, default=12000,
                   help="每个类别最多解出多少张 (<=0 表示全部)")
    p.add_argument("--seed", type=int, default=20260616)
    return p.parse_args()


def label_names_from_metadata(schema) -> dict[int, str]:
    """从 HF 写入 parquet schema 的 metadata 里读 ClassLabel 名字。"""
    try:
        meta = schema.metadata or {}
        raw = meta.get(b"huggingface") or meta.get("huggingface")
        if raw is None:
            return {}
        info = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        feats = info.get("info", {}).get("features", {})
        names = feats.get("label", {}).get("names")
        if isinstance(names, list):
            return {i: str(n) for i, n in enumerate(names)}
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 无法从 metadata 解析标签名: {exc!r}", file=sys.stderr)
    return {}


def main() -> None:
    import pyarrow.parquet as pq
    from PIL import Image

    args = parse_args()
    files = sorted(args.parquet_dir.glob("*.parquet"))
    if not files:
        print(f"未找到 parquet: {args.parquet_dir}", file=sys.stderr)
        sys.exit(1)

    # 先读一个分片拿 schema / 标签名
    first = pq.read_table(files[0])
    id2name = label_names_from_metadata(first.schema)
    print(f"[info] 标签名映射: {id2name or '(metadata 无, 退化为 label_<id>)'}")

    rng = np.random.default_rng(args.seed)
    counts: Counter = Counter()
    saved: Counter = Counter()
    res_w: list[int] = []
    res_h: list[int] = []
    fmt_cnt: Counter = Counter()

    per_class = args.per_class if args.per_class > 0 else None
    args.out.mkdir(parents=True, exist_ok=True)

    for f in files:
        t = pq.read_table(f, columns=["image", "label"])
        imgs = t.column("image").to_pylist()
        labels = t.column("label").to_pylist()
        for cell, lab in zip(imgs, labels):
            counts[lab] += 1
            name = id2name.get(int(lab), f"label_{lab}")
            if per_class is not None and saved[name] >= per_class:
                continue
            data = cell.get("bytes") if isinstance(cell, dict) else cell
            if data is None:
                continue
            try:
                im = Image.open(io.BytesIO(data)).convert("RGB")
            except Exception:  # noqa: BLE001
                continue
            # 抽样统计分辨率/格式 (每 500 张记一次)
            if saved[name] % 500 == 0:
                res_w.append(im.width)
                res_h.append(im.height)
                fmt_cnt[im.format or "JPEG"] += 1
            sub = args.out / name
            sub.mkdir(parents=True, exist_ok=True)
            idx = saved[name]
            # 原字节是 JPEG, 直接 re-save 成统一 jpg (RGB) 保证下游 PIL/cv2 可读
            im.save(sub / f"{name}_{idx:06d}.jpg", quality=98)
            saved[name] += 1
        print(f"[info] 处理完 {f.name}: 累计 saved={dict(saved)}")

    def stat(a: list[int]) -> dict:
        if not a:
            return {}
        arr = np.array(a)
        return {"min": int(arr.min()), "max": int(arr.max()),
                "median": int(np.median(arr)), "mean": round(float(arr.mean()), 1)}

    manifest = {
        "source": "Hemg/deepfake-and-real-images (HF parquet)",
        "label_names": id2name,
        "total_rows_by_label": {str(k): v for k, v in counts.items()},
        "saved_by_class": dict(saved),
        "per_class_cap": args.per_class,
        "seed": args.seed,
        "width_stats_sampled": stat(res_w),
        "height_stats_sampled": stat(res_h),
        "format_sampled": dict(fmt_cnt),
        "out_dir": str(args.out),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
