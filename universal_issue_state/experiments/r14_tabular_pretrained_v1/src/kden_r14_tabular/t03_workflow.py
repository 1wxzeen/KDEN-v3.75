"""T03 bounded acceptance, predecessor binding, restart and cost reporting."""
from __future__ import annotations
import os
import threading
import time
from collections import Counter
from datetime import date
from .common import ContractError, atomic_json, canonical, check_document, digest, hash_file, inside, read_json, signed, utc_now, verify_record
from .foundation import isolation_check
from .t02_workflow import validate_t02
from .t02_runtime import no_network
from .dates import DENVER, inclusive, issue_times, native_blocks, parse_date
from .features import FeatureStore
from .truth import TruthAccess
from .replay import (History, UnitStore, bounded_plan, development_plan, fit_coefficients, identity,
                     native_unit, plan_counts, process_day, process_native, publish_day, run_path)

PASS = "manifests/T03_PASS.json"
CHECKS = "manifests/T03_IMPLEMENTATION_CHECKS.json"
RECIPE = {"schema_version":"R14_TABULAR_T03_RECIPE_V1","arms":["KDEN_TABICL_RAW","KDEN_TABICL_T1",
          "KDEN_TABICL_TRANSITION","KDEN_TABICL_T3","KDEN_TABDPT_RAW","KDEN_TABDPT_D0","KDEN_TABDPT_D2_NATIVE"],
          "label_delay_days_exclusive":7,"native_updates":"MONTHLY_BLOCK_START",
          "correction_updates":"MONDAYS_AND_NATIVE_BLOCK_STARTS","half_life_days":90,"minimum_history_days":90,
          "minimum_minute_days":60,"location_shrinkage_days":20,"center_slope_penalty":100,
          "width_intercept_penalty":20,"width_slope_penalty":100,
          "width_optimizer":{"method":"L-BFGS-B","maxiter":300,"maxls":50,"ftol":1e-10,"gtol":1e-5,"eta_guard_exclusive":5},
          "baseline":{"minimum_context_days":180,"kernel_sigma_f":1.25,"weights":"UNIFORM_ALL_EARLIER_SAME_MINUTE"},
          "export_integer_low":-40,"export_integer_high":120,"primary_law_floored":False,
          "bounded_contexts":[{"block_start":"2022-01-01","query_dates":["2022-01-01","2022-01-02"],"minute":600},
                              {"block_start":"2025-08-01","query_dates":["2025-08-01","2025-08-02"],"minute":600}],
          "bounded_scope":"TECHNICAL_ACCEPTANCE_ONLY_NOT_DEVELOPMENT_SCORE_OR_RECIPE_LOCK"}


def recipe(experiment):
    cfg = read_json(inside(experiment,"config/replay.json")); check_document(experiment,"t03_recipe",cfg)
    if cfg!=RECIPE: raise ContractError("T03 configuration differs from the binding native/correction recipe")
    return cfg


def implementation_checks(experiment):
    value = verify_record(read_json(inside(experiment,CHECKS)))
    if (value["status"]!="PASS" or value["code_identity"]!=identity(experiment)
        or value["synthetic_tests_run"]<25 or value["failures"] or value["errors"]):
        raise ContractError("T03 bounded implementation checks absent/stale/failed")
    return value


def preflight(project,experiment):
    t02 = validate_t02(project,experiment)
    checks = implementation_checks(experiment); cfg = recipe(experiment)
    return {"status":"READY_FOR_OWNER_BOUNDED_T03_ACCEPTANCE","t02_record_sha256":t02["record_sha256"],
            "device":t02["device"],"code_identity":identity(experiment),"recipe_sha256":digest(cfg),
            "implementation_checks_sha256":checks["record_sha256"],"bounded_plan":bounded_plan(),
            "bounded_counts":plan_counts(bounded_plan()),"development_counts_for_planning_only":plan_counts(development_plan()),
            "runtime_isolation":isolation_check(experiment),"holdout_value_pages_read":0,"network_requests_made":0,
            "study_model_fits_performed":0,"preflight_runs_inference":False,
            "scope_note":"Four development contexts, eight native query predictions, four issue states. No full replay, holdout opening, accuracy selection or recipe lock."}


