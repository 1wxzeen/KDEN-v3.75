"""Bounded R14 Step 04 confirmation pilot.

The earlier broad-universe reports and PASS record remain historical evidence.
This active implementation consumes only the sealed R14 plans, registry, and
regional geometry.  It publishes one source object at a time so pause/resume
is hash-verifiable and duplicate-free.
"""

from __future__ import annotations

import csv
import json
import math
import os
import resource
import shutil
import struct
import sys
import tempfile
import time
import tomllib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo

from .accounting import AcquisitionAccounting, RequestTerminalResult
from .contracts import (
    ContractError,
    PauseRequested,
    load_project_paths,
    relative_to_root,
    utc_now,
)
from .execution import execute_bounded
from .hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from .io import grib as grib_io
from .io.atomic import atomic_publish_directory, atomic_write_json
from .io.cache import SourceGroupCache
from .io.http_range import (
    AttemptEvidence,
    HttpContractError,
    MessageRange,
    PersistentHttpTransport,
    TransportRangeGroup,
    VerifiedHttpClient,
    coalesce_exact_adjacent_ranges,
    split_coalesced_payload,
)
from .io.parquet import atomic_write_table
from .progress import ProgressCoordinator, WorkUnitReceipt, publish_work_unit_manifest
from .r14 import (
    EXPECTED_SUPPORT_ORDER,
    R14_ALL_IDS,
    R14_DYNAMIC_HOURLY,
    R14_SCOPE_ID,
    R14_SPATIAL_CONTRACT_ID,
    R14_SPATIAL_GEOMETRY_PATH,
    R14_STATIC_HOURLY,
    R14_SUBHOURLY,
    load_r14_field_registry,
    validate_r14_spatial_contract,
    verify_r14_registry_bundle,
)
from .r14_plan_records import verify_r14_step03_pass
from .r14_request_plans import (
    PRODUCTS,
    R14_PLAN_DIRECTORY as PLAN_DIRECTORY,
    R14_PLAN_MANIFEST as PLAN_MANIFEST,
    R14_PLAN_MANIFEST_SCHEMA_VERSION as PLAN_MANIFEST_SCHEMA_VERSION,
    load_r14_request_schema,
    verify_r14_product_plan,
)
from .r14_schedule import R14_SCHEDULE_PARQUET_PATH as SCHEDULE_PARQUET_PATH
from .registries import _arrow_type, load_parquet_schema


PILOT_DESIGN_SCHEMA_VERSION = "KDEN_V375_R14_CONFIRMATION_PILOT_DESIGN_V1"
PILOT_SELECTION_SCHEMA_VERSION = "KDEN_V375_R14_PILOT_SELECTION_V1"
PILOT_REPORT_SCHEMA_VERSION = "KDEN_V375_R14_PILOT_REPORT_V1"
PILOT_DESIGN_PATH = "config/pilot_design_r14_v375.json"
PILOT_REPORT_JSON_PATH = "reports/step_04_r14_pilot_report_v375.json"
PILOT_REPORT_MD_PATH = "reports/step_04_r14_pilot_report_v375.md"
STEP_ID = "STEP_04"
DENVER = ZoneInfo("America/Denver")
EXPECTED_FIELDS = R14_DYNAMIC_HOURLY + R14_STATIC_HOURLY + R14_SUBHOURLY
EXPECTED_SEASONS = frozenset({"winter", "spring", "summer", "fall"})
EXPECTED_STRATA = frozenset({"early", "middle", "late"})
EXPECTED_ERAS = frozenset({"KDEN_COORD_20040105", "KDEN_COORD_20211122"})
PRIMARY_MODE = "primary"
REBUILD_MODE = "rebuild"
DERIVATION_VERSION = "KDEN_V375_R14_DIRECT_NATIVE_REGIONAL_EXTRACTION_V1"


class PilotContractError(ContractError):
    """A bounded pilot selection, acquisition, or closeout gate failed."""


@dataclass(frozen=True, slots=True)
class PilotWeek:
    week_id: str
    season: str
    archive_stratum: str
    start_date: date
    end_date: date
    coordinate_era: str
    dst_regime: str
    required_transition: str | None = None

    @property
    def target_days(self) -> tuple[date, ...]:
        return tuple(self.start_date + timedelta(days=offset) for offset in range(7))


@dataclass(frozen=True, slots=True)
class PilotDesign:
    raw: Mapping[str, Any]
    weeks: tuple[PilotWeek, ...]
    target_days: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class PilotSourceTask:
    base_unit_id: str
    product: str
    target_day: date
    week_id: str
    cohort: str
    source_object_identity: str
    rows: tuple[Mapping[str, Any], ...]

    def unit_id(self, mode: str) -> str:
        return f"{mode.upper()}_{self.base_unit_id}"


@dataclass(frozen=True, slots=True)
class PilotSelection:
    rows: tuple[Mapping[str, Any], ...]
    tasks: tuple[PilotSourceTask, ...]
    selection_sha256: str
    manifest: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PilotWorkResult:
    receipt: WorkUnitReceipt
    metrics: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProfiledDecode:
    decoded: grib_io.DecodedExtraction
    decode_seconds: float
    extraction_seconds: float
    regional_values_native: tuple[float | None, ...]
    regional_coverage_mask: int
    terrain_values_by_coordinate_era: Mapping[str, tuple[float | None, ...]]
    terrain_masks_by_coordinate_era: Mapping[str, int]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise PilotContractError(f"JSON artifact must contain an object: {path}")
    return value


def _load_r14_field_state_schema(project_root: Path) -> Any:
    """Build the Step 04 schema without modifying the sealed Step 01 loader."""

    try:
        import pyarrow as pa
    except ImportError as exc:
        raise PilotContractError("pyarrow is required for R14 pilot publication") from exc
    value = _read_json(project_root / "schemas/hrrr_field_state_r14_v375.json")
    if (
        value.get("schema_version") != "KDEN_V375_PARQUET_SCHEMA_V1"
        or value.get("schema_id") != "KDEN_V375_HRRR_FIELD_STATE_R14_V1"
        or value.get("compression") != "zstd"
    ):
        raise PilotContractError("unsupported R14 field-state schema identity")
    names = [column.get("name") for column in value.get("columns", [])]
    regional = [f"regional_value_{index:02d}" for index in range(8)]
    required = {
        "regional_spatial_contract_id",
        "regional_operator",
        "regional_support_count",
        "regional_coverage_mask",
        *regional,
    }
    if not required.issubset(names) or len(names) != len(set(names)):
        raise PilotContractError("R14 field-state regional columns are incomplete")
    return pa.schema(
        [
            pa.field(
                column["name"],
                _arrow_type(column["arrow_type"]),
                nullable=bool(column["nullable"]),
            )
            for column in value["columns"]
        ],
        metadata={
            b"schema_version": str(value["schema_version"]).encode("ascii"),
            b"schema_id": str(value["schema_id"]).encode("ascii"),
            b"compression": str(value["compression"]).encode("ascii"),
        },
    )


def load_pilot_design(project_root: Path | str) -> PilotDesign:
    paths = load_project_paths(project_root)
    raw = _read_json(paths.root / PILOT_DESIGN_PATH)
    if raw.get("schema_version") != PILOT_DESIGN_SCHEMA_VERSION:
        raise PilotContractError("unsupported representative-pilot design schema")
    if raw.get("scope_id") != R14_SCOPE_ID:
        raise PilotContractError("pilot design does not bind the active R14 scope")
    if raw.get("network_authority") != "BOUNDED_SELECTED_REQUESTS_ONLY":
        raise PilotContractError("pilot network authority is not bounded")
    if raw.get("lead_policy") != "TARGET_WINDOW_RIGHT_OPEN":
        raise PilotContractError("pilot attempted to reopen the lead policy")
    declared = raw.get("weeks", [])
    if len(declared) != 4:
        raise PilotContractError("pilot must declare exactly four representative weeks")
    weeks: list[PilotWeek] = []
    all_days: list[date] = []
    for item in declared:
        week = PilotWeek(
            week_id=str(item["week_id"]),
            season=str(item["season"]),
            archive_stratum=str(item["archive_stratum"]),
            start_date=date.fromisoformat(str(item["start_date"])),
            end_date=date.fromisoformat(str(item["end_date"])),
            coordinate_era=str(item["coordinate_era"]),
            dst_regime=str(item["dst_regime"]),
            required_transition=item.get("required_transition"),
        )
        if (week.end_date - week.start_date).days != 6:
            raise PilotContractError(f"pilot week is not seven days: {week.week_id}")
        weeks.append(week)
        all_days.extend(week.target_days)
    if len(set(all_days)) != 28:
        raise PilotContractError("pilot weeks overlap or do not contain 28 unique dates")
    if {week.season for week in weeks} != EXPECTED_SEASONS:
        raise PilotContractError("pilot does not contain every meteorological season")
    if not EXPECTED_STRATA.issubset({week.archive_stratum for week in weeks}):
        raise PilotContractError("pilot does not span early, middle, and late archive years")
    if {week.coordinate_era for week in weeks} != EXPECTED_ERAS:
        raise PilotContractError("pilot does not span both KDEN coordinate eras")
    transitions = {week.required_transition for week in weeks if week.required_transition}
    if transitions != {"spring_forward", "fall_back"}:
        raise PilotContractError("pilot transition-date coverage is incomplete")
    selection = raw.get("selection", {})
    if selection.get("daily_cycle_roles") != ["c23", "c00", "c14"]:
        raise PilotContractError("pilot c23/c00/c14 cycle rotation changed")
    if selection.get("daily_lead_roles") != ["first", "middle", "final"]:
        raise PilotContractError("pilot lead-position rotation changed")
    if selection.get("q15_repeated_block_leads_min") != [15, 30, 45, 60]:
        raise PilotContractError("Q15 repeated-block coverage changed")
    if selection.get("parity_fields") != {"wrfsfcf": "H16", "wrfsubhf": "Q05"}:
        raise PilotContractError("H16/Q05 parity field identity changed")
    if (
        selection.get("select_all_r14_fields_for_daily_state") is not True
        or selection.get("include_static_H14_once") is not True
    ):
        raise PilotContractError("pilot selection does not cover the complete R14 source set")
    runtime = raw.get("runtime", {})
    if (
        runtime.get("primary_workers") != 8
        or runtime.get("rebuild_workers") != 8
        or runtime.get("optional_four_worker_diagnostic") is not False
        or runtime.get("cache_policy")
        != "retain_until_hash_verified_rebuild_then_discard"
        or runtime.get("parquet_compression") != "zstd"
    ):
        raise PilotContractError("R14 pilot worker/compression policy changed")
    gates = raw.get("gates", {})
    if gates.get("selected_precision") != "float64" or gates.get("selected_compression") != "zstd":
        raise PilotContractError("pilot must retain the conservative frozen physical schema")
    ranges = raw.get("physical_ranges", {})
    if set(ranges) != set(EXPECTED_FIELDS):
        raise PilotContractError("physical-range gate does not cover all H/Q fields")
    for field_id, bounds in ranges.items():
        if len(bounds) != 2 or not float(bounds[0]) < float(bounds[1]):
            raise PilotContractError(f"invalid physical bounds for {field_id}")
    if int(gates.get("required_primary_workers", 0)) != 8:
        raise PilotContractError("R14 pilot must exercise the eight-worker path")
    _load_worker_profiles(paths.root, raw)
    return PilotDesign(raw=raw, weeks=tuple(weeks), target_days=tuple(sorted(all_days)))


def _load_worker_profile(path: Path, *, product: str, workers: int) -> dict[str, Any]:
    with path.open("rb") as stream:
        value = tomllib.load(stream)
    if value.get("schema_version") != "KDEN_V375_WORKER_PROFILE_V1":
        raise PilotContractError(f"unsupported worker profile: {path}")
    if value.get("product") != product or int(value.get("max_workers", 0)) != workers:
        raise PilotContractError(f"worker profile identity changed: {path}")
    if int(value.get("pool_maxsize_per_host", 0)) != 1:
        raise PilotContractError("each worker session must retain a one-connection host pool")
    return value


