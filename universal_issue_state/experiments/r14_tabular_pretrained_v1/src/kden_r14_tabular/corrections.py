"""Chronological, stage-specific corrections of preserved emitted forecast laws."""
from __future__ import annotations
import calendar
import math
from collections import Counter
from datetime import date
import numpy as np
from scipy.optimize import minimize
from .common import ContractError, digest
from .dates import label_cutoff, parse_date
from .laws import AffineLaw, QuantileLaw, from_payload

CALENDAR = ("sin1","cos1","sin2","cos2","hour","hour2","hour_sin","hour_cos")
WEATHER = ("trend_q14_f","dewpoint_deficit_remaining_f","cloud_remaining_fraction",
           "q_minus_h_common_f","h_revision_abs_f")
WIDTH = ("log_sigma","hour","sin1","cos1","trend_q14_f","q_minus_h_common_f","cloud_remaining_fraction")
RAW = {"tabicl":"KDEN_TABICL_RAW", "tabdpt":"KDEN_TABDPT_RAW"}
CONTROL = {"tabicl":"KDEN_TABICL_T1", "tabdpt":"KDEN_TABDPT_D0"}
CENTER = {"tabicl":"KDEN_TABICL_TRANSITION", "tabdpt":"KDEN_TABDPT_D2_NATIVE"}


def feature_values(row, sigma=None):
    d = parse_date(row["target_date"]); minute = row["local_issue_minute"]
    if minute not in range(120,961,15): raise ContractError("invalid correction issue minute")
    theta = 2*math.pi*(d.timetuple().tm_yday-1)/(366 if calendar.isleap(d.year) else 365)
    h = (minute/60-9)/7
    values = dict(zip(CALENDAR,(math.sin(theta),math.cos(theta),math.sin(2*theta),math.cos(2*theta),
                                h,h*h,h*math.sin(theta),h*math.cos(theta))))
    for key in WEATHER:
        v = row.get(key)
        if v is not None and not math.isfinite(v): raise ContractError("nonfinite correction feature")
        values[key],values[key+"_missing"] = v,float(v is None)
    if sigma is not None:
        if not math.isfinite(sigma) or sigma<=0: raise ContractError("width requires a positive native sigma")
        values["log_sigma"] = math.log(sigma)
    return values


def eligible_history(emissions, truth, update_date, expected_arm):
    """Only receipts-backed, supported, originally emitted controls may fit a stage."""
    cutoff = label_cutoff(update_date)
    labels = {r["target_date"]:r["y_audited_f"] for r in truth.context(update_date)}
    out,seen = [],set()
    for r in emissions:
        if r["arm"] != expected_arm: raise ContractError("wrong calibration-stage lineage")
        d = parse_date(r["target_date"])
        key = (str(d),r["local_issue_minute"])
        if key in seen: raise ContractError("duplicate emitted day/issue calibration history")
        seen.add(key)
        if not r.get("emission_receipt_sha256") or not r.get("coefficient_version"):
            raise ContractError("uncommitted/unversioned calibration forecast")
        if d >= cutoff or not r["supported"] or str(d) not in labels: continue
        if not math.isfinite(r["mean_f"]): raise ContractError("nonfinite emitted center")
        out.append({**r,"truth":labels[str(d)]})
    return sorted(out,key=lambda r:(r["target_date"],r["local_issue_minute"]))


def weights(rows, cutoff):
    if not rows or any(parse_date(r["target_date"])>=cutoff for r in rows):
        raise ContractError("empty or current/future calibration history")
    keys = [(r["target_date"],r["local_issue_minute"]) for r in rows]
    if len(set(keys)) != len(keys): raise ContractError("duplicate calibration day/issue")
    counts = Counter(r["target_date"] for r in rows)
    wday = {d:2**(-(cutoff-parse_date(d)).days/90) for d in counts}
    a = np.array(list(wday.values())); ess = float(a.sum()**2/(a@a))
    w = np.array([wday[r["target_date"]]/counts[r["target_date"]] for r in rows])
    return w*ess/w.sum(),ess