class Paused(Exception): pass


class LiveState:
    """Heartbeat records active time even during a slow native call; pauses add no time."""
    def __init__(self,experiment,run_id,state):
        self.experiment,self.run_id,self.state = experiment,run_id,state
        self.started,self.prior = time.monotonic(),state.get("active_seconds",0.)
        self.mutex,self.stop,self.error = threading.RLock(),threading.Event(),None
        self.thread = threading.Thread(target=self._heartbeat,daemon=True)
    def write(self,**fields):
        with self.mutex:
            self.state.update(fields,active_seconds=self.prior+time.monotonic()-self.started,updated_at_utc=utc_now())
            check_document(self.experiment,"t03_state",self.state)
            atomic_json(run_path(self.experiment,self.run_id,"state.json"),self.state)
    def _heartbeat(self):
        while not self.stop.wait(2.):
            try: self.write()
            except Exception as exc: self.error = exc; self.stop.set()
    def check_pause(self):
        if self.error is not None: raise ContractError("monitoring writer failed") from self.error
        if run_path(self.experiment,self.run_id,"pause.request.json").exists(): raise Paused()
    def close(self,status,message):
        self.stop.set()
        if self.thread.is_alive(): self.thread.join()
        self.write(status=status,message=message,pid=None,current_unit=None)


