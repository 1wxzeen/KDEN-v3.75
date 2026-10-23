"""Additive development identity and explicit, owner-confirmed recipe locking."""
from __future__ import annotations
import math
import re
from .common import ContractError, atomic_json, check_document, digest, hash_file, inside, read_json, signed, utc_now, verify_record
from .replay import development_plan, plan_counts
from .t03_workflow import validate_t03

PASS = "manifests/T04_DEVELOPMENT_PASS.json"
LOCK = "manifests/T04_RECIPE_LOCK.json"
CHECKS = "manifests/T04_IMPLEMENTATION_CHECKS.json"
FILES = ["run_t04.py", "config/scoring_t04.json", "config/decision_t04_proposal.json",
         "schemas/t04_state.json", "schemas/t04_pass.json", "schemas/t04_score.json", "schemas/t04_lock.json",
         "src/kden_r14_tabular/t04_contract.py", "src/kden_r14_tabular/t04_history.py",
         "src/kden_r14_tabular/t04_scoring.py", "src/kden_r14_tabular/t04_workflow.py",
         "src/kden_r14_tabular/t04_cli.py", "tests/test_t04.py", "reports/T04_OWNER_RUNBOOK.md"]
FLAGSHIPS = ("KDEN_TABICL_T3", "KDEN_TABDPT_D2_NATIVE")


def identity(experiment):
    return {p: hash_file(inside(experiment, p)) for p in FILES}


def run_path(experiment, run_id, relative):
    if not re.fullmatch(r"kdenv375-t04-[A-Za-z0-9_-]{1,100}", run_id):
        raise ContractError("T04 run ID must start kdenv375-t04-; letters/numbers/_/- only")
    return inside(experiment, f"runs/{run_id}/{relative}")


def scoring_policy(experiment):
    cfg = read_json(inside(experiment, "config/scoring_t04.json"))
    if (cfg["schema_version"] != "R14_TABULAR_T04_SCORING_V1" or cfg["probability_floor"] is not None
        or cfg["holdout_values_permitted"] or cfg["windows"] != {"EARLY_DIAGNOSTIC_02_08": [120,480], "PRIMARY_02_14": [120,840], "FULL_02_16": [120,960]}
        or cfg["primary_window_name"]!="PRIMARY_02_14" or cfg["primary_window_owner_confirmed"] is not True
        or cfg["comparison_family"] != [[FLAGSHIPS[0], "Q_RESIDUAL"], [FLAGSHIPS[1], "Q_RESIDUAL"]]):
        raise ContractError("T04 scoring contract changed; version the experiment, not its accepted recipe")
    return cfg


def counts(plan=None):
    base = plan_counts(development_plan() if plan is None else plan)
    return {**base, "score_days": base["correction_days"], "total_units": base["total_units"] + base["correction_days"] + 1}


def preflight(project, experiment):
    predecessor = validate_t03(project, experiment)
    t03 = verify_record(read_json(inside(experiment, "manifests/T03_PASS.json")))
    checks = verify_record(read_json(inside(experiment, CHECKS)))
    code = identity(experiment)
    if (checks["status"] != "PASS" or checks["code_identity"] != code or checks["synthetic_tests_run"] < 25
        or checks["failures"] or checks["errors"]):
        raise ContractError("T04 short implementation checks absent/stale/failed")
    cfg = scoring_policy(experiment)
    performance = verify_record(read_json(inside(experiment, t03["performance_report_path"])))
    return {"status": "READY_FOR_OWNER_DEVELOPMENT_REPLAY", "t03_record_sha256": predecessor["record_sha256"],
            "t03_binding_sha256": t03["identity_sha256"], "device": t03["binding"]["device"],
            "code_identity": code, "scoring_policy_sha256": digest(cfg),
            "implementation_checks_sha256": checks["record_sha256"], "counts": counts(),
            "development_start": "2022-01-01", "development_end": "2025-09-06",
            "t03_native_only_projection": performance["result"]["projections"]["development_native_only"],
            "projection_note": "Measured native-only envelope is not full T04 ETA; corrections/scoring/I/O add cost.",
            "neural_processes": 1, "holdout_value_pages_read": 0, "network_requests_made": 0,
            "study_model_fits_performed": 0, "recipe_lock_created": False,
            "lock_note": "Development PASS is separate from an explicit owner-approved recipe lock; no T05 is started."}


