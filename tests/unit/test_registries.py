from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from kden_v375.registries import (
    BUNDLE_INPUTS,
    interval_bounds,
    load_field_registry,
    load_parquet_schema,
    seal_registry_bundle,
    validate_registry_inputs,
    verify_registry_bundle,
)


ROOT = Path(__file__).resolve().parents[2]


class RegistryContractTests(unittest.TestCase):
    def test_full_field_universe_and_machine_intervals(self) -> None:
        evidence = validate_registry_inputs(ROOT)
        fields = evidence["field_registries"]
        self.assertEqual(fields["hourly_field_count"], 44)
        self.assertEqual(fields["subhourly_field_count"], 14)
        self.assertEqual(fields["unique_selector_contract_count"], 58)
        self.assertEqual(fields["normal_network_acquisitions"], ["H16", "Q05"])
        self.assertEqual(fields["interval_contracts"]["Q09"]["duration_minutes"], 5)
        self.assertEqual(fields["interval_contracts"]["Q11"]["duration_minutes"], 15)
        self.assertEqual(
            fields["interval_contracts"]["Q13"]["semantics"],
            "preceding_accumulation",
        )

    def test_interval_bounds_end_at_valid_time(self) -> None:
        valid = datetime(2021, 1, 1, 12, tzinfo=UTC)
        start, end = interval_bounds(
            {"field_id": "Q09", "interval_semantics": "preceding_average", "interval_minutes": "5"},
            valid,
        )
        self.assertEqual((end - start).total_seconds(), 300)
        self.assertEqual(end, valid)

    def test_bundle_round_trip_and_active_loader(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "config").mkdir()
            (root / "registries").mkdir()
            (root / "schemas").mkdir()
            shutil.copy2(ROOT / "config/project_v375.toml", root / "config")
            for relative in BUNDLE_INPUTS:
                destination = root / relative
                shutil.copy2(ROOT / relative, destination)
            sealed = seal_registry_bundle(root)["bundle"]
            verified = verify_registry_bundle(root)["bundle"]
            self.assertEqual(sealed["bundle_sha256"], verified["bundle_sha256"])
            self.assertEqual(len(verified["artifacts"]), len(BUNDLE_INPUTS))
            self.assertEqual(len(load_field_registry(root, "wrfsfcf")), 44)
            self.assertEqual(len(load_field_registry(root, "wrfsubhf")), 14)

    def test_compact_tile_schema_is_not_cell_normalized(self) -> None:
        schema = json.loads(
            (ROOT / "schemas/hrrr_field_state_v375.json").read_text(encoding="utf-8")
        )
        columns = {field["name"]: field["arrow_type"] for field in schema["columns"]}
        self.assertEqual(columns["tile_shape"], "list<int16>")
        self.assertEqual(columns["tile_values"], "list<float64>")
        self.assertNotIn("tile_cell_row", columns)
        self.assertNotIn("tile_cell_column", columns)

    def test_nullable_tile_shape_round_trips_mixed_nulls(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        from kden_v375.io.parquet import atomic_write_table

        schema = load_parquet_schema(ROOT, "hrrr_field_state_v375.json")
        tile_shape = schema.field("tile_shape")
        self.assertEqual(tile_shape.type, pa.list_(pa.int16()))
        self.assertTrue(tile_shape.nullable)

        table = pa.Table.from_arrays(
            [pa.array([[3, 3], None, [9, 9]], type=tile_shape.type)],
            schema=pa.schema([tile_shape], metadata=schema.metadata),
        )
        with tempfile.TemporaryDirectory() as name:
            destination = Path(name) / "mixed-tile-shape.parquet"
            atomic_write_table(table, destination, schema=table.schema)
            observed = pq.read_table(destination)
        self.assertEqual(observed.column("tile_shape").to_pylist(), [[3, 3], None, [9, 9]])


if __name__ == "__main__":
    unittest.main()
