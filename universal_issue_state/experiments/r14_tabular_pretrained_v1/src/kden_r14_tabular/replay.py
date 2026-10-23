"""One-process, atomic-unit chronological replay primitives.

T03 exposes ONLY its fixed bounded development acceptance. Full development and
holdout commands belong to later stages. Accepted native shapes are stored once;
corrected laws reference them by hash and affine transform, not by copied arrays.
"""
from __future__ import annotations
import gc
import json
import math
import os
import re
import resource
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
import numpy as np
from .common import ContractError, atomic_json, canonical, check_document, digest, hash_file, inside, read_json, signed, utc_now, verify_record
from .dates import DENVER, DEV_END, inclusive, issue_times, label_cutoff, native_blocks, parse_date
from .features import FeatureStore, stamp
from .truth import TruthAccess
from .corrections import RAW, CONTROL, CENTER, WEATHER, arm_law, emit_arms, feature_values, fit_center, fit_location, fit_width
from .laws import KernelLaw, PointLaw, describe, from_payload, native_law
from .t02_runtime import backend, no_network, raw_predict

ARM_IDS = [RAW["tabicl"],CONTROL["tabicl"],CENTER["tabicl"],"KDEN_TABICL_T3",
           RAW["tabdpt"],CONTROL["tabdpt"],CENTER["tabdpt"]]
T03_FILES = ["run_t03.py","config/replay.json","schemas/t03_recipe.json","schemas/t03_unit.json",
             "schemas/t03_pass.json","schemas/t03_state.json","schemas/t03_predictions.json",
             "src/kden_r14_tabular/laws.py","src/kden_r14_tabular/corrections.py",
             "src/kden_r14_tabular/replay.py","src/kden_r14_tabular/t03_workflow.py",
             "src/kden_r14_tabular/t03_cli.py","tests/test_t03.py","reports/T03_OWNER_RUNBOOK.md"]


def identity(experiment): return {p:hash_file(inside(experiment,p)) for p in T03_FILES}


def run_path(experiment,run_id,relative):
    if not re.fullmatch(r"kdenv375-t03-[A-Za-z0-9_-]{1,100}",run_id):
        raise ContractError("run ID must start kdenv375-t03- and contain only letters/numbers/_/-")
    return inside(experiment,f"runs/{run_id}/{relative}")


def development_plan():
    """Pure enumeration; never opens labels or executes model inference."""
    return [{**b,"minutes":list(range(120,961,15)),
             "query_dates":[str(d) for d in inclusive(parse_date(b["start_date"]),parse_date(b["end_date"]))]}
            for b in native_blocks() if b["role"]=="DEVELOPMENT"]


def bounded_plan():
    blocks = {b["start_date"]:b for b in development_plan()}
    return [{**blocks[start],"minutes":[600],"query_dates":[start,str(parse_date(start)+timedelta(days=1))]}
            for start in ("2022-01-01","2025-08-01")]


def plan_counts(plan):
    states = 0
    for b in plan:
        if b["role"]!="DEVELOPMENT" or not b["query_dates"]: raise ContractError("T03 cannot run holdout or empty blocks")
        if b["start_date"]!=b["query_dates"][0]: raise ContractError("replay must begin at the native block start")
        for d in b["query_dates"]:
            if not date(2022,1,1)<=parse_date(d)<=DEV_END: raise ContractError("T03 query outside development")
            states += sum(t.astimezone(DENVER).hour*60+t.astimezone(DENVER).minute in b["minutes"] for t in issue_times(parse_date(d)))
    return {"native_contexts":sum(2*len(b["minutes"]) for b in plan),"issue_states":states,
            "query_calls":2*states,"correction_days":sum(len(b["query_dates"]) for b in plan),
            "total_units":sum(2*len(b["minutes"])+len(b["query_dates"]) for b in plan)+1}


