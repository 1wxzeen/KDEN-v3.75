"""Bounded synthetic tests: no production labels, models or network access."""
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from kden_r14_tabular.cli import recover_lock, snapshot
from kden_r14_tabular.common import (ContractError, atomic_json, canonical, digest,
                                     hash_file, inside, read_json, schema_check, signed)
from kden_r14_tabular.dates import (DEV_END, END, HOLDOUT_END, HOLDOUT_START,
                                   START, date_overlay, inclusive, issue_times,
                                   label_cutoff, label_eligible, native_blocks, role)
from kden_r14_tabular.foundation import (ADOPTION, EXPERIMENT_REL, EXPOSURE,
                                        P06_FREEZE, TAIL_MANIFEST, authorities, code_identity,
                                        hash_input, preflight, run_t01, validate_t01)
from kden_r14_tabular.truth import (CATALOG, DEV_LEDGER, SEALED_CANDIDATES,
                                   SEALED_EVIDENCE, TAIL_LEDGER, TruthAccess,
                                   audit_chronology, evidence_inventory, trusted_rows)

ROOT = Path(__file__).resolve().parents[1]
RUN = "kden-r14-t01-20261010T010000Z-synthetic"


def json_file(root, relative, value):
    p = root / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(p, value)
    return p


def parquet_file(root, relative, rows):
    p = root / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), p)
    return p


class Fixture(unittest.TestCase):
    def setUp(self):
        cache = ROOT / "cache"
        cache.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="t01-test-", dir=cache)
        self.project = Path(self.tmp.name)
        self.exp = self.project / EXPERIMENT_REL
        self.exp.mkdir(parents=True)
        for name in ["src", "schemas", "config", "tests", "reports"]:
            shutil.copytree(ROOT / name, self.exp / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ["run.py", "README.md"]:
            shutil.copy2(ROOT / name, self.exp / name)

    def tearDown(self):
        self.tmp.cleanup()

    def build_inputs(self):
        dev_dates = inclusive(START, DEV_END)
        unresolved = set(dev_dates[:3])
        dev = [{"target_date": d, "y_audited_f": None if d in unresolved else 80,
                "truth_qc_status": "unresolved_cf6_only" if d in unresolved else "auto_audited_cli_cf6_unanimous"} for d in dev_dates]
        dev_path = parquet_file(self.project, DEV_LEDGER, dev)
        tail = [{"target_date": d, "y_audited_f": 81, "truth_qc_status": "auto_audited_cli_cf6_unanimous"}
                for d in inclusive(HOLDOUT_END + timedelta(days=1), END)]
        tail_path = parquet_file(self.project, TAIL_LEDGER, tail)
        sealed = [{"target_date": d, "y_audited_f": None, "cli_values_json": "[]", "cf6_values_json": "[]",
                   "audit_raw_sha256": "0" * 64} for d in inclusive(HOLDOUT_START, HOLDOUT_END)]
        sealed_path = parquet_file(self.project, SEALED_CANDIDATES, sealed)
        metadata = []
        for d in inclusive(START, END):
            is_dev, is_hold = d <= DEV_END, HOLDOUT_START <= d <= HOLDOUT_END
            rel = DEV_LEDGER if is_dev else SEALED_CANDIDATES if is_hold else TAIL_LEDGER
            src = dev_path if is_dev else sealed_path if is_hold else tail_path
            metadata.append({"target_date": d, "truth_qc_status": "unresolved_cf6_only" if d in unresolved else "sealed_pending_audit" if is_hold else "auto_audited_cli_cf6_unanimous",
                             "truth_evidence_status": "unresolved" if d in unresolved else "audited" if is_dev else "sealed_holdout" if is_hold else "tail_audited",
                             "source_artifact_path": rel, "source_artifact_sha256": hash_file(src),
                             "source_followup_window_open_at_freeze": not is_dev,
                             "y_audited_f": None if is_hold or d in unresolved else 80 if is_dev else 81})
        catalog = parquet_file(self.project, CATALOG, metadata)
        spine_rel = "universal_issue_state/v1/issue_spine/issue_spine.parquet"
        spine = self.project / spine_rel
        spine.parent.mkdir(parents=True)
        pq.write_table(pa.table({"synthetic_id": range(118536)}), spine)
        adoption_files = [dev_path, sealed_path]
        for d in inclusive(HOLDOUT_START, HOLDOUT_END):
            p = json_file(self.project, f"{SEALED_EVIDENCE}/audit/year={d.year}/date={d}/audit.json", {"synthetic_opaque": True})
            adoption_files.append(p)
        for pil in ["CLIDEN", "CF6DEN"]:
            for year in [2025, 2026]:
                for filename in ["products.zip", "product_index.json", "products.meta.json"]:
                    p = self.project / SEALED_EVIDENCE / f"afos/pil={pil}/year={year}/{filename}"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"synthetic-opaque")
                    adoption_files.append(p)
        adoption = {"file_count": len(adoption_files), "files": [{"destination_relative_path": p.relative_to(self.project).as_posix(),
                     "sha256": hash_file(p), "size_bytes": p.stat().st_size} for p in adoption_files]}
        adoption_path = json_file(self.project, ADOPTION, adoption)
        tail_manifest_path = json_file(self.project, TAIL_MANIFEST, {"normalized_artifacts": {
            "truth": {"path": TAIL_LEDGER, "sha256": hash_file(tail_path)}}, "source_files": []})
        freeze = signed({"status": "FROZEN_ACCEPTED", "frozen_files": {str(p.relative_to(self.project)): hash_file(p) for p in [dev_path, tail_path, catalog, spine]}})
        json_file(self.project, P06_FREEZE, freeze)
        p02 = signed({"status": "PASS", "stage_id": "PREFIT_P02", "authority_hashes": {
            "ADOPTION_MANIFEST": hash_file(adoption_path), "TRUTH_CATALOG": hash_file(catalog),
            "TAIL_MANIFEST": hash_file(tail_manifest_path)}})
        p06 = signed({"status": "PASS", "stage_id": "PREFIT_P06"})
        json_file(self.project, "state/PREFIT_P02_PASS.json", p02)
        json_file(self.project, "state/PREFIT_P06_PASS.json", p06)
        boundary = signed({"status": "PREFIT_COMPLETE_MODEL_FITTING_AUTHORIZED", "p06_record_sha256": p06["record_sha256"]})
        boundary_path = json_file(self.project, "state/KDEN_V375_MODELING_BOUNDARY_PASS.json", boundary)
        p07 = signed({"status": "PASS", "stage_id": "PREFIT_P07", "predecessor_hashes": {"PREFIT_P06": p06["record_sha256"]},
            "authority_hashes": {"P06_FREEZE": freeze["record_sha256"], "P07_MODELING_BOUNDARY_PASS": boundary["record_sha256"], "TRUTH_CATALOG": hash_file(catalog)},
            "artifact_hashes": {str(boundary_path.relative_to(self.project)): hash_file(boundary_path)}})
        json_file(self.project, "state/PREFIT_P07_PASS.json", p07)
        config = read_json(self.exp / "config/experiment.json")
        config["trusted_record_pins"] = {rel: read_json(self.project / rel)["record_sha256"] for rel in config["trusted_record_pins"]}
        atomic_json(self.exp / "config/experiment.json", config)
        json_file(self.project, EXPOSURE, {"records": [{"kind": "previous_research_exposure"}]})


