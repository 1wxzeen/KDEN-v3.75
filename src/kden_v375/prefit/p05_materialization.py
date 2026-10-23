"""P05: materialize the complete target-free universal issue-state substrate."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..archive_readers import R14ArchiveReader, load_issue_view_contract
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
from ..io.atomic import (
    atomic_publish_file,
    atomic_write_bytes,
    atomic_write_json,
    fsync_directory,
)
from ..time import as_utc
from .p03_issue_spine import (
    EXPECTED_ISSUE_ROWS,
    EXPECTED_TARGET_DAYS,
    ISSUE_OUTPUT_PATH,
    PRODUCT_ORDER,
    SELECTION_OUTPUT_PATH,
    STUDY_END,
    STUDY_START,
    _inclusive_dates,
)
from .p04_features import (
    CONFIG_PATH as P04_CONFIG_PATH,
    PANEL_SCHEMA_ID,
    REGISTRY_ID,
    REGISTRY_PATH,
    build_feature_registry,
    compute_issue_feature_row,
    feature_panel_schema,
)
from .records import (
    make_prefit_run_id,
    utc_now,
    validate_prefit_run_id,
    verify_prefit_pass,
    write_prefit_pass,
)


STAGE_NO = 5
CONFIG_PATH = "config/prefit/p05_materialization_v375.json"
TRAJECTORY_SCHEMA_PATH = "schemas/prefit/trajectory_catalog_v375.json"
RUN_STATE_SCHEMA_PATH = "schemas/prefit/p05_run_state_v375.json"
RELEASE_SCHEMA_PATH = "schemas/prefit/p05_release_manifest_v375.json"
RUNBOOK_PATH = "reports/prefit/P05_OWNER_RUNBOOK.md"
REPORT_PATH = "reports/prefit/P05_MATERIALIZATION_REPORT.md"
RELEASE_MANIFEST_PATH = "universal_issue_state/v1/manifests/p05_release_manifest.json"
RELEASE_INDEX_PATH = "universal_issue_state/v1/release_index.json"
TRAJECTORY_ROOT = "universal_issue_state/v1/trajectory_catalog"
FEATURE_ROOT = "universal_issue_state/v1/deterministic_features"
STATIC_TRAJECTORY_PATH = f"{TRAJECTORY_ROOT}/static/h14.parquet"
PASS_PATH = "state/PREFIT_P05_PASS.json"

CONFIG_SCHEMA = "KDEN_V375_PREFIT_P05_CONFIG_V1"
RUN_STATE_SCHEMA = "KDEN_V375_PREFIT_P05_RUN_V1"
DAY_CHECKPOINT_SCHEMA = "KDEN_V375_PREFIT_P05_DAY_CHECKPOINT_V1"
YEAR_CHECKPOINT_SCHEMA = "KDEN_V375_PREFIT_P05_YEAR_CHECKPOINT_V1"
TRAJECTORY_SCHEMA_ID = "KDEN_V375_TRAJECTORY_CATALOG_V1"
RELEASE_MANIFEST_SCHEMA = "KDEN_V375_P05_RELEASE_MANIFEST_V1"
RELEASE_INDEX_SCHEMA = "KDEN_V375_UNIVERSAL_ISSUE_STATE_INDEX_V1"
SUBSTRATE_RELEASE_ID = "KDEN_V375_UNIVERSAL_ISSUE_STATE_V1"
EXPECTED_P04_SHA256 = (
    "70515a2e73fbe0cef9775d01a566fbbd03f10e81978de3d96a728e4615227dc2"
)
EXPECTED_DYNAMIC_TRAJECTORY_ROWS = 8_919_597
EXPECTED_DYNAMIC_MISSING_TRAJECTORY_ROWS = 12
EXPECTED_STATIC_TRAJECTORY_ROWS = 1
EXPECTED_TRAJECTORY_ROWS = 8_919_598
EXPECTED_FEATURE_ROWS = EXPECTED_ISSUE_ROWS
TARGET_YEARS = tuple(range(STUDY_START.year, STUDY_END.year + 1))


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


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ContractError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def _stable_id(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}_{sha256_bytes(canonical_json_bytes(dict(value)))}"


def time_support_id(row: Mapping[str, Any]) -> str:
    return _stable_id(
        "TIME_SUPPORT",
        {
            "step_type": str(row["step_type"]),
            "interval_start_utc": as_utc(row["interval_start_utc"])
            .isoformat()
            .replace("+00:00", "Z"),
            "interval_end_utc": as_utc(row["interval_end_utc"])
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )


def trajectory_state_id(
    row: Mapping[str, Any], *, spatial_contract_id: str
) -> str:
    support_id = time_support_id(row)
    return _stable_id(
        "TRAJECTORY_STATE",
        {
            "product": str(row["product"]),
            "field_registry_id": str(row["field_registry_id"]),
            "cycle_init_utc": as_utc(row["cycle_init_utc"])
            .isoformat()
            .replace("+00:00", "Z"),
            "valid_time_utc": as_utc(row["valid_time_utc"])
            .isoformat()
            .replace("+00:00", "Z"),
            "time_support_id": support_id,
            "spatial_contract_id": spatial_contract_id,
        },
    )


def trajectory_catalog_schema() -> pa.Schema:
    timestamp = pa.timestamp("us", tz="UTC")
    return pa.schema(
        [
            pa.field("trajectory_state_id", pa.string(), nullable=False),
            pa.field("target_date", pa.date32(), nullable=False),
            pa.field("product", pa.string(), nullable=False),
            pa.field("field_registry_id", pa.string(), nullable=False),
            pa.field("cycle_init_utc", timestamp, nullable=False),
            pa.field("valid_time_utc", timestamp, nullable=False),
            pa.field("forecast_lead_min", pa.int32(), nullable=False),
            pa.field("interval_start_utc", timestamp, nullable=False),
            pa.field("interval_end_utc", timestamp, nullable=False),
            pa.field("time_support_id", pa.string(), nullable=False),
            pa.field("parameter", pa.string(), nullable=False),
            pa.field("level", pa.string(), nullable=False),
            pa.field("step_type", pa.string(), nullable=False),
            pa.field("native_unit", pa.string(), nullable=False),
            pa.field("canonical_unit", pa.string(), nullable=False),
            pa.field("spatial_contract_id", pa.string(), nullable=False),
            pa.field("local_value_column", pa.string(), nullable=False),
            pa.field("tile_values_available", pa.bool_(), nullable=False),
            pa.field("regional_values_available", pa.bool_(), nullable=False),
            pa.field("regional_spatial_contract_id", pa.string(), nullable=False),
            pa.field("regional_operator", pa.string()),
            pa.field("regional_support_count", pa.int8(), nullable=False),
            pa.field("regional_coverage_mask", pa.int16(), nullable=False),
            pa.field("station_id", pa.string(), nullable=False),
            pa.field("station_coord_era", pa.string(), nullable=False),
            pa.field("grid_geometry_id", pa.string(), nullable=False),
            pa.field("coverage_flag", pa.string(), nullable=False),
            pa.field("missing_reason", pa.string()),
            pa.field("selector_identity", pa.string(), nullable=False),
            pa.field("source_idx_hash_hex", pa.string(), nullable=False),
            pa.field("payload_hash_hex", pa.string()),
            pa.field("canonical_archive_path", pa.string(), nullable=False),
            pa.field("canonical_archive_row_ordinal", pa.int32(), nullable=False),
            pa.field("canonical_archive_sha256", pa.string(), nullable=False),
            pa.field("hrrr_version", pa.string(), nullable=False),
            pa.field("derivation_version", pa.string(), nullable=False),
        ],
        metadata={
            b"schema_version": b"KDEN_V375_PARQUET_SCHEMA_V1",
            b"schema_id": TRAJECTORY_SCHEMA_ID.encode("ascii"),
            b"reference_only": b"true",
            b"canonical_values_duplicated": b"false",
        },
    )


def trajectory_schema_document() -> dict[str, Any]:
    schema = trajectory_catalog_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "KDEN_V375_TRAJECTORY_CATALOG_SCHEMA_V1",
        "schema_id": TRAJECTORY_SCHEMA_ID,
        "format": "parquet",
        "primary_key": ["trajectory_state_id"],
        "natural_key": [
            "product",
            "field_registry_id",
            "cycle_init_utc",
            "valid_time_utc",
            "time_support_id",
            "spatial_contract_id",
        ],
        "columns": [
            {
                "name": field.name,
                "arrow_type": str(field.type),
                "nullable": field.nullable,
            }
            for field in schema
        ],
        "reference_contract": {
            "canonical_r14_values_are_referenced_not_duplicated": True,
            "source_locator": [
                "canonical_archive_path",
                "canonical_archive_row_ordinal",
                "canonical_archive_sha256",
            ],
            "value_column_locator": "local_value_column",
            "target_values_allowed": False,
        },
        "forbidden_columns": [
            "bi_value",
            "nn_value",
            "tile_values",
            "regional_value_00",
            "y_audited_f",
            "truth_qc_status",
            "market_price",
            "settlement",
            "madis_temperature",
        ],
    }


def _parquet_bytes(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> bytes:
    table = pa.Table.from_pylist(list(rows), schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        version="2.6",
        write_statistics=True,
        use_dictionary=True,
        row_group_size=65536,
    )
    return sink.getvalue().to_pybytes()


def _load_config(root: Path) -> dict[str, Any]:
    config = _read_json(root / CONFIG_PATH)
    if config.get("schema_version") != CONFIG_SCHEMA:
        raise ContractError("unsupported P05 configuration schema")
    expected = {
        "substrate_release_id": SUBSTRATE_RELEASE_ID,
        "trajectory_schema_id": TRAJECTORY_SCHEMA_ID,
        "feature_panel_schema_id": PANEL_SCHEMA_ID,
        "feature_registry_id": REGISTRY_ID,
        "predecessor_p04_record_sha256": EXPECTED_P04_SHA256,
        "expected_target_days": EXPECTED_TARGET_DAYS,
        "expected_feature_rows": EXPECTED_FEATURE_ROWS,
        "expected_dynamic_trajectory_rows": EXPECTED_DYNAMIC_TRAJECTORY_ROWS,
        "expected_dynamic_missing_trajectory_rows": EXPECTED_DYNAMIC_MISSING_TRAJECTORY_ROWS,
        "expected_static_trajectory_rows": EXPECTED_STATIC_TRAJECTORY_ROWS,
        "expected_total_trajectory_rows": EXPECTED_TRAJECTORY_ROWS,
    }
    for key, value in expected.items():
        if config.get(key) != value:
            raise ContractError(f"P05 frozen configuration changed: {key}")
    if config.get("execution") != {
        "network_allowed": False,
        "truth_reads_allowed": False,
        "model_fitting_allowed": False,
        "owner_run_required": True,
    }:
        raise ContractError("P05 execution boundary changed")
    if _read_json(root / TRAJECTORY_SCHEMA_PATH) != trajectory_schema_document():
        raise StaleStateError("P05 trajectory schema document changed")
    for required_path in (RUN_STATE_SCHEMA_PATH, RELEASE_SCHEMA_PATH):
        if not (root / required_path).is_file():
            raise ContractError(f"P05 schema is missing: {required_path}")
    return config


def _predecessor(root: Path) -> dict[str, Any]:
    record = verify_prefit_pass(root, 4)
    if record.get("record_sha256") != EXPECTED_P04_SHA256:
        raise StaleStateError("P05 requires the accepted P04 feature contract")
    return record


def _load_feature_authority(root: Path) -> tuple[list[dict[str, Any]], str]:
    config = _read_json(root / P04_CONFIG_PATH)
    generated = build_feature_registry(config)
    published = _read_json(root / REGISTRY_PATH)
    if published.get("registry_id") != REGISTRY_ID:
        raise ContractError("P04 feature registry identity changed")
    if published.get("features") != generated:
        raise StaleStateError("P04 registry and deterministic generator disagree")
    return generated, sha256_file(root / REGISTRY_PATH)


def _load_field_contracts(root: Path) -> dict[str, dict[str, Any]]:
    bundle = _read_json(root / "registries/registry_bundle_r14_v375.json")
    result: dict[str, dict[str, Any]] = {}
    for rows in bundle.get("active_fields", {}).values():
        for row in rows:
            field_id = str(row["field_id"])
            if field_id in result:
                raise ContractError(f"duplicate R14 field registry ID: {field_id}")
            result[field_id] = dict(row)
    if set(result) != {
        "H02", "H07", "H14", "H16", "H17", "H18", "H19", "H24",
        "H26", "H28", "H31", "H36", "H38", "Q05",
    }:
        raise ContractError("R14 field registry universe changed")
    return result


def _catalog_rows_for_table(
    table: pa.Table,
    *,
    archive_path: str,
    archive_sha256: str,
    field_contracts: Mapping[str, Mapping[str, Any]],
    local_value_columns: Mapping[str, str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ordinal, row in enumerate(table.to_pylist()):
        field_id = str(row["field_registry_id"])
        try:
            field_contract = field_contracts[field_id]
            local_value_column = str(local_value_columns[field_id])
        except KeyError as exc:
            raise ContractError(f"unregistered R14 field in canonical archive: {field_id}") from exc
        spatial_contract_id = str(field_contract["spatial_contract_id"])
        support_id = time_support_id(row)
        source_hash = row["source_idx_hash"]
        payload_hash = row["payload_hash"]
        if not isinstance(source_hash, bytes) or len(source_hash) != 32:
            raise ContractError("canonical source-index hash is invalid")
        if payload_hash is not None and (
            not isinstance(payload_hash, bytes) or len(payload_hash) != 32
        ):
            raise ContractError("canonical payload hash is invalid")
        result.append(
            {
                "trajectory_state_id": trajectory_state_id(
                    row, spatial_contract_id=spatial_contract_id
                ),
                "target_date": row["target_day"],
                "product": str(row["product"]),
                "field_registry_id": field_id,
                "cycle_init_utc": as_utc(row["cycle_init_utc"]),
                "valid_time_utc": as_utc(row["valid_time_utc"]),
                "forecast_lead_min": int(row["forecast_lead_min"]),
                "interval_start_utc": as_utc(row["interval_start_utc"]),
                "interval_end_utc": as_utc(row["interval_end_utc"]),
                "time_support_id": support_id,
                "parameter": str(row["parameter"]),
                "level": str(row["level"]),
                "step_type": str(row["step_type"]),
                "native_unit": str(row["native_unit"]),
                "canonical_unit": str(row["canonical_unit"]),
                "spatial_contract_id": spatial_contract_id,
                "local_value_column": local_value_column,
                "tile_values_available": row["tile_values"] is not None,
                "regional_values_available": bool(row["regional_coverage_mask"]),
                "regional_spatial_contract_id": str(
                    row["regional_spatial_contract_id"]
                ),
                "regional_operator": (
                    None
                    if row["regional_operator"] is None
                    else str(row["regional_operator"])
                ),
                "regional_support_count": int(row["regional_support_count"]),
                "regional_coverage_mask": int(row["regional_coverage_mask"]),
                "station_id": str(row["station_id"]),
                "station_coord_era": str(row["station_coord_era"]),
                "grid_geometry_id": str(row["grid_geometry_id"]),
                "coverage_flag": str(row["coverage_flag"]),
                "missing_reason": row["missing_reason"],
                "selector_identity": str(row["selector_identity"]),
                "source_idx_hash_hex": source_hash.hex(),
                "payload_hash_hex": None if payload_hash is None else payload_hash.hex(),
                "canonical_archive_path": archive_path,
                "canonical_archive_row_ordinal": ordinal,
                "canonical_archive_sha256": archive_sha256,
                "hrrr_version": str(row["hrrr_version"]),
                "derivation_version": str(row["derivation_version"]),
            }
        )
    return result


def _source_cycle_path(
    root: Path,
    contract: Mapping[str, Any],
    target_day: date,
    product: str,
    cycle_init_utc: datetime,
) -> tuple[Path, str]:
    relative = (
        Path(str(contract["archive_roots"][product]))
        / f"target_year={target_day.year:04d}"
        / f"target_month={target_day.month:02d}"
        / f"target_day={target_day.isoformat()}"
        / f"cycle={as_utc(cycle_init_utc).strftime('%Y%m%dT%H%M%SZ')}"
        / "field_state.parquet"
    )
    absolute = _inside(root, relative)
    if not absolute.is_file():
        raise ContractError(f"canonical R14 partition is missing: {relative}")
    return absolute, relative.as_posix()


def _command_prefix() -> str:
    return ".venv/bin/python -m kden_v375.prefit.cli"


def p05_preflight(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    predecessor = _predecessor(root)
    config = _load_config(root)
    features, registry_hash = _load_feature_authority(root)
    acquisition = _read_json(root / "reports/step_08_final_acceptance_v375.json")
    totals = acquisition.get("combined", {})
    if (
        totals.get("request_count") != EXPECTED_TRAJECTORY_ROWS
        or acquisition.get("status") != "PASS"
    ):
        raise ContractError("accepted R14 row count changed")
    usage = shutil.disk_usage(root)
    required = int(config["minimum_free_bytes_at_start"])
    run_id = make_prefit_run_id(5, "owner-full", "universal-substrate")
    prefix = _command_prefix()
    return {
        "schema_version": "KDEN_V375_PREFIT_P05_PREFLIGHT_V1",
        "status": (
            "READY_FOR_OWNER_P05"
            if usage.free >= required
            else "INSUFFICIENT_FREE_DISK"
        ),
        "predecessor_record_sha256": predecessor["record_sha256"],
        "substrate_release_id": SUBSTRATE_RELEASE_ID,
        "feature_registry_sha256": registry_hash,
        "feature_count": len(features),
        "expected_target_days": EXPECTED_TARGET_DAYS,
        "expected_feature_rows": EXPECTED_FEATURE_ROWS,
        "expected_trajectory_rows": EXPECTED_TRAJECTORY_ROWS,
        "trajectory_values_duplicated": False,
        "available_bytes_now": usage.free,
        "minimum_free_bytes_at_start": required,
        "disk_pass": usage.free >= required,
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "suggested_run_id": run_id,
        "start_command": f"{prefix} run-p05 --run-id {run_id}",
        "status_command": f"{prefix} p05-status --run-id {run_id}",
        "live_status_command": (
            f"{prefix} p05-live-status --run-id {run_id} --interval-seconds 5"
        ),
        "eta_command": f"{prefix} p05-eta --run-id {run_id}",
        "pause_command": f"{prefix} p05-pause --run-id {run_id}",
        "resume_command": f"{prefix} resume-p05 --run-id {run_id}",
        "validation_command": f"{prefix} validate-p05",
    }


def _run_paths(root: Path, run_id: str) -> dict[str, Path]:
    base = _inside(root, Path("prefit_runs") / run_id / "p05")
    return {
        "base": base,
        "state": base / "run.json",
        "pause": base / "control/pause.requested.json",
        "checkpoints": base / "checkpoints",
        "year_manifests": base / "year_manifests",
        "journal": base / "progress/completions.jsonl",
    }


def _initialize_state(root: Path, run_id: str) -> dict[str, Any]:
    validate_prefit_run_id(run_id, stage_no=5, scope="owner-full")
    path = _run_paths(root, run_id)["state"]
    if path.is_file():
        state = _read_json(path)
        if state.get("schema_version") != RUN_STATE_SCHEMA or state.get("run_id") != run_id:
            raise StaleStateError("P05 run-state identity mismatch")
        return state
    created = utc_now()
    state = {
        "schema_version": RUN_STATE_SCHEMA,
        "stage_id": "PREFIT_P05",
        "run_id": run_id,
        "status": "INITIALIZED",
        "phase": "NOT_STARTED",
        "message": "initialized",
        "created_at_utc": created,
        "started_at_utc": None,
        "updated_at_utc": created,
        "completed_at_utc": None,
        "expected_target_days": EXPECTED_TARGET_DAYS,
        "completed_target_days": 0,
        "expected_feature_rows": EXPECTED_FEATURE_ROWS,
        "completed_feature_rows": 0,
        "expected_dynamic_trajectory_rows": EXPECTED_DYNAMIC_TRAJECTORY_ROWS,
        "completed_dynamic_trajectory_rows": 0,
        "expected_total_trajectory_rows": EXPECTED_TRAJECTORY_ROWS,
        "completed_total_trajectory_rows": 0,
        "completed_years": [],
        "current_target_date": None,
        "current_issue_states_completed": None,
        "current_issue_states_expected": None,
        "current_source_cycles_completed": None,
        "current_source_cycles_expected": None,
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
    payload = canonical_json_bytes(dict(value))
    with path.open("ab") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def _journal_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StaleStateError(
                    f"P05 completion journal is malformed at line {line_number}"
                ) from exc
            if not isinstance(value, dict):
                raise StaleStateError("P05 journal record is not a JSON object")
            records.append(value)
    return records


def _day_checkpoint_paths(root: Path, run_id: str, target_day: date) -> dict[str, Path]:
    base = (
        _run_paths(root, run_id)["checkpoints"]
        / f"target_year={target_day.year:04d}"
        / f"target_day={target_day.isoformat()}"
    )
    return {
        "base": base,
        "trajectory": base / "trajectory_catalog.parquet",
        "features": base / "deterministic_features.parquet",
        "manifest": base / "manifest.json",
    }


def _valid_day_checkpoint(
    root: Path, run_id: str, target_day: date
) -> dict[str, Any] | None:
    paths = _day_checkpoint_paths(root, run_id, target_day)
    if not paths["manifest"].is_file():
        return None
    manifest = _read_json(paths["manifest"])
    if (
        manifest.get("schema_version") != DAY_CHECKPOINT_SCHEMA
        or manifest.get("target_date") != target_day.isoformat()
    ):
        return None
    for key in ("trajectory", "features"):
        path = paths[key]
        if not path.is_file() or sha256_file(path) != manifest[f"{key}_sha256"]:
            return None
    if pq.ParquetFile(paths["trajectory"]).metadata.num_rows != manifest["trajectory_rows"]:
        return None
    if pq.ParquetFile(paths["features"]).metadata.num_rows != manifest["feature_rows"]:
        return None
    return manifest


def _year_partition_paths(root: Path, year: int) -> dict[str, Path]:
    return {
        "trajectory": _inside(
            root,
            Path(TRAJECTORY_ROOT)
            / f"target_year={year:04d}"
            / f"part-{year:04d}.parquet",
        ),
        "features": _inside(
            root,
            Path(FEATURE_ROOT)
            / f"target_year={year:04d}"
            / f"part-{year:04d}.parquet",
        ),
    }


def _year_manifest_path(root: Path, run_id: str, year: int) -> Path:
    return _run_paths(root, run_id)["year_manifests"] / f"year={year:04d}.json"


def _valid_year_partition(
    root: Path, run_id: str, year: int
) -> dict[str, Any] | None:
    path = _year_manifest_path(root, run_id, year)
    if not path.is_file():
        return None
    manifest = _read_json(path)
    if manifest.get("schema_version") != YEAR_CHECKPOINT_SCHEMA or manifest.get("year") != year:
        return None
    outputs = _year_partition_paths(root, year)
    for key in ("trajectory", "features"):
        if (
            not outputs[key].is_file()
            or sha256_file(outputs[key]) != manifest[f"{key}_sha256"]
            or pq.ParquetFile(outputs[key]).metadata.num_rows
            != manifest[f"{key}_rows"]
        ):
            return None
    return manifest


def _load_year_inputs(
    root: Path, year: int
) -> tuple[dict[date, list[dict[str, Any]]], dict[str, dict[str, dict[str, Any]]]]:
    issues = pq.read_table(
        root / ISSUE_OUTPUT_PATH,
        filters=[("target_date", ">=", date(year, 1, 1)), ("target_date", "<=", date(year, 12, 31))],
    ).to_pylist()
    selections = pq.read_table(
        root / SELECTION_OUTPUT_PATH,
        filters=[("target_date", ">=", date(year, 1, 1)), ("target_date", "<=", date(year, 12, 31))],
    ).to_pylist()
    issues_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in issues:
        issues_by_day[row["target_date"]].append(row)
    selections_by_issue: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in selections:
        selections_by_issue[str(row["issue_state_id"])][str(row["product"])] = row
    for target_day, rows in issues_by_day.items():
        rows.sort(key=lambda row: row["issue_time_utc"])
        for row in rows:
            selected = selections_by_issue[str(row["issue_state_id"])]
            if set(selected) != set(PRODUCT_ORDER):
                raise ContractError(f"P03 selections are incomplete for {target_day}")
    return dict(issues_by_day), dict(selections_by_issue)


def _publish_heartbeat(
    root: Path,
    run_id: str,
    *,
    target_day: date,
    issue_done: int | None = None,
    issue_expected: int | None = None,
    cycles_done: int | None = None,
    cycles_expected: int | None = None,
) -> None:
    updates: dict[str, Any] = {"current_target_date": target_day.isoformat()}
    if issue_done is not None:
        updates.update(
            current_issue_states_completed=issue_done,
            current_issue_states_expected=issue_expected,
        )
    if cycles_done is not None:
        updates.update(
            current_source_cycles_completed=cycles_done,
            current_source_cycles_expected=cycles_expected,
        )
    _update_state(root, run_id, **updates)


def _build_day_checkpoint(
    *,
    root: Path,
    run_id: str,
    target_day: date,
    issue_rows: Sequence[Mapping[str, Any]],
    selections_by_issue: Mapping[str, Mapping[str, Mapping[str, Any]]],
    reader: R14ArchiveReader,
    contract: Mapping[str, Any],
    features: Sequence[Mapping[str, Any]],
    field_contracts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    started = time.monotonic()
    feature_rows: list[dict[str, Any]] = []
    last_heartbeat = time.monotonic()
    for index, issue_row in enumerate(issue_rows, start=1):
        feature_rows.append(
            compute_issue_feature_row(
                issue_row=issue_row,
                selection_rows=selections_by_issue[str(issue_row["issue_state_id"])],
                reader=reader,
                features=features,
            )
        )
        if time.monotonic() - last_heartbeat >= 1 or index == len(issue_rows):
            _publish_heartbeat(
                root,
                run_id,
                target_day=target_day,
                issue_done=index,
                issue_expected=len(issue_rows),
                cycles_done=0,
                cycles_expected=sum(
                    len(reader.schedule_rows(target_day, product))
                    for product in PRODUCT_ORDER
                ),
            )
            last_heartbeat = time.monotonic()

    trajectory_rows: list[dict[str, Any]] = []
    cycles = [
        (product, row["cycle_init_utc"])
        for product in PRODUCT_ORDER
        for row in reader.schedule_rows(target_day, product)
    ]
    for cycle_index, (product, cycle_init) in enumerate(cycles, start=1):
        source_path, source_relative = _source_cycle_path(
            root, contract, target_day, product, cycle_init
        )
        table = reader.read_cycle(target_day, product, cycle_init)
        trajectory_rows.extend(
            _catalog_rows_for_table(
                table,
                archive_path=source_relative,
                archive_sha256=sha256_file(source_path),
                field_contracts=field_contracts,
                local_value_columns=contract["local_value_column_by_field"],
            )
        )
        if time.monotonic() - last_heartbeat >= 1 or cycle_index == len(cycles):
            _publish_heartbeat(
                root,
                run_id,
                target_day=target_day,
                issue_done=len(issue_rows),
                issue_expected=len(issue_rows),
                cycles_done=cycle_index,
                cycles_expected=len(cycles),
            )
            last_heartbeat = time.monotonic()

    feature_schema = feature_panel_schema(features)
    trajectory_schema = trajectory_catalog_schema()
    feature_identifiers = [str(row["issue_state_id"]) for row in feature_rows]
    expected_feature_identifiers = [str(row["issue_state_id"]) for row in issue_rows]
    if feature_identifiers != expected_feature_identifiers or len(feature_identifiers) != len(
        set(feature_identifiers)
    ):
        raise ContractError("P05 target-day feature rows changed order or identity")
    trajectory_identifiers = [str(row["trajectory_state_id"]) for row in trajectory_rows]
    source_locators = [
        (str(row["canonical_archive_path"]), int(row["canonical_archive_row_ordinal"]))
        for row in trajectory_rows
    ]
    if len(trajectory_identifiers) != len(set(trajectory_identifiers)):
        raise ContractError("P05 target-day trajectory identity is duplicated")
    if len(source_locators) != len(set(source_locators)):
        raise ContractError("P05 target-day source locator is duplicated")
    paths = _day_checkpoint_paths(root, run_id, target_day)
    trajectory_hash = atomic_write_bytes(
        paths["trajectory"],
        _parquet_bytes(trajectory_rows, trajectory_schema),
        replace=True,
    )
    feature_hash = atomic_write_bytes(
        paths["features"],
        _parquet_bytes(feature_rows, feature_schema),
        replace=True,
    )
    manifest = {
        "schema_version": DAY_CHECKPOINT_SCHEMA,
        "target_date": target_day.isoformat(),
        "target_year": target_day.year,
        "feature_rows": len(feature_rows),
        "trajectory_rows": len(trajectory_rows),
        "trajectory_present_rows": sum(
            row["coverage_flag"] == "PRESENT" for row in trajectory_rows
        ),
        "trajectory_missing_rows": sum(
            row["coverage_flag"] != "PRESENT" for row in trajectory_rows
        ),
        "source_cycle_count": len(cycles),
        "trajectory_sha256": trajectory_hash,
        "features_sha256": feature_hash,
        "elapsed_seconds": time.monotonic() - started,
    }
    atomic_write_json(paths["manifest"], manifest, replace=True)
    return manifest


def _write_partition_from_days(
    *,
    destination: Path,
    source_paths: Sequence[Path],
    schema: pa.Schema,
) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    writer: pq.ParquetWriter | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        writer = pq.ParquetWriter(
            temporary,
            schema,
            compression="zstd",
            version="2.6",
            write_statistics=True,
            use_dictionary=True,
        )
        for path in source_paths:
            table = pq.ParquetFile(path).read()
            if table.schema != schema:
                raise ContractError(f"P05 day checkpoint schema changed: {path}")
            writer.write_table(table, row_group_size=65536)
        writer.close()
        writer = None
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        digest = atomic_publish_file(temporary, destination, replace=True)
        temporary = None
        return digest
    finally:
        if writer is not None:
            writer.close()
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _merge_year(
    *,
    root: Path,
    run_id: str,
    year: int,
    target_days: Sequence[date],
    features: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    manifests: list[dict[str, Any]] = []
    day_paths: list[dict[str, Path]] = []
    for target_day in target_days:
        manifest = _valid_day_checkpoint(root, run_id, target_day)
        if manifest is None:
            raise ContractError(f"P05 day checkpoint is absent or stale: {target_day}")
        manifests.append(manifest)
        day_paths.append(_day_checkpoint_paths(root, run_id, target_day))
    outputs = _year_partition_paths(root, year)
    trajectory_hash = _write_partition_from_days(
        destination=outputs["trajectory"],
        source_paths=[paths["trajectory"] for paths in day_paths],
        schema=trajectory_catalog_schema(),
    )
    feature_hash = _write_partition_from_days(
        destination=outputs["features"],
        source_paths=[paths["features"] for paths in day_paths],
        schema=feature_panel_schema(features),
    )
    manifest = {
        "schema_version": YEAR_CHECKPOINT_SCHEMA,
        "year": year,
        "target_day_count": len(target_days),
        "feature_rows": sum(int(value["feature_rows"]) for value in manifests),
        "trajectory_rows": sum(int(value["trajectory_rows"]) for value in manifests),
        "trajectory_present_rows": sum(
            int(value["trajectory_present_rows"]) for value in manifests
        ),
        "trajectory_missing_rows": sum(
            int(value["trajectory_missing_rows"]) for value in manifests
        ),
        "trajectory_path": _relative(root, outputs["trajectory"]),
        "trajectory_sha256": trajectory_hash,
        "features_path": _relative(root, outputs["features"]),
        "features_sha256": feature_hash,
    }
    atomic_write_json(_year_manifest_path(root, run_id, year), manifest, replace=True)
    checkpoint_year = _run_paths(root, run_id)["checkpoints"] / f"target_year={year:04d}"
    if checkpoint_year.is_dir():
        shutil.rmtree(checkpoint_year)
        fsync_directory(checkpoint_year.parent)
    return manifest


def _publish_static_catalog(
    root: Path,
    reader: R14ArchiveReader,
    contract: Mapping[str, Any],
    field_contracts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    source_relative = str(contract["static_terrain_path"])
    source_path = _inside(root, source_relative)
    rows = _catalog_rows_for_table(
        reader.read_static_terrain(),
        archive_path=source_relative,
        archive_sha256=sha256_file(source_path),
        field_contracts=field_contracts,
        local_value_columns={**contract["local_value_column_by_field"], "H14": "bi_value"},
    )
    if len(rows) != 1 or rows[0]["field_registry_id"] != "H14":
        raise ContractError("P05 static trajectory reference is not unique H14")
    digest = atomic_write_bytes(
        root / STATIC_TRAJECTORY_PATH,
        _parquet_bytes(rows, trajectory_catalog_schema()),
        replace=True,
    )
    return {"path": STATIC_TRAJECTORY_PATH, "rows": 1, "sha256": digest}


def _completion_summary(
    root: Path, run_id: str
) -> tuple[list[dict[str, Any]], int, int, int, list[int]]:
    years: list[dict[str, Any]] = []
    completed_days = 0
    completed_features = 0
    completed_trajectories = 0
    completed_years: list[int] = []
    for year in TARGET_YEARS:
        value = _valid_year_partition(root, run_id, year)
        if value is None:
            break
        years.append(value)
        completed_years.append(year)
        completed_days += int(value["target_day_count"])
        completed_features += int(value["feature_rows"])
        completed_trajectories += int(value["trajectory_rows"])
    # Incomplete-year day checkpoints are counted by the main loop, including
    # checkpoints recovered during resume. Counting them here as well would
    # double-count recovered days when that loop advances over them.
    return years, completed_days, completed_features, completed_trajectories, completed_years


def _publish_release(
    *,
    root: Path,
    run_id: str,
    predecessor: Mapping[str, Any],
    year_manifests: Sequence[Mapping[str, Any]],
    static: Mapping[str, Any],
    registry_hash: str,
) -> dict[str, Any]:
    issue_hash = sha256_file(root / ISSUE_OUTPUT_PATH)
    selection_hash = sha256_file(root / SELECTION_OUTPUT_PATH)
    dynamic_rows = sum(int(value["trajectory_rows"]) for value in year_manifests)
    feature_rows = sum(int(value["feature_rows"]) for value in year_manifests)
    present_rows = sum(int(value["trajectory_present_rows"]) for value in year_manifests)
    missing_rows = sum(int(value["trajectory_missing_rows"]) for value in year_manifests)
    journal_path = _run_paths(root, run_id)["journal"]
    manifest = {
        "schema_version": RELEASE_MANIFEST_SCHEMA,
        "status": "PASS_CANDIDATE",
        "release_id": SUBSTRATE_RELEASE_ID,
        "run_id": run_id,
        "created_at_utc": utc_now(),
        "predecessor_p04_record_sha256": predecessor["record_sha256"],
        "execution": {
            "network_requests_made": 0,
            "truth_rows_read": 0,
            "model_fits_performed": 0,
        },
        "issue_spine": {
            "path": ISSUE_OUTPUT_PATH,
            "rows": EXPECTED_ISSUE_ROWS,
            "sha256": issue_hash,
        },
        "selected_cycles": {
            "path": SELECTION_OUTPUT_PATH,
            "rows": EXPECTED_ISSUE_ROWS * 2,
            "sha256": selection_hash,
        },
        "feature_registry": {
            "path": REGISTRY_PATH,
            "registry_id": REGISTRY_ID,
            "sha256": registry_hash,
        },
        "trajectory_catalog": {
            "schema_id": TRAJECTORY_SCHEMA_ID,
            "dynamic_rows": dynamic_rows,
            "static_rows": int(static["rows"]),
            "total_rows": dynamic_rows + int(static["rows"]),
            "present_rows": present_rows + 1,
            "missing_rows": missing_rows,
            "canonical_values_duplicated": False,
            "static": dict(static),
            "year_partitions": [
                {
                    "year": value["year"],
                    "path": value["trajectory_path"],
                    "rows": value["trajectory_rows"],
                    "sha256": value["trajectory_sha256"],
                }
                for value in year_manifests
            ],
        },
        "deterministic_features": {
            "schema_id": PANEL_SCHEMA_ID,
            "rows": feature_rows,
            "year_partitions": [
                {
                    "year": value["year"],
                    "path": value["features_path"],
                    "rows": value["feature_rows"],
                    "sha256": value["features_sha256"],
                }
                for value in year_manifests
            ],
        },
        "partitioning": {
            "final_partition_key": "target_year",
            "atomic_checkpoint_key": "target_date",
            "target_day_count": EXPECTED_TARGET_DAYS,
        },
        "resumability": {
            "completion_journal_path": _relative(root, journal_path),
            "completion_journal_sha256": sha256_file(journal_path),
            "pause_boundary": "after a complete target-day checkpoint",
        },
        "isolation": {
            "labels_physically_separate": True,
            "fold_assignments_physically_separate": True,
            "market_data_absent": True,
            "madis_data_absent": True,
            "legacy_runtime_dependency_absent": True,
        },
    }
    atomic_write_json(root / RELEASE_MANIFEST_PATH, manifest, replace=True)
    manifest_hash = sha256_file(root / RELEASE_MANIFEST_PATH)
    index = {
        "schema_version": RELEASE_INDEX_SCHEMA,
        "release_id": SUBSTRATE_RELEASE_ID,
        "status": "PASS_CANDIDATE",
        "manifest": {
            "path": RELEASE_MANIFEST_PATH,
            "sha256": manifest_hash,
        },
        "objects": {
            "issue_spine": ISSUE_OUTPUT_PATH,
            "selected_cycles": SELECTION_OUTPUT_PATH,
            "trajectory_catalog": TRAJECTORY_ROOT,
            "deterministic_features": FEATURE_ROOT,
            "feature_registry": REGISTRY_PATH,
        },
        "physically_separate_objects": {
            "labels": "truth/kden_tmax/v1",
            "fold_assignments": "folds/kden_v375/v1",
        },
    }
    atomic_write_json(root / RELEASE_INDEX_PATH, index, replace=True)
    report = f"""# P05 Universal Substrate Materialization Report

