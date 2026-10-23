"""Successor R14 cycle schedule with a strictly right-open target window.

The historical Step 02 schedule is retained as immutable evidence.  This
module rebuilds the same target-day and cycle envelope under the corrected
``[07Z_d, 07Z_{d+1})`` rule and publishes it to a separate R14 namespace.
"""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .contracts import ContractError, load_project_paths
from .hashes import canonical_json_bytes, sha256_file
from .io.atomic import atomic_write_json
from .io.parquet import atomic_write_table
from .r14 import R14_BUNDLE_PATH, R14_SCOPE_ID, verify_r14_registry_bundle
from .r14_records import read_historical_record_identity, verify_r14_attestation
from .request_plans import native_leads
from .registries import load_parquet_schema
from .schedule import (
    PRODUCTS,
    SchedulePolicy,
    cycle_candidates_for_target,
    dst_transition_dates,
    load_schedule_policy,
    logical_schedule_sha256,
    native_horizon,
    target_dates,
    validate_horizon_evidence,
)


R14_SCHEDULE_POLICY_SCHEMA_VERSION = "KDEN_V375_R14_CYCLE_SCHEDULE_POLICY_V1"
R14_SCHEDULE_MANIFEST_SCHEMA_VERSION = "KDEN_V375_R14_CYCLE_SCHEDULE_MANIFEST_V1"
R14_SCHEDULE_POLICY_PATH = "config/cycle_schedule_r14_v375.toml"
R14_SCHEDULE_PARQUET_PATH = (
    "hrrr_v4_local_archive/common/cycle_schedule_r14/cycle_schedule_r14_v375.parquet"
)
R14_SCHEDULE_MANIFEST_PATH = (
    "hrrr_v4_local_archive/common/cycle_schedule_r14/"
    "cycle_schedule_r14_v375_manifest.json"
)
HISTORICAL_SCHEDULE_MANIFEST_PATH = (
    "hrrr_v4_local_archive/common/cycle_schedule/cycle_schedule_v375_manifest.json"
)
HORIZON_EVIDENCE_PATH = "reports/step_02_horizon_discovery_v375.json"
SCHEDULE_SCHEMA_PATH = "schemas/cycle_schedule_v375.json"
EXPECTED_NATIVE_STATE_COUNTS = {"wrfsfcf": 563_583, "wrfsubhf": 2_156_601}
EXPECTED_PRODUCT_CYCLE_COUNT = 33_279


class R14ScheduleContractError(ContractError):
    """The R14 right-open temporal contract was violated."""


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise R14ScheduleContractError(f"JSON contract must contain an object: {path}")
    return value


def load_r14_schedule_policy(project_root: Path | str) -> SchedulePolicy:
    """Load R14 policy while proving all non-endpoint schedule inputs stayed fixed."""

    paths = load_project_paths(project_root)
    raw = _read_toml(paths.root / R14_SCHEDULE_POLICY_PATH)
    if (
        raw.get("schema_version") != R14_SCHEDULE_POLICY_SCHEMA_VERSION
        or raw.get("scope_id") != R14_SCOPE_ID
    ):
        raise R14ScheduleContractError("unsupported R14 schedule policy identity")
    target = raw["target_dates"]
    envelope = raw["cycle_envelope"]
    window = raw["target_window"]
    availability = raw["availability"]
    horizons = raw["horizon"]
    policy = SchedulePolicy(
        historical_start=date.fromisoformat(target["start"]),
        historical_end=date.fromisoformat(target["end"]),
        expected_target_date_count=int(target["expected_count"]),
        timezone_name=str(envelope["timezone"]),
        previous_local_day_hours=tuple(int(value) for value in envelope["previous_local_day_hours"]),
        target_local_day_first_hour=int(envelope["target_local_day_first_hour"]),
        target_local_day_last_hour=int(envelope["target_local_day_last_hour"]),
        expected_product_cycle_count=int(envelope["expected_product_cycle_count"]),
        window_start_utc_hour=int(window["start_utc_hour"]),
        window_end_utc_hour=int(window["end_utc_hour"]),
        window_end_day_offset=int(window["end_day_offset"]),
        availability_policy_id=str(availability["policy_id"]),
        availability_lag_minutes=int(availability["lag_minutes"]),
        hourly_ordinary_max_forecast_hour=int(
            horizons["wrfsfcf"]["ordinary_max_forecast_hour"]
        ),
        hourly_extended_max_forecast_hour=int(
            horizons["wrfsfcf"]["extended_max_forecast_hour"]
        ),
        hourly_extended_cycle_hours_utc=tuple(
            int(value) for value in horizons["wrfsfcf"]["extended_cycle_hours_utc"]
        ),
        subhourly_max_forecast_hour=int(
            horizons["wrfsubhf"]["ordinary_max_forecast_hour"]
        ),
    )
    if window.get("retention_rule") != "native_valid_time_lt_window_end_and_le_native_horizon":
        raise R14ScheduleContractError("R14 right-open retention rule changed")
    if window.get("endpoint_inclusive_when_native") is not False:
        raise R14ScheduleContractError("R14 schedule must exclude an exact window endpoint")
    if window.get("retain_fh00") is not True:
        raise R14ScheduleContractError("R14 schedule must retain FH00")
    if policy.expected_product_cycle_count != EXPECTED_PRODUCT_CYCLE_COUNT:
        raise R14ScheduleContractError("R14 per-product cycle count changed")
    if policy.expected_target_date_count != 2_080:
        raise R14ScheduleContractError("R14 target-date count changed")
    for product, expected in EXPECTED_NATIVE_STATE_COUNTS.items():
        observed = int(horizons[product]["expected_native_state_count"])
        if observed != expected:
            raise R14ScheduleContractError(
                f"R14 expected native-state count changed for {product}"
            )
    if (
        int(horizons["wrfsfcf"]["native_cadence_minutes"]) != 60
        or int(horizons["wrfsubhf"]["native_cadence_minutes"]) != 15
    ):
        raise R14ScheduleContractError("R14 native cadence changed")
    historical_policy = load_schedule_policy(paths.root)
    if policy != historical_policy:
        raise R14ScheduleContractError(
            "R14 changed a schedule input other than endpoint inclusion semantics"
        )
    return policy


