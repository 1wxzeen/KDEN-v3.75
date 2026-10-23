"""P02: adopt audited KDEN truth and extend it through the R14 endpoint."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import time
import urllib.parse
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

import pyarrow.parquet as pq
import requests

from ..contracts import (
    ContractError,
    ExclusiveRunLock,
    PauseController,
    PauseRequested,
    StaleStateError,
    load_project_paths,
    validate_runtime_isolation,
)
from ..hashes import TRANSIENT_NAMES, directory_manifest, sha256_file, sha256_path
from ..io.atomic import atomic_write_bytes, atomic_write_json, fsync_directory
from .p01_foundation import STAGE5R_SOURCE_HASHES, TRUTH_RELEASE_ID, verify_p01
from .p02_rules import (
    TruthRuleError,
    catalog_schema,
    evaluate_audit_document,
    parquet_bytes,
    parse_audit_payload,
    tail_event_schema,
    tail_truth_schema,
    validate_archive_payload,
)
from .records import (
    make_prefit_run_id,
    publish_immutable_json,
    utc_now,
    validate_prefit_run_id,
    verify_prefit_pass,
    write_prefit_pass,
)


STAGE_NO = 2
P02_CONFIG_PATH = "config/prefit/p02_truth_v375.json"
CATALOG_SCHEMA_PATH = "schemas/prefit/truth_catalog_v375.json"
ADOPTION_SCHEMA_PATH = "schemas/prefit/truth_adoption_manifest_v375.json"
RUN_SCHEMA_PATH = "schemas/prefit/p02_run_state_v375.json"
RUNBOOK_PATH = "reports/prefit/P02_OWNER_RUNBOOK.md"
TRUTH_ROOT = "truth/kden_tmax/v1"
ADOPTION_MANIFEST_PATH = f"{TRUTH_ROOT}/adopted_stage5r1/adoption_manifest.json"
TAIL_ROOT = f"{TRUTH_ROOT}/tail_2026-09-07_2026-09-11"
TAIL_TRUTH_PATH = f"{TAIL_ROOT}/normalized/kden_truth_tail.parquet"
TAIL_EVENTS_PATH = f"{TAIL_ROOT}/normalized/kden_truth_tail_events.parquet"
TAIL_MANIFEST_PATH = f"{TAIL_ROOT}/manifest/manifest.json"
CATALOG_PATH = f"{TRUTH_ROOT}/catalog/kden_truth_catalog.parquet"
CATALOG_MANIFEST_PATH = f"{TRUTH_ROOT}/catalog/manifest.json"
COVERAGE_REPORT_PATH = f"{TRUTH_ROOT}/reports/P02_TRUTH_COVERAGE_QC.md"
PASS_PATH = "state/PREFIT_P02_PASS.json"

RUN_STATE_SCHEMA = "KDEN_V375_PREFIT_P02_RUN_V1"
ADOPTION_SCHEMA = "KDEN_V375_TRUTH_ADOPTION_MANIFEST_V1"
TAIL_MANIFEST_SCHEMA = "KDEN_V375_TRUTH_TAIL_MANIFEST_V1"
CATALOG_MANIFEST_SCHEMA = "KDEN_V375_TRUTH_CATALOG_MANIFEST_V1"

DEVELOPMENT_START = date(2021, 1, 1)
DEVELOPMENT_END = date(2025, 9, 6)
HOLDOUT_START = date(2025, 9, 7)
HOLDOUT_END = date(2026, 9, 6)
TAIL_START = date(2026, 9, 7)
TAIL_END = date(2026, 9, 11)
STUDY_START = DEVELOPMENT_START
STUDY_END = TAIL_END

KNOWN_DESTINATIONS = {
    "configs/stage5r_truth_v1.toml": (
        f"{TRUTH_ROOT}/adopted_stage5r1/protocol/stage5r_truth_v1.toml"
    ),
    "configs/stage5r_truth_exceptions_v1.csv": (
        f"{TRUTH_ROOT}/adopted_stage5r1/protocol/stage5r_truth_exceptions_v1.csv"
    ),
    "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_ledger.parquet": (
        f"{TRUTH_ROOT}/adopted_stage5r1/development/kden_truth_ledger.parquet"
    ),
    "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_events.parquet": (
        f"{TRUTH_ROOT}/adopted_stage5r1/development/kden_truth_events.parquet"
    ),
    "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_review_queue.parquet": (
        f"{TRUTH_ROOT}/adopted_stage5r1/development/kden_truth_review_queue.parquet"
    ),
    "data/sealed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "kden_truth_mechanical_candidates.parquet": (
        f"{TRUTH_ROOT}/adopted_stage5r1/sealed_holdout/"
        "kden_truth_mechanical_candidates.parquet"
    ),
    "manifests/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
    "run=stage5r1-build-20260911T081406Z-e1bd6f97f4/manifest.json": (
        f"{TRUTH_ROOT}/adopted_stage5r1/source_manifest/manifest.json"
    ),
}

EVIDENCE_ROOTS = {
    "data/raw/stage5r/kden_truth/protocol=1.0.0": (
        f"{TRUTH_ROOT}/adopted_stage5r1/source_evidence/development"
    ),
    "data/sealed/stage5r/kden_truth/protocol=1.0.0": (
        f"{TRUTH_ROOT}/adopted_stage5r1/source_evidence/sealed"
    ),
}


@dataclass(frozen=True, slots=True)
class CopyItem:
    source_relative_path: str
    destination_relative_path: str
    size_bytes: int
    expected_sha256: str | None


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ContractError(f"JSON object expected: {path}")
    return value


def _inside(root: Path, relative: str | Path) -> Path:
    candidate = (root / Path(relative)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"path escapes project root: {relative}") from exc
    return candidate


def _inclusive_dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=index) for index in range((end - start).days + 1))


def _load_config(project_root: Path) -> dict[str, Any]:
    config = _read_json(project_root / P02_CONFIG_PATH)
    if config.get("schema_version") != "KDEN_V375_PREFIT_P02_CONFIG_V1":
        raise ContractError("unsupported P02 configuration schema")
    if config.get("truth_release_id") != TRUTH_RELEASE_ID:
        raise ContractError("P02 truth release identity disagrees with P01")
    configured_hashes = config.get("authorized_source_hashes")
    if configured_hashes != dict(sorted(STAGE5R_SOURCE_HASHES.items())):
        raise ContractError("P02 source hashes disagree with the frozen P01 authority")
    return config


def _source_inventory(source_root: Path) -> tuple[CopyItem, ...]:
    if not source_root.is_dir():
        raise ContractError(f"truth migration source is not a directory: {source_root}")
    items: list[CopyItem] = []
    for source_relative, destination_relative in KNOWN_DESTINATIONS.items():
        source = _inside(source_root, source_relative)
        if not source.is_file() or source.is_symlink():
            raise ContractError(f"required migration source is missing or unsafe: {source_relative}")
        items.append(
            CopyItem(
                source_relative,
                destination_relative,
                source.stat().st_size,
                STAGE5R_SOURCE_HASHES[source_relative],
            )
        )
    for source_base_relative, destination_base_relative in EVIDENCE_ROOTS.items():
        source_base = _inside(source_root, source_base_relative)
        if not source_base.is_dir() or source_base.is_symlink():
            raise ContractError(f"required source-evidence root is missing: {source_base_relative}")
        for source in sorted(source_base.rglob("*")):
            if source.is_symlink():
                raise ContractError(f"source-evidence symlink is forbidden: {source}")
            if not source.is_file():
                continue
            relative_below = source.relative_to(source_base)
            if any(part in TRANSIENT_NAMES for part in relative_below.parts):
                continue
            source_relative = (Path(source_base_relative) / relative_below).as_posix()
            destination_relative = (
                Path(destination_base_relative) / relative_below
            ).as_posix()
            items.append(
                CopyItem(
                    source_relative,
                    destination_relative,
                    source.stat().st_size,
                    None,
                )
            )
    items.sort(key=lambda item: item.destination_relative_path)
    destinations = [item.destination_relative_path for item in items]
    if len(destinations) != len(set(destinations)):
        raise ContractError("P02 migration inventory has duplicate destinations")
    return tuple(items)


def _verify_known_source_hashes(source_root: Path) -> dict[str, str]:
    verified: dict[str, str] = {}
    for relative, expected in sorted(STAGE5R_SOURCE_HASHES.items()):
        actual = sha256_file(_inside(source_root, relative))
        if actual != expected:
            raise StaleStateError(f"authorized migration source hash mismatch: {relative}")
        verified[relative] = actual
    return verified


def _command_prefix() -> str:
    return ".venv/bin/python -m kden_v375.prefit.cli"


def p02_preflight(project_root: Path | str, source_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source = Path(source_root).expanduser().resolve()
    p01 = verify_p01(root)
    _load_config(root)
    verified = _verify_known_source_hashes(source)
    inventory = _source_inventory(source)
    total_bytes = sum(item.size_bytes for item in inventory)
    available = shutil.disk_usage(root).free
    required = int(total_bytes * 1.25)
    if available < required:
        raise ContractError(
            f"insufficient free space: need {required} bytes with margin, have {available}"
        )
    run_id = make_prefit_run_id(2, "owner-full", "truth-adoption")
    quoted_source = shlex.quote(str(source))
    prefix = _command_prefix()
    return {
        "schema_version": "KDEN_V375_PREFIT_P02_PREFLIGHT_V1",
        "status": "READY_FOR_OWNER_P02",
        "network_requests_made": 0,
        "predecessor_record_sha256": p01["record_sha256"],
        "known_source_hashes_verified": len(verified),
        "copy_file_count": len(inventory),
        "copy_bytes": total_bytes,
        "disk": {
            "available_bytes_now": available,
            "required_bytes_with_25_percent_margin": required,
            "pass": True,
        },
        "tail_network_task_count": 7,
        "truth_package_directory": TRUTH_ROOT,
        "suggested_run_id": run_id,
        "start_command": (
            f"{prefix} run-p02 --source-root {quoted_source} --run-id {run_id}"
        ),
        "status_command": f"{prefix} p02-status --run-id {run_id}",
        "live_status_command": (
            f"{prefix} p02-live-status --run-id {run_id} --interval-seconds 5"
        ),
        "eta_command": f"{prefix} p02-eta --run-id {run_id}",
        "pause_command": f"{prefix} p02-pause --run-id {run_id}",
        "resume_command": (
            f"{prefix} resume-p02 --source-root {quoted_source} --run-id {run_id}"
        ),
        "validation_command": f"{prefix} validate-p02",
    }


def _run_paths(project_root: Path, run_id: str) -> dict[str, Path]:
    base = _inside(project_root, Path("prefit_runs") / run_id / "p02")
    return {
        "base": base,
        "state": base / "run.json",
        "pause": base / "control/pause.requested.json",
    }


def _write_run_state(path: Path, state: Mapping[str, Any]) -> None:
    atomic_write_json(path, dict(state), replace=True)


def _initialize_run_state(
    project_root: Path, run_id: str, inventory: tuple[CopyItem, ...]
) -> dict[str, Any]:
    validate_prefit_run_id(run_id, stage_no=2, scope="owner-full")
    paths = _run_paths(project_root, run_id)
    if paths["state"].is_file():
        state = _read_json(paths["state"])
        if state.get("schema_version") != RUN_STATE_SCHEMA or state.get("run_id") != run_id:
            raise StaleStateError("P02 run-state identity mismatch")
        if state.get("expected_copy_files") != len(inventory) or state.get(
            "expected_copy_bytes"
        ) != sum(item.size_bytes for item in inventory):
            raise StaleStateError("P02 source inventory changed since run creation")
        return state
    created = utc_now()
    state = {
        "schema_version": RUN_STATE_SCHEMA,
        "stage_id": "PREFIT_P02",
        "run_id": run_id,
        "status": "INITIALIZED",
        "phase": "NOT_STARTED",
        "message": "initialized",
        "created_at_utc": created,
        "started_at_utc": None,
        "updated_at_utc": created,
        "source_package_id": "KDEN_STAGE5R1_TRUTH_PROTOCOL_1_0_0",
        "expected_copy_files": len(inventory),
        "completed_copy_files": 0,
        "expected_copy_bytes": sum(item.size_bytes for item in inventory),
        "completed_copy_bytes": 0,
        "expected_network_tasks": 7,
        "completed_network_tasks": 0,
        "current_item": None,
        "normalization_cutoff_utc": None,
    }
    _write_run_state(paths["state"], state)
    return state


def _update_run_state(project_root: Path, run_id: str, **updates: Any) -> dict[str, Any]:
    path = _run_paths(project_root, run_id)["state"]
    state = _read_json(path)
    state.update(updates, updated_at_utc=utc_now())
    _write_run_state(path, state)
    return state


def _atomic_copy_verified(
    source: Path, destination: Path, expected_sha256: str | None
) -> str:
    source_hash = sha256_file(source)
    if expected_sha256 is not None and source_hash != expected_sha256:
        raise StaleStateError(f"migration source hash mismatch: {source.name}")
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != source_hash:
            raise StaleStateError(f"immutable P02 destination differs: {destination}")
        return source_hash
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if sha256_file(temporary) != source_hash:
            raise StaleStateError(f"copied bytes failed verification: {destination}")
        if destination.exists():
            if sha256_file(destination) != source_hash:
                raise StaleStateError(f"immutable P02 destination differs: {destination}")
            temporary.unlink()
        else:
            os.replace(temporary, destination)
            fsync_directory(destination.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return source_hash


def _copy_adopted_package(
    *,
    project_root: Path,
    source_root: Path,
    run_id: str,
    inventory: tuple[CopyItem, ...],
    pause: PauseController,
) -> dict[str, Any]:
    _update_run_state(
        project_root,
        run_id,
        phase="COPY_ADOPTED_PACKAGE",
        completed_copy_files=0,
        completed_copy_bytes=0,
        current_item=None,
        message="copying and hash-verifying source evidence",
    )
    entries: list[dict[str, Any]] = []
    copied_bytes = 0
    last_publish = time.monotonic()
    for ordinal, item in enumerate(inventory, start=1):
        pause.raise_if_requested()
        source = _inside(source_root, item.source_relative_path)
        destination = _inside(project_root, item.destination_relative_path)
        digest = _atomic_copy_verified(source, destination, item.expected_sha256)
        entries.append(
            {
                "source_relative_path": item.source_relative_path,
                "destination_relative_path": item.destination_relative_path,
                "size_bytes": item.size_bytes,
                "sha256": digest,
            }
        )
        copied_bytes += item.size_bytes
        if ordinal == len(inventory) or ordinal % 20 == 0 or time.monotonic() - last_publish >= 1:
            _update_run_state(
                project_root,
                run_id,
                completed_copy_files=ordinal,
                completed_copy_bytes=copied_bytes,
                current_item=item.destination_relative_path,
            )
            last_publish = time.monotonic()
    state = _read_json(_run_paths(project_root, run_id)["state"])
    manifest = {
        "schema_version": ADOPTION_SCHEMA,
        "truth_release_id": TRUTH_RELEASE_ID,
        "source_package_id": state["source_package_id"],
        "adopted_at_utc": state["created_at_utc"],
        "copy_policy": "byte_identical_immutable_copy",
        "absolute_source_paths_persisted": False,
        "file_count": len(entries),
        "total_bytes": copied_bytes,
        "files": entries,
    }
    publish_immutable_json(project_root / ADOPTION_MANIFEST_PATH, manifest)
    return manifest


def _tail_audit_path(project_root: Path, target: date) -> Path:
    return (
        project_root
        / TAIL_ROOT
        / "source_evidence/audit"
        / f"year={target.year}"
        / f"date={target.isoformat()}"
        / "audit.json"
    )


def _tail_archive_dir(project_root: Path, pil: str) -> Path:
    return project_root / TAIL_ROOT / "source_evidence/afos" / f"pil={pil}" / "year=2026"


def _audit_url(config: Mapping[str, Any], target: date) -> str:
    return str(config["source"]["audit_url_template"]).format(
        date=urllib.parse.quote(target.isoformat())
    )


def _archive_url(config: Mapping[str, Any], pil: str) -> str:
    return str(config["source"]["afos_url_template"]).format(
        pil=urllib.parse.quote(pil), start="2026-01-01", end="2027-01-01"
    )


def _fetch(
    session: requests.Session,
    *,
    url: str,
    accept: str,
    config: Mapping[str, Any],
) -> tuple[bytes | None, requests.Response, int]:
    acquisition = config["acquisition"]
    retries = int(acquisition["retries"])
    backoff = float(acquisition["backoff_seconds"])
    error: BaseException | None = None
    response: requests.Response | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(
                url,
                headers={
                    "User-Agent": str(acquisition["user_agent"]),
                    "Accept": accept,
                    "Cache-Control": "no-cache",
                },
                timeout=(
                    float(acquisition["connect_timeout_seconds"]),
                    float(acquisition["read_timeout_seconds"]),
                ),
            )
            if response.status_code == 200 and response.content:
                return response.content, response, attempt + 1
            if response.status_code in {204, 404, 410}:
                return None, response, attempt + 1
            retryable = response.status_code in {408, 429} or response.status_code >= 500
            error = ContractError(f"HTTP {response.status_code} for {url}")
            if not retryable:
                break
        except requests.RequestException as exc:
            error = exc
        if attempt < retries:
            time.sleep(backoff * (2**attempt))
    if response is not None:
        raise ContractError(f"source retrieval failed for {url}: {error}")
    raise ContractError(f"source transport failed for {url}: {error}")


def _valid_cached_audit(
    project_root: Path, config: Mapping[str, Any], target: date
) -> bool:
    payload_path = _tail_audit_path(project_root, target)
    meta_path = payload_path.with_name("audit.meta.json")
    if not payload_path.is_file() or not meta_path.is_file():
        return False
    try:
        payload = payload_path.read_bytes()
        meta = _read_json(meta_path)
        parse_audit_payload(payload, target)
    except (OSError, ContractError, TruthRuleError):
        return False
    return (
        meta.get("source_url") == _audit_url(config, target)
        and meta.get("sha256") == sha256_file(payload_path)
    )


def _valid_cached_archive(project_root: Path, config: Mapping[str, Any], pil: str) -> bool:
    base = _tail_archive_dir(project_root, pil)
    payload_path = base / "products.zip"
    meta_path = base / "products.meta.json"
    index_path = base / "product_index.json"
    if not all(path.is_file() for path in (payload_path, meta_path, index_path)):
        return False
    try:
        payload = payload_path.read_bytes()
        expected_index = validate_archive_payload(payload, pil=pil, year=2026)
        meta = _read_json(meta_path)
        index = _read_json(index_path)
    except (OSError, ContractError, TruthRuleError):
        return False
    return (
        meta.get("source_url") == _archive_url(config, pil)
        and meta.get("sha256") == sha256_file(payload_path)
        and index == expected_index
    )


def _unavailable_marker(path: Path, source_url: str) -> bool:
    if not path.is_file():
        return False
    try:
        value = _read_json(path)
    except (OSError, ContractError):
        return False
    return value.get("source_url") == source_url and value.get("status") == "SOURCE_UNAVAILABLE"


def _download_archive(
    session: requests.Session,
    project_root: Path,
    config: Mapping[str, Any],
    pil: str,
) -> dict[str, Any]:
    base = _tail_archive_dir(project_root, pil)
    url = _archive_url(config, pil)
    marker = base / "source_unavailable.json"
    if _valid_cached_archive(project_root, config, pil):
        return {"task": f"archive-{pil}-2026", "status": "CACHED"}
    if _unavailable_marker(marker, url):
        return {"task": f"archive-{pil}-2026", "status": "SOURCE_UNAVAILABLE"}
    payload, response, attempts = _fetch(session, url=url, accept="application/zip", config=config)
    observed = utc_now()
    if payload is None:
        atomic_write_json(
            marker,
            {
                "schema_version": "KDEN_V375_SOURCE_UNAVAILABLE_V1",
                "status": "SOURCE_UNAVAILABLE",
                "source_url": url,
                "observed_at_utc": observed,
                "http_status": response.status_code,
                "attempts": attempts,
            },
            replace=True,
        )
        return {"task": f"archive-{pil}-2026", "status": "SOURCE_UNAVAILABLE"}
    index = validate_archive_payload(payload, pil=pil, year=2026)
    digest = atomic_write_bytes(base / "products.zip", payload, replace=True)
    atomic_write_json(base / "product_index.json", index, replace=True)
    marker.unlink(missing_ok=True)
    atomic_write_json(
        base / "products.meta.json",
        {
            "schema_version": "KDEN_V375_TAIL_SOURCE_META_V1",
            "pil": pil,
            "year": 2026,
            "source_url": url,
            "retrieved_at_utc": observed,
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "bytes": len(payload),
            "sha256": digest,
            "attempts": attempts,
        },
        replace=True,
    )
    return {"task": f"archive-{pil}-2026", "status": "DOWNLOADED"}


def _download_audit(
    session: requests.Session,
    project_root: Path,
    config: Mapping[str, Any],
    target: date,
) -> dict[str, Any]:
    payload_path = _tail_audit_path(project_root, target)
    url = _audit_url(config, target)
    marker = payload_path.with_name("source_unavailable.json")
    if _valid_cached_audit(project_root, config, target):
        return {"task": f"audit-{target.isoformat()}", "status": "CACHED"}
    if _unavailable_marker(marker, url):
        return {"task": f"audit-{target.isoformat()}", "status": "SOURCE_UNAVAILABLE"}
    payload, response, attempts = _fetch(session, url=url, accept="application/json", config=config)
    observed = utc_now()
    if payload is None:
        atomic_write_json(
            marker,
            {
                "schema_version": "KDEN_V375_SOURCE_UNAVAILABLE_V1",
                "status": "SOURCE_UNAVAILABLE",
                "source_url": url,
                "observed_at_utc": observed,
                "http_status": response.status_code,
                "attempts": attempts,
            },
            replace=True,
        )
        return {"task": f"audit-{target.isoformat()}", "status": "SOURCE_UNAVAILABLE"}
    document = parse_audit_payload(payload, target)
    digest = atomic_write_bytes(payload_path, payload, replace=True)
    marker.unlink(missing_ok=True)
    atomic_write_json(
        payload_path.with_name("audit.meta.json"),
        {
            "schema_version": "KDEN_V375_TAIL_SOURCE_META_V1",
            "target_date": target.isoformat(),
            "source_url": url,
            "retrieved_at_utc": observed,
            "generated_at": document.get("generated_at"),
            "http_status": response.status_code,
            "content_type": response.headers.get("content-type"),
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "bytes": len(payload),
            "sha256": digest,
            "attempts": attempts,
        },
        replace=True,
    )
    return {"task": f"audit-{target.isoformat()}", "status": "DOWNLOADED"}


def _acquire_tail(
    *,
    project_root: Path,
    run_id: str,
    config: Mapping[str, Any],
    pause: PauseController,
) -> list[dict[str, Any]]:
    _update_run_state(
        project_root,
        run_id,
        phase="ACQUIRE_FIVE_DAY_TAIL",
        completed_network_tasks=0,
        current_item=None,
        message="acquiring current CLI/CF6 evidence for five tail dates",
    )
    tasks: list[tuple[str, str | date]] = [
        ("archive", str(config["source"]["cli_pil"])),
        ("archive", str(config["source"]["cf6_pil"])),
        *(("audit", target) for target in _inclusive_dates(TAIL_START, TAIL_END)),
    ]
    results: list[dict[str, Any]] = []
    with requests.Session() as session:
        for ordinal, (kind, identity) in enumerate(tasks, start=1):
            pause.raise_if_requested()
            if kind == "archive":
                result = _download_archive(session, project_root, config, str(identity))
            else:
                if not isinstance(identity, date):  # pragma: no cover
                    raise ContractError("invalid P02 audit task")
                result = _download_audit(session, project_root, config, identity)
            results.append(result)
            _update_run_state(
                project_root,
                run_id,
                completed_network_tasks=ordinal,
                current_item=result["task"],
            )
    return results


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ContractError(f"timestamp lacks timezone: {value!r}")
    return parsed.astimezone(UTC)


def _source_file_rows(project_root: Path, relative_root: str) -> list[dict[str, Any]]:
    base = project_root / relative_root
    return [
        {
            "path": (Path(relative_root) / row["path"]).as_posix(),
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
        }
        for row in directory_manifest(base)
    ]


def _build_tail_outputs(project_root: Path, run_id: str) -> dict[str, Any]:
    state_path = _run_paths(project_root, run_id)["state"]
    state = _read_json(state_path)
    cutoff_text = state.get("normalization_cutoff_utc")
    if not cutoff_text:
        cutoff_text = utc_now()
        state["normalization_cutoff_utc"] = cutoff_text
        state["updated_at_utc"] = utc_now()
        _write_run_state(state_path, state)
    cutoff = _parse_utc(str(cutoff_text))
    _update_run_state(
        project_root,
        run_id,
        phase="NORMALIZE_FIVE_DAY_TAIL",
        current_item=None,
        message="applying frozen CLI/CF6 audit rules",
    )
    product_ids: set[str] = set()
    for pil in ("CLIDEN", "CF6DEN"):
        index_path = _tail_archive_dir(project_root, pil) / "product_index.json"
        if index_path.is_file():
            product_ids.update(str(value) for value in _read_json(index_path)["product_ids"])

    rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    retrieval_times: list[str] = []
    for target in _inclusive_dates(TAIL_START, TAIL_END):
        payload_path = _tail_audit_path(project_root, target)
        marker_path = payload_path.with_name("source_unavailable.json")
        followup_close = datetime.combine(
            target + timedelta(days=62), wall_time(7), tzinfo=UTC
        )
        followup_open = cutoff < followup_close
        if marker_path.is_file() and not payload_path.is_file():
            marker = _read_json(marker_path)
            retrieved = _parse_utc(str(marker["observed_at_utc"]))
            retrieval_times.append(str(marker["observed_at_utc"]))
            row = {
                "schema_version": "KDEN_V375_TRUTH_AUDIT_V1",
                "target_date": target,
                "station_id": "KDEN",
                "y_audited_f": None,
                "truth_qc_status": "source_unavailable",
                "truth_selection_reason": "authoritative_audit_source_unavailable",
                "exception_rule_id": None,
                "y_cli_first_completed_f": None,
                "cli_first_completed_time_utc": None,
                "cli_first_completed_product_id": None,
                "y_cli_latest_f": None,
                "cli_latest_time_utc": None,
                "cli_latest_product_id": None,
                "y_cf6_first_f": None,
                "cf6_first_time_utc": None,
                "cf6_first_product_id": None,
                "y_cf6_latest_f": None,
                "cf6_latest_time_utc": None,
                "cf6_latest_product_id": None,
                "cli_values_json": "[]",
                "cf6_values_json": "[]",
                "cli_product_ids_json": "[]",
                "cf6_product_ids_json": "[]",
                "eligible_cli_event_count": 0,
                "eligible_cf6_event_count": 0,
                "missing_archived_product_ids_json": "[]",
                "review_flags_json": '["source_unavailable"]',
                "audit_raw_sha256": None,
                "truth_evidence_cutoff_utc": cutoff,
                "source_followup_window_open_at_freeze": followup_open,
                "source_retrieved_at_utc": retrieved,
            }
            rows.append(row)
            continue
        if not payload_path.is_file():
            raise ContractError(f"tail audit evidence is incomplete for {target}")
        payload = payload_path.read_bytes()
        document = parse_audit_payload(payload, target)
        row, events = evaluate_audit_document(
            target=target,
            document=document,
            raw_sha256=sha256_file(payload_path),
            product_ids_available=product_ids,
        )
        meta = _read_json(payload_path.with_name("audit.meta.json"))
        retrieved = _parse_utc(str(meta["retrieved_at_utc"]))
        retrieval_times.append(str(meta["retrieved_at_utc"]))
        row.update(
            truth_evidence_cutoff_utc=cutoff,
            source_followup_window_open_at_freeze=followup_open,
            source_retrieved_at_utc=retrieved,
        )
        rows.append(row)
        event_rows.extend(events)

    truth_payload = parquet_bytes(rows, tail_truth_schema())
    event_payload = parquet_bytes(event_rows, tail_event_schema())
    truth_hash = atomic_write_bytes(project_root / TAIL_TRUTH_PATH, truth_payload, replace=True)
    event_hash = atomic_write_bytes(project_root / TAIL_EVENTS_PATH, event_payload, replace=True)
    source_files = _source_file_rows(project_root, f"{TAIL_ROOT}/source_evidence")
    manifest = {
        "schema_version": TAIL_MANIFEST_SCHEMA,
        "truth_release_id": TRUTH_RELEASE_ID,
        "date_range": {"start": TAIL_START.isoformat(), "end": TAIL_END.isoformat()},
        "date_count": len(rows),
        "truth_evidence_cutoff_utc": cutoff_text,
        "source_retrieval_timestamps": sorted(retrieval_times),
        "source_files": source_files,
        "normalized_artifacts": {
            "truth": {
                "path": TAIL_TRUTH_PATH,
                "rows": len(rows),
                "sha256": truth_hash,
            },
            "events": {
                "path": TAIL_EVENTS_PATH,
                "rows": len(event_rows),
                "sha256": event_hash,
            },
        },
        "status_counts": dict(sorted(Counter(row["truth_qc_status"] for row in rows).items())),
        "pending_maturity_exclusion_applied": False,
        "followup_window_flag_is_metadata_only": True,
    }
    atomic_write_json(project_root / TAIL_MANIFEST_PATH, manifest, replace=True)
    return manifest


def _development_rows(project_root: Path) -> list[dict[str, Any]]:
    ledger_path = project_root / KNOWN_DESTINATIONS[
        "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
        "kden_truth_ledger.parquet"
    ]
    table = pq.read_table(
        ledger_path,
        columns=["target_date", "y_audited_f", "truth_qc_status"],
    )
    selected = [
        row
        for row in table.to_pylist()
        if DEVELOPMENT_START <= row["target_date"] <= DEVELOPMENT_END
    ]
    selected.sort(key=lambda row: row["target_date"])
    expected_dates = list(_inclusive_dates(DEVELOPMENT_START, DEVELOPMENT_END))
    if [row["target_date"] for row in selected] != expected_dates:
        raise ContractError("adopted development ledger does not cover the R14 interval exactly")
    if len(selected) != 1710:
        raise ContractError("adopted development ledger must contribute 1,710 R14 rows")
    audited = sum(row["y_audited_f"] is not None for row in selected)
    if audited != 1707:
        raise ContractError("adopted development ledger must contain 1,707 audited R14 rows")
    return selected


def _verify_sealed_metadata_only(project_root: Path) -> str:
    source_relative = (
        "data/sealed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
        "kden_truth_mechanical_candidates.parquet"
    )
    sealed_path = project_root / KNOWN_DESTINATIONS[source_relative]
    if sha256_file(sealed_path) != STAGE5R_SOURCE_HASHES[source_relative]:
        raise StaleStateError("sealed holdout copy hash mismatch")
    parquet_file = pq.ParquetFile(sealed_path)
    if parquet_file.metadata.num_rows != 365:
        raise ContractError("sealed holdout metadata must report 365 rows")
    required = {"target_date", "y_audited_f", "truth_qc_status"}
    if not required.issubset(set(parquet_file.schema_arrow.names)):
        raise ContractError("sealed holdout Parquet schema is incomplete")
    return STAGE5R_SOURCE_HASHES[source_relative]


def _build_catalog(project_root: Path, run_id: str) -> dict[str, Any]:
    _update_run_state(
        project_root,
        run_id,
        phase="BUILD_TRUTH_CATALOG",
        current_item=CATALOG_PATH,
        message="building one explicit evidence-status row per R14 target day",
    )
    development = _development_rows(project_root)
    sealed_hash = _verify_sealed_metadata_only(project_root)
    tail_table = pq.read_table(project_root / TAIL_TRUTH_PATH)
    tail = sorted(tail_table.to_pylist(), key=lambda row: row["target_date"])
    if [row["target_date"] for row in tail] != list(_inclusive_dates(TAIL_START, TAIL_END)):
        raise ContractError("tail truth artifact must cover exactly five R14 dates")

    ledger_source = (
        "data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
        "kden_truth_ledger.parquet"
    )
    ledger_destination = KNOWN_DESTINATIONS[ledger_source]
    ledger_hash = STAGE5R_SOURCE_HASHES[ledger_source]
    rows: list[dict[str, Any]] = []
    for source in development:
        audited = source["y_audited_f"] is not None
        guarded = source["truth_qc_status"] == "audited_guarded_exception"
        rows.append(
            {
                "target_date": source["target_date"],
                "truth_release_id": TRUTH_RELEASE_ID,
                "truth_group": "development",
                "truth_evidence_status": (
                    "audited_guarded_exception" if guarded else "audited" if audited else "unresolved"
                ),
                "label_available_for_supervised_use": audited,
                "label_available_for_final_scoring": False,
                "y_audited_f": source["y_audited_f"],
                "truth_qc_status": source["truth_qc_status"],
                "source_artifact_path": ledger_destination,
                "source_artifact_sha256": ledger_hash,
                "truth_evidence_cutoff_utc": None,
                "source_followup_window_open_at_freeze": None,
                "exclusion_reason": None if audited else "unresolved_truth",
            }
        )
    sealed_destination = KNOWN_DESTINATIONS[
        "data/sealed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/"
        "kden_truth_mechanical_candidates.parquet"
    ]
    for target in _inclusive_dates(HOLDOUT_START, HOLDOUT_END):
        rows.append(
            {
                "target_date": target,
                "truth_release_id": TRUTH_RELEASE_ID,
                "truth_group": "sealed_final_holdout",
                "truth_evidence_status": "sealed_holdout",
                "label_available_for_supervised_use": False,
                "label_available_for_final_scoring": False,
                "y_audited_f": None,
                "truth_qc_status": "sealed_pending_audit",
                "source_artifact_path": sealed_destination,
                "source_artifact_sha256": sealed_hash,
                "truth_evidence_cutoff_utc": None,
                "source_followup_window_open_at_freeze": None,
                "exclusion_reason": "sealed_until_model_and_evaluation_freeze",
            }
        )
    tail_hash = sha256_file(project_root / TAIL_TRUTH_PATH)
    for source in tail:
        audited = source["y_audited_f"] is not None
        source_unavailable = source["truth_qc_status"] == "source_unavailable"
        rows.append(
            {
                "target_date": source["target_date"],
                "truth_release_id": TRUTH_RELEASE_ID,
                "truth_group": "post_holdout_tail",
                "truth_evidence_status": (
                    "tail_audited"
                    if audited
                    else "source_unavailable"
                    if source_unavailable
                    else "tail_unresolved"
                ),
                "label_available_for_supervised_use": False,
                "label_available_for_final_scoring": audited,
                "y_audited_f": source["y_audited_f"],
                "truth_qc_status": source["truth_qc_status"],
                "source_artifact_path": TAIL_TRUTH_PATH,
                "source_artifact_sha256": tail_hash,
                "truth_evidence_cutoff_utc": source["truth_evidence_cutoff_utc"],
                "source_followup_window_open_at_freeze": source[
                    "source_followup_window_open_at_freeze"
                ],
                "exclusion_reason": (
                    None
                    if audited
                    else "source_unavailable"
                    if source_unavailable
                    else "tail_unresolved"
                ),
            }
        )
    rows.sort(key=lambda row: row["target_date"])
    if [row["target_date"] for row in rows] != list(_inclusive_dates(STUDY_START, STUDY_END)):
        raise ContractError("truth catalog must have exactly one ordered row per R14 target date")
    payload = parquet_bytes(rows, catalog_schema())
    catalog_hash = atomic_write_bytes(project_root / CATALOG_PATH, payload, replace=True)
    status_counts = dict(sorted(Counter(row["truth_evidence_status"] for row in rows).items()))
    group_counts = dict(sorted(Counter(row["truth_group"] for row in rows).items()))
    manifest = {
        "schema_version": CATALOG_MANIFEST_SCHEMA,
        "truth_release_id": TRUTH_RELEASE_ID,
        "catalog_path": CATALOG_PATH,
        "catalog_sha256": catalog_hash,
        "schema_path": CATALOG_SCHEMA_PATH,
        "row_count": len(rows),
        "start_date": STUDY_START.isoformat(),
        "end_date": STUDY_END.isoformat(),
        "group_counts": group_counts,
        "status_counts": status_counts,
        "development_supervised_label_count": sum(
            row["label_available_for_supervised_use"] for row in rows
        ),
        "tail_final_scoring_label_count": sum(
            row["truth_group"] == "post_holdout_tail"
            and row["label_available_for_final_scoring"]
            for row in rows
        ),
        "sealed_holdout_values_read": False,
        "sealed_holdout_values_materialized_in_catalog": False,
    }
    atomic_write_json(project_root / CATALOG_MANIFEST_PATH, manifest, replace=True)
    report = f"""# P02 Truth Coverage and QC

