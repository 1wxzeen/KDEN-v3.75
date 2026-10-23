from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from kden_v375.registries import BUNDLE_INPUTS, BUNDLE_PATH, seal_registry_bundle
from kden_v375.schedule import (
    HORIZON_EVIDENCE_PATH,
    SCHEDULE_MANIFEST_PATH,
    SCHEDULE_PARQUET_PATH,
    SCHEDULE_POLICY_PATH,
    seal_cycle_schedule,
    verify_cycle_schedule,
)


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(importlib.util.find_spec("pyarrow"), "pyarrow is not installed")
class CycleSchedulePublicationTests(unittest.TestCase):
    def test_parquet_and_manifest_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for relative in (
                "config/project_v375.toml",
                SCHEDULE_POLICY_PATH,
                HORIZON_EVIDENCE_PATH,
                *BUNDLE_INPUTS,
            ):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            seal_registry_bundle(root)
            result = seal_cycle_schedule(root, step01_record_sha256="0" * 64)
            verified = verify_cycle_schedule(root)
            self.assertEqual(result["manifest"], verified["manifest"])
            self.assertEqual(result["manifest"]["row_count"], 66558)
            self.assertTrue((root / SCHEDULE_PARQUET_PATH).is_file())
            self.assertTrue((root / SCHEDULE_MANIFEST_PATH).is_file())


if __name__ == "__main__":
    unittest.main()
