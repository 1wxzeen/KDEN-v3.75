"""Step 04: execute, rebuild, measure, and seal the R14 confirmation pilot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts import PauseController
from ..pilot import run_representative_pilot
from ..r14_pilot_records import verify_r14_step04_pass, write_r14_step04_pass


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    result = run_representative_pilot(
        project_root=project_root,
        run_id=run_id,
        pause_requested=None if pause is None else (lambda: pause.requested),
    )
    return write_r14_step04_pass(
        project_root,
        run_id=run_id,
        artifacts=result["artifact_paths"],
        gate_evidence=result["gate_evidence"],
    )


def verify_pass(project_root: Path | str) -> dict[str, Any]:
    return verify_r14_step04_pass(project_root)
