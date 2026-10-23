"""Leakage-safe, on-demand readers and issue-time views for the sealed R14 archive."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo

from .acquisition.records import (
    COMBINED_PASS_PATH,
    COMBINED_PASS_SCHEMA,
    PRODUCT_PASS_PATH,
    PRODUCT_PASS_SCHEMA,
)
from .contracts import ContractError, load_project_paths
from .hashes import canonical_json_bytes, sha256_bytes
from .r14 import (
    R14_DYNAMIC_HOURLY,
    R14_SCOPE_ID,
    R14_STATIC_HOURLY,
    R14_SUBHOURLY,
)
from .r14_schedule import R14_SCHEDULE_PARQUET_PATH
from .time import as_utc


ISSUE_VIEW_CONTRACT_PATH = "config/issue_time_views_r14_v375.json"
ISSUE_VIEW_SCHEMA_PATH = "schemas/issue_time_view_r14_v375.json"
ISSUE_VIEW_CONTRACT_SCHEMA = "KDEN_V375_R14_ISSUE_VIEW_CONTRACT_V1"
ISSUE_VIEW_CONTRACT_ID = "KDEN_V375_R14_ISSUE_VIEWS_V1"
FIELD_STATE_SCHEMA_ID = "KDEN_V375_HRRR_FIELD_STATE_R14_V1"
SCHEDULE_SCHEMA_ID = "KDEN_V375_CYCLE_SCHEDULE_V1"
PRODUCTS = ("wrfsfcf", "wrfsubhf")


class ArchiveReaderError(ContractError):
    """An archive row or issue-time request violates the frozen R14 contract."""


def _arrow() -> tuple[Any, Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - environment contract
        raise ArchiveReaderError("pyarrow is required for R14 archive readers") from exc
    return pa, pc, pq


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ArchiveReaderError(f"JSON contract must contain an object: {path}")
    return value


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ArchiveReaderError(f"reader path leaves project root: {relative}")
    return path


def _normalise_day(value: date | str) -> date:
    result = value if isinstance(value, date) else date.fromisoformat(value)
    return result


def _clock_minutes(value: str) -> int:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ArchiveReaderError(f"invalid local clock value: {value!r}") from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ArchiveReaderError("issue-grid clocks must be minute-resolution local times")
    return parsed.hour * 60 + parsed.minute


def load_issue_view_contract(project_root: Path | str) -> dict[str, Any]:
    """Load and fail-closed validate the R14 reader/view contract."""

    paths = load_project_paths(project_root)
    value = _read_json(paths.root / ISSUE_VIEW_CONTRACT_PATH)
    if (
        value.get("schema_version") != ISSUE_VIEW_CONTRACT_SCHEMA
        or value.get("contract_id") != ISSUE_VIEW_CONTRACT_ID
        or value.get("scope_id") != R14_SCOPE_ID
    ):
        raise ArchiveReaderError("unsupported R14 issue-view contract identity")
    expected_fields = {
        "wrfsfcf": list(R14_DYNAMIC_HOURLY),
        "wrfsubhf": list(R14_SUBHOURLY),
    }
    if value.get("product_fields") != expected_fields:
        raise ArchiveReaderError("issue-view field universe changed")
    if value.get("static_fields") != list(R14_STATIC_HOURLY):
        raise ArchiveReaderError("issue-view static field universe changed")
    availability = value.get("availability", {})
    if (
        availability.get("policy_id") != "KDEN_HIST_COMPLETE_L105_V1"
        or int(availability.get("lag_minutes", -1)) != 105
        or availability.get("actual_first_seen_is_not_reconstructed") is not True
    ):
        raise ArchiveReaderError("historical availability emulator changed")
    issue_grid = value.get("default_issue_grid", {})
    if (
        issue_grid.get("timezone") != "America/Denver"
        or issue_grid.get("start_local") != "02:00"
        or issue_grid.get("end_local") != "16:00"
        or int(issue_grid.get("cadence_minutes", -1)) != 15
        or issue_grid.get("end_inclusive") is not True
    ):
        raise ArchiveReaderError("default issue-time grid changed")
    if set(value.get("cross_product_alignment_contracts", ())) != {
        "separate_experts",
        "same_cycle",
    }:
        raise ArchiveReaderError("cross-product alignment contracts changed")
    publication = value.get("publication_policy", {})
    if not all(
        publication.get(name) is True
        for name in (
            "reader_is_read_only",
            "views_are_built_on_demand",
            "no_cycle_stitching",
            "source_cycle_identities_are_mandatory",
        )
    ):
        raise ArchiveReaderError("issue-view publication policy changed")
    for relative in (
        value["schedule_path"],
        *value["archive_roots"].values(),
        value["static_terrain_path"],
        ISSUE_VIEW_SCHEMA_PATH,
    ):
        if not _inside(paths.root, str(relative)).exists():
            raise ArchiveReaderError(f"required reader artifact is missing: {relative}")
    return value


def read_combined_pass_identity(project_root: Path | str) -> dict[str, Any]:
    """Verify the completed R14 record and product lineage without a deep rescan.

    Step 05's owner validation already performed the expensive artifact-chain
    verification. Reader startup rechecks the immutable JSON identities and
    their cryptographic links; Step 08 owns the final deep archive acceptance.
    """

    root = load_project_paths(project_root).root
    combined = _read_json(root / COMBINED_PASS_PATH)
    if (
        combined.get("schema_version") != COMBINED_PASS_SCHEMA
        or combined.get("record_id") != "R14"
        or combined.get("scope_id") != R14_SCOPE_ID
        or combined.get("status") != "PASS"
    ):
        raise ArchiveReaderError("combined R14 acquisition identity changed")
    body = dict(combined)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise ArchiveReaderError("combined R14 acquisition record hash mismatch")
    expected_ids = {
        "wrfsfcf": "WRFSFCF_R14",
        "wrfsubhf": "WRFSUBHF_Q05_R14",
    }
    predecessors = combined.get("predecessor_hashes", {})
    for product, record_id in expected_ids.items():
        record = _read_json(root / PRODUCT_PASS_PATH[product])
        if (
            record.get("schema_version") != PRODUCT_PASS_SCHEMA
            or record.get("record_id") != record_id
            or record.get("scope_id") != R14_SCOPE_ID
            or record.get("product") != product
            or record.get("status") != "PASS"
            or record.get("run_id") != combined.get("run_id")
        ):
            raise ArchiveReaderError(f"{product} acquisition identity changed")
        product_body = dict(record)
        product_hash = product_body.pop("record_sha256", None)
        if product_hash != sha256_bytes(canonical_json_bytes(product_body)):
            raise ArchiveReaderError(f"{product} acquisition record hash mismatch")
        if predecessors.get(record_id) != product_hash:
            raise ArchiveReaderError(f"combined R14 lineage lost {record_id}")
    return combined


def issue_time_grid(
    target_day: date | str,
    *,
    timezone_name: str = "America/Denver",
    start_local: str = "02:00",
    end_local: str = "16:00",
    cadence_minutes: int = 15,
) -> tuple[datetime, ...]:
    """Enumerate UTC first, then filter local time so DST gaps/folds are real."""

    day = _normalise_day(target_day)
    if cadence_minutes <= 0 or 60 % cadence_minutes:
        raise ArchiveReaderError("issue cadence must be a positive divisor of 60 minutes")
    start_minutes = _clock_minutes(start_local)
    end_minutes = _clock_minutes(end_local)
    if start_minutes > end_minutes:
        raise ArchiveReaderError("issue grid cannot cross local midnight")
    timezone = ZoneInfo(timezone_name)
    local_midnight = datetime.combine(day, time.min, tzinfo=timezone)
    next_midnight = datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone)
    current = local_midnight.astimezone(UTC)
    stop = next_midnight.astimezone(UTC)
    result: list[datetime] = []
    while current < stop:
        local = current.astimezone(timezone)
        local_minutes = local.hour * 60 + local.minute
        if (
            local.date() == day
            and start_minutes <= local_minutes <= end_minutes
            and (local_minutes - start_minutes) % cadence_minutes == 0
        ):
            result.append(current)
        current += timedelta(minutes=cadence_minutes)
    if len(result) != len(set(result)):
        raise ArchiveReaderError("issue grid produced duplicate UTC instants")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class CycleSelection:
    target_day: date
    product: str
    issue_time_utc: datetime
    issue_time_local: datetime
    cycle_init_utc: datetime
    cycle_init_local: datetime
    emulated_complete_time_utc: datetime
    availability_policy_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_day": self.target_day.isoformat(),
            "product": self.product,
            "issue_time_utc": self.issue_time_utc.isoformat().replace("+00:00", "Z"),
            "issue_time_local": self.issue_time_local.isoformat(),
            "cycle_init_utc": self.cycle_init_utc.isoformat().replace("+00:00", "Z"),
            "cycle_init_local": self.cycle_init_local.isoformat(),
            "emulated_complete_time_utc": self.emulated_complete_time_utc.isoformat().replace(
                "+00:00", "Z"
            ),
            "availability_policy_id": self.availability_policy_id,
        }


@dataclass(frozen=True, slots=True)
class ProductIssueView:
    selection: CycleSelection
    previous_selection: CycleSelection | None
    field_state: Any
    temperature_trajectory: Any
    cycle_revisions: Any
    static_terrain: Any | None


@dataclass(frozen=True, slots=True)
class IssueTimeView:
    target_day: date
    issue_time_utc: datetime
    issue_time_local: datetime
    alignment_contract: str
    hourly: ProductIssueView
    q05: ProductIssueView
    cross_product_temperature: Any


def _selection_from_row(
    row: Mapping[str, Any], issue_time_utc: datetime, timezone: ZoneInfo
) -> CycleSelection:
    return CycleSelection(
        target_day=row["target_day"],
        product=str(row["product"]),
        issue_time_utc=issue_time_utc,
        issue_time_local=issue_time_utc.astimezone(timezone),
        cycle_init_utc=as_utc(row["cycle_init_utc"]),
        cycle_init_local=row["cycle_init_local"],
        emulated_complete_time_utc=as_utc(row["emulated_complete_time_utc"]),
        availability_policy_id=str(row["availability_policy_id"]),
    )


def select_newest_legal_cycle(
    schedule_rows: Sequence[Mapping[str, Any]], issue_time: datetime | str
) -> tuple[Mapping[str, Any], Mapping[str, Any] | None]:
    """Pure selector used by the reader and unit tests."""

    issue_utc = as_utc(issue_time)
    legal = sorted(
        (
            row
            for row in schedule_rows
            if as_utc(row["emulated_complete_time_utc"]) <= issue_utc
        ),
        key=lambda row: as_utc(row["cycle_init_utc"]),
    )
    if not legal:
        raise ArchiveReaderError("no scheduled cycle is legal at the requested issue time")
    current = legal[-1]
    previous = legal[-2] if len(legal) > 1 else None
    if as_utc(current["emulated_complete_time_utc"]) > issue_utc:
        raise ArchiveReaderError("cycle selector admitted a future-complete cycle")
    return current, previous


class R14ArchiveReader:
    """Read sealed R14 days and construct legal, on-demand issue-time views."""

    def __init__(self, project_root: Path | str, *, verify_acquisition: bool = True):
        self.paths = load_project_paths(project_root)
        self.root = self.paths.root
        self.contract = load_issue_view_contract(self.root)
        if verify_acquisition:
            self.acquisition_pass = read_combined_pass_identity(self.root)
        else:
            self.acquisition_pass = None
        self.timezone = ZoneInfo(self.contract["default_issue_grid"]["timezone"])
        self._schedule = self._load_schedule_index()

    def _load_schedule_index(self) -> dict[tuple[date, str], tuple[dict[str, Any], ...]]:
        _, _, pq = _arrow()
        path = _inside(self.root, self.contract["schedule_path"])
        parquet = pq.ParquetFile(path)
        metadata = parquet.schema_arrow.metadata or {}
        if metadata.get(b"schema_id", b"").decode() != SCHEDULE_SCHEMA_ID:
            raise ArchiveReaderError("R14 cycle-schedule Parquet schema changed")
        table = parquet.read(
            columns=[
                "target_day",
                "product",
                "cycle_init_utc",
                "cycle_init_local",
                "window_start_utc",
                "window_end_utc",
                "retained_valid_start_utc",
                "retained_valid_end_utc",
                "availability_policy_id",
                "emulated_complete_time_utc",
            ]
        )
        grouped: dict[tuple[date, str], list[dict[str, Any]]] = {}
        for row in table.to_pylist():
            key = (row["target_day"], str(row["product"]))
            grouped.setdefault(key, []).append(row)
        result: dict[tuple[date, str], tuple[dict[str, Any], ...]] = {}
        for key, rows in grouped.items():
            ordered = tuple(sorted(rows, key=lambda row: row["cycle_init_utc"]))
            if len({row["cycle_init_utc"] for row in ordered}) != len(ordered):
                raise ArchiveReaderError(f"duplicate cycle key in R14 schedule: {key}")
            result[key] = ordered
        return result

    def schedule_rows(
        self, target_day: date | str, product: str
    ) -> tuple[dict[str, Any], ...]:
        day = _normalise_day(target_day)
        if product not in PRODUCTS:
            raise ArchiveReaderError(f"unsupported R14 product: {product!r}")
        try:
            return self._schedule[(day, product)]
        except KeyError as exc:
            raise ArchiveReaderError(
                f"target day/product is outside the sealed schedule: {day}/{product}"
            ) from exc

    def _issue_utc(self, target_day: date, issue_time: datetime | str) -> datetime:
        issue_utc = as_utc(issue_time)
        if issue_utc.astimezone(self.timezone).date() != target_day:
            raise ArchiveReaderError("issue time does not belong to the target local day")
        return issue_utc

    def select_cycles(
        self, target_day: date | str, product: str, issue_time: datetime | str
    ) -> tuple[CycleSelection, CycleSelection | None]:
        day = _normalise_day(target_day)
        issue_utc = self._issue_utc(day, issue_time)
        rows = self.schedule_rows(day, product)
        current, previous = select_newest_legal_cycle(rows, issue_utc)
        expected_policy = self.contract["availability"]["policy_id"]
        if any(row["availability_policy_id"] != expected_policy for row in rows):
            raise ArchiveReaderError("schedule availability policy changed")
        return (
            _selection_from_row(current, issue_utc, self.timezone),
            None
            if previous is None
            else _selection_from_row(previous, issue_utc, self.timezone),
        )

    def _day_directory(self, target_day: date, product: str) -> Path:
        base = _inside(self.root, self.contract["archive_roots"][product])
        return base / (
            f"target_year={target_day.year:04d}/target_month={target_day.month:02d}/"
            f"target_day={target_day.isoformat()}"
        )

    @staticmethod
    def _cycle_partition(cycle_init_utc: datetime) -> str:
        return f"cycle={as_utc(cycle_init_utc).strftime('%Y%m%dT%H%M%SZ')}"

    @lru_cache(maxsize=64)
    def _read_cycle_all(
        self, target_day: date, product: str, cycle_init_utc: datetime
    ) -> Any:
        _, _, pq = _arrow()
        scheduled = {
            as_utc(row["cycle_init_utc"])
            for row in self.schedule_rows(target_day, product)
        }
        cycle_utc = as_utc(cycle_init_utc)
        if cycle_utc not in scheduled:
            raise ArchiveReaderError("requested cycle is not scheduled for target day/product")
        path = (
            self._day_directory(target_day, product)
            / self._cycle_partition(cycle_utc)
            / "field_state.parquet"
        )
        if not path.is_file():
            raise ArchiveReaderError(f"canonical cycle partition is missing: {path}")
        parquet = pq.ParquetFile(path)
        metadata = parquet.schema_arrow.metadata or {}
        if metadata.get(b"schema_id", b"").decode() != FIELD_STATE_SCHEMA_ID:
            raise ArchiveReaderError(f"field-state schema changed: {path}")
        table = parquet.read()
        forbidden = set(self.contract["forbidden_columns"])
        if forbidden & set(table.column_names):
            raise ArchiveReaderError("truth or market columns entered the source archive")
        rows = table.to_pylist()
        if not rows:
            raise ArchiveReaderError(f"empty canonical cycle partition: {path}")
        expected_fields = set(self.contract["product_fields"][product])
        observed_fields = {str(row["field_registry_id"]) for row in rows}
        if observed_fields != expected_fields:
            raise ArchiveReaderError(
                f"canonical cycle field universe changed: {target_day}/{product}/{cycle_utc}"
            )
        if any(
            row["target_day"] != target_day
            or str(row["product"]) != product
            or as_utc(row["cycle_init_utc"]) != cycle_utc
            for row in rows
        ):
            raise ArchiveReaderError("canonical cycle partition contains a foreign row")
        keys = [
            (
                row["valid_time_utc"],
                str(row["field_registry_id"]),
                row["interval_start_utc"],
            )
            for row in rows
        ]
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise ArchiveReaderError("canonical cycle rows are unsorted or non-unique")
        if any(str(row["coverage_flag"]) == "QUARANTINED" for row in rows):
            raise ArchiveReaderError("a quarantined row entered a passed R14 archive")
        return table

    def read_cycle(
        self,
        target_day: date | str,
        product: str,
        cycle_init_utc: datetime | str,
        *,
        field_ids: Sequence[str] | None = None,
    ) -> Any:
        pa, pc, _ = _arrow()
        day = _normalise_day(target_day)
        cycle_utc = as_utc(cycle_init_utc)
        table = self._read_cycle_all(day, product, cycle_utc)
        if field_ids is None:
            return table
        requested = tuple(dict.fromkeys(str(value) for value in field_ids))
        allowed = set(self.contract["product_fields"][product])
        if not requested or not set(requested) <= allowed:
            raise ArchiveReaderError("requested fields leave the active R14 product universe")
        mask = pc.is_in(
            pc.cast(table["field_registry_id"], pa.string()),
            value_set=pa.array(requested, type=pa.string()),
        )
        return table.filter(mask)

    @lru_cache(maxsize=1)
    def read_static_terrain(self) -> Any:
        _, _, pq = _arrow()
        path = _inside(self.root, self.contract["static_terrain_path"])
        table = pq.ParquetFile(path).read()
        if table.num_rows != 1 or set(table["field_registry_id"].to_pylist()) != {"H14"}:
            raise ArchiveReaderError("static terrain archive changed")
        row = table.to_pylist()[0]
        if row["coverage_flag"] != "PRESENT" or row["bi_value"] is None:
            raise ArchiveReaderError("static H14 terrain is not present and finite")
        regional_values = [row[f"regional_value_{index:02d}"] for index in range(8)]
        if (
            row["regional_support_count"] != 8
            or row["regional_coverage_mask"] != 255
            or any(value is None for value in regional_values)
        ):
            raise ArchiveReaderError("static H14 terrain lacks its eight regional supports")
        return table

    def read_temporal_coverage(self, target_day: date | str, product: str) -> Any:
        _, _, pq = _arrow()
        day = _normalise_day(target_day)
        path = self._day_directory(day, product) / "_temporal_coverage.parquet"
        if not path.is_file():
            raise ArchiveReaderError(f"temporal coverage is missing: {path}")
        table = pq.ParquetFile(path).read()
        for row in table.to_pylist():
            if row["target_day"] != day or str(row["product"]) != product:
                raise ArchiveReaderError("temporal coverage belongs to another day/product")
            if row["expected_valid_count"] != (
                row["present_valid_count"]
                + row["missing_valid_count"]
                + row["quarantined_valid_count"]
            ):
                raise ArchiveReaderError("temporal coverage counts do not reconcile")
            if row["quarantined_valid_count"]:
                raise ArchiveReaderError("temporal coverage contains quarantined rows")
        return table

    def _trajectory_schema(self) -> Any:
        pa, _, _ = _arrow()
        return pa.schema(
            [
                pa.field("target_day", pa.date32(), nullable=False),
                pa.field("issue_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field(
                    "issue_time_local",
                    pa.timestamp("us", tz="America/Denver"),
                    nullable=False,
                ),
                pa.field("product", pa.string(), nullable=False),
                pa.field("baseline_id", pa.string(), nullable=False),
                pa.field("cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field(
                    "cycle_init_local",
                    pa.timestamp("us", tz="America/Denver"),
                    nullable=False,
                ),
                pa.field(
                    "emulated_complete_time_utc",
                    pa.timestamp("us", tz="UTC"),
                    nullable=False,
                ),
                pa.field("valid_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field(
                    "valid_time_local",
                    pa.timestamp("us", tz="America/Denver"),
                    nullable=False,
                ),
                pa.field("forecast_lead_min", pa.int32(), nullable=False),
                pa.field("bi_value", pa.float64()),
                pa.field("nn_value", pa.float64()),
                pa.field("coverage_flag", pa.string(), nullable=False),
                pa.field("missing_reason", pa.string()),
            ],
            metadata={
                b"schema_version": b"KDEN_V375_ISSUE_TIME_VIEW_SCHEMA_V1",
                b"table_id": b"temperature_trajectory",
            },
        )

    def build_temperature_trajectory(
        self, selection: CycleSelection, field_state: Any | None = None
    ) -> Any:
        pa, _, _ = _arrow()
        baseline = self.contract["temperature_baselines"][selection.product]
        table = (
            field_state
            if field_state is not None
            else self.read_cycle(
                selection.target_day,
                selection.product,
                selection.cycle_init_utc,
                field_ids=(baseline["field_id"],),
            )
        )
        rows = []
        for row in table.to_pylist():
            if str(row["field_registry_id"]) != baseline["field_id"]:
                continue
            rows.append(
                {
                    "target_day": selection.target_day,
                    "issue_time_utc": selection.issue_time_utc,
                    "issue_time_local": selection.issue_time_local,
                    "product": selection.product,
                    "baseline_id": baseline["baseline_id"],
                    "cycle_init_utc": selection.cycle_init_utc,
                    "cycle_init_local": selection.cycle_init_local,
                    "emulated_complete_time_utc": selection.emulated_complete_time_utc,
                    "valid_time_utc": row["valid_time_utc"],
                    "valid_time_local": row["valid_time_local"],
                    "forecast_lead_min": row["forecast_lead_min"],
                    "bi_value": row["bi_value"],
                    "nn_value": row["nn_value"],
                    "coverage_flag": str(row["coverage_flag"]),
                    "missing_reason": row["missing_reason"],
                }
            )
        rows.sort(key=lambda row: row["valid_time_utc"])
        if not rows:
            raise ArchiveReaderError("selected cycle has no temperature trajectory")
        return pa.Table.from_pylist(rows, schema=self._trajectory_schema())

    def _revision_schema(self) -> Any:
        pa, _, _ = _arrow()
        return pa.schema(
            [
                pa.field("target_day", pa.date32(), nullable=False),
                pa.field("issue_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("product", pa.string(), nullable=False),
                pa.field("field_registry_id", pa.string(), nullable=False),
                pa.field("valid_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field(
                    "current_cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False
                ),
                pa.field(
                    "previous_cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False
                ),
                pa.field("value_column", pa.string(), nullable=False),
                pa.field("current_value", pa.float64()),
                pa.field("previous_value", pa.float64()),
                pa.field("revision_value", pa.float64()),
                pa.field("current_coverage_flag", pa.string(), nullable=False),
                pa.field("previous_coverage_flag", pa.string(), nullable=False),
            ],
            metadata={
                b"schema_version": b"KDEN_V375_ISSUE_TIME_VIEW_SCHEMA_V1",
                b"table_id": b"cycle_revision",
            },
        )

    def build_cycle_revisions(
        self,
        selection: CycleSelection,
        previous_selection: CycleSelection | None,
        *,
        field_ids: Sequence[str] | None = None,
    ) -> Any:
        pa, _, _ = _arrow()
        if previous_selection is None:
            return pa.Table.from_pylist([], schema=self._revision_schema())
        if (
            previous_selection.product != selection.product
            or previous_selection.target_day != selection.target_day
            or previous_selection.cycle_init_utc >= selection.cycle_init_utc
        ):
            raise ArchiveReaderError("cycle revision inputs are not ordered same-product states")
        fields = tuple(field_ids or self.contract["product_fields"][selection.product])
        current = self.read_cycle(
            selection.target_day,
            selection.product,
            selection.cycle_init_utc,
            field_ids=fields,
        ).to_pylist()
        previous = self.read_cycle(
            previous_selection.target_day,
            previous_selection.product,
            previous_selection.cycle_init_utc,
            field_ids=fields,
        ).to_pylist()
        key = lambda row: (str(row["field_registry_id"]), row["valid_time_utc"])
        current_by_key = {key(row): row for row in current}
        previous_by_key = {key(row): row for row in previous}
        rows: list[dict[str, Any]] = []
        value_columns = self.contract["local_value_column_by_field"]
        for field_id, valid_time in sorted(set(current_by_key) & set(previous_by_key)):
            current_row = current_by_key[(field_id, valid_time)]
            previous_row = previous_by_key[(field_id, valid_time)]
            value_column = value_columns[field_id]
            current_value = current_row[value_column]
            previous_value = previous_row[value_column]
            current_flag = str(current_row["coverage_flag"])
            previous_flag = str(previous_row["coverage_flag"])
            revision = (
                float(current_value) - float(previous_value)
                if current_flag == previous_flag == "PRESENT"
                and current_value is not None
                and previous_value is not None
                else None
            )
            rows.append(
                {
                    "target_day": selection.target_day,
                    "issue_time_utc": selection.issue_time_utc,
                    "product": selection.product,
                    "field_registry_id": field_id,
                    "valid_time_utc": valid_time,
                    "current_cycle_init_utc": selection.cycle_init_utc,
                    "previous_cycle_init_utc": previous_selection.cycle_init_utc,
                    "value_column": value_column,
                    "current_value": current_value,
                    "previous_value": previous_value,
                    "revision_value": revision,
                    "current_coverage_flag": current_flag,
                    "previous_coverage_flag": previous_flag,
                }
            )
        return pa.Table.from_pylist(rows, schema=self._revision_schema())

    def _selection_for_cycle(
        self,
        target_day: date,
        product: str,
        issue_utc: datetime,
        cycle_utc: datetime,
    ) -> tuple[CycleSelection, CycleSelection | None]:
        legal = [
            row
            for row in self.schedule_rows(target_day, product)
            if as_utc(row["emulated_complete_time_utc"]) <= issue_utc
        ]
        positions = {
            as_utc(row["cycle_init_utc"]): index
            for index, row in enumerate(sorted(legal, key=lambda row: row["cycle_init_utc"]))
        }
        ordered = sorted(legal, key=lambda row: row["cycle_init_utc"])
        if cycle_utc not in positions:
            raise ArchiveReaderError("requested common cycle is not legal for both products")
        index = positions[cycle_utc]
        current = _selection_from_row(ordered[index], issue_utc, self.timezone)
        previous = (
            None
            if index == 0
            else _selection_from_row(ordered[index - 1], issue_utc, self.timezone)
        )
        return current, previous

    def _common_cycle_selections(
        self, target_day: date, issue_utc: datetime
    ) -> tuple[
        tuple[CycleSelection, CycleSelection | None],
        tuple[CycleSelection, CycleSelection | None],
    ]:
        legal_by_product: dict[str, set[datetime]] = {}
        for product in PRODUCTS:
            legal_by_product[product] = {
                as_utc(row["cycle_init_utc"])
                for row in self.schedule_rows(target_day, product)
                if as_utc(row["emulated_complete_time_utc"]) <= issue_utc
            }
        common = sorted(legal_by_product["wrfsfcf"] & legal_by_product["wrfsubhf"])
        if not common:
            raise ArchiveReaderError("no common legal hourly/Q05 cycle exists")
        cycle = common[-1]
        return (
            self._selection_for_cycle(target_day, "wrfsfcf", issue_utc, cycle),
            self._selection_for_cycle(target_day, "wrfsubhf", issue_utc, cycle),
        )

    def build_product_view(
        self,
        selection: CycleSelection,
        previous_selection: CycleSelection | None,
    ) -> ProductIssueView:
        field_state = self.read_cycle(
            selection.target_day, selection.product, selection.cycle_init_utc
        )
        trajectory = self.build_temperature_trajectory(selection, field_state)
        revisions = self.build_cycle_revisions(selection, previous_selection)
        terrain = self.read_static_terrain() if selection.product == "wrfsfcf" else None
        return ProductIssueView(
            selection=selection,
            previous_selection=previous_selection,
            field_state=field_state,
            temperature_trajectory=trajectory,
            cycle_revisions=revisions,
            static_terrain=terrain,
        )

    def _cross_schema(self) -> Any:
        pa, _, _ = _arrow()
        return pa.schema(
            [
                pa.field("target_day", pa.date32(), nullable=False),
                pa.field("issue_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("alignment_contract", pa.string(), nullable=False),
                pa.field("valid_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field(
                    "hourly_cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False
                ),
                pa.field("q05_cycle_init_utc", pa.timestamp("us", tz="UTC"), nullable=False),
                pa.field("h16_bi_value", pa.float64()),
                pa.field("q05_bi_value", pa.float64()),
                pa.field("q05_minus_h16", pa.float64()),
                pa.field("hourly_coverage_flag", pa.string(), nullable=False),
                pa.field("q05_coverage_flag", pa.string(), nullable=False),
            ],
            metadata={
                b"schema_version": b"KDEN_V375_ISSUE_TIME_VIEW_SCHEMA_V1",
                b"table_id": b"cross_product_temperature",
            },
        )

    def build_cross_product_temperature(
        self,
        hourly: ProductIssueView,
        q05: ProductIssueView,
        *,
        alignment_contract: str,
    ) -> Any:
        pa, _, _ = _arrow()
        allowed = set(self.contract["cross_product_alignment_contracts"])
        if alignment_contract not in allowed:
            raise ArchiveReaderError("cross-product alignment contract must be explicit")
        if alignment_contract == "same_cycle" and (
            hourly.selection.cycle_init_utc != q05.selection.cycle_init_utc
        ):
            raise ArchiveReaderError("same_cycle view contains unequal product cycles")
        hourly_rows = {
            row["valid_time_utc"]: row
            for row in hourly.temperature_trajectory.to_pylist()
        }
        q05_rows = {
            row["valid_time_utc"]: row for row in q05.temperature_trajectory.to_pylist()
        }
        rows = []
        for valid_time in sorted(set(hourly_rows) & set(q05_rows)):
            h = hourly_rows[valid_time]
            q = q05_rows[valid_time]
            h_value = h["bi_value"]
            q_value = q["bi_value"]
            delta = (
                float(q_value) - float(h_value)
                if h["coverage_flag"] == q["coverage_flag"] == "PRESENT"
                and h_value is not None
                and q_value is not None
                else None
            )
            rows.append(
                {
                    "target_day": hourly.selection.target_day,
                    "issue_time_utc": hourly.selection.issue_time_utc,
                    "alignment_contract": alignment_contract,
                    "valid_time_utc": valid_time,
                    "hourly_cycle_init_utc": hourly.selection.cycle_init_utc,
                    "q05_cycle_init_utc": q05.selection.cycle_init_utc,
                    "h16_bi_value": h_value,
                    "q05_bi_value": q_value,
                    "q05_minus_h16": delta,
                    "hourly_coverage_flag": h["coverage_flag"],
                    "q05_coverage_flag": q["coverage_flag"],
                }
            )
        return pa.Table.from_pylist(rows, schema=self._cross_schema())

    def build_issue_view(
        self,
        target_day: date | str,
        issue_time: datetime | str,
        *,
        alignment_contract: str | None = None,
    ) -> IssueTimeView:
        day = _normalise_day(target_day)
        issue_utc = self._issue_utc(day, issue_time)
        alignment = alignment_contract or self.contract[
            "default_cross_product_alignment_contract"
        ]
        if alignment == "same_cycle":
            hourly_pair, q05_pair = self._common_cycle_selections(day, issue_utc)
        elif alignment == "separate_experts":
            hourly_pair = self.select_cycles(day, "wrfsfcf", issue_utc)
            q05_pair = self.select_cycles(day, "wrfsubhf", issue_utc)
        else:
            raise ArchiveReaderError("cross-product alignment contract must be explicit")
        hourly = self.build_product_view(*hourly_pair)
        q05 = self.build_product_view(*q05_pair)
        cross = self.build_cross_product_temperature(
            hourly, q05, alignment_contract=alignment
        )
        return IssueTimeView(
            target_day=day,
            issue_time_utc=issue_utc,
            issue_time_local=issue_utc.astimezone(self.timezone),
            alignment_contract=alignment,
            hourly=hourly,
            q05=q05,
            cross_product_temperature=cross,
        )

    def iter_issue_views(
        self,
        target_day: date | str,
        *,
        alignment_contract: str | None = None,
        start_local: str | None = None,
        end_local: str | None = None,
        cadence_minutes: int | None = None,
    ) -> Iterator[IssueTimeView]:
        day = _normalise_day(target_day)
        grid = self.contract["default_issue_grid"]
        for issue_utc in issue_time_grid(
            day,
            timezone_name=grid["timezone"],
            start_local=grid["start_local"] if start_local is None else start_local,
            end_local=grid["end_local"] if end_local is None else end_local,
            cadence_minutes=(
                int(grid["cadence_minutes"])
                if cadence_minutes is None
                else cadence_minutes
            ),
        ):
            yield self.build_issue_view(
                day, issue_utc, alignment_contract=alignment_contract
            )
