"""Bounded synthetic contracts only; no archive scan, weights or holdout labels."""
import copy
import json
import math
import socket
import sys
import tempfile
import unittest
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
EXP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXP / "src"))
from kden_r14_tabular.common import ContractError, atomic_json, digest, read_json, verify_record, signed
from kden_r14_tabular.features import (FeatureContext, adapt, config, label_free_trend, native_value)
from kden_r14_tabular.truth import TruthAccess
from kden_r14_tabular.t02_runtime import backend, no_network, raw_predict
from kden_r14_tabular.t02_workflow import build_partition, publish_parquet, resume_partition

CFG = config(EXP)


def source(d=date(2021, 1, 1), minute=180):
    issue = datetime(d.year, d.month, d.day, minute//60, minute%60, tzinfo=ZoneInfo("America/Denver")).astimezone(UTC)
    init = (issue-timedelta(minutes=105)).replace(minute=0, second=0, microsecond=0)
    key = "ISSUE_TEST_" + str(d) + "_" + str(minute)
    raw = {f["source"]: (277.15 if f["transform"] == "K_TO_F" else 1.) for f in CFG["features"]}
    raw.update(issue_state_id=key, target_date=d, issue_time_utc=issue,
               wrfsfcf_cycle_init_utc=init, wrfsubhf_cycle_init_utc=init,
               feature_registry_id="KDEN_V375_UNIVERSAL_FEATURE_REGISTRY_V1", derivation_id="KDEN_V375_DETERMINISTIC_FEATURES_V1",
               h16_local_retained_coverage_fraction=1., h16_local_retained_missing_count=0)
    spine = {"issue_state_id": key, "target_date": d, "issue_time_utc": issue,
             "local_issue_hour": minute//60, "local_issue_minute": minute%60,
             "local_dst_flag": bool(issue.astimezone(ZoneInfo("America/Denver")).dst()), "issue_state_eligible": True}
    cycles = {}
    for p in ["wrfsfcf", "wrfsubhf"]:
        cycles[p] = {"issue_state_id": key, "target_date": d, "issue_time_utc": issue, "product": p,
                     "availability_policy_id": "KDEN_HIST_COMPLETE_L105_V1", "cycle_init_utc": init,
                     "emulated_complete_time_utc": init+timedelta(minutes=105),
                     "cycle_age_minutes": (issue-init).total_seconds()/60,
                     "availability_age_minutes": (issue-init).total_seconds()/60-105,
                     "previous_cycle_init_utc": None}
    return raw, spine, cycles


def row(d=date(2021, 1, 1), minute=180):
    raw, spine, cycles = source(d, minute)
    return adapt(raw, spine, cycles, CFG, source_path="frozen-test.parquet", source_sha256="a"*64)


def context_rows():
    return [row(date(2021, 1, 1)+timedelta(days=i)) for i in range(200)]


def truth(rows):
    return TruthAccess([{"target_date": r["target_date"], "y_audited_f": 50} for r in rows], EXP)


class T02Contracts(unittest.TestCase):
    def test_exact_whitelist_and_units(self):
        self.assertEqual(len(CFG["input_columns"]), 71)
        self.assertEqual(CFG["input_columns"][:34], [f["name"] for f in CFG["features"]])
        self.assertEqual(CFG["input_columns"][34:68], [f["name"]+"_missing" for f in CFG["features"]])
        self.assertAlmostEqual(native_value(273.15, "K_TO_F"), 32)
        self.assertAlmostEqual(native_value(10, "DELTA_K_TO_F"), 18)
        self.assertAlmostEqual(native_value(50, "PERCENT_TO_FRACTION"), .5)

    def test_missing_primary_abstains_nonfinite_ancillary_fails(self):
        raw, spine, cycles = source()
        for value in [None, float("nan"), float("inf"), -float("inf")]:
            raw["q05_local_retained_max"] = value
            r = adapt(raw, spine, cycles, CFG, source_path="test", source_sha256="a"*64)
            self.assertIsNone(r["anchor_q_f"])
            self.assertEqual(r["anchor_q_f_missing"], 1.)
            self.assertTrue(r["native_status"].startswith("ABSTAIN"))
        raw["q05_local_asof_value"] = float("nan")
        with self.assertRaises(ContractError): adapt(raw, spine, cycles, CFG, source_path="test", source_sha256="a"*64)
        with self.assertRaises(ContractError): native_value("oops", "IDENTITY")

    def test_no_source_column_silent_null(self):
        raw, spine, cycles = source(); del raw["h31_local_remaining_mean"]
        with self.assertRaises(ContractError): adapt(raw, spine, cycles, CFG, source_path="test", source_sha256="a"*64)

    def test_future_cycle_and_revision_rejected(self):
        raw, spine, cycles = source()
        cycles["wrfsubhf"]["emulated_complete_time_utc"] += timedelta(hours=3)
        with self.assertRaises(ContractError): adapt(raw, spine, cycles, CFG, source_path="test", source_sha256="a"*64)
        raw, spine, cycles = source()
        cycles["wrfsfcf"]["previous_cycle_init_utc"] = cycles["wrfsfcf"]["cycle_init_utc"]-timedelta(hours=2)
        cycles["wrfsfcf"]["previous_emulated_complete_time_utc"] = cycles["wrfsfcf"]["previous_cycle_init_utc"]+timedelta(minutes=105)
        with self.assertRaises(ContractError): adapt(raw, spine, cycles, CFG, source_path="test", source_sha256="a"*64)

    def test_dst_and_leap_calendar(self):
        r = row(date(2024, 12, 31))
        theta = 2*math.pi*365/366
        self.assertAlmostEqual(r["season_sin"], math.sin(theta))
        self.assertEqual(row(date(2021, 3, 14))["local_dst_flag"], 1.)
        raw, spine, cycles = source(date(2021, 3, 14)); spine["local_issue_hour"] = 2
        with self.assertRaises(ContractError): adapt(raw, spine, cycles, CFG, source_path="test", source_sha256="a"*64)

    def test_context_medians_query_independence_residual_anchor(self):
        import numpy as np
        rows = context_rows()
        rows[0]["cloud_remaining_fraction"] = None
        for r in rows: r["solar_remaining_w_m2"] = None
        c = FeatureContext(rows, truth(rows), date(2021, 9, 1), 180, CFG)
        self.assertIn("solar_remaining_w_m2", c.all_missing)
        q = row(date(2022, 1, 1)); q["solar_remaining_w_m2"] = None
        q["y_audited_f"] = 999999  # ignored metadata must never enter X or median fitting
        q2 = row(date(2022, 1, 2)); q2["cloud_remaining_fraction"] = 1e20
        batch = c.matrix([q, q2]); reverse = c.matrix([q2, q])[::-1]
        np.testing.assert_array_equal(batch, reverse)
        np.testing.assert_array_equal(batch[0], c.matrix([q])[0])
        self.assertEqual(c.medians["cloud_remaining_fraction"], .01)
        self.assertEqual(c.medians["solar_remaining_w_m2"], 0.)
        np.testing.assert_allclose(c.y_residual_f, 50-rows[0]["anchor_q_f"])
        # Future/query weather rows never change earlier-context medians.
        c2 = FeatureContext(rows+[q2], truth(rows), date(2021, 9, 1), 180, CFG)
        self.assertEqual(c.metadata, c2.metadata)

    def test_exclusive_embargo_equality(self):
        rows = context_rows()
        border = row(date(2021, 9, 24)); just_before = row(date(2021, 9, 23))
        c = FeatureContext(rows+[border, just_before], truth(rows+[border, just_before]), date(2021, 10, 1), 180, CFG)
        self.assertNotIn(border["issue_state_id"], c.metadata["source_issue_state_ids"])
        self.assertIn(just_before["issue_state_id"], c.metadata["source_issue_state_ids"])

    def test_distinct_days_minimum_context_no_anchor_imputation(self):
        rows = context_rows()
        with self.assertRaises(ContractError): FeatureContext(rows+[rows[0]], truth(rows), date(2021, 9, 1), 180, CFG)
        with self.assertRaises(ContractError): FeatureContext(rows[:179], truth(rows), date(2021, 9, 1), 180, CFG)
        c = FeatureContext(rows, truth(rows), date(2021, 9, 1), 180, CFG)
        q = row(date(2022, 1, 1)); q["anchor_q_f"] = None
        with self.assertRaises(ContractError): c.matrix([q])
        rows[0]["anchor_q_f"] = None
        c = FeatureContext(rows, truth(rows), date(2021, 9, 1), 180, CFG)
        self.assertEqual(c.metadata["context_days"], 199)

    def test_mixed_time_rejected_and_unresolved_labels_excluded(self):
        rows = context_rows()
        ta = truth(rows); ta._labels[date(2021, 1, 1)]["y_audited_f"] = None
        c = FeatureContext(rows, ta, date(2021, 9, 1), 180, CFG)
        self.assertEqual(len(c.rows), 199)
        with self.assertRaises(ContractError): c.matrix([row(date(2022, 1, 1), 195)])

    def test_holdout_loader_stays_closed(self):
        with self.assertRaises(ContractError): TruthAccess([{"target_date": "2025-09-07", "y_audited_f": 70}], EXP)

    def test_trend_calendar_support_and_no_labels(self):
        q = row(date(2022, 1, 1))
        history = [row(date(2021, 12, 18)+timedelta(days=i)) for i in range(14)]
        for r in history: r["poisoned_label"] = 12345
        result = label_free_trend(q, history)
        self.assertAlmostEqual(result["trend_q14_f"], 0.)
        self.assertEqual(result["trend_q14_valid_days"], 14)
        self.assertIsNone(label_free_trend(q, history[:6])["trend_q14_f"])
        self.assertAlmostEqual(label_free_trend(q, history[:7])["trend_q14_f"], 0.)
        for invalid in [history+[history[0]], [row(date(2021, 12, 17))], [q], [row(date(2021, 12, 20), 195)]]:
            with self.assertRaises(ContractError): label_free_trend(q, invalid)

    def test_partition_schema_provenance_and_cross_year_history(self):
        import pyarrow.parquet as pq
        history = defaultdict(deque)
        for i in range(14): history[180].append(row(date(2021, 12, 18)+timedelta(days=i)))
        raw, spine, cycles = source(date(2022, 1, 1))
        out, counts = build_partition([raw], [spine], list(cycles.values()), CFG, "test", "a"*64, history)
        self.assertEqual(counts, {"READY": 1})
        self.assertEqual(out[0]["trend_q14_valid_days"], 14)
        self.assertIn("selected_cycles", json.loads(out[0]["source_provenance_json"]))
        self.assertIn("missing_count", out[0]["coverage_diagnostics_json"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"part.parquet"
            sha = publish_parquet(path, out, CFG)
            self.assertEqual(sha, publish_parquet(path, out, CFG))
            f = pq.ParquetFile(path)
            self.assertEqual(f.schema_arrow.names[-71:], CFG["input_columns"])
            self.assertEqual(f.read().to_pylist()[0]["anchor_q_f"], out[0]["anchor_q_f"])
            changed = copy.deepcopy(out); changed[0]["anchor_q_f"] += 1
            with self.assertRaises(ContractError): publish_parquet(path, changed, CFG)

    def test_network_inference_guard(self):
        original = socket.create_connection
        with no_network():
            with self.assertRaises(ContractError): socket.create_connection(("localhost", 1))
        self.assertIs(socket.create_connection, original)

    def test_completed_partition_resume_rejects_changed_identity(self):
        import shutil
        out = []
        for i in range(20):
            r = row(date(2021, 12, 12)+timedelta(days=i))
            r.update(label_free_trend(r, [])); out.append(r)
        with tempfile.TemporaryDirectory() as directory:
            exp = Path(directory); (exp/"schemas").mkdir()
            shutil.copyfile(EXP/"schemas/t02_partition.json", exp/"schemas/t02_partition.json")
            output_rel = "runs/kdenv375-t02-test/features/part.parquet"
            path = exp/output_rel; sha = publish_parquet(path, out, CFG)
            ident = {"code": "original"}
            receipt = signed({"schema_version": "R14_TABULAR_T02_PARTITION_V1", "year": 2021,
                              "path": output_rel, "sha256": sha, "rows": 20, "source_path": "test",
                              "source_sha256": "a"*64, "identity_sha256": digest(ident), "native_status_counts": {"READY": 20}})
            journal = exp/"receipt.json"; atomic_json(journal, receipt, immutable=True)
            actual, history = resume_partition(exp, journal, output_rel, "a"*64, ident, 20)
            self.assertEqual(actual, receipt)
            self.assertEqual(len(history[180]), 14)
            self.assertEqual(history[180][0]["target_date"], "2021-12-18")
            with self.assertRaises(ContractError): resume_partition(exp, journal, output_rel, "b"*64, ident, 20)
            with self.assertRaises(ContractError): resume_partition(exp, journal, output_rel, "a"*64, {"code": "changed"}, 20)
            with self.assertRaises(ContractError): resume_partition(exp, journal, output_rel, "a"*64, ident, 19)
            with path.open("ab") as stream: stream.write(b"changed")
            with self.assertRaises(ContractError): resume_partition(exp, journal, output_rel, "a"*64, ident, 20)

    def test_raw_predict_full_context_and_no_reduction(self):
        import numpy as np
        class Model:
            max_features = 128
            projection = None
            def predict(self, X, **kwargs):
                self.kwargs = kwargs
                return {"borders": np.array([-1., 0., 1.]), "logits": np.zeros((len(X), 2))}
        m = Model(); raw_predict(m, "tabdpt", np.zeros((1, 71)))
        self.assertIsNone(m.kwargs["context_size"])
        self.assertEqual(m.kwargs["n_ensembles"], 8)
        self.assertEqual(m.kwargs["output_type"], "full")
        m.projection = np.zeros((71, 32))
        with self.assertRaises(ContractError): raw_predict(m, "tabdpt", np.zeros((1, 71)))
        with self.assertRaises(ContractError): raw_predict(m, "tabdpt", np.zeros((1, 70)))

    def test_receipts_detect_tampering(self):
        receipt = signed({"status": "PASS", "rows": 1})
        verify_record(receipt); receipt["rows"] = 2
        with self.assertRaises(ContractError): verify_record(receipt)


if __name__ == "__main__": unittest.main()
