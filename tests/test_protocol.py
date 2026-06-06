from __future__ import annotations

import unittest

from system.evaluation.protocol import REQUIRED_MODELS, attack_spec, load_protocol, protocol_summary, validate_protocol


class ProtocolTests(unittest.TestCase):
    def test_protocol_is_valid_and_registers_all_models(self) -> None:
        protocol = load_protocol()
        self.assertEqual(validate_protocol(protocol), [])
        self.assertEqual(set(protocol["models"]), REQUIRED_MODELS)

    def test_attack_ids_are_unique(self) -> None:
        protocol = load_protocol()
        ids = [item["id"] for item in protocol["attacks"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(attack_spec("jpeg50")["parameters"]["quality"], 50)

    def test_protocol_summary_exposes_metric_semantics(self) -> None:
        summary = protocol_summary()
        self.assertEqual(summary["schema_version"], "evaluation_protocol.v1")
        self.assertIn("ber", summary["metric_semantics"])
        self.assertIn("KAD-Net", summary["models"])


if __name__ == "__main__":
    unittest.main()