def _window(policy: SchedulePolicy, target_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_day, time(policy.window_start_utc_hour), tzinfo=UTC)
    end_day = target_day + timedelta(days=policy.window_end_day_offset)
    end = datetime.combine(end_day, time(policy.window_end_utc_hour), tzinfo=UTC)
    return start, end


def _cadence_minutes(product: str) -> int:
    if product == "wrfsfcf":
        return 60
    if product == "wrfsubhf":
        return 15
    raise R14ScheduleContractError(f"unsupported HRRR product: {product!r}")


def build_r14_schedule_rows(policy: SchedulePolicy) -> list[dict[str, Any]]:
    """Build rows whose retained end is the final included native valid time."""

    rows: list[dict[str, Any]] = []
    for target_day in target_dates(policy):
        candidates = cycle_candidates_for_target(target_day, policy.timezone_name)
        window_start, window_end = _window(policy, target_day)
        for product in PRODUCTS:
            cadence = timedelta(minutes=_cadence_minutes(product))
            last_time_before_window_end = window_end - cadence
            for candidate in candidates:
                cycle_utc = candidate.cycle_init_utc
                local = candidate.cycle_init_local
                max_hour, horizon_class = native_horizon(policy, product, cycle_utc)
                native_end = cycle_utc + timedelta(hours=max_hour)
                retained_end = min(native_end, last_time_before_window_end)
                offset = local.utcoffset()
                if offset is None:
                    raise R14ScheduleContractError(
                        "converted local cycle lacks a UTC offset"
                    )
                rows.append(
                    {
                        "target_day": target_day,
                        "product": product,
                        "cycle_init_utc": cycle_utc,
                        "cycle_init_local": local,
                        "local_calendar_date": local.date(),
                        "local_cycle_hour": local.hour,
                        "utc_offset_minutes": int(offset.total_seconds() // 60),
                        "dst_flag": bool(local.dst()),
                        "local_fold": int(local.fold),
                        "hrrr_version": policy.hrrr_version,
                        "native_max_forecast_hour": max_hour,
                        "horizon_class": horizon_class,
                        "window_start_utc": window_start,
                        "window_end_utc": window_end,
                        "retained_valid_start_utc": cycle_utc,
                        "retained_valid_end_utc": retained_end,
                        "availability_policy_id": policy.availability_policy_id,
                        "emulated_complete_time_utc": cycle_utc
                        + timedelta(minutes=policy.availability_lag_minutes),
                        "actual_first_seen_utc": None,
                        "availability_basis": "historical_cycle_init_plus_105_minutes",
                        "source_inventory_hash": None,
                        "complete_flag": False,
                        "missing_or_quarantine_reason": "PENDING_ACQUISITION_INVENTORY",
                        "retrieval_run_id": None,
                    }
                )
    return rows


def validate_r14_schedule_rows(
    rows: list[dict[str, Any]], policy: SchedulePolicy
) -> dict[str, Any]:
    """Fail closed on DST, horizons, FH00, and every right-open endpoint."""

    expected_row_count = policy.expected_product_cycle_count * len(PRODUCTS)
    if len(rows) != expected_row_count:
        raise R14ScheduleContractError("total R14 product-cycle count changed")
    observed_dates = {row["target_day"] for row in rows}
    if observed_dates != set(target_dates(policy)):
        raise R14ScheduleContractError("R14 target-date coverage changed")
    keys = [(row["target_day"], row["product"], row["cycle_init_utc"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise R14ScheduleContractError("R14 cycle schedule primary key is not unique")

    timezone = ZoneInfo(policy.timezone_name)
    product_counts = Counter(row["product"] for row in rows)
    native_counts = Counter()
    horizon_counts: dict[str, Counter[str]] = {product: Counter() for product in PRODUCTS}
    capped_counts = Counter()
    for row in rows:
        target_day = row["target_day"]
        cycle_utc = row["cycle_init_utc"]
        local = row["cycle_init_local"]
        product = row["product"]
        cadence = timedelta(minutes=_cadence_minutes(product))
        if cycle_utc.utcoffset() != timedelta(0):
            raise R14ScheduleContractError("R14 cycle identity is not UTC")
        if local != cycle_utc.astimezone(timezone) or row["local_fold"] != local.fold:
            raise R14ScheduleContractError("R14 local cycle metadata does not round-trip")
        previous_day = target_day - timedelta(days=1)
        if not (
            (local.date() == previous_day and local.hour == 23)
            or (local.date() == target_day and 0 <= local.hour <= 14)
        ):
            raise R14ScheduleContractError("R14 cycle falls outside local envelope")
        window_start, window_end = _window(policy, target_day)
        if row["window_start_utc"] != window_start or row["window_end_utc"] != window_end:
            raise R14ScheduleContractError("R14 target-window bounds changed")
        max_hour, horizon_class = native_horizon(policy, product, cycle_utc)
        native_end = cycle_utc + timedelta(hours=max_hour)
        expected_end = min(native_end, window_end - cadence)
        if row["retained_valid_start_utc"] != cycle_utc:
            raise R14ScheduleContractError("an R14 cycle does not begin at FH00")
        if row["retained_valid_end_utc"] != expected_end:
            raise R14ScheduleContractError("R14 retained endpoint changed")
        if not expected_end < window_end:
            raise R14ScheduleContractError("R14 schedule included the right-open endpoint")
        if expected_end < cycle_utc:
            raise R14ScheduleContractError("R14 retained endpoint precedes initialization")
        leads = native_leads(row, product)
        if not leads or leads[0] != 0:
            raise R14ScheduleContractError("R14 schedule lost FH00")
        native_counts[product] += len(leads)
        horizon_counts[product][horizon_class] += 1
        if expected_end < native_end:
            capped_counts[product] += 1
        if row["emulated_complete_time_utc"] != cycle_utc + timedelta(minutes=105):
            raise R14ScheduleContractError("R14 historical availability time changed")

    if dict(product_counts) != {
        "wrfsfcf": EXPECTED_PRODUCT_CYCLE_COUNT,
        "wrfsubhf": EXPECTED_PRODUCT_CYCLE_COUNT,
    }:
        raise R14ScheduleContractError("R14 per-product cycle count changed")
    if dict(native_counts) != EXPECTED_NATIVE_STATE_COUNTS:
        raise R14ScheduleContractError("R14 native-state accounting changed")

    hourly_rows = [row for row in rows if row["product"] == "wrfsfcf"]
    day_class_counts = Counter(Counter(
        row["target_day"] for row in hourly_rows
    ).values())
    if day_class_counts != Counter({16: 2_069, 15: 6, 17: 5}):
        raise R14ScheduleContractError("R14 ordinary/DST cycle classes changed")
    transition_tests: list[dict[str, Any]] = []
    for year in range(2021, 2027):
        transitions = dst_transition_dates(year, policy.timezone_name)
        observed_counts = [
            len(cycle_candidates_for_target(value, policy.timezone_name))
            for value in transitions
        ]
        if sorted(observed_counts) != [15, 17]:
            raise R14ScheduleContractError(f"R14 DST transition coverage failed in {year}")
        transition_tests.extend(
            {
                "target_day": value.isoformat(),
                "cycle_count": count,
                "in_historical_range": policy.historical_start
                <= value
                <= policy.historical_end,
            }
            for value, count in zip(transitions, observed_counts, strict=True)
        )

    first = cycle_candidates_for_target(policy.historical_start, policy.timezone_name)[0]
    if first.cycle_init_local.date() != date(2020, 12, 31):
        raise R14ScheduleContractError("R14 first target lost prior-local c23")
    return {
        "scope_id": R14_SCOPE_ID,
        "target_date_count": len(observed_dates),
        "total_product_cycle_count": len(rows),
        "per_product_cycle_count": dict(sorted(product_counts.items())),
        "native_state_count": dict(sorted(native_counts.items())),
        "target_date_cycle_classes": {
            "spring_forward_15": day_class_counts[15],
            "ordinary_16": day_class_counts[16],
            "fall_back_17": day_class_counts[17],
        },
        "horizon_class_counts": {
            product: dict(sorted(counts.items()))
            for product, counts in horizon_counts.items()
        },
        "target_window_capped_cycle_counts": dict(sorted(capped_counts.items())),
        "window_semantics": "[07Z_d,07Z_d_plus_1)",
        "all_native_valid_times_strictly_before_window_end": True,
        "all_cycles_begin_at_fh00": True,
        "utc_cycle_keys_unique_per_product": True,
        "first_source_local_date": first.cycle_init_local.date().isoformat(),
        "dst_transition_tests": transition_tests,
    }


def _read_parquet(path: Path) -> Any:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise R14ScheduleContractError("pyarrow is required for the R14 schedule") from exc
    return pq.read_table(path)


def _publish_deterministic_json(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists():
        if canonical_json_bytes(_read_json(path)) != canonical_json_bytes(value):
            raise R14ScheduleContractError(f"immutable R14 artifact differs: {path}")
        return sha256_file(path)
    return atomic_write_json(path, value, replace=False)


def seal_r14_cycle_schedule(project_root: Path | str) -> dict[str, Any]:
    """Publish and verify the successor schedule without touching historical Step 02."""

    paths = load_project_paths(project_root)
    registry = verify_r14_registry_bundle(paths.root)["bundle"]
    step01_r14 = verify_r14_attestation(paths.root, "STEP_01_R14")
    historical_step02 = read_historical_record_identity(paths.root, 2)
    policy = load_r14_schedule_policy(paths.root)
    horizon = validate_horizon_evidence(paths.root, policy)
    rows = build_r14_schedule_rows(policy)
    evidence = validate_r14_schedule_rows(rows, policy)
    logical_hash = logical_schedule_sha256(rows)
    schema = load_parquet_schema(paths.root, "cycle_schedule_v375.json")
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise R14ScheduleContractError("pyarrow is required to publish the R14 schedule") from exc
    destination = paths.root / R14_SCHEDULE_PARQUET_PATH
    if destination.exists():
        observed = _read_parquet(destination)
        if not observed.schema.equals(schema, check_metadata=True):
            raise R14ScheduleContractError("existing R14 schedule schema changed")
        if logical_schedule_sha256(observed.to_pylist()) != logical_hash:
            raise R14ScheduleContractError("existing immutable R14 schedule differs")
        parquet_hash = sha256_file(destination)
    else:
        table = pa.Table.from_pylist(rows, schema=schema)
        parquet_hash = atomic_write_table(
            table, destination, schema=schema, compression="zstd", replace=False
        )
    observed = _read_parquet(destination)
    observed_rows = observed.to_pylist()
    if logical_schedule_sha256(observed_rows) != logical_hash:
        raise R14ScheduleContractError("published R14 schedule changed on round trip")
    if validate_r14_schedule_rows(observed_rows, policy) != evidence:
        raise R14ScheduleContractError("R14 schedule evidence changed on round trip")

    manifest_body = {
        "schema_version": R14_SCHEDULE_MANIFEST_SCHEMA_VERSION,
        "schedule_id": "KDEN_V375_R14_CYCLE_SCHEDULE_20210101_20260911_V1",
        "scope_id": R14_SCOPE_ID,
        "target_date_start": policy.historical_start.isoformat(),
        "target_date_end": policy.historical_end.isoformat(),
        "timezone": policy.timezone_name,
        "window_semantics": "[07Z_d,07Z_d_plus_1)",
        "logical_schedule_sha256": logical_hash,
        "row_count": len(rows),
        "per_product_cycle_count": evidence["per_product_cycle_count"],
        "native_state_count": evidence["native_state_count"],
        "parquet": {
            "path": R14_SCHEDULE_PARQUET_PATH,
            "sha256": parquet_hash,
            "size_bytes": destination.stat().st_size,
            "compression": "zstd",
        },
        "schema": {
            "path": SCHEDULE_SCHEMA_PATH,
            "sha256": sha256_file(paths.root / SCHEDULE_SCHEMA_PATH),
        },
        "schedule_policy": {
            "path": R14_SCHEDULE_POLICY_PATH,
            "sha256": sha256_file(paths.root / R14_SCHEDULE_POLICY_PATH),
        },
        "horizon_discovery": {
            "path": HORIZON_EVIDENCE_PATH,
            "sha256": sha256_file(paths.root / HORIZON_EVIDENCE_PATH),
            "evidence_id": horizon["evidence_id"],
        },
        "r14_registry_bundle": {
            "path": R14_BUNDLE_PATH,
            "bundle_sha256": registry["bundle_sha256"],
            "file_sha256": sha256_file(paths.root / R14_BUNDLE_PATH),
        },
        "step01_r14_record_sha256": step01_r14["record_sha256"],
        "historical_step02_pass": historical_step02,
        "historical_schedule_manifest": {
            "path": HISTORICAL_SCHEDULE_MANIFEST_PATH,
            "sha256": sha256_file(paths.root / HISTORICAL_SCHEDULE_MANIFEST_PATH),
            "role": "lineage_evidence_only_not_active_R14_schedule",
        },
    }
    manifest = {
        **manifest_body,
        "manifest_sha256": sha256(canonical_json_bytes(manifest_body)).hexdigest(),
    }
    _publish_deterministic_json(paths.root / R14_SCHEDULE_MANIFEST_PATH, manifest)
    return {
        "manifest": manifest,
        "gate_evidence": {
            "schedule": evidence,
            "horizon_discovery": horizon,
            "publication": {
                "logical_schedule_sha256": logical_hash,
                "parquet_sha256": parquet_hash,
                "parquet_roundtrip_verified": True,
                "schema_roundtrip_verified": True,
                "historical_schedule_unchanged": True,
            },
        },
    }


def verify_r14_cycle_schedule(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    manifest = _read_json(paths.root / R14_SCHEDULE_MANIFEST_PATH)
    if manifest.get("schema_version") != R14_SCHEDULE_MANIFEST_SCHEMA_VERSION:
        raise R14ScheduleContractError("unsupported R14 schedule manifest schema")
    body = dict(manifest)
    supplied = body.pop("manifest_sha256", None)
    if supplied != sha256(canonical_json_bytes(body)).hexdigest():
        raise R14ScheduleContractError("R14 schedule manifest content hash mismatch")
    registry = verify_r14_registry_bundle(paths.root)["bundle"]
    if manifest["r14_registry_bundle"]["bundle_sha256"] != registry["bundle_sha256"]:
        raise R14ScheduleContractError("R14 schedule points to another registry bundle")
    step01_r14 = verify_r14_attestation(paths.root, "STEP_01_R14")
    if manifest.get("step01_r14_record_sha256") != step01_r14["record_sha256"]:
        raise R14ScheduleContractError("R14 schedule points to another Step 01 attestation")
    historical_step02 = read_historical_record_identity(paths.root, 2)
    if manifest.get("historical_step02_pass") != historical_step02:
        raise R14ScheduleContractError("R14 schedule lost historical Step 02 lineage")
    parquet_path = paths.root / manifest["parquet"]["path"]
    if (
        sha256_file(parquet_path) != manifest["parquet"]["sha256"]
        or parquet_path.stat().st_size != manifest["parquet"]["size_bytes"]
    ):
        raise R14ScheduleContractError("sealed R14 schedule Parquet changed")
    schema = load_parquet_schema(paths.root, "cycle_schedule_v375.json")
    table = _read_parquet(parquet_path)
    if not table.schema.equals(schema, check_metadata=True):
        raise R14ScheduleContractError("sealed R14 schedule schema changed")
    rows = table.to_pylist()
    if logical_schedule_sha256(rows) != manifest["logical_schedule_sha256"]:
        raise R14ScheduleContractError("sealed R14 schedule logical hash changed")
    gates = validate_r14_schedule_rows(rows, load_r14_schedule_policy(paths.root))
    if gates["native_state_count"] != manifest["native_state_count"]:
        raise R14ScheduleContractError("R14 schedule native-state manifest count changed")
    return {"manifest": manifest, "gate_evidence": gates}
