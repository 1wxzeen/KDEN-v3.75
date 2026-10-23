"""Step 00: freeze and prove the independent project foundation."""

from __future__ import annotations

import importlib.metadata
import tempfile
from pathlib import Path
from typing import Any

from ..accounting import AcquisitionAccounting, RequestTerminalResult
from ..contracts import (
    PauseController,
    load_project_paths,
    validate_runtime_isolation,
    write_step_pass,
)
from ..hashes import sha256_bytes
from ..execution import execute_bounded
from ..io.atomic import atomic_publish_directory, atomic_write_bytes
from ..io.cache import SourceGroupCache
from ..io.grib import parse_index, resolve_index_range
from ..io.http_range import (
    HttpResponse,
    MessageRange,
    VerifiedHttpClient,
    coalesce_exact_adjacent_ranges,
    split_coalesced_payload,
)
from ..progress import ProgressCoordinator, publish_work_unit_manifest


STEP_ID = "STEP_00"
STEP00_ARTIFACTS = (
    "pyproject.toml",
    "README.md",
    "environment/requirements.lock",
    "environment/build-requirements.lock",
    "environment/environment_v375.json",
    "config/project_v375.toml",
    "config/wrfsfcf_4w.toml",
    "config/wrfsfcf_8w.toml",
    "config/wrfsubhf_4w.toml",
    "config/wrfsubhf_8w.toml",
    "schemas/log_event_v375.json",
    "schemas/run_state_v375.json",
    "schemas/step_pass_v375.json",
    "src/kden_v375/__init__.py",
    "src/kden_v375/__main__.py",
    "src/kden_v375/cli.py",
    "src/kden_v375/accounting.py",
    "src/kden_v375/contracts.py",
    "src/kden_v375/execution.py",
    "src/kden_v375/hashes.py",
    "src/kden_v375/logging.py",
    "src/kden_v375/planning.py",
    "src/kden_v375/progress.py",
    "src/kden_v375/time.py",
    "src/kden_v375/io/__init__.py",
    "src/kden_v375/io/atomic.py",
    "src/kden_v375/io/cache.py",
    "src/kden_v375/io/http_range.py",
    "src/kden_v375/io/grib.py",
    "src/kden_v375/io/parquet.py",
    "src/kden_v375/steps/__init__.py",
    "src/kden_v375/steps/step_00_initialize.py",
)


class _SyntheticInterruption(RuntimeError):
    pass


def _dependency_lock_gate(root: Path) -> dict[str, Any]:
    checked = 0
    for relative in (
        "environment/requirements.lock",
        "environment/build-requirements.lock",
    ):
        for raw in (root / relative).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "==" not in line or line.startswith(("-e ", "http:", "https:", "/")):
                raise RuntimeError(f"dependency is not exactly pinned in {relative}: {line}")
            checked += 1
    if checked < 6:
        raise RuntimeError("dependency locks are unexpectedly incomplete")
    return {"exactly_pinned_entries": checked, "python_contract": ">=3.12,<3.13"}


def _installation_gate() -> dict[str, Any]:
    version = importlib.metadata.version("kden-v375")
    if version != "0.1.0":
        raise RuntimeError(f"unexpected installed package version: {version}")
    import kden_v375

    module_path = Path(kden_v375.__file__).resolve()
    legacy_names = {"kden" + "_panel", "kden" + "35"}
    if any(part in legacy_names for part in module_path.parts):
        raise RuntimeError("installed package resolved into a legacy package")
    return {"distribution": "kden-v375", "version": version, "importable": True}


def _atomic_gate(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=".step00-atomic-", dir=root / "runs") as name:
        scratch = Path(name)
        destination = scratch / "artifact.bin"
        atomic_write_bytes(destination, b"original")

        def interrupt(_temporary: Path) -> None:
            raise _SyntheticInterruption("synthetic interruption before atomic replace")

        try:
            atomic_write_bytes(destination, b"replacement", before_replace=interrupt)
        except _SyntheticInterruption:
            pass
        else:
            raise RuntimeError("synthetic atomic interruption did not fire")
        if destination.read_bytes() != b"original":
            raise RuntimeError("interrupted publication changed its destination")
        if list(scratch.glob(".artifact.bin.*.tmp")):
            raise RuntimeError("interrupted publication left temporary siblings")

        staging = scratch / "directory.staging"
        staging.mkdir()
        atomic_write_bytes(staging / "part.bin", b"sealed")
        published = scratch / "directory.final"
        atomic_publish_directory(staging, published)
        if (published / "part.bin").read_bytes() != b"sealed" or staging.exists():
            raise RuntimeError("atomic directory promotion failed")
    return {
        "rule": "write-fsync-hash-replace-fsync-parent",
        "interrupted_destination_unchanged": True,
        "temporary_sibling_cleaned": True,
        "directory_promotion_verified": True,
    }


