"""Owner-run T01 input binding, overlay publication and content-addressed PASS."""
from __future__ import annotations

import ast
import os
import re
import time
from collections import Counter
from pathlib import Path

from .common import (ContractError, atomic_json, canonical, check_document, digest,
                     hash_file, inside, read_json, signed, utc_now, verify_record)
from .dates import date_overlay
from .truth import (CATALOG, DEV_LEDGER, SEALED_CANDIDATES, TAIL_LEDGER,
                    TRUTH_BASE, evidence_inventory, trusted_rows)

EXPERIMENT_REL = "universal_issue_state/experiments/r14_tabular_pretrained_v1"
P06_FREEZE = "universal_issue_state/v1/manifests/p06_substrate_freeze_manifest.json"
ADOPTION = f"{TRUTH_BASE}/adopted_stage5r1/adoption_manifest.json"
TAIL_MANIFEST = f"{TRUTH_BASE}/tail_2026-09-07_2026-09-11/manifest/manifest.json"
EXPOSURE = "universal_issue_state/experiments/r14_first_model_comparison_v1/config/evidence_exposure.json"
PASS_REL = "manifests/T01_PASS.json"
TRANSIENT = {"__pycache__", ".pytest_cache", ".DS_Store"}
RUN_PATTERN = re.compile(r"^kden-r14-t01-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,31}$")
T01_FILES = ["README.md", "run.py", "reports/T01_OWNER_RUNBOOK.md", "config/experiment.json",
             "tests/test_foundation.py"] + [f"src/kden_r14_tabular/{name}.py" for name in
             ["__init__", "common", "dates", "truth", "foundation", "cli"]] + [f"schemas/{name}.json" for name in
             ["experiment", "input_inventory", "date_roles", "trusted_labels", "holdout_evidence",
              "exposure", "truth_adapter", "run_state", "pass", "forecast_commit"]]


class PauseRequested(RuntimeError):
    pass


def run_path(experiment, run_id, relative=""):
    if not RUN_PATTERN.fullmatch(run_id):
        raise ContractError("run ID must be kden-r14-t01-YYYYMMDDTHHMMSSZ-label")
    return inside(experiment, f"runs/{run_id}/{relative}")


def code_identity(experiment):
    # Bind just this stage's owned files. Future stages may ADD modules and
    # schemas without invalidating T01; changing an owned file remains forbidden.
    return {p: hash_file(inside(experiment, p)) for p in sorted(T01_FILES)}


