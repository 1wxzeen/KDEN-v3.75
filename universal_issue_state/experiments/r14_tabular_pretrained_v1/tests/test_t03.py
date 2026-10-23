"""Short synthetic tests only: no checkpoint load, neural fit, network or holdout."""
import calendar
import json
import math
import shutil
import sys
import tempfile
import unittest
from datetime import UTC,date,datetime,timedelta
from pathlib import Path
from unittest.mock import MagicMock,patch
import numpy as np
from scipy.integrate import quad
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from kden_r14_tabular.common import ContractError,atomic_json,digest,hash_file,read_json,signed
from kden_r14_tabular.dates import DENVER,issue_times,label_cutoff
from kden_r14_tabular.truth import TruthAccess
from kden_r14_tabular.laws import AffineLaw,HistogramLaw,KernelLaw,PointLaw,QuantileLaw,describe,losses,native_law
from kden_r14_tabular.corrections import (CALENDAR,CENTER,CONTROL,RAW,QuantileBatch,correction_shift,design,
    eligible_history,emit_arms,feature_values,fit_center,fit_location,fit_width,version,weights,width_scale)
from kden_r14_tabular.replay import (History,UnitStore,assert_invariant,bounded_plan,check_query,day_balanced_scoring,
    check_coefficients,development_plan,fit_coefficients,identity,plan_counts)
from kden_r14_tabular.t03_workflow import RECIPE,performance_report,recipe,run_t03,validate_t03
from kden_r14_tabular.t03_cli import snapshot


def weather(d="2022-01-01",minute=600):
    day = date.fromisoformat(d); issue = datetime.combine(day,datetime.min.time(),DENVER)+timedelta(minutes=minute)
    issue = issue.astimezone(UTC); init = issue.replace(minute=0)-timedelta(hours=2)
    cycles = {name:{"issue_state_id":"ISSUE_"+d+"_"+str(minute),"issue_time_utc":issue.isoformat(),
                   "cycle_init_utc":init.isoformat(),"emulated_complete_time_utc":(init+timedelta(minutes=105)).isoformat(),
                   "previous_cycle_init_utc":(init-timedelta(hours=1)).isoformat(),
                   "previous_emulated_complete_time_utc":(init-timedelta(hours=1)+timedelta(minutes=105)).isoformat()}
              for name in ("wrfsfcf","wrfsubhf")}
    return {"issue_state_id":"ISSUE_"+d+"_"+str(minute),"target_date":d,"issue_time_utc":issue.isoformat(),
            "local_issue_minute":minute,"availability_policy_id":"KDEN_HIST_COMPLETE_L105_V1",
            "anchor_q_f":60.,"anchor_h_f":59.,"native_status":"READY","source_feature_path":"synthetic.parquet",
            "source_feature_sha256":"a"*64,"source_provenance_json":json.dumps({"selected_cycles":cycles}),
            "coverage_diagnostics_json":"{}","trend_q14_source_ids_json":"[]","trend_q14_status":"READY",
            "trend_q14_f":1.,"dewpoint_deficit_remaining_f":12.,"cloud_remaining_fraction":.3,
            "q_minus_h_common_f":1.,"h_revision_abs_f":.5}


def truth(rows): return TruthAccess([{"target_date":d,"y_audited_f":y} for d,y in rows],ROOT)


def histories(arm,count=100,minutes=(600,615),mean=60.,sigma=1.):
    rows,labels = [],[]
    for i in range(count):
        d = str(date(2022,1,1)+timedelta(days=i)); labels.append((d,62))
        for minute in minutes:
            r = weather(d,minute)
            rows.append({"target_date":d,"issue_state_id":r["issue_state_id"],"local_issue_minute":minute,
                         "arm":arm,"supported":True,"mean_f":mean,"sigma_f":sigma,
                         "features":feature_values(r,sigma),"coefficient_version":"original_"+d,
                         "emission_receipt_sha256":"b"*64,"t1_sigma_f":sigma,"t1_mean_f":mean,
                         "t1_quantiles_f":np.linspace(mean-3,mean+3,999).tolist()})
    return rows,truth(labels)


