"""Additive recovery; original T04 code, identity and completed units stay intact.

Only the two diagnostic probability flags change Python type: NumPy bool ->
builtin bool. Numeric metrics, native laws, forecasts, correction history and
scientific contracts are untouched. New score/report units bind this extension
via extra_artifacts; the final report binds its provenance and the original PASS
binds that report. The baseline run binding is deliberately not rewritten.
"""
from __future__ import annotations
import argparse
import json
from contextlib import contextmanager
from pathlib import Path
import sys
from unittest.mock import patch
import numpy as np
from .common import (ContractError, atomic_json, digest, hash_file, inside,
                     read_json, signed, utc_now, verify_record)
from .cli import process_alive
from .foundation import EXPERIMENT_REL
from . import t04_cli as cli, t04_contract as contract
from . import t04_scoring as scoring, t04_workflow as workflow

REPAIR_ID = "T04_NUMPY_BOOLEAN_SERIALIZATION_V1"
CHECKS = "manifests/T04_SERIALIZATION_REPAIR_CHECKS_V1.json"
FILES = ("run_t04_serialization_repair.py",
         "src/kden_r14_tabular/t04_serialization_repair.py",
         "tests/test_t04_serialization_repair.py",
         "reports/T04_SERIALIZATION_REPAIR_OWNER_RUNBOOK.md")
FLAGS = {"genuine_zero_probability", "probability_underflow"}


def identity(experiment):
    return {p: hash_file(inside(experiment, p)) for p in FILES}


def repair_path(run_id):
    # Apply the original run-name safety check without using any user path.
    contract.run_path(Path.cwd(), run_id, "identity.json")
    return f"runs/{run_id}/repairs/{REPAIR_ID}.json"


def boolean_metrics(original, *args, **kwargs):
    metrics, flags, reliability = original(*args, **kwargs)
    if set(flags) != FLAGS or any(not isinstance(v, (bool, np.bool_)) for v in flags.values()):
        raise ContractError("serialization repair accepts only the two boolean probability flags")
    return metrics, {k: bool(v) for k, v in flags.items()}, reliability


def repair_checks(experiment):
    record = verify_record(read_json(inside(experiment, CHECKS)))
    if (record.get("repair_id") != REPAIR_ID or record.get("status") != "PASS"
        or record.get("code_identity") != identity(experiment)
        or record.get("synthetic_tests_run", 0) < 12 or record.get("failures") != 0
        or record.get("errors") != 0):
        raise ContractError("boolean repair checks absent, stale or failed")
    return record


def baseline(project, experiment, run_id):
    if experiment.resolve() != inside(project, EXPERIMENT_REL):
        raise ContractError("repair must remain in the declared experiment")
    checks = repair_checks(experiment)
    ready = contract.preflight(project, experiment)
    original = verify_record(read_json(contract.run_path(experiment, run_id, "identity.json")))
    if original["binding"] != workflow.binding(experiment, ready, workflow.development_plan()):
        raise ContractError("original run code, inputs or contracts changed; refuse recovery")
    return original, checks, ready


def checkpoint_receipts(experiment, run_id, binding_sha):
    directory = contract.run_path(experiment, run_id, "receipts")
    result = {}
    for p in sorted(directory.glob("*.json")):
        relative = p.relative_to(experiment.resolve()).as_posix()
        record = verify_record(read_json(inside(experiment, relative)))
        if (record["status"] != "COMMITTED" or record["identity_sha256"] != binding_sha
            or record["unit_id"] != p.stem
            or record["bundle_path"] != f"runs/{run_id}/units/{p.stem}.json"):
            raise ContractError("checkpoint receipt does not belong to the original run")
        result[relative] = hash_file(p)
    if not result:
        raise ContractError("repair requires a nonempty original checkpoint")
    return result


