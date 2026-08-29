from __future__ import annotations

import threading
import time
import unittest

from system.backend.snapshot_cache import SnapshotCache


class SnapshotCacheTests(unittest.TestCase):
    def test_cache_returns_defensive_copies_and_refreshes_after_ttl(self) -> None:
        calls = 0

        def loader() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"calls": calls, "nested": {"ok": True}}

        cache = SnapshotCache(loader, ttl_seconds=1, name="test")
        first = cache.get()
        first["nested"]["ok"] = False  # type: ignore[index]
        second = cache.get()
        self.assertEqual(calls, 1)
        self.assertEqual(second, {"calls": 1, "nested": {"ok": True}})

        time.sleep(1.05)
        third = cache.get()
        self.assertEqual(calls, 2)
        self.assertEqual(third["calls"], 2)

    def test_concurrent_miss_is_coalesced(self) -> None:
        calls = 0
        barrier = threading.Barrier(5)

        def loader() -> dict[str, int]:
            nonlocal calls
            calls += 1
            time.sleep(0.05)
            return {"calls": calls}

        cache = SnapshotCache(loader, ttl_seconds=30, name="test")
        results: list[dict[str, object]] = []

        def worker() -> None:
            barrier.wait()
            results.append(cache.get())

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(calls, 1)
        self.assertEqual(results, [{"calls": 1}] * 5)

    def test_clear_forces_refresh(self) -> None:
        calls = 0

        def loader() -> dict[str, int]:
            nonlocal calls
            calls += 1
            return {"calls": calls}

        cache = SnapshotCache(loader, ttl_seconds=30, name="test")
        cache.get()
        cache.clear()
        self.assertEqual(cache.get(), {"calls": 2})


if __name__ == "__main__":
    unittest.main()