def isolation_check(experiment):
    scanned = 0
    for p in inside(experiment, "src").rglob("*.py"):
        text = p.read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            modules = ([n.name for n in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(m.split(".")[0] in {"kden35", "kden_panel", "kden_v375", "lamp_pipeline"} for m in modules):
                raise ContractError("runtime import from a reference codebase is forbidden")
        if any(marker in text for marker in ("/" + "Users" + "/", "previous" + " codebases/")):
            raise ContractError("absolute user path or legacy runtime reference in source")
        scanned += 1
    return {"source_files_scanned": scanned, "legacy_runtime_imports": 0, "absolute_user_paths": 0}


def load_config(project, experiment):
    if Path(experiment).resolve() != inside(project, EXPERIMENT_REL).resolve():
        raise ContractError("experiment must be contained at its declared KDEN location")
    config = read_json(inside(experiment, "config/experiment.json"))
    check_document(experiment, "experiment", config)
    overlay = date_overlay()
    counts = Counter(r["date_role"] for r in overlay["rows"])
    expected = config["expected_counts"]
    if (len(overlay["rows"]) != expected["target_days"]
            or sum(r["expected_issue_count"] for r in overlay["rows"]) != expected["issue_states"]
            or counts["ROLLING_HOLDOUT"] != expected["holdout_days"]
            or counts["ADDITIONAL_TRUSTED"] != expected["additional_trusted_days"]
            or sum(b["role"] == "DEVELOPMENT" for b in overlay["native_blocks"]) != 45
            or sum(b["role"] == "ROLLING_HOLDOUT" for b in overlay["native_blocks"]) != 13):
        raise ContractError("date enumeration disagrees with the frozen T01 contract")
    return config


def authorities(project, config):
    records = {}
    for rel, expected in config["trusted_record_pins"].items():
        record = verify_record(read_json(inside(project, rel)))
        if record["record_sha256"] != expected:
            raise ContractError(f"trusted predecessor identity changed: {rel}")
        records[rel] = record
    p02, p06, p07 = [records[f"state/PREFIT_P{n:02d}_PASS.json"] for n in [2, 6, 7]]
    for n, record in [(2, p02), (6, p06), (7, p07)]:
        if record.get("status") != "PASS" or record.get("stage_id") != f"PREFIT_P{n:02d}":
            raise ContractError("required prefit predecessor is not PASS")
    if p07["predecessor_hashes"]["PREFIT_P06"] != p06["record_sha256"]:
        raise ContractError("P07 predecessor chain mismatch")
    freeze = records[P06_FREEZE]
    if freeze.get("status") != "FROZEN_ACCEPTED" or p07["authority_hashes"]["P06_FREEZE"] != freeze["record_sha256"]:
        raise ContractError("substrate freeze chain mismatch")
    boundary = records["state/KDEN_V375_MODELING_BOUNDARY_PASS.json"]
    if (boundary.get("status") != "PREFIT_COMPLETE_MODEL_FITTING_AUTHORIZED"
            or boundary["p06_record_sha256"] != p06["record_sha256"]
            or p07["authority_hashes"]["P07_MODELING_BOUNDARY_PASS"] != boundary["record_sha256"]):
        raise ContractError("modeling boundary predecessor mismatch")
    if hash_file(inside(project, ADOPTION)) != p02["authority_hashes"]["ADOPTION_MANIFEST"]:
        raise ContractError("adopted truth manifest differs from P02 authority")
    if hash_file(inside(project, TAIL_MANIFEST)) != p02["authority_hashes"]["TAIL_MANIFEST"]:
        raise ContractError("accepted five-day manifest differs from P02 authority")
    if p07["authority_hashes"]["TRUTH_CATALOG"] != p02["authority_hashes"]["TRUTH_CATALOG"]:
        raise ContractError("truth catalog authority chain mismatch")
    return records


def input_inventory(project, config, records):
    entries = {}

    def add(rel, expected, source, size=None):
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ContractError("malformed input hash authority")
        path = inside(project, rel)
        if not path.exists():
            raise ContractError(f"required input missing: {rel}")
        kind = "file" if path.is_file() else "directory"
        if rel in entries and entries[rel]["sha256"] != expected:
            raise ContractError("predecessors give conflicting input hashes")
        if size is not None and (kind != "file" or path.stat().st_size != size):
            raise ContractError(f"adopted evidence size changed: {rel}")
        entries[rel] = {"path": rel, "kind": kind, "sha256": expected,
                        "size_bytes": path.stat().st_size if kind == "file" else None,
                        "hash_authority": source}

    for rel, record in records.items():
        add(rel, hash_file(inside(project, rel)), "TRUSTED_RECORD_PIN")
    freeze = records[P06_FREEZE]
    for rel, expected in freeze["frozen_files"].items():
        add(rel, expected, "P06_FROZEN_FILES")
    for rel, expected in records["state/PREFIT_P07_PASS.json"]["artifact_hashes"].items():
        add(rel, expected, "P07_ARTIFACT_HASHES")
    p02 = records["state/PREFIT_P02_PASS.json"]
    add(ADOPTION, p02["authority_hashes"]["ADOPTION_MANIFEST"], "P02_ADOPTION_AUTHORITY")
    add(TAIL_MANIFEST, p02["authority_hashes"]["TAIL_MANIFEST"], "P02_ACCEPTED_FIVE_DAY_AUTHORITY")
    add(CATALOG, p02["authority_hashes"]["TRUTH_CATALOG"], "P02_CATALOG_AUTHORITY")
    adoption = read_json(inside(project, ADOPTION))
    if adoption["file_count"] != len(adoption["files"]):
        raise ContractError("adoption inventory count mismatch")
    for item in adoption["files"]:
        add(item["destination_relative_path"], item["sha256"], "P02_ADOPTED_BYTE_COPY", item["size_bytes"])
    tail = read_json(inside(project, TAIL_MANIFEST))
    for item in tail["normalized_artifacts"].values():
        add(item["path"], item["sha256"], "P02_ACCEPTED_FIVE_DAY_NORMALIZED")
    for item in tail["source_files"]:
        add(item["path"], item["sha256"], "P02_ACCEPTED_FIVE_DAY_SOURCE", item["size_bytes"])
    # These sources have independent authorities; P06 does not inline them.
    for required in [DEV_LEDGER, TAIL_LEDGER, SEALED_CANDIDATES]:
        if required not in entries:
            raise ContractError(f"required trusted or opaque evidence input is unbound: {required}")
    add(EXPOSURE, hash_file(inside(project, EXPOSURE)), "T01_EXISTING_EXPOSURE_SNAPSHOT")
    return {"schema_version": "R14_TABULAR_INPUT_INVENTORY_V1", "files": list(sorted(entries.values(), key=lambda r: r["path"])),
            "scope": "P06 frozen substrate files, P07 artifact bindings, copied P02 truth evidence, and local exposure disclosure; canonical HRRR values remain covered by upstream acceptance, not re-scanned here.",
            "holdout_hash_method": "Opaque bytes only; hashes do not parse outcomes."}


def preflight(project, experiment):
    config = load_config(project, experiment)
    records = authorities(project, config)
    inventory = input_inventory(project, config, records)
    evidence = evidence_inventory(project)
    import pyarrow.parquet as pq
    spine = pq.ParquetFile(inside(project, "universal_issue_state/v1/issue_spine/issue_spine.parquet"))
    if spine.metadata.num_rows != config["expected_counts"]["issue_states"]:
        raise ContractError("issue spine footer row count changed")
    return {"schema_version": "R14_TABULAR_T01_PREFLIGHT_V1",
            "status": "READY_FOR_OWNER_T01" if evidence["status"] == "STRUCTURALLY_PRESENT" else "EVIDENCE_GAPS",
            "network_requests_made": 0, "model_fits_performed": 0, "holdout_value_pages_read": 0,
            "planned_input_bindings": len(inventory["files"]),
            "adopted_truth_files": read_json(inside(project, ADOPTION))["file_count"],
            "hashing_is_owner_run": True, "holdout_evidence_status": evidence["status"],
            "missing_holdout_audit_dates": evidence["missing_audit_dates"],
            "input_inventory_sha256": digest(inventory), "code_identity_sha256": digest(code_identity(experiment)),
            "expected_counts": config["expected_counts"], "runtime_isolation": isolation_check(experiment)}


def hash_input(project, entry, check_pause=lambda: None):
    path = inside(project, entry["path"])
    check_pause()
    if entry["kind"] == "file":
        actual = hash_file(path)
    else:
        items = []
        for p in sorted(path.rglob("*")):
            relative = p.relative_to(path)
            if any(part in TRANSIENT for part in relative.parts):
                continue
            check_pause()
            inside(project, p.relative_to(project))
            if p.is_file():
                items.append({"path": relative.as_posix(), "size_bytes": p.stat().st_size, "sha256": hash_file(p)})
        actual = digest(items)
    if actual != entry["sha256"]:
        raise ContractError(f"frozen input SHA-256 mismatch: {entry['path']}")
    return actual


def _publish(experiment, relative, value, schema=None):
    if schema:
        check_document(experiment, schema, value)
    atomic_json(inside(experiment, relative), value, immutable=True)
    return hash_file(inside(experiment, relative))


def run_t01(project, experiment, run_id):
    run_dir = run_path(experiment, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = inside(experiment, "runs/T01_RUNNING.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ContractError("a T01 lock exists; inspect status, then use recover-t01-lock only after its process has stopped") from exc
    with os.fdopen(fd, "w") as stream:
        stream.write(canonical({"pid": os.getpid(), "run_id": run_id}).decode())
    state = {"schema_version": "R14_TABULAR_T01_RUN_V1", "run_id": run_id,
             "status": "RUNNING", "pid": os.getpid(), "completed_inputs": 0, "total_inputs": 0,
             "phase": "PREFLIGHT", "current_input": None, "active_seconds": 0.0,
             "updated_at_utc": utc_now(), "message": None}
    start = time.monotonic()
    previous_active = 0.0

    def update(**fields):
        state.update(fields)
        state.update(updated_at_utc=utc_now(), active_seconds=previous_active + time.monotonic() - start)
        check_document(experiment, "run_state", state)
        atomic_json(run_path(experiment, run_id, "state.json"), state)

    def check_pause():
        if run_path(experiment, run_id, "pause.request.json").exists():
            raise PauseRequested()

    try:
        if inside(experiment, PASS_REL).exists():
            result = validate_t01(project, experiment, deep=False)
            update(status="PASS", phase="COMPLETE", pid=None)
            return result
        old_state_path = run_path(experiment, run_id, "state.json")
        if old_state_path.exists():
            previous_active = read_json(old_state_path).get("active_seconds", 0.0)
        update()
        ready = preflight(project, experiment)
        if ready["status"] != "READY_FOR_OWNER_T01":
            raise ContractError("holdout structural evidence gaps; no automatic reacquisition or truth promotion")
        config = load_config(project, experiment)
        records = authorities(project, config)
        inventory = input_inventory(project, config, records)
        identity = {"code_identity": code_identity(experiment), "input_inventory_sha256": digest(inventory),
                    "predecessor_records": {p: r["record_sha256"] for p, r in records.items()}}
        identity_path = run_path(experiment, run_id, "identity.json")
        if identity_path.exists() and read_json(identity_path) != identity:
            raise ContractError("resume code/config/input authority differs from the original run")
        atomic_json(identity_path, identity, immutable=True)
        files = inventory["files"]
        update(total_inputs=len(files), phase="VERIFY_INPUT_HASHES")
        for start_index in range(0, len(files), 128):
            check_pause()
            chunk = files[start_index:start_index + 128]
            cp = run_path(experiment, run_id, f"checkpoints/hash-{start_index:05d}.json")
            if cp.exists():
                receipt = verify_record(read_json(cp))
                if receipt.get("files") != chunk or receipt.get("identity_sha256") != digest(identity):
                    raise ContractError("hash checkpoint authority mismatch")
            # Reverify completed chunks on resume: no trust in stale timestamps.
            for offset, entry in enumerate(chunk):
                check_pause()
                if offset % 16 == 0:
                    update(current_input=entry["path"], completed_inputs=start_index + offset)
                hash_input(project, entry, check_pause)
            if not cp.exists():
                atomic_json(cp, signed({"schema_version": "R14_TABULAR_T01_HASH_CHECKPOINT_V1",
                                       "identity_sha256": digest(identity), "files": chunk}), immutable=True)
            update(completed_inputs=start_index + len(chunk))
        check_pause()
        update(phase="BUILD_TRUSTED_OVERLAYS", current_input=None)
        trusted = trusted_rows(project)
        evidence = evidence_inventory(project)
        exposure = {"schema_version": "R14_TABULAR_EXPOSURE_V1", "prior_exposure_source": EXPOSURE,
                    "prior_exposure_source_sha256": hash_file(inside(project, EXPOSURE)),
                    "prior_exposure_disclosure": read_json(inside(project, EXPOSURE)),
                    "t01_new_holdout_values_read": False,
                    "claim": "Reserved rolling evaluation for this recipe, not historically untouched outcomes.",
                    "checkpoint_historical_deployability_claimed": False}
        artifact_hashes = {}
        artifacts = [
            ("inputs/input_inventory.json", inventory, "input_inventory"),
            ("inputs/date_roles.json", date_overlay(), "date_roles"),
            ("inputs/truth/trusted_labels.json", {"schema_version": "R14_TABULAR_TRUSTED_LABELS_V1", "rows": trusted}, "trusted_labels"),
            ("inputs/truth/holdout_evidence_inventory.json", evidence, "holdout_evidence"),
            ("inputs/exposure_ledger.json", exposure, "exposure"),
            ("inputs/truth/adapter_contract.json", {
                "schema_version": "R14_TABULAR_TRUTH_ADAPTER_V1", "holdout_access": "CLOSED",
                "training_cutoff": "target_date < update_date - 7 calendar days",
                "query_truth_requires_committed_forecast": True, "truth_imputation": False,
                "additional_five_days": "TRUSTED_VERBATIM_NO_MATURITY_WAIT",
                "future_holdout_audit": "CLI_AND_CF6_UNANIMITY_OR_EXACT_FROZEN_GUARDED_EXCEPTION",
                "content_audit_deferred_until": "T04_RECIPE_LOCK_AND_OWNER_T05_REPLAY"}, "truth_adapter")]
        for rel, value, schema in artifacts:
            check_pause()
            artifact_hashes[rel] = _publish(experiment, rel, value, schema)
        # Verify value-bearing source files again after reading, to catch changes
        # during normalization. Other inputs are hashed once in this owner run.
        by_path = {e["path"]: e for e in files}
        for rel in [DEV_LEDGER, TAIL_LEDGER, CATALOG]:
            hash_input(project, by_path[rel], check_pause)
        if code_identity(experiment) != identity["code_identity"]:
            raise ContractError("implementation changed during T01")
        counts = {"trusted_rows": len(trusted), "development_labels": sum(r["y_audited_f"] is not None for r in trusted if r["target_date"] <= "2025-09-06"),
                  "development_unresolved": sum(r["y_audited_f"] is None for r in trusted),
                  "additional_trusted_labels": 5, "holdout_days": 365}
        result = signed({"schema_version": "R14_TABULAR_T01_PASS_V1", "stage_id": "T01", "status": "PASS",
                         "run_id": run_id, "completed_at_utc": utc_now(),
                         "predecessor_records": identity["predecessor_records"],
                         "code_identity": identity["code_identity"], "artifact_hashes": artifact_hashes,
                         "gate_evidence": {**counts, "input_bindings_hashed": len(files), "holdout_value_pages_read": 0,
                                           "network_requests_made": 0, "model_fits_performed": 0,
                                           "holdout_content_audit_performed": False, "runtime_isolation": isolation_check(experiment)}})
        check_pause()
        check_document(experiment, "pass", result)
        atomic_json(inside(experiment, PASS_REL), result, immutable=True)
        update(status="PASS", phase="COMPLETE", pid=None, current_input=None)
        return {"status": "PASS", "stage": "T01", "record_sha256": result["record_sha256"],
                "pass_path": PASS_REL, "gate_evidence": result["gate_evidence"]}
    except PauseRequested:
        update(status="PAUSED", pid=None, message="paused before publication boundary")
        return {"status": "PAUSED", "run_id": run_id}
    except Exception as exc:
        update(status="FAILED", pid=None, message=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        lock.unlink(missing_ok=True)


def validate_t01(project, experiment, *, deep=False):
    config = load_config(project, experiment)
    records = authorities(project, config)
    result = verify_record(read_json(inside(experiment, PASS_REL)))
    check_document(experiment, "pass", result)
    if result["code_identity"] != code_identity(experiment):
        raise ContractError("T01 implementation/config changed after PASS")
    if result["predecessor_records"] != {p: r["record_sha256"] for p, r in records.items()}:
        raise ContractError("predecessor changed after T01")
    schemas = {"inputs/input_inventory.json": "input_inventory", "inputs/date_roles.json": "date_roles",
               "inputs/truth/trusted_labels.json": "trusted_labels", "inputs/truth/holdout_evidence_inventory.json": "holdout_evidence",
               "inputs/exposure_ledger.json": "exposure", "inputs/truth/adapter_contract.json": "truth_adapter"}
    if set(result["artifact_hashes"]) != set(schemas):
        raise ContractError("PASS artifact list differs from the required T01 outputs")
    for rel, expected in result["artifact_hashes"].items():
        if hash_file(inside(experiment, rel)) != expected:
            raise ContractError(f"T01 artifact changed: {rel}")
        check_document(experiment, schemas[rel], read_json(inside(experiment, rel)))
    stored = read_json(inside(experiment, "inputs/input_inventory.json"))
    current = input_inventory(project, config, records)
    if stored != current:
        raise ContractError("bound input inventory changed after T01")
    if read_json(inside(experiment, "inputs/date_roles.json")) != date_overlay():
        raise ContractError("date overlay no longer matches deterministic enumeration")
    checked = 0
    if deep:
        for entry in stored["files"]:
            hash_input(project, entry)
            checked += 1
    return {"status": "VALID", "validated_stage": "T01", "record_sha256": result["record_sha256"],
            "validation_mode": "DEEP_INPUT_BYTES" if deep else "RECEIPTS_OVERLAYS_AND_INPUT_METADATA",
            "original_input_bindings_rehashed": checked,
            "holdout_value_pages_read": 0, "network_requests_made": 0, "model_fits_performed": 0}