def verify_repair(experiment, run_id, original, checks):
    relative = repair_path(run_id)
    record = verify_record(read_json(inside(experiment, relative)))
    expected = {"repair_id": REPAIR_ID, "run_id": run_id,
                "original_identity_record_sha256": original["record_sha256"],
                "baseline_binding_sha256": digest(original["binding"]),
                "code_identity": identity(experiment),
                "implementation_checks_sha256": checks["record_sha256"],
                "change_scope": "TWO_PROBABILITY_FLAGS_NUMPY_BOOL_TO_BUILTIN_BOOL_ONLY",
                "numeric_metrics_changed": False, "forecast_bytes_changed": False,
                "holdout_value_pages_read": 0, "model_fits_performed": 0}
    if any(record.get(k) != v for k, v in expected.items()):
        raise ContractError("repair attestation changed or binds a different run/code")
    if not record.get("checkpoint_receipt_hashes"):
        raise ContractError("repair lacks original checkpoint provenance")
    for p, sha in record["checkpoint_receipt_hashes"].items():
        if not p.startswith(f"runs/{run_id}/receipts/") or hash_file(inside(experiment, p)) != sha:
            raise ContractError("a pre-repair committed receipt changed")
    return record


def prepare(project, experiment, run_id):
    original, checks, ready = baseline(project, experiment, run_id)
    if inside(experiment, repair_path(run_id)).exists():
        return verify_repair(experiment, run_id, original, checks)
    state = read_json(contract.run_path(experiment, run_id, "state.json"))
    if state["status"] != "FAILED" or process_alive(state["pid"]):
        raise ContractError("prepare repair only for the failed, stopped run")
    lock = inside(experiment, "runs/T04_RUNNING.lock")
    if lock.exists() or inside(experiment, contract.PASS).exists():
        raise ContractError("repair preparation refuses an existing running lock or accepted PASS")
    if state["identity_sha256"] != digest(original["binding"]):
        raise ContractError("failed state does not belong to the original run")
    if state["message"] != "TypeError: Object of type bool is not JSON serializable":
        raise ContractError("this repair does not address the recorded failure")
    receipts = checkpoint_receipts(experiment, run_id, state["identity_sha256"])
    if len(receipts) != state["completed_units"]:
        raise ContractError("checkpoint count differs from the failed state; inspect before preparing")
    record = signed({"repair_id": REPAIR_ID, "run_id": run_id, "created_at_utc": utc_now(),
        "original_identity_record_sha256": original["record_sha256"],
        "baseline_binding_sha256": state["identity_sha256"],
        "code_identity": identity(experiment), "implementation_checks_sha256": checks["record_sha256"],
        "change_scope": "TWO_PROBABILITY_FLAGS_NUMPY_BOOL_TO_BUILTIN_BOOL_ONLY",
        "numeric_metrics_changed": False, "forecast_bytes_changed": False,
        "holdout_value_pages_read": 0, "model_fits_performed": 0,
        "failure_state_sha256": hash_file(contract.run_path(experiment, run_id, "state.json")),
        "failure_message": state["message"], "checkpoint_receipt_hashes": receipts,
        "checkpoint_counts": {k: state[k] for k in ("completed_units", "completed_native_contexts",
                                                      "completed_issue_states", "completed_score_days")}})
    atomic_json(inside(experiment, repair_path(run_id)), record, immutable=True)
    return record


def provenance(experiment, run_id, repair):
    relative = repair_path(run_id)
    return {"repair_id": REPAIR_ID, "manifest_path": relative,
            "manifest_sha256": hash_file(inside(experiment, relative)),
            "manifest_record_sha256": repair["record_sha256"],
            "baseline_binding_sha256": repair["baseline_binding_sha256"],
            "numeric_metrics_changed": False, "forecast_bytes_changed": False}


