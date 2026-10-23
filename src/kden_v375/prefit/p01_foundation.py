"""P01: freeze the universal-substrate foundation without reading targets."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from ..acceptance.workflow import verify_final_acceptance_pass
from ..contracts import (
    ContractError,
    StaleStateError,
    load_project_paths,
    validate_runtime_isolation,
    verify_step_pass,
)
from ..hashes import sha256_file
from ..io.atomic import atomic_write_bytes
from .records import (
    publish_immutable_json,
    validate_prefit_run_id,
    verify_prefit_pass,
    write_prefit_pass,
)


STAGE_NO = 1
PLAN_ID = "KDEN_V375_UNIVERSAL_MODELING_PREFIT_V2"
FOUNDATION_CONTRACT_ID = "KDEN_V375_PREFIT_FOUNDATION_V1"
TIME_ONTOLOGY_ID = "KDEN_V375_TIME_ONTOLOGY_V1"
EVIDENCE_ROLE_ID = "KDEN_V375_TRUTH_EVIDENCE_ROLES_V1"
ENVIRONMENT_ID = "KDEN_V375_PREFIT_ENV_V1"
SUBSTRATE_RELEASE_ID = "KDEN_V375_UNIVERSAL_ISSUE_STATE_V1"
TRUTH_RELEASE_ID = "KDEN_V375_TRUTH_EVIDENCE_V1"

PLAN_PATH = "RAFM_V375_UNIVERSAL_MODELING_PREFIT_PLAN.md"
ISSUE_VIEW_CONTRACT_PATH = "config/issue_time_views_r14_v375.json"
FOUNDATION_PATH = "config/prefit/p01_foundation_v375.json"
FOUNDATION_SCHEMA_PATH = "schemas/prefit/p01_foundation_v375.json"
TIME_SCHEMA_PATH = "schemas/prefit/time_ontology_v375.json"
EVIDENCE_SCHEMA_PATH = "schemas/prefit/truth_evidence_roles_v375.json"
PASS_SCHEMA_PATH = "schemas/prefit/prefit_pass_v375.json"
ENVIRONMENT_PATH = "environment/prefit/v1/environment.json"
RUNTIME_LOCK_PATH = "environment/prefit/v1/requirements.lock"
BUILD_LOCK_PATH = "environment/prefit/v1/build-requirements.lock"
REPORT_PATH = "reports/prefit/P01_FOUNDATION_DECISION_REPORT.md"
PASS_PATH = "state/PREFIT_P01_PASS.json"

BASE_RUNTIME_LOCK_PATH = "environment/requirements.lock"
BASE_BUILD_LOCK_PATH = "environment/build-requirements.lock"
FREEZE_PATH = "reports/kden_v375_acquisition_freeze_manifest.json"

EXPECTED_IDENTITIES = {
    "R14": "0852fea463aaad9b4b65ce5c103c45605a0b13ccd338914911b025b1aff8ecfb",
    "STEP_07": "5d66348c7dc7bbba5beb4eb3f27a9e1b847c4e15abc4646da6f8c9849b8928c5",
    "KDEN_V375_ACQUISITION": "66c58ff231b1382c0a00e4aae0ae32c93e3c48255ce8ab3aa8a444c20cc37c1a",
    "STEP_08": "2d525d3e7949adcb5e64781c858e3b7f2f7be7072ec917bd88eea087dbc4f85e",
    "ACQUISITION_FREEZE": "291cfc543f41fce327812e4453e2a56688eb1145ec19fc8193242b647de4c320",
}

STAGE5R_SOURCE_HASHES = {
    "configs/stage5r_truth_exceptions_v1.csv": (
        "3a94910bdfe58a13dcbb7098e6bf13be0e4265a10b1458522414ce340ac665a5"
    ),
    "configs/stage5r_truth_v1.toml": (
        "0d60111957f79f25128e0dacdd400cb93ead9f75690449ba045c151dddf37ded"
    ),
    "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_events.parquet": (
        "e73e976d0023edb4fbd1126b714111ca068d2b5713689842857074d9180840fb"
    ),
    "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_ledger.parquet": (
        "8e720bc58c1b31f63ba207a26fa50b9e49b5582850b2304ea2c0df1d008634ca"
    ),
    "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_review_queue.parquet": (
        "f75989560f3c2603c5729fba806770098147d2925b4a51600350e0b7cfb84a9e"
    ),
    "data/sealed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_mechanical_candidates.parquet": (
        "3ae63561b432e302a304319ad87fbc3c302fab091469516b00279e6c6985dd36"
    ),
    "manifests/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "run=stage5r1-build-20260911T081406Z-e1bd6f97f4/manifest.json": (
        "2a61bc8a0d2b7160399d9138b7ef461ff2678a53d59fc6e791949b736ab37fe8"
    ),
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ContractError(f"JSON object expected: {path}")
    return value


def _date_count(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _foundation_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "KDEN_V375_PREFIT_P01_FOUNDATION_SCHEMA_V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "contract_id",
            "status",
            "plan",
            "predecessors",
            "study",
            "clock_ontology",
            "object_contracts",
            "truth_contract",
            "artifact_roots",
            "environment_strategy",
            "isolation_contract",
            "deferred_decisions",
            "execution_policy",
        ],
        "properties": {
            "schema_version": {"const": "KDEN_V375_PREFIT_P01_FOUNDATION_V1"},
            "contract_id": {"const": FOUNDATION_CONTRACT_ID},
            "status": {"const": "FROZEN"},
            "plan": {"type": "object"},
            "predecessors": {"type": "object"},
            "study": {"type": "object"},
            "clock_ontology": {"type": "object"},
            "object_contracts": {"type": "object"},
            "truth_contract": {"type": "object"},
            "artifact_roots": {"type": "object"},
            "environment_strategy": {"type": "object"},
            "isolation_contract": {"type": "object"},
            "deferred_decisions": {"type": "object"},
            "execution_policy": {"type": "object"},
        },
    }


def _time_ontology() -> dict[str, Any]:
    return {
        "schema_version": "KDEN_V375_TIME_ONTOLOGY_SCHEMA_V1",
        "ontology_id": TIME_ONTOLOGY_ID,
        "status": "FROZEN",
        "clocks": {
            "target_date": {
                "meaning": "contract-authoritative KDEN calendar date",
                "storage": "ISO 8601 date",
                "timezone_context": "America/Denver",
            },
            "issue_time_utc": {
                "meaning": "weather-information cutoff and issue-state identity",
                "storage": "timezone-aware UTC timestamp",
            },
            "issue_time_local": {
                "meaning": "issue time rendered in America/Denver with UTC offset",
                "storage": "timezone-aware ISO 8601 timestamp plus timezone name",
            },
            "cycle_init_utc": {
                "meaning": "initialization of one HRRR product cycle",
                "storage": "timezone-aware UTC timestamp",
            },
            "emulated_available_time_utc": {
                "meaning": "historical time at which a cycle becomes legally usable",
                "storage": "timezone-aware UTC timestamp",
            },
            "valid_time_utc": {
                "meaning": "physical time described by a forecast value",
                "storage": "timezone-aware UTC timestamp",
            },
            "forecast_lead_minutes": {
                "meaning": "valid_time_utc minus cycle_init_utc",
                "storage": "signed integer minutes",
            },
            "issue_horizon_minutes": {
                "meaning": "valid_time_utc minus issue_time_utc",
                "storage": "signed integer minutes",
            },
            "interval_support": {
                "meaning": "right-open physical support for interval-valued fields",
                "fields": ["interval_start_utc", "interval_end_utc"],
                "storage": "two timezone-aware UTC timestamps or explicit nulls",
            },
            "model_ready_time_utc": {
                "meaning": "issue time plus measured operational processing latency",
                "status": "deferred_to_commercial_bridge",
            },
            "market_time_utc": {
                "meaning": "causal market observation or decision time",
                "status": "forbidden_from_universal_weather_substrate",
            },
            "truth_available_time_utc": {
                "meaning": "time at which final daily outcome evidence can be known",
                "status": "truth_metadata_only",
            },
        },
        "target_window": {
            "definition": "[07:00Z on target_date, 07:00Z on target_date plus one day)",
            "start_utc_hour": 7,
            "end_utc_hour": 7,
            "left_closed": True,
            "right_open": True,
        },
        "issue_grid": {
            "timezone": "America/Denver",
            "start_local": "02:00",
            "end_local": "16:00",
            "cadence_minutes": 15,
            "end_inclusive": True,
            "enumeration": "UTC timeline filtered by local calendar membership",
        },
        "historical_availability": {
            "policy_id": "KDEN_HIST_COMPLETE_L105_V1",
            "lag_minutes": 105,
            "eligibility_equation": (
                "cycle_init_utc + 105 minutes <= issue_time_utc"
            ),
            "selection_rule": "newest eligible cycle independently for each product",
            "actual_first_seen_reconstructed": False,
        },
        "products": {
            "wrfsfcf": {"selection": "independent", "native_cadence_minutes": 60},
            "wrfsubhf": {"selection": "independent", "native_cadence_minutes": 15},
        },
        "rules": {
            "cycle_stitching_allowed": False,
            "same_issue_products_may_use_distinct_cycles": True,
            "all_timestamps_are_timezone_aware": True,
            "target_day_is_independent_statistical_unit": True,
        },
    }


def _evidence_roles() -> dict[str, Any]:
    return {
        "schema_version": "KDEN_V375_TRUTH_EVIDENCE_ROLES_SCHEMA_V1",
        "role_contract_id": EVIDENCE_ROLE_ID,
        "truth_release_id": TRUTH_RELEASE_ID,
        "status": "FROZEN",
        "authoritative_target": {
            "source_object": "kden_truth_ledger.parquet",
            "join_key": "target_date",
            "target_field": "y_audited_f",
            "supervised_rule": "target field must be non-null and role must permit use",
            "metadata_field": "truth_qc_status",
            "unresolved_imputation_allowed": False,
        },
        "date_groups": [
            {
                "group_id": "development_audited",
                "start_date": "2021-01-01",
                "end_date": "2025-09-06",
                "date_count": 1710,
                "expected_audited_count": 1707,
                "expected_unresolved_count": 3,
                "migration_action": "copy_verified_stage5r1_bytes",
                "training_or_tuning_allowed": True,
            },
            {
                "group_id": "sealed_final_holdout",
                "start_date": "2025-09-07",
                "end_date": "2026-09-06",
                "date_count": 365,
                "migration_action": "copy_evidence_without_opening_outcomes",
                "training_or_tuning_allowed": False,
                "outcome_access": "sealed_until_model_and_evaluation_freeze",
            },
            {
                "group_id": "post_holdout_tail",
                "start_date": "2026-09-07",
                "end_date": "2026-09-11",
                "date_count": 5,
                "migration_action": "owner_run_acquisition_then_fixed_audit",
                "training_or_tuning_allowed": False,
                "pending_maturity_exclusion": False,
                "required_metadata": [
                    "truth_evidence_cutoff_utc",
                    "source_followup_window_open_at_freeze",
                    "source_retrieval_timestamps",
                    "source_hashes",
                ],
                "required_final_sensitivity": "include_and_exclude_open_followup_rows",
            },
        ],
        "allowed_evidence_statuses": {
            "audited": {
                "target_may_be_non_null": True,
                "development_supervised_use": True,
            },
            "audited_guarded_exception": {
                "target_may_be_non_null": True,
                "development_supervised_use": True,
            },
            "unresolved": {
                "target_may_be_non_null": False,
                "development_supervised_use": False,
            },
            "sealed_holdout": {
                "target_may_be_non_null": False,
                "development_supervised_use": False,
            },
            "tail_audited": {
                "target_may_be_non_null": True,
                "development_supervised_use": False,
            },
            "tail_unresolved": {
                "target_may_be_non_null": False,
                "development_supervised_use": False,
            },
            "source_unavailable": {
                "target_may_be_non_null": False,
                "development_supervised_use": False,
            },
        },
        "authorized_migration_inputs": dict(sorted(STAGE5R_SOURCE_HASHES.items())),
        "non_authoritative_targets": [
            "atomic_iem_daily_value",
            "selected_tmax_f",
            "label_selected_tmax_f",
            "individual_cli_value",
            "individual_cf6_value",
            "madis_daily_maximum",
            "mechanical_candidate",
            "reconstructed_market_settlement",
        ],
        "predictor_forbidden_roles": [
            "target_value",
            "truth_qc_status",
            "review_flag",
            "cli_or_cf6_value",
            "madis_observation",
            "market_data",
            "outcome_or_settlement",
        ],
    }


def _pass_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "KDEN_V375_PREFIT_PASS_V1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "stage_id",
            "status",
            "completed_at_utc",
            "run_id",
            "predecessor_hashes",
            "authority_hashes",
            "artifact_hashes",
            "gate_evidence",
            "record_sha256",
        ],
        "properties": {
            "schema_version": {"const": "KDEN_V375_PREFIT_PASS_V1"},
            "stage_id": {"type": "string", "pattern": "^PREFIT_P0[1-7]$"},
            "status": {"const": "PASS"},
            "completed_at_utc": {"type": "string", "format": "date-time"},
            "run_id": {
                "type": "string",
                "pattern": (
                    "^kdenv375-p0[1-7]-(ordinary|diagnostic|owner-full|validation|"
                    "synthetic)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,31}$"
                ),
            },
            "predecessor_hashes": {"type": "object"},
            "authority_hashes": {"type": "object"},
            "artifact_hashes": {"type": "object"},
            "gate_evidence": {"type": "object"},
            "record_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    }


def _environment_contract(root: Path) -> dict[str, Any]:
    return {
        "schema_version": "KDEN_V375_PREFIT_ENVIRONMENT_V1",
        "environment_id": ENVIRONMENT_ID,
        "status": "FROZEN_FOR_P01",
        "python_implementation": "CPython",
        "python_requires": ">=3.12,<3.13",
        "local_virtual_environment": ".venv-prefit-v1",
        "runtime_lock": {
            "path": RUNTIME_LOCK_PATH,
            "sha256": sha256_file(root / BASE_RUNTIME_LOCK_PATH),
            "initial_source": BASE_RUNTIME_LOCK_PATH,
            "source_bytes_copied_unchanged": True,
        },
        "build_lock": {
            "path": BUILD_LOCK_PATH,
            "sha256": sha256_file(root / BASE_BUILD_LOCK_PATH),
            "initial_source": BASE_BUILD_LOCK_PATH,
            "source_bytes_copied_unchanged": True,
        },
        "acquisition_environment": {
            "environment_id": "KDEN_V375_ENVIRONMENT_V1",
            "runtime_lock": BASE_RUNTIME_LOCK_PATH,
            "build_lock": BASE_BUILD_LOCK_PATH,
            "mutation_allowed": False,
        },
        "successor_policy": {
            "dependency_change_requires_new_environment_id": True,
            "dependency_change_requires_new_versioned_directory": True,
            "existing_lock_rewrite_allowed": False,
            "fresh_virtual_environment_required": True,
            "future_path_template": "environment/prefit/vN/",
        },
        "runtime_isolation": {
            "legacy_package_imports_allowed": False,
            "external_project_path_dependencies_allowed": False,
            "scientific_artifacts_may_contain_absolute_user_paths": False,
        },
    }


def _object_contracts() -> dict[str, Any]:
    return {
        "issue_spine": {
            "primary_key": ["issue_state_id"],
            "natural_key": ["target_date", "issue_time_utc"],
            "statistical_group_key": ["target_date"],
            "target_values_allowed": False,
        },
        "selected_cycles": {
            "primary_key": ["issue_state_id", "product"],
            "products": ["wrfsfcf", "wrfsubhf"],
            "selection_is_independent_by_product": True,
            "target_values_allowed": False,
        },
        "trajectory_catalog": {
            "primary_key": ["trajectory_state_id"],
            "natural_key": [
                "product",
                "field_registry_id",
                "cycle_init_utc",
                "valid_time_utc",
                "time_support_id",
                "spatial_contract_id",
            ],
            "canonical_r14_values_are_referenced_not_duplicated": True,
            "target_values_allowed": False,
        },
        "deterministic_feature_panel": {
            "primary_key": ["issue_state_id"],
            "feature_registry_is_frozen_in_stage": "P04",
            "learned_or_target_guided_features_allowed": False,
            "target_values_allowed": False,
        },
        "truth_catalog": {
            "primary_key": ["target_date"],
            "physical_isolation_from_features": True,
            "release_id": TRUTH_RELEASE_ID,
        },
        "fold_assignments": {
            "primary_key": ["target_date"],
            "all_issue_rows_for_day_share_assignment": True,
            "exact_boundaries_frozen_in_stage": "P07",
        },
        "provenance": {
            "primary_key": ["object_type", "object_id", "source_artifact_id"],
            "source_hash_required": True,
        },
    }


def _foundation_contract(
    root: Path,
    *,
    predecessors: Mapping[str, str],
) -> dict[str, Any]:
    artifact_roots = {
        "truth_bundle": "truth/kden_tmax/v1",
        "universal_issue_state": "universal_issue_state/v1",
        "issue_spine": "universal_issue_state/v1/issue_spine",
        "selected_cycles": "universal_issue_state/v1/selected_cycles",
        "trajectory_catalog": "universal_issue_state/v1/trajectory_catalog",
        "deterministic_features": "universal_issue_state/v1/deterministic_features",
        "release_manifests": "universal_issue_state/v1/manifests",
        "fold_registry": "folds/kden_v375/v1",
        "model_experiments": "modeling/experiments",
        "prefit_runs": "prefit_runs",
    }
    return {
        "schema_version": "KDEN_V375_PREFIT_P01_FOUNDATION_V1",
        "contract_id": FOUNDATION_CONTRACT_ID,
        "status": "FROZEN",
        "plan": {
            "plan_id": PLAN_ID,
            "path": PLAN_PATH,
            "sha256": sha256_file(root / PLAN_PATH),
            "supersedes": ["prefit plan V1.0", "prefit clarification V1.1"],
        },
        "predecessors": dict(predecessors),
        "study": {
            "scope_id": "KDEN_V375_R14_V1",
            "target_start_date": "2021-01-01",
            "target_end_date": "2026-09-11",
            "target_day_count": 2080,
            "issue_view_contract": ISSUE_VIEW_CONTRACT_PATH,
            "substrate_release_id": SUBSTRATE_RELEASE_ID,
            "truth_release_id": TRUTH_RELEASE_ID,
        },
        "clock_ontology": {
            "ontology_id": TIME_ONTOLOGY_ID,
            "schema_path": TIME_SCHEMA_PATH,
        },
        "object_contracts": _object_contracts(),
        "truth_contract": {
            "role_contract_id": EVIDENCE_ROLE_ID,
            "schema_path": EVIDENCE_SCHEMA_PATH,
            "truth_is_not_a_predictor": True,
            "holdout_remains_sealed_through_p07": True,
            "tail_is_never_training_or_tuning_data": True,
        },
        "artifact_roots": artifact_roots,
        "environment_strategy": {
            "environment_id": ENVIRONMENT_ID,
            "contract_path": ENVIRONMENT_PATH,
            "separate_from_acquisition_environment": True,
            "versioned_successors_only": True,
        },
        "isolation_contract": {
            "weather_features": "target_free",
            "truth_storage": "separate",
            "fold_storage": "separate",
            "market_storage": "separate_and_later",
            "madis_predictors_allowed": False,
            "legacy_runtime_dependencies_allowed": False,
            "absolute_user_paths_allowed_in_scientific_artifacts": False,
        },
        "modeling_direction": {
            "first_program": "RAFM",
            "method_family": "Analog Ensemble specialist mixture",
            "relationship_to_substrate": "adapter_not_definition",
            "future_model_families_allowed": True,
        },
        "deferred_decisions": {
            "exact_issue_row_count": "P03",
            "deterministic_feature_definitions": "P04",
            "partition_and_chunk_layout": "P05",
            "acceptance_anchors_and_release_hashes": "P06",
            "fold_boundaries": "P07",
            "pmf_support_and_tails": "P07",
            "analog_hyperparameters": "P07",
            "specialist_and_gate_contracts": "P07",
            "model_ready_and_market_latency": "later_commercial_bridge",
        },
        "execution_policy": {
            "p01_network_allowed": False,
            "p01_target_value_read_allowed": False,
            "p01_feature_materialization_allowed": False,
            "p01_fold_assignment_allowed": False,
            "p01_model_fitting_allowed": False,
            "long_running_work_is_owner_run": True,
        },
    }


def _decision_report(contract: Mapping[str, Any]) -> bytes:
    predecessors = contract["predecessors"]
    plan = contract["plan"]
    text = f"""# P01 Foundation Decision Report

