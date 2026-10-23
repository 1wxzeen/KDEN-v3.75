from __future__ import annotations

import unittest
from datetime import timedelta
from pathlib import Path

import pyarrow.parquet as pq

from kden_v375.contracts import ContractError
from kden_v375.hashes import sha256_file
from kden_v375.prefit.p03_issue_spine import ISSUE_OUTPUT_PATH, SELECTION_OUTPUT_PATH
from kden_v375.prefit.p05_materialization import (
    RELEASE_MANIFEST_PATH,
    _load_feature_authority,
    _load_field_contracts,
)
from kden_v375.prefit.p06_acceptance import (
    EXPECTED_FEATURE_COUNT,
    EXPECTED_FEATURE_ROWS,
    EXPECTED_ISSUE_ROWS,
    EXPECTED_SELECTION_ROWS,
    EXPECTED_TRAJECTORY_ROWS,
    _check_leakage,
    _expected_era,
    _expected_trajectory_era,
    _load_feature_range_errata,
    _load_schedule_authority,
    _read_json,
    _validate_feature_row,
    _validate_issue_row,
    _validate_selection_row,
    _validate_trajectory_row,
    p06_preflight,
)


ROOT = Path(__file__).resolve().parents[2]


def _first_row(path: Path) -> dict[str, object]:
    return next(pq.ParquetFile(path).iter_batches(batch_size=1)).to_pylist()[0]


