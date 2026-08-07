from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_script(module_name: str, filename: str):
    path = ROOT / "system" / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


GENERATOR = load_script("jys_generate_lfw_lidmark", "generate_lfw_lidmark.py")
TRAINER = load_script("jys_train_lidmark_stage1", "train_lidmark_stage1.py")
SELECTOR = load_script(
    "jys_select_lidmark_checkpoint", "select_lidmark_checkpoint.py"
)


class LIDMarkDatasetToolTests(unittest.TestCase):
    def test_identity_partition_is_deterministic_and_identity_disjoint(self) -> None:
        records = []
        for identity_index, count in enumerate((9, 7, 5, 4, 3, 3, 2, 2, 1, 1)):
            identity = f"person_{identity_index:02d}"
            records.extend({"identity": identity} for _ in range(count))

        partition, counts = GENERATOR.identity_partition(records)
        shuffled = list(records)
        random.Random(20260603).shuffle(shuffled)
        shuffled_partition, shuffled_counts = GENERATOR.identity_partition(shuffled)

        self.assertEqual(partition, shuffled_partition)
        self.assertEqual(counts, shuffled_counts)
        self.assertEqual(set(partition), set(counts))
        self.assertEqual(set(partition.values()), {"train", "val", "test"})
        for split in GENERATOR.SPLIT_ORDER:
            identities = {name for name, assigned in partition.items() if assigned == split}
            other_identities = {
                name for name, assigned in partition.items() if assigned != split
            }
            self.assertTrue(identities.isdisjoint(other_identities))

    def test_identity_codes_are_stable_collision_free_bipolar_values(self) -> None:
        identities = ["Zoe", "Alice", "Bob", "Alice"]
        first = GENERATOR.identity_codes(identities)
        second = GENERATOR.identity_codes(reversed(identities))
        self.assertEqual(first, second)
        self.assertEqual(len(set(first.values())), len(first))
        encoded = {
            identity: GENERATOR.bipolar_code_values(code)
            for identity, code in first.items()
        }
        self.assertEqual(len(set(encoded.values())), len(first))
        self.assertTrue(all(len(bits) == 16 for bits in encoded.values()))
        self.assertTrue(
            all(bit in {-1, 1} for bits in encoded.values() for bit in bits)
        )

    def test_visible_gpu_parser_rejects_multi_gpu_masks(self) -> None:
        self.assertEqual(GENERATOR.parse_visible_gpu("2"), 2)
        for invalid in (None, "", "2,7", "cuda:2", "-1"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(RuntimeError):
                    GENERATOR.parse_visible_gpu(invalid)

    def test_generator_paths_are_confined_to_data_root(self) -> None:
        accepted = GENERATOR.resolve_data_path(GENERATOR.DATA_ROOT / "lfw", "raw-root")
        self.assertEqual(accepted, (GENERATOR.DATA_ROOT / "lfw").resolve())
        with self.assertRaises(ValueError):
            GENERATOR.resolve_data_path(
                GENERATOR.DATA_ROOT.parent / "outside-data-root", "output-root"
            )


class LIDMarkTrainerToolTests(unittest.TestCase):
    def test_stage1_config_is_portable_and_preregistered(self) -> None:
        config = TRAINER.build_stage1_config(
            "lidmark-unit-s7-128", seed=7, batch_size=64, epochs=3
        )
        self.assertEqual(config["seed"], 7)
        self.assertEqual(config["batch_size"], 64)
        self.assertEqual(config["epochs"], 3)
        self.assertEqual(config["watermark_length"], 152)
        self.assertEqual(config["train_transform"], "resize_normalize_no_crop")
        self.assertTrue(config["validation"]["enable"])
        self.assertTrue(config["verify_dataset_files"])
        for field in TRAINER.PORTABLE_PATH_FIELDS:
            self.assertFalse(Path(config[field]).is_absolute(), field)
            self.assertNotIn("..", Path(config[field]).parts)

    def test_stage1_config_materializes_only_below_explicit_roots(self) -> None:
        config = TRAINER.build_stage1_config("lidmark-unit-s7-128", seed=7)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            roots = {
                "project": base / "project",
                "data": base / "data",
                "weights": base / "weights",
                "reports": base / "reports",
                "model-sources": base / "models",
            }
            materialized = TRAINER.materialize_config(config, roots)
            self.assertEqual(
                Path(materialized["source_root"]), roots["model-sources"] / "LIDMark"
            )
            self.assertEqual(
                Path(materialized["dataset_manifest"]),
                roots["data"]
                / "lfw"
                / "lidmark_identity_disjoint"
                / "manifests"
                / "dataset_manifest.json",
            )
            for field in TRAINER.PORTABLE_PATH_FIELDS:
                self.assertTrue(Path(materialized[field]).is_absolute(), field)

    def test_absolute_or_traversing_config_paths_are_rejected(self) -> None:
        config = TRAINER.build_stage1_config("lidmark-unit-s7-128", seed=7)
        for invalid in ("/tmp/data", "data/../outside"):
            mutated = dict(config)
            mutated["dataset_manifest"] = invalid
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    TRAINER.validate_stage1_config(mutated)

    def test_checkpoint_epoch_parser_is_strict(self) -> None:
        self.assertEqual(TRAINER.checkpoint_epoch(Path("checkpoint_epoch_20.pth")), 20)
        for invalid in ("checkpoint_epoch_0.pth", "epoch_1.pth", "checkpoint_epoch_1.pt"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    TRAINER.checkpoint_epoch(Path(invalid))

    def test_resume_checkpoint_is_bound_to_hash_size_and_logical_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root = root / "report"
            report_root.mkdir()
            checkpoint = root / "checkpoint_epoch_3.pth"
            checkpoint.write_bytes(b"trusted-checkpoint")
            record = {
                "epoch": 3,
                "path": TRAINER.logical_path(checkpoint),
                "size_bytes": checkpoint.stat().st_size,
                "sha256": TRAINER.sha256_file(checkpoint),
            }
            (report_root / "checkpoint_hashes.json").write_text(
                json.dumps({"checkpoints": [record]}) + "\n",
                encoding="utf-8",
            )
            verified = TRAINER.verify_resume_checkpoint(checkpoint, report_root)
            self.assertEqual(verified["epoch"], 3)
            checkpoint.write_bytes(b"tampered-checkpoint")
            with self.assertRaises(RuntimeError):
                TRAINER.verify_resume_checkpoint(checkpoint, report_root)

    def test_repository_scripts_do_not_embed_host_roots(self) -> None:
        for filename in (
            "generate_lfw_lidmark.py",
            "train_lidmark_stage1.py",
            "select_lidmark_checkpoint.py",
            "run_lidmark_lfw_benchmark.py",
        ):
            content = (ROOT / "system" / "scripts" / filename).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("/root/", content, filename)
            self.assertNotIn("/home/", content, filename)


class LIDMarkModelSelectionTests(unittest.TestCase):
    @staticmethod
    def epoch_record(
        epoch: int,
        *,
        g_loss: float,
        psnr: float,
        landmark_aed: float,
        id_ber: float = 0.0,
        strict_reload: bool = True,
    ) -> dict:
        return {
            "epoch": epoch,
            "train": {"g_loss": g_loss + 0.1, "id_ber": id_ber},
            "val": {
                "g_loss": g_loss,
                "psnr": psnr,
                "landmark_aed": landmark_aed,
                "id_ber": id_ber,
            },
            "gradient_finite_all_batches": True,
            "loss_metric_finite_all_batches": True,
            "strict_reload": {"strict_reload": strict_reload},
        }

    def test_selection_uses_declared_objective_and_tie_break_order(self) -> None:
        tied = [
            self.epoch_record(1, g_loss=0.4, psnr=30.0, landmark_aed=4.0),
            self.epoch_record(2, g_loss=0.4, psnr=31.0, landmark_aed=5.0),
            self.epoch_record(3, g_loss=0.4, psnr=31.0, landmark_aed=3.0),
            self.epoch_record(4, g_loss=0.4, psnr=31.0, landmark_aed=3.0),
        ]
        selected, _ = SELECTOR.select_best_epoch(tied)
        self.assertEqual(selected["epoch"], 3)

        primary_winner = self.epoch_record(
            5, g_loss=0.39, psnr=1.0, landmark_aed=100.0
        )
        selected, _ = SELECTOR.select_best_epoch(tied + [primary_winner])
        self.assertEqual(selected["epoch"], 5)

    def test_selection_excludes_failed_reload_nonfinite_and_high_ber(self) -> None:
        valid = self.epoch_record(1, g_loss=0.4, psnr=30.0, landmark_aed=3.0)
        failed_reload = self.epoch_record(
            2,
            g_loss=0.1,
            psnr=99.0,
            landmark_aed=0.1,
            strict_reload=False,
        )
        nonfinite = self.epoch_record(
            3, g_loss=float("nan"), psnr=99.0, landmark_aed=0.1
        )
        high_ber = self.epoch_record(
            4, g_loss=0.1, psnr=99.0, landmark_aed=0.1, id_ber=0.010001
        )
        selected, assessments = SELECTOR.select_best_epoch(
            [valid, failed_reload, nonfinite, high_ber]
        )
        self.assertEqual(selected["epoch"], 1)
        self.assertEqual(
            {item["epoch"] for item in assessments if not item["eligible"]},
            {2, 3, 4},
        )

    def test_selection_report_rehashes_every_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_root = root / "report"
            weight_root = root / "weights"
            report_root.mkdir()
            weight_root.mkdir()
            history_records = []
            checkpoint_records = []
            for epoch, g_loss in ((1, 0.4), (2, 0.3)):
                checkpoint = weight_root / f"checkpoint_epoch_{epoch}.pth"
                checkpoint.write_bytes(f"checkpoint-{epoch}".encode())
                checkpoint_record = {
                    "epoch": epoch,
                    "path": str(checkpoint),
                    "size_bytes": checkpoint.stat().st_size,
                    "sha256": SELECTOR.sha256_file(checkpoint),
                }
                record = self.epoch_record(
                    epoch, g_loss=g_loss, psnr=30.0, landmark_aed=3.0
                )
                record["checkpoint"] = dict(checkpoint_record)
                record["strict_reload"]["checkpoint_sha256"] = checkpoint_record[
                    "sha256"
                ]
                history_records.append(record)
                checkpoint_records.append(checkpoint_record)
            history_path = report_root / "history.json"
            hashes_path = report_root / "checkpoint_hashes.json"
            state_path = report_root / "run_state.json"
            history_path.write_text(
                json.dumps({"epochs": history_records}), encoding="utf-8"
            )
            hashes_path.write_text(
                json.dumps({"checkpoints": checkpoint_records}), encoding="utf-8"
            )
            state_path.write_text(
                json.dumps({"status": "complete", "completed_epoch": 2}),
                encoding="utf-8",
            )
            report = SELECTOR.build_selection_report(
                "lidmark-unit-s7-128",
                history_path,
                hashes_path,
                state_path,
                weight_root,
                2,
            )
            self.assertTrue(report["all_checkpoint_integrity_verified"])
            self.assertEqual(report["audited_checkpoint_count"], 2)
            self.assertEqual(report["selected"]["epoch"], 2)


if __name__ == "__main__":
    unittest.main()