class DateTests(unittest.TestCase):
    def test_dates_grid_blocks(self):
        overlay = date_overlay()
        self.assertEqual(len(overlay["rows"]), 2080)
        self.assertEqual(sum(r["expected_issue_count"] for r in overlay["rows"]), 118536)
        self.assertEqual(sum(r["date_role"] == "ROLLING_HOLDOUT" for r in overlay["rows"]), 365)
        blocks = native_blocks()
        self.assertEqual(len(blocks), 58)
        self.assertEqual(blocks[45]["start_date"], "2025-09-07")
        self.assertEqual(blocks[-1]["end_date"], "2026-09-06")
        self.assertEqual(overlay["rows"][-1]["native_block_id"], blocks[-1]["block_id"])
        self.assertEqual(role("2026-09-07"), "ADDITIONAL_TRUSTED")

    def test_dst_and_clocks(self):
        self.assertEqual(len(issue_times(date(2025, 3, 9))), 53)
        self.assertEqual(len(issue_times(date(2025, 11, 2))), 57)
        self.assertEqual(len(set(issue_times(date(2025, 3, 9)))), 53)

    def test_exclusive_cutoff(self):
        self.assertEqual(label_cutoff("2025-10-01"), date(2025, 9, 24))
        self.assertTrue(label_eligible("2025-09-23", "2025-10-01"))
        self.assertFalse(label_eligible("2025-09-24", "2025-10-01"))
        self.assertFalse(label_eligible("2025-10-01", "2025-10-01"))


class CommonTests(Fixture):
    def test_atomic_no_overwrite_and_escape(self):
        p = self.exp / "manifests/immutable.json"
        atomic_json(p, {"a": 1}, immutable=True)
        atomic_json(p, {"a": 1}, immutable=True)
        with self.assertRaises(ContractError):
            atomic_json(p, {"a": 2}, immutable=True)
        for relative in ["../escape", "/escape"]:
            with self.assertRaises(ContractError):
                inside(self.exp, relative)
        (self.exp / "escape").symlink_to(self.project)
        with self.assertRaises(ContractError):
            inside(self.exp, "escape/file")

    def test_schema_type_bool_is_not_integer(self):
        with self.assertRaises(ContractError):
            schema_check(True, {"type": "integer"})
        with self.assertRaises(ContractError):
            schema_check({"x": 1}, {"type": "object", "required": ["y"]})


