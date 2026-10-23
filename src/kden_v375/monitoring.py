"""Read-only live progress and recent-performance ETA reporting.

The monitoring surface deliberately owns no acquisition state.  It reads the
atomic run/progress snapshots and append-only completion journals written by a
step, so observing a run cannot affect pause/resume or publication.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .contracts import ContractError, RunStateStore, load_project_paths, utc_now, validate_run_id


MONITOR_SCHEMA_VERSION = "KDEN_V375_MONITOR_SNAPSHOT_V1"
TERMINAL_RUN_STATUSES = frozenset({"PASS", "FAILED", "PAUSED"})
STALE_ACTIVE_COMMIT_SECONDS = 300.0


class MonitoringError(ContractError):
    """A run's observational progress data cannot be interpreted safely."""


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise MonitoringError(f"invalid UTC timestamp in monitoring data: {value!r}") from exc
    if parsed.tzinfo is None:
        raise MonitoringError(f"monitoring timestamp has no UTC offset: {value!r}")
    return parsed.astimezone(UTC)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except json.JSONDecodeError as exc:
        raise MonitoringError(f"invalid monitoring JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MonitoringError(f"monitoring document is not an object: {path}")
    return value


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _first_int(value: Mapping[str, Any], names: Iterable[str]) -> int | None:
    for name in names:
        candidate = value.get(name)
        if candidate is not None and not isinstance(candidate, bool):
            try:
                result = int(candidate)
            except (TypeError, ValueError):
                continue
            if result >= 0:
                return result
    return None


def _progress_candidates(run_dir: Path) -> tuple[Path, ...]:
    """Return new-contract locations first, followed by historical locations."""

    return (
        run_dir / "monitoring/live_status.json",
        run_dir / "live_status.json",
        run_dir / "acquisition/live_status.json",
        run_dir / "pilot/live_status.json",
        run_dir / "step03_r14_progress.json",
    )


def _load_progress(root: Path, run_dir: Path) -> tuple[dict[str, Any], str | None]:
    for path in _progress_candidates(run_dir):
        if path.is_file():
            return _read_json(path), _relative(root, path)
    return {}, None


def _load_journal_records(root: Path, run_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    paths: list[str] = []
    for path in sorted(run_dir.rglob("completions.jsonl")):
        paths.append(_relative(root, path))
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MonitoringError(f"cannot read completion journal: {path}") from exc
        # A writer may be between bytes while the read-only monitor samples it.
        # Only a final non-newline-terminated fragment may be ignored.
        lines = raw.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if not line.endswith(b"\n"):
                if index == len(lines) - 1:
                    continue
                raise MonitoringError(f"torn non-final journal record: {path}")
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MonitoringError(f"invalid completion journal record: {path}") from exc
            if not isinstance(record, dict) or "completed_at_utc" not in record:
                raise MonitoringError(f"completion journal record lacks identity: {path}")
            if record.get("run_id") not in {None, run_dir.name}:
                raise MonitoringError(f"completion journal belongs to another run: {path}")
            records.append(record)
    records.sort(key=lambda row: _parse_utc(str(row["completed_at_utc"])))
    return records, paths


def _active_segment_start(run_dir: Path) -> datetime | None:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return None
    latest: datetime | None = None
    raw = path.read_bytes()
    for line in raw.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            continue
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if record.get("event_code") in {"RUN_STARTED", "RUN_RESUMED"}:
            latest = _parse_utc(str(record["timestamp_utc"]))
    return latest


def _normalise_progress(
    progress: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    completed_units = _first_int(
        progress, ("completed_work_units", "completed_units", "completed_count")
    )
    expected_units = _first_int(
        progress, ("expected_work_units", "expected_units", "expected_count")
    )
    remaining_units = _first_int(
        progress, ("remaining_work_units", "remaining_units", "remaining_count")
    )
    if completed_units is None and records:
        completed_units = len(records)
    if expected_units is None and completed_units is not None and remaining_units is not None:
        expected_units = completed_units + remaining_units
    if remaining_units is None and completed_units is not None and expected_units is not None:
        remaining_units = max(0, expected_units - completed_units)

    completed_requests = _first_int(
        progress,
        (
            "completed_logical_requests",
            "logical_requests_completed",
            "completed_request_count",
            "request_rows_completed",
        ),
    )
    expected_requests = _first_int(
        progress,
        (
            "expected_logical_requests",
            "logical_requests_expected",
            "expected_request_count",
            "request_rows_expected",
        ),
    )
    remaining_requests = _first_int(
        progress,
        (
            "remaining_logical_requests",
            "logical_requests_remaining",
            "remaining_request_count",
            "request_rows_remaining",
        ),
    )
    if completed_requests is None and records:
        completed_requests = sum(int(row.get("request_count", 0)) for row in records)
    if expected_requests is None and completed_requests is not None and remaining_requests is not None:
        expected_requests = completed_requests + remaining_requests
    if remaining_requests is None and completed_requests is not None and expected_requests is not None:
        remaining_requests = max(0, expected_requests - completed_requests)

    return {
        "phase": progress.get("phase"),
        "product": progress.get("product") or progress.get("current_product"),
        "current_work_unit": progress.get("current_work_unit"),
        "current_target_day": progress.get("current_target_day"),
        "inflight_source_objects_completed": _first_int(
            progress, ("inflight_source_objects_completed",)
        ),
        "inflight_source_objects_expected": _first_int(
            progress, ("inflight_source_objects_expected",)
        ),
        "inflight_logical_requests": _first_int(
            progress, ("inflight_logical_requests",)
        ),
        "updated_at_utc": progress.get("updated_at_utc"),
        "completed_work_units": completed_units,
        "expected_work_units": expected_units,
        "remaining_work_units": remaining_units,
        "completed_logical_requests": completed_requests,
        "expected_logical_requests": expected_requests,
        "remaining_logical_requests": remaining_requests,
        "accepted_bytes": _first_int(
            progress, ("accepted_bytes", "network_accepted_bytes", "completed_bytes")
        ),
        "disk_bytes": _first_int(
            progress, ("disk_bytes", "pilot_disk_bytes", "archive_disk_bytes")
        ),
    }


def _recent_performance(
    *,
    records: Sequence[Mapping[str, Any]],
    segment_started: datetime | None,
    recent_records: int,
    observed_at: datetime,
    run_status: str,
) -> dict[str, Any]:
    if recent_records < 2:
        raise MonitoringError("recent-records must be at least 2")
    eligible = [
        row
        for row in records
        if segment_started is None
        or _parse_utc(str(row["completed_at_utc"])) >= segment_started
    ]
    selected = eligible[-recent_records:]
    if not selected:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "reason": "no committed work units in the current start/resume segment",
            "sample_records": 0,
        }

    truncated = len(eligible) > len(selected)
    if segment_started is not None and not truncated:
        started = segment_started
        counted = selected
    elif len(selected) >= 2:
        # The first completion establishes the left edge when older history was
        # discarded; count only work committed after that edge.
        started = _parse_utc(str(selected[0]["completed_at_utc"]))
        counted = selected[1:]
    else:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "reason": "at least two recent commits are required for an ETA",
            "sample_records": len(selected),
        }

    last_commit = _parse_utc(str(selected[-1]["completed_at_utc"]))
    ended = observed_at if run_status in {"RUNNING", "PAUSE_REQUESTED"} else last_commit
    elapsed = max(0.0, (ended - started).total_seconds())
    completed_units = len(counted)
    completed_requests = sum(int(row.get("request_count", 0)) for row in counted)
    completed_bytes = sum(int(row.get("accepted_bytes", 0)) for row in counted)
    if elapsed <= 0.0 or completed_units <= 0:
        return {
            "status": "INSUFFICIENT_HISTORY",
            "reason": "recent commits do not span a positive time interval",
            "sample_records": len(selected),
        }
    return {
        "status": "AVAILABLE",
        "sample_records": len(selected),
        "window_started_at_utc": started.isoformat().replace("+00:00", "Z"),
        "window_ended_at_utc": ended.isoformat().replace("+00:00", "Z"),
        "window_seconds": elapsed,
        "last_commit_at_utc": last_commit.isoformat().replace("+00:00", "Z"),
        "last_commit_age_seconds": max(0.0, (observed_at - last_commit).total_seconds()),
        "committed_work_units": completed_units,
        "committed_logical_requests": completed_requests,
        "accepted_bytes": completed_bytes,
        "work_units_per_second": completed_units / elapsed,
        "logical_requests_per_second": completed_requests / elapsed,
        "accepted_bytes_per_second": completed_bytes / elapsed,
    }


def _eta(
    *,
    run_status: str,
    progress: Mapping[str, Any],
    performance: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    if run_status == "PASS":
        return {
            "status": "COMPLETE",
            "basis": "terminal_run_state",
            "remaining_seconds": 0.0,
            "estimated_completion_utc": None,
        }
    if run_status == "FAILED":
        return {
            "status": "UNAVAILABLE",
            "reason": "the run is FAILED; resume or start a corrected run before estimating",
        }
    if run_status == "PAUSE_REQUESTED":
        return {
            "status": "UNAVAILABLE",
            "reason": "a cooperative pause has been requested; ETA resumes after the run resumes",
        }
    if performance.get("status") != "AVAILABLE":
        return {
            "status": "UNAVAILABLE",
            "reason": performance.get("reason", "recent performance is unavailable"),
        }
    last_commit_age = float(performance.get("last_commit_age_seconds", 0.0))
    if run_status == "RUNNING" and last_commit_age > STALE_ACTIVE_COMMIT_SECONDS:
        return {
            "status": "STALE_PROGRESS",
            "reason": (
                "no work unit has committed for "
                f"{int(last_commit_age)} seconds; inspect or recover the run before trusting an ETA"
            ),
            "last_commit_age_seconds": last_commit_age,
            "stale_after_seconds": STALE_ACTIVE_COMMIT_SECONDS,
        }

    remaining_requests = progress.get("remaining_logical_requests")
    request_rate = float(performance.get("logical_requests_per_second", 0.0))
    remaining_units = progress.get("remaining_work_units")
    unit_rate = float(performance.get("work_units_per_second", 0.0))
    if remaining_requests is not None and request_rate > 0.0:
        remaining = int(remaining_requests)
        rate = request_rate
        basis = "recent_logical_request_throughput"
        seconds = remaining / rate
    elif remaining_units is not None and unit_rate > 0.0:
        remaining = int(remaining_units)
        rate = unit_rate
        basis = "recent_work_unit_throughput"
        seconds = remaining / rate
    else:
        return {
            "status": "UNAVAILABLE",
            "reason": "the step has not published a usable remaining-work total",
        }
    if not math.isfinite(seconds):
        return {"status": "UNAVAILABLE", "reason": "recent throughput is not finite"}
    completion = observed_at + timedelta(seconds=seconds)
    return {
        "status": "PAUSED_ESTIMATE" if run_status == "PAUSED" else "AVAILABLE",
        "basis": basis,
        "remaining": remaining,
        "recent_rate_per_second": rate,
        "remaining_seconds": seconds,
        "estimated_completion_utc": completion.isoformat().replace("+00:00", "Z"),
        "note": (
            "active-runtime estimate; paused time is excluded"
            if run_status == "PAUSED"
            else "estimate responds to recent commits and may move as source-object cost changes"
        ),
    }


def build_monitor_snapshot(
    project_root: Path | str,
    run_id: str,
    *,
    recent_records: int = 20,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Return one read-only progress/ETA snapshot for any supported long run."""

    validate_run_id(run_id)
    root = Path(project_root).resolve()
    paths = load_project_paths(root)
    run_dir = paths.runs / run_id
    state = RunStateStore(root, run_id).read()
    progress_raw, progress_path = _load_progress(root, run_dir)
    records, journal_paths = _load_journal_records(root, run_dir)
    progress = _normalise_progress(progress_raw, records)
    now = (observed_at or datetime.now(UTC)).astimezone(UTC)
    performance = _recent_performance(
        records=records,
        segment_started=_active_segment_start(run_dir),
        recent_records=recent_records,
        observed_at=now,
        run_status=str(state["status"]),
    )
    eta = _eta(
        run_status=str(state["status"]),
        progress=progress,
        performance=performance,
        observed_at=now,
    )
    return {
        "schema_version": MONITOR_SCHEMA_VERSION,
        "observed_at_utc": now.isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "step_id": state["step_id"],
        "run_status": state["status"],
        "run_message": state.get("message"),
        "progress_source": progress_path,
        "completion_journals": journal_paths,
        "progress": progress,
        "recent_performance": performance,
        "eta": eta,
    }


def _duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "unavailable"
    total = max(0, int(round(float(seconds))))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def format_live_line(snapshot: Mapping[str, Any]) -> str:
    """Format a compact, append-only terminal line; never emits clear codes."""

    progress = snapshot["progress"]
    eta = snapshot["eta"]
    performance = snapshot["recent_performance"]
    pieces = [
        f"[{snapshot['observed_at_utc']}]",
        str(snapshot["run_status"]),
    ]
    if progress.get("phase"):
        pieces.append(f"phase={progress['phase']}")
    if progress.get("product"):
        pieces.append(f"product={progress['product']}")
    if progress.get("current_target_day"):
        pieces.append(f"day={progress['current_target_day']}")
    inflight_done = progress.get("inflight_source_objects_completed")
    inflight_expected = progress.get("inflight_source_objects_expected")
    if inflight_done is not None and inflight_expected:
        pieces.append(f"day-sources={inflight_done}/{inflight_expected}")
    completed = progress.get("completed_work_units")
    expected = progress.get("expected_work_units")
    if completed is not None and expected is not None:
        percent = (100.0 * completed / expected) if expected else 100.0
        pieces.append(f"units={completed}/{expected} ({percent:.1f}%)")
    completed_requests = progress.get("completed_logical_requests")
    expected_requests = progress.get("expected_logical_requests")
    if completed_requests is not None and expected_requests is not None:
        pieces.append(f"requests={completed_requests}/{expected_requests}")
    if performance.get("status") == "AVAILABLE":
        if eta.get("basis") == "recent_logical_request_throughput":
            pieces.append(
                f"recent={float(performance['logical_requests_per_second']):.3f} req/s"
            )
        else:
            pieces.append(f"recent={float(performance['work_units_per_second']):.3f} units/s")
    if eta.get("status") in {"AVAILABLE", "PAUSED_ESTIMATE", "COMPLETE"}:
        pieces.append(f"ETA={_duration(eta.get('remaining_seconds'))}")
        if eta.get("estimated_completion_utc"):
            pieces.append(f"finish={eta['estimated_completion_utc']}")
    else:
        pieces.append(f"ETA=unavailable ({eta.get('reason', 'insufficient history')})")
    return " | ".join(pieces)


def live_status(
    project_root: Path | str,
    run_id: str,
    *,
    interval_seconds: float = 5.0,
    recent_records: int = 20,
    json_lines: bool = False,
) -> None:
    """Print non-clearing snapshots until PASS, FAILED, PAUSED, or Ctrl-C."""

    import time

    if interval_seconds < 1.0:
        raise MonitoringError("interval-seconds must be at least 1")
    while True:
        snapshot = build_monitor_snapshot(
            project_root, run_id, recent_records=recent_records
        )
        if json_lines:
            print(json.dumps(snapshot, sort_keys=True), flush=True)
        else:
            print(format_live_line(snapshot), flush=True)
        if snapshot["run_status"] in TERMINAL_RUN_STATUSES:
            return
        time.sleep(interval_seconds)
