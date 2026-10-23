"""Load, validate, and seal the immutable Step 01 registry bundle."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import ContractError, load_project_paths
from .hashes import canonical_json_bytes, sha256_bytes, sha256_file
from .io.atomic import atomic_write_json


REGISTRY_SCHEMA_VERSION = "KDEN_V375_FIELD_REGISTRY_V1"
BUNDLE_SCHEMA_VERSION = "KDEN_V375_REGISTRY_BUNDLE_V1"
PARQUET_SCHEMA_VERSION = "KDEN_V375_PARQUET_SCHEMA_V1"
ARROW_TYPE_NAMES = frozenset(
    {
        "bool",
        "date32",
        "int8",
        "int16",
        "int32",
        "int64",
        "float64",
        "string",
        "timestamp[us,UTC]",
        "timestamp[us,America/Denver]",
        "fixed_size_binary[32]",
        "dictionary<string>",
        "list<int16>",
        "list<float64>",
        "list<struct<start:timestamp[us,UTC],end:timestamp[us,UTC],reason:string>>",
    }
)

REGISTRY_INPUTS = (
    "registries/hrrr_hourly_v375.csv",
    "registries/hrrr_subhourly_v375.csv",
    "registries/station_coordinate_eras_v375.csv",
    "registries/availability_policies_v375.csv",
    "registries/decoded_grib_identities_v375.json",
    "registries/grid_geometry_v375.json",
)
SCHEMA_INPUTS = (
    "schemas/cycle_schedule_v375.json",
    "schemas/request_plan_v375.json",
    "schemas/hrrr_field_state_v375.json",
    "schemas/retrieval_ledger_v375.json",
    "schemas/temporal_coverage_v375.json",
)
BUNDLE_PATH = "registries/registry_bundle_v375.json"
BUNDLE_INPUTS = REGISTRY_INPUTS + SCHEMA_INPUTS

FIELD_COLUMNS = (
    "schema_version",
    "field_id",
    "ordinal",
    "product",
    "parameter",
    "level",
    "interval_semantics",
    "decoded_step_type",
    "interval_minutes",
    "native_cadence_minutes",
    "native_unit",
    "canonical_unit",
    "unit_conversion",
    "spatial_contract_id",
    "acquisition_contract_id",
    "parameter_identity_id",
    "level_identity_id",
    "selector_contract_id",
)

REQUIRED_SCHEMA_COLUMNS: dict[str, tuple[str, ...]] = {
    "cycle_schedule_v375.json": (
        "target_day", "product", "cycle_init_utc", "cycle_init_local",
        "local_calendar_date", "local_cycle_hour", "utc_offset_minutes", "dst_flag",
        "local_fold", "hrrr_version", "native_max_forecast_hour", "horizon_class",
        "window_start_utc", "window_end_utc", "retained_valid_start_utc",
        "retained_valid_end_utc", "availability_policy_id", "emulated_complete_time_utc",
        "actual_first_seen_utc", "availability_basis", "source_inventory_hash",
        "complete_flag", "missing_or_quarantine_reason", "retrieval_run_id",
    ),
    "request_plan_v375.json": (
        "request_id", "target_day", "product", "cycle_init_utc",
        "source_object_identity", "index_object_identity", "forecast_lead_min",
        "valid_time_utc", "field_registry_id", "selector_identity", "step_type",
        "interval_start_utc", "interval_end_utc", "spatial_contract_id", "request_action",
    ),
    "hrrr_field_state_v375.json": (
        "target_day", "cycle_init_utc", "cycle_init_local", "product", "hrrr_version",
        "forecast_lead_min", "valid_time_utc", "valid_time_local", "field_registry_id",
        "parameter", "level", "step_type", "interval_start_utc", "interval_end_utc",
        "native_unit", "canonical_unit", "station_id", "station_coord_era",
        "grid_geometry_id", "bi_value", "nn_value", "tile_shape", "tile_values",
        "coverage_flag", "missing_reason", "selector_identity", "source_idx_hash",
        "payload_hash", "byte_start", "byte_end", "decoded_grib_identity",
        "retrieval_run_id", "derivation_version",
    ),
    "retrieval_ledger_v375.json": (
        "request_id", "retrieval_run_id", "attempt_number", "product", "cycle_init_utc",
        "source_object_identity", "index_object_identity", "field_registry_id",
        "selector_identity", "http_status", "retry_class", "byte_start", "byte_end",
        "requested_bytes", "accepted_bytes", "coalesced_group_id", "source_idx_hash",
        "payload_hash", "decoded_grib_identity", "publication_status", "terminal_disposition",
    ),
    "temporal_coverage_v375.json": (
        "target_day", "product", "cycle_init_utc", "field_registry_id",
        "expected_valid_count", "present_valid_count", "missing_valid_count",
        "quarantined_valid_count", "first_valid_time_utc", "last_valid_time_utc",
        "gap_intervals", "complete_flag", "retrieval_run_id",
    ),
}


class RegistryContractError(ContractError):
    """A Step 01 registry or schema violates its frozen contract."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FIELD_COLUMNS and path.name.startswith("hrrr_"):
            raise RegistryContractError(f"unexpected field-registry columns: {path.name}")
        return list(reader)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RegistryContractError(f"JSON artifact must contain an object: {path.name}")
    return value


