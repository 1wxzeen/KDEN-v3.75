"""Resumable full-history acceptance and immutable freeze for the R14 archive."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..acquisition.records import PRODUCT_MANIFEST_PATH
from ..acquisition.workflow import (
    COMBINED_REQUEST_COUNT,
    COMBINED_UNIT_COUNT,
    PRODUCT_PHASES,
    UnitSpec,
    _execute_on_persistent_pool,
    build_unit_specs,
    coverage_rows,
    load_unit_plan_rows,
)
from ..contracts import (
    ContractError,
    PauseController,
    load_project_paths,
    relative_to_root,
    utc_now,
    validate_run_id,
    validate_runtime_isolation,
    verify_step_pass,
)
from ..archive_readers import read_combined_pass_identity
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from ..io.atomic import atomic_write_bytes, atomic_write_json, fsync_directory
from ..pilot import _load_r14_field_state_schema
from ..r14 import (
    R14_DYNAMIC_HOURLY,
    R14_SCOPE_ID,
    R14_STATIC_HOURLY,
    R14_SUBHOURLY,
    R14_SPATIAL_CONTRACT_ID,
    load_r14_field_registry,
)
from ..r14_pilot_records import (
    R14_STEP04_PASS_SCHEMA_VERSION,
    R14_STEP04_RECORD_PATH,
)
from ..r14_request_plans import (
    EXPECTED_COUNTS,
    PRODUCTS,
    R14_PLAN_DIRECTORY,
    R14_PLAN_MANIFEST,
    R14_PLAN_MANIFEST_SCHEMA_VERSION,
)
from ..r14_schedule import verify_r14_cycle_schedule
from ..registries import load_parquet_schema


CONTRACT_PATH = "config/step_08_acceptance_v375.json"
SCHEMA_PATH = "schemas/step_08_acceptance_v375.json"
REPORT_PATH = "reports/step_08_final_acceptance_v375.json"
FREEZE_PATH = "reports/kden_v375_acquisition_freeze_manifest.json"
RUNBOOK_PATH = "reports/step_08_OWNER_RUNBOOK.md"
FINAL_PASS_PATH = "state/KDEN_V375_ACQUISITION_PASS.json"
STEP_ID = "STEP_08"
CONTRACT_SCHEMA = "KDEN_V375_STEP08_ACCEPTANCE_CONTRACT_V1"
CONTRACT_ID = "KDEN_V375_R14_FINAL_ACCEPTANCE_V1"
FINAL_PASS_SCHEMA = "KDEN_V375_ACQUISITION_PASS_V1"
FREEZE_SCHEMA = "KDEN_V375_ACQUISITION_FREEZE_MANIFEST_V1"
REPORT_SCHEMA = "KDEN_V375_STEP08_FINAL_ACCEPTANCE_REPORT_V1"
CHECKPOINT_SCHEMA = "KDEN_V375_STEP08_CHECKPOINT_V1"
JOURNAL_SCHEMA = "KDEN_V375_STEP08_ACCEPTANCE_JOURNAL_V1"
LIVE_SCHEMA = "KDEN_V375_STEP08_ACCEPTANCE_LIVE_STATUS_V1"
ZERO_HASH = "0" * 64
DENVER = ZoneInfo("America/Denver")
_ARROW_TO_PYTHON_LOCK = Lock()


class AcceptanceError(ContractError):
    """The complete archive does not satisfy its frozen R14 contracts."""


def _arrow_to_pylist(table: Any) -> list[dict[str, Any]]:
    """Convert Arrow timestamps under one lock.

    PyArrow resolves timezone objects lazily while converting timestamp
    scalars. Concurrent first-use conversions can deadlock in Python's module
    lock, leaving the ordered worker pool waiting forever. File reads and
    hashing remain parallel; only the Python-object conversion is serialized.
    """

    with _ARROW_TO_PYTHON_LOCK:
        return table.to_pylist()


def _prepare_arrow_python_conversion() -> None:
    """Resolve every archive timezone once on the coordinator thread."""

    try:
        import pyarrow as pa
    except ImportError as exc:
        raise AcceptanceError("pyarrow is required for full acceptance") from exc
    instant = datetime(2021, 1, 1, tzinfo=UTC)
    probe = pa.table(
        {
            "utc": pa.array([instant], type=pa.timestamp("us", tz="UTC")),
            "denver": pa.array(
                [instant.astimezone(DENVER)],
                type=pa.timestamp("us", tz="America/Denver"),
            ),
        }
    )
    converted = _arrow_to_pylist(probe)
    if len(converted) != 1 or any(value is None for value in converted[0].values()):
        raise AcceptanceError("PyArrow timezone conversion warm-up failed")


@dataclass(frozen=True, slots=True)
class AcceptanceUnit:
    sequence: int
    spec: UnitSpec
    acquisition_entry: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AcceptanceContext:
    root: Path
    contract: Mapping[str, Any]
    acquisition_run_id: str
    r14_pass_sha256: str
    step07_pass_sha256: str
    step04_pass_sha256: str
    contract_sha256: str
    units: tuple[AcceptanceUnit, ...]
    product_plan: Mapping[str, Mapping[str, Any]]
    product_manifest: Mapping[str, Mapping[str, Any]]
    registries: Mapping[str, Mapping[str, Mapping[str, str]]]
    field_schema: Any
    ledger_schema: Any
    coverage_schema: Any
    schedule_evidence: Mapping[str, Any]
    isolation_evidence: Mapping[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except json.JSONDecodeError as exc:
        raise AcceptanceError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise AcceptanceError(f"JSON artifact is not an object: {path}")
    return value


def _inside(root: Path, relative: str | Path) -> Path:
    path = (root / Path(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise AcceptanceError(f"acceptance path leaves project root: {relative}")
    return path


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AcceptanceError("archive timestamp has no UTC offset")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _utc(value).isoformat().replace("+00:00", "Z")


def _tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def load_acceptance_contract(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    value = _read_json(root / CONTRACT_PATH)
    expected = value.get("expected", {})
    if (
        value.get("schema_version") != CONTRACT_SCHEMA
        or value.get("contract_id") != CONTRACT_ID
        or value.get("scope_id") != R14_SCOPE_ID
        or value.get("predecessor_step") != "STEP_07"
        or value.get("execution", {}).get("network_allowed") is not False
        or int(value.get("execution", {}).get("max_local_validation_workers", 0)) != 4
        or int(expected.get("work_unit_count", -1)) != COMBINED_UNIT_COUNT
        or int(expected.get("logical_request_count", -1)) != COMBINED_REQUEST_COUNT
        or value.get("final_pass_path") != FINAL_PASS_PATH
        or value.get("report_path") != REPORT_PATH
        or value.get("freeze_manifest_path") != FREEZE_PATH
    ):
        raise AcceptanceError("Step 08 acceptance contract identity changed")
    expected_fields = {
        "wrfsfcf": set(R14_DYNAMIC_HOURLY + R14_STATIC_HOURLY),
        "wrfsubhf": set(R14_SUBHOURLY),
    }
    for product in PRODUCTS:
        item = expected.get(product, {})
        if set(item.get("field_ids", ())) != expected_fields[product]:
            raise AcceptanceError(f"Step 08 {product} field universe changed")
    return value


def _verify_product_manifest_hash(manifest: Mapping[str, Any], product: str) -> None:
    body = dict(manifest)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise AcceptanceError(f"{product} acquisition manifest hash changed")


def _read_step04_identity(root: Path) -> dict[str, Any]:
    """Validate the sealed pilot record itself without rehashing its large outputs."""

    record = _read_json(root / R14_STEP04_RECORD_PATH)
    if (
        record.get("schema_version") != R14_STEP04_PASS_SCHEMA_VERSION
        or record.get("record_id") != "STEP_04_R14"
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("status") != "PASS"
        or not record.get("gate_evidence")
        or not all(value is True for value in record["gate_evidence"].values())
    ):
        raise AcceptanceError("R14 Step 04 pilot identity or gates changed")
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise AcceptanceError("R14 Step 04 pilot record hash changed")
    return record


def _verify_plan_identity_for_acceptance(
    root: Path,
    product: str,
    *,
    schedule_manifest_sha256: str,
) -> dict[str, Any]:
    """Verify sealed plan files once; unit scanning validates every plan row later."""

    manifest = _read_json(root / R14_PLAN_MANIFEST[product])
    body = dict(manifest)
    supplied = body.pop("plan_sha256", None)
    if (
        supplied != sha256_bytes(canonical_json_bytes(body))
        or manifest.get("schema_version") != R14_PLAN_MANIFEST_SCHEMA_VERSION
        or manifest.get("scope_id") != R14_SCOPE_ID
        or manifest.get("product") != product
        or manifest.get("r14_schedule", {}).get("manifest_sha256")
        != schedule_manifest_sha256
    ):
        raise AcceptanceError(f"{product} request-plan identity changed")
    frozen = EXPECTED_COUNTS[product]
    parts = manifest.get("partitions", [])
    if len(parts) != 6:
        raise AcceptanceError(f"{product} request-plan partition count changed")
    total = 0
    plan_root = root / R14_PLAN_DIRECTORY[product]
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise AcceptanceError("pyarrow is required for plan verification") from exc
    for part in parts:
        path = plan_root / str(part["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(part["size_bytes"])
            or sha256_file(path) != part["sha256"]
            or pq.ParquetFile(path).metadata.num_rows != int(part["row_count"])
        ):
            raise AcceptanceError(f"{product} request-plan partition changed: {path}")
        total += int(part["row_count"])
    expected_fields = {
        row["field_id"]: (
            1 if row["field_id"] == "H14" else int(frozen["native_valid_states"])
        )
        for row in load_r14_field_registry(root, product)
    }
    if (
        total != int(frozen["request_rows"])
        or total != int(manifest.get("request_row_count", -1))
        or manifest.get("field_request_counts") != expected_fields
        or int(manifest.get("maximum_forecast_lead_min", 48 * 60)) >= 48 * 60
        or not datetime.fromisoformat(
            str(manifest["maximum_valid_time_utc"]).replace("Z", "+00:00")
        )
        < datetime.fromisoformat(
            str(manifest["maximum_window_end_utc"]).replace("Z", "+00:00")
        )
    ):
        raise AcceptanceError(f"{product} request-plan accounting changed")
    return {
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "plan_sha256": manifest["plan_sha256"],
        "request_row_count": total,
        "native_valid_state_count": int(frozen["native_valid_states"]),
        "field_request_counts": expected_fields,
        "all_valid_times_strictly_before_window_end": True,
        "fh48_only_tail_absent": True,
    }


def _read_schedule_identity(root: Path) -> dict[str, Any]:
    manifest = _read_json(
        root
        / "hrrr_v4_local_archive/common/cycle_schedule_r14/"
        "cycle_schedule_r14_v375_manifest.json"
    )
    body = dict(manifest)
    supplied = body.pop("manifest_sha256", None)
    parquet = manifest.get("parquet", {})
    path = _inside(root, str(parquet.get("path", "")))
    if (
        supplied != sha256_bytes(canonical_json_bytes(body))
        or manifest.get("scope_id") != R14_SCOPE_ID
        or not path.is_file()
        or path.stat().st_size != int(parquet.get("size_bytes", -1))
        or sha256_file(path) != parquet.get("sha256")
    ):
        raise AcceptanceError("R14 schedule identity changed")
    return {
        "manifest": manifest,
        "gate_evidence": {
            "all_native_valid_times_strictly_before_window_end": True,
            "identity_only": True,
        },
    }


def build_acceptance_context(
    project_root: Path | str, *, _deep_schedule_verification: bool = True
) -> AcceptanceContext:
    paths = load_project_paths(project_root)
    root = paths.root
    contract = load_acceptance_contract(root)
    step07 = verify_step_pass(root, 7)
    combined = read_combined_pass_identity(root)
    step04 = _read_step04_identity(root)
    schedule = (
        verify_r14_cycle_schedule(root)
        if _deep_schedule_verification
        else _read_schedule_identity(root)
    )
    plans = {
        product: _verify_plan_identity_for_acceptance(
            root,
            product,
            schedule_manifest_sha256=schedule["manifest"]["manifest_sha256"],
        )
        for product in PRODUCTS
    }
    manifests = {
        product: _read_json(root / PRODUCT_MANIFEST_PATH[product])
        for product in PRODUCTS
    }
    for product, manifest in manifests.items():
        _verify_product_manifest_hash(manifest, product)
        if (
            manifest.get("run_id") != combined["run_id"]
            or manifest.get("scope_id") != R14_SCOPE_ID
            or manifest.get("status") != "PASS"
            or manifest.get("request_plan_sha256") != plans[product]["plan_sha256"]
        ):
            raise AcceptanceError(f"{product} acquisition manifest lineage changed")

    units: list[AcceptanceUnit] = []
    sequence = 0
    for product in PRODUCTS:
        specs = build_unit_specs(root, product)
        entries = manifests[product].get("units", [])
        if len(entries) != len(specs):
            raise AcceptanceError(f"{product} work-unit manifest is incomplete")
        for spec, entry in zip(specs, entries, strict=True):
            if (
                entry.get("unit_id") != spec.unit_id
                or entry.get("artifact_path") != spec.artifact_path
                or entry.get("manifest_path") != spec.manifest_path
            ):
                raise AcceptanceError(f"{product} unit ordering or identity changed")
            units.append(AcceptanceUnit(sequence, spec, dict(entry)))
            sequence += 1
    if len(units) != COMBINED_UNIT_COUNT:
        raise AcceptanceError("combined Step 08 work-unit count changed")

    registries = {
        product: {
            row["field_id"]: row for row in load_r14_field_registry(root, product)
        }
        for product in PRODUCTS
    }
    return AcceptanceContext(
        root=root,
        contract=contract,
        acquisition_run_id=str(combined["run_id"]),
        r14_pass_sha256=str(combined["record_sha256"]),
        step07_pass_sha256=str(step07["record_sha256"]),
        step04_pass_sha256=str(step04["record_sha256"]),
        contract_sha256=sha256_file(root / CONTRACT_PATH),
        units=tuple(units),
        product_plan=plans,
        product_manifest=manifests,
        registries=registries,
        field_schema=_load_r14_field_state_schema(root),
        ledger_schema=load_parquet_schema(root, "retrieval_ledger_v375.json"),
        coverage_schema=load_parquet_schema(root, "temporal_coverage_v375.json"),
        schedule_evidence=schedule["gate_evidence"],
        isolation_evidence=validate_runtime_isolation(root),
    )


def _cycle_partition(cycle: datetime) -> str:
    return f"cycle={_utc(cycle).strftime('%Y%m%dT%H%M%SZ')}"


def _schema_matches(actual: Any, expected: Any) -> bool:
    """Treat Arrow's list-child name alias as cosmetic, but bind metadata exactly."""

    return actual.equals(expected, check_metadata=False) and (
        actual.metadata or {}
    ) == (expected.metadata or {})


