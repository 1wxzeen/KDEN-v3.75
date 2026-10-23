"""Unified, resumable owner-full acquisition for the frozen R14 universe.

Step 05 owns both products.  It publishes H14 once, then every hourly target
day, seals the hourly product, and only then begins Q05.  Source objects are
parallel work inside a target-day transaction; only the calling coordinator
may publish a canonical day, append progress, or issue a product PASS.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import tomllib
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..contracts import (
    ContractError,
    PauseRequested,
    load_project_paths,
    make_run_id,
    relative_to_root,
    utc_now,
    validate_run_id,
)
from ..execution import ExecutionSummary
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from ..io.atomic import atomic_publish_directory, atomic_write_json
from ..io.http_range import PersistentHttpTransport
from ..io.parquet import atomic_write_table
from ..pilot import (
    _load_r14_field_state_schema,
    _regional_geometry,
    _station_coordinates,
    load_pilot_design,
)
from ..progress import ProgressCoordinator, WorkUnitReceipt, publish_work_unit_manifest
from ..r14 import (
    R14_DYNAMIC_HOURLY,
    R14_STATIC_HOURLY,
    R14_SUBHOURLY,
    R14_SCOPE_ID,
    load_r14_field_registry,
)
from ..r14_pilot_records import R14_STEP04_REPORT_PATH, verify_r14_step04_pass
from ..r14_request_plans import (
    PRODUCTS,
    R14_PLAN_DIRECTORY,
    R14_PLAN_MANIFEST,
    verify_r14_product_plan,
)
from ..registries import load_parquet_schema
from .records import (
    COMBINED_PASS_PATH,
    COMBINED_REPORT_PATH,
    PRODUCT_MANIFEST_PATH,
    PRODUCT_PASS_PATH,
    PRODUCT_REPORT_PATH,
    verify_combined_pass,
    verify_product_pass,
    verify_ready_record,
    write_combined_pass,
    write_product_pass,
    write_ready_record,
)
from .source import SourceResult, SourceTask, process_source_object


STEP_ID = "STEP_05"
RUNTIME_PATH = "config/r14_acquisition_runtime_v375.json"
RUNTIME_SCHEMA = "KDEN_V375_R14_ACQUISITION_RUNTIME_V1"
PRODUCT_PHASES = {"wrfsfcf": "WRFSFCF_R14", "wrfsubhf": "WRFSUBHF_Q05_R14"}
PRODUCT_UNIT_COUNTS = {"wrfsfcf": 2_081, "wrfsubhf": 2_080}
COMBINED_UNIT_COUNT = 4_161
COMBINED_REQUEST_COUNT = 8_919_598
LIVE_SCHEMA = "KDEN_V375_R14_ACQUISITION_LIVE_STATUS_V1"
UNIT_SUMMARY_SCHEMA = "KDEN_V375_R14_ACQUISITION_UNIT_SUMMARY_V1"
PRODUCT_MANIFEST_SCHEMA = "KDEN_V375_R14_PRODUCT_ACQUISITION_MANIFEST_V1"
PRODUCT_REPORT_SCHEMA = "KDEN_V375_R14_PRODUCT_ACQUISITION_REPORT_V1"
COMBINED_REPORT_SCHEMA = "KDEN_V375_R14_COMBINED_ACQUISITION_REPORT_V1"
LIFECYCLE_SCHEMA = "KDEN_V375_R14_ACQUISITION_LIFECYCLE_V1"


class AcquisitionWorkflowError(ContractError):
    """The owner-full workflow cannot preserve the frozen R14 contract."""


@dataclass(frozen=True, slots=True)
class UnitSpec:
    unit_id: str
    ordinal: int
    product: str
    target_day: date
    static: bool
    artifact_path: str
    manifest_path: str


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AcquisitionWorkflowError(f"JSON artifact is not an object: {path}")
    return value


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _write_lifecycle(
    root: Path,
    *,
    run_id: str,
    status: str,
    product: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    allowed = {"PENDING", "RUNNING", "PAUSED", "FAILED"}
    if status not in allowed:
        raise AcquisitionWorkflowError(f"unsupported acquisition lifecycle status: {status}")
    record_id = "R14" if product is None else PRODUCT_PHASES[product]
    filename = f"{record_id}_{status}.json"
    destination = (
        root / "state" / filename
        if product is None
        else root / f"hrrr_v4_local_archive/{product}/state" / filename
    )
    body = {
        "schema_version": LIFECYCLE_SCHEMA,
        "record_id": record_id,
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "run_id": run_id,
        "status": status,
        "updated_at_utc": utc_now(),
        "message": message,
    }
    atomic_write_json(destination, body)
    atomic_write_json(
        root / "runs" / run_id / "acquisition/lifecycle.json", body
    )
    return body


def _dates(start: date, end: date) -> tuple[date, ...]:
    if end < start:
        raise AcquisitionWorkflowError("historical date range is reversed")
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))


def target_days(project_root: Path | str) -> tuple[date, ...]:
    paths = load_project_paths(project_root)
    project = _read_toml(paths.config)["project"]
    values = _dates(
        date.fromisoformat(str(project["historical_start"])),
        date.fromisoformat(str(project["historical_end"])),
    )
    if len(values) != 2_080 or values[0] != date(2021, 1, 1) or values[-1] != date(2026, 9, 11):
        raise AcquisitionWorkflowError("R14 historical target-day extent changed")
    return values


def load_runtime_config(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    value = _read_json(root / RUNTIME_PATH)
    if (
        value.get("schema_version") != RUNTIME_SCHEMA
        or value.get("scope_id") != R14_SCOPE_ID
        or value.get("phase_order") != ["WRFSFCF_R14", "WRFSUBHF_Q05_R14"]
        or int(value.get("max_total_download_workers", 0)) != 8
        or value.get("work_unit") != "product_target_day"
        or value.get("static_work_unit") != "wrfsfcf_h14_once_per_grid"
    ):
        raise AcquisitionWorkflowError("R14 owner-full runtime identity changed")
    expected = {
        "wrfsfcf": (6_762_997, list(R14_DYNAMIC_HOURLY), list(R14_STATIC_HOURLY), True),
        "wrfsubhf": (2_156_601, list(R14_SUBHOURLY), [], False),
    }
    profiles: dict[str, dict[str, Any]] = {}
    for product, (count, dynamic, static, static_first) in expected.items():
        item = value.get("products", {}).get(product, {})
        if (
            item.get("phase_id") != PRODUCT_PHASES[product]
            or int(item.get("expected_request_count", -1)) != count
            or item.get("expected_dynamic_field_ids") != dynamic
            or item.get("expected_static_field_ids") != static
            or item.get("static_first") is not static_first
        ):
            raise AcquisitionWorkflowError(f"R14 runtime product contract changed: {product}")
        profile = _read_toml(root / str(item["worker_profile"]))
        if (
            profile.get("schema_version") != "KDEN_V375_WORKER_PROFILE_V1"
            or profile.get("product") != product
            or int(profile.get("max_workers", 0)) != 8
            or int(profile.get("pool_maxsize_per_host", 0)) != 1
        ):
            raise AcquisitionWorkflowError(f"eight-worker profile changed: {product}")
        profiles[product] = profile
    if value.get("cache", {}).get("full_domain_grib_retention") is not False:
        raise AcquisitionWorkflowError("full-domain GRIB retention must remain disabled")
    return {**value, "_profiles": profiles}


def build_unit_specs(project_root: Path | str, product: str) -> tuple[UnitSpec, ...]:
    if product not in PRODUCTS:
        raise AcquisitionWorkflowError(f"unknown R14 product: {product}")
    days = target_days(project_root)
    units: list[UnitSpec] = []
    if product == "wrfsfcf":
        units.append(
            UnitSpec(
                unit_id="WRFSFCF_R14_STATIC_H14",
                ordinal=0,
                product=product,
                target_day=days[0],
                static=True,
                artifact_path=(
                    "hrrr_v4_local_archive/common/static_geometry/"
                    "grid_geometry_id=HRRR_CONUS_NATIVE_LAMBERT_V4/field=H14"
                ),
                manifest_path=(
                    "hrrr_v4_local_archive/wrfsfcf/manifests/acquisition_r14_units/"
                    "WRFSFCF_R14_STATIC_H14.json"
                ),
            )
        )
    for day in days:
        prefix = "WRFSFCF_R14_DAY" if product == "wrfsfcf" else "WRFSUBHF_Q05_R14_DAY"
        unit_id = f"{prefix}_{day.isoformat()}"
        units.append(
            UnitSpec(
                unit_id=unit_id,
                ordinal=len(units),
                product=product,
                target_day=day,
                static=False,
                artifact_path=(
                    f"hrrr_v4_local_archive/{product}/canonical/r14/"
                    f"target_year={day.year:04d}/target_month={day.month:02d}/"
                    f"target_day={day.isoformat()}"
                ),
                manifest_path=(
                    f"hrrr_v4_local_archive/{product}/manifests/acquisition_r14_units/"
                    f"{unit_id}.json"
                ),
            )
        )
    if len(units) != PRODUCT_UNIT_COUNTS[product]:
        raise AcquisitionWorkflowError(f"unexpected R14 work-unit count: {product}")
    return tuple(units)


def _plan_manifest(root: Path, product: str) -> dict[str, Any]:
    return _read_json(root / R14_PLAN_MANIFEST[product])


def _plan_partition(root: Path, product: str, year: int) -> Path:
    manifest = _plan_manifest(root, product)
    matches = [part for part in manifest.get("partitions", []) if int(part["target_year"]) == year]
    if len(matches) != 1:
        raise AcquisitionWorkflowError(f"no unique R14 plan partition for {product} {year}")
    return root / R14_PLAN_DIRECTORY[product] / str(matches[0]["path"])


def load_unit_plan_rows(root: Path, unit: UnitSpec) -> list[dict[str, Any]]:
    try:
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise AcquisitionWorkflowError("pyarrow is required for owner acquisition") from exc
    table = pq.read_table(
        _plan_partition(root, unit.product, unit.target_day.year),
        filters=[("target_day", "=", unit.target_day)],
    )
    if unit.static:
        table = table.filter(pc.equal(table["field_registry_id"], "H14"))
    elif unit.product == "wrfsfcf":
        table = table.filter(pc.not_equal(table["field_registry_id"], "H14"))
    rows = table.to_pylist()
    if not rows:
        raise AcquisitionWorkflowError(f"work unit has no planned requests: {unit.unit_id}")
    allowed = {"H14"} if unit.static else (
        set(R14_DYNAMIC_HOURLY) if unit.product == "wrfsfcf" else set(R14_SUBHOURLY)
    )
    request_ids = [str(row["request_id"]) for row in rows]
    if (
        len(request_ids) != len(set(request_ids))
        or {str(row["product"]) for row in rows} != {unit.product}
        or {row["target_day"] for row in rows} != {unit.target_day}
        or {str(row["field_registry_id"]) for row in rows} - allowed
        or {str(row["request_action"]) for row in rows}
        != ({"ARCHIVE_GRID_STATIC_ONCE_V1"} if unit.static else {"ARCHIVE_NETWORK_RANGE_V1"})
    ):
        raise AcquisitionWorkflowError(f"R14 plan rows violate unit identity: {unit.unit_id}")
    return sorted(
        rows,
        key=lambda row: (
            row["cycle_init_utc"], row["valid_time_utc"], row["field_registry_id"], row["request_id"]
        ),
    )


def build_source_tasks(rows: Sequence[Mapping[str, Any]]) -> tuple[SourceTask, ...]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["source_object_identity"])].append(row)
    return tuple(
        SourceTask(
            product=str(group[0]["product"]),
            source_object_identity=source,
            rows=tuple(
                sorted(
                    group,
                    key=lambda row: (
                        row["valid_time_utc"], row["field_registry_id"], row["request_id"]
                    ),
                )
            ),
        )
        for source, group in sorted(grouped.items())
    )


def coverage_rows(field_rows: Sequence[Mapping[str, Any]], run_id: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in field_rows:
        key = (row["target_day"], row["product"], row["cycle_init_utc"], row["field_registry_id"])
        grouped[key].append(row)
    output: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        values = sorted(values, key=lambda row: (row["valid_time_utc"], row["interval_start_utc"]))
        present = [row for row in values if row["coverage_flag"] == "PRESENT"]
        missing = [row for row in values if row["coverage_flag"] == "MISSING"]
        quarantined = [row for row in values if row["coverage_flag"] == "QUARANTINED"]
        gaps = [
            {
                "start": row["interval_start_utc"],
                "end": row["interval_end_utc"],
                "reason": str(row.get("missing_reason") or row["coverage_flag"]),
            }
            for row in values
            if row["coverage_flag"] != "PRESENT"
        ]
        output.append(
            {
                "target_day": key[0],
                "product": key[1],
                "cycle_init_utc": key[2],
                "field_registry_id": key[3],
                "expected_valid_count": len(values),
                "present_valid_count": len(present),
                "missing_valid_count": len(missing),
                "quarantined_valid_count": len(quarantined),
                "first_valid_time_utc": present[0]["valid_time_utc"] if present else None,
                "last_valid_time_utc": present[-1]["valid_time_utc"] if present else None,
                "gap_intervals": gaps,
                "complete_flag": not missing and not quarantined,
                "retrieval_run_id": run_id,
            }
        )
    return output


def _unit_staging(artifact: Path, run_id: str) -> Path:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    for stale in artifact.parent.glob(f".{artifact.name}.{run_id}.*"):
        if stale.is_dir():
            shutil.rmtree(stale)
    return Path(tempfile.mkdtemp(dir=artifact.parent, prefix=f".{artifact.name}.{run_id}."))


def _write_parquet(rows: Sequence[Mapping[str, Any]], schema: Any, path: Path) -> None:
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise AcquisitionWorkflowError("pyarrow is required for owner acquisition") from exc
    table = pa.Table.from_pylist(list(rows), schema=schema)
    atomic_write_table(table, path, schema=schema, replace=False)


def _unit_summary(root: Path, unit: UnitSpec) -> dict[str, Any]:
    return _read_json(root / unit.artifact_path / "_unit_summary.json")


def _receipt_from_manifest(root: Path, unit: UnitSpec) -> WorkUnitReceipt:
    path = root / unit.manifest_path
    body = _read_json(path)
    counts = body.get("counts", {})
    if body.get("unit_id") != unit.unit_id or body.get("plan_ordinal") != unit.ordinal:
        raise AcquisitionWorkflowError(f"work-unit manifest identity changed: {unit.unit_id}")
    if sha256_path(root / str(body["artifact_path"])) != body["artifact_sha256"]:
        raise AcquisitionWorkflowError(f"work-unit artifact changed: {unit.unit_id}")
    return WorkUnitReceipt(
        unit_id=unit.unit_id,
        plan_ordinal=unit.ordinal,
        artifact_path=str(body["artifact_path"]),
        artifact_sha256=str(body["artifact_sha256"]),
        manifest_path=unit.manifest_path,
        manifest_sha256=sha256_file(path),
        row_count=int(counts["row_count"]),
        request_count=int(counts["request_count"]),
        accepted_bytes=int(counts["accepted_bytes"]),
    )


def recover_unit_receipt(
    root: Path, unit: UnitSpec, *, run_id: str, plan_sha256: str
) -> WorkUnitReceipt | None:
    artifact = root / unit.artifact_path
    manifest = root / unit.manifest_path
    if manifest.exists() and not artifact.exists():
        raise AcquisitionWorkflowError(f"manifest exists without artifact: {unit.unit_id}")
    if manifest.exists():
        receipt = _receipt_from_manifest(root, unit)
        if _unit_summary(root, unit).get("run_id") != run_id:
            raise AcquisitionWorkflowError(f"canonical unit belongs to another run: {unit.unit_id}")
        return receipt
    if not artifact.exists():
        return None
    summary = _unit_summary(root, unit)
    if (
        summary.get("schema_version") != UNIT_SUMMARY_SCHEMA
        or summary.get("run_id") != run_id
        or summary.get("unit_id") != unit.unit_id
        or summary.get("request_plan_sha256") != plan_sha256
    ):
        raise AcquisitionWorkflowError(f"uncommitted artifact identity changed: {unit.unit_id}")
    return publish_work_unit_manifest(
        project_root=root,
        manifest_path=unit.manifest_path,
        run_id=run_id,
        step_id=STEP_ID,
        request_plan_sha256=plan_sha256,
        unit_id=unit.unit_id,
        plan_ordinal=unit.ordinal,
        artifact_path=unit.artifact_path,
        row_count=int(summary["field_state_row_count"]),
        request_count=int(summary["request_count"]),
        accepted_bytes=int(summary["network_accepted_bytes"]),
    )


def publish_unit(
    root: Path,
    unit: UnitSpec,
    *,
    run_id: str,
    plan_sha256: str,
    plan_rows: Sequence[Mapping[str, Any]],
    results: Sequence[SourceResult],
) -> WorkUnitReceipt:
    field_rows = [dict(row) for result in results for row in result.field_rows]
    ledger_rows = [dict(row) for result in results for row in result.ledger_rows]
    planned_ids = {str(row["request_id"]) for row in plan_rows}
    ledger_ids = {str(row["request_id"]) for row in ledger_rows}
    if len(field_rows) != len(plan_rows) or len(ledger_rows) != len(plan_rows) or ledger_ids != planned_ids:
        raise AcquisitionWorkflowError(f"unit request reconciliation failed: {unit.unit_id}")
    field_rows.sort(
        key=lambda row: (
            row["target_day"], row["product"], row["cycle_init_utc"],
            row["valid_time_utc"], row["field_registry_id"], row["interval_start_utc"],
        )
    )
    ledger_rows.sort(key=lambda row: (row["retrieval_run_id"], row["request_id"], row["attempt_number"]))
    coverage = coverage_rows(field_rows, run_id)
    metrics = [result.metrics for result in results]
    success = sum(int(value["success_count"]) for value in metrics)
    missing = sum(int(value["confirmed_remote_missing_count"]) for value in metrics)
    accepted = sum(
        int(value["source_range_accepted_bytes"])
        + int(value["index_accepted_bytes"])
        + int(value["parent_probe_accepted_bytes"])
        for value in metrics
    )
    retries = sum(
        int(value["range_retry_count"])
        + int(value["index_retry_count"])
        + int(value["parent_probe_retry_count"])
        for value in metrics
    )
    terrain = [item for value in metrics for item in value.get("terrain_evidence", [])]
    if unit.static and (
        len(terrain) != 1
        or len(terrain[0].get("values_by_coordinate_era", {})) != 2
    ):
        raise AcquisitionWorkflowError("H14 does not cover both KDEN coordinate eras")
    if not unit.static and terrain:
        raise AcquisitionWorkflowError("dynamic unit unexpectedly contains H14 terrain")
    summary = {
        "schema_version": UNIT_SUMMARY_SCHEMA,
        "scope_id": R14_SCOPE_ID,
        "run_id": run_id,
        "step_id": STEP_ID,
        "phase": PRODUCT_PHASES[unit.product],
        "product": unit.product,
        "unit_id": unit.unit_id,
        "plan_ordinal": unit.ordinal,
        "target_day": unit.target_day.isoformat(),
        "static": unit.static,
        "request_plan_sha256": plan_sha256,
        "request_count": len(plan_rows),
        "field_state_row_count": len(field_rows),
        "ledger_row_count": len(ledger_rows),
        "coverage_row_count": len(coverage),
        "source_object_count": len(results),
        "success_count": success,
        "confirmed_remote_missing_count": missing,
        "quarantined_count": 0,
        "network_accepted_bytes": accepted,
        "retry_count": retries,
        "field_ids": sorted({str(row["field_registry_id"]) for row in plan_rows}),
        "maximum_valid_time_utc": max(row["valid_time_utc"] for row in plan_rows).isoformat(),
        "full_grid_cells_persisted": sum(int(value["full_grid_cells_persisted"]) for value in metrics),
        "max_download_workers": 8,
        "publication_order": "artifact_then_manifest_then_progress",
    }
    if success + missing != len(plan_rows):
        raise AcquisitionWorkflowError(f"unit terminal accounting failed: {unit.unit_id}")
    artifact = root / unit.artifact_path
    staging = _unit_staging(artifact, run_id)
    try:
        field_schema = _load_r14_field_state_schema(root)
        ledger_schema = load_parquet_schema(root, "retrieval_ledger_v375.json")
        coverage_schema = load_parquet_schema(root, "temporal_coverage_v375.json")
        for cycle, rows in sorted(
            _group_rows(field_rows, "cycle_init_utc").items(), key=lambda item: item[0]
        ):
            cycle_id = cycle.strftime("%Y%m%dT%H%M%SZ")
            _write_parquet(rows, field_schema, staging / f"cycle={cycle_id}/field_state.parquet")
        _write_parquet(ledger_rows, ledger_schema, staging / "_retrieval_ledger.parquet")
        _write_parquet(coverage, coverage_schema, staging / "_temporal_coverage.parquet")
        if terrain:
            atomic_write_json(
                staging / "_h14_terrain_supports.json",
                {
                    "schema_version": "KDEN_V375_R14_H14_TERRAIN_SUPPORTS_V1",
                    "run_id": run_id,
                    "unit_id": unit.unit_id,
                    "evidence": terrain,
                },
                replace=False,
            )
        atomic_write_json(staging / "_unit_summary.json", summary, replace=False)
        atomic_publish_directory(staging, artifact)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return publish_work_unit_manifest(
        project_root=root,
        manifest_path=unit.manifest_path,
        run_id=run_id,
        step_id=STEP_ID,
        request_plan_sha256=plan_sha256,
        unit_id=unit.unit_id,
        plan_ordinal=unit.ordinal,
        artifact_path=unit.artifact_path,
        row_count=len(field_rows),
        request_count=len(plan_rows),
        accepted_bytes=accepted,
    )


def _group_rows(
    rows: Sequence[Mapping[str, Any]], key: str
) -> dict[Any, list[Mapping[str, Any]]]:
    output: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        output[row[key]].append(row)
    return dict(output)


def _journal_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    output: list[dict[str, Any]] = []
    for line in path.read_bytes().splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AcquisitionWorkflowError(f"progress record is not an object: {path}")
        output.append(value)
    return output


def _completed_before_product(root: Path, product: str, run_id: str) -> tuple[int, int, int]:
    if product == "wrfsfcf":
        return 0, 0, 0
    pass_path = root / PRODUCT_PASS_PATH["wrfsfcf"]
    manifest_path = root / PRODUCT_MANIFEST_PATH["wrfsfcf"]
    if not pass_path.is_file() or not manifest_path.is_file():
        return 0, 0, 0
    pass_record = _read_json(pass_path)
    manifest = _read_json(manifest_path)
    if (
        pass_record.get("status") != "PASS"
        or pass_record.get("run_id") != run_id
        or manifest.get("status") != "PASS"
        or manifest.get("run_id") != run_id
    ):
        raise AcquisitionWorkflowError("hourly checkpoint changed during Q05 acquisition")
    totals = manifest["totals"]
    return (
        int(manifest["completed_work_unit_count"]),
        int(totals["request_count"]),
        int(totals["network_accepted_bytes"]),
    )


def write_live_status(
    root: Path,
    *,
    run_id: str,
    phase: str,
    product: str | None,
    coordinator: ProgressCoordinator | None,
    current_unit: UnitSpec | None = None,
    inflight_completed: int = 0,
    inflight_expected: int = 0,
    inflight_requests: int = 0,
    completed_accepted_bytes: int | None = None,
) -> dict[str, Any]:
    prior_units, prior_requests, prior_bytes = (
        _completed_before_product(root, product, run_id) if product else (0, 0, 0)
    )
    completed_units = prior_units + (len(coordinator.completed_units) if coordinator else COMBINED_UNIT_COUNT)
    completed_requests = prior_requests + (
        coordinator.completed_request_count if coordinator else COMBINED_REQUEST_COUNT
    )
    accepted = (
        int(completed_accepted_bytes)
        if completed_accepted_bytes is not None
        else prior_bytes + (coordinator.completed_accepted_bytes if coordinator else 0)
    )
    body = {
        "schema_version": LIVE_SCHEMA,
        "run_id": run_id,
        "scope_id": R14_SCOPE_ID,
        "updated_at_utc": utc_now(),
        "phase": phase,
        "product": product,
        "current_work_unit": current_unit.unit_id if current_unit else None,
        "current_target_day": current_unit.target_day.isoformat() if current_unit else None,
        "inflight_source_objects_completed": inflight_completed,
        "inflight_source_objects_expected": inflight_expected,
        "inflight_logical_requests": inflight_requests,
        "completed_work_units": completed_units,
        "expected_work_units": COMBINED_UNIT_COUNT,
        "remaining_work_units": COMBINED_UNIT_COUNT - completed_units,
        "completed_logical_requests": completed_requests,
        "expected_logical_requests": COMBINED_REQUEST_COUNT,
        "remaining_logical_requests": COMBINED_REQUEST_COUNT - completed_requests,
        "accepted_bytes": accepted,
        "max_total_download_workers": 8,
    }
    atomic_write_json(root / "runs" / run_id / "acquisition/live_status.json", body)
    return body


def _process_unit(
    *,
    root: Path,
    run_id: str,
    unit: UnitSpec,
    plan_sha256: str,
    profile: Mapping[str, Any],
    field_registry: Mapping[str, Mapping[str, str]],
    coordinate_rows: Sequence[Mapping[str, Any]],
    regional_geometry: Mapping[str, Sequence[Mapping[str, Any]]],
    physical_ranges: Mapping[str, Sequence[float]],
    transport: PersistentHttpTransport,
    executor: ThreadPoolExecutor,
    coordinator: ProgressCoordinator,
    pause_requested: Callable[[], bool],
) -> WorkUnitReceipt:
    recovered = recover_unit_receipt(root, unit, run_id=run_id, plan_sha256=plan_sha256)
    if recovered is not None:
        return recovered
    plan_rows = load_unit_plan_rows(root, unit)
    tasks = build_source_tasks(plan_rows)
    results: list[SourceResult] = []
    inflight_requests = 0
    last_live_write = 0.0

    def commit(result: SourceResult) -> None:
        nonlocal inflight_requests, last_live_write
        results.append(result)
        inflight_requests += int(result.metrics["request_count"])
        import time

        now = time.monotonic()
        if now - last_live_write >= 5.0 or len(results) == len(tasks):
            write_live_status(
                root,
                run_id=run_id,
                phase=PRODUCT_PHASES[unit.product],
                product=unit.product,
                coordinator=coordinator,
                current_unit=unit,
                inflight_completed=len(results),
                inflight_expected=len(tasks),
                inflight_requests=inflight_requests,
            )
            last_live_write = now

    def worker(task: SourceTask) -> SourceResult:
        return process_source_object(
            root=root,
            run_id=run_id,
            task=task,
            field_registry=field_registry,
            coordinate_rows=coordinate_rows,
            regional_geometry=regional_geometry,
            profile=profile,
            physical_ranges=physical_ranges,
            required_regional_mask=(1 << 8) - 1,
            transport=transport,
        )

    summary = _execute_on_persistent_pool(
        tasks,
        executor=executor,
        worker=worker,
        commit=commit,
        pause_requested=pause_requested,
    )
    if summary.paused or summary.remaining_count:
        raise PauseRequested(
            f"paused inside {unit.unit_id}; no partial target day was published"
        )
    return publish_unit(
        root,
        unit,
        run_id=run_id,
        plan_sha256=plan_sha256,
        plan_rows=plan_rows,
        results=results,
    )


def _execute_on_persistent_pool(
    items: Sequence[SourceTask],
    *,
    executor: ThreadPoolExecutor,
    worker: Callable[[SourceTask], SourceResult],
    commit: Callable[[SourceResult], None],
    pause_requested: Callable[[], bool],
) -> ExecutionSummary:
    """Use one eight-thread pool across days while retaining bounded ordering."""

    total = len(items)
    next_submit = 0
    next_commit = 0
    submitted = 0
    completed: dict[int, SourceResult] = {}
    futures: dict[Future[SourceResult], int] = {}
    paused = False
    window = 16

    def submit_available() -> None:
        nonlocal next_submit, submitted, paused
        while next_submit < total and len(futures) + len(completed) < window:
            if pause_requested():
                paused = True
                return
            ordinal = next_submit
            futures[executor.submit(worker, items[ordinal])] = ordinal
            next_submit += 1
            submitted += 1

    submit_available()
    try:
        while futures:
            done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
            for future in done:
                ordinal = futures.pop(future)
                completed[ordinal] = future.result()
            while next_commit in completed:
                commit(completed.pop(next_commit))
                next_commit += 1
            if pause_requested():
                paused = True
            if not paused:
                submit_available()
    except BaseException:
        for future in futures:
            future.cancel()
        raise
    return ExecutionSummary(
        submitted_count=submitted,
        committed_count=next_commit,
        paused=paused and next_submit < total,
        remaining_count=total - next_commit,
    )


def _immutable_json(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    if path.exists():
        existing = _read_json(path)
        if existing != dict(value):
            raise AcquisitionWorkflowError(f"immutable closeout artifact changed: {path}")
        return existing
    atomic_write_json(path, dict(value), replace=False)
    return dict(value)


def _close_product(
    root: Path,
    *,
    run_id: str,
    product: str,
    units: Sequence[UnitSpec],
    coordinator: ProgressCoordinator,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    coordinator.snapshot("COMPLETE")
    records = _journal_records(coordinator.journal_path)
    if len(records) != len(units):
        raise AcquisitionWorkflowError(f"{product} completion journal is incomplete")
    summaries = [_unit_summary(root, unit) for unit in units]
    totals = {
        "request_count": sum(int(value["request_count"]) for value in summaries),
        "success_count": sum(int(value["success_count"]) for value in summaries),
        "confirmed_remote_missing_count": sum(
            int(value["confirmed_remote_missing_count"]) for value in summaries
        ),
        "quarantined_count": sum(int(value["quarantined_count"]) for value in summaries),
        "network_accepted_bytes": sum(int(value["network_accepted_bytes"]) for value in summaries),
        "retry_count": sum(int(value["retry_count"]) for value in summaries),
        "field_state_row_count": sum(int(value["field_state_row_count"]) for value in summaries),
    }
    expected_fields = (
        set(R14_DYNAMIC_HOURLY + R14_STATIC_HOURLY)
        if product == "wrfsfcf"
        else set(R14_SUBHOURLY)
    )
    observed_fields = {field for value in summaries for field in value["field_ids"]}
    h14_units = sum(value["field_ids"] == ["H14"] for value in summaries)
    gates = {
        "expected_work_units_complete": len(records) == PRODUCT_UNIT_COUNTS[product],
        "request_count_matches_sealed_plan": totals["request_count"] == int(plan["request_row_count"]),
        "every_request_has_one_terminal_row": (
            totals["success_count"] + totals["confirmed_remote_missing_count"]
            == totals["request_count"] == totals["field_state_row_count"]
        ),
        "quarantine_count_is_zero": totals["quarantined_count"] == 0,
        "exact_r14_field_universe": observed_fields == expected_fields,
        "h14_once_for_hourly_and_absent_from_q05": (
            h14_units == 1 if product == "wrfsfcf" else h14_units == 0
        ),
        "normal_network_sentinel_present": any(
            ("H16" if product == "wrfsfcf" else "Q05") in value["field_ids"]
            for value in summaries
        ),
        "no_full_grid_cells_persisted": all(
            int(value["full_grid_cells_persisted"]) == 0 for value in summaries
        ),
        "eight_worker_bound": all(int(value["max_download_workers"]) == 8 for value in summaries),
        "right_open_plan_preverified": plan["all_valid_times_strictly_before_window_end"] is True,
        "fh48_only_tail_absent": plan["fh48_only_tail_absent"] is True,
    }
    if not all(gates.values()):
        failed = [key for key, passed in gates.items() if not passed]
        raise AcquisitionWorkflowError(f"{product} closeout gates failed: {', '.join(failed)}")
    unit_chain = [
        {
            "unit_id": record["unit_id"],
            "artifact_path": record["artifact_path"],
            "artifact_sha256": record["artifact_sha256"],
            "manifest_path": record["manifest_path"],
            "manifest_sha256": record["manifest_sha256"],
            "request_count": int(record["request_count"]),
        }
        for record in records
    ]
    body = {
        "schema_version": PRODUCT_MANIFEST_SCHEMA,
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "phase": PRODUCT_PHASES[product],
        "status": "PASS",
        "run_id": run_id,
        "completed_at_utc": records[-1]["completed_at_utc"],
        "request_plan_sha256": plan["plan_sha256"],
        "completed_work_unit_count": len(records),
        "units": unit_chain,
        "totals": totals,
        "gates": gates,
    }
    manifest = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    _immutable_json(root / PRODUCT_MANIFEST_PATH[product], manifest)
    report = {
        "schema_version": PRODUCT_REPORT_SCHEMA,
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "phase": PRODUCT_PHASES[product],
        "status": "PASS",
        "run_id": run_id,
        "completed_at_utc": records[-1]["completed_at_utc"],
        "request_plan_sha256": plan["plan_sha256"],
        "work_units": len(records),
        "totals": totals,
        "gates": gates,
        "archive_root": relative_to_root(root, root / f"hrrr_v4_local_archive/{product}/canonical/r14"),
        "raw_grib_retained": False,
    }
    _immutable_json(root / PRODUCT_REPORT_PATH[product], report)
    return write_product_pass(root, product=product, run_id=run_id, gate_evidence=gates)


def _run_product(
    root: Path,
    *,
    run_id: str,
    product: str,
    runtime: Mapping[str, Any],
    pause_requested: Callable[[], bool],
) -> dict[str, Any]:
    try:
        return verify_product_pass(root, product, expected_run_id=run_id, deep=True)
    except FileNotFoundError:
        pass
    _write_lifecycle(root, run_id=run_id, status="RUNNING", product=product)
    units = build_unit_specs(root, product)
    plan = verify_r14_product_plan(root, product)
    coordinator = ProgressCoordinator(
        project_root=root,
        run_dir=f"runs/{run_id}/acquisition/{product}",
        run_id=run_id,
        step_id=STEP_ID,
        request_plan_sha256=plan["plan_sha256"],
        expected_units={unit.unit_id: unit.ordinal for unit in units},
        recover_torn_final=True,
    )
    fields = {row["field_id"]: row for row in load_r14_field_registry(root, product)}
    coordinates = _station_coordinates(root)
    regional = _regional_geometry(root)
    design = load_pilot_design(root)
    profile = runtime["_profiles"][product]
    try:
        with PersistentHttpTransport(
            pool_connections=int(profile["pool_connections_per_session"]),
            pool_maxsize=int(profile["pool_maxsize_per_host"]),
        ) as transport, ThreadPoolExecutor(
            max_workers=8, thread_name_prefix=f"kden-v375-{product}"
        ) as executor:
            for unit in units:
                if unit.unit_id in coordinator.completed_units:
                    continue
                if pause_requested():
                    raise PauseRequested(f"paused before {unit.unit_id}")
                write_live_status(
                    root,
                    run_id=run_id,
                    phase=PRODUCT_PHASES[product],
                    product=product,
                    coordinator=coordinator,
                    current_unit=unit,
                )
                receipt = _process_unit(
                    root=root,
                    run_id=run_id,
                    unit=unit,
                    plan_sha256=plan["plan_sha256"],
                    profile=profile,
                    field_registry=fields,
                    coordinate_rows=coordinates,
                    regional_geometry=regional,
                    physical_ranges=design.raw["physical_ranges"],
                    transport=transport,
                    executor=executor,
                    coordinator=coordinator,
                    pause_requested=pause_requested,
                )
                coordinator.commit(receipt)
                cache = root / "runs" / run_id / "acquisition/cache"
                if cache.exists():
                    shutil.rmtree(cache)
    except PauseRequested:
        coordinator.snapshot("PAUSED")
        _write_lifecycle(
            root,
            run_id=run_id,
            status="PAUSED",
            product=product,
            message="cooperative pause at an unpublished or completed target-day boundary",
        )
        write_live_status(
            root,
            run_id=run_id,
            phase="paused",
            product=product,
            coordinator=coordinator,
        )
        raise
    except Exception as exc:
        _write_lifecycle(
            root,
            run_id=run_id,
            status="FAILED",
            product=product,
            message=f"{type(exc).__name__}: {exc}",
        )
        raise
    cache = root / "runs" / run_id / "acquisition/cache"
    if cache.exists():
        shutil.rmtree(cache)
    return _close_product(
        root,
        run_id=run_id,
        product=product,
        units=units,
        coordinator=coordinator,
        plan=plan,
    )


def _close_combined(root: Path, run_id: str) -> dict[str, Any]:
    product_passes = {
        product: verify_product_pass(root, product, expected_run_id=run_id, deep=False)
        for product in PRODUCTS
    }
    manifests = {product: _read_json(root / PRODUCT_MANIFEST_PATH[product]) for product in PRODUCTS}
    totals = {
        "work_unit_count": sum(int(value["completed_work_unit_count"]) for value in manifests.values()),
        "request_count": sum(int(value["totals"]["request_count"]) for value in manifests.values()),
        "network_accepted_bytes": sum(
            int(value["totals"]["network_accepted_bytes"]) for value in manifests.values()
        ),
        "confirmed_remote_missing_count": sum(
            int(value["totals"]["confirmed_remote_missing_count"]) for value in manifests.values()
        ),
    }
    gates = {
        "hourly_product_pass": product_passes["wrfsfcf"]["status"] == "PASS",
        "q05_product_pass": product_passes["wrfsubhf"]["status"] == "PASS",
        "one_owner_run": {value["run_id"] for value in product_passes.values()} == {run_id},
        "hourly_then_q05_phase_order": [manifests[p]["phase"] for p in PRODUCTS]
        == ["WRFSFCF_R14", "WRFSUBHF_Q05_R14"],
        "combined_work_unit_count": totals["work_unit_count"] == COMBINED_UNIT_COUNT,
        "combined_request_count": totals["request_count"] == COMBINED_REQUEST_COUNT,
        "shared_maximum_eight_workers": all(
            value["gates"]["eight_worker_bound"] for value in manifests.values()
        ),
        "product_checkpoints_independent": all(
            (root / PRODUCT_PASS_PATH[product]).is_file() for product in PRODUCTS
        ),
    }
    if not all(gates.values()):
        raise AcquisitionWorkflowError("combined R14 closeout gates failed")
    report = {
        "schema_version": COMBINED_REPORT_SCHEMA,
        "scope_id": R14_SCOPE_ID,
        "status": "PASS",
        "run_id": run_id,
        "completed_at_utc": manifests["wrfsubhf"]["completed_at_utc"],
        "phase_order": ["WRFSFCF_R14", "WRFSUBHF_Q05_R14"],
        "products": {
            product: {
                "pass_record_sha256": product_passes[product]["record_sha256"],
                "manifest_record_sha256": manifests[product]["record_sha256"],
            }
            for product in PRODUCTS
        },
        "totals": totals,
        "gates": gates,
    }
    _immutable_json(root / COMBINED_REPORT_PATH, report)
    result = write_combined_pass(root, run_id=run_id, gate_evidence=gates)
    write_live_status(
        root,
        run_id=run_id,
        phase="complete",
        product=None,
        coordinator=None,
        completed_accepted_bytes=totals["network_accepted_bytes"],
    )
    return result


def run_r14_acquisition(
    *,
    project_root: Path | str,
    run_id: str,
    pause_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    validate_run_id(run_id, step_no=5, scope="owner-full")
    verify_ready_record(root)
    runtime = load_runtime_config(root)
    if (root / COMBINED_PASS_PATH).exists():
        return verify_combined_pass(root, expected_run_id=run_id, deep=True)
    requested = pause_requested or (lambda: False)
    _write_lifecycle(root, run_id=run_id, status="RUNNING")
    if not (root / PRODUCT_PASS_PATH["wrfsubhf"]).exists():
        _write_lifecycle(root, run_id=run_id, status="PENDING", product="wrfsubhf")
    try:
        for product in PRODUCTS:
            _run_product(
                root,
                run_id=run_id,
                product=product,
                runtime=runtime,
                pause_requested=requested,
            )
        return _close_combined(root, run_id)
    except PauseRequested as exc:
        _write_lifecycle(
            root, run_id=run_id, status="PAUSED", message=str(exc)
        )
        raise
    except Exception as exc:
        _write_lifecycle(
            root,
            run_id=run_id,
            status="FAILED",
            message=f"{type(exc).__name__}: {exc}",
        )
        raise


def _disk_preflight(root: Path) -> dict[str, Any]:
    report = _read_json(root / R14_STEP04_REPORT_PATH)
    required = int(report["projection"]["required_disk_bytes_with_margin"])
    available = shutil.disk_usage(root).free
    return {
        "required_bytes_with_25_percent_margin": required,
        "available_bytes_now": available,
        "pass": available >= required,
    }


def owner_run_contract(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    runtime = load_runtime_config(root)
    verify_r14_step04_pass(root)
    plans = {product: verify_r14_product_plan(root, product) for product in PRODUCTS}
    units = {product: build_unit_specs(root, product) for product in PRODUCTS}
    disk = _disk_preflight(root)
    if not disk["pass"]:
        raise AcquisitionWorkflowError("owner-full disk safety gate failed")
    return {
        "scope_id": R14_SCOPE_ID,
        "owner_facing_step": 5,
        "required_scope": "owner-full",
        "phase_order": runtime["phase_order"],
        "max_total_download_workers": 8,
        "product_request_counts": {
            product: int(plans[product]["request_row_count"]) for product in PRODUCTS
        },
        "combined_request_count": COMBINED_REQUEST_COUNT,
        "product_work_unit_counts": {product: len(units[product]) for product in PRODUCTS},
        "combined_work_unit_count": COMBINED_UNIT_COUNT,
        "work_unit": "complete product target day; H14 is one preceding static unit",
        "pause_boundary": "no incomplete target day is published",
        "raw_grib_retained": False,
        "disk": disk,
    }


def prepare_owner_run(project_root: Path | str) -> dict[str, Any]:
    """Seal the network-free implementation after all code and tests are final."""

    root = load_project_paths(project_root).root
    return write_ready_record(root, execution_contract=owner_run_contract(root))


def acquisition_preflight(project_root: Path | str) -> dict[str, Any]:
    """Verify owner authority, lineage, plans, code seal, and disk with no network I/O."""

    root = load_project_paths(project_root).root
    ready = verify_ready_record(root)
    contract = owner_run_contract(root)
    suggested_run_id = make_run_id(5, "owner-full", "r14-acquisition")
    return {
        "schema_version": "KDEN_V375_R14_ACQUISITION_PREFLIGHT_V1",
        "status": "READY_FOR_OWNER_FULL_ACQUISITION",
        "network_requests_made": 0,
        "readiness_record_sha256": ready["record_sha256"],
        **contract,
        "suggested_run_id": suggested_run_id,
        "start_command": (
            ".venv/bin/kden-v375 run-step 5 --scope owner-full "
            f"--run-id {suggested_run_id}"
        ),
        "live_status_command": (
            f".venv/bin/kden-v375 live-status --run-id {suggested_run_id} "
            "--interval-seconds 5"
        ),
        "eta_command": f".venv/bin/kden-v375 eta --run-id {suggested_run_id}",
        "pause_command": f".venv/bin/kden-v375 pause-run {suggested_run_id}",
        "resume_command": f".venv/bin/kden-v375 resume {suggested_run_id}",
    }