def _load_worker_profiles(root: Path, raw: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    output: dict[str, dict[str, dict[str, Any]]] = {}
    for label, workers in (("eight_worker", 8),):
        output[label] = {}
        for product in PRODUCTS:
            relative = raw["runtime"]["profiles"][label][product]
            output[label][product] = _load_worker_profile(
                root / relative, product=product, workers=workers
            )
    return output


def _schedule_rows(
    root: Path, target_days: Sequence[date] | None = None
) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise PilotContractError("pyarrow is required for pilot selection") from exc
    filters = None if target_days is None else [("target_day", "in", list(target_days))]
    return pq.read_table(root / SCHEDULE_PARQUET_PATH, filters=filters).to_pylist()


def _sealed_product_plans(root: Path) -> dict[str, dict[str, Any]]:
    """Read plan identities through the verified R14 Step 03 successor seal."""

    verify_r14_step03_pass(root)
    output: dict[str, dict[str, Any]] = {}
    for product in PRODUCTS:
        gate = verify_r14_product_plan(root, product)
        manifest = _read_json(root / PLAN_MANIFEST[product])
        if (
            manifest.get("schema_version") != PLAN_MANIFEST_SCHEMA_VERSION
            or manifest.get("scope_id") != R14_SCOPE_ID
            or manifest.get("product") != product
        ):
            raise PilotContractError(f"sealed plan identity is invalid for {product}")
        body = dict(manifest)
        supplied = body.pop("plan_sha256", None)
        if supplied != sha256_bytes(canonical_json_bytes(body)):
            raise PilotContractError(f"sealed plan manifest hash is invalid for {product}")
        if gate.get("plan_sha256") != supplied:
            raise PilotContractError(f"R14 Step 03 seal disagrees with {product} plan")
        output[product] = manifest
    return output


def _cycle_role(row: Mapping[str, Any], target_day: date) -> str | None:
    local = row["cycle_init_local"]
    if local.date() == target_day - timedelta(days=1) and local.hour == 23:
        return "c23"
    if local.date() == target_day and local.hour == 0:
        return "c00"
    if local.date() == target_day and local.hour == 14:
        return "c14"
    return None


def _select_cycle(
    rows: Sequence[Mapping[str, Any]], target_day: date, product: str, role: str
) -> Mapping[str, Any]:
    matches = [
        row
        for row in rows
        if row["target_day"] == target_day
        and row["product"] == product
        and _cycle_role(row, target_day) == role
    ]
    if len(matches) != 1:
        raise PilotContractError(
            f"pilot expected one {product} {role} cycle on {target_day}; found {len(matches)}"
        )
    return matches[0]


def _lead_for_role(row: Mapping[str, Any], product: str, role: str) -> int:
    cycle = row["cycle_init_utc"]
    end = row["retained_valid_end_utc"]
    maximum = int((end - cycle).total_seconds() // 60)
    cadence = 60 if product == "wrfsfcf" else 15
    if role == "first":
        return 0
    if role == "middle":
        return (maximum // (2 * cadence)) * cadence
    if role == "final":
        return maximum
    raise PilotContractError(f"unknown pilot lead role: {role}")


def _week_for_day(design: PilotDesign, target_day: date) -> PilotWeek:
    matches = [week for week in design.weeks if target_day in week.target_days]
    if len(matches) != 1:
        raise PilotContractError(f"pilot target day has no unique week: {target_day}")
    return matches[0]


def _load_plan_rows_for_days(
    root: Path, product: str, target_days: Sequence[date]
) -> list[dict[str, Any]]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise PilotContractError("pyarrow is required for pilot selection") from exc
    manifest = _read_json(root / PLAN_MANIFEST[product])
    by_year: dict[int, list[date]] = defaultdict(list)
    for value in target_days:
        by_year[value.year].append(value)
    tables = []
    for part in manifest["partitions"]:
        year = int(part["target_year"])
        if year not in by_year:
            continue
        path = root / PLAN_DIRECTORY[product] / part["path"]
        tables.append(pq.read_table(path, filters=[("target_day", "in", by_year[year])]))
    if product == "wrfsfcf":
        static_part = next(part for part in manifest["partitions"] if int(part["target_year"]) == 2021)
        static_path = root / PLAN_DIRECTORY[product] / static_part["path"]
        tables.append(pq.read_table(static_path, filters=[("field_registry_id", "=", "H14")]))
    if not tables:
        raise PilotContractError(f"no plan partitions overlap the pilot for {product}")
    return pa.concat_tables(tables).to_pylist()


def _selection_state_keys(
    design: PilotDesign, schedule: Sequence[Mapping[str, Any]]
) -> tuple[set[tuple[date, str, datetime, int]], set[tuple[date, str, datetime, int, str]], dict[str, Any]]:
    selection = design.raw["selection"]
    cycle_roles = selection["daily_cycle_roles"]
    lead_roles = selection["daily_lead_roles"]
    all_field_states: set[tuple[date, str, datetime, int]] = set()
    field_states: set[tuple[date, str, datetime, int, str]] = set()
    daily_evidence: list[dict[str, Any]] = []
    for index, target_day in enumerate(design.target_days):
        cycle_role = cycle_roles[index % len(cycle_roles)]
        lead_role = lead_roles[index % len(lead_roles)]
        week = _week_for_day(design, target_day)
        for product in PRODUCTS:
            cycle_row = _select_cycle(schedule, target_day, product, cycle_role)
            lead = _lead_for_role(cycle_row, product, lead_role)
            all_field_states.add((target_day, product, cycle_row["cycle_init_utc"], lead))
            daily_evidence.append(
                {
                    "target_day": target_day.isoformat(),
                    "week_id": week.week_id,
                    "product": product,
                    "cycle_role": cycle_role,
                    "lead_role": lead_role,
                    "cycle_init_utc": cycle_row["cycle_init_utc"].isoformat(),
                    "forecast_lead_min": lead,
                    "horizon_class": cycle_row["horizon_class"],
                    "truncated_by_target_window": cycle_row["retained_valid_end_utc"]
                    < cycle_row["cycle_init_utc"]
                    + timedelta(hours=int(cycle_row["native_max_forecast_hour"])),
                }
            )

    for week in design.weeks:
        target_day = week.start_date
        sub_cycle = _select_cycle(schedule, target_day, "wrfsubhf", "c00")
        for lead in selection["q15_repeated_block_leads_min"]:
            all_field_states.add((target_day, "wrfsubhf", sub_cycle["cycle_init_utc"], int(lead)))
        for product, field_id in selection["parity_fields"].items():
            cycle_row = _select_cycle(schedule, target_day, product, "c00")
            maximum = int(
                (cycle_row["retained_valid_end_utc"] - cycle_row["cycle_init_utc"]).total_seconds()
                // 60
            )
            for lead in selection["parity_leads_min"]:
                if int(lead) <= maximum:
                    field_states.add(
                        (target_day, product, cycle_row["cycle_init_utc"], int(lead), field_id)
                    )
    return all_field_states, field_states, {"daily_state_selection": daily_evidence}


def _selection_row_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["target_day"],
        row["product"],
        row["cycle_init_utc"],
        int(row["forecast_lead_min"]),
        row["field_registry_id"],
    )


def _selection_digest(rows: Sequence[Mapping[str, Any]], design_sha256: str, plan_hashes: Mapping[str, str]) -> str:
    identity = {
        "design_sha256": design_sha256,
        "product_plan_sha256": dict(sorted(plan_hashes.items())),
        "request_ids": [str(row["request_id"]) for row in rows],
    }
    return sha256_bytes(canonical_json_bytes(identity))


def _static_schedule_days(rows: Sequence[Mapping[str, Any]]) -> tuple[date, ...]:
    """Return schedule dates needed only by once-per-grid static requests."""

    return tuple(
        sorted(
            {
                row["target_day"]
                for row in rows
                if row["field_registry_id"] == "H14"
            }
        )
    )


def build_pilot_selection(
    project_root: Path | str,
    run_id: str,
    design: PilotDesign | None = None,
    *,
    publish: bool = True,
) -> PilotSelection:
    """Build or verify the immutable bounded request subset; performs no network I/O."""

    paths = load_project_paths(project_root)
    selected_design = design or load_pilot_design(paths.root)
    plan_manifests = _sealed_product_plans(paths.root)
    plan_hashes = {product: plan_manifests[product]["plan_sha256"] for product in PRODUCTS}
    schedule = _schedule_rows(paths.root, selected_design.target_days)
    all_field_states, field_states, evidence = _selection_state_keys(selected_design, schedule)
    selected_rows: list[dict[str, Any]] = []
    for product in PRODUCTS:
        candidates = _load_plan_rows_for_days(paths.root, product, selected_design.target_days)
        for row in candidates:
            key = (
                row["target_day"],
                row["product"],
                row["cycle_init_utc"],
                int(row["forecast_lead_min"]),
            )
            full_key = (*key, row["field_registry_id"])
            if key in all_field_states or full_key in field_states or row["field_registry_id"] == "H14":
                selected_rows.append(row)
    selected_rows.sort(key=_selection_row_identity)
    request_ids = [str(row["request_id"]) for row in selected_rows]
    if len(request_ids) != len(set(request_ids)):
        raise PilotContractError("pilot selection contains duplicate request IDs")
    observed_fields = {str(row["field_registry_id"]) for row in selected_rows}
    if observed_fields != set(EXPECTED_FIELDS):
        raise PilotContractError(
            f"pilot selector coverage is incomplete: {sorted(set(EXPECTED_FIELDS) - observed_fields)}"
        )
    static_days = tuple(
        value
        for value in _static_schedule_days(selected_rows)
        if value not in set(selected_design.target_days)
    )
    if static_days:
        schedule.extend(_schedule_rows(paths.root, static_days))
    schedule_by_key = {
        (row["target_day"], row["product"], row["cycle_init_utc"]): row for row in schedule
    }
    for row in selected_rows:
        schedule_row = schedule_by_key[(row["target_day"], row["product"], row["cycle_init_utc"])]
        if row["valid_time_utc"] >= schedule_row["window_end_utc"]:
            raise PilotContractError("pilot request reaches the right-open TARGET_WINDOW endpoint")

    design_sha = sha256_file(paths.root / PILOT_DESIGN_PATH)
    selection_sha = _selection_digest(selected_rows, design_sha, plan_hashes)
    row_week = {
        value: _week_for_day(selected_design, value).week_id
        for value in selected_design.target_days
    }
    row_week.update({value: "STATIC_GRID_LINEAGE" for value in _static_schedule_days(selected_rows)})
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected_rows:
        grouped[str(row["source_object_identity"])].append(row)
    tasks: list[PilotSourceTask] = []
    for source_uri, rows in sorted(grouped.items()):
        first = rows[0]
        week_id = row_week[first["target_day"]]
        tasks.append(
            PilotSourceTask(
                base_unit_id="PILOT_SRC_" + sha256_bytes(source_uri.encode("utf-8")),
                product=str(first["product"]),
                target_day=first["target_day"],
                week_id=week_id,
                cohort="eight_worker",
                source_object_identity=source_uri,
                rows=tuple(rows),
            )
        )
    if {task.cohort for task in tasks} != {"eight_worker"}:
        raise PilotContractError("R14 pilot tasks must use the shared eight-worker cohort")
    if {task.product for task in tasks} != set(PRODUCTS):
        raise PilotContractError("R14 eight-worker cohort does not cover both products")

    cycle_roles = {
        item["cycle_role"] for item in evidence["daily_state_selection"]
    }
    lead_roles = {item["lead_role"] for item in evidence["daily_state_selection"]}
    horizon_classes = {
        item["horizon_class"]
        for item in evidence["daily_state_selection"]
        if item["product"] == "wrfsfcf"
    }
    if cycle_roles != {"c23", "c00", "c14"} or lead_roles != {"first", "middle", "final"}:
        raise PilotContractError("pilot cycle/lead position coverage is incomplete")
    if horizon_classes != {"ordinary", "extended"}:
        raise PilotContractError("pilot hourly horizon-class coverage is incomplete")
    if not any(item["truncated_by_target_window"] for item in evidence["daily_state_selection"]):
        raise PilotContractError("pilot lacks a TARGET_WINDOW-truncated late cycle")
    q_repeated = [
        row
        for row in selected_rows
        if row["product"] == "wrfsubhf"
        and int(row["forecast_lead_min"]) in {15, 30, 45, 60}
        and row["target_day"] in {week.start_date for week in selected_design.weeks}
    ]
    if {int(row["forecast_lead_min"]) for row in q_repeated} != {15, 30, 45, 60}:
        raise PilotContractError("pilot repeated Q15 block coverage is incomplete")

    manifest_body = {
        "schema_version": PILOT_SELECTION_SCHEMA_VERSION,
        "scope_id": R14_SCOPE_ID,
        "pilot_id": selected_design.raw["pilot_id"],
        "run_id": run_id,
        "selection_sha256": selection_sha,
        "design": {"path": PILOT_DESIGN_PATH, "sha256": design_sha},
        "product_plan_sha256": plan_hashes,
        "request_count": len(selected_rows),
        "source_object_count": len(tasks),
        "field_ids": sorted(observed_fields),
        "target_days": [value.isoformat() for value in selected_design.target_days],
        "coverage": {
            "seasons": sorted(EXPECTED_SEASONS),
            "archive_strata": sorted(EXPECTED_STRATA),
            "coordinate_eras": sorted(EXPECTED_ERAS),
            "cycle_roles": sorted(cycle_roles),
            "lead_roles": sorted(lead_roles),
            "hourly_horizon_classes": sorted(horizon_classes),
            "spring_forward_date": "2023-03-12",
            "fall_back_date": "2021-11-07",
            "fh00_products": sorted(
                {row["product"] for row in selected_rows if int(row["forecast_lead_min"]) == 0}
            ),
            "q15_repeated_block_leads_min": [15, 30, 45, 60],
            "target_window_truncated_late_cycle": True,
            "all_valid_times_strictly_before_window_end": True,
            "active_field_ids": list(EXPECTED_FIELDS),
            "excluded_field_ids_present": [],
        },
        "worker_profile": {
            "workers": 8,
            "source_object_count": len(tasks),
            "request_count": len(selected_rows),
            "products": sorted({task.product for task in tasks}),
            "optional_four_worker_diagnostic_run": False,
        },
        "tasks": [
            {
                "base_unit_id": task.base_unit_id,
                "product": task.product,
                "target_day": task.target_day.isoformat(),
                "week_id": task.week_id,
                "cohort": task.cohort,
                "source_object_identity": task.source_object_identity,
                "request_count": len(task.rows),
            }
            for task in tasks
        ],
    }
    manifest = {
        **manifest_body,
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest_body)),
    }
    if publish:
        selection_dir = paths.runs / run_id / "pilot/selection"
        parquet_path = selection_dir / "pilot_requests.parquet"
        manifest_path = selection_dir / "selection_manifest.json"
        schema = load_r14_request_schema(paths.root)
        try:
            import pyarrow as pa
        except ImportError as exc:
            raise PilotContractError("pyarrow is required for pilot selection") from exc
        table = pa.Table.from_pylist(selected_rows, schema=schema)
        if parquet_path.exists() or manifest_path.exists():
            if not parquet_path.is_file() or not manifest_path.is_file():
                raise PilotContractError("pilot selection has a partial publication")
            supplied = _read_json(manifest_path)
            if supplied != manifest:
                raise PilotContractError("pilot selection changed on resume")
            observed = __import__("pyarrow.parquet", fromlist=["read_table"]).read_table(parquet_path)
            if observed.schema != schema or [row["request_id"] for row in observed.to_pylist()] != request_ids:
                raise PilotContractError("published pilot request selection changed")
        else:
            atomic_write_table(table, parquet_path, schema=schema, compression="zstd", replace=False)
            atomic_write_json(manifest_path, manifest, replace=False)
    return PilotSelection(tuple(selected_rows), tuple(tasks), selection_sha, manifest)


def parse_pilot_index(text: str) -> tuple[grib_io.IndexRecord, ...]:
    """Parse HRRR indexes while preserving NOAA's FH00 zero-day source text.

    The frozen general parser handles minute/hour intervals.  Operational FH00
    accumulated/averaged messages use the equivalent ``0-0 day`` spelling, so
    the pilot normalizes only that zero-length unit for selector matching and
    retains each original line for evidence.
    """

    raw_lines = [line for line in text.splitlines() if line.strip()]
    normalized_lines: list[str] = []
    for raw in raw_lines:
        pieces = raw.rstrip("\r\n").split(":")
        if len(pieces) >= 6 and pieces[5].strip() in {
            "0-0 day ave fcst",
            "0-0 day acc fcst",
        }:
            pieces[5] = pieces[5].replace("day", "min")
        normalized_lines.append(":".join(pieces))
    parsed = grib_io.parse_index("\n".join(normalized_lines))
    if len(parsed) != len(raw_lines):
        raise PilotContractError("pilot index normalization changed record count")
    return tuple(
        replace(record, original_line=raw)
        for record, raw in zip(parsed, raw_lines, strict=True)
    )


def _index_cache_paths(run_dir: Path, index_url: str) -> tuple[Path, Path]:
    key = sha256_bytes(index_url.encode("utf-8"))
    base = run_dir / "pilot/cache/indexes"
    return base / f"{key}.idx", base / f"{key}.json"


def _quarantine_partial_pair(
    run_dir: Path, category: str, identity: str, paths: Sequence[Path]
) -> None:
    destination = (
        run_dir
        / "quarantine"
        / category
        / identity
        / utc_now().replace(":", "").replace("-", "")
    )
    destination.mkdir(parents=True, exist_ok=False)
    for path in paths:
        if path.exists():
            os.replace(path, destination / path.name)
    atomic_write_json(
        destination / "quarantine_record.json",
        {
            "schema_version": "KDEN_V375_PILOT_QUARANTINE_V1",
            "category": category,
            "identity": identity,
            "quarantined_at_utc": utc_now(),
            "reason": "partial_or_invalid_cache_pair",
        },
        replace=False,
    )