class PrefitP06AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = _read_json(ROOT / RELEASE_MANIFEST_PATH)
        cls.features, registry_hash = _load_feature_authority(ROOT)
        cls.range_errata, _ = _load_feature_range_errata(
            ROOT,
            registry_hash=registry_hash,
            features=cls.features,
        )
        cls.schedule, _, _ = _load_schedule_authority(ROOT)

    def test_preflight_is_network_free_and_uses_frozen_counts(self) -> None:
        result = p06_preflight(ROOT)
        self.assertEqual(result["status"], "READY_FOR_OWNER_P06")
        self.assertEqual(result["expected_issue_rows"], EXPECTED_ISSUE_ROWS)
        self.assertEqual(result["expected_selection_rows"], EXPECTED_SELECTION_ROWS)
        self.assertEqual(result["expected_feature_rows"], EXPECTED_FEATURE_ROWS)
        self.assertEqual(result["expected_trajectory_rows"], EXPECTED_TRAJECTORY_ROWS)
        self.assertEqual(result["feature_count"], EXPECTED_FEATURE_COUNT)
        self.assertEqual(result["network_requests_made"], 0)
        self.assertEqual(result["truth_value_rows_read"], 0)
        self.assertEqual(result["model_fits_performed"], 0)

    def test_actual_issue_and_selection_obey_clock_and_availability_rules(self) -> None:
        issue = _first_row(ROOT / ISSUE_OUTPUT_PATH)
        selection = _first_row(ROOT / SELECTION_OUTPUT_PATH)
        self.assertEqual(selection["issue_state_id"], issue["issue_state_id"])
        _validate_issue_row(issue)
        _validate_selection_row(selection, issue, self.schedule)

        bad_issue = dict(issue)
        bad_issue["target_window_end_utc"] = issue["target_window_end_utc"] + timedelta(minutes=15)
        with self.assertRaises(ContractError):
            _validate_issue_row(bad_issue)

        bad_selection = dict(selection)
        bad_selection["emulated_complete_time_utc"] = issue["issue_time_utc"] + timedelta(minutes=1)
        with self.assertRaises(ContractError):
            _validate_selection_row(bad_selection, issue, self.schedule)

    def test_post_dst_predecessor_context_may_begin_before_target_window(self) -> None:
        identifier = "ISSUE_80f9eabb769bfcdaa393112df1a76aa037d67a50490a5e737e2e7c27a7db9d53"
        issue = pq.read_table(
            ROOT / ISSUE_OUTPUT_PATH,
            filters=[("issue_state_id", "=", identifier)],
        ).to_pylist()[0]
        selection = pq.read_table(
            ROOT / SELECTION_OUTPUT_PATH,
            filters=[
                ("issue_state_id", "=", identifier),
                ("product", "=", "wrfsfcf"),
            ],
        ).to_pylist()[0]
        self.assertLess(selection["retained_valid_start_utc"], issue["target_window_start_utc"])
        self.assertLess(
            selection["previous_retained_valid_start_utc"],
            issue["target_window_start_utc"],
        )
        _validate_selection_row(selection, issue, self.schedule)

    def test_actual_feature_row_reconciles_to_p03_authorities(self) -> None:
        issue = _first_row(ROOT / ISSUE_OUTPUT_PATH)
        selection_rows = next(
            pq.ParquetFile(ROOT / SELECTION_OUTPUT_PATH).iter_batches(batch_size=2)
        ).to_pylist()
        selections = {str(row["product"]): row for row in selection_rows}
        feature_path = ROOT / self.manifest["deterministic_features"]["year_partitions"][0]["path"]
        feature = _first_row(feature_path)
        self.assertEqual(feature["issue_state_id"], issue["issue_state_id"])
        checked, _ = _validate_feature_row(
            feature,
            issue,
            selections,
            self.features,
            self.range_errata,
        )
        self.assertGreater(checked, 0)

    def test_three_narrow_range_errata_accept_real_values_and_fail_closed(self) -> None:
        self.assertEqual(
            set(self.range_errata),
            {
                "support_wrfsfcf_retained_start_offset_minutes",
                "support_wrfsubhf_retained_start_offset_minutes",
                "derived_dewpoint_depression_future_first_k",
            },
        )
        feature_path = ROOT / self.manifest["deterministic_features"]["year_partitions"][0]["path"]
        identifiers = (
            "ISSUE_80f9eabb769bfcdaa393112df1a76aa037d67a50490a5e737e2e7c27a7db9d53",
            "ISSUE_fb602f469393f2e6e352066df701653de051299db9e8aaf919f77cc76e4836b7",
        )
        rows: dict[str, tuple[dict[str, object], dict[str, dict[str, object]], dict[str, object]]] = {}
        for identifier in identifiers:
            issue = pq.read_table(
                ROOT / ISSUE_OUTPUT_PATH,
                filters=[("issue_state_id", "=", identifier)],
            ).to_pylist()[0]
            selection_rows = pq.read_table(
                ROOT / SELECTION_OUTPUT_PATH,
                filters=[("issue_state_id", "=", identifier)],
            ).to_pylist()
            feature = pq.read_table(
                feature_path,
                filters=[("issue_state_id", "=", identifier)],
            ).to_pylist()[0]
            rows[identifier] = (
                issue,
                {str(row["product"]): row for row in selection_rows},
                feature,
            )

        dst_issue, dst_selections, dst_feature = rows[identifiers[0]]
        self.assertEqual(dst_feature["support_wrfsfcf_retained_start_offset_minutes"], -60)
        self.assertEqual(dst_feature["support_wrfsubhf_retained_start_offset_minutes"], -60)
        _validate_feature_row(
            dst_feature,
            dst_issue,
            dst_selections,
            self.features,
            self.range_errata,
        )
        below_dst_bound = dict(dst_feature)
        below_dst_bound["support_wrfsfcf_retained_start_offset_minutes"] = -61
        with self.assertRaises(ContractError):
            _validate_feature_row(
                below_dst_bound,
                dst_issue,
                dst_selections,
                self.features,
                self.range_errata,
            )

        dewpoint_issue, dewpoint_selections, dewpoint_feature = rows[identifiers[1]]
        self.assertLess(dewpoint_feature["derived_dewpoint_depression_future_first_k"], 0)
        _validate_feature_row(
            dewpoint_feature,
            dewpoint_issue,
            dewpoint_selections,
            self.features,
            self.range_errata,
        )
        below_dewpoint_bound = dict(dewpoint_feature)
        below_dewpoint_bound["derived_dewpoint_depression_future_first_k"] = -0.051
        with self.assertRaises(ContractError):
            _validate_feature_row(
                below_dewpoint_bound,
                dewpoint_issue,
                dewpoint_selections,
                self.features,
                self.range_errata,
            )

    def test_actual_trajectory_row_obeys_reference_contract(self) -> None:
        entry = self.manifest["trajectory_catalog"]["year_partitions"][0]
        partition = ROOT / entry["path"]
        row = _first_row(partition)
        canonical_path = ROOT / str(row["canonical_archive_path"])
        self.assertEqual(sha256_file(canonical_path), row["canonical_archive_sha256"])
        self.assertGreater(pq.ParquetFile(canonical_path).metadata.num_rows, 0)
        contracts = _load_field_contracts(ROOT)
        for field in ("H02", "H36", "H38", "Q05"):
            representative = pq.read_table(
                partition,
                filters=[("field_registry_id", "=", field)],
            ).slice(0, 1).to_pylist()[0]
            self.assertTrue(
                _validate_trajectory_row(
                    representative,
                    year=int(entry["year"]),
                    field_contracts=contracts,
                    schedule_rows=self.schedule,
                )
            )
        bad = dict(row)
        bad["forecast_lead_min"] = int(row["forecast_lead_min"]) + 15
        with self.assertRaises(ContractError):
            _validate_trajectory_row(
                bad,
                year=int(entry["year"]),
                field_contracts=contracts,
                schedule_rows=self.schedule,
            )

    def test_coordinate_transition_trajectory_uses_physical_valid_time(self) -> None:
        entry = self.manifest["trajectory_catalog"]["year_partitions"][0]
        partition = ROOT / entry["path"]
        identifier = "TRAJECTORY_STATE_c0787e6052d2a0c8a7d24ffa0c8821153136e616bb83d5faf3d9a285bfef0ccb"
        row = pq.read_table(
            partition,
            filters=[("trajectory_state_id", "=", identifier)],
        ).to_pylist()[0]
        self.assertNotEqual(row["station_coord_era"], _expected_era(row["target_date"]))
        self.assertEqual(
            row["station_coord_era"],
            _expected_trajectory_era(row["valid_time_utc"]),
        )
        self.assertTrue(
            _validate_trajectory_row(
                row,
                year=int(entry["year"]),
                field_contracts=_load_field_contracts(ROOT),
                schedule_rows=self.schedule,
            )
        )
        wrong = dict(row)
        wrong["station_coord_era"] = _expected_era(row["target_date"])
        with self.assertRaises(ContractError):
            _validate_trajectory_row(
                wrong,
                year=int(entry["year"]),
                field_contracts=_load_field_contracts(ROOT),
                schedule_rows=self.schedule,
            )

    def test_all_known_missing_trajectories_preserve_contract_without_payloads(self) -> None:
        contracts = _load_field_contracts(ROOT)
        missing: list[tuple[int, dict[str, object]]] = []
        for entry in self.manifest["trajectory_catalog"]["year_partitions"]:
            partition = ROOT / entry["path"]
            rows = pq.read_table(
                partition,
                filters=[("coverage_flag", "=", "MISSING")],
            ).to_pylist()
            missing.extend((int(entry["year"]), row) for row in rows)
        self.assertEqual(len(missing), 12)
        for year, row in missing:
            self.assertFalse(row["tile_values_available"])
            self.assertFalse(row["regional_values_available"])
            self.assertEqual(row["regional_coverage_mask"], 0)
            self.assertFalse(
                _validate_trajectory_row(
                    row,
                    year=year,
                    field_contracts=contracts,
                    schedule_rows=self.schedule,
                )
            )

        poisoned = dict(missing[0][1])
        poisoned["tile_values_available"] = True
        with self.assertRaises(ContractError):
            _validate_trajectory_row(
                poisoned,
                year=missing[0][0],
                field_contracts=contracts,
                schedule_rows=self.schedule,
            )

    def test_model_neutral_namespace_scan_fails_closed(self) -> None:
        config = _read_json(ROOT / "config/prefit/p06_acceptance_v375.json")
        evidence = _check_leakage(config, self.features)
        self.assertEqual(evidence["truth_leakage_found"], 0)
        poisoned = [dict(row) for row in self.features]
        poisoned[0]["name"] = "truth_leak"
        with self.assertRaises(ContractError):
            _check_leakage(config, poisoned)


if __name__ == "__main__":
    unittest.main()
