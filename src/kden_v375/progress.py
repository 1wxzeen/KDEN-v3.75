"""Single-coordinator, hash-chained durable progress with resume verification."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractError, relative_to_root, utc_now, validate_run_id
from .hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from .io.atomic import atomic_write_json, fsync_directory


JOURNAL_SCHEMA_VERSION = "KDEN_V375_PROGRESS_RECORD_V1"
MANIFEST_SCHEMA_VERSION = "KDEN_V375_WORK_UNIT_MANIFEST_V1"
SNAPSHOT_SCHEMA_VERSION = "KDEN_V375_PROGRESS_SNAPSHOT_V1"
ZERO_HASH = "0" * 64


class ProgressError(ContractError):
    pass


class ProgressOwnershipError(ProgressError):
    pass


class JournalCorruptionError(ProgressError):
    pass


class PublicationVerificationError(ProgressError):
    pass


@dataclass(frozen=True, slots=True)
class WorkUnitReceipt:
    unit_id: str
    plan_ordinal: int
    artifact_path: str
    artifact_sha256: str
    manifest_path: str
    manifest_sha256: str
    row_count: int
    request_count: int
    accepted_bytes: int


def _append_durable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("progress append made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if created:
        fsync_directory(path.parent)


def publish_work_unit_manifest(
    *,
    project_root: Path | str,
    manifest_path: Path | str,
    run_id: str,
    step_id: str,
    request_plan_sha256: str,
    unit_id: str,
    plan_ordinal: int,
    artifact_path: Path | str,
    row_count: int,
    request_count: int,
    accepted_bytes: int,
) -> WorkUnitReceipt:
    root = Path(project_root).resolve()
    validate_run_id(run_id)
    artifact = root / artifact_path
    manifest = root / manifest_path
    artifact_relative = relative_to_root(root, artifact)
    manifest_relative = relative_to_root(root, manifest)
    if not artifact.exists():
        raise PublicationVerificationError(f"artifact is not published: {artifact_relative}")
    if any(value < 0 for value in (plan_ordinal, row_count, request_count, accepted_bytes)):
        raise PublicationVerificationError("work-unit counts and ordinal must be nonnegative")
    body = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "step_id": step_id,
        "request_plan_sha256": request_plan_sha256,
        "unit_id": unit_id,
        "plan_ordinal": int(plan_ordinal),
        "artifact_path": artifact_relative,
        "artifact_sha256": sha256_path(artifact),
        "counts": {
            "row_count": int(row_count),
            "request_count": int(request_count),
            "accepted_bytes": int(accepted_bytes),
        },
    }
    atomic_write_json(manifest, body, replace=False)
    return WorkUnitReceipt(
        unit_id=unit_id,
        plan_ordinal=int(plan_ordinal),
        artifact_path=artifact_relative,
        artifact_sha256=body["artifact_sha256"],
        manifest_path=manifest_relative,
        manifest_sha256=sha256_file(manifest),
        row_count=int(row_count),
        request_count=int(request_count),
        accepted_bytes=int(accepted_bytes),
    )


def _parse_journal(
    path: Path,
    *,
    run_id: str,
    step_id: str,
    request_plan_sha256: str,
    expected_units: Mapping[str, int],
    allow_torn_tail: bool,
) -> tuple[list[dict[str, Any]], bytes | None]:
    if not path.exists():
        return [], None
    raw = path.read_bytes()
    complete = raw
    torn: bytes | None = None
    if raw and not raw.endswith(b"\n"):
        position = raw.rfind(b"\n")
        complete = raw[: position + 1] if position >= 0 else b""
        torn = raw[position + 1 :]
        if not allow_torn_tail:
            raise JournalCorruptionError("progress journal has a torn final record")

    records: list[dict[str, Any]] = []
    previous = ZERO_HASH
    seen: set[str] = set()
    generation: int | None = None
    for sequence, line in enumerate(complete.splitlines(keepends=True)):
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JournalCorruptionError(f"invalid JSON at journal line {sequence + 1}") from exc
        if line != canonical_json_bytes(record):
            raise JournalCorruptionError(f"noncanonical JSON at journal line {sequence + 1}")
        if record.get("schema_version") != JOURNAL_SCHEMA_VERSION:
            raise JournalCorruptionError("unsupported progress journal schema")
        if record.get("run_id") != run_id or record.get("step_id") != step_id:
            raise JournalCorruptionError("journal record belongs to another run or step")
        if record.get("request_plan_sha256") != request_plan_sha256:
            raise JournalCorruptionError("journal request-plan hash changed")
        if record.get("sequence") != sequence:
            raise JournalCorruptionError("journal sequence is not contiguous")
        current_generation = int(record.get("journal_generation", 0))
        generation = current_generation if generation is None else generation
        if current_generation != generation or generation < 1:
            raise JournalCorruptionError("journal generation is invalid")
        unit_id = str(record.get("unit_id", ""))
        if unit_id not in expected_units or unit_id in seen:
            raise JournalCorruptionError(f"unexpected or duplicate work unit: {unit_id!r}")
        if int(record.get("plan_ordinal", -1)) != expected_units[unit_id]:
            raise JournalCorruptionError(f"plan ordinal changed for {unit_id!r}")
        if record.get("previous_record_sha256") != previous:
            raise JournalCorruptionError("journal hash chain is broken")
        body = dict(record)
        supplied = body.pop("record_sha256", None)
        observed = sha256_bytes(canonical_json_bytes(body))
        if supplied != observed:
            raise JournalCorruptionError("journal record hash mismatch")
        previous = observed
        seen.add(unit_id)
        records.append(record)
    return records, torn


class ProgressCoordinator:
    """Only its creating thread may append completed work-unit receipts."""

    def __init__(
        self,
        *,
        project_root: Path | str,
        run_dir: Path | str,
        run_id: str,
        step_id: str,
        request_plan_sha256: str,
        expected_units: Mapping[str, int],
        recover_torn_final: bool = False,
    ) -> None:
        self.root = Path(project_root).resolve()
        self.run_dir = self.root / run_dir
        relative_to_root(self.root, self.run_dir)
        validate_run_id(run_id)
        if len(request_plan_sha256) != 64:
            raise ProgressError("request-plan identity must be a SHA-256 digest")
        if not expected_units or len(set(expected_units.values())) != len(expected_units):
            raise ProgressError("expected work units and plan ordinals must be nonempty and unique")
        self.run_id = run_id
        self.step_id = step_id
        self.request_plan_sha256 = request_plan_sha256
        self.expected_units = {str(key): int(value) for key, value in expected_units.items()}
        self.progress_dir = self.run_dir / "progress"
        self.journal_path = self.progress_dir / "completions.jsonl"
        self.snapshot_path = self.progress_dir / "progress.json"
        self._owner_thread = threading.get_ident()
        self._generation = 1
        try:
            records, _ = _parse_journal(
                self.journal_path,
                run_id=run_id,
                step_id=step_id,
                request_plan_sha256=request_plan_sha256,
                expected_units=self.expected_units,
                allow_torn_tail=False,
            )
        except JournalCorruptionError:
            if not recover_torn_final:
                raise
            records, torn = _parse_journal(
                self.journal_path,
                run_id=run_id,
                step_id=step_id,
                request_plan_sha256=request_plan_sha256,
                expected_units=self.expected_units,
                allow_torn_tail=True,
            )
            if torn is None:
                raise
            prior_generation = int(records[0]["journal_generation"]) if records else 1
            quarantine = self.run_dir / "quarantine/progress_journal"
            quarantine.mkdir(parents=True, exist_ok=True)
            archived = quarantine / f"completions.g{prior_generation:04d}.{utc_now().replace(':', '')}.torn.jsonl"
            os.replace(self.journal_path, archived)
            fsync_directory(quarantine)
            self._generation = prior_generation + 1
            old_records = records
            records = []
            self._records = records
            self._by_unit: dict[str, dict[str, Any]] = {}
            for old in old_records:
                receipt = WorkUnitReceipt(
                    **{field: old[field] for field in WorkUnitReceipt.__dataclass_fields__}
                )
                self.commit(receipt, completed_at_utc=str(old["completed_at_utc"]))
        self._records = records
        self._by_unit = {str(record["unit_id"]): record for record in records}
        if records:
            self._generation = int(records[0]["journal_generation"])
        self.verify_published()

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise ProgressOwnershipError("only the creating coordinator thread may append progress")

    def _validate_receipt(self, receipt: WorkUnitReceipt) -> None:
        if receipt.unit_id not in self.expected_units:
            raise PublicationVerificationError(f"unexpected unit: {receipt.unit_id!r}")
        if receipt.plan_ordinal != self.expected_units[receipt.unit_id]:
            raise PublicationVerificationError("plan ordinal changed")
        artifact = self.root / receipt.artifact_path
        manifest = self.root / receipt.manifest_path
        relative_to_root(self.root, artifact)
        relative_to_root(self.root, manifest)
        if sha256_path(artifact) != receipt.artifact_sha256:
            raise PublicationVerificationError(f"artifact hash mismatch: {receipt.unit_id}")
        if sha256_file(manifest) != receipt.manifest_sha256:
            raise PublicationVerificationError(f"manifest hash mismatch: {receipt.unit_id}")
        with manifest.open("r", encoding="utf-8") as stream:
            body = json.load(stream)
        expected = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "request_plan_sha256": self.request_plan_sha256,
            "unit_id": receipt.unit_id,
            "plan_ordinal": receipt.plan_ordinal,
            "artifact_path": receipt.artifact_path,
            "artifact_sha256": receipt.artifact_sha256,
            "counts": {
                "row_count": receipt.row_count,
                "request_count": receipt.request_count,
                "accepted_bytes": receipt.accepted_bytes,
            },
        }
        if body != expected:
            raise PublicationVerificationError(f"manifest content mismatch: {receipt.unit_id}")

    @property
    def completed_units(self) -> frozenset[str]:
        return frozenset(self._by_unit)

    @property
    def remaining_units(self) -> tuple[str, ...]:
        return tuple(
            unit
            for unit, _ in sorted(self.expected_units.items(), key=lambda item: item[1])
            if unit not in self._by_unit
        )

    @property
    def completed_request_count(self) -> int:
        """Logical requests represented by durably committed work units."""

        return sum(int(record["request_count"]) for record in self._records)

    @property
    def completed_accepted_bytes(self) -> int:
        """Network bytes represented by durably committed work units."""

        return sum(int(record["accepted_bytes"]) for record in self._records)

    def commit(
        self, receipt: WorkUnitReceipt, *, completed_at_utc: str | None = None
    ) -> dict[str, Any]:
        self._assert_owner()
        self._validate_receipt(receipt)
        existing = self._by_unit.get(receipt.unit_id)
        if existing is not None:
            identity = {field: existing[field] for field in WorkUnitReceipt.__dataclass_fields__}
            if identity != {
                field: getattr(receipt, field) for field in WorkUnitReceipt.__dataclass_fields__
            }:
                raise PublicationVerificationError("conflicting duplicate completion")
            return dict(existing)
        previous = self._records[-1]["record_sha256"] if self._records else ZERO_HASH
        body = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "journal_generation": self._generation,
            "sequence": len(self._records),
            "run_id": self.run_id,
            "step_id": self.step_id,
            "request_plan_sha256": self.request_plan_sha256,
            **{field: getattr(receipt, field) for field in WorkUnitReceipt.__dataclass_fields__},
            "completed_at_utc": completed_at_utc or utc_now(),
            "previous_record_sha256": previous,
        }
        record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
        _append_durable(self.journal_path, canonical_json_bytes(record))
        self._records.append(record)
        self._by_unit[receipt.unit_id] = record
        return dict(record)

    def verify_published(self) -> None:
        for record in self._records:
            self._validate_receipt(
                WorkUnitReceipt(
                    **{field: record[field] for field in WorkUnitReceipt.__dataclass_fields__}
                )
            )

    def snapshot(self, status: str) -> dict[str, Any]:
        self._assert_owner()
        if status not in {"PAUSED", "COMPLETE"}:
            raise ProgressError("snapshot must be PAUSED or COMPLETE")
        if status == "COMPLETE" and self.remaining_units:
            raise ProgressError("cannot complete with unfinished units")
        if not self.journal_path.exists():
            _append_durable(self.journal_path, b"")
        body = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "request_plan_sha256": self.request_plan_sha256,
            "status": status,
            "materialized_at_utc": utc_now(),
            "journal_path": relative_to_root(self.root, self.journal_path),
            "journal_sha256": sha256_file(self.journal_path),
            "journal_generation": self._generation,
            "journal_tip_sha256": self._records[-1]["record_sha256"] if self._records else ZERO_HASH,
            "expected_count": len(self.expected_units),
            "completed_count": len(self._records),
            "remaining_count": len(self.remaining_units),
            "completed_units": sorted(self.completed_units),
        }
        atomic_write_json(self.snapshot_path, body)
        return body


def read_progress_status(
    *,
    project_root: Path | str,
    run_dir: Path | str,
    run_id: str,
    step_id: str,
    request_plan_sha256: str,
    expected_units: Mapping[str, int],
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    journal = root / run_dir / "progress/completions.jsonl"
    records, torn = _parse_journal(
        journal,
        run_id=run_id,
        step_id=step_id,
        request_plan_sha256=request_plan_sha256,
        expected_units=expected_units,
        allow_torn_tail=True,
    )
    return {
        "expected_count": len(expected_units),
        "completed_count": len(records),
        "remaining_count": len(expected_units) - len(records),
        "last_committed_unit": records[-1]["unit_id"] if records else None,
        "journal_tip_sha256": records[-1]["record_sha256"] if records else ZERO_HASH,
        "uncommitted_trailing_bytes": len(torn or b""),
    }
