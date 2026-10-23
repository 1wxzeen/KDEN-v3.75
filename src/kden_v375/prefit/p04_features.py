"""P04: freeze and bounded-test deterministic, target-free R14 features."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..archive_readers import R14ArchiveReader, load_issue_view_contract
from ..contracts import ContractError, StaleStateError, validate_runtime_isolation
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_file
from ..io.atomic import atomic_write_bytes, atomic_write_json
from ..time import as_utc
from .p03_issue_spine import ISSUE_OUTPUT_PATH, SELECTION_OUTPUT_PATH
from .records import verify_prefit_pass, write_prefit_pass


STAGE_NO = 4
CONFIG_PATH = "config/prefit/p04_features_v375.json"
REGISTRY_SCHEMA_PATH = "schemas/prefit/p04_feature_registry_v375.json"
PANEL_SCHEMA_PATH = "schemas/prefit/deterministic_feature_panel_v375.json"
REGISTRY_PATH = (
    "universal_issue_state/v1/registries/universal_feature_registry_v1.json"
)
REPORT_PATH = "reports/prefit/P04_UNIVERSAL_FEATURE_CONTRACT_REPORT.md"
RUNBOOK_PATH = "reports/prefit/P04_OWNER_RUNBOOK.md"
PASS_PATH = "state/PREFIT_P04_PASS.json"
H14_TERRAIN_SUPPORTS_PATH = (
    "hrrr_v4_local_archive/common/static_geometry/"
    "grid_geometry_id=HRRR_CONUS_NATIVE_LAMBERT_V4/field=H14/"
    "_h14_terrain_supports.json"
)

CONFIG_SCHEMA = "KDEN_V375_PREFIT_P04_CONFIG_V1"
REGISTRY_ID = "KDEN_V375_UNIVERSAL_FEATURE_REGISTRY_V1"
PANEL_SCHEMA_ID = "KDEN_V375_DETERMINISTIC_FEATURE_PANEL_V1"
DERIVATION_ID = "KDEN_V375_DETERMINISTIC_FEATURES_V1"
EXPECTED_P03_SHA256 = (
    "c1201500ecfd5ed6eac60d45889c4b7ecdd2620c76998c00a1769531c9479f3b"
)

SNAPSHOT_FIELDS = (
    "H02",
    "H07",
    "H16",
    "H17",
    "H18",
    "H19",
    "H24",
    "H26",
    "H28",
    "H31",
    "H36",
    "Q05",
)
ACCUMULATION_FIELDS = ("H38",)
DYNAMIC_FIELDS = SNAPSHOT_FIELDS + ACCUMULATION_FIELDS
FIELD_PRODUCT = {**{field: "wrfsfcf" for field in DYNAMIC_FIELDS}, "Q05": "wrfsubhf"}
FIELD_PRODUCT["Q05"] = "wrfsubhf"
LOCAL_VALUE_COLUMN = {field: "bi_value" for field in SNAPSHOT_FIELDS}
LOCAL_VALUE_COLUMN["H38"] = "nn_value"
FIELD_UNITS = {
    "H02": "K",
    "H07": "K",
    "H14": "m",
    "H16": "K",
    "H17": "K",
    "H18": "m s-1",
    "H19": "m s-1",
    "H24": "m",
    "H26": "%",
    "H28": "%",
    "H31": "W m-2",
    "H36": "dBZ",
    "H38": "kg m-2",
    "Q05": "K",
}
REGIONAL_FIELDS = (
    "H16",
    "H17",
    "H18",
    "H19",
    "H24",
    "H26",
    "H28",
    "H31",
    "H36",
    "H38",
    "Q05",
)
TILE_FIELDS = ("H02", "H07", "H28", "H31", "H36", "H38")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ContractError(f"JSON object expected: {path}")
    return value


def _stable_isolation_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "source_files_scanned"}


def _load_config(root: Path) -> dict[str, Any]:
    config = _read_json(root / CONFIG_PATH)
    if config.get("schema_version") != CONFIG_SCHEMA:
        raise ContractError("unsupported P04 configuration schema")
    if (
        config.get("registry_id") != REGISTRY_ID
        or config.get("panel_schema_id") != PANEL_SCHEMA_ID
        or config.get("derivation_id") != DERIVATION_ID
        or config.get("predecessor_p03_record_sha256") != EXPECTED_P03_SHA256
    ):
        raise ContractError("P04 identity or predecessor changed")
    execution = config.get("execution", {})
    if execution != {
        "network_allowed": False,
        "truth_reads_allowed": False,
        "full_history_materialization_allowed": False,
        "model_fitting_allowed": False,
        "bounded_archive_cases_only": True,
    }:
        raise ContractError("P04 execution boundary changed")
    if config.get("aggregate_missingness", {}).get("primary_policy") != (
        "STRICT_COMPLETE_SUPPORT"
    ):
        raise ContractError("P04 aggregate missingness must fail closed")
    return config


def _predecessor(root: Path) -> dict[str, Any]:
    record = verify_prefit_pass(root, 3)
    if record.get("record_sha256") != EXPECTED_P03_SHA256:
        raise StaleStateError("P04 requires the accepted P03 issue-state release")
    return record


def _feature(
    *,
    name: str,
    family: str,
    operator: str,
    source_fields: Sequence[str],
    product: str | None,
    spatial_support: str,
    window_id: str,
    unit: str,
    dtype: str = "float64",
    physical_range: Sequence[float | int] | None,
    null_policy: str = "NULL_UNLESS_COMPLETE_DECLARED_SUPPORT",
    alignment_id: str = "ONE_SELECTED_CYCLE",
    description: str,
) -> dict[str, Any]:
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in name):
        raise ContractError(f"invalid deterministic feature name: {name!r}")
    semantic = {
        "name": name,
        "family": family,
        "operator": operator,
        "source_fields": list(source_fields),
        "product": product,
        "spatial_support": spatial_support,
        "window_id": window_id,
        "unit": unit,
        "dtype": dtype,
        "physical_range": None if physical_range is None else list(physical_range),
        "null_policy": null_policy,
        "alignment_id": alignment_id,
        "description": description,
    }
    return {
        "feature_id": "FEATURE_" + sha256_bytes(canonical_json_bytes(semantic)),
        **semantic,
    }


def _field_range(config: Mapping[str, Any], field: str) -> tuple[float, float]:
    values = config["physical_ranges"][field]
    return float(values[0]), float(values[1])


def build_feature_registry(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the ordered, closed V1 deterministic feature universe."""

    features: list[dict[str, Any]] = []

    def add(**kwargs: Any) -> None:
        features.append(_feature(**kwargs))

    clock_specs = (
        ("clock_issue_minutes_since_0200", "IDENTITY", "min", "int16", [0, 840]),
        ("clock_issue_time_sin", "CYCLIC_SIN", "1", "float64", [-1.0, 1.0]),
        ("clock_issue_time_cos", "CYCLIC_COS", "1", "float64", [-1.0, 1.0]),
        ("clock_target_doy_sin", "CYCLIC_SIN", "1", "float64", [-1.0, 1.0]),
        ("clock_target_doy_cos", "CYCLIC_COS", "1", "float64", [-1.0, 1.0]),
        ("clock_local_dst_flag", "IDENTITY", "binary", "bool", [0, 1]),
    )
    for name, operator, unit, dtype, bounds in clock_specs:
        add(
            name=name,
            family="clock",
            operator=operator,
            source_fields=(),
            product=None,
            spatial_support="NONE",
            window_id="ASOF",
            unit=unit,
            dtype=dtype,
            physical_range=bounds,
            null_policy="NEVER_NULL_FROM_P03_ISSUE_SPINE",
            alignment_id="P03_ISSUE_STATE",
            description="Deterministic issue-state clock encoding.",
        )
    for product in ("wrfsfcf", "wrfsubhf"):
        for suffix in (
            "cycle_age_minutes",
            "availability_age_minutes",
            "previous_cycle_age_minutes",
            "previous_availability_age_minutes",
        ):
            add(
                name=f"clock_{product}_{suffix}",
                family="clock",
                operator="IDENTITY",
                source_fields=(),
                product=product,
                spatial_support="NONE",
                window_id="ASOF",
                unit="min",
                dtype="int32",
                physical_range=[0, 2880],
                null_policy="NULL_IF_P03_SELECTION_IS_ABSENT",
                alignment_id="P03_SELECTED_CYCLE",
                description="Age of the independently selected legal product cycle.",
            )
        for suffix, description in (
            ("retained_start_offset_minutes", "Selected path start relative to the target-window start."),
            ("retained_end_offset_minutes", "Selected path end relative to the target-window start; the target-window right boundary remains excluded."),
            ("retained_span_minutes", "Physical span from first through last retained valid time."),
            ("remaining_horizon_minutes", "Physical minutes from issue time to the selected path's retained end, floored at zero."),
        ):
            add(
                name=f"support_{product}_{suffix}",
                family="trajectory_support",
                operator="TIME_SUPPORT",
                source_fields=(),
                product=product,
                spatial_support="NONE",
                window_id="RETAINED",
                unit="min",
                dtype="int32",
                physical_range=[0, 1440],
                null_policy="NULL_IF_P03_SELECTION_SUPPORT_IS_ABSENT",
                alignment_id="P03_SELECTED_CYCLE",
                description=description,
            )

    for field in SNAPSHOT_FIELDS:
        unit = FIELD_UNITS[field]
        low, high = _field_range(config, field)
        stem = field.lower()
        product = FIELD_PRODUCT[field]
        base = dict(
            family="trajectory",
            source_fields=(field,),
            product=product,
            spatial_support="KDEN_LOCAL_CONTRACT_VALUE",
            unit=unit,
            alignment_id="ONE_SELECTED_CYCLE",
        )
        for suffix, operator, window, bounds, description in (
            ("asof_value", "LAST_AT_OR_BEFORE", "ASOF", [low, high], "Latest non-interpolated retained snapshot at or before issue time."),
            ("future_first_value", "FIRST_AT_OR_AFTER", "FUTURE_FIRST", [low, high], "First non-interpolated retained snapshot at or after issue time."),
            ("retained_min", "MIN", "RETAINED", [low, high], "Minimum across the selected cycle's retained target-window path."),
            ("retained_max", "MAX", "RETAINED", [low, high], "Maximum across the selected cycle's retained target-window path."),
            ("retained_mean", "MEAN", "RETAINED", [low, high], "Arithmetic mean across the selected cycle's retained target-window path."),
            ("retained_range", "RANGE", "RETAINED", [0.0, high - low], "Maximum minus minimum over retained support."),
            ("remaining_min", "MIN", "REMAINING", [low, high], "Minimum over retained snapshots not earlier than issue time."),
            ("remaining_max", "MAX", "REMAINING", [low, high], "Maximum over retained snapshots not earlier than issue time."),
            ("remaining_mean", "MEAN", "REMAINING", [low, high], "Arithmetic mean over retained snapshots not earlier than issue time."),
            ("remaining_range", "RANGE", "REMAINING", [0.0, high - low], "Maximum minus minimum over remaining support."),
            ("remaining_endpoint_slope_per_hour", "ENDPOINT_SLOPE", "REMAINING", [-(high - low), high - low], "Last minus first remaining snapshot divided by elapsed hours."),
        ):
            add(
                name=f"{stem}_local_{suffix}",
                operator=operator,
                window_id=window,
                physical_range=bounds,
                null_policy=(
                    "NULL_IF_SELECTED_ROW_MISSING"
                    if window in {"ASOF", "FUTURE_FIRST"}
                    else "NULL_UNLESS_ALL_DECLARED_WINDOW_ROWS_PRESENT"
                ),
                description=description,
                **base,
            )
        for suffix, window in (("asof_offset_minutes", "ASOF"), ("future_first_offset_minutes", "FUTURE_FIRST")):
            add(
                name=f"{stem}_local_{suffix}",
                family="trajectory",
                operator="TIME_OFFSET",
                source_fields=(field,),
                product=product,
                spatial_support="KDEN_LOCAL_CONTRACT_VALUE",
                window_id=window,
                unit="min",
                dtype="int32",
                physical_range=[0, 1440],
                null_policy="NULL_IF_ANCHOR_ROW_IS_ABSENT",
                alignment_id="ONE_SELECTED_CYCLE",
                description="Absolute issue-to-anchor valid-time offset; no interpolation.",
            )
        for window in ("retained", "remaining"):
            add(
                name=f"{stem}_local_{window}_coverage_fraction",
                family="missingness",
                operator="COVERAGE_FRACTION",
                source_fields=(field,),
                product=product,
                spatial_support="KDEN_LOCAL_CONTRACT_VALUE",
                window_id=window.upper(),
                unit="1",
                physical_range=[0.0, 1.0],
                null_policy="ZERO_WHEN_WINDOW_HAS_ROWS_BUT_NONE_PRESENT",
                alignment_id="ONE_SELECTED_CYCLE",
                description="Present rows divided by declared rows in the feature window.",
            )
            add(
                name=f"{stem}_local_{window}_missing_count",
                family="missingness",
                operator="MISSING_COUNT",
                source_fields=(field,),
                product=product,
                spatial_support="KDEN_LOCAL_CONTRACT_VALUE",
                window_id=window.upper(),
                unit="count",
                dtype="int16",
                physical_range=[0, 200],
                null_policy="NEVER_NULL_WHEN_WINDOW_IS_DEFINED",
                alignment_id="ONE_SELECTED_CYCLE",
                description="Explicit count of absent or non-finite source values.",
            )

    low, high = _field_range(config, "H38")
    for suffix, operator, window, unit, bounds, description in (
        ("asof_interval_value", "LAST_COMPLETED_INTERVAL", "ASOF", "kg m-2", [low, high], "Latest fully ended native precipitation interval."),
        ("retained_sum", "NATIVE_INTERVAL_SUM", "RETAINED", "kg m-2", [0.0, 5000.0], "Sum of native non-overlapping retained precipitation intervals."),
        ("retained_max", "MAX", "RETAINED", "kg m-2", [low, high], "Largest retained native precipitation interval."),
        ("remaining_sum", "NATIVE_INTERVAL_SUM", "REMAINING", "kg m-2", [0.0, 5000.0], "Sum only intervals whose full support starts no earlier than issue time."),
        ("remaining_max", "MAX", "REMAINING", "kg m-2", [low, high], "Largest fully remaining native precipitation interval."),
        ("remaining_wet_fraction", "FRACTION_ABOVE_ZERO", "REMAINING", "1", [0.0, 1.0], "Fraction of complete remaining native intervals with precipitation above zero."),
    ):
        add(
            name=f"h38_local_{suffix}", family="trajectory", operator=operator,
            source_fields=("H38",), product="wrfsfcf",
            spatial_support="KDEN_LOCAL_NEAREST", window_id=window, unit=unit,
            physical_range=bounds,
            null_policy=("NULL_IF_SELECTED_ROW_MISSING" if window == "ASOF" else "NULL_UNLESS_ALL_NATIVE_INTERVALS_PRESENT_AND_NONOVERLAPPING"),
            alignment_id="ONE_SELECTED_CYCLE",
            description=description,
        )
    add(
        name="h38_local_asof_interval_end_offset_minutes", family="trajectory",
        operator="TIME_OFFSET", source_fields=("H38",), product="wrfsfcf",
        spatial_support="KDEN_LOCAL_NEAREST", window_id="ASOF", unit="min",
        dtype="int32", physical_range=[0, 1440],
        null_policy="NULL_IF_ANCHOR_ROW_IS_ABSENT", alignment_id="ONE_SELECTED_CYCLE",
        description="Minutes from latest completed native interval end to issue time.",
    )
    for window in ("retained", "remaining"):
        for suffix, operator, dtype, bounds in (
            ("coverage_fraction", "COVERAGE_FRACTION", "float64", [0.0, 1.0]),
            ("missing_count", "MISSING_COUNT", "int16", [0, 200]),
        ):
            add(
                name=f"h38_local_{window}_{suffix}", family="missingness",
                operator=operator, source_fields=("H38",), product="wrfsfcf",
                spatial_support="KDEN_LOCAL_NEAREST", window_id=window.upper(),
                unit="1" if suffix == "coverage_fraction" else "count", dtype=dtype,
                physical_range=bounds, null_policy="NEVER_NULL_WHEN_WINDOW_IS_DEFINED",
                alignment_id="ONE_SELECTED_CYCLE",
                description="Explicit native-interval precipitation coverage metadata.",
            )

    for field in REGIONAL_FIELDS:
        low, high = _field_range(config, field)
        unit = FIELD_UNITS[field]
        product = FIELD_PRODUCT[field]
        anchor_name = (
            "remaining_first_interval" if field == "H38" else "future_first"
        )
        window_id = "REMAINING" if field == "H38" else "FUTURE_FIRST"
        for suffix, operator, bounds in (
            ("mean", "MEAN", [low, high]),
            ("min", "MIN", [low, high]),
            ("max", "MAX", [low, high]),
            ("range", "RANGE", [0.0, high - low]),
            ("west_minus_east_mean", "SECTOR_CONTRAST", [low - high, high - low]),
            ("near_minus_far_mean", "DISTANCE_CONTRAST", [low - high, high - low]),
        ):
            add(
                name=f"{field.lower()}_regional_{anchor_name}_{suffix}",
                family="spatial", operator=operator, source_fields=(field,),
                product=product, spatial_support="EIGHT_REGISTERED_REGIONAL_SUPPORTS",
                window_id=window_id, unit=unit, physical_range=bounds,
                null_policy="NULL_UNLESS_ALL_EIGHT_SUPPORTS_PRESENT",
                alignment_id="ONE_SELECTED_CYCLE",
                description=(
                    "Deterministic regional summary for the first fully remaining native interval."
                    if field == "H38"
                    else "Deterministic regional summary at the first future native snapshot."
                ),
            )
        add(
            name=f"{field.lower()}_regional_{anchor_name}_coverage_fraction",
            family="missingness", operator="COVERAGE_FRACTION",
            source_fields=(field,), product=product,
            spatial_support="EIGHT_REGISTERED_REGIONAL_SUPPORTS",
            window_id=window_id, unit="1", physical_range=[0.0, 1.0],
            null_policy="NEVER_NULL_WHEN_ANCHOR_ROW_EXISTS",
            alignment_id="ONE_SELECTED_CYCLE",
                description="Present registered regional supports divided by eight at the declared anchor.",
        )

    for field in TILE_FIELDS:
        low, high = _field_range(config, field)
        unit = FIELD_UNITS[field]
        product = FIELD_PRODUCT[field]
        anchor_name = (
            "remaining_first_interval" if field == "H38" else "future_first"
        )
        window_id = "REMAINING" if field == "H38" else "FUTURE_FIRST"
        for suffix, operator, bounds in (
            ("mean", "MEAN", [low, high]),
            ("min", "MIN", [low, high]),
            ("max", "MAX", [low, high]),
            ("range", "RANGE", [0.0, high - low]),
            ("stddev", "POPULATION_STDDEV", [0.0, high - low]),
        ):
            add(
                name=f"{field.lower()}_tile_{anchor_name}_{suffix}", family="spatial",
                operator=operator, source_fields=(field,), product=product,
                spatial_support="ACQUIRED_NATIVE_TILE", window_id=window_id,
                unit=unit, physical_range=bounds,
                null_policy="NULL_UNLESS_TILE_SHAPE_AND_ALL_NODES_ARE_PRESENT",
                alignment_id="ONE_SELECTED_CYCLE",
                description=(
                    "Deterministic acquired-tile summary for the first fully remaining native interval."
                    if field == "H38"
                    else "Deterministic acquired-tile summary at the first future native snapshot."
                ),
            )
        add(
            name=f"{field.lower()}_tile_{anchor_name}_coverage_fraction",
            family="missingness", operator="COVERAGE_FRACTION",
            source_fields=(field,), product=product,
            spatial_support="ACQUIRED_NATIVE_TILE", window_id=window_id,
            unit="1", physical_range=[0.0, 1.0],
            null_policy="NEVER_NULL_WHEN_ANCHOR_ROW_EXISTS",
            alignment_id="ONE_SELECTED_CYCLE",
            description="Finite tile nodes divided by declared tile node count.",
        )

    for name, operator, unit, bounds, description in (
        ("h14_terrain_archive_anchor_m", "IDENTITY", "m", [-500.0, 9000.0], "Static terrain at the once-acquired H14 archive anchor; dynamic coordinate era is a separate panel key."),
        ("h14_terrain_regional_mean_m", "MEAN", "m", [-500.0, 9000.0], "Mean terrain across eight registered supports."),
        ("h14_terrain_regional_range_m", "RANGE", "m", [0.0, 9500.0], "Regional terrain maximum minus minimum."),
        ("h14_terrain_west_minus_east_mean_m", "SECTOR_CONTRAST", "m", [-9500.0, 9500.0], "West-support mean minus east-support mean terrain."),
        ("h14_terrain_near_minus_far_mean_m", "DISTANCE_CONTRAST", "m", [-9500.0, 9500.0], "Mean 30-km terrain minus mean 60-km terrain."),
    ):
        add(
            name=name, family="static_spatial", operator=operator,
            source_fields=("H14",), product="wrfsfcf",
            spatial_support="KDEN_AND_EIGHT_REGISTERED_SUPPORTS", window_id="STATIC",
            unit=unit, physical_range=bounds,
            null_policy="NEVER_NULL_AFTER_R14_STATIC_ACCEPTANCE",
            alignment_id="STATIC_HRRR_V4_GEOMETRY", description=description,
        )

    derived = (
        ("derived_t850_minus_t2m_future_first_k", "DIFFERENCE", ("H07", "H16"), "K", [-80.0, 80.0], "Same-cycle 850-mb temperature minus 2-m temperature at earliest common future valid time."),
        ("derived_t700_minus_t850_future_first_k", "DIFFERENCE", ("H02", "H07"), "K", [-80.0, 80.0], "Same-cycle 700-mb temperature minus 850-mb temperature at earliest common future valid time."),
        ("derived_dewpoint_depression_future_first_k", "DIFFERENCE", ("H16", "H17"), "K", [0.0, 100.0], "Same-cycle 2-m temperature minus dewpoint at earliest common future valid time."),
        ("derived_wind_speed_future_first_m_s", "VECTOR_MAGNITUDE", ("H18", "H19"), "m s-1", [0.0, 150.0], "Same-cycle 10-m wind-vector magnitude at earliest common future valid time."),
        ("derived_q05_minus_h16_common_remaining_mean_k", "MEAN_DIFFERENCE", ("Q05", "H16"), "K", [-80.0, 80.0], "Q05 minus H16 over exact shared valid times from independently legal cycles."),
        ("derived_q05_minus_h16_common_remaining_max_abs_k", "MAX_ABS_DIFFERENCE", ("Q05", "H16"), "K", [0.0, 80.0], "Maximum absolute Q05/H16 difference over exact shared valid times."),
        ("derived_wind_speed_remaining_mean_m_s", "VECTOR_MAGNITUDE_MEAN", ("H18", "H19"), "m s-1", [0.0, 150.0], "Mean wind-vector magnitude over exact common remaining support."),
        ("derived_wind_speed_remaining_max_m_s", "VECTOR_MAGNITUDE_MAX", ("H18", "H19"), "m s-1", [0.0, 150.0], "Maximum wind-vector magnitude over exact common remaining support."),
        ("derived_dewpoint_depression_remaining_mean_k", "MEAN_DIFFERENCE", ("H16", "H17"), "K", [0.0, 100.0], "Mean temperature-dewpoint depression over exact common remaining support."),
        ("derived_dewpoint_depression_remaining_max_k", "MAX_DIFFERENCE", ("H16", "H17"), "K", [0.0, 100.0], "Maximum temperature-dewpoint depression over exact common remaining support."),
        ("derived_h31_remaining_trapezoid_mj_m2", "TRAPEZOID_INTEGRAL", ("H31",), "MJ m-2", [0.0, 100.0], "Trapezoidal integral of remaining downwelling shortwave flux."),
        ("derived_h36_remaining_ge20_fraction", "FRACTION_AT_OR_ABOVE", ("H36",), "1", [0.0, 1.0], "Fraction of complete remaining reflectivity snapshots at or above 20 dBZ."),
        ("derived_h26_remaining_positive_fraction", "FRACTION_ABOVE_ZERO", ("H26",), "1", [0.0, 1.0], "Fraction of complete remaining snow-cover snapshots above zero percent."),
    )
    for name, operator, fields, unit, bounds, description in derived:
        products = {FIELD_PRODUCT[field] for field in fields}
        add(
            name=name, family="derived", operator=operator, source_fields=fields,
            product=next(iter(products)) if len(products) == 1 else None,
            spatial_support="KDEN_LOCAL_CONTRACT_VALUE",
            window_id="FUTURE_FIRST" if "future_first" in name else "COMMON_REMAINING",
            unit=unit, physical_range=bounds,
            null_policy="NULL_UNLESS_ALL_EXACT_TIME_INPUTS_AND_DECLARED_WINDOW_ROWS_ARE_PRESENT",
            alignment_id=("ONE_SELECTED_CYCLE" if len(products) == 1 else "SAME_VALID_TIME_INDEPENDENT_LEGAL_CYCLES"),
            description=description,
        )

    for field in DYNAMIC_FIELDS:
        low, high = _field_range(config, field)
        product = FIELD_PRODUCT[field]
        for suffix, operator, unit, dtype, bounds in (
            ("overlap_count", "OVERLAP_COUNT", "count", "int16", [0, 200]),
            ("coverage_fraction", "COVERAGE_FRACTION", "1", "float64", [0.0, 1.0]),
            ("missing_count", "MISSING_COUNT", "count", "int16", [0, 200]),
            ("mean", "MEAN_REVISION", FIELD_UNITS[field], "float64", [low - high, high - low]),
            ("max_abs", "MAX_ABS_REVISION", FIELD_UNITS[field], "float64", [0.0, high - low]),
        ):
            add(
                name=f"revision_{field.lower()}_remaining_{suffix}", family="revision",
                operator=operator, source_fields=(field,), product=product,
                spatial_support="KDEN_LOCAL_CONTRACT_VALUE", window_id="REVISION_OVERLAP",
                unit=unit, dtype=dtype, physical_range=bounds,
                null_policy=("NEVER_NULL_WHEN_BOTH_CYCLES_EXIST" if suffix in {"overlap_count", "coverage_fraction", "missing_count"} else "NULL_UNLESS_ALL_OVERLAP_ROWS_PRESENT"),
                alignment_id="CURRENT_MINUS_IMMEDIATE_PREVIOUS_IDENTICAL_VALID_TIME",
                description="Current minus immediately previous legal same-product cycle on exact remaining overlap.",
            )

    names = [feature["name"] for feature in features]
    identifiers = [feature["feature_id"] for feature in features]
    if len(names) != len(set(names)) or len(identifiers) != len(set(identifiers)):
        raise ContractError("P04 feature registry contains duplicate names or identities")
    return features