def _expected_coordinate_era(valid_time: datetime) -> str:
    local_day = _utc(valid_time).astimezone(DENVER).date()
    return (
        "KDEN_COORD_20040105"
        if local_day < date(2021, 11, 22)
        else "KDEN_COORD_20211122"
    )


def _all_values(row: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for name in ("bi_value", "nn_value"):
        if row[name] is not None:
            values.append(float(row[name]))
    if row["tile_values"] is not None:
        values.extend(
            float(value) for value in row["tile_values"] if value is not None
        )
    values.extend(
        float(row[f"regional_value_{index:02d}"])
        for index in range(8)
        if row[f"regional_value_{index:02d}"] is not None
    )
    return values


def _validate_spatial_values(
    row: Mapping[str, Any],
    *,
    field: Mapping[str, str],
    physical_range: Sequence[float],
) -> tuple[float | None, float | None]:
    coverage = str(row["coverage_flag"])
    spatial = field["spatial_contract_id"]
    expected_shape = {
        "POINT_BI_TILE3_V1": [3, 3],
        "POINT_BI_TILE9_V1": [9, 9],
        "POINT_BI_TILE9_DERIVE3_V1": [9, 9],
        "POINT_NN_TILE9_V1": [9, 9],
    }.get(spatial)
    regional_count = 0 if field["field_id"] in {"H02", "H07"} else 8
    regional_values = [row[f"regional_value_{index:02d}"] for index in range(8)]
    if coverage == "MISSING":
        nullable = [row["bi_value"], row["nn_value"], row["tile_shape"], row["tile_values"]]
        if (
            any(value is not None for value in nullable + regional_values)
            or int(row["regional_coverage_mask"]) != 0
            or not row["missing_reason"]
        ):
            raise AcceptanceError("missing canonical row contains values or lacks a reason")
        return None, None
    if coverage != "PRESENT" or row["missing_reason"] is not None:
        raise AcceptanceError(f"unsupported canonical coverage state: {coverage}")
    if int(row["regional_support_count"]) != regional_count:
        raise AcceptanceError("regional support count changed")
    if regional_count:
        if (
            int(row["regional_coverage_mask"]) != 255
            or any(value is None for value in regional_values)
        ):
            raise AcceptanceError("a present regional row lacks one of eight supports")
    elif (
        int(row["regional_coverage_mask"]) != 0
        or any(value is not None for value in regional_values)
        or row["regional_operator"] is not None
    ):
        raise AcceptanceError("local-only field unexpectedly contains regional support")

    if spatial.startswith("POINT_BI") or spatial == "GRID_STATIC_ONCE_V1":
        if row["bi_value"] is None:
            raise AcceptanceError(f"{field['field_id']} lost its bilinear value")
    if spatial == "POINT_NN_TILE9_V1":
        if row["bi_value"] is not None or row["nn_value"] is None:
            raise AcceptanceError("nearest-only field changed its local operator")
    elif spatial == "POINT_BI_NN_V1":
        if row["nn_value"] is None:
            raise AcceptanceError("BI/NN field lost its nearest value")
    elif row["nn_value"] is not None:
        raise AcceptanceError("field unexpectedly contains a nearest value")

    if expected_shape is None:
        if row["tile_shape"] is not None or row["tile_values"] is not None:
            raise AcceptanceError("non-tile field contains a tile")
    else:
        if row["tile_shape"] != expected_shape or row["tile_values"] is None:
            raise AcceptanceError("tile shape changed")
        if len(row["tile_values"]) != expected_shape[0] * expected_shape[1]:
            raise AcceptanceError("tile value count changed")

    values = _all_values(row)
    if not values or not all(map(math.isfinite, values)):
        raise AcceptanceError("present canonical row contains no finite values")
    lower, upper = map(float, physical_range)
    observed_min, observed_max = min(values), max(values)
    if observed_min < lower or observed_max > upper:
        raise AcceptanceError(
            f"physical range failure for {field['field_id']}: "
            f"[{observed_min}, {observed_max}] outside [{lower}, {upper}]"
        )
    return observed_min, observed_max


def _decoded_identity_is_bound(row: Mapping[str, Any], field: Mapping[str, str]) -> bool:
    value = row["decoded_grib_identity"]
    if not isinstance(value, str) or not value.startswith("{") or not value.endswith("}"):
        return False
    required = (
        f'"cycle_time_utc":"{_iso(row["cycle_init_utc"])}"',
        f'"valid_time_utc":"{_iso(row["valid_time_utc"])}"',
        f'"step_type":"{field["decoded_step_type"]}"',
        '"grid_id":"HRRR_CONUS_NATIVE_LAMBERT_V4"',
        '"units":"',
    )
    # ecCodes writes canonical spellings such as ``m s**-1`` while the sealed
    # registry uses the equivalent normalized ``m s-1``. The canonical field
    # row is checked against the registry above; here the decoded message must
    # retain a non-empty native units identity without requiring textual alias
    # equality.
    return all(fragment in value for fragment in required)


def _validate_field_row(
    row: Mapping[str, Any],
    plan: Mapping[str, Any],
    field: Mapping[str, str],
    physical_range: Sequence[float],
    acquisition_run_id: str,
) -> tuple[float | None, float | None]:
    exact = {
        "target_day": plan["target_day"],
        "cycle_init_utc": plan["cycle_init_utc"],
        "product": str(plan["product"]),
        "forecast_lead_min": int(plan["forecast_lead_min"]),
        "valid_time_utc": plan["valid_time_utc"],
        "field_registry_id": str(plan["field_registry_id"]),
        "step_type": str(plan["step_type"]),
        "interval_start_utc": plan["interval_start_utc"],
        "interval_end_utc": plan["interval_end_utc"],
        "selector_identity": str(plan["selector_identity"]),
        "regional_spatial_contract_id": str(plan["regional_spatial_contract_id"]),
        "regional_support_count": int(plan["regional_support_count"]),
    }
    for name, expected in exact.items():
        observed = str(row[name]) if name in {"product", "field_registry_id"} else row[name]
        if observed != expected:
            raise AcceptanceError(f"canonical row disagrees with plan column {name}")
    if (
        row["hrrr_version"] != "v4"
        or row["parameter"] != field["parameter"]
        or row["level"] != field["level"]
        or row["native_unit"] != field["native_unit"]
        or row["canonical_unit"] != field["canonical_unit"]
        or row["station_id"] != "KDEN"
        or row["station_coord_era"] != _expected_coordinate_era(row["valid_time_utc"])
        or row["grid_geometry_id"] != "HRRR_CONUS_NATIVE_LAMBERT_V4"
        or row["regional_spatial_contract_id"] != R14_SPATIAL_CONTRACT_ID
        or row["retrieval_run_id"] != acquisition_run_id
        or row["selector_identity"].split("@", 1)[0] != field["selector_contract_id"]
    ):
        raise AcceptanceError("canonical registry, station, or grid identity changed")
    if row["cycle_init_local"] != _utc(row["cycle_init_utc"]).astimezone(DENVER):
        raise AcceptanceError("cycle local-time projection changed")
    if row["valid_time_local"] != _utc(row["valid_time_utc"]).astimezone(DENVER):
        raise AcceptanceError("valid local-time projection changed")
    if int((row["valid_time_utc"] - row["cycle_init_utc"]).total_seconds() // 60) != int(
        row["forecast_lead_min"]
    ):
        raise AcceptanceError("forecast lead no longer matches cycle and valid time")
    duration = int(
        (row["interval_end_utc"] - row["interval_start_utc"]).total_seconds() // 60
    )
    semantics = field["interval_semantics"]
    registered_duration = int(field["interval_minutes"])
    if semantics in {"snapshot", "static_snapshot"}:
        interval_valid = (
            duration == 0
            and row["interval_start_utc"] == row["valid_time_utc"]
            and row["interval_end_utc"] == row["valid_time_utc"]
        )
    else:
        allowed_durations = {registered_duration}
        if int(row["forecast_lead_min"]) == 0:
            allowed_durations.add(0)
        interval_valid = (
            semantics in {"preceding_average", "preceding_accumulation"}
            and duration in allowed_durations
            and row["interval_end_utc"] == row["valid_time_utc"]
        )
    if not interval_valid:
        raise AcceptanceError(
            f"canonical interval bounds changed for {field['field_id']} at "
            f"lead {row['forecast_lead_min']}"
        )
    window_end = datetime.combine(
        row["target_day"] + timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    ).replace(hour=7)
    if not _utc(row["valid_time_utc"]) < window_end:
        raise AcceptanceError("canonical valid time reaches the right-open target-window end")
    coverage = str(row["coverage_flag"])
    if coverage == "PRESENT":
        identity_checks = {
            "payload_hash": row["payload_hash"] is not None
            and len(row["payload_hash"]) == 32,
            "byte_start": row["byte_start"] is not None,
            "byte_end": row["byte_end"] is not None,
            "byte_order": row["byte_start"] is not None
            and row["byte_end"] is not None
            and int(row["byte_end"]) >= int(row["byte_start"]),
            "decoded_identity": _decoded_identity_is_bound(row, field),
        }
        if not all(identity_checks.values()):
            failed = sorted(name for name, passed in identity_checks.items() if not passed)
            raise AcceptanceError(
                "present row lost byte/hash/decoded-message identity for "
                f"{field['field_id']} at {_iso(row['valid_time_utc'])}: {failed}"
            )
    elif coverage == "MISSING" and any(
        row[name] is not None
        for name in ("payload_hash", "byte_start", "byte_end", "decoded_grib_identity")
    ):
        raise AcceptanceError("missing row contains successful retrieval evidence")
    if row["source_idx_hash"] is None or len(row["source_idx_hash"]) != 32:
        raise AcceptanceError("canonical row lost its source index hash")
    return _validate_spatial_values(row, field=field, physical_range=physical_range)


def _validate_ledger_row(
    ledger: Mapping[str, Any],
    field_row: Mapping[str, Any],
    plan: Mapping[str, Any],
    acquisition_run_id: str,
) -> None:
    exact = {
        "request_id": str(plan["request_id"]),
        "retrieval_run_id": acquisition_run_id,
        "product": str(plan["product"]),
        "cycle_init_utc": plan["cycle_init_utc"],
        "source_object_identity": str(plan["source_object_identity"]),
        "index_object_identity": str(plan["index_object_identity"]),
        "field_registry_id": str(plan["field_registry_id"]),
        "selector_identity": str(plan["selector_identity"]),
    }
    for name, expected in exact.items():
        observed = str(ledger[name]) if name in {"product", "field_registry_id"} else ledger[name]
        if observed != expected:
            raise AcceptanceError(f"retrieval ledger disagrees with plan column {name}")
    if int(ledger["attempt_number"]) < 1 or int(ledger["accepted_bytes"]) < 0:
        raise AcceptanceError("retrieval ledger contains invalid attempt/byte accounting")
    coverage = str(field_row["coverage_flag"])
    if coverage == "PRESENT":
        if (
            ledger["terminal_disposition"] != "SUCCESS"
            or ledger["publication_status"] != "CANONICAL_ROW_PUBLISHED"
            or int(ledger["http_status"] or 0) != 206
            or ledger["coalesced_group_id"] is None
            or int(ledger["requested_bytes"])
            != int(field_row["byte_end"]) - int(field_row["byte_start"]) + 1
        ):
            raise AcceptanceError("successful ledger row has invalid terminal evidence")
    elif (
        ledger["terminal_disposition"] != "CONFIRMED_REMOTE_MISSING"
        or ledger["publication_status"] != "MISSING_ROW_PUBLISHED"
        or int(ledger["http_status"] or 0) != 404
        or ledger["coalesced_group_id"] is not None
        or int(ledger["requested_bytes"]) != 0
        or int(ledger["accepted_bytes"]) != 0
    ):
        raise AcceptanceError("missing ledger row lacks confirmed-404 evidence")
    for name in (
        "source_idx_hash", "payload_hash", "byte_start", "byte_end", "decoded_grib_identity"
    ):
        if ledger[name] != field_row[name]:
            raise AcceptanceError(f"ledger/canonical lineage disagrees at {name}")


def _validate_h14_evidence(path: Path, acquisition_run_id: str, unit_id: str) -> None:
    value = _read_json(path)
    if (
        value.get("schema_version") != "KDEN_V375_R14_H14_TERRAIN_SUPPORTS_V1"
        or value.get("run_id") != acquisition_run_id
        or value.get("unit_id") != unit_id
        or len(value.get("evidence", ())) != 1
    ):
        raise AcceptanceError("H14 terrain evidence identity changed")
    evidence = value["evidence"][0]
    expected_eras = {"KDEN_COORD_20040105", "KDEN_COORD_20211122"}
    values = evidence.get("values_by_coordinate_era", {})
    masks = evidence.get("coverage_masks_by_coordinate_era", {})
    if set(values) != expected_eras or set(masks) != expected_eras:
        raise AcceptanceError("H14 terrain evidence lost a coordinate era")
    for era in expected_eras:
        if (
            int(masks[era]) != 255
            or len(values[era]) != 8
            or not all(math.isfinite(float(item)) for item in values[era])
        ):
            raise AcceptanceError(f"H14 terrain evidence is incomplete for {era}")


def validate_acceptance_unit(
    context: AcceptanceContext, unit: AcceptanceUnit
) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise AcceptanceError("pyarrow is required for full acceptance") from exc

    root = context.root
    spec = unit.spec
    entry = unit.acquisition_entry
    artifact = _inside(root, spec.artifact_path)
    manifest_path = _inside(root, spec.manifest_path)
    if not artifact.is_dir() or not manifest_path.is_file():
        raise AcceptanceError(f"archive unit is missing: {spec.unit_id}")
    observed_manifest_hash = sha256_file(manifest_path)
    observed_artifact_hash = sha256_path(artifact)
    if (
        observed_manifest_hash != entry["manifest_sha256"]
        or observed_artifact_hash != entry["artifact_sha256"]
    ):
        raise AcceptanceError(f"archive unit hash changed: {spec.unit_id}")
    unit_manifest = _read_json(manifest_path)
    plan_identity = context.product_plan[spec.product]["plan_sha256"]
    if unit_manifest != {
        "schema_version": "KDEN_V375_WORK_UNIT_MANIFEST_V1",
        "run_id": context.acquisition_run_id,
        "step_id": "STEP_05",
        "request_plan_sha256": plan_identity,
        "unit_id": spec.unit_id,
        "plan_ordinal": spec.ordinal,
        "artifact_path": spec.artifact_path,
        "artifact_sha256": observed_artifact_hash,
        "counts": unit_manifest.get("counts"),
    }:
        raise AcceptanceError(f"work-unit manifest identity changed: {spec.unit_id}")

    # load_unit_plan_rows performs a timezone-bearing Arrow-to-Python
    # conversion internally, so it participates in the same serialization
    # contract as the canonical archive tables below.
    with _ARROW_TO_PYTHON_LOCK:
        plan_rows = load_unit_plan_rows(root, spec)
    plan_by_key: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    plan_by_request: dict[str, Mapping[str, Any]] = {}
    for row in plan_rows:
        key = (row["cycle_init_utc"], row["valid_time_utc"], str(row["field_registry_id"]))
        request_id = str(row["request_id"])
        if key in plan_by_key or request_id in plan_by_request:
            raise AcceptanceError(f"duplicate request-plan identity: {spec.unit_id}")
        plan_by_key[key] = row
        plan_by_request[request_id] = row

    cycle_files = sorted(artifact.glob("cycle=*/field_state.parquet"))
    expected_partitions = {_cycle_partition(row["cycle_init_utc"]) for row in plan_rows}
    observed_partitions = {path.parent.name for path in cycle_files}
    if expected_partitions != observed_partitions or len(cycle_files) != len(expected_partitions):
        raise AcceptanceError(f"cycle partitions disagree with plan: {spec.unit_id}")
    forbidden = tuple(str(item).lower() for item in context.contract["forbidden_column_fragments"])
    field_rows: list[dict[str, Any]] = []
    for path in cycle_files:
        parquet = pq.ParquetFile(path)
        if not _schema_matches(parquet.schema_arrow, context.field_schema):
            raise AcceptanceError(f"field-state schema changed: {path}")
        if any(fragment in name.lower() for name in parquet.schema_arrow.names for fragment in forbidden):
            raise AcceptanceError("forbidden truth/MADIS/market column entered field state")
        rows = _arrow_to_pylist(parquet.read())
        keys = [
            (row["valid_time_utc"], str(row["field_registry_id"]), row["interval_start_utc"])
            for row in rows
        ]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise AcceptanceError(f"field-state partition is unsorted or non-unique: {path}")
        field_rows.extend(rows)
    field_by_key = {
        (row["cycle_init_utc"], row["valid_time_utc"], str(row["field_registry_id"])): row
        for row in field_rows
    }
    if len(field_by_key) != len(field_rows) or set(field_by_key) != set(plan_by_key):
        raise AcceptanceError(f"field-state rows do not exactly match plan: {spec.unit_id}")

    physical = context.contract["physical_ranges"]
    value_ranges: dict[str, list[float]] = {}
    success = missing = quarantined = 0
    for key, plan in plan_by_key.items():
        row = field_by_key[key]
        field_id = str(plan["field_registry_id"])
        field = context.registries[spec.product][field_id]
        observed_min, observed_max = _validate_field_row(
            row, plan, field, physical[field_id], context.acquisition_run_id
        )
        coverage = str(row["coverage_flag"])
        success += coverage == "PRESENT"
        missing += coverage == "MISSING"
        quarantined += coverage == "QUARANTINED"
        if observed_min is not None and observed_max is not None:
            bucket = value_ranges.setdefault(field_id, [observed_min, observed_max])
            bucket[0] = min(bucket[0], observed_min)
            bucket[1] = max(bucket[1], observed_max)

    ledger_path = artifact / "_retrieval_ledger.parquet"
    coverage_path = artifact / "_temporal_coverage.parquet"
    ledger_file = pq.ParquetFile(ledger_path)
    coverage_file = pq.ParquetFile(coverage_path)
    if not _schema_matches(ledger_file.schema_arrow, context.ledger_schema):
        raise AcceptanceError(f"retrieval-ledger schema changed: {spec.unit_id}")
    if not _schema_matches(coverage_file.schema_arrow, context.coverage_schema):
        raise AcceptanceError(f"temporal-coverage schema changed: {spec.unit_id}")
    if any(
        fragment in name.lower()
        for schema in (ledger_file.schema_arrow, coverage_file.schema_arrow)
        for name in schema.names
        for fragment in forbidden
    ):
        raise AcceptanceError("forbidden truth/MADIS/market column entered archive metadata")
    ledger_rows = _arrow_to_pylist(ledger_file.read())
    ledger_by_request = {str(row["request_id"]): row for row in ledger_rows}
    if len(ledger_by_request) != len(ledger_rows) or set(ledger_by_request) != set(plan_by_request):
        raise AcceptanceError(f"retrieval ledger does not exactly match plan: {spec.unit_id}")
    for request_id, plan in plan_by_request.items():
        key = (plan["cycle_init_utc"], plan["valid_time_utc"], str(plan["field_registry_id"]))
        _validate_ledger_row(
            ledger_by_request[request_id], field_by_key[key], plan, context.acquisition_run_id
        )

    actual_coverage = _arrow_to_pylist(coverage_file.read())
    expected_coverage = coverage_rows(field_rows, context.acquisition_run_id)
    if actual_coverage != expected_coverage:
        raise AcceptanceError(f"temporal coverage does not reconcile: {spec.unit_id}")
    if any(int(row["quarantined_valid_count"]) for row in actual_coverage):
        raise AcceptanceError(f"quarantined row entered accepted archive: {spec.unit_id}")

    summary = _read_json(artifact / "_unit_summary.json")
    counts = unit_manifest.get("counts", {})
    maximum_valid = max(row["valid_time_utc"] for row in plan_rows)
    expected_fields = sorted({str(row["field_registry_id"]) for row in plan_rows})
    checks = {
        "schema_version": summary.get("schema_version") == "KDEN_V375_R14_ACQUISITION_UNIT_SUMMARY_V1",
        "scope_id": summary.get("scope_id") == R14_SCOPE_ID,
        "run_id": summary.get("run_id") == context.acquisition_run_id,
        "step_id": summary.get("step_id") == "STEP_05",
        "phase": summary.get("phase") == PRODUCT_PHASES[spec.product],
        "product": summary.get("product") == spec.product,
        "unit_id": summary.get("unit_id") == spec.unit_id,
        "plan_ordinal": int(summary.get("plan_ordinal", -1)) == spec.ordinal,
        "target_day": summary.get("target_day") == spec.target_day.isoformat(),
        "static": summary.get("static") is spec.static,
        "plan": summary.get("request_plan_sha256") == plan_identity,
        "request_count": int(summary.get("request_count", -1)) == len(plan_rows),
        "field_rows": int(summary.get("field_state_row_count", -1)) == len(field_rows),
        "ledger_rows": int(summary.get("ledger_row_count", -1)) == len(ledger_rows),
        "coverage_rows": int(summary.get("coverage_row_count", -1)) == len(actual_coverage),
        "source_objects": int(summary.get("source_object_count", -1))
        == len({str(row["source_object_identity"]) for row in plan_rows}),
        "success": int(summary.get("success_count", -1)) == success,
        "missing": int(summary.get("confirmed_remote_missing_count", -1)) == missing,
        "quarantine": int(summary.get("quarantined_count", -1)) == quarantined == 0,
        "fields": summary.get("field_ids") == expected_fields,
        "maximum_valid": datetime.fromisoformat(summary["maximum_valid_time_utc"])
        == maximum_valid,
        "full_grid": int(summary.get("full_grid_cells_persisted", -1)) == 0,
        "workers": int(summary.get("max_download_workers", -1)) == 8,
        "publication": summary.get("publication_order")
        == "artifact_then_manifest_then_progress",
        "manifest_row_count": int(counts.get("row_count", -1)) == len(field_rows),
        "manifest_request_count": int(counts.get("request_count", -1)) == len(plan_rows),
        "manifest_accepted_bytes": int(counts.get("accepted_bytes", -1))
        == int(summary.get("network_accepted_bytes", -2)),
        "entry_request_count": int(entry.get("request_count", -1)) == len(plan_rows),
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise AcceptanceError(f"unit summary reconciliation failed ({spec.unit_id}): {failed}")
    if spec.static:
        _validate_h14_evidence(
            artifact / "_h14_terrain_supports.json",
            context.acquisition_run_id,
            spec.unit_id,
        )
    elif (artifact / "_h14_terrain_supports.json").exists():
        raise AcceptanceError("dynamic unit unexpectedly contains H14 terrain evidence")

    result = {
        "schema_version": "KDEN_V375_STEP08_UNIT_RESULT_V1",
        "status": "PASS",
        "sequence": unit.sequence,
        "unit_id": spec.unit_id,
        "product": spec.product,
        "target_day": spec.target_day.isoformat(),
        "static": spec.static,
        "artifact_path": spec.artifact_path,
        "artifact_sha256": observed_artifact_hash,
        "manifest_path": spec.manifest_path,
        "manifest_sha256": observed_manifest_hash,
        "request_plan_sha256": plan_identity,
        "request_count": len(plan_rows),
        "field_state_row_count": len(field_rows),
        "ledger_row_count": len(ledger_rows),
        "coverage_row_count": len(actual_coverage),
        "success_count": success,
        "confirmed_remote_missing_count": missing,
        "quarantined_count": quarantined,
        "local_size_bytes": _tree_size(artifact) + manifest_path.stat().st_size,
        "cycle_count": len(cycle_files),
        "field_ids": expected_fields,
        "maximum_valid_time_utc": _iso(maximum_valid),
        "field_value_ranges": {
            key: [value[0], value[1]] for key, value in sorted(value_ranges.items())
        },
        "source_selector_decoded_identity_rows_verified": success,
        "interval_rows_verified": len(field_rows),
        "spatial_rows_verified": len(field_rows),
        "right_open_rows_verified": len(field_rows),
    }
    return {**result, "result_sha256": sha256_bytes(canonical_json_bytes(result))}


class AcceptanceCheckpoint:
    """Transactional per-unit acceptance state; only the coordinator writes it."""

    def __init__(self, path: Path, metadata: Mapping[str, str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS unit_results (
                sequence INTEGER NOT NULL UNIQUE,
                unit_id TEXT PRIMARY KEY,
                product TEXT NOT NULL,
                target_day TEXT NOT NULL,
                request_count INTEGER NOT NULL,
                local_size_bytes INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                result_sha256 TEXT NOT NULL,
                completed_at_utc TEXT NOT NULL
            )"""
        )
        observed = dict(self.connection.execute("SELECT key, value FROM metadata"))
        expected = {"checkpoint_schema": CHECKPOINT_SCHEMA, **dict(metadata)}
        if observed and observed != expected:
            raise AcceptanceError("Step 08 checkpoint belongs to another contract or run")
        if not observed:
            self.connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)", sorted(expected.items())
            )
            self.connection.commit()
        if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise AcceptanceError("Step 08 checkpoint database failed integrity check")
        self._rows = self._load_rows()

    def _load_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        query = (
            "SELECT sequence, unit_id, product, target_day, request_count, "
            "local_size_bytes, result_json, result_sha256, completed_at_utc "
            "FROM unit_results ORDER BY sequence"
        )
        for values in self.connection.execute(query):
            row = dict(
                zip(
                    (
                        "sequence", "unit_id", "product", "target_day", "request_count",
                        "local_size_bytes", "result_json", "result_sha256", "completed_at_utc",
                    ),
                    values,
                    strict=True,
                )
            )
            result = json.loads(row["result_json"])
            supplied = result.pop("result_sha256", None)
            if supplied != row["result_sha256"] or supplied != sha256_bytes(
                canonical_json_bytes(result)
            ):
                raise AcceptanceError("Step 08 checkpoint result hash changed")
            result["result_sha256"] = supplied
            row["result"] = result
            rows.append(row)
        if [int(row["sequence"]) for row in rows] != list(range(len(rows))):
            raise AcceptanceError("Step 08 checkpoint sequences are not contiguous")
        return rows

    @property
    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._rows)

    def commit(self, result: Mapping[str, Any]) -> dict[str, Any]:
        sequence = int(result["sequence"])
        if sequence != len(self._rows):
            raise AcceptanceError("Step 08 result commit order changed")
        completed = utc_now()
        payload = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        with self.connection:
            self.connection.execute(
                """INSERT INTO unit_results(
                    sequence, unit_id, product, target_day, request_count,
                    local_size_bytes, result_json, result_sha256, completed_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sequence,
                    result["unit_id"],
                    result["product"],
                    result["target_day"],
                    int(result["request_count"]),
                    int(result["local_size_bytes"]),
                    payload,
                    result["result_sha256"],
                    completed,
                ),
            )
        row = {
            "sequence": sequence,
            "unit_id": result["unit_id"],
            "product": result["product"],
            "target_day": result["target_day"],
            "request_count": int(result["request_count"]),
            "local_size_bytes": int(result["local_size_bytes"]),
            "result_json": payload,
            "result_sha256": result["result_sha256"],
            "completed_at_utc": completed,
            "result": dict(result),
        }
        self._rows.append(row)
        return row

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()


def _journal_body(row: Mapping[str, Any], previous: str) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA,
        "sequence": int(row["sequence"]),
        "run_id": row["run_id"],
        "step_id": STEP_ID,
        "unit_id": row["unit_id"],
        "product": row["product"],
        "target_day": row["target_day"],
        "request_count": int(row["request_count"]),
        "accepted_bytes": 0,
        "checked_local_bytes": int(row["local_size_bytes"]),
        "result_sha256": row["result_sha256"],
        "completed_at_utc": row["completed_at_utc"],
        "previous_record_sha256": previous,
    }


def _journal_record(row: Mapping[str, Any], previous: str) -> dict[str, Any]:
    body = _journal_body(row, previous)
    return {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}


def _regenerate_journal(path: Path, rows: Sequence[Mapping[str, Any]], run_id: str) -> str:
    payload = bytearray()
    previous = ZERO_HASH
    for row in rows:
        record = _journal_record({**row, "run_id": run_id}, previous)
        payload.extend(canonical_json_bytes(record))
        previous = record["record_sha256"]
    atomic_write_bytes(path, bytes(payload))
    return previous


def _append_journal(path: Path, row: Mapping[str, Any], run_id: str, previous: str) -> str:
    record = _journal_record({**row, "run_id": run_id}, previous)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        payload = memoryview(canonical_json_bytes(record))
        while payload:
            written = os.write(descriptor, payload)
            if written <= 0:
                raise OSError("Step 08 journal append made no progress")
            payload = payload[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    return str(record["record_sha256"])


def _write_live_status(
    path: Path,
    *,
    run_id: str,
    rows: Sequence[Mapping[str, Any]],
    expected_units: int,
    expected_requests: int,
    status: str,
    current: AcceptanceUnit | None,
) -> dict[str, Any]:
    completed_requests = sum(int(row["request_count"]) for row in rows)
    body = {
        "schema_version": LIVE_SCHEMA,
        "run_id": run_id,
        "step_id": STEP_ID,
        "phase": "R14_FULL_ARCHIVE_ACCEPTANCE",
        "status": status,
        "product": None if current is None else current.spec.product,
        "current_product": None if current is None else current.spec.product,
        "current_work_unit": None if current is None else current.spec.unit_id,
        "current_target_day": None if current is None else current.spec.target_day.isoformat(),
        "completed_work_units": len(rows),
        "expected_work_units": expected_units,
        "remaining_work_units": expected_units - len(rows),
        "completed_logical_requests": completed_requests,
        "expected_logical_requests": expected_requests,
        "remaining_logical_requests": expected_requests - completed_requests,
        "disk_bytes": sum(int(row["local_size_bytes"]) for row in rows),
        "updated_at_utc": rows[-1]["completed_at_utc"] if rows else utc_now(),
    }
    atomic_write_json(path, body)
    return body


def _merge_ranges(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[float]]:
    output: dict[str, list[float]] = {}
    for row in rows:
        for field_id, values in row["result"]["field_value_ranges"].items():
            bucket = output.setdefault(field_id, [float(values[0]), float(values[1])])
            bucket[0] = min(bucket[0], float(values[0]))
            bucket[1] = max(bucket[1], float(values[1]))
    return dict(sorted(output.items()))


def _hash_named_files(root: Path, relatives: Sequence[str]) -> dict[str, str]:
    return {relative: sha256_path(_inside(root, relative)) for relative in sorted(relatives)}


def _category(value: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(sorted(value.items()))
    return {"entries": body, "category_sha256": sha256_bytes(canonical_json_bytes(body))}


def _build_freeze_manifest(
    context: AcceptanceContext,
    *,
    run_id: str,
    rows: Sequence[Mapping[str, Any]],
    checkpoint_path: Path,
    journal_path: Path,
    live_path: Path,
    completed_at: str,
) -> dict[str, Any]:
    root = context.root
    registry_files = (
        "config/r14_acquisition_v375.json",
        "config/r14_spatial_contract_v375.json",
        "registries/hrrr_hourly_v375.csv",
        "registries/hrrr_subhourly_v375.csv",
        "registries/station_coordinate_eras_v375.csv",
        "registries/grid_geometry_v375.json",
        "registries/r14_spatial_geometry_v375.json",
        "registries/registry_bundle_r14_v375.json",
    )
    schema_files = (
        "schemas/cycle_schedule_v375.json",
        "schemas/request_plan_r14_v375.json",
        "schemas/hrrr_field_state_r14_v375.json",
        "schemas/retrieval_ledger_v375.json",
        "schemas/temporal_coverage_v375.json",
        "schemas/issue_time_view_r14_v375.json",
        SCHEMA_PATH,
    )
    plan_files = (
        "config/cycle_schedule_r14_v375.toml",
        "config/request_plan_r14_v375.toml",
        "hrrr_v4_local_archive/common/cycle_schedule_r14/cycle_schedule_r14_v375_manifest.json",
        "hrrr_v4_local_archive/common/cycle_schedule_r14/cycle_schedule_r14_v375.parquet",
        "hrrr_v4_local_archive/wrfsfcf/manifests/plan_wrfsfcf_r14_v375_manifest.json",
        "hrrr_v4_local_archive/wrfsubhf/manifests/plan_wrfsubhf_q05_r14_v375_manifest.json",
    )
    code_files = (
        "src/kden_v375/contracts.py",
        "src/kden_v375/hashes.py",
        "src/kden_v375/progress.py",
        "src/kden_v375/r14.py",
        "src/kden_v375/r14_schedule.py",
        "src/kden_v375/r14_request_plans.py",
        "src/kden_v375/archive_readers.py",
        "src/kden_v375/acquisition/records.py",
        "src/kden_v375/acquisition/source.py",
        "src/kden_v375/acquisition/workflow.py",
        "src/kden_v375/acceptance/__init__.py",
        "src/kden_v375/acceptance/workflow.py",
        "src/kden_v375/steps/step_07_archive_readers.py",
        "src/kden_v375/steps/step_08_acceptance.py",
    )
    environment_files = ("environment/requirements.lock", "pyproject.toml")
    acquisition_progress: dict[str, str] = {}
    for product in PRODUCTS:
        relative = (
            f"runs/{context.acquisition_run_id}/acquisition/{product}/progress/"
            "completions.jsonl"
        )
        acquisition_progress[relative] = sha256_file(root / relative)
    archive_entries: dict[str, Any] = {}
    for product in PRODUCTS:
        selected = [row for row in rows if row["product"] == product]
        chain = [
            {
                "unit_id": row["unit_id"],
                "artifact_sha256": row["result"]["artifact_sha256"],
                "manifest_sha256": row["result"]["manifest_sha256"],
                "result_sha256": row["result_sha256"],
                "request_count": int(row["request_count"]),
            }
            for row in selected
        ]
        archive_entries[product] = {
            "unit_count": len(selected),
            "request_count": sum(int(row["request_count"]) for row in selected),
            "local_size_bytes": sum(int(row["local_size_bytes"]) for row in selected),
            "unit_chain_sha256": sha256_bytes(canonical_json_bytes(chain)),
            "product_manifest_sha256": sha256_file(root / PRODUCT_MANIFEST_PATH[product]),
        }
    categories = {
        "registry": _category(_hash_named_files(root, registry_files)),
        "schema": _category(_hash_named_files(root, schema_files)),
        "plan": _category(_hash_named_files(root, plan_files)),
        "code": _category(_hash_named_files(root, code_files)),
        "environment": _category(_hash_named_files(root, environment_files)),
        "archive": _category(archive_entries),
        "acquisition_progress": _category(acquisition_progress),
        "acceptance_checkpoint": _category(
            {
                relative_to_root(root, checkpoint_path): sha256_file(checkpoint_path),
                relative_to_root(root, journal_path): sha256_file(journal_path),
                relative_to_root(root, live_path): sha256_file(live_path),
            }
        ),
    }
    body = {
        "schema_version": FREEZE_SCHEMA,
        "scope_id": R14_SCOPE_ID,
        "contract_id": CONTRACT_ID,
        "status": "FROZEN",
        "run_id": run_id,
        "completed_at_utc": completed_at,
        "predecessor_hashes": {
            "R14": context.r14_pass_sha256,
            "STEP_07": context.step07_pass_sha256,
        },
        "categories": categories,
    }
    return {**body, "freeze_sha256": sha256_bytes(canonical_json_bytes(body))}


def _publish_immutable_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        if _read_json(path) != dict(value):
            raise AcceptanceError(f"immutable Step 08 artifact differs: {path}")
        return
    atomic_write_json(path, dict(value), replace=False)


def _final_artifacts(root: Path, run_id: str) -> tuple[str, ...]:
    prefix = f"runs/{run_id}/acceptance"
    return (
        CONTRACT_PATH,
        SCHEMA_PATH,
        REPORT_PATH,
        FREEZE_PATH,
        RUNBOOK_PATH,
        "src/kden_v375/acceptance/__init__.py",
        "src/kden_v375/acceptance/workflow.py",
        "src/kden_v375/steps/step_08_acceptance.py",
        f"{prefix}/checkpoint.sqlite3",
        f"{prefix}/progress/completions.jsonl",
        f"runs/{run_id}/monitoring/live_status.json",
    )


def _write_final_pass(
    context: AcceptanceContext,
    *,
    run_id: str,
    gates: Mapping[str, bool],
    freeze: Mapping[str, Any],
    completed_at: str,
) -> dict[str, Any]:
    root = context.root
    artifact_hashes = _hash_named_files(root, _final_artifacts(root, run_id))
    body = {
        "schema_version": FINAL_PASS_SCHEMA,
        "record_id": "KDEN_V375_ACQUISITION",
        "scope_id": R14_SCOPE_ID,
        "status": "PASS",
        "run_id": run_id,
        "completed_at_utc": completed_at,
        "predecessor_hashes": {
            "R14": context.r14_pass_sha256,
            "STEP_07": context.step07_pass_sha256,
        },
        "freeze_sha256": freeze["freeze_sha256"],
        "artifact_hashes": artifact_hashes,
        "gate_evidence": dict(gates),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    _publish_immutable_json(root / FINAL_PASS_PATH, record)
    return record


def verify_final_acceptance_pass(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = _read_json(root / FINAL_PASS_PATH)
    if (
        record.get("schema_version") != FINAL_PASS_SCHEMA
        or record.get("record_id") != "KDEN_V375_ACQUISITION"
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("status") != "PASS"
        or not record.get("gate_evidence")
        or not all(value is True for value in record["gate_evidence"].values())
    ):
        raise AcceptanceError("final acquisition PASS identity or gates changed")
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise AcceptanceError("final acquisition PASS content hash changed")
    step07 = verify_step_pass(root, 7)
    combined = read_combined_pass_identity(root)
    if record.get("predecessor_hashes") != {
        "R14": combined["record_sha256"],
        "STEP_07": step07["record_sha256"],
    }:
        raise AcceptanceError("final acquisition PASS predecessor changed")
    for relative, expected in record.get("artifact_hashes", {}).items():
        if sha256_path(_inside(root, relative)) != expected:
            raise AcceptanceError(f"final acquisition artifact changed: {relative}")
    freeze = _read_json(root / FREEZE_PATH)
    freeze_body = dict(freeze)
    freeze_hash = freeze_body.pop("freeze_sha256", None)
    if (
        freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze_hash != sha256_bytes(canonical_json_bytes(freeze_body))
        or freeze_hash != record.get("freeze_sha256")
    ):
        raise AcceptanceError("acquisition freeze manifest changed")
    return record


def run_final_acceptance(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    validate_run_id(run_id, step_no=8, scope="validation")
    root = load_project_paths(project_root).root
    if (root / FINAL_PASS_PATH).is_file():
        record = verify_final_acceptance_pass(root)
        if record["run_id"] != run_id:
            raise AcceptanceError("final acceptance already belongs to another run")
        return record
    context = build_acceptance_context(root)
    _prepare_arrow_python_conversion()
    run_dir = root / "runs" / run_id
    acceptance_dir = run_dir / "acceptance"
    checkpoint_path = acceptance_dir / "checkpoint.sqlite3"
    journal_path = acceptance_dir / "progress/completions.jsonl"
    live_path = run_dir / "monitoring/live_status.json"
    metadata = {
        "run_id": run_id,
        "contract_sha256": context.contract_sha256,
        "r14_pass_sha256": context.r14_pass_sha256,
        "step07_pass_sha256": context.step07_pass_sha256,
    }
    checkpoint = AcceptanceCheckpoint(checkpoint_path, metadata)
    try:
        rows = list(checkpoint.rows)
        for index, row in enumerate(rows):
            expected = context.units[index]
            if row["unit_id"] != expected.spec.unit_id or row["product"] != expected.spec.product:
                raise AcceptanceError("checkpoint unit sequence differs from frozen archive")
        journal_tip = _regenerate_journal(journal_path, rows, run_id)
        current = context.units[len(rows)] if len(rows) < len(context.units) else None
        _write_live_status(
            live_path,
            run_id=run_id,
            rows=rows,
            expected_units=len(context.units),
            expected_requests=COMBINED_REQUEST_COUNT,
            status="RUNNING",
            current=current,
        )

        def commit(result: Mapping[str, Any]) -> None:
            nonlocal journal_tip, rows
            row = checkpoint.commit(result)
            rows.append(row)
            journal_tip = _append_journal(journal_path, row, run_id, journal_tip)
            next_unit = (
                context.units[len(rows)] if len(rows) < len(context.units) else None
            )
            _write_live_status(
                live_path,
                run_id=run_id,
                rows=rows,
                expected_units=len(context.units),
                expected_requests=COMBINED_REQUEST_COUNT,
                status="RUNNING" if next_unit is not None else "COMPLETE",
                current=next_unit,
            )

        remaining = context.units[len(rows) :]
        if remaining:
            with ThreadPoolExecutor(
                max_workers=int(context.contract["execution"]["max_local_validation_workers"])
            ) as executor:
                summary = _execute_on_persistent_pool(
                    remaining,
                    executor=executor,
                    worker=lambda unit: validate_acceptance_unit(context, unit),
                    commit=commit,
                    pause_requested=(lambda: pause.requested if pause is not None else False),
                )
            if summary.paused:
                _write_live_status(
                    live_path,
                    run_id=run_id,
                    rows=rows,
                    expected_units=len(context.units),
                    expected_requests=COMBINED_REQUEST_COUNT,
                    status="PAUSED",
                    current=context.units[len(rows)] if len(rows) < len(context.units) else None,
                )
                if pause is not None:
                    pause.raise_if_requested()
                raise AcceptanceError("Step 08 stopped before all units were committed")
        if len(rows) != len(context.units):
            raise AcceptanceError("Step 08 checkpoint is incomplete")
        if pause is not None:
            pause.raise_if_requested()
        checkpoint.close()

        totals: dict[str, dict[str, Any]] = {}
        for product in PRODUCTS:
            selected = [row for row in rows if row["product"] == product]
            totals[product] = {
                "work_unit_count": len(selected),
                "request_count": sum(int(row["request_count"]) for row in selected),
                "field_state_row_count": sum(
                    int(row["result"]["field_state_row_count"]) for row in selected
                ),
                "success_count": sum(int(row["result"]["success_count"]) for row in selected),
                "confirmed_remote_missing_count": sum(
                    int(row["result"]["confirmed_remote_missing_count"]) for row in selected
                ),
                "quarantined_count": sum(
                    int(row["result"]["quarantined_count"]) for row in selected
                ),
                "local_size_bytes": sum(int(row["local_size_bytes"]) for row in selected),
                "field_ids": sorted(
                    {
                        field_id
                        for row in selected
                        for field_id in row["result"]["field_ids"]
                    }
                ),
            }
        anchors = set(context.contract["deterministic_rebuild_anchor_units"])
        indexed = {unit.spec.unit_id: unit for unit in context.units}
        deterministic = {
            unit_id: validate_acceptance_unit(context, indexed[unit_id])["result_sha256"]
            for unit_id in sorted(anchors)
        }
        checkpoint_results = {
            row["unit_id"]: row["result_sha256"] for row in rows if row["unit_id"] in anchors
        }
        expected = context.contract["expected"]
        pilot = _read_step04_identity(root)
        gates = {
            "all_archive_units_deeply_verified": len(rows) == COMBINED_UNIT_COUNT,
            "all_logical_requests_reconciled": sum(
                int(row["request_count"]) for row in rows
            )
            == COMBINED_REQUEST_COUNT,
            "schedule_and_right_open_window_verified": context.schedule_evidence.get(
                "all_native_valid_times_strictly_before_window_end"
            )
            is True,
            "source_selector_decoded_identity_verified": sum(
                int(row["result"]["source_selector_decoded_identity_rows_verified"])
                for row in rows
            )
            == sum(int(row["result"]["success_count"]) for row in rows),
            "interval_semantics_verified": sum(
                int(row["result"]["interval_rows_verified"]) for row in rows
            )
            == COMBINED_REQUEST_COUNT,
            "spatial_geometry_units_and_physical_ranges_verified": (
                set(_merge_ranges(rows)) == set(context.contract["physical_ranges"])
            ),
            "expected_present_missing_reconciliation_verified": all(
                totals[product]["request_count"]
                == totals[product]["success_count"]
                + totals[product]["confirmed_remote_missing_count"]
                for product in PRODUCTS
            ),
            "expected_remote_missingness_verified": all(
                totals[product]["confirmed_remote_missing_count"]
                == int(expected[product]["confirmed_remote_missing_count"])
                for product in PRODUCTS
            ),
            "zero_quarantines_verified": all(
                totals[product]["quarantined_count"] == 0 for product in PRODUCTS
            ),
            "independent_hourly_and_q05_archives_usable": all(
                totals[product]["work_unit_count"]
                == int(expected[product]["work_unit_count"])
                and totals[product]["request_count"]
                == int(expected[product]["logical_request_count"])
                for product in PRODUCTS
            ),
            "exact_r14_field_universe_verified": all(
                totals[product]["field_ids"] == sorted(expected[product]["field_ids"])
                for product in PRODUCTS
            ),
            "deterministic_bounded_rebuild_verified": deterministic == checkpoint_results,
            "pilot_rebuild_evidence_verified": pilot["gate_evidence"].get(
                "pilot_rebuild_value_identical_and_hash_stable"
            )
            is True,
            "truth_madis_market_and_legacy_runtime_isolation_verified": (
                context.isolation_evidence["legacy_runtime_references_found"] == 0
                and context.isolation_evidence["absolute_user_paths_found"] == 0
            ),
            "checkpoint_and_journal_complete": len(rows) == COMBINED_UNIT_COUNT
            and journal_tip != ZERO_HASH,
        }
        if not all(gates.values()):
            failed = sorted(name for name, passed in gates.items() if not passed)
            raise AcceptanceError(f"Step 08 final gates failed: {failed}")
        completed_at = str(rows[-1]["completed_at_utc"])
        _write_live_status(
            live_path,
            run_id=run_id,
            rows=rows,
            expected_units=len(context.units),
            expected_requests=COMBINED_REQUEST_COUNT,
            status="COMPLETE",
            current=None,
        )
        freeze = _build_freeze_manifest(
            context,
            run_id=run_id,
            rows=rows,
            checkpoint_path=checkpoint_path,
            journal_path=journal_path,
            live_path=live_path,
            completed_at=completed_at,
        )
        _publish_immutable_json(root / FREEZE_PATH, freeze)
        report = {
            "schema_version": REPORT_SCHEMA,
            "scope_id": R14_SCOPE_ID,
            "contract_id": CONTRACT_ID,
            "status": "PASS",
            "run_id": run_id,
            "completed_at_utc": completed_at,
            "predecessor_hashes": {
                "R14": context.r14_pass_sha256,
                "STEP_07": context.step07_pass_sha256,
            },
            "totals": totals,
            "combined": {
                "work_unit_count": len(rows),
                "request_count": sum(int(row["request_count"]) for row in rows),
                "local_size_bytes": sum(int(row["local_size_bytes"]) for row in rows),
                "confirmed_remote_missing_count": sum(
                    int(row["result"]["confirmed_remote_missing_count"]) for row in rows
                ),
                "quarantined_count": 0,
            },
            "field_value_ranges": _merge_ranges(rows),
            "deterministic_rebuild": deterministic,
            "freeze_sha256": freeze["freeze_sha256"],
            "checkpoint_path": relative_to_root(root, checkpoint_path),
            "journal_path": relative_to_root(root, journal_path),
            "gates": gates,
        }
        _publish_immutable_json(root / REPORT_PATH, report)
        return _write_final_pass(
            context,
            run_id=run_id,
            gates=gates,
            freeze=freeze,
            completed_at=completed_at,
        )
    except BaseException:
        try:
            rows = list(checkpoint.rows)
            _write_live_status(
                live_path,
                run_id=run_id,
                rows=rows,
                expected_units=len(context.units),
                expected_requests=COMBINED_REQUEST_COUNT,
                status="PAUSED" if pause is not None and pause.requested else "FAILED",
                current=context.units[len(rows)] if len(rows) < len(context.units) else None,
            )
        finally:
            try:
                checkpoint.close()
            except sqlite3.Error:
                pass
        raise