def check_query(row):
    d,issue = parse_date(row["target_date"]),stamp(row["issue_time_utc"])
    minute = row["local_issue_minute"]
    if issue not in issue_times(d) or minute!=issue.astimezone(DENVER).hour*60+issue.astimezone(DENVER).minute:
        raise ContractError("query is outside the DST-safe issue grid")
    if row["availability_policy_id"]!="KDEN_HIST_COMPLETE_L105_V1": raise ContractError("wrong query availability")
    provenance = json.loads(row["source_provenance_json"])
    for product in ("wrfsfcf","wrfsubhf"):
        cycle = provenance["selected_cycles"][product]
        if cycle["issue_state_id"]!=row["issue_state_id"] or stamp(cycle["issue_time_utc"])!=issue:
            raise ContractError("forecast provenance does not match its query")
        if cycle["cycle_init_utc"] is not None:
            init = stamp(cycle["cycle_init_utc"]); available = stamp(cycle["emulated_complete_time_utc"])
            if available!=init+timedelta(minutes=105) or available>issue or init.minute or init.second or init.microsecond:
                raise ContractError("future or malformed selected cycle")
        if cycle.get("previous_cycle_init_utc") is not None:
            previous = stamp(cycle["previous_cycle_init_utc"])
            if (previous!=stamp(cycle["cycle_init_utc"])-timedelta(hours=1)
                or stamp(cycle["previous_emulated_complete_time_utc"])!=previous+timedelta(minutes=105)
                or previous+timedelta(minutes=105)>issue): raise ContractError("future/wrong revision cycle")
    trend_ids = json.loads(row["trend_q14_source_ids_json"])
    if row["issue_state_id"] in trend_ids or len(set(trend_ids))!=len(trend_ids):
        raise ContractError("trend contains duplicate or query-state IDs")


def query_rows(store,dates,minute):
    import pyarrow.dataset as ds
    columns = list(dict.fromkeys(store.columns+["source_provenance_json","coverage_diagnostics_json"]))
    rows = store.dataset.to_table(columns=columns,filter=(ds.field("local_issue_minute")==minute)
                                  & ds.field("target_date").isin(dates)).to_pylist()
    rows.sort(key=lambda r:r["target_date"])
    expected = {d for d in dates if any(t.astimezone(DENVER).hour*60+t.astimezone(DENVER).minute==minute for t in issue_times(parse_date(d)))}
    if len(rows)!=len(expected) or {r["target_date"] for r in rows}!=expected or len({r["issue_state_id"] for r in rows})!=len(rows):
        raise ContractError("query keys differ from the expected DST-safe schedule")
    for row in rows: check_query(row)
    return rows


def baseline_context(store,truth,update,minute):
    """Independent H/Q eligibility: an absent Q anchor must not erase valid H history."""
    import pyarrow.dataset as ds
    labels = {r["target_date"]:r["y_audited_f"] for r in truth.context(update)}
    rows = store.dataset.to_table(columns=["target_date","local_issue_minute","anchor_h_f","anchor_q_f"],
             filter=(ds.field("local_issue_minute")==minute)&(ds.field("target_date")<str(label_cutoff(update)))).to_pylist()
    if len({r["target_date"] for r in rows})!=len(rows): raise ContractError("duplicate baseline context date")
    out = {}
    for source in ("H","Q"):
        key = "anchor_h_f" if source=="H" else "anchor_q_f"
        samples = [labels[r["target_date"]]-r[key] for r in rows if r["target_date"] in labels and r[key] is not None]
        out[source] = {"context_days":len(samples),"supported":len(samples)>=180,
                       "residual_law":KernelLaw(samples).payload() if len(samples)>=180 else None,
                       "label_cutoff_exclusive":str(label_cutoff(update)),"bandwidth_f":1.25}
    return out


def assert_invariant(model,name,X,full):
    """Real supplied context: order reversal and singleton partitioning, same raw API."""
    reverse = raw_predict(model,name,X[::-1]); singles = [raw_predict(model,name,X[i:i+1]) for i in range(len(X))]
    for key,value in full.items():
        candidates = [reverse[key],*(s[key] for s in singles)] if key=="borders" else [reverse[key][::-1],np.concatenate([s[key] for s in singles])]
        if any(not np.allclose(value,other,atol=1e-5,rtol=1e-5) for other in candidates):
            raise ContractError("native distribution depends on query batching/order")


def memory_bytes():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(r if sys.platform=="darwin" else r*1024)


