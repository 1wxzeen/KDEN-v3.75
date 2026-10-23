"""Step 05: one owner-facing acquisition for hourly R14 followed by Q05."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..acquisition.records import verify_combined_pass
from ..acquisition.workflow import run_r14_acquisition


def run(
    *, project_root: Path | str, run_id: str, pause: Any
) -> dict[str, Any]:
    return run_r14_acquisition(
        project_root=project_root,
        run_id=run_id,
        pause_requested=lambda: pause.requested,
    )


def verify_pass(project_root: Path | str) -> dict[str, Any]:
    return verify_combined_pass(project_root, deep=True)
