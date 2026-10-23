"""Frozen KDEN Tmax audit rules used by the P02 five-day extension."""

from __future__ import annotations

import io
import json
import re
import urllib.parse
import zipfile
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq


RULE_SCHEMA_VERSION = "KDEN_V375_TRUTH_AUDIT_V1"
PRODUCT_ID_PATTERN = re.compile(
    r"\d{12}-[A-Z0-9]{4}-[A-Z0-9]{6}-[A-Z0-9]{3,6}(?:-[A-Z0-9]{3})?"
)


class TruthRuleError(RuntimeError):
    """A source payload or frozen truth-selection rule is invalid."""


def _int_f(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        result = int(value)
        return result if -100 <= result <= 150 else None
    return None


def _event_time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TruthRuleError(f"invalid event timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise TruthRuleError(f"event timestamp lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def _product_id(link: Any) -> str | None:
    if not isinstance(link, str) or not link:
        return None
    parsed = urllib.parse.urlparse(link)
    query = urllib.parse.parse_qs(parsed.query)
    if query.get("pid"):
        candidate = query["pid"][0]
    else:
        candidate = parsed.path.rstrip("/").split("/")[-1]
    return candidate if PRODUCT_ID_PATTERN.fullmatch(candidate) else None


def parse_audit_payload(payload: bytes, target: date) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TruthRuleError(f"{target}: audit response is not valid JSON") from exc
    if not isinstance(document, dict):
        raise TruthRuleError(f"{target}: audit response root is not an object")
    if document.get("station") != "KDEN" or document.get("date") != target.isoformat():
        raise TruthRuleError(f"{target}: audit response identity mismatch")
    if document.get("tzname") != "America/Denver":
        raise TruthRuleError(f"{target}: audit response timezone mismatch")
    high = document.get("high")
    if not isinstance(high, dict) or not isinstance(high.get("events"), list):
        raise TruthRuleError(f"{target}: audit response lacks high.events")
    for ordinal, event in enumerate(high["events"]):
        if not isinstance(event, dict):
            raise TruthRuleError(f"{target}: high.events[{ordinal}] is not an object")
        if event.get("varname") != "high":
            raise TruthRuleError(f"{target}: high.events[{ordinal}] has wrong varname")
        _event_time(event.get("utc_valid"))
    return document


def eligible_events(document: Mapping[str, Any], target: date) -> list[dict[str, Any]]:
    cutoff = datetime.combine(target + timedelta(days=1), wall_time(7), tzinfo=UTC)
    output: list[dict[str, Any]] = []
    for ordinal, event in enumerate(document["high"]["events"]):
        source = str(event.get("source") or "")
        when = _event_time(event.get("utc_valid"))
        value = _int_f(event.get("value"))
        output.append(
            {
                "source": source,
                "value_f": value,
                "event_time_utc": when,
                "product_id": _product_id(event.get("link")),
                "product_url": event.get("link") or None,
                "description": str(event.get("description") or ""),
                "source_ordinal": ordinal,
                "eligible_postcutoff": (
                    source in {"CLI", "CF6"} and when >= cutoff and value is not None
                ),
            }
        )
    output.sort(key=lambda row: (row["event_time_utc"], row["source_ordinal"]))
    return output


def _first_last(
    events: Sequence[Mapping[str, Any]], source: str
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    selected = [
        event
        for event in events
        if event["eligible_postcutoff"] and event["source"] == source
    ]
    return (selected[0], selected[-1]) if selected else (None, None)


def _expected_int(exception: Mapping[str, Any], key: str) -> int | None:
    value = exception.get(key)
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TruthRuleError(f"guarded exception has invalid {key}") from exc


def evaluate_audit_document(
    *,
    target: date,
    document: Mapping[str, Any],
    raw_sha256: str,
    product_ids_available: set[str],
    atomic_value: int | None = None,
    exception: Mapping[str, Any] | None = None,
    sealed: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply the fixed 07Z, CLI/CF6 unanimity, and guarded-exception rules."""

    events = eligible_events(document, target)
    cli_first, cli_last = _first_last(events, "CLI")
    cf6_first, cf6_last = _first_last(events, "CF6")
    cli_values = sorted(
        {
            int(event["value_f"])
            for event in events
            if event["eligible_postcutoff"] and event["source"] == "CLI"
        }
    )
    cf6_values = sorted(
        {
            int(event["value_f"])
            for event in events
            if event["eligible_postcutoff"] and event["source"] == "CF6"
        }
    )
    atomic_value = _int_f(atomic_value)
    flags: list[str] = []
    if len(cli_values) > 1:
        flags.append("cli_chronology_value_conflict")
    if len(cf6_values) > 1:
        flags.append("cf6_chronology_value_conflict")
    if cli_values and cf6_values and set(cli_values) != set(cf6_values):
        flags.append("cli_cf6_value_conflict")
    if not cli_values:
        flags.append("completed_cli_missing")
    if not cf6_values:
        flags.append("postcutoff_cf6_missing")
    missing_products = sorted(
        {
            str(event["product_id"])
            for event in events
            if event["eligible_postcutoff"]
            and event["product_id"]
            and event["product_id"] not in product_ids_available
        }
    )
    if missing_products:
        flags.append("linked_product_absent_from_raw_archive")

    audited: int | None = None
    exception_rule_id: str | None = None
    if sealed:
        status = "sealed_pending_audit"
        reason = "holdout_outcome_access_deferred"
    else:
        unanimous = bool(
            cli_values and cf6_values and len(set(cli_values + cf6_values)) == 1
        )
        if unanimous:
            audited = cli_values[0]
            status = "auto_audited_cli_cf6_unanimous"
            reason = "all_eligible_cli_and_cf6_values_agree"
        elif exception is not None and str(exception.get("approval_status", "")).startswith(
            "approved_"
        ):
            guards = {
                "expected_iem_atomic_raw_f": atomic_value,
                "expected_cli_first_completed_f": (
                    int(cli_first["value_f"]) if cli_first else None
                ),
                "expected_cf6_first_f": int(cf6_first["value_f"]) if cf6_first else None,
            }
            for key, actual in guards.items():
                expected = _expected_int(exception, key)
                if expected != actual:
                    raise TruthRuleError(
                        f"{target}: guarded exception expected {key}={expected}, got {actual}"
                    )
            selected_product = str(exception.get("selected_product_id") or "")
            if selected_product and selected_product not in {
                event["product_id"] for event in events
            }:
                raise TruthRuleError(
                    f"{target}: guarded exception product is absent from chronology"
                )
            audited = _expected_int(exception, "y_audited_f")
            if audited is None:
                raise TruthRuleError(f"{target}: approved exception has no audited value")
            status = str(exception.get("truth_qc_status") or "audited_guarded_exception")
            exception_rule_id = str(exception.get("rule_id") or "") or None
            reason = "guarded_development_exception_applied"
        elif cli_values and cf6_values:
            status = "unresolved_cli_cf6_or_chronology_conflict"
            reason = "eligible_cli_cf6_values_are_not_unanimous"
        elif cli_values:
            status = "unresolved_cli_only"
            reason = "no_independent_cf6_value"
        elif cf6_values:
            status = "unresolved_cf6_only"
            reason = "completed_cli_missing"
        else:
            status = "unresolved_missing"
            reason = "completed_cli_and_cf6_missing"

    row = {
        "schema_version": RULE_SCHEMA_VERSION,
        "target_date": target,
        "station_id": "KDEN",
        "y_audited_f": None if sealed else audited,
        "truth_qc_status": status,
        "truth_selection_reason": reason,
        "exception_rule_id": exception_rule_id,
        "y_cli_first_completed_f": int(cli_first["value_f"]) if cli_first else None,
        "cli_first_completed_time_utc": cli_first["event_time_utc"] if cli_first else None,
        "cli_first_completed_product_id": cli_first["product_id"] if cli_first else None,
        "y_cli_latest_f": int(cli_last["value_f"]) if cli_last else None,
        "cli_latest_time_utc": cli_last["event_time_utc"] if cli_last else None,
        "cli_latest_product_id": cli_last["product_id"] if cli_last else None,
        "y_cf6_first_f": int(cf6_first["value_f"]) if cf6_first else None,
        "cf6_first_time_utc": cf6_first["event_time_utc"] if cf6_first else None,
        "cf6_first_product_id": cf6_first["product_id"] if cf6_first else None,
        "y_cf6_latest_f": int(cf6_last["value_f"]) if cf6_last else None,
        "cf6_latest_time_utc": cf6_last["event_time_utc"] if cf6_last else None,
        "cf6_latest_product_id": cf6_last["product_id"] if cf6_last else None,
        "cli_values_json": json.dumps(cli_values, separators=(",", ":")),
        "cf6_values_json": json.dumps(cf6_values, separators=(",", ":")),
        "cli_product_ids_json": json.dumps(
            [
                event["product_id"]
                for event in events
                if event["eligible_postcutoff"]
                and event["source"] == "CLI"
                and event["product_id"]
            ],
            separators=(",", ":"),
        ),
        "cf6_product_ids_json": json.dumps(
            [
                event["product_id"]
                for event in events
                if event["eligible_postcutoff"]
                and event["source"] == "CF6"
                and event["product_id"]
            ],
            separators=(",", ":"),
        ),
        "eligible_cli_event_count": sum(
            event["eligible_postcutoff"] and event["source"] == "CLI"
            for event in events
        ),
        "eligible_cf6_event_count": sum(
            event["eligible_postcutoff"] and event["source"] == "CF6"
            for event in events
        ),
        "missing_archived_product_ids_json": json.dumps(
            missing_products, separators=(",", ":")
        ),
        "review_flags_json": json.dumps(sorted(flags), separators=(",", ":")),
        "audit_raw_sha256": raw_sha256,
    }
    event_rows = [
        {
            "schema_version": RULE_SCHEMA_VERSION,
            "target_date": target,
            "station_id": "KDEN",
            "source": event["source"],
            "value_f": event["value_f"],
            "event_time_utc": event["event_time_utc"],
            "product_id": event["product_id"],
            "product_url": event["product_url"],
            "description": event["description"],
            "source_ordinal": event["source_ordinal"],
            "eligible_postcutoff": event["eligible_postcutoff"],
            "raw_product_archive_present": (
                event["product_id"] in product_ids_available
                if event["product_id"]
                else None
            ),
            "audit_raw_sha256": raw_sha256,
        }
        for event in events
        if event["source"] in {"CLI", "CF6"}
    ]
    return row, event_rows


def validate_archive_payload(payload: bytes, *, pil: str, year: int) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise TruthRuleError(f"{pil}-{year}: corrupt ZIP member {bad}")
            members = [name for name in archive.namelist() if not name.endswith("/")]
            records: list[dict[str, str]] = []
            for name in members:
                member = Path(name)
                if member.is_absolute() or ".." in member.parts:
                    raise TruthRuleError(f"{pil}-{year}: unsafe ZIP member {name!r}")
                filename_match = re.fullmatch(
                    rf"{re.escape(pil)}_(\d{{12}})(?:_[A-Z0-9]{{3}})?\.txt",
                    member.name,
                )
                text = archive.read(name).decode("utf-8", errors="strict")
                header_match = re.search(
                    r"(?m)^([A-Z0-9]{6}) ([A-Z0-9]{4}) [0-9]{6}"
                    r"(?: ([A-Z0-9]{3}))?\s*$",
                    text,
                )
                pil_match = re.search(rf"(?m)^{re.escape(pil)}\s*$", text)
                if not filename_match or not header_match or not pil_match:
                    raise TruthRuleError(
                        f"{pil}-{year}: cannot identify AFOS product {name!r}"
                    )
                timestamp = filename_match.group(1)
                ttaaii, center, bbb = header_match.groups()
                product_id = f"{timestamp}-{center}-{ttaaii}-{pil}"
                if bbb:
                    product_id += f"-{bbb}"
                if not PRODUCT_ID_PATTERN.fullmatch(product_id):
                    raise TruthRuleError(
                        f"{pil}-{year}: invalid derived product ID {product_id!r}"
                    )
                records.append({"member": name, "product_id": product_id})
    except (zipfile.BadZipFile, UnicodeDecodeError, OSError) as exc:
        raise TruthRuleError(f"{pil}-{year}: invalid AFOS ZIP: {exc}") from exc
    if not records:
        raise TruthRuleError(f"{pil}-{year}: AFOS ZIP has no identifiable products")
    return {
        "schema_version": RULE_SCHEMA_VERSION,
        "pil": pil,
        "year": year,
        "member_count": len(members),
        "product_count": len(records),
        "product_ids": sorted({row["product_id"] for row in records}),
        "members": sorted(records, key=lambda row: (row["product_id"], row["member"])),
    }


def tail_truth_schema() -> pa.Schema:
    timestamp = pa.timestamp("us", tz="UTC")
    return pa.schema(
        [
            ("schema_version", pa.string()),
            ("target_date", pa.date32()),
            ("station_id", pa.string()),
            ("y_audited_f", pa.int16()),
            ("truth_qc_status", pa.string()),
            ("truth_selection_reason", pa.string()),
            ("exception_rule_id", pa.string()),
            ("y_cli_first_completed_f", pa.int16()),
            ("cli_first_completed_time_utc", timestamp),
            ("cli_first_completed_product_id", pa.string()),
            ("y_cli_latest_f", pa.int16()),
            ("cli_latest_time_utc", timestamp),
            ("cli_latest_product_id", pa.string()),
            ("y_cf6_first_f", pa.int16()),
            ("cf6_first_time_utc", timestamp),
            ("cf6_first_product_id", pa.string()),
            ("y_cf6_latest_f", pa.int16()),
            ("cf6_latest_time_utc", timestamp),
            ("cf6_latest_product_id", pa.string()),
            ("cli_values_json", pa.string()),
            ("cf6_values_json", pa.string()),
            ("cli_product_ids_json", pa.string()),
            ("cf6_product_ids_json", pa.string()),
            ("eligible_cli_event_count", pa.int16()),
            ("eligible_cf6_event_count", pa.int16()),
            ("missing_archived_product_ids_json", pa.string()),
            ("review_flags_json", pa.string()),
            ("audit_raw_sha256", pa.string()),
            ("truth_evidence_cutoff_utc", timestamp),
            ("source_followup_window_open_at_freeze", pa.bool_()),
            ("source_retrieved_at_utc", timestamp),
        ]
    )


def tail_event_schema() -> pa.Schema:
    return pa.schema(
        [
            ("schema_version", pa.string()),
            ("target_date", pa.date32()),
            ("station_id", pa.string()),
            ("source", pa.string()),
            ("value_f", pa.int16()),
            ("event_time_utc", pa.timestamp("us", tz="UTC")),
            ("product_id", pa.string()),
            ("product_url", pa.string()),
            ("description", pa.string()),
            ("source_ordinal", pa.int16()),
            ("eligible_postcutoff", pa.bool_()),
            ("raw_product_archive_present", pa.bool_()),
            ("audit_raw_sha256", pa.string()),
        ]
    )


def catalog_schema() -> pa.Schema:
    return pa.schema(
        [
            ("target_date", pa.date32()),
            ("truth_release_id", pa.string()),
            ("truth_group", pa.string()),
            ("truth_evidence_status", pa.string()),
            ("label_available_for_supervised_use", pa.bool_()),
            ("label_available_for_final_scoring", pa.bool_()),
            ("y_audited_f", pa.int16()),
            ("truth_qc_status", pa.string()),
            ("source_artifact_path", pa.string()),
            ("source_artifact_sha256", pa.string()),
            ("truth_evidence_cutoff_utc", pa.timestamp("us", tz="UTC")),
            ("source_followup_window_open_at_freeze", pa.bool_()),
            ("exclusion_reason", pa.string()),
        ]
    )


def parquet_bytes(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> bytes:
    table = pa.Table.from_pylist(list(rows), schema=schema)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        version="2.6",
        write_statistics=True,
    )
    return sink.getvalue().to_pybytes()
