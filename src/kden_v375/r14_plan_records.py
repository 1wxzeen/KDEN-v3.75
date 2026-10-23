"""Immutable product and aggregate PASS records for R14 Step 03."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import ContractError, load_project_paths, utc_now, validate_run_id
from .hashes import canonical_json_bytes, sha256_bytes, sha256_path
from .io.atomic import atomic_write_json
from .r14 import R14_SCOPE_ID
from .r14_records import verify_r14_attestation
from .r14_request_plans import PRODUCTS, verify_r14_product_plan


R14_PRODUCT_PASS_SCHEMA_VERSION = "KDEN_V375_R14_PRODUCT_PLAN_PASS_V1"
R14_STEP03_PASS_SCHEMA_VERSION = "KDEN_V375_R14_STEP03_PASS_V1"
R14_STEP03_PASS_SCHEMA_PATH = "schemas/r14_step03_pass_v375.json"
R14_PRODUCT_RECORD_PATHS = {
    "wrfsfcf": "state/STEP_03_R14_WRFSFCF_PASS.json",
    "wrfsubhf": "state/STEP_03_R14_WRFSUBHF_PASS.json",
}
R14_STEP03_RECORD_PATH = "state/STEP_03_R14_PASS.json"


class R14PlanRecordError(ContractError):
    """An R14 Step 03 record is missing, malformed, or stale."""


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise R14PlanRecordError(f"PASS record must contain an object: {path}")
    return value


def _inside(root: Path, relative: Path | str) -> Path:
    path = (root / Path(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise R14PlanRecordError(f"PASS artifact leaves project root: {relative}")
    return path


def _artifact_hashes(root: Path, artifacts: Iterable[Path | str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in artifacts:
        path = _inside(root, relative)
        result[path.relative_to(root.resolve()).as_posix()] = sha256_path(path)
    return dict(sorted(result.items()))


def _write_record(
    root: Path,
    *,
    destination: str,
    schema_version: str,
    record_id: str,
    run_id: str,
    artifacts: Iterable[Path | str],
    gate_evidence: Mapping[str, Any],
    predecessor_hashes: Mapping[str, str],
    product: str | None = None,
) -> dict[str, Any]:
    path = root / destination
    if path.exists():
        return _verify_record(
            root,
            destination=destination,
            schema_version=schema_version,
            record_id=record_id,
            product=product,
        )
    validate_run_id(run_id, step_no=3)
    body: dict[str, Any] = {
        "schema_version": schema_version,
        "record_id": record_id,
        "scope_id": R14_SCOPE_ID,
        "status": "PASS",
        "completed_at_utc": utc_now(),
        "run_id": run_id,
        "predecessor_hashes": dict(sorted(predecessor_hashes.items())),
        "artifact_hashes": _artifact_hashes(root, artifacts),
        "gate_evidence": dict(gate_evidence),
    }
    if product is not None:
        body["product"] = product
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(path, record, replace=False)
    return record


def _verify_record(
    root: Path,
    *,
    destination: str,
    schema_version: str,
    record_id: str,
    product: str | None,
) -> dict[str, Any]:
    record = _read_json(root / destination)
    if (
        record.get("schema_version") != schema_version
        or record.get("record_id") != record_id
        or record.get("scope_id") != R14_SCOPE_ID
        or record.get("status") != "PASS"
        or record.get("product") != product
    ):
        raise R14PlanRecordError(f"invalid R14 Step 03 record identity: {record_id}")
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise R14PlanRecordError(f"R14 Step 03 record hash mismatch: {record_id}")
    for relative, expected in record.get("artifact_hashes", {}).items():
        if sha256_path(_inside(root, relative)) != expected:
            raise R14PlanRecordError(
                f"R14 Step 03 artifact changed: {record_id}/{relative}"
            )
    return record


def write_r14_product_pass(
    project_root: Path | str,
    *,
    product: str,
    run_id: str,
    artifacts: Iterable[Path | str],
    gate_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if product not in PRODUCTS:
        raise R14PlanRecordError(f"unsupported R14 product: {product!r}")
    root = load_project_paths(project_root).root
    step01 = verify_r14_attestation(root, "STEP_01_R14")
    step02 = verify_r14_attestation(root, "STEP_02_R14")
    return _write_record(
        root,
        destination=R14_PRODUCT_RECORD_PATHS[product],
        schema_version=R14_PRODUCT_PASS_SCHEMA_VERSION,
        record_id=f"STEP_03_R14_{product.upper()}",
        run_id=run_id,
        artifacts=artifacts,
        gate_evidence=gate_evidence,
        predecessor_hashes={
            "STEP_01_R14": step01["record_sha256"],
            "STEP_02_R14": step02["record_sha256"],
        },
        product=product,
    )


def verify_r14_product_pass(
    project_root: Path | str, product: str
) -> dict[str, Any]:
    if product not in PRODUCTS:
        raise R14PlanRecordError(f"unsupported R14 product: {product!r}")
    root = load_project_paths(project_root).root
    record = _verify_record(
        root,
        destination=R14_PRODUCT_RECORD_PATHS[product],
        schema_version=R14_PRODUCT_PASS_SCHEMA_VERSION,
        record_id=f"STEP_03_R14_{product.upper()}",
        product=product,
    )
    step01 = verify_r14_attestation(root, "STEP_01_R14")
    step02 = verify_r14_attestation(root, "STEP_02_R14")
    if record["predecessor_hashes"] != {
        "STEP_01_R14": step01["record_sha256"],
        "STEP_02_R14": step02["record_sha256"],
    }:
        raise R14PlanRecordError(f"R14 {product} predecessor lineage changed")
    plan = verify_r14_product_plan(root, product)
    if record["gate_evidence"] != plan:
        raise R14PlanRecordError(f"R14 {product} plan gates changed")
    return record


def write_r14_step03_pass(
    project_root: Path | str,
    *,
    run_id: str,
    artifacts: Iterable[Path | str],
    gate_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    step01 = verify_r14_attestation(root, "STEP_01_R14")
    step02 = verify_r14_attestation(root, "STEP_02_R14")
    products = {
        product: verify_r14_product_pass(root, product) for product in PRODUCTS
    }
    return _write_record(
        root,
        destination=R14_STEP03_RECORD_PATH,
        schema_version=R14_STEP03_PASS_SCHEMA_VERSION,
        record_id="STEP_03_R14",
        run_id=run_id,
        artifacts=artifacts,
        gate_evidence=gate_evidence,
        predecessor_hashes={
            "STEP_01_R14": step01["record_sha256"],
            "STEP_02_R14": step02["record_sha256"],
            "STEP_03_R14_WRFSFCF": products["wrfsfcf"]["record_sha256"],
            "STEP_03_R14_WRFSUBHF": products["wrfsubhf"]["record_sha256"],
        },
    )


def verify_r14_step03_pass(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = _verify_record(
        root,
        destination=R14_STEP03_RECORD_PATH,
        schema_version=R14_STEP03_PASS_SCHEMA_VERSION,
        record_id="STEP_03_R14",
        product=None,
    )
    step01 = verify_r14_attestation(root, "STEP_01_R14")
    step02 = verify_r14_attestation(root, "STEP_02_R14")
    products = {
        product: verify_r14_product_pass(root, product) for product in PRODUCTS
    }
    expected = {
        "STEP_01_R14": step01["record_sha256"],
        "STEP_02_R14": step02["record_sha256"],
        "STEP_03_R14_WRFSFCF": products["wrfsfcf"]["record_sha256"],
        "STEP_03_R14_WRFSUBHF": products["wrfsubhf"]["record_sha256"],
    }
    if record["predecessor_hashes"] != expected:
        raise R14PlanRecordError("R14 aggregate Step 03 predecessor lineage changed")
    return record
