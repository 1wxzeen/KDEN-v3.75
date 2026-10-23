from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kden_v375.registries import load_field_registry, load_parquet_schema
from kden_v375.request_plans import (
    FORBIDDEN_PLAN_COLUMNS,
    expected_product_counts,
    load_plan_policy,
    native_leads,
    planned_interval,
    source_file_forecast_hour,
    validate_fh00_evidence,
)
from kden_v375.schedule import build_schedule_rows, load_schedule_policy


ROOT = Path(__file__).resolve().parents[2]


class RequestPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_plan_policy(ROOT)

    def test_subhourly_repeated_blocks_map_to_parent_hour_file(self) -> None:
        self.assertEqual(
            [source_file_forecast_hour("wrfsubhf", lead) for lead in (0, 15, 30, 45, 60)],
            [0, 1, 1, 1, 1],
        )
        self.assertEqual(source_file_forecast_hour("wrfsubhf", 75), 2)
        self.assertEqual(source_file_forecast_hour("wrfsfcf", 18 * 60), 18)

    def test_fh00_interval_override_and_positive_lead_contract(self) -> None:
        fields = {row["field_id"]: row for row in load_field_registry(ROOT, "wrfsubhf")}
        valid = datetime(2024, 6, 1, 6, tzinfo=UTC)
        zero = planned_interval(
            fields["Q09"], 0, valid, self.policy["fh00_selector_overrides"]
        )
        positive = planned_interval(
            fields["Q09"], 15, valid, self.policy["fh00_selector_overrides"]
        )
        self.assertEqual(zero[2], 0)
        self.assertEqual(zero[3], zero[4])
        self.assertEqual(positive[2], 5)
        self.assertEqual((positive[4] - positive[3]).total_seconds(), 300)
        self.assertEqual(
            validate_fh00_evidence(ROOT)["override_fields"],
            ["H38", "Q09", "Q10", "Q11", "Q13"],
        )

    def test_full_schedule_request_counts_and_target_cap(self) -> None:
        schedule = build_schedule_rows(load_schedule_policy(ROOT))
        by_product = {
            product: [row for row in schedule if row["product"] == product]
            for product in ("wrfsfcf", "wrfsubhf")
        }
        hourly = expected_product_counts(by_product["wrfsfcf"], "wrfsfcf", 44)
        subhourly = expected_product_counts(by_product["wrfsubhf"], "wrfsubhf", 14)
        self.assertEqual(hourly["native_valid_state_count"], 585085)
        self.assertEqual(hourly["request_row_count"], 25158656)
        self.assertEqual(subhourly["native_valid_state_count"], 2173943)
        self.assertEqual(subhourly["request_row_count"], 30435202)
        self.assertTrue(
            all(
                row["cycle_init_utc"]
                + timedelta(minutes=max(native_leads(row, row["product"])))
                <= row["window_end_utc"]
                for row in schedule
            )
        )

    def test_plan_schema_has_no_checkpoint_or_observational_dependency(self) -> None:
        schema = load_parquet_schema(ROOT, "request_plan_v375.json")
        self.assertFalse(set(schema.names) & FORBIDDEN_PLAN_COLUMNS)


if __name__ == "__main__":
    unittest.main()