def _load_or_fetch_index(
    *,
    run_dir: Path,
    client: VerifiedHttpClient,
    index_url: str,
) -> tuple[bytes, dict[str, Any]]:
    payload_path, metadata_path = _index_cache_paths(run_dir, index_url)
    if payload_path.exists() or metadata_path.exists():
        if payload_path.is_file() and metadata_path.is_file():
            payload = payload_path.read_bytes()
            metadata = _read_json(metadata_path)
            if (
                metadata.get("index_url") == index_url
                and metadata.get("sha256") == sha256_bytes(payload)
                and int(metadata.get("size_bytes", -1)) == len(payload)
            ):
                return payload, {**metadata, "cache_status": "VERIFIED_HIT"}
        _quarantine_partial_pair(
            run_dir,
            "index_cache",
            sha256_bytes(index_url.encode("utf-8")),
            (payload_path, metadata_path),
        )
    evidence = client.fetch_index(index_url)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    from .io.atomic import atomic_write_bytes

    atomic_write_bytes(payload_path, evidence.body, replace=False)
    metadata = {
        "schema_version": "KDEN_V375_PILOT_INDEX_CACHE_V1",
        "index_url": index_url,
        "sha256": evidence.sha256,
        "size_bytes": evidence.size_bytes,
        "http_status": evidence.status,
        "retry_count": evidence.retry_count,
        "wall_seconds": evidence.wall_seconds,
        "cache_status": "DOWNLOADED",
    }
    try:
        atomic_write_json(metadata_path, metadata, replace=False)
    except Exception:
        _quarantine_partial_pair(
            run_dir,
            "index_cache",
            sha256_bytes(index_url.encode("utf-8")),
            (payload_path, metadata_path),
        )
        raise
    return evidence.body, metadata


def _station_coordinates(project_root: Path) -> tuple[dict[str, Any], ...]:
    path = project_root / "registries/station_coordinate_eras_v375.csv"
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = tuple(dict(row) for row in csv.DictReader(stream))
    return rows


def _station_for_valid_time(
    coordinate_rows: Sequence[Mapping[str, Any]], valid_time_utc: datetime
) -> grib_io.StationCoordinate:
    local_day = valid_time_utc.astimezone(DENVER).date()
    matches = []
    for row in coordinate_rows:
        start = date.fromisoformat(str(row["effective_start"]))
        end = date.max if not row["effective_end"] else date.fromisoformat(str(row["effective_end"]))
        if start <= local_day < end:
            matches.append(row)
    if len(matches) != 1:
        raise PilotContractError(f"valid time has no unique KDEN coordinate era: {valid_time_utc}")
    row = matches[0]
    return grib_io.StationCoordinate(
        era_id=str(row["station_coordinate_era_id"]),
        latitude_deg=float(row["latitude_deg"]),
        longitude_deg=float(row["longitude_deg"]),
    )


