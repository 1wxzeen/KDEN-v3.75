from __future__ import annotations

import json
import unittest
from datetime import date

from kden_v375.prefit.p02_rules import (
    catalog_schema,
    evaluate_audit_document,
    parse_audit_payload,
)


def _event(source: str, value: int, timestamp: str, product_id: str) -> dict[str, object]:
    return {
        "source": source,
        "value": value,
        "utc_valid": timestamp,
        "varname": "high",
        "link": f"https://example.invalid/product?pid={product_id}",
        "description": "synthetic bounded rule test",
    }


def _document(target: date, events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "station": "KDEN",
        "date": target.isoformat(),
        "tzname": "America/Denver",
        "high": {"events": events},
    }


class PrefitP02TruthRuleTests(unittest.TestCase):
    def test_audit_payload_identity_is_strict(self) -> None:
        target = date(2026, 9, 7)
        payload = json.dumps(_document(target, [])).encode("utf-8")
        parsed = parse_audit_payload(payload, target)
        self.assertEqual(parsed["station"], "KDEN")

    def test_unanimous_cli_and_cf6_is_accepted(self) -> None:
        target = date(2026, 9, 7)
        cli = "202609080731-KBOU-CDUS45-CLIDEN"
        cf6 = "202609080740-KBOU-CXUS55-CF6DEN"
        document = _document(
            target,
            [
                _event("CLI", 88, "2026-09-08T07:31:00Z", cli),
                _event("CF6", 88, "2026-09-08T07:40:00Z", cf6),
            ],
        )
        row, _ = evaluate_audit_document(
            target=target,
            document=document,
            raw_sha256="0" * 64,
            product_ids_available={cli, cf6},
        )
        self.assertEqual(row["y_audited_f"], 88)
        self.assertEqual(row["truth_qc_status"], "auto_audited_cli_cf6_unanimous")

    def test_nonunanimous_tail_is_unresolved(self) -> None:
        target = date(2026, 9, 8)
        document = _document(
            target,
            [
                _event(
                    "CLI",
                    81,
                    "2026-09-09T07:31:00Z",
                    "202609090731-KBOU-CDUS45-CLIDEN",
                ),
                _event(
                    "CF6",
                    82,
                    "2026-09-09T07:40:00Z",
                    "202609090740-KBOU-CXUS55-CF6DEN",
                ),
            ],
        )
        row, _ = evaluate_audit_document(
            target=target,
            document=document,
            raw_sha256="1" * 64,
            product_ids_available=set(),
        )
        self.assertIsNone(row["y_audited_f"])
        self.assertEqual(
            row["truth_qc_status"],
            "unresolved_cli_cf6_or_chronology_conflict",
        )

    def test_holdout_rule_never_emits_target(self) -> None:
        target = date(2026, 1, 1)
        document = _document(
            target,
            [
                _event(
                    "CLI",
                    50,
                    "2026-01-02T07:31:00Z",
                    "202601020731-KBOU-CDUS45-CLIDEN",
                ),
                _event(
                    "CF6",
                    50,
                    "2026-01-02T07:40:00Z",
                    "202601020740-KBOU-CXUS55-CF6DEN",
                ),
            ],
        )
        row, _ = evaluate_audit_document(
            target=target,
            document=document,
            raw_sha256="2" * 64,
            product_ids_available=set(),
            sealed=True,
        )
        self.assertIsNone(row["y_audited_f"])
        self.assertEqual(row["truth_qc_status"], "sealed_pending_audit")

    def test_guarded_2021_correction_requires_exact_evidence(self) -> None:
        target = date(2021, 1, 20)
        selected = "202101210731-KBOU-CDUS45-CLIDEN"
        document = _document(
            target,
            [
                _event("CLI", 59, "2021-01-21T07:31:00Z", selected),
                _event(
                    "CF6",
                    59,
                    "2021-01-21T07:40:00Z",
                    "202101210740-KBOU-CXUS55-CF6DEN",
                ),
                _event(
                    "CLI",
                    39,
                    "2021-01-22T07:31:00Z",
                    "202101220731-KBOU-CDUS45-CLIDEN",
                ),
            ],
        )
        exception = {
            "approval_status": "approved_existing_project_record",
            "expected_iem_atomic_raw_f": "39",
            "expected_cli_first_completed_f": "59",
            "expected_cf6_first_f": "59",
            "y_audited_f": "59",
            "selected_product_id": selected,
            "truth_qc_status": "audited_guarded_exception",
            "rule_id": "KDEN_CLI_20210120_OVERWRITE",
        }
        row, _ = evaluate_audit_document(
            target=target,
            document=document,
            raw_sha256="3" * 64,
            product_ids_available=set(),
            atomic_value=39,
            exception=exception,
        )
        self.assertEqual(row["y_audited_f"], 59)
        self.assertEqual(row["truth_qc_status"], "audited_guarded_exception")

    def test_guarded_2022_correction_requires_exact_evidence(self) -> None:
        target = date(2022, 4, 18)
        selected = "202204190733-KBOU-CDUS45-CLIDEN"
        document = _document(
            target,
            [
                _event("CLI", 65, "2022-04-19T07:33:00Z", selected),
                _event(
                    "CF6",
                    65,
                    "2022-04-19T07:40:00Z",
                    "202204190740-KBOU-CXUS55-CF6DEN",
                ),
                _event(
                    "CLI",
                    80,
                    "2022-04-20T07:33:00Z",
                    "202204200733-KBOU-CDUS45-CLIDEN",
                ),
            ],
        )
        exception = {
            "approval_status": "approved_existing_project_record",
            "expected_iem_atomic_raw_f": "80",
            "expected_cli_first_completed_f": "65",
            "expected_cf6_first_f": "65",
            "y_audited_f": "65",
            "selected_product_id": selected,
            "truth_qc_status": "audited_guarded_exception",
            "rule_id": "KDEN_CLI_20220418_MISDATE",
        }
        row, _ = evaluate_audit_document(
            target=target,
            document=document,
            raw_sha256="4" * 64,
            product_ids_available=set(),
            atomic_value=80,
            exception=exception,
        )
        self.assertEqual(row["y_audited_f"], 65)
        self.assertEqual(row["exception_rule_id"], "KDEN_CLI_20220418_MISDATE")

    def test_catalog_schema_keeps_truth_separate_and_explicit(self) -> None:
        names = set(catalog_schema().names)
        self.assertIn("truth_evidence_status", names)
        self.assertIn("label_available_for_supervised_use", names)
        self.assertIn("y_audited_f", names)
        self.assertNotIn("feature_vector", names)


if __name__ == "__main__":
    unittest.main()
