from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kden_v375.io.cache import SourceGroupCache
from kden_v375.io.http_range import MessageRange, coalesce_exact_adjacent_ranges


class CacheTests(unittest.TestCase):
    def test_partial_pair_is_quarantined_and_never_trusted(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            group = coalesce_exact_adjacent_ranges(
                "source", (MessageRange("a", 0, 8),)
            )[0]
            cache = SourceGroupCache(root / "cache", root / "quarantine")
            payload_path, _ = cache.paths(group)
            payload_path.parent.mkdir(parents=True)
            payload_path.write_bytes(b"GRIBa7777")
            self.assertIsNone(cache.load(group))
            self.assertFalse(payload_path.exists())
            quarantined = list((root / "quarantine" / group.group_id).glob("*/*.grib2"))
            self.assertEqual(len(quarantined), 1)

    def test_complete_pair_is_hash_verified(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            group = coalesce_exact_adjacent_ranges(
                "source", (MessageRange("a", 0, 8),)
            )[0]
            cache = SourceGroupCache(root / "cache", root / "quarantine")
            payload = b"GRIBa7777"
            self.assertEqual(cache.publish(group, payload)["cache_status"], "PUBLISHED")
            self.assertEqual(cache.load(group), payload)


if __name__ == "__main__":
    unittest.main()

