from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from kden_v375.acquisition.source import SourceResult, SourceTask, process_source_object
from kden_v375.acquisition.workflow import (
    COMBINED_REQUEST_COUNT,
    COMBINED_UNIT_COUNT,
    _execute_on_persistent_pool,
    build_source_tasks,
    build_unit_specs,
    coverage_rows,
    load_runtime_config,
    load_unit_plan_rows,
    target_days,
)
from kden_v375.contracts import ContractError
from kden_v375.io.http_range import HttpResponse
from kden_v375.pilot import _station_coordinates
from kden_v375.r14 import load_r14_field_registry
from kden_v375.steps import step_06_wrfsubhf


ROOT = Path(__file__).resolve().parents[2]


class R14AcquisitionContractTests(unittest.TestCase):
    def test_runtime_and_day_units_are_exact(self) -> None:
        runtime = load_runtime_config(ROOT)
        self.assertEqual(runtime["phase_order"], ["WRFSFCF_R14", "WRFSUBHF_Q05_R14"])
        self.assertEqual(runtime["max_total_download_workers"], 8)
        self.assertEqual(COMBINED_REQUEST_COUNT, 8_919_598)
        self.assertEqual(COMBINED_UNIT_COUNT, 4_161)
        self.assertEqual(len(target_days(ROOT)), 2_080)

        hourly = build_unit_specs(ROOT, "wrfsfcf")
        q05 = build_unit_specs(ROOT, "wrfsubhf")
        self.assertEqual(len(hourly), 2_081)
        self.assertEqual(len(q05), 2_080)
        self.assertTrue(hourly[0].static)
        self.assertEqual(hourly[0].unit_id, "WRFSFCF_R14_STATIC_H14")
        self.assertFalse(q05[0].static)
        self.assertEqual(q05[-1].target_day, date(2026, 9, 11))

    def test_first_day_plan_is_split_without_changing_requests(self) -> None:
        static, dynamic = build_unit_specs(ROOT, "wrfsfcf")[:2]
        q05 = build_unit_specs(ROOT, "wrfsubhf")[0]
        static_rows = load_unit_plan_rows(ROOT, static)
        dynamic_rows = load_unit_plan_rows(ROOT, dynamic)
        q05_rows = load_unit_plan_rows(ROOT, q05)
        self.assertEqual({row["field_registry_id"] for row in static_rows}, {"H14"})
        self.assertNotIn("H14", {row["field_registry_id"] for row in dynamic_rows})
        self.assertEqual({row["field_registry_id"] for row in q05_rows}, {"Q05"})
        self.assertEqual(len(static_rows), 1)
        self.assertEqual(len(dynamic_rows), 3_180)
        self.assertEqual(len(q05_rows), 1_015)
        self.assertEqual(len(build_source_tasks(dynamic_rows)), 265)
        self.assertEqual(len(build_source_tasks(q05_rows)), 268)

    def test_coverage_reconciles_explicit_missingness(self) -> None:
        cycle = datetime(2021, 1, 1, 6, tzinfo=UTC)
        missing = cycle.replace(hour=7)
        rows = [
            {
                "target_day": date(2021, 1, 1),
                "product": "wrfsubhf",
                "cycle_init_utc": cycle,
                "field_registry_id": "Q05",
                "valid_time_utc": cycle,
                "interval_start_utc": cycle,
                "interval_end_utc": cycle,
                "coverage_flag": "PRESENT",
                "missing_reason": None,
            },
            {
                "target_day": date(2021, 1, 1),
                "product": "wrfsubhf",
                "cycle_init_utc": cycle,
                "field_registry_id": "Q05",
                "valid_time_utc": missing,
                "interval_start_utc": missing,
                "interval_end_utc": missing,
                "coverage_flag": "MISSING",
                "missing_reason": "SOURCE_INDEX_HTTP_404",
            },
        ]
        result = coverage_rows(rows, "kdenv375-s05-owner-full-20260914T230000Z-test")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["expected_valid_count"], 2)
        self.assertEqual(result[0]["present_valid_count"], 1)
        self.assertEqual(result[0]["missing_valid_count"], 1)
        self.assertFalse(result[0]["complete_flag"])
        self.assertEqual(result[0]["gap_intervals"][0]["reason"], "SOURCE_INDEX_HTTP_404")

    def test_persistent_pool_commits_in_input_order(self) -> None:
        tasks = tuple(SourceTask("wrfsubhf", str(index), ()) for index in range(12))
        committed: list[int] = []

        def worker(task: SourceTask) -> SourceResult:
            index = int(task.source_object_identity)
            time.sleep((11 - index) * 0.0005)
            return SourceResult(str(index), (), (), {"request_count": 0})

        with ThreadPoolExecutor(max_workers=8) as executor:
            summary = _execute_on_persistent_pool(
                tasks,
                executor=executor,
                worker=worker,
                commit=lambda result: committed.append(int(result.source_object_identity)),
                pause_requested=lambda: False,
            )
        self.assertEqual(committed, list(range(12)))
        self.assertEqual(summary.committed_count, 12)
        self.assertFalse(summary.paused)

    def test_stale_index_with_missing_source_object_is_explicit_missingness(self) -> None:
        cycle = datetime(2022, 2, 26, 18, tzinfo=UTC)
        valid = datetime(2022, 2, 27, 6, tzinfo=UTC)
        source_url = (
            "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/"
            "hrrr.20220226/conus/hrrr.t18z.wrfsfcf12.grib2"
        )
        index_url = f"{source_url}.idx"
        plan = {
            "request_id": "REQ-R14-WRFSFCF-20220226T1800Z-L0720-H02",
            "target_day": date(2022, 2, 26),
            "product": "wrfsfcf",
            "cycle_init_utc": cycle,
            "forecast_lead_min": 720,
            "valid_time_utc": valid,
            "field_registry_id": "H02",
            "step_type": "instant",
            "interval_start_utc": valid,
            "interval_end_utc": valid,
            "source_object_identity": source_url,
            "index_object_identity": index_url,
            "selector_identity": "WRFSFCF_H02_V1",
            "regional_spatial_contract_id": "KDEN_R14_REGIONAL_CONTEXT_V1",
            "regional_operator_id": "NONE",
            "regional_support_count": 0,
        }
        index_payload = (
            b"20:12296392:d=2022022618:TMP:700 mb:12 hour fcst:\n"
            b"21:12865399:d=2022022618:DPT:700 mb:12 hour fcst:\n"
        )
        calls: list[str] = []

        def transport(url: str, _headers: dict[str, str], _timeout: float) -> HttpResponse:
            calls.append(url)
            if url == index_url:
                return HttpResponse(
                    200,
                    {"content-length": str(len(index_payload))},
                    index_payload,
                )
            if url == source_url:
                return HttpResponse(404, {"content-length": "0"}, b"")
            raise AssertionError(f"unexpected URL: {url}")

        fields = {
            row["field_id"]: row for row in load_r14_field_registry(ROOT, "wrfsfcf")
        }
        task = SourceTask("wrfsfcf", source_url, (plan,))
        profile = {
            "max_attempts": 1,
            "timeout_seconds": 1.0,
            "initial_backoff_seconds": 0.0,
        }
        run_id = "kdenv375-s05-owner-full-20260915T230000Z-source-404-test"
        with TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            result = process_source_object(
                root=temporary_root,
                run_id=run_id,
                task=task,
                field_registry=fields,
                coordinate_rows=_station_coordinates(ROOT),
                regional_geometry={},
                profile=profile,
                physical_ranges={},
                required_regional_mask=(1 << 8) - 1,
                transport=transport,
            )
            self.assertEqual(calls, [index_url, source_url])
            self.assertEqual(result.field_rows[0]["coverage_flag"], "MISSING")
            self.assertEqual(
                result.field_rows[0]["missing_reason"], "SOURCE_OBJECT_HTTP_404"
            )
            self.assertEqual(
                result.ledger_rows[0]["terminal_disposition"],
                "CONFIRMED_REMOTE_MISSING",
            )
            self.assertEqual(result.metrics["confirmed_remote_missing_count"], 1)
            self.assertEqual(result.metrics["success_count"], 0)

            calls.clear()
            resumed = process_source_object(
                root=temporary_root,
                run_id=run_id,
                task=task,
                field_registry=fields,
                coordinate_rows=_station_coordinates(ROOT),
                regional_geometry={},
                profile=profile,
                physical_ranges={},
                required_regional_mask=(1 << 8) - 1,
                transport=transport,
            )
            self.assertEqual(calls, [])
            self.assertEqual(
                resumed.field_rows[0]["missing_reason"], "SOURCE_OBJECT_HTTP_404"
            )

    def test_step06_cannot_start_a_competing_acquisition(self) -> None:
        with self.assertRaisesRegex(ContractError, "cannot start a second acquisition"):
            step_06_wrfsubhf.run()


if __name__ == "__main__":
    unittest.main()
