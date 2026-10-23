from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from kden_v375.schedule import (
    build_schedule_rows,
    cycle_candidates_for_target,
    load_schedule_policy,
    native_horizon,
    validate_schedule_rows,
)


ROOT = Path(__file__).resolve().parents[2]


class CycleScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_schedule_policy(ROOT)
        cls.rows = build_schedule_rows(cls.policy)
        cls.evidence = validate_schedule_rows(cls.rows, cls.policy)

    def test_full_schedule_counts_and_unique_keys(self) -> None:
        self.assertEqual(self.evidence["target_date_count"], 2080)
        self.assertEqual(
            self.evidence["per_product_cycle_count"],
            {"wrfsfcf": 33279, "wrfsubhf": 33279},
        )
        self.assertEqual(
            self.evidence["target_date_cycle_classes"],
            {"spring_forward_15": 6, "ordinary_16": 2069, "fall_back_17": 5},
        )
        self.assertTrue(self.evidence["utc_cycle_keys_unique_per_product"])

    def test_every_2021_through_2026_dst_transition(self) -> None:
        transitions = {
            2021: (date(2021, 3, 14), date(2021, 11, 7)),
            2022: (date(2022, 3, 13), date(2022, 11, 6)),
            2023: (date(2023, 3, 12), date(2023, 11, 5)),
            2024: (date(2024, 3, 10), date(2024, 11, 3)),
            2025: (date(2025, 3, 9), date(2025, 11, 2)),
            2026: (date(2026, 3, 8), date(2026, 11, 1)),
        }
        for year, (spring, fall) in transitions.items():
            with self.subTest(year=year, transition="spring"):
                spring_rows = cycle_candidates_for_target(spring)
                self.assertEqual(len(spring_rows), 15)
                self.assertFalse(
                    any(
                        row.cycle_init_local.date() == spring
                        and row.cycle_init_local.hour == 2
                        for row in spring_rows
                    )
                )
            with self.subTest(year=year, transition="fall"):
                fall_rows = cycle_candidates_for_target(fall)
                self.assertEqual(len(fall_rows), 17)
                repeated = [
                    row for row in fall_rows
                    if row.cycle_init_local.date() == fall and row.cycle_init_local.hour == 1
                ]
                self.assertEqual(len(repeated), 2)
                self.assertEqual({row.cycle_init_local.fold for row in repeated}, {0, 1})
                self.assertEqual(len({row.cycle_init_utc for row in repeated}), 2)

    def test_first_target_includes_previous_local_c23(self) -> None:
        rows = cycle_candidates_for_target(date(2021, 1, 1))
        self.assertEqual(rows[0].envelope_member, "previous_local_c23")
        self.assertEqual(rows[0].cycle_init_local.date(), date(2020, 12, 31))
        self.assertEqual(rows[0].cycle_init_local.hour, 23)

    def test_native_horizon_and_target_window_cap(self) -> None:
        extended = datetime(2024, 1, 1, 6, tzinfo=UTC)
        ordinary = datetime(2024, 1, 1, 7, tzinfo=UTC)
        self.assertEqual(native_horizon(self.policy, "wrfsfcf", extended), (48, "extended"))
        self.assertEqual(native_horizon(self.policy, "wrfsfcf", ordinary), (18, "ordinary"))
        self.assertEqual(native_horizon(self.policy, "wrfsubhf", extended), (18, "ordinary"))
        for row in self.rows:
            self.assertEqual(row["retained_valid_start_utc"], row["cycle_init_utc"])
            self.assertLessEqual(row["retained_valid_end_utc"], row["window_end_utc"])
            self.assertEqual(
                row["emulated_complete_time_utc"],
                row["cycle_init_utc"] + timedelta(minutes=105),
            )


if __name__ == "__main__":
    unittest.main()
