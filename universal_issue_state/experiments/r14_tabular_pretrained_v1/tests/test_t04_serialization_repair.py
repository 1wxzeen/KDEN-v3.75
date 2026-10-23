"""Small synthetic regression checks; no models, study labels or network."""
import copy
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kden_r14_tabular.common import (ContractError, atomic_json, canonical, digest,
                                    hash_file, read_json, signed, verify_record)
from kden_r14_tabular.laws import HistogramLaw, PointLaw, QuantileLaw, describe
from kden_r14_tabular.t04_scoring import law_metrics
from kden_r14_tabular.replay import UnitStore
from kden_r14_tabular import t04_serialization_repair as repair


class BooleanTests(unittest.TestCase):
    def metrics(self, law, y):
        return repair.boolean_metrics(law_metrics, law, y, describe(law), [[60,61]])

    def test_real_tail_branch_reproduces_original_failure(self):
        law = QuantileLaw(np.linspace(59,61,999))
        old = law_metrics(law,70,describe(law),[])
        self.assertIsInstance(old[1]["genuine_zero_probability"], np.bool_)
        with self.assertRaises(TypeError): canonical(old)
        fixed = repair.boolean_metrics(law_metrics,law,70,describe(law),[])
        json.loads(canonical(fixed))
        self.assertIs(type(fixed[1]["genuine_zero_probability"]), bool)
        self.assertEqual(fixed[0], old[0]); self.assertEqual(fixed[2], old[2])

    def test_left_tail_same_numeric_scores(self):
        law = QuantileLaw(np.linspace(59,61,999))
        old = law_metrics(law,50,describe(law),[])
        fixed = repair.boolean_metrics(law_metrics,law,50,describe(law),[])
        self.assertEqual(old[0],fixed[0]); self.assertEqual(old[2],fixed[2])
        self.assertTrue(all(type(v) is bool for v in fixed[1].values()))

    def test_already_serializable_scores_byte_identical(self):
        for law,y in [(PointLaw(60),60),(QuantileLaw(np.linspace(59,61,999)),60),
                      (HistogramLaw([59,60,61],[0,0]),60)]:
            old = law_metrics(law,y,describe(law),[])
            fixed = repair.boolean_metrics(law_metrics,law,y,describe(law),[])
            self.assertEqual(canonical(old),canonical(fixed))

    def test_true_zero_stays_infinite(self):
        result = self.metrics(PointLaw(60),70)
        self.assertEqual(result[0]["integer_nll"],"Infinity")
        self.assertIs(result[1]["genuine_zero_probability"],True)
        json.loads(canonical(result))

    def test_finite_underflow_not_floored(self):
        result = self.metrics(HistogramLaw([59.5,60.5,61.5],[0,-1000]),61)
        self.assertEqual(result[0]["integer_nll"],1000.)
        self.assertIs(result[1]["probability_underflow"],True)
        self.assertIs(result[1]["genuine_zero_probability"],False)

    def test_reject_numeric_fake_boolean(self):
        def wrong(): return {}, {"genuine_zero_probability":0,"probability_underflow":False}, {}
        with self.assertRaises(ContractError): repair.boolean_metrics(wrong)

    def test_reject_unrecognized_flag(self):
        def wrong(): return {}, {"new":np.bool_(False)}, {}
        with self.assertRaises(ContractError): repair.boolean_metrics(wrong)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.exp = self.project / repair.EXPERIMENT_REL; self.exp.mkdir(parents=True)
        self.run = "kdenv375-t04-synthetic-repair"
        for p in repair.FILES:
            target = self.exp / p; target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text("fixture " + p)
        shutil.copytree(ROOT / "schemas", self.exp / "schemas")
        self.binding = {"science":"UNCHANGED"}
        self.original = signed({"binding":self.binding})
        atomic_json(self.exp / f"runs/{self.run}/identity.json",self.original,immutable=True)
        self.checks = signed({"repair_id":repair.REPAIR_ID,"status":"PASS",
            "code_identity":repair.identity(self.exp),"synthetic_tests_run":20,"failures":0,"errors":0})
        atomic_json(self.exp / repair.CHECKS,self.checks,immutable=True)
        self.units = UnitStore(self.exp,self.run,self.binding)
        self.units.commit("score-2022-01-01",{"old":True},[],.01)
        self.state = {"status":"FAILED","pid":None,"identity_sha256":digest(self.binding),
            "message":"TypeError: Object of type bool is not JSON serializable","completed_units":1,
            "completed_native_contexts":0,"completed_issue_states":57,"completed_score_days":1}
        atomic_json(self.exp / f"runs/{self.run}/state.json",self.state)
        self.addCleanup(patch.stopall)
        patch.object(repair.contract,"preflight",return_value={}).start()
        patch.object(repair.workflow,"binding",return_value=self.binding).start()

    def prepare(self): return repair.prepare(self.project,self.exp,self.run)

    def test_prepare_preserves_identity_and_existing_receipt(self):
        paths = [self.exp / f"runs/{self.run}/identity.json",self.exp / self.units.paths("score-2022-01-01")[1]]
        before = [hash_file(p) for p in paths]
        result = self.prepare()
        self.assertEqual(result["checkpoint_counts"]["completed_units"],1)
        self.assertEqual(before,[hash_file(p) for p in paths])

    def test_prepare_idempotent(self):
        first = self.prepare(); second = self.prepare()
        self.assertEqual(first,second)

    def test_wrong_failure_refused(self):
        self.state["message"] = "Other failure"
        atomic_json(self.exp / f"runs/{self.run}/state.json",self.state)
        with self.assertRaises(ContractError): self.prepare()

    def test_live_run_refused(self):
        import os
        self.state["pid"] = os.getpid()
        atomic_json(self.exp / f"runs/{self.run}/state.json",self.state)
        with self.assertRaises(ContractError): self.prepare()

    def test_existing_lock_refused(self):
        atomic_json(self.exp / "runs/T04_RUNNING.lock",{"pid":None})
        with self.assertRaises(ContractError): self.prepare()

    def test_changed_base_refused(self):
        with patch.object(repair.workflow,"binding",return_value={"science":"CHANGED"}):
            with self.assertRaises(ContractError): self.prepare()

    def test_stale_repair_code_refused(self):
        (self.exp / repair.FILES[0]).write_text("changed")
        with self.assertRaises(ContractError): self.prepare()

    def test_modified_existing_receipt_refused(self):
        self.prepare()
        path = self.exp / self.units.paths("score-2022-01-01")[1]
        path.write_text(path.read_text()+" ")
        with self.assertRaises(ContractError):
            repair.verify_repair(self.exp,self.run,self.original,self.checks)

    def test_checkpoint_count_mismatch_refused(self):
        self.state["completed_units"] = 2
        atomic_json(self.exp / f"runs/{self.run}/state.json",self.state)
        with self.assertRaises(ContractError): self.prepare()

    def test_new_score_binds_repair_existing_score_unchanged(self):
        self.prepare(); old = self.exp / self.units.paths("score-2022-01-01")[0]
        before = hash_file(old)
        with repair.installed(self.project,self.exp,self.run):
            units = repair.workflow.UnitStore(self.exp,self.run,self.binding)
            units.read("score-2022-01-01",[])
            body,_ = units.commit("score-2022-01-02",{"new":True},[],.01)
            self.assertIn(repair.repair_path(self.run),body["extra_artifacts"])
            self.assertEqual(before,hash_file(old))

    def test_final_report_binds_repair_provenance(self):
        self.prepare()
        with repair.installed(self.project,self.exp,self.run):
            units = repair.workflow.UnitStore(self.exp,self.run,self.binding)
            body,_ = units.commit("development-scorecard",{"scorecard":{}},[],.01)
            self.assertEqual(body["result"]["implementation_repairs"][0]["repair_id"],repair.REPAIR_ID)
            self.assertIn(repair.repair_path(self.run),body["extra_artifacts"])

    def test_post_repair_unattested_score_rejected(self):
        self.prepare()
        self.units.commit("score-2022-01-02",{"new":True},[],.01)
        with repair.installed(self.project,self.exp,self.run):
            units = repair.workflow.UnitStore(self.exp,self.run,self.binding)
            with self.assertRaises(ContractError): units.read("score-2022-01-02",[])

    def test_numeric_metric_patch_is_scoped_and_restored(self):
        self.prepare(); original = repair.scoring.law_metrics
        with repair.installed(self.project,self.exp,self.run):
            law = QuantileLaw(np.linspace(59,61,999))
            fixed = repair.scoring.law_metrics(law,70,describe(law),[])
            json.loads(canonical(fixed))
        self.assertIs(repair.scoring.law_metrics,original)


if __name__ == "__main__": unittest.main()
