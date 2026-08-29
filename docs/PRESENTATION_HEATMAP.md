# PPT 热力图生成与边界

## 用途

`configs/presentation_heatmap.v1.json` 保存从用户提供的 `789×579` 低清图逐格转录的矩阵，`tools/regenerate_presentation_heatmap.py` 生成：

- `system/frontend/assets/heatmap_watermark_recovery_4k.png`：`3840×2400`、`300 DPI`，适合插入 PPT；
- `system/frontend/assets/heatmap_watermark_recovery_editable.svg`：矢量网格和可编辑文本；
- `system/frontend/assets/heatmap_watermark_recovery_manifest.json`：源图哈希、字体、尺寸和展示范围。

```bash
python3 tools/regenerate_presentation_heatmap.py \
  --source-image /path/to/f5546a864bb267cc8f20c110924de871.png
```

Windows/WSL 环境优先使用 `C:\Windows\Fonts\msyh.ttc`；服务器环境可通过 `JYS_HEATMAP_FONT` 或 `--font` 指定已安装的中文字体。没有中文字体时仍可生成 SVG，但生成 PNG 前应补齐字体并复核中文字形，避免 PPT 出现方框。

## 证据边界

这张图是**展示重建图**，数值来源是提供的低清图转录，不是从当前服务器重新跑出的签名 benchmark。它不能替代 `/api/claims`、`/api/evidence/audit` 或固定实验 artifact，也不能外推为任意图片、任意攻击或“零误报/全面鲁棒”。正式答辩统一说：

> 这张热力图用于展示固定样本口径下的传播退化趋势；正式性能结论以同版本、同 checkpoint、同协议和签名证据包为准。超出协议时系统不发布数字，转为不可核验或需复核。

## PPT 使用建议

优先插入 SVG；若 PPT 字体替换或兼容性不稳定，再插入 4K PNG。不要对 PNG 进行二次截图或低质量压缩，不要删除脚注和“展示重建”范围说明。
