"""Content-addressed successor attestations for the R14 migration lineage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import ContractError, load_project_paths, utc_now
from .hashes import canonical_json_bytes, sha256_bytes, sha256_path
from .io.atomic import atomic_write_json
from .r14 import R14_SCOPE_ID


R14_ATTESTATION_SCHEMA_VERSION = "KDEN_V375_R14_MIGRATION_ATTESTATION_V1"
R14_ATTESTATION_SCHEMA_PATH = "schemas/r14_attestation_v375.json"
R14_RECORD_PATHS = {
    "STEP_01_R14": "state/STEP_01_R14_PASS.json",
    "STEP_02_R14": "state/STEP_02_R14_ATTESTATION.json",
}


class R14AttestationError(ContractError):
    """An R14 successor attestation is missing, stale, or malformed."""


def _inside(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise R14AttestationError(f"attestation artifact leaves project root: {path}")
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise R14AttestationError(f"attestation must contain a JSON object: {path}")
    return value


def write_r14_attestation(
    project_root: Path | str,
    *,
    record_id: str,
    run_id: str,
    artifact_paths: Iterable[Path | str],
    gate_evidence: Mapping[str, Any],
    predecessor_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Write one immutable named R14 record, or verify an existing one."""

    paths = load_project_paths(project_root)
    if record_id not in R14_RECORD_PATHS:
        raise R14AttestationError(f"unsupported R14 record identity: {record_id!r}")
    if not run_id.startswith("kdenv375-"):
        raise R14AttestationError("R14 attestation run_id must begin with kdenv375-")
    destination = paths.root / R14_RECORD_PATHS[record_id]
    if destination.exists():
        return verify_r14_attestation(paths.root, record_id)
    artifact_hashes: dict[str, str] = {}
    for artifact in artifact_paths:
        absolute = _inside(paths.root, paths.root / Path(artifact))
        relative = absolute.relative_to(paths.root.resolve()).as_posix()
        artifact_hashes[relative] = sha256_path(absolute)
    body = {
        "schema_version": R14_ATTESTATION_SCHEMA_VERSION,
        "record_id": record_id,
        "scope_id": R14_SCOPE_ID,
        "status": "PASS",
        "completed_at_utc": utc_now(),
        "run_id": run_id,
        "predecessor_hashes": dict(sorted(predecessor_hashes.items())),
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "gate_evidence": dict(gate_evidence),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(destination, record, replace=False)
    return record


def verify_r14_attestation(
    project_root: Path | str, record_id: str
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    if record_id not in R14_RECORD_PATHS:
        raise R14AttestationError(f"unsupported R14 record identity: {record_id!r}")
    record = _read_json(paths.root / R14_RECORD_PATHS[record_id])
    if (
        record.get("schema_version") != R14_ATTESTATION_SCHEMA_VERSION
        or record.get("record_id") != record_id
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("status") != "PASS"
    ):
        raise R14AttestationError(f"invalid R14 attestation identity: {record_id}")
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise R14AttestationError(f"R14 attestation content hash mismatch: {record_id}")
    for relative, expected in record.get("artifact_hashes", {}).items():
        artifact = _inside(paths.root, paths.root / relative)
        if sha256_path(artifact) != expected:
            raise R14AttestationError(
                f"R14 attestation artifact changed: {record_id}/{relative}"
            )
    return record


def read_historical_record_identity(
    project_root: Path | str, step_no: int
) -> dict[str, str]:
    """Verify historical record self-integrity without treating it as live authority."""

    paths = load_project_paths(project_root)
    relative = f"state/STEP_{step_no:02d}_PASS.json"
    record = _read_json(paths.root / relative)
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise R14AttestationError(f"historical Step {step_no:02d} record hash mismatch")
    return {
        "path": relative,
        "record_sha256": str(supplied),
        "role": "historical_lineage_evidence_not_live_R14_authorization",
    }