def decision(value):
    expected = set(read_decision_fields())
    if set(value) != expected or value["schema_version"] != "R14_TABULAR_T04_DECISION_V1" or value["owner_confirmed"] is not True:
        raise ContractError("owner-confirmed exact decision document required, not the proposal")
    window = value["primary_window_minutes"]
    if (not isinstance(window, list) or len(window)!=2 or any(isinstance(x,bool) or not isinstance(x,int) for x in window)
        or window != [120,840]):
        raise ContractError("this scoring release uses owner-confirmed 02:00–14:00; a different window needs a versioned scoring release before lock")
    for k in ("modal_hit_rate_min", "mean_mae_f_max", "mean_rmse_f_max", "integer_nll_nats_max", "supported_forecast_fraction_min"):
        x = value[k]
        if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0:
            raise ContractError("explicit positive finite success limits required")
    if value["modal_hit_rate_min"] > 1 or value["supported_forecast_fraction_min"] > 1:
        raise ContractError("success fractions must not exceed one")
    n = value["complete_holdout_days_min"]
    if isinstance(n,bool) or not isinstance(n,int) or not 1<=n<=365:
        raise ContractError("complete holdout days must be in 1..365")
    if value["selected_operational_candidate"] not in FLAGSHIPS:
        raise ContractError("select one development-inspected flagship before holdout; no winner selection on holdout")
    if any(not isinstance(value[k],str) or not value[k].strip() for k in ("selection_rationale", "development_revision_exposure_note")):
        raise ContractError("selection rationale and exposure note required")
    return value


def read_decision_fields():
    return ("schema_version", "owner_confirmed", "primary_window_minutes", "modal_hit_rate_min", "mean_mae_f_max",
            "mean_rmse_f_max", "integer_nll_nats_max", "complete_holdout_days_min", "supported_forecast_fraction_min",
            "selected_operational_candidate", "selection_rationale", "development_revision_exposure_note")


def lock_recipe(project, experiment, decision_relative):
    # Full development acceptance is owner-run. Lock rechecks bound identity and the final report,
    # not thousands of original archive files or any holdout value pages.
    ready = preflight(project, experiment)
    passed = verify_record(read_json(inside(experiment, PASS)))
    if passed["binding"]["code_identity"] != ready["code_identity"] or passed["binding"]["t03_record_sha256"] != ready["t03_record_sha256"]:
        raise ContractError("development PASS binds a different implementation/predecessor")
    validation_path = "manifests/T04_DEVELOPMENT_VALIDATED.json"
    validation = verify_record(read_json(inside(experiment, validation_path)))
    if validation["development_record_sha256"] != passed["record_sha256"] or validation["status"] != "VALID":
        raise ContractError("validate-t04 must complete before recipe lock")
    value = decision(read_json(inside(experiment, decision_relative)))
    report_path = passed["report_path"]
    if hash_file(inside(experiment, report_path)) != passed["report_sha256"]:
        raise ContractError("development scorecard changed")
    report = verify_record(read_json(inside(experiment, report_path)))["result"]
    candidate = value["selected_operational_candidate"]
    score = report["scorecard"]["windows"]["PRIMARY_02_14"][candidate]
    if score["complete_day"]["days"] == 0:
        raise ContractError("cannot nominate a candidate with no complete supported development days")
    body = signed({"schema_version": "R14_TABULAR_T04_LOCK_V1", "status": "LOCKED", "stage": "T04_RECIPE_LOCK",
        "created_at_utc": utc_now(), "development_record_sha256": passed["record_sha256"],
        "development_report_sha256": passed["report_sha256"], "development_validation_sha256": validation["record_sha256"],
        "frozen_binding": passed["binding"], "success_and_selection_contract": value,
        "scoring_policy": scoring_policy(experiment), "regime_cutoffs": report["regime_cutoffs"],
        "holdout_value_pages_read": 0, "holdout_replay_started": False,
        "historical_exposure_ledger_sha256": passed["binding"]["exposure_ledger_sha256"]})
    check_document(experiment, "t04_lock", body)
    atomic_json(inside(experiment, "manifests/T04_OWNER_DECISION.json"), signed({"decision": value}), immutable=True)
    if inside(experiment, LOCK).exists():
        old = verify_record(read_json(inside(experiment, LOCK)))
        if old["success_and_selection_contract"] != value or old["development_record_sha256"] != passed["record_sha256"]:
            raise ContractError("recipe already locked differently; no overwrite")
        return old
    atomic_json(inside(experiment, LOCK), body, immutable=True)
    return body
