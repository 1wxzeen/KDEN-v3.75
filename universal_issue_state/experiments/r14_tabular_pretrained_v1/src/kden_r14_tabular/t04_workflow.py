"""Owner-run full development replay: forecast commit, then separate scoring.

Accepted T03 model/law/update mechanics are reused, not rewritten. T04 units use
the existing immutable bundle/receipt protocol; T04 has its own state and PASS.
"""
from __future__ import annotations
import json
import os
import threading
import time
from collections import Counter
from .common import ContractError, atomic_json, canonical, check_document, digest, hash_file, inside, read_json, signed, utc_now, verify_record
from .cli import process_alive
from .dates import DENVER, issue_times, parse_date
from .features import FeatureStore, stamp
from .truth import TruthAccess
from .replay import UnitStore, development_plan, native_unit, process_native, process_day, publish_day, check_prediction, check_coefficients, check_query
from .t02_runtime import no_network
from .t04_contract import PASS, LOCK, counts, identity, preflight, run_path, scoring_policy
from .t04_history import FullHistory, fit_coefficients
from .t04_scoring import KernelCache, Scorecard, feature_tags, regime_cutoffs, score_day


class Paused(Exception): pass


class LiveState:
    def __init__(self,experiment,run_id,state):
        self.experiment,self.run_id,self.state=experiment,run_id,state
        self.started,self.prior=time.monotonic(),state.get("active_seconds",0.)
        self.mutex,self.stop,self.error=threading.RLock(),threading.Event(),None
        self.thread=threading.Thread(target=self.heartbeat,daemon=True)
    def elapsed(self): return self.prior+time.monotonic()-self.started
    def write(self,**fields):
        with self.mutex:
            self.state.update(fields,active_seconds=self.elapsed(),updated_at_utc=utc_now())
            check_document(self.experiment,"t04_state",self.state)
            atomic_json(run_path(self.experiment,self.run_id,"state.json"),self.state)
    def heartbeat(self):
        while not self.stop.wait(2.):
            try: self.write()
            except Exception as exc: self.error=exc; self.stop.set()
    def check_pause(self):
        if self.error is not None: raise ContractError("monitoring writer failed") from self.error
        if run_path(self.experiment,self.run_id,"pause.request.json").exists(): raise Paused()
    def begin(self,phase,unit):
        self.check_pause(); self.write(phase=phase,current_unit=unit,current_unit_started_active_seconds=self.elapsed())
    def done(self,kind,body,*,contexts=0,issues=0,score_days=0):
        with self.mutex:
            values=self.state["unit_costs"].setdefault(kind,[])
            values.append(body["active_seconds"]); values[:]=values[-14:]
            self.write(completed_units=self.state["completed_units"]+1,
                       completed_native_contexts=self.state["completed_native_contexts"]+contexts,
                       completed_issue_states=self.state["completed_issue_states"]+issues,
                       completed_score_days=self.state["completed_score_days"]+score_days,
                       current_unit=None,current_unit_started_active_seconds=self.elapsed())
    def close(self,status,message):
        self.stop.set()
        if self.thread.is_alive(): self.thread.join()
        self.write(status=status,message=message,pid=None,current_unit=None,
                   phase="COMPLETE" if status=="PASS" else self.state["phase"])