def _arrow_type(type_name: str) -> Any:
    """Parse the deliberately small Arrow type language used by our schemas."""

    import pyarrow as pa

    primitive = {
        "bool": pa.bool_(),
        "date32": pa.date32(),
        "int8": pa.int8(),
        "int16": pa.int16(),
        "int32": pa.int32(),
        "int64": pa.int64(),
        "float64": pa.float64(),
        "string": pa.string(),
        "timestamp[us,UTC]": pa.timestamp("us", tz="UTC"),
        "timestamp[us,America/Denver]": pa.timestamp("us", tz="America/Denver"),
        "fixed_size_binary[32]": pa.binary(32),
        "dictionary<string>": pa.dictionary(pa.int16(), pa.string()),
        "list<int16>": pa.list_(pa.int16()),
        "list<float64>": pa.list_(pa.float64()),
        "list<struct<start:timestamp[us,UTC],end:timestamp[us,UTC],reason:string>>": pa.list_(
            pa.struct(
                [
                    pa.field("start", pa.timestamp("us", tz="UTC"), nullable=False),
                    pa.field("end", pa.timestamp("us", tz="UTC"), nullable=False),
                    pa.field("reason", pa.string(), nullable=False),
                ]
            )
        ),
    }
    try:
        return primitive[type_name]
    except KeyError as exc:
        raise RegistryContractError(f"unsupported frozen Arrow type: {type_name!r}") from exc


def load_parquet_schema(project_root: Path | str, schema_name: str) -> Any:
    """Build an executable PyArrow schema from one frozen JSON declaration."""

    import pyarrow as pa

    paths = load_project_paths(project_root)
    if schema_name not in REQUIRED_SCHEMA_COLUMNS:
        raise RegistryContractError(f"unknown Parquet schema: {schema_name!r}")
    value = _read_json(paths.schemas / schema_name)
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
                nullable=column["nullable"],
            )
            for column in value["columns"]
        ],
        metadata=metadata,
    )


def interval_bounds(
    field: Mapping[str, str], valid_time_utc: datetime
) -> tuple[datetime, datetime]:
    """Resolve machine-testable native support bounds for one field row."""

    valid = valid_time_utc
    if valid.tzinfo is None or valid.utcoffset() is None:
        raise RegistryContractError("valid time must be timezone-aware")
    valid = valid.astimezone(UTC)
    semantics = field["interval_semantics"]
    minutes = int(field["interval_minutes"])
    if semantics in {"snapshot", "static_snapshot"}:
        if minutes != 0:
            raise RegistryContractError("snapshot interval must be zero minutes")
        return valid, valid
    if semantics in {"preceding_average", "preceding_accumulation"} and minutes > 0:
        return valid - timedelta(minutes=minutes), valid
    raise RegistryContractError(
        f"unsupported interval contract for {field.get('field_id', '<unknown>')}"
    )


