"""Target dates, DST-safe issue opportunities and deterministic update blocks."""
from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .common import ContractError

START = date(2021, 1, 1)
END = date(2026, 9, 11)
DEV_END = date(2025, 9, 6)
HOLDOUT_START = date(2025, 9, 7)
HOLDOUT_END = date(2026, 9, 6)
DENVER = ZoneInfo("America/Denver")


def parse_date(value):
    if isinstance(value, datetime):
        raise ContractError("target date must not be a timestamp")
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid ISO target date") from exc
    if not START <= parsed <= END:
        raise ContractError("target date lies outside the R14 study")
    return parsed


def inclusive(start, end):
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def role(day):
    day = parse_date(day)
    if day.year == 2021:
        return "INITIAL_CONTEXT"
    if day <= DEV_END:
        return "DEVELOPMENT"
    if day <= HOLDOUT_END:
        return "ROLLING_HOLDOUT"
    return "ADDITIONAL_TRUSTED"


def label_cutoff(update_date):
    return parse_date(update_date) - timedelta(days=7)


def label_eligible(target, update_date):
    return parse_date(target) < label_cutoff(update_date)


def issue_times(day):
    """Roundtrip each local quarter hour; omit nonexistent spring-forward times."""
    result = []
    for minute in range(120, 961, 15):
        local = datetime.combine(day, time(minute // 60, minute % 60), DENVER)
        utc = local.astimezone(UTC)
        if utc.astimezone(DENVER) == local:
            result.append(utc)
    return result


def native_blocks():
    blocks = []
    for phase, start, end in [("DEVELOPMENT", date(2022, 1, 1), DEV_END),
                              ("ROLLING_HOLDOUT", HOLDOUT_START, HOLDOUT_END)]:
        while start <= end:
            last = min(date(start.year, start.month, calendar.monthrange(start.year, start.month)[1]), end)
            blocks.append({"block_id": f"{phase}_{start.isoformat()}", "role": phase,
                           "start_date": str(start), "end_date": str(last),
                           "label_cutoff_exclusive": str(label_cutoff(start))})
            start = last + timedelta(days=1)
    return blocks


def date_overlay():
    blocks = native_blocks()
    block_map = {d: b for b in blocks for d in inclusive(date.fromisoformat(b["start_date"]),
                                                       date.fromisoformat(b["end_date"]))}
    rows = []
    for d in inclusive(START, END):
        block = block_map.get(d)
        if role(d) == "ADDITIONAL_TRUSTED":
            block = blocks[-1]
        rows.append({"target_date": str(d), "date_role": role(d),
                     "expected_issue_count": len(issue_times(d)),
                     "native_block_id": block["block_id"] if block else None,
                     "included_in_primary_holdout_score": role(d) == "ROLLING_HOLDOUT"})
    return {"schema_version": "R14_TABULAR_DATE_ROLES_V1", "rows": rows,
            "native_blocks": blocks,
            "weekly_update_dates": [str(d) for d in inclusive(date(2022, 1, 1), END)
                                    if d.weekday() == 0 or any(b["start_date"] == str(d) for b in blocks)]}
