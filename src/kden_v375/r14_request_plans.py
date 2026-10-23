"""Resumable, independent request-plan construction for the sparse R14 scope.

This module performs no network I/O.  It converts the sealed R14 schedule,
field bundle, and regional geometry into deterministic product plans.  The
historical broad-universe plans remain untouched.
"""

from __future__ import annotations

import json
import math
import os
import tomllib
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .contracts import ContractError, PauseRequested, load_project_paths, utc_now
from .hashes import canonical_json_bytes, sha256_bytes, sha256_directory, sha256_file
from .io.atomic import atomic_publish_directory, atomic_publish_file, atomic_write_json
from .r14 import (
    R14_BUNDLE_PATH,
    R14_SCOPE_ID,
    R14_SPATIAL_CONTRACT_ID,
    R14_SPATIAL_CONTRACT_PATH,
    R14_SPATIAL_GEOMETRY_PATH,
    load_r14_field_registry,
    load_r14_scope,
    verify_r14_registry_bundle,
)
from .r14_records import verify_r14_attestation
from .r14_schedule import (
    R14_SCHEDULE_MANIFEST_PATH,
    R14_SCHEDULE_PARQUET_PATH,
    verify_r14_cycle_schedule,
)
from .registries import _arrow_type
from .request_plans import (
    FORBIDDEN_PLAN_COLUMNS,
    native_leads,
    planned_interval,
    source_file_forecast_hour,
    source_object_identity,
)


R14_PLAN_POLICY_SCHEMA_VERSION = "KDEN_V375_R14_REQUEST_PLAN_POLICY_V1"
R14_PLAN_MANIFEST_SCHEMA_VERSION = "KDEN_V375_R14_REQUEST_PLAN_MANIFEST_V1"
R14_PARTITION_RECORD_SCHEMA_VERSION = "KDEN_V375_R14_PLAN_PARTITION_V1"
R14_BUILD_SUMMARY_SCHEMA_VERSION = "KDEN_V375_R14_PLAN_BUILD_SUMMARY_V1"
R14_PLAN_POLICY_PATH = "config/request_plan_r14_v375.toml"
R14_REQUEST_SCHEMA_PATH = "schemas/request_plan_r14_v375.json"
R14_FH00_EVIDENCE_PATH = "reports/step_03_fh00_selector_evidence_v375.json"
R14_PROJECTION_REPORT_PATH = "reports/step_03_r14_cost_disk_projection_v375.json"
PRODUCTS = ("wrfsfcf", "wrfsubhf")
R14_PLAN_DIRECTORY = {
    "wrfsfcf": "hrrr_v4_local_archive/wrfsfcf/manifests/plan_wrfsfcf_r14",
    "wrfsubhf": "hrrr_v4_local_archive/wrfsubhf/manifests/plan_wrfsubhf_q05_r14",
}
R14_PLAN_MANIFEST = {
    "wrfsfcf": (
        "hrrr_v4_local_archive/wrfsfcf/manifests/"
        "plan_wrfsfcf_r14_v375_manifest.json"
    ),
    "wrfsubhf": (
        "hrrr_v4_local_archive/wrfsubhf/manifests/"
        "plan_wrfsubhf_q05_r14_v375_manifest.json"
    ),
}
EXPECTED_COUNTS = {
    "wrfsfcf": {
        "dynamic_fields": 12,
        "static_fields": 1,
        "native_valid_states": 563_583,
        "request_rows": 6_762_997,
    },
    "wrfsubhf": {
        "dynamic_fields": 1,
        "static_fields": 0,
        "native_valid_states": 2_156_601,
        "request_rows": 2_156_601,
    },
}
EXPECTED_R14_REQUEST_COLUMNS = (
    "request_id",
    "target_day",
    "product",
    "cycle_init_utc",
    "source_object_identity",
    "index_object_identity",
    "forecast_lead_min",
    "valid_time_utc",
    "field_registry_id",
    "selector_identity",
    "step_type",
    "interval_start_utc",
    "interval_end_utc",
    "baseline_spatial_contract_id",
    "regional_spatial_contract_id",
    "regional_operator_id",
    "regional_support_count",
    "request_action",
)


