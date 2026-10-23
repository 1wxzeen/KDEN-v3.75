"""Bounded synthetic checks. No real checkpoints, fits, holdout pages or network."""
import copy
import json
import math
import os
import subprocess
import shutil
import sys
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from kden_r14_tabular.common import ContractError,atomic_json,canonical,check_document,digest,hash_file,read_json,signed,verify_record
from kden_r14_tabular.dates import DENVER,issue_times,label_cutoff
from kden_r14_tabular.laws import HistogramLaw,KernelLaw,PointLaw,QuantileLaw,describe
from kden_r14_tabular.corrections import CENTER,CONTROL,RAW,QuantileBatch,feature_values
from kden_r14_tabular.corrections import fit_width as original_width
from kden_r14_tabular.truth import TruthAccess
from kden_r14_tabular.replay import UnitStore,development_plan,native_unit
from kden_r14_tabular.t04_contract import counts,decision,lock_recipe,run_path,scoring_policy
from kden_r14_tabular.t04_history import ChunkedWidthObjective,FullHistory,fit_width
from kden_r14_tabular.t04_scoring import (MODELS,CachedKernel,KernelCache,Scorecard,Summary,age_tags,law_metrics,numeric,
                                         paired_calendar_bootstrap,serial,tags)
from kden_r14_tabular.t04_workflow import LiveState,Paused,binding,checked_forecast_keys,replay
from kden_r14_tabular.t04_cli import recover,snapshot
from test_t03 import weather,histories


def policy(): return scoring_policy(ROOT)


def score_row(issue="a",day="2022-01-01",model="Q_RESIDUAL",minute=120,supported=True,available=True,error=2.,nll=1.):
    law=PointLaw(60.); metrics,flags,reliability=law_metrics(law,60,describe(law),policy()["diagnostic_integer_bands"])
    metrics.update(absolute_error_f=error,squared_error_f=error**2,signed_error_f=error,integer_nll=nll)
    return {"issue_state_id":issue,"target_date":day,"local_issue_minute":minute,"model":model,
            "supported":supported,"support_reason":None if supported else "WARMUP","truth_available":available,
            "metrics":metrics if supported and available else None,"flags":flags if supported and available else {},
            "reliability":reliability if supported and available else {},"strata":["regime:snow:ABSENT"]}


def score_day_fixture(day="2022-01-01"):
    minutes=[t.astimezone(DENVER).hour*60+t.astimezone(DENVER).minute for t in issue_times(date.fromisoformat(day))]
    return {"target_date":day,"verification_rows":[score_row(str(m),day,model,m) for m in minutes for model in MODELS]}


class MetricTests(unittest.TestCase):
    def test_cached_kernel_exact_crps(self):
        k=KernelLaw([-3,0,2,5]); c=CachedKernel(k.centers)
        for y in (-20,0,1,50): self.assertAlmostEqual(c.crps(y),k.crps(y),places=13)
    def test_kernel_translation_cache(self):
        cache=KernelCache(); payload=KernelLaw([-1,0,2]).payload()
        a,b=cache.law("x",payload,60.),cache.law("x",payload,75.)
        self.assertEqual(len(cache.values),1); self.assertAlmostEqual(a.crps(62),b.crps(77),places=13)
    def test_zero_probability_keeps_infinity(self):
        h=HistogramLaw([59,60],[0]); m,f,_=law_metrics(h,70,describe(h),[])
        self.assertEqual(m["integer_nll"],"Infinity"); self.assertTrue(f["genuine_zero_probability"])
        self.assertEqual(numeric(m["integer_nll"]),math.inf)
    def test_underflow_is_not_zero_support(self):
        h=HistogramLaw([59.5,60.5,61.5],[0,-1000]); m,f,_=law_metrics(h,61,describe(h),[])
        self.assertEqual(m["integer_nll"],1000.); self.assertTrue(f["probability_underflow"]); self.assertFalse(f["genuine_zero_probability"])
    def test_boundary_atom_right_bin(self):
        p=PointLaw(60.5); m,_,_=law_metrics(p,61,describe(p),[[61,61]])
        self.assertEqual(m["integer_nll"],0.); self.assertEqual(m["modal_integer_hit"],1)
    def test_outside_display_tail_brier(self):
        p=PointLaw(150.); m,_,_=law_metrics(p,150,describe(p),[])
        self.assertEqual(m["display_category_brier"],0.); self.assertEqual(m["display_above_mass"],1.)
    def test_band_is_integrated_not_center_assigned(self):
        h=HistogramLaw([59,63],[0]); m,_,r=law_metrics(h,61,describe(h),[[60,61]])
        self.assertAlmostEqual(r["BAND_60_61"]["probability"],.5); self.assertEqual(m["BAND_60_61_brier"],.25)
    def test_closed_quantile_coverage_for_atoms(self):
        p=PointLaw(60.); m,_,_=law_metrics(p,60,describe(p),[])
        self.assertEqual(m["coverage_95"],1); self.assertEqual(m["width_f_95"],0.)
    def test_scoring_moments_must_match_commit(self):
        p=PointLaw(60.); desc=describe(p); desc["mean_f"]=61.
        with self.assertRaises(ContractError): law_metrics(p,60,desc,[])
    def test_noninteger_target_rejected(self):
        p=PointLaw(60.)
        with self.assertRaises(ContractError): law_metrics(p,60.1,describe(p),[])
    def test_serial_does_not_drop_infinity(self):
        self.assertEqual(json.loads(canonical(serial({"x":math.inf})))["x"],"Infinity")
    def test_nan_rejected(self):
        with self.assertRaises(ContractError): serial(float("nan"))


