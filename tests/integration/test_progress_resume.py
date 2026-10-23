from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kden_v375.hashes import sha256_bytes
from kden_v375.io.atomic import atomic_write_bytes
from kden_v375.progress import ProgressCoordinator, publish_work_unit_manifest


class ProgressResumeTests(unittest.TestCase):
    def test_pause_resume_is_hash_verified_and_duplicate_free(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run_id = "kdenv375-s05-synthetic-20260912T120000Z-progress"
            plan_hash = sha256_bytes(b"plan")
            expected = {"u0": 0, "u1": 1}

            def publish(unit: str):
                artifact = Path("runs/test/artifacts") / f"{unit}.bin"
                manifest = Path("runs/test/manifests") / f"{unit}.json"
                atomic_write_bytes(root / artifact, unit.encode(), replace=False)
                return publish_work_unit_manifest(
                    project_root=root,
                    manifest_path=manifest,
                    run_id=run_id,
                    step_id="STEP_05",
                    request_plan_sha256=plan_hash,
                    unit_id=unit,
                    plan_ordinal=expected[unit],
                    artifact_path=artifact,
                    row_count=1,
                    request_count=1,
                    accepted_bytes=len(unit),
                )

            first = ProgressCoordinator(
                project_root=root,
                run_dir="runs/test",
                run_id=run_id,
                step_id="STEP_05",
                request_plan_sha256=plan_hash,
                expected_units=expected,
            )
            first.commit(publish("u0"))
            first.snapshot("PAUSED")

            second = ProgressCoordinator(
                project_root=root,
                run_dir="runs/test",
                run_id=run_id,
                step_id="STEP_05",
                request_plan_sha256=plan_hash,
                expected_units=expected,
            )
            self.assertEqual(second.remaining_units, ("u1",))
            receipt = publish("u1")
            second.commit(receipt)
            second.commit(receipt)
            snapshot = second.snapshot("COMPLETE")
            self.assertEqual(snapshot["completed_count"], 2)
            self.assertEqual(second.completed_request_count, 2)
            self.assertEqual(second.completed_accepted_bytes, 4)
            self.assertEqual(
                len(second.journal_path.read_text(encoding="utf-8").splitlines()), 2
            )


if __name__ == "__main__":
    unittest.main()
