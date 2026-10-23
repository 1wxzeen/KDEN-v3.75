from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from kden_v375.prefit.p04_features import (
    CONFIG_PATH,
    PANEL_SCHEMA_ID,
    REGISTRY_ID,
    _accumulation_features,
    _regional_features,
    _revision_features,
    _snapshot_features,
    build_feature_registry,
    feature_panel_schema,
    panel_schema_document,
    run_bounded_acceptance,
)


ROOT = Path(__file__).resolve().parents[2]


def _row(
    valid: datetime,
    value: float | None,
    *,
    flag: str = "PRESENT",
    interval_start: datetime | None = None,
    interval_end: datetime | None = None,
) -> dict[str, object]:
    return {
        "valid_time_utc": valid,
        "interval_start_utc": interval_start or valid,
        "interval_end_utc": interval_end or valid,
        "coverage_flag": flag,
        "bi_value": value,
        "nn_value": value,
    }


class PrefitP04PrimitiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
        cls.features = build_feature_registry(cls.config)

    def test_registry_is_closed_unique_and_model_neutral(self) -> None:
        names = [feature["name"] for feature in self.features]
        identifiers = [feature["feature_id"] for feature in self.features]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertGreater(len(names), 250)
        self.assertTrue(all(identifier.startswith("FEATURE_") for identifier in identifiers))
        searchable = json.dumps(self.features).lower()
        for token in ("y_audited_f", "kalshi", "madis", "analog_weight", "fitted_regime"):
            self.assertNotIn(token, searchable)

    def test_panel_schema_matches_registry_order(self) -> None:
        logical = panel_schema_document(self.features)
        arrow = feature_panel_schema(self.features)
        self.assertEqual(logical["schema_id"], PANEL_SCHEMA_ID)
        self.assertEqual(logical["feature_registry_id"], REGISTRY_ID)
        self.assertEqual(arrow.names, [column["name"] for column in logical["columns"]])
        self.assertEqual(len(arrow.names), len(self.features) + 9)

    def test_snapshot_aggregate_fails_closed_and_keeps_coverage(self) -> None:
        issue = datetime(2024, 1, 1, 12, tzinfo=UTC)
        rows = [
            _row(issue, 280.0),
            _row(issue + timedelta(hours=1), None, flag="MISSING"),
            _row(issue + timedelta(hours=2), 285.0),
        ]
        result = _snapshot_features("H16", rows, issue)
        self.assertEqual(result["h16_local_remaining_missing_count"], 1)
        self.assertAlmostEqual(result["h16_local_remaining_coverage_fraction"], 2 / 3)
        self.assertIsNone(result["h16_local_remaining_max"])
        self.assertEqual(result["h16_local_future_first_value"], 280.0)

    def test_accumulation_excludes_interval_straddling_issue(self) -> None:
        issue = datetime(2024, 1, 1, 12, 30, tzinfo=UTC)
        rows = [
            _row(
                datetime(2024, 1, 1, 13, tzinfo=UTC),
                2.0,
                interval_start=datetime(2024, 1, 1, 12, tzinfo=UTC),
                interval_end=datetime(2024, 1, 1, 13, tzinfo=UTC),
            ),
            _row(
                datetime(2024, 1, 1, 14, tzinfo=UTC),
                3.0,
                interval_start=datetime(2024, 1, 1, 13, tzinfo=UTC),
                interval_end=datetime(2024, 1, 1, 14, tzinfo=UTC),
            ),
        ]
        result = _accumulation_features(rows, issue)
        self.assertEqual(result["h38_local_remaining_sum"], 3.0)
        self.assertEqual(result["h38_local_remaining_missing_count"], 0)

    def test_regional_summary_fails_closed_on_one_missing_support(self) -> None:
        row = {
            "regional_support_count": 8,
            "regional_coverage_mask": 253,
            **{f"regional_value_{index:02d}": float(index) for index in range(8)},
        }
        row["regional_value_01"] = None
        result = _regional_features("H16", row)
        self.assertEqual(result["h16_regional_future_first_coverage_fraction"], 7 / 8)
        self.assertIsNone(result["h16_regional_future_first_mean"])

    def test_revision_uses_only_identical_remaining_valid_times(self) -> None:
        issue = datetime(2024, 1, 1, 12, tzinfo=UTC)
        current = [
            _row(issue, 280.0),
            _row(issue + timedelta(hours=1), 282.0),
        ]
        previous = [
            _row(issue - timedelta(hours=1), 275.0),
            _row(issue, 279.0),
            _row(issue + timedelta(hours=1), 280.0),
        ]
        result = _revision_features("H16", current, previous, issue)
        self.assertEqual(result["revision_h16_remaining_overlap_count"], 2)
        self.assertEqual(result["revision_h16_remaining_mean"], 1.5)
        self.assertEqual(result["revision_h16_remaining_max_abs"], 2.0)


class PrefitP04BoundedArchiveTests(unittest.TestCase):
    def test_predeclared_real_archive_cases(self) -> None:
        if not (ROOT / "state/PREFIT_P03_PASS.json").is_file():
            self.skipTest("P03 substrate is unavailable")
        config = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
        features = build_feature_registry(config)
        evidence = run_bounded_acceptance(ROOT, config, features)
        self.assertEqual(evidence["case_count"], 7)
        self.assertTrue(evidence["strict_missing_aggregate_is_null"])
        self.assertTrue(evidence["h38_fh00_zero_duration_verified"])
        self.assertEqual(evidence["truth_rows_read"], 0)


if __name__ == "__main__":
    unittest.main()