class R14RequestPlanError(ContractError):
    """An R14 plan, projection, or publication contract failed."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise R14RequestPlanError(f"JSON artifact must contain an object: {path}")
    return value


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif hasattr(value, "to_pydatetime"):
        result = value.to_pydatetime()
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise R14RequestPlanError("timestamp must be timezone-aware")
    return result.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc_datetime(value).isoformat().replace("+00:00", "Z")


def load_r14_plan_policy(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    policy = _read_toml(paths.root / R14_PLAN_POLICY_PATH)
    if (
        policy.get("schema_version") != R14_PLAN_POLICY_SCHEMA_VERSION
        or policy.get("scope_id") != R14_SCOPE_ID
    ):
        raise R14RequestPlanError("unsupported R14 request-plan policy identity")
    publication = policy.get("publication", {})
    if (
        publication.get("compression") != "zstd"
        or publication.get("partition_key") != "target_year"
        or publication.get("coalescence_policy_id")
        != "EXACT_ADJACENT_REQUIRED_MESSAGES_V1"
        or publication.get("resume_granularity")
        != "completed_target_year_partition"
    ):
        raise R14RequestPlanError("R14 request-plan publication contract changed")
    if int(publication.get("batch_rows", 0)) <= 0 or int(
        publication.get("row_group_rows", 0)
    ) <= 0:
        raise R14RequestPlanError("R14 request-plan batch sizes must be positive")

    project = _read_toml(paths.config)
    source = policy.get("source", {})
    if source.get("root") != project["source"]["primary_root"]:
        raise R14RequestPlanError("R14 plan source disagrees with project config")
    if source.get("index_suffix") != ".idx" or "{product}" not in str(
        source.get("path_template", "")
    ):
        raise R14RequestPlanError("R14 source-object template changed")

    overrides = policy.get("fh00_selector_overrides", {})
    if set(overrides) != {"H38"}:
        raise R14RequestPlanError("R14 requires only the retained H38 FH00 override")
    h38 = overrides["H38"]
    if (
        h38.get("product") != "wrfsfcf"
        or h38.get("interval_semantics") != "preceding_accumulation"
        or h38.get("decoded_step_type") != "accum"
        or int(h38.get("interval_minutes", -1)) != 0
        or h38.get("observed_index_time_descriptor") != "0-0 day acc fcst"
    ):
        raise R14RequestPlanError("R14 H38 FH00 override changed")

    scope = load_r14_scope(paths.root)
    expected = policy.get("expected_counts", {})
    for product in PRODUCTS:
        configured = expected.get(product, {})
        frozen = EXPECTED_COUNTS[product]
        observed = {
            "dynamic_fields": int(configured.get("active_dynamic_field_count", -1)),
            "static_fields": int(configured.get("active_static_field_count", -1)),
            "native_valid_states": int(configured.get("native_valid_state_count", -1)),
            "request_rows": int(configured.get("request_row_count", -1)),
        }
        if observed != frozen:
            raise R14RequestPlanError(f"R14 expected counts changed for {product}")
        scope_product = scope["field_universe"][product]
        if (
            len(scope_product["dynamic"]) != frozen["dynamic_fields"]
            or len(scope_product["static"]) != frozen["static_fields"]
        ):
            raise R14RequestPlanError(f"R14 active field count changed for {product}")
    regional = policy.get("regional_extraction", {})
    if (
        regional.get("contract_id") != R14_SPATIAL_CONTRACT_ID
        or regional.get("geometry_path") != R14_SPATIAL_GEOMETRY_PATH
        or int(regional.get("support_count", -1)) != 8
        or regional.get("static_h14_full_grid_persisted") is not False
        or regional.get("static_h14_values")
        != "KDEN_BI_PLUS_EIGHT_REGIONAL_SUPPORTS"
    ):
        raise R14RequestPlanError("R14 regional plan policy changed")
    return policy


def load_r14_request_schema(project_root: Path | str) -> Any:
    """Build the successor Arrow schema without changing the sealed v1 loader."""

    paths = load_project_paths(project_root)
    value = _read_json(paths.root / R14_REQUEST_SCHEMA_PATH)
    if (
        value.get("schema_version") != "KDEN_V375_PARQUET_SCHEMA_V1"
        or value.get("schema_id") != "KDEN_V375_REQUEST_PLAN_R14_V1"
        or value.get("compression") != "zstd"
    ):
        raise R14RequestPlanError("unsupported R14 request-plan schema identity")
    columns = value.get("columns", [])
    if tuple(column.get("name") for column in columns) != EXPECTED_R14_REQUEST_COLUMNS:
        raise R14RequestPlanError("R14 request-plan column sequence changed")
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise R14RequestPlanError("pyarrow is required for the R14 request schema") from exc
    metadata = {
        b"schema_version": str(value["schema_version"]).encode("ascii"),
        b"schema_id": str(value["schema_id"]).encode("ascii"),
        b"compression": str(value["compression"]).encode("ascii"),
    }
    return pa.schema(
        [
            pa.field(
                column["name"],
                _arrow_type(column["arrow_type"]),
                nullable=bool(column["nullable"]),
            )
            for column in columns
        ],
        metadata=metadata,
    )


def validate_r14_fh00_evidence(project_root: Path | str) -> dict[str, Any]:
    """Retain audited H38 evidence and assert Q05's snapshot-at-FH00 rule."""

    paths = load_project_paths(project_root)
    evidence = _read_json(paths.root / R14_FH00_EVIDENCE_PATH)
    if evidence.get("schema_version") != "KDEN_V375_FH00_SELECTOR_EVIDENCE_V1":
        raise R14RequestPlanError("unsupported FH00 selector evidence schema")
    hourly = next(
        (row for row in evidence.get("objects", []) if row.get("product") == "wrfsfcf"),
        None,
    )
    if hourly is None or set(hourly.get("observations", {})) != {"H38"}:
        raise R14RequestPlanError("R14 H38 FH00 evidence is missing")
    if not str(hourly["observations"]["H38"]).endswith("0-0 day acc fcst:"):
        raise R14RequestPlanError("R14 H38 FH00 evidence changed")
    q05 = load_r14_field_registry(paths.root, "wrfsubhf")[0]
    if (
        q05["field_id"] != "Q05"
        or q05["interval_semantics"] != "snapshot"
        or q05["decoded_step_type"] != "instant"
        or int(q05["interval_minutes"]) != 0
    ):
        raise R14RequestPlanError("Q05 no longer has a point-in-time FH00 contract")
    return {
        "evidence_id": evidence["evidence_id"],
        "historical_evidence_sha256": sha256_file(paths.root / R14_FH00_EVIDENCE_PATH),
        "H38_fh00": "zero_minute_preceding_accumulation",
        "Q05_fh00": "zero_minute_snapshot_from_registry",
        "positive_leads": "field_registry_native_interval",
    }


def _regional_operator_map(project_root: Path) -> dict[str, dict[str, Any]]:
    contract = _read_json(project_root / R14_SPATIAL_CONTRACT_PATH)
    mapping: dict[str, dict[str, Any]] = {}
    for operator, field_ids in contract.get("field_operators", {}).items():
        support_count = 0 if operator == "LOCAL_BASELINE_ONLY_NO_REGIONAL_SUPPORT" else 8
        for field_id in field_ids:
            if field_id in mapping:
                raise R14RequestPlanError(f"duplicate R14 regional operator: {field_id}")
            mapping[field_id] = {
                "regional_spatial_contract_id": R14_SPATIAL_CONTRACT_ID,
                "regional_operator_id": operator,
                "regional_support_count": support_count,
            }
    scope = load_r14_scope(project_root)
    retained = {
        field_id
        for product in PRODUCTS
        for key in ("dynamic", "static")
        for field_id in scope["field_universe"][product][key]
    }
    if set(mapping) != retained:
        raise R14RequestPlanError("R14 regional operator mapping is incomplete")
    return mapping


def _selector_identity(
    field: Mapping[str, str], valid: datetime, interval_minutes: int
) -> str:
    return (
        f"{field['selector_contract_id']}@{valid:%Y%m%dT%H%MZ}"
        f"@D{int(interval_minutes):04d}"
    )


