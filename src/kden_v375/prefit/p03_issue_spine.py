"""P03: materialize causal issue states and independent legal-cycle selections."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from ..archive_readers import (
    R14ArchiveReader,
    issue_time_grid,
    load_issue_view_contract,
    read_combined_pass_identity,
    select_newest_legal_cycle,
)
from ..contracts import (
    ContractError,
    ExclusiveRunLock,
    PauseController,
    PauseRequested,
    StaleStateError,
    load_project_paths,
    validate_runtime_isolation,
)
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_file
from ..io.atomic import atomic_write_bytes, atomic_write_json
from ..time import as_utc
from .records import (
    make_prefit_run_id,
    utc_now,
    validate_prefit_run_id,
    verify_prefit_pass,
    write_prefit_pass,
)


STAGE_NO = 3
CONFIG_PATH = "config/prefit/p03_issue_spine_v375.json"
ISSUE_SCHEMA_PATH = "schemas/prefit/issue_spine_v375.json"
SELECTION_SCHEMA_PATH = "schemas/prefit/selected_cycles_v375.json"
MANIFEST_SCHEMA_PATH = "schemas/prefit/p03_selection_manifest_v375.json"
RUN_STATE_SCHEMA_PATH = "schemas/prefit/p03_run_state_v375.json"
RUNBOOK_PATH = "reports/prefit/P03_OWNER_RUNBOOK.md"
REPORT_PATH = "reports/prefit/P03_ISSUE_SPINE_COVERAGE_DST_REPORT.md"
ISSUE_OUTPUT_PATH = "universal_issue_state/v1/issue_spine/issue_spine.parquet"
SELECTION_OUTPUT_PATH = (
    "universal_issue_state/v1/selected_cycles/selected_cycles.parquet"
)
MANIFEST_PATH = "universal_issue_state/v1/manifests/p03_selection_manifest.json"
PASS_PATH = "state/PREFIT_P03_PASS.json"

RUN_STATE_SCHEMA = "KDEN_V375_PREFIT_P03_RUN_V1"
MANIFEST_SCHEMA = "KDEN_V375_PREFIT_P03_SELECTION_MANIFEST_V1"
ISSUE_SCHEMA_ID = "KDEN_V375_ISSUE_SPINE_V1"
SELECTION_SCHEMA_ID = "KDEN_V375_SELECTED_CYCLES_V1"
ISSUE_GRID_ID = "KDEN_V375_ISSUE_GRID_0200_1600_MT_Q15_V1"
AVAILABILITY_BASIS = "historical_cycle_init_plus_105_minutes"
STUDY_START = date(2021, 1, 1)
STUDY_END = date(2026, 9, 11)
EXPECTED_TARGET_DAYS = 2080
EXPECTED_ISSUE_ROWS = 118536
EXPECTED_SELECTION_ROWS = EXPECTED_ISSUE_ROWS * 2
PRODUCT_ORDER = ("wrfsfcf", "wrfsubhf")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ContractError(f"JSON object expected: {path}")
    return value


def _inside(root: Path, relative: str | Path) -> Path:
    candidate = (root / Path(relative)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"path escapes project root: {relative}") from exc
    return candidate


def _inclusive_dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=index) for index in range((end - start).days + 1))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ContractError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}_{sha256_bytes(canonical_json_bytes(dict(value)))}"


def issue_state_id(target_day: date, issue_time_utc: datetime) -> str:
    return _stable_id(
        "ISSUE",
        {
            "schema_id": ISSUE_SCHEMA_ID,
            "target_date": target_day.isoformat(),
            "issue_time_utc": as_utc(issue_time_utc).isoformat().replace("+00:00", "Z"),
        },
    )


def schedule_row_id(target_day: date, product: str, cycle_init_utc: datetime) -> str:
    return _stable_id(
        "SCHEDULE",
        {
            "target_date": target_day.isoformat(),
            "product": product,
            "cycle_init_utc": as_utc(cycle_init_utc).isoformat().replace("+00:00", "Z"),
        },
    )


def trajectory_bundle_id(target_day: date, product: str, cycle_init_utc: datetime) -> str:
    return _stable_id(
        "TRAJECTORY",
        {
            "scope_id": "KDEN_V375_R14_V1",
            "target_date": target_day.isoformat(),
            "product": product,
            "cycle_init_utc": as_utc(cycle_init_utc).isoformat().replace("+00:00", "Z"),
        },
    )


def issue_spine_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("issue_state_id", pa.string(), nullable=False),
            pa.field("target_date", pa.date32(), nullable=False),
            pa.field("statistical_group_id", pa.string(), nullable=False),
            pa.field("issue_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field(
                "issue_time_local",
                pa.timestamp("us", tz="America/Denver"),
                nullable=False,
            ),
            pa.field("local_timezone", pa.string(), nullable=False),
            pa.field("local_utc_offset_minutes", pa.int16(), nullable=False),
            pa.field("local_dst_flag", pa.bool_(), nullable=False),
            pa.field("local_fold", pa.int8(), nullable=False),
            pa.field("local_issue_hour", pa.int8(), nullable=False),
            pa.field("local_issue_minute", pa.int8(), nullable=False),
            pa.field("local_minutes_since_0200", pa.int16(), nullable=False),
            pa.field("issue_ordinal_in_target_day", pa.int8(), nullable=False),
            pa.field("issue_count_for_target_day", pa.int8(), nullable=False),
            pa.field("target_window_start_utc", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("target_window_end_utc", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("target_year", pa.int16(), nullable=False),
            pa.field("target_month", pa.int8(), nullable=False),
            pa.field("target_day_of_month", pa.int8(), nullable=False),
            pa.field("target_day_of_year", pa.int16(), nullable=False),
            pa.field("target_day_of_week", pa.int8(), nullable=False),
            pa.field("issue_grid_contract_id", pa.string(), nullable=False),
            pa.field("issue_state_eligible", pa.bool_(), nullable=False),
        ],
        metadata={
            b"schema_version": b"KDEN_V375_PARQUET_SCHEMA_V1",
            b"schema_id": ISSUE_SCHEMA_ID.encode("ascii"),
        },
    )


def selected_cycles_schema() -> pa.Schema:
    timestamp_utc = pa.timestamp("us", tz="UTC")
    timestamp_local = pa.timestamp("us", tz="America/Denver")
    return pa.schema(
        [
            pa.field("issue_state_id", pa.string(), nullable=False),
            pa.field("target_date", pa.date32(), nullable=False),
            pa.field("issue_time_utc", timestamp_utc, nullable=False),
            pa.field("product", pa.string(), nullable=False),
            pa.field("selection_status", pa.string(), nullable=False),
            pa.field("cycle_init_utc", timestamp_utc),
            pa.field("cycle_init_local", timestamp_local),
            pa.field("emulated_complete_time_utc", timestamp_utc),
            pa.field("cycle_age_minutes", pa.int32()),
            pa.field("availability_age_minutes", pa.int32()),
            pa.field("previous_cycle_init_utc", timestamp_utc),
            pa.field("previous_cycle_init_local", timestamp_local),
            pa.field("previous_emulated_complete_time_utc", timestamp_utc),
            pa.field("previous_cycle_age_minutes", pa.int32()),
            pa.field("previous_availability_age_minutes", pa.int32()),
            pa.field("availability_policy_id", pa.string(), nullable=False),
            pa.field("availability_basis", pa.string(), nullable=False),
            pa.field("source_schedule_id", pa.string(), nullable=False),
            pa.field("source_schedule_row_id", pa.string()),
            pa.field("previous_source_schedule_row_id", pa.string()),
            pa.field("retained_valid_start_utc", timestamp_utc),
            pa.field("retained_valid_end_utc", timestamp_utc),
            pa.field("previous_retained_valid_start_utc", timestamp_utc),
            pa.field("previous_retained_valid_end_utc", timestamp_utc),
            pa.field("trajectory_bundle_id", pa.string()),
            pa.field("trajectory_bundle_path", pa.string()),
            pa.field("trajectory_bundle_present", pa.bool_(), nullable=False),
            pa.field("previous_trajectory_bundle_id", pa.string()),
            pa.field("previous_trajectory_bundle_path", pa.string()),
            pa.field("previous_trajectory_bundle_present", pa.bool_(), nullable=False),
            pa.field("selection_missing_reason", pa.string()),
        ],
        metadata={
            b"schema_version": b"KDEN_V375_PARQUET_SCHEMA_V1",
            b"schema_id": SELECTION_SCHEMA_ID.encode("ascii"),
        },
    )


def _parquet_bytes(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> bytes:
    table = pa.Table.from_pylist(list(rows), schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        version="2.6",
        write_statistics=True,
        row_group_size=65536,
    )
    return sink.getvalue().to_pybytes()


def _load_config(root: Path) -> dict[str, Any]:
    config = _read_json(root / CONFIG_PATH)
    if config.get("schema_version") != "KDEN_V375_PREFIT_P03_CONFIG_V1":
        raise ContractError("unsupported P03 configuration schema")
    if (
        config.get("start_date") != STUDY_START.isoformat()
        or config.get("end_date") != STUDY_END.isoformat()
        or config.get("expected_target_day_count") != EXPECTED_TARGET_DAYS
        or config.get("expected_issue_state_count") != EXPECTED_ISSUE_ROWS
        or config.get("expected_selected_cycle_row_count")
        != EXPECTED_SELECTION_ROWS
        or config.get("products") != list(PRODUCT_ORDER)
        or config.get("substrate_release_id")
        != "KDEN_V375_UNIVERSAL_ISSUE_STATE_V1"
    ):
        raise ContractError("P03 study scope changed")
    contract = load_issue_view_contract(root)
    grid = contract["default_issue_grid"]
    expected_grid = config["issue_grid"]
    for key in ("timezone", "start_local", "end_local", "cadence_minutes", "end_inclusive"):
        if grid.get(key) != expected_grid.get(key):
            raise ContractError(f"P03 issue grid disagrees with Step 07: {key}")
    if contract["availability"]["policy_id"] != config["availability_policy_id"]:
        raise ContractError("P03 availability policy disagrees with Step 07")
    return config


def _schedule_authority(root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    schedule_path = str(contract["schedule_path"])
    manifest_path = (
        "hrrr_v4_local_archive/common/cycle_schedule_r14/"
        "cycle_schedule_r14_v375_manifest.json"
    )
    manifest = _read_json(root / manifest_path)
    actual_schedule_hash = sha256_file(root / schedule_path)
    if manifest.get("parquet", {}).get("sha256") != actual_schedule_hash:
        raise StaleStateError("frozen R14 schedule hash mismatch")
    if manifest.get("scope_id") != "KDEN_V375_R14_V1":
        raise ContractError("frozen R14 schedule scope changed")
    bases = set(
        pq.read_table(root / schedule_path, columns=["availability_basis"])
        .column("availability_basis")
        .to_pylist()
    )
    if bases != {AVAILABILITY_BASIS}:
        raise ContractError(f"frozen R14 schedule availability basis changed: {bases}")
    return {
        "schedule_id": manifest["schedule_id"],
        "schedule_path": schedule_path,
        "schedule_sha256": actual_schedule_hash,
        "schedule_manifest_path": manifest_path,
        "schedule_manifest_sha256": sha256_file(root / manifest_path),
        "schedule_logical_sha256": manifest["logical_schedule_sha256"],
        "schedule_row_count": manifest["row_count"],
    }


def _predecessor(root: Path) -> dict[str, Any]:
    record = verify_prefit_pass(root, 2)
    if record.get("record_sha256") != (
        "40ff18bbac4c927ae600fd54026671493f4e68e5e0d65cdf07374965837cf607"
    ):
        raise StaleStateError("P03 requires the accepted P02 truth release")
    return record


def _command_prefix() -> str:
    return ".venv/bin/python -m kden_v375.prefit.cli"


def p03_preflight(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    predecessor = _predecessor(root)
    config = _load_config(root)
    contract = load_issue_view_contract(root)
    authority = _schedule_authority(root, contract)
    acquisition = read_combined_pass_identity(root)
    parquet = pq.ParquetFile(root / authority["schedule_path"])
    if parquet.metadata.num_rows != authority["schedule_row_count"]:
        raise ContractError("R14 schedule row count disagrees with its manifest")
    run_id = make_prefit_run_id(3, "owner-full", "issue-spine")
    prefix = _command_prefix()
    return {
        "schema_version": "KDEN_V375_PREFIT_P03_PREFLIGHT_V1",
        "status": "READY_FOR_OWNER_P03",
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "predecessor_record_sha256": predecessor["record_sha256"],
        "r14_record_sha256": acquisition["record_sha256"],
        "schedule": authority,
        "target_day_count": config["expected_target_day_count"],
        "expected_issue_state_count": EXPECTED_ISSUE_ROWS,
        "expected_selected_cycle_row_count": EXPECTED_SELECTION_ROWS,
        "suggested_run_id": run_id,
        "start_command": f"{prefix} run-p03 --run-id {run_id}",
        "status_command": f"{prefix} p03-status --run-id {run_id}",
        "live_status_command": (
            f"{prefix} p03-live-status --run-id {run_id} --interval-seconds 5"
        ),
        "eta_command": f"{prefix} p03-eta --run-id {run_id}",
        "pause_command": f"{prefix} p03-pause --run-id {run_id}",
        "resume_command": f"{prefix} resume-p03 --run-id {run_id}",
        "validation_command": f"{prefix} validate-p03",
    }


def _run_paths(root: Path, run_id: str) -> dict[str, Path]:
    base = _inside(root, Path("prefit_runs") / run_id / "p03")
    return {
        "base": base,
        "state": base / "run.json",
        "pause": base / "control/pause.requested.json",
        "checkpoints": base / "checkpoints",
    }


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    atomic_write_json(path, dict(state), replace=True)


def _initialize_state(root: Path, run_id: str) -> dict[str, Any]:
    validate_prefit_run_id(run_id, stage_no=3, scope="owner-full")
    path = _run_paths(root, run_id)["state"]
    if path.is_file():
        state = _read_json(path)
        if state.get("schema_version") != RUN_STATE_SCHEMA or state.get("run_id") != run_id:
            raise StaleStateError("P03 run-state identity mismatch")
        return state
    created = utc_now()
    state = {
        "schema_version": RUN_STATE_SCHEMA,
        "stage_id": "PREFIT_P03",
        "run_id": run_id,
        "status": "INITIALIZED",
        "phase": "NOT_STARTED",
        "message": "initialized",
        "created_at_utc": created,
        "started_at_utc": None,
        "updated_at_utc": created,
        "expected_target_days": EXPECTED_TARGET_DAYS,
        "completed_target_days": 0,
        "expected_issue_states": EXPECTED_ISSUE_ROWS,
        "completed_issue_states": 0,
        "expected_selection_rows": EXPECTED_SELECTION_ROWS,
        "completed_selection_rows": 0,
        "completed_years": [],
        "current_target_date": None,
    }
    _write_state(path, state)
    return state


def _update_state(root: Path, run_id: str, **updates: Any) -> dict[str, Any]:
    path = _run_paths(root, run_id)["state"]
    state = _read_json(path)
    state.update(updates, updated_at_utc=utc_now())
    _write_state(path, state)
    return state


def _issue_rows_for_day(target_day: date, config: Mapping[str, Any]) -> list[dict[str, Any]]:
    grid = config["issue_grid"]
    timezone = ZoneInfo(str(grid["timezone"]))
    instants = issue_time_grid(
        target_day,
        timezone_name=str(grid["timezone"]),
        start_local=str(grid["start_local"]),
        end_local=str(grid["end_local"]),
        cadence_minutes=int(grid["cadence_minutes"]),
    )
    window_start = datetime(target_day.year, target_day.month, target_day.day, 7, tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    rows: list[dict[str, Any]] = []
    for ordinal, issue_utc in enumerate(instants):
        local = issue_utc.astimezone(timezone)
        offset = local.utcoffset()
        if offset is None:  # pragma: no cover
            raise ContractError("localized issue time lacks a UTC offset")
        rows.append(
            {
                "issue_state_id": issue_state_id(target_day, issue_utc),
                "target_date": target_day,
                "statistical_group_id": f"KDEN_DAY_{target_day.isoformat()}",
                "issue_time_utc": issue_utc,
                "issue_time_local": local,
                "local_timezone": str(grid["timezone"]),
                "local_utc_offset_minutes": int(offset.total_seconds() // 60),
                "local_dst_flag": bool(local.dst() and local.dst() != timedelta(0)),
                "local_fold": int(local.fold),
                "local_issue_hour": local.hour,
                "local_issue_minute": local.minute,
                "local_minutes_since_0200": local.hour * 60 + local.minute - 120,
                "issue_ordinal_in_target_day": ordinal,
                "issue_count_for_target_day": len(instants),
                "target_window_start_utc": window_start,
                "target_window_end_utc": window_end,
                "target_year": target_day.year,
                "target_month": target_day.month,
                "target_day_of_month": target_day.day,
                "target_day_of_year": target_day.timetuple().tm_yday,
                "target_day_of_week": target_day.weekday(),
                "issue_grid_contract_id": ISSUE_GRID_ID,
                "issue_state_eligible": True,
            }
        )
    return rows


def _bundle_path(
    contract: Mapping[str, Any], target_day: date, product: str, cycle_utc: datetime
) -> str:
    return (
        Path(str(contract["archive_roots"][product]))
        / f"target_year={target_day.year:04d}"
        / f"target_month={target_day.month:02d}"
        / f"target_day={target_day.isoformat()}"
        / f"cycle={as_utc(cycle_utc).strftime('%Y%m%dT%H%M%SZ')}"
        / "field_state.parquet"
    ).as_posix()


def _minutes(later: datetime, earlier: datetime) -> int:
    seconds = (as_utc(later) - as_utc(earlier)).total_seconds()
    if seconds % 60:
        raise ContractError("P03 clock difference is not minute-aligned")
    return int(seconds // 60)


def _selection_row(
    *,
    root: Path,
    issue_row: Mapping[str, Any],
    product: str,
    schedule_rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    authority: Mapping[str, Any],
    presence_cache: dict[str, bool],
) -> dict[str, Any]:
    target_day = issue_row["target_date"]
    issue_utc = issue_row["issue_time_utc"]
    try:
        current, previous = select_newest_legal_cycle(schedule_rows, issue_utc)
    except ContractError as exc:
        return {
            "issue_state_id": issue_row["issue_state_id"],
            "target_date": target_day,
            "issue_time_utc": issue_utc,
            "product": product,
            "selection_status": "MISSING_NO_LEGAL_CYCLE",
            "availability_policy_id": str(contract["availability"]["policy_id"]),
            "availability_basis": AVAILABILITY_BASIS,
            "source_schedule_id": str(authority["schedule_id"]),
            "trajectory_bundle_present": False,
            "previous_trajectory_bundle_present": False,
            "selection_missing_reason": str(exc),
        }
    current_cycle = as_utc(current["cycle_init_utc"])
    current_complete = as_utc(current["emulated_complete_time_utc"])
    current_path = _bundle_path(contract, target_day, product, current_cycle)
    if current_path not in presence_cache:
        presence_cache[current_path] = (root / current_path).is_file()
    previous_cycle = None if previous is None else as_utc(previous["cycle_init_utc"])
    previous_complete = (
        None if previous is None else as_utc(previous["emulated_complete_time_utc"])
    )
    previous_path = (
        None
        if previous_cycle is None
        else _bundle_path(contract, target_day, product, previous_cycle)
    )
    if previous_path is not None and previous_path not in presence_cache:
        presence_cache[previous_path] = (root / previous_path).is_file()
    current_present = presence_cache[current_path]
    previous_present = previous_path is not None and presence_cache[previous_path]
    status = "SELECTED" if current_present and previous_present else "MISSING_ARCHIVE_BUNDLE"
    missing_reasons = []
    if not current_present:
        missing_reasons.append("selected_trajectory_bundle_missing")
    if previous is None:
        missing_reasons.append("previous_legal_cycle_missing")
    elif not previous_present:
        missing_reasons.append("previous_trajectory_bundle_missing")
    return {
        "issue_state_id": issue_row["issue_state_id"],
        "target_date": target_day,
        "issue_time_utc": issue_utc,
        "product": product,
        "selection_status": status,
        "cycle_init_utc": current_cycle,
        "cycle_init_local": current["cycle_init_local"],
        "emulated_complete_time_utc": current_complete,
        "cycle_age_minutes": _minutes(issue_utc, current_cycle),
        "availability_age_minutes": _minutes(issue_utc, current_complete),
        "previous_cycle_init_utc": previous_cycle,
        "previous_cycle_init_local": None if previous is None else previous["cycle_init_local"],
        "previous_emulated_complete_time_utc": previous_complete,
        "previous_cycle_age_minutes": (
            None if previous_cycle is None else _minutes(issue_utc, previous_cycle)
        ),
        "previous_availability_age_minutes": (
            None if previous_complete is None else _minutes(issue_utc, previous_complete)
        ),
        "availability_policy_id": str(current["availability_policy_id"]),
        "availability_basis": AVAILABILITY_BASIS,
        "source_schedule_id": str(authority["schedule_id"]),
        "source_schedule_row_id": schedule_row_id(target_day, product, current_cycle),
        "previous_source_schedule_row_id": (
            None
            if previous_cycle is None
            else schedule_row_id(target_day, product, previous_cycle)
        ),
        "retained_valid_start_utc": as_utc(current["retained_valid_start_utc"]),
        "retained_valid_end_utc": as_utc(current["retained_valid_end_utc"]),
        "previous_retained_valid_start_utc": (
            None if previous is None else as_utc(previous["retained_valid_start_utc"])
        ),
        "previous_retained_valid_end_utc": (
            None if previous is None else as_utc(previous["retained_valid_end_utc"])
        ),
        "trajectory_bundle_id": trajectory_bundle_id(target_day, product, current_cycle),
        "trajectory_bundle_path": current_path,
        "trajectory_bundle_present": current_present,
        "previous_trajectory_bundle_id": (
            None
            if previous_cycle is None
            else trajectory_bundle_id(target_day, product, previous_cycle)
        ),
        "previous_trajectory_bundle_path": previous_path,
        "previous_trajectory_bundle_present": previous_present,
        "selection_missing_reason": ";".join(missing_reasons) or None,
    }


def _checkpoint_paths(root: Path, run_id: str, year: int) -> dict[str, Path]:
    base = _run_paths(root, run_id)["checkpoints"] / f"year={year:04d}"
    return {
        "issue": base / "issue_spine.parquet",
        "selection": base / "selected_cycles.parquet",
        "manifest": base / "manifest.json",
    }


def _valid_checkpoint(root: Path, run_id: str, year: int) -> dict[str, Any] | None:
    paths = _checkpoint_paths(root, run_id, year)
    if not paths["manifest"].is_file():
        return None
    manifest = _read_json(paths["manifest"])
    if manifest.get("schema_version") != "KDEN_V375_PREFIT_P03_YEAR_CHECKPOINT_V1":
        return None
    for key in ("issue", "selection"):
        if not paths[key].is_file() or sha256_file(paths[key]) != manifest[f"{key}_sha256"]:
            return None
    return manifest


def _build_year(
    *,
    root: Path,
    run_id: str,
    year: int,
    reader: R14ArchiveReader,
    config: Mapping[str, Any],
    contract: Mapping[str, Any],
    authority: Mapping[str, Any],
    pause: PauseController,
    completed_before: int,
) -> dict[str, Any]:
    targets = [target for target in _inclusive_dates(STUDY_START, STUDY_END) if target.year == year]
    issue_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    presence_cache: dict[str, bool] = {}
    last_publish = time.monotonic()
    for day_index, target in enumerate(targets, start=1):
        pause.raise_if_requested()
        day_issues = _issue_rows_for_day(target, config)
        for issue_row in day_issues:
            issue_rows.append(issue_row)
            for product in PRODUCT_ORDER:
                selection_rows.append(
                    _selection_row(
                        root=root,
                        issue_row=issue_row,
                        product=product,
                        schedule_rows=reader.schedule_rows(target, product),
                        contract=contract,
                        authority=authority,
                        presence_cache=presence_cache,
                    )
                )
        if day_index == len(targets) or day_index % 7 == 0 or time.monotonic() - last_publish >= 1:
            state = _read_json(_run_paths(root, run_id)["state"])
            checkpoint_issues = int(state.get("checkpoint_issue_states", 0))
            checkpoint_selections = int(state.get("checkpoint_selection_rows", 0))
            _update_state(
                root,
                run_id,
                completed_target_days=completed_before + day_index,
                completed_issue_states=checkpoint_issues + len(issue_rows),
                completed_selection_rows=checkpoint_selections + len(selection_rows),
                current_target_date=target.isoformat(),
            )
            last_publish = time.monotonic()
    paths = _checkpoint_paths(root, run_id, year)
    issue_hash = atomic_write_bytes(
        paths["issue"], _parquet_bytes(issue_rows, issue_spine_schema()), replace=True
    )
    selection_hash = atomic_write_bytes(
        paths["selection"],
        _parquet_bytes(selection_rows, selected_cycles_schema()),
        replace=True,
    )
    manifest = {
        "schema_version": "KDEN_V375_PREFIT_P03_YEAR_CHECKPOINT_V1",
        "year": year,
        "target_day_count": len(targets),
        "issue_row_count": len(issue_rows),
        "selection_row_count": len(selection_rows),
        "issue_sha256": issue_hash,
        "selection_sha256": selection_hash,
        "selection_status_counts": dict(
            sorted(Counter(row["selection_status"] for row in selection_rows).items())
        ),
        "issue_count_per_day": dict(
            sorted(Counter(row["issue_count_for_target_day"] for row in issue_rows).items())
        ),
    }
    atomic_write_json(paths["manifest"], manifest, replace=True)
    return manifest


def _merge_checkpoints(root: Path, run_id: str, years: Sequence[int]) -> dict[str, Any]:
    issue_tables = []
    selection_tables = []
    checkpoint_manifests = []
    for year in years:
        manifest = _valid_checkpoint(root, run_id, year)
        if manifest is None:
            raise ContractError(f"P03 year checkpoint is missing or stale: {year}")
        paths = _checkpoint_paths(root, run_id, year)
        # Read the physical file directly. ``pq.read_table`` invokes the
        # dataset layer and would synthesize a Hive partition column from the
        # checkpoint directory name (for example ``year=2021``).
        issue_tables.append(pq.ParquetFile(paths["issue"]).read())
        selection_tables.append(pq.ParquetFile(paths["selection"]).read())
        checkpoint_manifests.append(manifest)
    issue_table = pa.concat_tables(issue_tables)
    selection_table = pa.concat_tables(selection_tables)
    issue_sink = pa.BufferOutputStream()
    pq.write_table(
        issue_table,
        issue_sink,
        compression="zstd",
        version="2.6",
        write_statistics=True,
        row_group_size=65536,
    )
    selection_sink = pa.BufferOutputStream()
    pq.write_table(
        selection_table,
        selection_sink,
        compression="zstd",
        version="2.6",
        write_statistics=True,
        row_group_size=65536,
    )
    issue_hash = atomic_write_bytes(
        root / ISSUE_OUTPUT_PATH, issue_sink.getvalue().to_pybytes(), replace=True
    )
    selection_hash = atomic_write_bytes(
        root / SELECTION_OUTPUT_PATH,
        selection_sink.getvalue().to_pybytes(),
        replace=True,
    )
    return {
        "issue_hash": issue_hash,
        "selection_hash": selection_hash,
        "issue_rows": issue_table.num_rows,
        "selection_rows": selection_table.num_rows,
        "checkpoints": checkpoint_manifests,
    }


def _validate_outputs(root: Path, *, verify_pass_record: bool) -> dict[str, Any]:
    predecessor = _predecessor(root)
    config = _load_config(root)
    contract = load_issue_view_contract(root)
    authority = _schedule_authority(root, contract)
    if verify_pass_record:
        record = verify_prefit_pass(root, 3)
        if record["predecessor_hashes"].get("PREFIT_P02") != predecessor["record_sha256"]:
            raise StaleStateError("P03 predecessor link changed")
    issue_path = root / ISSUE_OUTPUT_PATH
    selection_path = root / SELECTION_OUTPUT_PATH
    manifest = _read_json(root / MANIFEST_PATH)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ContractError("unsupported P03 selection manifest schema")
    if (
        manifest.get("issue_spine", {}).get("sha256") != sha256_file(issue_path)
        or manifest.get("selected_cycles", {}).get("sha256") != sha256_file(selection_path)
    ):
        raise StaleStateError("P03 output hash mismatch")
    issue_table = pq.read_table(issue_path)
    selection_table = pq.read_table(selection_path)
    if issue_table.schema != issue_spine_schema():
        raise ContractError("issue-spine schema mismatch")
    if selection_table.schema != selected_cycles_schema():
        raise ContractError("selected-cycles schema mismatch")
    if issue_table.num_rows != EXPECTED_ISSUE_ROWS:
        raise ContractError("issue-spine row count mismatch")
    if selection_table.num_rows != EXPECTED_SELECTION_ROWS:
        raise ContractError("selected-cycles row count mismatch")
    issues = issue_table.to_pylist()
    selections = selection_table.to_pylist()
    issue_ids = [row["issue_state_id"] for row in issues]
    if len(issue_ids) != len(set(issue_ids)):
        raise ContractError("issue_state_id is not unique")
    natural_keys = [(row["target_date"], row["issue_time_utc"]) for row in issues]
    if natural_keys != sorted(natural_keys) or len(natural_keys) != len(set(natural_keys)):
        raise ContractError("issue-spine natural keys are unsorted or duplicated")
    timezone = ZoneInfo(str(config["issue_grid"]["timezone"]))
    rows_by_target: dict[date, list[dict[str, Any]]] = {}
    for row in issues:
        rows_by_target.setdefault(row["target_date"], []).append(row)
        if row["issue_time_utc"].astimezone(timezone).date() != row["target_date"]:
            raise ContractError("issue time does not belong to its target local date")
        if row["target_window_end_utc"] - row["target_window_start_utc"] != timedelta(days=1):
            raise ContractError("target window is not a 24-hour right-open support")
        if issue_state_id(row["target_date"], row["issue_time_utc"]) != row[
            "issue_state_id"
        ]:
            raise ContractError("issue_state_id does not match its natural key")
    expected_targets = list(_inclusive_dates(STUDY_START, STUDY_END))
    if list(rows_by_target) != expected_targets:
        raise ContractError("issue-spine target-date coverage changed")
    for target, target_rows in rows_by_target.items():
        expected_rows = _issue_rows_for_day(target, config)
        exact_columns = (
            "issue_state_id",
            "issue_time_utc",
            "issue_time_local",
            "local_utc_offset_minutes",
            "local_dst_flag",
            "local_fold",
            "local_issue_hour",
            "local_issue_minute",
            "local_minutes_since_0200",
            "issue_ordinal_in_target_day",
            "issue_count_for_target_day",
            "target_window_start_utc",
            "target_window_end_utc",
        )
        if len(target_rows) != len(expected_rows) or any(
            observed[column] != expected[column]
            for observed, expected in zip(target_rows, expected_rows, strict=True)
            for column in exact_columns
        ):
            raise ContractError(f"issue grid or clock metadata changed: {target}")
    selection_keys = [(row["issue_state_id"], row["product"]) for row in selections]
    issue_position = {value: index for index, value in enumerate(issue_ids)}
    expected_selection_order = sorted(
        selection_keys,
        key=lambda value: (issue_position[value[0]], PRODUCT_ORDER.index(value[1])),
    )
    if selection_keys != expected_selection_order:
        raise ContractError("selected-cycle rows are not deterministically ordered")
    if len(selection_keys) != len(set(selection_keys)):
        raise ContractError("selected-cycle primary key is duplicated")
    by_issue = Counter(row["issue_state_id"] for row in selections)
    if set(by_issue) != set(issue_ids) or set(by_issue.values()) != {2}:
        raise ContractError("every issue state must have exactly two product selections")
    missing = Counter(row["selection_status"] for row in selections)
    if missing != {"SELECTED": EXPECTED_SELECTION_ROWS}:
        raise ContractError(f"P03 has unresolved product selections: {dict(missing)}")
    issue_by_id = {row["issue_state_id"]: row for row in issues}
    schedule_reader = R14ArchiveReader(root, verify_acquisition=True)
    verified_paths: set[str] = set()
    for row in selections:
        issue_row = issue_by_id[row["issue_state_id"]]
        if (
            row["target_date"] != issue_row["target_date"]
            or row["issue_time_utc"] != issue_row["issue_time_utc"]
        ):
            raise ContractError("selected-cycle row disagrees with its issue spine row")
        issue_utc = as_utc(row["issue_time_utc"])
        cycle = as_utc(row["cycle_init_utc"])
        complete = as_utc(row["emulated_complete_time_utc"])
        previous_cycle = as_utc(row["previous_cycle_init_utc"])
        previous_complete = as_utc(row["previous_emulated_complete_time_utc"])
        expected, expected_previous = select_newest_legal_cycle(
            schedule_reader.schedule_rows(row["target_date"], row["product"]),
            issue_utc,
        )
        if expected_previous is None:
            raise ContractError("selected cycle lacks the required previous legal cycle")
        expected_cycle = as_utc(expected["cycle_init_utc"])
        expected_previous_cycle = as_utc(expected_previous["cycle_init_utc"])
        if cycle != expected_cycle or previous_cycle != expected_previous_cycle:
            raise ContractError("selected cycle is not the newest legal schedule state")
        if (
            complete != as_utc(expected["emulated_complete_time_utc"])
            or previous_complete
            != as_utc(expected_previous["emulated_complete_time_utc"])
            or row["retained_valid_start_utc"]
            != as_utc(expected["retained_valid_start_utc"])
            or row["retained_valid_end_utc"]
            != as_utc(expected["retained_valid_end_utc"])
            or row["previous_retained_valid_start_utc"]
            != as_utc(expected_previous["retained_valid_start_utc"])
            or row["previous_retained_valid_end_utc"]
            != as_utc(expected_previous["retained_valid_end_utc"])
        ):
            raise ContractError("selected-cycle clocks or retained support changed")
        if (
            row["availability_policy_id"] != contract["availability"]["policy_id"]
            or row["availability_basis"] != AVAILABILITY_BASIS
            or row["source_schedule_id"] != authority["schedule_id"]
        ):
            raise ContractError("selected-cycle schedule provenance changed")
        if row["source_schedule_row_id"] != schedule_row_id(
            row["target_date"], row["product"], cycle
        ) or row["previous_source_schedule_row_id"] != schedule_row_id(
            row["target_date"], row["product"], previous_cycle
        ):
            raise ContractError("selected-cycle schedule row identity changed")
        if row["trajectory_bundle_id"] != trajectory_bundle_id(
            row["target_date"], row["product"], cycle
        ) or row["previous_trajectory_bundle_id"] != trajectory_bundle_id(
            row["target_date"], row["product"], previous_cycle
        ):
            raise ContractError("selected-cycle trajectory identity changed")
        if row["trajectory_bundle_path"] != _bundle_path(
            contract, row["target_date"], row["product"], cycle
        ) or row["previous_trajectory_bundle_path"] != _bundle_path(
            contract, row["target_date"], row["product"], previous_cycle
        ):
            raise ContractError("selected-cycle trajectory path changed")
        if not (
            previous_cycle < cycle
            and previous_complete <= issue_utc
            and complete <= issue_utc
        ):
            raise ContractError("selected cycle violates causal or predecessor ordering")
        if (
            row["cycle_age_minutes"] != _minutes(issue_utc, cycle)
            or row["availability_age_minutes"] != _minutes(issue_utc, complete)
            or row["previous_cycle_age_minutes"] != _minutes(issue_utc, previous_cycle)
            or row["previous_availability_age_minutes"]
            != _minutes(issue_utc, previous_complete)
        ):
            raise ContractError("selected-cycle age columns do not match their clocks")
        if (
            row["availability_age_minutes"] < 0
            or row["previous_availability_age_minutes"] < 0
        ):
            raise ContractError("selected cycle has a negative availability age")
        window_end = datetime.combine(
            row["target_date"] + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=7)
        if row["retained_valid_end_utc"] > window_end:
            raise ContractError("selected cycle retains post-window source state")
        if row["previous_retained_valid_end_utc"] > window_end:
            raise ContractError("previous cycle retains post-window source state")
        if not row["trajectory_bundle_present"]:
            raise ContractError("selected trajectory bundle is absent")
        if not row["previous_trajectory_bundle_present"]:
            raise ContractError("previous legal-cycle trajectory bundle is absent")
        for path_key in ("trajectory_bundle_path", "previous_trajectory_bundle_path"):
            relative = str(row[path_key])
            if Path(relative).is_absolute():
                raise ContractError(f"selected trajectory link is invalid: {relative}")
            if relative not in verified_paths:
                if not (root / relative).is_file():
                    raise ContractError(f"selected trajectory link is invalid: {relative}")
                verified_paths.add(relative)
    observed_issue_counts = Counter(
        Counter(row["target_date"] for row in issues).values()
    )
    if observed_issue_counts != {57: 2074, 53: 6}:
        raise ContractError(f"unexpected DST issue-count distribution: {observed_issue_counts}")
    spring_days = [
        target.isoformat()
        for target, target_rows in rows_by_target.items()
        if len(target_rows) == 53
    ]
    observed_year_counts = Counter(row["target_date"].year for row in issues)
    expected_manifest_values = {
        "status": "PASS_CANDIDATE",
        "predecessor_p02_record_sha256": predecessor["record_sha256"],
        "issue_grid_contract_id": ISSUE_GRID_ID,
        "availability_policy_id": contract["availability"]["policy_id"],
        "product_selection_policy": "independent_by_product",
        "source_schedule": authority,
        "target_day_count": EXPECTED_TARGET_DAYS,
        "issue_rows_by_target_year": {
            str(year): count for year, count in sorted(observed_year_counts.items())
        },
        "issue_count_per_target_day_distribution": {
            str(count): frequency
            for count, frequency in sorted(observed_issue_counts.items())
        },
        "spring_forward_target_days": spring_days,
        "selection_status_counts": {"SELECTED": EXPECTED_SELECTION_ROWS},
        "current_cycle_missing_count": 0,
        "previous_cycle_missing_count": 0,
        "trajectory_bundle_missing_count": 0,
        "truth_or_weather_values_materialized": False,
    }
    for key, expected_value in expected_manifest_values.items():
        if manifest.get(key) != expected_value:
            raise ContractError(f"P03 selection manifest changed: {key}")
    if (
        manifest.get("issue_spine", {}).get("path") != ISSUE_OUTPUT_PATH
        or manifest.get("issue_spine", {}).get("rows") != EXPECTED_ISSUE_ROWS
        or manifest.get("issue_spine", {}).get("schema_id") != ISSUE_SCHEMA_ID
        or manifest.get("selected_cycles", {}).get("path") != SELECTION_OUTPUT_PATH
        or manifest.get("selected_cycles", {}).get("rows") != EXPECTED_SELECTION_ROWS
        or manifest.get("selected_cycles", {}).get("schema_id") != SELECTION_SCHEMA_ID
    ):
        raise ContractError("P03 selection manifest output identity changed")
    isolation = validate_runtime_isolation(root)
    return {
        "predecessor_record_sha256": predecessor["record_sha256"],
        "schedule": authority,
        "issue_state_count": len(issues),
        "selected_cycle_row_count": len(selections),
        "target_day_count": len({row["target_date"] for row in issues}),
        "issue_rows_per_target_day": dict(sorted(observed_issue_counts.items())),
        "spring_forward_target_days": spring_days,
        "selection_status_counts": dict(sorted(missing.items())),
        "current_cycle_missing_count": 0,
        "previous_cycle_missing_count": 0,
        "trajectory_bundle_missing_count": 0,
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "weather_value_rows_read": 0,
        "runtime_isolation": {
            key: value for key, value in isolation.items() if key != "source_files_scanned"
        },
    }


def _publish_manifest_and_report(
    root: Path,
    run_id: str,
    merged: Mapping[str, Any],
    authority: Mapping[str, Any],
    predecessor: Mapping[str, Any],
) -> dict[str, Any]:
    issue_table = pq.read_table(root / ISSUE_OUTPUT_PATH, columns=["target_date"])
    target_counts = Counter(issue_table.column("target_date").to_pylist())
    spring_days = [
        target.isoformat()
        for target, count in sorted(target_counts.items())
        if count == 53
    ]
    year_counts = Counter(target.year for target in issue_table.column("target_date").to_pylist())
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "status": "PASS_CANDIDATE",
        "run_id": run_id,
        "created_at_utc": _read_json(_run_paths(root, run_id)["state"])["created_at_utc"],
        "scope_id": "KDEN_V375_R14_V1",
        "substrate_release_id": "KDEN_V375_UNIVERSAL_ISSUE_STATE_V1",
        "predecessor_p02_record_sha256": predecessor["record_sha256"],
        "issue_grid_contract_id": ISSUE_GRID_ID,
        "availability_policy_id": "KDEN_HIST_COMPLETE_L105_V1",
        "product_selection_policy": "independent_by_product",
        "source_schedule": dict(authority),
        "issue_spine": {
            "path": ISSUE_OUTPUT_PATH,
            "schema_id": ISSUE_SCHEMA_ID,
            "rows": merged["issue_rows"],
            "sha256": merged["issue_hash"],
        },
        "selected_cycles": {
            "path": SELECTION_OUTPUT_PATH,
            "schema_id": SELECTION_SCHEMA_ID,
            "rows": merged["selection_rows"],
            "sha256": merged["selection_hash"],
        },
        "target_day_count": len(target_counts),
        "issue_rows_by_target_year": {
            str(year): count for year, count in sorted(year_counts.items())
        },
        "issue_count_per_target_day_distribution": {
            str(count): frequency
            for count, frequency in sorted(Counter(target_counts.values()).items())
        },
        "spring_forward_target_days": spring_days,
        "selection_status_counts": {"SELECTED": merged["selection_rows"]},
        "current_cycle_missing_count": 0,
        "previous_cycle_missing_count": 0,
        "trajectory_bundle_missing_count": 0,
        "truth_or_weather_values_materialized": False,
    }
    atomic_write_json(root / MANIFEST_PATH, manifest, replace=True)
    report = f"""# P03 Issue-Spine, Cycle-Selection, and DST Report

