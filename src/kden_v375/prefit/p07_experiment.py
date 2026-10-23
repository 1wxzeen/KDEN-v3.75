"""P07: freeze folds, target-free model adapters, and the RAFM experiment."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..contracts import (
    ContractError,
    ExclusiveRunLock,
    PauseController,
    PauseRequested,
    StaleStateError,
    load_project_paths,
    resolve_project_root,
    validate_runtime_isolation,
)
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from ..io.atomic import atomic_write_json, fsync_directory
from .p06_acceptance import verify_p06
from .records import (
    PREFIT_PASS_SCHEMA_VERSION,
    make_prefit_run_id,
    publish_immutable_json,
    utc_now,
    validate_prefit_run_id,
    verify_prefit_pass,
    write_prefit_pass,
)


STAGE_NO = 7
CONFIG_PATH = "config/prefit/p07_rafm_experiment_v375.json"
RUN_STATE_SCHEMA_PATH = "schemas/prefit/p07_run_state_v375.json"
CONTRACT_SCHEMA_PATH = "schemas/prefit/p07_experiment_contract_v375.json"
FOLD_SCHEMA_PATH = "schemas/prefit/p07_fold_registry_v375.json"
ADAPTER_SCHEMA_PATH = "schemas/prefit/p07_model_adapter_v375.json"
FREEZE_SCHEMA_PATH = "schemas/prefit/p07_experiment_freeze_v375.json"
BOUNDARY_SCHEMA_PATH = "schemas/prefit/p07_modeling_boundary_pass_v375.json"
RUNBOOK_PATH = "reports/prefit/P07_OWNER_RUNBOOK.md"
DECISIONS_PATH = "reports/prefit/P07_SCIENTIFIC_DECISIONS.md"
CONTAMINATION_REPORT_PATH = "reports/prefit/P07_CONTAMINATION_HOLDOUT_REPORT.md"
TRUTH_CATALOG_PATH = "truth/kden_tmax/v1/catalog/kden_truth_catalog.parquet"
ISSUE_SPINE_PATH = "universal_issue_state/v1/issue_spine/issue_spine.parquet"
FEATURE_REGISTRY_PATH = (
    "universal_issue_state/v1/registries/universal_feature_registry_v1.json"
)
P05_MANIFEST_PATH = "universal_issue_state/v1/manifests/p05_release_manifest.json"
P06_FREEZE_PATH = "universal_issue_state/v1/manifests/p06_substrate_freeze_manifest.json"
P06_FINAL_PASS_PATH = "state/KDEN_V375_UNIVERSAL_ISSUE_STATE_PASS.json"

FOLD_ROOT = "folds/kden_v375/v1"
DATE_ROLES_PATH = f"{FOLD_ROOT}/date_roles.parquet"
OUTER_FOLDS_PATH = f"{FOLD_ROOT}/outer_folds.parquet"
INNER_FOLDS_PATH = f"{FOLD_ROOT}/inner_folds.parquet"
FOLD_MANIFEST_PATH = f"{FOLD_ROOT}/fold_manifest.json"
EXPERIMENT_ROOT = "modeling/experiments/rafm_v1"
ADAPTER_INDEX_PATH = f"{EXPERIMENT_ROOT}/adapters/issue_model_index.parquet"
ADAPTER_REGISTRY_PATH = f"{EXPERIMENT_ROOT}/adapters/adapter_registry.json"
FREEZE_PATH = f"{EXPERIMENT_ROOT}/manifests/p07_experiment_freeze.json"
BOUNDARY_PASS_PATH = "state/KDEN_V375_MODELING_BOUNDARY_PASS.json"
PASS_PATH = "state/PREFIT_P07_PASS.json"

CONFIG_SCHEMA = "KDEN_V375_PREFIT_P07_CONFIG_V1"
CONTRACT_ID = "KDEN_V375_RAFM_EXPERIMENT_V1"
RUN_STATE_SCHEMA = "KDEN_V375_PREFIT_P07_RUN_V1"
CHECKPOINT_SCHEMA = "KDEN_V375_PREFIT_P07_CHECKPOINT_V1"
JOURNAL_SCHEMA = "KDEN_V375_PREFIT_P07_COMPLETION_V1"
FOLD_MANIFEST_SCHEMA = "KDEN_V375_P07_FOLD_MANIFEST_V1"
ADAPTER_REGISTRY_SCHEMA = "KDEN_V375_P07_ADAPTER_REGISTRY_V1"
FREEZE_SCHEMA = "KDEN_V375_P07_EXPERIMENT_FREEZE_V1"
BOUNDARY_PASS_SCHEMA = "KDEN_V375_MODELING_BOUNDARY_PASS_V1"
SUBSTRATE_RELEASE_ID = "KDEN_V375_UNIVERSAL_ISSUE_STATE_V1"
EXPERIMENT_RELEASE_ID = "KDEN_V375_RAFM_EXPERIMENT_V1"
EXPECTED_P02_RECORD = "40ff18bbac4c927ae600fd54026671493f4e68e5e0d65cdf07374965837cf607"
EXPECTED_P06_RECORD = "9f420b8625b428a8663d190a332a0958bf72e5565c37c4543f5b78808a7f4b72"
EXPECTED_P06_FINAL = "45d226fe8e23fc4291bda55cac6736806f5a77b3308970eaa77d4b7a909f6dd5"
EXPECTED_P06_FREEZE = "9043b5dcb69ccfb143217ab657022f85f1750a1460e4011269526ebb08b52af6"
EXPECTED_TRUTH_HASH = "762c5778aceeff517ce2f5b2eb2ef2f3890808de3744efa5ef7e6b669d500773"
EXPECTED_ISSUE_HASH = "c23c7276d9dea07511d58794b444c278d550bf87c74c9b6126ef91d431287b29"
EXPECTED_FEATURE_REGISTRY_HASH = "e41d78a122be15a01986f0b914518209843108062313d7d55f62e308d37aaf65"
EXPECTED_TARGET_DAYS = 2_080
EXPECTED_ISSUE_ROWS = 118_536
UNITS = ("authorities", "folds", "adapters")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ContractError(f"JSON object expected: {path}")
    return value


def _inside(root: Path, relative: str | Path) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ContractError(f"P07 path escapes the project root: {relative}") from exc
    return path


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _record_hash(value: Mapping[str, Any], *, label: str) -> None:
    body = dict(value)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise StaleStateError(f"{label} record hash changed")


def _prefit_identity(root: Path, stage_no: int) -> dict[str, Any]:
    path = root / "state" / f"PREFIT_P{stage_no:02d}_PASS.json"
    value = _read_json(path)
    if (
        value.get("schema_version") != PREFIT_PASS_SCHEMA_VERSION
        or value.get("stage_id") != f"PREFIT_P{stage_no:02d}"
        or value.get("status") != "PASS"
    ):
        raise StaleStateError(f"P{stage_no:02d} PASS identity changed")
    validate_prefit_run_id(str(value.get("run_id", "")), stage_no=stage_no)
    _record_hash(value, label=f"P{stage_no:02d} PASS")
    return value


def _p06_identity(root: Path) -> dict[str, Any]:
    record = _prefit_identity(root, 6)
    final = _read_json(root / P06_FINAL_PASS_PATH)
    freeze = _read_json(root / P06_FREEZE_PATH)
    _record_hash(final, label="P06 final PASS")
    _record_hash(freeze, label="P06 freeze")
    if (
        record.get("record_sha256") != EXPECTED_P06_RECORD
        or final.get("record_sha256") != EXPECTED_P06_FINAL
        or freeze.get("record_sha256") != EXPECTED_P06_FREEZE
        or final.get("release_id") != SUBSTRATE_RELEASE_ID
        or freeze.get("status") != "FROZEN_ACCEPTED"
    ):
        raise StaleStateError("P07 requires the accepted P06 substrate release")
    return record


def _load_config(root: Path) -> tuple[dict[str, Any], str]:
    path = root / CONFIG_PATH
    config = _read_json(path)
    if (
        config.get("schema_version") != CONFIG_SCHEMA
        or config.get("contract_id") != CONTRACT_ID
        or config.get("substrate_release_id") != SUBSTRATE_RELEASE_ID
        or config.get("predecessor_p06_record_sha256") != EXPECTED_P06_RECORD
    ):
        raise ContractError("P07 experiment contract identity changed")
    execution = config.get("execution", {})
    if execution != {
        "network_allowed": False,
        "model_fitting_allowed": False,
        "sealed_holdout_values_allowed": False,
        "market_reads_allowed": False,
        "madis_predictors_allowed": False,
        "legacy_runtime_dependencies_allowed": False,
        "owner_approval_hash_required": True,
        "owner_run_required": True,
        "pause_boundary": "between the authority, fold, adapter, and publication units",
    }:
        raise ContractError("P07 execution policy changed")
    if len(config.get("folds", {}).get("outer", [])) != 3:
        raise ContractError("P07 must declare exactly three rolling outer folds")
    if len(config.get("experts", [])) != 6:
        raise ContractError("P07 must declare the generalist and five specialists")
    if config.get("pmf", {}).get("support_min_f") != -40 or config.get("pmf", {}).get(
        "support_max_f"
    ) != 120:
        raise ContractError("P07 PMF support identity changed")
    for fold in config["folds"]["outer"]:
        train_start = date.fromisoformat(fold["train_start"])
        train_end = date.fromisoformat(fold["train_end"])
        assess_start = date.fromisoformat(fold["assessment_start"])
        assess_end = date.fromisoformat(fold["assessment_end"])
        if not train_start <= train_end < assess_start <= assess_end:
            raise ContractError(f"P07 outer fold is not causal: {fold['outer_fold_id']}")
    digest = sha256_file(path)
    required_files = [
        RUN_STATE_SCHEMA_PATH,
        CONTRACT_SCHEMA_PATH,
        FOLD_SCHEMA_PATH,
        ADAPTER_SCHEMA_PATH,
        FREEZE_SCHEMA_PATH,
        BOUNDARY_SCHEMA_PATH,
        RUNBOOK_PATH,
        DECISIONS_PATH,
        "src/kden_v375/prefit/p07_experiment.py",
        "tests/unit/test_prefit_p07_experiment.py",
    ]
    for relative in required_files:
        if not (root / relative).is_file():
            raise ContractError(f"P07 implementation artifact is missing: {relative}")
    for relative in (
        RUN_STATE_SCHEMA_PATH,
        CONTRACT_SCHEMA_PATH,
        FOLD_SCHEMA_PATH,
        ADAPTER_SCHEMA_PATH,
        FREEZE_SCHEMA_PATH,
        BOUNDARY_SCHEMA_PATH,
    ):
        _read_json(root / relative)
    if digest not in (root / DECISIONS_PATH).read_text(encoding="utf-8"):
        raise StaleStateError("P07 decision document does not name the current contract hash")
    return config, digest


def _validate_features(root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    path = root / FEATURE_REGISTRY_PATH
    if sha256_file(path) != EXPECTED_FEATURE_REGISTRY_HASH:
        raise StaleStateError("P07 feature registry changed")
    registry = _read_json(path)
    names = {str(row["name"]) for row in registry.get("features", [])}
    required: set[str] = {
        str(row["center_feature"]) for row in config["baselines"].values()
    }
    for expert in config["experts"]:
        features = [str(item) for item in expert["distance_features"]]
        if not 3 <= len(features) <= 8 or len(features) != len(set(features)):
            raise ContractError(
                f"P07 expert must declare 3--8 unique distance features: {expert['expert_id']}"
            )
        required.update(features)
        eligibility = expert["eligibility"]
        required.update(str(item) for item in eligibility.get("features", []))
        required.update(str(item["feature"]) for item in eligibility.get("conditions", []))
    for item in config["mixtures"]["adaptive_gate"]["state_inputs"]:
        if str(item) in names:
            required.add(str(item))
    missing = sorted(required - names)
    if missing:
        raise ContractError(f"P07 contract names unknown frozen features: {missing}")
    return {"feature_count": len(names), "required_feature_count": len(required)}


def _metadata(schema_id: str) -> dict[bytes, bytes]:
    return {
        b"schema_version": b"KDEN_V375_PARQUET_SCHEMA_V1",
        b"schema_id": schema_id.encode("ascii"),
    }


def date_roles_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("target_date", pa.date32(), nullable=False),
            pa.field("statistical_group_id", pa.string(), nullable=False),
            pa.field("evidence_role", pa.string(), nullable=False),
            pa.field("supervised_eligible", pa.bool_(), nullable=False),
            pa.field("final_scoring_eligible", pa.bool_(), nullable=False),
            pa.field("truth_evidence_status", pa.string(), nullable=False),
            pa.field("truth_qc_status", pa.string()),
            pa.field("source_followup_window_open_at_freeze", pa.bool_()),
            pa.field("season", pa.string(), nullable=False),
            pa.field("sealed_outcome_unopened", pa.bool_(), nullable=False),
        ],
        metadata=_metadata("KDEN_V375_P07_DATE_ROLES_V1"),
    )


def outer_folds_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("outer_fold_id", pa.string(), nullable=False),
            pa.field("target_date", pa.date32(), nullable=False),
            pa.field("statistical_group_id", pa.string(), nullable=False),
            pa.field("assignment", pa.string(), nullable=False),
            pa.field("supervised_assignment", pa.bool_(), nullable=False),
            pa.field("season", pa.string(), nullable=False),
        ],
        metadata=_metadata("KDEN_V375_P07_OUTER_FOLDS_V1"),
    )


def inner_folds_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("outer_fold_id", pa.string(), nullable=False),
            pa.field("inner_fold_id", pa.string(), nullable=False),
            pa.field("target_date", pa.date32(), nullable=False),
            pa.field("statistical_group_id", pa.string(), nullable=False),
            pa.field("assignment", pa.string(), nullable=False),
            pa.field("supervised_assignment", pa.bool_(), nullable=False),
            pa.field("season", pa.string(), nullable=False),
        ],
        metadata=_metadata("KDEN_V375_P07_INNER_FOLDS_V1"),
    )


def adapter_index_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("issue_state_id", pa.string(), nullable=False),
            pa.field("target_date", pa.date32(), nullable=False),
            pa.field("statistical_group_id", pa.string(), nullable=False),
            pa.field("issue_time_utc", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field(
                "issue_time_local",
                pa.timestamp("us", tz="America/Denver"),
                nullable=False,
            ),
            pa.field("local_minutes_since_0200", pa.int16(), nullable=False),
            pa.field("exact_time_key", pa.string(), nullable=False),
            pa.field("issue_ordinal_in_target_day", pa.int8(), nullable=False),
            pa.field("issue_count_for_target_day", pa.int8(), nullable=False),
            pa.field("target_year", pa.int16(), nullable=False),
            pa.field("feature_partition_path", pa.string(), nullable=False),
            pa.field("feature_row_ordinal", pa.int32(), nullable=False),
            pa.field("feature_registry_id", pa.string(), nullable=False),
            pa.field("adapter_registry_id", pa.string(), nullable=False),
        ],
        metadata=_metadata("KDEN_V375_P07_ISSUE_MODEL_INDEX_V1"),
    )


def _season(target: date) -> str:
    if target.month in {12, 1, 2}:
        return "winter"
    if target.month in {3, 4, 5}:
        return "spring"
    if target.month in {6, 7, 8}:
        return "summer"
    return "autumn"


def _write_parquet(path: Path, rows: list[dict[str, Any]], schema: pa.Schema) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _publish_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise StaleStateError(f"immutable P07 artifact differs: {path}")
        return sha256_file(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _truth_metadata(root: Path) -> list[dict[str, Any]]:
    path = root / TRUTH_CATALOG_PATH
    if sha256_file(path) != EXPECTED_TRUTH_HASH:
        raise StaleStateError("P07 truth catalog changed")
    parquet = pq.ParquetFile(path)
    if parquet.metadata.num_rows != EXPECTED_TARGET_DAYS:
        raise ContractError("P07 truth catalog target-day count changed")
    columns = [
        "target_date",
        "truth_group",
        "truth_evidence_status",
        "label_available_for_supervised_use",
        "label_available_for_final_scoring",
        "truth_qc_status",
        "source_followup_window_open_at_freeze",
    ]
    rows = parquet.read(columns=columns).to_pylist()
    dates = [row["target_date"] for row in rows]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise ContractError("P07 truth catalog date key is not unique and ordered")
    if dates[0] != date(2021, 1, 1) or dates[-1] != date(2026, 9, 11):
        raise ContractError("P07 truth catalog coverage changed")
    return rows


def _role(row: Mapping[str, Any]) -> str:
    group = str(row["truth_group"])
    if group == "development":
        return (
            "DEVELOPMENT_SUPERVISED"
            if row["label_available_for_supervised_use"] is True
            else "DEVELOPMENT_UNRESOLVED"
        )
    if group == "sealed_final_holdout":
        return "SEALED_HOLDOUT"
    if group == "post_holdout_tail":
        return "POST_HOLDOUT_TAIL"
    raise ContractError(f"P07 encountered an unknown truth group: {group}")


def _date_role_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        target = row["target_date"]
        role = _role(row)
        result.append(
            {
                "target_date": target,
                "statistical_group_id": f"KDEN_DAY_{target.isoformat()}",
                "evidence_role": role,
                "supervised_eligible": bool(row["label_available_for_supervised_use"]),
                "final_scoring_eligible": bool(row["label_available_for_final_scoring"]),
                "truth_evidence_status": str(row["truth_evidence_status"]),
                "truth_qc_status": row["truth_qc_status"],
                "source_followup_window_open_at_freeze": row[
                    "source_followup_window_open_at_freeze"
                ],
                "season": _season(target),
                "sealed_outcome_unopened": role == "SEALED_HOLDOUT",
            }
        )
    counts = Counter(row["evidence_role"] for row in result)
    if counts != {
        "DEVELOPMENT_SUPERVISED": 1707,
        "DEVELOPMENT_UNRESOLVED": 3,
        "SEALED_HOLDOUT": 365,
        "POST_HOLDOUT_TAIL": 5,
    }:
        raise ContractError(f"P07 evidence-role counts changed: {dict(counts)}")
    return result


def _assignment(
    role: Mapping[str, Any],
    *,
    train_start: date,
    train_end: date,
    assessment_start: date,
    assessment_end: date,
) -> str:
    if role["evidence_role"] in {"SEALED_HOLDOUT", "POST_HOLDOUT_TAIL"}:
        return "FINAL_EVALUATION_LOCKED"
    if not role["supervised_eligible"]:
        return "UNRESOLVED_EXCLUDED"
    target = role["target_date"]
    if train_start <= target <= train_end:
        return "TRAIN"
    if assessment_start <= target <= assessment_end:
        return "ASSESS"
    return "DEVELOPMENT_NOT_USED"


def _fold_rows(
    config: Mapping[str, Any], roles: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    outer_rows: list[dict[str, Any]] = []
    inner_rows: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {"outer": {}, "inner": {}}
    for outer in config["folds"]["outer"]:
        outer_id = str(outer["outer_fold_id"])
        bounds = {key: date.fromisoformat(outer[key]) for key in (
            "train_start", "train_end", "assessment_start", "assessment_end"
        )}
        for role in roles:
            assignment = _assignment(role, **bounds)
            outer_rows.append(
                {
                    "outer_fold_id": outer_id,
                    "target_date": role["target_date"],
                    "statistical_group_id": role["statistical_group_id"],
                    "assignment": assignment,
                    "supervised_assignment": assignment in {"TRAIN", "ASSESS"},
                    "season": role["season"],
                }
            )
        selected = [row for row in outer_rows if row["outer_fold_id"] == outer_id]
        coverage["outer"][outer_id] = _coverage(selected)
        for inner in config["folds"]["inner_assessment_blocks"]:
            if date.fromisoformat(inner["assessment_end"]) > bounds["train_end"]:
                continue
            inner_id = str(inner["inner_fold_id"])
            inner_bounds = {key: date.fromisoformat(inner[key]) for key in (
                "train_start", "train_end", "assessment_start", "assessment_end"
            )}
            if inner_bounds["assessment_end"] > bounds["train_end"]:
                raise ContractError("P07 inner fold escapes its outer training interval")
            for role in roles:
                assignment = _assignment(role, **inner_bounds)
                if assignment == "DEVELOPMENT_NOT_USED":
                    assignment = "OUTSIDE_INNER_FOLD"
                inner_rows.append(
                    {
                        "outer_fold_id": outer_id,
                        "inner_fold_id": inner_id,
                        "target_date": role["target_date"],
                        "statistical_group_id": role["statistical_group_id"],
                        "assignment": assignment,
                        "supervised_assignment": assignment in {"TRAIN", "ASSESS"},
                        "season": role["season"],
                    }
                )
            key = f"{outer_id}/{inner_id}"
            selected_inner = [
                row
                for row in inner_rows
                if row["outer_fold_id"] == outer_id and row["inner_fold_id"] == inner_id
            ]
            coverage["inner"][key] = _coverage(selected_inner)
    if len(outer_rows) != 6_240 or len(inner_rows) != 31_200:
        raise ContractError("P07 fold registry row counts changed")
    return outer_rows, inner_rows, coverage


def _coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    assignments = Counter(str(row["assignment"]) for row in rows)
    seasons: dict[str, dict[str, int]] = {}
    for assignment in ("TRAIN", "ASSESS"):
        seasons[assignment] = dict(
            sorted(
                Counter(
                    str(row["season"])
                    for row in rows
                    if row["assignment"] == assignment
                ).items()
            )
        )
    return {"assignments": dict(sorted(assignments.items())), "seasons": seasons}


def _build_folds(root: Path, config: Mapping[str, Any], config_hash: str) -> dict[str, Any]:
    truth_rows = _truth_metadata(root)
    roles = _date_role_rows(truth_rows)
    outer, inner, coverage = _fold_rows(config, roles)
    hashes = {
        DATE_ROLES_PATH: _write_parquet(root / DATE_ROLES_PATH, roles, date_roles_schema()),
        OUTER_FOLDS_PATH: _write_parquet(root / OUTER_FOLDS_PATH, outer, outer_folds_schema()),
        INNER_FOLDS_PATH: _write_parquet(root / INNER_FOLDS_PATH, inner, inner_folds_schema()),
    }
    manifest = {
        "schema_version": FOLD_MANIFEST_SCHEMA,
        "contract_id": CONTRACT_ID,
        "config_sha256": config_hash,
        "truth_catalog_sha256": EXPECTED_TRUTH_HASH,
        "group_key": "target_date",
        "all_issue_rows_for_day_share_assignment": True,
        "date_role_rows": len(roles),
        "outer_rows": len(outer),
        "inner_rows": len(inner),
        "outer_fold_count": 3,
        "nested_inner_fold_instances": 15,
        "coverage": coverage,
        "artifacts": {
            path: {"sha256": value} for path, value in sorted(hashes.items())
        },
        "target_values_materialized": False,
        "sealed_holdout_values_read": False,
    }
    atomic_write_json(root / FOLD_MANIFEST_PATH, manifest, replace=True)
    hashes[FOLD_MANIFEST_PATH] = sha256_file(root / FOLD_MANIFEST_PATH)
    return {"hashes": hashes, "manifest": manifest}


def _build_adapters(
    root: Path, config: Mapping[str, Any], config_hash: str
) -> dict[str, Any]:
    issue_path = root / ISSUE_SPINE_PATH
    if sha256_file(issue_path) != EXPECTED_ISSUE_HASH:
        raise StaleStateError("P07 issue spine changed")
    p05 = _read_json(root / P05_MANIFEST_PATH)
    partitions = {
        int(row["year"]): dict(row)
        for row in p05["deterministic_features"]["year_partitions"]
    }
    issue_columns = [
        "issue_state_id", "target_date", "statistical_group_id", "issue_time_utc",
        "issue_time_local", "local_minutes_since_0200", "issue_ordinal_in_target_day",
        "issue_count_for_target_day", "target_year",
    ]
    issues = pq.ParquetFile(issue_path).read(columns=issue_columns).to_pylist()
    if len(issues) != EXPECTED_ISSUE_ROWS:
        raise ContractError("P07 issue-spine row count changed")
    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in issues:
        by_year.setdefault(int(row["target_year"]), []).append(row)
    output: list[dict[str, Any]] = []
    partition_evidence: list[dict[str, Any]] = []
    for year in sorted(by_year):
        entry = partitions.get(year)
        if entry is None:
            raise ContractError(f"P07 feature partition missing for {year}")
        partition_path = str(entry["path"])
        path = root / partition_path
        if sha256_file(path) != str(entry["sha256"]):
            raise StaleStateError(f"P07 feature partition changed: {year}")
        feature_ids = pq.ParquetFile(path).read(columns=["issue_state_id"])[
            "issue_state_id"
        ].to_pylist()
        issue_ids = [row["issue_state_id"] for row in by_year[year]]
        if feature_ids != issue_ids:
            raise ContractError(f"P07 issue-to-feature order mismatch for {year}")
        for ordinal, row in enumerate(by_year[year]):
            minute = int(row["local_minutes_since_0200"])
            output.append(
                {
                    **row,
                    "exact_time_key": f"LOCAL_MINUTE_{minute:04d}",
                    "feature_partition_path": partition_path,
                    "feature_row_ordinal": ordinal,
                    "feature_registry_id": "KDEN_V375_UNIVERSAL_FEATURE_REGISTRY_V1",
                    "adapter_registry_id": "KDEN_V375_RAFM_ADAPTER_REGISTRY_V1",
                }
            )
        partition_evidence.append(
            {
                "target_year": year,
                "path": partition_path,
                "sha256": entry["sha256"],
                "rows": len(feature_ids),
            }
        )
    index_hash = _write_parquet(
        root / ADAPTER_INDEX_PATH, output, adapter_index_schema()
    )
    registry = {
        "schema_version": ADAPTER_REGISTRY_SCHEMA,
        "adapter_registry_id": "KDEN_V375_RAFM_ADAPTER_REGISTRY_V1",
        "contract_id": CONTRACT_ID,
        "config_sha256": config_hash,
        "substrate_release_id": SUBSTRATE_RELEASE_ID,
        "feature_registry_path": FEATURE_REGISTRY_PATH,
        "feature_registry_sha256": EXPECTED_FEATURE_REGISTRY_HASH,
        "issue_model_index": {
            "path": ADAPTER_INDEX_PATH,
            "sha256": index_hash,
            "rows": len(output),
        },
        "feature_partitions": partition_evidence,
        "baselines": config["baselines"],
        "experts": config["experts"],
        "neighboring_time_challenger": config["neighboring_time_challenger"],
        "truth_columns_present": False,
        "fold_columns_present": False,
        "market_columns_present": False,
        "model_fits_performed": 0,
    }
    atomic_write_json(root / ADAPTER_REGISTRY_PATH, registry, replace=True)
    return {
        "hashes": {
            ADAPTER_INDEX_PATH: index_hash,
            ADAPTER_REGISTRY_PATH: sha256_file(root / ADAPTER_REGISTRY_PATH),
        },
        "registry": registry,
    }


def _run_paths(root: Path, run_id: str) -> dict[str, Path]:
    base = _inside(root, Path("prefit_runs") / run_id / "p07")
    return {
        "base": base,
        "state": base / "run.json",
        "pause": base / "control/pause.requested.json",
        "checkpoints": base / "checkpoints",
        "journal": base / "progress/completions.jsonl",
    }


def _initialize_state(root: Path, run_id: str, contract_hash: str) -> dict[str, Any]:
    validate_prefit_run_id(run_id, stage_no=7, scope="owner-full")
    path = _run_paths(root, run_id)["state"]
    if path.exists():
        value = _read_json(path)
        if (
            value.get("schema_version") != RUN_STATE_SCHEMA
            or value.get("run_id") != run_id
            or value.get("approved_contract_sha256") != contract_hash
        ):
            raise StaleStateError("P07 run state identity changed")
        return value
    created = utc_now()
    value = {
        "schema_version": RUN_STATE_SCHEMA,
        "stage_id": "PREFIT_P07",
        "run_id": run_id,
        "approved_contract_sha256": contract_hash,
        "status": "INITIALIZED",
        "phase": "NOT_STARTED",
        "message": "initialized",
        "created_at_utc": created,
        "started_at_utc": None,
        "updated_at_utc": created,
        "completed_at_utc": None,
        "expected_units": len(UNITS),
        "completed_units": [],
        "current_unit": None,
        "record_sha256": None,
    }
    atomic_write_json(path, value, replace=False)
    return value


def _update_state(root: Path, run_id: str, **updates: Any) -> dict[str, Any]:
    path = _run_paths(root, run_id)["state"]
    state = _read_json(path)
    state.update(updates, updated_at_utc=utc_now())
    atomic_write_json(path, state, replace=True)
    return state


def _checkpoint_path(root: Path, run_id: str, unit_id: str) -> Path:
    return _run_paths(root, run_id)["checkpoints"] / f"{unit_id}.json"


def _checkpoint(root: Path, run_id: str, unit_id: str, contract_hash: str) -> dict[str, Any] | None:
    path = _checkpoint_path(root, run_id, unit_id)
    if not path.exists():
        return None
    value = _read_json(path)
    body = dict(value)
    supplied = body.pop("record_sha256", None)
    if (
        value.get("schema_version") != CHECKPOINT_SCHEMA
        or value.get("unit_id") != unit_id
        or value.get("contract_sha256") != contract_hash
        or supplied != sha256_bytes(canonical_json_bytes(body))
    ):
        raise StaleStateError(f"P07 checkpoint changed: {unit_id}")
    for relative, expected in value.get("output_hashes", {}).items():
        if sha256_path(root / relative) != expected:
            raise StaleStateError(f"P07 checkpoint output changed: {relative}")
    return value


def _publish_checkpoint(
    root: Path,
    run_id: str,
    unit_id: str,
    contract_hash: str,
    *,
    evidence: Mapping[str, Any],
    output_hashes: Mapping[str, str],
    elapsed_seconds: float,
) -> dict[str, Any]:
    body = {
        "schema_version": CHECKPOINT_SCHEMA,
        "unit_id": unit_id,
        "contract_sha256": contract_hash,
        "completed_at_utc": utc_now(),
        "elapsed_seconds": elapsed_seconds,
        "output_hashes": dict(sorted(output_hashes.items())),
        "evidence": dict(evidence),
    }
    value = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(_checkpoint_path(root, run_id, unit_id), value, replace=True)
    return value


def _journal(root: Path, run_id: str, checkpoint: Mapping[str, Any]) -> None:
    path = _run_paths(root, run_id)["journal"]
    existing: set[str] = set()
    if path.exists():
        with path.open("r", encoding="utf-8") as stream:
            existing = {str(json.loads(line)["unit_id"]) for line in stream if line.strip()}
    if checkpoint["unit_id"] in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": JOURNAL_SCHEMA,
        "unit_id": checkpoint["unit_id"],
        "elapsed_seconds": checkpoint["elapsed_seconds"],
        "committed_at_utc": utc_now(),
    }
    with path.open("ab") as stream:
        stream.write(canonical_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def _authority_scan(root: Path) -> dict[str, Any]:
    p06 = verify_p06(root)
    p02 = verify_prefit_pass(root, 2)
    if p06.get("record_sha256") != EXPECTED_P06_RECORD:
        raise StaleStateError("P07 P06 predecessor changed during deep verification")
    if p02.get("record_sha256") != EXPECTED_P02_RECORD:
        raise StaleStateError("P07 P02 truth authority changed")
    if sha256_file(root / TRUTH_CATALOG_PATH) != EXPECTED_TRUTH_HASH:
        raise StaleStateError("P07 truth catalog hash changed")
    isolation = validate_runtime_isolation(root)
    return {
        "p02_record_sha256": p02["record_sha256"],
        "p06_record_sha256": p06["record_sha256"],
        "p06_freeze_record_sha256": p06["freeze_record_sha256"],
        "truth_catalog_sha256": EXPECTED_TRUTH_HASH,
        "runtime_isolation": {
            key: value for key, value in isolation.items() if key != "source_files_scanned"
        },
        "network_requests_made": 0,
        "model_fits_performed": 0,
        "sealed_holdout_values_read": False,
    }


def _authority_checkpoint_hashes(root: Path) -> dict[str, str]:
    """Bind resume to every P06-frozen file and the complete P02 truth bundle."""

    freeze = _read_json(root / P06_FREEZE_PATH)
    p02 = _prefit_identity(root, 2)
    truth_hash = p02.get("artifact_hashes", {}).get("truth/kden_tmax/v1")
    if not isinstance(truth_hash, str) or len(truth_hash) != 64:
        raise StaleStateError("P07 cannot resolve the P02 truth-bundle authority hash")
    return {
        **{str(path): str(digest) for path, digest in freeze["frozen_files"].items()},
        "truth/kden_tmax/v1": truth_hash,
    }


def _contamination_report(config_hash: str, fold_manifest: Mapping[str, Any]) -> bytes:
    lines = [
        "# P07 Contamination and Holdout Report",
        "",
        "Status: **PASS CANDIDATE — HOLDOUT UNOPENED**  ",
        f"Experiment contract SHA-256: `{config_hash}`",
        "",
        "## Evidence separation",
        "",
        "- Development: 1,710 target days; 1,707 supervised and 3 unresolved.",
        "- Final sealed holdout: 365 target days, 2025-09-07 through 2026-09-06.",
        "- Post-holdout tail: 5 accepted dates, never available to fitting or tuning.",
        "- Fold and adapter artifacts contain no target values.",
        "- The adapter index contains no fold assignments, truth fields, or market fields.",
        "- All 57 ordinary issue states from a target day remain in the same statistical group.",
        "",
        "## Rolling-origin structure",
        "",
        f"- Outer fold count: {fold_manifest['outer_fold_count']}",
        f"- Nested inner fold instances: {fold_manifest['nested_inner_fold_instances']}",
        "- Training dates strictly precede assessment dates in every fold.",
        "- Seasonal coverage is recorded in `fold_manifest.json` for every training and assessment block.",
        "",
        "## Final-evaluation lock",
        "",
        "P07 does not open the one-year holdout, inspect its outcomes, fit a model, or score a",
        "forecast. Holdout opening is allowed only after model and evaluation code, predictions,",
        "and all hyperparameters are frozen under the approved experiment contract.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _freeze_inventory(root: Path) -> dict[str, str]:
    paths = [
        CONFIG_PATH,
        RUN_STATE_SCHEMA_PATH,
        CONTRACT_SCHEMA_PATH,
        FOLD_SCHEMA_PATH,
        ADAPTER_SCHEMA_PATH,
        FREEZE_SCHEMA_PATH,
        BOUNDARY_SCHEMA_PATH,
        RUNBOOK_PATH,
        DECISIONS_PATH,
        CONTAMINATION_REPORT_PATH,
        "src/kden_v375/prefit/p07_experiment.py",
        "tests/unit/test_prefit_p07_experiment.py",
        DATE_ROLES_PATH,
        OUTER_FOLDS_PATH,
        INNER_FOLDS_PATH,
        FOLD_MANIFEST_PATH,
        ADAPTER_INDEX_PATH,
        ADAPTER_REGISTRY_PATH,
    ]
    return {relative: sha256_path(root / relative) for relative in sorted(paths)}


def _publish_final(
    root: Path,
    run_id: str,
    config: Mapping[str, Any],
    config_hash: str,
    checkpoints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    fold_manifest = _read_json(root / FOLD_MANIFEST_PATH)
    _publish_bytes(
        root / CONTAMINATION_REPORT_PATH,
        _contamination_report(config_hash, fold_manifest),
    )
    frozen = _freeze_inventory(root)
    frozen_at = max(str(item["completed_at_utc"]) for item in checkpoints)
    freeze_body = {
        "schema_version": FREEZE_SCHEMA,
        "release_id": EXPERIMENT_RELEASE_ID,
        "status": "FROZEN_NO_MODEL_FITS",
        "frozen_at_utc": frozen_at,
        "approved_contract_sha256": config_hash,
        "predecessor_p06_record_sha256": EXPECTED_P06_RECORD,
        "predecessor_p06_freeze_record_sha256": EXPECTED_P06_FREEZE,
        "truth_catalog_sha256": EXPECTED_TRUTH_HASH,
        "feature_registry_sha256": EXPECTED_FEATURE_REGISTRY_HASH,
        "checkpoint_digest": sha256_path(_run_paths(root, run_id)["checkpoints"]),
        "frozen_files": frozen,
        "holdout_opened": False,
        "sealed_holdout_values_read": False,
        "model_fits_performed": 0,
        "network_requests_made": 0,
        "expert_count": len(config["experts"]),
        "completed_unit_count": len(checkpoints),
    }
    freeze = {
        **freeze_body,
        "record_sha256": sha256_bytes(canonical_json_bytes(freeze_body)),
    }
    publish_immutable_json(root / FREEZE_PATH, freeze)
    boundary_body = {
        "schema_version": BOUNDARY_PASS_SCHEMA,
        "release_id": EXPERIMENT_RELEASE_ID,
        "status": "PREFIT_COMPLETE_MODEL_FITTING_AUTHORIZED",
        "completed_at_utc": frozen_at,
        "p06_record_sha256": EXPECTED_P06_RECORD,
        "p07_contract_sha256": config_hash,
        "p07_freeze_manifest_sha256": sha256_file(root / FREEZE_PATH),
        "p07_freeze_record_sha256": freeze["record_sha256"],
        "target_day_count": EXPECTED_TARGET_DAYS,
        "issue_state_count": EXPECTED_ISSUE_ROWS,
        "development_supervised_target_days": 1707,
        "development_unresolved_target_days": 3,
        "sealed_holdout_target_days": 365,
        "post_holdout_tail_target_days": 5,
        "outer_fold_count": 3,
        "nested_inner_fold_instances": 15,
        "holdout_opened": False,
        "sealed_holdout_values_read": False,
        "model_fits_performed": 0,
        "network_requests_made": 0,
    }
    boundary = {
        **boundary_body,
        "record_sha256": sha256_bytes(canonical_json_bytes(boundary_body)),
    }
    publish_immutable_json(root / BOUNDARY_PASS_PATH, boundary)
    artifact_paths = [
        *_freeze_inventory(root).keys(),
        FREEZE_PATH,
        BOUNDARY_PASS_PATH,
        _relative(root, _run_paths(root, run_id)["checkpoints"]),
        _relative(root, _run_paths(root, run_id)["journal"]),
    ]
    isolation = validate_runtime_isolation(root)
    record = write_prefit_pass(
        root,
        stage_no=7,
        run_id=run_id,
        artifact_paths=artifact_paths,
        predecessor_hashes={"PREFIT_P06": EXPECTED_P06_RECORD},
        authority_hashes={
            "PREFIT_P02": EXPECTED_P02_RECORD,
            "P06_FREEZE": EXPECTED_P06_FREEZE,
            "P06_FINAL_PASS": EXPECTED_P06_FINAL,
            "P07_CONTRACT": config_hash,
            "P07_EXPERIMENT_FREEZE": freeze["record_sha256"],
            "P07_MODELING_BOUNDARY_PASS": boundary["record_sha256"],
            "TRUTH_CATALOG": EXPECTED_TRUTH_HASH,
            "FEATURE_REGISTRY": EXPECTED_FEATURE_REGISTRY_HASH,
        },
        gate_evidence={
            "experiment_release_id": EXPERIMENT_RELEASE_ID,
            "owner_contract_approval_verified": True,
            "target_day_grouped_outer_folds": 3,
            "nested_inner_fold_instances": 15,
            "seasonal_coverage_reported": True,
            "target_free_adapter_rows": EXPECTED_ISSUE_ROWS,
            "generalist_and_specialist_contracts_frozen": True,
            "nested_oof_gate_training_required": True,
            "exact_time_analog_default_frozen": True,
            "neighboring_time_is_separate_challenger": True,
            "holdout_opening_procedure_frozen": True,
            "four_way_final_report_frozen": True,
            "holdout_opened": False,
            "sealed_holdout_values_read": False,
            "truth_values_materialized_in_folds_or_adapters": False,
            "model_fits_performed": 0,
            "network_requests_made": 0,
            "runtime_isolation": {
                key: value
                for key, value in isolation.items()
                if key != "source_files_scanned"
            },
        },
    )
    return record


def p07_preflight(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    predecessor = _p06_identity(root)
    config, contract_hash = _load_config(root)
    features = _validate_features(root, config)
    if pq.ParquetFile(root / TRUTH_CATALOG_PATH).metadata.num_rows != EXPECTED_TARGET_DAYS:
        raise ContractError("P07 truth-catalog row count changed")
    if pq.ParquetFile(root / ISSUE_SPINE_PATH).metadata.num_rows != EXPECTED_ISSUE_ROWS:
        raise ContractError("P07 issue-spine row count changed")
    run_id = make_prefit_run_id(7, "owner-full", "rafm-experiment-freeze")
    prefix = ".venv/bin/python -m kden_v375.prefit.p07_experiment"
    return {
        "schema_version": "KDEN_V375_PREFIT_P07_PREFLIGHT_V1",
        "status": "AWAITING_EXPLICIT_CONTRACT_APPROVAL",
        "contract_id": CONTRACT_ID,
        "contract_path": CONFIG_PATH,
        "contract_sha256": contract_hash,
        "predecessor_p06_record_sha256": predecessor["record_sha256"],
        "feature_registry_sha256": EXPECTED_FEATURE_REGISTRY_HASH,
        "feature_count": features["feature_count"],
        "required_model_feature_count": features["required_feature_count"],
        "outer_fold_count": 3,
        "nested_inner_fold_instances": 15,
        "pmf_support_f": [-40, 120],
        "exact_time_default": True,
        "expert_count": 6,
        "holdout_opened": False,
        "sealed_holdout_values_read": False,
        "model_fits_performed": 0,
        "network_requests_made": 0,
        "decision_document": DECISIONS_PATH,
        "suggested_run_id": run_id,
        "start_command": f"{prefix} run --run-id {run_id} --approve-contract-sha256 {contract_hash}",
        "status_command": f"{prefix} status --run-id {run_id}",
        "live_status_command": f"{prefix} live-status --run-id {run_id} --interval-seconds 5",
        "eta_command": f"{prefix} eta --run-id {run_id}",
        "pause_command": f"{prefix} pause --run-id {run_id}",
        "resume_command": f"{prefix} resume --run-id {run_id} --approve-contract-sha256 {contract_hash}",
        "validation_command": f"{prefix} validate",
    }


def run_p07(
    *, project_root: Path | str, run_id: str, approved_contract_sha256: str, resume: bool = False
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if (root / PASS_PATH).exists():
        return verify_p07(root)
    _p06_identity(root)
    config, contract_hash = _load_config(root)
    _validate_features(root, config)
    if approved_contract_sha256 != contract_hash:
        raise ContractError(
            "P07 requires explicit approval of the exact preflight contract SHA-256"
        )
    state = _initialize_state(root, run_id, contract_hash)
    resumable = {"INITIALIZED", "FAILED", "PAUSED", "PAUSE_REQUESTED"}
    if resume and state["status"] not in resumable:
        raise ContractError(f"P07 run is not resumable from {state['status']}")
    if not resume and state["status"] not in {"INITIALIZED", "FAILED"}:
        raise ContractError(f"P07 run already exists in {state['status']}; use resume")
    paths = _run_paths(root, run_id)
    pause = PauseController(paths["pause"])
    if resume:
        pause.clear()
    with ExclusiveRunLock(load_project_paths(root).state / "PREFIT_P07.lock"):
        pause.install()
        _update_state(
            root,
            run_id,
            status="RUNNING",
            phase="P07_EXPERIMENT_FREEZE",
            message="resumed" if resume else "started",
            started_at_utc=state.get("started_at_utc") or utc_now(),
        )
        try:
            checkpoints: list[dict[str, Any]] = []
            for unit in UNITS:
                checkpoint = _checkpoint(root, run_id, unit, contract_hash)
                if checkpoint is None:
                    pause.raise_if_requested()
                    _update_state(root, run_id, current_unit=unit, message=f"running {unit}")
                    started = time.monotonic()
                    if unit == "authorities":
                        evidence = _authority_scan(root)
                        hashes = _authority_checkpoint_hashes(root)
                    elif unit == "folds":
                        value = _build_folds(root, config, contract_hash)
                        evidence = {
                            "date_role_rows": value["manifest"]["date_role_rows"],
                            "outer_rows": value["manifest"]["outer_rows"],
                            "inner_rows": value["manifest"]["inner_rows"],
                            "sealed_holdout_values_read": False,
                        }
                        hashes = value["hashes"]
                    else:
                        value = _build_adapters(root, config, contract_hash)
                        evidence = {
                            "adapter_rows": value["registry"]["issue_model_index"]["rows"],
                            "truth_columns_present": False,
                            "fold_columns_present": False,
                            "model_fits_performed": 0,
                        }
                        hashes = value["hashes"]
                    checkpoint = _publish_checkpoint(
                        root,
                        run_id,
                        unit,
                        contract_hash,
                        evidence=evidence,
                        output_hashes=hashes,
                        elapsed_seconds=time.monotonic() - started,
                    )
                checkpoints.append(checkpoint)
                _journal(root, run_id, checkpoint)
                _update_state(
                    root,
                    run_id,
                    completed_units=[item["unit_id"] for item in checkpoints],
                    current_unit=None,
                )
            pause.raise_if_requested()
            _update_state(
                root,
                run_id,
                phase="PUBLISHING_IMMUTABLE_EXPERIMENT",
                message="all checks complete; publishing P07 freeze",
            )
            record = _publish_final(root, run_id, config, contract_hash, checkpoints)
        except PauseRequested as exc:
            _update_state(
                root, run_id, status="PAUSED", message=str(exc), current_unit=None
            )
            return {"stage_id": "PREFIT_P07", "run_id": run_id, "status": "PAUSED"}
        except Exception as exc:
            _update_state(
                root,
                run_id,
                status="FAILED",
                message=f"{type(exc).__name__}: {exc}",
            )
            raise
        else:
            pause.clear()
            _update_state(
                root,
                run_id,
                status="PASS",
                phase="COMPLETE",
                message="P07 passed; the model-fitting boundary is frozen",
                completed_at_utc=utc_now(),
                completed_units=list(UNITS),
                current_unit=None,
                record_sha256=record["record_sha256"],
            )
            return record
        finally:
            pause.restore()


def _state(root: Path, run_id: str) -> dict[str, Any]:
    validate_prefit_run_id(run_id, stage_no=7)
    return _read_json(_run_paths(root, run_id)["state"])


def p07_status(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    value = _state(root, run_id)
    return {
        **value,
        "completed_unit_count": len(value.get("completed_units", [])),
        "fold_manifest_path": FOLD_MANIFEST_PATH,
        "adapter_registry_path": ADAPTER_REGISTRY_PATH,
        "freeze_manifest_path": FREEZE_PATH,
        "modeling_boundary_pass_path": BOUNDARY_PASS_PATH,
        "eta": _eta(root, run_id, value),
    }


def _eta(root: Path, run_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    if state["status"] == "PASS":
        return {"status": "COMPLETE", "remaining_seconds": 0}
    if state["status"] in {"FAILED", "PAUSED"}:
        return {"status": "UNAVAILABLE", "reason": f"run is {state['status']}"}
    elapsed: list[float] = []
    for unit in state.get("completed_units", []):
        path = _checkpoint_path(root, run_id, str(unit))
        if path.exists():
            elapsed.append(float(_read_json(path).get("elapsed_seconds", 0)))
    if not elapsed:
        return {"status": "UNAVAILABLE", "reason": "no completed P07 unit yet"}
    remaining = max(0, len(UNITS) - len(elapsed))
    return {
        "status": "AVAILABLE",
        "basis": "mean_completed_unit_wall_time",
        "remaining_units": remaining,
        "remaining_seconds": remaining * sum(elapsed) / len(elapsed),
    }


def p07_eta(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state = _state(root, run_id)
    return {
        "schema_version": "KDEN_V375_PREFIT_P07_ETA_V1",
        "run_id": run_id,
        "observed_at_utc": utc_now(),
        "run_status": state["status"],
        "eta": _eta(root, run_id, state),
    }


def p07_pause(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = _run_paths(root, run_id)
    state = _read_json(paths["state"])
    if state["status"] not in {"RUNNING", "PAUSE_REQUESTED"}:
        raise ContractError(f"P07 run is not active: {state['status']}")
    atomic_write_json(
        paths["pause"],
        {"schema_version": "KDEN_V375_PAUSE_REQUEST_V1", "requested_at_utc": utc_now()},
        replace=True,
    )
    return _update_state(
        root,
        run_id,
        status="PAUSE_REQUESTED",
        message="cooperative pause requested; P07 stops at the next unit boundary",
    )


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "unavailable"
    remaining = max(0, int(seconds))
    minutes, seconds = divmod(remaining, 60)
    return f"{minutes}m {seconds}s"


def p07_live_status(
    project_root: Path | str,
    run_id: str,
    *,
    interval_seconds: float = 5,
    json_lines: bool = False,
) -> None:
    if interval_seconds <= 0:
        raise ContractError("live-status interval must be positive")
    while True:
        snapshot = p07_status(project_root, run_id)
        if json_lines:
            print(json.dumps(snapshot, sort_keys=True), flush=True)
        else:
            eta = snapshot["eta"]
            eta_text = (
                "complete"
                if eta.get("status") == "COMPLETE"
                else _format_duration(eta.get("remaining_seconds"))
                if eta.get("status") == "AVAILABLE"
                else "unavailable"
            )
            print(
                f"[{utc_now()}] | {snapshot['status']} | phase={snapshot['phase']} | "
                f"units={snapshot['completed_unit_count']}/{snapshot['expected_units']} | "
                f"current={snapshot.get('current_unit') or '-'} | ETA={eta_text}",
                flush=True,
            )
        if snapshot["status"] in {"PASS", "FAILED", "PAUSED"}:
            return
        time.sleep(interval_seconds)


def verify_p07(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    record = verify_prefit_pass(root, 7)
    if record.get("predecessor_hashes") != {"PREFIT_P06": EXPECTED_P06_RECORD}:
        raise StaleStateError("P07 predecessor changed")
    _p06_identity(root)
    config, contract_hash = _load_config(root)
    _validate_features(root, config)
    freeze = _read_json(root / FREEZE_PATH)
    boundary = _read_json(root / BOUNDARY_PASS_PATH)
    _record_hash(freeze, label="P07 freeze")
    _record_hash(boundary, label="P07 modeling-boundary PASS")
    if (
        freeze.get("schema_version") != FREEZE_SCHEMA
        or freeze.get("status") != "FROZEN_NO_MODEL_FITS"
        or freeze.get("approved_contract_sha256") != contract_hash
        or boundary.get("schema_version") != BOUNDARY_PASS_SCHEMA
        or boundary.get("status") != "PREFIT_COMPLETE_MODEL_FITTING_AUTHORIZED"
        or boundary.get("p07_freeze_record_sha256") != freeze.get("record_sha256")
        or freeze.get("holdout_opened") is not False
        or boundary.get("holdout_opened") is not False
    ):
        raise ContractError("P07 final release identity changed")
    for relative, expected in freeze["frozen_files"].items():
        if sha256_path(root / relative) != expected:
            raise StaleStateError(f"P07 frozen artifact changed: {relative}")
    expected_tables = [
        (DATE_ROLES_PATH, date_roles_schema(), 2_080),
        (OUTER_FOLDS_PATH, outer_folds_schema(), 6_240),
        (INNER_FOLDS_PATH, inner_folds_schema(), 31_200),
        (ADAPTER_INDEX_PATH, adapter_index_schema(), EXPECTED_ISSUE_ROWS),
    ]
    for relative, schema, rows in expected_tables:
        parquet = pq.ParquetFile(root / relative)
        if parquet.schema_arrow != schema or parquet.metadata.num_rows != rows:
            raise ContractError(f"P07 table schema or count changed: {relative}")
    roles = pq.read_table(
        root / DATE_ROLES_PATH,
        columns=["evidence_role", "sealed_outcome_unopened"],
    ).to_pylist()
    if Counter(row["evidence_role"] for row in roles) != {
        "DEVELOPMENT_SUPERVISED": 1707,
        "DEVELOPMENT_UNRESOLVED": 3,
        "SEALED_HOLDOUT": 365,
        "POST_HOLDOUT_TAIL": 5,
    }:
        raise ContractError("P07 evidence-role counts changed")
    if sum(bool(row["sealed_outcome_unopened"]) for row in roles) != 365:
        raise ContractError("P07 holdout lock changed")
    adapter_columns = set(pq.ParquetFile(root / ADAPTER_INDEX_PATH).schema_arrow.names)
    forbidden = {"y_audited_f", "truth_qc_status", "truth_evidence_status", "fold_id"}
    if adapter_columns & forbidden:
        raise ContractError("P07 target-free adapter contains forbidden columns")
    isolation = validate_runtime_isolation(root)
    return {
        "status": "VALID",
        "validated_stage": "PREFIT_P07",
        "record_sha256": record["record_sha256"],
        "release_id": EXPERIMENT_RELEASE_ID,
        "release_status": boundary["status"],
        "contract_sha256": contract_hash,
        "freeze_record_sha256": freeze["record_sha256"],
        "modeling_boundary_pass_sha256": boundary["record_sha256"],
        "outer_fold_count": 3,
        "nested_inner_fold_instances": 15,
        "date_role_rows": 2_080,
        "target_free_adapter_rows": EXPECTED_ISSUE_ROWS,
        "sealed_holdout_rows": 365,
        "holdout_opened": False,
        "sealed_holdout_values_read": False,
        "model_fits_performed": 0,
        "network_requests_made": 0,
        "runtime_isolation": {
            key: value for key, value in isolation.items() if key != "source_files_scanned"
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m kden_v375.prefit.p07_experiment")
    parser.add_argument("--project-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="show and hash the complete P07 decision contract")
    for name in ("run", "resume"):
        command = commands.add_parser(name, help=f"{name} the owner-controlled P07 freeze")
        command.add_argument("--run-id", required=True)
        command.add_argument("--approve-contract-sha256", required=True)
    for name in ("status", "eta", "pause"):
        command = commands.add_parser(name, help=f"show or request P07 {name}")
        command.add_argument("--run-id", required=True)
    live = commands.add_parser("live-status", help="show append-only P07 progress")
    live.add_argument("--run-id", required=True)
    live.add_argument("--interval-seconds", type=float, default=5.0)
    live.add_argument("--json-lines", action="store_true")
    commands.add_parser("validate", help="verify the sealed P07 release")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = resolve_project_root(args.project_root)
        if args.command == "preflight":
            result = p07_preflight(root)
        elif args.command in {"run", "resume"}:
            result = run_p07(
                project_root=root,
                run_id=args.run_id,
                approved_contract_sha256=args.approve_contract_sha256,
                resume=args.command == "resume",
            )
        elif args.command == "status":
            result = p07_status(root, args.run_id)
        elif args.command == "eta":
            result = p07_eta(root, args.run_id)
        elif args.command == "pause":
            result = p07_pause(root, args.run_id)
        elif args.command == "live-status":
            try:
                p07_live_status(
                    root,
                    args.run_id,
                    interval_seconds=args.interval_seconds,
                    json_lines=args.json_lines,
                )
            except KeyboardInterrupt:
                pass
            return 0
        else:
            result = verify_p07(root)
    except (ContractError, OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