def metadata(rows,update,arm,stage):
    return {"stage":stage,"history_arm":arm,"update_date":str(update),
            "label_cutoff_exclusive":str(label_cutoff(update)),
            "history_days":len({r["target_date"] for r in rows}),
            "history_last_date":max((r["target_date"] for r in rows),default=None),
            "history_identity":digest([{k:r[k] for k in ("issue_state_id","emission_receipt_sha256","coefficient_version")} for r in rows])}


def minute_shifts(rows,cutoff):
    result = {}
    for minute in sorted({r["local_issue_minute"] for r in rows}):
        items = [r for r in rows if r["local_issue_minute"]==minute]
        if len(items)<60: continue
        w,ess = weights(items,cutoff)
        shift = float(np.average([r["truth"]-r["mean_f"] for r in items],weights=w)*ess/(ess+20))
        result[str(minute)] = {"shift_f":shift,"days":len(items),"effective_days":ess}
    return result


def version(body): return {**body,"coefficient_version":digest(body)}


def fit_location(emissions,truth,update,learner):
    arm = RAW[learner]; rows = eligible_history(emissions,truth,update,arm)
    out = metadata(rows,update,arm,"MONTHLY_LOCATION")
    out["minutes"] = minute_shifts(rows,label_cutoff(update)) if out["history_days"]>=90 else {}
    out["fit_status"] = "SUPPORTED" if out["minutes"] else "UNSUPPORTED_INSUFFICIENT_EMITTED_HISTORY"
    return version(out)


def design(rows,names,*,weights_array=None,spec=None):
    X = np.array([[r["features"].get(k) if r["features"].get(k) is not None else np.nan for k in names]
                  for r in rows],float).reshape(len(rows),len(names))
    if np.isinf(X).any(): raise ContractError("infinite ancillary correction input")
    if spec is None:
        if weights_array is None or len(weights_array)!=len(rows): raise ContractError("fit weights required")
        medians = np.array([np.median(c[~np.isnan(c)]) if (~np.isnan(c)).any() else 0. for c in X.T])
        X = np.where(np.isnan(X),medians,X)
        mean = np.average(X,axis=0,weights=weights_array)
        scale = np.sqrt(np.average((X-mean)**2,axis=0,weights=weights_array))
        scale = np.where(scale>1e-8,scale,1.)
        spec = {"names":list(names),"medians":medians.tolist(),"means":mean.tolist(),"scales":scale.tolist()}
    else:
        if list(names)!=spec["names"]: raise ContractError("correction feature order changed")
        X = np.where(np.isnan(X),spec["medians"],X)
    X = (X-np.asarray(spec["means"]))/np.asarray(spec["scales"])
    if not np.isfinite(X).all(): raise ContractError("nonfinite correction design")
    return X,spec


def fit_center(emissions,truth,update,learner):
    arm = CONTROL[learner]; rows = eligible_history(emissions,truth,update,arm)
    out = metadata(rows,update,arm,"WEEKLY_CENTER")
    out.update(minutes={},smooth=None,fit_status="UNSUPPORTED_INSUFFICIENT_EMITTED_HISTORY")
    if out["history_days"]<90: return version(out)
    out["minutes"] = minute_shifts(rows,label_cutoff(update))
    items = [r for r in rows if str(r["local_issue_minute"]) in out["minutes"]]
    if not items: return version(out)
    names = CALENDAR + (WEATHER+tuple(k+"_missing" for k in WEATHER) if learner=="tabicl" else ())
    w,ess = weights(items,label_cutoff(update)); X,spec = design(items,names,weights_array=w)
    y = np.array([r["truth"]-r["mean_f"]-out["minutes"][str(r["local_issue_minute"])]["shift_f"] for r in items])
    coef = np.linalg.solve(X.T@(w[:,None]*X)+100*np.eye(len(names)),X.T@(w*y))
    if not np.isfinite(coef).all(): raise ContractError("nonfinite center ridge solution")
    out.update(fit_status="SUPPORTED",smooth={"spec":spec,"coefficients":coef.tolist(),"slope_penalty":100,
                                             "intercept_fitted":False,"effective_days":ess})
    return version(out)