class AggregationTests(unittest.TestCase):
    def test_incomplete_available_denominator(self):
        s=Summary(); s.add([score_row("a",error=4),score_row("b",supported=False)],2)
        self.assertEqual(s.result()["available_forecast"]["absolute_error_f"],4.)
        self.assertEqual(s.result()["complete_day"]["days"],0)
    def test_days_equal_not_issue_rows(self):
        s=Summary(); s.add([score_row("a",error=2)],1)
        s.add([score_row("b",day="2022-01-02",error=4),score_row("c",day="2022-01-02",error=4)],2)
        self.assertEqual(s.result()["complete_day"]["absolute_error_f"],3.)
    def test_rmse_is_sqrt_average_mse(self):
        s=Summary(); s.add([score_row("a",error=2)],1); s.add([score_row("b",day="2022-01-02",error=4)],1)
        self.assertAlmostEqual(s.result()["complete_day"]["rmse_f"],math.sqrt(10))
    def test_infinite_nll_not_removed(self):
        s=Summary(); r=score_row(); r["metrics"]["integer_nll"]="Infinity"; r["flags"]["genuine_zero_probability"]=True
        s.add([r,score_row("b")],2)
        self.assertEqual(s.result()["complete_day"]["integer_nll"],"Infinity"); self.assertEqual(s.result()["genuine_zero_probability_count"],1)
    def test_unresolved_label_excluded_but_coverage_kept(self):
        s=Summary(); s.add([score_row(available=False)],1)
        self.assertEqual(s.result()["supported_forecast_fraction"],1.); self.assertEqual(s.result()["truth_missing_days"],1)
        self.assertEqual(s.result()["available_forecast"]["days"],0)
    def test_duplicate_key_rejected(self):
        with self.assertRaises(ContractError): Summary().add([score_row(),score_row()],2)
    def test_missing_scheduled_keys_rejected(self):
        with self.assertRaises(ContractError): Summary().add([score_row()],2)
    def test_primary_window_owner_02_14(self):
        c=Scorecard(policy()); c.add(score_day_fixture())
        self.assertEqual(c.result()["windows"]["PRIMARY_02_14"]["Q_RESIDUAL"]["expected_issues"],49)
    def test_dst_population_45_primary(self):
        c=Scorecard(policy()); c.add(score_day_fixture("2022-03-13"))
        self.assertEqual(c.result()["windows"]["PRIMARY_02_14"]["Q_RESIDUAL"]["expected_issues"],45)
    def test_pairing_identical_supported_ids(self):
        value=score_day_fixture(); first=next(r for r in value["verification_rows"] if r["model"]=="KDEN_TABICL_T3")
        first.update(supported=False,metrics=None,flags={},reliability={})
        c=Scorecard(policy()); c.add(value)
        pair=c.result()["paired_comparisons"]["PRIMARY_02_14:KDEN_TABICL_T3-vs-Q_RESIDUAL"]
        self.assertEqual(pair["candidate"]["scored_issues"],48); self.assertEqual(pair["control"]["scored_issues"],48)
        self.assertEqual(pair["candidate"]["complete_day"]["days"],0)
    def test_duplicate_verification_day_rejected(self):
        c=Scorecard(policy()); c.add(score_day_fixture())
        with self.assertRaises(ContractError): c.add(score_day_fixture())
    def test_nomination_only_matched_primary(self):
        value=score_day_fixture()
        for r in value["verification_rows"]:
            if r["model"]=="KDEN_TABDPT_D2_NATIVE": r["metrics"]["integer_nll"]=.9
        c=Scorecard(policy()); c.add(value)
        self.assertEqual(c.result()["development_nomination"]["candidate"],"KDEN_TABDPT_D2_NATIVE")
        self.assertTrue(c.result()["development_nomination"]["owner_selection_still_required"])
    def test_month_season_minute_slices(self):
        c=Scorecard(policy()); c.add(score_day_fixture()); r=c.result()["descriptive_slices"]
        self.assertIn("month:2022-01",r); self.assertIn("season:DJF",r); self.assertIn("minute:840",r)
    def test_all_neural_comparisons_are_matched_descriptions(self):
        c=Scorecard(policy()); c.add(score_day_fixture())
        pairs=c.result()["paired_comparisons"]
        self.assertFalse(pairs["PRIMARY_02_14:KDEN_TABICL_T1-vs-Q_RESIDUAL"]["in_predeclared_inferential_family"])
        self.assertTrue(pairs["PRIMARY_02_14:KDEN_TABICL_T3-vs-Q_RESIDUAL"]["in_predeclared_inferential_family"])
    def test_support_population_separate_from_paired_loss(self):
        v=score_day_fixture()
        r=next(r for r in v["verification_rows"] if r["model"]=="KDEN_TABICL_T3")
        r.update(supported=False,metrics=None,flags={},reliability={})
        c=Scorecard(policy()); c.add(v)
        card=c.result()
        self.assertEqual(card["windows"]["PRIMARY_02_14"]["Q_RESIDUAL"]["supported_issues"],49)
        self.assertEqual(card["paired_comparisons"]["PRIMARY_02_14:KDEN_TABICL_T3-vs-Q_RESIDUAL"]["control"]["supported_issues"],48)
    def test_scorecard_reproducible_across_python_hash_seeds(self):
        code="""import sys
sys.path.insert(0,'tests')
from test_t04 import score_day_fixture, policy, Scorecard, digest
value=score_day_fixture()
for i,r in enumerate(value['verification_rows']):
    r['metrics']['integer_nll'] = (i % 19)*0.11313241837819 + (i % 7)*0.00019712317
card=Scorecard(policy()); card.add(value)
print(digest(card.result()))
"""
        values=[]
        for seed in (31,94):
            env=dict(os.environ,PYTHONHASHSEED=str(seed),PYTHONDONTWRITEBYTECODE="1")
            values.append(subprocess.check_output([sys.executable,"-B","-c",code],cwd=ROOT,env=env,text=True,timeout=15).strip())
        self.assertEqual(values[0],values[1])


