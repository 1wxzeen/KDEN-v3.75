"""DST-safe native-UTC cycle scheduling and sealed Parquet publication."""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from .contracts import ContractError, load_project_paths
from .hashes import canonical_json_bytes, sha256_file
from .io.atomic import atomic_write_json
from .io.parquet import atomic_write_table
from .registries import load_parquet_schema, verify_registry_bundle


SCHEDULE_POLICY_SCHEMA_VERSION = "KDEN_V375_CYCLE_SCHEDULE_POLICY_V1"
HORIZON_EVIDENCE_SCHEMA_VERSION = "KDEN_V375_HORIZON_DISCOVERY_V1"
SCHEDULE_MANIFEST_SCHEMA_VERSION = "KDEN_V375_CYCLE_SCHEDULE_MANIFEST_V1"
SCHEDULE_POLICY_PATH = "config/cycle_schedule_v375.toml"
HORIZON_EVIDENCE_PATH = "reports/step_02_horizon_discovery_v375.json"
SCHEDULE_PARQUET_PATH = (
    "hrrr_v4_local_archive/common/cycle_schedule/cycle_schedule_v375.parquet"
)
SCHEDULE_MANIFEST_PATH = (
    "hrrr_v4_local_archive/common/cycle_schedule/cycle_schedule_v375_manifest.json"
)
PRODUCTS = ("wrfsfcf", "wrfsubhf")


class ScheduleContractError(ContractError):
    """The Step 02 temporal or horizon contract was violated."""


@dataclass(frozen=True, slots=True)
class SchedulePolicy:
    historical_start: date
    historical_end: date
    expected_target_date_count: int
    timezone_name: str
    previous_local_day_hours: tuple[int, ...]
    target_local_day_first_hour: int
    target_local_day_last_hour: int
    expected_product_cycle_count: int
    window_start_utc_hour: int
    window_end_utc_hour: int
    window_end_day_offset: int
    availability_policy_id: str
    availability_lag_minutes: int
    hourly_ordinary_max_forecast_hour: int
    hourly_extended_max_forecast_hour: int
    hourly_extended_cycle_hours_utc: tuple[int, ...]
    subhourly_max_forecast_hour: int
    hrrr_version: str = "v4"


@dataclass(frozen=True, slots=True)
class CycleCandidate:
    cycle_init_utc: datetime
    cycle_init_local: datetime
    envelope_member: str


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def load_schedule_policy(project_root: Path | str) -> SchedulePolicy:
    paths = load_project_paths(project_root)
    raw = _read_toml(paths.root / SCHEDULE_POLICY_PATH)
    if raw.get("schema_version") != SCHEDULE_POLICY_SCHEMA_VERSION:
        raise ScheduleContractError("unsupported cycle-schedule policy schema")
    project = _read_toml(paths.config)["project"]
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
    expected_from_project = {
        "historical_start": date.fromisoformat(project["historical_start"]),
        "historical_end": date.fromisoformat(project["historical_end"]),
        "timezone_name": str(project["timezone"]),
        "window_start_utc_hour": int(project["target_window_start_utc_hour"]),
        "window_end_utc_hour": int(project["target_window_end_utc_hour"]),
        "availability_policy_id": str(project["availability_policy_id"]),
    }
    for field, expected in expected_from_project.items():
        if getattr(policy, field) != expected:
            raise ScheduleContractError(f"schedule policy disagrees with project config: {field}")
    if (policy.historical_end - policy.historical_start).days + 1 != 2080:
        raise ScheduleContractError("historical range does not contain exactly 2,080 dates")
    if policy.expected_target_date_count != 2080:
        raise ScheduleContractError("expected target-date count changed")
    if policy.previous_local_day_hours != (23,):
        raise ScheduleContractError("previous-local-day cycle anchor changed")
    if (policy.target_local_day_first_hour, policy.target_local_day_last_hour) != (0, 14):
        raise ScheduleContractError("target-local-day cycle envelope changed")
    if policy.availability_lag_minutes != 105:
        raise ScheduleContractError("historical availability lag changed")
    if policy.hourly_extended_cycle_hours_utc != (0, 6, 12, 18):
        raise ScheduleContractError("extended hourly UTC initialization set changed")
    if (
        policy.hourly_ordinary_max_forecast_hour,
        policy.hourly_extended_max_forecast_hour,
        policy.subhourly_max_forecast_hour,
    ) != (18, 48, 18):
        raise ScheduleContractError("native HRRR horizon boundary changed")
    return policy


def _utc_hours(start: datetime, end: datetime) -> Iterable[datetime]:
    current = start
    while current < end:
        yield current
        current += timedelta(hours=1)