class QuantileBatch:
    """Vectorized exact spline density/CDF for integer-bin width likelihood."""
    def __init__(self,quantiles):
        laws = [QuantileLaw(q) for q in quantiles]
        self.q = np.asarray([v.q for v in laws]); self.p = np.arange(1,1000)/1000
        self.left,self.right = np.array([v.beta_left for v in laws]),np.array([v.beta_right for v in laws])
    def cdf_density(self,values):
        n,k = self.q.shape
        if np.shape(values)!=(n,): raise ContractError("width boundary shape mismatch")
        low,high,ix = np.zeros(n,int),np.full(n,k,int),np.arange(n)
        while np.any(low<high):
            mid = (low+high)//2; active = low<high; less = self.q[ix,np.minimum(mid,k-1)]<values
            low = np.where(active&less,mid+1,low); high = np.where(active&~less,mid,high)
        j = low; below,above = j==0,j==k; middle = ~(below|above)
        cdf,density = np.zeros(n),np.zeros(n)
        take = below&(self.left>0)
        cdf[take] = self.p[0]*np.exp(np.minimum(0.,(values[take]-self.q[take,0])/self.left[take]))
        density[take] = cdf[take]/self.left[take]; cdf[above] = 1.
        take = above&(self.right>0)
        survival = (1-self.p[-1])*np.exp(np.minimum(0.,(self.q[take,-1]-values[take])/self.right[take]))
        cdf[take] = 1-survival; density[take] = survival/self.right[take]
        a,b = ix[middle],j[middle]
        density[middle] = (self.p[b]-self.p[b-1])/(self.q[a,b]-self.q[a,b-1])
        cdf[middle] = self.p[b-1]+(values[middle]-self.q[a,b-1])*density[middle]
        return cdf,density
    def likelihood(self,errors,eta):
        lo,hi = (errors-.5)/np.exp(eta),(errors+.5)/np.exp(eta)
        flo,dlo = self.cdf_density(lo); fhi,dhi = self.cdf_density(hi); mass = fhi-flo
        with np.errstate(divide="ignore",invalid="ignore"):
            lp,derivative = np.log(mass),(lo*dlo-hi*dhi)/mass
        for take,beta,edge,left in [(hi<self.q[:,0],self.left,self.q[:,0],True),
                                    (lo>self.q[:,-1],self.right,self.q[:,-1],False)]:
            take = take&(beta>0); z = (hi[take]-lo[take])/beta[take]
            lp[take] = ((math.log(self.p[0])+(hi[take]-edge[take])/beta[take]) if left else
                        (math.log1p(-self.p[-1])+(edge[take]-lo[take])/beta[take]))+np.log(-np.expm1(-z))
            with np.errstate(over="ignore"): ratio = z/np.expm1(z)
            derivative[take] = (-hi[take]/beta[take] if left else lo[take]/beta[take])-ratio
        return lp,derivative


def fit_width(emissions,truth,update):
    arm = CENTER["tabicl"]; rows = eligible_history(emissions,truth,update,arm)
    out = metadata(rows,update,arm,"WEEKLY_T3_WIDTH")
    counts = Counter(str(r["local_issue_minute"]) for r in rows)
    out.update(minutes={k:{"days":v} for k,v in counts.items() if v>=60},
               fit_status="UNSUPPORTED_INSUFFICIENT_EMITTED_HISTORY",smooth=None)
    if out["history_days"]<90: out["minutes"] = {}; return version(out)
    rows = [r for r in rows if str(r["local_issue_minute"]) in out["minutes"]]
    if not rows: return version(out)
    if any(r["t1_sigma_f"]<=0 for r in rows):
        out.update(fit_status="UNSUPPORTED_ZERO_SIGMA",minutes={}); return version(out)
    names = WIDTH+tuple(k+"_missing" for k in WIDTH[-3:])
    w,ess = weights(rows,label_cutoff(update)); X,spec = design(rows,names,weights_array=w)
    X = np.column_stack((np.ones(len(rows)),X))
    batch = QuantileBatch([np.asarray(r["t1_quantiles_f"])-r["t1_mean_f"] for r in rows])
    errors = np.array([r["truth"]-r["mean_f"] for r in rows]); penalty = np.r_[20.,np.full(len(names),100.)]
    def objective(beta):
        raw = X@beta; eta = np.clip(raw,-5.,5.); outside = raw-eta
        lp,derivative = batch.likelihood(errors,eta)
        if not np.isfinite(lp).all() or not np.isfinite(derivative).all():
            raise ContractError("degenerate width likelihood; no probability jitter/floor permitted")
        loss = -w@lp+.5*(penalty*beta)@beta+1e6*(outside@outside)
        grad = X.T@(-w*derivative*(np.abs(raw)<5)+2e6*outside)+penalty*beta
        return float(loss),grad
    fit = minimize(objective,np.zeros(X.shape[1]),jac=True,method="L-BFGS-B",
                   options={"maxiter":300,"maxls":50,"ftol":1e-10,"gtol":1e-5})
    loss,grad = objective(fit.x)
    if not fit.success or not np.isfinite(fit.x).all() or np.max(np.abs(X@fit.x))>=5:
        raise ContractError(f"width fit failed or guard activated: {fit.message}; objective={loss}; gradient={np.max(np.abs(grad))}")
    out.update(fit_status="SUPPORTED",smooth={"spec":spec,"coefficients":fit.x.tolist(),"effective_days":ess},
               optimizer={"method":"L-BFGS-B","success":True,"message":str(fit.message),"iterations":int(fit.nit),
                          "function_evaluations":int(fit.nfev),"objective":loss,"gradient_inf_norm":float(np.max(np.abs(grad)))})
    return version(out)


