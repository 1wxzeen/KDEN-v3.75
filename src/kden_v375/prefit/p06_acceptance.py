"""P06: deep acceptance and immutable freeze of the universal issue-state release."""

from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time as daytime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..archive_readers import R14ArchiveReader
from ..contracts import (
    ContractError,
    ExclusiveRunLock,
    PauseController,
    PauseRequested,
    StaleStateError,
    load_project_paths,
    validate_runtime_isolation,
)
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from ..io.atomic import atomic_write_json, fsync_directory
from ..time import as_utc
from .p03_issue_spine import (
    AVAILABILITY_BASIS,
    ISSUE_GRID_ID,
    ISSUE_OUTPUT_PATH,
    PRODUCT_ORDER,
    SELECTION_OUTPUT_PATH,
    issue_spine_schema,
    issue_state_id,
    selected_cycles_schema,
)
from .p04_features import (
    DERIVATION_ID,
    DYNAMIC_FIELDS,
    FIELD_PRODUCT,
    FIELD_UNITS,
    LOCAL_VALUE_COLUMN,
    PANEL_SCHEMA_ID,
    REGIONAL_FIELDS,
    REGISTRY_ID,
    REGISTRY_PATH,
    TILE_FIELDS,
    _case_rows,
    _validate_range,
    compute_issue_feature_row,
    feature_panel_schema,
)
from .p05_materialization import (
    EXPECTED_DYNAMIC_MISSING_TRAJECTORY_ROWS,
    EXPECTED_DYNAMIC_TRAJECTORY_ROWS,
    EXPECTED_FEATURE_ROWS,
    EXPECTED_STATIC_TRAJECTORY_ROWS,
    EXPECTED_TRAJECTORY_ROWS,
    RELEASE_INDEX_PATH,
    RELEASE_MANIFEST_PATH,
    STATIC_TRAJECTORY_PATH,
    SUBSTRATE_RELEASE_ID,
    TARGET_YEARS,
    _load_feature_authority,
    _load_field_contracts,
    time_support_id,
    trajectory_catalog_schema,
    trajectory_state_id,
)
from .records import (
    PREFIT_PASS_SCHEMA_VERSION,
    make_prefit_run_id,
    publish_immutable_json,
    utc_now,
    validate_prefit_run_id,
    verify_prefit_pass,
    write_prefit_pass,
)


STAGE_NO = 6
CONFIG_PATH = "config/prefit/p06_acceptance_v375.json"
FEATURE_ERRATA_PATH = "config/prefit/p06_feature_contract_errata_v375.json"
RUN_STATE_SCHEMA_PATH = "schemas/prefit/p06_run_state_v375.json"
FREEZE_SCHEMA_PATH = "schemas/prefit/p06_freeze_manifest_v375.json"
FINAL_PASS_SCHEMA_PATH = "schemas/prefit/universal_issue_state_pass_v375.json"
FEATURE_ERRATA_SCHEMA_PATH = "schemas/prefit/p06_feature_contract_errata_v375.json"
RUNBOOK_PATH = "reports/prefit/P06_OWNER_RUNBOOK.md"
REPORT_PATH = "reports/prefit/P06_SUBSTRATE_ACCEPTANCE_REPORT.md"
FREEZE_PATH = "universal_issue_state/v1/manifests/p06_substrate_freeze_manifest.json"
FINAL_PASS_PATH = "state/KDEN_V375_UNIVERSAL_ISSUE_STATE_PASS.json"
PASS_PATH = "state/PREFIT_P06_PASS.json"

CONFIG_SCHEMA = "KDEN_V375_PREFIT_P06_CONFIG_V1"
FEATURE_ERRATA_SCHEMA = "KDEN_V375_P06_FEATURE_CONTRACT_ERRATA_V1"
FEATURE_ERRATA_ID = "KDEN_V375_P06_FEATURE_RANGE_ERRATA_V1"
RUN_STATE_SCHEMA = "KDEN_V375_PREFIT_P06_RUN_V1"
CHECKPOINT_SCHEMA = "KDEN_V375_PREFIT_P06_CHECKPOINT_V1"
JOURNAL_SCHEMA = "KDEN_V375_PREFIT_P06_COMPLETION_V1"
FREEZE_SCHEMA = "KDEN_V375_SUBSTRATE_FREEZE_MANIFEST_V1"
FINAL_PASS_SCHEMA = "KDEN_V375_UNIVERSAL_ISSUE_STATE_PASS_V1"
ACCEPTANCE_ID = "KDEN_V375_UNIVERSAL_ISSUE_STATE_ACCEPTANCE_V1"
EXPECTED_P05_SHA256 = "7e1366d32972aa492ae1064c354bfb0261401f59a16e16a26e12a65df96c4132"
EXPECTED_TARGET_DAYS = 2_080
EXPECTED_ISSUE_ROWS = 118_536
EXPECTED_SELECTION_ROWS = 237_072
EXPECTED_FEATURE_COUNT = 433
EXPECTED_SCHEDULE_ROWS = 66_558
ISSUE_VIEW_CONTRACT_PATH = "config/issue_time_views_r14_v375.json"
STUDY_START = date(2021, 1, 1)
STUDY_END = date(2026, 9, 11)
DENVER = ZoneInfo("America/Denver")
ACCEPTANCE_UNITS = (
    "issue-spine",
    "selected-cycles",
    "static-h14",
    *(f"target-year-{year}" for year in TARGET_YEARS),
    "anchor-rebuilds",
)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ContractError(f"JSON object expected: {path}")
    return value


