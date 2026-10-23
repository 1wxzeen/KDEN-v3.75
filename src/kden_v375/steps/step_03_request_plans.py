"""Step 03: build, project, and seal independent product request plans."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from ..contracts import (
    PASS_SCHEMA_VERSION,
    PauseController,
    load_project_paths,
    predecessor_hashes,
    utc_now,
    validate_run_id,
    write_step_pass,
)
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_path
from ..io.atomic import atomic_write_json
from ..request_plans import (
    FH00_EVIDENCE_PATH,
    PLAN_DIRECTORY,
    PLAN_MANIFEST,
    PLAN_POLICY_PATH,
    PRODUCTS,
    PROJECTION_REPORT_PATH,
    build_product_plan,
    verify_product_plan,
)


PRODUCT_PASS_SCHEMA_VERSION = "KDEN_V375_PRODUCT_PLAN_PASS_V1"


def _write_product_pass(
    project_root: Path | str,
    *,
    product: str,
    run_id: str,
    artifacts: tuple[str, ...],
    gate_evidence: Mapping[str, Any],
    predecessors: Mapping[str, str],
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    validate_run_id(run_id, step_no=3)
    artifact_hashes = {
        relative: sha256_path(paths.root / relative) for relative in sorted(artifacts)
    }
    body = {
        "schema_version": PRODUCT_PASS_SCHEMA_VERSION,
        "step_id": "STEP_03",
        "product": product,
        "status": "PASS",
        "completed_at_utc": utc_now(),
        "run_id": run_id,
        "predecessor_hashes": dict(sorted(predecessors.items())),
        "artifact_hashes": artifact_hashes,
        "gate_evidence": dict(gate_evidence),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(paths.state / f"STEP_03_{product.upper()}_PASS.json", record)
    return record


def _write_projection_report(
    project_root: Path | str,
    projections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    by_product = {
        product: projections[product]["by_product"] for product in PRODUCTS
    }
    body = {
        "schema_version": "KDEN_V375_STEP03_COST_DISK_PROJECTION_V1",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "PRE_PILOT_DRY_RUN",
        "warning": "Sizing assumptions are planning estimates; Step 04 measured pilot values supersede them before full-history acquisition.",
        "products": {
            product: {
                "unique_source_objects": projections[product]["unique_source_objects"],
                **projections[product]["by_product"],
            }
            for product in PRODUCTS
        },
        "by_field": {
            product: projections[product]["by_field"] for product in PRODUCTS
        },
        "by_year": {
            product: projections[product]["by_year"] for product in PRODUCTS
        },
        "by_tile_size": {
            product: projections[product]["by_tile_size"] for product in PRODUCTS
        },
        "combined": {
            key: sum(int(by_product[product][key]) for product in PRODUCTS)
            for key in by_product[PRODUCTS[0]]
        },
    }
    atomic_write_json(paths.root / PROJECTION_REPORT_PATH, body)
    return body


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    predecessors = predecessor_hashes(project_root, 3)
    projections: dict[str, Mapping[str, Any]] = {}
    product_records: dict[str, dict[str, Any]] = {}
    for product in PRODUCTS:
        if pause is not None:
            pause.raise_if_requested()
        built = build_product_plan(
            project_root,
            product,
            step02_record_sha256=predecessors["STEP_02"],
            pause=pause,
        )
        verified = verify_product_plan(project_root, product)
        if built["manifest"]["plan_sha256"] != verified["plan_sha256"]:
            raise RuntimeError(f"{product} plan changed between sealing and verification")
        projections[product] = built["projection"]
        artifacts = (
            PLAN_DIRECTORY[product],
            PLAN_MANIFEST[product],
            PLAN_POLICY_PATH,
            FH00_EVIDENCE_PATH,
            "schemas/request_plan_v375.json",
            "src/kden_v375/request_plans.py",
            "src/kden_v375/steps/step_03_request_plans.py",
        )
        product_records[product] = _write_product_pass(
            project_root,
            product=product,
            run_id=run_id,
            artifacts=artifacts,
            gate_evidence=verified,
            predecessors=predecessors,
        )

    projection = _write_projection_report(project_root, projections)
    if pause is not None:
        pause.raise_if_requested()
    paths = load_project_paths(project_root)
    product_pass_paths = tuple(
        f"state/STEP_03_{product.upper()}_PASS.json" for product in PRODUCTS
    )
    aggregate_gates = {
        "products": {
            product: {
                "plan_sha256": product_records[product]["gate_evidence"]["plan_sha256"],
                "request_row_count": product_records[product]["gate_evidence"]["request_row_count"],
                "native_valid_state_count": product_records[product]["gate_evidence"]["native_valid_state_count"],
                "unique_source_object_count": product_records[product]["gate_evidence"]["unique_source_object_count"],
                "independently_loadable": True,
            }
            for product in PRODUCTS
        },
        "independent_product_pass_record_sha256": {
            product: product_records[product]["record_sha256"] for product in PRODUCTS
        },
        "target_window_cap_verified": all(
            product_records[product]["gate_evidence"]["target_window_cap_verified"]
            for product in PRODUCTS
        ),
        "fh48_only_tail_absent": all(
            product_records[product]["gate_evidence"]["fh48_only_tail_absent"]
            for product in PRODUCTS
        ),
        "H16_network_request_count": product_records["wrfsfcf"]["gate_evidence"][
            "normal_network_sentinel_count"
        ],
        "Q05_network_request_count": product_records["wrfsubhf"]["gate_evidence"][
            "normal_network_sentinel_count"
        ],
        "H14_planned_once_per_grid_version": product_records["wrfsfcf"][
            "gate_evidence"
        ]["h14_once_per_grid_version"],
        "forbidden_dependency_columns": [],
        "sealed_before_network_execution": True,
        "projection_status": projection["status"],
    }
    artifacts = (
        PLAN_POLICY_PATH,
        FH00_EVIDENCE_PATH,
        PROJECTION_REPORT_PATH,
        "src/kden_v375/request_plans.py",
        "src/kden_v375/steps/step_03_request_plans.py",
        *tuple(PLAN_DIRECTORY[product] for product in PRODUCTS),
        *tuple(PLAN_MANIFEST[product] for product in PRODUCTS),
        *product_pass_paths,
    )
    return write_step_pass(
        paths.root,
        step_no=3,
        run_id=run_id,
        artifact_paths=artifacts,
        gate_evidence=aggregate_gates,
        predecessor_hashes=predecessors,
    )