def _regional_geometry(project_root: Path) -> dict[str, tuple[dict[str, Any], ...]]:
    validate_r14_spatial_contract(project_root)
    value = _read_json(project_root / R14_SPATIAL_GEOMETRY_PATH)
    if (
        value.get("schema_version") != "KDEN_V375_R14_SPATIAL_GEOMETRY_V1"
        or value.get("scope_id") != R14_SCOPE_ID
        or value.get("spatial_contract_id") != R14_SPATIAL_CONTRACT_ID
        or tuple(value.get("support_order", ())) != EXPECTED_SUPPORT_ORDER
    ):
        raise PilotContractError("R14 resolved regional geometry identity changed")
    body = dict(value)
    supplied = body.pop("geometry_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise PilotContractError("R14 resolved regional geometry hash changed")
    output = {
        str(era): tuple(dict(row) for row in supports)
        for era, supports in value.get("coordinate_era_supports", {}).items()
    }
    if set(output) != EXPECTED_ERAS or any(len(rows) != 8 for rows in output.values()):
        raise PilotContractError("R14 regional geometry does not cover both coordinate eras")
    return output


def _operators(spatial_contract_id: str) -> tuple[str, ...]:
    mapping = {
        "POINT_BI_V1": ("BI",),
        "POINT_BI_NN_V1": ("BI", "NN"),
        "POINT_BI_TILE3_V1": ("BI", "3x3"),
        "POINT_BI_TILE9_V1": ("BI", "9x9"),
        "POINT_NN_TILE9_V1": ("NN", "9x9"),
        "POINT_BI_TILE9_DERIVE3_V1": ("BI", "9x9"),
        # H14 is requested once, but the decoded message yields KDEN BI plus
        # the eight terrain supports; the full grid is never persisted.
        "GRID_STATIC_ONCE_V1": ("BI",),
    }
    try:
        return mapping[spatial_contract_id]
    except KeyError as exc:
        raise PilotContractError(f"unknown spatial contract: {spatial_contract_id}") from exc


def _regional_interpolation(operator_id: str) -> str | None:
    if operator_id == "LOCAL_BASELINE_ONLY_NO_REGIONAL_SUPPORT":
        return None
    if operator_id in {
        "BILINEAR_AT_EIGHT_SUPPORTS",
        "STATIC_TERRAIN_BILINEAR_AT_EIGHT_SUPPORTS",
    }:
        return "BILINEAR"
    if operator_id == "NEAREST_AT_EIGHT_SUPPORTS":
        return "NEAREST"
    raise PilotContractError(f"unknown R14 regional operator: {operator_id}")


def _profiled_decode_and_extract(
    payload: bytes,
    *,
    request: Mapping[str, Any],
    index_record: grib_io.IndexRecord,
    station: grib_io.StationCoordinate,
    operators: Sequence[str],
    regional_operator_id: str,
    regional_geometry: Mapping[str, Sequence[Mapping[str, Any]]],
    native_unit: str,
    canonical_unit: str,
) -> ProfiledDecode:
    """Run the active decoder while measuring decode and extraction separately."""

    if not (payload.startswith(b"GRIB") and payload.endswith(b"7777")):
        raise grib_io.GribContractError("payload is not one framed GRIB message")
    library = grib_io._require_eccodes()
    handle = library.codes_new_from_message(payload)
    if handle is None:
        raise grib_io.GribContractError("ecCodes could not create a message handle")
    try:
        decode_started = time.monotonic()
        encoded = bytes(library.codes_get_message(handle))
        if len(encoded) != len(payload):
            raise grib_io.GribContractError(
                "bounded payload contains trailing or multiple message bytes"
            )
        metadata = grib_io._decode_metadata(handle)
        grib_io.validate_decoded_identity(metadata, request, index_record)
        if not grib_io.decoded_unit_matches_registry(
            str(request["parameter"]), metadata.units, native_unit
        ):
            raise grib_io.GribContractError(
                f"decoded unit {metadata.units!r} disagrees with registry {native_unit!r}"
            )
        decode_seconds = time.monotonic() - decode_started

        extraction_started = time.monotonic()
        spatial = grib_io._extract_spatial(handle, metadata.grid, station, operators)
        interpolation = _regional_interpolation(regional_operator_id)
        terrain_values: dict[str, tuple[float | None, ...]] = {}
        terrain_masks: dict[str, int] = {}
        if interpolation is None:
            regional_values = (None,) * 8
            regional_mask = 0
        elif regional_operator_id == "STATIC_TERRAIN_BILINEAR_AT_EIGHT_SUPPORTS":
            for era_id, supports in regional_geometry.items():
                values, mask = grib_io.extract_registered_supports(
                    handle, metadata.grid, supports, interpolation=interpolation
                )
                terrain_values[era_id] = values
                terrain_masks[era_id] = mask
            regional_values = terrain_values[station.era_id]
            regional_mask = terrain_masks[station.era_id]
        else:
            supports = regional_geometry.get(station.era_id)
            if supports is None:
                raise PilotContractError(
                    f"R14 regional geometry lacks coordinate era {station.era_id}"
                )
            regional_values, regional_mask = grib_io.extract_registered_supports(
                handle, metadata.grid, supports, interpolation=interpolation
            )
        sample = None
        if spatial is not None:
            sample = next(
                (value for value in spatial.operator_values.values() if value is not None),
                None,
            )
            if sample is None:
                sample = next(
                    (float(value) for value in (spatial.tile_values or ()) if value is not None),
                    None,
                )
        canonical = (
            None
            if sample is None
            else grib_io.convert_native_to_canonical(sample, native_unit, canonical_unit)
        )
        reconstructed = (
            None
            if canonical is None
            else grib_io.convert_canonical_to_native(canonical, canonical_unit, native_unit)
        )
        error = None if sample is None else abs(float(reconstructed) - float(sample))
        if error is not None and error > 1e-9 * max(1.0, abs(float(sample))):
            raise grib_io.GribContractError("unit conversion failed round-trip tolerance")
        extraction_seconds = time.monotonic() - extraction_started
        decoded = grib_io.DecodedExtraction(
            metadata=metadata,
            spatial=spatial,
            native_value_sample=None if sample is None else float(sample),
            canonical_value_sample=None if canonical is None else float(canonical),
            unit_roundtrip_error=error,
            decode_seconds=decode_seconds + extraction_seconds,
        )
        return ProfiledDecode(
            decoded,
            decode_seconds,
            extraction_seconds,
            regional_values,
            regional_mask,
            terrain_values,
            terrain_masks,
        )
    finally:
        library.codes_release(handle)


def _decoded_identity(decoded: grib_io.DecodedExtraction) -> str:
    value = asdict(decoded.metadata)
    value["cycle_time_utc"] = decoded.metadata.cycle_time_utc.isoformat().replace("+00:00", "Z")
    value["valid_time_utc"] = decoded.metadata.valid_time_utc.isoformat().replace("+00:00", "Z")
    return canonical_json_bytes(value).decode("ascii").strip()


def _canonical_spatial_values(
    decoded: grib_io.DecodedExtraction,
    native_unit: str,
    canonical_unit: str,
    regional_values_native: Sequence[float | None],
    regional_coverage_mask: int,
) -> tuple[
    float | None,
    float | None,
    list[int] | None,
    list[float | None] | None,
    tuple[float | None, ...],
    int,
]:
    spatial = decoded.spatial
    convert = lambda value: (
        None
        if value is None
        else grib_io.convert_native_to_canonical(float(value), native_unit, canonical_unit)
    )
    if spatial is None:
        regional_values = tuple(convert(value) for value in regional_values_native)
        if len(regional_values) != 8:
            raise PilotContractError("R14 regional extraction did not return eight positions")
        return None, None, None, None, regional_values, int(regional_coverage_mask)
    bi_value = convert(spatial.operator_values.get("BI"))
    nn_value = convert(spatial.operator_values.get("NN"))
    tile_shape = None if spatial.tile_shape is None else list(spatial.tile_shape)
    tile_values = (
        None
        if spatial.tile_values is None
        else [convert(value) for value in spatial.tile_values]
    )
    regional_values = tuple(convert(value) for value in regional_values_native)
    if len(regional_values) != 8:
        raise PilotContractError("R14 regional extraction did not return eight positions")
    return bi_value, nn_value, tile_shape, tile_values, regional_values, int(regional_coverage_mask)


def _field_state_row(
    *,
    plan: Mapping[str, Any],
    field: Mapping[str, str],
    run_id: str,
    station: grib_io.StationCoordinate,
    source_idx_hash: bytes,
    payload_hash: bytes | None,
    byte_start: int | None,
    byte_end: int | None,
    coverage_flag: str,
    missing_reason: str | None,
    decoded_identity: str | None,
    values: tuple[
        float | None,
        float | None,
        list[int] | None,
        list[float | None] | None,
        tuple[float | None, ...],
        int,
    ],
    grid_geometry_id: str = "HRRR_CONUS_NATIVE_LAMBERT_V4",
) -> dict[str, Any]:
    valid = plan["valid_time_utc"]
    cycle = plan["cycle_init_utc"]
    regional_values = values[4]
    if len(regional_values) != 8:
        raise PilotContractError("R14 field-state row requires eight regional value slots")
    regional_support_count = int(plan["regional_support_count"])
    return {
        "target_day": plan["target_day"],
        "cycle_init_utc": cycle,
        "cycle_init_local": cycle.astimezone(DENVER),
        "product": plan["product"],
        "hrrr_version": "v4",
        "forecast_lead_min": int(plan["forecast_lead_min"]),
        "valid_time_utc": valid,
        "valid_time_local": valid.astimezone(DENVER),
        "field_registry_id": field["field_id"],
        "parameter": field["parameter"],
        "level": field["level"],
        "step_type": plan["step_type"],
        "interval_start_utc": plan["interval_start_utc"],
        "interval_end_utc": plan["interval_end_utc"],
        "native_unit": field["native_unit"],
        "canonical_unit": field["canonical_unit"],
        "station_id": "KDEN",
        "station_coord_era": station.era_id,
        "grid_geometry_id": grid_geometry_id,
        "bi_value": values[0],
        "nn_value": values[1],
        "tile_shape": values[2],
        "tile_values": values[3],
        "regional_spatial_contract_id": plan["regional_spatial_contract_id"],
        "regional_operator": (
            None if regional_support_count == 0 else plan["regional_operator_id"]
        ),
        "regional_support_count": regional_support_count,
        "regional_coverage_mask": int(values[5]),
        **{
            f"regional_value_{index:02d}": regional_values[index]
            for index in range(8)
        },
        "coverage_flag": coverage_flag,
        "missing_reason": missing_reason,
        "selector_identity": plan["selector_identity"],
        "source_idx_hash": source_idx_hash,
        "payload_hash": payload_hash,
        "byte_start": byte_start,
        "byte_end": byte_end,
        "decoded_grib_identity": decoded_identity,
        "retrieval_run_id": run_id,
        "derivation_version": DERIVATION_VERSION,
    }


def _ledger_row(
    *,
    plan: Mapping[str, Any],
    run_id: str,
    field: Mapping[str, str],
    disposition: str,
    publication_status: str,
    source_idx_hash: bytes,
    payload_hash: bytes | None,
    decoded_identity: str | None,
    byte_start: int | None,
    byte_end: int | None,
    group_id: str | None,
    http_status: int | None,
    retry_count: int,
    requested_bytes: int,
    accepted_bytes: int,
) -> dict[str, Any]:
    return {
        "request_id": plan["request_id"],
        "retrieval_run_id": run_id,
        "attempt_number": max(1, int(retry_count) + 1),
        "product": plan["product"],
        "cycle_init_utc": plan["cycle_init_utc"],
        "source_object_identity": plan["source_object_identity"],
        "index_object_identity": plan["index_object_identity"],
        "field_registry_id": field["field_id"],
        "selector_identity": plan["selector_identity"],
        "http_status": http_status,
        "retry_class": "RETRIED" if retry_count else None,
        "byte_start": byte_start,
        "byte_end": byte_end,
        "requested_bytes": int(requested_bytes),
        "accepted_bytes": int(accepted_bytes),
        "coalesced_group_id": group_id,
        "source_idx_hash": source_idx_hash,
        "payload_hash": payload_hash,
        "decoded_grib_identity": decoded_identity,
        "publication_status": publication_status,
        "terminal_disposition": disposition,
    }


def _existing_receipt(
    *,
    root: Path,
    manifest_path: Path,
    artifact_path: Path,
    run_id: str,
    unit_id: str,
    plan_ordinal: int,
    selection_sha256: str,
) -> WorkUnitReceipt | None:
    exists = (artifact_path.exists(), manifest_path.exists())
    if exists == (False, False):
        return None
    if exists != (True, True) or not artifact_path.is_dir() or not manifest_path.is_file():
        _quarantine_partial_pair(
            root / "runs" / run_id,
            "orphaned_work_unit",
            unit_id,
            (artifact_path, manifest_path),
        )
        return None
    body = _read_json(manifest_path)
    expected_artifact = relative_to_root(root, artifact_path)
    if (
        body.get("schema_version") != "KDEN_V375_WORK_UNIT_MANIFEST_V1"
        or body.get("run_id") != run_id
        or body.get("step_id") != STEP_ID
        or body.get("request_plan_sha256") != selection_sha256
        or body.get("unit_id") != unit_id
        or int(body.get("plan_ordinal", -1)) != plan_ordinal
        or body.get("artifact_path") != expected_artifact
        or body.get("artifact_sha256") != sha256_path(artifact_path)
    ):
        _quarantine_partial_pair(
            root / "runs" / run_id,
            "orphaned_work_unit",
            unit_id,
            (artifact_path, manifest_path),
        )
        return None
    counts = body.get("counts", {})
    return WorkUnitReceipt(
        unit_id=unit_id,
        plan_ordinal=plan_ordinal,
        artifact_path=expected_artifact,
        artifact_sha256=str(body["artifact_sha256"]),
        manifest_path=relative_to_root(root, manifest_path),
        manifest_sha256=sha256_file(manifest_path),
        row_count=int(counts["row_count"]),
        request_count=int(counts["request_count"]),
        accepted_bytes=int(counts["accepted_bytes"]),
    )


def _metric_from_artifact(artifact_path: Path) -> dict[str, Any]:
    return _read_json(artifact_path / "metrics.json")


def _field_value_sequence(
    values: tuple[
        float | None,
        float | None,
        list[int] | None,
        list[float | None] | None,
        tuple[float | None, ...],
        int,
    ]
) -> tuple[float, ...]:
    output = [value for value in values[:2] if isinstance(value, (int, float)) and math.isfinite(value)]
    output.extend(
        value
        for value in (values[3] or [])
        if isinstance(value, (int, float)) and math.isfinite(value)
    )
    output.extend(
        value
        for value in values[4]
        if isinstance(value, (int, float)) and math.isfinite(value)
    )
    return tuple(float(value) for value in output)


def _process_source_task(
    *,
    root: Path,
    run_id: str,
    task: PilotSourceTask,
    mode: str,
    plan_ordinal: int,
    selection_sha256: str,
    design: PilotDesign,
    field_registry: Mapping[str, Mapping[str, str]],
    coordinate_rows: Sequence[Mapping[str, Any]],
    regional_geometry: Mapping[str, Sequence[Mapping[str, Any]]],
    transport: PersistentHttpTransport,
) -> PilotWorkResult:
    unit_id = task.unit_id(mode)
    run_dir = root / "runs" / run_id
    artifact_path = run_dir / "pilot" / mode / "units" / unit_id
    manifest_path = run_dir / "pilot/manifests" / mode / f"{unit_id}.json"
    existing = _existing_receipt(
        root=root,
        manifest_path=manifest_path,
        artifact_path=artifact_path,
        run_id=run_id,
        unit_id=unit_id,
        plan_ordinal=plan_ordinal,
        selection_sha256=selection_sha256,
    )
    if existing is not None:
        return PilotWorkResult(existing, _metric_from_artifact(artifact_path))

    task_started = time.monotonic()
    attempts: list[dict[str, Any]] = []

    def record_attempt(url: str, evidence: AttemptEvidence) -> None:
        attempts.append(
            {
                "url": url,
                "attempt": evidence.attempt,
                "status": evidence.status,
                "outcome": evidence.outcome,
                "elapsed_seconds": evidence.elapsed_seconds,
                "detail": evidence.detail,
            }
        )

    profile_label = "eight_worker"
    profile = _load_worker_profiles(root, design.raw)[profile_label][task.product]
    client = VerifiedHttpClient(
        transport=transport,
        max_attempts=int(profile["max_attempts"]),
        timeout_seconds=float(profile["timeout_seconds"]),
        initial_backoff_seconds=float(profile["initial_backoff_seconds"]),
        attempt_callback=record_attempt,
    )
    index_url_values = {str(row["index_object_identity"]) for row in task.rows}
    if len(index_url_values) != 1:
        raise PilotContractError(f"source task has multiple index identities: {unit_id}")
    index_url = next(iter(index_url_values))
    index_started = time.monotonic()
    source_index_missing = False
    try:
        index_payload, index_meta = _load_or_fetch_index(
            run_dir=run_dir, client=client, index_url=index_url
        )
    except HttpContractError as exc:
        last_status = next(
            (item["status"] for item in reversed(attempts) if item["status"] is not None),
            None,
        )
        if last_status != 404:
            raise PilotContractError(
                f"pilot index unavailable for {task.source_object_identity}; "
                f"last_status={last_status}: {exc}"
            ) from exc
        source_index_missing = True
        index_payload = b""
        index_meta = {
            "index_url": index_url,
            "sha256": sha256_bytes(index_payload),
            "size_bytes": 0,
            "http_status": 404,
            "retry_count": 0,
            "cache_status": "CONFIRMED_HTTP_404",
        }
    index_seconds = time.monotonic() - index_started
    index_hash_hex = sha256_bytes(index_payload)
    index_hash = bytes.fromhex(index_hash_hex)
    records = () if source_index_missing else parse_pilot_index(index_payload.decode("utf-8"))

    request_entries: list[dict[str, Any]] = []
    needs_parent_size = False
    for plan in task.rows:
        field = field_registry[str(plan["field_registry_id"])]
        interval_minutes = int(
            (plan["interval_end_utc"] - plan["interval_start_utc"]).total_seconds() // 60
        )
        request = {
            **dict(plan),
            "parameter": field["parameter"],
            "level": field["level"],
            "interval_semantics": field["interval_semantics"],
            "interval_minutes": interval_minutes,
        }
        matches = (
            []
            if source_index_missing
            else [
                (position, record)
                for position, record in enumerate(records)
                if grib_io.record_matches_request(record, request)
            ]
        )
        if len(matches) == 1 and matches[0][0] == len(records) - 1:
            needs_parent_size = True
        request_entries.append(
            {"plan": dict(plan), "field": field, "request": request, "matches": matches}
        )

    parent_size: int | None = None
    parent_probe_bytes = 0
    parent_probe_seconds = 0.0
    parent_probe_retry_count = 0
    if needs_parent_size:
        parent_started = time.monotonic()
        parent_size, parent_evidence = client.fetch_parent_size(task.source_object_identity)
        parent_probe_seconds = time.monotonic() - parent_started
        parent_probe_bytes = parent_evidence.size_bytes
        parent_probe_retry_count = parent_evidence.retry_count

    resolved_by_request: dict[str, dict[str, Any]] = {}
    message_requests: dict[tuple[int, int], list[str]] = defaultdict(list)
    selector_miss = 0
    selector_ambiguity = 0
    for entry in request_entries:
        plan = entry["plan"]
        request_id = str(plan["request_id"])
        matches = entry["matches"]
        if source_index_missing:
            resolved_by_request[request_id] = {
                **entry,
                "selector_status": "SOURCE_INDEX_HTTP_404",
            }
            continue
        if len(matches) == 0:
            selector_miss += 1
            resolved_by_request[request_id] = {**entry, "selector_status": "NOT_FOUND"}
            continue
        if len(matches) > 1:
            selector_ambiguity += 1
            resolved_by_request[request_id] = {**entry, "selector_status": "AMBIGUOUS"}
            continue
        resolved = grib_io.resolve_index_range(records, entry["request"], parent_size_bytes=parent_size)
        range_key = (resolved.record.start_byte, resolved.end_byte)
        message_requests[range_key].append(request_id)
        resolved_by_request[request_id] = {
            **entry,
            "selector_status": "RESOLVED",
            "resolved": resolved,
            "range_key": range_key,
        }

    message_id_by_range = {
        range_key: "MSG_"
        + sha256_bytes(
            canonical_json_bytes(
                {
                    "source_object_identity": task.source_object_identity,
                    "byte_start": range_key[0],
                    "byte_end": range_key[1],
                }
            )
        )
        for range_key in message_requests
    }
    groups = coalesce_exact_adjacent_ranges(
        task.source_object_identity,
        tuple(
            MessageRange(message_id_by_range[key], key[0], key[1])
            for key in sorted(message_requests)
        ),
    )
    payload_by_message: dict[str, bytes] = {}
    group_by_request: dict[str, dict[str, Any]] = {}
    cache = SourceGroupCache(
        run_dir / "pilot/cache/source_groups",
        run_dir / "quarantine/source_groups",
    )
    range_fetch_seconds = 0.0
    range_payload_bytes = 0
    accepted_range_bytes = 0
    range_retry_count = 0
    range_cache_hits = 0
    for group in groups:
        cached = cache.load(group)
        if cached is None:
            fetch_started = time.monotonic()
            evidence = client.fetch_range_span(group.source_uri, group.start, group.end)
            range_fetch_seconds += time.monotonic() - fetch_started
            cache.publish(group, evidence.body)
            payload = evidence.body
            status = evidence.status
            retries = evidence.retry_count
            accepted = evidence.size_bytes
            cache_status = "DOWNLOADED"
        else:
            payload = cached
            status = 206
            retries = 0
            accepted = 0
            cache_status = "VERIFIED_HIT"
            range_cache_hits += 1
        split = split_coalesced_payload(group, payload)
        payload_by_message.update(split)
        range_payload_bytes += len(payload)
        accepted_range_bytes += accepted
        range_retry_count += retries
        leader_message = group.members[0].request_id
        leader_requests = message_requests[
            next(key for key, value in message_id_by_range.items() if value == leader_message)
        ]
        leader_request = sorted(leader_requests)[0]
        for member in group.members:
            range_key = next(key for key, value in message_id_by_range.items() if value == member.request_id)
            for request_id in message_requests[range_key]:
                group_by_request[request_id] = {
                    "group": group,
                    "message_id": member.request_id,
                    "http_status": status,
                    "retry_count": retries if request_id == leader_request else 0,
                    "requested_bytes": range_key[1] - range_key[0] + 1,
                    "accepted_bytes": accepted if request_id == leader_request else 0,
                    "cache_status": cache_status,
                }

    field_state_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    accounting = AcquisitionAccounting({str(row["request_id"]) for row in task.rows})
    decode_seconds = 0.0
    extraction_seconds = 0.0
    physical_violations: list[dict[str, Any]] = []
    terrain_evidence: list[dict[str, Any]] = []
    selector_hits = 0
    extracted_values = 0
    for plan in task.rows:
        request_id = str(plan["request_id"])
        entry = resolved_by_request[request_id]
        field = entry["field"]
        station = _station_for_valid_time(coordinate_rows, plan["valid_time_utc"])
        status = entry["selector_status"]
        if status != "RESOLVED":
            remote_missing = status == "SOURCE_INDEX_HTTP_404"
            disposition = "CONFIRMED_REMOTE_MISSING" if remote_missing else "QUARANTINED"
            reason = (
                "SOURCE_INDEX_HTTP_404"
                if remote_missing
                else "SELECTOR_AMBIGUOUS"
                if status == "AMBIGUOUS"
                else "SELECTOR_NOT_FOUND"
            )
            field_state_rows.append(
                _field_state_row(
                    plan=plan,
                    field=field,
                    run_id=run_id,
                    station=station,
                    source_idx_hash=index_hash,
                    payload_hash=None,
                    byte_start=None,
                    byte_end=None,
                    coverage_flag="MISSING" if remote_missing else "QUARANTINED",
                    missing_reason=reason,
                    decoded_identity=None,
                    values=(None, None, None, None, (None,) * 8, 0),
                )
            )
            ledger_rows.append(
                _ledger_row(
                    plan=plan,
                    run_id=run_id,
                    field=field,
                    disposition=disposition,
                    publication_status=(
                        "MISSING_ROW_PUBLISHED" if remote_missing else "QUARANTINE_ROW_PUBLISHED"
                    ),
                    source_idx_hash=index_hash,
                    payload_hash=None,
                    decoded_identity=None,
                    byte_start=None,
                    byte_end=None,
                    group_id=None,
                    http_status=404 if remote_missing else 200,
                    retry_count=0,
                    requested_bytes=0,
                    accepted_bytes=0,
                )
            )
            accounting.record(
                RequestTerminalResult(request_id, disposition, task.source_object_identity)
            )
            continue

        selector_hits += 1
        resolved = entry["resolved"]
        transport_meta = group_by_request[request_id]
        payload = payload_by_message[transport_meta["message_id"]]
        payload_hash = bytes.fromhex(sha256_bytes(payload))
        try:
            profiled = _profiled_decode_and_extract(
                payload,
                request=entry["request"],
                index_record=resolved.record,
                station=station,
                operators=_operators(field["spatial_contract_id"]),
                regional_operator_id=str(plan["regional_operator_id"]),
                regional_geometry=regional_geometry,
                native_unit=field["native_unit"],
                canonical_unit=field["canonical_unit"],
            )
            decode_seconds += profiled.decode_seconds
            extraction_seconds += profiled.extraction_seconds
            values = _canonical_spatial_values(
                profiled.decoded,
                field["native_unit"],
                field["canonical_unit"],
                profiled.regional_values_native,
                profiled.regional_coverage_mask,
            )
            expected_supports = int(plan["regional_support_count"])
            expected_mask = (1 << expected_supports) - 1 if expected_supports else 0
            if int(values[5]) != expected_mask:
                raise PilotContractError(
                    f"regional coverage is incomplete for {field['field_id']}: "
                    f"mask={int(values[5])} expected={expected_mask}"
                )
            if field["field_id"] == "H14":
                converted_terrain = {
                    era_id: [
                        None
                        if value is None
                        else grib_io.convert_native_to_canonical(
                            float(value), field["native_unit"], field["canonical_unit"]
                        )
                        for value in era_values
                    ]
                    for era_id, era_values in profiled.terrain_values_by_coordinate_era.items()
                }
                terrain_evidence.append(
                    {
                        "request_id": request_id,
                        "values_by_coordinate_era": converted_terrain,
                        "coverage_masks_by_coordinate_era": dict(
                            profiled.terrain_masks_by_coordinate_era
                        ),
                    }
                )
                required_mask = int(design.raw["gates"]["required_regional_coverage_mask"])
                if (
                    set(converted_terrain) != EXPECTED_ERAS
                    or any(mask != required_mask for mask in profiled.terrain_masks_by_coordinate_era.values())
                ):
                    raise PilotContractError("H14 terrain is not finite for both coordinate eras")
            finite_values = _field_value_sequence(values)
            bounds = design.raw["physical_ranges"][field["field_id"]]
            violations = [
                value
                for value in finite_values
                if value < float(bounds[0]) or value > float(bounds[1])
            ]
            if violations:
                physical_violations.append(
                    {
                        "request_id": request_id,
                        "field_registry_id": field["field_id"],
                        "minimum_observed": min(violations),
                        "maximum_observed": max(violations),
                        "allowed": [float(bounds[0]), float(bounds[1])],
                    }
                )
                raise PilotContractError("physical value lies outside the configured obvious-unit range")
            if field["field_id"] != "H14" and not finite_values:
                raise PilotContractError("required KDEN extraction contains no finite values")
            extracted_count = len(finite_values)
            extracted_values += extracted_count
            decoded_identity = _decoded_identity(profiled.decoded)
            field_state_rows.append(
                _field_state_row(
                    plan=plan,
                    field=field,
                    run_id=run_id,
                    station=station,
                    source_idx_hash=index_hash,
                    payload_hash=payload_hash,
                    byte_start=resolved.record.start_byte,
                    byte_end=resolved.end_byte,
                    coverage_flag="PRESENT",
                    missing_reason=None,
                    decoded_identity=decoded_identity,
                    values=values,
                    grid_geometry_id=profiled.decoded.metadata.grid.grid_id,
                )
            )
            disposition = "SUCCESS"
            publication_status = "CANONICAL_ROW_PUBLISHED"
        except (grib_io.GribContractError, PilotContractError) as exc:
            values = (None, None, None, None, (None,) * 8, 0)
            extracted_count = 0
            decoded_identity = canonical_json_bytes(
                {"error_type": type(exc).__name__, "error": str(exc)}
            ).decode("ascii").strip()
            field_state_rows.append(
                _field_state_row(
                    plan=plan,
                    field=field,
                    run_id=run_id,
                    station=station,
                    source_idx_hash=index_hash,
                    payload_hash=payload_hash,
                    byte_start=resolved.record.start_byte,
                    byte_end=resolved.end_byte,
                    coverage_flag="QUARANTINED",
                    missing_reason=f"{type(exc).__name__}: {exc}",
                    decoded_identity=decoded_identity,
                    values=values,
                )
            )
            disposition = "QUARANTINED"
            publication_status = "QUARANTINE_ROW_PUBLISHED"
        ledger_rows.append(
            _ledger_row(
                plan=plan,
                run_id=run_id,
                field=field,
                disposition=disposition,
                publication_status=publication_status,
                source_idx_hash=index_hash,
                payload_hash=payload_hash,
                decoded_identity=decoded_identity,
                byte_start=resolved.record.start_byte,
                byte_end=resolved.end_byte,
                group_id=transport_meta["group"].group_id,
                http_status=int(transport_meta["http_status"]),
                retry_count=int(transport_meta["retry_count"]),
                requested_bytes=int(transport_meta["requested_bytes"]),
                accepted_bytes=int(transport_meta["accepted_bytes"]),
            )
        )
        accounting.record(
            RequestTerminalResult(
                request_id=request_id,
                disposition=disposition,
                source_object_identity=task.source_object_identity,
                transport_group_id=transport_meta["group"].group_id,
                retry_count=int(transport_meta["retry_count"]),
                accepted_bytes=int(transport_meta["accepted_bytes"]),
                extracted_value_count=extracted_count,
            )
        )
    reconciliation = accounting.assert_reconciled(allow_quarantine=True)

    field_state_rows.sort(
        key=lambda row: (
            row["target_day"],
            row["cycle_init_utc"],
            row["product"],
            row["forecast_lead_min"],
            row["field_registry_id"],
            row["station_coord_era"],
        )
    )
    ledger_rows.sort(key=lambda row: (row["retrieval_run_id"], row["request_id"], row["attempt_number"]))
    units_parent = artifact_path.parent
    units_parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{unit_id}.", suffix=".staging", dir=units_parent)
    )
    try:
        try:
            import pyarrow as pa
        except ImportError as exc:
            raise PilotContractError("pyarrow is required for pilot publication") from exc
        field_schema = _load_r14_field_state_schema(root)
        ledger_schema = load_parquet_schema(root, "retrieval_ledger_v375.json")
        parquet_started = time.monotonic()
        field_table = pa.Table.from_pylist(field_state_rows, schema=field_schema)
        ledger_table = pa.Table.from_pylist(ledger_rows, schema=ledger_schema)
        atomic_write_table(
            field_table,
            staging / "field_state.parquet",
            schema=field_schema,
            compression="zstd",
            replace=False,
        )
        atomic_write_table(
            ledger_table,
            staging / "retrieval_ledger.parquet",
            schema=ledger_schema,
            compression="zstd",
            replace=False,
        )
        parquet_seconds = time.monotonic() - parquet_started
        metrics = {
            "schema_version": "KDEN_V375_R14_PILOT_WORK_UNIT_METRICS_V1",
            "run_id": run_id,
            "mode": mode,
            "unit_id": unit_id,
            "base_unit_id": task.base_unit_id,
            "product": task.product,
            "target_day": task.target_day.isoformat(),
            "week_id": task.week_id,
            "cohort": task.cohort,
            "source_object_identity": task.source_object_identity,
            "source_index_http_status": int(index_meta["http_status"]),
            "source_index_confirmed_missing": source_index_missing,
            "request_count": len(task.rows),
            "selector_hit_count": selector_hits,
            "selector_miss_count": selector_miss,
            "selector_ambiguity_count": selector_ambiguity,
            "unique_message_count": len(message_requests),
            "coalesced_range_count": len(groups),
            "range_payload_bytes": range_payload_bytes,
            "network_accepted_range_bytes": accepted_range_bytes,
            "index_payload_bytes": len(index_payload),
            "parent_probe_bytes": parent_probe_bytes,
            "range_retry_count": range_retry_count,
            "index_retry_count": int(index_meta.get("retry_count", 0)),
            "parent_probe_retry_count": parent_probe_retry_count,
            "range_cache_hit_count": range_cache_hits,
            "index_cache_hit": index_meta.get("cache_status") == "VERIFIED_HIT",
            "index_fetch_seconds": index_seconds,
            "parent_probe_seconds": parent_probe_seconds,
            "range_fetch_seconds": range_fetch_seconds,
            "decode_seconds": decode_seconds,
            "extraction_seconds": extraction_seconds,
            "parquet_write_seconds": parquet_seconds,
            "task_wall_seconds": time.monotonic() - task_started,
            "extracted_value_count": extracted_values,
            "physical_violation_count": len(physical_violations),
            "physical_violations": physical_violations,
            "terrain_evidence": terrain_evidence,
            "terminal_accounting": reconciliation,
            "http_attempts": attempts,
            "field_state_sha256": sha256_file(staging / "field_state.parquet"),
            "field_state_size_bytes": (staging / "field_state.parquet").stat().st_size,
            "retrieval_ledger_sha256": sha256_file(staging / "retrieval_ledger.parquet"),
            "retrieval_ledger_size_bytes": (staging / "retrieval_ledger.parquet").stat().st_size,
        }
        atomic_write_json(staging / "metrics.json", metrics, replace=False)
        atomic_publish_directory(staging, artifact_path)
        staging = None
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    receipt = publish_work_unit_manifest(
        project_root=root,
        manifest_path=manifest_path,
        run_id=run_id,
        step_id=STEP_ID,
        request_plan_sha256=selection_sha256,
        unit_id=unit_id,
        plan_ordinal=plan_ordinal,
        artifact_path=artifact_path,
        row_count=len(field_state_rows),
        request_count=len(task.rows),
        accepted_bytes=accepted_range_bytes,
    )
    return PilotWorkResult(receipt, metrics)


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _live_status(
    *,
    run_dir: Path,
    phase: str,
    coordinator: ProgressCoordinator,
    last_unit_id: str | None,
    expected_logical_requests: int,
) -> None:
    atomic_write_json(
        run_dir / "pilot/live_status.json",
        {
            "schema_version": "KDEN_V375_R14_PILOT_LIVE_STATUS_V1",
            "updated_at_utc": utc_now(),
            "phase": phase,
            "completed_work_units": len(coordinator.completed_units),
            "expected_work_units": len(coordinator.expected_units),
            "remaining_work_units": len(coordinator.remaining_units),
            "completed_logical_requests": coordinator.completed_request_count,
            "expected_logical_requests": int(expected_logical_requests),
            "remaining_logical_requests": max(
                0, int(expected_logical_requests) - coordinator.completed_request_count
            ),
            "network_accepted_bytes": coordinator.completed_accepted_bytes,
            "last_committed_unit": last_unit_id,
            "pilot_disk_bytes": _directory_size(run_dir / "pilot"),
        },
    )