def _progress_gate(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=".step00-resume-", dir=root / "runs") as name:
        synthetic_root = Path(name)
        run_id = "kdenv375-s00-synthetic-20260101T000000Z-resume-gate"
        run_relative = Path("run")
        plan_hash = sha256_bytes(b"step00 synthetic plan")
        expected = {"unit-0": 0, "unit-1": 1, "unit-2": 2}

        def publish(unit_id: str) -> Any:
            ordinal = expected[unit_id]
            artifact = Path("run/artifacts") / f"{unit_id}.bin"
            manifest = Path("run/manifests") / f"{unit_id}.json"
            atomic_write_bytes(synthetic_root / artifact, unit_id.encode("ascii"), replace=False)
            return publish_work_unit_manifest(
                project_root=synthetic_root,
                manifest_path=manifest,
                run_id=run_id,
                step_id=STEP_ID,
                request_plan_sha256=plan_hash,
                unit_id=unit_id,
                plan_ordinal=ordinal,
                artifact_path=artifact,
                row_count=1,
                request_count=1,
                accepted_bytes=len(unit_id),
            )

        first = ProgressCoordinator(
            project_root=synthetic_root,
            run_dir=run_relative,
            run_id=run_id,
            step_id=STEP_ID,
            request_plan_sha256=plan_hash,
            expected_units=expected,
        )
        first.commit(publish("unit-0"))
        paused = first.snapshot("PAUSED")
        if paused["completed_count"] != 1:
            raise RuntimeError("synthetic pause did not persist committed progress")

        resumed = ProgressCoordinator(
            project_root=synthetic_root,
            run_dir=run_relative,
            run_id=run_id,
            step_id=STEP_ID,
            request_plan_sha256=plan_hash,
            expected_units=expected,
        )
        if resumed.remaining_units != ("unit-1", "unit-2"):
            raise RuntimeError("resume did not recover the exact remaining work")
        receipts = {unit_id: publish(unit_id) for unit_id in resumed.remaining_units}
        for unit_id in resumed.remaining_units:
            resumed.commit(receipts[unit_id])
        duplicate = resumed.commit(receipts["unit-2"])
        if duplicate["sequence"] != 2:
            raise RuntimeError("idempotent duplicate commit changed journal identity")
        complete = resumed.snapshot("COMPLETE")
        final = ProgressCoordinator(
            project_root=synthetic_root,
            run_dir=run_relative,
            run_id=run_id,
            step_id=STEP_ID,
            request_plan_sha256=plan_hash,
            expected_units=expected,
        )
        if len(final.completed_units) != 3 or complete["remaining_count"] != 0:
            raise RuntimeError("synthetic resume did not reconcile every work unit")
        journal_lines = final.journal_path.read_text(encoding="utf-8").splitlines()
        if len(journal_lines) != 3:
            raise RuntimeError("resume introduced duplicate journal records")
    return {
        "expected_units": 3,
        "pre_pause_completed": 1,
        "post_resume_completed": 3,
        "duplicate_records": 0,
        "published_hashes_reverified": True,
    }


