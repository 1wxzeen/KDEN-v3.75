from __future__ import annotations

import json
import unittest
from pathlib import Path

from kden_v375.prefit.p01_foundation import (
    ENVIRONMENT_ID,
    FOUNDATION_PATH,
    PASS_PATH,
    SUBSTRATE_RELEASE_ID,
    TIME_ONTOLOGY_ID,
    TRUTH_RELEASE_ID,
    _stable_isolation_evidence,
    verify_p01,
)
from kden_v375.prefit.records import make_prefit_run_id, validate_prefit_run_id


ROOT = Path(__file__).resolve().parents[2]


class PrefitP01ContractTests(unittest.TestCase):
    def test_prefit_run_identity_is_stage_scoped(self) -> None:
        run_id = make_prefit_run_id(
            1,
            "ordinary",
            "foundation",
            timestamp="20260923T120000Z",
        )
        identity = validate_prefit_run_id(run_id, stage_no=1, scope="ordinary")
        self.assertEqual(identity["stage_no"], 1)
        self.assertEqual(identity["label"], "foundation")

    def test_foundation_contract_has_model_neutral_separation(self) -> None:
        if not (ROOT / FOUNDATION_PATH).is_file():
            self.skipTest("P01 has not been published")
        contract = json.loads((ROOT / FOUNDATION_PATH).read_text(encoding="utf-8"))
        self.assertEqual(contract["study"]["target_day_count"], 2080)
        self.assertEqual(contract["study"]["substrate_release_id"], SUBSTRATE_RELEASE_ID)
        self.assertEqual(contract["study"]["truth_release_id"], TRUTH_RELEASE_ID)
        self.assertEqual(contract["clock_ontology"]["ontology_id"], TIME_ONTOLOGY_ID)
        self.assertEqual(
            contract["environment_strategy"]["environment_id"], ENVIRONMENT_ID
        )
        self.assertTrue(contract["truth_contract"]["holdout_remains_sealed_through_p07"])
        self.assertEqual(
            contract["modeling_direction"]["relationship_to_substrate"],
            "adapter_not_definition",
        )
        self.assertEqual(
            contract["object_contracts"]["fold_assignments"]["primary_key"],
            ["target_date"],
        )

    def test_isolation_evidence_does_not_freeze_source_file_count(self) -> None:
        evidence = {
            "absolute_user_paths_found": 0,
            "denied_import_prefixes": ["example_a", "example_b"],
            "legacy_runtime_references_found": 0,
            "package_root": "src/kden_v375",
            "source_files_scanned": 53,
        }
        stable = _stable_isolation_evidence(evidence)
        self.assertNotIn("source_files_scanned", stable)
        evidence["source_files_scanned"] = 99
        self.assertEqual(stable, _stable_isolation_evidence(evidence))

    def test_p01_pass_verifies_when_present(self) -> None:
        if not (ROOT / PASS_PATH).is_file():
            self.skipTest("P01 has not been published")
        record = verify_p01(ROOT)
        self.assertEqual(record["status"], "PASS")
        self.assertEqual(record["stage_id"], "PREFIT_P01")
        self.assertEqual(record["gate_evidence"]["network_requests_made"], 0)
        self.assertEqual(record["gate_evidence"]["target_value_files_read"], 0)


if __name__ == "__main__":
    unittest.main()
