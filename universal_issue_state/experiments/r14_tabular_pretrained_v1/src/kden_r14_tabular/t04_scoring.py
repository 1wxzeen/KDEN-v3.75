"""Truth-separated, unfloored, day-balanced scoring reusable after recipe lock.

Positive infinity is serialized as the string 'Infinity', never null/zero or a
probability floor. Display-category Brier explicitly includes both outside tails.
Regime tags are descriptive, overlapping predictor-only tags, not selection rules.
"""
from __future__ import annotations
import json
import math
from collections import defaultdict
from datetime import datetime
import numpy as np
from scipy.special import ndtr
from .common import ContractError
from .corrections import arm_law
from .dates import DENVER, issue_times, parse_date
from .laws import KernelLaw, PointLaw, describe, checked_crps
from .replay import ARM_IDS

MODELS = tuple(ARM_IDS) + ("H_POINT", "H_RESIDUAL", "Q_POINT", "Q_RESIDUAL")
METRICS = ("absolute_error_f", "squared_error_f", "signed_error_f", "median_absolute_error_f",
           "modal_integer_hit", "rounded_mean_integer_hit", "integer_nll", "crps_f", "modal_brier",
           "display_category_brier", "display_below_mass", "display_above_mass") + tuple(
               f"{prefix}_{level}" for level in (50,80,90,95) for prefix in ("coverage","width_f"))


