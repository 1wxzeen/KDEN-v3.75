"""R14 Step 03: build, project, and seal both independent product plans."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from ..contracts import PauseController, load_project_paths
from ..io.atomic import atomic_write_json
from ..r14_plan_records import (
    R14_PRODUCT_RECORD_PATHS,
    R14_STEP03_PASS_SCHEMA_PATH,
    R14_STEP03_RECORD_PATH,
    verify_r14_product_pass,
    verify_r14_step03_pass,
    write_r14_product_pass,
    write_r14_step03_pass,
)
from ..r14_records import R14_RECORD_PATHS, verify_r14_attestation
from ..r14_request_plans import (
    PRODUCTS,
    R14_FH00_EVIDENCE_PATH,
    R14_PLAN_DIRECTORY,
    R14_PLAN_MANIFEST,
    R14_PLAN_POLICY_PATH,
    R14_PROJECTION_REPORT_PATH,
    R14_REQUEST_SCHEMA_PATH,
    build_r14_product_plan,
    verify_r14_product_plan,
)


def _write_projection_report(
    project_root: Path,
    projections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    by_product = {product: projections[product]["by_product"] for product in PRODUCTS}
    body = {
        "schema_version": "KDEN_V375_STEP03_R14_COST_DISK_PROJECTION_V1",
        "scope_id": "KDEN_V375_R14_V1",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "PRE_R14_PILOT_DRY_RUN",
        "warning": (
            "Sizing assumptions are planning estimates; the bounded R14 pilot "
            "supersedes them before full-history acquisition."
        ),
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
        "by_spatial_shape": {
            product: projections[product]["by_spatial_shape"] for product in PRODUCTS
        },
        "combined": {
            key: sum(int(by_product[product][key]) for product in PRODUCTS)
            for key in by_product[PRODUCTS[0]]
        },
        "h14_full_grid_persisted": False,
        "regional_supports_included": True,
    }
    atomic_write_json(project_root / R14_PROJECTION_REPORT_PATH, body, replace=True)
    return body


def _product_artifacts(product: str) -> tuple[str, ...]:
    return (
        R14_PLAN_DIRECTORY[product],
        R14_PLAN_MANIFEST[product],
        R14_PLAN_POLICY_PATH,
        R14_FH00_EVIDENCE_PATH,
        R14_REQUEST_SCHEMA_PATH,
        R14_STEP03_PASS_SCHEMA_PATH,
        "src/kden_v375/r14_request_plans.py",
        "src/kden_v375/r14_plan_records.py",
        "src/kden_v375/steps/step_03_r14_request_plans.py",
    )


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    if (paths.root / R14_STEP03_RECORD_PATH).exists():
        return verify_r14_step03_pass(paths.root)
    verify_r14_attestation(paths.root, "STEP_01_R14")
    verify_r14_attestation(paths.root, "STEP_02_R14")
    projections: dict[str, Mapping[str, Any]] = {}
    records: dict[str, dict[str, Any]] = {}
    for product in PRODUCTS:
        if pause is not None:
            pause.raise_if_requested()
        product_record_path = paths.root / R14_PRODUCT_RECORD_PATHS[product]
        if product_record_path.exists():
            record = verify_r14_product_pass(paths.root, product)
            plan = verify_r14_product_plan(paths.root, product)
            manifest_path = paths.root / R14_PLAN_MANIFEST[product]
            with manifest_path.open("r", encoding="utf-8") as stream:
                manifest = json.load(stream)
            projections[product] = manifest["projection"]
        else:
            built = build_r14_product_plan(
                paths.root,
                product,
                run_id=run_id,
                pause=pause,
            )
            plan = built["gate_evidence"]
            projections[product] = built["projection"]
            record = write_r14_product_pass(
                paths.root,
                product=product,
                run_id=run_id,
                artifacts=_product_artifacts(product),
                gate_evidence=plan,
            )
        records[product] = record

    report = _write_projection_report(paths.root, projections)
    if pause is not None:
        pause.raise_if_requested()
    gates = {
        "scope_id": "KDEN_V375_R14_V1",
        "products": {
            product: records[product]["gate_evidence"] for product in PRODUCTS
        },
        "independent_product_pass_record_sha256": {
            product: records[product]["record_sha256"] for product in PRODUCTS
        },
        "combined_request_row_count": sum(
            int(records[product]["gate_evidence"]["request_row_count"])
            for product in PRODUCTS
        ),
        "expected_combined_request_row_count": 8_919_598,
        "all_valid_times_strictly_before_window_end": all(
            records[product]["gate_evidence"][
                "all_valid_times_strictly_before_window_end"
            ]
            for product in PRODUCTS
        ),
        "fh48_only_tail_absent": all(
            records[product]["gate_evidence"]["fh48_only_tail_absent"]
            for product in PRODUCTS
        ),
        "H16_network_request_count": records["wrfsfcf"]["gate_evidence"][
            "normal_network_sentinel_count"
        ],
        "Q05_network_request_count": records["wrfsubhf"]["gate_evidence"][
            "normal_network_sentinel_count"
        ],
        "H14_planned_once_per_grid_version": records["wrfsfcf"][
            "gate_evidence"
        ]["h14_once_per_grid_version"],
        "H14_full_grid_persisted": False,
        "forbidden_dependency_columns": [],
        "sealed_before_network_execution": True,
        "projection_status": report["status"],
    }
    if gates["combined_request_row_count"] != gates[
        "expected_combined_request_row_count"
    ]:
        raise RuntimeError("R14 combined Step 03 request count changed")
    aggregate_artifacts = (
        R14_PLAN_POLICY_PATH,
        R14_REQUEST_SCHEMA_PATH,
        R14_STEP03_PASS_SCHEMA_PATH,
        R14_PROJECTION_REPORT_PATH,
        R14_RECORD_PATHS["STEP_01_R14"],
        R14_RECORD_PATHS["STEP_02_R14"],
        "src/kden_v375/r14_request_plans.py",
        "src/kden_v375/r14_plan_records.py",
        "src/kden_v375/steps/step_03_r14_request_plans.py",
        *tuple(R14_PLAN_DIRECTORY[product] for product in PRODUCTS),
        *tuple(R14_PLAN_MANIFEST[product] for product in PRODUCTS),
        *tuple(R14_PRODUCT_RECORD_PATHS[product] for product in PRODUCTS),
    )
    return write_r14_step03_pass(
        paths.root,
        run_id=run_id,
        artifacts=aggregate_artifacts,
        gate_evidence=gates,
    )


def verify_pass(project_root: Path | str) -> dict[str, Any]:
    """CLI hook for R14-aware resume and validate-only behavior."""

    return verify_r14_step03_pass(project_root)
