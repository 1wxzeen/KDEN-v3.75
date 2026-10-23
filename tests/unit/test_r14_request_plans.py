from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from kden_v375.r14 import load_r14_field_registry
from kden_v375.r14_request_plans import (
    EXPECTED_COUNTS,
    FORBIDDEN_PLAN_COLUMNS,
    _build_year_partition,
    _regional_operator_map,
    expected_r14_product_counts,
    iter_r14_requests_for_schedule_row,
    load_r14_plan_policy,
    load_r14_request_schema,
    validate_r14_fh00_evidence,
)
from kden_v375.r14_schedule import build_r14_schedule_rows, load_r14_schedule_policy


ROOT = Path(__file__).resolve().parents[2]


class R14RequestPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = load_r14_plan_policy(ROOT)
        cls.schedule = build_r14_schedule_rows(load_r14_schedule_policy(ROOT))
        cls.regional = _regional_operator_map(ROOT)

    def test_full_right_open_counts_without_materializing_plan_rows(self) -> None:
        for product in ("wrfsfcf", "wrfsubhf"):
            rows = [row for row in self.schedule if row["product"] == product]
            fields = load_r14_field_registry(ROOT, product)
            observed = expected_r14_product_counts(rows, product, fields)
            self.assertEqual(
                observed,
                {
                    "native_valid_state_count": EXPECTED_COUNTS[product][
                        "native_valid_states"
                    ],
                    "request_row_count": EXPECTED_COUNTS[product]["request_rows"],
                },
            )

    def test_sample_hourly_rows_include_h14_once_and_exact_r14_fields(self) -> None:
        schedule_row = next(row for row in self.schedule if row["product"] == "wrfsfcf")
        fields = load_r14_field_registry(ROOT, "wrfsfcf")
        requests = list(iter_r14_requests_for_schedule_row(
            schedule_row,
            product="wrfsfcf",
            fields=fields,
            policy=self.policy,
            regional_operators=self.regional,
            include_static_h14=True,
        ))
        counts = Counter(row["field_registry_id"] for row in requests)
        self.assertEqual(counts["H14"], 1)
        self.assertEqual(set(counts), {field["field_id"] for field in fields})
        self.assertTrue(all(
            row["valid_time_utc"] < schedule_row["window_end_utc"] for row in requests
        ))
        self.assertEqual(
            {row["regional_support_count"] for row in requests if row["field_registry_id"] in {"H02", "H07"}},
            {0},
        )
        self.assertEqual(
            {row["regional_support_count"] for row in requests if row["field_registry_id"] not in {"H02", "H07"}},
            {8},
        )

    def test_h38_fh00_override_does_not_change_positive_lead_interval(self) -> None:
        schedule_row = next(row for row in self.schedule if row["product"] == "wrfsfcf")
        fields = load_r14_field_registry(ROOT, "wrfsfcf")
        requests = list(iter_r14_requests_for_schedule_row(
            schedule_row,
            product="wrfsfcf",
            fields=fields,
            policy=self.policy,
            regional_operators=self.regional,
            include_static_h14=False,
        ))
        h38 = [row for row in requests if row["field_registry_id"] == "H38"]
        self.assertEqual(h38[0]["forecast_lead_min"], 0)
        self.assertEqual(h38[0]["interval_start_utc"], h38[0]["interval_end_utc"])
        positive = next(row for row in h38 if row["forecast_lead_min"] > 0)
        self.assertEqual(
            (positive["interval_end_utc"] - positive["interval_start_utc"]).seconds,
            3600,
        )

    def test_q05_quarter_hours_share_their_parent_forecast_file(self) -> None:
        schedule_row = next(row for row in self.schedule if row["product"] == "wrfsubhf")
        requests = list(iter_r14_requests_for_schedule_row(
            schedule_row,
            product="wrfsubhf",
            fields=load_r14_field_registry(ROOT, "wrfsubhf"),
            policy=self.policy,
            regional_operators=self.regional,
            include_static_h14=False,
        ))
        by_lead = {row["forecast_lead_min"]: row for row in requests}
        parent_urls = {
            by_lead[lead]["source_object_identity"] for lead in (15, 30, 45, 60)
        }
        self.assertEqual(len(parent_urls), 1)
        self.assertTrue(next(iter(parent_urls)).endswith("wrfsubhf01.grib2"))

    def test_r14_schema_has_spatial_lineage_and_no_observation_dependency(self) -> None:
        schema = load_r14_request_schema(ROOT)
        self.assertFalse(set(schema.names) & FORBIDDEN_PLAN_COLUMNS)
        self.assertTrue({
            "baseline_spatial_contract_id",
            "regional_spatial_contract_id",
            "regional_operator_id",
            "regional_support_count",
        }.issubset(schema.names))
        self.assertEqual(validate_r14_fh00_evidence(ROOT)["Q05_fh00"], "zero_minute_snapshot_from_registry")

    def test_completed_year_partition_is_reused_on_resume(self) -> None:
        row = next(row for row in self.schedule if row["product"] == "wrfsfcf")
        fields = load_r14_field_registry(ROOT, "wrfsfcf")
        geometry = json.loads(
            (ROOT / "registries/grid_geometry_v375.json").read_text(encoding="utf-8")
        )
        schema = load_r14_request_schema(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "stage"
            stage.mkdir()
            arguments = {
                "project_root": root,
                "stage": stage,
                "product": "wrfsfcf",
                "year": 2021,
                "year_rows": [row],
                "fields": fields,
                "policy": self.policy,
                "regional_operators": self.regional,
                "geometry": geometry,
                "schema": schema,
                "build_inputs_sha256": "0" * 64,
                "include_static_h14": True,
                "run_id": "kdenv375-s03-ordinary-20260914T120000Z-unit-plan",
                "completed_years": [],
                "prior_request_rows": 0,
                "pause": None,
            }
            first = _build_year_partition(**arguments)
            second = _build_year_partition(**arguments)
            self.assertEqual(first, second)
            self.assertEqual(first["field_request_counts"]["H14"], 1)
            self.assertTrue(first["all_valid_times_strictly_before_window_end"])


if __name__ == "__main__":
    unittest.main()