def binding(experiment,ready,plan):
    t01=verify_record(read_json(inside(experiment,"manifests/T01_PASS.json")))
    t02=verify_record(read_json(inside(experiment,"manifests/T02_PASS.json")))
    t03=verify_record(read_json(inside(experiment,"manifests/T03_PASS.json")))
    return {k:ready[k] for k in ("t03_record_sha256","t03_binding_sha256","device","code_identity",
                                "implementation_checks_sha256","scoring_policy_sha256")} | {
        "plan":plan,"scope":"FULL_DEVELOPMENT_ONLY_2022_2025", "t01_record_sha256":t01["record_sha256"],
        "t02_record_sha256":t02["record_sha256"],"t01_code_identity":t01["code_identity"],
        "t01_artifact_hashes":t01["artifact_hashes"],"t02_binding":t02["binding"] if "binding" in t02 else
            {k:t02[k] for k in ("source_bindings","runtime_identity","code_identity")},
        "t03_binding":t03["binding"],"exposure_ledger_sha256":hash_file(inside(experiment,"inputs/exposure_ledger.json")),
        "truth_audit_contract_sha256":hash_file(inside(experiment,"inputs/truth/adapter_contract.json")),
        "scientific_recipe_sha256":hash_file(inside(experiment,"config/replay.json")),
        "feature_order_sha256":hash_file(inside(experiment,"config/features.json")),
        "checkpoint_contract_sha256":hash_file(inside(experiment,"config/checkpoints.json")),
        "date_contract_sha256":hash_file(inside(experiment,"config/experiment.json")),
        "query_invariance_evidence":"ACCEPTED_T03_EARLY_AND_LATE_REAL_CONTEXTS; NO_EXTRA_FULL_REPLAY_SINGLETON_PROBES"}


def checked_forecast_keys(experiment,result,block):
    import pyarrow.parquet as pq
    day=parse_date(result["target_date"])
    if str(day) not in block["query_dates"]: raise ContractError("forecast outside development block")
    commit=verify_record(read_json(inside(experiment,result["forecast_commit_path"])))
    check_document(experiment,"forecast_commit",commit)
    if (commit["artifact_path"]!=result["forecast_path"] or commit["target_dates"]!=[str(day)]
        or commit["artifact_sha256"]!=hash_file(inside(experiment,result["forecast_path"]))):
        raise ContractError("daily forecast commit mismatch")
    rows=pq.ParquetFile(inside(experiment,result["forecast_path"])).read().to_pylist()
    expected=set(issue_times(day))
    if len(rows)!=len(expected) or len({r["issue_state_id"] for r in rows})!=len(rows): raise ContractError("incomplete/duplicate daily issue grid")
    actual=set()
    for row in rows:
        pred=json.loads(row["prediction_json"]); check_prediction(pred); check_document(experiment,"t03_predictions",pred)
        if any(row[k]!=pred[k] for k in ("issue_state_id","target_date","issue_time_utc")) or pred["native_block_id"]!=block["block_id"]:
            raise ContractError("daily forecast provenance/key mismatch")
        actual.add(stamp(pred["issue_time_utc"]))
    if actual!=expected or result["issue_states"]!=len(expected): raise ContractError("DST-aware forecast clock grid differs")
    check_coefficients(result["coefficients"],block,day)