def cycle_candidates_for_target(
    target_day: date, timezone_name: str = "America/Denver"
) -> tuple[CycleCandidate, ...]:
    """Enumerate UTC first, then filter by converted local calendar membership."""

    timezone = ZoneInfo(timezone_name)
    previous_day = target_day - timedelta(days=1)
    search_start = datetime.combine(previous_day, time.min, tzinfo=UTC) - timedelta(hours=12)
    search_end = datetime.combine(target_day + timedelta(days=2), time.min, tzinfo=UTC)
    candidates: list[CycleCandidate] = []
    for cycle_utc in _utc_hours(search_start, search_end):
        local = cycle_utc.astimezone(timezone)
        if local.date() == previous_day and local.hour == 23:
            candidates.append(CycleCandidate(cycle_utc, local, "previous_local_c23"))
        elif local.date() == target_day and 0 <= local.hour <= 14:
            candidates.append(CycleCandidate(cycle_utc, local, "target_local_c00_c14"))
    return tuple(sorted(candidates, key=lambda value: value.cycle_init_utc))


def target_dates(policy: SchedulePolicy) -> tuple[date, ...]:
    return tuple(
        policy.historical_start + timedelta(days=offset)
        for offset in range((policy.historical_end - policy.historical_start).days + 1)
    )


def native_horizon(
    policy: SchedulePolicy, product: str, cycle_init_utc: datetime
) -> tuple[int, str]:
    if product == "wrfsfcf":
        if cycle_init_utc.hour in policy.hourly_extended_cycle_hours_utc:
            return policy.hourly_extended_max_forecast_hour, "extended"
        return policy.hourly_ordinary_max_forecast_hour, "ordinary"
    if product == "wrfsubhf":
        return policy.subhourly_max_forecast_hour, "ordinary"
    raise ScheduleContractError(f"unsupported HRRR product: {product!r}")


def _window(policy: SchedulePolicy, target_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_day, time(policy.window_start_utc_hour), tzinfo=UTC)
    end_day = target_day + timedelta(days=policy.window_end_day_offset)
    end = datetime.combine(end_day, time(policy.window_end_utc_hour), tzinfo=UTC)
    return start, end


def build_schedule_rows(policy: SchedulePolicy) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target_day in target_dates(policy):
        candidates = cycle_candidates_for_target(target_day, policy.timezone_name)
        window_start, window_end = _window(policy, target_day)
        for product in PRODUCTS:
            for candidate in candidates:
                cycle_utc = candidate.cycle_init_utc
                local = candidate.cycle_init_local
                max_hour, horizon_class = native_horizon(policy, product, cycle_utc)
                retained_end = min(cycle_utc + timedelta(hours=max_hour), window_end)
                offset = local.utcoffset()
                if offset is None:
                    raise ScheduleContractError("converted local cycle lacks a UTC offset")
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


def dst_transition_dates(year: int, timezone_name: str) -> tuple[date, ...]:
    """Find civil transition dates by observing an hourly UTC timeline."""

    timezone = ZoneInfo(timezone_name)
    start = datetime(year, 1, 1, tzinfo=UTC) - timedelta(days=1)
    end = datetime(year + 1, 1, 2, tzinfo=UTC)
    previous_offset: timedelta | None = None
    transitions: list[date] = []
    for value in _utc_hours(start, end):
        local = value.astimezone(timezone)
        offset = local.utcoffset()
        if previous_offset is not None and offset != previous_offset and local.date() not in transitions:
            transitions.append(local.date())
        previous_offset = offset
    return tuple(transitions)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        text = value.isoformat()
        return text.replace("+00:00", "Z") if value.utcoffset() == timedelta(0) else text
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def logical_schedule_sha256(rows: Iterable[Mapping[str, Any]]) -> str:
    digest = sha256()
    for row in rows:
        digest.update(canonical_json_bytes({key: _iso(value) for key, value in row.items()}))
    return digest.hexdigest()


