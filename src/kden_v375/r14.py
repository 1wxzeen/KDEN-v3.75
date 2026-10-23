"""Versioned R14 field and regional-spatial acquisition contracts.

The historical 58-identity registries remain immutable selector catalogs.  This
module validates the owner-selected sparse R14 overlay, resolves its map-aware
regional supports, and seals successor artifacts without modifying v1 inputs.
"""

from __future__ import annotations

import csv
import json
import math
import tomllib
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractError, load_project_paths, validate_runtime_isolation
from .hashes import canonical_json_bytes, sha256_bytes, sha256_file
from .io.atomic import atomic_write_json
from .io.grib import LambertGrid, bilinear_indices_and_weights, grid_fraction
from .registries import load_field_registry, verify_registry_bundle


R14_SCOPE_SCHEMA_VERSION = "KDEN_V375_R14_ACQUISITION_SCOPE_V1"
R14_SCOPE_ID = "KDEN_V375_R14_V1"
R14_SPATIAL_SCHEMA_VERSION = "KDEN_V375_R14_SPATIAL_CONTRACT_V1"
R14_SPATIAL_CONTRACT_ID = "KDEN_V375_R14_REGIONAL_SPATIAL_V1"
R14_SPATIAL_GEOMETRY_SCHEMA_VERSION = "KDEN_V375_R14_SPATIAL_GEOMETRY_V1"
R14_BUNDLE_SCHEMA_VERSION = "KDEN_V375_R14_REGISTRY_BUNDLE_V1"

R14_SCOPE_PATH = "config/r14_acquisition_v375.json"
R14_SPATIAL_CONTRACT_PATH = "config/r14_spatial_contract_v375.json"
R14_FIELD_STATE_SCHEMA_PATH = "schemas/hrrr_field_state_r14_v375.json"
R14_SPATIAL_GEOMETRY_PATH = "registries/r14_spatial_geometry_v375.json"
R14_BUNDLE_PATH = "registries/registry_bundle_r14_v375.json"

R14_DYNAMIC_HOURLY = (
    "H02", "H07", "H16", "H17", "H18", "H19",
    "H24", "H26", "H28", "H31", "H36", "H38",
)
R14_STATIC_HOURLY = ("H14",)
R14_SUBHOURLY = ("Q05",)
R14_ALL_IDS = frozenset(R14_DYNAMIC_HOURLY + R14_STATIC_HOURLY + R14_SUBHOURLY)
EXPECTED_SUPPORT_ORDER = (
    "WEST_FOOTHILL_D030",
    "WEST_FOOTHILL_D060",
    "NNE_PLAINS_D030",
    "NNE_PLAINS_D060",
    "EAST_PLAINS_D030",
    "EAST_PLAINS_D060",
    "SSE_PALMER_D030",
    "SSE_PALMER_D060",
)
EXPECTED_FIELD_OPERATORS = {
    "BILINEAR_AT_EIGHT_SUPPORTS": {
        "H16", "H17", "H18", "H19", "H24", "H26", "H28", "H31", "Q05"
    },
    "NEAREST_AT_EIGHT_SUPPORTS": {"H36", "H38"},
    "STATIC_TERRAIN_BILINEAR_AT_EIGHT_SUPPORTS": {"H14"},
    "LOCAL_BASELINE_ONLY_NO_REGIONAL_SUPPORT": {"H02", "H07"},
}


