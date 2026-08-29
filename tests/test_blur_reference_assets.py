from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.blur_reference_assets import generate


REFERENCE = Path("/tmp/jys-frontend-reference-20260820/鉴源盾前端参考")


class BlurReferenceAssetsTests(unittest.TestCase):
    def test_reference_assets_generate_with_manifest(self) -> None:
        if not REFERENCE.is_dir():
            self.skipTest("reference zip is not extracted in this environment")
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            manifest_path = generate(REFERENCE, output_dir)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["original_assets_preserved"])
            self.assertEqual(set(manifest["assets"]), {"background", "logo_candidate_1", "logo_candidate_2"})
            for entry in manifest["assets"].values():
                output = output_dir / entry["output"]
                self.assertTrue(output.is_file())
                self.assertEqual(entry["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
                with Image.open(output) as image:
                    self.assertEqual(list(image.size), entry["source_dimensions"])


if __name__ == "__main__":
    unittest.main()