def validate_horizon_evidence(
    project_root: Path | str, policy: SchedulePolicy
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    with (paths.root / HORIZON_EVIDENCE_PATH).open("r", encoding="utf-8") as stream:
        evidence = json.load(stream)
    if evidence.get("schema_version") != HORIZON_EVIDENCE_SCHEMA_VERSION:
        raise ScheduleContractError("unsupported horizon-discovery evidence schema")
    conclusion = evidence.get("frozen_conclusion", {})
    hourly = conclusion.get("wrfsfcf", {})
    subhourly = conclusion.get("wrfsubhf", {})
    expected = {
        "ordinary_max_forecast_hour": policy.hourly_ordinary_max_forecast_hour,
        "extended_max_forecast_hour": policy.hourly_extended_max_forecast_hour,
        "extended_cycle_hours_utc": list(policy.hourly_extended_cycle_hours_utc),
    }
    if hourly != expected:
        raise ScheduleContractError("hourly horizon conclusion disagrees with schedule policy")
    if subhourly != {
        "ordinary_max_forecast_hour": policy.subhourly_max_forecast_hour,
        "extended_cycle_hours_utc": [],
    }:
        raise ScheduleContractError("subhourly horizon conclusion disagrees with schedule policy")
    groups = evidence.get("probe_groups", [])
    if len(groups) != 4:
        raise ScheduleContractError("horizon discovery must contain four probe groups")
    for group in groups:
        if group.get("present_http_status") != 200 or group.get("next_http_status") != 404:
            raise ScheduleContractError("horizon boundary probe did not close at present/next")
    covered_dates = {
        value for group in groups for value in group.get("dates", [])
    }
    if not {"2021-01-01", "2024-06-01", "2026-09-11"}.issubset(covered_dates):
        raise ScheduleContractError("horizon evidence does not span early, middle, and final years")
    extended_hours = {
        int(value)
        for group in groups
        if group.get("product") == "wrfsfcf"
        and group.get("present_forecast_hour") == 48
        for value in group.get("cycle_hours_utc", [])
    }
    if extended_hours != set(policy.hourly_extended_cycle_hours_utc):
        raise ScheduleContractError("not every extended UTC cycle hour was probed")
    return {
        "evidence_id": evidence["evidence_id"],
        "source_root": evidence["source_root"],
        "probe_group_count": len(groups),
        "archive_years_sampled": [2021, 2024, 2026],
        "hourly_ordinary_max_forecast_hour": policy.hourly_ordinary_max_forecast_hour,
        "hourly_extended_max_forecast_hour": policy.hourly_extended_max_forecast_hour,
        "hourly_extended_cycle_hours_utc": list(policy.hourly_extended_cycle_hours_utc),
        "subhourly_max_forecast_hour": policy.subhourly_max_forecast_hour,
    }


def validate_schedule_rows(
    rows: list[dict[str, Any]], policy: SchedulePolicy
) -> dict[str, Any]:
    if len(rows) != policy.expected_product_cycle_count * len(PRODUCTS):
        raise ScheduleContractError("total product-cycle count changed")
    expected_dates = target_dates(policy)
    observed_dates = {row["target_day"] for row in rows}
    if observed_dates != set(expected_dates):
        raise ScheduleContractError("target-date coverage changed")
    keys = [(row["target_day"], row["product"], row["cycle_init_utc"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ScheduleContractError("cycle schedule primary key is not unique")

    timezone = ZoneInfo(policy.timezone_name)
    product_counts = Counter(row["product"] for row in rows)
    horizon_counts: dict[str, Counter[str]] = {product: Counter() for product in PRODUCTS}
    capped_counts = Counter()
    for row in rows:
        target_day = row["target_day"]
        cycle_utc = row["cycle_init_utc"]
        local = row["cycle_init_local"]
        if cycle_utc.utcoffset() != timedelta(0):
            raise ScheduleContractError("cycle identity is not UTC")
        if local != cycle_utc.astimezone(timezone) or row["local_fold"] != local.fold:
            raise ScheduleContractError("local cycle metadata does not round-trip from UTC")
        previous_day = target_day - timedelta(days=1)
        in_envelope = (
            local.date() == previous_day and local.hour == 23
        ) or (
            local.date() == target_day and 0 <= local.hour <= 14
        )
        if not in_envelope:
            raise ScheduleContractError("cycle falls outside the frozen local envelope")
        window_start, window_end = _window(policy, target_day)
        if row["window_start_utc"] != window_start or row["window_end_utc"] != window_end:
            raise ScheduleContractError("target-window bounds changed")
        max_hour, horizon_class = native_horizon(policy, row["product"], cycle_utc)
        if (
            row["native_max_forecast_hour"] != max_hour
            or row["horizon_class"] != horizon_class
        ):
            raise ScheduleContractError("native horizon classification changed")
        expected_end = min(cycle_utc + timedelta(hours=max_hour), window_end)
        if row["retained_valid_start_utc"] != cycle_utc:
            raise ScheduleContractError("a cycle does not begin at FH00")
        if row["retained_valid_end_utc"] != expected_end or expected_end > window_end:
            raise ScheduleContractError("TARGET_WINDOW retained endpoint changed")
        if expected_end < cycle_utc:
            raise ScheduleContractError("retained endpoint precedes cycle initialization")
        if row["emulated_complete_time_utc"] != cycle_utc + timedelta(minutes=105):
            raise ScheduleContractError("historical availability time changed")
        if row["availability_policy_id"] != policy.availability_policy_id:
            raise ScheduleContractError("availability policy ID changed")
        horizon_counts[row["product"]][horizon_class] += 1
        if expected_end < cycle_utc + timedelta(hours=max_hour):
            capped_counts[row["product"]] += 1

    if any(product_counts[product] != policy.expected_product_cycle_count for product in PRODUCTS):
        raise ScheduleContractError("per-product cycle count changed")
    for product in PRODUCTS:
        utc_keys = [row["cycle_init_utc"] for row in rows if row["product"] == product]
        if len(utc_keys) != len(set(utc_keys)):
            raise ScheduleContractError(f"UTC cycle keys are not unique for {product}")

    base_rows = [row for row in rows if row["product"] == "wrfsfcf"]
    per_day = Counter(row["target_day"] for row in base_rows)
    day_class_counts = Counter(per_day.values())
    if day_class_counts != Counter({16: 2069, 15: 6, 17: 5}):
        raise ScheduleContractError("ordinary/DST target-date cycle counts changed")

    transition_tests: list[dict[str, Any]] = []
    for year in range(2021, 2027):
        transitions = dst_transition_dates(year, policy.timezone_name)
        if len(transitions) != 2:
            raise ScheduleContractError(f"expected two DST transitions in {year}")
        observed_counts = []
        for transition_day in transitions:
            candidates = cycle_candidates_for_target(transition_day, policy.timezone_name)
            count = len(candidates)
            observed_counts.append(count)
            if count not in {15, 17}:
                raise ScheduleContractError(f"DST envelope failed for {transition_day}")
            if count == 15 and any(
                candidate.cycle_init_local.hour == 2
                and candidate.cycle_init_local.date() == transition_day
                for candidate in candidates
            ):
                raise ScheduleContractError("spring-forward schedule constructed local 02:00")
            if count == 17:
                repeated = [
                    candidate for candidate in candidates
                    if candidate.cycle_init_local.date() == transition_day
                    and candidate.cycle_init_local.hour == 1
                ]
                if len(repeated) != 2 or {value.cycle_init_local.fold for value in repeated} != {0, 1}:
                    raise ScheduleContractError("fall-back 01:00 folds were not preserved")
            transition_tests.append(
                {
                    "target_day": transition_day.isoformat(),
                    "cycle_count": count,
                    "in_historical_range": policy.historical_start <= transition_day <= policy.historical_end,
                }
            )
        if sorted(observed_counts) != [15, 17]:
            raise ScheduleContractError(f"DST transition types are incomplete for {year}")

    first_candidates = cycle_candidates_for_target(policy.historical_start, policy.timezone_name)
    if first_candidates[0].cycle_init_local.date() != date(2020, 12, 31):
        raise ScheduleContractError("first target date lost its previous-local-day c23 anchor")

    return {
        "target_date_count": len(observed_dates),
        "total_product_cycle_count": len(rows),
        "per_product_cycle_count": dict(sorted(product_counts.items())),
        "target_date_cycle_classes": {
            "spring_forward_15": day_class_counts[15],
            "ordinary_16": day_class_counts[16],
            "fall_back_17": day_class_counts[17],
        },
        "horizon_class_counts": {
            product: dict(sorted(counts.items())) for product, counts in horizon_counts.items()
        },
        "target_window_capped_cycle_counts": dict(sorted(capped_counts.items())),
        "utc_cycle_keys_unique_per_product": True,
        "all_cycles_begin_at_fh00": True,
        "all_retained_endpoints_at_or_before_window_end": True,
        "first_source_local_date": first_candidates[0].cycle_init_local.date().isoformat(),
        "dst_transition_tests": transition_tests,
    }


def _read_parquet(path: Path) -> Any:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ScheduleContractError(
            "pyarrow is required to read the sealed cycle schedule"
        ) from exc
    return pq.read_table(path)


def seal_cycle_schedule(project_root: Path | str, *, step01_record_sha256: str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    registry = verify_registry_bundle(paths.root)["bundle"]
    policy = load_schedule_policy(paths.root)
    horizon_evidence = validate_horizon_evidence(paths.root, policy)
    rows = build_schedule_rows(policy)
    schedule_evidence = validate_schedule_rows(rows, policy)
    logical_hash = logical_schedule_sha256(rows)
    schema = load_parquet_schema(paths.root, "cycle_schedule_v375.json")
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise ScheduleContractError(
            "pyarrow is required to publish the sealed cycle schedule"
        ) from exc
    table = pa.Table.from_pylist(rows, schema=schema)
    destination = paths.root / SCHEDULE_PARQUET_PATH
    parquet_hash = atomic_write_table(
        table,
        destination,
        schema=schema,
        compression="zstd",
        replace=True,
    )
    observed = _read_parquet(destination)
    if not observed.schema.equals(schema, check_metadata=True):
        raise ScheduleContractError("published cycle-schedule schema changed on round trip")
    observed_rows = observed.to_pylist()
    if logical_schedule_sha256(observed_rows) != logical_hash:
        raise ScheduleContractError("published cycle schedule changed on round trip")
    roundtrip_evidence = validate_schedule_rows(observed_rows, policy)
    if roundtrip_evidence != schedule_evidence:
        raise ScheduleContractError("published cycle-schedule gate evidence changed")

    manifest_body = {
        "schema_version": SCHEDULE_MANIFEST_SCHEMA_VERSION,
        "schedule_id": "KDEN_V375_CYCLE_SCHEDULE_20210101_20260911_V1",
        "target_date_start": policy.historical_start.isoformat(),
        "target_date_end": policy.historical_end.isoformat(),
        "timezone": policy.timezone_name,
        "logical_schedule_sha256": logical_hash,
        "row_count": len(rows),
        "per_product_cycle_count": schedule_evidence["per_product_cycle_count"],
        "parquet": {
            "path": SCHEDULE_PARQUET_PATH,
            "sha256": parquet_hash,
            "size_bytes": destination.stat().st_size,
            "compression": "zstd",
        },
        "schema": {
            "path": "schemas/cycle_schedule_v375.json",
            "sha256": sha256_file(paths.root / "schemas/cycle_schedule_v375.json"),
        },
        "schedule_policy": {
            "path": SCHEDULE_POLICY_PATH,
            "sha256": sha256_file(paths.root / SCHEDULE_POLICY_PATH),
        },
        "horizon_discovery": {
            "path": HORIZON_EVIDENCE_PATH,
            "sha256": sha256_file(paths.root / HORIZON_EVIDENCE_PATH),
            "evidence_id": horizon_evidence["evidence_id"],
        },
        "registry_bundle_sha256": registry["bundle_sha256"],
        "step01_record_sha256": step01_record_sha256,
    }
    manifest = {
        **manifest_body,
        "manifest_sha256": sha256(canonical_json_bytes(manifest_body)).hexdigest(),
    }
    atomic_write_json(paths.root / SCHEDULE_MANIFEST_PATH, manifest)
    return {
        "manifest": manifest,
        "gate_evidence": {
            "schedule": schedule_evidence,
            "horizon_discovery": horizon_evidence,
            "publication": {
                "logical_schedule_sha256": logical_hash,
                "parquet_sha256": parquet_hash,
                "parquet_roundtrip_verified": True,
                "schema_roundtrip_verified": True,
                "compression": "zstd",
            },
        },
    }


def verify_cycle_schedule(project_root: Path | str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    with (paths.root / SCHEDULE_MANIFEST_PATH).open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("schema_version") != SCHEDULE_MANIFEST_SCHEMA_VERSION:
        raise ScheduleContractError("unsupported cycle-schedule manifest schema")
    body = dict(manifest)
    supplied = body.pop("manifest_sha256", None)
    if supplied != sha256(canonical_json_bytes(body)).hexdigest():
        raise ScheduleContractError("cycle-schedule manifest content hash mismatch")
    parquet_path = paths.root / manifest["parquet"]["path"]
    if (
        sha256_file(parquet_path) != manifest["parquet"]["sha256"]
        or parquet_path.stat().st_size != manifest["parquet"]["size_bytes"]
    ):
        raise ScheduleContractError("sealed cycle-schedule Parquet changed")
    policy = load_schedule_policy(paths.root)
    table = _read_parquet(parquet_path)
    schema = load_parquet_schema(paths.root, "cycle_schedule_v375.json")
    if not table.schema.equals(schema, check_metadata=True):
        raise ScheduleContractError("sealed cycle-schedule schema changed")
    rows = table.to_pylist()
    if logical_schedule_sha256(rows) != manifest["logical_schedule_sha256"]:
        raise ScheduleContractError("sealed cycle-schedule logical hash changed")
    gates = validate_schedule_rows(rows, policy)
    return {"manifest": manifest, "gate_evidence": gates}
