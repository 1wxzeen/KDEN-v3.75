"""Trusted local labels, strict chronological access and deferred truth auditing.

T01 deliberately has no command or flag that opens holdout outcomes. These are
application-level guardrails, not OS isolation from an owner who can read files.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta

from .common import ContractError, check_document, hash_file, inside, read_json, verify_record
from .dates import (DEV_END, END, HOLDOUT_END, HOLDOUT_START, START, inclusive,
                    label_cutoff, parse_date, role)

TRUTH_BASE = "truth/kden_tmax/v1"
DEV_LEDGER = f"{TRUTH_BASE}/adopted_stage5r1/development/kden_truth_ledger.parquet"
TAIL_LEDGER = f"{TRUTH_BASE}/tail_2026-09-07_2026-09-11/normalized/kden_truth_tail.parquet"
CATALOG = f"{TRUTH_BASE}/catalog/kden_truth_catalog.parquet"
SEALED_CANDIDATES = f"{TRUTH_BASE}/adopted_stage5r1/sealed_holdout/kden_truth_mechanical_candidates.parquet"
SEALED_EVIDENCE = f"{TRUTH_BASE}/adopted_stage5r1/source_evidence/sealed"


def integer_label(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("invalid integer Tmax label")
    if not math.isfinite(value) or not float(value).is_integer() or not -100 <= value <= 150:
        raise ContractError("invalid integer Tmax label")
    return int(value)


def trusted_rows(project):
    """Read labels ONLY from separate development and accepted five-day files.

    The catalog projection reads metadata columns only, never y/raw candidates.
    Never use a filtered read of the sealed candidate file as a shortcut.
    """
    import pyarrow.parquet as pq

    dev_path, tail_path = inside(project, DEV_LEDGER), inside(project, TAIL_LEDGER)
    source_hashes = {DEV_LEDGER: hash_file(dev_path), TAIL_LEDGER: hash_file(tail_path)}
    sources = {}
    for rel, path, first, last in [(DEV_LEDGER, dev_path, START, DEV_END),
                                   (TAIL_LEDGER, tail_path, HOLDOUT_END + timedelta(days=1), END)]:
        rows = pq.ParquetFile(path).read(columns=["target_date", "y_audited_f", "truth_qc_status"]).to_pylist()
        for row in rows:
            d = row["target_date"]
            if not first <= d <= last:
                continue
            if d in sources:
                raise ContractError("duplicate trusted target date")
            sources[d] = {"target_date": d.isoformat(), "date_role": role(d),
                          "y_audited_f": integer_label(row["y_audited_f"]),
                          "source_truth_qc_status": row["truth_qc_status"],
                          "source_artifact_path": rel}
    expected = set(inclusive(START, DEV_END) + inclusive(HOLDOUT_END + timedelta(days=1), END))
    if set(sources) != expected:
        raise ContractError("trusted truth source does not cover all authorized dates")
    metadata = pq.ParquetFile(inside(project, CATALOG)).read(columns=[
        "target_date", "truth_qc_status", "truth_evidence_status", "source_followup_window_open_at_freeze",
        "source_artifact_path", "source_artifact_sha256"]).to_pylist()
    if len(metadata) != 2080 or {r["target_date"] for r in metadata} != set(inclusive(START, END)):
        raise ContractError("catalog metadata date coverage failed")
    for row in metadata:
        d = row["target_date"]
        if d not in sources:
            continue
        output = sources[d]
        if row["source_artifact_path"] != output["source_artifact_path"]:
            raise ContractError("catalog source lineage disagrees with trusted adapter")
        if row["source_artifact_sha256"] != source_hashes[output["source_artifact_path"]]:
            raise ContractError("catalog trusted-source hash disagrees with actual source bytes")
        output.update({"truth_qc_status": row["truth_qc_status"],
                       "truth_evidence_status": row["truth_evidence_status"],
                       "source_artifact_sha256": row["source_artifact_sha256"],
                       "source_followup_window_open_at_freeze": row["source_followup_window_open_at_freeze"]})
    rows = [sources[d] for d in sorted(sources)]
    dev = [r for r in rows if r["target_date"] <= str(DEV_END)]
    extra = [r for r in rows if r["date_role"] == "ADDITIONAL_TRUSTED"]
    if len(dev) != 1710 or sum(r["y_audited_f"] is not None for r in dev) != 1707:
        raise ContractError("development truth count disagrees with frozen P02")
    if len(extra) != 5 or any(r["y_audited_f"] is None for r in extra):
        raise ContractError("five accepted additional labels are not complete")
    for row in rows:
        if (row["y_audited_f"] is None) != (row["truth_evidence_status"] == "unresolved"):
            raise ContractError("null/status truth inconsistency")
    return rows


def evidence_inventory(project):
    """Inspect filenames, sizes and Parquet FOOTERS; no holdout value pages."""
    import pyarrow.parquet as pq

    sealed = inside(project, SEALED_CANDIDATES)
    f = pq.ParquetFile(sealed)
    needed = {"target_date", "y_audited_f", "cli_values_json", "cf6_values_json", "audit_raw_sha256"}
    if f.metadata.num_rows != 365 or not needed <= set(f.schema_arrow.names):
        raise ContractError("sealed evidence candidate footer is incompatible")
    audits = []
    missing = []
    for d in inclusive(HOLDOUT_START, HOLDOUT_END):
        rel = f"{SEALED_EVIDENCE}/audit/year={d.year}/date={d}/audit.json"
        path = inside(project, rel)
        exists = path.is_file() and path.stat().st_size > 0
        audits.append({"target_date": str(d), "audit_path": rel, "present": exists,
                       "size_bytes": path.stat().st_size if exists else None})
        if not exists:
            missing.append(str(d))
    archives = []
    for pil in ["CLIDEN", "CF6DEN"]:
        for year in [2025, 2026]:
            base = f"{SEALED_EVIDENCE}/afos/pil={pil}/year={year}"
            paths = [f"{base}/{name}" for name in ["products.zip", "product_index.json", "products.meta.json"]]
            present = all(inside(project, p).is_file() and inside(project, p).stat().st_size > 0 for p in paths)
            archives.append({"pil": pil, "year": year, "paths": paths, "present": present})
    return {"schema_version": "R14_TABULAR_HOLDOUT_EVIDENCE_V1",
            "status": "STRUCTURALLY_PRESENT" if not missing and all(a["present"] for a in archives) else "EVIDENCE_GAPS",
            "sealed_candidate_rows_from_footer": f.metadata.num_rows,
            "audit_payloads": audits, "archive_bundles": archives,
            "missing_audit_dates": missing,
            "content_audit_performed": False, "holdout_value_pages_read": 0,
            "interpretation": "Presence and hash integrity are not CLI/CF6 agreement or usable-label proof. Content audit is deferred until recipe lock and owner-run replay."}


class TruthAccess:
    """Separate training/history and committed-forecast scoring roles.

    No all-labels property, no permissive holdout flag, no implicit imputation.
    Future rolling holdout access will require a separately implemented lock gate.
    """
    def __init__(self, rows, experiment):
        self._experiment = experiment
        self._labels = {}
        for row in rows:
            d = parse_date(row["target_date"])
            if HOLDOUT_START <= d <= HOLDOUT_END:
                raise ContractError("T01 cannot load holdout values")
            if d in self._labels:
                raise ContractError("duplicate target date in trusted label table")
            self._labels[d] = {**row, "y_audited_f": integer_label(row["y_audited_f"])}

    @classmethod
    def from_release(cls, experiment):
        release = verify_record(read_json(inside(experiment, "manifests/T01_PASS.json")))
        rel = "inputs/truth/trusted_labels.json"
        path = inside(experiment, rel)
        if hash_file(path) != release["artifact_hashes"][rel]:
            raise ContractError("trusted truth overlay changed after T01")
        return cls(read_json(path)["rows"], experiment)

    def context(self, update_date, *, dates=None):
        cutoff = label_cutoff(update_date)
        requested = sorted(self._labels) if dates is None else [parse_date(d) for d in dates]
        if len(requested) != len(set(requested)):
            raise ContractError("duplicate training target dates")
        output = []
        for d in requested:
            if HOLDOUT_START <= d <= HOLDOUT_END:
                raise ContractError("holdout access requires the future recipe-lock/replay gate")
            if d >= cutoff:
                if dates is None:
                    continue
                raise ContractError("training/history date violates exclusive seven-day cutoff")
            if d not in self._labels:
                raise ContractError("requested date has no authorized trusted source")
            row = self._labels[d]
            if row["y_audited_f"] is not None:
                output.append(dict(row))
        return output

    def score(self, target_date, *, commit_path):
        d = parse_date(target_date)
        if HOLDOUT_START <= d <= HOLDOUT_END:
            raise ContractError("T01 holdout scoring is closed")
        path = inside(self._experiment, commit_path)
        if not str(commit_path).startswith("runs/"):
            raise ContractError("forecast commit must live inside experiment runs")
        receipt = verify_record(read_json(path))
        check_document(self._experiment, "forecast_commit", receipt)
        if receipt.get("schema_version") != "R14_TABULAR_FORECAST_COMMIT_V1" or receipt.get("status") != "COMMITTED":
            raise ContractError("committed forecast receipt required before scoring")
        artifact = receipt.get("artifact_path", "")
        if not artifact.startswith("runs/") or not artifact.endswith(".parquet"):
            raise ContractError("forecast payload must be an experiment-local Parquet file")
        payload = inside(self._experiment, artifact)
        if hash_file(payload) != receipt.get("artifact_sha256"):
            raise ContractError("committed forecast payload changed")
        import pyarrow.parquet as pq
        keys = pq.ParquetFile(payload).read(columns=["issue_state_id", "target_date"]).to_pylist()
        ids = [r["issue_state_id"] for r in keys]
        actual_dates = {str(r["target_date"]) for r in keys}
        if not keys or len(ids) != len(set(ids)) or actual_dates != set(receipt.get("target_dates", [])):
            raise ContractError("forecast receipt does not match committed query keys")
        if str(d) not in actual_dates:
            raise ContractError("query date has no committed prediction")
        if d not in self._labels:
            raise ContractError("query date is not authorized")
        return dict(self._labels[d])  # unresolved remains null, never imputed


def audit_chronology(target, events, *, atomic_value=None, guarded_exception=None):
    """Pure future-adapter rule, exercised only with synthetic evidence in T01.

    Accepts normalized CLI/CF6 events; does not read files or make requests.
    Product parsing and sealed publication are deliberately not enabled in T01.
    """
    target = parse_date(target)
    cutoff = datetime.combine(target + timedelta(days=1), time(7), UTC)
    eligible = []
    for event in events:
        when = datetime.fromisoformat(event["event_time_utc"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ContractError("truth event timestamp lacks timezone")
        value = integer_label(event.get("value_f"))
        if event.get("source") in {"CLI", "CF6"} and when >= cutoff and value is not None:
            eligible.append({**event, "when": when, "value_f": value})
    eligible.sort(key=lambda e: e["when"])
    cli = [e for e in eligible if e["source"] == "CLI"]
    cf6 = [e for e in eligible if e["source"] == "CF6"]
    values = {e["value_f"] for e in eligible}
    if cli and cf6 and len(values) == 1:
        return {"y_audited_f": next(iter(values)), "truth_qc_status": "audited"}
    if guarded_exception is not None:
        e = guarded_exception
        guards = {"target_date": str(target), "expected_iem_atomic_raw_f": integer_label(atomic_value),
                  "expected_cli_first_completed_f": cli[0]["value_f"] if cli else None,
                  "expected_cf6_first_f": cf6[0]["value_f"] if cf6 else None}
        if not str(e.get("approval_status", "")).startswith("approved_") or any(e.get(k) != v for k, v in guards.items()):
            raise ContractError("guarded exception evidence mismatch")
        selected = e.get("selected_product_id")
        if not selected or selected not in {r.get("product_id") for r in eligible}:
            raise ContractError("guarded exception selected product absent")
        audited = integer_label(e.get("y_audited_f"))
        if audited is None:
            raise ContractError("guarded exception has no audited value")
        return {"y_audited_f": audited, "truth_qc_status": "audited_guarded_exception"}
    return {"y_audited_f": None, "truth_qc_status": "unresolved"}
