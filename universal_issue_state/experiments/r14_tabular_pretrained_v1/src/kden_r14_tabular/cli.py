"""T01 owner controls. No neural imports, downloads, or holdout-opening command."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .common import ContractError, atomic_json, inside, read_json
from .foundation import (PASS_REL, preflight, run_path, run_t01, validate_t01)


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # uncertain ownership is not evidence that recovery is safe
    return True


def snapshot(experiment, run_id):
    state = read_json(run_path(experiment, run_id, "state.json"))
    alive = process_alive(state.get("pid"))
    status = state["status"]
    if status == "RUNNING":
        if not alive:
            status = "INTERRUPTED_PROCESS_NOT_ALIVE"
        elif run_path(experiment, run_id, "pause.request.json").exists():
            status = "PAUSE_REQUESTED"
    count, total, active = state["completed_inputs"], state["total_inputs"], state["active_seconds"]
    remaining = None
    if status == "RUNNING" and count >= 16 and active > 0:
        remaining = (total - count) / (count / active)
    return {**state, "observed_status": status, "process_alive": alive,
            "eta_seconds": remaining,
            "eta_basis": "active-time input-binding rate; file costs differ, so this is approximate" if remaining is not None else "unavailable or terminal",
            "pass_exists": inside(experiment, PASS_REL).exists()}


def recover_lock(experiment):
    lock = inside(experiment, "runs/T01_RUNNING.lock")
    if not lock.exists():
        return {"status": "NO_LOCK"}
    record = read_json(lock)
    if process_alive(record.get("pid")):
        raise ContractError("lock process still exists; recovery refuses to remove its lock")
    # Re-read before removing so a changed lock cannot be recovered by mistake.
    if read_json(lock) != record:
        raise ContractError("lock changed during recovery")
    lock.unlink()
    return {"status": "STALE_LOCK_RECOVERED", "run_id": record["run_id"],
            "removed": "runs/T01_RUNNING.lock", "input_or_checkpoint_files_removed": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    default_experiment = Path(__file__).resolve().parents[2]
    for name in ["t01-preflight", "run-t01", "resume-t01", "validate-t01", "t01-status",
                 "t01-live-status", "t01-eta", "pause-t01", "recover-t01-lock"]:
        p = commands.add_parser(name)
        p.add_argument("--project-root", type=Path, default=default_experiment.parents[2])
        p.add_argument("--experiment-root", type=Path, default=default_experiment)
        if name in {"run-t01", "resume-t01", "t01-status", "t01-live-status", "t01-eta", "pause-t01"}:
            p.add_argument("--run-id", required=True)
        if name == "validate-t01":
            p.add_argument("--deep", action="store_true", help="Owner-run rehash of original input bytes")
        if name == "t01-live-status":
            p.add_argument("--interval-seconds", type=float, default=5)
    args = parser.parse_args(argv)
    project, experiment = args.project_root.resolve(), args.experiment_root.resolve()
    try:
        if experiment != inside(project, "universal_issue_state/experiments/r14_tabular_pretrained_v1"):
            raise ContractError("all experiment writes must stay at the declared KDEN location")
        if args.command == "t01-preflight":
            result = preflight(project, experiment)
        elif args.command in {"run-t01", "resume-t01"}:
            if args.command == "resume-t01":
                state = read_json(run_path(experiment, args.run_id, "state.json"))
                if process_alive(state.get("pid")) or inside(experiment, "runs/T01_RUNNING.lock").exists():
                    raise ContractError("run or lock is still active; inspect before resuming")
                run_path(experiment, args.run_id, "pause.request.json").unlink(missing_ok=True)
            result = run_t01(project, experiment, args.run_id)
        elif args.command == "validate-t01":
            result = validate_t01(project, experiment, deep=args.deep)
        elif args.command == "recover-t01-lock":
            result = recover_lock(experiment)
        elif args.command == "pause-t01":
            state = snapshot(experiment, args.run_id)
            if not state["process_alive"] or state["status"] != "RUNNING":
                raise ContractError("no live running T01 process to pause")
            atomic_json(run_path(experiment, args.run_id, "pause.request.json"),
                        {"run_id": args.run_id, "pause_requested": True}, immutable=True)
            result = {"status": "PAUSE_REQUESTED", "run_id": args.run_id,
                      "note": "hash checks stop between files; final PASS is not published while a pause is pending"}
        elif args.command in {"t01-status", "t01-eta"}:
            result = snapshot(experiment, args.run_id)
        else:
            if not 0.2 <= args.interval_seconds <= 60:
                raise ContractError("live-status interval must be between 0.2 and 60 seconds")
            while True:
                result = snapshot(experiment, args.run_id)
                print(f"[{result['updated_at_utc']}] | {result['observed_status']} | phase={result['phase']} | "
                      f"inputs={result['completed_inputs']}/{result['total_inputs']} | "
                      f"ETA-seconds={round(result['eta_seconds']) if result['eta_seconds'] is not None else '-'} | "
                      f"current={result['current_input'] or '-'}", flush=True)
                if result["observed_status"] not in {"RUNNING", "PAUSE_REQUESTED"}:
                    return 0
                time.sleep(args.interval_seconds)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except KeyboardInterrupt:
        print("Interrupted. No incomplete PASS is accepted; inspect status and recover a dead-process lock if needed.")
        return 130
    except (ContractError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
