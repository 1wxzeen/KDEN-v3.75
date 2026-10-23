"""Resumable, truth-free six-partition adapter acceptance. No neural replay."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import subprocess
import sys
from collections import Counter, defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

from .common import (ContractError, atomic_json, check_document, digest, hash_file,
                     inside, read_json, signed, utc_now, verify_record)
from .features import BASE, CYCLES, REGISTRY, SPINE, adapt, config, label_free_trend, source_proof
from .foundation import validate_t01
from .t02_runtime import checkpoint_config, probe_code_identity, runtime_identity

T02_FILES = ["run_t02.py", "config/features.json", "config/checkpoints.json",
             "environment/requirements-t02.txt", "src/kden_r14_tabular/features.py",
             "src/kden_r14_tabular/t02_runtime.py", "src/kden_r14_tabular/t02_workflow.py",
             "src/kden_r14_tabular/t02_cli.py", "schemas/t02_features.json",
             "schemas/t02_pass.json", "schemas/t02_state.json", "schemas/t02_partition.json",
             "tests/test_t02.py", "reports/T02_OWNER_RUNBOOK.md"]
PASS = "manifests/T02_PASS.json"


def run_path(experiment, run_id, relative):
    if not re.fullmatch(r"kdenv375-t02-[a-zA-Z0-9_-]{1,100}", run_id):
        raise ContractError("run ID must start kdenv375-t02- and contain only letters/numbers/_/-")
    return inside(experiment, f"runs/{run_id}/{relative}")


def identity(experiment):
    return {p: hash_file(inside(experiment, p)) for p in T02_FILES}


def bindings(experiment):
    files = read_json(inside(experiment, "inputs/input_inventory.json"))["files"]
    names = [SPINE, CYCLES, REGISTRY] + [f"{BASE}/target_year={y}/part-{y}.parquet" for y in range(2021, 2027)]
    result = {}
    for name in names:
        matches = [f for f in files if f["path"] == name and f["kind"] == "file"]
        if len(matches) != 1:
            raise ContractError("T02 source is not singly bound by accepted T01: " + name)
        result[name] = matches[0]["sha256"]
    return result


def checked_source(project, rel, expected):
    path = inside(project, rel)
    if hash_file(path) != expected:
        raise ContractError("frozen source changed: " + rel)
    return path


def preflight(project, experiment, device="cpu", *, require_runtime=False):
    t01 = validate_t01(project, experiment)
    cfg = config(experiment)
    proof = source_proof(project, cfg)
    bound = bindings(experiment)
    # Registry is small and directly rehashed even in preflight.
    checked_source(project, REGISTRY, bound[REGISTRY])
    missing = []
    for rel in ["environment/installation.json", "environment/requirements-resolved.txt",
                "environment/pip-install-report.json", f"environment/probe-{device}.json"]:
        if not inside(experiment, rel).is_file():
            missing.append(rel)
    for m in checkpoint_config(experiment)["models"]:
        rel = "checkpoints/" + m["filename"]
        if not inside(experiment, rel).is_file(): missing.append(rel)
    runtime = None
    if require_runtime:
        if missing:
            raise ContractError("owner preparation is incomplete: " + ", ".join(missing))
        runtime = runtime_identity(experiment, device)
        probe = verify_record(read_json(inside(experiment, f"environment/probe-{device}.json")))
        if (probe["status"] != "PASS" or probe["runtime_identity"] != runtime
                or probe["implementation_identity"] != probe_code_identity(experiment)
                or not all(p["query_order_and_batch_invariant"] for p in probe["probe_results"].values())):
            raise ContractError("offline device probe no longer matches runtime")
    return {"status": "READY_FOR_OWNER_ACCEPTANCE" if runtime else "FEATURE_INPUTS_READY_RUNTIME_PREPARATION_REQUIRED",
            "t01_record_sha256": t01["record_sha256"], "source_proof": proof,
            "source_bindings": bound, "t02_code_identity": identity(experiment),
            "runtime_identity": runtime, "missing_preparation_files": missing,
            "network_requests_made": 0, "holdout_value_pages_read": 0, "study_model_fits_performed": 0,
            "preflight_does_not_run_inference": True,
            "note": "without --runtime this is a structural preflight, not a runtime readiness claim"}


class Paused(Exception):
    pass


def publish_parquet(path, rows, cfg):
    import pyarrow as pa
    import pyarrow.parquet as pq
    path.parent.mkdir(parents=True, exist_ok=True)
    string_keys = ["issue_state_id", "target_date", "issue_time_utc", "availability_policy_id", "date_role",
                   "native_status", "source_feature_path", "source_feature_sha256", "source_provenance_json",
                   "coverage_diagnostics_json", "trend_q14_source_ids_json", "trend_q14_status"]
    fields = [pa.field(k, pa.string(), nullable=False) for k in string_keys]
    fields += [pa.field("local_issue_minute", pa.int16(), nullable=False),
               pa.field("trend_q14_valid_days", pa.int16(), nullable=False), pa.field("trend_q14_f", pa.float64())]
    # Fixed numeric schema even when an entire source column is missing.
    fields += [pa.field(k, pa.float64()) for k in cfg["input_columns"]]
    table = pa.Table.from_pylist(rows, schema=pa.schema(fields))
    fd, temporary = tempfile.mkstemp(prefix=".partition-", dir=path.parent)
    os.close(fd)
    try:
        pq.write_table(table, temporary, compression="zstd", row_group_size=4096)
        with open(temporary, "rb") as stream: os.fsync(stream.fileno())
        sha = hash_file(temporary)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if hash_file(path) != sha:
                raise ContractError("immutable partition already differs; no overwrite")
        return sha
    finally:
        os.unlink(temporary)


def _index(rows, keys):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        if key in result: raise ContractError("duplicate frozen spine/cycle identity")
        result[key] = row
    return result


def resume_partition(experiment, receipt_path, output_rel, source_sha256, run_identity, expected_rows):
    """Accept only a complete matching year and restore its last 14-day anchors."""
    import pyarrow.parquet as pq
    receipt = verify_record(read_json(receipt_path))
    check_document(experiment, "t02_partition", receipt)
    output_path = inside(experiment, output_rel)
    if (receipt["source_sha256"] != source_sha256 or receipt["identity_sha256"] != digest(run_identity)
            or receipt["path"] != output_rel or receipt["rows"] != expected_rows
            or hash_file(output_path) != receipt["sha256"]):
        raise ContractError("completed partition/identity differs on resume")
    rows = pq.ParquetFile(output_path).read(columns=["target_date", "local_issue_minute", "issue_time_utc", "anchor_q_f", "issue_state_id"]).to_pylist()
    if len(rows) != expected_rows:
        raise ContractError("completed partition footer differs from receipt")
    last = max(date.fromisoformat(r["target_date"]) for r in rows)
    history = defaultdict(deque)
    for row in rows:
        if date.fromisoformat(row["target_date"]) >= last-timedelta(days=13):
            history[row["local_issue_minute"]].append(row)
    return receipt, history


def build_partition(raw_rows, spine_rows, cycle_rows, cfg, source_path, source_sha256,
                    history, *, progress=lambda count: None):
    spine = _index(spine_rows, ["issue_state_id"])
    selected = _index(cycle_rows, ["issue_state_id", "product"])
    if len(selected) != 2 * len(spine):
        raise ContractError("selected-cycle row count differs from product-pair contract")
    output, seen, groups, counts = [], set(), set(), Counter()
    for ordinal, raw in enumerate(sorted(raw_rows, key=lambda r: (r["target_date"], r["issue_time_utc"])), 1):
        key = raw["issue_state_id"]
        if key in seen or (key,) not in spine:
            raise ContractError("duplicate/missing frozen issue ID")
        seen.add(key)
        products = {p: selected.get((key, p)) for p in ["wrfsfcf", "wrfsubhf"]}
        if any(v is None for v in products.values()):
            raise ContractError("missing per-product selection record")
        row = adapt(raw, spine[(key,)], products, cfg, source_path=source_path, source_sha256=source_sha256)
        group = (row["target_date"], row["local_issue_minute"])
        if group in groups: raise ContractError("one exact-minute row per weather day required")
        groups.add(group)
        day = date.fromisoformat(row["target_date"])
        prior = history[row["local_issue_minute"]]
        while prior and date.fromisoformat(prior[0]["target_date"]) < day - timedelta(days=14):
            prior.popleft()
        row.update(label_free_trend(row, prior))
        prior.append({k: row[k] for k in ["target_date", "local_issue_minute", "issue_time_utc", "anchor_q_f", "issue_state_id"]})
        counts[row["native_status"]] += 1
        output.append(row)
        if ordinal % 512 == 0: progress(ordinal)
    if seen != {k[0] for k in spine}:
        raise ContractError("feature partition does not cover its complete spine")
    return output, dict(counts)


def run_t02(project, experiment, run_id, device, *, resume=False):
    import pyarrow.parquet as pq
    if inside(experiment, PASS).exists():
        return validate_t02(project, experiment, device)
    root = run_path(experiment, run_id, "state.json").parent
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.json"
    if state_path.exists() and not resume:
        raise ContractError("existing run ID; use resume-t02")
    if resume and not state_path.exists():
        raise ContractError("resume requires an existing T02 run")
    if resume and read_json(state_path)["device"] != device:
        raise ContractError("resume must use the original explicit device")
    lock = inside(experiment, "runs/T02_RUNNING.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ContractError("T02 lock exists; inspect/recover only after its process is dead") from exc
    with os.fdopen(fd, "w") as stream: json.dump({"pid": os.getpid(), "run_id": run_id}, stream)
    state = {"schema_version": "R14_TABULAR_T02_STATE_V1", "run_id": run_id, "status": "RUNNING",
             "pid": os.getpid(), "device": device, "phase": "PREFLIGHT", "completed_partitions": 0,
             "total_partitions": 6, "completed_rows": 0, "total_rows": 118536,
             "inflight_rows": 0, "current_year": None, "active_seconds": 0., "message": None,
             "updated_at_utc": utc_now()}
    started = time.monotonic(); previous_active = 0.
    if resume:
        old = read_json(state_path)
        previous_active = old["active_seconds"]
    def write():
        state["updated_at_utc"] = utc_now()
        state["active_seconds"] = previous_active + time.monotonic() - started
        check_document(experiment, "t02_state", state)
        atomic_json(state_path, state)
    def pause():
        if (root / "pause.request.json").exists(): raise Paused()
    try:
        write()
        pre = preflight(project, experiment, device, require_runtime=True)
        bound, cfg = pre["source_bindings"], config(experiment)
        run_identity = {"t01_record_sha256": pre["t01_record_sha256"], "code_identity": pre["t02_code_identity"],
                        "source_bindings": bound, "runtime_identity": pre["runtime_identity"],
                        "probe_sha256": hash_file(inside(experiment, f"environment/probe-{device}.json"))}
        atomic_json(root / "identity.json", signed(run_identity), immutable=True)
        pause()
        state["phase"] = "FROZEN_CLOCKS"; write()
        spine = pq.ParquetFile(checked_source(project, SPINE, bound[SPINE])).read().to_pylist()
        cycles = pq.ParquetFile(checked_source(project, CYCLES, bound[CYCLES])).read().to_pylist()
        if len(spine) != 118536 or len(cycles) != 237072:
            raise ContractError("frozen clock counts disagree")
        spine_years, cycle_years = defaultdict(list), defaultdict(list)
        for row in spine: spine_years[row["target_date"].year].append(row)
        for row in cycles: cycle_years[row["target_date"].year].append(row)
        history, receipts = defaultdict(deque), []
        for partition in pre["source_proof"]["partitions"]:
            pause()
            rel = partition["path"]; year = int(rel.split("target_year=")[1][:4])
            state.update(phase="FEATURE_TRANSFORM", current_year=year, inflight_rows=0); write()
            receipt_path = root / f"receipts/{year}.json"
            output_rel = f"runs/{run_id}/features/target_year={year}/part-{year}.parquet"
            output_path = inside(experiment, output_rel)
            source = checked_source(project, rel, bound[rel])
            if receipt_path.exists():
                receipt, history = resume_partition(experiment, receipt_path, output_rel, bound[rel],
                                                    run_identity, partition["rows"])
            else:
                f = pq.ParquetFile(source)
                names = set(x["source"] for x in cfg["features"])
                names.update(["issue_state_id", "target_date", "issue_time_utc", "wrfsfcf_cycle_init_utc",
                              "wrfsubhf_cycle_init_utc", "feature_registry_id", "derivation_id"])
                names.update(k for k in f.schema_arrow.names if "coverage_fraction" in k or "missing_count" in k)
                raw = f.read(columns=[k for k in f.schema_arrow.names if k in names]).to_pylist()
                def progress(n):
                    state["inflight_rows"] = n; write(); pause()
                rows, counts = build_partition(raw, spine_years[year], cycle_years[year], cfg,
                                               rel, bound[rel], history, progress=progress)
                if len(rows) != partition["rows"]:
                    raise ContractError("adapted partition row count differs")
                pause()
                output_hash = publish_parquet(output_path, rows, cfg)
                receipt = signed({"schema_version": "R14_TABULAR_T02_PARTITION_V1", "year": year,
                                  "path": output_rel, "sha256": output_hash, "rows": len(rows),
                                  "source_path": rel, "source_sha256": bound[rel],
                                  "identity_sha256": digest(run_identity), "native_status_counts": counts})
                check_document(experiment, "t02_partition", receipt)
                atomic_json(receipt_path, receipt, immutable=True)
            receipts.append(receipt)
            state["completed_partitions"] += 1; state["completed_rows"] += receipt["rows"]
            state["inflight_rows"] = 0; write()
        pause()
        if state["completed_rows"] != 118536: raise ContractError("complete issue coverage failed")
        state.update(phase="CONTRACT_TESTS", current_year=None); write()
        tests = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s",
                                str(inside(experiment, "tests")), "-p", "test_t02.py"],
                               cwd=experiment, capture_output=True, text=True, timeout=60)
        if tests.returncode:
            raise ContractError("T02 bounded contract tests failed: " + tests.stderr[-3000:])
        report = {"status": "PASS", "rows": state["completed_rows"], "input_columns": cfg["input_columns"],
                  "native_status_counts": dict(sum((Counter(r["native_status_counts"]) for r in receipts), Counter())),
                  "source_proof": pre["source_proof"], "partitions": receipts,
                  "imputation": "NOT_GLOBALLY_MATERIALIZED; fitted separately on eligible earlier exact-minute contexts",
                  "truth_columns_in_features": False, "holdout_value_pages_read": 0,
                  "network_requests_made": 0, "study_model_fits_performed": 0,
                  "bounded_contract_tests": {"status": "PASS", "output": tests.stderr}}
        atomic_json(root / "feature_report.json", signed(report), immutable=True)
        body = {"schema_version": "R14_TABULAR_T02_PASS_V1", "status": "PASS", "stage": "T02",
                "run_id": run_id, "completed_at_utc": utc_now(), **run_identity,
                "partitions": receipts, "report_path": f"runs/{run_id}/feature_report.json",
                "report_sha256": hash_file(root / "feature_report.json"),
                "feature_columns": 71, "rows": 118536, "holdout_value_pages_read": 0,
                "network_requests_made": 0, "study_model_fits_performed": 0}
        record = signed(body); check_document(experiment, "t02_pass", record); pause()
        atomic_json(inside(experiment, PASS), record, immutable=True)
        state.update(status="PASS", phase="COMPLETE", pid=None, current_year=None); write()
        return record
    except Paused:
        state.update(status="PAUSED", pid=None, message="paused between bounded transform batches; only complete years are published")
        write(); return state
    except BaseException as exc:
        state.update(status="FAILED", pid=None, message=f"{type(exc).__name__}: {exc}"); write(); raise
    finally:
        lock.unlink(missing_ok=True)


def validate_t02(project, experiment, device=None):
    import pyarrow.parquet as pq
    t01 = validate_t01(project, experiment)
    result = verify_record(read_json(inside(experiment, PASS)))
    check_document(experiment, "t02_pass", result)
    actual_device = result["runtime_identity"]["device"]
    if device is not None and device != actual_device:
        raise ContractError("validation device differs from accepted runtime")
    if (result["t01_record_sha256"] != t01["record_sha256"] or result["code_identity"] != identity(experiment)
            or result["source_bindings"] != bindings(experiment)):
        raise ContractError("T02 code, source binding, or T01 predecessor changed")
    if result["runtime_identity"] != runtime_identity(experiment, actual_device):
        raise ContractError("T02 runtime changed")
    if result["probe_sha256"] != hash_file(inside(experiment, f"environment/probe-{actual_device}.json")):
        raise ContractError("accepted hardware probe changed")
    if result["report_sha256"] != hash_file(inside(experiment, result["report_path"])):
        raise ContractError("feature report changed")
    verify_record(read_json(inside(experiment, result["report_path"])))
    rows = 0
    if len(result["partitions"]) != 6 or {r["year"] for r in result["partitions"]} != set(range(2021, 2027)):
        raise ContractError("six complete year partitions required")
    for receipt in result["partitions"]:
        verify_record(receipt); check_document(experiment, "t02_partition", receipt)
        path = inside(experiment, receipt["path"])
        if hash_file(path) != receipt["sha256"] or pq.ParquetFile(path).metadata.num_rows != receipt["rows"]:
            raise ContractError("accepted adapter partition changed")
        rows += receipt["rows"]
    if rows != 118536: raise ContractError("accepted issue coverage changed")
    return {"status": "VALID", "validated_stage": "T02", "record_sha256": result["record_sha256"],
            "rows": rows, "feature_columns": 71, "device": actual_device,
            "holdout_value_pages_read": 0, "network_requests_made": 0, "study_model_fits_performed": 0,
            "original_feature_bytes_rehashed": False,
            "validation_mode": "ACCEPTED_ADAPTER_BYTES_RUNTIME_WEIGHTS_AND_T01_METADATA"}
