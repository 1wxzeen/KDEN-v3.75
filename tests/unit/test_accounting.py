from __future__ import annotations

import unittest

from kden_v375.accounting import (
    AcquisitionAccounting,
    ReconciliationError,
    RequestTerminalResult,
)


class AccountingTests(unittest.TestCase):
    def test_exact_terminal_reconciliation(self) -> None:
        ledger = AcquisitionAccounting({"a", "b"})
        ledger.record(
            RequestTerminalResult(
                "a", "SUCCESS", "source", "group", 1, 10, 2, 8
            )
        )
        ledger.record(
            RequestTerminalResult("b", "CONFIRMED_REMOTE_MISSING", "missing-source")
        )
        report = ledger.assert_reconciled()
        self.assertEqual(report["planned_request_count"], 2)
        self.assertEqual(report["success_count"], 1)
        self.assertEqual(report["confirmed_remote_missing_count"], 1)
        self.assertEqual(report["retry_count"], 1)

    def test_duplicate_terminal_request_is_rejected(self) -> None:
        ledger = AcquisitionAccounting({"a"})
        result = RequestTerminalResult("a", "SUCCESS", "source")
        ledger.record(result)
        with self.assertRaises(ReconciliationError):
            ledger.record(result)


if __name__ == "__main__":
    unittest.main()

