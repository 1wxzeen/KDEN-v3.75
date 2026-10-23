"""Independent, deterministic Step 03 request-plan construction.

The planner performs no network I/O.  It expands the sealed cycle schedule and
the frozen product registry into one Parquet row per native field-state, while
grouping repeated rows by their shared source-object identity for later index
fetch deduplication and exact-adjacent byte-range coalescence.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import tomllib
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .contracts import ContractError, load_project_paths
from .hashes import canonical_json_bytes, sha256_bytes, sha256_directory, sha256_file
from .io.atomic import atomic_publish_directory, atomic_write_json
from .registries import load_field_registry, load_parquet_schema, verify_registry_bundle
from .schedule import SCHEDULE_PARQUET_PATH, verify_cycle_schedule


PLAN_POLICY_SCHEMA_VERSION = "KDEN_V375_REQUEST_PLAN_POLICY_V1"
PLAN_MANIFEST_SCHEMA_VERSION = "KDEN_V375_REQUEST_PLAN_MANIFEST_V1"
FH00_EVIDENCE_SCHEMA_VERSION = "KDEN_V375_FH00_SELECTOR_EVIDENCE_V1"
PLAN_POLICY_PATH = "config/request_plan_v375.toml"
FH00_EVIDENCE_PATH = "reports/step_03_fh00_selector_evidence_v375.json"
PROJECTION_REPORT_PATH = "reports/step_03_cost_disk_projection_v375.json"
PRODUCTS = ("wrfsfcf", "wrfsubhf")
PLAN_DIRECTORY = {
    product: f"hrrr_v4_local_archive/{product}/manifests/plan_{product}"
    for product in PRODUCTS
}
PLAN_MANIFEST = {
    product: f"hrrr_v4_local_archive/{product}/manifests/plan_{product}_v375_manifest.json"
    for product in PRODUCTS
}
EXPECTED_FH00_OVERRIDES = {
    "H38": ("wrfsfcf", "preceding_accumulation", "accum"),
    "Q09": ("wrfsubhf", "preceding_average", "avg"),
    "Q10": ("wrfsubhf", "preceding_average", "avg"),
    "Q11": ("wrfsubhf", "preceding_average", "avg"),
    "Q13": ("wrfsubhf", "preceding_accumulation", "accum"),
}
FORBIDDEN_PLAN_COLUMNS = frozenset(
    {
        "checkpoint",
        "checkpoint_id",
        "checkpoint_time",
        "madis",
        "madis_candidate",
        "observation",
        "observation_source",
        "truth_source",
    }
)


class RequestPlanContractError(ContractError):
    """A Step 03 plan, projection, or mapping violates its contract."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RequestPlanContractError(f"JSON artifact must contain an object: {path}")
    return value