def performance_report(native_results):
    measurements = [{k:r[k] for k in ("block_id","learner","local_issue_minute","native_fit_seconds","predict_seconds",
                                      "context_setup_seconds","invariance_check_seconds","peak_process_rss_bytes","ready_queries",
                                      "context_fits_performed","query_order_and_batch_invariant")}
                    | {"context_days":r["context"]["context_days"]} for r in native_results]
    contexts = {name:[r for r in measurements if r["learner"]==name] for name in ("tabicl","tabdpt")}
    dev = plan_counts(development_plan()); all_contexts = len(native_blocks())*57
    all_states = sum(len(issue_times(d)) for d in inclusive(date(2022,1,1),date(2026,9,11)))
    projections = {}
    for scope,ncontexts,nqueries in [("development_native_only",dev["native_contexts"]//2,dev["issue_states"]),
                                    ("58_blocks_plus_five_days_native_only",all_contexts,all_states)]:
        per_model = {}
        for name,items in contexts.items():
            per_query = [r["predict_seconds"]/r["ready_queries"] for r in items if r["ready_queries"]]
            if not per_query: raise ContractError("bounded check has no measured supported queries")
            fit = [r["native_fit_seconds"]+r["context_setup_seconds"] for r in items]
            per_model[name] = {"contexts":ncontexts,"queries":nqueries,
                               "measured_rate_envelope_seconds":[ncontexts*min(fit)+nqueries*min(per_query),
                                                                ncontexts*max(fit)+nqueries*max(per_query)]}
        projections[scope] = {"learners":per_model,"sum_envelope_seconds":[sum(m["measured_rate_envelope_seconds"][j] for m in per_model.values()) for j in (0,1)]}
    return {"measurements":measurements,"projections":projections,
            "projection_is_not_full_replay_eta":True,"full_replay_capacity_proven":False,
            "caveats":["Two exact-minute contexts per learner are cost samples, not a throughput guarantee.",
                       "Other minutes, larger 2026 contexts, cache behavior, correction/width fits, scoring and I/O can add cost.",
                       "Envelope excludes extra order/batch invariance calls; process RSS is a cumulative high-water mark, not per-model allocation.",
                       "Corrected-arm warmup is unsupported in this sparse probe; it is not seed calibration history for T04."]}


def run_t03(project,experiment,run_id,*,resume=False):
    ready = preflight(project,experiment)
    binding = {"t02_record_sha256":ready["t02_record_sha256"],"code_identity":ready["code_identity"],
               "recipe_sha256":ready["recipe_sha256"],"implementation_checks_sha256":ready["implementation_checks_sha256"],
               "device":ready["device"],"plan":bounded_plan(),"scope":"BOUNDED_T03_TECHNICAL_ACCEPTANCE"}
    if inside(experiment,PASS).exists():
        accepted = verify_record(read_json(inside(experiment,PASS)))
        if accepted["run_id"]!=run_id: raise ContractError("T03 already accepted by another run; no replacement")
        return validate_t03(project,experiment)
    identity_path = run_path(experiment,run_id,"identity.json")
    if identity_path.exists():
        old = verify_record(read_json(identity_path))
        if not resume: raise ContractError("run already exists; use resume-t03")
        if old["binding"]!=binding: raise ContractError("code/config/predecessor/plan changed; resume refuses mixed history")
    elif resume: raise ContractError("resume needs an existing run identity")
    else: atomic_json(identity_path,signed({"binding":binding}),immutable=True)
    lock = inside(experiment,"runs/T03_RUNNING.lock")
    lock.parent.mkdir(parents=True,exist_ok=True)
    try: fd = os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError as exc: raise ContractError("T03 lock exists; inspect/recover a dead process before resume") from exc
    with os.fdopen(fd,"w") as stream:
        stream.write(canonical({"pid":os.getpid(),"run_id":run_id}).decode()); stream.flush(); os.fsync(stream.fileno())
    live = None
    try:
        prior = read_json(run_path(experiment,run_id,"state.json")) if resume and run_path(experiment,run_id,"state.json").exists() else {}
        if prior and prior["identity_sha256"]!=digest(binding): raise ContractError("run-state identity changed")
        run_path(experiment,run_id,"pause.request.json").unlink(missing_ok=True)
        state = {"schema_version":"R14_TABULAR_T03_STATE_V1","run_id":run_id,"status":"RUNNING","pid":os.getpid(),
                 "phase":"VERIFYING_COMPLETED_UNITS","identity_sha256":digest(binding),"completed_units":0,
                 "total_units":ready["bounded_counts"]["total_units"],"completed_native_contexts":0,"completed_issue_states":0,
                 "current_unit":None,"active_seconds":prior.get("active_seconds",0.),"updated_at_utc":utc_now(),
                 "message":"bounded development technical acceptance; no holdout values", "unit_costs":[],"completed_unit_ids":[]}
        live = LiveState(experiment,run_id,state); live.write(); live.thread.start()
        units = UnitStore(experiment,run_id,binding)
        history = History(experiment); all_receipts,native_results = [],[]; previous = None
        store,truth = FeatureStore(experiment),TruthAccess.from_release(experiment)
        def done(unit,kind,body,receipt,*,contexts=0,states=0):
            all_receipts.append({"unit_id":unit,"path":units.paths(unit)[1],"sha256":hash_file(inside(experiment,units.paths(unit)[1])),
                                 "record_sha256":receipt["record_sha256"]})
            with live.mutex:
                live.state["unit_costs"].append({"kind":kind,"active_seconds":body["active_seconds"]})
                live.state["completed_unit_ids"].append(unit)
                live.write(completed_units=live.state["completed_units"]+1,
                           completed_native_contexts=live.state["completed_native_contexts"]+contexts,
                           completed_issue_states=live.state["completed_issue_states"]+states)
        with no_network():
            for block in binding["plan"]:
                native_units = {}
                for minute in block["minutes"]:
                    for name in ("tabicl","tabdpt"):
                        live.check_pause(); unit = native_unit(block,minute,name)
                        live.write(phase="NATIVE_CONTEXT_AND_INVARIANCE",current_unit=unit)
                        found = units.read(unit,[])
                        if found is None:
                            begin = time.monotonic()
                            result = process_native(experiment,store,truth,block,minute,name,ready["device"],check_invariance=True)
                            if not result["query_order_and_batch_invariant"]: raise ContractError("query invariance was not accepted")
                            found = units.commit(unit,result,[],time.monotonic()-begin)
                        body,receipt = found; native_results.append(body["result"]); native_units[name,minute] = found
                        done(unit,"native_"+name,body,receipt,contexts=1)
                monthly,weekly = None,None
                for i,target in enumerate(block["query_dates"]):
                    live.check_pause(); day = parse_date(target); unit = "day-"+target
                    deps = [p[1]["record_sha256"] for p in native_units.values()]+([previous] if previous else [])
                    live.write(phase="CHRONOLOGICAL_CORRECTIONS_AND_PUBLICATION",current_unit=unit)
                    found = units.read(unit,deps)
                    if found is None:
                        begin = time.monotonic()
                        coefficients = fit_coefficients(history,truth,day,monthly,weekly,block_start=i==0)
                        forecasts,history_rows = process_day(native_units,block,day,coefficients)
                        result,extra = publish_day(experiment,run_id,day,forecasts,history_rows,coefficients,ready["recipe_sha256"])
                        found = units.commit(unit,result,deps,time.monotonic()-begin,extra)
                    body,receipt = found
                    monthly,weekly = body["result"]["coefficients"]["monthly"],body["result"]["coefficients"]["weekly"]
                    history.add(body,receipt); previous = receipt["record_sha256"]
                    done(unit,"day",body,receipt,states=body["result"]["issue_states"])
            live.check_pause(); live.write(phase="PERFORMANCE_REPORT",current_unit="performance-report")
            deps = [r["record_sha256"] for r in all_receipts]
            found = units.read("performance-report",deps)
            if found is None:
                begin = time.monotonic(); result = performance_report(native_results)
                found = units.commit("performance-report",result,deps,time.monotonic()-begin)
            body,receipt = found; done("performance-report","report",body,receipt)
        # Recheck accepted sources/environment, but never original large archive bytes.
        final_preflight = preflight(project,experiment)
        if any(final_preflight[k]!=ready[k] for k in ("t02_record_sha256","code_identity","recipe_sha256","implementation_checks_sha256","device")):
            raise ContractError("bound inputs changed during T03")
        passed = signed({"schema_version":"R14_TABULAR_T03_PASS_V1","stage":"T03","status":"PASS","run_id":run_id,
                         "completed_at_utc":utc_now(),"binding":binding,"identity_sha256":digest(binding),
                         "unit_receipts":all_receipts,"counts":ready["bounded_counts"],
                         "performance_report_path":units.paths("performance-report")[0],
                         "holdout_value_pages_read":0,"network_requests_made":0,
                         "study_context_fits_performed":sum(r["context_fits_performed"] for r in native_results),
                         "full_development_replay_performed":False,"recipe_lock_created":False})
        check_document(experiment,"t03_pass",passed); atomic_json(inside(experiment,PASS),passed,immutable=True)
        live.close("PASS","bounded T03 acceptance complete; T04 full development replay is next, not started")
        return passed
    except Paused:
        live.close("PAUSED","cooperative pause at an atomic-unit boundary")
        return dict(live.state)
    except BaseException as exc:
        if live is not None: live.close("FAILED",f"{type(exc).__name__}: {exc}")
        raise
    finally:
        # Never delete another run's lock or anything in accepted inputs.
        if lock.exists() and read_json(lock)=={"pid":os.getpid(),"run_id":run_id}: lock.unlink()


def validate_t03(project,experiment):
    ready = preflight(project,experiment)
    passed = verify_record(read_json(inside(experiment,PASS))); check_document(experiment,"t03_pass",passed)
    b = passed["binding"]
    if (b["t02_record_sha256"]!=ready["t02_record_sha256"] or b["code_identity"]!=identity(experiment)
        or b["recipe_sha256"]!=ready["recipe_sha256"] or b["device"]!=ready["device"]
        or b["implementation_checks_sha256"]!=ready["implementation_checks_sha256"] or b["plan"]!=bounded_plan()
        or passed["identity_sha256"]!=digest(b) or passed["counts"]!=plan_counts(b["plan"])):
        raise ContractError("T03 accepted identity or bounded scope changed")
    units = UnitStore(experiment,passed["run_id"],b)
    expected = []
    for block in b["plan"]:
        expected += [native_unit(block,m,n) for m in block["minutes"] for n in ("tabicl","tabdpt")]
        expected += ["day-"+d for d in block["query_dates"]]
    expected += ["performance-report"]
    if [r["unit_id"] for r in passed["unit_receipts"]]!=expected: raise ContractError("accepted unit schedule changed")
    validated = []; previous = None; native_refs = []; state_count = 0
    import pyarrow.parquet as pq
    for r in passed["unit_receipts"]:
        unit = r["unit_id"]; _,receipt_rel = units.paths(unit)
        if r["path"]!=receipt_rel or hash_file(inside(experiment,receipt_rel))!=r["sha256"]:
            raise ContractError("accepted receipt changed")
        receipt = verify_record(read_json(inside(experiment,receipt_rel)))
        if receipt["record_sha256"]!=r["record_sha256"]: raise ContractError("accepted receipt identity differs")
        if unit.startswith("native-"):
            deps = []
            if "-tabicl" in unit: native_refs = []  # bounded plan has one minute per block
            native_refs.append(receipt["record_sha256"])
        elif unit.startswith("day-"): deps = native_refs+([previous] if previous else [])
        else: deps = validated.copy()
        body,_ = units.read(unit,deps)
        if receipt["bundle_record_sha256"]!=body["record_sha256"]: raise ContractError("unit bundle changed")
        if unit.startswith("native-"):
            result = body["result"]
            if not result["query_order_and_batch_invariant"] or result["context"]["context_days"]<180:
                raise ContractError("native context support/invariance missing")
            for q in result["queries"]:
                check_query_for_validation(q)
        if unit.startswith("day-"):
            result = body["result"]; commit = verify_record(read_json(inside(experiment,result["forecast_commit_path"])))
            check_document(experiment,"forecast_commit",commit)
            if commit["artifact_path"]!=result["forecast_path"] or commit["artifact_sha256"]!=body["extra_artifacts"][result["forecast_path"]]:
                raise ContractError("forecast receipt/hash mismatch")
            rows = pq.ParquetFile(inside(experiment,result["forecast_path"])).read().to_pylist()
            from .replay import check_prediction, check_coefficients
            day = parse_date(result["target_date"])
            block = next(block for block in b["plan"] if str(day) in block["query_dates"])
            check_coefficients(result["coefficients"],block,day)
            if len(rows)!=result["issue_states"] or len({x["issue_state_id"] for x in rows})!=len(rows): raise ContractError("forecast key count changed")
            for row in rows:
                value = __import__("json").loads(row["prediction_json"]); check_document(experiment,"t03_predictions",value); check_prediction(value)
                if any(value[k]!=row[k] for k in ("issue_state_id","target_date","issue_time_utc")): raise ContractError("prediction key mismatch")
                if value["target_date"]!=result["target_date"] or value["local_issue_minute"] not in block["minutes"]:
                    raise ContractError("forecast dates/minutes differ from the bounded schedule")
            state_count += len(rows); previous = receipt["record_sha256"]
        validated.append(receipt["record_sha256"])
    if state_count!=passed["counts"]["issue_states"]: raise ContractError("T03 scheduled issue denominator changed")
    return {"status":"VALID","validated_stage":"T03","record_sha256":passed["record_sha256"],
            "native_contexts":passed["counts"]["native_contexts"],"issue_states":state_count,"unit_receipts_verified":len(validated),
            "holdout_value_pages_read":0,"network_requests_made":0,"model_fits_performed":0,
            "full_development_replay_performed":False,"recipe_lock_created":False,
            "performance_report_path":passed["performance_report_path"],"validation_mode":"BOUNDED_FORECAST_BUNDLES_AND_ACCEPTED_T02_RUNTIME"}


def check_query_for_validation(q):
    from .replay import check_query
    from .laws import describe, from_payload
    check_query(q["weather"])
    if q["law"] is not None: describe(from_payload(q["law"]))