@contextmanager
def installed(project, experiment, run_id):
    original, checks, _ = baseline(project, experiment, run_id)
    repair = verify_repair(experiment, run_id, original, checks)
    proof = provenance(experiment, run_id, repair)
    existing_units = {Path(p).stem for p in repair["checkpoint_receipt_hashes"]}
    metric_function, preflight_function = scoring.law_metrics, contract.preflight
    base_store = workflow.UnitStore

    def guarded_preflight(p, e):
        ready = preflight_function(p, e)
        verify_repair(e, run_id, original, repair_checks(e))
        if workflow.binding(e, ready, workflow.development_plan()) != original["binding"]:
            raise ContractError("baseline binding changed after serialization repair")
        return ready

    class RepairStore(base_store):
        def verify_bundle(self, body, unit, deps):
            super().verify_bundle(body, unit, deps)
            if unit == "development-scorecard" or (unit.startswith("score-") and unit not in existing_units):
                if body["extra_artifacts"].get(proof["manifest_path"]) != proof["manifest_sha256"]:
                    raise ContractError("post-repair verification unit does not bind its repair manifest")
            if unit == "development-scorecard" and body["result"].get("implementation_repairs") != [proof]:
                raise ContractError("final scorecard lacks the exact repair provenance")

        def commit(self, unit, result, deps, active_seconds, extra=None):
            if unit == "development-scorecard" or unit.startswith("score-"):
                extra = {**(extra or {}), proof["manifest_path"]: proof["manifest_sha256"]}
            if unit == "development-scorecard":
                result = {**result, "implementation_repairs": [proof]}
            return super().commit(unit, result, deps, active_seconds, extra)

    with patch.object(scoring, "law_metrics", lambda *a, **kw: boolean_metrics(metric_function, *a, **kw)), \
         patch.object(workflow, "UnitStore", RepairStore), \
         patch.object(workflow, "preflight", guarded_preflight), \
         patch.object(contract, "preflight", guarded_preflight), \
         patch.object(cli, "preflight", guarded_preflight):
        yield repair


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    experiment = Path(__file__).resolve().parents[2]
    project = experiment.parents[2]
    try:
        command = argv[0] if argv else ""
        if command in {"prepare-t04-serialization-repair", "repair-preflight"}:
            parser = argparse.ArgumentParser()
            parser.add_argument("command", choices=("prepare-t04-serialization-repair", "repair-preflight"))
            parser.add_argument("--run-id", required=True)
            args = parser.parse_args(argv)
            if command == "prepare-t04-serialization-repair":
                record = prepare(project, experiment, args.run_id)
                value = {"status": "SERIALIZATION_REPAIR_PREPARED", "manifest_path": repair_path(args.run_id),
                         "record_sha256": record["record_sha256"], "checkpoint_counts": record["checkpoint_counts"],
                         "completed_work_discarded": 0, "model_fits_performed": 0, "holdout_value_pages_read": 0}
            else:
                with installed(project, experiment, args.run_id) as repair:
                    value = {**cli.preflight(project, experiment), "serialization_repair_id": REPAIR_ID,
                             "serialization_repair_record_sha256": repair["record_sha256"]}
            print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
            return 0
        allowed = {"resume-t04", "validate-t04", "t04-status", "t04-eta", "t04-live-status",
                   "pause-t04", "stop-t04", "recover-t04-lock", "t04-report", "prepare-t04-decision", "lock-t04"}
        if command not in allowed:
            raise ContractError("repair entry point supports existing-run recovery, not new replay or holdout work")
        if "--run-id" in argv:
            run_id = argv[argv.index("--run-id") + 1]
        elif command == "recover-t04-lock":
            return cli.main(argv)
        else:
            run_id = verify_record(read_json(inside(experiment, contract.PASS)))["run_id"]
        # Read-only controls and cooperative pause retain the original lightweight interface.
        if command in {"t04-status", "t04-eta", "t04-live-status", "pause-t04", "stop-t04"}:
            return cli.main(argv)
        with installed(project, experiment, run_id):
            return cli.main(argv)
    except (ContractError, OSError, ValueError, KeyError, IndexError) as exc:
        print(f"error: {exc}")
        return 2