def _validate_fields(
    root: Path, identities: Mapping[str, Any], geometry: Mapping[str, Any]
) -> dict[str, Any]:
    hourly = _read_csv(root / REGISTRY_INPUTS[0])
    subhourly = _read_csv(root / REGISTRY_INPUTS[1])
    expected = (
        (hourly, "wrfsfcf", tuple(f"H{i:02d}" for i in range(1, 45))),
        (subhourly, "wrfsubhf", tuple(f"Q{i:02d}" for i in range(1, 15))),
    )
    all_rows: list[dict[str, str]] = []
    parameter_identities = identities.get("parameters", {})
    level_identities = identities.get("levels", {})
    step_identities = identities.get("step_types", {})
    spatial_ids = set(geometry.get("spatial_contracts", {}))
    selector_ids: set[str] = set()

    for rows, product, expected_ids in expected:
        observed_ids = tuple(row.get("field_id", "") for row in rows)
        if observed_ids != expected_ids:
            raise RegistryContractError(f"{product} field IDs are not unique and contiguous")
        if tuple(int(row["ordinal"]) for row in rows) != tuple(range(1, len(rows) + 1)):
            raise RegistryContractError(f"{product} ordinals are not contiguous")
        for row in rows:
            field_id = row["field_id"]
            if row["schema_version"] != REGISTRY_SCHEMA_VERSION or row["product"] != product:
                raise RegistryContractError(f"registry identity changed for {field_id}")
            if not row["native_unit"] or not row["canonical_unit"] or not row["unit_conversion"]:
                raise RegistryContractError(f"unit contract is incomplete for {field_id}")
            if row["parameter_identity_id"] not in parameter_identities:
                raise RegistryContractError(f"parameter identity is unresolved for {field_id}")
            if row["parameter_identity_id"] != row["parameter"]:
                raise RegistryContractError(f"parameter selector and identity disagree for {field_id}")
            if row["level_identity_id"] not in level_identities:
                raise RegistryContractError(f"level identity is unresolved for {field_id}")
            parameter_identity = parameter_identities[row["parameter_identity_id"]]
            if not parameter_identity.get("aliases_normalized") and not parameter_identity.get(
                "grib2_codes"
            ):
                raise RegistryContractError(
                    f"allowed decoded parameter identities are empty for {field_id}"
                )
            level_identity = level_identities[row["level_identity_id"]]
            if level_identity.get("selector_text") != row["level"] or not level_identity.get(
                "allowed"
            ):
                raise RegistryContractError(
                    f"allowed decoded level identities are incomplete for {field_id}"
                )
            allowed_steps = step_identities.get(row["decoded_step_type"], {}).get(
                "aliases_normalized", []
            )
            if not allowed_steps:
                raise RegistryContractError(f"decoded step identity is unresolved for {field_id}")
            if row["spatial_contract_id"] not in spatial_ids:
                raise RegistryContractError(f"spatial contract is unresolved for {field_id}")
            acquisition = row["acquisition_contract_id"]
            if acquisition not in {"ARCHIVE_NETWORK_RANGE_V1", "ARCHIVE_GRID_STATIC_ONCE_V1"}:
                raise RegistryContractError(f"invalid acquisition contract for {field_id}")
            if any(token in acquisition for token in (",", ";", "|")):
                raise RegistryContractError(f"multiple acquisition contracts for {field_id}")
            selector_id = row["selector_contract_id"]
            if not selector_id or selector_id in selector_ids:
                raise RegistryContractError(f"selector contract is not unique for {field_id}")
            selector_ids.add(selector_id)
            interval_bounds(row, datetime(2021, 1, 1, 12, tzinfo=UTC))
            all_rows.append(row)

    by_id = {row["field_id"]: row for row in all_rows}
    if by_id["H14"]["acquisition_contract_id"] != "ARCHIVE_GRID_STATIC_ONCE_V1":
        raise RegistryContractError("H14 must use the static-grid acquisition contract")
    for field_id, row in by_id.items():
        if field_id != "H14" and row["acquisition_contract_id"] != "ARCHIVE_NETWORK_RANGE_V1":
            raise RegistryContractError(f"{field_id} must use normal network acquisition")
    for field_id in ("H16", "Q05"):
        if by_id[field_id]["acquisition_contract_id"] != "ARCHIVE_NETWORK_RANGE_V1":
            raise RegistryContractError(f"{field_id} is not a normal network acquisition")

    special_spatial = {
        "POINT_BI_TILE3_V1": {"H01", "H02", "H06", "H07", "H12"},
        "POINT_BI_NN_V1": {"H16", "Q05"},
        "POINT_BI_TILE9_DERIVE3_V1": {"H36", "Q01"},
        "POINT_NN_TILE9_V1": {"H38", "Q13"},
        "POINT_BI_TILE9_V1": {
            "H28", "H29", "H30", "H31", "H35", "H37", "H40", "H41", "H42",
            "H43", "H44", "Q02", "Q11", "Q12", "Q14",
        },
        "GRID_STATIC_ONCE_V1": {"H14"},
    }
    assigned_special = set().union(*special_spatial.values())
    expected_spatial = {
        field_id: contract
        for contract, field_ids in special_spatial.items()
        for field_id in field_ids
    }
    expected_spatial.update(
        {field_id: "POINT_BI_V1" for field_id in by_id if field_id not in assigned_special}
    )
    for field_id, expected_contract in expected_spatial.items():
        if by_id[field_id]["spatial_contract_id"] != expected_contract:
            raise RegistryContractError(f"spatial-support contract changed for {field_id}")

    exact_intervals = {
        "Q09": ("preceding_average", "avg", 5),
        "Q10": ("preceding_average", "avg", 5),
        "Q11": ("preceding_average", "avg", 15),
        "Q13": ("preceding_accumulation", "accum", 15),
        "H38": ("preceding_accumulation", "accum", 60),
    }
    interval_evidence: dict[str, Any] = {}
    valid = datetime(2021, 1, 1, 12, tzinfo=UTC)
    for field_id, contract in exact_intervals.items():
        row = by_id[field_id]
        observed = (
            row["interval_semantics"], row["decoded_step_type"], int(row["interval_minutes"])
        )
        if observed != contract:
            raise RegistryContractError(f"native interval contract changed for {field_id}")
        start, end = interval_bounds(row, valid)
        interval_evidence[field_id] = {
            "semantics": observed[0],
            "duration_minutes": observed[2],
            "test_start_utc": start.isoformat().replace("+00:00", "Z"),
            "test_end_utc": end.isoformat().replace("+00:00", "Z"),
        }
    for field_id, row in by_id.items():
        if field_id in exact_intervals:
            continue
        expected_semantics = "static_snapshot" if field_id == "H14" else "snapshot"
        if (
            row["interval_semantics"] != expected_semantics
            or row["decoded_step_type"] != "instant"
            or int(row["interval_minutes"]) != 0
        ):
            raise RegistryContractError(f"snapshot contract changed for {field_id}")

    return {
        "hourly_field_count": len(hourly),
        "subhourly_field_count": len(subhourly),
        "unique_selector_contract_count": len(selector_ids),
        "single_acquisition_contract_per_field": True,
        "normal_network_acquisitions": ["H16", "Q05"],
        "interval_contracts": interval_evidence,
    }


