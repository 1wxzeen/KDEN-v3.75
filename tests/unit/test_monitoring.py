from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from kden_v375.contracts import RunStateStore
from kden_v375.monitoring import build_monitor_snapshot, format_live_line


RUN_ID = "kdenv375-s04-synthetic-20260914T120000Z-monitor"


def _project(root: Path, status: str = "RUNNING") -> Path:
    (root / "config").mkdir()
    (root / "config/project_v375.toml").write_text(
        """schema_version = "KDEN_V375_PROJECT_CONFIG_V1"

[paths]
registries = "registries"
schemas = "schemas"
archive = "archive"
runs = "runs"
reports = "reports"
state = "state"
""",
        encoding="utf-8",
    )
    store = RunStateStore(root, RUN_ID)
    store.initialize()
    store.transition(status, message="test")
    return root / "runs" / RUN_ID


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class MonitoringTests(unittest.TestCase):
    def test_eta_prefers_recent_logical_request_throughput(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run_dir = _project(root)
            (run_dir / "monitoring").mkdir()
            (run_dir / "monitoring/live_status.json").write_text(
                json.dumps(
                    {
                        "phase": "r14_primary",
                        "completed_work_units": 2,
                        "expected_work_units": 10,
                        "completed_logical_requests": 20,
                        "expected_logical_requests": 100,
                        "updated_at_utc": "2026-09-14T12:02:00Z",
                    }
                ),
                encoding="utf-8",
            )
            _write_jsonl(
                run_dir / "events.jsonl",
                [
                    {
                        "event_code": "RUN_STARTED",
                        "timestamp_utc": "2026-09-14T12:00:00Z",
                    }
                ],
            )
            _write_jsonl(
                run_dir / "progress/completions.jsonl",
                [
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T12:01:00Z",
                        "request_count": 10,
                        "accepted_bytes": 100,
                    },
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T12:02:00Z",
                        "request_count": 10,
                        "accepted_bytes": 100,
                    },
                ],
            )

            snapshot = build_monitor_snapshot(
                root,
                RUN_ID,
                observed_at=datetime(2026, 9, 14, 12, 3, tzinfo=UTC),
            )
            self.assertEqual(snapshot["eta"]["basis"], "recent_logical_request_throughput")
            self.assertAlmostEqual(snapshot["recent_performance"]["logical_requests_per_second"], 20 / 180)
            self.assertAlmostEqual(snapshot["eta"]["remaining_seconds"], 720.0)

    def test_resume_segment_excludes_pre_pause_history(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run_dir = _project(root)
            (run_dir / "pilot").mkdir()
            (run_dir / "pilot/live_status.json").write_text(
                json.dumps(
                    {
                        "completed_work_units": 4,
                        "expected_work_units": 10,
                        "remaining_work_units": 6,
                    }
                ),
                encoding="utf-8",
            )
            _write_jsonl(
                run_dir / "events.jsonl",
                [
                    {"event_code": "RUN_STARTED", "timestamp_utc": "2026-09-14T12:00:00Z"},
                    {"event_code": "RUN_RESUMED", "timestamp_utc": "2026-09-14T13:00:00Z"},
                ],
            )
            _write_jsonl(
                run_dir / "pilot/progress/completions.jsonl",
                [
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T12:01:00Z",
                        "request_count": 1,
                    },
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T13:00:30Z",
                        "request_count": 1,
                    },
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T13:01:00Z",
                        "request_count": 1,
                    },
                ],
            )
            snapshot = build_monitor_snapshot(
                root,
                RUN_ID,
                observed_at=datetime(2026, 9, 14, 13, 1, tzinfo=UTC),
            )
            self.assertEqual(snapshot["recent_performance"]["sample_records"], 2)
            self.assertAlmostEqual(snapshot["recent_performance"]["work_units_per_second"], 2 / 60)

    def test_pass_is_complete_even_without_a_journal(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _project(root, status="PASS")
            snapshot = build_monitor_snapshot(root, RUN_ID)
            self.assertEqual(snapshot["eta"]["status"], "COMPLETE")
            self.assertEqual(snapshot["eta"]["remaining_seconds"], 0.0)

    def test_stale_running_progress_suppresses_misleading_eta(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run_dir = _project(root)
            (run_dir / "monitoring").mkdir()
            (run_dir / "monitoring/live_status.json").write_text(
                json.dumps(
                    {
                        "completed_work_units": 2,
                        "expected_work_units": 10,
                        "completed_logical_requests": 20,
                        "expected_logical_requests": 100,
                    }
                ),
                encoding="utf-8",
            )
            _write_jsonl(
                run_dir / "progress/completions.jsonl",
                [
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T12:00:00Z",
                        "request_count": 10,
                    },
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T12:01:00Z",
                        "request_count": 10,
                    },
                ],
            )
            snapshot = build_monitor_snapshot(
                root,
                RUN_ID,
                observed_at=datetime(2026, 9, 14, 12, 7, tzinfo=UTC),
            )
            self.assertEqual(snapshot["eta"]["status"], "STALE_PROGRESS")
            self.assertIn("no work unit has committed", snapshot["eta"]["reason"])

    def test_pause_requested_suppresses_eta(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            run_dir = _project(root)
            RunStateStore(root, RUN_ID).request_pause()
            (run_dir / "monitoring").mkdir()
            (run_dir / "monitoring/live_status.json").write_text(
                json.dumps(
                    {
                        "completed_work_units": 2,
                        "expected_work_units": 10,
                        "completed_logical_requests": 20,
                        "expected_logical_requests": 100,
                    }
                ),
                encoding="utf-8",
            )
            _write_jsonl(
                run_dir / "progress/completions.jsonl",
                [
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T12:00:00Z",
                        "request_count": 10,
                    },
                    {
                        "run_id": RUN_ID,
                        "completed_at_utc": "2026-09-14T12:01:00Z",
                        "request_count": 10,
                    },
                ],
            )
            snapshot = build_monitor_snapshot(
                root,
                RUN_ID,
                observed_at=datetime(2026, 9, 14, 12, 2, tzinfo=UTC),
            )
            self.assertEqual(snapshot["eta"]["status"], "UNAVAILABLE")
            self.assertIn("pause has been requested", snapshot["eta"]["reason"])

    def test_live_line_is_compact_and_never_clears_terminal(self) -> None:
        snapshot = {
            "observed_at_utc": "2026-09-14T12:00:00Z",
            "run_status": "RUNNING",
            "progress": {
                "phase": "pilot",
                "product": "wrfsfcf",
                "completed_work_units": 5,
                "expected_work_units": 10,
                "completed_logical_requests": None,
                "expected_logical_requests": None,
            },
            "recent_performance": {"status": "AVAILABLE", "work_units_per_second": 0.5},
            "eta": {
                "status": "AVAILABLE",
                "basis": "recent_work_unit_throughput",
                "remaining_seconds": 10,
                "estimated_completion_utc": "2026-09-14T12:00:10Z",
            },
        }
        line = format_live_line(snapshot)
        self.assertIn("units=5/10 (50.0%)", line)
        self.assertIn("ETA=10s", line)
        self.assertNotIn("\x1b", line)


if __name__ == "__main__":
    unittest.main()
