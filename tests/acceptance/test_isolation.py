from __future__ import annotations

import ast
import unittest
from pathlib import Path

from kden_v375.contracts import validate_runtime_isolation


ROOT = Path(__file__).resolve().parents[2]


class IsolationAcceptanceTests(unittest.TestCase):
    def test_runtime_tree_has_no_fossil_import_or_path(self) -> None:
        evidence = validate_runtime_isolation(ROOT)
        self.assertGreaterEqual(evidence["source_files_scanned"], 10)

    def test_packaging_discovers_only_the_new_namespace(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('include = ["kden_v375*"]', pyproject)
        self.assertIn('exclude = ["kden_panel*", "kden35*"]', pyproject)
        for path in (ROOT / "src/kden_v375").rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


if __name__ == "__main__":
    unittest.main()

