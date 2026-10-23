from __future__ import annotations

import unittest
from collections import Counter
from datetime import timedelta
from pathlib import Path

from kden_v375.r14_schedule import (
    EXPECTED_NATIVE_STATE_COUNTS,
    R14ScheduleContractError,
    build_r14_schedule_rows,
    load_r14_schedule_policy,
    validate_r14_schedule_rows,
)
from kden_v375.request_plans import native_leads


ROOT = Path(__file__).resolve().parents[2]


class R14RightOpenScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_r14_schedule_policy(ROOT)
        cls.rows = build_r14_schedule_rows(cls.policy)
        cls.evidence = validate_r14_schedule_rows(cls.rows, cls.policy)

    def test_exact_counts_and_dst_envelope(self) -> None:
        self.assertEqual(len(self.rows), 66_558)
        self.assertEqual(
            self.evidence["per_product_cycle_count"],
            {"wrfsfcf": 33_279, "wrfsubhf": 33_279},
        )
        self.assertEqual(
            self.evidence["native_state_count"], EXPECTED_NATIVE_STATE_COUNTS
        )
        self.assertEqual(
            self.evidence["target_date_cycle_classes"],
            {"spring_forward_15": 6, "ordinary_16": 2_069, "fall_back_17": 5},
        )

    def test_no_native_valid_time_equals_window_end(self) -> None:
        self.assertTrue(all(
            row["retained_valid_end_utc"] < row["window_end_utc"]
            for row in self.rows
        ))
        counts = Counter()
        for row in self.rows:
            leads = native_leads(row, row["product"])
            counts[row["product"]] += len(leads)
            last_valid = row["cycle_init_utc"] + timedelta(minutes=leads[-1])
            self.assertLess(last_valid, row["window_end_utc"])
        self.assertEqual(dict(counts), EXPECTED_NATIVE_STATE_COUNTS)

    def test_endpoint_capped_rows_stop_one_native_interval_before_07z(self) -> None:
        hourly = next(
            row for row in self.rows
            if row["product"] == "wrfsfcf"
            and row["retained_valid_end_utc"] == row["window_end_utc"] - timedelta(hours=1)
        )
        subhourly = next(
            row for row in self.rows
            if row["product"] == "wrfsubhf"
            and row["retained_valid_end_utc"] == row["window_end_utc"] - timedelta(minutes=15)
        )
        self.assertEqual(hourly["retained_valid_end_utc"].hour, 6)
        self.assertEqual(subhourly["retained_valid_end_utc"].minute, 45)

    def test_validator_rejects_historical_inclusive_endpoint(self) -> None:
        rows = [dict(row) for row in self.rows]
        index = next(
            index for index, row in enumerate(rows)
            if row["retained_valid_end_utc"]
            == row["window_end_utc"] - timedelta(hours=1)
            and row["product"] == "wrfsfcf"
        )
        rows[index]["retained_valid_end_utc"] = rows[index]["window_end_utc"]
        with self.assertRaises(R14ScheduleContractError):
            validate_r14_schedule_rows(rows, self.policy)


if __name__ == "__main__":
    unittest.main()