def correction_shift(fit,row):
    key = str(row["local_issue_minute"])
    if fit["fit_status"]!="SUPPORTED" or key not in fit["minutes"]: return 0.,False
    shift = fit["minutes"][key]["shift_f"]
    smooth = fit.get("smooth")
    if smooth:
        X,_ = design([{"features":feature_values(row)}],smooth["spec"]["names"],spec=smooth["spec"])
        shift += float(X[0]@smooth["coefficients"])
    if not math.isfinite(shift): raise ContractError("nonfinite correction shift")
    return shift,True


def width_scale(fit,row,sigma):
    if sigma<=0 or fit["fit_status"]!="SUPPORTED" or str(row["local_issue_minute"]) not in fit["minutes"]: return 1.,False
    smooth = fit["smooth"]
    X,_ = design([{"features":feature_values(row,sigma)}],smooth["spec"]["names"],spec=smooth["spec"])
    eta = float(np.r_[1.,X[0]]@smooth["coefficients"])
    if not math.isfinite(eta) or abs(eta)>=5: raise ContractError("width extrapolation guard activated; no silent cap")
    return math.exp(eta),True


def arm_law(shape,arm): return AffineLaw(from_payload(shape),arm["shift_f"],arm["scale"])


def emit_arms(native,row,learner,location,center,width=None):
    """All transforms reference one native shape. Preserve T1 shape for width history."""
    from .laws import describe
    raw = from_payload(native); raw_mean,sigma = raw.moments()
    shift,ok = correction_shift(location,row)
    extra,center_ok = correction_shift(center,row)
    center_ok &= ok
    if not center_ok: extra = 0.
    definitions = [(RAW[learner],0.,1.,True,"NATIVE_CONTEXT",None),
                   (CONTROL[learner],shift,1.,ok,location["coefficient_version"],None if ok else location["fit_status"]),
                   (CENTER[learner],shift+extra,1.,center_ok,center["coefficient_version"],None if center_ok else "UNSUPPORTED_CENTER_OR_CONTROL_HISTORY")]
    if learner=="tabicl":
        s,width_ok = width_scale(width,row,sigma); width_ok &= center_ok
        if not width_ok: s = 1.
        mu_t1,mu_transition = raw_mean+shift,raw_mean+shift+extra
        # Equivalent transform of RAW: transition_center+s*(RAW-raw_mean).
        definitions.append(("KDEN_TABICL_T3",mu_transition-s*raw_mean,s,width_ok,
                            width["coefficient_version"],None if width_ok else "UNSUPPORTED_WIDTH_CENTER_OR_ZERO_SIGMA"))
    result = {}
    for name,delta,scale,supported,ver,reason in definitions:
        law = AffineLaw(raw,delta,scale)
        result[name] = {"shape":RAW[learner],"shift_f":delta,"scale":scale,"supported":supported,
                        "coefficient_version":ver,"fallback_reason":reason,**describe(law)}
    return result