def process_native(experiment,store,truth,block,minute,name,device,*,check_invariance=False):
    update = parse_date(block["start_date"]); begin = time.monotonic()
    context = store.context(truth,update,minute)
    queries = query_rows(store,block["query_dates"],minute)
    ready = [r for r in queries if r["native_status"]=="READY" and r["anchor_q_f"] is not None]
    result = {"block_id":block["block_id"],"learner":name,"local_issue_minute":minute,
              "context":context.metadata,"context_setup_seconds":time.monotonic()-begin,
              "baseline_contexts":baseline_context(store,truth,update,minute) if name=="tabicl" else {},"queries":[]}
    raw,constant = None,bool(np.ptp(context.y_residual_f)==0)
    result.update(native_fit_seconds=0.,predict_seconds=0.,invariance_check_seconds=0.,context_fits_performed=0)
    if ready and not constant:
        begin = time.monotonic(); model = backend(experiment,name,device,checked=True)
        model.fit(context.X,context.y_residual_f)
        if name=="tabdpt" and (model.n_instances!=len(context.rows) or model.n_features!=71 or model.projection is not None):
            raise ContractError("native backend reduced context/features")
        result["native_fit_seconds"] = time.monotonic()-begin; result["context_fits_performed"] = 1
        X = context.matrix(ready); begin = time.monotonic(); raw = raw_predict(model,name,X)
        result["predict_seconds"] = time.monotonic()-begin
        if check_invariance:
            begin = time.monotonic(); assert_invariant(model,name,X,raw)
            result["invariance_check_seconds"] = time.monotonic()-begin
        del model; gc.collect()
    result.update(query_order_and_batch_invariant=bool(check_invariance or constant),constant_context_point_mass=constant,
                  peak_process_rss_bytes=memory_bytes(),ready_queries=len(ready))
    laws = {r["issue_state_id"]:PointLaw(float(context.y_residual_f[0])+r["anchor_q_f"]) if constant else native_law(raw,name,i,r["anchor_q_f"])
            for i,r in enumerate(ready)}
    for row in queries:
        law = laws.get(row["issue_state_id"])
        result["queries"].append({"weather":{k:row[k] for k in ["issue_state_id","target_date","issue_time_utc","local_issue_minute",
            "availability_policy_id","anchor_q_f","anchor_h_f","source_feature_path","source_feature_sha256","source_provenance_json",
            "coverage_diagnostics_json","trend_q14_source_ids_json","trend_q14_status",*WEATHER]},
            "law":law.payload() if law else None,"support_status":"SUPPORTED" if law else "ABSTAIN_MISSING_Q05_ANCHOR",
            "context_identity":context.metadata["context_identity"]})
    return result


class UnitStore:
    """Bundle first, receipt last. A complete orphan bundle is verified and adopted."""
    def __init__(self,experiment,run_id,run_identity):
        self.experiment,self.run_id,self.binding = experiment,run_id,digest(run_identity)
    def paths(self,unit):
        if not re.fullmatch(r"[A-Za-z0-9_-]+",unit): raise ContractError("unsafe unit ID")
        return f"runs/{self.run_id}/units/{unit}.json",f"runs/{self.run_id}/receipts/{unit}.json"
    def verify_bundle(self,body,unit,deps):
        verify_record(body); check_document(self.experiment,"t03_unit",body)
        if body["identity_sha256"]!=self.binding or body["unit_id"]!=unit or body["dependencies"]!=deps:
            raise ContractError("resume unit identity/dependency mismatch")
        for p,sha in body["extra_artifacts"].items():
            if not p.startswith(f"runs/{self.run_id}/") or hash_file(inside(self.experiment,p))!=sha:
                raise ContractError("committed unit artifact changed")
    def receipt(self,unit,body):
        p,r = self.paths(unit)
        record = signed({"status":"COMMITTED","unit_id":unit,"identity_sha256":self.binding,
                         "bundle_path":p,"bundle_sha256":hash_file(inside(self.experiment,p)),
                         "bundle_record_sha256":body["record_sha256"]})
        atomic_json(inside(self.experiment,r),record,immutable=True)
        return record
    def read(self,unit,deps):
        p,r = self.paths(unit); path = inside(self.experiment,p); receipt_path = inside(self.experiment,r)
        if not path.exists():
            if receipt_path.exists(): raise ContractError("receipt exists without its immutable bundle")
            return None
        body = read_json(path); self.verify_bundle(body,unit,deps)
        record = self.receipt(unit,body)  # equal publication verifies existing receipt, or recovers an orphan
        verify_record(record)
        return body,record
    def commit(self,unit,result,deps,active_seconds,extra=None):
        p,_ = self.paths(unit)
        body = signed({"schema_version":"R14_TABULAR_T03_UNIT_V1","unit_id":unit,"status":"COMPLETE",
                       "identity_sha256":self.binding,"dependencies":deps,"result":result,
                       "active_seconds":active_seconds,"extra_artifacts":extra or {}})
        self.verify_bundle(body,unit,deps); atomic_json(inside(self.experiment,p),body,immutable=True)
        return body,self.receipt(unit,body)


