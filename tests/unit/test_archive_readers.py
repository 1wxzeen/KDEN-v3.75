from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from kden_v375.archive_readers import (
    ArchiveReaderError,
    R14ArchiveReader,
    issue_time_grid,
    load_issue_view_contract,
    select_newest_legal_cycle,
)


ROOT = Path(__file__).resolve().parents[2]


class IssueTimeGridTests(unittest.TestCase):
    def test_default_grid_is_utc_unique_and_dst_safe(self) -> None:
        ordinary = issue_time_grid(date(2024, 1, 15))
        spring = issue_time_grid(date(2023, 3, 12))
        fall = issue_time_grid(date(2023, 11, 5))
        self.assertEqual(len(ordinary), 57)
        self.assertEqual(len(spring), 53)
        self.assertEqual(len(fall), 57)
        self.assertEqual(len(set(ordinary)), len(ordinary))
        self.assertEqual(len(set(spring)), len(spring))
        self.assertEqual(len(set(fall)), len(fall))

    def test_transition_window_exposes_gap_and_fold(self) -> None:
        spring = issue_time_grid(
            date(2023, 3, 12), start_local="00:00", end_local="04:00"
        )
        fall = issue_time_grid(
            date(2023, 11, 5), start_local="00:00", end_local="04:00"
        )
        self.assertEqual(len(spring), 13)
        self.assertEqual(len(fall), 21)

    def test_grid_rejects_midnight_wrap(self) -> None:
        with self.assertRaisesRegex(ArchiveReaderError, "cannot cross"):
            issue_time_grid(date(2024, 1, 15), start_local="16:00", end_local="02:00")


class AvailabilitySelectorTests(unittest.TestCase):
    def test_newest_complete_cycle_and_predecessor_are_selected(self) -> None:
        base = datetime(2024, 1, 1, 7, tzinfo=UTC)
        rows = [
            {
                "cycle_init_utc": base + timedelta(hours=offset),
                "emulated_complete_time_utc": base
                + timedelta(hours=offset, minutes=105),
            }
            for offset in range(4)
        ]
        current, previous = select_newest_legal_cycle(
            rows, base + timedelta(hours=4)
        )
        self.assertEqual(current["cycle_init_utc"], base + timedelta(hours=2))
        self.assertIsNotNone(previous)
        self.assertEqual(previous["cycle_init_utc"], base + timedelta(hours=1))

    def test_future_complete_cycle_is_not_legal(self) -> None:
        cycle = datetime(2024, 1, 1, 7, tzinfo=UTC)
        rows = [
            {
                "cycle_init_utc": cycle,
                "emulated_complete_time_utc": cycle + timedelta(minutes=105),
            }
        ]
        with self.assertRaisesRegex(ArchiveReaderError, "no scheduled cycle"):
            select_newest_legal_cycle(rows, cycle + timedelta(minutes=104))


class R14ArchiveReaderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (ROOT / "state/R14_PASS.json").is_file():
            raise unittest.SkipTest("completed local R14 archive is unavailable")
        cls.reader = R14ArchiveReader(ROOT)

    def test_contract_is_exact_r14(self) -> None:
        contract = load_issue_view_contract(ROOT)
        self.assertEqual(contract["product_fields"]["wrfsubhf"], ["Q05"])
        self.assertEqual(len(contract["product_fields"]["wrfsfcf"]), 12)
        self.assertEqual(contract["static_fields"], ["H14"])

    def test_issue_view_preserves_cycles_and_native_paths(self) -> None:
        target_day = date(2021, 1, 10)
        issue = datetime(2021, 1, 10, 17, tzinfo=UTC)
        view = self.reader.build_issue_view(target_day, issue)
        self.assertEqual(view.hourly.selection.issue_time_utc, issue)
        self.assertEqual(view.q05.selection.issue_time_utc, issue)
        self.assertEqual(
            set(view.hourly.field_state["field_registry_id"].to_pylist()),
            set(self.reader.contract["product_fields"]["wrfsfcf"]),
        )
        self.assertEqual(
            set(view.q05.field_state["field_registry_id"].to_pylist()), {"Q05"}
        )
        self.assertGreater(view.hourly.cycle_revisions.num_rows, 0)
        self.assertGreater(view.q05.cycle_revisions.num_rows, 0)
        self.assertGreater(view.cross_product_temperature.num_rows, 0)

    def test_same_cycle_contract_is_enforced(self) -> None:
        view = self.reader.build_issue_view(
            date(2025, 7, 15),
            datetime(2025, 7, 15, 18, tzinfo=UTC),
            alignment_contract="same_cycle",
        )
        self.assertEqual(
            view.hourly.selection.cycle_init_utc,
            view.q05.selection.cycle_init_utc,
        )
        self.assertEqual(
            set(view.cross_product_temperature["alignment_contract"].to_pylist()),
            {"same_cycle"},
        )

    def test_confirmed_remote_missingness_is_not_dropped(self) -> None:
        table = self.reader.read_cycle(
            date(2022, 2, 26),
            "wrfsfcf",
            datetime(2022, 2, 26, 18, tzinfo=UTC),
        )
        missing = [
            row for row in table.to_pylist() if row["coverage_flag"] == "MISSING"
        ]
        self.assertGreater(len(missing), 0)
        self.assertTrue(all(row["missing_reason"] for row in missing))

    def test_issue_time_must_belong_to_target_local_day(self) -> None:
        with self.assertRaisesRegex(ArchiveReaderError, "target local day"):
            self.reader.select_cycles(
                date(2021, 1, 10),
                "wrfsfcf",
                datetime(2021, 1, 12, 17, tzinfo=UTC),
            )


if __name__ == "__main__":
    unittest.main()