def _phase_segment_path(run_dir: Path, phase: str) -> Path:
    stamp = utc_now().replace(":", "").replace("-", "").replace(".", "")
    directory = run_dir / "pilot/benchmark_segments" / phase
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"segment-{stamp}.json"


def _run_phase(
    *,
    root: Path,
    run_id: str,
    run_dir: Path,
    phase: str,
    tasks: Sequence[PilotSourceTask],
    mode: str,
    workers: int,
    ordinals: Mapping[str, int],
    selection_sha256: str,
    design: PilotDesign,
    field_registry: Mapping[str, Mapping[str, str]],
    coordinate_rows: Sequence[Mapping[str, Any]],
    regional_geometry: Mapping[str, Sequence[Mapping[str, Any]]],
    coordinator: ProgressCoordinator,
    pause_requested: Callable[[], bool],
    expected_logical_requests: int,
) -> None:
    remaining = [task for task in tasks if task.unit_id(mode) in coordinator.remaining_units]
    if not remaining:
        return
    started_wall = time.monotonic()
    started_utc = utc_now()
    completed_this_segment: list[PilotWorkResult] = []
    with PersistentHttpTransport(
        pool_connections=workers, pool_maxsize=1
    ) as transport:

        def worker(task: PilotSourceTask) -> PilotWorkResult:
            return _process_source_task(
                root=root,
                run_id=run_id,
                task=task,
                mode=mode,
                plan_ordinal=ordinals[task.unit_id(mode)],
                selection_sha256=selection_sha256,
                design=design,
                field_registry=field_registry,
                coordinate_rows=coordinate_rows,
                regional_geometry=regional_geometry,
                transport=transport,
            )

        def commit(result: PilotWorkResult) -> None:
            coordinator.commit(result.receipt)
            completed_this_segment.append(result)
            _live_status(
                run_dir=run_dir,
                phase=phase,
                coordinator=coordinator,
                last_unit_id=result.receipt.unit_id,
                expected_logical_requests=expected_logical_requests,
            )

        summary = execute_bounded(
            remaining,
            worker=worker,
            commit=commit,
            max_workers=workers,
            pause_requested=pause_requested,
        )
        transport_snapshot = transport.snapshot()
    elapsed = time.monotonic() - started_wall
    segment = {
        "schema_version": "KDEN_V375_PILOT_BENCHMARK_SEGMENT_V1",
        "phase": phase,
        "mode": mode,
        "workers": workers,
        "started_at_utc": started_utc,
        "completed_at_utc": utc_now(),
        "wall_seconds": elapsed,
        "submitted_count": summary.submitted_count,
        "committed_count": summary.committed_count,
        "remaining_count": summary.remaining_count,
        "paused": summary.paused,
        "request_count": sum(int(result.metrics["request_count"]) for result in completed_this_segment),
        "range_payload_bytes": sum(
            int(result.metrics["range_payload_bytes"]) for result in completed_this_segment
        ),
        "network_accepted_range_bytes": sum(
            int(result.metrics["network_accepted_range_bytes"])
            for result in completed_this_segment
        ),
        "transport": transport_snapshot,
    }
    atomic_write_json(_phase_segment_path(run_dir, phase), segment, replace=False)
    if summary.paused or pause_requested():
        coordinator.snapshot("PAUSED")
        raise PauseRequested(f"pilot paused after atomic {phase} work units")


def _read_all_unit_metrics(run_dir: Path, mode: str) -> list[dict[str, Any]]:
    return [
        _read_json(path)
        for path in sorted((run_dir / "pilot" / mode / "units").glob("*/metrics.json"))
    ]


def _read_all_unit_tables(root: Path, run_dir: Path, mode: str, filename: str) -> Any:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise PilotContractError("pyarrow is required for pilot closeout") from exc
    paths = sorted((run_dir / "pilot" / mode / "units").glob(f"*/{filename}"))
    if not paths:
        raise PilotContractError(f"pilot has no {mode} {filename} artifacts")
    tables = [pq.read_table(path) for path in paths]
    return pa.concat_tables(tables)


