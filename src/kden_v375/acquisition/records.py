"""Readiness, independent product, and combined R14 acquisition seals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..contracts import ContractError, load_project_paths, utc_now, validate_run_id
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from ..io.atomic import atomic_write_json
from ..r14 import R14_SCOPE_ID
from ..r14_pilot_records import verify_r14_step04_pass
from ..r14_request_plans import PRODUCTS, R14_PLAN_MANIFEST, verify_r14_product_plan


READY_SCHEMA = "KDEN_V375_R14_READY_FOR_OWNER_RUN_V1"
PRODUCT_PASS_SCHEMA = "KDEN_V375_R14_PRODUCT_ACQUISITION_PASS_V1"
COMBINED_PASS_SCHEMA = "KDEN_V375_R14_COMBINED_ACQUISITION_PASS_V1"
READY_PATH = "state/R14_READY_FOR_OWNER_RUN.json"
COMBINED_PASS_PATH = "state/R14_PASS.json"
PRODUCT_PASS_PATH = {
    "wrfsfcf": "hrrr_v4_local_archive/wrfsfcf/state/WRFSFCF_R14_PASS.json",
    "wrfsubhf": (
        "hrrr_v4_local_archive/wrfsubhf/state/WRFSUBHF_Q05_R14_PASS.json"
    ),
}
PRODUCT_MANIFEST_PATH = {
    "wrfsfcf": (
        "hrrr_v4_local_archive/wrfsfcf/manifests/"
        "acquisition_wrfsfcf_r14_v375_manifest.json"
    ),
    "wrfsubhf": (
        "hrrr_v4_local_archive/wrfsubhf/manifests/"
        "acquisition_wrfsubhf_q05_r14_v375_manifest.json"
    ),
}
PRODUCT_REPORT_PATH = {
    "wrfsfcf": "hrrr_v4_local_archive/wrfsfcf/reports/acquisition_r14_v375.json",
    "wrfsubhf": "hrrr_v4_local_archive/wrfsubhf/reports/acquisition_q05_r14_v375.json",
}
COMBINED_REPORT_PATH = "reports/step_05_r14_acquisition_report_v375.json"


class AcquisitionRecordError(ContractError):
    """An acquisition authorization or PASS chain is missing or stale."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AcquisitionRecordError(f"record is not a JSON object: {path}")
    return value


