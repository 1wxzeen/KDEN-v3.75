from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kden_v375.io.atomic import PublicationExistsError, atomic_write_bytes


class AtomicPublicationTests(unittest.TestCase):
    def test_interruption_preserves_destination_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            destination = root / "artifact.bin"
            atomic_write_bytes(destination, b"old")

            def interrupt(_path: Path) -> None:
                raise RuntimeError("interrupt")

            with self.assertRaisesRegex(RuntimeError, "interrupt"):
                atomic_write_bytes(destination, b"new", before_replace=interrupt)
            self.assertEqual(destination.read_bytes(), b"old")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_immutable_publication_refuses_replace(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            destination = Path(name) / "artifact.bin"
            atomic_write_bytes(destination, b"first", replace=False)
            with self.assertRaises(PublicationExistsError):
                atomic_write_bytes(destination, b"second", replace=False)


if __name__ == "__main__":
    unittest.main()