def _precision_value_rows(field_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in field_rows:
        identity = (
            f"{row['target_day']}|{row['cycle_init_utc'].isoformat()}|{row['product']}|"
            f"{int(row['forecast_lead_min'])}|{row['field_registry_id']}|{row['station_coord_era']}"
        )
        values: list[tuple[str, int, float]] = []
        if row["bi_value"] is not None:
            values.append(("BI", 0, float(row["bi_value"])))
        if row["nn_value"] is not None:
            values.append(("NN", 0, float(row["nn_value"])))
        values.extend(
            ("TILE", index, float(value))
            for index, value in enumerate(row["tile_values"] or [])
            if value is not None
        )
        values.extend(
            ("REGIONAL", index, float(row[f"regional_value_{index:02d}"]))
            for index in range(8)
            if row[f"regional_value_{index:02d}"] is not None
        )
        for kind, index, value in values:
            rows.append(
                {
                    "value_id": f"{identity}|{kind}|{index}",
                    "product": row["product"],
                    "field_registry_id": row["field_registry_id"],
                    "value_kind": kind,
                    "value": value,
                }
            )
    return rows


def _float32_roundtrip(value: float) -> float:
    return float(struct.unpack("!f", struct.pack("!f", float(value)))[0])


def _precision_report(
    *,
    run_dir: Path,
    value_rows: Sequence[Mapping[str, Any]],
    design: PilotDesign,
) -> dict[str, Any]:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise PilotContractError("pyarrow is required for precision comparison") from exc
    base_fields = [
        pa.field("value_id", pa.string(), nullable=False),
        pa.field("product", pa.dictionary(pa.int16(), pa.string()), nullable=False),
        pa.field("field_registry_id", pa.dictionary(pa.int16(), pa.string()), nullable=False),
        pa.field("value_kind", pa.dictionary(pa.int16(), pa.string()), nullable=False),
    ]
    schema64 = pa.schema([*base_fields, pa.field("value", pa.float64(), nullable=False)])
    schema32 = pa.schema([*base_fields, pa.field("value", pa.float32(), nullable=False)])
    table64 = pa.Table.from_pylist(value_rows, schema=schema64)
    table32 = pa.Table.from_pylist(value_rows, schema=schema32)
    destination = run_dir / "pilot/precision"
    destination.mkdir(parents=True, exist_ok=True)
    path64 = destination / "values_float64.parquet"
    path32 = destination / "values_float32.parquet"
    atomic_write_table(table64, path64, schema=schema64, compression="zstd", replace=True)
    atomic_write_table(table32, path32, schema=schema32, compression="zstd", replace=True)
    absolute_tolerance = float(design.raw["gates"]["float32_absolute_tolerance"])
    relative_tolerance = float(design.raw["gates"]["float32_relative_tolerance"])
    failures = 0
    max_absolute = 0.0
    max_relative = 0.0
    for row in value_rows:
        original = float(row["value"])
        reconstructed = _float32_roundtrip(original)
        absolute = abs(reconstructed - original)
        relative = absolute / max(abs(original), 1e-30)
        max_absolute = max(max_absolute, absolute)
        max_relative = max(max_relative, relative)
        if absolute > absolute_tolerance and relative > relative_tolerance:
            failures += 1
    return {
        "value_count": len(value_rows),
        "float64": {
            "path": relative_to_root(run_dir.parents[1], path64),
            "size_bytes": path64.stat().st_size,
            "sha256": sha256_file(path64),
        },
        "float32": {
            "path": relative_to_root(run_dir.parents[1], path32),
            "size_bytes": path32.stat().st_size,
            "sha256": sha256_file(path32),
        },
        "max_absolute_difference": max_absolute,
        "max_relative_difference": max_relative,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "failure_count": failures,
        "parity_pass": failures == 0,
        "selected_precision": design.raw["gates"]["selected_precision"],
        "selection_reason": "retain frozen float64 because projected storage fits; float32 remains comparison evidence only",
    }


def _parquet_buffer_size(table: Any) -> int:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise PilotContractError("pyarrow is required for output-size profiling") from exc
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd", use_dictionary=True)
    return sink.getvalue().size


def _output_size_report(
    field_table: Any,
    field_rows: Sequence[Mapping[str, Any]],
    field_registry: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise PilotContractError("pyarrow is required for output-size profiling") from exc

    def take(indices: Sequence[int]) -> Any:
        return field_table.take(pa.array(indices, type=pa.int64()))

    def sizes(table: Any) -> dict[str, Any]:
        compressed = _parquet_buffer_size(table)
        uncompressed = int(table.nbytes)
        return {
            "arrow_uncompressed_bytes": uncompressed,
            "isolated_zstd_bytes": compressed,
            "uncompressed_to_zstd_ratio": uncompressed / compressed if compressed else 0.0,
        }

    by_product: dict[str, Any] = {}
    by_field: dict[str, Any] = {}
    by_spatial: dict[str, Any] = {}
    for product in PRODUCTS:
        indices = [index for index, row in enumerate(field_rows) if row["product"] == product]
        subset = take(indices)
        by_product[product] = {
            "row_count": len(indices),
            **sizes(subset),
        }
    for field_id in EXPECTED_FIELDS:
        indices = [index for index, row in enumerate(field_rows) if row["field_registry_id"] == field_id]
        subset = take(indices)
        by_field[field_id] = {
            "product": field_registry[field_id]["product"],
            "spatial_contract_id": field_registry[field_id]["spatial_contract_id"],
            "row_count": len(indices),
            **sizes(subset),
        }
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(field_rows):
        grouped[field_registry[str(row["field_registry_id"])]["spatial_contract_id"]].append(index)
    for spatial_id, indices in sorted(grouped.items()):
        by_spatial[spatial_id] = {
            "row_count": len(indices),
            **sizes(take(indices)),
        }
    return {
        "whole_primary_field_table": {
            "row_count": len(field_rows),
            **sizes(field_table),
        },
        "by_product": by_product,
        "by_field": by_field,
        "by_spatial_shape": by_spatial,
    }


def pilot_preflight(project_root: Path | str) -> dict[str, Any]:
    """Validate the immutable pilot design and sealed inputs without network I/O."""

    paths = load_project_paths(project_root)
    design = load_pilot_design(paths.root)
    registry_verification = verify_r14_registry_bundle(paths.root)
    spatial = validate_r14_spatial_contract(paths.root)
    selection = build_pilot_selection(
        paths.root,
        "kdenv375-s04-validation-20260914T000000Z-preflight",
        design,
        publish=False,
    )
    schedule_rows = _schedule_rows(paths.root, design.target_days)
    all_states, parity_states, evidence = _selection_state_keys(design, schedule_rows)
    cycle_roles = {row["cycle_role"] for row in evidence["daily_state_selection"]}
    lead_roles = {row["lead_role"] for row in evidence["daily_state_selection"]}
    horizon_classes = {
        row["horizon_class"]
        for row in evidence["daily_state_selection"]
        if row["product"] == "wrfsfcf"
    }
    return {
        "status": "READY_FOR_OWNER_PILOT",
        "network_requests_made": 0,
        "pilot_week_count": len(design.weeks),
        "pilot_target_day_count": len(design.target_days),
        "daily_product_state_count": len(evidence["daily_state_selection"]),
        "selected_all_field_state_count": len(all_states),
        "selected_parity_field_state_count": len(parity_states),
        "selected_request_count": len(selection.rows),
        "selected_source_object_count": len(selection.tasks),
        "selected_field_ids": list(EXPECTED_FIELDS),
        "seasons": sorted({week.season for week in design.weeks}),
        "archive_strata": sorted({week.archive_stratum for week in design.weeks}),
        "coordinate_eras": sorted({week.coordinate_era for week in design.weeks}),
        "dst_transitions": sorted(
            week.required_transition for week in design.weeks if week.required_transition
        ),
        "cycle_roles": sorted(cycle_roles),
        "lead_roles": sorted(lead_roles),
        "hourly_horizon_classes": sorted(horizon_classes),
        "scope_id": R14_SCOPE_ID,
        "registry_bundle_sha256": registry_verification["bundle"]["bundle_sha256"],
        "regional_spatial_contract": spatial,
        "product_plan_sha256": {
            product: selection.manifest["product_plan_sha256"][product]
            for product in PRODUCTS
        },
        "lead_policy": design.raw["lead_policy"],
        "primary_workers": 8,
        "long_running_execution_deferred_to_owner": True,
    }


def _selector_report(
    field_rows: Sequence[Mapping[str, Any]],
    ledger_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_field: dict[str, Any] = {}
    for field_id in EXPECTED_FIELDS:
        rows = [row for row in field_rows if row["field_registry_id"] == field_id]
        counts = Counter(str(row["coverage_flag"]) for row in rows)
        ambiguity = sum(
            str(row["missing_reason"] or "").startswith("SELECTOR_AMBIGUOUS")
            for row in rows
        )
        misses = sum(
            str(row["missing_reason"] or "").startswith("SELECTOR_NOT_FOUND")
            for row in rows
        )
        source_missing = sum(
            str(row["missing_reason"] or "").startswith("SOURCE_INDEX_HTTP_404")
            for row in rows
        )
        total = len(rows)
        selector_hits = total - ambiguity - misses - source_missing
        by_field[field_id] = {
            "request_count": total,
            "selector_hit_count": selector_hits,
            "validated_count": counts["PRESENT"],
            "explicitly_blocked_count": counts["MISSING"] + counts["QUARANTINED"],
            "source_missing_count": source_missing,
            "selector_not_found_count": misses,
            "selector_ambiguity_count": ambiguity,
            "hit_rate": selector_hits / total if total else 0.0,
            "ambiguity_rate": ambiguity / total if total else 0.0,
        }
    terminal = Counter(str(row["terminal_disposition"]) for row in ledger_rows)
    return {
        "request_count": len(ledger_rows),
        "success_count": terminal["SUCCESS"],
        "confirmed_remote_missing_count": terminal["CONFIRMED_REMOTE_MISSING"],
        "quarantined_count": terminal["QUARANTINED"],
        "selector_hit_count": sum(row["selector_hit_count"] for row in by_field.values()),
        "hit_rate": (
            sum(row["selector_hit_count"] for row in by_field.values()) / len(ledger_rows)
            if ledger_rows
            else 0.0
        ),
        "ambiguity_count": sum(row["selector_ambiguity_count"] for row in by_field.values()),
        "ambiguity_rate": (
            sum(row["selector_ambiguity_count"] for row in by_field.values())
            / len(ledger_rows)
            if ledger_rows
            else 0.0
        ),
        "by_field": by_field,
    }


def _decoded_interval_report(
    field_rows: Sequence[Mapping[str, Any]],
    field_registry: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    by_field: dict[str, Any] = {}
    for field_id in EXPECTED_FIELDS:
        rows = [row for row in field_rows if row["field_registry_id"] == field_id]
        decoded = [row for row in rows if row["coverage_flag"] == "PRESENT"]
        blocked = [row for row in rows if row["coverage_flag"] != "PRESENT"]
        by_field[field_id] = {
            "interval_semantics": field_registry[field_id]["interval_semantics"],
            "interval_minutes": int(field_registry[field_id]["interval_minutes"]),
            "decoded_key_and_interval_validated_count": len(decoded),
            "explicitly_blocked_count": len(blocked),
            "status": "VALIDATED" if decoded else "EXPLICITLY_BLOCKED",
        }
    return {
        "decoded_and_interval_validated_count": sum(
            row["decoded_key_and_interval_validated_count"] for row in by_field.values()
        ),
        "explicitly_blocked_count": sum(
            row["explicitly_blocked_count"] for row in by_field.values()
        ),
        "all_fields_validated_or_blocked": all(
            row["decoded_key_and_interval_validated_count"]
            + row["explicitly_blocked_count"]
            > 0
            for row in by_field.values()
        ),
        "by_field": by_field,
    }


def _physical_range_report(
    field_rows: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    design: PilotDesign,
) -> dict[str, Any]:
    by_field: dict[str, Any] = {}
    violation_count = 0
    for field_id in EXPECTED_FIELDS:
        values: list[float] = []
        for row in field_rows:
            if row["field_registry_id"] != field_id:
                continue
            for value in (row["bi_value"], row["nn_value"]):
                if value is not None and math.isfinite(float(value)):
                    values.append(float(value))
            values.extend(
                float(value)
                for value in (row["tile_values"] or [])
                if value is not None and math.isfinite(float(value))
            )
            values.extend(
                float(row[f"regional_value_{index:02d}"])
                for index in range(8)
                if row[f"regional_value_{index:02d}"] is not None
                and math.isfinite(float(row[f"regional_value_{index:02d}"]))
            )
        lower, upper = map(float, design.raw["physical_ranges"][field_id])
        failures = sum(value < lower or value > upper for value in values)
        violation_count += failures
        by_field[field_id] = {
            "value_count": len(values),
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "allowed_minimum": lower,
            "allowed_maximum": upper,
            "violation_count": failures,
            "status": "PASS" if failures == 0 else "FAIL",
        }
    rejected_violations = [
        violation
        for metric in metrics
        for violation in metric.get("physical_violations", [])
    ]
    total_violations = violation_count + len(rejected_violations)
    return {
        "violation_count": total_violations,
        "rejected_violation_evidence": rejected_violations,
        "obvious_unit_gate_pass": total_violations == 0,
        "by_field": by_field,
    }


def _regional_spatial_report(
    field_rows: Sequence[Mapping[str, Any]],
    metrics: Sequence[Mapping[str, Any]],
    design: PilotDesign,
) -> dict[str, Any]:
    required_mask = int(design.raw["gates"]["required_regional_coverage_mask"])
    local_only = {"H02", "H07"}
    by_field: dict[str, Any] = {}
    for field_id in EXPECTED_FIELDS:
        present = [
            row
            for row in field_rows
            if row["field_registry_id"] == field_id and row["coverage_flag"] == "PRESENT"
        ]
        expected_supports = 0 if field_id in local_only else 8
        valid_rows = 0
        for row in present:
            values = [row[f"regional_value_{index:02d}"] for index in range(8)]
            if expected_supports == 0:
                valid = (
                    int(row["regional_support_count"]) == 0
                    and int(row["regional_coverage_mask"]) == 0
                    and row["regional_operator"] is None
                    and all(value is None for value in values)
                )
            else:
                valid = (
                    int(row["regional_support_count"]) == 8
                    and int(row["regional_coverage_mask"]) == required_mask
                    and row["regional_operator"] is not None
                    and all(value is not None and math.isfinite(float(value)) for value in values)
                )
            valid_rows += int(valid)
        by_field[field_id] = {
            "present_row_count": len(present),
            "expected_support_count": expected_supports,
            "contract_valid_row_count": valid_rows,
            "all_present_rows_contract_valid": bool(present) and valid_rows == len(present),
        }

    terrain_entries = [
        entry
        for metric in metrics
        for entry in metric.get("terrain_evidence", [])
    ]
    terrain_by_era: dict[str, Any] = {}
    terrain_lower, terrain_upper = map(float, design.raw["physical_ranges"]["H14"])
    for era_id in sorted(EXPECTED_ERAS):
        values = [
            value
            for entry in terrain_entries
            for value in entry.get("values_by_coordinate_era", {}).get(era_id, [])
        ]
        masks = [
            int(entry.get("coverage_masks_by_coordinate_era", {}).get(era_id, 0))
            for entry in terrain_entries
            if era_id in entry.get("coverage_masks_by_coordinate_era", {})
        ]
        finite = len(values) == 8 and all(
            value is not None and math.isfinite(float(value)) for value in values
        )
        in_range = finite and all(
            terrain_lower <= float(value) <= terrain_upper for value in values
        )
        terrain_by_era[era_id] = {
            "support_count": len(values),
            "coverage_masks": masks,
            "all_finite": finite,
            "all_within_obvious_terrain_range": in_range,
            "minimum": min(map(float, values)) if finite else None,
            "maximum": max(map(float, values)) if finite else None,
        }
    terrain_pass = len(terrain_entries) == 1 and all(
        row["all_finite"]
        and row["all_within_obvious_terrain_range"]
        and row["coverage_masks"] == [required_mask]
        for row in terrain_by_era.values()
    )
    return {
        "spatial_contract_id": R14_SPATIAL_CONTRACT_ID,
        "support_order": list(EXPECTED_SUPPORT_ORDER),
        "required_coverage_mask": required_mask,
        "by_field": by_field,
        "all_r14_field_operators_validated": all(
            row["all_present_rows_contract_valid"] for row in by_field.values()
        ),
        "h14_single_decode_evidence_count": len(terrain_entries),
        "h14_terrain_by_coordinate_era": terrain_by_era,
        "h14_terrain_support_pass": terrain_pass,
        "dynamic_supports_have_finite_corresponding_h14": terrain_pass,
        "full_grid_cells_persisted": 0,
    }


def _special_interval_report(
    field_rows: Sequence[Mapping[str, Any]],
    selection: PilotSelection,
    design: PilotDesign,
) -> dict[str, Any]:
    h38_fh00 = [
        row
        for row in field_rows
        if row["field_registry_id"] == "H38"
        and int(row["forecast_lead_min"]) == 0
        and row["coverage_flag"] == "PRESENT"
    ]
    h38_positive = [
        row
        for row in field_rows
        if row["field_registry_id"] == "H38"
        and int(row["forecast_lead_min"]) > 0
        and row["coverage_flag"] == "PRESENT"
    ]
    h38_fh00_pass = bool(h38_fh00) and all(
        row["step_type"] == "accum"
        and row["interval_start_utc"] == row["interval_end_utc"] == row["valid_time_utc"]
        for row in h38_fh00
    )
    h38_positive_pass = bool(h38_positive) and all(
        row["step_type"] == "accum"
        and int((row["interval_end_utc"] - row["interval_start_utc"]).total_seconds()) == 3600
        and row["interval_end_utc"] == row["valid_time_utc"]
        for row in h38_positive
    )

    repeated_leads = {15, 30, 45, 60}
    anchor_days = {week.start_date for week in design.weeks}
    q_rows = [
        row
        for row in selection.rows
        if row["field_registry_id"] == "Q05"
        and row["target_day"] in anchor_days
        and int(row["forecast_lead_min"]) in repeated_leads
    ]
    candidates: dict[tuple[Any, Any], list[Mapping[str, Any]]] = defaultdict(list)
    for row in q_rows:
        candidates[(row["target_day"], row["cycle_init_utc"])].append(row)
    by_cycle = {
        key: rows
        for key, rows in candidates.items()
        if {int(row["forecast_lead_min"]) for row in rows} == repeated_leads
    }
    q_block_pass = len(by_cycle) == len(design.weeks) and all(
        {int(row["forecast_lead_min"]) for row in rows} == repeated_leads
        and len({row["source_object_identity"] for row in rows}) == 1
        for rows in by_cycle.values()
    )
    return {
        "h38_fh00_present_count": len(h38_fh00),
        "h38_fh00_zero_minute_accumulation_pass": h38_fh00_pass,
        "h38_positive_lead_present_count": len(h38_positive),
        "h38_positive_lead_one_hour_accumulation_pass": h38_positive_pass,
        "q05_repeated_block_cycle_count": len(by_cycle),
        "q05_repeated_block_leads_min": sorted(repeated_leads),
        "q05_repeated_blocks_share_f01_parent_and_remain_unambiguous": q_block_pass,
    }


def _h16_q05_parity_report(
    field_rows: Sequence[Mapping[str, Any]], design: PilotDesign
) -> dict[str, Any]:
    parity_ids = {"H16", "Q05"}
    indexed: dict[tuple[Any, ...], dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in field_rows:
        field_id = str(row["field_registry_id"])
        if field_id not in parity_ids or row["coverage_flag"] != "PRESENT":
            continue
        key = (
            row["target_day"],
            row["cycle_init_utc"],
            int(row["forecast_lead_min"]),
            row["valid_time_utc"],
            row["station_coord_era"],
        )
        indexed[key][field_id] = row
    tolerance = float(design.raw["gates"]["h16_q05_absolute_tolerance"])
    comparisons: list[dict[str, Any]] = []
    for key, pair in sorted(indexed.items(), key=lambda item: str(item[0])):
        if set(pair) != parity_ids:
            continue
        comparison_columns = [
            ("BI", "bi_value"),
            ("NN", "nn_value"),
            *[
                (f"REGIONAL_{index:02d}", f"regional_value_{index:02d}")
                for index in range(8)
            ],
        ]
        for operator, column in comparison_columns:
            left = pair["H16"][column]
            right = pair["Q05"][column]
            if left is None or right is None:
                continue
            difference = abs(float(left) - float(right))
            comparisons.append(
                {
                    "target_day": key[0].isoformat(),
                    "cycle_init_utc": key[1].isoformat(),
                    "forecast_lead_min": key[2],
                    "operator": operator,
                    "H16": float(left),
                    "Q05": float(right),
                    "absolute_difference": difference,
                    "pass": difference <= tolerance,
                }
            )
    required = int(design.raw["gates"]["minimum_h16_q05_pairs"])
    failures = sum(not row["pass"] for row in comparisons)
    return {
        "comparison_count": len(comparisons),
        "minimum_required": required,
        "absolute_tolerance": tolerance,
        "maximum_absolute_difference": max(
            (row["absolute_difference"] for row in comparisons), default=None
        ),
        "failure_count": failures,
        "parity_pass": len(comparisons) >= required and failures == 0,
        "comparisons": comparisons,
    }


def _sum_metric(metrics: Sequence[Mapping[str, Any]], name: str) -> float:
    return sum(float(row.get(name, 0)) for row in metrics)


def _segment_report(run_dir: Path, phase: str, expected_requests: int) -> dict[str, Any]:
    segment_paths = sorted((run_dir / "pilot/benchmark_segments" / phase).glob("*.json"))
    segments = [_read_json(path) for path in segment_paths]
    request_count = sum(int(row["request_count"]) for row in segments)
    wall_seconds = sum(float(row["wall_seconds"]) for row in segments)
    return {
        "phase": phase,
        "segment_count": len(segments),
        "request_count": request_count,
        "expected_request_count": expected_requests,
        "wall_seconds": wall_seconds,
        "logical_requests_per_second": request_count / wall_seconds if wall_seconds else 0.0,
        "range_payload_bytes": sum(int(row["range_payload_bytes"]) for row in segments),
        "network_accepted_range_bytes": sum(
            int(row["network_accepted_range_bytes"]) for row in segments
        ),
        "complete": request_count == expected_requests,
        "segments": [relative_to_root(run_dir.parents[1], path) for path in segment_paths],
    }


def _throughput_report(
    run_dir: Path,
    primary_metrics: Sequence[Mapping[str, Any]],
    selection: PilotSelection,
    design: PilotDesign,
) -> dict[str, Any]:
    expected = sum(len(task.rows) for task in selection.tasks)
    eight = _segment_report(run_dir, "primary_eight_worker", expected)
    eight_metrics = list(primary_metrics)
    eight_retry = int(
        _sum_metric(eight_metrics, "range_retry_count")
        + _sum_metric(eight_metrics, "index_retry_count")
        + _sum_metric(eight_metrics, "parent_probe_retry_count")
    )
    eight_rate = eight["logical_requests_per_second"]
    eight_retry_rate = eight_retry / expected if expected else 0.0
    eight_safe = eight["complete"] and eight_rate > 0.0
    return {
        "four_worker_diagnostic": {
            "status": "NOT_RUN_OPTIONAL",
            "reason": "R14 production starts from the previously selected eight-worker profile",
        },
        "eight_worker": {**eight, "retry_count": eight_retry, "retry_rate": eight_retry_rate},
        "selected_workers": 8,
        "selected_logical_requests_per_second": eight_rate,
        "selection_reason": "the R14 bounded primary phase completed through the required shared eight-worker profile",
        "eight_worker_primary_complete": eight_safe,
        "benchmark_complete": eight_safe,
    }


def _rebuild_report(
    primary_metrics: Sequence[Mapping[str, Any]],
    rebuild_metrics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    primary = {str(row["base_unit_id"]): row for row in primary_metrics}
    rebuild = {str(row["base_unit_id"]): row for row in rebuild_metrics}
    comparisons: list[dict[str, Any]] = []
    for base_unit_id in sorted(set(primary) | set(rebuild)):
        left = primary.get(base_unit_id)
        right = rebuild.get(base_unit_id)
        comparisons.append(
            {
                "base_unit_id": base_unit_id,
                "primary_field_state_sha256": None if left is None else left["field_state_sha256"],
                "rebuild_field_state_sha256": None if right is None else right["field_state_sha256"],
                "hash_identical": left is not None
                and right is not None
                and left["field_state_sha256"] == right["field_state_sha256"],
            }
        )
    failures = sum(not row["hash_identical"] for row in comparisons)
    return {
        "work_unit_comparison_count": len(comparisons),
        "failure_count": failures,
        "value_identical": failures == 0 and bool(comparisons),
        "hash_stable": failures == 0 and bool(comparisons),
        "comparisons": comparisons,
    }


def _resume_audit(
    *,
    root: Path,
    run_id: str,
    selection: PilotSelection,
    expected_units: Mapping[str, int],
) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    reopened = ProgressCoordinator(
        project_root=root,
        run_dir=f"runs/{run_id}/pilot",
        run_id=run_id,
        step_id=STEP_ID,
        request_plan_sha256=selection.selection_sha256,
        expected_units=expected_units,
    )
    reopened.verify_published()
    first = selection.tasks[0]
    unit_id = first.unit_id(PRIMARY_MODE)
    artifact_path = run_dir / "pilot" / PRIMARY_MODE / "units" / unit_id
    manifest_path = run_dir / "pilot/manifests" / PRIMARY_MODE / f"{unit_id}.json"
    receipt = _existing_receipt(
        root=root,
        manifest_path=manifest_path,
        artifact_path=artifact_path,
        run_id=run_id,
        unit_id=unit_id,
        plan_ordinal=expected_units[unit_id],
        selection_sha256=selection.selection_sha256,
    )
    if receipt is None:
        raise PilotContractError("resume audit could not reopen a completed primary unit")
    journal_path = run_dir / "pilot/progress/completions.jsonl"
    before_hash = sha256_file(journal_path)
    before_lines = len(journal_path.read_bytes().splitlines())
    artifact_hash = sha256_path(artifact_path)
    reopened.commit(receipt)
    after_hash = sha256_file(journal_path)
    after_lines = len(journal_path.read_bytes().splitlines())
    reopened.verify_published()
    return {
        "audit_method": "reopen durable coordinator and replay one completed receipt",
        "completed_count_after_reopen": len(reopened.completed_units),
        "journal_sha256_before_replay": before_hash,
        "journal_sha256_after_replay": after_hash,
        "journal_line_count_before_replay": before_lines,
        "journal_line_count_after_replay": after_lines,
        "replayed_artifact_sha256": artifact_hash,
        "duplicate_free": before_lines == after_lines,
        "change_free": before_hash == after_hash and artifact_hash == sha256_path(artifact_path),
        "pass": before_lines == after_lines and before_hash == after_hash,
    }


def _disk_and_duration_projection(
    *,
    root: Path,
    run_dir: Path,
    selection: PilotSelection,
    primary_metrics: Sequence[Mapping[str, Any]],
    throughput: Mapping[str, Any],
    precision: Mapping[str, Any],
    design: PilotDesign,
) -> dict[str, Any]:
    plan_manifests = {product: _read_json(root / PLAN_MANIFEST[product]) for product in PRODUCTS}
    full_requests = sum(int(value["request_row_count"]) for value in plan_manifests.values())
    pilot_requests = len(selection.rows)
    pilot_output_bytes = sum(
        int(row["field_state_size_bytes"]) + int(row["retrieval_ledger_size_bytes"])
        for row in primary_metrics
    )
    output_bytes_per_request = pilot_output_bytes / pilot_requests
    projected_output_bytes = math.ceil(output_bytes_per_request * full_requests)
    selected_rate = float(throughput["selected_logical_requests_per_second"])
    projected_seconds = full_requests / selected_rate if selected_rate else math.inf
    workers = int(throughput["selected_workers"])
    maximum_source_group_bytes = max(
        (int(row["range_payload_bytes"]) for row in primary_metrics), default=0
    )
    projected_temporary_bytes = maximum_source_group_bytes * workers * 2
    immutable_input_bytes = sum(
        _directory_size(root / PLAN_DIRECTORY[product])
        + (root / PLAN_MANIFEST[product]).stat().st_size
        for product in PRODUCTS
    )
    projected_incremental_bytes = projected_output_bytes + projected_temporary_bytes
    margin_fraction = float(design.raw["gates"]["disk_safety_margin_fraction"])
    required_with_margin = math.ceil(projected_incremental_bytes * (1.0 + margin_fraction))
    available = shutil.disk_usage(root).free
    return {
        "full_history_logical_request_count": full_requests,
        "pilot_logical_request_count": pilot_requests,
        "pilot_primary_output_bytes": pilot_output_bytes,
        "pilot_output_bytes_per_request": output_bytes_per_request,
        "projected_full_history_output_bytes": projected_output_bytes,
        "projected_temporary_working_bytes": projected_temporary_bytes,
        "immutable_plan_input_bytes": immutable_input_bytes,
        "projected_incremental_disk_bytes_before_margin": projected_incremental_bytes,
        "projected_total_footprint_before_margin": immutable_input_bytes
        + projected_incremental_bytes,
        "safety_margin_fraction": margin_fraction,
        "required_disk_bytes_with_margin": required_with_margin,
        "owner_storage_available_bytes_at_closeout": available,
        "disk_gate_pass": required_with_margin <= available,
        "selected_workers": workers,
        "selected_logical_requests_per_second": selected_rate,
        "projected_duration_seconds": None if not math.isfinite(projected_seconds) else projected_seconds,
        "projected_duration_hours": (
            None if not math.isfinite(projected_seconds) else projected_seconds / 3600.0
        ),
        "selected_encoding": design.raw["gates"]["selected_precision"],
        "selected_compression": design.raw["gates"]["selected_compression"],
        "float32_storage_bytes_in_pilot_comparison": precision["float32"]["size_bytes"],
        "float64_storage_bytes_in_pilot_comparison": precision["float64"]["size_bytes"],
        "raw_retention_decision": design.raw["runtime"][
            "full_history_raw_retention_decision"
        ],
        "pilot_cache_bytes_used_for_rebuild": _directory_size(run_dir / "pilot/cache"),
    }


def _resource_report(run_dir: Path, primary_metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    return {
        "process_peak_memory_bytes": peak_bytes,
        "pilot_directory_bytes": _directory_size(run_dir / "pilot"),
        "temporary_cache_bytes": _directory_size(run_dir / "pilot/cache"),
        "maximum_work_unit_range_payload_bytes": max(
            (int(row["range_payload_bytes"]) for row in primary_metrics), default=0
        ),
    }


def _retrieval_report(metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    request_count = int(_sum_metric(metrics, "request_count"))
    unique_messages = int(_sum_metric(metrics, "unique_message_count"))
    groups = int(_sum_metric(metrics, "coalesced_range_count"))
    index_network_bytes = sum(
        0 if row["index_cache_hit"] else int(row["index_payload_bytes"]) for row in metrics
    )
    retries = int(
        _sum_metric(metrics, "range_retry_count")
        + _sum_metric(metrics, "index_retry_count")
        + _sum_metric(metrics, "parent_probe_retry_count")
    )
    return {
        "logical_request_count": request_count,
        "unique_message_count": unique_messages,
        "transport_range_group_count": groups,
        "message_to_range_group_ratio": unique_messages / groups if groups else 0.0,
        "coalesced_message_savings_count": unique_messages - groups,
        "range_payload_bytes": int(_sum_metric(metrics, "range_payload_bytes")),
        "network_accepted_source_range_bytes": int(
            _sum_metric(metrics, "network_accepted_range_bytes")
        ),
        "network_accepted_index_bytes": index_network_bytes,
        "network_accepted_parent_probe_bytes": int(
            _sum_metric(metrics, "parent_probe_bytes")
        ),
        "retry_count": retries,
        "timing_seconds": {
            "index_fetch": _sum_metric(metrics, "index_fetch_seconds"),
            "parent_probe": _sum_metric(metrics, "parent_probe_seconds"),
            "range_fetch": _sum_metric(metrics, "range_fetch_seconds"),
            "decode": _sum_metric(metrics, "decode_seconds"),
            "extraction": _sum_metric(metrics, "extraction_seconds"),
            "parquet_write": _sum_metric(metrics, "parquet_write_seconds"),
            "summed_work_unit_wall": _sum_metric(metrics, "task_wall_seconds"),
        },
    }


def _owner_report_markdown(report: Mapping[str, Any]) -> str:
    gates = report["gates"]
    selector = report["selector_validation"]
    throughput = report["worker_profile_decision"]
    projection = report["projection"]
    retrieval = report["retrieval"]
    duration = projection["projected_duration_hours"]
    duration_text = "unavailable" if duration is None else f"{duration:.2f} hours"
    lines = [
        "# KDEN v3.75 Step 04 R14 confirmation pilot",
        "",
        f"**Status:** {report['status']}",
        "",
        f"Run: `{report['run_id']}`",
        f"Scope: `{R14_SCOPE_ID}`",
        "",
        "## Decision",
        "",
        f"- Lead policy remains `{report['lead_policy']}`.",
        f"- Selected safe worker profile: **{throughput['selected_workers']} workers**.",
        f"- Selected physical encoding/compression: **{projection['selected_encoding']} / {projection['selected_compression']}**.",
        f"- Full-history raw retention: `{projection['raw_retention_decision']}`.",
        "",
        "## Pilot result",
        "",
        f"- Logical requests: {retrieval['logical_request_count']:,}",
        f"- Selector hits: {selector['selector_hit_count']:,} ({selector['hit_rate']:.2%})",
        f"- Successfully decoded rows: {selector['success_count']:,}",
        f"- Explicit remote missing: {selector['confirmed_remote_missing_count']:,}",
        f"- Quarantined: {selector['quarantined_count']:,}",
        f"- Selector ambiguities: {selector['ambiguity_count']:,}",
        f"- Unique messages / HTTP range groups: {retrieval['unique_message_count']:,} / {retrieval['transport_range_group_count']:,}",
        f"- Accepted source-range bytes: {retrieval['network_accepted_source_range_bytes']:,}",
        f"- Retries: {retrieval['retry_count']:,}",
        "",
        "## Worker profile",
        "",
        f"- Eight workers: {throughput['eight_worker']['logical_requests_per_second']:.3f} logical requests/s",
        "- Four-worker diagnostic: not run (optional; prior engineering pilot already selected eight workers).",
        f"- Decision basis: {throughput['selection_reason']}.",
        "",
        "## Full-history projection",
        "",
        f"- Duration: {duration_text}",
        f"- Output: {projection['projected_full_history_output_bytes']:,} bytes",
        f"- Additional free disk required with {projection['safety_margin_fraction']:.0%} margin: {projection['required_disk_bytes_with_margin']:,} bytes",
        f"- Available at closeout: {projection['owner_storage_available_bytes_at_closeout']:,} bytes",
        "",
        "## Gates",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — {name.replace('_', ' ')}"
        for name, passed in gates.items()
    )
    lines.extend(
        [
            "",
            "The JSON report beside this file contains per-field selector, interval, physical-range, storage, timing, retry, parity, resume, and rebuild evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _closeout_pilot(
    *,
    root: Path,
    run_id: str,
    design: PilotDesign,
    selection: PilotSelection,
    expected_units: Mapping[str, int],
    field_registry: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    primary_field_table = _read_all_unit_tables(root, run_dir, PRIMARY_MODE, "field_state.parquet")
    primary_ledger_table = _read_all_unit_tables(
        root, run_dir, PRIMARY_MODE, "retrieval_ledger.parquet"
    )
    primary_rows = primary_field_table.to_pylist()
    ledger_rows = primary_ledger_table.to_pylist()
    if len(primary_rows) != len(selection.rows) or len(ledger_rows) != len(selection.rows):
        raise PilotContractError("primary pilot row counts do not reconcile to selection")
    expected_request_ids = {str(row["request_id"]) for row in selection.rows}
    observed_request_ids = {str(row["request_id"]) for row in ledger_rows}
    if len(observed_request_ids) != len(ledger_rows) or observed_request_ids != expected_request_ids:
        raise PilotContractError("primary retrieval ledger does not reconcile to request IDs")
    expected_field_identities = {_selection_row_identity(row) for row in selection.rows}
    observed_field_identities = {
        (
            row["target_day"],
            row["product"],
            row["cycle_init_utc"],
            int(row["forecast_lead_min"]),
            row["field_registry_id"],
        )
        for row in primary_rows
    }
    if (
        len(observed_field_identities) != len(primary_rows)
        or observed_field_identities != expected_field_identities
    ):
        raise PilotContractError("primary field-state identities do not reconcile to selection")
    primary_metrics = _read_all_unit_metrics(run_dir, PRIMARY_MODE)
    rebuild_metrics = _read_all_unit_metrics(run_dir, REBUILD_MODE)
    if len(primary_metrics) != len(selection.tasks) or len(rebuild_metrics) != len(selection.tasks):
        raise PilotContractError("pilot work-unit counts do not reconcile to selection")

    value_rows = _precision_value_rows(primary_rows)
    precision = _precision_report(run_dir=run_dir, value_rows=value_rows, design=design)
    selector = _selector_report(primary_rows, ledger_rows)
    decoded_intervals = _decoded_interval_report(primary_rows, field_registry)
    physical_ranges = _physical_range_report(primary_rows, primary_metrics, design)
    regional_spatial = _regional_spatial_report(primary_rows, primary_metrics, design)
    special_intervals = _special_interval_report(primary_rows, selection, design)
    parity = _h16_q05_parity_report(primary_rows, design)
    throughput = _throughput_report(run_dir, primary_metrics, selection, design)
    rebuild = _rebuild_report(primary_metrics, rebuild_metrics)
    resume = _resume_audit(
        root=root,
        run_id=run_id,
        selection=selection,
        expected_units=expected_units,
    )
    output_size = _output_size_report(primary_field_table, primary_rows, field_registry)
    retrieval = _retrieval_report(primary_metrics)
    projection = _disk_and_duration_projection(
        root=root,
        run_dir=run_dir,
        selection=selection,
        primary_metrics=primary_metrics,
        throughput=throughput,
        precision=precision,
        design=design,
    )
    resources = _resource_report(run_dir, primary_metrics)
    repeated_days = {week.start_date for week in design.weeks}
    ambiguous_repeated_q_accepted = sum(
        row["field_registry_id"].startswith("Q")
        and row["target_day"] in repeated_days
        and int(row["forecast_lead_min"]) in {15, 30, 45, 60}
        and row["coverage_flag"] == "PRESENT"
        and str(row["missing_reason"] or "").startswith("SELECTOR_AMBIGUOUS")
        for row in primary_rows
    )
    observed_field_ids = {str(row["field_registry_id"]) for row in primary_rows}
    excluded_fields_absent = observed_field_ids == set(EXPECTED_FIELDS) == set(R14_ALL_IDS)
    gates = {
        "every_selector_validated_or_explicitly_blocked": decoded_intervals[
            "all_fields_validated_or_blocked"
        ],
        "no_ambiguous_repeated_q15_block_accepted": ambiguous_repeated_q_accepted == 0,
        "h38_fh00_and_positive_lead_intervals": special_intervals[
            "h38_fh00_zero_minute_accumulation_pass"
        ]
        and special_intervals["h38_positive_lead_one_hour_accumulation_pass"],
        "q05_repeated_blocks_resolve_by_full_identity": special_intervals[
            "q05_repeated_blocks_share_f01_parent_and_remain_unambiguous"
        ],
        "h16_q05_spatial_parity": parity["parity_pass"],
        "all_r14_regional_operators_validated": regional_spatial[
            "all_r14_field_operators_validated"
        ],
        "h14_terrain_finite_for_both_coordinate_eras": regional_spatial[
            "h14_terrain_support_pass"
        ],
        "dynamic_regional_supports_have_finite_h14": regional_spatial[
            "dynamic_supports_have_finite_corresponding_h14"
        ],
        "no_full_grid_cells_persisted": regional_spatial["full_grid_cells_persisted"] == 0,
        "excluded_h_and_q_identities_absent": excluded_fields_absent,
        "interruption_resume_duplicate_and_change_free": resume["pass"],
        "pilot_rebuild_value_identical_and_hash_stable": rebuild["value_identical"]
        and rebuild["hash_stable"],
        "projected_disk_fits_with_safety_margin": projection["disk_gate_pass"],
        "physical_value_ranges_and_units": physical_ranges["obvious_unit_gate_pass"],
        "float32_comparison_completed_and_within_tolerance": precision["value_count"] > 0
        and precision["parity_pass"],
        "eight_worker_end_to_end_primary_complete": throughput[
            "eight_worker_primary_complete"
        ],
    }
    report: dict[str, Any] = {
        "schema_version": PILOT_REPORT_SCHEMA_VERSION,
        "scope_id": R14_SCOPE_ID,
        "generated_at_utc": utc_now(),
        "status": "PASS" if all(gates.values()) else "FAIL",
        "run_id": run_id,
        "pilot_id": design.raw["pilot_id"],
        "lead_policy": design.raw["lead_policy"],
        "selection": selection.manifest,
        "selector_validation": selector,
        "decoded_key_and_interval_validation": decoded_intervals,
        "retrieval": retrieval,
        "resource_usage": resources,
        "output_size": output_size,
        "precision_comparison": precision,
        "projection": projection,
        "missingness_and_quarantine": {
            "confirmed_remote_missing_count": selector["confirmed_remote_missing_count"],
            "quarantined_count": selector["quarantined_count"],
            "classification_is_disjoint": True,
        },
        "physical_ranges": physical_ranges,
        "regional_spatial_validation": regional_spatial,
        "special_interval_validation": special_intervals,
        "h16_q05_spatial_parity": parity,
        "worker_profile_decision": throughput,
        "resume_audit": resume,
        "rebuild_audit": rebuild,
        "ambiguous_repeated_q15_accepted_count": ambiguous_repeated_q_accepted,
        "active_field_ids": sorted(observed_field_ids),
        "excluded_field_ids_present": [],
        "gates": gates,
    }
    cache_path = run_dir / "pilot/cache"
    cache_bytes_before_cleanup = _directory_size(cache_path)
    if report["status"] == "PASS" and cache_path.exists():
        shutil.rmtree(cache_path)
    report["temporary_cache_cleanup"] = {
        "policy": design.raw["runtime"]["cache_policy"],
        "bytes_before_cleanup": cache_bytes_before_cleanup,
        "removed_after_verified_rebuild": report["status"] == "PASS"
        and not cache_path.exists(),
        "raw_grib_or_index_cache_retained": cache_path.exists(),
    }
    run_report_dir = run_dir / "pilot/reports"
    run_report_dir.mkdir(parents=True, exist_ok=True)
    run_json = run_report_dir / "pilot_report.json"
    run_markdown = run_report_dir / "pilot_report.md"
    atomic_write_json(run_json, report)
    from .io.atomic import atomic_write_bytes

    markdown = _owner_report_markdown(report).encode("utf-8")
    atomic_write_bytes(run_markdown, markdown)
    atomic_write_json(root / PILOT_REPORT_JSON_PATH, report)
    atomic_write_bytes(root / PILOT_REPORT_MD_PATH, markdown)
    if report["status"] != "PASS":
        failed = [name for name, passed in gates.items() if not passed]
        raise PilotContractError(f"Step 04 pilot gates failed: {', '.join(failed)}")
    return report


def run_representative_pilot(
    *,
    project_root: Path | str,
    run_id: str,
    pause_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Execute/resume the bounded owner-run pilot and publish its report."""

    paths = load_project_paths(project_root)
    design = load_pilot_design(paths.root)
    selection = build_pilot_selection(paths.root, run_id, design)
    fields = {
        row["field_id"]: row
        for product in PRODUCTS
        for row in load_r14_field_registry(paths.root, product)
    }
    if set(fields) != set(EXPECTED_FIELDS):
        raise PilotContractError("combined active field registry is incomplete")
    coordinate_rows = _station_coordinates(paths.root)
    regional_geometry = _regional_geometry(paths.root)
    units = [task.unit_id(PRIMARY_MODE) for task in selection.tasks] + [
        task.unit_id(REBUILD_MODE) for task in selection.tasks
    ]
    ordinals = {unit_id: ordinal for ordinal, unit_id in enumerate(units)}
    coordinator = ProgressCoordinator(
        project_root=paths.root,
        run_dir=f"runs/{run_id}/pilot",
        run_id=run_id,
        step_id=STEP_ID,
        request_plan_sha256=selection.selection_sha256,
        expected_units=ordinals,
    )
    requested = pause_requested or (lambda: False)
    expected_logical_requests = 2 * len(selection.rows)
    _live_status(
        run_dir=paths.runs / run_id,
        phase="primary_eight_worker",
        coordinator=coordinator,
        last_unit_id=None,
        expected_logical_requests=expected_logical_requests,
    )
    phases = (
        (
            "primary_eight_worker",
            selection.tasks,
            PRIMARY_MODE,
            8,
        ),
        ("rebuild", selection.tasks, REBUILD_MODE, int(design.raw["runtime"]["rebuild_workers"])),
    )
    for phase, tasks, mode, workers in phases:
        _run_phase(
            root=paths.root,
            run_id=run_id,
            run_dir=paths.runs / run_id,
            phase=phase,
            tasks=tasks,
            mode=mode,
            workers=workers,
            ordinals=ordinals,
            selection_sha256=selection.selection_sha256,
            design=design,
            field_registry=fields,
            coordinate_rows=coordinate_rows,
            regional_geometry=regional_geometry,
            coordinator=coordinator,
            pause_requested=requested,
            expected_logical_requests=expected_logical_requests,
        )
    coordinator.snapshot("COMPLETE")
    _live_status(
        run_dir=paths.runs / run_id,
        phase="closeout",
        coordinator=coordinator,
        last_unit_id=None,
        expected_logical_requests=expected_logical_requests,
    )
    report = _closeout_pilot(
        root=paths.root,
        run_id=run_id,
        design=design,
        selection=selection,
        expected_units=ordinals,
        field_registry=fields,
    )
    run_relative = f"runs/{run_id}/pilot"
    artifacts = (
        PILOT_DESIGN_PATH,
        PILOT_REPORT_JSON_PATH,
        PILOT_REPORT_MD_PATH,
        "reports/step_04_r14_OWNER_RUNBOOK.md",
        f"{run_relative}/selection",
        f"{run_relative}/primary",
        f"{run_relative}/rebuild",
        f"{run_relative}/manifests",
        f"{run_relative}/progress",
        f"{run_relative}/benchmark_segments",
        f"{run_relative}/precision",
        f"{run_relative}/reports",
        "src/kden_v375/pilot.py",
        "src/kden_v375/steps/step_04_pilot.py",
        "src/kden_v375/r14_pilot_records.py",
        "src/kden_v375/io/grib.py",
        "src/kden_v375/io/http_range.py",
        "src/kden_v375/io/cache.py",
        "src/kden_v375/execution.py",
        "src/kden_v375/progress.py",
        "schemas/r14_step04_pass_v375.json",
    )
    return {"report": report, "artifact_paths": artifacts, "gate_evidence": report["gates"]}