def _validate_coordinate_eras(root: Path) -> dict[str, Any]:
    path = root / "registries/station_coordinate_eras_v375.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected_ids = (
        "KDEN_COORD_19950228", "KDEN_COORD_20040105", "KDEN_COORD_20211122"
    )
    if tuple(row.get("station_coordinate_era_id") for row in rows) != expected_ids:
        raise RegistryContractError("station coordinate-era sequence changed")
    if rows[0]["effective_end"] != rows[1]["effective_start"]:
        raise RegistryContractError("first coordinate-era boundary is discontinuous")
    if rows[1]["effective_end"] != rows[2]["effective_start"]:
        raise RegistryContractError("second coordinate-era boundary is discontinuous")
    if rows[2]["effective_end"]:
        raise RegistryContractError("latest coordinate era must be open-ended")
    if any(row["station_id"] != "KDEN" for row in rows):
        raise RegistryContractError("coordinate registry contains another station")
    return {
        "coordinate_era_count": len(rows),
        "continuous_boundaries": True,
        "hrrrv4_coordinate_eras": expected_ids[1:],
    }


def _validate_geometry(geometry: Mapping[str, Any]) -> dict[str, Any]:
    if geometry.get("schema_version") != "KDEN_V375_GRID_GEOMETRY_V1":
        raise RegistryContractError("grid-geometry schema changed")
    grid = geometry.get("operational_grid", {})
    expected_grid = {
        "grid_geometry_id": "HRRR_CONUS_NATIVE_LAMBERT_V4",
        "nx": 1799,
        "ny": 1059,
        "dx_m": 3000,
        "dy_m": 3000,
        "scanning_mode": 64,
        "earth_shape_code": 6,
        "earth_radius_m": 6371229,
    }
    for key, value in expected_grid.items():
        if grid.get(key) != value:
            raise RegistryContractError(f"operational grid contract changed: {key}")
    if geometry.get("node_order") != ["SW", "SE", "NW", "NE"]:
        raise RegistryContractError("bilinear grid-node ordering changed")
    if geometry.get("tile_contract", {}).get("derived_3x3_slice") != [3, 6, 3, 6]:
        raise RegistryContractError("centered 3x3 derivation from 9x9 changed")
    weights = geometry.get("coordinate_era_extractions", {})
    for era in ("KDEN_COORD_20040105", "KDEN_COORD_20211122"):
        value = weights.get(era, {})
        nodes = value.get("bilinear_nodes", [])
        if len(nodes) != 4 or [node.get("order") for node in nodes] != ["SW", "SE", "NW", "NE"]:
            raise RegistryContractError(f"bilinear nodes changed for {era}")
        if abs(sum(float(node["weight"]) for node in nodes) - 1.0) > 1e-12:
            raise RegistryContractError(f"bilinear weights do not sum to one for {era}")
        nearest = value.get("nearest_node", {})
        if {nearest.get("i"), nearest.get("j")} - {696, 586, 587}:
            raise RegistryContractError(f"nearest-node indices are invalid for {era}")
    source_hashes = geometry.get("source_artifact_sha256", {})
    if len(source_hashes) < 5 or any(
        len(str(value)) != 64 for value in source_hashes.values()
    ):
        raise RegistryContractError("audited spatial source hashes are incomplete")
    return {
        "grid_geometry_id": grid["grid_geometry_id"],
        "operational_dimensions": [grid["ny"], grid["nx"]],
        "coordinate_era_extraction_count": len(weights),
        "bilinear_weight_tolerance": 1e-12,
        "nearest_node_rule": geometry["methods"]["nearest_node"]["rule"],
        "compact_tile_layout": geometry["tile_contract"]["layout"],
    }


