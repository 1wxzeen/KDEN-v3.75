"""Step 08: deep full-history acceptance and immutable acquisition freeze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..acceptance.workflow import (
    CONTRACT_PATH,
    FINAL_PASS_PATH,
    FREEZE_PATH,
    REPORT_PATH,
    RUNBOOK_PATH,
    SCHEMA_PATH,
    run_final_acceptance,
    verify_final_acceptance_pass,
)
from ..contracts import (
    PauseController,
    load_project_paths,
    verify_step_pass,
    write_step_pass,
)


STEP_NO = 8


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    if (root / "state/STEP_08_PASS.json").is_file():
        return verify_pass(root)
    final = run_final_acceptance(
        project_root=root,
        run_id=run_id,
        pause=pause,
    )
    step07 = verify_step_pass(root, 7)
    return write_step_pass(
        root,
        step_no=STEP_NO,
        run_id=run_id,
        artifact_paths=(
            CONTRACT_PATH,
            SCHEMA_PATH,
            REPORT_PATH,
            FREEZE_PATH,
            RUNBOOK_PATH,
            FINAL_PASS_PATH,
            "src/kden_v375/acceptance/__init__.py",
            "src/kden_v375/acceptance/workflow.py",
            "src/kden_v375/steps/step_08_acceptance.py",
        ),
        predecessor_hashes={"STEP_07": step07["record_sha256"]},
        gate_evidence={
            **final["gate_evidence"],
            "kden_v375_acquisition_pass_sha256": final["record_sha256"],
        },
    )


def verify_pass(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = verify_step_pass(root, STEP_NO)
    final = verify_final_acceptance_pass(root)
    expected = {
        **final["gate_evidence"],
        "kden_v375_acquisition_pass_sha256": final["record_sha256"],
    }
    if record.get("gate_evidence") != expected:
        raise RuntimeError("Step 08 gate evidence changed")
    if record.get("predecessor_hashes") != {
        "STEP_07": verify_step_pass(root, 7)["record_sha256"]
    }:
        raise RuntimeError("Step 08 predecessor changed")
    return record