class Laws(unittest.TestCase):
    def test_histogram_moments(self):
        mu,sigma = HistogramLaw([0,1],[0]).moments()
        self.assertEqual(mu,.5); self.assertAlmostEqual(sigma,math.sqrt(1/12))
    def test_histogram_finite_support(self):
        h = HistogramLaw([0,1,3],[0,0]); self.assertEqual(h.log_mass(4,5),-math.inf)
        self.assertAlmostEqual(float(h.mass(-100,100)),1.)
    def test_histogram_crps_uniform(self): self.assertAlmostEqual(HistogramLaw([0,1],[0]).crps(.5),1/12)
    def test_histogram_crps_outside(self): self.assertAlmostEqual(HistogramLaw([0,1],[0]).crps(2),4/3)
    def test_histogram_log_underflow_not_zero(self):
        h = HistogramLaw([0,1,2],[0,-1000]); self.assertEqual(float(h.mass(1,2)),0.)
        self.assertEqual(h.log_mass(1,2),-1000.)
    def test_point_boundary(self):
        p = PointLaw(60.5); self.assertEqual(float(p.mass(59.5,60.5)),0.)
        self.assertEqual(float(p.mass(60.5,61.5)),1.); self.assertEqual(p.modal_integer(),(61,1.))
    def test_repeated_quantile_atoms(self):
        q = QuantileLaw(np.r_[np.full(500,60.5),np.full(499,61.5)])
        self.assertEqual(q.beta_left,0.); self.assertEqual(q.beta_right,0.)
        # Half the mass is an atom at the left knot, .001 is the intervening
        # continuous spline segment, and .499 is the right-knot atom.
        self.assertAlmostEqual(float(q.mass(60.5,61.5)),.501)
        self.assertAlmostEqual(float(q.mass(61.5,62.5)),.499)
        self.assertEqual(q.modal_integer()[0],61)
    def test_smallest_integer_mode_tie(self):
        self.assertEqual(HistogramLaw([60.5,62.5],[0]).modal_integer()[0],61)
    def test_constant_quantiles(self):
        q = QuantileLaw(np.full(999,2.5)); self.assertEqual(q.moments(),(2.5,0.)); self.assertEqual(q.crps(0),2.5)
        self.assertEqual(float(q.cdf(2.5,left=True)),0.); self.assertEqual(float(q.cdf(2.5)),1.)
    def test_sorted_quantile_crossings(self):
        q = QuantileLaw(np.arange(999)[::-1]); self.assertEqual(q.crossings,998); self.assertEqual(q.max_sort_change,998.)
    def test_tail_log_underflow_not_zero(self):
        q = QuantileLaw(-np.log1p(-np.arange(1,1000)/1000))
        self.assertEqual(float(q.mass(1000,1001)),0.); self.assertTrue(math.isfinite(q.log_mass(1000,1001)))
    def test_endpoint_plateau_and_positive_tail(self):
        raw = np.linspace(0,1,999); raw[-10:] = 1.; q = QuantileLaw(raw)
        self.assertGreater(q.beta_right,0.)
        self.assertAlmostEqual(math.exp(q.log_mass(1.,2.)),float(q.mass(1.,2.)),places=12)
    def test_quantile_analytic_integrals(self):
        q = QuantileLaw(np.linspace(-2,2,999)); mu,s = q.moments()
        self.assertAlmostEqual(mu,0.,places=12)
        numeric_mu = quad(lambda p:q.quantile(p),0,1,epsabs=1e-8,points=[.001,.999],limit=100)[0]
        self.assertAlmostEqual(mu,numeric_mu,places=7)
        y = .31; lo,hi = q.q[0]-40*q.beta_left,q.q[-1]+40*q.beta_right
        numerical = quad(lambda x:float(q.cdf(x))**2,lo,y,points=[q.q[0]],epsabs=1e-8)[0]
        numerical += quad(lambda x:(1-float(q.cdf(x)))**2,y,hi,points=[q.q[-1]],epsabs=1e-8)[0]
        self.assertAlmostEqual(q.crps(y),numerical,places=7)
        second = quad(lambda p:q.quantile(p)**2,0,1,points=[.001,.999],epsabs=1e-8,limit=100)[0]
        self.assertAlmostEqual(s*s,second-mu*mu,places=7)
    def test_affine_mass_and_crps(self):
        h = HistogramLaw([0,1],[0]); a = AffineLaw(h,60,2)
        self.assertEqual(a.moments()[0],61); self.assertAlmostEqual(a.crps(61),2*h.crps(.5))
        self.assertAlmostEqual(float(a.mass(60,61)),.5)
    def test_anchor_added_once(self):
        dpt = native_law({"borders":np.array([-1,1]),"logits":np.array([[0.]])},"tabdpt",0,60)
        icl = native_law({"quantiles":np.zeros((1,999))},"tabicl",0,60)
        self.assertEqual(dpt.moments()[0],60); self.assertEqual(icl.moments()[0],60)
    def test_true_mode_outside_export(self):
        h = HistogramLaw([150,151],[0]); self.assertEqual(h.modal_integer()[0],150)
        d = describe(h); self.assertEqual(d["pmf_above120"],1.); self.assertEqual(sum(d["pmf_minus40_to120"]),0.)
    def test_malformed_laws_fail(self):
        for fn in [lambda:QuantileLaw([1]),lambda:HistogramLaw([0,0],[0]),lambda:HistogramLaw([0,1],[math.nan]),lambda:PointLaw(math.inf),lambda:AffineLaw(PointLaw(1),0,0)]:
            with self.assertRaises(ContractError): fn()
    def test_kernel_mass_and_crps(self):
        k = KernelLaw([0.]); self.assertAlmostEqual(float(k.mass(-math.inf,math.inf)),1.)
        self.assertAlmostEqual(k.crps(0),1.25*(math.sqrt(2)-1)/math.sqrt(math.pi))
        self.assertTrue(math.isfinite(k.log_mass(1000,1001)))
    def test_no_hidden_probability_floor(self):
        r = losses(HistogramLaw([0,1],[0]),2); self.assertEqual(r["integer_nll"],math.inf); self.assertTrue(r["genuine_zero_probability"])


