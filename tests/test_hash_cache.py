from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from system.backend import signing


class StableHashCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        signing._sha256_stable_file_identity.cache_clear()

    def tearDown(self) -> None:
        signing._sha256_stable_file_identity.cache_clear()

    def test_reuses_digest_for_the_same_file_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.bin"
            path.write_bytes(b"fixed-evidence" * 1024)
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(signing.sha256_file(path), expected)
            first = signing._sha256_stable_file_identity.cache_info()
            self.assertEqual(signing.sha256_file(path), expected)
            second = signing._sha256_stable_file_identity.cache_info()
            self.assertEqual(second.hits, first.hits + 1)

    def test_same_size_in_place_mutation_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.bin"
            path.write_bytes(b"AAAA")
            before = signing.sha256_file(path)
            path.write_bytes(b"BBBB")
            after = signing.sha256_file(path)
            self.assertNotEqual(before, after)
            self.assertEqual(after, hashlib.sha256(b"BBBB").hexdigest())

    def test_atomic_replacement_invalidates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "manifest.json"
            replacement = root / "replacement.json"
            path.write_bytes(b"old")
            before = signing.sha256_file(path)
            replacement.write_bytes(b"new")
            replacement.replace(path)
            after = signing.sha256_file(path)
            self.assertNotEqual(before, after)
            self.assertEqual(after, hashlib.sha256(b"new").hexdigest())


if __name__ == "__main__":
    unittest.main()