class ContractTests(unittest.TestCase):
    def approved(self):
        v=read_json(ROOT/"config/decision_t04_proposal.json")
        v.update(owner_confirmed=True,selected_operational_candidate="KDEN_TABICL_T3",selection_rationale="Matched development evidence and operational cost inspected.")
        return v
    def test_full_counts(self):
        self.assertEqual(counts(),{"native_contexts":5130,"issue_states":76649,"query_calls":153298,
            "correction_days":1345,"score_days":1345,"total_units":7822})
    def test_holdout_not_in_plan(self):
        self.assertEqual(max(d for b in development_plan() for d in b["query_dates"]),"2025-09-06")
    def test_truth_holdout_access_closed(self):
        with self.assertRaises(ContractError): TruthAccess([{"target_date":"2025-09-07","y_audited_f":60}],ROOT)
    def test_approved_decision(self): self.assertEqual(decision(self.approved())["primary_window_minutes"],[120,840])
    def test_unapproved_proposal_rejected(self):
        with self.assertRaises(ContractError): decision(read_json(ROOT/"config/decision_t04_proposal.json"))
    def test_wrong_window_rejected(self):
        v=self.approved(); v["primary_window_minutes"]=[120,480]
        with self.assertRaises(ContractError): decision(v)
    def test_missing_candidate_rejected(self):
        v=self.approved(); v["selected_operational_candidate"]=None
        with self.assertRaises(ContractError): decision(v)
    def test_nan_threshold_rejected(self):
        v=self.approved(); v["integer_nll_nats_max"]=math.nan
        with self.assertRaises(ContractError): decision(v)
    def test_impossible_support_rejected(self):
        v=self.approved(); v["supported_forecast_fraction_min"]=1.1
        with self.assertRaises(ContractError): decision(v)
    def test_bad_run_id_rejected(self):
        with self.assertRaises(ContractError): run_path(ROOT,"../elsewhere","state.json")
    def test_regime_missing_is_unknown(self):
        cutoff={"transition":{k:{"absolute_75th_percentile":1.} for k in ("h_revision_abs_f","trend_q14_f")}}
        self.assertTrue(all("UNKNOWN" in t for t in tags({},cutoff)))
    def test_regime_inclusive_cloud_and_strict_snow(self):
        cutoff={"transition":{k:{"absolute_75th_percentile":1.} for k in ("h_revision_abs_f","trend_q14_f")}}
        out=tags({"snow_asof_fraction":0.,"cloud_remaining_fraction":.5,"reflectivity_ge20_fraction":.1,
                  "h_revision_abs_f":1.,"trend_q14_f":1.},cutoff)
        self.assertIn("regime:snow:ABSENT",out); self.assertIn("regime:cloud:PRESENT",out); self.assertIn("regime:transition:ABSENT",out)
    def test_cycle_age_future_rejected(self):
        row=weather(); row["issue_time_utc"]="2022-01-01T00:00:00Z"
        with self.assertRaises(ContractError): age_tags(row)
    def test_bootstrap_deterministic_calendar_missing(self):
        values=[None,1.,2.,None,0.,3.,1.]*3
        self.assertEqual(paired_calendar_bootstrap(values,draws=20),paired_calendar_bootstrap(values,draws=20))
    def test_bootstrap_infinite_not_dropped(self):
        self.assertEqual(paired_calendar_bootstrap([1.]*6+["Infinity"],draws=20)["status"],"NONFINITE_CONTRAST_NO_FINITE_INTERVAL")
    def test_chunk_objective_equals_full_t03(self):
        q=np.array([np.linspace(-3+i/10,3+i/10,999) for i in range(9)])
        batch=QuantileBatch(q); X=np.column_stack((np.ones(9),np.linspace(-1,1,9)))
        errors=np.linspace(-1,1,9); w=np.ones(9); penalty=np.array([20.,100.]); beta=np.array([.1,.02])
        objective=ChunkedWidthObjective(batch.q,batch.left,batch.right,X,errors,w,penalty,chunk=2)
        lp,g=batch.likelihood(errors,X@beta)
        expected=-w@lp+.5*(penalty*beta)@beta; gradient=X.T@(-w*g)+penalty*beta
        value,grad=objective(beta); self.assertAlmostEqual(value,expected,places=12); np.testing.assert_allclose(grad,gradient,atol=1e-12)
    def test_chunk_gradient_finite_difference(self):
        q=np.tile(np.linspace(-4,4,999),(7,1)); batch=QuantileBatch(q)
        X=np.column_stack((np.ones(7),np.linspace(-1,1,7)))
        fun=ChunkedWidthObjective(batch.q,batch.left,batch.right,X,np.linspace(-1,1,7),np.ones(7),np.array([20.,100.]),chunk=3)
        beta=np.array([.1,.02]); _,grad=fun(beta)
        for i in range(2):
            step=np.eye(2)[i]*1e-6; self.assertAlmostEqual(grad[i],(fun(beta+step)[0]-fun(beta-step)[0])/2e-6,places=5)
    def test_full_width_insufficient_history_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            hist=FullHistory(Path(directory)); t=TruthAccess([],Path(directory))
            fit=fit_width(hist,t,date(2022,1,1))
            self.assertEqual(fit["fit_status"],"UNSUPPORTED_INSUFFICIENT_EMITTED_HISTORY")
    def test_supported_width_matches_accepted_objective(self):
        rows,truth=histories(CENTER["tabicl"],count=95,minutes=(600,615))
        update=date(2022,5,1); expected=original_width(rows,truth,update)
        with tempfile.TemporaryDirectory() as directory:
            history=FullHistory(Path(directory))
            history.rows=lambda arm,day: rows
            def fill(items,q,left,right):
                batch=QuantileBatch([np.asarray(r["t1_quantiles_f"])-r["t1_mean_f"] for r in items])
                q[:]=batch.q; left[:]=batch.left; right[:]=batch.right
            history.fill_shapes=fill
            actual=fit_width(history,truth,update)
        self.assertEqual(actual["fit_status"],expected["fit_status"])
        np.testing.assert_allclose(actual["smooth"]["coefficients"],expected["smooth"]["coefficients"],atol=1e-8,rtol=1e-8)
        self.assertAlmostEqual(actual["optimizer"]["objective"],expected["optimizer"]["objective"],places=8)
    def test_binding_uses_actual_t02_receipt_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            atomic_json(root/"manifests/T01_PASS.json",signed({"code_identity":{},"artifact_hashes":{}}))
            atomic_json(root/"manifests/T02_PASS.json",signed({"code_identity":{},"source_bindings":{},"runtime_identity":{}}))
            atomic_json(root/"manifests/T03_PASS.json",signed({"binding":{}}))
            for path in ("inputs/exposure_ledger.json","inputs/truth/adapter_contract.json","config/replay.json",
                         "config/features.json","config/checkpoints.json","config/experiment.json"):
                atomic_json(root/path,{"synthetic":True})
            ready={k:"test" for k in ("t03_record_sha256","t03_binding_sha256","device","code_identity","implementation_checks_sha256","scoring_policy_sha256")}
            self.assertIn("code_identity",binding(root,ready,[])["t02_binding"])


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        shutil.copytree(ROOT/"schemas",self.root/"schemas"); shutil.copytree(ROOT/"config",self.root/"config")
        self.run="kdenv375-t04-synthetic"; blocks=development_plan()
        self.plan=[{**b,"query_dates":[b["start_date"]]} for b in blocks[:2]]
        self.b={"plan":self.plan,"device":"cpu"}; self.labels=TruthAccess([
            {"target_date":b["start_date"],"y_audited_f":60,"truth_qc_status":"audited"} for b in self.plan],self.root)
        self.native_calls=0
    def tearDown(self): self.temp.cleanup()
    def state(self):
        return {"schema_version":"R14_TABULAR_T04_STATE_V1","run_id":self.run,"status":"RUNNING","pid":os.getpid(),
                "phase":"TEST","identity_sha256":digest(self.b),"completed_units":0,"total_units":counts(self.plan)["total_units"],
                "completed_native_contexts":0,"completed_issue_states":0,"completed_score_days":0,"current_unit":None,
                "current_unit_started_active_seconds":0.,"active_seconds":0.,"updated_at_utc":"test","message":"synthetic","unit_costs":{}}
    def native(self,experiment,store,truth,block,minute,name,device,**kw):
        self.native_calls+=1
        # Accepted T02 uses ISO '+00:00', not Z. Key checks must compare instants.
        row=weather(block["start_date"],minute)
        return {"block_id":block["block_id"],"learner":name,"local_issue_minute":minute,
                "context":{"context_days":180},"context_fits_performed":0,"queries":[{"weather":row,
                "law":PointLaw(60.).payload(),"support_status":"SUPPORTED","context_identity":"c"*64}],
                "baseline_contexts":{s:{"supported":True,"context_days":180,"residual_law":KernelLaw([0.]*180).payload()} for s in ("H","Q")}}
    def replay(self,live):
        cutoff={"transition":{k:{"absolute_75th_percentile":1.} for k in ("h_revision_abs_f","trend_q14_f")}}
        def regime_day(store,day,cuts):
            return {weather(str(day),m)["issue_state_id"]:["regime:snow:ABSENT"] for m in range(120,961,15)}
        with patch("kden_r14_tabular.t04_workflow.process_native",side_effect=self.native), \
             patch("kden_r14_tabular.t04_workflow.regime_cutoffs",return_value=cutoff), \
             patch("kden_r14_tabular.t04_workflow.feature_tags",side_effect=regime_day):
            return replay(self.root,self.run,self.b,live,None,self.labels)
    def test_two_block_multiminute_resume(self):
        live=LiveState(self.root,self.run,self.state()); entries,report,fits=self.replay(live)
        self.assertEqual(len(entries),234); self.assertEqual(live.state["completed_issue_states"],114)
        self.assertEqual(self.native_calls,228)
        files={str(p.relative_to(self.root)):hash_file(p) for p in (self.root/"runs"/self.run).rglob("*") if p.is_file() and p.name!="state.json"}
        second=LiveState(self.root,self.run,self.state())
        with patch("kden_r14_tabular.t04_workflow.process_native",side_effect=AssertionError("completed context must not refit")):
            # The local helper also patches native; every existing unit should avoid calling either mock.
            self.replay(second)
        self.assertEqual(files,{str(p.relative_to(self.root)):hash_file(p) for p in (self.root/"runs"/self.run).rglob("*") if p.is_file() and p.name!="state.json"})
        self.assertEqual(self.native_calls,228)
        value=verify_record(read_json(self.root/report))["result"]["scorecard"]
        self.assertEqual(value["development_days"],2); self.assertFalse(value["holdout_scores_computed"])
    def test_pause_before_any_native_preserves_atomic_regime(self):
        live=LiveState(self.root,self.run,self.state())
        atomic_json(run_path(self.root,self.run,"pause.request.json"),{"pause_requested":True})
        with self.assertRaises(Paused): self.replay(live)
        self.assertFalse(run_path(self.root,self.run,"units/regime-cutoffs.json").exists())
    def test_receipt_rejects_changed_dependencies(self):
        units=UnitStore(self.root,self.run,self.b); units.commit("x",{"ok":True},[],.1)
        with self.assertRaises(ContractError): units.read("x",["a"*64])
    def test_stale_lock_recovery_keeps_outputs(self):
        p=self.root/"runs/T04_RUNNING.lock"; atomic_json(p,{"pid":999999,"run_id":self.run})
        with patch("kden_r14_tabular.t04_cli.process_alive",return_value=False): result=recover(self.root)
        self.assertEqual(result["forecast_or_input_files_removed"],0); self.assertFalse(p.exists())
    def test_live_process_recovery_refused(self):
        p=self.root/"runs/T04_RUNNING.lock"; atomic_json(p,{"pid":os.getpid(),"run_id":self.run})
        with self.assertRaises(ContractError): recover(self.root)
    def test_eta_missing_cost_not_faked(self):
        atomic_json(run_path(self.root,self.run,"state.json"),self.state())
        self.assertIsNone(snapshot(self.root,self.run)["eta_seconds"])
    def test_eta_pause_wall_time_excluded(self):
        state=self.state(); state.update(status="PAUSED",pid=None,active_seconds=10.,unit_costs={"native_tabicl":[2.],"native_tabdpt":[3.],"day":[1.],"score":[1.]})
        atomic_json(run_path(self.root,self.run,"state.json"),state)
        self.assertIsNone(snapshot(self.root,self.run)["eta_seconds"])
    def test_eta_estimates_recent_active_unit_costs(self):
        state=self.state(); state["unit_costs"]={"native_tabicl":[2.],"native_tabdpt":[3.],"day":[1.],"score":[1.]}
        atomic_json(run_path(self.root,self.run,"state.json"),state)
        self.assertEqual(snapshot(self.root,self.run)["eta_seconds"],2565*5+1345*2)
    def test_lock_requires_owner_decision(self):
        # Lock is unavailable before a development PASS, even with a nominal decision path.
        with patch("kden_r14_tabular.t04_contract.preflight",return_value={}):
            with self.assertRaises(ContractError): lock_recipe(self.root,self.root,"decision.json")
    def test_explicit_lock_idempotent_and_immutable(self):
        score={"complete_day":{"days":5,"integer_nll":1.5}}
        report_path="runs/accepted/units/development-scorecard.json"
        atomic_json(self.root/report_path,signed({"result":{"scorecard":{"windows":{"PRIMARY_02_14":{"KDEN_TABICL_T3":score}}},"regime_cutoffs":{}}}),immutable=True)
        passed=signed({"binding":{"code_identity":{},"t03_record_sha256":"t03","exposure_ledger_sha256":"opaque"},
                       "report_path":report_path,"report_sha256":hash_file(self.root/report_path)})
        atomic_json(self.root/"manifests/T04_DEVELOPMENT_PASS.json",passed,immutable=True)
        atomic_json(self.root/"manifests/T04_DEVELOPMENT_VALIDATED.json",signed({"development_record_sha256":passed["record_sha256"],"status":"VALID"}),immutable=True)
        v=read_json(self.root/"config/decision_t04_proposal.json")
        v.update(owner_confirmed=True,selected_operational_candidate="KDEN_TABICL_T3",selection_rationale="Inspected development evidence.")
        atomic_json(self.root/"decision.json",v)
        with patch("kden_r14_tabular.t04_contract.preflight",return_value={"code_identity":{},"t03_record_sha256":"t03"}):
            first=lock_recipe(self.root,self.root,"decision.json")
            self.assertEqual(first,lock_recipe(self.root,self.root,"decision.json"))
            self.assertFalse(first["holdout_replay_started"])
            v["mean_mae_f_max"]=1.2; atomic_json(self.root/"different.json",v)
            with self.assertRaises(ContractError): lock_recipe(self.root,self.root,"different.json")


if __name__=="__main__": unittest.main()