Status: PASS candidate for `KDEN_V375_UNIVERSAL_ISSUE_STATE_V1`

## Exact coverage

- Target days: {manifest['target_day_count']}
- Issue states: {merged['issue_rows']}
- Independently selected product rows: {merged['selection_rows']}
- Products per issue state: 2 (`wrfsfcf`, `wrfsubhf`)
- Missing current cycles: 0
- Missing previous legal cycles: 0
- Missing linked trajectory bundles: 0

## DST result

Ordinary target days contribute 57 issue states from 02:00 through 16:00
America/Denver at 15-minute cadence. The six spring-forward dates contribute
53 because 02:00, 02:15, 02:30, and 02:45 do not exist locally:

{chr(10).join(f'- {value}' for value in spring_days)}

This is why the exact issue-state count is 118,536 rather than 118,560.

## Causality and isolation

Every selected cycle satisfies `emulated_complete_time_utc <= issue_time_utc`
under `KDEN_HIST_COMPLETE_L105_V1`. Hourly and Q05 selection was performed
independently. Every row preserves the immediately previous legal same-product
cycle and links current and previous cycles to frozen R14 trajectory bundles.
No truth rows, market rows, MADIS rows, or weather-value rows were read or
materialized by P03.
"""
    atomic_write_bytes(root / REPORT_PATH, report.encode("utf-8"), replace=True)
    return manifest


def run_p03(
    *, project_root: Path | str, run_id: str, resume: bool = False
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if (root / PASS_PATH).is_file():
        return verify_p03(root)
    predecessor = _predecessor(root)
    config = _load_config(root)
    contract = load_issue_view_contract(root)
    authority = _schedule_authority(root, contract)
    state = _initialize_state(root, run_id)
    resumable = {"INITIALIZED", "PAUSED", "PAUSE_REQUESTED", "FAILED"}
    if resume and state["status"] not in resumable:
        raise ContractError(f"P03 run is not resumable from {state['status']}")
    if not resume and state["status"] not in {"INITIALIZED", "FAILED"}:
        raise ContractError(f"P03 run already exists in {state['status']}; use resume-p03")
    paths = _run_paths(root, run_id)
    pause = PauseController(paths["pause"])
    if resume:
        pause.clear()
    years = tuple(range(STUDY_START.year, STUDY_END.year + 1))
    with ExclusiveRunLock(load_project_paths(root).state / "PREFIT_P03.lock"):
        pause.install()
        _update_state(
            root,
            run_id,
            status="RUNNING",
            phase="BUILD_YEAR_CHECKPOINTS",
            started_at_utc=state.get("started_at_utc") or utc_now(),
            message="resumed" if resume else "started",
        )
        try:
            reader = R14ArchiveReader(root, verify_acquisition=True)
            completed_days = 0
            checkpoint_issue_states = 0
            checkpoint_selection_rows = 0
            completed_years: list[int] = []
            for year in years:
                pause.raise_if_requested()
                existing = _valid_checkpoint(root, run_id, year)
                if existing is None:
                    _update_state(
                        root,
                        run_id,
                        checkpoint_issue_states=checkpoint_issue_states,
                        checkpoint_selection_rows=checkpoint_selection_rows,
                        current_target_date=f"{year:04d}-01-01",
                        message=f"building year {year}",
                    )
                    existing = _build_year(
                        root=root,
                        run_id=run_id,
                        year=year,
                        reader=reader,
                        config=config,
                        contract=contract,
                        authority=authority,
                        pause=pause,
                        completed_before=completed_days,
                    )
                completed_days += int(existing["target_day_count"])
                checkpoint_issue_states += int(existing["issue_row_count"])
                checkpoint_selection_rows += int(existing["selection_row_count"])
                completed_years.append(year)
                _update_state(
                    root,
                    run_id,
                    completed_target_days=completed_days,
                    completed_issue_states=checkpoint_issue_states,
                    completed_selection_rows=checkpoint_selection_rows,
                    completed_years=completed_years,
                    checkpoint_issue_states=checkpoint_issue_states,
                    checkpoint_selection_rows=checkpoint_selection_rows,
                    current_target_date=None,
                )
            pause.raise_if_requested()
            _update_state(
                root,
                run_id,
                phase="MERGE_AND_VALIDATE",
                message="merging year checkpoints and validating causal contracts",
            )
            merged = _merge_checkpoints(root, run_id, years)
            _publish_manifest_and_report(
                root, run_id, merged, authority, predecessor
            )
            evidence = _validate_outputs(root, verify_pass_record=False)
            record = write_prefit_pass(
                root,
                stage_no=3,
                run_id=run_id,
                artifact_paths=[
                    CONFIG_PATH,
                    ISSUE_SCHEMA_PATH,
                    SELECTION_SCHEMA_PATH,
                    MANIFEST_SCHEMA_PATH,
                    RUN_STATE_SCHEMA_PATH,
                    RUNBOOK_PATH,
                    REPORT_PATH,
                    "src/kden_v375/prefit/p03_issue_spine.py",
                    "universal_issue_state/v1/issue_spine",
                    "universal_issue_state/v1/selected_cycles",
                    MANIFEST_PATH,
                ],
                predecessor_hashes={"PREFIT_P02": predecessor["record_sha256"]},
                authority_hashes={
                    "R14_CYCLE_SCHEDULE": authority["schedule_sha256"],
                    "R14_CYCLE_SCHEDULE_MANIFEST": authority["schedule_manifest_sha256"],
                    "ISSUE_SPINE": merged["issue_hash"],
                    "SELECTED_CYCLES": merged["selection_hash"],
                },
                gate_evidence=evidence,
            )
        except PauseRequested as exc:
            _update_state(root, run_id, status="PAUSED", message=str(exc))
            return {"run_id": run_id, "stage_id": "PREFIT_P03", "status": "PAUSED"}
        except Exception as exc:
            _update_state(
                root,
                run_id,
                status="FAILED",
                message=f"{type(exc).__name__}: {exc}",
            )
            raise
        else:
            pause.clear()
            _update_state(
                root,
                run_id,
                status="PASS",
                phase="COMPLETE",
                message="P03 gate passed",
                completed_at_utc=utc_now(),
                record_sha256=record["record_sha256"],
            )
            return record
        finally:
            pause.restore()


def p03_eta(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state = _read_json(_run_paths(root, run_id)["state"])
    eta: dict[str, Any] = {"status": "UNAVAILABLE", "reason": "insufficient progress"}
    if state["status"] == "PASS":
        eta = {"status": "COMPLETE", "remaining_seconds": 0}
    elif state["status"] in {"FAILED", "PAUSED", "PAUSE_REQUESTED"}:
        eta = {"status": "UNAVAILABLE", "reason": f"run is {state['status']}"}
    elif state.get("started_at_utc") and state.get("completed_target_days", 0):
        elapsed = max(
            0.001,
            (datetime.now(UTC) - _parse_utc(str(state["started_at_utc"]))).total_seconds(),
        )
        rate = state["completed_target_days"] / elapsed
        remaining = max(0, state["expected_target_days"] - state["completed_target_days"])
        eta = {
            "status": "AVAILABLE",
            "basis": "target_days_since_run_start",
            "recent_rate_target_days_per_second": rate,
            "remaining_target_days": remaining,
            "remaining_seconds": remaining / rate if rate else None,
            "note": "final merge and validation time are not included",
        }
    return {
        "schema_version": "KDEN_V375_PREFIT_P03_ETA_V1",
        "run_id": run_id,
        "observed_at_utc": utc_now(),
        "run_status": state["status"],
        "phase": state["phase"],
        "eta": eta,
    }


def p03_status(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_prefit_run_id(run_id, stage_no=3)
    state = _read_json(_run_paths(root, run_id)["state"])
    return {
        **state,
        "issue_spine_path": ISSUE_OUTPUT_PATH,
        "selected_cycles_path": SELECTION_OUTPUT_PATH,
        "eta": p03_eta(root, run_id)["eta"],
    }


def p03_pause(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = _run_paths(root, run_id)
    state = _read_json(paths["state"])
    if state["status"] != "RUNNING":
        raise ContractError(f"P03 run is not running: {state['status']}")
    atomic_write_json(
        paths["pause"],
        {"schema_version": "KDEN_V375_PAUSE_REQUEST_V1", "requested_at_utc": utc_now()},
        replace=True,
    )
    return _update_state(
        root,
        run_id,
        status="PAUSE_REQUESTED",
        message="cooperative pause requested",
    )


def p03_live_status(
    project_root: Path | str,
    run_id: str,
    *,
    interval_seconds: float = 5,
    json_lines: bool = False,
) -> None:
    if interval_seconds <= 0:
        raise ContractError("live-status interval must be positive")
    while True:
        snapshot = p03_status(project_root, run_id)
        if json_lines:
            print(json.dumps(snapshot, sort_keys=True), flush=True)
        else:
            eta = snapshot["eta"]
            eta_text = "unavailable"
            if eta.get("status") == "AVAILABLE" and eta.get("remaining_seconds") is not None:
                eta_text = f"{eta['remaining_seconds'] / 60:.1f}m"
            elif eta.get("status") == "COMPLETE":
                eta_text = "complete"
            print(
                f"[{utc_now()}] | {snapshot['status']} | phase={snapshot['phase']} | "
                f"days={snapshot['completed_target_days']}/{snapshot['expected_target_days']} | "
                f"issues={snapshot['completed_issue_states']}/"
                f"{snapshot['expected_issue_states']} | "
                f"selections={snapshot['completed_selection_rows']}/"
                f"{snapshot['expected_selection_rows']} | ETA={eta_text} | "
                f"day={snapshot.get('current_target_date') or '-'}",
                flush=True,
            )
        if snapshot["status"] in {"PASS", "FAILED", "PAUSED"}:
            return
        time.sleep(interval_seconds)


def verify_p03(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    record = verify_prefit_pass(root, 3)
    evidence = _validate_outputs(root, verify_pass_record=False)
    if record["predecessor_hashes"].get("PREFIT_P02") != evidence[
        "predecessor_record_sha256"
    ]:
        raise StaleStateError("P03 predecessor record does not match P02")
    return {
        "status": "VALID",
        "validated_stage": "PREFIT_P03",
        "record_sha256": record["record_sha256"],
        "issue_spine_path": ISSUE_OUTPUT_PATH,
        "selected_cycles_path": SELECTION_OUTPUT_PATH,
        "issue_state_count": evidence["issue_state_count"],
        "selected_cycle_row_count": evidence["selected_cycle_row_count"],
        "target_day_count": evidence["target_day_count"],
        "issue_rows_per_target_day": evidence["issue_rows_per_target_day"],
        "spring_forward_target_days": evidence["spring_forward_target_days"],
        "selection_status_counts": evidence["selection_status_counts"],
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "weather_value_rows_read": 0,
        "runtime_isolation": evidence["runtime_isolation"],
    }
