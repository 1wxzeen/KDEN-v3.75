"""R14 successor Step 02: seal and attest the right-open cycle schedule."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..r14_records import (
    R14_ATTESTATION_SCHEMA_PATH,
    read_historical_record_identity,
    verify_r14_attestation,
    write_r14_attestation,
)
from ..r14_schedule import (
    HORIZON_EVIDENCE_PATH,
    R14_SCHEDULE_MANIFEST_PATH,
    R14_SCHEDULE_PARQUET_PATH,
    R14_SCHEDULE_POLICY_PATH,
    seal_r14_cycle_schedule,
    verify_r14_cycle_schedule,
)


STEP02_R14_ARTIFACTS = (
    R14_SCHEDULE_POLICY_PATH,
    HORIZON_EVIDENCE_PATH,
    R14_SCHEDULE_PARQUET_PATH,
    R14_SCHEDULE_MANIFEST_PATH,
    R14_ATTESTATION_SCHEMA_PATH,
    "src/kden_v375/r14_schedule.py",
    "src/kden_v375/steps/step_02_r14_cycle_schedule.py",
)


def run(*, project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    step01 = verify_r14_attestation(root, "STEP_01_R14")
    historical_step02 = read_historical_record_identity(root, 2)
    sealed = seal_r14_cycle_schedule(root)
    verified = verify_r14_cycle_schedule(root)
    if sealed["manifest"] != verified["manifest"]:
        raise RuntimeError("R14 schedule manifest changed between sealing and verification")
    return write_r14_attestation(
        root,
        record_id="STEP_02_R14",
        run_id=run_id,
        artifact_paths=STEP02_R14_ARTIFACTS,
        gate_evidence=sealed["gate_evidence"],
        predecessor_hashes={
            "STEP_01_R14": step01["record_sha256"],
            "HISTORICAL_STEP_02": historical_step02["record_sha256"],
        },
    )