class TruthTests(Fixture):
    def test_training_guards_nulls_and_closed_holdout(self):
        rows = [{"target_date": "2025-08-29", "y_audited_f": 80},
                {"target_date": "2025-08-30", "y_audited_f": 81},
                {"target_date": "2025-08-28", "y_audited_f": None},
                {"target_date": "2026-09-07", "y_audited_f": 82}]
        access = TruthAccess(rows, self.exp)
        self.assertEqual([r["target_date"] for r in access.context("2025-09-06")], ["2025-08-29"])
        with self.assertRaises(ContractError):
            access.context("2025-09-06", dates=["2025-08-30"])
        with self.assertRaises(ContractError):
            access.context("2026-09-11", dates=["2025-09-07"])
        with self.assertRaises(ContractError):
            TruthAccess([{"target_date": "2025-09-07", "y_audited_f": 80}], self.exp)
        with self.assertRaises(ContractError):
            access.score("2025-09-07", commit_path="runs/none.json")

    def test_score_requires_real_committed_keys_and_hash(self):
        access = TruthAccess([{"target_date": "2025-08-01", "y_audited_f": 80}], self.exp)
        with self.assertRaises(ContractError):
            access.score("2025-08-01", commit_path="outside.json")
        payload = parquet_file(self.exp, "runs/synthetic/predictions.parquet", [{"issue_state_id": "SYNTHETIC", "target_date": date(2025, 8, 1)}])
        receipt = signed({"schema_version": "R14_TABULAR_FORECAST_COMMIT_V1", "status": "COMMITTED", "artifact_path": "runs/synthetic/predictions.parquet",
                          "artifact_sha256": hash_file(payload), "target_dates": ["2025-08-01"], "recipe_sha256": "0" * 64, "model_id": "SYNTHETIC", "run_id": "synthetic"})
        json_file(self.exp, "runs/synthetic/commit.json", receipt)
        self.assertEqual(access.score("2025-08-01", commit_path="runs/synthetic/commit.json")["y_audited_f"], 80)
        payload.write_bytes(b"tamper")
        with self.assertRaises(ContractError):
            access.score("2025-08-01", commit_path="runs/synthetic/commit.json")

    def test_no_holdout_payload_parsing(self):
        self.build_inputs()
        real_parquet = pq.ParquetFile
        observed_columns = []
        class Guard:
            def __init__(self, path):
                self.path = Path(path)
                self.inner = real_parquet(path)
                self.metadata, self.schema_arrow = self.inner.metadata, self.inner.schema_arrow
            def read(self, columns=None):
                if self.path.name == "kden_truth_mechanical_candidates.parquet":
                    raise AssertionError("holdout page read")
                if self.path.name == "kden_truth_catalog.parquet":
                    observed_columns.append(columns)
                    assert "y_audited_f" not in columns
                return self.inner.read(columns=columns)
        with patch("pyarrow.parquet.ParquetFile", Guard):
            self.assertEqual(evidence_inventory(self.project)["status"], "STRUCTURALLY_PRESENT")
            rows = trusted_rows(self.project)
        self.assertEqual(len(rows), 1715)
        self.assertEqual(sum(r["y_audited_f"] is None for r in rows), 3)
        self.assertTrue(observed_columns)
        self.assertTrue(all(r["y_audited_f"] == 81 for r in rows if r["date_role"] == "ADDITIONAL_TRUSTED"))

    def test_synthetic_cli_cf6_agreement_conflict_cutoff(self):
        events = [{"source": s, "event_time_utc": "2025-08-02T07:00:00Z", "value_f": 80, "product_id": s}
                  for s in ["CLI", "CF6"]]
        self.assertEqual(audit_chronology("2025-08-01", events)["y_audited_f"], 80)
        events.append({"source": "CLI", "event_time_utc": "2025-08-03T10:00:00Z", "value_f": 81, "product_id": "LATER"})
        self.assertIsNone(audit_chronology("2025-08-01", events)["y_audited_f"])
        self.assertIsNone(audit_chronology("2025-08-01", events[:1])["y_audited_f"])
        e = {"target_date": "2025-08-01", "approval_status": "approved_synthetic", "expected_iem_atomic_raw_f": 79,
             "expected_cli_first_completed_f": 80, "expected_cf6_first_f": 80, "selected_product_id": "CLI", "y_audited_f": 80}
        self.assertEqual(audit_chronology("2025-08-01", events, atomic_value=79, guarded_exception=e)["truth_qc_status"], "audited_guarded_exception")
        with self.assertRaises(ContractError):
            audit_chronology("2025-08-01", events, atomic_value=78, guarded_exception=e)

    def test_precutoff_and_timezone_rejection(self):
        before = [{"source": s, "event_time_utc": "2025-08-02T06:59:59Z", "value_f": 80}
                  for s in ["CLI", "CF6"]]
        self.assertIsNone(audit_chronology("2025-08-01", before)["y_audited_f"])
        with self.assertRaises(ContractError):
            audit_chronology("2025-08-01", [{"source": "CLI", "event_time_utc": "2025-08-02T07:00:00", "value_f": 80}])


