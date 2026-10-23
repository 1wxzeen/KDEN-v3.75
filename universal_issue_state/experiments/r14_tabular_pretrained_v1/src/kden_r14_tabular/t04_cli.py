"""Owner-only long development controls; no T05 or holdout-opening command."""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from .cli import process_alive
from .common import ContractError, atomic_json, inside, read_json, signed, utc_now, verify_record
from .foundation import EXPERIMENT_REL, isolation_check
from .t04_contract import CHECKS, PASS, LOCK, counts, decision, identity, lock_recipe, preflight, run_path
from .t04_workflow import run_t04, validate_t04


def snapshot(experiment,run_id):
    state=read_json(run_path(experiment,run_id,"state.json"))
    alive=process_alive(state["pid"]); status=state["status"]
    if status=="RUNNING":
        if not alive: status="INTERRUPTED_PROCESS_NOT_ALIVE"
        elif run_path(experiment,run_id,"pause.request.json").exists(): status="PAUSE_REQUESTED"
    total=counts(); costs=state["unit_costs"]
    native_done=state["completed_native_contexts"]
    # The plan is minute-major, tabicl then tabdpt, including after restart.
    remaining={"native_tabicl":total["native_contexts"]//2-(native_done+1)//2,
               "native_tabdpt":total["native_contexts"]//2-native_done//2,
               "day":total["correction_days"]-state["completed_score_days"],
               "score":total["score_days"]-state["completed_score_days"]}
    # A forecast day may be committed while its score is in progress.
    if state["current_unit"] and state["current_unit"].startswith("score-"):
        remaining["day"]=max(0,remaining["day"]-1)
    missing=[k for k,n in remaining.items() if n and not costs.get(k)]
    eta=None
    if status=="RUNNING" and not missing:
        means={k:sum(v)/len(v) for k,v in costs.items() if v}
        eta=sum(n*means[k] for k,n in remaining.items() if n)
    if status=="PASS": eta=0.
    now=datetime.now(UTC)
    finish=(now+timedelta(seconds=eta)).isoformat().replace("+00:00","Z") if eta is not None else None
    return {**state,"observed_status":status,"process_alive":alive,"observed_at_utc":utc_now(),
            "eta_seconds":eta,"estimated_completion_utc":finish,"unmeasured_remaining_unit_classes":missing,
            "remaining_units_by_class":remaining,
            "eta_basis":"RECENT_COMPLETED_UNIT_ACTIVE_COSTS_LAST_14_PER_CLASS; IN_FLIGHT_INCLUDED_CONSERVATIVELY",
            "eta_note":"Forecast/calibration cost varies on Mondays and grows with history; final report/reverification not projected. Estimate is not a deadline. Paused wall time is excluded.",
            "inflight_active_seconds":max(0.,state["active_seconds"]-state["current_unit_started_active_seconds"]) if state["current_unit"] else 0.,
            "recipe_locked":inside(experiment,LOCK).exists(),"holdout_value_pages_read":0}


def recover(experiment):
    path=inside(experiment,"runs/T04_RUNNING.lock")
    if not path.exists(): return {"status":"NO_LOCK"}
    old=read_json(path)
    if process_alive(old["pid"]): raise ContractError("process still exists; refusing lock recovery")
    if read_json(path)!=old: raise ContractError("lock changed during inspection")
    path.unlink()
    return {"status":"STALE_LOCK_RECOVERED","removed":"runs/T04_RUNNING.lock","forecast_or_input_files_removed":0}


def check(experiment):
    if inside(experiment,PASS).exists(): raise ContractError("T04 already accepted; check receipt is frozen")
    before=identity(experiment); env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",PYTHONNOUSERSITE="1")
    temp=inside(experiment,".cache/tmp"); temp.mkdir(parents=True,exist_ok=True); env["TMPDIR"]=str(temp); env.pop("PYTHONPATH",None)
    begin=time.monotonic()
    child=subprocess.run([sys.executable,"-B","-m","unittest","discover","-s",str(inside(experiment,"tests")),
                          "-p","test_t04.py","-v"],capture_output=True,text=True,env=env,cwd=experiment,timeout=60)
    output=child.stdout+child.stderr; print(output,file=sys.stderr)
    match=re.search(r"Ran (\d+) tests",output)
    if child.returncode or not match or identity(experiment)!=before: raise ContractError("short T04 tests failed or code changed")
    value=signed({"stage":"T04_IMPLEMENTATION_CHECKS","status":"PASS","code_identity":before,
                  "synthetic_tests_run":int(match[1]),"failures":0,"errors":0,"active_seconds":time.monotonic()-begin,
                  "study_model_fits_performed":0,"holdout_value_pages_read":0,"network_requests_made":0,
                  "runtime_isolation":isolation_check(experiment)})
    path=inside(experiment,CHECKS)
    if path.exists():
        old=verify_record(read_json(path))
        if old["code_identity"]!=before: raise ContractError("check receipt binds different code; no overwrite")
        return old
    atomic_json(path,value,immutable=True); return value