def replay(experiment,run_id,b,live,store,truth):
    units=UnitStore(experiment,run_id,b); history=FullHistory(experiment)
    entries=[]; previous=None; fits=0; score_results=[]; unit_seconds=Counter()
    def done(unit,kind,found,**kw):
        body,receipt=found
        unit_seconds[kind]+=body["active_seconds"]
        entries.append({"unit_id":unit,"path":units.paths(unit)[1],"sha256":hash_file(inside(experiment,units.paths(unit)[1])),
                        "record_sha256":receipt["record_sha256"]})
        live.done(kind,body,**kw)
        return body,receipt
    live.begin("DEVELOPMENT_PREDICTOR_REGIME_CUTOFFS","regime-cutoffs")
    found=units.read("regime-cutoffs",[])
    if found is None:
        begin=time.monotonic(); found=units.commit("regime-cutoffs",regime_cutoffs(store),[],time.monotonic()-begin)
    regime_body,regime_receipt=done("regime-cutoffs","regime",found)
    cutoffs=regime_body["result"]; policy=scoring_policy(experiment)
    for block in b["plan"]:
        native_units={}; cache=KernelCache()
        for minute in block["minutes"]:
            for name in ("tabicl","tabdpt"):
                unit=native_unit(block,minute,name); live.begin("NATIVE_MONTHLY_CONTEXTS",unit)
                found=units.read(unit,[])
                if found is None:
                    begin=time.monotonic()
                    value=process_native(experiment,store,truth,block,minute,name,b["device"],check_invariance=False)
                    found=units.commit(unit,value,[],time.monotonic()-begin)
                body,receipt=done(unit,"native_"+name,found,contexts=1)
                native_units[name,minute]=found; fits+=body["result"]["context_fits_performed"]
        monthly,weekly=None,None
        for i,target in enumerate(block["query_dates"]):
            day=parse_date(target); unit="day-"+target
            deps=[p[1]["record_sha256"] for p in native_units.values()]+([previous] if previous else [])
            live.begin("CHRONOLOGICAL_CORRECTION_AND_FORECAST_COMMIT",unit)
            found=units.read(unit,deps)
            if found is None:
                begin=time.monotonic()
                coefficients=fit_coefficients(history,truth,day,monthly,weekly,block_start=i==0)
                forecasts,history_rows=process_day(native_units,block,day,coefficients)
                result,extra=publish_day(experiment,run_id,day,forecasts,history_rows,coefficients,digest(b))
                checked_forecast_keys(experiment,result,block)
                found=units.commit(unit,result,deps,time.monotonic()-begin,extra)
            body,receipt=done(unit,"day",found,issues=body_issue_count(found))
            monthly,weekly=body["result"]["coefficients"]["monthly"],body["result"]["coefficients"]["weekly"]
            history.add(body,receipt); previous=receipt["record_sha256"]
            score_unit="score-"+target; score_deps=[previous,regime_receipt["record_sha256"]]
            live.begin("SEPARATE_COMMITTED_DEVELOPMENT_VERIFICATION",score_unit)
            scored=units.read(score_unit,score_deps)
            if scored is None:
                begin=time.monotonic()
                value=score_day(experiment,truth,day,body["result"],native_units,policy,feature_tags(store,day,cutoffs),cache)
                check_document(experiment,"t04_score",value)
                scored=units.commit(score_unit,value,score_deps,time.monotonic()-begin)
            score_body,score_receipt=done(score_unit,"score",scored,score_days=1)
            score_results.append((units.paths(score_unit)[0],score_receipt["bundle_sha256"]))
        history.native.cache_clear()
    live.begin("DEVELOPMENT_SCORECARD","development-scorecard")
    deps=[r["record_sha256"] for r in entries]
    found=units.read("development-scorecard",deps)
    if found is None:
        begin=time.monotonic(); card=Scorecard(policy)
        for path,sha in score_results:
            live.check_pause()
            if hash_file(inside(experiment,path))!=sha: raise ContractError("verification bundle changed during reporting")
            value=verify_record(read_json(inside(experiment,path)))["result"]
            check_document(experiment,"t04_score",value); card.add(value)
        value={"scorecard":card.result(),"regime_cutoffs":cutoffs,"counts":counts(b["plan"]),
               "completed_context_fits":fits,"unit_active_seconds":dict(unit_seconds),
               "cost_note":"Sum of original completed unit active costs, including restored units; replay restart verification and final report overhead are additional run active time",
               "holdout_value_pages_read":0,"no_holdout_or_market_outcomes_used":True,
               "recipe_lock_created":False,"decision_proposal_path":"config/decision_t04_proposal.json"}
        found=units.commit("development-scorecard",value,deps,time.monotonic()-begin)
    done("development-scorecard","report",found)
    return entries,units.paths("development-scorecard")[0],fits


def body_issue_count(found): return found[0]["result"]["issue_states"]


