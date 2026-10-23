"""Shared UTC normalization helpers; Step 02 owns schedule construction."""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def utc_text(value: datetime | str) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")