def _validate_availability(root: Path) -> dict[str, Any]:
    path = root / "registries/availability_policies_v375.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise RegistryContractError("exactly one initial availability policy is required")
    row = rows[0]
    if (
        row.get("availability_policy_id") != "KDEN_HIST_COMPLETE_L105_V1"
        or row.get("products") != "wrfsfcf;wrfsubhf"
        or int(row.get("lag_minutes", "-1")) != 105
        or row.get("complete_rule") != "cycle_init_utc+105m"
    ):
        raise RegistryContractError("initial historical availability policy changed")
    return {
        "availability_policy_id": row["availability_policy_id"],
        "lag_minutes": int(row["lag_minutes"]),
        "products": row["products"].split(";"),
    }


def _validate_schemas(root: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for relative in SCHEMA_INPUTS:
        path = root / relative
        schema = _read_json(path)
        if schema.get("schema_version") != PARQUET_SCHEMA_VERSION:
            raise RegistryContractError(f"Parquet schema version changed: {path.name}")
        if schema.get("format") != "parquet" or schema.get("compression") != "zstd":
            raise RegistryContractError(f"physical storage contract changed: {path.name}")
        columns = schema.get("columns", [])
        names = [column.get("name") for column in columns]
        required = REQUIRED_SCHEMA_COLUMNS[path.name]
        if len(names) != len(set(names)) or any(name not in names for name in required):
            raise RegistryContractError(f"required columns are incomplete: {path.name}")
        for column in columns:
            if not column.get("name") or not column.get("arrow_type"):
                raise RegistryContractError(f"invalid column declaration: {path.name}")
            if not isinstance(column.get("nullable"), bool):
                raise RegistryContractError(f"nullable flag is not Boolean: {path.name}")
            if column["arrow_type"] not in ARROW_TYPE_NAMES:
                raise RegistryContractError(
                    f"unrecognized Arrow type declaration in {path.name}: {column['arrow_type']}"
                )
        evidence[path.name] = {
            "column_count": len(columns),
            "required_columns_present": True,
            "arrow_type_grammar_validated": True,
        }

    field_schema = _read_json(root / "schemas/hrrr_field_state_v375.json")
    fields = {column["name"]: column for column in field_schema["columns"]}
    if fields["tile_shape"]["arrow_type"] != "list<int16>":
        raise RegistryContractError("tile shape must be one compact two-element array")
    if fields["tile_values"]["arrow_type"] != "list<float64>":
        raise RegistryContractError("tile values must be one compact array")
    tile_rules = field_schema.get("row_rules", {}).get("compact_tile", {})
    if tile_rules.get("allowed_shapes") != [[3, 3], [9, 9]]:
        raise RegistryContractError("compact tile shapes changed")
    if tile_rules.get("length_rule") != "len(tile_values)=tile_shape[0]*tile_shape[1]":
        raise RegistryContractError("compact tile length rule changed")
    return evidence


def _scan_active_bundle_text(root: Path) -> dict[str, Any]:
    denied = ("REUSE" + "_L1", "MA" + "DIS", "truth" + " dependency")
    occurrences: list[str] = []
    for relative in BUNDLE_INPUTS:
        text = (root / relative).read_text(encoding="utf-8").casefold()
        for token in denied:
            if token.casefold() in text:
                occurrences.append(f"{relative}:{token}")
    if occurrences:
        raise RegistryContractError(
            "active registry bundle contains a forbidden dependency marker: "
            + ", ".join(occurrences)
        )
    return {"artifacts_scanned": len(BUNDLE_INPUTS), "forbidden_markers_found": 0}


def validate_registry_inputs(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    for relative in BUNDLE_INPUTS:
        if not (paths.root / relative).is_file():
            raise RegistryContractError(f"registry bundle input is missing: {relative}")
    identities = _read_json(paths.root / "registries/decoded_grib_identities_v375.json")
    if identities.get("schema_version") != "KDEN_V375_DECODED_GRIB_IDENTITIES_V1":
        raise RegistryContractError("decoded-GRIB identity schema changed")
    geometry = _read_json(paths.root / "registries/grid_geometry_v375.json")
    return {
        "field_registries": _validate_fields(paths.root, identities, geometry),
        "coordinate_eras": _validate_coordinate_eras(paths.root),
        "grid_geometry": _validate_geometry(geometry),
        "availability_policy": _validate_availability(paths.root),
        "parquet_schemas": _validate_schemas(paths.root),
        "dependency_isolation": _scan_active_bundle_text(paths.root),
    }


def seal_registry_bundle(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    evidence = validate_registry_inputs(paths.root)
    artifacts = [
        {
            "path": relative,
            "sha256": sha256_file(paths.root / relative),
            "size_bytes": (paths.root / relative).stat().st_size,
        }
        for relative in BUNDLE_INPUTS
    ]
    body = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "registry_version": "KDEN_V375_REGISTRY_BUNDLE_1_0_0",
        "artifacts": artifacts,
        "field_counts": {"wrfsfcf": 44, "wrfsubhf": 14, "total": 58},
        "source_policy": "provenance hashes only; active files are self-contained",
        "validation_summary": {
            "field_ids_unique_and_contiguous": True,
            "single_acquisition_contract_per_field": True,
            "native_interval_contracts_machine_testable": True,
            "forbidden_dependency_markers_found": 0,
        },
    }
    bundle = {**body, "bundle_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(paths.root / BUNDLE_PATH, bundle)
    return {"bundle": bundle, "gate_evidence": evidence}


def verify_registry_bundle(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    bundle = _read_json(paths.root / BUNDLE_PATH)
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise RegistryContractError("unsupported registry-bundle schema")
    body = dict(bundle)
    supplied = body.pop("bundle_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise RegistryContractError("registry-bundle content hash mismatch")
    expected_paths = list(BUNDLE_INPUTS)
    artifacts = bundle.get("artifacts", [])
    if [row.get("path") for row in artifacts] != expected_paths:
        raise RegistryContractError("registry-bundle artifact sequence changed")
    for row in artifacts:
        path = paths.root / row["path"]
        if sha256_file(path) != row.get("sha256") or path.stat().st_size != row.get("size_bytes"):
            raise RegistryContractError(f"registry-bundle artifact changed: {row['path']}")
    validation = validate_registry_inputs(paths.root)
    return {"bundle": bundle, "gate_evidence": validation}


def load_field_registry(project_root: Path | str, product: str) -> tuple[dict[str, str], ...]:
    """Return one validated active field registry for downstream planning."""

    paths = load_project_paths(project_root)
    verify_registry_bundle(paths.root)
    names = {
        "wrfsfcf": "registries/hrrr_hourly_v375.csv",
        "wrfsubhf": "registries/hrrr_subhourly_v375.csv",
    }
    try:
        relative = names[product]
    except KeyError as exc:
        raise RegistryContractError(f"unknown HRRR product: {product!r}") from exc
    return tuple(_read_csv(paths.root / relative))