def report(experiment):
    passed=verify_record(read_json(inside(experiment,PASS)))
    from .common import hash_file
    if hash_file(inside(experiment,passed["report_path"]))!=passed["report_sha256"]: raise ContractError("accepted scorecard changed")
    value=verify_record(read_json(inside(experiment,passed["report_path"])))["result"]
    return {"status":"DEVELOPMENT_REPORT","development_record_sha256":passed["record_sha256"],
            "report_path":passed["report_path"],"development_nomination":value["scorecard"]["development_nomination"],
            "primary_window_owner_confirmed_02_14":value["scorecard"]["windows"]["PRIMARY_02_14"],
            "first_supported_date":value["scorecard"]["first_supported_date"],"holdout_scores_computed":False,
            "recipe_locked":inside(experiment,LOCK).exists()}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); commands=parser.add_subparsers(dest="command",required=True)
    exp=Path(__file__).resolve().parents[2]
    names=("check-t04","t04-preflight","run-t04","resume-t04","validate-t04","t04-status","t04-eta",
           "t04-live-status","pause-t04","stop-t04","recover-t04-lock","t04-report","prepare-t04-decision","lock-t04")
    for name in names:
        p=commands.add_parser(name); p.add_argument("--project-root",type=Path,default=exp.parents[2]); p.add_argument("--experiment-root",type=Path,default=exp)
        if name in {"run-t04","resume-t04","t04-status","t04-eta","t04-live-status","pause-t04","stop-t04"}: p.add_argument("--run-id",required=True)
        if name=="t04-live-status": p.add_argument("--interval-seconds",type=float,default=5.)
        if name=="lock-t04": p.add_argument("--decision-file",required=True,help="experiment-relative owner decision JSON")
        if name=="prepare-t04-decision":
            p.add_argument("--candidate",choices=("KDEN_TABICL_T3","KDEN_TABDPT_D2_NATIVE"),required=True)
            p.add_argument("--rationale",required=True)
            p.add_argument("--confirm-proposed-limits",action="store_true",required=True,
                           help="explicitly approve hit≥.30, MAE≤1.15, RMSE≤1.70, NLL≤1.85, complete days≥300, support≥.95; primary window is owner-confirmed 02–14")
    args=parser.parse_args(argv); project,experiment=args.project_root.resolve(),args.experiment_root.resolve()
    try:
        if experiment!=inside(project,EXPERIMENT_REL): raise ContractError("T04 writes must stay inside the declared experiment")
        c=args.command
        if c=="check-t04": value=check(experiment)
        elif c=="t04-preflight": value=preflight(project,experiment)
        elif c in {"run-t04","resume-t04"}:
            if c=="resume-t04" and snapshot(experiment,args.run_id)["process_alive"]: raise ContractError("cannot resume a live process")
            value=run_t04(project,experiment,args.run_id,resume=c=="resume-t04")
        elif c=="validate-t04": value=validate_t04(project,experiment)
        elif c=="recover-t04-lock": value=recover(experiment)
        elif c=="t04-report": value=report(experiment)
        elif c=="prepare-t04-decision":
            # Decision preparation is not recipe locking. Refuse to prepare selection before accepted development evidence.
            report(experiment)
            v=read_json(inside(experiment,"config/decision_t04_proposal.json"))
            v.update(owner_confirmed=True,selected_operational_candidate=args.candidate,selection_rationale=args.rationale)
            decision(v); path="reports/T04_OWNER_DECISION_APPROVED.json"
            atomic_json(inside(experiment,path),v,immutable=True)
            value={"status":"OWNER_DECISION_PREPARED","decision_file":path,"recipe_locked":False}
        elif c=="lock-t04": value=lock_recipe(project,experiment,args.decision_file)
        elif c in {"pause-t04","stop-t04"}:
            state=snapshot(experiment,args.run_id)
            if not state["process_alive"] or state["status"]!="RUNNING": raise ContractError("no live running T04 process")
            path=run_path(experiment,args.run_id,"pause.request.json")
            atomic_json(path,{"run_id":args.run_id,"pause_requested":True},immutable=True)
            value={"status":"PAUSE_REQUESTED","note":"cooperative pause after the current complete native/calibration/scoring unit; not immediate termination"}
        elif c in {"t04-status","t04-eta"}: value=snapshot(experiment,args.run_id)
        else:
            if not .2<=args.interval_seconds<=60: raise ContractError("invalid refresh interval")
            while True:
                value=snapshot(experiment,args.run_id); eta=value["eta_seconds"]
                if eta is None: formatted="unavailable"
                else:
                    seconds=max(0,int(eta)); days,seconds=divmod(seconds,86400); hours,seconds=divmod(seconds,3600); minutes,_=divmod(seconds,60)
                    formatted=f"{days}d {hours}h {minutes}m"
                print(f"[{value['observed_at_utc']}] | {value['observed_status']} | {value['phase']} | "
                      f"units={value['completed_units']}/{value['total_units']} | contexts={value['completed_native_contexts']}/5130 | "
                      f"issues={value['completed_issue_states']}/76649 | scored-days={value['completed_score_days']}/1345 | "
                      f"current={value['current_unit'] or '-'} | ETA={formatted}",flush=True)
                if value["observed_status"] not in {"RUNNING","PAUSE_REQUESTED"}: return 0
                time.sleep(args.interval_seconds)
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)); return 0
    except KeyboardInterrupt:
        print("Interrupted; committed outputs are preserved. Inspect status; recover only a dead-process lock, then resume."); return 130
    except (ContractError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}"); return 2