def _request_id(product: str, cycle: datetime, lead: int, field_id: str) -> str:
    return f"REQ-R14-{product.upper()}-{cycle:%Y%m%dT%H%MZ}-L{lead:04d}-{field_id}"


def iter_r14_requests_for_schedule_row(
    schedule_row: Mapping[str, Any],
    *,
    product: str,
    fields: Sequence[Mapping[str, str]],
    policy: Mapping[str, Any],
    regional_operators: Mapping[str, Mapping[str, Any]],
    include_static_h14: bool,
) -> Iterator[dict[str, Any]]:
    """Expand one cycle row; exposed so bounded tests exercise exact plan rows."""

    cycle = _utc_datetime(schedule_row["cycle_init_utc"])
    window_end = _utc_datetime(schedule_row["window_end_utc"])
    target_day = schedule_row["target_day"]
    overrides = policy["fh00_selector_overrides"]
    for lead in native_leads(schedule_row, product):
        valid = cycle + timedelta(minutes=lead)
        if valid >= window_end:
            raise R14RequestPlanError("R14 planned valid time reaches right-open endpoint")
        file_hour = source_file_forecast_hour(product, lead)
        source_url = source_object_identity(policy, product, cycle, file_hour)
        index_url = source_url + str(policy["source"]["index_suffix"])
        for field in fields:
            if field["field_id"] == "H14" and not include_static_h14:
                continue
            semantics, step_type, duration, interval_start, interval_end = planned_interval(
                field, lead, valid, overrides
            )
            regional = regional_operators[field["field_id"]]
            yield {
                "request_id": _request_id(product, cycle, lead, field["field_id"]),
                "target_day": target_day,
                "product": product,
                "cycle_init_utc": cycle,
                "source_object_identity": source_url,
                "index_object_identity": index_url,
                "forecast_lead_min": lead,
                "valid_time_utc": valid,
                "field_registry_id": field["field_id"],
                "selector_identity": _selector_identity(field, valid, duration),
                "step_type": step_type,
                "interval_start_utc": interval_start,
                "interval_end_utc": interval_end,
                "baseline_spatial_contract_id": field["spatial_contract_id"],
                "regional_spatial_contract_id": regional[
                    "regional_spatial_contract_id"
                ],
                "regional_operator_id": regional["regional_operator_id"],
                "regional_support_count": regional["regional_support_count"],
                "request_action": field["acquisition_contract_id"],
            }
            if field["field_id"] == "H14":
                include_static_h14 = False


def _partition_schedule_rows(
    project_root: Path, product: str
) -> dict[int, list[dict[str, Any]]]:
    verify_r14_cycle_schedule(project_root)
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise R14RequestPlanError("pyarrow is required to read the R14 schedule") from exc
    table = pq.read_table(project_root / R14_SCHEDULE_PARQUET_PATH)
    partitions: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen: set[datetime] = set()
    for row in table.to_pylist():
        if row["product"] != product:
            continue
        cycle = _utc_datetime(row["cycle_init_utc"])
        if cycle in seen:
            raise R14RequestPlanError(f"duplicate cycle in R14 {product} schedule")
        seen.add(cycle)
        partitions[row["target_day"].year].append(row)
    if tuple(partitions) != (2021, 2022, 2023, 2024, 2025, 2026):
        raise R14RequestPlanError(f"R14 {product} year partitions changed")
    return dict(partitions)


def expected_r14_product_counts(
    schedule_rows: Iterable[Mapping[str, Any]], product: str, fields: Sequence[Mapping[str, str]]
) -> dict[str, int]:
    native_states = sum(len(native_leads(row, product)) for row in schedule_rows)
    static_fields = sum(field["field_id"] == "H14" for field in fields)
    dynamic_fields = len(fields) - static_fields
    return {
        "native_valid_state_count": native_states,
        "request_row_count": native_states * dynamic_fields + static_fields,
    }


def _metric_bucket() -> dict[str, int]:
    return {
        "request_rows": 0,
        "messages": 0,
        "baseline_point_values": 0,
        "regional_values": 0,
        "tile_cells": 0,
        "full_grid_cells_persisted": 0,
        "extracted_values": 0,
    }


def _add_bucket(destination: dict[str, int], source: Mapping[str, int]) -> None:
    for key in destination:
        destination[key] += int(source.get(key, 0))


def _spatial_value_counts(
    field: Mapping[str, str],
    regional: Mapping[str, Any],
    geometry: Mapping[str, Any],
) -> tuple[int, int, int]:
    if field["field_id"] == "H14":
        return 1, int(regional["regional_support_count"]), 0
    baseline = geometry["spatial_contracts"][field["spatial_contract_id"]]
    point_values = len(baseline.get("point_outputs", []))
    shape = baseline.get("tile_shape")
    tile_cells = 0 if shape is None else int(shape[0]) * int(shape[1])
    return point_values, int(regional["regional_support_count"]), tile_cells


def _record_metric(
    bucket: dict[str, int], *, point_values: int, regional_values: int, tile_cells: int
) -> None:
    bucket["request_rows"] += 1
    bucket["messages"] += 1
    bucket["baseline_point_values"] += point_values
    bucket["regional_values"] += regional_values
    bucket["tile_cells"] += tile_cells
    bucket["extracted_values"] += point_values + regional_values + tile_cells


def _finish_projection_bucket(
    bucket: Mapping[str, int], assumptions: Mapping[str, Any]
) -> dict[str, int]:
    result = {key: int(value) for key, value in bucket.items()}
    messages = result["messages"]
    values = result["extracted_values"]
    numerator = int(assumptions["coalesced_range_ratio_numerator"])
    denominator = int(assumptions["coalesced_range_ratio_denominator"])
    result["estimated_coalesced_byte_ranges"] = math.ceil(
        messages * numerator / denominator
    )
    result["estimated_source_message_bytes"] = messages * int(
        assumptions["mean_message_bytes"]
    )
    result["estimated_plan_parquet_bytes"] = result["request_rows"] * int(
        assumptions["plan_row_bytes"]
    )
    result["estimated_canonical_output_bytes"] = (
        result["request_rows"] * int(assumptions["canonical_row_overhead_bytes"])
        + values * int(assumptions["numeric_value_bytes"])
    )
    return result