def serial(value):
    if isinstance(value,float) and not math.isfinite(value):
        if value == math.inf: return "Infinity"
        if value == -math.inf: return "-Infinity"
        raise ContractError("NaN is not an admissible score")
    if isinstance(value,dict): return {k:serial(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [serial(v) for v in value]
    return value


def numeric(value):
    if value == "Infinity": return math.inf
    if value == "-Infinity": return -math.inf
    if isinstance(value,bool) or not isinstance(value,(int,float)) or math.isnan(value):
        raise ContractError("invalid numeric score")
    return value


class CachedKernel(KernelLaw):
    def __init__(self,centers,pair_term=None):
        super().__init__(centers)
        self.pair_term = self.pair_expectation() if pair_term is None else pair_term
    @staticmethod
    def expected_abs(delta,sigma):
        z = delta/sigma
        return 2*sigma*np.exp(-z*z/2)/math.sqrt(2*math.pi)+delta*(2*ndtr(z)-1)
    def pair_expectation(self):
        return float(sum(self.expected_abs(self.centers[i:i+128,None]-self.centers[None,:],math.sqrt(2)*1.25).sum()
                         for i in range(0,len(self.centers),128))/len(self.centers)**2)
    def crps(self,y):
        return checked_crps(float(self.expected_abs(y-self.centers,1.25).mean())-.5*self.pair_term)


class KernelCache:
    def __init__(self): self.values = {}
    def law(self,key,payload,anchor):
        if key not in self.values:
            self.values[key] = CachedKernel(payload["centers_f"])
        base = self.values[key]
        # Translation changes the first CRPS term but never the pair integral.
        return CachedKernel(base.centers+anchor,base.pair_term)


def law_metrics(law,truth,summary,bands):
    if isinstance(truth,bool) or not isinstance(truth,(int,float)) or not float(truth).is_integer():
        raise ContractError("integer truth required")
    m,s = law.moments()
    if not math.isclose(m,summary["mean_f"],rel_tol=1e-9,abs_tol=1e-8) or not math.isclose(s,summary["sigma_f"],rel_tol=1e-9,abs_tol=1e-8):
        raise ContractError("scoring law disagrees with committed forecast moments")
    lp = law.log_mass(truth-.5,truth+.5)
    if math.isnan(lp) or lp > 1e-9: raise ContractError("invalid integer-bin log mass")
    mode,p = summary["modal_integer_f"],summary["modal_probability"]
    hit = int(mode==truth)
    probs = [summary["pmf_below_minus40"],*summary["pmf_minus40_to120"],summary["pmf_above120"]]
    if abs(sum(probs)-1)>1e-9 or any(x<0 or x>1 for x in probs): raise ContractError("incomplete display probability accounting")
    category = 0 if truth < -40 else 162 if truth > 120 else int(truth)+41
    metrics = {"absolute_error_f":abs(m-truth),"squared_error_f":(m-truth)**2,"signed_error_f":m-truth,
               "median_absolute_error_f":abs(summary["median_f"]-truth),"modal_integer_hit":hit,
               "rounded_mean_integer_hit":int(summary["rounded_mean_integer_f"]==truth),
               "integer_nll":-lp,"crps_f":law.crps(truth),"modal_brier":(p-hit)**2,
               "display_category_brier":sum(x*x for x in probs)-2*probs[category]+1,
               "display_below_mass":probs[0],"display_above_mass":probs[-1]}
    reliability = {"MODAL":{"probability":p,"event":hit}}
    for low,high in bands:
        probability = float(law.mass(low-.5,high+.5)); event = int(low<=truth<=high)
        key = f"BAND_{low}_{high}"
        metrics[key+"_brier"] = (probability-event)**2
        reliability[key] = {"probability":probability,"event":event}
    for level in (50,80,90,95):
        low,high = summary["intervals"][str(level)]
        metrics[f"coverage_{level}"] = int(low<=truth<=high)
        metrics[f"width_f_{level}"] = high-low
    return serial(metrics), {"genuine_zero_probability":lp==-math.inf,
                            "probability_underflow":math.isfinite(lp) and math.exp(lp)==0.}, reliability


def regime_cutoffs(store):
    import pyarrow.dataset as ds
    rows = store.dataset.to_table(columns=["h_revision_abs_f","trend_q14_f"],
         filter=(ds.field("target_date")>="2022-01-01")&(ds.field("target_date")<="2025-09-06")).to_pylist()
    out = {}
    for name in ("h_revision_abs_f","trend_q14_f"):
        values = [abs(r[name]) for r in rows if r[name] is not None]
        if not values or not np.isfinite(values).all(): raise ContractError("development-only regime cutoff has no valid predictor support")
        out[name] = {"absolute_75th_percentile":float(np.quantile(values,.75,method="linear")),"predictor_rows":len(values)}
    return {"source_start":"2022-01-01","source_end":"2025-09-06","outcome_values_used":0,
            "transition":out,"cloud_fraction_threshold":.5,"snow_fraction_exclusive":0.,"reflectivity_fraction_exclusive":0.}


def feature_tags(store,day,cutoffs):
    import pyarrow.dataset as ds
    columns = ["issue_state_id","snow_asof_fraction","cloud_remaining_fraction","reflectivity_ge20_fraction",
               "h_revision_abs_f","trend_q14_f"]
    rows = store.dataset.to_table(columns=columns,filter=ds.field("target_date")==str(day)).to_pylist()
    return {r["issue_state_id"]:tags(r,cutoffs) for r in rows}


def tags(row,cutoffs):
    out = []
    for name,key,threshold,closed in [("snow","snow_asof_fraction",0.,False),
           ("cloud","cloud_remaining_fraction",.5,True),("convective","reflectivity_ge20_fraction",0.,False)]:
        x = row.get(key)
        state = "UNKNOWN" if x is None else "PRESENT" if (x>=threshold if closed else x>threshold) else "ABSENT"
        out.append(f"regime:{name}:{state}")
    values = [row.get(k) for k in ("h_revision_abs_f","trend_q14_f")]
    yes = any(x is not None and abs(x)>cutoffs["transition"][k]["absolute_75th_percentile"]
              for k,x in zip(("h_revision_abs_f","trend_q14_f"),values))
    out.append("regime:transition:"+("PRESENT" if yes else "UNKNOWN" if any(x is None for x in values) else "ABSENT"))
    return out


def age_tags(pred):
    provenance = json.loads(pred["source_provenance_json"])
    issue = datetime.fromisoformat(pred["issue_time_utc"].replace("Z","+00:00")); out = []
    for product in ("wrfsfcf","wrfsubhf"):
        cycle = provenance["selected_cycles"][product]["cycle_init_utc"]
        if cycle is None: label = "MISSING"
        else:
            age = (issue-datetime.fromisoformat(cycle.replace("Z","+00:00"))).total_seconds()/60
            if age<105: raise ContractError("future cycle reached scoring")
            label = "105_165" if age<165 else "165_225" if age<225 else "225_345" if age<345 else "345_PLUS"
        out.append(f"cycle_age:{product}:{label}")
    return out


def score_day(experiment,truth,day,result,native_units,policy,regime_by_issue,cache):
    import pyarrow.parquet as pq
    # This accessor verifies a committed forecast before permitting its query label.
    label = truth.score(day,commit_path=result["forecast_commit_path"])
    y = label["y_audited_f"]
    from .common import inside
    rows = pq.ParquetFile(inside(experiment,result["forecast_path"])).read().to_pylist()
    output = []
    for row in rows:
        pred = json.loads(row["prediction_json"]); minute = pred["local_issue_minute"]
        strata = age_tags(pred)+regime_by_issue[pred["issue_state_id"]]
        definitions = []
        for name in ARM_IDS:
            arm = pred["arms"][name]; law = None
            if arm["supported"]:
                learner = "tabicl" if name.startswith("KDEN_TABICL") else "tabdpt"
                bundle,receipt = native_units[learner,minute]
                ref = pred["native_references"][learner]
                if ref["sha256"]!=receipt["bundle_sha256"]: raise ContractError("scoring native reference changed")
                query = next(q for q in bundle["result"]["queries"] if q["weather"]["issue_state_id"]==pred["issue_state_id"])
                law = arm_law(query["law"],arm)
            definitions.append((name,arm["supported"],arm.get("fallback_reason"),law,arm))
        for source in ("H","Q"):
            base = pred["baselines"][source]; anchor = base["raw_anchor_f"]
            point = PointLaw(anchor) if base["point_supported"] else None
            definitions.append((source+"_POINT",base["point_supported"],None,point,describe(point) if point else None))
            law = None
            if base["distribution_supported"]:
                bundle,receipt = native_units["tabicl",minute]
                payload = bundle["result"]["baseline_contexts"][source]["residual_law"]
                law = cache.law((receipt["record_sha256"],source),payload,anchor)
            definitions.append((source+"_RESIDUAL",base["distribution_supported"],None,law,base.get("distribution")))
        for model,supported,reason,law,summary in definitions:
            metrics,flags,reliability = (None,{}, {}) if not supported or y is None else law_metrics(law,y,summary,policy["diagnostic_integer_bands"])
            output.append({"issue_state_id":pred["issue_state_id"],"target_date":str(day),"local_issue_minute":minute,
                           "model":model,"supported":supported,"support_reason":reason,"truth_available":y is not None,
                           "metrics":metrics,"flags":flags,"reliability":reliability,"strata":strata})
    return {"target_date":str(day),"forecast_commit_path":result["forecast_commit_path"],
            "truth_status":label["truth_qc_status"],"truth_available":y is not None,
            "verification_rows":output,"query_truth_values_kept_out_of_forecasts":True,"holdout_value_pages_read":0}


class Summary:
    """Streaming target-day averages; memory does not grow with issue rows."""
    def __init__(self):
        self.expected_days=0; self.expected=0; self.supported=0; self.scored=0; self.zero=0; self.underflow=0
        self.complete_days=0; self.available_days=0; self.truth_missing_days=0
        self.sums={"complete_day":defaultdict(float),"available_forecast":defaultdict(float)}
        self.reliability=defaultdict(lambda: [0,0.,0.,0.,0])
    def add(self,rows,expected):
        if expected<=0 or len(rows)!=expected or len({r["issue_state_id"] for r in rows})!=expected:
            raise ContractError("score population does not match its scheduled keys")
        self.expected_days+=1; self.expected+=expected
        self.supported+=sum(r["supported"] for r in rows)
        good = [r for r in rows if r["supported"] and r["truth_available"] and r["metrics"] is not None]
        self.truth_missing_days+=int(not any(r["truth_available"] for r in rows))
        self.scored+=len(good)
        if not good: return
        self.available_days+=1; complete=len(good)==expected; self.complete_days+=int(complete)
        self.zero+=sum(r["flags"]["genuine_zero_probability"] for r in good)
        self.underflow+=sum(r["flags"]["probability_underflow"] for r in good)
        for key in good[0]["metrics"]:
            mean = sum(numeric(r["metrics"][key]) for r in good)/len(good)
            self.sums["available_forecast"][key]+=mean
            if complete: self.sums["complete_day"][key]+=mean
        buckets=defaultdict(list)
        for r in good:
            for name,v in r["reliability"].items():
                bucket=min(9,int(v["probability"]*10)); buckets[name,bucket].append(v)
        for (name,bucket),values in buckets.items():
            entry=self.reliability[f"{name}:{bucket}"]
            entry[0]+=1; entry[1]+=sum(v["probability"] for v in values)/len(values)
            entry[2]+=sum(v["event"] for v in values)/len(values)
            entry[3]+=sum((v["probability"]-v["event"])**2 for v in values)/len(values); entry[4]+=len(values)
    def result(self):
        out={}
        for kind,n in (("complete_day",self.complete_days),("available_forecast",self.available_days)):
            values={k:v/n for k,v in self.sums[kind].items()} if n else {}
            if n: values["rmse_f"]=math.sqrt(values["squared_error_f"])
            out[kind]={"days":n,**values}
        out.update(expected_days=self.expected_days,expected_issues=self.expected,supported_issues=self.supported,
                   scored_issues=self.scored,supported_forecast_fraction=self.supported/self.expected if self.expected else None,
                   excluded_complete_days=self.expected_days-self.complete_days,truth_missing_days=self.truth_missing_days,
                   genuine_zero_probability_count=self.zero,probability_underflow_count=self.underflow,
                   reliability={k:{"days":v[0],"predicted_probability":v[1]/v[0],"observed_frequency":v[2]/v[0],
                                   "brier":v[3]/v[0],"issue_count":v[4]} for k,v in sorted(self.reliability.items())},
                   reliability_weighting="EQUAL_DAYS_WITH_AT_LEAST_ONE_FORECAST_IN_BIN_THEN_EQUAL_ISSUES_WITHIN_DAY_BIN")
        return serial(out)


class Scorecard:
    def __init__(self,policy):
        self.policy=policy; self.groups=defaultdict(Summary); self.pairs=defaultdict(lambda: (Summary(),Summary()))
        self.paired_days=[]; self.days=set(); self.support_first={}; self.reasons=defaultdict(int)
        self.nomination={m:Summary() for m in ("KDEN_TABICL_T3","KDEN_TABDPT_D2_NATIVE")}
    def add(self,day_result):
        day=day_result["target_date"]
        if day in self.days: raise ContractError("duplicate verification day")
        self.days.add(day); rows=day_result["verification_rows"]
        expected_minutes={t.astimezone(DENVER).hour*60+t.astimezone(DENVER).minute for t in issue_times(parse_date(day))}
        if len(rows)!=len(expected_minutes)*len(MODELS): raise ContractError("incomplete verification population")
        by_model={m:[] for m in MODELS}
        for r in rows:
            if r["model"] not in MODELS or r["target_date"]!=day: raise ContractError("wrong verification model/date")
            by_model[r["model"]].append(r)
            if r["supported"]: self.support_first.setdefault(r["model"],day)
            else: self.reasons[r["model"]+":"+str(r["support_reason"])]+=1
        month=day[:7]; season={12:"DJF",1:"DJF",2:"DJF",3:"MAM",4:"MAM",5:"MAM",6:"JJA",7:"JJA",8:"JJA",9:"SON",10:"SON",11:"SON"}[int(day[5:7])]
        for model,items in by_model.items():
            if {r["local_issue_minute"] for r in items}!=expected_minutes or len(items)!=len(expected_minutes): raise ContractError("minute/DST key mismatch")
            slices=defaultdict(list)
            for r in items:
                for key in ["month:"+month,"season:"+season,"minute:"+str(r["local_issue_minute"]),*r["strata"],"support:"+str(r["supported"])]: slices[key].append(r)
            for key,subset in slices.items(): self.groups["slice",key,model].add(subset,len(subset))
            for window,(lo,hi) in self.policy["windows"].items():
                subset=[r for r in items if lo<=r["local_issue_minute"]<=hi]
                self.groups["window",window,model].add(subset,len(subset))
        for window,(lo,hi) in self.policy["windows"].items():
            # All neural/Q and H-residual/Q comparisons are matched descriptions.
            # ONLY the two frozen flagship/Q contrasts belong to the inferential family.
            for candidate,control in [(m,"Q_RESIDUAL") for m in (*ARM_IDS,"H_RESIDUAL")]:
                a={r["issue_state_id"]:r for r in by_model[candidate] if lo<=r["local_issue_minute"]<=hi}
                b={r["issue_state_id"]:r for r in by_model[control] if lo<=r["local_issue_minute"]<=hi}
                if set(a)!=set(b): raise ContractError("comparison schedule differs")
                # Pair only identical supported keys, but retain the full scheduled denominator.
                shared={k for k in a if a[k]["metrics"] is not None and b[k]["metrics"] is not None}
                ar=[{**r,"supported":k in shared,"metrics":r["metrics"] if k in shared else None} for k,r in a.items()]
                br=[{**r,"supported":k in shared,"metrics":r["metrics"] if k in shared else None} for k,r in b.items()]
                sa,sb=self.pairs[window,candidate,control]; sa.add(ar,len(ar)); sb.add(br,len(br))
                if shared:
                    # Stable key order is required for byte-identical report reproduction
                    # in a later validation process with a different Python hash seed.
                    paired_keys=sorted(shared)
                    av=sum(numeric(a[k]["metrics"]["integer_nll"]) for k in paired_keys)/len(shared)
                    bv=sum(numeric(b[k]["metrics"]["integer_nll"]) for k in paired_keys)/len(shared)
                    diff=av-bv
                    self.paired_days.append(serial({"target_date":day,"window":window,"candidate":candidate,"control":control,
                        "paired_issues":len(shared),"expected_issues":len(a),"complete_day":len(shared)==len(a),
                        "candidate_integer_nll":av,"control_integer_nll":bv,
                        "difference":None if math.isnan(diff) else diff,"undefined_infinity_difference":math.isnan(diff)}))
        lo,hi=self.policy["windows"][self.policy["primary_window_name"]]
        joint={m:{r["issue_state_id"]:r for r in by_model[m] if lo<=r["local_issue_minute"]<=hi}
               for m in (*self.nomination,"Q_RESIDUAL")}
        keys=set(joint["Q_RESIDUAL"])
        if any(set(v)!=keys for v in joint.values()): raise ContractError("nomination schedules differ")
        shared={k for k in keys if all(v[k]["metrics"] is not None for v in joint.values())}
        for model,summary in self.nomination.items():
            summary.add([{**r,"supported":k in shared,"metrics":r["metrics"] if k in shared else None}
                         for k,r in joint[model].items()],len(keys))
    def result(self):
        windows={w:{m:self.groups["window",w,m].result() for m in MODELS} for w in self.policy["windows"]}
        slices=defaultdict(dict)
        for (kind,key,model),value in sorted(self.groups.items()):
            if kind=="slice": slices[key][model]=value.result()
        nominated={m:s.result() for m,s in self.nomination.items()}
        candidates=[(numeric(v["complete_day"]["integer_nll"]),v["complete_day"]["absolute_error_f"],m)
                    for m,v in nominated.items() if v["complete_day"]["days"] and
                    math.isfinite(numeric(v["complete_day"]["integer_nll"]))]
        return {"windows":windows,"descriptive_slices":dict(slices),"paired_comparisons":{
            f"{w}:{a}-vs-{b}":{"candidate":v[0].result(),"control":v[1].result(),"pairing":"IDENTICAL_SUPPORTED_ISSUE_STATE_IDS",
                "in_predeclared_inferential_family":[a,b] in self.policy["comparison_family"]}
            for (w,a,b),v in sorted(self.pairs.items())},"paired_daily_nll":self.paired_days,
            "first_supported_date":self.support_first,"unsupported_reasons":dict(self.reasons),
            "development_days":len(self.days),"threshold_verdicts": "NOT_HOLDOUT_VERDICTS",
            "holdout_scores_computed":False,"bootstrap_performed":False,
            "development_nomination":{"candidate":min(candidates)[2] if candidates else None,
                "rule":"LOWEST_COMPLETE_DAY_INTEGER_NLL_ON_IDENTICAL_T3_D2_Q_SUPPORTED_KEYS_IN_PRIMARY_02_14; MEAN_MAE_THEN_NAME_BREAK_TIES",
                "matched_scores":nominated,"owner_selection_still_required":True}}


def paired_calendar_bootstrap(calendar_values, *, block_days=7, draws=5000, seed=3751010):
    """T06 utility: paired daily differences on a COMPLETE consecutive calendar.

    None marks unscored days. Draw non-circular overlapping calendar blocks; do
    not compress missing dates into an adjacent sequence. Infinity makes that
    contrast non-finite/unbootstrappable rather than silently dropping failures.
    """
    if block_days not in (7,14) or draws<1 or len(calendar_values)<block_days: raise ContractError("invalid bootstrap schedule")
    data=np.array([np.nan if x is None else numeric(x) for x in calendar_values],float)
    if np.isinf(data).any(): return {"status":"NONFINITE_CONTRAST_NO_FINITE_INTERVAL"}
    if not np.isfinite(data).any(): return {"status":"NO_PAIRED_SCORES"}
    rng=np.random.default_rng(seed); out=[]; n=len(data)
    offsets=np.arange(block_days)
    for _ in range(draws):
        starts=rng.integers(0,n-block_days+1,size=math.ceil(n/block_days))
        sample=data[(starts[:,None]+offsets).ravel()[:n]]
        if np.isfinite(sample).any(): out.append(float(np.nanmean(sample)))
    if not out: return {"status":"NO_SCORED_DRAWS"}
    return {"status":"AVAILABLE","block_days":block_days,"requested_draws":draws,"scored_draws":len(out),"seed":seed,
            "point_difference":float(np.nanmean(data)),"interval_percentiles":[1.25,98.75],
            "interval":np.quantile(out,[.0125,.9875],method="linear").tolist()}