def feature_registry_schema_document() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "KDEN_V375_P04_FEATURE_REGISTRY_SCHEMA_V1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "registry_id", "derivation_id", "feature_count", "features", "contracts", "source_authority"],
        "properties": {
            "schema_version": {"const": "KDEN_V375_UNIVERSAL_FEATURE_REGISTRY_DOCUMENT_V1"},
            "registry_id": {"const": REGISTRY_ID},
            "derivation_id": {"const": DERIVATION_ID},
            "feature_count": {"type": "integer", "minimum": 1},
            "features": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["feature_id", "name", "family", "operator", "source_fields", "product", "spatial_support", "window_id", "unit", "dtype", "physical_range", "null_policy", "alignment_id", "description"],
                    "properties": {
                        "feature_id": {"type": "string", "pattern": "^FEATURE_[0-9a-f]{64}$"},
                        "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                        "family": {"type": "string"},
                        "operator": {"type": "string"},
                        "source_fields": {"type": "array", "items": {"type": "string"}},
                        "product": {"type": ["string", "null"]},
                        "spatial_support": {"type": "string"},
                        "window_id": {"type": "string"},
                        "unit": {"type": "string"},
                        "dtype": {"enum": ["bool", "int16", "int32", "float64"]},
                        "physical_range": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                        "null_policy": {"type": "string"},
                        "alignment_id": {"type": "string"},
                        "description": {"type": "string"}
                    }
                }
            },
            "contracts": {"type": "object"},
            "source_authority": {"type": "object"}
        }
    }