def _spatial_shape_key(point_values: int, regional_values: int, tile_cells: int) -> str:
    if tile_cells:
        return f"tile_{int(math.sqrt(tile_cells))}x{int(math.sqrt(tile_cells))}_regional_{regional_values}"
    return f"point_{point_values}_regional_{regional_values}"


def _build_inputs(project_root: Path) -> dict[str, str]:
    paths = (
        R14_PLAN_POLICY_PATH,
        R14_REQUEST_SCHEMA_PATH,
        R14_BUNDLE_PATH,
        R14_SCHEDULE_MANIFEST_PATH,
        R14_SPATIAL_CONTRACT_PATH,
        R14_SPATIAL_GEOMETRY_PATH,
        R14_FH00_EVIDENCE_PATH,
    )
    return {relative: sha256_file(project_root / relative) for relative in paths}


def _empty_columns(schema: Any) -> dict[str, list[Any]]:
    return {field.name: [] for field in schema}


def _partition_record_path(partition_dir: Path) -> Path:
    return partition_dir / "partition_record.json"


def _validate_partition_record(
    stage: Path,
    record: Mapping[str, Any],
    *,
    product: str,
    year: int,
    schema: Any,
    build_inputs_sha256: str,
) -> dict[str, Any]:
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise R14RequestPlanError(f"R14 partition record hash mismatch: {product}/{year}")
    if (
        record.get("schema_version") != R14_PARTITION_RECORD_SCHEMA_VERSION
        or record.get("product") != product
        or int(record.get("target_year", -1)) != year
        or record.get("build_inputs_sha256") != build_inputs_sha256
    ):
        raise R14RequestPlanError(f"stale R14 staging partition: {product}/{year}")
    part_path = stage / record["path"]
    if (
        sha256_file(part_path) != record.get("sha256")
        or part_path.stat().st_size != int(record.get("size_bytes", -1))
    ):
        raise R14RequestPlanError(f"R14 staging partition changed: {product}/{year}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise R14RequestPlanError("pyarrow is required to verify an R14 partition") from exc
    parquet = pq.ParquetFile(part_path)
    if not parquet.schema_arrow.equals(schema, check_metadata=True):
        raise R14RequestPlanError(f"R14 partition schema changed: {product}/{year}")
    if parquet.metadata.num_rows != int(record["row_count"]):
        raise R14RequestPlanError(f"R14 partition row count changed: {product}/{year}")
    return dict(record)


def _write_progress(
    project_root: Path,
    run_id: str,
    *,
    product: str,
    status: str,
    completed_years: Sequence[int],
    current_year: int | None,
    schedule_rows_processed: int,
    schedule_rows_in_year: int,
    request_rows_completed: int,
) -> None:
    value = {
        "schema_version": "KDEN_V375_R14_STEP03_PROGRESS_V1",
        "run_id": run_id,
        "step_id": "STEP_03_R14",
        "product": product,
        "status": status,
        "completed_target_years": list(completed_years),
        "current_target_year": current_year,
        "current_year_schedule_rows_processed": schedule_rows_processed,
        "current_year_schedule_rows_total": schedule_rows_in_year,
        "product_request_rows_completed": request_rows_completed,
        "updated_at_utc": utc_now(),
    }
    atomic_write_json(project_root / "runs" / run_id / "step03_r14_progress.json", value)


def _build_year_partition(
    *,
    project_root: Path,
    stage: Path,
    product: str,
    year: int,
    year_rows: Sequence[Mapping[str, Any]],
    fields: Sequence[Mapping[str, str]],
    policy: Mapping[str, Any],
    regional_operators: Mapping[str, Mapping[str, Any]],
    geometry: Mapping[str, Any],
    schema: Any,
    build_inputs_sha256: str,
    include_static_h14: bool,
    run_id: str,
    completed_years: Sequence[int],
    prior_request_rows: int,
    pause: Any | None,
) -> dict[str, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise R14RequestPlanError("pyarrow is required to build R14 plans") from exc
    partition_dir = stage / f"target_year={year}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    part_name = f"part-{year}-{product}-r14.parquet"
    part_path = partition_dir / part_name
    record_path = _partition_record_path(partition_dir)
    if part_path.exists() and record_path.exists():
        return _validate_partition_record(
            stage,
            _read_json(record_path),
            product=product,
            year=year,
            schema=schema,
            build_inputs_sha256=build_inputs_sha256,
        )
    part_path.unlink(missing_ok=True)
    record_path.unlink(missing_ok=True)
    temporary = partition_dir / f".{part_name}.tmp"
    temporary.unlink(missing_ok=True)

    columns = _empty_columns(schema)
    writer = pq.ParquetWriter(
        temporary,
        schema,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
    )
    batch_rows = int(policy["publication"]["batch_rows"])
    row_group_rows = int(policy["publication"]["row_group_rows"])
    request_count = 0
    native_state_count = 0
    source_object_count = 0
    fields_seen: Counter[str] = Counter()
    fields_by_id = {field["field_id"]: field for field in fields}
    totals = _metric_bucket()
    by_field = {field["field_id"]: _metric_bucket() for field in fields}
    by_shape: dict[str, dict[str, int]] = defaultdict(_metric_bucket)
    maximum_lead = 0
    maximum_valid: datetime | None = None
    maximum_window_end: datetime | None = None
    logical_digest = sha256()
    static_pending = include_static_h14
    try:
        for row_index, schedule_row in enumerate(year_rows, start=1):
            if pause is not None:
                pause.raise_if_requested()
            leads = native_leads(schedule_row, product)
            native_state_count += len(leads)
            cycle = _utc_datetime(schedule_row["cycle_init_utc"])
            window_end = _utc_datetime(schedule_row["window_end_utc"])
            maximum_window_end = (
                window_end
                if maximum_window_end is None or window_end > maximum_window_end
                else maximum_window_end
            )
            source_hours = {source_file_forecast_hour(product, lead) for lead in leads}
            source_object_count += len(source_hours)
            for request in iter_r14_requests_for_schedule_row(
                schedule_row,
                product=product,
                fields=fields,
                policy=policy,
                regional_operators=regional_operators,
                include_static_h14=static_pending,
            ):
                field_id = request["field_registry_id"]
                if field_id == "H14":
                    static_pending = False
                for name in columns:
                    columns[name].append(request[name])
                request_count += 1
                fields_seen[field_id] += 1
                logical_digest.update(request["request_id"].encode("ascii"))
                logical_digest.update(b"\n")
                maximum_lead = max(maximum_lead, int(request["forecast_lead_min"]))
                valid = _utc_datetime(request["valid_time_utc"])
                maximum_valid = (
                    valid if maximum_valid is None or valid > maximum_valid else maximum_valid
                )
                field = fields_by_id[field_id]
                regional = regional_operators[field_id]
                point_values, regional_values, tile_cells = _spatial_value_counts(
                    field, regional, geometry
                )
                _record_metric(
                    totals,
                    point_values=point_values,
                    regional_values=regional_values,
                    tile_cells=tile_cells,
                )
                _record_metric(
                    by_field[field_id],
                    point_values=point_values,
                    regional_values=regional_values,
                    tile_cells=tile_cells,
                )
                shape = _spatial_shape_key(point_values, regional_values, tile_cells)
                _record_metric(
                    by_shape[shape],
                    point_values=point_values,
                    regional_values=regional_values,
                    tile_cells=tile_cells,
                )
                if len(columns["request_id"]) >= batch_rows:
                    writer.write_table(
                        pa.Table.from_pydict(columns, schema=schema),
                        row_group_size=row_group_rows,
                    )
                    columns = _empty_columns(schema)
            if row_index == 1 or row_index % 250 == 0:
                _write_progress(
                    project_root,
                    run_id,
                    product=product,
                    status="RUNNING",
                    completed_years=completed_years,
                    current_year=year,
                    schedule_rows_processed=row_index,
                    schedule_rows_in_year=len(year_rows),
                    request_rows_completed=prior_request_rows + request_count,
                )
        if columns["request_id"]:
            writer.write_table(
                pa.Table.from_pydict(columns, schema=schema),
                row_group_size=row_group_rows,
            )
    except PauseRequested:
        _write_progress(
            project_root,
            run_id,
            product=product,
            status="PAUSED",
            completed_years=completed_years,
            current_year=year,
            schedule_rows_processed=0,
            schedule_rows_in_year=len(year_rows),
            request_rows_completed=prior_request_rows,
        )
        raise
    finally:
        writer.close()
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    parquet_hash = atomic_publish_file(temporary, part_path, replace=False)
    record_body = {
        "schema_version": R14_PARTITION_RECORD_SCHEMA_VERSION,
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "target_year": year,
        "path": part_path.relative_to(stage).as_posix(),
        "sha256": parquet_hash,
        "size_bytes": part_path.stat().st_size,
        "row_count": request_count,
        "native_valid_state_count": native_state_count,
        "unique_source_object_count": source_object_count,
        "field_request_counts": dict(sorted(fields_seen.items())),
        "maximum_forecast_lead_min": maximum_lead,
        "maximum_valid_time_utc": _iso(maximum_valid),
        "maximum_window_end_utc": _iso(maximum_window_end),
        "all_valid_times_strictly_before_window_end": True,
        "logical_request_sequence_sha256": logical_digest.hexdigest(),
        "build_inputs_sha256": build_inputs_sha256,
        "projection_raw": {
            "by_year": totals,
            "by_field": dict(sorted(by_field.items())),
            "by_spatial_shape": dict(sorted(by_shape.items())),
        },
    }
    record = {
        **record_body,
        "record_sha256": sha256_bytes(canonical_json_bytes(record_body)),
    }
    atomic_write_json(record_path, record, replace=False)
    return record


def _aggregate_partition_records(
    product: str,
    fields: Sequence[Mapping[str, str]],
    records: Sequence[Mapping[str, Any]],
    policy: Mapping[str, Any],
    regional_operators: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    request_count = sum(int(record["row_count"]) for record in records)
    state_count = sum(int(record["native_valid_state_count"]) for record in records)
    source_count = sum(int(record["unique_source_object_count"]) for record in records)
    field_counts: Counter[str] = Counter()
    total = _metric_bucket()
    by_field = {field["field_id"]: _metric_bucket() for field in fields}
    by_year: dict[str, dict[str, int]] = {}
    source_objects_by_year: dict[str, int] = {}
    by_shape: dict[str, dict[str, int]] = defaultdict(_metric_bucket)
    for record in records:
        field_counts.update(record["field_request_counts"])
        raw = record["projection_raw"]
        year_bucket = {key: int(value) for key, value in raw["by_year"].items()}
        by_year[str(record["target_year"])] = year_bucket
        source_objects_by_year[str(record["target_year"])] = int(
            record["unique_source_object_count"]
        )
        _add_bucket(total, year_bucket)
        for field_id, bucket in raw["by_field"].items():
            _add_bucket(by_field[field_id], bucket)
        for shape, bucket in raw["by_spatial_shape"].items():
            _add_bucket(by_shape[shape], bucket)
    frozen = EXPECTED_COUNTS[product]
    if request_count != frozen["request_rows"] or state_count != frozen["native_valid_states"]:
        raise R14RequestPlanError(f"R14 {product} logical counts changed")
    expected_field_counts = {
        field["field_id"]: (
            1 if field["field_id"] == "H14" else frozen["native_valid_states"]
        )
        for field in fields
    }
    if dict(field_counts) != expected_field_counts:
        raise R14RequestPlanError(f"R14 {product} field expansion changed")
    max_valid = max(_utc_datetime(record["maximum_valid_time_utc"]) for record in records)
    max_window_end = max(
        _utc_datetime(record["maximum_window_end_utc"]) for record in records
    )
    if not max_valid < max_window_end:
        raise R14RequestPlanError("R14 plan reaches the right-open endpoint")
    maximum_lead = max(int(record["maximum_forecast_lead_min"]) for record in records)
    if maximum_lead >= 48 * 60:
        raise R14RequestPlanError("FH48-only tail remains in R14 plan")
    assumptions = policy["projection_assumptions"]
    projection = {
        "product": product,
        "unique_source_objects": source_count,
        "by_product": _finish_projection_bucket(total, assumptions),
        "by_field": {
            key: _finish_projection_bucket(value, assumptions)
            for key, value in sorted(by_field.items())
        },
        "by_year": {
            key: {
                **_finish_projection_bucket(value, assumptions),
                "unique_source_objects": source_objects_by_year[key],
            }
            for key, value in sorted(by_year.items())
        },
        "by_spatial_shape": {
            key: _finish_projection_bucket(value, assumptions)
            for key, value in sorted(by_shape.items())
        },
    }
    sequence_members = [
        {
            "target_year": int(record["target_year"]),
            "logical_request_sequence_sha256": record[
                "logical_request_sequence_sha256"
            ],
        }
        for record in records
    ]
    return {
        "request_row_count": request_count,
        "native_valid_state_count": state_count,
        "unique_source_object_count": source_count,
        "field_request_counts": dict(sorted(field_counts.items())),
        "maximum_forecast_lead_min": maximum_lead,
        "maximum_valid_time_utc": _iso(max_valid),
        "maximum_window_end_utc": _iso(max_window_end),
        "logical_request_sequence_sha256": sha256_bytes(
            canonical_json_bytes(sequence_members)
        ),
        "partition_sequence_hashes": sequence_members,
        "regional_operator_by_field": {
            field_id: dict(regional_operators[field_id])
            for field_id in sorted(regional_operators)
            if field_id in expected_field_counts
        },
        "projection": projection,
    }


def _publish_deterministic_json(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists():
        if canonical_json_bytes(_read_json(path)) != canonical_json_bytes(value):
            raise R14RequestPlanError(f"immutable R14 artifact differs: {path}")
        return sha256_file(path)
    return atomic_write_json(path, value, replace=False)


def _manifest_from_summary(
    project_root: Path,
    product: str,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    registry = verify_r14_registry_bundle(project_root)["bundle"]
    schedule = verify_r14_cycle_schedule(project_root)["manifest"]
    step02 = verify_r14_attestation(project_root, "STEP_02_R14")
    fh00 = validate_r14_fh00_evidence(project_root)
    destination = project_root / R14_PLAN_DIRECTORY[product]
    body = {
        "schema_version": R14_PLAN_MANIFEST_SCHEMA_VERSION,
        "plan_id": (
            "KDEN_V375_PLAN_WRFSFCF_R14_20210101_20260911_V1"
            if product == "wrfsfcf"
            else "KDEN_V375_PLAN_WRFSUBHF_Q05_R14_20210101_20260911_V1"
        ),
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "plan_directory": R14_PLAN_DIRECTORY[product],
        "directory_sha256": sha256_directory(destination),
        "build_summary_sha256": summary["summary_sha256"],
        "logical_request_sequence_sha256": summary[
            "logical_request_sequence_sha256"
        ],
        "request_row_count": summary["request_row_count"],
        "native_valid_state_count": summary["native_valid_state_count"],
        "unique_source_object_count": summary["unique_source_object_count"],
        "index_object_fetch_count": summary["unique_source_object_count"],
        "field_request_counts": summary["field_request_counts"],
        "maximum_forecast_lead_min": summary["maximum_forecast_lead_min"],
        "maximum_valid_time_utc": summary["maximum_valid_time_utc"],
        "maximum_window_end_utc": summary["maximum_window_end_utc"],
        "partitions": summary["partitions"],
        "request_schema": {
            "path": R14_REQUEST_SCHEMA_PATH,
            "sha256": sha256_file(project_root / R14_REQUEST_SCHEMA_PATH),
        },
        "r14_registry_bundle": {
            "path": R14_BUNDLE_PATH,
            "bundle_sha256": registry["bundle_sha256"],
            "file_sha256": sha256_file(project_root / R14_BUNDLE_PATH),
        },
        "r14_schedule": {
            "path": R14_SCHEDULE_MANIFEST_PATH,
            "manifest_sha256": schedule["manifest_sha256"],
            "file_sha256": sha256_file(project_root / R14_SCHEDULE_MANIFEST_PATH),
        },
        "step02_r14_record_sha256": step02["record_sha256"],
        "plan_policy": {
            "path": R14_PLAN_POLICY_PATH,
            "sha256": sha256_file(project_root / R14_PLAN_POLICY_PATH),
        },
        "fh00_selector_evidence": {
            "path": R14_FH00_EVIDENCE_PATH,
            "sha256": sha256_file(project_root / R14_FH00_EVIDENCE_PATH),
            **fh00,
        },
        "regional_spatial": {
            "contract_id": R14_SPATIAL_CONTRACT_ID,
            "contract_path": R14_SPATIAL_CONTRACT_PATH,
            "contract_sha256": sha256_file(project_root / R14_SPATIAL_CONTRACT_PATH),
            "geometry_path": R14_SPATIAL_GEOMETRY_PATH,
            "geometry_sha256": sha256_file(project_root / R14_SPATIAL_GEOMETRY_PATH),
            "operator_by_field": summary["regional_operator_by_field"],
        },
        "deduplication": {
            "one_index_fetch_per_unique_source_object": True,
            "logical_message_identity_unique": True,
            "coalescence_policy_id": "EXACT_ADJACENT_REQUIRED_MESSAGES_V1",
            "byte_ranges_resolved_from_source_index_at_acquisition": True,
        },
        "projection": summary["projection"],
    }
    return {**body, "plan_sha256": sha256_bytes(canonical_json_bytes(body))}


def build_r14_product_plan(
    project_root: Path | str,
    product: str,
    *,
    run_id: str,
    pause: Any | None = None,
) -> dict[str, Any]:
    """Build one product plan with resumable, year-level checkpoints."""

    if product not in PRODUCTS:
        raise R14RequestPlanError(f"unsupported R14 product: {product!r}")
    paths = load_project_paths(project_root)
    verify_r14_registry_bundle(paths.root)
    verify_r14_cycle_schedule(paths.root)
    verify_r14_attestation(paths.root, "STEP_02_R14")
    policy = load_r14_plan_policy(paths.root)
    validate_r14_fh00_evidence(paths.root)
    fields = load_r14_field_registry(paths.root, product)
    regional = _regional_operator_map(paths.root)
    geometry = _read_json(paths.root / "registries/grid_geometry_v375.json")
    schema = load_r14_request_schema(paths.root)
    if set(schema.names) & FORBIDDEN_PLAN_COLUMNS:
        raise R14RequestPlanError("R14 request schema contains a forbidden dependency")
    partitions = _partition_schedule_rows(paths.root, product)
    schedule_rows = [row for values in partitions.values() for row in values]
    expected = expected_r14_product_counts(schedule_rows, product, fields)
    if expected != {
        "native_valid_state_count": EXPECTED_COUNTS[product]["native_valid_states"],
        "request_row_count": EXPECTED_COUNTS[product]["request_rows"],
    }:
        raise R14RequestPlanError(f"R14 {product} pre-build counts changed")

    destination = paths.root / R14_PLAN_DIRECTORY[product]
    manifest_path = paths.root / R14_PLAN_MANIFEST[product]
    if destination.exists():
        summary = _read_json(destination / "_build_summary.json")
        manifest = _manifest_from_summary(paths.root, product, summary)
        _publish_deterministic_json(manifest_path, manifest)
        verified = verify_r14_product_plan(paths.root, product)
        return {"manifest": manifest, "projection": summary["projection"], "gate_evidence": verified}

    stage = paths.root / "runs" / run_id / "step03_r14_staging" / product
    stage.mkdir(parents=True, exist_ok=True)
    build_inputs = _build_inputs(paths.root)
    build_inputs_sha256 = sha256_bytes(canonical_json_bytes(build_inputs))
    records: list[dict[str, Any]] = []
    completed_years: list[int] = []
    prior_rows = 0
    static_written = False
    for year, year_rows in partitions.items():
        record = _build_year_partition(
            project_root=paths.root,
            stage=stage,
            product=product,
            year=year,
            year_rows=year_rows,
            fields=fields,
            policy=policy,
            regional_operators=regional,
            geometry=geometry,
            schema=schema,
            build_inputs_sha256=build_inputs_sha256,
            include_static_h14=product == "wrfsfcf" and not static_written,
            run_id=run_id,
            completed_years=completed_years,
            prior_request_rows=prior_rows,
            pause=pause,
        )
        records.append(record)
        completed_years.append(year)
        prior_rows += int(record["row_count"])
        static_written = static_written or int(record["field_request_counts"].get("H14", 0)) == 1
        _write_progress(
            paths.root,
            run_id,
            product=product,
            status="PARTITION_COMPLETE",
            completed_years=completed_years,
            current_year=None,
            schedule_rows_processed=0,
            schedule_rows_in_year=0,
            request_rows_completed=prior_rows,
        )

    aggregate = _aggregate_partition_records(product, fields, records, policy, regional)
    summary_body = {
        "schema_version": R14_BUILD_SUMMARY_SCHEMA_VERSION,
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "build_inputs": build_inputs,
        "build_inputs_sha256": build_inputs_sha256,
        "partitions": [
            {
                key: record[key]
                for key in (
                    "target_year", "path", "sha256", "size_bytes", "row_count",
                    "native_valid_state_count", "unique_source_object_count",
                    "logical_request_sequence_sha256", "record_sha256",
                )
            }
            for record in records
        ],
        **aggregate,
    }
    summary = {
        **summary_body,
        "summary_sha256": sha256_bytes(canonical_json_bytes(summary_body)),
    }
    atomic_write_json(stage / "_build_summary.json", summary, replace=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    atomic_publish_directory(stage, destination)
    manifest = _manifest_from_summary(paths.root, product, summary)
    _publish_deterministic_json(manifest_path, manifest)
    verified = verify_r14_product_plan(paths.root, product)
    _write_progress(
        paths.root,
        run_id,
        product=product,
        status="PRODUCT_PLAN_PASS",
        completed_years=completed_years,
        current_year=None,
        schedule_rows_processed=0,
        schedule_rows_in_year=0,
        request_rows_completed=aggregate["request_row_count"],
    )
    return {"manifest": manifest, "projection": aggregate["projection"], "gate_evidence": verified}


def _parquet_statistics(metadata: Any, column_index: int) -> Iterator[Any]:
    for index in range(metadata.num_row_groups):
        statistics = metadata.row_group(index).column(column_index).statistics
        if statistics is None or not statistics.has_min_max:
            raise R14RequestPlanError("R14 request-plan row group lacks statistics")
        yield statistics


def verify_r14_product_plan(project_root: Path | str, product: str) -> dict[str, Any]:
    """Verify either R14 product plan without opening or requiring its peer."""

    if product not in PRODUCTS:
        raise R14RequestPlanError(f"unsupported R14 product: {product!r}")
    paths = load_project_paths(project_root)
    policy = load_r14_plan_policy(paths.root)
    validate_r14_fh00_evidence(paths.root)
    registry = verify_r14_registry_bundle(paths.root)["bundle"]
    schedule = verify_r14_cycle_schedule(paths.root)["manifest"]
    step02 = verify_r14_attestation(paths.root, "STEP_02_R14")
    manifest = _read_json(paths.root / R14_PLAN_MANIFEST[product])
    if manifest.get("schema_version") != R14_PLAN_MANIFEST_SCHEMA_VERSION:
        raise R14RequestPlanError("unsupported R14 request-plan manifest schema")
    body = dict(manifest)
    supplied = body.pop("plan_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise R14RequestPlanError("R14 request-plan manifest hash mismatch")
    if manifest.get("scope_id") != R14_SCOPE_ID or manifest.get("product") != product:
        raise R14RequestPlanError("R14 request-plan identity changed")
    if manifest["r14_registry_bundle"]["bundle_sha256"] != registry["bundle_sha256"]:
        raise R14RequestPlanError("R14 request plan is stale against registry bundle")
    if manifest["r14_schedule"]["manifest_sha256"] != schedule["manifest_sha256"]:
        raise R14RequestPlanError("R14 request plan is stale against schedule")
    if manifest.get("step02_r14_record_sha256") != step02["record_sha256"]:
        raise R14RequestPlanError("R14 request plan is stale against Step 02")
    for binding, relative in (
        ("plan_policy", R14_PLAN_POLICY_PATH),
        ("request_schema", R14_REQUEST_SCHEMA_PATH),
    ):
        if manifest[binding]["sha256"] != sha256_file(paths.root / relative):
            raise R14RequestPlanError(f"R14 request plan changed binding: {binding}")
    destination = paths.root / R14_PLAN_DIRECTORY[product]
    if sha256_directory(destination) != manifest.get("directory_sha256"):
        raise R14RequestPlanError("sealed R14 request-plan directory changed")
    summary = _read_json(destination / "_build_summary.json")
    summary_body = dict(summary)
    summary_hash = summary_body.pop("summary_sha256", None)
    if summary_hash != sha256_bytes(canonical_json_bytes(summary_body)):
        raise R14RequestPlanError("R14 build-summary hash mismatch")
    if summary_hash != manifest.get("build_summary_sha256"):
        raise R14RequestPlanError("R14 manifest points to another build summary")
    if summary.get("build_inputs") != _build_inputs(paths.root):
        raise R14RequestPlanError("R14 product plan build inputs changed")
    schema = load_r14_request_schema(paths.root)
    if set(schema.names) & FORBIDDEN_PLAN_COLUMNS:
        raise R14RequestPlanError("R14 plan requires a forbidden dependency column")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise R14RequestPlanError("pyarrow is required to verify R14 plans") from exc
    total_rows = 0
    maximum_lead = 0
    maximum_valid: datetime | None = None
    for part in manifest.get("partitions", []):
        path = destination / part["path"]
        if (
            sha256_file(path) != part["sha256"]
            or path.stat().st_size != int(part["size_bytes"])
        ):
            raise R14RequestPlanError(f"R14 plan partition changed: {part['path']}")
        parquet = pq.ParquetFile(path)
        if not parquet.schema_arrow.equals(schema, check_metadata=True):
            raise R14RequestPlanError("R14 plan partition schema changed")
        if parquet.metadata.num_rows != int(part["row_count"]):
            raise R14RequestPlanError("R14 plan partition row count changed")
        total_rows += parquet.metadata.num_rows
        lead_index = schema.get_field_index("forecast_lead_min")
        valid_index = schema.get_field_index("valid_time_utc")
        maximum_lead = max(
            maximum_lead,
            *(int(value.max) for value in _parquet_statistics(parquet.metadata, lead_index)),
        )
        part_max_valid = max(
            _utc_datetime(value.max)
            for value in _parquet_statistics(parquet.metadata, valid_index)
        )
        maximum_valid = (
            part_max_valid
            if maximum_valid is None or part_max_valid > maximum_valid
            else maximum_valid
        )
    frozen = EXPECTED_COUNTS[product]
    if total_rows != frozen["request_rows"] or total_rows != int(
        manifest.get("request_row_count", -1)
    ):
        raise R14RequestPlanError("R14 request-plan total row count changed")
    if int(manifest.get("native_valid_state_count", -1)) != frozen[
        "native_valid_states"
    ]:
        raise R14RequestPlanError("R14 native-state count changed")
    if maximum_lead != int(manifest.get("maximum_forecast_lead_min", -1)):
        raise R14RequestPlanError("R14 maximum forecast lead changed")
    if maximum_valid is None or _iso(maximum_valid) != manifest.get(
        "maximum_valid_time_utc"
    ):
        raise R14RequestPlanError("R14 maximum valid time changed")
    if not maximum_valid < _utc_datetime(manifest["maximum_window_end_utc"]):
        raise R14RequestPlanError("R14 request plan reaches right-open endpoint")
    if maximum_lead >= 48 * 60:
        raise R14RequestPlanError("FH48-only tail remains in R14 request plan")
    fields = load_r14_field_registry(paths.root, product)
    expected_field_counts = {
        field["field_id"]: (
            1 if field["field_id"] == "H14" else frozen["native_valid_states"]
        )
        for field in fields
    }
    if manifest.get("field_request_counts") != expected_field_counts:
        raise R14RequestPlanError("R14 plan field request counts changed")
    sentinel = "H16" if product == "wrfsfcf" else "Q05"
    if int(expected_field_counts.get(sentinel, 0)) <= 0:
        raise R14RequestPlanError(f"R14 {sentinel} has no network requests")
    h14_count = int(expected_field_counts.get("H14", 0))
    if (product == "wrfsfcf" and h14_count != 1) or (
        product == "wrfsubhf" and h14_count != 0
    ):
        raise R14RequestPlanError("R14 H14 once-per-grid gate failed")
    return {
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "plan_sha256": manifest["plan_sha256"],
        "directory_sha256": manifest["directory_sha256"],
        "request_row_count": total_rows,
        "native_valid_state_count": frozen["native_valid_states"],
        "unique_source_object_count": int(manifest["unique_source_object_count"]),
        "index_object_fetch_count": int(manifest["index_object_fetch_count"]),
        "estimated_coalesced_byte_ranges": int(
            manifest["projection"]["by_product"]["estimated_coalesced_byte_ranges"]
        ),
        "partition_count": len(manifest["partitions"]),
        "field_request_counts": expected_field_counts,
        "maximum_forecast_lead_min": maximum_lead,
        "maximum_valid_time_utc": _iso(maximum_valid),
        "all_valid_times_strictly_before_window_end": True,
        "fh48_only_tail_absent": True,
        "normal_network_sentinel": sentinel,
        "normal_network_sentinel_count": expected_field_counts[sentinel],
        "h14_once_per_grid_version": h14_count == 1 if product == "wrfsfcf" else True,
        "h14_full_grid_persisted": False,
        "forbidden_dependency_columns": [],
        "independently_loadable": True,
        "source_object_fetches_deduplicated": True,
        "logical_messages_deduplicated": True,
        "coalescence_policy_id": policy["publication"]["coalescence_policy_id"],
        "sealed_before_network_execution": True,
    }


def iter_r14_product_plan_batches(
    project_root: Path | str,
    product: str,
    *,
    columns: Sequence[str] | None = None,
    batch_size: int = 65_536,
) -> Iterator[Any]:
    verify_r14_product_plan(project_root, product)
    paths = load_project_paths(project_root)
    manifest = _read_json(paths.root / R14_PLAN_MANIFEST[product])
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise R14RequestPlanError("pyarrow is required to load R14 plans") from exc
    for part in manifest["partitions"]:
        parquet = pq.ParquetFile(paths.root / R14_PLAN_DIRECTORY[product] / part["path"])
        yield from parquet.iter_batches(batch_size=batch_size, columns=columns)