Status: **PASS-ready foundation contract**  
Contract: `{FOUNDATION_CONTRACT_ID}`  
Plan: `{PLAN_ID}`  
Universal substrate release reserved: `{SUBSTRATE_RELEASE_ID}`

## What P01 freezes

- The R14 study covers 2,080 target days from 2021-01-01 through 2026-09-11.
- Historical issue states use the 02:00–16:00 America/Denver grid every 15 minutes, inclusive.
- Cycle availability remains L105, with hourly and Q05 cycles selected independently.
- The target day—not an issue row—is the independent weather event.
- Weather features, truth, folds, market data, and model experiments remain separate objects.
- The existing 365-day truth holdout stays sealed.
- The five post-holdout dates are handled by P02 and are never development data.
- RAFM is the first model adapter; it does not define the universal substrate.
- Exact folds and all tuning choices remain deferred to P07.

## Bound predecessors

| Record | SHA-256 |
|---|---|
| R14 acquisition | `{predecessors['R14']}` |
| Step 07 | `{predecessors['STEP_07']}` |
| Final acquisition | `{predecessors['KDEN_V375_ACQUISITION']}` |
| Step 08 | `{predecessors['STEP_08']}` |
| Acquisition freeze | `{predecessors['ACQUISITION_FREEZE']}` |
| Governing V2 plan | `{plan['sha256']}` |