def _retrieval_gate() -> dict[str, Any]:
    first_message = b"GRIBa7777"
    second_message = b"GRIBb7777"
    members = (
        MessageRange("r1", 10, 18),
        MessageRange("r2", 19, 27),
    )
    groups = coalesce_exact_adjacent_ranges("synthetic://hrrr", members)
    if len(groups) != 1:
        raise RuntimeError("exactly adjacent messages did not coalesce")

    payload = first_message + second_message

    def transport(_url: str, headers: dict[str, str], _timeout: float) -> HttpResponse:
        if headers.get("Range") != "bytes=10-27":
            raise RuntimeError("unexpected synthetic Range header")
        return HttpResponse(
            status=206,
            headers={"content-range": "bytes 10-27/100", "content-length": "18"},
            body=payload,
        )

    evidence = VerifiedHttpClient(transport=transport, sleep=lambda _seconds: None).fetch_range_span(
        "https://example.invalid/hrrr", 10, 27
    )
    split = split_coalesced_payload(groups[0], evidence.body)
    if split != {"r1": first_message, "r2": second_message}:
        raise RuntimeError("coalesced payload split changed constituent bytes")

    index = parse_index(
        "1:0:d=2021010100:TMP:2 m above ground:anl:\n"
        "2:9:d=2021010100:TMP:2 m above ground:1 hour fcst:\n"
    )
    request = {
        "cycle_init_utc": "2021-01-01T00:00:00Z",
        "parameter": "TMP",
        "level": "2 m above ground",
        "interval_semantics": "snapshot",
        "forecast_lead_min": 0,
        "interval_minutes": 0,
        "field_registry_id": "SYNTHETIC_TMP",
    }
    resolved = resolve_index_range(index, request)
    if (resolved.record.start_byte, resolved.end_byte, resolved.match_count) != (0, 8, 1):
        raise RuntimeError("full-identity index resolution failed")
    return {
        "verified_http_206": True,
        "exact_content_range": True,
        "exact_adjacent_members": 2,
        "constituent_hashes_preserved": True,
        "full_selector_match_count": 1,
    }


def _shared_primitives_gate(root: Path) -> dict[str, Any]:
    committed: list[int] = []
    execution = execute_bounded(
        [0, 1, 2, 3],
        worker=lambda value: value,
        commit=committed.append,
        max_workers=2,
    )
    if committed != [0, 1, 2, 3]:
        raise RuntimeError("bounded workers did not commit in deterministic plan order")

    accounting = AcquisitionAccounting({"success", "missing"})
    accounting.record(
        RequestTerminalResult(
            "success", "SUCCESS", "source-a", "group-a", 1, 9, 1, 8
        )
    )
    accounting.record(
        RequestTerminalResult("missing", "CONFIRMED_REMOTE_MISSING", "source-b")
    )
    reconciled = accounting.assert_reconciled()

    with tempfile.TemporaryDirectory(prefix=".step00-cache-", dir=root / "runs") as name:
        scratch = Path(name)
        group = coalesce_exact_adjacent_ranges(
            "synthetic://cache", (MessageRange("cache-request", 0, 8),)
        )[0]
        cache = SourceGroupCache(scratch / "cache", scratch / "quarantine")
        payload_path, _ = cache.paths(group)
        payload_path.parent.mkdir(parents=True)
        atomic_write_bytes(payload_path, b"GRIBa7777", replace=False)
        if cache.load(group) is not None or payload_path.exists():
            raise RuntimeError("partial source-group cache was trusted")
        published = cache.publish(group, b"GRIBa7777")
        if cache.load(group) != b"GRIBa7777":
            raise RuntimeError("sealed source-group cache did not round-trip")

    return {
        "bounded_workers": 2,
        "deterministic_commits": execution.committed_count,
        "single_coordinator_commit": True,
        "partial_cache_quarantined": True,
        "sealed_cache_roundtrip": published["cache_status"] == "PUBLISHED",
        "planned_requests_reconciled": reconciled["planned_request_count"],
        "retry_count_reconciled": reconciled["retry_count"],
        "accepted_bytes_reconciled": reconciled["accepted_bytes"],
    }


def run(
    *,
    project_root: Path | str,
    run_id: str,
    pause: PauseController | None = None,
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    for directory in (
        paths.registries,
        paths.schemas,
        paths.archive,
        paths.runs,
        paths.reports,
        paths.state,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    gates: dict[str, Any] = {}
    for name, check in (
        ("clean_installation", lambda: _installation_gate()),
        ("dependency_freeze", lambda: _dependency_lock_gate(paths.root)),
        ("runtime_isolation", lambda: validate_runtime_isolation(paths.root)),
        ("atomic_publication", lambda: _atomic_gate(paths.root)),
        ("interruption_resume", lambda: _progress_gate(paths.root)),
        ("retrieval_primitives", _retrieval_gate),
        ("shared_acquisition_primitives", lambda: _shared_primitives_gate(paths.root)),
    ):
        if pause is not None:
            pause.raise_if_requested()
        gates[name] = check()

    record = write_step_pass(
        paths.root,
        step_no=0,
        run_id=run_id,
        artifact_paths=STEP00_ARTIFACTS,
        gate_evidence=gates,
    )
    return record
