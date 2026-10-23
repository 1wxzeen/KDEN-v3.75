from __future__ import annotations

import csv
import json
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCOPE_PATH = ROOT / "config/r14_acquisition_v375.json"
SPATIAL_PATH = ROOT / "config/r14_spatial_contract_v375.json"


def _catalog_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return {row["field_id"] for row in csv.DictReader(stream)}


class R14ScopeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))

    def test_exact_sparse_field_partition(self) -> None:
        fields = self.scope["field_universe"]
        hourly = fields["wrfsfcf"]
        subhourly = fields["wrfsubhf"]
        retained_hourly = set(hourly["dynamic"] + hourly["static"])
        retained_subhourly = set(subhourly["dynamic"] + subhourly["static"])

        self.assertEqual(
            hourly["dynamic"],
            [
                "H02", "H07", "H16", "H17", "H18", "H19",
                "H24", "H26", "H28", "H31", "H36", "H38",
            ],
        )
        self.assertEqual(hourly["static"], ["H14"])
        self.assertEqual(subhourly["dynamic"], ["Q05"])
        self.assertEqual(len(retained_hourly | retained_subhourly), 14)
        self.assertFalse(retained_hourly & set(hourly["excluded"]))
        self.assertFalse(retained_subhourly & set(subhourly["excluded"]))
        self.assertEqual(
            retained_hourly | set(hourly["excluded"]),
            _catalog_ids(ROOT / "registries/hrrr_hourly_v375.csv"),
        )
        self.assertEqual(
            retained_subhourly | set(subhourly["excluded"]),
            _catalog_ids(ROOT / "registries/hrrr_subhourly_v375.csv"),
        )

    def test_spatial_mapping_covers_only_retained_fields(self) -> None:
        fields = self.scope["field_universe"]
        retained = set(
            fields["wrfsfcf"]["dynamic"]
            + fields["wrfsfcf"]["static"]
            + fields["wrfsubhf"]["dynamic"]
        )
        self.assertEqual(
            set(self.scope["baseline_spatial_contract_by_field"]), retained
        )
        spatial = json.loads(SPATIAL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(spatial["status"], "SEALED_FOR_R14_CONFIRMATION_PILOT")
        self.assertTrue(spatial["confirmation_pilot_authorized"])
        self.assertFalse(spatial["full_history_authorized"])
        self.assertEqual(len(spatial["support_order"]), 8)
        self.assertEqual(
            set().union(*(set(value) for value in spatial["field_operators"].values())),
            retained,
        )

    def test_right_open_request_accounting(self) -> None:
        schedule = self.scope["schedule"]
        counts = self.scope["request_accounting_expectation"]
        self.assertTrue(schedule["window_end_is_exclusive"])
        self.assertTrue(schedule["r14_schedule_rebuild_required"])
        self.assertEqual(
            counts["wrfsfcf_logical_request_count"],
            counts["wrfsfcf_dynamic_native_state_count"]
            * counts["wrfsfcf_dynamic_identity_count"]
            + counts["wrfsfcf_static_request_count"],
        )
        self.assertEqual(
            counts["combined_logical_request_count"],
            counts["wrfsfcf_logical_request_count"]
            + counts["wrfsubhf_logical_request_count"],
        )
        self.assertEqual(counts["combined_logical_request_count"], 8_919_598)

    def test_project_config_points_to_unified_r14_workflow(self) -> None:
        with (ROOT / "config/project_v375.toml").open("rb") as stream:
            project = tomllib.load(stream)
        self.assertEqual(
            project["project"]["active_acquisition_scope_id"],
            self.scope["scope_id"],
        )
        self.assertEqual(project["execution"]["owner_facing_acquisition_step"], 5)
        self.assertEqual(project["execution"]["max_total_download_workers"], 8)
        self.assertEqual(
            project["execution"]["phase_order"],
            ["WRFSFCF_R14", "WRFSUBHF_Q05_R14"],
        )


if __name__ == "__main__":
    unittest.main()
