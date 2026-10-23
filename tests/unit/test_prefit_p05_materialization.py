from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from kden_v375.prefit.p05_materialization import (
    CONFIG_PATH,
    EXPECTED_FEATURE_ROWS,
    EXPECTED_TRAJECTORY_ROWS,
    TRAJECTORY_SCHEMA_ID,
    _catalog_rows_for_table,
    _parquet_bytes,
    time_support_id,
    trajectory_catalog_schema,
    trajectory_schema_document,
    trajectory_state_id,
)


ROOT = Path(__file__).resolve().parents[2]


class PrefitP05MaterializationTests(unittest.TestCase):
    def test_frozen_counts_and_reference_only_contract(self) -> None:
        config = json.loads((ROOT / CONFIG_PATH).read_text(encoding="utf-8"))
        self.assertEqual(config["expected_feature_rows"], EXPECTED_FEATURE_ROWS)
        self.assertEqual(config["expected_total_trajectory_rows"], EXPECTED_TRAJECTORY_ROWS)
        self.assertTrue(config["trajectory_catalog"]["reference_only"])
        self.assertFalse(
            config["trajectory_catalog"]["canonical_weather_values_duplicated"]
        )

    def test_trajectory_schema_has_locators_but_no_weather_values_or_targets(self) -> None:
        schema = trajectory_catalog_schema()
        self.assertEqual(schema.metadata[b"schema_id"], TRAJECTORY_SCHEMA_ID.encode())
        self.assertIn("canonical_archive_path", schema.names)
        self.assertIn("canonical_archive_row_ordinal", schema.names)
        self.assertIn("canonical_archive_sha256", schema.names)
        forbidden = {
            "bi_value",
            "nn_value",
            "tile_values",
            "regional_value_00",
            "y_audited_f",
            "truth_qc_status",
            "market_price",
            "settlement",
        }
        self.assertFalse(forbidden & set(schema.names))
        self.assertTrue(trajectory_schema_document()["reference_contract"]["canonical_r14_values_are_referenced_not_duplicated"])

    def test_identifiers_are_stable_and_support_sensitive(self) -> None:
        row = {
            "product": "wrfsfcf",
            "field_registry_id": "H38",
            "cycle_init_utc": datetime(2024, 1, 1, 6, tzinfo=UTC),
            "valid_time_utc": datetime(2024, 1, 1, 7, tzinfo=UTC),
            "interval_start_utc": datetime(2024, 1, 1, 6, tzinfo=UTC),
            "interval_end_utc": datetime(2024, 1, 1, 7, tzinfo=UTC),
            "step_type": "accum",
        }
        first = trajectory_state_id(row, spatial_contract_id="POINT_NN_TILE9_V1")
        self.assertEqual(first, trajectory_state_id(row, spatial_contract_id="POINT_NN_TILE9_V1"))
        changed = dict(row, interval_start_utc=datetime(2024, 1, 1, 5, tzinfo=UTC))
        self.assertNotEqual(time_support_id(row), time_support_id(changed))
        self.assertNotEqual(
            first,
            trajectory_state_id(changed, spatial_contract_id="POINT_NN_TILE9_V1"),
        )

    def test_catalog_row_round_trip_is_reference_only(self) -> None:
        source_schema = pa.schema(
            [
                pa.field("target_day", pa.date32(), nullable=False),
                pa.field("cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("product", pa.string(), nullable=False),
                pa.field("hrrr_version", pa.string(), nullable=False),
                pa.field("forecast_lead_min", pa.int32(), nullable=False),
                pa.field("valid_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("field_registry_id", pa.string(), nullable=False),
                pa.field("parameter", pa.string(), nullable=False),
                pa.field("level", pa.string(), nullable=False),
                pa.field("step_type", pa.string(), nullable=False),
                pa.field("interval_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("interval_end_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("native_unit", pa.string(), nullable=False),
                pa.field("canonical_unit", pa.string(), nullable=False),
                pa.field("station_id", pa.string(), nullable=False),
                pa.field("station_coord_era", pa.string(), nullable=False),
                pa.field("grid_geometry_id", pa.string(), nullable=False),
                pa.field("bi_value", pa.float64()),
                pa.field("tile_values", pa.list_(pa.float64())),
                pa.field("regional_spatial_contract_id", pa.string(), nullable=False),
                pa.field("regional_operator", pa.string()),
                pa.field("regional_support_count", pa.int8(), nullable=False),
                pa.field("regional_coverage_mask", pa.int16(), nullable=False),
                pa.field("coverage_flag", pa.string(), nullable=False),
                pa.field("missing_reason", pa.string()),
                pa.field("selector_identity", pa.string(), nullable=False),
                pa.field("source_idx_hash", pa.binary(32), nullable=False),
                pa.field("payload_hash", pa.binary(32)),
                pa.field("derivation_version", pa.string(), nullable=False),
            ]
        )
        instant = datetime(2024, 1, 1, 7, tzinfo=UTC)
        table = pa.Table.from_pylist(
            [
                {
                    "target_day": date(2024, 1, 1),
                    "cycle_init_utc": datetime(2024, 1, 1, 6, tzinfo=UTC),
                    "product": "wrfsfcf",
                    "hrrr_version": "v4",
                    "forecast_lead_min": 60,
                    "valid_time_utc": instant,
                    "field_registry_id": "H16",
                    "parameter": "TMP",
                    "level": "2 m above ground",
                    "step_type": "instant",
                    "interval_start_utc": instant,
                    "interval_end_utc": instant,
                    "native_unit": "K",
                    "canonical_unit": "K",
                    "station_id": "KDEN",
                    "station_coord_era": "KDEN_COORD_20211122",
                    "grid_geometry_id": "HRRR_CONUS_NATIVE_LAMBERT_V4",
                    "bi_value": 280.0,
                    "tile_values": None,
                    "regional_spatial_contract_id": "KDEN_V375_R14_REGIONAL_SPATIAL_V1",
                    "regional_operator": "BILINEAR_AT_EIGHT_SUPPORTS",
                    "regional_support_count": 8,
                    "regional_coverage_mask": 255,
                    "coverage_flag": "PRESENT",
                    "missing_reason": None,
                    "selector_identity": "WRFSFCF_H16_V1@test",
                    "source_idx_hash": b"a" * 32,
                    "payload_hash": b"b" * 32,
                    "derivation_version": "TEST",
                }
            ],
            schema=source_schema,
        )
        rows = _catalog_rows_for_table(
            table,
            archive_path="archive/example.parquet",
            archive_sha256="c" * 64,
            field_contracts={"H16": {"spatial_contract_id": "POINT_BI_NN_V1"}},
            local_value_columns={"H16": "bi_value"},
        )
        self.assertEqual(len(rows), 1)
        self.assertNotIn("bi_value", rows[0])
        self.assertEqual(rows[0]["local_value_column"], "bi_value")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.parquet"
            path.write_bytes(_parquet_bytes(rows, trajectory_catalog_schema()))
            self.assertEqual(pq.ParquetFile(path).schema_arrow, trajectory_catalog_schema())


if __name__ == "__main__":
    unittest.main()
