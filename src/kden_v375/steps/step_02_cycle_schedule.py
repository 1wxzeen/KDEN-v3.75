"""Step 02: build, publish, and seal the DST-safe cycle schedule."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts import PauseController, predecessor_hashes, write_step_pass
from ..schedule import (
    HORIZON_EVIDENCE_PATH,
    SCHEDULE_MANIFEST_PATH,
    SCHEDULE_PARQUET_PATH,
    SCHEDULE_POLICY_PATH,
    seal_cycle_schedule,
    verify_cycle_schedule,
)


STEP02_ARTIFACTS = (
    SCHEDULE_POLICY_PATH,
    HORIZON_EVIDENCE_PATH,
    SCHEDULE_PARQUET_PATH,
    SCHEDULE_MANIFEST_PATH,
    "src/kden_v375/schedule.py",
    "src/kden_v375/steps/step_02_cycle_schedule.py",
)


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    predecessors = predecessor_hashes(project_root, 2)
    if pause is not None:
        pause.raise_if_requested()
    sealed = seal_cycle_schedule(
        project_root,
        step01_record_sha256=predecessors["STEP_01"],
    )
    if pause is not None:
        pause.raise_if_requested()
    verified = verify_cycle_schedule(project_root)
    if sealed["manifest"] != verified["manifest"]:
        raise RuntimeError("cycle-schedule manifest changed between sealing and verification")
    return write_step_pass(
        project_root,
        step_no=2,
        run_id=run_id,
        artifact_paths=STEP02_ARTIFACTS,
        gate_evidence=sealed["gate_evidence"],
        predecessor_hashes=predecessors,
    )
