from __future__ import annotations

import unittest
from pathlib import Path

from kden_v375.r14 import verify_r14_registry_bundle
from kden_v375.r14_records import (
    read_historical_record_identity,
    verify_r14_attestation,
)
from kden_v375.r14_schedule import verify_r14_cycle_schedule


ROOT = Path(__file__).resolve().parents[2]


class R14SuccessorPublicationTests(unittest.TestCase):
    def test_registry_and_spatial_successor_is_sealed(self) -> None:
        bundle = verify_r14_registry_bundle(ROOT)["bundle"]
        record = verify_r14_attestation(ROOT, "STEP_01_R14")
        self.assertEqual(bundle["field_counts"], {"wrfsfcf": 13, "wrfsubhf": 1, "total": 14})
        self.assertEqual(
            record["gate_evidence"]["registry_bundle_sha256"],
            bundle["bundle_sha256"],
        )

    def test_right_open_schedule_and_lineage_are_sealed(self) -> None:
        step01 = verify_r14_attestation(ROOT, "STEP_01_R14")
        step02 = verify_r14_attestation(ROOT, "STEP_02_R14")
        schedule = verify_r14_cycle_schedule(ROOT)
        historical = read_historical_record_identity(ROOT, 2)
        self.assertEqual(
            step02["predecessor_hashes"]["STEP_01_R14"],
            step01["record_sha256"],
        )
        self.assertEqual(
            step02["predecessor_hashes"]["HISTORICAL_STEP_02"],
            historical["record_sha256"],
        )
        self.assertEqual(
            schedule["manifest"]["historical_step02_pass"]["record_sha256"],
            historical["record_sha256"],
        )
        self.assertEqual(
            schedule["gate_evidence"]["native_state_count"],
            {"wrfsfcf": 563_583, "wrfsubhf": 2_156_601},
        )


if __name__ == "__main__":
    unittest.main()
