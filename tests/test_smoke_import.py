"""
test_smoke_import.py — 烟雾测试（无权重依赖）

验证：
1. 关键模块均可 import，无语法错误、无缺少依赖（运行期）
2. 评测协议 JSON 可解析，结构合规（schema_version / success_threshold / models）
3. runtime.py 路径从 JYS_MODEL_SOURCE_ROOT 等环境变量派生，不硬连接 /data1

本文件不加载任何模型权重，可在 CI（无 GPU/无权重）环境安全运行。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SmokeImportTests(unittest.TestCase):
    """核心模块 import 烟雾测试"""

    def test_import_runtime(self) -> None:
        """runtime.py 必须可 import，且导出关键路径常量"""
        from system.evaluation import runtime  # noqa: F401

        self.assertTrue(hasattr(runtime, "PROJECT_ROOT"))
        self.assertTrue(hasattr(runtime, "MODEL_SOURCE_ROOT"))
        self.assertTrue(hasattr(runtime, "DATA_ROOT"))
        self.assertTrue(hasattr(runtime, "WEIGHT_ROOT"))

    def test_import_protocol(self) -> None:
        """protocol.py 必须可 import"""
        from system.evaluation import protocol  # noqa: F401

        self.assertTrue(hasattr(protocol, "load_protocol"))
        self.assertTrue(hasattr(protocol, "protocol_summary"))
        self.assertTrue(hasattr(protocol, "REQUIRED_MODELS"))

    def test_import_attacks(self) -> None:
        """attacks.py 必须可 import"""
        from system.evaluation import attacks  # noqa: F401

        self.assertTrue(hasattr(attacks, "apply_attack"))
        self.assertTrue(hasattr(attacks, "ATTACKS"))

    def test_import_metrics(self) -> None:
        """metrics.py 必须可 import"""
        from system.evaluation import metrics  # noqa: F401

        self.assertTrue(hasattr(metrics, "bit_accuracy"))

    def test_import_statistics(self) -> None:
        """statistics.py 必须可 import"""
        from system.evaluation import statistics  # noqa: F401

    def test_import_run_metadata(self) -> None:
        """run_metadata.py 必须可 import"""
        from system.evaluation import run_metadata  # noqa: F401

        self.assertTrue(hasattr(run_metadata, "build_run_metadata"))

    def test_import_signing(self) -> None:
        """signing.py 必须可 import（仅依赖 cryptography，无权重）"""
        from system.backend import signing  # noqa: F401

    def test_import_evidence(self) -> None:
        """evidence.py 必须可 import"""
        from system.backend import evidence  # noqa: F401


class ProtocolJsonTests(unittest.TestCase):
    """评测协议 JSON 可解析性与结构验证"""

    PROTOCOL_PATH = ROOT / "configs" / "evaluation_protocol.v1.json"

    def test_protocol_json_is_parseable(self) -> None:
        """configs/evaluation_protocol.v1.json 必须是合法 JSON"""
        self.assertTrue(
            self.PROTOCOL_PATH.exists(),
            f"协议文件不存在：{self.PROTOCOL_PATH}",
        )
        with self.PROTOCOL_PATH.open("r", encoding="utf-8") as f:
            protocol = json.load(f)
        self.assertIsInstance(protocol, dict, "协议 JSON 根节点必须为 dict")

    def test_protocol_schema_version(self) -> None:
        """协议必须声明 schema_version = evaluation_protocol.v1"""
        with self.PROTOCOL_PATH.open("r", encoding="utf-8") as f:
            protocol = json.load(f)
        self.assertEqual(
            protocol.get("schema_version"),
            "evaluation_protocol.v1",
            "schema_version 字段不匹配",
        )

    def test_protocol_success_threshold(self) -> None:
        """协议 success_threshold 必须在 (0, 1] 范围内"""
        with self.PROTOCOL_PATH.open("r", encoding="utf-8") as f:
            protocol = json.load(f)
        threshold = protocol.get("success_threshold")
        self.assertIsInstance(threshold, (int, float))
        self.assertGreater(threshold, 0.0)
        self.assertLessEqual(threshold, 1.0)

    def test_protocol_models_field(self) -> None:
        """协议必须包含 models 字段，且包含五个预期模型"""
        with self.PROTOCOL_PATH.open("r", encoding="utf-8") as f:
            protocol = json.load(f)
        models = protocol.get("models", {})
        self.assertIsInstance(models, dict)
        expected = {"LIDMark", "HiDDeN", "SepMark", "WaveGuard", "KAD-Net"}
        self.assertEqual(set(models.keys()), expected)

    def test_protocol_attacks_non_empty(self) -> None:
        """协议 attacks 列表不能为空，且每条攻击有 id 字段"""
        with self.PROTOCOL_PATH.open("r", encoding="utf-8") as f:
            protocol = json.load(f)
        attacks = protocol.get("attacks", [])
        self.assertIsInstance(attacks, list)
        self.assertGreater(len(attacks), 0)
        for attack in attacks:
            self.assertIn("id", attack, f"攻击条目缺少 id 字段：{attack}")


class RuntimeEnvTests(unittest.TestCase):
    """runtime.py 路径衍生行为验证"""

    def test_model_source_root_respects_env(self) -> None:
        """MODEL_SOURCE_ROOT 须从 JYS_MODEL_SOURCE_ROOT 环境变量读取"""
        import subprocess

        env = os.environ.copy()
        env["JYS_MODEL_SOURCE_ROOT"] = "/tmp/jys_test_model_source"
        result = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from system.evaluation.runtime import MODEL_SOURCE_ROOT; print(MODEL_SOURCE_ROOT)",
            ],
            cwd=ROOT,
            env=env,
            text=True,
        ).strip()
        self.assertEqual(result, "/tmp/jys_test_model_source")

    def test_no_data1_hardcode_in_system_scripts(self) -> None:
        """system/scripts/ 下的 run_*.py 不应硬编码 /data1"""
        scripts_dir = ROOT / "system" / "scripts"
        offenders = []
        for path in scripts_dir.glob("run_*.py"):
            if path.is_file() and "/data1" in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        self.assertEqual(
            offenders, [],
            f"以下脚本硬编码了 /data1，请改用 JYS_MODEL_SOURCE_ROOT：{offenders}",
        )


if __name__ == "__main__":
    unittest.main()
