from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.regenerate_presentation_heatmap import load_spec, render


ROOT = Path(__file__).resolve().parents[1]


class PresentationHeatmapTests(unittest.TestCase):
    def test_spec_preserves_supplied_matrix(self) -> None:
        spec = load_spec(ROOT / "configs" / "presentation_heatmap.v1.json")
        self.assertEqual(spec["source"]["dimensions"], [789, 579])
        self.assertEqual(spec["rows"][0]["values"], [100.0, 99.3, 91.3, 99.9, 99.9, 0.0, 0.0])
        self.assertEqual(spec["rows"][2]["values"], [100.0, 97.7, 94.2, 100.0, 100.0, 2.7, 52.7])

    def test_render_emits_print_and_editable_outputs(self) -> None:
        spec = load_spec(ROOT / "configs" / "presentation_heatmap.v1.json")
        with tempfile.TemporaryDirectory() as temporary:
            outputs = render(spec, Path(temporary), font_path="DejaVuSans.ttf")
            with Image.open(outputs["png"]) as image:
                self.assertEqual(image.size, (3840, 2400))
            svg_text = outputs["svg"].read_text(encoding="utf-8")
            self.assertIn("不同传播裁剪下的水印恢复成功率", svg_text)
            manifest = json.loads(outputs["manifest"].read_text(encoding="utf-8"))
            self.assertEqual(manifest["dimensions"]["width"], 3840)
            self.assertEqual(manifest["scope"], "presentation_only_not_signed_benchmark_evidence")

    def test_source_hash_mismatch_blocks_before_writing_outputs(self) -> None:
        spec = load_spec(ROOT / "configs" / "presentation_heatmap.v1.json")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            source.write_bytes(b"not-the-supplied-figure")
            output_dir = root / "outputs"
            with self.assertRaisesRegex(ValueError, "source image hash"):
                render(spec, output_dir, source_image=source)
            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
