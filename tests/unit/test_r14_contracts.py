from __future__ import annotations

import json
import unittest
from pathlib import Path

from kden_v375.r14 import (
    EXPECTED_FIELD_OPERATORS,
    EXPECTED_SUPPORT_ORDER,
    load_r14_field_registry,
    load_r14_scope,
    resolve_r14_spatial_geometry,
    validate_r14_spatial_contract,
)


ROOT = Path(__file__).resolve().parents[2]


class R14RegistryAndSpatialContractTests(unittest.TestCase):
    def test_scope_loader_fail_closed_selection(self) -> None:
        scope = load_r14_scope(ROOT)
        self.assertEqual(scope["scope_id"], "KDEN_V375_R14_V1")
        self.assertEqual(
            [row["field_id"] for row in load_r14_field_registry(ROOT, "wrfsfcf")],
            [
                "H02", "H07", "H14", "H16", "H17", "H18", "H19",
                "H24", "H26", "H28", "H31", "H36", "H38",
            ],
        )
        self.assertEqual(
            [row["field_id"] for row in load_r14_field_registry(ROOT, "wrfsubhf")],
            ["Q05"],
        )

    def test_spatial_geometry_is_exact_for_both_coordinate_eras(self) -> None:
        geometry = resolve_r14_spatial_geometry(ROOT)
        self.assertEqual(geometry["support_order"], list(EXPECTED_SUPPORT_ORDER))
        self.assertEqual(
            set(geometry["coordinate_era_supports"]),
            {"KDEN_COORD_20040105", "KDEN_COORD_20211122"},
        )
        for supports in geometry["coordinate_era_supports"].values():
            self.assertEqual(
                [support["support_id"] for support in supports],
                list(EXPECTED_SUPPORT_ORDER),
            )
            for support in supports:
                self.assertGreaterEqual(support["nearest_node"]["i"], 0)
                self.assertGreaterEqual(support["nearest_node"]["j"], 0)
                self.assertLess(support["nearest_node"]["i"], 1799)
                self.assertLess(support["nearest_node"]["j"], 1059)
                self.assertAlmostEqual(
                    sum(node["weight"] for node in support["bilinear_nodes"]),
                    1.0,
                    places=12,
                )

    def test_field_operators_partition_exactly_r14(self) -> None:
        evidence = validate_r14_spatial_contract(ROOT)
        observed = {
            name: set(field_ids)
            for name, field_ids in evidence["regional_fields_by_operator"].items()
        }
        self.assertEqual(observed, EXPECTED_FIELD_OPERATORS)
        self.assertTrue(evidence["confirmation_pilot_authorized"])
        self.assertFalse(evidence["full_history_authorized"])

    def test_storage_uses_fixed_nullable_columns_not_nullable_list_members(self) -> None:
        schema = json.loads(
            (ROOT / "schemas/hrrr_field_state_r14_v375.json").read_text(
                encoding="utf-8"
            )
        )
        columns = {column["name"]: column for column in schema["columns"]}
        for index in range(8):
            column = columns[f"regional_value_{index:02d}"]
            self.assertEqual(column["arrow_type"], "float64")
            self.assertTrue(column["nullable"])
        self.assertNotIn("regional_values", columns)


if __name__ == "__main__":
    unittest.main()
