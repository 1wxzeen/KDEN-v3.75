"""Full-history corrections with bounded native-shape memory; no history thinning.

The accepted T03 objective/update rules are unchanged. Quantiles are resolved
in file groups into an experiment-local scratch mapping and evaluated in chunks.
No model, label, minute, day or tail is omitted to obtain the memory bound.
"""
from __future__ import annotations
import math
import tempfile
from collections import Counter, defaultdict
from functools import lru_cache
import numpy as np
from scipy.optimize import minimize
from .common import ContractError, hash_file, inside, read_json, verify_record
from .corrections import (RAW, CONTROL, CENTER, WIDTH, QuantileBatch, design, eligible_history,
                          feature_values, fit_center, fit_location, metadata, version, weights)
from .dates import label_cutoff
from .laws import QuantileLaw
from .replay import History


class FullHistory(History):
    @lru_cache(maxsize=4)
    def native(self, path, sha):
        if hash_file(inside(self.experiment, path)) != sha:
            raise ContractError("preserved native shape changed")
        return verify_record(read_json(inside(self.experiment, path)))["result"]

    def rows(self, arm, update):
        cutoff, out = str(label_cutoff(update)), []
        for rows, receipt_sha in self.days:
            for r in rows:
                if r["target_date"] >= cutoff or not r["arms"][arm]["supported"]:
                    continue
                a = r["arms"][arm]
                item = {k:r[k] for k in ("issue_state_id", "target_date", "local_issue_minute")}
                item.update(arm=arm, emission_receipt_sha256=receipt_sha,
                            coefficient_version=a["coefficient_version"], supported=True,
                            mean_f=a["mean_f"], sigma_f=a["sigma_f"], features=feature_values(r["weather"]))
                if arm == CENTER["tabicl"]:
                    t1 = r["arms"][CONTROL["tabicl"]]
                    item.update(t1_mean_f=t1["mean_f"], t1_sigma_f=t1["sigma_f"],
                                t1_shift_f=t1["shift_f"], shape_reference=r["native_references"]["tabicl"])
                    if t1["sigma_f"] > 0:
                        item["features"] = feature_values(r["weather"], t1["sigma_f"])
                out.append(item)
        return out

    def fill_shapes(self, rows, q, left, right):
        groups = defaultdict(list)
        for i, r in enumerate(rows):
            ref = r["shape_reference"]
            groups[ref["path"], ref["sha256"]].append((i, r))
        for (path, sha), items in groups.items():
            native = self.native(path, sha)
            queries = {v["weather"]["issue_state_id"]:v for v in native["queries"]}
            for i, r in items:
                query = queries[r["issue_state_id"]]
                if query["law"]["kind"] != "quantiles" or query["context_identity"] != r["shape_reference"]["context_identity"]:
                    raise ContractError("wrong width-history shape/context")
                centered = np.asarray(query["law"]["quantiles_f"]) + r["t1_shift_f"] - r["t1_mean_f"]
                law = QuantileLaw(centered)
                q[i], left[i], right[i] = law.q, law.beta_left, law.beta_right


class ChunkedWidthObjective:
    """Exact T03 bin likelihood and gradient summed over bounded row chunks."""
    def __init__(self, q, left, right, X, errors, w, penalty, chunk=512):
        self.q,self.left,self.right,self.X,self.errors,self.w,self.penalty,self.chunk = q,left,right,X,errors,w,penalty,chunk

    def __call__(self, beta):
        raw = self.X @ beta
        eta = np.clip(raw, -5., 5.); outside = raw-eta
        loss = .5*(self.penalty*beta)@beta + 1e6*(outside@outside)
        grad = self.X.T@(2e6*outside) + self.penalty*beta
        for start in range(0, len(self.errors), self.chunk):
            sl = slice(start, start+self.chunk)
            batch = QuantileBatch.__new__(QuantileBatch)
            batch.q = self.q[sl]; batch.p = np.arange(1,1000)/1000
            batch.left, batch.right = self.left[sl], self.right[sl]
            lp, derivative = batch.likelihood(self.errors[sl], eta[sl])
            if not np.isfinite(lp).all() or not np.isfinite(derivative).all():
                raise ContractError("degenerate width likelihood; no jitter or probability floor")
            loss -= self.w[sl]@lp
            grad += self.X[sl].T@(-self.w[sl]*derivative*(np.abs(raw[sl])<5))
        return float(loss), grad


def fit_width(history, truth, update):
    rows = eligible_history(history.rows(CENTER["tabicl"],update),truth,update,CENTER["tabicl"])
    out = metadata(rows,update,CENTER["tabicl"],"WEEKLY_T3_WIDTH")
    by_minute = Counter(str(r["local_issue_minute"]) for r in rows)
    out.update(minutes={k:{"days":v} for k,v in by_minute.items() if v>=60},
               fit_status="UNSUPPORTED_INSUFFICIENT_EMITTED_HISTORY", smooth=None)
    if out["history_days"] < 90:
        out["minutes"] = {}; return version(out)
    rows = [r for r in rows if str(r["local_issue_minute"]) in out["minutes"]]
    if not rows:
        return version(out)
    if any(r["t1_sigma_f"]<=0 for r in rows):
        out.update(fit_status="UNSUPPORTED_ZERO_SIGMA", minutes={}); return version(out)
    names = WIDTH + tuple(k+"_missing" for k in WIDTH[-3:])
    w, ess = weights(rows,label_cutoff(update)); X,spec = design(rows,names,weights_array=w)
    X = np.column_stack((np.ones(len(rows)),X))
    errors = np.array([r["truth"]-r["mean_f"] for r in rows])
    penalty = np.r_[20.,np.full(len(names),100.)]
    scratch = inside(history.experiment, ".cache/tmp"); scratch.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="t04-width-",dir=scratch) as directory:
        q = np.memmap(directory+"/quantiles.bin",mode="w+",dtype="float64",shape=(len(rows),999))
        left,right = np.empty(len(rows)),np.empty(len(rows))
        history.fill_shapes(rows,q,left,right); q.flush()
        objective = ChunkedWidthObjective(q,left,right,X,errors,w,penalty)
        fit = minimize(objective,np.zeros(X.shape[1]),jac=True,method="L-BFGS-B",
                       options={"maxiter":300,"maxls":50,"ftol":1e-10,"gtol":1e-5})
        loss,grad = objective(fit.x)
        del objective,q  # close only this unit's scratch mapping before cleanup
    if not fit.success or not np.isfinite(fit.x).all() or np.max(np.abs(X@fit.x))>=5:
        raise ContractError(f"width fit failed or guard activated: {fit.message}; objective={loss}; gradient={np.max(np.abs(grad))}")
    out.update(fit_status="SUPPORTED",smooth={"spec":spec,"coefficients":fit.x.tolist(),"effective_days":ess},
               optimizer={"method":"L-BFGS-B","success":True,"message":str(fit.message),"iterations":int(fit.nit),
                          "function_evaluations":int(fit.nfev),"objective":loss,"gradient_inf_norm":float(np.max(np.abs(grad)))})
    return version(out)


def fit_coefficients(history, truth, day, monthly=None, weekly=None, *, block_start=False):
    if monthly is None or block_start:
        monthly = {n:fit_location(history.rows(RAW[n],day),truth,day,n) for n in RAW}
    if weekly is None or block_start or day.weekday()==0:
        weekly = {n:fit_center(history.rows(CONTROL[n],day),truth,day,n) for n in RAW}
        weekly["width"] = fit_width(history,truth,day)
    return {"monthly":monthly,"weekly":weekly}
