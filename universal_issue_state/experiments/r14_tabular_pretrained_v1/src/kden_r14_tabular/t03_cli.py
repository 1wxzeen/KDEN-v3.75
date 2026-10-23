"""Owner controls for fixed bounded T03 acceptance, not full development replay."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from .cli import process_alive
from .common import ContractError, atomic_json, inside, read_json, signed, utc_now
from .foundation import EXPERIMENT_REL, isolation_check
from .replay import bounded_plan, identity, native_unit, run_path
from .t03_workflow import CHECKS, PASS, preflight, run_t03, validate_t03


def snapshot(experiment,run_id):
    state = read_json(run_path(experiment,run_id,"state.json"))
    alive = process_alive(state["pid"]); status = state["status"]
    if status=="RUNNING":
        if not alive: status = "INTERRUPTED_PROCESS_NOT_ALIVE"
        elif run_path(experiment,run_id,"pause.request.json").exists(): status = "PAUSE_REQUESTED"
    costs = {}
    for r in state["unit_costs"]: costs.setdefault(r["kind"],[]).append(r["active_seconds"])
    completed = set(state["completed_unit_ids"]); pending = []
    for block in bounded_plan():
        for m in block["minutes"]:
            for name in ("tabicl","tabdpt"):
                if native_unit(block,m,name) not in completed: pending.append("native_"+name)
        pending += ["day" for d in block["query_dates"] if "day-"+d not in completed]
    # Report cost is short and its missing first sample should not conceal native ETA.
    known = [sum(costs[k][-3:])/len(costs[k][-3:]) for k in pending if k in costs]
    missing = sorted(set(pending)-set(costs))
    eta = sum(known) if status=="RUNNING" and not missing and costs else None
    if status=="PASS": eta = 0.
    return {**state,"observed_status":status,"process_alive":alive,"observed_at_utc":utc_now(),
            "eta_seconds":eta,"unmeasured_remaining_unit_classes":missing,
            "eta_basis":"recent completed atomic-unit active costs; current unit included conservatively; paused/stalled wall time is not a rate denominator",
            "note":"Bounded T03 ETA only. Slow in-flight calls can exceed prior samples. No full-replay ETA is claimed."}


def recover(experiment):
    path = inside(experiment,"runs/T03_RUNNING.lock")
    if not path.exists(): return {"status":"NO_LOCK"}
    old = read_json(path)
    if process_alive(old["pid"]): raise ContractError("lock process still exists; refusing recovery")
    if read_json(path)!=old: raise ContractError("lock changed during inspection")
    path.unlink()
    return {"status":"STALE_LOCK_RECOVERED","removed":"runs/T03_RUNNING.lock","forecast_or_input_files_removed":0}


def check(experiment):
    if inside(experiment,PASS).exists(): raise ContractError("T03 accepted; do not replace implementation-check receipt")
    before = identity(experiment); env = dict(os.environ,PYTHONDONTWRITEBYTECODE="1",PYTHONNOUSERSITE="1")
    # The T02-prepared mutable cache keeps owner-test scratch inside the experiment.
    temp = inside(experiment,".cache/tmp"); temp.mkdir(parents=True,exist_ok=True); env["TMPDIR"] = str(temp)
    env.pop("PYTHONPATH",None)
    begin = time.monotonic()
    child = subprocess.run([sys.executable,"-B","-m","unittest","discover","-s",str(inside(experiment,"tests")),
                            "-p","test_t03.py","-v"],capture_output=True,text=True,env=env,cwd=experiment,timeout=60)
    output = child.stdout+child.stderr
    print(output,file=sys.stderr)
    if child.returncode!=0: raise ContractError("short T03 checks failed; no check receipt published")
    import re
    match = re.search(r"Ran (\d+) tests",output)
    if not match or identity(experiment)!=before: raise ContractError("check suite count/code identity missing or changed")
    value = signed({"status":"PASS","stage":"T03_IMPLEMENTATION_CHECKS","code_identity":before,
                    "synthetic_tests_run":int(match[1]),"failures":0,"errors":0,"active_seconds":time.monotonic()-begin,
                    "model_fits_performed":0,"holdout_value_pages_read":0,"network_requests_made":0,
                    "runtime_isolation":isolation_check(experiment)})
    # Before acceptance, same code may have different measured test duration.
    path = inside(experiment,CHECKS)
    if path.exists():
        old = read_json(path)
        if old["code_identity"]==before: return old
        raise ContractError("existing checks bind other code; use a new release rather than overwrite")
    atomic_json(path,value,immutable=True); return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="command",required=True)
    exp = Path(__file__).resolve().parents[2]
    names = ["check-t03","t03-preflight","run-t03","resume-t03","validate-t03","t03-status","t03-eta",
             "t03-live-status","pause-t03","stop-t03","recover-t03-lock"]
    for name in names:
        p = commands.add_parser(name); p.add_argument("--project-root",type=Path,default=exp.parents[2]); p.add_argument("--experiment-root",type=Path,default=exp)
        if name in {"run-t03","resume-t03","t03-status","t03-eta","t03-live-status","pause-t03","stop-t03"}: p.add_argument("--run-id",required=True)
        if name=="t03-live-status": p.add_argument("--interval-seconds",type=float,default=5.)
    args = parser.parse_args(argv); project,experiment = args.project_root.resolve(),args.experiment_root.resolve()
    try:
        if experiment!=inside(project,EXPERIMENT_REL): raise ContractError("all writes must remain in the declared KDEN experiment")
        command = args.command
        if command=="check-t03": value = check(experiment)
        elif command=="t03-preflight": value = preflight(project,experiment)
        elif command in {"run-t03","resume-t03"}:
            if command=="resume-t03":
                state = snapshot(experiment,args.run_id)
                if state["process_alive"]: raise ContractError("run process still exists; cannot resume concurrently")
            value = run_t03(project,experiment,args.run_id,resume=command=="resume-t03")
        elif command=="validate-t03": value = validate_t03(project,experiment)
        elif command=="recover-t03-lock": value = recover(experiment)
        elif command in {"pause-t03","stop-t03"}:
            state = snapshot(experiment,args.run_id)
            if state["status"]!="RUNNING" or not state["process_alive"]: raise ContractError("no live running T03 process to stop/pause")
            atomic_json(run_path(experiment,args.run_id,"pause.request.json"),{"run_id":args.run_id,"pause_requested":True},immutable=True)
            value = {"status":"PAUSE_REQUESTED","note":"stop and pause are cooperative at a complete native/correction unit; active inference finishes before publication/pause"}
        elif command in {"t03-status","t03-eta"}: value = snapshot(experiment,args.run_id)
        else:
            if not .2<=args.interval_seconds<=60: raise ContractError("invalid live-status interval")
            while True:
                value = snapshot(experiment,args.run_id)
                eta = round(value["eta_seconds"]) if value["eta_seconds"] is not None else "unavailable"
                print(f"[{value['observed_at_utc']}] | {value['observed_status']} | phase={value['phase']} | "
                      f"units={value['completed_units']}/{value['total_units']} | contexts={value['completed_native_contexts']}/4 | "
                      f"issues={value['completed_issue_states']}/4 | current={value['current_unit'] or '-'} | ETA-seconds={eta}",flush=True)
                if value["observed_status"] not in {"RUNNING","PAUSE_REQUESTED"}: return 0
                time.sleep(args.interval_seconds)
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)); return 0
    except KeyboardInterrupt:
        print("Interrupted; committed units remain immutable. Inspect status, recover only a dead-process lock, then resume."); return 130
    except (ContractError,OSError,KeyError,ValueError,subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}"); return 2
