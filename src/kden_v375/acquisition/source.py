"""One-source-object R14 range retrieval and scientific extraction.

The Step 04 implementation is immutable pilot evidence.  This module uses the
same sealed selector and extraction helpers, but returns in-memory rows to a
target-day coordinator instead of publishing one tiny Parquet file per source
object.  Only the target-day coordinator owns durable archive publication.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..accounting import AcquisitionAccounting, RequestTerminalResult
from ..contracts import ContractError, utc_now
from ..hashes import canonical_json_bytes, sha256_bytes
from ..io import grib as grib_io
from ..io.atomic import atomic_write_bytes, atomic_write_json
from ..io.cache import SourceGroupCache
from ..io.http_range import (
    AttemptEvidence,
    HttpContractError,
    MessageRange,
    PersistentHttpTransport,
    VerifiedHttpClient,
    coalesce_exact_adjacent_ranges,
    split_coalesced_payload,
)
from ..pilot import (
    PilotContractError,
    _canonical_spatial_values,
    _decoded_identity,
    _field_state_row,
    _field_value_sequence,
    _ledger_row,
    _operators,
    _profiled_decode_and_extract,
    _station_for_valid_time,
    parse_pilot_index,
)


INDEX_CACHE_SCHEMA = "KDEN_V375_R14_ACQUISITION_INDEX_CACHE_V1"
INDEX_MISSING_SCHEMA = "KDEN_V375_R14_ACQUISITION_INDEX_MISSING_V1"
SOURCE_MISSING_SCHEMA = "KDEN_V375_R14_ACQUISITION_SOURCE_MISSING_V1"
GROUP_EVIDENCE_SCHEMA = "KDEN_V375_R14_ACQUISITION_GROUP_EVIDENCE_V1"
PARENT_SIZE_SCHEMA = "KDEN_V375_R14_ACQUISITION_PARENT_SIZE_V1"


class AcquisitionSourceError(ContractError):
    """A source object could not meet its frozen selector/decode contract."""


@dataclass(frozen=True, slots=True)
class SourceTask:
    product: str
    source_object_identity: str
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class SourceResult:
    source_object_identity: str
    field_rows: tuple[Mapping[str, Any], ...]
    ledger_rows: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, Any]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AcquisitionSourceError(f"JSON cache metadata is not an object: {path}")
    return value


def _index_paths(cache_root: Path, index_url: str) -> tuple[Path, Path, Path]:
    key = sha256_bytes(index_url.encode("utf-8"))
    base = cache_root / "indexes"
    return base / f"{key}.idx", base / f"{key}.json", base / f"{key}.missing.json"


def _source_missing_path(cache_root: Path, source_url: str) -> Path:
    key = sha256_bytes(source_url.encode("utf-8"))
    return cache_root / "source_missing" / f"{key}.json"


def _quarantine_cache_pair(
    quarantine_root: Path,
    identity: str,
    paths: Sequence[Path],
    reason: str,
) -> None:
    destination = (
        quarantine_root
        / "index_cache"
        / identity
        / f"{utc_now().replace(':', '').replace('-', '')}_{reason}"
    )
    destination.mkdir(parents=True, exist_ok=False)
    for path in paths:
        if path.exists():
            os.replace(path, destination / path.name)
    atomic_write_json(
        destination / "quarantine_record.json",
        {
            "schema_version": "KDEN_V375_R14_ACQUISITION_CACHE_QUARANTINE_V1",
            "identity": identity,
            "reason": reason,
            "quarantined_at_utc": utc_now(),
        },
        replace=False,
    )


def _load_index_cache(
    cache_root: Path,
    quarantine_root: Path,
    index_url: str,
) -> tuple[bytes, dict[str, Any]] | None:
    payload_path, metadata_path, missing_path = _index_paths(cache_root, index_url)
    identity = sha256_bytes(index_url.encode("utf-8"))
    if missing_path.exists():
        marker = _read_json(missing_path)
        if marker != {
            "schema_version": INDEX_MISSING_SCHEMA,
            "index_url": index_url,
            "http_status": 404,
        }:
            _quarantine_cache_pair(
                quarantine_root, identity, (missing_path,), "invalid_missing_marker"
            )
            return None
        return b"", {**marker, "size_bytes": 0, "retry_count": 0, "cache_status": "VERIFIED_HIT"}
    if not payload_path.exists() and not metadata_path.exists():
        return None
    if not payload_path.is_file() or not metadata_path.is_file():
        _quarantine_cache_pair(
            quarantine_root,
            identity,
            (payload_path, metadata_path),
            "partial_pair",
        )
        return None
    payload = payload_path.read_bytes()
    metadata = _read_json(metadata_path)
    expected = {
        "schema_version": INDEX_CACHE_SCHEMA,
        "index_url": index_url,
        "sha256": sha256_bytes(payload),
        "size_bytes": len(payload),
        "http_status": 200,
        "retry_count": int(metadata.get("retry_count", -1)),
    }
    if metadata != expected or expected["retry_count"] < 0:
        _quarantine_cache_pair(
            quarantine_root,
            identity,
            (payload_path, metadata_path),
            "invalid_pair",
        )
        return None
    return payload, {**metadata, "cache_status": "VERIFIED_HIT"}


def _load_or_fetch_index(
    *,
    cache_root: Path,
    quarantine_root: Path,
    client: VerifiedHttpClient,
    index_url: str,
) -> tuple[bytes, dict[str, Any]]:
    cached = _load_index_cache(cache_root, quarantine_root, index_url)
    if cached is not None:
        return cached
    payload_path, metadata_path, missing_path = _index_paths(cache_root, index_url)
    try:
        evidence = client.fetch_index(index_url)
    except HttpContractError:
        # VerifiedHttpClient records every attempt before raising.  The caller
        # distinguishes a confirmed HTTP 404 from transport or server errors.
        raise
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(payload_path, evidence.body, replace=False)
    metadata = {
        "schema_version": INDEX_CACHE_SCHEMA,
        "index_url": index_url,
        "sha256": evidence.sha256,
        "size_bytes": evidence.size_bytes,
        "http_status": evidence.status,
        "retry_count": evidence.retry_count,
    }
    try:
        atomic_write_json(metadata_path, metadata, replace=False)
    except Exception:
        _quarantine_cache_pair(
            quarantine_root,
            sha256_bytes(index_url.encode("utf-8")),
            (payload_path, metadata_path),
            "publication_interrupted",
        )
        raise
    missing_path.unlink(missing_ok=True)
    return evidence.body, {**metadata, "cache_status": "DOWNLOADED"}


def _publish_missing_index_marker(cache_root: Path, index_url: str) -> None:
    _, _, path = _index_paths(cache_root, index_url)
    marker = {
        "schema_version": INDEX_MISSING_SCHEMA,
        "index_url": index_url,
        "http_status": 404,
    }
    if path.exists():
        if _read_json(path) != marker:
            raise AcquisitionSourceError("confirmed-404 cache marker changed")
        return
    atomic_write_json(path, marker, replace=False)


def _load_source_missing_marker(
    cache_root: Path,
    quarantine_root: Path,
    source_url: str,
) -> bool:
    path = _source_missing_path(cache_root, source_url)
    if not path.exists():
        return False
    marker = _read_json(path)
    expected = {
        "schema_version": SOURCE_MISSING_SCHEMA,
        "source_url": source_url,
        "http_status": 404,
        "missing_reason": "SOURCE_OBJECT_HTTP_404",
    }
    if marker != expected:
        _quarantine_cache_pair(
            quarantine_root,
            sha256_bytes(source_url.encode("utf-8")),
            (path,),
            "invalid_source_missing_marker",
        )
        return False
    return True


def _publish_source_missing_marker(cache_root: Path, source_url: str) -> None:
    path = _source_missing_path(cache_root, source_url)
    marker = {
        "schema_version": SOURCE_MISSING_SCHEMA,
        "source_url": source_url,
        "http_status": 404,
        "missing_reason": "SOURCE_OBJECT_HTTP_404",
    }
    if path.exists():
        if _read_json(path) != marker:
            raise AcquisitionSourceError("confirmed source-object 404 marker changed")
        return
    atomic_write_json(path, marker, replace=False)


def _last_http_status(
    attempts: Sequence[Mapping[str, Any]],
    url: str,
) -> int | None:
    return next(
        (
            int(row["status"])
            for row in reversed(attempts)
            if row.get("url") == url and row.get("status") is not None
        ),
        None,
    )


def _client(
    *,
    transport: PersistentHttpTransport,
    profile: Mapping[str, Any],
    attempts: list[dict[str, Any]],
) -> VerifiedHttpClient:
    def record(url: str, evidence: AttemptEvidence) -> None:
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

    return VerifiedHttpClient(
        transport=transport,
        max_attempts=int(profile["max_attempts"]),
        timeout_seconds=float(profile["timeout_seconds"]),
        initial_backoff_seconds=float(profile["initial_backoff_seconds"]),
        attempt_callback=record,
    )


def _load_or_fetch_parent_size(
    *,
    cache_root: Path,
    client: VerifiedHttpClient,
    source_url: str,
) -> tuple[int, dict[str, Any]]:
    key = sha256_bytes(source_url.encode("utf-8"))
    path = cache_root / "parent_sizes" / f"{key}.json"
    if path.is_file():
        value = _read_json(path)
        expected = {
            "schema_version": PARENT_SIZE_SCHEMA,
            "source_url": source_url,
            "parent_size_bytes": int(value.get("parent_size_bytes", -1)),
            "accepted_bytes": int(value.get("accepted_bytes", -1)),
            "retry_count": int(value.get("retry_count", -1)),
        }
        if (
            value != expected
            or expected["parent_size_bytes"] <= 0
            or expected["accepted_bytes"] < 0
            or expected["retry_count"] < 0
        ):
            raise AcquisitionSourceError(f"parent-size cache changed: {source_url}")
        return expected["parent_size_bytes"], expected
    size, evidence = client.fetch_parent_size(source_url)
    value = {
        "schema_version": PARENT_SIZE_SCHEMA,
        "source_url": source_url,
        "parent_size_bytes": size,
        "accepted_bytes": evidence.size_bytes,
        "retry_count": evidence.retry_count,
    }
    atomic_write_json(path, value, replace=False)
    return size, value


def process_source_object(
    *,
    root: Path,
    run_id: str,
    task: SourceTask,
    field_registry: Mapping[str, Mapping[str, str]],
    coordinate_rows: Sequence[Mapping[str, Any]],
    regional_geometry: Mapping[str, Sequence[Mapping[str, Any]]],
    profile: Mapping[str, Any],
    physical_ranges: Mapping[str, Sequence[float]],
    required_regional_mask: int,
    transport: PersistentHttpTransport,
) -> SourceResult:
    """Retrieve and extract exactly the planned messages in one source object."""

    started = time.monotonic()
    run_dir = root / "runs" / run_id
    cache_root = run_dir / "acquisition/cache"
    quarantine_root = run_dir / "quarantine/acquisition"
    attempts: list[dict[str, Any]] = []
    client = _client(transport=transport, profile=profile, attempts=attempts)
    index_urls = {str(row["index_object_identity"]) for row in task.rows}
    if len(index_urls) != 1:
        raise AcquisitionSourceError(
            f"source object has multiple index identities: {task.source_object_identity}"
        )
    index_url = next(iter(index_urls))
    index_started = time.monotonic()
    source_missing = _load_source_missing_marker(
        cache_root,
        quarantine_root,
        task.source_object_identity,
    )
    missing_reason = "SOURCE_OBJECT_HTTP_404" if source_missing else None
    try:
        index_payload, index_meta = _load_or_fetch_index(
            cache_root=cache_root,
            quarantine_root=quarantine_root,
            client=client,
            index_url=index_url,
        )
    except HttpContractError as exc:
        last_status = _last_http_status(attempts, index_url)
        if last_status != 404:
            raise AcquisitionSourceError(
                f"index unavailable for {task.source_object_identity}; "
                f"last_status={last_status}: {exc}"
            ) from exc
        source_missing = True
        missing_reason = "SOURCE_INDEX_HTTP_404"
        _publish_missing_index_marker(cache_root, index_url)
        index_payload = b""
        index_meta = {
            "http_status": 404,
            "size_bytes": 0,
            "retry_count": 0,
            "cache_status": "CONFIRMED_HTTP_404",
        }
    else:
        if int(index_meta["http_status"]) == 404:
            source_missing = True
            missing_reason = "SOURCE_INDEX_HTTP_404"
    index_seconds = time.monotonic() - index_started
    index_hash = bytes.fromhex(sha256_bytes(index_payload))
    records = () if source_missing else parse_pilot_index(index_payload.decode("utf-8"))

    entries: list[dict[str, Any]] = []
    needs_parent_size = False
    for plan in task.rows:
        field_id = str(plan["field_registry_id"])
        try:
            field = field_registry[field_id]
        except KeyError as exc:
            raise AcquisitionSourceError(f"unregistered R14 field in plan: {field_id}") from exc
        interval_minutes = int(
            (plan["interval_end_utc"] - plan["interval_start_utc"]).total_seconds()
            // 60
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
            if source_missing
            else [
                (position, record)
                for position, record in enumerate(records)
                if grib_io.record_matches_request(record, request)
            ]
        )
        if len(matches) > 1:
            raise AcquisitionSourceError(
                f"selector ambiguity for {plan['request_id']} in {task.source_object_identity}"
            )
        if not source_missing and len(matches) == 0:
            raise AcquisitionSourceError(
                f"selector not found for {plan['request_id']} in {task.source_object_identity}"
            )
        if len(matches) == 1 and matches[0][0] == len(records) - 1:
            needs_parent_size = True
        entries.append(
            {"plan": dict(plan), "field": field, "request": request, "matches": matches}
        )

    parent_size: int | None = None
    parent_probe_bytes = 0
    parent_probe_retry_count = 0
    if needs_parent_size:
        try:
            parent_size, parent_evidence = _load_or_fetch_parent_size(
                cache_root=cache_root,
                client=client,
                source_url=task.source_object_identity,
            )
        except HttpContractError as exc:
            last_status = _last_http_status(attempts, task.source_object_identity)
            if last_status != 404:
                raise AcquisitionSourceError(
                    f"parent-size probe failed for {task.source_object_identity}; "
                    f"last_status={last_status}: {exc}"
                ) from exc
            source_missing = True
            missing_reason = "SOURCE_OBJECT_HTTP_404"
            _publish_source_missing_marker(cache_root, task.source_object_identity)
        else:
            parent_probe_bytes = int(parent_evidence["accepted_bytes"])
            parent_probe_retry_count = int(parent_evidence["retry_count"])

    resolved_by_request: dict[str, dict[str, Any]] = {}
    message_requests: dict[tuple[int, int], list[str]] = {}
    for entry in entries:
        request_id = str(entry["plan"]["request_id"])
        if source_missing:
            resolved_by_request[request_id] = {**entry, "missing": True}
            continue
        resolved = grib_io.resolve_index_range(
            records, entry["request"], parent_size_bytes=parent_size
        )
        key = (resolved.record.start_byte, resolved.end_byte)
        message_requests.setdefault(key, []).append(request_id)
        resolved_by_request[request_id] = {
            **entry,
            "missing": False,
            "resolved": resolved,
            "range_key": key,
        }

    message_id_by_range = {
        key: "MSG_"
        + sha256_bytes(
            canonical_json_bytes(
                {
                    "source_object_identity": task.source_object_identity,
                    "byte_start": key[0],
                    "byte_end": key[1],
                }
            )
        )
        for key in message_requests
    }
    key_by_message_id = {value: key for key, value in message_id_by_range.items()}
    groups = coalesce_exact_adjacent_ranges(
        task.source_object_identity,
        tuple(
            MessageRange(message_id_by_range[key], key[0], key[1])
            for key in sorted(message_requests)
        ),
    )
    payload_by_message: dict[str, bytes] = {}
    transport_by_request: dict[str, dict[str, Any]] = {}
    cache = SourceGroupCache(
        cache_root / "source_groups",
        quarantine_root / "source_groups",
    )
    range_bytes = 0
    range_retry_count = 0
    cache_hit_count = 0
    for group in groups:
        cached = cache.load(group)
        evidence_path = cache_root / "source_group_evidence" / f"{group.group_id}.json"
        if cached is None:
            try:
                evidence = client.fetch_range_span(group.source_uri, group.start, group.end)
            except HttpContractError as exc:
                last_status = _last_http_status(attempts, group.source_uri)
                if last_status != 404:
                    raise AcquisitionSourceError(
                        f"range retrieval failed for {group.source_uri}; "
                        f"last_status={last_status}: {exc}"
                    ) from exc
                if range_bytes or cache_hit_count or payload_by_message:
                    raise AcquisitionSourceError(
                        "source object returned 404 after verified ranges had already "
                        f"been accepted: {group.source_uri}"
                    ) from exc
                source_missing = True
                missing_reason = "SOURCE_OBJECT_HTTP_404"
                _publish_source_missing_marker(cache_root, group.source_uri)
                for entry in resolved_by_request.values():
                    entry["missing"] = True
                transport_by_request.clear()
                payload_by_message.clear()
                break
            atomic_write_json(
                evidence_path,
                {
                    "schema_version": GROUP_EVIDENCE_SCHEMA,
                    "group_id": group.group_id,
                    "source_uri": group.source_uri,
                    "range_start": group.start,
                    "range_end": group.end,
                    "accepted_bytes": evidence.size_bytes,
                    "retry_count": evidence.retry_count,
                },
            )
            cache.publish(group, evidence.body)
            payload = evidence.body
            retry_count = evidence.retry_count
            cache_status = "DOWNLOADED"
        else:
            payload = cached
            if not evidence_path.is_file():
                raise AcquisitionSourceError(
                    f"verified payload lacks transport evidence: {group.group_id}"
                )
            group_evidence = _read_json(evidence_path)
            expected_evidence = {
                "schema_version": GROUP_EVIDENCE_SCHEMA,
                "group_id": group.group_id,
                "source_uri": group.source_uri,
                "range_start": group.start,
                "range_end": group.end,
                "accepted_bytes": len(payload),
                "retry_count": int(group_evidence.get("retry_count", -1)),
            }
            if group_evidence != expected_evidence or expected_evidence["retry_count"] < 0:
                raise AcquisitionSourceError(
                    f"range transport evidence changed: {group.group_id}"
                )
            retry_count = expected_evidence["retry_count"]
            cache_status = "VERIFIED_HIT"
            cache_hit_count += 1
        # Cache hits represent bytes accepted in an interrupted earlier attempt
        # at this still-uncommitted target-day unit. Count them exactly once in
        # the eventual durable ledger.
        accepted = len(payload)
        range_bytes += accepted
        range_retry_count += retry_count
        payload_by_message.update(split_coalesced_payload(group, payload))
        leader_message = group.members[0].request_id
        leader_request = sorted(message_requests[key_by_message_id[leader_message]])[0]
        for member in group.members:
            key = key_by_message_id[member.request_id]
            for request_id in message_requests[key]:
                transport_by_request[request_id] = {
                    "group": group,
                    "message_id": member.request_id,
                    "http_status": 206,
                    "retry_count": retry_count if request_id == leader_request else 0,
                    "requested_bytes": key[1] - key[0] + 1,
                    "accepted_bytes": accepted if request_id == leader_request else 0,
                    "cache_status": cache_status,
                }

    accounting = AcquisitionAccounting({str(row["request_id"]) for row in task.rows})
    field_rows: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    terrain_evidence: list[dict[str, Any]] = []
    extracted_values = 0
    for plan in task.rows:
        request_id = str(plan["request_id"])
        entry = resolved_by_request[request_id]
        field = entry["field"]
        station = _station_for_valid_time(coordinate_rows, plan["valid_time_utc"])
        if entry["missing"]:
            if missing_reason is None:
                raise AcquisitionSourceError(
                    f"missing source lacks a reason: {task.source_object_identity}"
                )
            field_rows.append(
                _field_state_row(
                    plan=plan,
                    field=field,
                    run_id=run_id,
                    station=station,
                    source_idx_hash=index_hash,
                    payload_hash=None,
                    byte_start=None,
                    byte_end=None,
                    coverage_flag="MISSING",
                    missing_reason=missing_reason,
                    decoded_identity=None,
                    values=(None, None, None, None, (None,) * 8, 0),
                )
            )
            ledger_rows.append(
                _ledger_row(
                    plan=plan,
                    run_id=run_id,
                    field=field,
                    disposition="CONFIRMED_REMOTE_MISSING",
                    publication_status="MISSING_ROW_PUBLISHED",
                    source_idx_hash=index_hash,
                    payload_hash=None,
                    decoded_identity=None,
                    byte_start=None,
                    byte_end=None,
                    group_id=None,
                    http_status=404,
                    retry_count=0,
                    requested_bytes=0,
                    accepted_bytes=0,
                )
            )
            accounting.record(
                RequestTerminalResult(
                    request_id,
                    "CONFIRMED_REMOTE_MISSING",
                    task.source_object_identity,
                )
            )
            continue

        resolved = entry["resolved"]
        transport_meta = transport_by_request[request_id]
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
                    f"regional mask {values[5]} disagrees with {expected_mask}"
                )
            if field["field_id"] == "H14":
                converted = {
                    era: [
                        None
                        if value is None
                        else grib_io.convert_native_to_canonical(
                            float(value), field["native_unit"], field["canonical_unit"]
                        )
                        for value in era_values
                    ]
                    for era, era_values in profiled.terrain_values_by_coordinate_era.items()
                }
                masks = dict(profiled.terrain_masks_by_coordinate_era)
                if (
                    len(converted) != 2
                    or any(len(row) != 8 for row in converted.values())
                    or any(mask != required_regional_mask for mask in masks.values())
                    or any(
                        value is None or not math.isfinite(float(value))
                        for row in converted.values()
                        for value in row
                    )
                ):
                    raise PilotContractError("H14 terrain support is incomplete")
                terrain_evidence.append(
                    {
                        "request_id": request_id,
                        "values_by_coordinate_era": converted,
                        "coverage_masks_by_coordinate_era": masks,
                    }
                )
            finite = _field_value_sequence(values)
            lower, upper = map(float, physical_ranges[field["field_id"]])
            if any(value < lower or value > upper for value in finite):
                raise PilotContractError(
                    f"physical range failure for {field['field_id']}"
                )
            if field["field_id"] != "H14" and not finite:
                raise PilotContractError("required extraction has no finite values")
        except (grib_io.GribContractError, PilotContractError) as exc:
            raise AcquisitionSourceError(
                f"decode/extraction failure for {request_id} in "
                f"{task.source_object_identity}: {exc}"
            ) from exc
        extracted_values += len(finite)
        decoded_identity = _decoded_identity(profiled.decoded)
        field_rows.append(
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
        ledger_rows.append(
            _ledger_row(
                plan=plan,
                run_id=run_id,
                field=field,
                disposition="SUCCESS",
                publication_status="CANONICAL_ROW_PUBLISHED",
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
                disposition="SUCCESS",
                source_object_identity=task.source_object_identity,
                transport_group_id=transport_meta["group"].group_id,
                retry_count=int(transport_meta["retry_count"]),
                accepted_bytes=int(transport_meta["accepted_bytes"]),
                extracted_value_count=len(finite),
            )
        )

    reconciliation = accounting.assert_reconciled()
    return SourceResult(
        source_object_identity=task.source_object_identity,
        field_rows=tuple(field_rows),
        ledger_rows=tuple(ledger_rows),
        metrics={
            "request_count": len(task.rows),
            "source_object_count": 1,
            "success_count": reconciliation["success_count"],
            "confirmed_remote_missing_count": reconciliation[
                "confirmed_remote_missing_count"
            ],
            "quarantined_count": 0,
            "unique_message_count": len(message_requests),
            "coalesced_range_count": len(groups),
            "source_range_accepted_bytes": range_bytes,
            "index_accepted_bytes": int(index_meta.get("size_bytes", 0)),
            "parent_probe_accepted_bytes": parent_probe_bytes,
            "range_retry_count": range_retry_count,
            "index_retry_count": int(index_meta.get("retry_count", 0)),
            "parent_probe_retry_count": parent_probe_retry_count,
            "source_group_cache_hit_count": cache_hit_count,
            "index_cache_hit": index_meta.get("cache_status") == "VERIFIED_HIT",
            "index_seconds": index_seconds,
            "extracted_value_count": extracted_values,
            "terrain_evidence": terrain_evidence,
            "http_attempts": attempts,
            "wall_seconds": time.monotonic() - started,
            "full_grid_cells_persisted": 0,
        },
    )