## New, non-acquisition roots

P01 reserves versioned roots for truth, universal issue states, folds, modeling
experiments, and prefit runs. It does not create feature rows, labels, folds,
or models. The frozen acquisition archive and environment are untouched.

## Modeling environment

`{ENVIRONMENT_ID}` starts with byte-identical copies of the frozen runtime and
build locks under `environment/prefit/v1/`. Any dependency change requires a
new environment ID, a new versioned directory, and a fresh virtual environment.
No existing lock may be rewritten.

## What P01 intentionally does not do

P01 makes no network request, reads no target values, opens no holdout outcome,
materializes no feature, assigns no fold, and fits no model. P02 is the next
stage: adopt the verified truth package into v3.75 and prepare the owner-run
five-day tail acquisition.

## Validation

After installing the local package, run:

```bash
.venv/bin/python -m kden_v375.prefit.cli validate-p01
```
"""
    return text.encode("utf-8")


def _verify_predecessors(root: Path) -> dict[str, str]:
    step07 = verify_step_pass(root, 7)
    step08 = verify_step_pass(root, 8)
    acquisition = verify_final_acceptance_pass(root)
    freeze = _read_json(root / FREEZE_PATH)
    predecessors = {
        "R14": str(step07["gate_evidence"]["r14_combined_pass_sha256"]),
        "STEP_07": str(step07["record_sha256"]),
        "KDEN_V375_ACQUISITION": str(acquisition["record_sha256"]),
        "STEP_08": str(step08["record_sha256"]),
        "ACQUISITION_FREEZE": str(freeze.get("freeze_sha256", "")),
    }
    if predecessors != EXPECTED_IDENTITIES:
        raise StaleStateError(
            "frozen acquisition identities differ from the governing V2 plan"
        )
    if acquisition.get("freeze_sha256") != predecessors["ACQUISITION_FREEZE"]:
        raise StaleStateError("final acquisition PASS and freeze identity disagree")
    return predecessors


def _validate_semantics(
    root: Path,
    contract: Mapping[str, Any],
    time_ontology: Mapping[str, Any],
    evidence_roles: Mapping[str, Any],
    environment: Mapping[str, Any],
) -> None:
    if _date_count("2021-01-01", "2026-09-11") != 2080:
        raise ContractError("R14 study date count is internally inconsistent")
    for group in evidence_roles["date_groups"]:
        if _date_count(group["start_date"], group["end_date"]) != group["date_count"]:
            raise ContractError(f"truth date group count changed: {group['group_id']}")
    if sum(group["date_count"] for group in evidence_roles["date_groups"]) != 2080:
        raise ContractError("truth date groups do not partition all R14 target days")
    issue = _read_json(root / ISSUE_VIEW_CONTRACT_PATH)
    if issue.get("availability", {}).get("lag_minutes") != 105:
        raise ContractError("Step 07 issue-view availability no longer matches L105")
    if issue.get("default_issue_grid") != time_ontology["issue_grid"]:
        raise ContractError("P01 issue grid differs from the Step 07 contract")
    if issue.get("default_cross_product_alignment_contract") != "separate_experts":
        raise ContractError("independent product selection contract changed")
    if contract["study"]["target_day_count"] != 2080:
        raise ContractError("foundation study count changed")
    if contract["truth_contract"]["holdout_remains_sealed_through_p07"] is not True:
        raise ContractError("P01 cannot open the final holdout")
    if any(
        path.startswith("hrrr_v4_local_archive/")
        for path in contract["artifact_roots"].values()
    ):
        raise ContractError("a new prefit root overlaps the frozen archive")
    if environment["acquisition_environment"]["mutation_allowed"] is not False:
        raise ContractError("acquisition environment must remain immutable")
    if environment["runtime_lock"]["sha256"] != sha256_file(root / RUNTIME_LOCK_PATH):
        raise StaleStateError("prefit runtime lock hash changed")
    if environment["build_lock"]["sha256"] != sha256_file(root / BUILD_LOCK_PATH):
        raise StaleStateError("prefit build lock hash changed")


def _authority_hashes(root: Path) -> dict[str, str]:
    return {
        "GOVERNING_PLAN": sha256_file(root / PLAN_PATH),
        "ISSUE_VIEW_CONTRACT": sha256_file(root / ISSUE_VIEW_CONTRACT_PATH),
        "ACQUISITION_RUNTIME_LOCK": sha256_file(root / BASE_RUNTIME_LOCK_PATH),
        "ACQUISITION_BUILD_LOCK": sha256_file(root / BASE_BUILD_LOCK_PATH),
    }


def _gate_evidence() -> dict[str, Any]:
    return {
        "step_07_predecessor_verified": True,
        "step_08_predecessor_verified": True,
        "final_acquisition_and_freeze_verified": True,
        "governing_v2_plan_bound": True,
        "clock_ontology_encoded": True,
        "object_primary_keys_encoded": True,
        "truth_evidence_roles_and_date_groups_encoded": True,
        "sealed_holdout_role_preserved": True,
        "tail_policy_encoded_without_pending_maturity_exclusion": True,
        "environment_successor_is_separate_and_versioned": True,
        "acquisition_environment_locks_copied_without_mutation": True,
        "new_artifact_roots_do_not_overlap_frozen_archive": True,
        "fold_choices_deferred_to_p07": True,
        "rafm_adapter_does_not_define_substrate": True,
        "network_requests_made": 0,
        "target_value_files_read": 0,
        "feature_rows_materialized": 0,
        "fold_assignments_created": 0,
        "models_fitted": 0,
    }


def _stable_isolation_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    """Retain policy results without freezing the evolving source-file count."""

    return {
        "absolute_user_paths_found": int(value["absolute_user_paths_found"]),
        "denied_import_prefixes": list(value["denied_import_prefixes"]),
        "legacy_runtime_references_found": int(
            value["legacy_runtime_references_found"]
        ),
        "package_root": str(value["package_root"]),
    }


def _publish_lock_copy(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != data:
            raise StaleStateError(f"immutable prefit lock differs: {destination}")
        return
    atomic_write_bytes(destination, data, replace=False)


def run_p01(*, project_root: Path | str, run_id: str) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    root = paths.root
    validate_prefit_run_id(run_id, stage_no=STAGE_NO, scope="ordinary")
    if (root / PASS_PATH).is_file():
        return verify_p01(root)
    predecessors = _verify_predecessors(root)
    _publish_lock_copy(root / BASE_RUNTIME_LOCK_PATH, root / RUNTIME_LOCK_PATH)
    _publish_lock_copy(root / BASE_BUILD_LOCK_PATH, root / BUILD_LOCK_PATH)
    environment = _environment_contract(root)
    time_ontology = _time_ontology()
    evidence_roles = _evidence_roles()
    contract = _foundation_contract(root, predecessors=predecessors)
    _validate_semantics(root, contract, time_ontology, evidence_roles, environment)

    publish_immutable_json(root / FOUNDATION_SCHEMA_PATH, _foundation_schema())
    publish_immutable_json(root / TIME_SCHEMA_PATH, time_ontology)
    publish_immutable_json(root / EVIDENCE_SCHEMA_PATH, evidence_roles)
    publish_immutable_json(root / PASS_SCHEMA_PATH, _pass_schema())
    publish_immutable_json(root / ENVIRONMENT_PATH, environment)
    publish_immutable_json(root / FOUNDATION_PATH, contract)
    report_bytes = _decision_report(contract)
    report_path = root / REPORT_PATH
    if report_path.exists():
        if report_path.read_bytes() != report_bytes:
            raise StaleStateError(f"immutable P01 report differs: {report_path}")
    else:
        atomic_write_bytes(report_path, report_bytes, replace=False)

    isolation = validate_runtime_isolation(root)
    if isolation["legacy_runtime_references_found"] != 0:
        raise ContractError("runtime isolation validation failed")
    return write_prefit_pass(
        root,
        stage_no=STAGE_NO,
        run_id=run_id,
        artifact_paths=(
            FOUNDATION_PATH,
            FOUNDATION_SCHEMA_PATH,
            TIME_SCHEMA_PATH,
            EVIDENCE_SCHEMA_PATH,
            PASS_SCHEMA_PATH,
            ENVIRONMENT_PATH,
            RUNTIME_LOCK_PATH,
            BUILD_LOCK_PATH,
            REPORT_PATH,
            "src/kden_v375/prefit/__init__.py",
            "src/kden_v375/prefit/records.py",
            "src/kden_v375/prefit/p01_foundation.py",
        ),
        predecessor_hashes=predecessors,
        authority_hashes=_authority_hashes(root),
        gate_evidence={
            **_gate_evidence(),
            "runtime_isolation": _stable_isolation_evidence(isolation),
        },
    )


def verify_p01(project_root: Path | str) -> dict[str, Any]:
    root = load_project_paths(project_root).root
    record = verify_prefit_pass(root, STAGE_NO)
    predecessors = _verify_predecessors(root)
    if record.get("predecessor_hashes") != predecessors:
        raise StaleStateError("P01 predecessor identities changed")
    if record.get("authority_hashes") != _authority_hashes(root):
        raise StaleStateError("P01 governing authority hashes changed")

    environment = _environment_contract(root)
    time_ontology = _time_ontology()
    evidence_roles = _evidence_roles()
    contract = _foundation_contract(root, predecessors=predecessors)
    expected_json = {
        FOUNDATION_PATH: contract,
        FOUNDATION_SCHEMA_PATH: _foundation_schema(),
        TIME_SCHEMA_PATH: time_ontology,
        EVIDENCE_SCHEMA_PATH: evidence_roles,
        PASS_SCHEMA_PATH: _pass_schema(),
        ENVIRONMENT_PATH: environment,
    }
    for relative, expected in expected_json.items():
        if _read_json(root / relative) != expected:
            raise StaleStateError(f"P01 semantic artifact changed: {relative}")
    if (root / RUNTIME_LOCK_PATH).read_bytes() != (root / BASE_RUNTIME_LOCK_PATH).read_bytes():
        raise StaleStateError("P01 runtime lock no longer matches its frozen source")
    if (root / BUILD_LOCK_PATH).read_bytes() != (root / BASE_BUILD_LOCK_PATH).read_bytes():
        raise StaleStateError("P01 build lock no longer matches its frozen source")
    if (root / REPORT_PATH).read_bytes() != _decision_report(contract):
        raise StaleStateError("P01 decision report changed")
    _validate_semantics(root, contract, time_ontology, evidence_roles, environment)
    expected_gates = {
        **_gate_evidence(),
        "runtime_isolation": _stable_isolation_evidence(
            validate_runtime_isolation(root)
        ),
    }
    if record.get("gate_evidence") != expected_gates:
        raise StaleStateError("P01 gate evidence changed")
    return record
