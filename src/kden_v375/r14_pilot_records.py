"""Immutable successor PASS record for the bounded R14 Step 04 pilot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import ContractError, load_project_paths, utc_now, validate_run_id
from .hashes import canonical_json_bytes, sha256_bytes, sha256_path
from .io.atomic import atomic_write_json
from .r14 import R14_SCOPE_ID
from .r14_plan_records import verify_r14_step03_pass
from .r14_records import verify_r14_attestation


R14_STEP04_PASS_SCHEMA_VERSION = "KDEN_V375_R14_STEP04_PASS_V1"
R14_STEP04_RECORD_PATH = "state/STEP_04_R14_PASS.json"
R14_STEP04_REPORT_PATH = "reports/step_04_r14_pilot_report_v375.json"


class R14PilotRecordError(ContractError):
    """The R14 pilot record is missing, malformed, or stale."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise R14PilotRecordError(f"R14 pilot record must be an object: {path}")
    return value


def _inside(root: Path, relative: Path | str) -> Path:
    path = (root / Path(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise R14PilotRecordError(f"R14 pilot artifact leaves project root: {relative}")
    return path


def _predecessors(root: Path) -> dict[str, str]:
    step01 = verify_r14_attestation(root, "STEP_01_R14")
    step02 = verify_r14_attestation(root, "STEP_02_R14")
    step03 = verify_r14_step03_pass(root)
    return {
        "STEP_01_R14": step01["record_sha256"],
        "STEP_02_R14": step02["record_sha256"],
        "STEP_03_R14": step03["record_sha256"],
    }


def _artifact_hashes(root: Path, artifacts: Iterable[Path | str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for relative in artifacts:
        path = _inside(root, relative)
        if not path.exists():
            raise R14PilotRecordError(f"R14 pilot artifact is missing: {relative}")
        values[path.relative_to(root).as_posix()] = sha256_path(path)
    return dict(sorted(values.items()))


def write_r14_step04_pass(
    project_root: Path | str,
    *,
    run_id: str,
    artifacts: Iterable[Path | str],
    gate_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    validate_run_id(run_id, step_no=4)
    destination = root / R14_STEP04_RECORD_PATH
    if destination.exists():
        return verify_r14_step04_pass(root)
    if not gate_evidence or not all(value is True for value in gate_evidence.values()):
        raise R14PilotRecordError("R14 Step 04 cannot pass with a failed or non-boolean gate")
    report = _read_json(root / R14_STEP04_REPORT_PATH)
    if (
        report.get("schema_version") != "KDEN_V375_R14_PILOT_REPORT_V1"
        or report.get("scope_id") != R14_SCOPE_ID
        or report.get("status") != "PASS"
        or report.get("run_id") != run_id
        or report.get("gates") != dict(gate_evidence)
    ):
        raise R14PilotRecordError("R14 pilot report does not support a PASS record")
    body = {
        "schema_version": R14_STEP04_PASS_SCHEMA_VERSION,
        "record_id": "STEP_04_R14",
        "scope_id": R14_SCOPE_ID,
        "status": "PASS",
        "completed_at_utc": utc_now(),
        "run_id": run_id,
        "predecessor_hashes": _predecessors(root),
        "artifact_hashes": _artifact_hashes(root, artifacts),
        "gate_evidence": dict(gate_evidence),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(destination, record, replace=False)
    return record


def verify_r14_step04_pass(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = _read_json(root / R14_STEP04_RECORD_PATH)
    if (
        record.get("schema_version") != R14_STEP04_PASS_SCHEMA_VERSION
        or record.get("record_id") != "STEP_04_R14"
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("status") != "PASS"
    ):
        raise R14PilotRecordError("R14 Step 04 PASS identity changed")
    validate_run_id(str(record.get("run_id", "")), step_no=4)
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise R14PilotRecordError("R14 Step 04 PASS record hash mismatch")
    if record.get("predecessor_hashes") != _predecessors(root):
        raise R14PilotRecordError("R14 Step 04 predecessor lineage changed")
    for relative, expected in record.get("artifact_hashes", {}).items():
        if sha256_path(_inside(root, relative)) != expected:
            raise R14PilotRecordError(f"R14 Step 04 artifact changed: {relative}")
    gates = record.get("gate_evidence", {})
    if not gates or not all(value is True for value in gates.values()):
        raise R14PilotRecordError("R14 Step 04 PASS contains a failed gate")
    report = _read_json(root / R14_STEP04_REPORT_PATH)
    if (
        report.get("scope_id") != R14_SCOPE_ID
        or report.get("run_id") != record["run_id"]
        or report.get("status") != "PASS"
        or report.get("gates") != gates
    ):
        raise R14PilotRecordError("R14 Step 04 report changed against its PASS")
    return record