class R14ContractError(ContractError):
    """An R14 scope, field, spatial, or successor-bundle contract failed."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise R14ContractError(f"JSON contract must contain an object: {path}")
    return value


def _catalog_ids(rows: tuple[dict[str, str], ...]) -> set[str]:
    return {row["field_id"] for row in rows}


def _active_ids(scope: Mapping[str, Any], product: str) -> tuple[str, ...]:
    product_scope = scope["field_universe"][product]
    selected = set(product_scope["dynamic"]) | set(product_scope["static"])
    catalog = load_field_registry(scope["_project_root"], product)
    return tuple(row["field_id"] for row in catalog if row["field_id"] in selected)


def load_r14_scope(project_root: Path | str) -> dict[str, Any]:
    """Load and fail-closed validate the machine-readable R14 overlay."""

    paths = load_project_paths(project_root)
    scope = _read_json(paths.root / R14_SCOPE_PATH)
    if (
        scope.get("schema_version") != R14_SCOPE_SCHEMA_VERSION
        or scope.get("scope_id") != R14_SCOPE_ID
    ):
        raise R14ContractError("unsupported R14 acquisition scope identity")
    with paths.config.open("rb") as stream:
        project = tomllib.load(stream)
    project_section = project.get("project", {})
    if project_section.get("active_acquisition_scope_id") != R14_SCOPE_ID:
        raise R14ContractError("project configuration does not activate R14")
    if project_section.get("active_acquisition_scope") != R14_SCOPE_PATH:
        raise R14ContractError("project configuration points to another scope file")

    fields = scope.get("field_universe", {})
    hourly = fields.get("wrfsfcf", {})
    subhourly = fields.get("wrfsubhf", {})
    if tuple(hourly.get("dynamic", ())) != R14_DYNAMIC_HOURLY:
        raise R14ContractError("R14 dynamic hourly identity sequence changed")
    if tuple(hourly.get("static", ())) != R14_STATIC_HOURLY:
        raise R14ContractError("R14 static hourly identity sequence changed")
    if tuple(subhourly.get("dynamic", ())) != R14_SUBHOURLY or subhourly.get("static") != []:
        raise R14ContractError("R14 subhourly identity sequence changed")
    if int(fields.get("retained_identity_count_including_static", -1)) != len(R14_ALL_IDS):
        raise R14ContractError("R14 retained identity count changed")

    hourly_catalog = load_field_registry(paths.root, "wrfsfcf")
    subhourly_catalog = load_field_registry(paths.root, "wrfsubhf")
    retained_hourly = set(R14_DYNAMIC_HOURLY + R14_STATIC_HOURLY)
    retained_subhourly = set(R14_SUBHOURLY)
    excluded_hourly = set(hourly.get("excluded", ()))
    excluded_subhourly = set(subhourly.get("excluded", ()))
    if retained_hourly & excluded_hourly or retained_subhourly & excluded_subhourly:
        raise R14ContractError("an R14 identity is both retained and excluded")
    if retained_hourly | excluded_hourly != _catalog_ids(hourly_catalog):
        raise R14ContractError("R14 hourly retained/excluded partition is incomplete")
    if retained_subhourly | excluded_subhourly != _catalog_ids(subhourly_catalog):
        raise R14ContractError("R14 subhourly retained/excluded partition is incomplete")
    if set(scope.get("baseline_spatial_contract_by_field", {})) != R14_ALL_IDS:
        raise R14ContractError("R14 baseline spatial mapping does not cover exactly R14")

    schedule = scope.get("schedule", {})
    if not schedule.get("window_end_is_exclusive") or not schedule.get(
        "r14_schedule_rebuild_required"
    ):
        raise R14ContractError("R14 must use a rebuilt right-open schedule")
    counts = scope.get("request_accounting_expectation", {})
    hourly_expected = (
        int(counts.get("wrfsfcf_dynamic_native_state_count", -1))
        * len(R14_DYNAMIC_HOURLY)
        + int(counts.get("wrfsfcf_static_request_count", -1))
    )
    if hourly_expected != int(counts.get("wrfsfcf_logical_request_count", -2)):
        raise R14ContractError("R14 hourly request accounting is internally inconsistent")
    combined = int(counts.get("wrfsfcf_logical_request_count", -1)) + int(
        counts.get("wrfsubhf_logical_request_count", -1)
    )
    if combined != int(counts.get("combined_logical_request_count", -2)):
        raise R14ContractError("R14 combined request accounting is internally inconsistent")
    execution = scope.get("execution", {})
    if (
        execution.get("owner_facing_step") != 5
        or execution.get("phase_order") != ["WRFSFCF_R14", "WRFSUBHF_Q05_R14"]
        or execution.get("shared_max_download_workers") != 8
    ):
        raise R14ContractError("R14 unified execution contract changed")
    for relative in scope.get("successor_lineage", {}).get(
        "historical_not_r14_authorization", []
    ):
        if not (paths.root / relative).exists():
            raise R14ContractError(f"historical R14 lineage artifact is missing: {relative}")
    return {**scope, "_project_root": paths.root}


def load_r14_field_registry(
    project_root: Path | str, product: str
) -> tuple[dict[str, str], ...]:
    """Return only active R14 rows, in original catalog ordinal order."""

    scope = load_r14_scope(project_root)
    if product not in {"wrfsfcf", "wrfsubhf"}:
        raise R14ContractError(f"unsupported R14 product: {product!r}")
    selected = set(_active_ids(scope, product))
    rows = tuple(
        row for row in load_field_registry(project_root, product)
        if row["field_id"] in selected
    )
    expected_count = 13 if product == "wrfsfcf" else 1
    if len(rows) != expected_count or {row["field_id"] for row in rows} != selected:
        raise R14ContractError(f"R14 {product} registry selection changed")
    return rows


def _grid_from_registry(value: Mapping[str, Any]) -> LambertGrid:
    grid = value["operational_grid"]
    return LambertGrid(
        grid_id=str(grid["grid_geometry_id"]),
        nx=int(grid["nx"]),
        ny=int(grid["ny"]),
        latitude_first_deg=float(grid["latitude_first_deg"]),
        longitude_first_deg=float(grid["longitude_first_deg_east"]),
        lov_deg=float(grid["lov_deg_east"]),
        latin1_deg=float(grid["latin1_deg"]),
        latin2_deg=float(grid["latin2_deg"]),
        lad_deg=float(grid["lad_deg"]),
        dx_m=float(grid["dx_m"]),
        dy_m=float(grid["dy_m"]),
        earth_radius_m=float(grid["earth_radius_m"]),
        scanning_mode=int(grid["scanning_mode"]),
        i_scans_negatively=False,
        j_scans_positively=True,
        j_points_are_consecutive=False,
        alternative_row_scanning=False,
    )


def _destination(
    latitude_deg: float,
    longitude_deg: float,
    bearing_deg: float,
    distance_m: float,
    radius_m: float,
) -> tuple[float, float]:
    phi1 = math.radians(latitude_deg)
    lambda1 = math.radians(longitude_deg)
    theta = math.radians(bearing_deg)
    delta = distance_m / radius_m
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta)
        + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    longitude = (math.degrees(lambda2) + 180.0) % 360.0 - 180.0
    return math.degrees(phi2), longitude


def _great_circle_distance(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
    radius_m: float,
) -> float:
    phi_a, phi_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2.0) ** 2
    )
    return radius_m * 2.0 * math.atan2(math.sqrt(value), math.sqrt(1.0 - value))


def _station_eras(project_root: Path) -> tuple[dict[str, str], ...]:
    path = project_root / "registries/station_coordinate_eras_v375.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = tuple(dict(row) for row in csv.DictReader(stream))
    required = ("KDEN_COORD_20040105", "KDEN_COORD_20211122")
    selected = tuple(row for row in rows if row["station_coordinate_era_id"] in required)
    if tuple(row["station_coordinate_era_id"] for row in selected) != required:
        raise R14ContractError("R14 coordinate-era sequence changed")
    return selected


def _load_spatial_contract(project_root: Path) -> dict[str, Any]:
    value = _read_json(project_root / R14_SPATIAL_CONTRACT_PATH)
    if (
        value.get("schema_version") != R14_SPATIAL_SCHEMA_VERSION
        or value.get("contract_id") != R14_SPATIAL_CONTRACT_ID
        or value.get("status") != "SEALED_FOR_R14_CONFIRMATION_PILOT"
        or not value.get("confirmation_pilot_authorized")
        or value.get("full_history_authorized")
    ):
        raise R14ContractError("R14 spatial contract has an invalid lifecycle state")
    if tuple(value.get("support_order", ())) != EXPECTED_SUPPORT_ORDER:
        raise R14ContractError("R14 regional support order changed")
    observed_operators = {
        name: set(field_ids) for name, field_ids in value.get("field_operators", {}).items()
    }
    if observed_operators != EXPECTED_FIELD_OPERATORS:
        raise R14ContractError("R14 field-to-regional-operator mapping changed")
    if set().union(*observed_operators.values()) != R14_ALL_IDS:
        raise R14ContractError("R14 regional operator mapping is incomplete")
    coordinate = value.get("coordinate_basis", {})
    if (
        coordinate.get("method")
        != "SPHERICAL_GEODESIC_DESTINATION_THEN_HRRR_LAMBERT_PROJECTION"
        or float(coordinate.get("earth_radius_m", 0.0)) != 6_371_229.0
    ):
        raise R14ContractError("R14 map-aware displacement contract changed")
    storage = value.get("storage", {})
    if storage.get("schema_path") != R14_FIELD_STATE_SCHEMA_PATH:
        raise R14ContractError("R14 spatial storage schema changed")
    schema = _read_json(project_root / R14_FIELD_STATE_SCHEMA_PATH)
    names = [column.get("name") for column in schema.get("columns", [])]
    expected_values = [f"regional_value_{index:02d}" for index in range(8)]
    if storage.get("support_value_columns") != expected_values:
        raise R14ContractError("R14 regional value-column order changed")
    if any(name not in names for name in expected_values):
        raise R14ContractError("R14 field-state schema lacks regional value columns")
    return value


def resolve_r14_spatial_geometry(project_root: Path | str) -> dict[str, Any]:
    """Resolve exact era-specific grid nodes from the sealed bearing/distance inputs."""

    paths = load_project_paths(project_root)
    load_r14_scope(paths.root)
    contract = _load_spatial_contract(paths.root)
    geometry_source = _read_json(paths.root / "registries/grid_geometry_v375.json")
    grid = _grid_from_registry(geometry_source)
    radius = float(contract["coordinate_basis"]["earth_radius_m"])
    definitions: dict[str, tuple[str, float, float]] = {}
    for sector in contract["sectors"]:
        for distance_km in sector["distances_km"]:
            support_id = f"{sector['support_prefix']}_D{int(distance_km):03d}"
            definitions[support_id] = (
                str(sector["sector_id"]),
                float(sector["bearing_degrees"]),
                float(distance_km) * 1000.0,
            )
    if tuple(definitions) != EXPECTED_SUPPORT_ORDER:
        raise R14ContractError("R14 sector declarations do not produce frozen support order")

    eras: dict[str, list[dict[str, Any]]] = {}
    tolerance = float(contract["validation"]["distance_absolute_tolerance_m"])
    for station in _station_eras(paths.root):
        era_id = station["station_coordinate_era_id"]
        station_latitude = float(station["latitude_deg"])
        station_longitude = float(station["longitude_deg"])
        supports: list[dict[str, Any]] = []
        for index, support_id in enumerate(EXPECTED_SUPPORT_ORDER):
            sector_id, bearing, distance_m = definitions[support_id]
            latitude, longitude = _destination(
                station_latitude, station_longitude, bearing, distance_m, radius
            )
            distance_check = _great_circle_distance(
                station_latitude, station_longitude, latitude, longitude, radius
            )
            if abs(distance_check - distance_m) > tolerance:
                raise R14ContractError(f"geodesic displacement failed for {era_id}/{support_id}")
            fraction_i, fraction_j = grid_fraction(grid, latitude, longitude)
            nearest_i = math.floor(fraction_i + 0.5)
            nearest_j = math.floor(fraction_j + 0.5)
            nodes, weights = bilinear_indices_and_weights(
                fraction_i, fraction_j, grid.nx, grid.ny
            )
            if not (0 <= nearest_i < grid.nx and 0 <= nearest_j < grid.ny):
                raise R14ContractError(f"regional support leaves HRRR grid: {era_id}/{support_id}")
            supports.append(
                {
                    "support_index": index,
                    "support_id": support_id,
                    "sector_id": sector_id,
                    "bearing_degrees": bearing,
                    "distance_m": distance_m,
                    "target_latitude_deg": round(latitude, 12),
                    "target_longitude_deg": round(longitude, 12),
                    "grid_fraction_i": round(fraction_i, 12),
                    "grid_fraction_j": round(fraction_j, 12),
                    "nearest_node": {"i": nearest_i, "j": nearest_j},
                    "bilinear_nodes": [
                        {
                            "order": order,
                            "i": node[0],
                            "j": node[1],
                            "weight": round(weight, 15),
                        }
                        for order, node, weight in zip(
                            ("SW", "SE", "NW", "NE"), nodes, weights, strict=True
                        )
                    ],
                }
            )
        eras[era_id] = supports

    body = {
        "schema_version": R14_SPATIAL_GEOMETRY_SCHEMA_VERSION,
        "scope_id": R14_SCOPE_ID,
        "spatial_contract_id": R14_SPATIAL_CONTRACT_ID,
        "grid_geometry_id": grid.grid_id,
        "support_order": list(EXPECTED_SUPPORT_ORDER),
        "coordinate_era_supports": eras,
        "source_sha256": {
            R14_SPATIAL_CONTRACT_PATH: sha256_file(paths.root / R14_SPATIAL_CONTRACT_PATH),
            "registries/grid_geometry_v375.json": sha256_file(
                paths.root / "registries/grid_geometry_v375.json"
            ),
            "registries/station_coordinate_eras_v375.csv": sha256_file(
                paths.root / "registries/station_coordinate_eras_v375.csv"
            ),
        },
    }
    return {**body, "geometry_sha256": sha256_bytes(canonical_json_bytes(body))}


def validate_r14_spatial_contract(project_root: Path | str) -> dict[str, Any]:
    """Validate inputs and resolved nodes without publishing anything."""

    paths = load_project_paths(project_root)
    contract = _load_spatial_contract(paths.root)
    geometry = resolve_r14_spatial_geometry(paths.root)
    tolerance = float(contract["validation"]["bilinear_weight_sum_tolerance"])
    for era_id, supports in geometry["coordinate_era_supports"].items():
        if len(supports) != 8:
            raise R14ContractError(f"R14 support count changed for {era_id}")
        for support in supports:
            weights = [node["weight"] for node in support["bilinear_nodes"]]
            if abs(sum(weights) - 1.0) > tolerance:
                raise R14ContractError(f"R14 weights do not sum to one: {era_id}")
    return {
        "contract_id": contract["contract_id"],
        "support_order": list(EXPECTED_SUPPORT_ORDER),
        "coordinate_era_count": len(geometry["coordinate_era_supports"]),
        "support_count_per_era": 8,
        "resolved_geometry_sha256": geometry["geometry_sha256"],
        "regional_fields_by_operator": {
            key: sorted(value) for key, value in EXPECTED_FIELD_OPERATORS.items()
        },
        "isobaric_regional_sampling": "FORBIDDEN_V1",
        "full_history_authorized": False,
        "confirmation_pilot_authorized": True,
    }


def _publish_deterministic_json(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists():
        existing = _read_json(path)
        if canonical_json_bytes(existing) != canonical_json_bytes(value):
            raise R14ContractError(f"immutable R14 artifact differs: {path}")
        return sha256_file(path)
    return atomic_write_json(path, value, replace=False)


def seal_r14_registry_bundle(project_root: Path | str) -> dict[str, Any]:
    """Publish resolved spatial geometry and the content-addressed R14 bundle."""

    paths = load_project_paths(project_root)
    scope = load_r14_scope(paths.root)
    spatial_evidence = validate_r14_spatial_contract(paths.root)
    geometry = resolve_r14_spatial_geometry(paths.root)
    geometry_path = paths.root / R14_SPATIAL_GEOMETRY_PATH
    _publish_deterministic_json(geometry_path, geometry)
    historical = verify_registry_bundle(paths.root)["bundle"]
    active_fields = {
        product: list(load_r14_field_registry(paths.root, product))
        for product in ("wrfsfcf", "wrfsubhf")
    }
    inputs = (
        R14_SCOPE_PATH,
        R14_SPATIAL_CONTRACT_PATH,
        R14_FIELD_STATE_SCHEMA_PATH,
        R14_SPATIAL_GEOMETRY_PATH,
        "registries/hrrr_hourly_v375.csv",
        "registries/hrrr_subhourly_v375.csv",
        "registries/decoded_grib_identities_v375.json",
        "registries/grid_geometry_v375.json",
        "registries/station_coordinate_eras_v375.csv",
        "registries/availability_policies_v375.csv",
    )
    artifacts = [
        {
            "path": relative,
            "sha256": sha256_file(paths.root / relative),
            "size_bytes": (paths.root / relative).stat().st_size,
        }
        for relative in inputs
    ]
    body = {
        "schema_version": R14_BUNDLE_SCHEMA_VERSION,
        "scope_id": R14_SCOPE_ID,
        "registry_version": "KDEN_V375_R14_REGISTRY_BUNDLE_1_0_0",
        "historical_registry_bundle_sha256": historical["bundle_sha256"],
        "artifacts": artifacts,
        "active_fields": active_fields,
        "field_counts": {"wrfsfcf": 13, "wrfsubhf": 1, "total": 14},
        "excluded_fields": {
            product: scope["field_universe"][product]["excluded"]
            for product in ("wrfsfcf", "wrfsubhf")
        },
        "spatial_validation": spatial_evidence,
        "runtime_isolation": validate_runtime_isolation(paths.root),
        "source_policy": "historical catalogs are selector provenance; only active_fields are plannable",
    }
    bundle = {**body, "bundle_sha256": sha256_bytes(canonical_json_bytes(body))}
    _publish_deterministic_json(paths.root / R14_BUNDLE_PATH, bundle)
    return {"bundle": bundle, "gate_evidence": spatial_evidence}


def verify_r14_registry_bundle(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    bundle = _read_json(paths.root / R14_BUNDLE_PATH)
    if bundle.get("schema_version") != R14_BUNDLE_SCHEMA_VERSION:
        raise R14ContractError("unsupported R14 registry-bundle schema")
    body = dict(bundle)
    supplied = body.pop("bundle_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise R14ContractError("R14 registry-bundle content hash mismatch")
    for artifact in bundle.get("artifacts", []):
        path = paths.root / artifact["path"]
        if (
            sha256_file(path) != artifact.get("sha256")
            or path.stat().st_size != artifact.get("size_bytes")
        ):
            raise R14ContractError(f"R14 bundle artifact changed: {artifact['path']}")
    expected_fields = {
        product: list(load_r14_field_registry(paths.root, product))
        for product in ("wrfsfcf", "wrfsubhf")
    }
    if bundle.get("active_fields") != expected_fields:
        raise R14ContractError("R14 active field rows changed")
    geometry = _read_json(paths.root / R14_SPATIAL_GEOMETRY_PATH)
    if geometry != resolve_r14_spatial_geometry(paths.root):
        raise R14ContractError("resolved R14 spatial geometry changed")
    return {"bundle": bundle, "gate_evidence": validate_r14_spatial_contract(paths.root)}
