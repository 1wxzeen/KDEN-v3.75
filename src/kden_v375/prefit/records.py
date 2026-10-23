"""Content-addressed records for the P01--P07 prefit stages."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..contracts import ContractError, StaleStateError, load_project_paths
from ..hashes import canonical_json_bytes, sha256_bytes, sha256_path
from ..io.atomic import atomic_write_json


PREFIT_PASS_SCHEMA_VERSION = "KDEN_V375_PREFIT_PASS_V1"
PREFIT_RUN_ID_PATTERN = re.compile(
    r"^kdenv375-p(?P<stage>0[1-7])-"
    r"(?P<scope>ordinary|diagnostic|owner-full|validation|synthetic)-"
    r"(?P<stamp>[0-9]{8}T[0-9]{6}Z)-"
    r"(?P<label>[a-z0-9][a-z0-9-]{0,31})$"
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def compact_utc_now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def make_prefit_run_id(
    stage_no: int,
    scope: str,
    label: str,
    *,
    timestamp: str | None = None,
) -> str:
    if not 1 <= int(stage_no) <= 7:
        raise ContractError("prefit stage number must be between 1 and 7")
    normalized = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:32]
    if not normalized:
        raise ContractError("prefit run label must contain an ASCII letter or digit")
    value = (
        f"kdenv375-p{int(stage_no):02d}-{scope}-"
        f"{timestamp or compact_utc_now()}-{normalized}"
    )
    validate_prefit_run_id(value, stage_no=stage_no, scope=scope)
    return value


def validate_prefit_run_id(
    run_id: str,
    *,
    stage_no: int | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    match = PREFIT_RUN_ID_PATTERN.fullmatch(run_id)
    if match is None:
        raise ContractError(
            "prefit run ID must match "
            "kdenv375-pNN-SCOPE-YYYYMMDDTHHMMSSZ-label"
        )
    identity = {
        "run_id": run_id,
        "stage_no": int(match.group("stage")),
        "scope": match.group("scope"),
        "timestamp_utc": match.group("stamp"),
        "label": match.group("label"),
    }
    if stage_no is not None and identity["stage_no"] != int(stage_no):
        raise ContractError("prefit run ID stage does not match requested stage")
    if scope is not None and identity["scope"] != scope:
        raise ContractError("prefit run ID scope does not match requested scope")
    return identity


def _inside(root: Path, relative: Path | str) -> Path:
    candidate = (root / Path(relative)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"path escapes project root: {relative}") from exc
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise StaleStateError(f"JSON object expected: {path}")
    return value


def publish_immutable_json(path: Path, value: Mapping[str, Any]) -> str:
    """Publish once, or accept an existing byte-equivalent JSON object."""

    expected = dict(value)
    if path.exists():
        if _read_json(path) != expected:
            raise StaleStateError(f"immutable prefit artifact differs: {path}")
        return sha256_path(path)
    return atomic_write_json(path, expected, replace=False)


def write_prefit_pass(
    project_root: Path | str,
    *,
    stage_no: int,
    run_id: str,
    artifact_paths: Iterable[Path | str],
    predecessor_hashes: Mapping[str, str],
    authority_hashes: Mapping[str, str],
    gate_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    validate_prefit_run_id(run_id, stage_no=stage_no)
    artifact_hashes: dict[str, str] = {}
    for artifact in artifact_paths:
        absolute = _inside(paths.root, artifact)
        relative = absolute.relative_to(paths.root).as_posix()
        artifact_hashes[relative] = sha256_path(absolute)
    body = {
        "schema_version": PREFIT_PASS_SCHEMA_VERSION,
        "stage_id": f"PREFIT_P{stage_no:02d}",
        "status": "PASS",
        "completed_at_utc": utc_now(),
        "run_id": run_id,
        "predecessor_hashes": dict(sorted(predecessor_hashes.items())),
        "authority_hashes": dict(sorted(authority_hashes.items())),
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "gate_evidence": dict(gate_evidence),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    destination = paths.state / f"PREFIT_P{stage_no:02d}_PASS.json"
    publish_immutable_json(destination, record)
    return record


def verify_prefit_pass(project_root: Path | str, stage_no: int) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    pass_path = paths.state / f"PREFIT_P{int(stage_no):02d}_PASS.json"
    if not pass_path.is_file():
        raise ContractError(f"Prefit P{int(stage_no):02d} PASS is missing")
    record = _read_json(pass_path)
    if record.get("schema_version") != PREFIT_PASS_SCHEMA_VERSION:
        raise StaleStateError("unsupported prefit PASS record schema")
    if (
        record.get("stage_id") != f"PREFIT_P{int(stage_no):02d}"
        or record.get("status") != "PASS"
    ):
        raise StaleStateError("prefit PASS record identity is invalid")
    validate_prefit_run_id(str(record.get("run_id", "")), stage_no=stage_no)
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != sha256_bytes(canonical_json_bytes(body)):
        raise StaleStateError("prefit PASS record content hash mismatch")
    for relative, expected in record.get("artifact_hashes", {}).items():
        artifact = _inside(paths.root, relative)
        if sha256_path(artifact) != expected:
            raise StaleStateError(
                f"Prefit P{int(stage_no):02d} artifact changed: {relative}"
            )
    return record