Status: PASS candidate for `{SUBSTRATE_RELEASE_ID}`

## Materialized objects

- Target days: {EXPECTED_TARGET_DAYS:,}
- Target-free issue feature rows: {feature_rows:,}
- Dynamic trajectory references: {dynamic_rows:,}
- Static H14 trajectory references: {int(static['rows']):,}
- Total trajectory references: {dynamic_rows + int(static['rows']):,}
- Explicit remote-missing trajectory rows: {missing_rows:,}
- Target-year partitions: {len(year_manifests)} per materialized object

The trajectory catalog is reference-only. It identifies a canonical R14
Parquet file, exact row ordinal, source-file SHA-256, value-column contract,
time support, and spatial contract. It does not copy the canonical weather
values into another 8.9-million-row value archive.

## Isolation and causality

P05 read only the frozen P03 issue/cycle objects, the frozen P04 feature
contract, and the frozen local R14 archive. It made no network requests, read
no target values, performed no model fitting, and did not materialize fold or
market information. Labels remain in their separate P02-owned package.

## Recovery

Publication was atomic by target day and final output was partitioned by target
year. The owner-run journal remains at
`{_relative(root, journal_path)}`. Day-level scratch checkpoints were removed
only after their corresponding year partitions had been published and hashed.
"""
    atomic_write_bytes(root / REPORT_PATH, report.encode("utf-8"), replace=True)
    return manifest


def _validate_outputs(
    root: Path, *, verify_hashes: bool
) -> dict[str, Any]:
    predecessor = _predecessor(root)
    config = _load_config(root)
    features, registry_hash = _load_feature_authority(root)
    manifest = _read_json(root / RELEASE_MANIFEST_PATH)
    index = _read_json(root / RELEASE_INDEX_PATH)
    if manifest.get("schema_version") != RELEASE_MANIFEST_SCHEMA:
        raise ContractError("unsupported P05 release manifest")
    if (
        manifest.get("release_id") != SUBSTRATE_RELEASE_ID
        or manifest.get("predecessor_p04_record_sha256") != predecessor["record_sha256"]
    ):
        raise StaleStateError("P05 release identity or predecessor changed")
    if index.get("schema_version") != RELEASE_INDEX_SCHEMA:
        raise ContractError("unsupported P05 release index")
    if index.get("manifest", {}).get("sha256") != sha256_file(root / RELEASE_MANIFEST_PATH):
        raise StaleStateError("P05 release-index manifest hash mismatch")
    if manifest.get("feature_registry", {}).get("sha256") != registry_hash:
        raise StaleStateError("P05 feature-registry hash mismatch")

    trajectory_partitions = manifest.get("trajectory_catalog", {}).get("year_partitions", [])
    feature_partitions = manifest.get("deterministic_features", {}).get("year_partitions", [])
    if [row.get("year") for row in trajectory_partitions] != list(TARGET_YEARS):
        raise ContractError("P05 trajectory year partition coverage changed")
    if [row.get("year") for row in feature_partitions] != list(TARGET_YEARS):
        raise ContractError("P05 feature year partition coverage changed")
    trajectory_rows = 0
    feature_rows = 0
    issue_ids: set[str] = set()
    last_feature_key: tuple[date, datetime] | None = None
    for trajectory, feature in zip(trajectory_partitions, feature_partitions, strict=True):
        trajectory_path = _inside(root, str(trajectory["path"]))
        feature_path = _inside(root, str(feature["path"]))
        trajectory_file = pq.ParquetFile(trajectory_path)
        feature_file = pq.ParquetFile(feature_path)
        if trajectory_file.schema_arrow != trajectory_catalog_schema():
            raise ContractError(f"P05 trajectory schema changed: {trajectory_path}")
        if feature_file.schema_arrow != feature_panel_schema(features):
            raise ContractError(f"P05 feature schema changed: {feature_path}")
        if trajectory_file.metadata.num_rows != int(trajectory["rows"]):
            raise ContractError("P05 trajectory partition row count mismatch")
        if feature_file.metadata.num_rows != int(feature["rows"]):
            raise ContractError("P05 feature partition row count mismatch")
        if verify_hashes:
            if sha256_file(trajectory_path) != trajectory["sha256"]:
                raise StaleStateError("P05 trajectory partition hash mismatch")
            if sha256_file(feature_path) != feature["sha256"]:
                raise StaleStateError("P05 feature partition hash mismatch")
        trajectory_rows += trajectory_file.metadata.num_rows
        feature_rows += feature_file.metadata.num_rows
        feature_keys = feature_file.read(columns=["issue_state_id", "target_date", "issue_time_utc"])
        for row in feature_keys.to_pylist():
            identifier = str(row["issue_state_id"])
            key = (row["target_date"], as_utc(row["issue_time_utc"]))
            if identifier in issue_ids:
                raise ContractError("P05 feature primary key is duplicated")
            if last_feature_key is not None and key <= last_feature_key:
                raise ContractError("P05 feature rows are not deterministically ordered")
            issue_ids.add(identifier)
            last_feature_key = key

    static = manifest.get("trajectory_catalog", {}).get("static", {})
    static_path = _inside(root, str(static.get("path", "")))
    static_file = pq.ParquetFile(static_path)
    if static_file.schema_arrow != trajectory_catalog_schema() or static_file.metadata.num_rows != 1:
        raise ContractError("P05 static H14 reference changed")
    if verify_hashes and sha256_file(static_path) != static.get("sha256"):
        raise StaleStateError("P05 static H14 reference hash mismatch")
    static_fields = static_file.read(columns=["field_registry_id"]).column(0).to_pylist()
    if static_fields != ["H14"]:
        raise ContractError("P05 static trajectory is not H14")

    if trajectory_rows != EXPECTED_DYNAMIC_TRAJECTORY_ROWS:
        raise ContractError("P05 dynamic trajectory count mismatch")
    if feature_rows != EXPECTED_FEATURE_ROWS or len(issue_ids) != EXPECTED_FEATURE_ROWS:
        raise ContractError("P05 deterministic feature count mismatch")
    trajectory_total = trajectory_rows + 1
    if manifest.get("trajectory_catalog", {}).get("total_rows") != trajectory_total:
        raise ContractError("P05 total trajectory count mismatch")
    if manifest.get("trajectory_catalog", {}).get("missing_rows") != (
        EXPECTED_DYNAMIC_MISSING_TRAJECTORY_ROWS
    ):
        raise ContractError("P05 explicit remote-missing trajectory count mismatch")
    if (
        int(manifest["trajectory_catalog"]["present_rows"])
        + int(manifest["trajectory_catalog"]["missing_rows"])
        != trajectory_total
    ):
        raise ContractError("P05 trajectory present/missing counts do not reconcile")
    if manifest.get("trajectory_catalog", {}).get("canonical_values_duplicated") is not False:
        raise ContractError("P05 trajectory catalog must remain reference-only")
    forbidden = {
        "bi_value", "nn_value", "tile_values", "regional_value_00",
        "y_audited_f", "truth_qc_status", "market_price", "settlement",
        "madis_temperature",
    }
    if forbidden & set(trajectory_catalog_schema().names):
        raise ContractError("P05 trajectory catalog duplicates a value or target column")
    if any(
        token in name.lower()
        for name in feature_panel_schema(features).names
        for token in ("truth", "y_audited", "market", "settlement", "madis", "fold")
    ):
        raise ContractError("P05 deterministic feature panel leaked a forbidden domain")
    if manifest.get("execution") != {
        "network_requests_made": 0,
        "truth_rows_read": 0,
        "model_fits_performed": 0,
    }:
        raise ContractError("P05 execution isolation evidence changed")
    isolation = validate_runtime_isolation(root)
    return {
        "predecessor_record_sha256": predecessor["record_sha256"],
        "release_id": SUBSTRATE_RELEASE_ID,
        "target_day_count": EXPECTED_TARGET_DAYS,
        "feature_row_count": feature_rows,
        "trajectory_dynamic_row_count": trajectory_rows,
        "trajectory_static_row_count": 1,
        "trajectory_total_row_count": trajectory_total,
        "trajectory_missing_row_count": EXPECTED_DYNAMIC_MISSING_TRAJECTORY_ROWS,
        "trajectory_reference_only": True,
        "target_year_partition_count": len(TARGET_YEARS),
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "model_fits_performed": 0,
        "runtime_isolation": {
            key: value for key, value in isolation.items() if key != "source_files_scanned"
        },
        "minimum_free_bytes_at_start": config["minimum_free_bytes_at_start"],
    }


def run_p05(
    *, project_root: Path | str, run_id: str, resume: bool = False
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if (root / PASS_PATH).is_file():
        return verify_p05(root)
    predecessor = _predecessor(root)
    config = _load_config(root)
    preflight = p05_preflight(root)
    if not resume and not preflight["disk_pass"]:
        raise ContractError("P05 preflight failed the minimum free-disk gate")
    features, registry_hash = _load_feature_authority(root)
    state = _initialize_state(root, run_id)
    resumable = {"INITIALIZED", "PAUSED", "PAUSE_REQUESTED", "FAILED"}
    if resume and state["status"] not in resumable:
        raise ContractError(f"P05 run is not resumable from {state['status']}")
    if not resume and state["status"] not in {"INITIALIZED", "FAILED"}:
        raise ContractError(f"P05 run already exists in {state['status']}; use resume-p05")
    paths = _run_paths(root, run_id)
    pause = PauseController(paths["pause"])
    if resume:
        pause.clear()
    with ExclusiveRunLock(load_project_paths(root).state / "PREFIT_P05.lock"):
        pause.install()
        _update_state(
            root,
            run_id,
            status="RUNNING",
            phase="MATERIALIZE_TARGET_DAYS",
            started_at_utc=state.get("started_at_utc") or utc_now(),
            message="resumed" if resume else "started",
        )
        try:
            reader = R14ArchiveReader(root, verify_acquisition=True)
            contract = load_issue_view_contract(root)
            field_contracts = _load_field_contracts(root)
            _, completed_days, completed_features, completed_trajectories, completed_years = (
                _completion_summary(root, run_id)
            )
            journal_days = {
                str(row.get("target_date")) for row in _journal_records(paths["journal"])
            }
            year_manifests: list[dict[str, Any]] = []
            for year in TARGET_YEARS:
                pause.raise_if_requested()
                existing_year = _valid_year_partition(root, run_id, year)
                if existing_year is not None:
                    year_manifests.append(existing_year)
                    continue
                issues_by_day, selections_by_issue = _load_year_inputs(root, year)
                target_days = [
                    target
                    for target in _inclusive_dates(STUDY_START, STUDY_END)
                    if target.year == year
                ]
                if list(issues_by_day) != target_days:
                    raise ContractError(f"P03 issue-state coverage changed for {year}")
                for target_day in target_days:
                    pause.raise_if_requested()
                    manifest = _valid_day_checkpoint(root, run_id, target_day)
                    if manifest is None:
                        _update_state(
                            root,
                            run_id,
                            phase="MATERIALIZE_TARGET_DAYS",
                            message=f"materializing {target_day}",
                            current_target_date=target_day.isoformat(),
                            current_issue_states_completed=0,
                            current_issue_states_expected=len(issues_by_day[target_day]),
                            current_source_cycles_completed=0,
                            current_source_cycles_expected=sum(
                                len(reader.schedule_rows(target_day, product))
                                for product in PRODUCT_ORDER
                            ),
                        )
                        manifest = _build_day_checkpoint(
                            root=root,
                            run_id=run_id,
                            target_day=target_day,
                            issue_rows=issues_by_day[target_day],
                            selections_by_issue=selections_by_issue,
                            reader=reader,
                            contract=contract,
                            features=features,
                            field_contracts=field_contracts,
                        )
                    if target_day.isoformat() not in journal_days:
                        _append_jsonl(
                            paths["journal"],
                            {
                                "schema_version": "KDEN_V375_PREFIT_P05_COMPLETION_V1",
                                "target_date": target_day.isoformat(),
                                "target_year": year,
                                "feature_rows": manifest["feature_rows"],
                                "trajectory_rows": manifest["trajectory_rows"],
                                "elapsed_seconds": manifest.get("elapsed_seconds"),
                                "committed_at_utc": utc_now(),
                            },
                        )
                        journal_days.add(target_day.isoformat())
                    completed_days += 1
                    completed_features += int(manifest["feature_rows"])
                    completed_trajectories += int(manifest["trajectory_rows"])
                    _update_state(
                        root,
                        run_id,
                        completed_target_days=completed_days,
                        completed_feature_rows=completed_features,
                        completed_dynamic_trajectory_rows=completed_trajectories,
                        completed_total_trajectory_rows=completed_trajectories,
                        current_target_date=None,
                        current_issue_states_completed=None,
                        current_issue_states_expected=None,
                        current_source_cycles_completed=None,
                        current_source_cycles_expected=None,
                    )
                pause.raise_if_requested()
                _update_state(
                    root,
                    run_id,
                    phase="PUBLISH_TARGET_YEAR",
                    message=f"publishing target year {year}",
                )
                year_manifest = _merge_year(
                    root=root,
                    run_id=run_id,
                    year=year,
                    target_days=target_days,
                    features=features,
                )
                year_manifests.append(year_manifest)
                completed_years.append(year)
                _update_state(
                    root,
                    run_id,
                    completed_years=completed_years,
                    phase="MATERIALIZE_TARGET_DAYS",
                    message=f"target year {year} published",
                )
            pause.raise_if_requested()
            _update_state(
                root,
                run_id,
                phase="PUBLISH_AND_VALIDATE_RELEASE",
                message="publishing static reference, release manifest, and report",
            )
            static = _publish_static_catalog(root, reader, contract, field_contracts)
            _update_state(
                root,
                run_id,
                completed_total_trajectory_rows=completed_trajectories + 1,
            )
            manifest = _publish_release(
                root=root,
                run_id=run_id,
                predecessor=predecessor,
                year_manifests=year_manifests,
                static=static,
                registry_hash=registry_hash,
            )
            evidence = _validate_outputs(root, verify_hashes=True)
            artifact_paths: list[str] = [
                CONFIG_PATH,
                TRAJECTORY_SCHEMA_PATH,
                RUN_STATE_SCHEMA_PATH,
                RELEASE_SCHEMA_PATH,
                RUNBOOK_PATH,
                REPORT_PATH,
                "src/kden_v375/prefit/cli.py",
                "src/kden_v375/prefit/p05_materialization.py",
                RELEASE_MANIFEST_PATH,
                RELEASE_INDEX_PATH,
                STATIC_TRAJECTORY_PATH,
                _relative(root, paths["journal"]),
                _relative(root, paths["year_manifests"]),
            ]
            artifact_paths.extend(
                str(row["trajectory_path"]) for row in year_manifests
            )
            artifact_paths.extend(str(row["features_path"]) for row in year_manifests)
            record = write_prefit_pass(
                root,
                stage_no=5,
                run_id=run_id,
                artifact_paths=artifact_paths,
                predecessor_hashes={"PREFIT_P04": predecessor["record_sha256"]},
                authority_hashes={
                    "P03_ISSUE_SPINE": manifest["issue_spine"]["sha256"],
                    "P03_SELECTED_CYCLES": manifest["selected_cycles"]["sha256"],
                    "P04_FEATURE_REGISTRY": registry_hash,
                    "P05_RELEASE_MANIFEST": sha256_file(root / RELEASE_MANIFEST_PATH),
                    "P05_RELEASE_INDEX": sha256_file(root / RELEASE_INDEX_PATH),
                },
                gate_evidence=evidence,
            )
        except PauseRequested as exc:
            _update_state(
                root,
                run_id,
                status="PAUSED",
                message=str(exc),
                current_target_date=None,
                current_issue_states_completed=None,
                current_issue_states_expected=None,
                current_source_cycles_completed=None,
                current_source_cycles_expected=None,
            )
            return {"run_id": run_id, "stage_id": "PREFIT_P05", "status": "PAUSED"}
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
                message="P05 gate passed",
                completed_at_utc=utc_now(),
                completed_target_days=EXPECTED_TARGET_DAYS,
                completed_feature_rows=EXPECTED_FEATURE_ROWS,
                completed_dynamic_trajectory_rows=EXPECTED_DYNAMIC_TRAJECTORY_ROWS,
                completed_total_trajectory_rows=EXPECTED_TRAJECTORY_ROWS,
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
    records = _journal_records(_run_paths(root, run_id)["journal"])
    recent = records[-20:]
    elapsed_values = [
        float(row["elapsed_seconds"])
        for row in recent
        if row.get("elapsed_seconds") is not None and float(row["elapsed_seconds"]) > 0
    ]
    if not elapsed_values:
        return {"status": "UNAVAILABLE", "reason": "insufficient completed target days"}
    days_per_second = len(elapsed_values) / sum(elapsed_values)
    remaining = max(0, EXPECTED_TARGET_DAYS - int(state["completed_target_days"]))
    return {
        "status": "AVAILABLE",
        "basis": "recent_complete_target_day_checkpoints",
        "sample_target_days": len(elapsed_values),
        "recent_rate_target_days_per_second": days_per_second,
        "remaining_target_days": remaining,
        "remaining_seconds": remaining / days_per_second,
        "note": "includes recent feature and catalog work; final publication and validation are not included",
    }


def p05_eta(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_prefit_run_id(run_id, stage_no=5)
    state = _read_json(_run_paths(root, run_id)["state"])
    return {
        "schema_version": "KDEN_V375_PREFIT_P05_ETA_V1",
        "run_id": run_id,
        "observed_at_utc": utc_now(),
        "run_status": state["status"],
        "phase": state["phase"],
        "eta": _eta_snapshot(root, run_id, state),
    }


def p05_status(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_prefit_run_id(run_id, stage_no=5)
    state = _read_json(_run_paths(root, run_id)["state"])
    return {
        **state,
        "release_index_path": RELEASE_INDEX_PATH,
        "release_manifest_path": RELEASE_MANIFEST_PATH,
        "trajectory_catalog_root": TRAJECTORY_ROOT,
        "deterministic_feature_root": FEATURE_ROOT,
        "eta": _eta_snapshot(root, run_id, state),
    }


def p05_pause(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = _run_paths(root, run_id)
    state = _read_json(paths["state"])
    if state["status"] not in {"RUNNING", "PAUSE_REQUESTED"}:
        raise ContractError(f"P05 run is not active: {state['status']}")
    atomic_write_json(
        paths["pause"],
        {"schema_version": "KDEN_V375_PAUSE_REQUEST_V1", "requested_at_utc": utc_now()},
        replace=True,
    )
    return _update_state(
        root,
        run_id,
        status="PAUSE_REQUESTED",
        message="cooperative pause requested; current target day will finish atomically",
    )


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "unavailable"
    remaining = max(0, int(seconds))
    days, remaining = divmod(remaining, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes, seconds = divmod(remaining, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"


def p05_live_status(
    project_root: Path | str,
    run_id: str,
    *,
    interval_seconds: float = 5,
    json_lines: bool = False,
) -> None:
    if interval_seconds <= 0:
        raise ContractError("live-status interval must be positive")
    while True:
        snapshot = p05_status(project_root, run_id)
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
            issue_progress = "-"
            if snapshot.get("current_issue_states_expected") is not None:
                issue_progress = (
                    f"{snapshot.get('current_issue_states_completed', 0)}/"
                    f"{snapshot['current_issue_states_expected']}"
                )
            cycle_progress = "-"
            if snapshot.get("current_source_cycles_expected") is not None:
                cycle_progress = (
                    f"{snapshot.get('current_source_cycles_completed', 0)}/"
                    f"{snapshot['current_source_cycles_expected']}"
                )
            print(
                f"[{utc_now()}] | {snapshot['status']} | phase={snapshot['phase']} | "
                f"days={snapshot['completed_target_days']}/{snapshot['expected_target_days']} | "
                f"features={snapshot['completed_feature_rows']}/"
                f"{snapshot['expected_feature_rows']} | "
                f"trajectory-refs={snapshot['completed_total_trajectory_rows']}/"
                f"{snapshot['expected_total_trajectory_rows']} | "
                f"day={snapshot.get('current_target_date') or '-'} | "
                f"day-issues={issue_progress} | day-cycles={cycle_progress} | ETA={eta_text}",
                flush=True,
            )
        if snapshot["status"] in {"PASS", "FAILED", "PAUSED"}:
            return
        time.sleep(interval_seconds)


def verify_p05(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    record = verify_prefit_pass(root, 5)
    evidence = _validate_outputs(root, verify_hashes=False)
    if record["predecessor_hashes"].get("PREFIT_P04") != evidence[
        "predecessor_record_sha256"
    ]:
        raise StaleStateError("P05 predecessor record does not match P04")
    return {
        "status": "VALID",
        "validated_stage": "PREFIT_P05",
        "record_sha256": record["record_sha256"],
        "release_id": evidence["release_id"],
        "release_index_path": RELEASE_INDEX_PATH,
        "release_manifest_path": RELEASE_MANIFEST_PATH,
        "target_day_count": evidence["target_day_count"],
        "feature_row_count": evidence["feature_row_count"],
        "trajectory_dynamic_row_count": evidence["trajectory_dynamic_row_count"],
        "trajectory_static_row_count": evidence["trajectory_static_row_count"],
        "trajectory_total_row_count": evidence["trajectory_total_row_count"],
        "trajectory_missing_row_count": evidence["trajectory_missing_row_count"],
        "trajectory_reference_only": True,
        "target_year_partition_count": evidence["target_year_partition_count"],
        "network_requests_made": 0,
        "truth_value_rows_read": 0,
        "model_fits_performed": 0,
        "runtime_isolation": evidence["runtime_isolation"],
    }