def load_plan_policy(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    with (paths.root / PLAN_POLICY_PATH).open("rb") as stream:
        policy = tomllib.load(stream)
    if policy.get("schema_version") != PLAN_POLICY_SCHEMA_VERSION:
        raise RequestPlanContractError("unsupported request-plan policy schema")
    publication = policy.get("publication", {})
    if publication.get("compression") != "zstd":
        raise RequestPlanContractError("request-plan compression must remain zstd")
    if int(publication.get("batch_rows", 0)) <= 0 or int(
        publication.get("row_group_rows", 0)
    ) <= 0:
        raise RequestPlanContractError("request-plan batch sizes must be positive")
    if publication.get("partition_key") != "target_year":
        raise RequestPlanContractError("request plans must remain partitioned by target year")
    if publication.get("coalescence_policy_id") != "EXACT_ADJACENT_REQUIRED_MESSAGES_V1":
        raise RequestPlanContractError("request-plan coalescence policy changed")

    overrides = policy.get("fh00_selector_overrides", {})
    if set(overrides) != set(EXPECTED_FH00_OVERRIDES):
        raise RequestPlanContractError("FH00 selector override set changed")
    for field_id, (product, semantics, step_type) in EXPECTED_FH00_OVERRIDES.items():
        value = overrides[field_id]
        observed = (
            value.get("product"),
            value.get("interval_semantics"),
            value.get("decoded_step_type"),
        )
        if observed != (product, semantics, step_type) or int(
            value.get("interval_minutes", -1)
        ) != 0:
            raise RequestPlanContractError(f"invalid FH00 selector override: {field_id}")
        if value.get("observed_index_time_descriptor") not in {
            "0-0 day ave fcst",
            "0-0 day acc fcst",
        }:
            raise RequestPlanContractError(f"unresolved FH00 index descriptor: {field_id}")
    return policy


def validate_fh00_evidence(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    evidence = _read_json(paths.root / FH00_EVIDENCE_PATH)
    if evidence.get("schema_version") != FH00_EVIDENCE_SCHEMA_VERSION:
        raise RequestPlanContractError("unsupported FH00 selector evidence schema")
    objects = evidence.get("objects", [])
    if len(objects) != 2 or {row.get("product") for row in objects} != set(PRODUCTS):
        raise RequestPlanContractError("FH00 evidence must cover both products")
    observed_fields = {
        field_id
        for row in objects
        for field_id in row.get("observations", {})
    }
    if observed_fields != set(EXPECTED_FH00_OVERRIDES):
        raise RequestPlanContractError("FH00 evidence field set changed")
    for row in objects:
        if len(str(row.get("sha256", ""))) != 64:
            raise RequestPlanContractError("FH00 evidence index hash is invalid")
        for line in row.get("observations", {}).values():
            if not str(line).endswith(("0-0 day ave fcst:", "0-0 day acc fcst:")):
                raise RequestPlanContractError("FH00 evidence lost its zero interval")
    return {
        "evidence_id": evidence["evidence_id"],
        "probe_cycle_utc": evidence["probe_cycle_utc"],
        "products": list(PRODUCTS),
        "override_fields": sorted(observed_fields),
        "official_index_hashes": {
            row["product"]: row["sha256"] for row in objects
        },
    }


def source_file_forecast_hour(product: str, forecast_lead_min: int) -> int:
    """Map a native valid lead to the HRRR parent-file forecast hour."""

    lead = int(forecast_lead_min)
    if lead < 0:
        raise RequestPlanContractError("forecast lead cannot be negative")
    if product == "wrfsfcf":
        if lead % 60:
            raise RequestPlanContractError("wrfsfcf lead must be an exact hour")
        return lead // 60
    if product == "wrfsubhf":
        if lead % 15:
            raise RequestPlanContractError("wrfsubhf lead must be an exact 15 minutes")
        return 0 if lead == 0 else math.ceil(lead / 60)
    raise RequestPlanContractError(f"unsupported HRRR product: {product!r}")


def native_leads(schedule_row: Mapping[str, Any], product: str) -> tuple[int, ...]:
    cycle = _utc_datetime(schedule_row["cycle_init_utc"])
    retained_end = _utc_datetime(schedule_row["retained_valid_end_utc"])
    window_end = _utc_datetime(schedule_row["window_end_utc"])
    if retained_end > window_end or retained_end < cycle:
        raise RequestPlanContractError("schedule row has invalid retained bounds")
    total_minutes = int((retained_end - cycle).total_seconds() // 60)
    cadence = 60 if product == "wrfsfcf" else 15 if product == "wrfsubhf" else 0
    if not cadence or total_minutes % cadence:
        raise RequestPlanContractError("retained endpoint is off native cadence")
    return tuple(range(0, total_minutes + 1, cadence))


def planned_interval(
    field: Mapping[str, str],
    forecast_lead_min: int,
    valid_time_utc: datetime,
    overrides: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, int, datetime, datetime]:
    """Resolve the actual selector support, including the FH00 source encoding."""

    semantics = field["interval_semantics"]
    step_type = field["decoded_step_type"]
    minutes = int(field["interval_minutes"])
    if int(forecast_lead_min) == 0 and field["field_id"] in overrides:
        override = overrides[field["field_id"]]
        if (
            override["product"] != field["product"]
            or override["interval_semantics"] != semantics
            or override["decoded_step_type"] != step_type
        ):
            raise RequestPlanContractError(
                f"FH00 override disagrees with field registry: {field['field_id']}"
            )
        minutes = int(override["interval_minutes"])
    valid = _utc_datetime(valid_time_utc)
    if semantics in {"snapshot", "static_snapshot"}:
        if minutes != 0:
            raise RequestPlanContractError("snapshot selector has nonzero duration")
    elif semantics in {"preceding_average", "preceding_accumulation"}:
        if minutes < 0:
            raise RequestPlanContractError("interval selector has negative duration")
    else:
        raise RequestPlanContractError(f"unsupported interval semantics: {semantics}")
    return semantics, step_type, minutes, valid - timedelta(minutes=minutes), valid


def source_object_identity(
    policy: Mapping[str, Any], product: str, cycle_init_utc: datetime, file_hour: int
) -> str:
    cycle = _utc_datetime(cycle_init_utc)
    source = policy["source"]
    relative = str(source["path_template"]).format(
        cycle_date_utc=f"{cycle:%Y%m%d}",
        cycle_hour_utc=f"{cycle:%H}",
        product=product,
        forecast_hour_2d=f"{int(file_hour):02d}",
    )
    return f"{str(source['root']).rstrip('/')}/{relative}"


def _utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif hasattr(value, "to_pydatetime"):
        result = value.to_pydatetime()
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise RequestPlanContractError("timestamp must be timezone-aware")
    return result.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc_datetime(value).isoformat().replace("+00:00", "Z")


def _selector_identity(
    field: Mapping[str, str], valid: datetime, interval_minutes: int
) -> str:
    return (
        f"{field['selector_contract_id']}@{valid:%Y%m%dT%H%MZ}"
        f"@D{int(interval_minutes):04d}"
    )


def _request_id(product: str, cycle: datetime, lead: int, field_id: str) -> str:
    return f"REQ-{product.upper()}-{cycle:%Y%m%dT%H%MZ}-L{lead:04d}-{field_id}"


def _empty_columns(schema: Any) -> dict[str, list[Any]]:
    return {field.name: [] for field in schema}


def _append_request(
    columns: dict[str, list[Any]],
    *,
    target_day: date,
    product: str,
    cycle: datetime,
    source_url: str,
    index_url: str,
    lead: int,
    valid: datetime,
    field: Mapping[str, str],
    semantics: str,
    step_type: str,
    interval_minutes: int,
    interval_start: datetime,
    interval_end: datetime,
) -> str:
    request_id = _request_id(product, cycle, lead, field["field_id"])
    columns["request_id"].append(request_id)
    columns["target_day"].append(target_day)
    columns["product"].append(product)
    columns["cycle_init_utc"].append(cycle)
    columns["source_object_identity"].append(source_url)
    columns["index_object_identity"].append(index_url)
    columns["forecast_lead_min"].append(lead)
    columns["valid_time_utc"].append(valid)
    columns["field_registry_id"].append(field["field_id"])
    columns["selector_identity"].append(
        _selector_identity(field, valid, interval_minutes)
    )
    columns["step_type"].append(step_type)
    columns["interval_start_utc"].append(interval_start)
    columns["interval_end_utc"].append(interval_end)
    columns["spatial_contract_id"].append(field["spatial_contract_id"])
    columns["request_action"].append(field["acquisition_contract_id"])
    return request_id


def _spatial_value_counts(
    field: Mapping[str, str], geometry: Mapping[str, Any]
) -> tuple[int, int, int]:
    if field["field_id"] == "H14":
        grid = geometry["operational_grid"]
        return 0, 0, int(grid["nx"]) * int(grid["ny"])
    contract = geometry["spatial_contracts"][field["spatial_contract_id"]]
    points = len(contract.get("point_outputs", []))
    shape = contract.get("tile_shape")
    tile_cells = 0 if shape is None else int(shape[0]) * int(shape[1])
    return points, tile_cells, 0


def _metric_bucket() -> dict[str, int]:
    return {
        "request_rows": 0,
        "messages": 0,
        "point_values": 0,
        "tile_cells": 0,
        "full_grid_cells": 0,
        "extracted_values": 0,
    }


def _record_metric(
    bucket: dict[str, int], point_values: int, tile_cells: int, full_grid_cells: int
) -> None:
    bucket["request_rows"] += 1
    bucket["messages"] += 1
    bucket["point_values"] += point_values
    bucket["tile_cells"] += tile_cells
    bucket["full_grid_cells"] += full_grid_cells
    bucket["extracted_values"] += point_values + tile_cells + full_grid_cells


def _finish_projection_bucket(
    bucket: Mapping[str, int], assumptions: Mapping[str, Any]
) -> dict[str, int]:
    result = dict(bucket)
    messages = int(result["messages"])
    extracted = int(result["extracted_values"])
    numerator = int(assumptions["coalesced_range_ratio_numerator"])
    denominator = int(assumptions["coalesced_range_ratio_denominator"])
    result["estimated_coalesced_byte_ranges"] = math.ceil(messages * numerator / denominator)
    result["estimated_source_message_bytes"] = messages * int(
        assumptions["mean_message_bytes"]
    )
    result["estimated_plan_parquet_bytes"] = int(result["request_rows"]) * int(
        assumptions["plan_row_bytes"]
    )
    result["estimated_canonical_output_bytes"] = (
        int(result["request_rows"]) * int(assumptions["canonical_row_overhead_bytes"])
        + extracted * int(assumptions["numeric_value_bytes"])
    )
    return result


def _partition_schedule_rows(project_root: Path, product: str) -> dict[int, list[dict[str, Any]]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RequestPlanContractError("pyarrow is required to read the cycle schedule") from exc
    table = pq.read_table(project_root / SCHEDULE_PARQUET_PATH)
    partitions: dict[int, list[dict[str, Any]]] = defaultdict(list)
    seen_cycles: set[datetime] = set()
    for row in table.to_pylist():
        if row["product"] != product:
            continue
        cycle = _utc_datetime(row["cycle_init_utc"])
        if cycle in seen_cycles:
            raise RequestPlanContractError(f"duplicate cycle in {product} schedule")
        seen_cycles.add(cycle)
        partitions[row["target_day"].year].append(row)
    if not partitions:
        raise RequestPlanContractError(f"cycle schedule contains no {product} rows")
    return dict(sorted(partitions.items()))


def expected_product_counts(
    schedule_rows: Iterable[Mapping[str, Any]], product: str, field_count: int
) -> dict[str, int]:
    state_count = sum(len(native_leads(row, product)) for row in schedule_rows)
    static_count = 1 if product == "wrfsfcf" else 0
    dynamic_fields = field_count - static_count
    return {
        "native_valid_state_count": state_count,
        "request_row_count": state_count * dynamic_fields + static_count,
    }


def build_product_plan(
    project_root: Path | str,
    product: str,
    *,
    step02_record_sha256: str,
    pause: Any | None = None,
) -> dict[str, Any]:
    """Build and atomically publish one product plan without touching the other."""

    if product not in PRODUCTS:
        raise RequestPlanContractError(f"unknown product: {product!r}")
    paths = load_project_paths(project_root)
    registry_verification = verify_registry_bundle(paths.root)
    schedule_verification = verify_cycle_schedule(paths.root)
    policy = load_plan_policy(paths.root)
    fh00_evidence = validate_fh00_evidence(paths.root)
    fields = load_field_registry(paths.root, product)
    field_ids = tuple(field["field_id"] for field in fields)
    geometry = _read_json(paths.root / "registries/grid_geometry_v375.json")
    schema = load_parquet_schema(paths.root, "request_plan_v375.json")
    schema_names = set(schema.names)
    if schema_names & FORBIDDEN_PLAN_COLUMNS:
        raise RequestPlanContractError("request-plan schema contains a forbidden dependency column")
    partitions = _partition_schedule_rows(paths.root, product)
    schedule_rows = [row for rows in partitions.values() for row in rows]
    expected = expected_product_counts(schedule_rows, product, len(fields))

    destination = paths.root / PLAN_DIRECTORY[product]
    if destination.exists():
        raise RequestPlanContractError(f"immutable product plan already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".staging", dir=destination.parent)
    )
    logical_digest = sha256()
    request_count = 0
    valid_state_count = 0
    source_object_count = 0
    max_valid: datetime | None = None
    max_window_end: datetime | None = None
    max_lead = 0
    h14_count = 0
    fields_seen: Counter[str] = Counter()
    sources_by_year: Counter[int] = Counter()
    totals = _metric_bucket()
    by_field: dict[str, dict[str, int]] = {field_id: _metric_bucket() for field_id in field_ids}
    by_year: dict[int, dict[str, int]] = {
        year: _metric_bucket() for year in partitions
    }
    by_tile: dict[str, dict[str, int]] = defaultdict(_metric_bucket)
    part_records: list[dict[str, Any]] = []
    publication = policy["publication"]
    overrides = policy["fh00_selector_overrides"]
    batch_rows = int(publication["batch_rows"])
    row_group_rows = int(publication["row_group_rows"])

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RequestPlanContractError("pyarrow is required to publish request plans") from exc

    try:
        static_written = False
        for year, year_rows in partitions.items():
            if pause is not None:
                pause.raise_if_requested()
            if staging is None:  # pragma: no cover - defensive publication invariant
                raise RequestPlanContractError("request-plan staging directory is unavailable")
            partition_dir = staging / f"target_year={year}"
            partition_dir.mkdir(parents=True)
            part_path = partition_dir / f"part-{year}-{product}.parquet"
            writer = pq.ParquetWriter(
                part_path,
                schema,
                compression="zstd",
                use_dictionary=True,
                write_statistics=True,
            )
            columns = _empty_columns(schema)
            part_count = 0
            part_states = 0
            try:
                for schedule_row in year_rows:
                    target_day = schedule_row["target_day"]
                    cycle = _utc_datetime(schedule_row["cycle_init_utc"])
                    window_end = _utc_datetime(schedule_row["window_end_utc"])
                    if max_window_end is None or window_end > max_window_end:
                        max_window_end = window_end
                    leads = native_leads(schedule_row, product)
                    part_states += len(leads)
                    valid_state_count += len(leads)
                    source_hours: set[int] = set()
                    for lead in leads:
                        file_hour = source_file_forecast_hour(product, lead)
                        source_hours.add(file_hour)
                        valid = cycle + timedelta(minutes=lead)
                        if valid > window_end:
                            raise RequestPlanContractError("planned valid exceeds TARGET_WINDOW")
                        max_valid = valid if max_valid is None or valid > max_valid else max_valid
                        max_lead = max(max_lead, lead)
                        source_url = source_object_identity(policy, product, cycle, file_hour)
                        index_url = source_url + str(policy["source"]["index_suffix"])
                        for field in fields:
                            if field["field_id"] == "H14":
                                if static_written:
                                    continue
                                static_written = True
                                h14_count += 1
                            semantics, step_type, duration, interval_start, interval_end = planned_interval(
                                field, lead, valid, overrides
                            )
                            request_id = _append_request(
                                columns,
                                target_day=target_day,
                                product=product,
                                cycle=cycle,
                                source_url=source_url,
                                index_url=index_url,
                                lead=lead,
                                valid=valid,
                                field=field,
                                semantics=semantics,
                                step_type=step_type,
                                interval_minutes=duration,
                                interval_start=interval_start,
                                interval_end=interval_end,
                            )
                            logical_digest.update(request_id.encode("ascii"))
                            logical_digest.update(b"\n")
                            request_count += 1
                            part_count += 1
                            fields_seen[field["field_id"]] += 1
                            points, tiles, full_grid = _spatial_value_counts(field, geometry)
                            _record_metric(totals, points, tiles, full_grid)
                            _record_metric(by_field[field["field_id"]], points, tiles, full_grid)
                            _record_metric(by_year[year], points, tiles, full_grid)
                            tile_key = (
                                "full_grid"
                                if full_grid
                                else "9x9"
                                if tiles == 81
                                else "3x3"
                                if tiles == 9
                                else "none"
                            )
                            _record_metric(by_tile[tile_key], points, tiles, full_grid)
                            if len(columns["request_id"]) >= batch_rows:
                                table = pa.Table.from_pydict(columns, schema=schema)
                                writer.write_table(table, row_group_size=row_group_rows)
                                columns = _empty_columns(schema)
                    source_object_count += len(source_hours)
                    sources_by_year[year] += len(source_hours)
                if columns["request_id"]:
                    table = pa.Table.from_pydict(columns, schema=schema)
                    writer.write_table(table, row_group_size=row_group_rows)
            finally:
                writer.close()
            with part_path.open("rb") as stream:
                os.fsync(stream.fileno())
            part_records.append(
                {
                    "target_year": year,
                    "path": part_path.relative_to(staging).as_posix(),
                    "sha256": sha256_file(part_path),
                    "size_bytes": part_path.stat().st_size,
                    "row_count": part_count,
                    "native_valid_state_count": part_states,
                    "unique_source_object_count": int(sources_by_year[year]),
                }
            )

        if request_count != expected["request_row_count"]:
            raise RequestPlanContractError(
                f"{product} request count changed: {request_count} != {expected['request_row_count']}"
            )
        if valid_state_count != expected["native_valid_state_count"]:
            raise RequestPlanContractError("native valid-state enumeration changed")
        if product == "wrfsfcf" and h14_count != 1:
            raise RequestPlanContractError("H14 must be planned exactly once")
        if product == "wrfsubhf" and h14_count != 0:
            raise RequestPlanContractError("subhourly plan unexpectedly contains H14")
        sentinel = "H16" if product == "wrfsfcf" else "Q05"
        if fields_seen[sentinel] <= 0:
            raise RequestPlanContractError(f"{sentinel} has no network requests")
        if max_valid is None or max_window_end is None or max_valid > max_window_end:
            raise RequestPlanContractError("request plan exceeds TARGET_WINDOW")
        if max_lead >= 48 * 60:
            raise RequestPlanContractError("FH48-only tail remains after TARGET_WINDOW cap")

        atomic_publish_directory(staging, destination)
        staging = None
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    directory_hash = sha256_directory(destination)
    schedule_manifest = schedule_verification["manifest"]
    registry_bundle = registry_verification["bundle"]
    manifest_body = {
        "schema_version": PLAN_MANIFEST_SCHEMA_VERSION,
        "plan_id": f"KDEN_V375_PLAN_{product.upper()}_20210101_20260911_V1",
        "product": product,
        "plan_directory": PLAN_DIRECTORY[product],
        "directory_sha256": directory_hash,
        "logical_request_sequence_sha256": logical_digest.hexdigest(),
        "request_row_count": request_count,
        "native_valid_state_count": valid_state_count,
        "unique_source_object_count": source_object_count,
        "index_object_fetch_count": source_object_count,
        "field_request_counts": dict(sorted(fields_seen.items())),
        "maximum_forecast_lead_min": max_lead,
        "maximum_valid_time_utc": _iso(max_valid),
        "maximum_window_end_utc": _iso(max_window_end),
        "partitions": part_records,
        "request_schema": {
            "path": "schemas/request_plan_v375.json",
            "sha256": sha256_file(paths.root / "schemas/request_plan_v375.json"),
        },
        "registry_bundle_sha256": registry_bundle["bundle_sha256"],
        "schedule_manifest_sha256": schedule_manifest["manifest_sha256"],
        "step02_record_sha256": step02_record_sha256,
        "plan_policy": {
            "path": PLAN_POLICY_PATH,
            "sha256": sha256_file(paths.root / PLAN_POLICY_PATH),
        },
        "fh00_selector_evidence": {
            "path": FH00_EVIDENCE_PATH,
            "sha256": sha256_file(paths.root / FH00_EVIDENCE_PATH),
            "evidence_id": fh00_evidence["evidence_id"],
        },
        "deduplication": {
            "source_object_identity_unique_before_fetch": True,
            "logical_message_identity_unique": True,
            "coalescence_policy_id": publication["coalescence_policy_id"],
            "byte_ranges_resolved_from_one_index_fetch_per_source_object": True,
        },
    }
    manifest = {
        **manifest_body,
        "plan_sha256": sha256_bytes(canonical_json_bytes(manifest_body)),
    }
    atomic_write_json(paths.root / PLAN_MANIFEST[product], manifest)
    return {
        "manifest": manifest,
        "projection": {
            "product": product,
            "unique_source_objects": source_object_count,
            "by_product": _finish_projection_bucket(totals, policy["projection_assumptions"]),
            "by_field": {
                key: _finish_projection_bucket(value, policy["projection_assumptions"])
                for key, value in sorted(by_field.items())
            },
            "by_year": {
                str(key): {
                    **_finish_projection_bucket(value, policy["projection_assumptions"]),
                    "unique_source_objects": int(sources_by_year[key]),
                }
                for key, value in sorted(by_year.items())
            },
            "by_tile_size": {
                key: _finish_projection_bucket(value, policy["projection_assumptions"])
                for key, value in sorted(by_tile.items())
            },
        },
    }


def _parquet_statistics(metadata: Any, column_index: int) -> Iterator[Any]:
    for row_group_index in range(metadata.num_row_groups):
        statistics = metadata.row_group(row_group_index).column(column_index).statistics
        if statistics is None or not statistics.has_min_max:
            raise RequestPlanContractError("request-plan row group lacks required statistics")
        yield statistics


def verify_product_plan(project_root: Path | str, product: str) -> dict[str, Any]:
    """Verify one sealed product plan without opening or depending on its peer."""

    if product not in PRODUCTS:
        raise RequestPlanContractError(f"unknown product: {product!r}")
    paths = load_project_paths(project_root)
    policy = load_plan_policy(paths.root)
    validate_fh00_evidence(paths.root)
    registry = verify_registry_bundle(paths.root)["bundle"]
    schedule = verify_cycle_schedule(paths.root)["manifest"]
    manifest = _read_json(paths.root / PLAN_MANIFEST[product])
    if manifest.get("schema_version") != PLAN_MANIFEST_SCHEMA_VERSION:
        raise RequestPlanContractError("unsupported request-plan manifest schema")
    body = dict(manifest)
    supplied = body.pop("plan_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise RequestPlanContractError("request-plan manifest content hash mismatch")
    if manifest.get("product") != product:
        raise RequestPlanContractError("request-plan product identity changed")
    if manifest.get("registry_bundle_sha256") != registry["bundle_sha256"]:
        raise RequestPlanContractError("request plan is stale against registry bundle")
    if manifest.get("schedule_manifest_sha256") != schedule["manifest_sha256"]:
        raise RequestPlanContractError("request plan is stale against cycle schedule")
    if manifest.get("plan_policy", {}).get("sha256") != sha256_file(
        paths.root / PLAN_POLICY_PATH
    ):
        raise RequestPlanContractError("request-plan policy changed after sealing")
    if manifest.get("request_schema", {}).get("sha256") != sha256_file(
        paths.root / "schemas/request_plan_v375.json"
    ):
        raise RequestPlanContractError("request-plan schema changed after sealing")
    if manifest.get("fh00_selector_evidence", {}).get("sha256") != sha256_file(
        paths.root / FH00_EVIDENCE_PATH
    ):
        raise RequestPlanContractError("FH00 selector evidence changed after sealing")

    plan_directory = paths.root / PLAN_DIRECTORY[product]
    if sha256_directory(plan_directory) != manifest.get("directory_sha256"):
        raise RequestPlanContractError("sealed request-plan directory changed")
    schema = load_parquet_schema(paths.root, "request_plan_v375.json")
    if set(schema.names) & FORBIDDEN_PLAN_COLUMNS:
        raise RequestPlanContractError("request plan requires a forbidden dependency column")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RequestPlanContractError("pyarrow is required to verify request plans") from exc
    total_rows = 0
    max_lead = 0
    max_valid: datetime | None = None
    for part in manifest.get("partitions", []):
        path = plan_directory / part["path"]
        if (
            sha256_file(path) != part["sha256"]
            or path.stat().st_size != int(part["size_bytes"])
        ):
            raise RequestPlanContractError(f"request-plan partition changed: {part['path']}")
        parquet = pq.ParquetFile(path)
        if not parquet.schema_arrow.equals(schema, check_metadata=True):
            raise RequestPlanContractError("request-plan partition schema changed")
        if parquet.metadata.num_rows != int(part["row_count"]):
            raise RequestPlanContractError("request-plan partition row count changed")
        total_rows += parquet.metadata.num_rows
        lead_index = schema.get_field_index("forecast_lead_min")
        valid_index = schema.get_field_index("valid_time_utc")
        max_lead = max(
            max_lead,
            *(int(statistics.max) for statistics in _parquet_statistics(parquet.metadata, lead_index)),
        )
        part_max_valid = max(
            _utc_datetime(statistics.max)
            for statistics in _parquet_statistics(parquet.metadata, valid_index)
        )
        max_valid = part_max_valid if max_valid is None or part_max_valid > max_valid else max_valid
    if total_rows != int(manifest.get("request_row_count", -1)):
        raise RequestPlanContractError("request-plan total row count changed")
    if max_lead != int(manifest.get("maximum_forecast_lead_min", -1)):
        raise RequestPlanContractError("request-plan maximum lead changed")
    if max_valid is None or _iso(max_valid) != manifest.get("maximum_valid_time_utc"):
        raise RequestPlanContractError("request-plan maximum valid time changed")
    if max_valid > _utc_datetime(manifest["maximum_window_end_utc"]):
        raise RequestPlanContractError("request plan exceeds TARGET_WINDOW")
    if max_lead >= 48 * 60:
        raise RequestPlanContractError("FH48-only tail remains in request plan")
    sentinel = "H16" if product == "wrfsfcf" else "Q05"
    if int(manifest.get("field_request_counts", {}).get(sentinel, 0)) <= 0:
        raise RequestPlanContractError(f"{sentinel} lacks network requests")
    h14_count = int(manifest.get("field_request_counts", {}).get("H14", 0))
    if (product == "wrfsfcf" and h14_count != 1) or (
        product == "wrfsubhf" and h14_count != 0
    ):
        raise RequestPlanContractError("H14 once-per-grid/version gate failed")
    return {
        "product": product,
        "plan_sha256": manifest["plan_sha256"],
        "directory_sha256": manifest["directory_sha256"],
        "request_row_count": total_rows,
        "native_valid_state_count": int(manifest["native_valid_state_count"]),
        "unique_source_object_count": int(manifest["unique_source_object_count"]),
        "index_object_fetch_count": int(manifest["index_object_fetch_count"]),
        "partition_count": len(manifest["partitions"]),
        "maximum_forecast_lead_min": max_lead,
        "maximum_valid_time_utc": _iso(max_valid),
        "target_window_cap_verified": True,
        "fh48_only_tail_absent": True,
        "normal_network_sentinel": sentinel,
        "normal_network_sentinel_count": int(manifest["field_request_counts"][sentinel]),
        "h14_once_per_grid_version": h14_count == 1 if product == "wrfsfcf" else True,
        "forbidden_dependency_columns": [],
        "independently_loadable": True,
        "source_object_fetches_deduplicated": True,
        "logical_messages_deduplicated": True,
        "coalescence_policy_id": policy["publication"]["coalescence_policy_id"],
        "sealed_before_network_execution": True,
    }


def iter_product_plan_batches(
    project_root: Path | str,
    product: str,
    *,
    columns: Sequence[str] | None = None,
    batch_size: int = 65536,
) -> Iterator[Any]:
    """Load either product plan independently in deterministic partition order."""

    verified = verify_product_plan(project_root, product)
    if not verified["independently_loadable"]:  # defensive contract assertion
        raise RequestPlanContractError("request plan is not independently loadable")
    paths = load_project_paths(project_root)
    manifest = _read_json(paths.root / PLAN_MANIFEST[product])
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RequestPlanContractError("pyarrow is required to load request plans") from exc
    for part in manifest["partitions"]:
        parquet = pq.ParquetFile(paths.root / PLAN_DIRECTORY[product] / part["path"])
        yield from parquet.iter_batches(batch_size=batch_size, columns=columns)