def _inside(root: Path, relative: Path | str) -> Path:
    path = (root / Path(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise AcquisitionRecordError(f"artifact leaves the project root: {relative}")
    return path


def _hash_artifacts(root: Path, artifacts: Iterable[Path | str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in artifacts:
        path = _inside(root, relative)
        if not path.exists():
            raise AcquisitionRecordError(f"required artifact is missing: {relative}")
        result[path.relative_to(root).as_posix()] = sha256_path(path)
    return dict(sorted(result.items()))


def _verify_record_hash(record: Mapping[str, Any], *, label: str) -> None:
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise AcquisitionRecordError(f"{label} record hash mismatch")


def readiness_artifacts() -> tuple[str, ...]:
    return (
        "config/project_v375.toml",
        "config/r14_acquisition_v375.json",
        "config/r14_acquisition_runtime_v375.json",
        "config/wrfsfcf_8w.toml",
        "config/wrfsubhf_8w.toml",
        "schemas/hrrr_field_state_r14_v375.json",
        "schemas/retrieval_ledger_v375.json",
        "schemas/temporal_coverage_v375.json",
        "schemas/r14_acquisition_ready_v375.json",
        "schemas/r14_acquisition_pass_v375.json",
        "reports/step_05_r14_OWNER_RUNBOOK.md",
        "src/kden_v375/acquisition/__init__.py",
        "src/kden_v375/acquisition/source.py",
        "src/kden_v375/acquisition/workflow.py",
        "src/kden_v375/acquisition/records.py",
        "src/kden_v375/steps/step_05_r14_acquisition.py",
        "src/kden_v375/steps/step_05_wrfsfcf.py",
        "src/kden_v375/steps/step_06_wrfsubhf.py",
        "src/kden_v375/cli.py",
        "src/kden_v375/monitoring.py",
        "src/kden_v375/progress.py",
        "src/kden_v375/execution.py",
        "src/kden_v375/pilot.py",
        "src/kden_v375/io/atomic.py",
        "src/kden_v375/io/cache.py",
        "src/kden_v375/io/grib.py",
        "src/kden_v375/io/http_range.py",
        "src/kden_v375/io/parquet.py",
        "environment/requirements.lock",
        "pyproject.toml",
    )


def write_ready_record(
    project_root: Path | str,
    *,
    execution_contract: Mapping[str, Any],
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    destination = root / READY_PATH
    if destination.exists():
        return verify_ready_record(root)
    step04 = verify_r14_step04_pass(root)
    plans = {product: verify_r14_product_plan(root, product) for product in PRODUCTS}
    body = {
        "schema_version": READY_SCHEMA,
        "record_id": "R14_READY_FOR_OWNER_RUN",
        "scope_id": R14_SCOPE_ID,
        "status": "READY_FOR_OWNER_RUN",
        "prepared_at_utc": utc_now(),
        "predecessor_hashes": {
            "STEP_04_R14": step04["record_sha256"],
            "STEP_03_R14": step04["predecessor_hashes"]["STEP_03_R14"],
            "wrfsfcf_plan": plans["wrfsfcf"]["plan_sha256"],
            "wrfsubhf_plan": plans["wrfsubhf"]["plan_sha256"],
        },
        "artifact_hashes": _hash_artifacts(root, readiness_artifacts()),
        "execution_contract": dict(execution_contract),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(destination, record, replace=False)
    return record


def verify_ready_record(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = _read_json(root / READY_PATH)
    if (
        record.get("schema_version") != READY_SCHEMA
        or record.get("record_id") != "R14_READY_FOR_OWNER_RUN"
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("status") != "READY_FOR_OWNER_RUN"
    ):
        raise AcquisitionRecordError("R14 owner-run readiness identity changed")
    _verify_record_hash(record, label="R14 readiness")
    step04 = verify_r14_step04_pass(root)
    plans = {product: verify_r14_product_plan(root, product) for product in PRODUCTS}
    expected_predecessors = {
        "STEP_04_R14": step04["record_sha256"],
        "STEP_03_R14": step04["predecessor_hashes"]["STEP_03_R14"],
        "wrfsfcf_plan": plans["wrfsfcf"]["plan_sha256"],
        "wrfsubhf_plan": plans["wrfsubhf"]["plan_sha256"],
    }
    if record.get("predecessor_hashes") != expected_predecessors:
        raise AcquisitionRecordError("R14 readiness predecessor lineage changed")
    for relative, expected in record.get("artifact_hashes", {}).items():
        if sha256_path(_inside(root, relative)) != expected:
            raise AcquisitionRecordError(f"R14 owner-run artifact changed: {relative}")
    return record


def _product_record_id(product: str) -> str:
    if product == "wrfsfcf":
        return "WRFSFCF_R14"
    if product == "wrfsubhf":
        return "WRFSUBHF_Q05_R14"
    raise AcquisitionRecordError(f"unknown acquisition product: {product}")


def write_product_pass(
    project_root: Path | str,
    *,
    product: str,
    run_id: str,
    gate_evidence: Mapping[str, bool],
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    validate_run_id(run_id, step_no=5, scope="owner-full")
    destination = root / PRODUCT_PASS_PATH[product]
    if destination.exists():
        return verify_product_pass(root, product, expected_run_id=run_id)
    if not gate_evidence or not all(value is True for value in gate_evidence.values()):
        raise AcquisitionRecordError(f"{product} cannot PASS with a failed gate")
    ready = verify_ready_record(root)
    step04 = verify_r14_step04_pass(root)
    artifacts = (PRODUCT_MANIFEST_PATH[product], PRODUCT_REPORT_PATH[product])
    body = {
        "schema_version": PRODUCT_PASS_SCHEMA,
        "record_id": _product_record_id(product),
        "scope_id": R14_SCOPE_ID,
        "product": product,
        "status": "PASS",
        "run_id": run_id,
        "completed_at_utc": utc_now(),
        "predecessor_hashes": {
            "STEP_04_R14": step04["record_sha256"],
            "R14_READY_FOR_OWNER_RUN": ready["record_sha256"],
        },
        "artifact_hashes": _hash_artifacts(root, artifacts),
        "gate_evidence": dict(gate_evidence),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(destination, record, replace=False)
    return record


def _verify_unit_chain(root: Path, manifest: Mapping[str, Any]) -> None:
    units = manifest.get("units", [])
    if len(units) != int(manifest.get("completed_work_unit_count", -1)):
        raise AcquisitionRecordError("product unit manifest count changed")
    for unit in units:
        manifest_path = _inside(root, str(unit["manifest_path"]))
        artifact_path = _inside(root, str(unit["artifact_path"]))
        if sha256_file(manifest_path) != unit["manifest_sha256"]:
            raise AcquisitionRecordError(
                f"work-unit manifest changed: {unit['unit_id']}"
            )
        if sha256_path(artifact_path) != unit["artifact_sha256"]:
            raise AcquisitionRecordError(f"work-unit artifact changed: {unit['unit_id']}")


def verify_product_pass(
    project_root: Path | str,
    product: str,
    *,
    expected_run_id: str | None = None,
    deep: bool = True,
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = _read_json(root / PRODUCT_PASS_PATH[product])
    if (
        record.get("schema_version") != PRODUCT_PASS_SCHEMA
        or record.get("record_id") != _product_record_id(product)
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("product") != product
        or record.get("status") != "PASS"
    ):
        raise AcquisitionRecordError(f"invalid {product} acquisition PASS identity")
    validate_run_id(str(record.get("run_id", "")), step_no=5, scope="owner-full")
    if expected_run_id is not None and record["run_id"] != expected_run_id:
        raise AcquisitionRecordError(
            f"{product} already belongs to a different owner-full run"
        )
    _verify_record_hash(record, label=f"{product} acquisition PASS")
    ready = verify_ready_record(root)
    step04 = verify_r14_step04_pass(root)
    if record.get("predecessor_hashes") != {
        "STEP_04_R14": step04["record_sha256"],
        "R14_READY_FOR_OWNER_RUN": ready["record_sha256"],
    }:
        raise AcquisitionRecordError(f"{product} predecessor lineage changed")
    for relative, expected in record.get("artifact_hashes", {}).items():
        if sha256_path(_inside(root, relative)) != expected:
            raise AcquisitionRecordError(f"{product} PASS artifact changed: {relative}")
    manifest = _read_json(root / PRODUCT_MANIFEST_PATH[product])
    if (
        manifest.get("schema_version")
        != "KDEN_V375_R14_PRODUCT_ACQUISITION_MANIFEST_V1"
        or manifest.get("scope_id") != R14_SCOPE_ID
        or manifest.get("product") != product
        or manifest.get("run_id") != record["run_id"]
        or manifest.get("status") != "PASS"
        or manifest.get("gates") != record["gate_evidence"]
    ):
        raise AcquisitionRecordError(f"{product} product manifest changed")
    _verify_record_hash(manifest, label=f"{product} product manifest")
    if deep:
        _verify_unit_chain(root, manifest)
    return record


def write_combined_pass(
    project_root: Path | str,
    *,
    run_id: str,
    gate_evidence: Mapping[str, bool],
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    validate_run_id(run_id, step_no=5, scope="owner-full")
    destination = root / COMBINED_PASS_PATH
    if destination.exists():
        return verify_combined_pass(root, expected_run_id=run_id)
    if not gate_evidence or not all(value is True for value in gate_evidence.values()):
        raise AcquisitionRecordError("combined R14 acquisition has a failed gate")
    products = {
        product: verify_product_pass(root, product, expected_run_id=run_id, deep=False)
        for product in PRODUCTS
    }
    ready = verify_ready_record(root)
    body = {
        "schema_version": COMBINED_PASS_SCHEMA,
        "record_id": "R14",
        "scope_id": R14_SCOPE_ID,
        "status": "PASS",
        "run_id": run_id,
        "completed_at_utc": utc_now(),
        "predecessor_hashes": {
            "R14_READY_FOR_OWNER_RUN": ready["record_sha256"],
            "WRFSFCF_R14": products["wrfsfcf"]["record_sha256"],
            "WRFSUBHF_Q05_R14": products["wrfsubhf"]["record_sha256"],
        },
        "artifact_hashes": _hash_artifacts(root, (COMBINED_REPORT_PATH,)),
        "gate_evidence": dict(gate_evidence),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(destination, record, replace=False)
    return record


def verify_combined_pass(
    project_root: Path | str,
    *,
    expected_run_id: str | None = None,
    deep: bool = True,
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = _read_json(root / COMBINED_PASS_PATH)
    if (
        record.get("schema_version") != COMBINED_PASS_SCHEMA
        or record.get("record_id") != "R14"
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("status") != "PASS"
    ):
        raise AcquisitionRecordError("combined R14 PASS identity changed")
    validate_run_id(str(record.get("run_id", "")), step_no=5, scope="owner-full")
    if expected_run_id is not None and record["run_id"] != expected_run_id:
        raise AcquisitionRecordError("combined R14 PASS belongs to another run")
    _verify_record_hash(record, label="combined R14 PASS")
    ready = verify_ready_record(root)
    products = {
        product: verify_product_pass(
            root, product, expected_run_id=record["run_id"], deep=deep
        )
        for product in PRODUCTS
    }
    if record.get("predecessor_hashes") != {
        "R14_READY_FOR_OWNER_RUN": ready["record_sha256"],
        "WRFSFCF_R14": products["wrfsfcf"]["record_sha256"],
        "WRFSUBHF_Q05_R14": products["wrfsubhf"]["record_sha256"],
    }:
        raise AcquisitionRecordError("combined R14 predecessor lineage changed")
    for relative, expected in record.get("artifact_hashes", {}).items():
        if sha256_path(_inside(root, relative)) != expected:
            raise AcquisitionRecordError(f"combined R14 artifact changed: {relative}")
    return record
