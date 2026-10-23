from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq

from kden_v375.archive_readers import issue_time_grid
from kden_v375.prefit.p03_issue_spine import (
    EXPECTED_ISSUE_ROWS,
    ISSUE_GRID_ID,
    ISSUE_OUTPUT_PATH,
    SELECTION_OUTPUT_PATH,
    _checkpoint_paths,
    _inclusive_dates,
    _issue_rows_for_day,
    _merge_checkpoints,
    _parquet_bytes,
    issue_spine_schema,
    issue_state_id,
    selected_cycles_schema,
)


CONFIG = {
    "issue_grid": {
        "timezone": "America/Denver",
        "start_local": "02:00",
        "end_local": "16:00",
        "cadence_minutes": 15,
        "end_inclusive": True,
    }
}


class PrefitP03IssueSpineTests(unittest.TestCase):
    def test_ordinary_day_has_57_quarter_hour_states(self) -> None:
        rows = _issue_rows_for_day(date(2026, 9, 11), CONFIG)
        self.assertEqual(len(rows), 57)
        self.assertEqual(rows[0]["local_issue_hour"], 2)
        self.assertEqual(rows[0]["local_issue_minute"], 0)
        self.assertEqual(rows[-1]["local_issue_hour"], 16)
        self.assertEqual(rows[-1]["local_issue_minute"], 0)
        self.assertTrue(all(row["issue_grid_contract_id"] == ISSUE_GRID_ID for row in rows))

    def test_spring_forward_day_omits_nonexistent_02_hour(self) -> None:
        rows = _issue_rows_for_day(date(2026, 3, 8), CONFIG)
        self.assertEqual(len(rows), 53)
        local_clocks = {
            (row["local_issue_hour"], row["local_issue_minute"]) for row in rows
        }
        self.assertFalse(any(hour == 2 for hour, _ in local_clocks))
        self.assertIn((3, 0), local_clocks)

    def test_full_study_exact_dst_safe_count(self) -> None:
        counts = []
        for target in _inclusive_dates(date(2021, 1, 1), date(2026, 9, 11)):
            counts.append(
                len(
                    issue_time_grid(
                        target,
                        timezone_name="America/Denver",
                        start_local="02:00",
                        end_local="16:00",
                        cadence_minutes=15,
                    )
                )
            )
        self.assertEqual(sum(counts), EXPECTED_ISSUE_ROWS)
        self.assertEqual(counts.count(53), 6)
        self.assertEqual(counts.count(57), 2074)

    def test_issue_id_is_stable_and_natural_key_sensitive(self) -> None:
        target = date(2024, 1, 15)
        first = datetime(2024, 1, 15, 10, tzinfo=UTC)
        second = first + timedelta(minutes=15)
        self.assertEqual(issue_state_id(target, first), issue_state_id(target, first))
        self.assertNotEqual(issue_state_id(target, first), issue_state_id(target, second))
        self.assertRegex(issue_state_id(target, first), r"^ISSUE_[0-9a-f]{64}$")

    def test_p03_tables_are_target_free_and_weather_value_free(self) -> None:
        names = set(issue_spine_schema().names) | set(selected_cycles_schema().names)
        forbidden = {
            "y_audited_f",
            "truth_qc_status",
            "bi_value",
            "nn_value",
            "regional_value_00",
            "market_price",
            "settlement",
        }
        self.assertFalse(names & forbidden)
        self.assertIn("statistical_group_id", names)
        self.assertIn("previous_cycle_init_utc", names)
        self.assertIn("trajectory_bundle_path", names)

    def test_schema_round_trip_uses_no_filesystem_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(Path(directory).is_dir())
            self.assertEqual(
                issue_spine_schema().metadata[b"schema_id"],
                b"KDEN_V375_ISSUE_SPINE_V1",
            )
            self.assertEqual(
                selected_cycles_schema().metadata[b"schema_id"],
                b"KDEN_V375_SELECTED_CYCLES_V1",
            )

    def test_checkpoint_hive_directory_does_not_add_year_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run_id = "kdenv375-p03-synthetic-20260923T000000Z-merge-test"
            paths = _checkpoint_paths(root, run_id, 2021)
            issue_payload = _parquet_bytes([], issue_spine_schema())
            selection_payload = _parquet_bytes([], selected_cycles_schema())
            paths["issue"].parent.mkdir(parents=True, exist_ok=True)
            paths["issue"].write_bytes(issue_payload)
            paths["selection"].write_bytes(selection_payload)
            paths["manifest"].write_text(
                json.dumps(
                    {
                        "schema_version": "KDEN_V375_PREFIT_P03_YEAR_CHECKPOINT_V1",
                        "issue_sha256": hashlib.sha256(issue_payload).hexdigest(),
                        "selection_sha256": hashlib.sha256(selection_payload).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            _merge_checkpoints(root, run_id, [2021])
            issue = pq.ParquetFile(root / ISSUE_OUTPUT_PATH).schema_arrow
            selection = pq.ParquetFile(root / SELECTION_OUTPUT_PATH).schema_arrow
            self.assertEqual(issue, issue_spine_schema())
            self.assertEqual(selection, selected_cycles_schema())
            self.assertNotIn("year", issue.names)
            self.assertNotIn("year", selection.names)


if __name__ == "__main__":
    unittest.main()