def run_t04(project,experiment,run_id,*,resume=False):
    ready=preflight(project,experiment); b=binding(experiment,ready,development_plan())
    path=run_path(experiment,run_id,"identity.json")
    if inside(experiment,PASS).exists():
        passed=verify_record(read_json(inside(experiment,PASS)))
        if passed["run_id"]!=run_id or passed["binding"]!=b: raise ContractError("development accepted under another run/binding; no replacement")
        return {"status":"ALREADY_PASS","record_sha256":passed["record_sha256"],"note":"use validate-t04; no replay rerun"}
    if path.exists():
        if not resume or verify_record(read_json(path))["binding"]!=b: raise ContractError("resume required with unchanged identity")
    elif resume: raise ContractError("resume requires an existing T04 identity")
    else: atomic_json(path,signed({"binding":b}),immutable=True)
    lock=inside(experiment,"runs/T04_RUNNING.lock"); lock.parent.mkdir(parents=True,exist_ok=True)
    try: fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError as exc: raise ContractError("T04 lock exists; recover only after its process is dead") from exc
    with os.fdopen(fd,"w") as stream:
        stream.write(canonical({"pid":os.getpid(),"run_id":run_id}).decode()); stream.flush(); os.fsync(stream.fileno())
    live=None
    try:
        old=read_json(run_path(experiment,run_id,"state.json")) if resume and run_path(experiment,run_id,"state.json").exists() else {}
        if old and old["identity_sha256"]!=digest(b): raise ContractError("state binds changed code/inputs")
        run_path(experiment,run_id,"pause.request.json").unlink(missing_ok=True)
        state={"schema_version":"R14_TABULAR_T04_STATE_V1","run_id":run_id,"status":"RUNNING","pid":os.getpid(),
               "phase":"VERIFYING_COMPLETED_UNITS","identity_sha256":digest(b),"completed_units":0,
               "total_units":counts(b["plan"])["total_units"],"completed_native_contexts":0,"completed_issue_states":0,
               "completed_score_days":0,"current_unit":None,"current_unit_started_active_seconds":old.get("active_seconds",0.),
               "active_seconds":old.get("active_seconds",0.),"updated_at_utc":utc_now(),
               "message":"development only; holdout closed; long run owned by user","unit_costs":{}}
        live=LiveState(experiment,run_id,state); live.write(); live.thread.start()
        store,truth=FeatureStore(experiment),TruthAccess.from_release(experiment)
        with no_network(): entries,report,fits=replay(experiment,run_id,b,live,store,truth)
        again=preflight(project,experiment)
        if binding(experiment,again,b["plan"])!=b: raise ContractError("accepted inputs/code/environment changed during replay")
        passed=signed({"schema_version":"R14_TABULAR_T04_PASS_V1","stage":"T04_DEVELOPMENT_REPLAY","status":"PASS",
                       "run_id":run_id,"completed_at_utc":utc_now(),"binding":b,"identity_sha256":digest(b),
                       "unit_receipts":entries,"counts":counts(b["plan"]),"report_path":report,"report_sha256":hash_file(inside(experiment,report)),
                       "holdout_value_pages_read":0,"network_requests_made":0,"full_development_replay_performed":True,
                       "recipe_lock_created":False,"study_context_fits_performed":fits})
        check_document(experiment,"t04_pass",passed); atomic_json(inside(experiment,PASS),passed,immutable=True)
        live.close("PASS","development replay complete; validate, inspect report and explicitly lock before T05")
        return {k:v for k,v in passed.items() if k not in {"binding","unit_receipts"}}
    except Paused:
        live.close("PAUSED","paused at an atomic unit; committed forecasts and verification are preserved")
        return dict(live.state)
    except BaseException as exc:
        if live is not None: live.close("FAILED",f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if lock.exists() and read_json(lock)=={"pid":os.getpid(),"run_id":run_id}: lock.unlink()


def validate_t04(project,experiment):
    """OWNER-RUN full experiment-output validation; no inference or archive re-scan."""
    ready=preflight(project,experiment); passed=verify_record(read_json(inside(experiment,PASS)))
    check_document(experiment,"t04_pass",passed)
    b=binding(experiment,ready,development_plan())
    if passed["binding"]!=b or passed["identity_sha256"]!=digest(b) or passed["counts"]!=counts(): raise ContractError("accepted T04 identity/counts changed")
    units=UnitStore(experiment,passed["run_id"],b); receipts=iter(passed["unit_receipts"]); verified=[]
    previous=None; states=0; fits=0; card=Scorecard(scoring_policy(experiment))
    def load(unit,deps):
        try: entry=next(receipts)
        except StopIteration as exc: raise ContractError("missing accepted unit") from exc
        p,r=units.paths(unit)
        if entry["unit_id"]!=unit or entry["path"]!=r or hash_file(inside(experiment,r))!=entry["sha256"]: raise ContractError("accepted receipt/order changed")
        receipt=verify_record(read_json(inside(experiment,r)))
        if receipt["record_sha256"]!=entry["record_sha256"] or hash_file(inside(experiment,p))!=receipt["bundle_sha256"]: raise ContractError("accepted bundle changed")
        body=read_json(inside(experiment,p)); units.verify_bundle(body,unit,deps)
        if body["record_sha256"]!=receipt["bundle_record_sha256"]: raise ContractError("accepted bundle/receipt disagreement")
        verified.append(receipt["record_sha256"]); return body,receipt
    cutoffs,regime_receipt=load("regime-cutoffs",[])
    for block in b["plan"]:
        native_refs=[]
        for minute in block["minutes"]:
            for name in ("tabicl","tabdpt"):
                body,receipt=load(native_unit(block,minute,name),[]); native_refs.append(receipt["record_sha256"])
                result=body["result"]; fits+=result["context_fits_performed"]
                if result["context"]["context_days"]<180 or result["learner"]!=name or result["local_issue_minute"]!=minute or result["block_id"]!=block["block_id"]:
                    raise ContractError("native context identity/support changed")
                expected={d for d in block["query_dates"] if any(t.astimezone(DENVER).hour*60+t.astimezone(DENVER).minute==minute for t in issue_times(parse_date(d)))}
                queries=result["queries"]
                if len(queries)!=len(expected) or {q["weather"]["target_date"] for q in queries}!=expected: raise ContractError("native query schedule differs")
                for q in queries: check_query(q["weather"])
        for target in block["query_dates"]:
            body,receipt=load("day-"+target,native_refs+([previous] if previous else []))
            checked_forecast_keys(experiment,body["result"],block); states+=body["result"]["issue_states"]
            previous=receipt["record_sha256"]
            scored,_=load("score-"+target,[previous,regime_receipt["record_sha256"]])
            check_document(experiment,"t04_score",scored["result"]); card.add(scored["result"])
    report,_=load("development-scorecard",verified.copy())
    if next(receipts,None) is not None or states!=passed["counts"]["issue_states"] or fits!=passed["study_context_fits_performed"]: raise ContractError("accepted schedule has extra/missing units")
    if (report["result"]["scorecard"]!=card.result() or report["result"]["regime_cutoffs"]!=cutoffs["result"]
        or hash_file(inside(experiment,passed["report_path"]))!=passed["report_sha256"]): raise ContractError("development scorecard does not reproduce from verified daily losses")
    result={"status":"VALID","validated_stage":"T04_DEVELOPMENT_REPLAY","development_record_sha256":passed["record_sha256"],
            "unit_receipts_verified":len(verified),"issue_states":states,"native_contexts":counts()["native_contexts"],
            "holdout_value_pages_read":0,"network_requests_made":0,"model_fits_performed":0,
            "recipe_locked":inside(experiment,LOCK).exists(),"validation_mode":"FULL_EXPERIMENT_RECEIPTS_FORECAST_KEYS_COEFFICIENT_CLOCKS_AND_REPRODUCED_SCORECARD"}
    # Idempotent receipt has no moving timestamp/lock state; subsequent validation returns current lock status separately.
    record=signed({k:v for k,v in result.items() if k!="recipe_locked"})
    atomic_json(inside(experiment,"manifests/T04_DEVELOPMENT_VALIDATED.json"),record,immutable=True)
    return {**result,"record_sha256":record["record_sha256"]}
