from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from kden_v375.acceptance.workflow import (
    AcceptanceCheckpoint,
    _arrow_to_pylist,
    _prepare_arrow_python_conversion,
    _regenerate_journal,
    build_acceptance_context,
    load_acceptance_contract,
    validate_acceptance_unit,
)
from kden_v375.hashes import canonical_json_bytes, sha256_bytes


ROOT = Path(__file__).resolve().parents[2]


class AcceptanceContractTests(unittest.TestCase):
    def test_contract_freezes_complete_r14_counts(self) -> None:
        contract = load_acceptance_contract(ROOT)
        self.assertEqual(contract["expected"]["work_unit_count"], 4_161)
        self.assertEqual(contract["expected"]["logical_request_count"], 8_919_598)
        self.assertFalse(contract["execution"]["network_allowed"])
        self.assertEqual(contract["execution"]["max_local_validation_workers"], 4)

    def test_checkpoint_is_transactional_and_resumable(self) -> None:
        body = {
            "schema_version": "KDEN_V375_STEP08_UNIT_RESULT_V1",
            "status": "PASS",
            "sequence": 0,
            "unit_id": "UNIT_0",
            "product": "wrfsfcf",
            "target_day": "2021-01-01",
            "request_count": 1,
            "local_size_bytes": 10,
        }
        result = {**body, "result_sha256": sha256_bytes(canonical_json_bytes(body))}
        metadata = {
            "run_id": "kdenv375-s08-validation-20260922T050000Z-test",
            "contract_sha256": "a" * 64,
            "r14_pass_sha256": "b" * 64,
            "step07_pass_sha256": "c" * 64,
        }
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "checkpoint.sqlite3"
            checkpoint = AcceptanceCheckpoint(database, metadata)
            checkpoint.commit(result)
            checkpoint.close()
            resumed = AcceptanceCheckpoint(database, metadata)
            self.assertEqual(len(resumed.rows), 1)
            self.assertEqual(resumed.rows[0]["result"], result)
            journal = root / "completions.jsonl"
            tip = _regenerate_journal(journal, resumed.rows, metadata["run_id"])
            record = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(record["record_sha256"], tip)
            resumed.close()

    def test_arrow_python_conversion_is_serialized_and_timezone_ready(self) -> None:
        active = 0
        maximum_active = 0
        counter_lock = threading.Lock()

        class ProbeTable:
            def to_pylist(self) -> list[dict[str, int]]:
                nonlocal active, maximum_active
                with counter_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                time.sleep(0.01)
                with counter_lock:
                    active -= 1
                return [{"value": 1}]

        _prepare_arrow_python_conversion()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(_arrow_to_pylist, [ProbeTable() for _ in range(8)])
            )
        self.assertEqual(maximum_active, 1)
        self.assertEqual(results, [[{"value": 1}]] * 8)


class RealArchiveAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "state/R14_PASS.json").is_file():
            raise unittest.SkipTest("completed R14 archive is unavailable")
        cls.context = build_acceptance_context(
            ROOT, _deep_schedule_verification=False
        )
        cls.by_id = {unit.spec.unit_id: unit for unit in cls.context.units}

    def test_static_h14_unit_passes_deep_acceptance(self) -> None:
        result = validate_acceptance_unit(
            self.context, self.by_id["WRFSFCF_R14_STATIC_H14"]
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["field_ids"], ["H14"])
        self.assertEqual(result["request_count"], 1)

    def test_known_2022_missingness_reconciles(self) -> None:
        result = validate_acceptance_unit(
            self.context, self.by_id["WRFSFCF_R14_DAY_2022-02-26"]
        )
        self.assertEqual(result["confirmed_remote_missing_count"], 12)
        self.assertEqual(result["quarantined_count"], 0)

    def test_q05_dst_day_passes_deep_acceptance(self) -> None:
        result = validate_acceptance_unit(
            self.context, self.by_id["WRFSUBHF_Q05_R14_DAY_2023-03-12"]
        )
        self.assertEqual(result["field_ids"], ["Q05"])
        self.assertEqual(result["confirmed_remote_missing_count"], 0)
        self.assertEqual(result["quarantined_count"], 0)


if __name__ == "__main__":
    unittest.main()