Status: complete for `{TRUTH_RELEASE_ID}`

The self-contained truth package lives at `{TRUTH_ROOT}/`.

## Coverage

- R14 target dates: {len(rows)} ({STUDY_START.isoformat()} through {STUDY_END.isoformat()})
- Development dates: {group_counts.get('development', 0)}
- Development labels available for supervised use: {manifest['development_supervised_label_count']}
- Sealed final-holdout dates: {group_counts.get('sealed_final_holdout', 0)}
- Post-holdout tail dates: {group_counts.get('post_holdout_tail', 0)}
- Tail labels available for post-freeze final scoring: {manifest['tail_final_scoring_label_count']}

## Evidence-status counts

```json
{json.dumps(status_counts, indent=2, sort_keys=True)}
```

The 365-day holdout was represented only by its fixed date range and verified
Parquet metadata. Its outcome values were not read or placed in the catalog.
Truth columns remain physically separate from the weather-feature substrate.
"""
    atomic_write_bytes(
        project_root / COVERAGE_REPORT_PATH,
        report.encode("utf-8"),
        replace=True,
    )
    return manifest


def _validate_adoption(project_root: Path, *, deep: bool) -> dict[str, Any]:
    manifest = _read_json(project_root / ADOPTION_MANIFEST_PATH)
    if manifest.get("schema_version") != ADOPTION_SCHEMA:
        raise ContractError("unsupported truth-adoption manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != manifest.get("file_count"):
        raise ContractError("truth-adoption manifest file inventory is invalid")
    absolute_fragments = [
        row
        for row in files
        if Path(str(row.get("source_relative_path", ""))).is_absolute()
        or Path(str(row.get("destination_relative_path", ""))).is_absolute()
    ]
    if absolute_fragments:
        raise ContractError("truth-adoption manifest contains an absolute path")
    for source_relative, expected in STAGE5R_SOURCE_HASHES.items():
        destination = project_root / KNOWN_DESTINATIONS[source_relative]
        if sha256_file(destination) != expected:
            raise StaleStateError(f"adopted authoritative file changed: {source_relative}")
    checked = 0
    if deep:
        for row in files:
            destination = _inside(project_root, str(row["destination_relative_path"]))
            if destination.stat().st_size != int(row["size_bytes"]):
                raise StaleStateError(f"adopted file size changed: {destination}")
            if sha256_file(destination) != row["sha256"]:
                raise StaleStateError(f"adopted file hash changed: {destination}")
            checked += 1
    return {
        "manifest_file_count": len(files),
        "deep_file_hashes_checked": checked,
        "known_authority_hashes_checked": len(STAGE5R_SOURCE_HASHES),
    }


def _validate_catalog(project_root: Path) -> dict[str, Any]:
    manifest = _read_json(project_root / CATALOG_MANIFEST_PATH)
    if manifest.get("schema_version") != CATALOG_MANIFEST_SCHEMA:
        raise ContractError("unsupported truth-catalog manifest schema")
    catalog_path = project_root / CATALOG_PATH
    if sha256_file(catalog_path) != manifest.get("catalog_sha256"):
        raise StaleStateError("truth catalog hash mismatch")
    table = pq.read_table(catalog_path)
    if table.schema != catalog_schema():
        raise ContractError("truth catalog schema mismatch")
    rows = table.to_pylist()
    if len(rows) != 2080:
        raise ContractError("truth catalog must contain 2,080 rows")
    if [row["target_date"] for row in rows] != list(_inclusive_dates(STUDY_START, STUDY_END)):
        raise ContractError("truth catalog date coverage or ordering is invalid")
    holdout = [row for row in rows if row["truth_group"] == "sealed_final_holdout"]
    if len(holdout) != 365 or any(
        row["y_audited_f"] is not None
        or row["label_available_for_supervised_use"]
        or row["label_available_for_final_scoring"]
        for row in holdout
    ):
        raise ContractError("truth catalog violates sealed-holdout policy")
    development = [row for row in rows if row["truth_group"] == "development"]
    if len(development) != 1710 or sum(
        row["label_available_for_supervised_use"] for row in development
    ) != 1707:
        raise ContractError("truth catalog development-label counts are invalid")
    tail = [row for row in rows if row["truth_group"] == "post_holdout_tail"]
    if len(tail) != 5 or any(row["label_available_for_supervised_use"] for row in tail):
        raise ContractError("truth catalog tail role is invalid")
    allowed = {
        "audited",
        "audited_guarded_exception",
        "unresolved",
        "sealed_holdout",
        "tail_audited",
        "tail_unresolved",
        "source_unavailable",
    }
    observed = {row["truth_evidence_status"] for row in rows}
    if not observed.issubset(allowed):
        raise ContractError(f"truth catalog contains unknown evidence statuses: {observed - allowed}")
    return {
        "row_count": len(rows),
        "development_rows": len(development),
        "development_supervised_labels": 1707,
        "sealed_holdout_rows": len(holdout),
        "tail_rows": len(tail),
        "status_counts": dict(
            sorted(Counter(row["truth_evidence_status"] for row in rows).items())
        ),
    }


def _validate_outputs(project_root: Path, *, deep: bool) -> dict[str, Any]:
    p01 = verify_p01(project_root)
    adoption = _validate_adoption(project_root, deep=deep)
    catalog = _validate_catalog(project_root)
    tail_manifest = _read_json(project_root / TAIL_MANIFEST_PATH)
    if tail_manifest.get("schema_version") != TAIL_MANIFEST_SCHEMA:
        raise ContractError("unsupported tail manifest schema")
    for artifact in tail_manifest.get("normalized_artifacts", {}).values():
        path = _inside(project_root, str(artifact["path"]))
        if sha256_file(path) != artifact["sha256"]:
            raise StaleStateError(f"tail normalized artifact hash mismatch: {path}")
    isolation = validate_runtime_isolation(project_root)
    return {
        "predecessor_record_sha256": p01["record_sha256"],
        "adoption": adoption,
        "catalog": catalog,
        "tail_status_counts": tail_manifest["status_counts"],
        "sealed_holdout_values_read": False,
        "runtime_isolation": {
            key: value for key, value in isolation.items() if key != "source_files_scanned"
        },
    }


def run_p02(
    *,
    project_root: Path | str,
    source_root: Path | str,
    run_id: str,
    resume: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source = Path(source_root).expanduser().resolve()
    if (root / PASS_PATH).is_file():
        return verify_p02(root, deep=False)
    verify_p01(root)
    config = _load_config(root)
    _verify_known_source_hashes(source)
    inventory = _source_inventory(source)
    state = _initialize_run_state(root, run_id, inventory)
    resumable = {"PAUSED", "PAUSE_REQUESTED", "FAILED", "INITIALIZED"}
    if resume and state["status"] not in resumable:
        raise ContractError(f"P02 run is not resumable from {state['status']}")
    if not resume and state["status"] not in {"INITIALIZED", "FAILED"}:
        raise ContractError(f"P02 run already exists in {state['status']}; use resume-p02")
    paths = _run_paths(root, run_id)
    pause = PauseController(paths["pause"])
    if resume:
        pause.clear()
    with ExclusiveRunLock(load_project_paths(root).state / "PREFIT_P02.lock"):
        pause.install()
        _update_run_state(
            root,
            run_id,
            status="RUNNING",
            started_at_utc=state.get("started_at_utc") or utc_now(),
            message="resumed" if resume else "started",
        )
        try:
            _copy_adopted_package(
                project_root=root,
                source_root=source,
                run_id=run_id,
                inventory=inventory,
                pause=pause,
            )
            pause.raise_if_requested()
            _acquire_tail(
                project_root=root,
                run_id=run_id,
                config=config,
                pause=pause,
            )
            pause.raise_if_requested()
            _build_tail_outputs(root, run_id)
            pause.raise_if_requested()
            catalog_manifest = _build_catalog(root, run_id)
            pause.raise_if_requested()
            _update_run_state(
                root,
                run_id,
                phase="VALIDATE_AND_SEAL",
                current_item=None,
                message="validating P02 outputs and publishing PASS",
            )
            evidence = _validate_outputs(root, deep=False)
            p01 = verify_p01(root)
            artifact_paths = [
                P02_CONFIG_PATH,
                CATALOG_SCHEMA_PATH,
                ADOPTION_SCHEMA_PATH,
                RUN_SCHEMA_PATH,
                RUNBOOK_PATH,
                "src/kden_v375/prefit/p02_rules.py",
                "src/kden_v375/prefit/p02_truth.py",
                TRUTH_ROOT,
            ]
            record = write_prefit_pass(
                root,
                stage_no=2,
                run_id=run_id,
                artifact_paths=artifact_paths,
                predecessor_hashes={"PREFIT_P01": p01["record_sha256"]},
                authority_hashes={
                    "ADOPTION_MANIFEST": sha256_file(root / ADOPTION_MANIFEST_PATH),
                    "TRUTH_CATALOG": catalog_manifest["catalog_sha256"],
                    "TAIL_MANIFEST": sha256_file(root / TAIL_MANIFEST_PATH),
                },
                gate_evidence={
                    **evidence,
                    "truth_release_id": TRUTH_RELEASE_ID,
                    "network_tail_dates": 5,
                    "pending_maturity_exclusion_applied": False,
                    "truth_and_weather_features_physically_separate": True,
                    "legacy_runtime_dependency_created": False,
                },
            )
        except PauseRequested as exc:
            _update_run_state(
                root,
                run_id,
                status="PAUSED",
                message=str(exc),
            )
            return {"run_id": run_id, "stage_id": "PREFIT_P02", "status": "PAUSED"}
        except Exception as exc:
            _update_run_state(
                root,
                run_id,
                status="FAILED",
                message=f"{type(exc).__name__}: {exc}",
            )
            raise
        else:
            pause.clear()
            _update_run_state(
                root,
                run_id,
                status="PASS",
                phase="COMPLETE",
                message="P02 gate passed",
                current_item=None,
                completed_at_utc=utc_now(),
                record_sha256=record["record_sha256"],
            )
            return record
        finally:
            pause.restore()


def p02_status(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    validate_prefit_run_id(run_id, stage_no=2)
    state = _read_json(_run_paths(root, run_id)["state"])
    return {
        **state,
        "truth_package_directory": TRUTH_ROOT,
        "catalog_path": CATALOG_PATH,
        "eta": p02_eta(root, run_id)["eta"],
    }


def p02_eta(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state = _read_json(_run_paths(root, run_id)["state"])
    eta: dict[str, Any] = {"status": "UNAVAILABLE", "reason": "insufficient progress"}
    if state["status"] == "PASS":
        eta = {"status": "COMPLETE", "remaining_seconds": 0}
    elif state["status"] in {"FAILED", "PAUSED", "PAUSE_REQUESTED"}:
        eta = {"status": "UNAVAILABLE", "reason": f"run is {state['status']}"}
    elif state.get("phase") == "COPY_ADOPTED_PACKAGE" and state.get(
        "completed_copy_bytes", 0
    ):
        started = _parse_utc(str(state["started_at_utc"]))
        elapsed = max(0.001, (datetime.now(UTC) - started).total_seconds())
        rate = state["completed_copy_bytes"] / elapsed
        remaining = max(0, state["expected_copy_bytes"] - state["completed_copy_bytes"])
        eta = {
            "status": "AVAILABLE",
            "basis": "copy_bytes_since_run_start",
            "recent_rate_bytes_per_second": rate,
            "remaining_copy_bytes": remaining,
            "remaining_seconds": remaining / rate if rate else None,
            "note": "network and normalization time are not included",
        }
    elif state.get("phase") == "ACQUIRE_FIVE_DAY_TAIL":
        eta = {
            "status": "UNAVAILABLE",
            "reason": "network tasks have unequal and externally variable cost",
            "remaining_network_tasks": max(
                0,
                state["expected_network_tasks"] - state["completed_network_tasks"],
            ),
        }
    return {
        "schema_version": "KDEN_V375_PREFIT_P02_ETA_V1",
        "run_id": run_id,
        "observed_at_utc": utc_now(),
        "run_status": state["status"],
        "phase": state["phase"],
        "eta": eta,
    }


def p02_pause(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    paths = _run_paths(root, run_id)
    state = _read_json(paths["state"])
    if state["status"] != "RUNNING":
        raise ContractError(f"P02 run is not running: {state['status']}")
    atomic_write_json(
        paths["pause"],
        {"schema_version": "KDEN_V375_PAUSE_REQUEST_V1", "requested_at_utc": utc_now()},
        replace=True,
    )
    return _update_run_state(
        root,
        run_id,
        status="PAUSE_REQUESTED",
        message="cooperative pause requested",
    )


def p02_live_status(
    project_root: Path | str,
    run_id: str,
    *,
    interval_seconds: float = 5,
    json_lines: bool = False,
) -> None:
    if interval_seconds <= 0:
        raise ContractError("live-status interval must be positive")
    while True:
        snapshot = p02_status(project_root, run_id)
        if json_lines:
            print(json.dumps(snapshot, sort_keys=True), flush=True)
        else:
            eta = snapshot["eta"]
            eta_text = "unavailable"
            if eta.get("status") == "AVAILABLE" and eta.get("remaining_seconds") is not None:
                eta_text = f"{eta['remaining_seconds'] / 60:.1f}m copy-only"
            elif eta.get("status") == "COMPLETE":
                eta_text = "complete"
            print(
                f"[{utc_now()}] | {snapshot['status']} | phase={snapshot['phase']} | "
                f"copy={snapshot['completed_copy_files']}/{snapshot['expected_copy_files']} "
                f"({snapshot['completed_copy_bytes']}/{snapshot['expected_copy_bytes']} bytes) | "
                f"network={snapshot['completed_network_tasks']}/{snapshot['expected_network_tasks']} | "
                f"ETA={eta_text} | item={snapshot.get('current_item') or '-'}",
                flush=True,
            )
        if snapshot["status"] in {"PASS", "FAILED", "PAUSED"}:
            return
        time.sleep(interval_seconds)


def verify_p02(project_root: Path | str, *, deep: bool = True) -> dict[str, Any]:
    root = Path(project_root).resolve()
    record = verify_prefit_pass(root, 2)
    evidence = _validate_outputs(root, deep=deep)
    if record["predecessor_hashes"].get("PREFIT_P01") != evidence[
        "predecessor_record_sha256"
    ]:
        raise StaleStateError("P02 predecessor record does not match P01")
    return {
        "status": "VALID",
        "validated_stage": "PREFIT_P02",
        "record_sha256": record["record_sha256"],
        "deep_adopted_file_hashes_checked": evidence["adoption"][
            "deep_file_hashes_checked"
        ],
        "truth_package_directory": TRUTH_ROOT,
        "catalog_path": CATALOG_PATH,
        "catalog": evidence["catalog"],
        "tail_status_counts": evidence["tail_status_counts"],
        "sealed_holdout_values_read": False,
        "runtime_isolation": evidence["runtime_isolation"],
    }