def native_unit(block,minute,name): return f"native-{block['start_date']}-{minute}-{name}"


def atomic_parquet(path,rows):
    import pyarrow as pa
    import pyarrow.parquet as pq
    path.parent.mkdir(parents=True,exist_ok=True)
    schema = pa.schema([pa.field(k,pa.string(),nullable=False) for k in
                        ["issue_state_id","target_date","issue_time_utc","prediction_json"]])
    table = pa.Table.from_pylist(rows,schema=schema)
    fd,tmp = tempfile.mkstemp(prefix=".forecast-",dir=path.parent); os.close(fd)
    try:
        pq.write_table(table,tmp,compression="zstd")
        with open(tmp,"rb") as f: os.fsync(f.fileno())
        try: os.link(tmp,path)
        except FileExistsError:
            if hash_file(tmp)!=hash_file(path): raise ContractError("immutable forecast already differs")
        directory = os.open(path.parent,os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally: os.unlink(tmp)


def check_prediction(value):
    """Structural guard: never put outcomes or outcome-dependent losses in forecasts."""
    allowed = {"issue_state_id","target_date","issue_time_utc","local_issue_minute","availability_policy_id",
               "native_block_id","native_references","coefficient_versions","source_provenance_json",
               "coverage_diagnostics_json","source_feature_path","source_feature_sha256","trend_q14_source_ids_json",
               "arms","baselines","correction_features"}
    if set(value)!=allowed: raise ContractError("target-free prediction fields changed")
    forbidden = {"truth","y_audited_f","y_tmax_f","absolute_error_f","integer_nll","label","truth_qc_status"}
    def visit(v):
        if isinstance(v,dict):
            if forbidden&set(v): raise ContractError("truth/loss leaked into target-free prediction")
            for child in v.values(): visit(child)
        elif isinstance(v,list):
            for child in v: visit(child)
    visit(value)
    if set(value["arms"])!=set(ARM_IDS): raise ContractError("seven neural arm identities required")


class History:
    """Load scalar committed history; native quantiles are resolved only for width fitting."""
    def __init__(self,experiment): self.experiment,self.days = experiment,[]
    def add(self,bundle,receipt):
        path = bundle["result"]["history_path"]
        value = verify_record(read_json(inside(self.experiment,path)))
        self.days.append((value["rows"],receipt["record_sha256"]))
    @lru_cache(maxsize=128)
    def native(self,path,sha):
        if hash_file(inside(self.experiment,path))!=sha: raise ContractError("preserved native shape changed")
        return verify_record(read_json(inside(self.experiment,path)))["result"]
    def rows(self,arm,update):
        cutoff = str(label_cutoff(update)); out = []
        for rows,receipt_sha in self.days:
            for r in rows:
                if r["target_date"]>=cutoff: continue
                a = r["arms"][arm]
                if not a["supported"]: continue
                item = {k:r[k] for k in ("issue_state_id","target_date","local_issue_minute")}
                item.update(arm=arm,emission_receipt_sha256=receipt_sha,coefficient_version=a["coefficient_version"],
                            supported=True,mean_f=a["mean_f"],sigma_f=a["sigma_f"],features=feature_values(r["weather"]))
                if arm==CENTER["tabicl"]:
                    t1 = r["arms"][CONTROL["tabicl"]]
                    item.update(t1_mean_f=t1["mean_f"],t1_sigma_f=t1["sigma_f"])
                    item["features"] = feature_values(r["weather"],t1["sigma_f"]) if t1["sigma_f"]>0 else item["features"]
                    ref = r["native_references"]["tabicl"]
                    result = self.native(ref["path"],ref["sha256"])
                    q = next(q for q in result["queries"] if q["weather"]["issue_state_id"]==r["issue_state_id"])
                    if q["law"]["kind"]=="quantiles": item["t1_quantiles_f"] = (np.asarray(q["law"]["quantiles_f"])+t1["shift_f"]).tolist()
                    elif q["law"]["kind"]=="point": item["t1_sigma_f"] = 0.
                    else: raise ContractError("T3 width history has a wrong native law family")
                out.append(item)
        return out


def fit_coefficients(history,truth,day,monthly=None,weekly=None,*,block_start=False):
    if monthly is None or block_start:
        monthly = {name:fit_location(history.rows(RAW[name],day),truth,day,name) for name in RAW}
    if weekly is None or block_start or day.weekday()==0:
        weekly = {name:fit_center(history.rows(CONTROL[name],day),truth,day,name) for name in RAW}
        weekly["width"] = fit_width(history.rows(CENTER["tabicl"],day),truth,day)
    return {"monthly":monthly,"weekly":weekly}


def process_day(units,block,day,coefficients):
    check_coefficients(coefficients,block,day)
    forecasts,history_rows = [],[]
    for minute in block["minutes"]:
        sources = {name:units[name,minute] for name in RAW}
        by_model = {name:[q for q in sources[name][0]["result"]["queries"] if q["weather"]["target_date"]==str(day)] for name in RAW}
        if not by_model["tabicl"] and not by_model["tabdpt"]: continue  # nonexistent DST issue
        if any(len(q)!=1 for q in by_model.values()): raise ContractError("product learners have different query keys")
        row = by_model["tabicl"][0]["weather"]
        arms,refs = {},{}
        for name in RAW:
            bundle,receipt = sources[name]; q = by_model[name][0]
            if q["weather"]!=row: raise ContractError("learner weather/provenance mismatch")
            refs[name] = {"path":receipt["bundle_path"],"sha256":receipt["bundle_sha256"],
                          "context_identity":q["context_identity"]}
            if q["law"] is None:
                names = [RAW[name],CONTROL[name],CENTER[name]]+(["KDEN_TABICL_T3"] if name=="tabicl" else [])
                arms.update({a:{"supported":False,"fallback_reason":q["support_status"],"coefficient_version":"NATIVE_ABSTENTION",
                                "mean_f":None,"sigma_f":None} for a in names})
            else:
                made = emit_arms(q["law"],row,name,coefficients["monthly"][name],coefficients["weekly"][name],
                                 coefficients["weekly"]["width"] if name=="tabicl" else None)
                made[RAW[name]]["coefficient_version"] = "NATIVE_"+q["context_identity"]
                arms.update(made)
        baselines = {}
        for source in ("H","Q"):
            anchor = row["anchor_h_f" if source=="H" else "anchor_q_f"]
            baseline = sources["tabicl"][0]["result"]["baseline_contexts"][source]
            base = {"raw_anchor_f":anchor,"point_supported":anchor is not None,"distribution_supported":anchor is not None and baseline["supported"],
                    "context_days":baseline["context_days"],"residual_shape_reference":refs["tabicl"]}
            if base["distribution_supported"]:
                centers = np.asarray(baseline["residual_law"]["centers_f"])+anchor
                base["distribution"] = describe(KernelLaw(centers))
            baselines[source] = base
        pred = {k:row[k] for k in ("issue_state_id","target_date","issue_time_utc","local_issue_minute","availability_policy_id",
                "source_provenance_json","coverage_diagnostics_json","source_feature_path","source_feature_sha256","trend_q14_source_ids_json")}
        pred.update(native_block_id=block["block_id"],native_references=refs,
                    coefficient_versions={kind:{n:v["coefficient_version"] for n,v in fits.items()} for kind,fits in coefficients.items()},
                    arms=arms,baselines=baselines,correction_features=feature_values(row))
        check_prediction(pred)
        forecasts.append({"issue_state_id":row["issue_state_id"],"target_date":str(day),"issue_time_utc":row["issue_time_utc"],
                          "prediction_json":canonical(pred).decode().strip()})
        history_rows.append({"issue_state_id":row["issue_state_id"],"target_date":str(day),"local_issue_minute":minute,
                             "weather":{k:row[k] for k in ("target_date","local_issue_minute",*WEATHER)},"native_references":refs,
                             "arms":{a:{k:v.get(k) for k in ("supported","coefficient_version","mean_f","sigma_f","shift_f","scale")} for a,v in arms.items()}})
    return forecasts,history_rows


def check_coefficients(coefficients,block,day):
    """Version, lineage, cutoff and refresh clocks are checked before emission."""
    start = parse_date(block["start_date"])
    weekly_date = max(start,day-timedelta(days=day.weekday()))
    for group,fits in coefficients.items():
        if group not in {"monthly","weekly"}: raise ContractError("unknown coefficient group")
        expected = {"tabicl","tabdpt"} if group=="monthly" else {"tabicl","tabdpt","width"}
        if set(fits)!=expected: raise ContractError("coefficient identities missing")
        for name,fit in fits.items():
            body = {k:v for k,v in fit.items() if k!="coefficient_version"}
            if fit["coefficient_version"]!=digest(body): raise ContractError("coefficient version changed")
            update = start if group=="monthly" else weekly_date
            arm = RAW[name] if group=="monthly" else CENTER["tabicl"] if name=="width" else CONTROL[name]
            stage = "MONTHLY_LOCATION" if group=="monthly" else "WEEKLY_T3_WIDTH" if name=="width" else "WEEKLY_CENTER"
            if (fit["update_date"]!=str(update) or fit["label_cutoff_exclusive"]!=str(label_cutoff(update))
                or fit["history_arm"]!=arm or fit["stage"]!=stage
                or (fit["history_last_date"] is not None and fit["history_last_date"]>=fit["label_cutoff_exclusive"])):
                raise ContractError("coefficient refresh/cutoff/stage clock mismatch")


def publish_day(experiment,run_id,day,forecasts,history,coefficients,recipe_sha):
    rel = f"runs/{run_id}/forecasts/{day}.parquet"; path = inside(experiment,rel)
    if not forecasts or len({r["issue_state_id"] for r in forecasts})!=len(forecasts): raise ContractError("empty/duplicate forecast day")
    for r in forecasts: check_document(experiment,"t03_predictions",json.loads(r["prediction_json"]))
    atomic_parquet(path,forecasts)
    commit = signed({"schema_version":"R14_TABULAR_FORECAST_COMMIT_V1","status":"COMMITTED","artifact_path":rel,
                     "artifact_sha256":hash_file(path),"target_dates":[str(day)],"recipe_sha256":recipe_sha,
                     "model_id":"R14_TABULAR_SEVEN_ARMS_AND_HQ_CONTROLS","run_id":run_id})
    check_document(experiment,"forecast_commit",commit)
    receipt_rel = f"runs/{run_id}/forecasts/{day}.commit.json"
    atomic_json(inside(experiment,receipt_rel),commit,immutable=True)
    history_rel = f"runs/{run_id}/history/{day}.json"
    atomic_json(inside(experiment,history_rel),signed({"rows":history}),immutable=True)
    return {"target_date":str(day),"forecast_path":rel,"forecast_commit_path":receipt_rel,"history_path":history_rel,
            "issue_states":len(forecasts),"coefficients":coefficients},\
           {p:hash_file(inside(experiment,p)) for p in (rel,receipt_rel,history_rel)}


def day_balanced_scoring(scored,expected_counts):
    """For a single arm; called only on a separately authorized verification table."""
    grouped = {}; seen = set()
    for r in scored:
        if r["issue_state_id"] in seen: raise ContractError("duplicate scoring issue")
        seen.add(r["issue_state_id"]); grouped.setdefault(r["target_date"],[]).append(r)
    available,complete = [],[]
    keys = ("absolute_error_f","squared_error_f","signed_error_f","integer_nll","modal_integer_hit","crps_f","median_absolute_error_f")
    for day,n in expected_counts.items():
        if n<=0: raise ContractError("positive scheduled denominator required")
        rows = grouped.get(day,[])
        if len(rows)>n: raise ContractError("more forecasts than scheduled")
        if rows:
            daily = {k:sum(r[k] for r in rows)/len(rows) for k in keys}
            available.append(daily)
            if len(rows)==n: complete.append(daily)
    if set(grouped)-set(expected_counts): raise ContractError("unscheduled scored target date")
    def summary(days):
        if not days: return {"days":0}
        result = {k:sum(d[k] for d in days)/len(days) for k in keys}
        result.update(days=len(days),rmse_f=math.sqrt(result["squared_error_f"]))
        return result
    return {"complete_day":summary(complete),"available_forecast":summary(available),
            "expected_days":len(expected_counts),"excluded_complete_days":len(expected_counts)-len(complete),
            "genuine_zero_probability_count":sum(r["genuine_zero_probability"] for r in scored)}
