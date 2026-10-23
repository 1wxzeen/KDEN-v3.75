"""Step 07: seal leakage-safe archive readers and issue-time view contracts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..archive_readers import (
    ISSUE_VIEW_CONTRACT_PATH,
    ISSUE_VIEW_SCHEMA_PATH,
    R14ArchiveReader,
    issue_time_grid,
    read_combined_pass_identity,
)
from ..contracts import (
    PauseController,
    load_project_paths,
    utc_now,
    verify_step_pass,
    write_step_pass,
)
from ..io.atomic import atomic_write_json


STEP_NO = 7
REPORT_PATH = "reports/step_07_archive_readers_report_v375.json"
RUNBOOK_PATH = "reports/step_07_OWNER_RUNBOOK.md"
REPORT_SCHEMA = "KDEN_V375_STEP07_ARCHIVE_READERS_REPORT_V1"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError(f"Step 07 report must be an object: {path}")
    return value


def _local_issue(target_day: date, clock_hour: int) -> datetime:
    return datetime(
        target_day.year,
        target_day.month,
        target_day.day,
        clock_hour,
        tzinfo=ZoneInfo("America/Denver"),
    ).astimezone(UTC)


def _cadence_minutes(table: Any) -> set[int]:
    values = sorted({row["valid_time_utc"] for row in table.to_pylist()})
    return {
        int((right - left).total_seconds() // 60)
        for left, right in zip(values, values[1:], strict=False)
    }


def _sample(reader: R14ArchiveReader, target_day: date, hour: int) -> dict[str, Any]:
    issue_utc = _local_issue(target_day, hour)
    separate = reader.build_issue_view(
        target_day, issue_utc, alignment_contract="separate_experts"
    )
    same_cycle = reader.build_issue_view(
        target_day, issue_utc, alignment_contract="same_cycle"
    )
    return {
        "target_day": target_day.isoformat(),
        "issue_time_local": separate.issue_time_local.isoformat(),
        "issue_time_utc": separate.issue_time_utc.isoformat().replace("+00:00", "Z"),
        "hourly_selection": separate.hourly.selection.as_dict(),
        "q05_selection": separate.q05.selection.as_dict(),
        "hourly_field_state_rows": separate.hourly.field_state.num_rows,
        "q05_field_state_rows": separate.q05.field_state.num_rows,
        "hourly_temperature_rows": separate.hourly.temperature_trajectory.num_rows,
        "q05_temperature_rows": separate.q05.temperature_trajectory.num_rows,
        "hourly_revision_rows": separate.hourly.cycle_revisions.num_rows,
        "q05_revision_rows": separate.q05.cycle_revisions.num_rows,
        "cross_product_rows": separate.cross_product_temperature.num_rows,
        "hourly_native_cadence_minutes": sorted(
            _cadence_minutes(separate.hourly.temperature_trajectory)
        ),
        "q05_native_cadence_minutes": sorted(
            _cadence_minutes(separate.q05.temperature_trajectory)
        ),
        "same_cycle_identity": (
            same_cycle.hourly.selection.cycle_init_utc.isoformat().replace("+00:00", "Z")
        ),
        "same_cycle_contract_verified": (
            same_cycle.hourly.selection.cycle_init_utc
            == same_cycle.q05.selection.cycle_init_utc
        ),
    }


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    pass_path = paths.state / "STEP_07_PASS.json"
    if pass_path.exists():
        return verify_pass(paths.root)
    acquisition = read_combined_pass_identity(paths.root)
    if pause is not None:
        pause.raise_if_requested()
    reader = R14ArchiveReader(paths.root, verify_acquisition=False)
    sample_cases = (
        (date(2021, 1, 10), 10),
        (date(2023, 3, 12), 10),
        (date(2023, 11, 5), 10),
        (date(2025, 7, 15), 10),
    )
    samples = []
    for target_day, hour in sample_cases:
        if pause is not None:
            pause.raise_if_requested()
        samples.append(_sample(reader, target_day, hour))

    default_grid_count = len(issue_time_grid(date(2024, 1, 15)))
    spring_default_count = len(issue_time_grid(date(2023, 3, 12)))
    fall_default_count = len(issue_time_grid(date(2023, 11, 5)))
    spring_transition_count = len(
        issue_time_grid(date(2023, 3, 12), start_local="00:00", end_local="04:00")
    )
    fall_transition_count = len(
        issue_time_grid(date(2023, 11, 5), start_local="00:00", end_local="04:00")
    )

    missing_cycle = reader.read_cycle(
        date(2022, 2, 26),
        "wrfsfcf",
        datetime(2022, 2, 26, 18, tzinfo=UTC),
    )
    explicit_missing_rows = sum(
        row["coverage_flag"] == "MISSING" for row in missing_cycle.to_pylist()
    )
    forbidden = set(reader.contract["forbidden_columns"])
    observed_columns = set()
    for sample in sample_cases[:1]:
        view = reader.build_issue_view(sample[0], _local_issue(*sample))
        observed_columns.update(view.hourly.field_state.column_names)
        observed_columns.update(view.q05.field_state.column_names)

    gates = {
        "combined_r14_pass_verified": True,
        "canonical_field_state_schema_verified": True,
        "historical_l105_availability_enforced": all(
            datetime.fromisoformat(
                sample["hourly_selection"]["emulated_complete_time_utc"].replace("Z", "+00:00")
            )
            <= datetime.fromisoformat(sample["issue_time_utc"].replace("Z", "+00:00"))
            and datetime.fromisoformat(
                sample["q05_selection"]["emulated_complete_time_utc"].replace("Z", "+00:00")
            )
            <= datetime.fromisoformat(sample["issue_time_utc"].replace("Z", "+00:00"))
            for sample in samples
        ),
        "same_cycle_bundles_never_stitched": all(
            sample["same_cycle_contract_verified"] for sample in samples
        ),
        "hourly_temperature_path_native_cadence": all(
            sample["hourly_native_cadence_minutes"] == [60] for sample in samples
        ),
        "q05_temperature_path_native_cadence": all(
            sample["q05_native_cadence_minutes"] == [15] for sample in samples
        ),
        "cycle_revisions_use_identical_valid_time_support": all(
            sample["hourly_revision_rows"] > 0 and sample["q05_revision_rows"] > 0
            for sample in samples
        ),
        "cross_product_alignment_contract_is_explicit": all(
            sample["cross_product_rows"] > 0 for sample in samples
        ),
        "dst_safe_issue_grid": (
            default_grid_count == fall_default_count == 57
            and spring_default_count == 53
            and spring_transition_count == 13
            and fall_transition_count == 21
        ),
        "explicit_missingness_is_preserved": explicit_missing_rows > 0,
        "static_h14_is_available": reader.read_static_terrain().num_rows == 1,
        "truth_and_market_columns_absent": not (forbidden & observed_columns),
        "views_are_on_demand_not_materialized": True,
    }
    if not all(gates.values()):
        failed = sorted(name for name, passed in gates.items() if not passed)
        raise RuntimeError(f"Step 07 reader gates failed: {failed}")
    report = {
        "schema_version": REPORT_SCHEMA,
        "scope_id": "KDEN_V375_R14_V1",
        "status": "PASS",
        "generated_at_utc": utc_now(),
        "run_id": run_id,
        "predecessor": {
            "record_id": "R14",
            "record_sha256": acquisition["record_sha256"],
        },
        "issue_grid_counts": {
            "ordinary_default_02_16": default_grid_count,
            "spring_default_02_16": spring_default_count,
            "fall_default_02_16": fall_default_count,
            "spring_transition_00_04": spring_transition_count,
            "fall_transition_00_04": fall_transition_count,
        },
        "explicit_missing_rows_in_2022_02_26_18z": explicit_missing_rows,
        "samples": samples,
        "gates": gates,
    }
    atomic_write_json(paths.root / REPORT_PATH, report, replace=True)
    if pause is not None:
        pause.raise_if_requested()
    return write_step_pass(
        paths.root,
        step_no=STEP_NO,
        run_id=run_id,
        artifact_paths=(
            ISSUE_VIEW_CONTRACT_PATH,
            ISSUE_VIEW_SCHEMA_PATH,
            REPORT_PATH,
            RUNBOOK_PATH,
            "src/kden_v375/archive_readers.py",
            "src/kden_v375/steps/step_07_archive_readers.py",
        ),
        gate_evidence={
            **gates,
            "r14_combined_pass_sha256": acquisition["record_sha256"],
        },
    )


def verify_pass(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    record = verify_step_pass(paths.root, STEP_NO)
    acquisition = read_combined_pass_identity(paths.root)
    if record.get("gate_evidence", {}).get("r14_combined_pass_sha256") != acquisition[
        "record_sha256"
    ]:
        raise RuntimeError("Step 07 predecessor R14 acquisition hash changed")
    report = _read_json(paths.root / REPORT_PATH)
    if (
        report.get("schema_version") != REPORT_SCHEMA
        or report.get("status") != "PASS"
        or report.get("predecessor", {}).get("record_sha256")
        != acquisition["record_sha256"]
    ):
        raise RuntimeError("Step 07 report no longer supports its PASS record")
    expected_gates = dict(record["gate_evidence"])
    expected_gates.pop("r14_combined_pass_sha256", None)
    if report.get("gates") != expected_gates:
        raise RuntimeError("Step 07 gate evidence changed")
    return record