def _inside(root: Path, relative: str | Path) -> Path:
    candidate = (root / Path(relative)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ContractError(f"P06 path escapes project root: {relative}") from exc
    return candidate


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _valid_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _load_config(root: Path) -> dict[str, Any]:
    config = _read_json(root / CONFIG_PATH)
    execution = config.get("execution", {})
    expected_execution = {
        "network_allowed": False,
        "truth_reads_allowed": False,
        "market_reads_allowed": False,
        "madis_reads_allowed": False,
        "model_fitting_allowed": False,
        "owner_run_required": True,
        "pause_boundary": "between scan batches; an incomplete year is discarded and rescanned on resume",
        "resume_revalidates_checkpoint_authorities": True,
    }
    expected_issue_grid = {
        "contract_id": ISSUE_GRID_ID,
        "local_timezone": "America/Denver",
        "first_local_time": "02:00",
        "last_local_time": "16:00",
        "spacing_minutes": 15,
        "ordinary_issue_count": 57,
        "spring_forward_issue_count": 53,
        "target_window": "[07:00Z_d,07:00Z_d_plus_1)",
    }
    expected_availability = {
        "policy_id": "KDEN_HIST_COMPLETE_L105_V1",
        "basis": AVAILABILITY_BASIS,
        "cycle_complete_lag_minutes": 105,
        "future_complete_cycle_allowed": False,
    }
    expected_eras = [
        {"start_date": "2021-01-01", "end_date": "2021-11-21", "era": "KDEN_COORD_20040105"},
        {"start_date": "2021-11-22", "end_date": "2026-09-11", "era": "KDEN_COORD_20211122"},
    ]
    expected_anchors = [
        {"case_id": "ordinary", "target_date": "2023-07-15", "issue_local": "09:00"},
        {"case_id": "dst_spring_forward", "target_date": "2023-03-12", "issue_local": "09:00"},
        {"case_id": "confirmed_remote_missing", "target_date": "2022-02-26", "issue_local": "12:45"},
        {"case_id": "snow", "target_date": "2024-01-15", "issue_local": "09:00"},
        {"case_id": "convective", "target_date": "2023-06-22", "issue_local": "09:00"},
        {"case_id": "dry_heating", "target_date": "2023-07-15", "issue_local": "09:00"},
        {"case_id": "mixing_downslope", "target_date": "2024-12-15", "issue_local": "09:00"},
    ]
    expected_forbidden = [
        "truth", "y_audited", "target_value", "market", "kalshi", "settlement",
        "madis", "outcome", "label", "fold", "prediction",
    ]
    if (
        config.get("schema_version") != CONFIG_SCHEMA
        or config.get("acceptance_id") != ACCEPTANCE_ID
        or config.get("substrate_release_id") != SUBSTRATE_RELEASE_ID
        or config.get("predecessor_p05_record_sha256") != EXPECTED_P05_SHA256
        or config.get("feature_contract_errata_path") != FEATURE_ERRATA_PATH
        or config.get("study_start_date") != STUDY_START.isoformat()
        or config.get("study_end_date") != STUDY_END.isoformat()
        or config.get("expected_target_days") != EXPECTED_TARGET_DAYS
        or config.get("expected_issue_rows") != EXPECTED_ISSUE_ROWS
        or config.get("expected_selection_rows") != EXPECTED_SELECTION_ROWS
        or config.get("expected_feature_rows") != EXPECTED_FEATURE_ROWS
        or config.get("expected_feature_count") != EXPECTED_FEATURE_COUNT
        or config.get("expected_dynamic_trajectory_rows") != EXPECTED_DYNAMIC_TRAJECTORY_ROWS
        or config.get("expected_static_trajectory_rows") != EXPECTED_STATIC_TRAJECTORY_ROWS
        or config.get("expected_total_trajectory_rows") != EXPECTED_TRAJECTORY_ROWS
        or config.get("expected_missing_trajectory_rows") != EXPECTED_DYNAMIC_MISSING_TRAJECTORY_ROWS
        or config.get("target_years") != list(TARGET_YEARS)
        or config.get("issue_grid") != expected_issue_grid
        or config.get("availability") != expected_availability
        or config.get("coordinate_eras") != expected_eras
        or config.get("anchor_cases") != expected_anchors
        or config.get("forbidden_predictor_tokens") != expected_forbidden
        or execution != expected_execution
        or config.get("freeze") != {
            "manifest_path": FREEZE_PATH,
            "final_pass_path": FINAL_PASS_PATH,
            "status_after_pass": "FROZEN_ACCEPTED",
        }
    ):
        raise ContractError("P06 acceptance configuration identity changed")
    return config


def _load_feature_range_errata(
    root: Path,
    *,
    registry_hash: str,
    features: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Load the narrow P06-only range overlay without modifying P04 or P05."""

    value = _read_json(root / FEATURE_ERRATA_PATH)
    expected_policy = (
        "P04 and P05 remain byte-immutable; P06 applies these acceptance-only "
        "bounds and freezes this overlay with the release"
    )
    expected_entries = [
        {
            "feature_name": "support_wrfsfcf_retained_start_offset_minutes",
            "declared_range": [0, 1440],
            "accepted_range": [-60, 1440],
            "observed_range": [-60, 840],
            "reason": (
                "The frozen DST-safe R14 schedule can retain a selected current "
                "cycle beginning one hour before the fixed 07Z target-window start."
            ),
        },
        {
            "feature_name": "support_wrfsubhf_retained_start_offset_minutes",
            "declared_range": [0, 1440],
            "accepted_range": [-60, 1440],
            "observed_range": [-60, 840],
            "reason": (
                "The frozen DST-safe R14 schedule can retain a selected current "
                "cycle beginning one hour before the fixed 07Z target-window start."
            ),
        },
        {
            "feature_name": "derived_dewpoint_depression_future_first_k",
            "declared_range": [0.0, 100.0],
            "accepted_range": [-0.05, 100.0],
            "observed_range": [-0.022247314453125, 48.628129088571654],
            "reason": (
                "Independent spatial interpolation of temperature and dewpoint can "
                "produce a numerically tiny negative difference; raw values remain "
                "unchanged and the tolerance is bounded to 0.05 K."
            ),
        },
    ]
    if value != {
        "schema_version": FEATURE_ERRATA_SCHEMA,
        "errata_id": FEATURE_ERRATA_ID,
        "registry_id": REGISTRY_ID,
        "registry_sha256": registry_hash,
        "policy": expected_policy,
        "entries": expected_entries,
    }:
        raise ContractError("P06 feature-range errata identity changed")

    features_by_name = {str(feature["name"]): feature for feature in features}
    entries: dict[str, dict[str, Any]] = {}
    for entry in expected_entries:
        name = str(entry["feature_name"])
        feature = features_by_name.get(name)
        if feature is None or feature.get("physical_range") != entry["declared_range"]:
            raise ContractError(f"P06 erratum does not match the frozen P04 registry: {name}")
        accepted = entry["accepted_range"]
        observed = entry["observed_range"]
        if not (
            accepted[0] <= observed[0] <= observed[1] <= accepted[1]
            and accepted[0] <= entry["declared_range"][0]
            and accepted[1] >= entry["declared_range"][1]
        ):
            raise ContractError(f"P06 erratum bounds are internally inconsistent: {name}")
        entries[name] = dict(entry)
    return entries, sha256_file(root / FEATURE_ERRATA_PATH)


def _prefit_pass_identity(root: Path, stage_no: int) -> dict[str, Any]:
    """Verify a PASS record itself without rehashing its potentially large payload."""

    path = root / "state" / f"PREFIT_P{stage_no:02d}_PASS.json"
    if not path.is_file():
        raise ContractError(f"Prefit P{stage_no:02d} PASS is missing")
    record = _read_json(path)
    if (
        record.get("schema_version") != PREFIT_PASS_SCHEMA_VERSION
        or record.get("stage_id") != f"PREFIT_P{stage_no:02d}"
        or record.get("status") != "PASS"
    ):
        raise StaleStateError(f"P{stage_no:02d} PASS record identity is invalid")
    validate_prefit_run_id(str(record.get("run_id", "")), stage_no=stage_no)
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise StaleStateError(f"P{stage_no:02d} PASS record content hash changed")
    return record


def _predecessor(root: Path) -> dict[str, Any]:
    record = _prefit_pass_identity(root, 5)
    if record.get("record_sha256") != EXPECTED_P05_SHA256:
        raise StaleStateError("P06 requires the accepted P05 release")
    return record


def _release_authority(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _read_json(root / RELEASE_MANIFEST_PATH)
    index = _read_json(root / RELEASE_INDEX_PATH)
    if (
        manifest.get("release_id") != SUBSTRATE_RELEASE_ID
        or manifest.get("status") != "PASS_CANDIDATE"
        or index.get("release_id") != SUBSTRATE_RELEASE_ID
        or index.get("status") != "PASS_CANDIDATE"
        or index.get("manifest", {}).get("sha256")
        != sha256_file(root / RELEASE_MANIFEST_PATH)
    ):
        raise StaleStateError("P05 release manifest or index changed")
    return manifest, index


def _load_schedule_authority(
    root: Path,
) -> tuple[dict[tuple[date, str, datetime], dict[str, Any]], str, str]:
    contract = _read_json(root / ISSUE_VIEW_CONTRACT_PATH)
    relative = str(contract.get("schedule_path", ""))
    path = _inside(root, relative)
    expected = str(
        _prefit_pass_identity(root, 3).get("authority_hashes", {}).get(
            "R14_CYCLE_SCHEDULE", ""
        )
    )
    actual = sha256_file(path)
    if not _valid_sha256(expected) or actual != expected:
        raise StaleStateError("P06 R14 cycle-schedule authority changed")
    columns = [
        "target_day", "product", "cycle_init_utc", "hrrr_version",
        "native_max_forecast_hour", "window_start_utc", "window_end_utc",
        "retained_valid_start_utc", "retained_valid_end_utc",
        "availability_policy_id", "emulated_complete_time_utc",
    ]
    rows = pq.ParquetFile(path).read(columns=columns).to_pylist()
    result: dict[tuple[date, str, datetime], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["target_day"],
            str(row["product"]),
            as_utc(row["cycle_init_utc"]),
        )
        if key in result:
            raise ContractError("P06 R14 cycle schedule contains a duplicate key")
        result[key] = row
    if len(result) != EXPECTED_SCHEDULE_ROWS:
        raise ContractError("P06 R14 cycle-schedule row count changed")
    return result, relative, actual


def _command_prefix() -> str:
    return ".venv/bin/python -m kden_v375.prefit.cli"


def p06_preflight(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    predecessor = _predecessor(root)
    config = _load_config(root)
    manifest, _ = _release_authority(root)
    features, registry_hash = _load_feature_authority(root)
    range_errata, range_errata_hash = _load_feature_range_errata(
        root,
        registry_hash=registry_hash,
        features=features,
    )
    schedule, schedule_path, schedule_hash = _load_schedule_authority(root)
    if len(features) != EXPECTED_FEATURE_COUNT:
        raise ContractError("P06 feature-registry count changed")
    issue_file = pq.ParquetFile(root / ISSUE_OUTPUT_PATH)
    selection_file = pq.ParquetFile(root / SELECTION_OUTPUT_PATH)
    if (
        issue_file.schema_arrow != issue_spine_schema()
        or issue_file.metadata.num_rows != EXPECTED_ISSUE_ROWS
        or selection_file.schema_arrow != selected_cycles_schema()
        or selection_file.metadata.num_rows != EXPECTED_SELECTION_ROWS
    ):
        raise ContractError("P06 P03 authority metadata changed")
    trajectory_partitions = manifest["trajectory_catalog"]["year_partitions"]
    feature_partitions = manifest["deterministic_features"]["year_partitions"]
    if [row["year"] for row in trajectory_partitions] != list(TARGET_YEARS):
        raise ContractError("P06 trajectory partitions changed")
    if [row["year"] for row in feature_partitions] != list(TARGET_YEARS):
        raise ContractError("P06 feature partitions changed")
    run_id = make_prefit_run_id(6, "owner-full", "substrate-acceptance")
    prefix = _command_prefix()
    return {
        "schema_version": "KDEN_V375_PREFIT_P06_PREFLIGHT_V1",
        "status": "READY_FOR_OWNER_P06",
        "acceptance_id": ACCEPTANCE_ID,
        "substrate_release_id": SUBSTRATE_RELEASE_ID,
        "predecessor_record_sha256": predecessor["record_sha256"],
        "feature_registry_sha256": registry_hash,
        "feature_range_errata_id": FEATURE_ERRATA_ID,
        "feature_range_errata_path": FEATURE_ERRATA_PATH,
        "feature_range_errata_sha256": range_errata_hash,
        "feature_range_errata_count": len(range_errata),
        "cycle_schedule_path": schedule_path,
        "cycle_schedule_sha256": schedule_hash,
        "cycle_schedule_rows": len(schedule),
        "feature_count": len(features),
        "expected_acceptance_units": len(ACCEPTANCE_UNITS),
        "expected_issue_rows": EXPECTED_ISSUE_ROWS,
        "expected_selection_rows": EXPECTED_SELECTION_ROWS,
        "expected_feature_rows": EXPECTED_FEATURE_ROWS,
        "expected_trajectory_rows": EXPECTED_TRAJECTORY_ROWS,
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "model_fits_performed": 0,
        "pause_boundary": config["execution"]["pause_boundary"],
        "suggested_run_id": run_id,
        "start_command": f"{prefix} run-p06 --run-id {run_id}",
        "status_command": f"{prefix} p06-status --run-id {run_id}",
        "live_status_command": f"{prefix} p06-live-status --run-id {run_id} --interval-seconds 5",
        "eta_command": f"{prefix} p06-eta --run-id {run_id}",
        "pause_command": f"{prefix} p06-pause --run-id {run_id}",
        "resume_command": f"{prefix} resume-p06 --run-id {run_id}",
        "validation_command": f"{prefix} validate-p06",
    }


def _run_paths(root: Path, run_id: str) -> dict[str, Path]:
    base = _inside(root, Path("prefit_runs") / run_id / "p06")
    return {
        "base": base,
        "state": base / "run.json",
        "pause": base / "control/pause.requested.json",
        "checkpoints": base / "checkpoints",
        "journal": base / "progress/completions.jsonl",
    }


def _initialize_state(root: Path, run_id: str) -> dict[str, Any]:
    validate_prefit_run_id(run_id, stage_no=6, scope="owner-full")
    path = _run_paths(root, run_id)["state"]
    if path.is_file():
        state = _read_json(path)
        if state.get("schema_version") != RUN_STATE_SCHEMA or state.get("run_id") != run_id:
            raise StaleStateError("P06 run-state identity mismatch")
        return state
    created = utc_now()
    state = {
        "schema_version": RUN_STATE_SCHEMA,
        "stage_id": "PREFIT_P06",
        "run_id": run_id,
        "status": "INITIALIZED",
        "phase": "NOT_STARTED",
        "message": "initialized",
        "created_at_utc": created,
        "started_at_utc": None,
        "updated_at_utc": created,
        "completed_at_utc": None,
        "expected_acceptance_units": len(ACCEPTANCE_UNITS),
        "completed_acceptance_units": 0,
        "completed_units": [],
        "expected_feature_rows": EXPECTED_FEATURE_ROWS,
        "completed_feature_rows": 0,
        "expected_trajectory_rows": EXPECTED_TRAJECTORY_ROWS,
        "completed_trajectory_rows": 0,
        "current_unit": None,
        "current_rows_completed": None,
        "current_rows_expected": None,
        "record_sha256": None,
    }
    atomic_write_json(path, state, replace=False)
    return state


def _update_state(root: Path, run_id: str, **updates: Any) -> dict[str, Any]:
    path = _run_paths(root, run_id)["state"]
    state = _read_json(path)
    state.update(updates, updated_at_utc=utc_now())
    atomic_write_json(path, state, replace=True)
    return state


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(canonical_json_bytes(dict(value)))
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def _journal_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise StaleStateError("P06 completion journal contains a non-object")
                records.append(value)
    return records


def _checkpoint_path(root: Path, run_id: str, unit_id: str) -> Path:
    return _run_paths(root, run_id)["checkpoints"] / f"{unit_id}.json"


def _checkpoint(root: Path, run_id: str, unit_id: str) -> dict[str, Any] | None:
    path = _checkpoint_path(root, run_id, unit_id)
    if not path.is_file():
        return None
    value = _read_json(path)
    body = dict(value)
    supplied = body.pop("record_sha256", None)
    if (
        value.get("schema_version") != CHECKPOINT_SCHEMA
        or value.get("unit_id") != unit_id
        or value.get("p05_record_sha256") != EXPECTED_P05_SHA256
        or supplied != sha256_bytes(canonical_json_bytes(body))
    ):
        raise StaleStateError(f"P06 checkpoint changed: {unit_id}")
    for relative, expected in value.get("input_hashes", {}).items():
        if sha256_file(_inside(root, relative)) != expected:
            raise StaleStateError(f"P06 checkpoint input changed: {relative}")
    return value


def _publish_checkpoint(
    root: Path,
    run_id: str,
    unit_id: str,
    *,
    evidence: Mapping[str, Any],
    input_hashes: Mapping[str, str],
    elapsed_seconds: float,
) -> dict[str, Any]:
    body = {
        "schema_version": CHECKPOINT_SCHEMA,
        "unit_id": unit_id,
        "p05_record_sha256": EXPECTED_P05_SHA256,
        "completed_at_utc": utc_now(),
        "elapsed_seconds": elapsed_seconds,
        "input_hashes": dict(sorted(input_hashes.items())),
        "evidence": dict(evidence),
    }
    value = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(_checkpoint_path(root, run_id, unit_id), value, replace=True)
    return value


def _commit_unit(root: Path, run_id: str, checkpoint: Mapping[str, Any]) -> None:
    records = _journal_records(_run_paths(root, run_id)["journal"])
    committed = {str(row.get("unit_id")) for row in records}
    if checkpoint["unit_id"] not in committed:
        _append_jsonl(
            _run_paths(root, run_id)["journal"],
            {
                "schema_version": JOURNAL_SCHEMA,
                "unit_id": checkpoint["unit_id"],
                "elapsed_seconds": checkpoint["elapsed_seconds"],
                "feature_rows": checkpoint["evidence"].get("feature_rows", 0),
                "trajectory_rows": checkpoint["evidence"].get("trajectory_rows", 0),
                "committed_at_utc": utc_now(),
            },
        )


def _completed_summary(root: Path, run_id: str) -> tuple[list[str], int, int]:
    completed: list[str] = []
    feature_rows = 0
    trajectory_rows = 0
    for unit_id in ACCEPTANCE_UNITS:
        item = _checkpoint(root, run_id, unit_id)
        if item is None:
            continue
        completed.append(unit_id)
        feature_rows += int(item["evidence"].get("feature_rows", 0))
        trajectory_rows += int(item["evidence"].get("trajectory_rows", 0))
    return completed, feature_rows, trajectory_rows


def _publish_completed_progress(
    root: Path,
    run_id: str,
    checkpoints: Sequence[Mapping[str, Any]],
) -> None:
    _update_state(
        root,
        run_id,
        completed_units=[str(item["unit_id"]) for item in checkpoints],
        completed_acceptance_units=len(checkpoints),
        completed_feature_rows=sum(
            int(item["evidence"].get("feature_rows", 0)) for item in checkpoints
        ),
        completed_trajectory_rows=sum(
            int(item["evidence"].get("trajectory_rows", 0)) for item in checkpoints
        ),
        current_unit=None,
        current_rows_completed=None,
        current_rows_expected=None,
    )


def _expected_era(target: date) -> str:
    return "KDEN_COORD_20040105" if target <= date(2021, 11, 21) else "KDEN_COORD_20211122"


def _expected_trajectory_era(valid_time_utc: datetime) -> str:
    """Resolve dynamic spatial support from physical valid time, not target label."""

    local_day = as_utc(valid_time_utc).astimezone(DENVER).date()
    return (
        "KDEN_COORD_20040105"
        if local_day < date(2021, 11, 22)
        else "KDEN_COORD_20211122"
    )


def _validate_issue_row(row: Mapping[str, Any]) -> None:
    target = row["target_date"]
    issue = as_utc(row["issue_time_utc"])
    local = issue.astimezone(DENVER)
    window_start = datetime.combine(target, daytime(7), tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    if row["issue_state_id"] != issue_state_id(target, issue):
        raise ContractError("P06 issue-state identifier mismatch")
    if (
        local.date() != target
        or row["issue_time_local"].replace(fold=local.fold) != local
        or row["local_timezone"] != "America/Denver"
        or int(row["local_utc_offset_minutes"]) != int(local.utcoffset().total_seconds() // 60)
        or bool(row["local_dst_flag"]) != bool(local.dst())
        or int(row["local_fold"]) != int(local.fold)
        or int(row["local_issue_hour"]) != local.hour
        or int(row["local_issue_minute"]) != local.minute
        or int(row["local_minutes_since_0200"]) != local.hour * 60 + local.minute - 120
        or local.minute not in {0, 15, 30, 45}
        or not 2 <= local.hour <= 16
        or row["target_window_start_utc"] != window_start
        or row["target_window_end_utc"] != window_end
        or row["statistical_group_id"] != f"KDEN_DAY_{target.isoformat()}"
        or row["issue_grid_contract_id"] != ISSUE_GRID_ID
        or row["issue_state_eligible"] is not True
    ):
        raise ContractError(f"P06 issue clock contract failed: {row['issue_state_id']}")


def _scan_issue_spine(root: Path, run_id: str, expected_hash: str) -> dict[str, Any]:
    path = root / ISSUE_OUTPUT_PATH
    if sha256_file(path) != expected_hash:
        raise StaleStateError("P06 issue-spine hash mismatch")
    parquet = pq.ParquetFile(path)
    if parquet.schema_arrow != issue_spine_schema() or parquet.metadata.num_rows != EXPECTED_ISSUE_ROWS:
        raise ContractError("P06 issue-spine schema or count changed")
    counts: Counter[date] = Counter()
    declared_counts: dict[date, int] = {}
    ordinals: dict[date, int] = defaultdict(int)
    last_key: tuple[date, datetime] | None = None
    completed = 0
    for batch in parquet.iter_batches(batch_size=32_768):
        for row in batch.to_pylist():
            _validate_issue_row(row)
            target = row["target_date"]
            key = (target, as_utc(row["issue_time_utc"]))
            if last_key is not None and key <= last_key:
                raise ContractError("P06 issue-spine ordering or uniqueness changed")
            if int(row["issue_ordinal_in_target_day"]) != ordinals[target]:
                raise ContractError("P06 issue ordinal changed")
            ordinals[target] += 1
            counts[target] += 1
            declared = int(row["issue_count_for_target_day"])
            previous_declared = declared_counts.setdefault(target, declared)
            if declared != previous_declared:
                raise ContractError(f"P06 issue count declaration changes within {target}")
            last_key = key
        completed += batch.num_rows
        _update_state(
            root,
            run_id,
            current_unit="issue-spine",
            current_rows_completed=completed,
            current_rows_expected=EXPECTED_ISSUE_ROWS,
        )
    expected_days = (STUDY_END - STUDY_START).days + 1
    if len(counts) != expected_days or min(counts) != STUDY_START or max(counts) != STUDY_END:
        raise ContractError("P06 issue-spine date coverage changed")
    spring_forward = []
    for target, count in counts.items():
        if count not in {53, 57}:
            raise ContractError(f"P06 unexpected issue count for {target}: {count}")
        if declared_counts[target] != count:
            raise ContractError(f"P06 declared issue count changed for {target}")
        if count == 53:
            spring_forward.append(target.isoformat())
    if spring_forward != [
        "2021-03-14", "2022-03-13", "2023-03-12",
        "2024-03-10", "2025-03-09", "2026-03-08",
    ]:
        raise ContractError("P06 DST spring-forward coverage changed")
    return {
        "issue_rows": completed,
        "target_days": len(counts),
        "ordinary_target_days": sum(value == 57 for value in counts.values()),
        "spring_forward_dates": spring_forward,
        "clock_equations_verified": True,
        "right_open_target_windows_verified": True,
        "dst_safe_issue_grid_verified": True,
    }


def _load_authority_maps(
    root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    issue_columns = [
        "issue_state_id", "target_date", "statistical_group_id", "issue_time_utc",
        "local_issue_hour", "local_issue_minute", "local_minutes_since_0200",
        "local_dst_flag", "target_day_of_year", "target_window_start_utc",
        "target_window_end_utc",
    ]
    issues = pq.ParquetFile(root / ISSUE_OUTPUT_PATH).read(columns=issue_columns).to_pylist()
    issues_by_id = {str(row["issue_state_id"]): row for row in issues}
    selection_columns = [
        "issue_state_id", "target_date", "issue_time_utc", "product",
        "selection_status", "cycle_init_utc", "emulated_complete_time_utc",
        "cycle_age_minutes", "availability_age_minutes", "previous_cycle_init_utc",
        "previous_emulated_complete_time_utc", "previous_cycle_age_minutes",
        "previous_availability_age_minutes", "availability_policy_id",
        "availability_basis", "retained_valid_start_utc", "retained_valid_end_utc",
        "previous_retained_valid_start_utc", "previous_retained_valid_end_utc",
        "trajectory_bundle_path", "trajectory_bundle_present",
        "previous_trajectory_bundle_path", "previous_trajectory_bundle_present",
        "selection_missing_reason",
    ]
    rows = pq.ParquetFile(root / SELECTION_OUTPUT_PATH).read(columns=selection_columns).to_pylist()
    selections: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        selections[str(row["issue_state_id"])][str(row["product"])] = row
    return issues_by_id, dict(selections)


def _validate_selection_row(
    row: Mapping[str, Any],
    issue: Mapping[str, Any],
    schedule_rows: Mapping[tuple[date, str, datetime], Mapping[str, Any]],
) -> None:
    issue_time = as_utc(issue["issue_time_utc"])
    if (
        row["target_date"] != issue["target_date"]
        or as_utc(row["issue_time_utc"]) != issue_time
        or row["availability_policy_id"] != "KDEN_HIST_COMPLETE_L105_V1"
        or row["availability_basis"] != AVAILABILITY_BASIS
        or row["product"] not in PRODUCT_ORDER
    ):
        raise ContractError("P06 selected-cycle authority mismatch")
    if row["selection_status"] != "SELECTED":
        raise ContractError("P05 materialized feature row has a non-selected product cycle")
    cycle = as_utc(row["cycle_init_utc"])
    complete = as_utc(row["emulated_complete_time_utc"])
    previous = as_utc(row["previous_cycle_init_utc"])
    previous_complete = as_utc(row["previous_emulated_complete_time_utc"])
    window_start = as_utc(issue["target_window_start_utc"])
    window_end = as_utc(issue["target_window_end_utc"])
    retained_start = as_utc(row["retained_valid_start_utc"])
    retained_end = as_utc(row["retained_valid_end_utc"])
    previous_retained_start = as_utc(row["previous_retained_valid_start_utc"])
    previous_retained_end = as_utc(row["previous_retained_valid_end_utc"])
    current_schedule = schedule_rows.get((issue["target_date"], str(row["product"]), cycle))
    previous_schedule = schedule_rows.get(
        (issue["target_date"], str(row["product"]), previous)
    )
    if current_schedule is None or previous_schedule is None:
        raise ContractError("P06 selected cycle lacks a frozen schedule parent")
    if (
        complete != cycle + timedelta(minutes=105)
        or previous_complete != previous + timedelta(minutes=105)
        or complete > issue_time
        or previous_complete > issue_time
        or previous >= cycle
        or int(row["cycle_age_minutes"]) != int((issue_time - cycle).total_seconds() // 60)
        or int(row["availability_age_minutes"]) != int((issue_time - complete).total_seconds() // 60)
        or int(row["previous_cycle_age_minutes"]) != int((issue_time - previous).total_seconds() // 60)
        or int(row["previous_availability_age_minutes"]) != int((issue_time - previous_complete).total_seconds() // 60)
        or retained_start != as_utc(current_schedule["retained_valid_start_utc"])
        or retained_end != as_utc(current_schedule["retained_valid_end_utc"])
        or previous_retained_start
        != as_utc(previous_schedule["retained_valid_start_utc"])
        or previous_retained_end != as_utc(previous_schedule["retained_valid_end_utc"])
        or as_utc(current_schedule["window_start_utc"]) != window_start
        or as_utc(current_schedule["window_end_utc"]) != window_end
        or as_utc(previous_schedule["window_start_utc"]) != window_start
        or as_utc(previous_schedule["window_end_utc"]) != window_end
        or retained_start > retained_end
        or previous_retained_start > previous_retained_end
        or retained_end > window_end
        or previous_retained_end > window_end
        or row["trajectory_bundle_present"] is not True
        or row["previous_trajectory_bundle_present"] is not True
        or row["selection_missing_reason"] is not None
    ):
        raise ContractError(
            f"P06 cycle availability or retained-window contract failed: {row['issue_state_id']}/{row['product']}"
        )


def _scan_selected_cycles(
    root: Path,
    run_id: str,
    expected_hash: str,
    issues_by_id: Mapping[str, Mapping[str, Any]],
    schedule_rows: Mapping[tuple[date, str, datetime], Mapping[str, Any]],
) -> dict[str, Any]:
    path = root / SELECTION_OUTPUT_PATH
    if sha256_file(path) != expected_hash:
        raise StaleStateError("P06 selected-cycle hash mismatch")
    parquet = pq.ParquetFile(path)
    if parquet.schema_arrow != selected_cycles_schema() or parquet.metadata.num_rows != EXPECTED_SELECTION_ROWS:
        raise ContractError("P06 selected-cycle schema or count changed")
    products_by_issue: dict[str, set[str]] = defaultdict(set)
    completed = 0
    unique_current_paths: set[str] = set()
    unique_previous_paths: set[str] = set()
    for batch in parquet.iter_batches(batch_size=32_768):
        for row in batch.to_pylist():
            identifier = str(row["issue_state_id"])
            issue = issues_by_id.get(identifier)
            if issue is None:
                raise ContractError("P06 selected cycle has no issue-spine parent")
            _validate_selection_row(row, issue, schedule_rows)
            product = str(row["product"])
            if product in products_by_issue[identifier]:
                raise ContractError("P06 duplicate product selection for one issue state")
            products_by_issue[identifier].add(product)
            current_path = str(row["trajectory_bundle_path"])
            previous_path = str(row["previous_trajectory_bundle_path"])
            _inside(root, current_path)
            _inside(root, previous_path)
            unique_current_paths.add(current_path)
            unique_previous_paths.add(previous_path)
        completed += batch.num_rows
        _update_state(
            root,
            run_id,
            current_unit="selected-cycles",
            current_rows_completed=completed,
            current_rows_expected=EXPECTED_SELECTION_ROWS,
        )
    if len(products_by_issue) != EXPECTED_ISSUE_ROWS or any(
        products != set(PRODUCT_ORDER) for products in products_by_issue.values()
    ):
        raise ContractError("P06 issue/product selection reconciliation failed")
    return {
        "selection_rows": completed,
        "issue_states_with_two_independent_products": len(products_by_issue),
        "unique_current_bundle_paths": len(unique_current_paths),
        "unique_previous_bundle_paths": len(unique_previous_paths),
        "future_complete_cycles_admitted": 0,
        "availability_equations_verified": True,
        "independent_product_selection_verified": True,
    }


def _scan_static(root: Path, expected_hash: str) -> dict[str, Any]:
    path = root / STATIC_TRAJECTORY_PATH
    if sha256_file(path) != expected_hash:
        raise StaleStateError("P06 static H14 catalog hash mismatch")
    parquet = pq.ParquetFile(path)
    if parquet.schema_arrow != trajectory_catalog_schema() or parquet.metadata.num_rows != 1:
        raise ContractError("P06 static H14 schema or count changed")
    row = parquet.read().to_pylist()[0]
    if (
        row["field_registry_id"] != "H14"
        or row["product"] != "wrfsfcf"
        or row["canonical_unit"] != "m"
        or row["spatial_contract_id"] != "GRID_STATIC_ONCE_V1"
        or row["coverage_flag"] != "PRESENT"
        or row["local_value_column"] != "bi_value"
        or row["regional_values_available"] is not True
        or row["regional_support_count"] != 8
        or row["regional_coverage_mask"] != 255
        or not _valid_sha256(row["canonical_archive_sha256"])
    ):
        raise ContractError("P06 static H14 contract changed")
    return {
        "trajectory_rows": 1,
        "static_field": "H14",
        "static_reference_once_verified": True,
        "terrain_coordinate_era_support_deferred_to_anchor_probe": True,
    }


def _feature_partition_for_year(manifest: Mapping[str, Any], year: int) -> Mapping[str, Any]:
    matches = [row for row in manifest["deterministic_features"]["year_partitions"] if row["year"] == year]
    if len(matches) != 1:
        raise ContractError(f"P06 feature partition is not unique for {year}")
    return matches[0]


def _trajectory_partition_for_year(manifest: Mapping[str, Any], year: int) -> Mapping[str, Any]:
    matches = [row for row in manifest["trajectory_catalog"]["year_partitions"] if row["year"] == year]
    if len(matches) != 1:
        raise ContractError(f"P06 trajectory partition is not unique for {year}")
    return matches[0]


def _validate_feature_row(
    row: Mapping[str, Any],
    issue: Mapping[str, Any],
    selections: Mapping[str, Mapping[str, Any]],
    features: Sequence[Mapping[str, Any]],
    range_errata: Mapping[str, Mapping[str, Any]],
) -> tuple[int, int]:
    if (
        row["target_date"] != issue["target_date"]
        or row["statistical_group_id"] != issue["statistical_group_id"]
        or as_utc(row["issue_time_utc"]) != as_utc(issue["issue_time_utc"])
        or row["station_coord_era"] != _expected_era(issue["target_date"])
        or as_utc(row["wrfsfcf_cycle_init_utc"]) != as_utc(selections["wrfsfcf"]["cycle_init_utc"])
        or as_utc(row["wrfsubhf_cycle_init_utc"]) != as_utc(selections["wrfsubhf"]["cycle_init_utc"])
        or row["feature_registry_id"] != REGISTRY_ID
        or row["derivation_id"] != DERIVATION_ID
        or row["clock_issue_minutes_since_0200"] != issue["local_minutes_since_0200"]
        or row["clock_local_dst_flag"] != issue["local_dst_flag"]
    ):
        raise ContractError(f"P06 feature/authority reconciliation failed: {row['issue_state_id']}")
    nulls = 0
    checked = 0
    for feature in features:
        name = str(feature["name"])
        value = row[name]
        if value is None:
            nulls += 1
            if str(feature["null_policy"]).startswith("NEVER_NULL"):
                raise ContractError(f"P06 required feature is null: {name}")
            continue
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError(f"P06 non-finite feature must be Arrow null: {name}")
        erratum = range_errata.get(name)
        if erratum is None:
            _validate_range(feature, value)
        else:
            if feature.get("physical_range") != erratum.get("declared_range"):
                raise ContractError(f"P06 erratum/registry range mismatch: {name}")
            acceptance_feature = dict(feature)
            acceptance_feature["physical_range"] = list(erratum["accepted_range"])
            _validate_range(acceptance_feature, value)
        checked += 1
    return checked, nulls


def _validate_trajectory_row(
    row: Mapping[str, Any],
    *,
    year: int,
    field_contracts: Mapping[str, Mapping[str, Any]],
    schedule_rows: Mapping[tuple[date, str, datetime], Mapping[str, Any]],
) -> bool:
    target = row["target_date"]
    cycle = as_utc(row["cycle_init_utc"])
    valid = as_utc(row["valid_time_utc"])
    interval_start = as_utc(row["interval_start_utc"])
    interval_end = as_utc(row["interval_end_utc"])
    field = str(row["field_registry_id"])
    product = str(row["product"])
    lead = int(row["forecast_lead_min"])
    window_start = datetime.combine(target, daytime(7), tzinfo=UTC)
    window_end = window_start + timedelta(days=1)
    schedule = schedule_rows.get((target, product, cycle))
    if schedule is None:
        raise ContractError("P06 trajectory has no frozen R14 schedule parent")
    field_contract = field_contracts[field]
    retained_start = as_utc(schedule["retained_valid_start_utc"])
    retained_end = as_utc(schedule["retained_valid_end_utc"])
    if (
        target.year != year
        or field not in DYNAMIC_FIELDS
        or product != FIELD_PRODUCT[field]
        or row["parameter"] != field_contract["parameter"]
        or row["level"] != field_contract["level"]
        or row["step_type"] != field_contract["decoded_step_type"]
        or row["native_unit"] != field_contract["native_unit"]
        or row["canonical_unit"] != FIELD_UNITS[field]
        or row["local_value_column"] != LOCAL_VALUE_COLUMN[field]
        or row["spatial_contract_id"] != field_contract["spatial_contract_id"]
        or row["station_id"] != "KDEN"
        or row["grid_geometry_id"] != "HRRR_CONUS_NATIVE_LAMBERT_V4"
        or row["regional_spatial_contract_id"] != "KDEN_V375_R14_REGIONAL_SPATIAL_V1"
        or not str(row["selector_identity"]).startswith(
            f"{field_contract['selector_contract_id']}@"
        )
        or row["station_coord_era"] != _expected_trajectory_era(valid)
        or lead != int((valid - cycle).total_seconds() // 60)
        or interval_end != valid
        or as_utc(schedule["window_start_utc"]) != window_start
        or as_utc(schedule["window_end_utc"]) != window_end
        or retained_end > window_end
        or not retained_start <= valid <= retained_end
        or schedule["availability_policy_id"] != "KDEN_HIST_COMPLETE_L105_V1"
        or as_utc(schedule["emulated_complete_time_utc"]) != cycle + timedelta(minutes=105)
        or row["hrrr_version"] != schedule["hrrr_version"]
        or lead > int(schedule["native_max_forecast_hour"]) * 60
        or row["time_support_id"] != time_support_id(row)
        or row["trajectory_state_id"]
        != trajectory_state_id(row, spatial_contract_id=str(row["spatial_contract_id"]))
        or not _valid_sha256(row["source_idx_hash_hex"])
        or not _valid_sha256(row["canonical_archive_sha256"])
        or not str(row["canonical_archive_path"]).startswith("hrrr_v4_local_archive/")
        or int(row["canonical_archive_row_ordinal"]) < 0
    ):
        raise ContractError(f"P06 trajectory contract failed: {row['trajectory_state_id']}")
    if field == "H38":
        expected_duration = 0 if lead == 0 else 60
        if int((interval_end - interval_start).total_seconds() // 60) != expected_duration:
            raise ContractError("P06 H38 interval semantics changed")
    elif interval_start != valid:
        raise ContractError("P06 snapshot field has non-instantaneous time support")
    expected_tile = field in TILE_FIELDS
    expected_regional = field in REGIONAL_FIELDS
    expected_regional_operator = (
        "NEAREST_AT_EIGHT_SUPPORTS"
        if field in {"H36", "H38"}
        else "BILINEAR_AT_EIGHT_SUPPORTS"
        if expected_regional
        else None
    )
    present = row["coverage_flag"] == "PRESENT"
    spatial_checks = {
        "tile_values_available": bool(row["tile_values_available"])
        == (expected_tile and present),
        "regional_values_available": bool(row["regional_values_available"])
        == (expected_regional and present),
        "regional_support_count": int(row["regional_support_count"])
        == (8 if expected_regional else 0),
        "regional_coverage_mask": int(row["regional_coverage_mask"])
        == (255 if expected_regional and present else 0),
        "regional_operator": row["regional_operator"] == expected_regional_operator,
    }
    failed_spatial = [name for name, passed in spatial_checks.items() if not passed]
    if failed_spatial:
        raise ContractError(
            "P06 trajectory spatial-support contract changed: "
            f"{row['trajectory_state_id']}; failed={','.join(failed_spatial)}"
        )
    if present:
        if row["missing_reason"] is not None or not _valid_sha256(row["payload_hash_hex"]):
            raise ContractError(
                "P06 present trajectory has invalid missingness evidence: "
                f"{row['trajectory_state_id']}"
            )
    elif (
        row["coverage_flag"] != "MISSING"
        or row["missing_reason"] != "SOURCE_OBJECT_HTTP_404"
        or row["payload_hash_hex"] is not None
    ):
        raise ContractError(
            "P06 missing trajectory is not explicitly represented: "
            f"{row['trajectory_state_id']}"
        )
    return present


def _scan_year(
    root: Path,
    run_id: str,
    *,
    year: int,
    manifest: Mapping[str, Any],
    issues_by_id: Mapping[str, Mapping[str, Any]],
    selections_by_issue: Mapping[str, Mapping[str, Mapping[str, Any]]],
    features: Sequence[Mapping[str, Any]],
    range_errata: Mapping[str, Mapping[str, Any]],
    field_contracts: Mapping[str, Mapping[str, Any]],
    schedule_rows: Mapping[tuple[date, str, datetime], Mapping[str, Any]],
    feature_base: int,
    trajectory_base: int,
    pause: PauseController,
) -> tuple[dict[str, Any], dict[str, str]]:
    feature_entry = _feature_partition_for_year(manifest, year)
    trajectory_entry = _trajectory_partition_for_year(manifest, year)
    feature_path = _inside(root, str(feature_entry["path"]))
    trajectory_path = _inside(root, str(trajectory_entry["path"]))
    feature_hash = sha256_file(feature_path)
    trajectory_hash = sha256_file(trajectory_path)
    if feature_hash != feature_entry["sha256"] or trajectory_hash != trajectory_entry["sha256"]:
        raise StaleStateError(f"P06 P05 partition hash changed for {year}")
    feature_file = pq.ParquetFile(feature_path)
    trajectory_file = pq.ParquetFile(trajectory_path)
    if feature_file.schema_arrow != feature_panel_schema(features):
        raise ContractError(f"P06 feature schema changed for {year}")
    if trajectory_file.schema_arrow != trajectory_catalog_schema():
        raise ContractError(f"P06 trajectory schema changed for {year}")
    expected_ids = {
        identifier for identifier, row in issues_by_id.items() if row["target_date"].year == year
    }
    seen_ids: set[str] = set()
    feature_rows = 0
    range_checks = 0
    feature_nulls = 0
    last_feature_key: tuple[date, datetime] | None = None
    for batch in feature_file.iter_batches(batch_size=2_048):
        pause.raise_if_requested()
        for row in batch.to_pylist():
            identifier = str(row["issue_state_id"])
            issue = issues_by_id.get(identifier)
            selections = selections_by_issue.get(identifier)
            if issue is None or selections is None or set(selections) != set(PRODUCT_ORDER):
                raise ContractError("P06 feature row lacks complete P03 authorities")
            key = (row["target_date"], as_utc(row["issue_time_utc"]))
            if identifier in seen_ids or (last_feature_key is not None and key <= last_feature_key):
                raise ContractError("P06 feature primary key or ordering changed")
            checked, nulls = _validate_feature_row(
                row,
                issue,
                selections,
                features,
                range_errata,
            )
            range_checks += checked
            feature_nulls += nulls
            seen_ids.add(identifier)
            last_feature_key = key
        feature_rows += batch.num_rows
        _update_state(
            root,
            run_id,
            current_unit=f"target-year-{year}:features",
            current_rows_completed=feature_rows,
            current_rows_expected=feature_file.metadata.num_rows,
            completed_feature_rows=feature_base + feature_rows,
        )
    if seen_ids != expected_ids or feature_rows != int(feature_entry["rows"]):
        raise ContractError(f"P06 feature/issue coverage mismatch for {year}")

    selected_paths = {
        str(selection[path_key])
        for identifier, by_product in selections_by_issue.items()
        if issues_by_id[identifier]["target_date"].year == year
        for selection in by_product.values()
        for path_key in ("trajectory_bundle_path", "previous_trajectory_bundle_path")
    }
    unmatched_selected_paths = set(selected_paths)
    trajectory_rows = 0
    missing_rows = 0
    source_paths: set[str] = set()
    completed_source_paths: set[str] = set()
    source_files_hashed = 0
    last_path: str | None = None
    last_ordinal = -1
    last_source_sha: str | None = None
    fields: Counter[str] = Counter()
    target_days: set[date] = set()
    observed_schedule_keys: set[tuple[date, str, datetime]] = set()

    def close_source(path_value: str, expected_sha: str, final_ordinal: int) -> None:
        nonlocal source_files_hashed
        absolute = _inside(root, path_value)
        if sha256_file(absolute) != expected_sha:
            raise StaleStateError(f"P06 canonical source hash changed: {path_value}")
        if pq.ParquetFile(absolute).metadata.num_rows != final_ordinal + 1:
            raise ContractError(f"P06 canonical source row coverage changed: {path_value}")
        source_files_hashed += 1

    for batch in trajectory_file.iter_batches(batch_size=16_384):
        pause.raise_if_requested()
        for row in batch.to_pylist():
            present = _validate_trajectory_row(
                row,
                year=year,
                field_contracts=field_contracts,
                schedule_rows=schedule_rows,
            )
            missing_rows += int(not present)
            field = str(row["field_registry_id"])
            fields[field] += 1
            target_days.add(row["target_date"])
            observed_schedule_keys.add(
                (
                    row["target_date"],
                    str(row["product"]),
                    as_utc(row["cycle_init_utc"]),
                )
            )
            source_path = str(row["canonical_archive_path"])
            source_sha = str(row["canonical_archive_sha256"])
            ordinal = int(row["canonical_archive_row_ordinal"])
            unmatched_selected_paths.discard(source_path)
            if source_path == last_path:
                if ordinal != last_ordinal + 1 or source_sha != last_source_sha:
                    raise ContractError("P06 canonical source locators are not contiguous")
            else:
                if source_path in completed_source_paths or ordinal != 0:
                    raise ContractError("P06 canonical source file reappeared or does not begin at row zero")
                if last_path is not None:
                    close_source(last_path, str(last_source_sha), last_ordinal)
                    completed_source_paths.add(last_path)
                source_paths.add(source_path)
                _inside(root, source_path)
            last_path = source_path
            last_ordinal = ordinal
            last_source_sha = source_sha
        trajectory_rows += batch.num_rows
        _update_state(
            root,
            run_id,
            current_unit=f"target-year-{year}:trajectories",
            current_rows_completed=trajectory_rows,
            current_rows_expected=trajectory_file.metadata.num_rows,
            completed_trajectory_rows=trajectory_base + trajectory_rows,
        )
    if last_path is not None:
        close_source(last_path, str(last_source_sha), last_ordinal)
        completed_source_paths.add(last_path)
    if trajectory_rows != int(trajectory_entry["rows"]):
        raise ContractError(f"P06 trajectory row count mismatch for {year}")
    if unmatched_selected_paths:
        sample = sorted(unmatched_selected_paths)[:3]
        raise ContractError(f"P06 selected bundles are absent from trajectory catalog: {sample}")
    expected_days = {
        row["target_date"] for row in issues_by_id.values() if row["target_date"].year == year
    }
    expected_schedule_keys = {key for key in schedule_rows if key[0].year == year}
    if target_days != expected_days or set(fields) != set(DYNAMIC_FIELDS):
        raise ContractError(f"P06 trajectory day/field coverage mismatch for {year}")
    if observed_schedule_keys != expected_schedule_keys:
        raise ContractError(f"P06 trajectory/schedule coverage mismatch for {year}")
    evidence = {
        "year": year,
        "feature_rows": feature_rows,
        "trajectory_rows": trajectory_rows,
        "missing_trajectory_rows": missing_rows,
        "source_bundle_paths": len(source_paths),
        "canonical_source_files_hashed": source_files_hashed,
        "selected_bundle_paths_reconciled": len(selected_paths),
        "feature_values_range_checked": range_checks,
        "feature_null_values": feature_nulls,
        "target_days": len(target_days),
        "field_row_counts": dict(sorted(fields.items())),
        "clock_lead_interval_rules_verified": True,
        "units_spatial_coordinate_rules_verified": True,
        "explicit_missingness_verified": True,
    }
    return evidence, {
        _relative(root, feature_path): feature_hash,
        _relative(root, trajectory_path): trajectory_hash,
        FEATURE_ERRATA_PATH: sha256_file(root / FEATURE_ERRATA_PATH),
    }


def _scan_anchors(
    root: Path,
    config: Mapping[str, Any],
    features: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    reader = R14ArchiveReader(root, verify_acquisition=True)
    cached_panels: dict[int, pa.Table] = {}
    rebuilt: list[str] = []
    for case in config["anchor_cases"]:
        target = date.fromisoformat(case["target_date"])
        issue, selections = _case_rows(root, target, case["issue_local"])
        computed = compute_issue_feature_row(
            issue_row=issue,
            selection_rows=selections,
            reader=reader,
            features=features,
        )
        panel = cached_panels.get(target.year)
        if panel is None:
            manifest, _ = _release_authority(root)
            entry = _feature_partition_for_year(manifest, target.year)
            panel = pq.ParquetFile(_inside(root, entry["path"])).read()
            cached_panels[target.year] = panel
        selected = panel.filter(pc.equal(panel["issue_state_id"], computed["issue_state_id"]))
        if selected.num_rows != 1:
            raise ContractError(f"P06 anchor is not unique in P05: {case['case_id']}")
        materialized = selected.to_pylist()[0]
        for name in materialized:
            expected = computed.get(name, materialized[name] if name == "target_year" else None)
            actual = materialized[name]
            if isinstance(expected, datetime):
                equal = as_utc(expected) == as_utc(actual)
            elif isinstance(expected, float) and isinstance(actual, float):
                equal = math.isclose(expected, actual, rel_tol=0.0, abs_tol=1e-12)
            else:
                equal = expected == actual
            if not equal:
                raise ContractError(f"P06 anchor rebuild differs: {case['case_id']}/{name}")
        rebuilt.append(str(case["case_id"]))
    return {
        "anchor_case_ids": rebuilt,
        "anchor_rebuild_count": len(rebuilt),
        "anchor_rows_exactly_match_p05": True,
        "coordinate_era_boundary_rebuilt": True,
        "confirmed_remote_missing_rebuilt": True,
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
    }


def _check_leakage(
    config: Mapping[str, Any],
    features: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    prohibited = tuple(str(token).lower() for token in config["forbidden_predictor_tokens"])
    feature_names = [str(row["name"]) for row in features]
    trajectory_names = trajectory_catalog_schema().names
    metadata_names = feature_panel_schema(features).names
    for name in feature_names + trajectory_names + metadata_names:
        lowered = name.lower()
        if any(token in lowered for token in prohibited):
            raise ContractError(f"P06 forbidden predictor namespace leaked: {name}")
    for feature in features:
        if any(
            any(token in str(source).lower() for token in prohibited)
            for source in feature.get("source_fields", [])
        ):
            raise ContractError(f"P06 forbidden feature source leaked: {feature['name']}")
    return {
        "feature_columns_scanned": len(metadata_names),
        "trajectory_columns_scanned": len(trajectory_names),
        "forbidden_predictor_tokens": list(prohibited),
        "truth_leakage_found": 0,
        "market_leakage_found": 0,
        "madis_leakage_found": 0,
        "outcome_leakage_found": 0,
        "fold_or_prediction_leakage_found": 0,
    }


def _freeze_inventory(root: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
    paths: set[str] = {
        "RAFM_V375_UNIVERSAL_MODELING_PREFIT_PLAN.md",
        "pyproject.toml",
        "environment/prefit/v1/environment.json",
        "reports/kden_v375_acquisition_freeze_manifest.json",
        RELEASE_INDEX_PATH,
        RELEASE_MANIFEST_PATH,
        ISSUE_OUTPUT_PATH,
        SELECTION_OUTPUT_PATH,
        ISSUE_VIEW_CONTRACT_PATH,
        REGISTRY_PATH,
        STATIC_TRAJECTORY_PATH,
        CONFIG_PATH,
        FEATURE_ERRATA_PATH,
        RUN_STATE_SCHEMA_PATH,
        FREEZE_SCHEMA_PATH,
        FINAL_PASS_SCHEMA_PATH,
        FEATURE_ERRATA_SCHEMA_PATH,
        RUNBOOK_PATH,
        "src/kden_v375/prefit/cli.py",
        "src/kden_v375/prefit/p01_foundation.py",
        "src/kden_v375/prefit/p02_rules.py",
        "src/kden_v375/prefit/p02_truth.py",
        "src/kden_v375/prefit/p03_issue_spine.py",
        "src/kden_v375/prefit/p04_features.py",
        "src/kden_v375/prefit/p05_materialization.py",
        "src/kden_v375/prefit/p06_acceptance.py",
        "src/kden_v375/prefit/records.py",
        "src/kden_v375/archive_readers.py",
        "src/kden_v375/contracts.py",
        "src/kden_v375/hashes.py",
        "src/kden_v375/r14.py",
        "src/kden_v375/time.py",
        "tests/unit/test_prefit_p06_acceptance.py",
        "hrrr_v4_local_archive/common/cycle_schedule_r14/cycle_schedule_r14_v375.parquet",
        "hrrr_v4_local_archive/common/cycle_schedule_r14/cycle_schedule_r14_v375_manifest.json",
        "registries/registry_bundle_r14_v375.json",
    }
    for stage in range(1, 6):
        paths.add(f"state/PREFIT_P{stage:02d}_PASS.json")
    for path in sorted((root / "config/prefit").glob("*.json")):
        paths.add(_relative(root, path))
    for path in sorted((root / "schemas/prefit").glob("*.json")):
        paths.add(_relative(root, path))
    for group in ("year_partitions",):
        for row in manifest["trajectory_catalog"][group]:
            paths.add(str(row["path"]))
        for row in manifest["deterministic_features"][group]:
            paths.add(str(row["path"]))
    return {relative: sha256_file(_inside(root, relative)) for relative in sorted(paths)}


def _gate_evidence(
    checkpoints: Sequence[Mapping[str, Any]],
    *,
    leakage: Mapping[str, Any],
    isolation: Mapping[str, Any],
    range_errata: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    evidence = [item["evidence"] for item in checkpoints]
    issue = next(item for item in evidence if "issue_rows" in item)
    selections = next(item for item in evidence if "selection_rows" in item)
    static = next(item for item in evidence if item.get("static_field") == "H14")
    anchors = next(item for item in evidence if "anchor_rebuild_count" in item)
    yearly = [item for item in evidence if "year" in item]
    feature_rows = sum(int(item["feature_rows"]) for item in yearly)
    dynamic_rows = sum(int(item["trajectory_rows"]) for item in yearly)
    missing_rows = sum(int(item["missing_trajectory_rows"]) for item in yearly)
    source_files = sum(int(item["canonical_source_files_hashed"]) for item in yearly)
    if (
        issue["issue_rows"] != EXPECTED_ISSUE_ROWS
        or selections["selection_rows"] != EXPECTED_SELECTION_ROWS
        or feature_rows != EXPECTED_FEATURE_ROWS
        or dynamic_rows != EXPECTED_DYNAMIC_TRAJECTORY_ROWS
        or dynamic_rows + int(static["trajectory_rows"]) != EXPECTED_TRAJECTORY_ROWS
        or missing_rows != EXPECTED_DYNAMIC_MISSING_TRAJECTORY_ROWS
        or source_files != EXPECTED_SCHEDULE_ROWS
        or len(yearly) != len(TARGET_YEARS)
    ):
        raise ContractError("P06 acceptance totals do not reconcile")
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "release_id": SUBSTRATE_RELEASE_ID,
        "target_day_count": issue["target_days"],
        "issue_row_count": issue["issue_rows"],
        "selection_row_count": selections["selection_rows"],
        "feature_row_count": feature_rows,
        "feature_count": EXPECTED_FEATURE_COUNT,
        "feature_range_errata_id": FEATURE_ERRATA_ID,
        "feature_range_errata_count": len(range_errata),
        "feature_range_errata_names": sorted(range_errata),
        "dynamic_trajectory_row_count": dynamic_rows,
        "static_trajectory_row_count": int(static["trajectory_rows"]),
        "total_trajectory_row_count": dynamic_rows + int(static["trajectory_rows"]),
        "explicit_missing_trajectory_row_count": missing_rows,
        "canonical_source_files_hashed": source_files,
        "target_year_partition_count": len(yearly),
        "clock_equations_verified": True,
        "right_open_windows_verified": True,
        "issue_time_availability_verified": True,
        "lead_horizon_interval_units_verified": True,
        "spatial_and_coordinate_era_rules_verified": True,
        "dst_verified": True,
        "explicit_missingness_verified": True,
        "anchor_rebuild_count": anchors["anchor_rebuild_count"],
        "anchor_rebuilds_exact": anchors["anchor_rows_exactly_match_p05"],
        "model_neutral_leakage_scan": dict(leakage),
        "runtime_isolation": {
            key: value for key, value in isolation.items() if key != "source_files_scanned"
        },
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "market_rows_read": 0,
        "madis_rows_read": 0,
        "model_fits_performed": 0,
    }


def _publish_freeze(
    root: Path,
    *,
    manifest: Mapping[str, Any],
    checkpoints_path: Path,
    gates: Mapping[str, Any],
    accepted_at: str,
) -> dict[str, Any]:
    frozen = _freeze_inventory(root, manifest)
    authorities = {
        **{
            f"PREFIT_P{stage:02d}": _prefit_pass_identity(root, stage)["record_sha256"]
            for stage in range(1, 6)
        },
        "ACQUISITION_FREEZE": sha256_file(root / "reports/kden_v375_acquisition_freeze_manifest.json"),
        "P05_RELEASE_INDEX": sha256_file(root / RELEASE_INDEX_PATH),
        "P05_RELEASE_MANIFEST": sha256_file(root / RELEASE_MANIFEST_PATH),
        "P04_FEATURE_REGISTRY": sha256_file(root / REGISTRY_PATH),
        "P06_FEATURE_RANGE_ERRATA": sha256_file(root / FEATURE_ERRATA_PATH),
        "R14_CYCLE_SCHEDULE": sha256_file(
            root
            / "hrrr_v4_local_archive/common/cycle_schedule_r14/cycle_schedule_r14_v375.parquet"
        ),
    }
    body = {
        "schema_version": FREEZE_SCHEMA,
        "release_id": SUBSTRATE_RELEASE_ID,
        "status": "FROZEN_ACCEPTED",
        "accepted_at_utc": accepted_at,
        "p05_record_sha256": EXPECTED_P05_SHA256,
        "authorities": dict(sorted(authorities.items())),
        "frozen_files": frozen,
        "acceptance_checkpoint_digest": sha256_path(checkpoints_path),
        "gate_evidence": dict(gates),
    }
    value = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    publish_immutable_json(root / FREEZE_PATH, value)
    return value


def _report_bytes(gates: Mapping[str, Any], freeze: Mapping[str, Any]) -> bytes:
    leakage = gates["model_neutral_leakage_scan"]
    lines = [
        "# P06 Universal Issue-State Acceptance Report",
        "",
        f"Status: **PASS — FROZEN_ACCEPTED**  ",
        f"Release: `{SUBSTRATE_RELEASE_ID}`  ",
        f"Accepted at: `{freeze['accepted_at_utc']}`  ",
        f"Freeze record: `{freeze['record_sha256']}`",
        "",
        "## Reconciled coverage",
        "",
        f"- Target days: {gates['target_day_count']:,}",
        f"- Issue states: {gates['issue_row_count']:,}",
        f"- Independent product selections: {gates['selection_row_count']:,}",
        f"- Deterministic feature rows: {gates['feature_row_count']:,}",
        f"- Frozen deterministic features: {gates['feature_count']:,}",
        f"- Dynamic trajectory references: {gates['dynamic_trajectory_row_count']:,}",
        f"- Static H14 references: {gates['static_trajectory_row_count']:,}",
        f"- Explicit missing trajectory rows: {gates['explicit_missing_trajectory_row_count']:,}",
        f"- Canonical source bundles rehashed: {gates['canonical_source_files_hashed']:,}",
        "",
        "## Acceptance gates",
        "",
        "- Clock equations, issue-time availability, and right-open windows passed.",
        "- Lead, horizon, interval, unit, spatial, DST, and coordinate-era rules passed.",
        "- Full feature ranges and explicit Arrow-null missingness passed.",
        (
            f"- {gates['feature_range_errata_count']} narrow acceptance-only range "
            "errata were applied and frozen; no P04/P05 data were changed."
        ),
        f"- {gates['anchor_rebuild_count']} declared archive anchors rebuilt exactly.",
        "- Target, market, MADIS, outcome, fold, and prediction leakage scans passed.",
        "- Runtime isolation from fossilized codebases passed.",
        "",
        "## Isolation",
        "",
        f"- Predictor columns scanned: {leakage['feature_columns_scanned']}",
        "- Truth values read: 0",
        "- Market rows read: 0",
        "- MADIS rows read: 0",
        "- Model fits performed: 0",
        "- Network requests made: 0",
        "",
        "P06 accepts and freezes the target-free universal substrate. Truth remains",
        "physically separate under `truth/kden_tmax/v1`; fold assignment and model",
        "adapters remain P07 work.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _publish_report(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise StaleStateError(f"immutable P06 report differs: {path}")
        return sha256_file(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _publish_final_pass(
    root: Path,
    *,
    gates: Mapping[str, Any],
    freeze: Mapping[str, Any],
    report_sha256: str,
) -> dict[str, Any]:
    body = {
        "schema_version": FINAL_PASS_SCHEMA,
        "release_id": SUBSTRATE_RELEASE_ID,
        "status": "PASS",
        "accepted_at_utc": freeze["accepted_at_utc"],
        "p05_record_sha256": EXPECTED_P05_SHA256,
        "freeze_manifest_sha256": sha256_file(root / FREEZE_PATH),
        "acceptance_report_sha256": report_sha256,
        "gate_evidence": dict(gates),
    }
    value = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    publish_immutable_json(root / FINAL_PASS_PATH, value)
    return value


def run_p06(
    *, project_root: Path | str, run_id: str, resume: bool = False
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if (root / PASS_PATH).is_file():
        return verify_p06(root)
    predecessor = _predecessor(root)
    config = _load_config(root)
    p06_preflight(root)
    manifest, _ = _release_authority(root)
    features, registry_hash = _load_feature_authority(root)
    range_errata, range_errata_hash = _load_feature_range_errata(
        root,
        registry_hash=registry_hash,
        features=features,
    )
    field_contracts = _load_field_contracts(root)
    schedule_rows, _schedule_path, schedule_hash = _load_schedule_authority(root)
    state = _initialize_state(root, run_id)
    resumable = {"INITIALIZED", "PAUSED", "PAUSE_REQUESTED", "FAILED"}
    if resume and state["status"] not in resumable:
        raise ContractError(f"P06 run is not resumable from {state['status']}")
    if not resume and state["status"] not in {"INITIALIZED", "FAILED"}:
        raise ContractError(f"P06 run already exists in {state['status']}; use resume-p06")
    paths = _run_paths(root, run_id)
    pause = PauseController(paths["pause"])
    if resume:
        pause.clear()
    with ExclusiveRunLock(load_project_paths(root).state / "PREFIT_P06.lock"):
        pause.install()
        _update_state(
            root,
            run_id,
            status="RUNNING",
            phase="FULL_SUBSTRATE_ACCEPTANCE",
            started_at_utc=state.get("started_at_utc") or utc_now(),
            message="resumed" if resume else "started",
        )
        try:
            issues_by_id, selections_by_issue = _load_authority_maps(root)
            _completed_summary(root, run_id)
            checkpoints: list[dict[str, Any]] = []

            unit_id = "issue-spine"
            checkpoint = _checkpoint(root, run_id, unit_id)
            if checkpoint is None:
                pause.raise_if_requested()
                started = time.monotonic()
                evidence = _scan_issue_spine(
                    root, run_id, manifest["issue_spine"]["sha256"]
                )
                checkpoint = _publish_checkpoint(
                    root,
                    run_id,
                    unit_id,
                    evidence=evidence,
                    input_hashes={ISSUE_OUTPUT_PATH: manifest["issue_spine"]["sha256"]},
                    elapsed_seconds=time.monotonic() - started,
                )
            checkpoints.append(checkpoint)
            _commit_unit(root, run_id, checkpoint)
            _publish_completed_progress(root, run_id, checkpoints)

            unit_id = "selected-cycles"
            checkpoint = _checkpoint(root, run_id, unit_id)
            if checkpoint is None:
                pause.raise_if_requested()
                started = time.monotonic()
                evidence = _scan_selected_cycles(
                    root,
                    run_id,
                    manifest["selected_cycles"]["sha256"],
                    issues_by_id,
                    schedule_rows,
                )
                checkpoint = _publish_checkpoint(
                    root,
                    run_id,
                    unit_id,
                    evidence=evidence,
                    input_hashes={SELECTION_OUTPUT_PATH: manifest["selected_cycles"]["sha256"]},
                    elapsed_seconds=time.monotonic() - started,
                )
            checkpoints.append(checkpoint)
            _commit_unit(root, run_id, checkpoint)
            _publish_completed_progress(root, run_id, checkpoints)

            unit_id = "static-h14"
            checkpoint = _checkpoint(root, run_id, unit_id)
            if checkpoint is None:
                pause.raise_if_requested()
                started = time.monotonic()
                static_hash = manifest["trajectory_catalog"]["static"]["sha256"]
                checkpoint = _publish_checkpoint(
                    root,
                    run_id,
                    unit_id,
                    evidence=_scan_static(root, static_hash),
                    input_hashes={STATIC_TRAJECTORY_PATH: static_hash},
                    elapsed_seconds=time.monotonic() - started,
                )
            checkpoints.append(checkpoint)
            _commit_unit(root, run_id, checkpoint)
            _publish_completed_progress(root, run_id, checkpoints)

            completed_features = sum(
                int(item["evidence"].get("feature_rows", 0)) for item in checkpoints
            )
            completed_trajectories = sum(
                int(item["evidence"].get("trajectory_rows", 0)) for item in checkpoints
            )
            for year in TARGET_YEARS:
                unit_id = f"target-year-{year}"
                checkpoint = _checkpoint(root, run_id, unit_id)
                if checkpoint is None:
                    pause.raise_if_requested()
                    started = time.monotonic()
                    evidence, hashes = _scan_year(
                        root,
                        run_id,
                        year=year,
                        manifest=manifest,
                        issues_by_id=issues_by_id,
                        selections_by_issue=selections_by_issue,
                        features=features,
                        range_errata=range_errata,
                        field_contracts=field_contracts,
                        schedule_rows=schedule_rows,
                        feature_base=completed_features,
                        trajectory_base=completed_trajectories,
                        pause=pause,
                    )
                    checkpoint = _publish_checkpoint(
                        root,
                        run_id,
                        unit_id,
                        evidence=evidence,
                        input_hashes=hashes,
                        elapsed_seconds=time.monotonic() - started,
                    )
                checkpoints.append(checkpoint)
                _commit_unit(root, run_id, checkpoint)
                completed_features += int(checkpoint["evidence"].get("feature_rows", 0))
                completed_trajectories += int(checkpoint["evidence"].get("trajectory_rows", 0))
                _publish_completed_progress(root, run_id, checkpoints)

            unit_id = "anchor-rebuilds"
            checkpoint = _checkpoint(root, run_id, unit_id)
            if checkpoint is None:
                pause.raise_if_requested()
                started = time.monotonic()
                evidence = _scan_anchors(root, config, features)
                anchor_hashes: dict[str, str] = {}
                for case in config["anchor_cases"]:
                    year = date.fromisoformat(case["target_date"]).year
                    entry = _feature_partition_for_year(manifest, year)
                    anchor_hashes[str(entry["path"])] = str(entry["sha256"])
                checkpoint = _publish_checkpoint(
                    root,
                    run_id,
                    unit_id,
                    evidence=evidence,
                    input_hashes=anchor_hashes,
                    elapsed_seconds=time.monotonic() - started,
                )
            checkpoints.append(checkpoint)
            _commit_unit(root, run_id, checkpoint)
            completed = [item["unit_id"] for item in checkpoints]
            _update_state(
                root,
                run_id,
                phase="FREEZE_RELEASE",
                completed_units=completed,
                completed_acceptance_units=len(completed),
                completed_feature_rows=EXPECTED_FEATURE_ROWS,
                completed_trajectory_rows=EXPECTED_TRAJECTORY_ROWS,
                current_unit=None,
                current_rows_completed=None,
                current_rows_expected=None,
                message="acceptance scans complete; publishing immutable freeze",
            )
            leakage = _check_leakage(config, features)
            isolation = validate_runtime_isolation(root)
            gates = _gate_evidence(
                checkpoints,
                leakage=leakage,
                isolation=isolation,
                range_errata=range_errata,
            )
            accepted_at = max(str(item["completed_at_utc"]) for item in checkpoints)
            freeze = _publish_freeze(
                root,
                manifest=manifest,
                checkpoints_path=paths["checkpoints"],
                gates=gates,
                accepted_at=accepted_at,
            )
            report_hash = _publish_report(root / REPORT_PATH, _report_bytes(gates, freeze))
            final = _publish_final_pass(
                root,
                gates=gates,
                freeze=freeze,
                report_sha256=report_hash,
            )
            artifact_paths = [
                CONFIG_PATH,
                FEATURE_ERRATA_PATH,
                RUN_STATE_SCHEMA_PATH,
                FREEZE_SCHEMA_PATH,
                FINAL_PASS_SCHEMA_PATH,
                FEATURE_ERRATA_SCHEMA_PATH,
                RUNBOOK_PATH,
                REPORT_PATH,
                FREEZE_PATH,
                FINAL_PASS_PATH,
                "src/kden_v375/prefit/cli.py",
                "src/kden_v375/prefit/p06_acceptance.py",
                _relative(root, paths["checkpoints"]),
                _relative(root, paths["journal"]),
            ]
            record = write_prefit_pass(
                root,
                stage_no=6,
                run_id=run_id,
                artifact_paths=artifact_paths,
                predecessor_hashes={"PREFIT_P05": predecessor["record_sha256"]},
                authority_hashes={
                    "P04_FEATURE_REGISTRY": registry_hash,
                    "P06_FEATURE_RANGE_ERRATA": range_errata_hash,
                    "P05_RELEASE_INDEX": sha256_file(root / RELEASE_INDEX_PATH),
                    "P05_RELEASE_MANIFEST": sha256_file(root / RELEASE_MANIFEST_PATH),
                    "R14_CYCLE_SCHEDULE": schedule_hash,
                    "P06_FREEZE_MANIFEST": sha256_file(root / FREEZE_PATH),
                    "UNIVERSAL_ISSUE_STATE_PASS": final["record_sha256"],
                },
                gate_evidence={
                    **gates,
                    "substrate_freeze_record_sha256": freeze["record_sha256"],
                    "universal_issue_state_pass_sha256": final["record_sha256"],
                },
            )
        except PauseRequested as exc:
            _update_state(
                root,
                run_id,
                status="PAUSED",
                message=str(exc),
                current_unit=None,
                current_rows_completed=None,
                current_rows_expected=None,
            )
            return {"run_id": run_id, "stage_id": "PREFIT_P06", "status": "PAUSED"}
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
                message="P06 gate passed; universal issue-state release is frozen",
                completed_at_utc=utc_now(),
                completed_units=list(ACCEPTANCE_UNITS),
                completed_acceptance_units=len(ACCEPTANCE_UNITS),
                completed_feature_rows=EXPECTED_FEATURE_ROWS,
                completed_trajectory_rows=EXPECTED_TRAJECTORY_ROWS,
                current_unit=None,
                current_rows_completed=None,
                current_rows_expected=None,
                record_sha256=record["record_sha256"],
            )
            return record
        finally:
            pause.restore()


def _eta_snapshot(root: Path, run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    if state["status"] == "PASS":
        return {"status": "COMPLETE", "remaining_seconds": 0}
    if state["status"] in {"FAILED", "PAUSED"}:
        return {"status": "UNAVAILABLE", "reason": f"run is {state['status']}"}
    recent = [
        row
        for row in _journal_records(_run_paths(root, run_id)["journal"])
        if int(row.get("trajectory_rows", 0)) > 1_000
    ][-3:]
    sampled_rows = sum(
        int(row.get("feature_rows", 0)) + int(row.get("trajectory_rows", 0))
        for row in recent
    )
    elapsed = sum(float(row.get("elapsed_seconds", 0)) for row in recent)
    if sampled_rows <= 0 or elapsed <= 0:
        return {
            "status": "UNAVAILABLE",
            "reason": "no completed target-year scan is available for a representative ETA",
        }
    rate = sampled_rows / elapsed
    expected_rows = EXPECTED_FEATURE_ROWS + EXPECTED_TRAJECTORY_ROWS
    completed_rows = int(state.get("completed_feature_rows", 0)) + int(
        state.get("completed_trajectory_rows", 0)
    )
    remaining = max(0, expected_rows - completed_rows)
    return {
        "status": "AVAILABLE",
        "basis": "recent_complete_target_year_row_throughput",
        "sample_year_partitions": len(recent),
        "sample_rows": sampled_rows,
        "recent_rate_rows_per_second": rate,
        "remaining_rows": remaining,
        "remaining_seconds": remaining / rate,
        "note": "estimate begins after the first complete target-year scan and includes canonical source rehashing",
    }


def p06_eta(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_prefit_run_id(run_id, stage_no=6)
    state = _read_json(_run_paths(root, run_id)["state"])
    return {
        "schema_version": "KDEN_V375_PREFIT_P06_ETA_V1",
        "run_id": run_id,
        "observed_at_utc": utc_now(),
        "run_status": state["status"],
        "phase": state["phase"],
        "eta": _eta_snapshot(root, run_id, state),
    }


def p06_status(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_prefit_run_id(run_id, stage_no=6)
    state = _read_json(_run_paths(root, run_id)["state"])
    return {
        **state,
        "acceptance_report_path": REPORT_PATH,
        "freeze_manifest_path": FREEZE_PATH,
        "final_pass_path": FINAL_PASS_PATH,
        "eta": _eta_snapshot(root, run_id, state),
    }


def p06_pause(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = _run_paths(root, run_id)
    state = _read_json(paths["state"])
    if state["status"] not in {"RUNNING", "PAUSE_REQUESTED"}:
        raise ContractError(f"P06 run is not active: {state['status']}")
    atomic_write_json(
        paths["pause"],
        {"schema_version": "KDEN_V375_PAUSE_REQUEST_V1", "requested_at_utc": utc_now()},
        replace=True,
    )
    return _update_state(
        root,
        run_id,
        status="PAUSE_REQUESTED",
        message=(
            "cooperative pause requested; the current scan batch will stop, and an "
            "incomplete year will be rescanned on resume"
        ),
    )


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "unavailable"
    remaining = max(0, int(seconds))
    days, remaining = divmod(remaining, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes, seconds = divmod(remaining, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"


def p06_live_status(
    project_root: Path | str,
    run_id: str,
    *,
    interval_seconds: float = 5,
    json_lines: bool = False,
) -> None:
    if interval_seconds <= 0:
        raise ContractError("live-status interval must be positive")
    while True:
        snapshot = p06_status(project_root, run_id)
        if json_lines:
            print(json.dumps(snapshot, sort_keys=True), flush=True)
        else:
            eta = snapshot["eta"]
            eta_text = (
                "complete"
                if eta.get("status") == "COMPLETE"
                else _format_duration(eta.get("remaining_seconds"))
                if eta.get("status") == "AVAILABLE"
                else "unavailable"
            )
            current = "-"
            if snapshot.get("current_rows_expected") is not None:
                current = (
                    f"{snapshot.get('current_rows_completed', 0)}/"
                    f"{snapshot['current_rows_expected']}"
                )
            print(
                f"[{utc_now()}] | {snapshot['status']} | phase={snapshot['phase']} | "
                f"units={snapshot['completed_acceptance_units']}/"
                f"{snapshot['expected_acceptance_units']} | "
                f"features={snapshot['completed_feature_rows']}/"
                f"{snapshot['expected_feature_rows']} | "
                f"trajectory-refs={snapshot['completed_trajectory_rows']}/"
                f"{snapshot['expected_trajectory_rows']} | "
                f"current={snapshot.get('current_unit') or '-'} | rows={current} | ETA={eta_text}",
                flush=True,
            )
        if snapshot["status"] in {"PASS", "FAILED", "PAUSED"}:
            return
        time.sleep(interval_seconds)


def _verify_record_hash(value: Mapping[str, Any], *, label: str) -> None:
    body = dict(value)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise StaleStateError(f"{label} record hash changed")


def verify_p06(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    record = verify_prefit_pass(root, 6)
    predecessor = _predecessor(root)
    if record.get("predecessor_hashes") != {"PREFIT_P05": predecessor["record_sha256"]}:
        raise StaleStateError("P06 predecessor changed")
    freeze = _read_json(root / FREEZE_PATH)
    final = _read_json(root / FINAL_PASS_PATH)
    if (
        freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze.get("release_id") != SUBSTRATE_RELEASE_ID
        or freeze.get("status") != "FROZEN_ACCEPTED"
        or final.get("schema_version") != FINAL_PASS_SCHEMA
        or final.get("release_id") != SUBSTRATE_RELEASE_ID
        or final.get("status") != "PASS"
    ):
        raise ContractError("P06 final identity changed")
    _verify_record_hash(freeze, label="P06 freeze manifest")
    _verify_record_hash(final, label="P06 universal substrate PASS")
    if (
        final.get("p05_record_sha256") != EXPECTED_P05_SHA256
        or final.get("freeze_manifest_sha256") != sha256_file(root / FREEZE_PATH)
        or final.get("acceptance_report_sha256") != sha256_file(root / REPORT_PATH)
    ):
        raise StaleStateError("P06 final authority hashes changed")
    for relative, expected in freeze["frozen_files"].items():
        if sha256_file(_inside(root, relative)) != expected:
            raise StaleStateError(f"P06 frozen file changed: {relative}")
    isolation = validate_runtime_isolation(root)
    return {
        "status": "VALID",
        "validated_stage": "PREFIT_P06",
        "record_sha256": record["record_sha256"],
        "release_id": SUBSTRATE_RELEASE_ID,
        "release_status": "FROZEN_ACCEPTED",
        "freeze_manifest_path": FREEZE_PATH,
        "freeze_record_sha256": freeze["record_sha256"],
        "final_pass_path": FINAL_PASS_PATH,
        "final_pass_sha256": final["record_sha256"],
        "frozen_file_count": len(freeze["frozen_files"]),
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "model_fits_performed": 0,
        "runtime_isolation": {
            key: value for key, value in isolation.items() if key != "source_files_scanned"
        },
    }
