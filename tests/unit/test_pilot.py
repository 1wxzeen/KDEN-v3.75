from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from kden_v375.io import grib as grib_io
from kden_v375.pilot import (
    EXPECTED_FIELDS,
    _float32_roundtrip,
    _static_schedule_days,
    load_pilot_design,
    parse_pilot_index,
)


ROOT = Path(__file__).resolve().parents[2]


class PilotContractTests(unittest.TestCase):
    def test_pilot_design_has_required_coverage(self) -> None:
        design = load_pilot_design(ROOT)

        self.assertEqual(len(design.weeks), 4)
        self.assertEqual(len(design.target_days), 28)
        self.assertEqual(
            {week.season for week in design.weeks},
            {"winter", "spring", "summer", "fall"},
        )
        self.assertEqual(
            {week.archive_stratum for week in design.weeks},
            {"early", "middle", "late"},
        )
        self.assertEqual(set(design.raw["physical_ranges"]), set(EXPECTED_FIELDS))
        self.assertEqual(design.raw["lead_policy"], "TARGET_WINDOW_RIGHT_OPEN")
        self.assertEqual(design.raw["runtime"]["primary_workers"], 8)
        self.assertEqual(design.raw["runtime"]["rebuild_workers"], 8)
        self.assertFalse(design.raw["runtime"]["optional_four_worker_diagnostic"])

    def test_pilot_index_accepts_fh00_zero_day_spelling(self) -> None:
        for descriptor in ("0-0 day ave fcst", "0-0 day acc fcst"):
            with self.subTest(descriptor=descriptor):
                source = f"1:0:d=2021010100:APCP:surface:{descriptor}:"
                record = parse_pilot_index(source)[0]

                self.assertEqual(record.original_line, source)
                interval = grib_io.parse_interval_descriptor(record.time_descriptor)
                self.assertEqual(interval.start_minute, 0)
                self.assertEqual(interval.end_minute, 0)

    def test_float32_comparison_roundtrips_to_binary32(self) -> None:
        value = 273.123456789
        observed = _float32_roundtrip(value)

        self.assertNotEqual(observed, value)
        self.assertLess(abs(observed - value), 0.001)

    def test_pilot_index_does_not_rewrite_nonzero_day_intervals(self) -> None:
        source = "1:0:d=2021010100:APCP:surface:0-1 day acc fcst:"
        record = parse_pilot_index(source)[0]

        self.assertEqual(record.time_descriptor, "0-1 day acc fcst")
        self.assertEqual(record.original_line, source)

    def test_static_h14_schedule_day_is_added_outside_pilot_weeks(self) -> None:
        static_day = date(2021, 1, 1)
        rows = [
            {"target_day": static_day, "field_registry_id": "H14"},
            {"target_day": date(2021, 1, 10), "field_registry_id": "H01"},
        ]

        self.assertEqual(_static_schedule_days(rows), (static_day,))


if __name__ == "__main__":
    unittest.main()
