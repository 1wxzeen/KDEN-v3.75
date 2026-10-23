"""Durable append-only JSON event logging under the frozen v3.75 schema."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .contracts import utc_now, validate_run_id
from .hashes import canonical_json_bytes


LOG_SCHEMA_VERSION = "KDEN_V375_LOG_EVENT_V1"
SEVERITIES = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
EVENT_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def append_event(
    path: Path | str,
    *,
    run_id: str,
    step_id: str,
    severity: str,
    event_code: str,
    target_day: str | None = None,
    product: str | None = None,
    source_object_identity: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_run_id(run_id)
    if not re.fullmatch(r"STEP_0[0-8]", step_id):
        raise ValueError(f"invalid step_id: {step_id!r}")
    if severity not in SEVERITIES:
        raise ValueError(f"invalid severity: {severity!r}")
    if EVENT_CODE_RE.fullmatch(event_code) is None:
        raise ValueError(f"invalid event_code: {event_code!r}")
    if product not in {None, "wrfsfcf", "wrfsubhf"}:
        raise ValueError(f"invalid product: {product!r}")
    record = {
        "schema_version": LOG_SCHEMA_VERSION,
        "timestamp_utc": utc_now(),
        "run_id": run_id,
        "step_id": step_id,
        "severity": severity,
        "event_code": event_code,
        "target_day": target_day,
        "product": product,
        "source_object_identity": source_object_identity,
        "details": details or {},
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = not destination.exists()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        view = memoryview(canonical_json_bytes(record))
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("event log append made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if created:
        from .io.atomic import fsync_directory

        fsync_directory(destination.parent)
    return record

