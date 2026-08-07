from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import create_release_snapshot as snapshot


class ReleaseSnapshotTests(unittest.TestCase):
    def test_snapshot_tracks_archived_release_core_chain(self) -> None:
        tracked = snapshot.tracked_report_files()
        self.assertEqual(
            set(name for name in tracked if name.startswith("release_core_")),
            {
                "release_core_manifest",
                "release_core_signature",
                "release_core_public_key",
            },
        )
        self.assertEqual(
            {name for name in tracked if name.startswith("mea_")},
            {
                "mea_dataset_manifest",
                "mea_run_config",
                "mea_raw_results",
                "mea_progress",
                "mea_summary",
            },
        )
        self.assertEqual(
            {name for name in tracked if name.startswith("supply_chain_")},
            {
                "supply_chain_requirements_lock",
                "supply_chain_build_manifest",
                "supply_chain_python_sbom",
            },
        )
        self.assertIn("collaboration_policy", tracked)
        self.assertEqual(
            {
                name
                for name in tracked
                if name.startswith("simswap_")
                and not name.startswith("simswap_visual_")
            },
            {
                "simswap_pair_manifest",
                "simswap_message_registry",
                "simswap_run_config",
                "simswap_identity_embeddings",
                "simswap_results",
                "simswap_progress",
                "simswap_assets_manifest",
                "simswap_summary",
            },
        )
        self.assertEqual(
            len([name for name in tracked if name.startswith("simswap_visual_")]),
            176,
        )

    def test_remote_origin_drops_credentials_query_and_fragment(self) -> None:
        with patch.object(
            snapshot,
            "run_git",
            return_value=(
                "https://token@example.com/org/repo.git"
                "?access_token=sensitive#fragment"
            ),
        ):
            self.assertEqual(
                snapshot.sanitized_remote_origin(),
                "https://example.com/org/repo.git",
            )

    def test_git_status_failure_is_fail_closed(self) -> None:
        with patch.object(snapshot, "run_git", return_value=None):
            result = snapshot.git_snapshot()
        self.assertTrue(result["dirty"])
        self.assertFalse(result["status_available"])
        self.assertIsNone(result["commit"])


if __name__ == "__main__":
    unittest.main()
