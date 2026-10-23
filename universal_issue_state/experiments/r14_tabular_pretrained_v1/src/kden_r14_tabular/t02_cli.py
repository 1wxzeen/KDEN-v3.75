"""T02 owner controls: explicit preparation, offline probe and resumable scan."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .cli import process_alive
from .common import ContractError, atomic_json, inside, read_json
from .foundation import EXPERIMENT_REL, validate_t01
from .t02_runtime import download_checkpoints, prepare_environment, probe
from .t02_workflow import preflight, run_path, run_t02, validate_t02


def snapshot(experiment, run_id):
    state = read_json(run_path(experiment, run_id, "state.json"))
    status = state["status"]
    alive = process_alive(state["pid"])
    if status == "RUNNING":
        if not alive: status = "INTERRUPTED_PROCESS_NOT_ALIVE"
        elif run_path(experiment, run_id, "pause.request.json").exists(): status = "PAUSE_REQUESTED"
    elapsed = state["active_seconds"]
    count = state["completed_rows"] + state["inflight_rows"]
    eta = (state["total_rows"] - count) * elapsed / count if status == "RUNNING" and count and elapsed else None
    return {**state, "observed_status": status, "process_alive": alive, "eta_seconds": eta,
            "eta_basis": "approximate active-time transformed-row rate, not neural replay performance" if eta is not None else "unavailable or terminal"}


def recover(experiment):
    result = []
    for rel in ["runs/T02_RUNNING.lock", "runs/T02_PREPARATION.lock"]:
        path = inside(experiment, rel)
        if not path.exists(): continue
        value = read_json(path)
        if process_alive(value["pid"]): raise ContractError("lock process still exists; recovery refuses removal")
        if read_json(path) != value: raise ContractError("lock changed while inspecting")
        path.unlink(); result.append(rel)
    return {"status": "STALE_LOCK_RECOVERED" if result else "NO_LOCK", "removed": result,
            "input_or_checkpoint_files_removed": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    exp = Path(__file__).resolve().parents[2]
    names = ["t02-preflight", "prepare-t02-environment", "download-t02-checkpoints", "probe-t02",
             "run-t02", "resume-t02", "validate-t02", "t02-status", "t02-live-status", "t02-eta",
             "pause-t02", "recover-t02-lock"]
    for name in names:
        p = commands.add_parser(name)
        p.add_argument("--project-root", type=Path, default=exp.parents[2])
        p.add_argument("--experiment-root", type=Path, default=exp)
        if name in {"t02-preflight", "probe-t02", "run-t02", "resume-t02"}:
            p.add_argument("--device", choices=["cpu", "mps", "cuda"], default="cpu")
        if name in {"run-t02", "resume-t02", "t02-status", "t02-live-status", "t02-eta", "pause-t02"}:
            p.add_argument("--run-id", required=True)
        if name == "t02-preflight": p.add_argument("--runtime", action="store_true")
        if name == "t02-live-status": p.add_argument("--interval-seconds", type=float, default=5.)
    args = parser.parse_args(argv)
    project, experiment = args.project_root.resolve(), args.experiment_root.resolve()
    try:
        if experiment != inside(project, EXPERIMENT_REL):
            raise ContractError("all writes must remain in the declared KDEN experiment directory")
        if args.command == "t02-preflight":
            value = preflight(project, experiment, args.device, require_runtime=args.runtime)
        elif args.command in {"prepare-t02-environment", "download-t02-checkpoints", "probe-t02"}:
            validate_t01(project, experiment)
            value = {"prepare-t02-environment": lambda: prepare_environment(experiment),
                     "download-t02-checkpoints": lambda: download_checkpoints(experiment),
                     "probe-t02": lambda: probe(experiment, args.device)}[args.command]()
        elif args.command in {"run-t02", "resume-t02"}:
            if args.command == "resume-t02":
                state = snapshot(experiment, args.run_id)
                if state["process_alive"] or inside(experiment, "runs/T02_RUNNING.lock").exists():
                    raise ContractError("run/lock still active; inspect before resuming")
                run_path(experiment, args.run_id, "pause.request.json").unlink(missing_ok=True)
            value = run_t02(project, experiment, args.run_id, args.device, resume=args.command == "resume-t02")
        elif args.command == "validate-t02": value = validate_t02(project, experiment)
        elif args.command == "recover-t02-lock": value = recover(experiment)
        elif args.command == "pause-t02":
            state = snapshot(experiment, args.run_id)
            if not state["process_alive"] or state["status"] != "RUNNING":
                raise ContractError("no live running T02 process to pause")
            atomic_json(run_path(experiment, args.run_id, "pause.request.json"),
                        {"run_id": args.run_id, "pause_requested": True}, immutable=True)
            value = {"status": "PAUSE_REQUESTED", "note": "checked every 512 rows and before year publication; file reads/hashes finish first"}
        elif args.command in {"t02-status", "t02-eta"}: value = snapshot(experiment, args.run_id)
        else:
            if not 0.2 <= args.interval_seconds <= 60: raise ContractError("invalid status interval")
            while True:
                value = snapshot(experiment, args.run_id)
                print(f"[{value['updated_at_utc']}] | {value['observed_status']} | phase={value['phase']} | "
                      f"years={value['completed_partitions']}/6 | rows={value['completed_rows']}+{value['inflight_rows']}/118536 | "
                      f"year={value['current_year'] or '-'} | ETA-seconds={round(value['eta_seconds']) if value['eta_seconds'] is not None else '-'}",
                      flush=True)
                if value["observed_status"] not in {"RUNNING", "PAUSE_REQUESTED"}: return 0
                time.sleep(args.interval_seconds)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)); return 0
    except KeyboardInterrupt:
        print("Interrupted. No incomplete PASS is accepted; inspect status and recover only a dead-process lock.")
        return 130
    except (ContractError, OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}"); return 2
