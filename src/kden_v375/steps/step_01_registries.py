"""Step 01: freeze and validate the complete registry/schema contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts import PauseController, predecessor_hashes, write_step_pass
from ..registries import BUNDLE_INPUTS, BUNDLE_PATH, seal_registry_bundle, verify_registry_bundle


STEP01_ARTIFACTS = BUNDLE_INPUTS + (
    BUNDLE_PATH,
    "src/kden_v375/registries.py",
    "src/kden_v375/steps/step_01_registries.py",
)


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    predecessors = predecessor_hashes(project_root, 1)
    if pause is not None:
        pause.raise_if_requested()
    sealed = seal_registry_bundle(project_root)
    if pause is not None:
        pause.raise_if_requested()
    verified = verify_registry_bundle(project_root)
    if sealed["bundle"]["bundle_sha256"] != verified["bundle"]["bundle_sha256"]:
        raise RuntimeError("registry bundle changed between sealing and verification")
    gates = verified["gate_evidence"]
    gates["registry_bundle"] = {
        "bundle_sha256": verified["bundle"]["bundle_sha256"],
        "artifact_count": len(verified["bundle"]["artifacts"]),
        "field_count": verified["bundle"]["field_counts"]["total"],
        "self_contained": True,
    }
    return write_step_pass(
        project_root,
        step_no=1,
        run_id=run_id,
        artifact_paths=STEP01_ARTIFACTS,
        gate_evidence=gates,
        predecessor_hashes=predecessors,
    )