def panel_schema_document(features: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fixed = [
        {"name": "issue_state_id", "arrow_type": "string", "nullable": False},
        {"name": "target_date", "arrow_type": "date32", "nullable": False},
        {"name": "statistical_group_id", "arrow_type": "string", "nullable": False},
        {"name": "issue_time_utc", "arrow_type": "timestamp[us,UTC]", "nullable": False},
        {"name": "station_coord_era", "arrow_type": "string", "nullable": False},
        {"name": "wrfsfcf_cycle_init_utc", "arrow_type": "timestamp[us,UTC]", "nullable": False},
        {"name": "wrfsubhf_cycle_init_utc", "arrow_type": "timestamp[us,UTC]", "nullable": False},
        {"name": "feature_registry_id", "arrow_type": "string", "nullable": False},
        {"name": "derivation_id", "arrow_type": "string", "nullable": False},
    ]
    arrow_type = {"bool": "bool", "int16": "int16", "int32": "int32", "float64": "float64"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "KDEN_V375_DETERMINISTIC_FEATURE_PANEL_SCHEMA_V1",
        "schema_id": PANEL_SCHEMA_ID,
        "format": "parquet",
        "primary_key": ["issue_state_id"],
        "statistical_group_key": ["target_date"],
        "feature_registry_id": REGISTRY_ID,
        "derivation_id": DERIVATION_ID,
        "columns": fixed + [
            {
                "name": feature["name"],
                "arrow_type": arrow_type[str(feature["dtype"])],
                "nullable": True,
                "feature_id": feature["feature_id"],
                "unit": feature["unit"],
            }
            for feature in features
        ],
        "forbidden_column_patterns": ["truth", "target_value", "y_audited", "market", "kalshi", "settlement", "madis", "fold", "prediction"],
        "row_rules": {
            "one_row_per_issue_state": True,
            "target_values_allowed": False,
            "cycle_stitching_allowed": False,
            "interpolation_allowed": False,
            "missing_numeric_values": "Arrow null only; never NaN or sentinel",
            "all_rows_for_one_target_date_share_statistical_group_id": True,
        },
    }


def feature_panel_schema(features: Sequence[Mapping[str, Any]]) -> pa.Schema:
    type_map: dict[str, pa.DataType] = {
        "bool": pa.bool_(), "int16": pa.int16(), "int32": pa.int32(), "float64": pa.float64()
    }
    fields = [
        pa.field("issue_state_id", pa.string(), nullable=False),
        pa.field("target_date", pa.date32(), nullable=False),
        pa.field("statistical_group_id", pa.string(), nullable=False),
        pa.field("issue_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("station_coord_era", pa.string(), nullable=False),
        pa.field("wrfsfcf_cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("wrfsubhf_cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("feature_registry_id", pa.string(), nullable=False),
        pa.field("derivation_id", pa.string(), nullable=False),
    ]
    fields.extend(
        pa.field(str(feature["name"]), type_map[str(feature["dtype"])])
        for feature in features
    )
    return pa.schema(
        fields,
        metadata={
            b"schema_version": b"KDEN_V375_PARQUET_SCHEMA_V1",
            b"schema_id": PANEL_SCHEMA_ID.encode("ascii"),
            b"feature_registry_id": REGISTRY_ID.encode("ascii"),
            b"derivation_id": DERIVATION_ID.encode("ascii"),
        },
    )


def _present(row: Mapping[str, Any], value_column: str) -> bool:
    value = row.get(value_column)
    return (
        str(row.get("coverage_flag")) == "PRESENT"
        and value is not None
        and math.isfinite(float(value))
    )


def _strict_stats(
    rows: Sequence[Mapping[str, Any]], value_column: str
) -> dict[str, float | int | None]:
    count = len(rows)
    present = [row for row in rows if _present(row, value_column)]
    missing = count - len(present)
    coverage = 0.0 if count == 0 else len(present) / count
    result: dict[str, float | int | None] = {
        "coverage_fraction": coverage,
        "missing_count": missing,
        "min": None,
        "max": None,
        "mean": None,
        "range": None,
        "endpoint_slope_per_hour": None,
    }
    if not rows or missing:
        return result
    values = [float(row[value_column]) for row in rows]
    result.update(
        min=min(values), max=max(values), mean=sum(values) / len(values), range=max(values) - min(values)
    )
    if len(rows) >= 2:
        elapsed = (as_utc(rows[-1]["valid_time_utc"]) - as_utc(rows[0]["valid_time_utc"])).total_seconds() / 3600.0
        if elapsed > 0:
            result["endpoint_slope_per_hour"] = (values[-1] - values[0]) / elapsed
    return result


def _anchor(
    rows: Sequence[Mapping[str, Any]], issue_time: datetime, *, mode: str
) -> Mapping[str, Any] | None:
    issue = as_utc(issue_time)
    if mode == "asof":
        eligible = [row for row in rows if as_utc(row["valid_time_utc"]) <= issue]
        return max(eligible, key=lambda row: as_utc(row["valid_time_utc"]), default=None)
    if mode == "future_first":
        eligible = [row for row in rows if as_utc(row["valid_time_utc"]) >= issue]
        return min(eligible, key=lambda row: as_utc(row["valid_time_utc"]), default=None)
    raise ContractError(f"unsupported anchor mode: {mode}")


def _snapshot_features(
    field: str, rows: Sequence[Mapping[str, Any]], issue_time: datetime
) -> dict[str, Any]:
    stem = field.lower()
    column = LOCAL_VALUE_COLUMN[field]
    issue = as_utc(issue_time)
    retained = list(rows)
    remaining = [row for row in rows if as_utc(row["valid_time_utc"]) >= issue]
    asof = _anchor(rows, issue, mode="asof")
    future = _anchor(rows, issue, mode="future_first")
    result: dict[str, Any] = {}
    for label, row in (("asof", asof), ("future_first", future)):
        result[f"{stem}_local_{label}_value"] = (
            float(row[column]) if row is not None and _present(row, column) else None
        )
        result[f"{stem}_local_{label}_offset_minutes"] = (
            None
            if row is None
            else int(abs((as_utc(row["valid_time_utc"]) - issue).total_seconds()) // 60)
        )
    for label, selected in (("retained", retained), ("remaining", remaining)):
        stats = _strict_stats(selected, column)
        for metric in ("min", "max", "mean", "range"):
            result[f"{stem}_local_{label}_{metric}"] = stats[metric]
        if label == "remaining":
            result[f"{stem}_local_remaining_endpoint_slope_per_hour"] = stats[
                "endpoint_slope_per_hour"
            ]
        result[f"{stem}_local_{label}_coverage_fraction"] = stats["coverage_fraction"]
        result[f"{stem}_local_{label}_missing_count"] = stats["missing_count"]
    return result


def _validate_nonoverlap(rows: Sequence[Mapping[str, Any]]) -> bool:
    intervals = sorted(
        (as_utc(row["interval_start_utc"]), as_utc(row["interval_end_utc"]))
        for row in rows
        if as_utc(row["interval_end_utc"]) > as_utc(row["interval_start_utc"])
    )
    return all(current[0] >= previous[1] for previous, current in zip(intervals, intervals[1:]))


def _accumulation_features(
    rows: Sequence[Mapping[str, Any]], issue_time: datetime
) -> dict[str, Any]:
    issue = as_utc(issue_time)
    column = "nn_value"
    retained = list(rows)
    remaining = [row for row in rows if as_utc(row["interval_start_utc"]) >= issue]
    completed = [row for row in rows if as_utc(row["interval_end_utc"]) <= issue]
    asof = max(completed, key=lambda row: as_utc(row["interval_end_utc"]), default=None)
    result: dict[str, Any] = {
        "h38_local_asof_interval_value": (
            float(asof[column]) if asof is not None and _present(asof, column) else None
        ),
        "h38_local_asof_interval_end_offset_minutes": (
            None if asof is None else int((issue - as_utc(asof["interval_end_utc"])).total_seconds() // 60)
        ),
    }
    for label, selected in (("retained", retained), ("remaining", remaining)):
        stats = _strict_stats(selected, column)
        complete = bool(selected) and stats["missing_count"] == 0 and _validate_nonoverlap(selected)
        values = [float(row[column]) for row in selected] if complete else []
        result[f"h38_local_{label}_coverage_fraction"] = stats["coverage_fraction"]
        result[f"h38_local_{label}_missing_count"] = stats["missing_count"]
        result[f"h38_local_{label}_sum"] = sum(values) if complete else None
        result[f"h38_local_{label}_max"] = max(values) if complete else None
        if label == "remaining":
            result["h38_local_remaining_wet_fraction"] = (
                sum(value > 0.0 for value in values) / len(values) if values else None
            )
    return result


def _future_anchor_row(
    rows_by_field: Mapping[str, Sequence[Mapping[str, Any]]], field: str, issue: datetime
) -> Mapping[str, Any] | None:
    if field == "H38":
        eligible = [
            row
            for row in rows_by_field[field]
            if as_utc(row["interval_start_utc"]) >= as_utc(issue)
        ]
        return min(
            eligible,
            key=lambda row: (
                as_utc(row["interval_start_utc"]), as_utc(row["interval_end_utc"])
            ),
            default=None,
        )
    return _anchor(rows_by_field[field], issue, mode="future_first")


def _regional_features(field: str, row: Mapping[str, Any] | None) -> dict[str, Any]:
    anchor_name = "remaining_first_interval" if field == "H38" else "future_first"
    stem = f"{field.lower()}_regional_{anchor_name}_"
    values = [] if row is None else [row.get(f"regional_value_{index:02d}") for index in range(8)]
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    coverage = len(finite) / 8.0
    complete = (
        row is not None
        and int(row.get("regional_support_count", 0)) == 8
        and int(row.get("regional_coverage_mask", 0)) == 255
        and len(finite) == 8
    )
    result: dict[str, Any] = {stem + "coverage_fraction": coverage}
    for suffix in ("mean", "min", "max", "range", "west_minus_east_mean", "near_minus_far_mean"):
        result[stem + suffix] = None
    if complete:
        result[stem + "mean"] = sum(finite) / 8.0
        result[stem + "min"] = min(finite)
        result[stem + "max"] = max(finite)
        result[stem + "range"] = max(finite) - min(finite)
        result[stem + "west_minus_east_mean"] = sum(finite[0:2]) / 2.0 - sum(finite[4:6]) / 2.0
        result[stem + "near_minus_far_mean"] = sum(finite[0::2]) / 4.0 - sum(finite[1::2]) / 4.0
    return result


def _tile_features(field: str, row: Mapping[str, Any] | None) -> dict[str, Any]:
    anchor_name = "remaining_first_interval" if field == "H38" else "future_first"
    stem = f"{field.lower()}_tile_{anchor_name}_"
    values = [] if row is None or row.get("tile_values") is None else list(row["tile_values"])
    shape = [] if row is None or row.get("tile_shape") is None else list(row["tile_shape"])
    expected = math.prod(int(value) for value in shape) if shape else 0
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    coverage = 0.0 if expected == 0 else len(finite) / expected
    complete = expected > 0 and len(values) == expected and len(finite) == expected
    result: dict[str, Any] = {stem + "coverage_fraction": coverage}
    for suffix in ("mean", "min", "max", "range", "stddev"):
        result[stem + suffix] = None
    if complete:
        mean = sum(finite) / expected
        result.update(
            {
                stem + "mean": mean,
                stem + "min": min(finite),
                stem + "max": max(finite),
                stem + "range": max(finite) - min(finite),
                stem + "stddev": math.sqrt(sum((value - mean) ** 2 for value in finite) / expected),
            }
        )
    return result


def _terrain_features(
    row: Mapping[str, Any], regional_values: Sequence[float]
) -> dict[str, Any]:
    values = [float(value) for value in regional_values]
    if len(values) != 8 or any(not math.isfinite(value) for value in values):
        raise ContractError("H14 coordinate-era terrain support is incomplete")
    return {
        "h14_terrain_archive_anchor_m": float(row["bi_value"]),
        "h14_terrain_regional_mean_m": sum(values) / 8.0,
        "h14_terrain_regional_range_m": max(values) - min(values),
        "h14_terrain_west_minus_east_mean_m": sum(values[0:2]) / 2.0 - sum(values[4:6]) / 2.0,
        "h14_terrain_near_minus_far_mean_m": sum(values[0::2]) / 4.0 - sum(values[1::2]) / 4.0,
    }


def _exact_common_rows(
    first: Sequence[Mapping[str, Any]],
    second: Sequence[Mapping[str, Any]],
    issue_time: datetime,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    issue = as_utc(issue_time)
    left = {as_utc(row["valid_time_utc"]): row for row in first if as_utc(row["valid_time_utc"]) >= issue}
    right = {as_utc(row["valid_time_utc"]): row for row in second if as_utc(row["valid_time_utc"]) >= issue}
    return [(left[key], right[key]) for key in sorted(set(left) & set(right))]


def _strict_pairs(
    pairs: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    first_column: str,
    second_column: str,
) -> list[tuple[float, float]] | None:
    if not pairs or any(not _present(left, first_column) or not _present(right, second_column) for left, right in pairs):
        return None
    return [(float(left[first_column]), float(right[second_column])) for left, right in pairs]


def _trapezoid(rows: Sequence[Mapping[str, Any]], column: str) -> float | None:
    if len(rows) < 2 or any(not _present(row, column) for row in rows):
        return None
    total = 0.0
    for left, right in zip(rows, rows[1:]):
        hours = (as_utc(right["valid_time_utc"]) - as_utc(left["valid_time_utc"])).total_seconds() / 3600.0
        if hours <= 0:
            return None
        total += (float(left[column]) + float(right[column])) * 0.5 * hours * 0.0036
    return total


def _derived_features(
    rows_by_field: Mapping[str, Sequence[Mapping[str, Any]]], issue_time: datetime
) -> dict[str, Any]:
    issue = as_utc(issue_time)
    result: dict[str, Any] = {}

    def pair_values(first: str, second: str) -> list[tuple[float, float]] | None:
        pairs = _exact_common_rows(rows_by_field[first], rows_by_field[second], issue)
        return _strict_pairs(pairs, LOCAL_VALUE_COLUMN[first], LOCAL_VALUE_COLUMN[second])

    for name, first, second in (
        ("derived_t850_minus_t2m_future_first_k", "H07", "H16"),
        ("derived_t700_minus_t850_future_first_k", "H02", "H07"),
        ("derived_dewpoint_depression_future_first_k", "H16", "H17"),
    ):
        values = pair_values(first, second)
        result[name] = None if not values else values[0][0] - values[0][1]
    wind = pair_values("H18", "H19")
    result["derived_wind_speed_future_first_m_s"] = (
        None if not wind else math.hypot(wind[0][0], wind[0][1])
    )
    qh = pair_values("Q05", "H16")
    result["derived_q05_minus_h16_common_remaining_mean_k"] = (
        None if not qh else sum(left - right for left, right in qh) / len(qh)
    )
    result["derived_q05_minus_h16_common_remaining_max_abs_k"] = (
        None if not qh else max(abs(left - right) for left, right in qh)
    )
    result["derived_wind_speed_remaining_mean_m_s"] = (
        None if not wind else sum(math.hypot(u, v) for u, v in wind) / len(wind)
    )
    result["derived_wind_speed_remaining_max_m_s"] = (
        None if not wind else max(math.hypot(u, v) for u, v in wind)
    )
    depression = pair_values("H16", "H17")
    result["derived_dewpoint_depression_remaining_mean_k"] = (
        None if not depression else sum(temp - dew for temp, dew in depression) / len(depression)
    )
    result["derived_dewpoint_depression_remaining_max_k"] = (
        None if not depression else max(temp - dew for temp, dew in depression)
    )
    h31_remaining = [row for row in rows_by_field["H31"] if as_utc(row["valid_time_utc"]) >= issue]
    result["derived_h31_remaining_trapezoid_mj_m2"] = _trapezoid(h31_remaining, "bi_value")
    for name, field, threshold, inclusive in (
        ("derived_h36_remaining_ge20_fraction", "H36", 20.0, True),
        ("derived_h26_remaining_positive_fraction", "H26", 0.0, False),
    ):
        rows = [row for row in rows_by_field[field] if as_utc(row["valid_time_utc"]) >= issue]
        column = LOCAL_VALUE_COLUMN[field]
        if not rows or any(not _present(row, column) for row in rows):
            result[name] = None
        else:
            values = [float(row[column]) for row in rows]
            result[name] = sum(value >= threshold if inclusive else value > threshold for value in values) / len(values)
    return result


def _revision_features(
    field: str,
    current: Sequence[Mapping[str, Any]],
    previous: Sequence[Mapping[str, Any]],
    issue_time: datetime,
) -> dict[str, Any]:
    stem = f"revision_{field.lower()}_remaining_"
    pairs = _exact_common_rows(current, previous, issue_time)
    column = LOCAL_VALUE_COLUMN[field]
    valid = [pair for pair in pairs if _present(pair[0], column) and _present(pair[1], column)]
    missing = len(pairs) - len(valid)
    coverage = 0.0 if not pairs else len(valid) / len(pairs)
    result: dict[str, Any] = {
        stem + "overlap_count": len(pairs),
        stem + "coverage_fraction": coverage,
        stem + "missing_count": missing,
        stem + "mean": None,
        stem + "max_abs": None,
    }
    if pairs and not missing:
        differences = [float(left[column]) - float(right[column]) for left, right in pairs]
        result[stem + "mean"] = sum(differences) / len(differences)
        result[stem + "max_abs"] = max(abs(value) for value in differences)
    return result


def compute_issue_feature_row(
    *,
    issue_row: Mapping[str, Any],
    selection_rows: Mapping[str, Mapping[str, Any]],
    reader: R14ArchiveReader,
    features: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute one P04/P05-compatible row without truth, interpolation, or stitching."""

    if set(selection_rows) != {"wrfsfcf", "wrfsubhf"}:
        raise ContractError("one independently selected row per R14 product is required")
    issue_time = as_utc(issue_row["issue_time_utc"])
    current_tables: dict[str, pa.Table] = {}
    previous_tables: dict[str, pa.Table] = {}
    for product, selection in selection_rows.items():
        if selection["issue_state_id"] != issue_row["issue_state_id"]:
            raise ContractError("P03 issue and product selection identities disagree")
        if as_utc(selection["emulated_complete_time_utc"]) > issue_time:
            raise ContractError("P04 was given a future-complete cycle")
        current_tables[product] = reader.read_cycle(
            issue_row["target_date"], product, selection["cycle_init_utc"]
        )
        previous_tables[product] = reader.read_cycle(
            issue_row["target_date"], product, selection["previous_cycle_init_utc"]
        )
    rows_by_field: dict[str, list[dict[str, Any]]] = {}
    previous_by_field: dict[str, list[dict[str, Any]]] = {}
    current_python: dict[str, list[dict[str, Any]]] = {
        product: table.to_pylist() for product, table in current_tables.items()
    }
    previous_python: dict[str, list[dict[str, Any]]] = {
        product: table.to_pylist() for product, table in previous_tables.items()
    }
    for field in DYNAMIC_FIELDS:
        product = FIELD_PRODUCT[field]
        rows_by_field[field] = sorted(
            [
                row
                for row in current_python[product]
                if str(row["field_registry_id"]) == field
            ],
            key=lambda row: (
                as_utc(row["valid_time_utc"]), as_utc(row["interval_start_utc"])
            ),
        )
        previous_by_field[field] = sorted(
            [
                row
                for row in previous_python[product]
                if str(row["field_registry_id"]) == field
            ],
            key=lambda row: (
                as_utc(row["valid_time_utc"]), as_utc(row["interval_start_utc"])
            ),
        )
    era_values = {
        str(row["station_coord_era"])
        for rows in current_python.values()
        for row in rows
    }
    if len(era_values) != 1:
        raise ContractError("selected product cycles disagree on KDEN coordinate era")
    result: dict[str, Any] = {
        "issue_state_id": issue_row["issue_state_id"],
        "target_date": issue_row["target_date"],
        "statistical_group_id": issue_row["statistical_group_id"],
        "issue_time_utc": issue_time,
        "station_coord_era": next(iter(era_values)),
        "wrfsfcf_cycle_init_utc": as_utc(selection_rows["wrfsfcf"]["cycle_init_utc"]),
        "wrfsubhf_cycle_init_utc": as_utc(selection_rows["wrfsubhf"]["cycle_init_utc"]),
        "feature_registry_id": REGISTRY_ID,
        "derivation_id": DERIVATION_ID,
    }
    local_minutes = int(issue_row["local_issue_hour"]) * 60 + int(issue_row["local_issue_minute"])
    result.update(
        clock_issue_minutes_since_0200=int(issue_row["local_minutes_since_0200"]),
        clock_issue_time_sin=math.sin(2.0 * math.pi * local_minutes / 1440.0),
        clock_issue_time_cos=math.cos(2.0 * math.pi * local_minutes / 1440.0),
        clock_target_doy_sin=math.sin(2.0 * math.pi * (int(issue_row["target_day_of_year"]) - 1) / 365.2425),
        clock_target_doy_cos=math.cos(2.0 * math.pi * (int(issue_row["target_day_of_year"]) - 1) / 365.2425),
        clock_local_dst_flag=bool(issue_row["local_dst_flag"]),
    )
    for product, selection in selection_rows.items():
        for suffix in (
            "cycle_age_minutes", "availability_age_minutes",
            "previous_cycle_age_minutes", "previous_availability_age_minutes",
        ):
            result[f"clock_{product}_{suffix}"] = int(selection[suffix])
        retained_start = as_utc(selection["retained_valid_start_utc"])
        retained_end = as_utc(selection["retained_valid_end_utc"])
        target_start = as_utc(issue_row["target_window_start_utc"])
        result[f"support_{product}_retained_start_offset_minutes"] = int(
            (retained_start - target_start).total_seconds() // 60
        )
        result[f"support_{product}_retained_end_offset_minutes"] = int(
            (retained_end - target_start).total_seconds() // 60
        )
        result[f"support_{product}_retained_span_minutes"] = int(
            (retained_end - retained_start).total_seconds() // 60
        )
        result[f"support_{product}_remaining_horizon_minutes"] = max(
            0, int((retained_end - issue_time).total_seconds() // 60)
        )
    for field in SNAPSHOT_FIELDS:
        result.update(_snapshot_features(field, rows_by_field[field], issue_time))
    result.update(_accumulation_features(rows_by_field["H38"], issue_time))
    for field in REGIONAL_FIELDS:
        result.update(_regional_features(field, _future_anchor_row(rows_by_field, field, issue_time)))
    for field in TILE_FIELDS:
        result.update(_tile_features(field, _future_anchor_row(rows_by_field, field, issue_time)))
    terrain = reader.read_static_terrain().to_pylist()[0]
    terrain_evidence = _read_json(reader.root / H14_TERRAIN_SUPPORTS_PATH)
    evidence_rows = terrain_evidence.get("evidence", [])
    if len(evidence_rows) != 1:
        raise ContractError("H14 terrain-support evidence is not unique")
    support_values = evidence_rows[0].get("values_by_coordinate_era", {}).get(
        result["station_coord_era"]
    )
    support_mask = evidence_rows[0].get("coverage_masks_by_coordinate_era", {}).get(
        result["station_coord_era"]
    )
    if support_values is None or support_mask != 255:
        raise ContractError("H14 terrain support is absent for the dynamic coordinate era")
    result.update(_terrain_features(terrain, support_values))
    result.update(_derived_features(rows_by_field, issue_time))
    for field in DYNAMIC_FIELDS:
        result.update(
            _revision_features(
                field, rows_by_field[field], previous_by_field[field], issue_time
            )
        )
    expected = {str(feature["name"]) for feature in features}
    produced = set(result) - {
        "issue_state_id", "target_date", "statistical_group_id", "issue_time_utc",
        "station_coord_era", "wrfsfcf_cycle_init_utc", "wrfsubhf_cycle_init_utc",
        "feature_registry_id", "derivation_id",
    }
    if produced != expected:
        missing = sorted(expected - produced)
        extra = sorted(produced - expected)
        raise ContractError(f"feature engine/registry mismatch; missing={missing}, extra={extra}")
    for feature in features:
        value = result[feature["name"]]
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError(f"non-finite feature must be Arrow null: {feature['name']}")
    return result


def _case_rows(root: Path, target: date, local_clock: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    parsed = time.fromisoformat(local_clock)
    issues = pq.read_table(
        root / ISSUE_OUTPUT_PATH,
        filters=[("target_date", "=", target)],
    ).to_pylist()
    matched = [
        row for row in issues
        if row["local_issue_hour"] == parsed.hour and row["local_issue_minute"] == parsed.minute
    ]
    if len(matched) != 1:
        raise ContractError(f"bounded P04 issue-state anchor is not unique: {target}/{local_clock}")
    issue = matched[0]
    selections = pq.read_table(
        root / SELECTION_OUTPUT_PATH,
        filters=[("issue_state_id", "=", issue["issue_state_id"])],
    ).to_pylist()
    by_product = {str(row["product"]): row for row in selections}
    if len(by_product) != 2:
        raise ContractError("bounded P04 case lacks two product selections")
    return issue, by_product


def _validate_range(feature: Mapping[str, Any], value: Any) -> None:
    bounds = feature["physical_range"]
    if value is None or bounds is None or isinstance(value, bool):
        return
    numeric = float(value)
    if numeric < float(bounds[0]) - 1e-9 or numeric > float(bounds[1]) + 1e-9:
        raise ContractError(
            f"bounded feature violates physical range: {feature['name']}={numeric} not in {bounds}"
        )


def run_bounded_acceptance(
    root: Path, config: Mapping[str, Any], features: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Exercise a small, predeclared weather-only acceptance set."""

    reader = R14ArchiveReader(root, verify_acquisition=True)
    rows: dict[str, dict[str, Any]] = {}
    for case in config["bounded_cases"]:
        issue, selections = _case_rows(
            root, date.fromisoformat(case["target_date"]), case["issue_local"]
        )
        row = compute_issue_feature_row(
            issue_row=issue, selection_rows=selections, reader=reader, features=features
        )
        for feature in features:
            _validate_range(feature, row[feature["name"]])
        encoded = pa.Table.from_pylist([row], schema=feature_panel_schema(features))
        if encoded.num_rows != 1 or encoded.schema != feature_panel_schema(features):
            raise ContractError("bounded P04 row does not encode under the frozen panel schema")
        rows[case["case_id"]] = row
    issue_dates = pq.read_table(root / ISSUE_OUTPUT_PATH, columns=["target_date"]).column(0).to_pylist()
    counts = Counter(issue_dates)
    spring = [
        "2021-03-14", "2022-03-13", "2023-03-12",
        "2024-03-10", "2025-03-09", "2026-03-08",
    ]
    if any(counts[date.fromisoformat(value)] != 53 for value in spring):
        raise ContractError("P04 DST anchors no longer have 53 legal issue states")
    missing = rows["confirmed_remote_missing"]
    if not (
        missing["h16_local_remaining_missing_count"] == 1
        and missing["h16_local_remaining_coverage_fraction"] < 1.0
        and missing["h16_local_remaining_max"] is None
        and missing["revision_h16_remaining_mean"] is None
    ):
        raise ContractError("confirmed 2022-02-26 source gap was not preserved explicitly")
    if not (
        rows["snow"]["h26_local_retained_max"] == 100.0
        and rows["convective"]["derived_h36_remaining_ge20_fraction"] > 0.0
        and rows["dry_heating"]["derived_dewpoint_depression_remaining_max_k"] > 5.0
        and rows["dry_heating"]["h31_local_retained_max"] > 500.0
        and rows["mixing_downslope"]["derived_wind_speed_remaining_max_m_s"] > 5.0
        and rows["mixing_downslope"]["h24_local_retained_max"] > 500.0
    ):
        raise ContractError("one or more predeclared meteorological probes lost its signal")
    era_checks: dict[str, str] = {}
    for target, expected in (
        (date(2021, 11, 21), "KDEN_COORD_20040105"),
        (date(2021, 11, 22), "KDEN_COORD_20211122"),
    ):
        cycle = datetime.combine(target, time(7), tzinfo=UTC)
        table = reader.read_cycle(target, "wrfsfcf", cycle, field_ids=("H16", "H38"))
        eras = {str(value) for value in table["station_coord_era"].to_pylist()}
        if eras != {expected}:
            raise ContractError("coordinate-era boundary changed")
        era_checks[target.isoformat()] = expected
    terrain_evidence = _read_json(root / H14_TERRAIN_SUPPORTS_PATH)
    terrain_rows = terrain_evidence.get("evidence", [])
    if len(terrain_rows) != 1:
        raise ContractError("H14 coordinate-era terrain evidence changed")
    terrain_by_era = terrain_rows[0].get("values_by_coordinate_era", {})
    terrain_masks = terrain_rows[0].get("coverage_masks_by_coordinate_era", {})
    if (
        set(terrain_by_era) != {"KDEN_COORD_20040105", "KDEN_COORD_20211122"}
        or set(terrain_masks) != set(terrain_by_era)
        or any(terrain_masks[era] != 255 for era in terrain_by_era)
        or any(len(values) != 8 for values in terrain_by_era.values())
        or terrain_by_era["KDEN_COORD_20040105"]
        == terrain_by_era["KDEN_COORD_20211122"]
    ):
        raise ContractError("H14 terrain does not preserve both coordinate eras")
    h38 = reader.read_cycle(
        date(2021, 11, 22), "wrfsfcf", datetime(2021, 11, 22, 7, tzinfo=UTC),
        field_ids=("H38",),
    ).to_pylist()
    lead0 = [row for row in h38 if row["forecast_lead_min"] == 0]
    lead60 = [row for row in h38 if row["forecast_lead_min"] == 60]
    if not (
        len(lead0) == len(lead60) == 1
        and lead0[0]["interval_start_utc"] == lead0[0]["interval_end_utc"]
        and lead60[0]["interval_end_utc"] - lead60[0]["interval_start_utc"] == timedelta(hours=1)
    ):
        raise ContractError("H38 FH00/preceding-hour interval semantics changed")
    return {
        "case_ids": [case["case_id"] for case in config["bounded_cases"]],
        "case_count": len(rows),
        "spring_forward_dates_checked": spring,
        "confirmed_remote_missing_h16_remaining_count": missing["h16_local_remaining_missing_count"],
        "strict_missing_aggregate_is_null": missing["h16_local_remaining_max"] is None,
        "coordinate_eras": era_checks,
        "h14_coordinate_era_supports_verified": True,
        "h38_fh00_zero_duration_verified": True,
        "h38_fh01_preceding_hour_verified": True,
        "truth_rows_read": 0,
        "network_requests_made": 0,
    }


def _authority(root: Path) -> dict[str, str]:
    paths = {
        "P03_ISSUE_SPINE": ISSUE_OUTPUT_PATH,
        "P03_SELECTED_CYCLES": SELECTION_OUTPUT_PATH,
        "R14_HOURLY_REGISTRY": "registries/hrrr_hourly_v375.csv",
        "R14_SUBHOURLY_REGISTRY": "registries/hrrr_subhourly_v375.csv",
        "R14_SPATIAL_CONTRACT": "config/r14_spatial_contract_v375.json",
        "R14_SPATIAL_GEOMETRY": "registries/r14_spatial_geometry_v375.json",
        "R14_FIELD_STATE_SCHEMA": "schemas/hrrr_field_state_r14_v375.json",
        "R14_H14_TERRAIN_SUPPORTS": H14_TERRAIN_SUPPORTS_PATH,
        "ISSUE_VIEW_CONTRACT": "config/issue_time_views_r14_v375.json",
        "STEP08_ACCEPTANCE": "reports/step_08_final_acceptance_v375.json",
    }
    return {key: sha256_file(root / relative) for key, relative in paths.items()}


def _registry_document(
    root: Path,
    config: Mapping[str, Any],
    features: Sequence[Mapping[str, Any]],
    predecessor: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "KDEN_V375_UNIVERSAL_FEATURE_REGISTRY_DOCUMENT_V1",
        "registry_id": REGISTRY_ID,
        "derivation_id": DERIVATION_ID,
        "feature_count": len(features),
        "features": list(features),
        "contracts": {
            "windows": config["windows"],
            "aggregate_missingness": config["aggregate_missingness"],
            "alignment": config["alignment"],
            "spatial": config["spatial"],
            "thresholds": config["thresholds"],
            "schema_evolution": config["schema_evolution"],
            "target_values_allowed": False,
            "model_specific_transforms_allowed": False,
        },
        "source_authority": {
            "predecessor_p03_record_sha256": predecessor["record_sha256"],
            "artifact_sha256": _authority(root),
        },
    }


def _validate_registry(
    config: Mapping[str, Any], registry: Mapping[str, Any]
) -> list[dict[str, Any]]:
    expected = build_feature_registry(config)
    if registry.get("registry_id") != REGISTRY_ID or registry.get("derivation_id") != DERIVATION_ID:
        raise ContractError("P04 registry identity changed")
    if registry.get("features") != expected or registry.get("feature_count") != len(expected):
        raise ContractError("published P04 feature registry differs from implementation")
    forbidden = tuple(str(value).lower() for value in config["prohibited_inputs"])
    for feature in expected:
        searchable = canonical_json_bytes(feature).decode("utf-8").lower()
        if any(token in searchable for token in forbidden):
            raise ContractError(f"prohibited input entered feature registry: {feature['name']}")
    panel = panel_schema_document(expected)
    names = [column["name"] for column in panel["columns"]]
    if len(names) != len(set(names)):
        raise ContractError("feature-panel schema contains duplicate columns")
    return expected


def p04_preflight(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    predecessor = _predecessor(root)
    config = _load_config(root)
    features = build_feature_registry(config)
    load_issue_view_contract(root)
    authority = _authority(root)
    return {
        "schema_version": "KDEN_V375_PREFIT_P04_PREFLIGHT_V1",
        "status": "READY_FOR_BOUNDED_P04",
        "predecessor_p03_record_sha256": predecessor["record_sha256"],
        "registry_id": REGISTRY_ID,
        "panel_schema_id": PANEL_SCHEMA_ID,
        "feature_count": len(features),
        "bounded_case_count": len(config["bounded_cases"]),
        "source_authority_sha256": authority,
        "network_requests_made": 0,
        "truth_rows_read": 0,
        "full_history_rows_materialized": 0,
        "run_command": ".venv/bin/python -m kden_v375.prefit.cli run-p04 --run-id kdenv375-p04-ordinary-YYYYMMDDTHHMMSSZ-feature-contract",
        "validation_command": ".venv/bin/python -m kden_v375.prefit.cli validate-p04",
    }


def _report(features: Sequence[Mapping[str, Any]], evidence: Mapping[str, Any]) -> bytes:
    families = Counter(str(feature["family"]) for feature in features)
    text = f"""# P04 Universal Primitive and Feature Contract Report

Status: **PASS candidate**  
Registry: `{REGISTRY_ID}`  
Panel schema: `{PANEL_SCHEMA_ID}`  
Deterministic features: {len(features)}

## What P04 freezes

P04 defines target-free, model-neutral transformations over one independently
selected R14 cycle per product. It publishes no full-history feature rows and
fits no model. P05 will use this exact registry and transformation library.
The {len(features)} registered columns are a universal library, not a mandate
to place all {len(features)} into one Analog Ensemble distance. P07 must freeze
small, model-specific adapter subsets and fold-local scaling without changing
the universal source object.

Feature-family counts:

{chr(10).join(f'- `{name}`: {count}' for name, count in sorted(families.items()))}

Primary aggregate features fail closed: if a declared window contains a
missing source state, the aggregate is null. Coverage fractions and missing
counts remain explicit. No value is interpolated, silently imputed, or filled
from another cycle.

## Time and alignment

- `ASOF`, `FUTURE_FIRST`, `RETAINED`, `REMAINING`, exact common-time, and
  current-versus-previous revision windows have separate definitions.
- Snapshot fields use physical `valid_time_utc`.
- H38 uses native interval start/end support; only fully remaining intervals
  enter remaining sums.
- Revisions compare the current cycle with the immediately previous legal
  same-product cycle at identical valid times.
- H16/Q05 comparisons use identical valid times while preserving their
  independently selected legal cycles.
- Cycle stitching and hourly/subhourly interpolation are prohibited.

## Spatial contract

Local point values, acquired native tiles, and the eight registered regional
supports are different operations. Regional and tile summaries require their
complete declared support. H02/H07 remain local/tile-only. No terrain lapse
rate correction is introduced. The dynamic `station_coord_era` is retained in
every eventual panel row.

## Bounded acceptance

The implementation exercised {evidence['case_count']} predeclared local-archive
cases: {', '.join(evidence['case_ids'])}. It also verified all six DST gaps,
the 2021-11-21/22 coordinate-era boundary, H38 FH00/FH01 interval semantics,
and the known 2022-02-26 remote source gap. That gap produces a missing H16
remaining state in the selected 18Z cycle; its strict aggregate is null and
its coverage metadata remains visible.

No truth row, market row, MADIS row, network source, fold assignment, learned
scaling, fitted regime, analog weight, or model prediction was used.

## Boundary to P05

P04 only freezes definitions and bounded evidence. P05 is the owner-run,
resumable full-history materialization of the normalized trajectory catalog and
deterministic feature panel.
"""
    return text.encode("utf-8")


def _runbook() -> bytes:
    return f"""# P04 Owner Runbook

P04 is a bounded, local-only contract publication. It does not scan or
materialize the full history, use the network, read truth values, or fit a
model. It normally completes in under a few minutes.

From the KDEN v3.75 project root:

```bash
.venv/bin/python -m pip install --no-build-isolation --no-deps .
.venv/bin/python -m kden_v375.prefit.cli p04-preflight
```

Use the fresh run ID returned by your timestamp convention, for example:

```bash
.venv/bin/python -m kden_v375.prefit.cli run-p04 \\
  --run-id kdenv375-p04-ordinary-YYYYMMDDTHHMMSSZ-feature-contract
```

Then validate independently:

```bash
.venv/bin/python -m kden_v375.prefit.cli validate-p04
```

Expected terminal states are `PASS` and `VALID`. There is no pause/resume or
ETA command because P04 is deliberately bounded. P05 will provide those
surfaces for the long full-history build.

Published artifacts:

- `{REGISTRY_PATH}`
- `{PANEL_SCHEMA_PATH}`
- `{REGISTRY_SCHEMA_PATH}`
- `{REPORT_PATH}`
- `{PASS_PATH}`
""".encode("utf-8")


def run_p04(*, project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if (root / PASS_PATH).is_file():
        return verify_p04(root)
    predecessor = _predecessor(root)
    config = _load_config(root)
    features = build_feature_registry(config)
    registry = _registry_document(root, config, features, predecessor)
    _validate_registry(config, registry)
    evidence = run_bounded_acceptance(root, config, features)
    atomic_write_json(root / REGISTRY_SCHEMA_PATH, feature_registry_schema_document(), replace=True)
    atomic_write_json(root / PANEL_SCHEMA_PATH, panel_schema_document(features), replace=True)
    atomic_write_json(root / REGISTRY_PATH, registry, replace=True)
    atomic_write_bytes(root / REPORT_PATH, _report(features, evidence), replace=True)
    atomic_write_bytes(root / RUNBOOK_PATH, _runbook(), replace=True)
    isolation = _stable_isolation_evidence(validate_runtime_isolation(root))
    gate = {
        "predecessor_record_sha256": predecessor["record_sha256"],
        "registry_id": REGISTRY_ID,
        "panel_schema_id": PANEL_SCHEMA_ID,
        "derivation_id": DERIVATION_ID,
        "feature_count": len(features),
        "feature_family_counts": dict(sorted(Counter(feature["family"] for feature in features).items())),
        "strict_aggregate_missingness": True,
        "cycle_stitching_allowed": False,
        "interpolation_allowed": False,
        "truth_rows_read": 0,
        "network_requests_made": 0,
        "full_history_rows_materialized": 0,
        "bounded_acceptance": evidence,
        "runtime_isolation": isolation,
    }
    return write_prefit_pass(
        root,
        stage_no=4,
        run_id=run_id,
        artifact_paths=[
            CONFIG_PATH, REGISTRY_SCHEMA_PATH, PANEL_SCHEMA_PATH, REGISTRY_PATH,
            REPORT_PATH, RUNBOOK_PATH, "src/kden_v375/prefit/p04_features.py",
        ],
        predecessor_hashes={"PREFIT_P03": predecessor["record_sha256"]},
        authority_hashes=_authority(root),
        gate_evidence=gate,
    )


def verify_p04(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    predecessor = _predecessor(root)
    record = verify_prefit_pass(root, 4)
    if record.get("predecessor_hashes", {}).get("PREFIT_P03") != predecessor["record_sha256"]:
        raise StaleStateError("P04 predecessor link changed")
    config = _load_config(root)
    registry = _read_json(root / REGISTRY_PATH)
    features = _validate_registry(config, registry)
    if _read_json(root / REGISTRY_SCHEMA_PATH) != feature_registry_schema_document():
        raise StaleStateError("P04 registry schema changed")
    if _read_json(root / PANEL_SCHEMA_PATH) != panel_schema_document(features):
        raise StaleStateError("P04 feature-panel schema changed")
    if registry.get("source_authority", {}).get("artifact_sha256") != _authority(root):
        raise StaleStateError("P04 source authority changed")
    evidence = run_bounded_acceptance(root, config, features)
    expected_gate = record["gate_evidence"]
    if evidence != expected_gate.get("bounded_acceptance"):
        raise StaleStateError("P04 bounded acceptance evidence changed")
    if feature_panel_schema(features).names != [column["name"] for column in panel_schema_document(features)["columns"]]:
        raise ContractError("logical and Arrow feature-panel schemas disagree")
    isolation = _stable_isolation_evidence(validate_runtime_isolation(root))
    if isolation != expected_gate.get("runtime_isolation"):
        raise StaleStateError("P04 runtime isolation evidence changed")
    return {
        "schema_version": "KDEN_V375_PREFIT_P04_VALIDATION_V1",
        "status": "VALID",
        "validated_stage": "PREFIT_P04",
        "record_sha256": record["record_sha256"],
        "registry_path": REGISTRY_PATH,
        "panel_schema_path": PANEL_SCHEMA_PATH,
        "feature_count": len(features),
        "feature_family_counts": expected_gate["feature_family_counts"],
        "bounded_acceptance": evidence,
        "runtime_isolation": isolation,
    }
