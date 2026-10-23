"""R14 successor Step 01: seal active fields and regional spatial geometry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..hashes import sha256_file
from ..r14 import (
    R14_BUNDLE_PATH,
    R14_FIELD_STATE_SCHEMA_PATH,
    R14_SCOPE_PATH,
    R14_SPATIAL_CONTRACT_PATH,
    R14_SPATIAL_GEOMETRY_PATH,
    seal_r14_registry_bundle,
    verify_r14_registry_bundle,
)
from ..r14_records import (
    R14_ATTESTATION_SCHEMA_PATH,
    read_historical_record_identity,
    write_r14_attestation,
)


STEP01_R14_ARTIFACTS = (
    R14_SCOPE_PATH,
    R14_SPATIAL_CONTRACT_PATH,
    R14_FIELD_STATE_SCHEMA_PATH,
    R14_SPATIAL_GEOMETRY_PATH,
    R14_BUNDLE_PATH,
    R14_ATTESTATION_SCHEMA_PATH,
    "src/kden_v375/r14.py",
    "src/kden_v375/r14_records.py",
    "src/kden_v375/steps/step_01_r14_registries.py",
)


def run(*, project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    historical_step00 = read_historical_record_identity(root, 0)
    historical_step01 = read_historical_record_identity(root, 1)
    sealed = seal_r14_registry_bundle(root)
    verified = verify_r14_registry_bundle(root)
    if sealed["bundle"] != verified["bundle"]:
        raise RuntimeError("R14 registry bundle changed between sealing and verification")
    return write_r14_attestation(
        root,
        record_id="STEP_01_R14",
        run_id=run_id,
        artifact_paths=STEP01_R14_ARTIFACTS,
        gate_evidence={
            **verified["gate_evidence"],
            "registry_bundle_sha256": verified["bundle"]["bundle_sha256"],
            "active_field_count": verified["bundle"]["field_counts"]["total"],
            "historical_catalogs_are_selector_provenance_only": True,
            "historical_pass_records_are_lineage_evidence_only": True,
        },
        predecessor_hashes={
            "HISTORICAL_STEP_00": historical_step00["record_sha256"],
            "HISTORICAL_STEP_01": historical_step01["record_sha256"],
            "OWNER_R14_HANDOFF_FILE": sha256_file(
                root / "reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md"
            ),
        },
    )