class Corrections(unittest.TestCase):
    def test_monthly_shrinkage(self):
        rows,t = histories(RAW["tabicl"]); update = date(2022,5,1)
        fit = fit_location(rows,t,update,"tabicl"); w,ess = weights(rows[:200:2],label_cutoff(update))
        shift,ok = correction_shift(fit,weather("2022-05-01")); self.assertTrue(ok)
        self.assertAlmostEqual(shift,2*ess/(ess+20)); self.assertEqual(fit["history_arm"],RAW["tabicl"])
    def test_day_weights(self):
        rows = [{"target_date":"2022-01-01","local_issue_minute":m} for m in (600,615,630)]
        rows += [{"target_date":"2022-01-02","local_issue_minute":600}]
        w,ess = weights(rows,date(2022,2,1)); self.assertAlmostEqual(w.sum(),ess)
        self.assertAlmostEqual(w[:3].sum()/w[3],2**(-1/90))
    def test_cutoff_equality_excluded(self):
        rows,t = histories(RAW["tabicl"],count=10)
        out = eligible_history(rows,t,date(2022,1,17),RAW["tabicl"])
        self.assertEqual(max(r["target_date"] for r in out),"2022-01-09")
        with self.assertRaises(ContractError): t.context("2022-01-17",dates=["2022-01-10"])
    def test_wrong_stage_rejected(self):
        rows,t = histories(RAW["tabicl"])
        with self.assertRaises(ContractError): fit_center(rows,t,date(2022,5,1),"tabicl")
    def test_uncommitted_history_rejected(self):
        rows,t = histories(RAW["tabicl"]); rows[0]["emission_receipt_sha256"] = None
        with self.assertRaises(ContractError): fit_location(rows,t,date(2022,5,1),"tabicl")
    def test_identity_warmup_unsupported(self):
        rows,t = histories(RAW["tabicl"],count=89); f = fit_location(rows,t,date(2022,5,1),"tabicl")
        self.assertEqual(correction_shift(f,weather("2022-05-01")),(0.,False))
    def test_exact_minute_support(self):
        rows,t = histories(RAW["tabicl"]); rows = [r for r in rows if r["local_issue_minute"]==600 or r["target_date"]<"2022-02-15"]
        f = fit_location(rows,t,date(2022,5,1),"tabicl")
        self.assertTrue(correction_shift(f,weather("2022-05-01",600))[1]); self.assertFalse(correction_shift(f,weather("2022-05-01",615))[1])
    def test_center_shapes_and_no_intercept(self):
        for learner,columns in (("tabicl",18),("tabdpt",8)):
            rows,t = histories(CONTROL[learner]); f = fit_center(rows,t,date(2022,5,1),learner)
            self.assertFalse(f["smooth"]["intercept_fitted"]); self.assertEqual(len(f["smooth"]["coefficients"]),columns)
    def test_context_only_imputation(self):
        rows = [{"features":{"x":None}},{"features":{"x":2.}}]; X,s = design(rows,["x"],weights_array=np.ones(2))
        _,out = design([{"features":{"x":None}}],["x"],spec=s); self.assertEqual(out,s); self.assertEqual(s["medians"],[2.])
        with self.assertRaises(ContractError): design([{"features":{"x":math.inf}}],["x"],weights_array=np.ones(1))
    def test_preserves_history_and_versions(self):
        rows,t = histories(CONTROL["tabicl"]); before = digest(rows)
        fit_center(rows,t,date(2022,5,1),"tabicl"); self.assertEqual(digest(rows),before)
    def test_width_gradient_matches_numeric(self):
        q = np.stack([np.linspace(-3,3,999),np.linspace(-2,2,999)]); batch = QuantileBatch(q)
        errors,eta = np.array([.27,7.]),np.array([.1,-.2]); lp,g = batch.likelihood(errors,eta)
        eps = 1e-6
        numeric = (batch.likelihood(errors,eta+eps)[0]-batch.likelihood(errors,eta-eps)[0])/(2*eps)
        np.testing.assert_allclose(g,numeric,rtol=1e-5,atol=1e-5)
    def test_width_optimizer_and_guard(self):
        rows,t = histories(CENTER["tabicl"],count=91,minutes=(600,),mean=60.)
        f = fit_width(rows,t,date(2022,5,1)); self.assertEqual(f["fit_status"],"SUPPORTED")
        self.assertTrue(f["optimizer"]["success"]); s,ok = width_scale(f,weather("2022-05-01"),1.); self.assertTrue(ok); self.assertGreater(s,0)
        f["smooth"]["coefficients"][0] = 6.
        with self.assertRaises(ContractError): width_scale(f,weather("2022-05-01"),1.)
    def test_width_failure_fails_unit(self):
        rows,t = histories(CENTER["tabicl"],count=90,minutes=(600,))
        failure = MagicMock(x=np.zeros(11),success=False,message="synthetic failure",nit=0,nfev=1)
        with patch("kden_r14_tabular.corrections.minimize",return_value=failure):
            with self.assertRaises(ContractError): fit_width(rows,t,date(2022,5,1))
    def test_width_zero_sigma_no_spread(self):
        rows,t = histories(CENTER["tabicl"],count=90,minutes=(600,)); rows[0]["t1_sigma_f"] = 0.
        f = fit_width(rows,t,date(2022,5,1)); self.assertEqual(f["fit_status"],"UNSUPPORTED_ZERO_SIGMA")
        self.assertEqual(width_scale(f,weather("2022-05-01"),0),(1.,False))
    def test_d2_preserves_native_width(self):
        row = weather("2022-05-01"); rows,t = histories(RAW["tabdpt"])
        location = fit_location(rows,t,date(2022,5,1),"tabdpt"); controls,t = histories(CONTROL["tabdpt"])
        center = fit_center(controls,t,date(2022,5,1),"tabdpt")
        arms = emit_arms(HistogramLaw([58,62],[0]).payload(),row,"tabdpt",location,center)
        self.assertEqual(arms[CENTER["tabdpt"]]["sigma_f"],arms[RAW["tabdpt"]]["sigma_f"])
    def test_calendar_year_and_clock(self):
        r = weather("2024-12-31",600); f = feature_values(r)
        self.assertAlmostEqual(f["sin1"],math.sin(2*math.pi*365/366)); self.assertAlmostEqual(f["hour"],1/7)
    def test_refresh_clocks_are_monthly_and_monday(self):
        h = MagicMock(); h.rows.return_value = []; t = truth([])
        block = {"start_date":"2022-01-01"}
        sat = fit_coefficients(h,t,date(2022,1,1),block_start=True)
        sun = fit_coefficients(h,t,date(2022,1,2),sat["monthly"],sat["weekly"])
        self.assertEqual(sat,sun); check_coefficients(sun,block,date(2022,1,2))
        mon = fit_coefficients(h,t,date(2022,1,3),sun["monthly"],sun["weekly"])
        self.assertEqual(mon["monthly"],sat["monthly"]); self.assertNotEqual(mon["weekly"],sat["weekly"])
        check_coefficients(mon,block,date(2022,1,3))
        with self.assertRaises(ContractError): check_coefficients(sun,block,date(2022,1,3))


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.exp = Path(self.temp.name)
        shutil.copytree(ROOT/"schemas",self.exp/"schemas")
    def tearDown(self): self.temp.cleanup()
    def test_atomic_immutable_and_hash_resume(self):
        s = UnitStore(self.exp,"kdenv375-t03-test",{"code":"a"}); body,receipt = s.commit("test",{"value":1},[],.1)
        self.assertEqual(s.read("test",[])[1],receipt)
        with self.assertRaises(ContractError): s.read("test",["x"])
        with self.assertRaises(ContractError): UnitStore(self.exp,"kdenv375-t03-test",{"code":"b"}).read("test",[])
        body["result"]["value"] = 2; atomic_json(self.exp/receipt["bundle_path"],body)
        with self.assertRaises(ContractError): s.read("test",[])
    def test_orphan_complete_bundle_recovery(self):
        s = UnitStore(self.exp,"kdenv375-t03-test",{}); b,r = s.commit("test",{},[],.1)
        (self.exp/s.paths("test")[1]).unlink(); self.assertEqual(s.read("test",[])[1],r)
    def test_extra_artifact_mutation_refused(self):
        path = "runs/kdenv375-t03-test/payload.json"; atomic_json(self.exp/path,{"value":1})
        s = UnitStore(self.exp,"kdenv375-t03-test",{}); s.commit("test",{},[],.1,{path:hash_file(self.exp/path)})
        atomic_json(self.exp/path,{"value":2})
        with self.assertRaises(ContractError): s.read("test",[])
    def test_dst_schedule(self):
        self.assertEqual(len(issue_times(date(2022,3,13))),53)
        self.assertEqual(plan_counts(development_plan())["native_contexts"],5130)
        self.assertEqual(plan_counts(development_plan())["issue_states"],76649)
        self.assertEqual(plan_counts(bounded_plan())["total_units"],9)
    def test_holdout_plan_rejected(self):
        plan = bounded_plan(); plan[0]["query_dates"] = ["2025-09-07"]
        with self.assertRaises(ContractError): plan_counts(plan)
    def test_future_cycle_rejected(self):
        r = weather(); p = json.loads(r["source_provenance_json"])
        p["selected_cycles"]["wrfsfcf"]["emulated_complete_time_utc"] = "2022-01-02T18:00:00Z"
        r["source_provenance_json"] = json.dumps(p)
        with self.assertRaises(ContractError): check_query(r)
    def test_query_trend_self_rejected(self):
        r = weather(); r["trend_q14_source_ids_json"] = json.dumps([r["issue_state_id"]])
        with self.assertRaises(ContractError): check_query(r)
    def test_native_batch_invariance(self):
        class Model:
            def predict(self,X,output_type): return np.repeat(X[:,:1],999,axis=1)
        from kden_r14_tabular.t02_runtime import raw_predict
        X = np.ones((2,71)); X[1,0] = 2
        m = Model(); assert_invariant(m,"tabicl",X,raw_predict(m,"tabicl",X))
        class Bad:
            def predict(self,X,output_type): return np.repeat(X[:,:1]+X[:,0].mean(),999,axis=1)
        bad = Bad()
        with self.assertRaises(ContractError): assert_invariant(bad,"tabicl",X,raw_predict(bad,"tabicl",X))
    def test_complete_day_not_rewarding_missing(self):
        a = losses(PointLaw(0),0); b = losses(PointLaw(0),2)
        rows = [{"issue_state_id":"a","target_date":"2022-01-01",**a},
                {"issue_state_id":"b","target_date":"2022-01-02",**b}]
        s = day_balanced_scoring(rows,{"2022-01-01":1,"2022-01-02":2})
        self.assertEqual(s["complete_day"]["absolute_error_f"],0)
        self.assertEqual(s["available_forecast"]["absolute_error_f"],1)
        self.assertEqual(s["available_forecast"]["integer_nll"],math.inf)
        self.assertAlmostEqual(s["available_forecast"]["rmse_f"],math.sqrt(2))
    def test_snapshot_dead_process_has_no_eta(self):
        d = {"pid":None,"status":"RUNNING","unit_costs":[{"kind":"native_tabicl","active_seconds":10}],"completed_unit_ids":[]}
        atomic_json(self.exp/"runs/kdenv375-t03-test/state.json",d)
        s = snapshot(self.exp,"kdenv375-t03-test"); self.assertEqual(s["observed_status"],"INTERRUPTED_PROCESS_NOT_ALIVE"); self.assertIsNone(s["eta_seconds"])
    def test_recipe_not_runtime_tunable(self):
        (self.exp/"config").mkdir(); atomic_json(self.exp/"config/replay.json",RECIPE); self.assertEqual(recipe(self.exp),RECIPE)
        bad = {**RECIPE,"half_life_days":5}; atomic_json(self.exp/"config/replay.json",bad)
        with self.assertRaises(ContractError): recipe(self.exp)
    def test_atomic_end_to_end_mocked_native_and_validate(self):
        # Exercise production ordering/publication/resume/validation with deterministic
        # fake native outputs, not real neural fits or a real feature scan.
        for p in ("config","src","reports"):
            if (ROOT/p).exists(): shutil.copytree(ROOT/p,self.exp/p,dirs_exist_ok=True)
        shutil.copytree(ROOT/"tests",self.exp/"tests",dirs_exist_ok=True)
        shutil.copy2(ROOT/"run_t03.py",self.exp/"run_t03.py")
        ident = identity(self.exp)
        ready = {"t02_record_sha256":"a"*64,"code_identity":ident,"recipe_sha256":digest(RECIPE),
                 "implementation_checks_sha256":"b"*64,"device":"cpu","bounded_counts":plan_counts(bounded_plan())}
        labels = truth([("2022-01-01",62),("2022-01-02",62)])
        ctx = MagicMock(); ctx.rows = list(range(180)); ctx.X = np.ones((180,71)); ctx.y_residual_f = np.linspace(-1,1,180)
        ctx.metadata = {"context_days":180,"context_identity":"c"*64}
        ctx.matrix.side_effect = lambda rows:np.array([[float(r["target_date"][-2:])]+[0.]*70 for r in rows])
        store = MagicMock(); store.context.return_value = ctx
        class Model:
            def __init__(self,name): self.name = name; self.max_features = 128; self.projection = None
            def fit(self,X,y): self.n_instances = len(X); self.n_features = X.shape[1]; return self
            def predict(self,X,**kw):
                if self.name=="tabicl": return X[:,:1]+np.linspace(-2,2,999)
                return {"borders":np.linspace(-2,2,11),"logits":np.repeat(X[:,:1],10,axis=1)}
        bases = {s:{"context_days":180,"supported":True,"residual_law":KernelLaw([0.]*180).payload(),"label_cutoff_exclusive":"2021-12-25","bandwidth_f":1.25} for s in ("H","Q")}
        with patch("kden_r14_tabular.t03_workflow.preflight",return_value=ready),\
             patch("kden_r14_tabular.t03_workflow.FeatureStore",return_value=store),\
             patch("kden_r14_tabular.t03_workflow.TruthAccess.from_release",return_value=labels),\
             patch("kden_r14_tabular.replay.query_rows",side_effect=lambda store,dates,m:[weather(d,m) for d in dates]),\
             patch("kden_r14_tabular.replay.baseline_context",return_value=bases),\
             patch("kden_r14_tabular.replay.backend",side_effect=lambda exp,name,device,checked:Model(name)):
            original = UnitStore.commit
            calls = []
            def interrupted(store,unit,*args,**kw):
                found = original(store,unit,*args,**kw); calls.append(unit)
                if len(calls)==1:
                    atomic_json(self.exp/"runs/kdenv375-t03-test/pause.request.json",{"pause_requested":True})
                return found
            if getattr(self,"pause_first",False):
                with patch.object(UnitStore,"commit",interrupted):
                    stopped = run_t03(self.exp,self.exp,"kdenv375-t03-test")
                    self.assertEqual(stopped["status"],"PAUSED"); self.assertEqual(stopped["completed_units"],1)
                self.assertFalse((self.exp/"manifests/T03_PASS.json").exists())
                old = ready["recipe_sha256"]; ready["recipe_sha256"] = "d"*64
                with self.assertRaises(ContractError): run_t03(self.exp,self.exp,"kdenv375-t03-test",resume=True)
                ready["recipe_sha256"] = old
                result = run_t03(self.exp,self.exp,"kdenv375-t03-test",resume=True)
            else: result = run_t03(self.exp,self.exp,"kdenv375-t03-test")
            self.assertEqual(result["counts"]["issue_states"],4); self.assertFalse(result["full_development_replay_performed"])
            accepted = validate_t03(self.exp,self.exp); self.assertEqual(accepted["status"],"VALID")
            self.assertEqual(run_t03(self.exp,self.exp,"kdenv375-t03-test",resume=True)["status"],"VALID")
            import pyarrow.parquet as pq
            f = sorted((self.exp/"runs/kdenv375-t03-test/forecasts").glob("*.parquet"))[0]; row = pq.ParquetFile(f).read().to_pylist()[0]
            p = json.loads(row["prediction_json"]); self.assertEqual(p["arms"][RAW["tabicl"]]["mean_f"],61.)
            self.assertTrue(p["arms"][RAW["tabicl"]]["supported"]); self.assertFalse(p["arms"][CONTROL["tabicl"]]["supported"])
            self.assertNotIn("truth",p)
    def test_cooperative_pause_restart_and_mixed_identity_rejected(self):
        self.pause_first = True
        self.test_atomic_end_to_end_mocked_native_and_validate()


if __name__=="__main__": unittest.main()
