from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from kden_v375.io.grib import (
    SelectorResolutionError,
    extract_registered_supports,
    parse_index,
    parse_interval_descriptor,
    resolve_index_range,
)
from kden_v375.r14 import _grid_from_registry


ROOT = Path(__file__).resolve().parents[2]


class GribContractTests(unittest.TestCase):
    def test_interval_semantics(self) -> None:
        interval = parse_interval_descriptor("45-60 min ave fcst")
        self.assertEqual(interval.semantics, "preceding_average")
        self.assertEqual((interval.start_minute, interval.end_minute), (45, 60))

    def test_full_identity_selects_exactly_once(self) -> None:
        records = parse_index(
            "1:0:d=2021010100:TMP:2 m above ground:anl:\n"
            "2:9:d=2021010100:TMP:2 m above ground:1 hour fcst:\n"
        )
        request = {
            "cycle_init_utc": "2021-01-01T00:00:00Z",
            "parameter": "TMP",
            "level": "2 m above ground",
            "interval_semantics": "snapshot",
            "forecast_lead_min": 0,
            "interval_minutes": 0,
            "field_registry_id": "T",
        }
        resolved = resolve_index_range(records, request)
        self.assertEqual((resolved.record.start_byte, resolved.end_byte), (0, 8))

    def test_ambiguity_is_rejected(self) -> None:
        records = parse_index(
            "1:0:d=2021010100:TMP:2 m above ground:anl:\n"
            "2:9:d=2021010100:TMP:2 m above ground:anl:\n"
        )
        request = {
            "cycle_init_utc": "2021-01-01T00:00:00Z",
            "parameter": "TMP",
            "level": "2 m above ground",
            "interval_semantics": "snapshot",
            "forecast_lead_min": 0,
            "interval_minutes": 0,
            "field_registry_id": "T",
        }
        with self.assertRaises(SelectorResolutionError):
            resolve_index_range(records, request)

    def test_registered_supports_revalidate_and_extract_in_frozen_order(self) -> None:
        grid = _grid_from_registry(
            json.loads((ROOT / "registries/grid_geometry_v375.json").read_text())
        )
        geometry = json.loads(
            (ROOT / "registries/r14_spatial_geometry_v375.json").read_text()
        )
        supports = geometry["coordinate_era_supports"]["KDEN_COORD_20211122"]

        def linear_nodes(_handle, indices, _grid):
            return {index: float(index[0] + index[1]) for index in set(indices)}

        with patch("kden_v375.io.grib._read_node_values", side_effect=linear_nodes):
            bilinear, bilinear_mask = extract_registered_supports(
                object(), grid, supports, interpolation="BILINEAR"
            )
            nearest, nearest_mask = extract_registered_supports(
                object(), grid, supports, interpolation="NEAREST"
            )

        self.assertEqual(bilinear_mask, 255)
        self.assertEqual(nearest_mask, 255)
        self.assertEqual(len(bilinear), 8)
        self.assertEqual(len(nearest), 8)
        for value, support in zip(bilinear, supports, strict=True):
            self.assertAlmostEqual(
                value,
                support["grid_fraction_i"] + support["grid_fraction_j"],
                places=8,
            )
        self.assertEqual(
            nearest,
            tuple(
                float(row["nearest_node"]["i"] + row["nearest_node"]["j"])
                for row in supports
            ),
        )


if __name__ == "__main__":
    unittest.main()