class WorkflowTests(Fixture):
    def test_owner_workflow_synthetic_pass_valid_tamper(self):
        self.build_inputs()
        self.assertEqual(preflight(self.project, self.exp)["status"], "READY_FOR_OWNER_T01")
        self.assertEqual(run_t01(self.project, self.exp, RUN)["status"], "PASS")
        self.assertEqual(validate_t01(self.project, self.exp)["status"], "VALID")
        self.assertEqual(validate_t01(self.project, self.exp, deep=True)["status"], "VALID")
        access = TruthAccess.from_release(self.exp)
        self.assertGreater(len(access.context("2025-09-07")), 1000)
        self.assertFalse((self.exp / "runs/T01_RUNNING.lock").exists())
        (self.project / DEV_LEDGER).write_bytes(b"tamper")
        with self.assertRaises(ContractError):
            validate_t01(self.project, self.exp, deep=True)

    def test_pause_resume_and_stale_identity(self):
        self.build_inputs()
        json_file(self.exp, f"runs/{RUN}/pause.request.json", {"pause_requested": True})
        self.assertEqual(run_t01(self.project, self.exp, RUN)["status"], "PAUSED")
        self.assertFalse((self.exp / "manifests/T01_PASS.json").exists())
        (self.exp / f"runs/{RUN}/pause.request.json").unlink()
        config = read_json(self.exp / "config/experiment.json")
        config["planning_proposals_not_locked"]["mean_rmse_f_max"] = 1.8
        atomic_json(self.exp / "config/experiment.json", config)
        with self.assertRaises(ContractError):
            run_t01(self.project, self.exp, RUN)
        self.assertEqual(read_json(self.exp / f"runs/{RUN}/state.json")["status"], "FAILED")

    def test_live_lock_refused(self):
        json_file(self.exp, "runs/T01_RUNNING.lock", {"pid": os.getpid(), "run_id": RUN})
        with self.assertRaises(ContractError):
            recover_lock(self.exp)
        with self.assertRaises(ContractError):
            run_t01(self.project, self.exp, RUN)
        self.assertTrue((self.exp / "runs/T01_RUNNING.lock").exists())

    def test_resume_without_code_changes(self):
        self.build_inputs()
        json_file(self.exp, f"runs/{RUN}/pause.request.json", {"pause_requested": True})
        self.assertEqual(run_t01(self.project, self.exp, RUN)["status"], "PAUSED")
        (self.exp / f"runs/{RUN}/pause.request.json").unlink()
        self.assertEqual(run_t01(self.project, self.exp, RUN)["status"], "PASS")
        self.assertEqual(validate_t01(self.project, self.exp)["status"], "VALID")

    def test_additive_future_stage_does_not_reseal_t01(self):
        identity = code_identity(self.exp)
        (self.exp / "src/kden_r14_tabular/t02_future.py").write_text("# Synthetic later-stage addition\n")
        self.assertEqual(identity, code_identity(self.exp))

    def test_wrong_lag_and_stale_record_rejected(self):
        self.build_inputs()
        config = read_json(self.exp / "config/experiment.json")
        bad = dict(config)
        bad["hrrr_availability_lag_minutes"] = 60
        atomic_json(self.exp / "config/experiment.json", bad)
        with self.assertRaises(ContractError):
            preflight(self.project, self.exp)
        atomic_json(self.exp / "config/experiment.json", config)
        body = read_json(self.project / "state/PREFIT_P06_PASS.json")
        body["status"] = "FAILED"
        atomic_json(self.project / "state/PREFIT_P06_PASS.json", body)
        with self.assertRaises(ContractError):
            preflight(self.project, self.exp)

    def test_missing_holdout_evidence_reported_without_values(self):
        self.build_inputs()
        p = self.project / SEALED_EVIDENCE / "audit/year=2025/date=2025-09-07/audit.json"
        p.unlink()
        report = evidence_inventory(self.project)
        self.assertEqual(report["status"], "EVIDENCE_GAPS")
        self.assertEqual(report["missing_audit_dates"], ["2025-09-07"])
        self.assertEqual(report["holdout_value_pages_read"], 0)


if __name__ == "__main__":
    unittest.main()
