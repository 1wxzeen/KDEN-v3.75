"""Project-root, run, lock, state, and content-addressed PASS contracts."""

from __future__ import annotations

import ast
import fcntl
import json
import os
import re
import signal
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .hashes import canonical_json_bytes, sha256_bytes, sha256_file, sha256_path
from .io.atomic import atomic_write_json


RUN_ID_PATTERN = re.compile(
    r"^kdenv375-s(?P<step>0[0-8])-"
    r"(?P<scope>ordinary|diagnostic|owner-full|validation|synthetic)-"
    r"(?P<stamp>[0-9]{8}T[0-9]{6}Z)-"
    r"(?P<label>[a-z0-9][a-z0-9-]{0,31})$"
)
STEP_ID_PATTERN = re.compile(r"^STEP_0[0-8]$")
OWNER_CONTROLLED_STEPS = frozenset({5, 6})
RUN_SCHEMA_VERSION = "KDEN_V375_RUN_STATE_V1"
PASS_SCHEMA_VERSION = "KDEN_V375_STEP_PASS_V1"
VALID_RUN_STATUSES = frozenset(
    {"INITIALIZED", "RUNNING", "PAUSE_REQUESTED", "PAUSED", "PASS", "FAILED"}
)
VALID_SCOPES = frozenset(
    {"ordinary", "diagnostic", "owner-full", "validation", "synthetic"}
)


class ContractError(RuntimeError):
    """A frozen project or execution contract was violated."""


class IsolationError(ContractError):
    """The independent package refers to a fossilized codebase at runtime."""


class ConcurrentRunError(ContractError):
    """A run already owns the requested durable state."""


class StaleStateError(ContractError):
    """A state record or a declared artifact no longer matches its hash."""


class PauseRequested(ContractError):
    """Cooperative pause was observed at an atomic work-unit boundary."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def compact_utc_now() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True, slots=True)
class RunIdentity:
    run_id: str
    step_no: int
    scope: str
    timestamp_utc: str
    label: str


def validate_run_id(run_id: str, *, step_no: int | None = None, scope: str | None = None) -> RunIdentity:
    match = RUN_ID_PATTERN.fullmatch(run_id)
    if match is None:
        raise ContractError(
            "run ID must match kdenv375-sNN-SCOPE-YYYYMMDDTHHMMSSZ-label"
        )
    identity = RunIdentity(
        run_id=run_id,
        step_no=int(match.group("step")),
        scope=match.group("scope"),
        timestamp_utc=match.group("stamp"),
        label=match.group("label"),
    )
    if step_no is not None and identity.step_no != int(step_no):
        raise ContractError("run ID step does not match requested step")
    if scope is not None and identity.scope != scope:
        raise ContractError("run ID scope does not match requested scope")
    return identity


def make_run_id(step_no: int, scope: str, label: str, *, timestamp: str | None = None) -> str:
    if not 0 <= int(step_no) <= 8:
        raise ContractError("step number must be between 0 and 8")
    if scope not in VALID_SCOPES:
        raise ContractError(f"unknown run scope: {scope!r}")
    normalized = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:32]
    if not normalized:
        raise ContractError("run label must contain an ASCII letter or digit")
    value = f"kdenv375-s{int(step_no):02d}-{scope}-{timestamp or compact_utc_now()}-{normalized}"
    validate_run_id(value, step_no=step_no, scope=scope)
    return value


def validate_scope(step_no: int, scope: str) -> None:
    if scope not in VALID_SCOPES:
        raise ContractError(f"unknown execution scope: {scope!r}")
    if step_no in OWNER_CONTROLLED_STEPS:
        if scope not in {"diagnostic", "owner-full", "validation", "synthetic"}:
            raise ContractError(
                f"Step {step_no:02d} requires diagnostic, owner-full, validation, or synthetic scope"
            )
    elif scope == "owner-full":
        raise ContractError("owner-full scope is reserved for Steps 05 and 06")


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path
    config: Path
    registries: Path
    schemas: Path
    archive: Path
    runs: Path
    reports: Path
    state: Path


def _inside(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"path escapes project root: {candidate}") from exc
    return resolved


def relative_to_root(root: Path | str, path: Path | str) -> str:
    base = Path(root).resolve()
    return _inside(base, Path(path)).relative_to(base).as_posix()


def resolve_project_root(explicit: Path | str | None = None) -> Path:
    if explicit is not None:
        candidates = [Path(explicit)]
    else:
        configured = os.environ.get("KDEN_V375_ROOT")
        candidates = ([Path(configured)] if configured else []) + [Path.cwd()]
    for candidate in candidates:
        root = candidate.expanduser().resolve()
        if (root / "PROJECT.md").is_file() and (root / "pyproject.toml").is_file():
            return root
    raise ContractError(
        "cannot identify the KDEN v3.75 root; use --project-root or KDEN_V375_ROOT"
    )


def load_project_paths(project_root: Path | str) -> ProjectPaths:
    root = Path(project_root).resolve()
    config_path = root / "config/project_v375.toml"
    if not config_path.is_file():
        raise ContractError(f"project configuration is missing: {config_path}")
    with config_path.open("rb") as stream:
        raw = tomllib.load(stream)
    if raw.get("schema_version") != "KDEN_V375_PROJECT_CONFIG_V1":
        raise ContractError("unsupported project configuration schema")
    configured = raw.get("paths", {})
    names = {
        "registries": configured.get("registries"),
        "schemas": configured.get("schemas"),
        "archive": configured.get("archive"),
        "runs": configured.get("runs"),
        "reports": configured.get("reports"),
        "state": configured.get("state"),
    }
    for label, value in names.items():
        candidate = Path(str(value))
        if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
            raise ContractError(f"{label} must be a relative path within the project")
    return ProjectPaths(
        root=root,
        config=config_path,
        **{label: _inside(root, root / str(value)) for label, value in names.items()},
    )


def validate_runtime_isolation(project_root: Path | str) -> dict[str, Any]:
    """Prove that the installed source tree has no legacy imports or paths."""

    root = Path(project_root).resolve()
    source_root = root / "src/kden_v375"
    if not source_root.is_dir():
        raise IsolationError("src/kden_v375 is missing")
    denied_imports = {"kden" + "_panel", "kden" + "35"}
    denied_fragments = (
        "/" + "Users" + "/",
        "previous" + " codebases",
        "src---" + "v3",
        "src---" + "v3.5",
        "kden" + "_panel",
        "kden" + "35",
    )
    scanned = 0
    for path in sorted(source_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        scanned += 1
        for fragment in denied_fragments:
            if fragment in text:
                raise IsolationError(
                    f"runtime source contains denied legacy/path reference {fragment!r}: "
                    f"{path.relative_to(root)}"
                )
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name.split(".", 1)[0] in denied_imports:
                    raise IsolationError(
                        f"runtime source imports denied package {name!r}: {path.relative_to(root)}"
                    )
    return {
        "source_files_scanned": scanned,
        "denied_import_prefixes": sorted(denied_imports),
        "absolute_user_paths_found": 0,
        "legacy_runtime_references_found": 0,
        "package_root": "src/kden_v375",
    }


class ExclusiveRunLock:
    """Nonblocking process lock; the lock file contains no scientific state."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._stream: Any | None = None

    def __enter__(self) -> "ExclusiveRunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._stream.close()
            self._stream = None
            raise ConcurrentRunError(f"run lock is held: {self.path}") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self._stream is not None:
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
            self._stream.close()
            self._stream = None


class PauseController:
    """Signal plus control-file pause flag checked only at atomic boundaries."""

    def __init__(self, pause_path: Path | str):
        self.pause_path = Path(pause_path)
        self._signaled = False
        self._previous: dict[int, Any] = {}

    @property
    def requested(self) -> bool:
        return self._signaled or self.pause_path.exists()

    def _handle(self, _signum: int, _frame: object) -> None:
        self._signaled = True

    def install(self) -> None:
        if os.getpid() != getattr(self, "_installed_pid", os.getpid()):
            return
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle)

    def restore(self) -> None:
        for signum, previous in self._previous.items():
            signal.signal(signum, previous)
        self._previous.clear()

    def request(self) -> None:
        self.pause_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.pause_path,
            {"schema_version": "KDEN_V375_PAUSE_REQUEST_V1", "requested_at_utc": utc_now()},
        )

    def clear(self) -> None:
        self.pause_path.unlink(missing_ok=True)

    def raise_if_requested(self) -> None:
        if self.requested:
            raise PauseRequested("pause requested at atomic work-unit boundary")


class RunStateStore:
    def __init__(self, project_root: Path | str, run_id: str):
        self.paths = load_project_paths(project_root)
        self.identity = validate_run_id(run_id)
        self.run_dir = _inside(self.paths.root, self.paths.runs / run_id)
        self.state_path = self.run_dir / "run.json"
        self.events_path = self.run_dir / "events.jsonl"
        self.pause_path = self.run_dir / "control/pause.requested.json"
        self.lock_path = self.run_dir / "control/run.lock"

    def read(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            raise ContractError(f"run does not exist: {self.identity.run_id}")
        with self.state_path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict) or value.get("schema_version") != RUN_SCHEMA_VERSION:
            raise ContractError(f"invalid run state: {self.state_path}")
        return value

    def initialize(self) -> dict[str, Any]:
        if self.state_path.exists():
            state = self.read()
            if (
                state.get("step_id") != f"STEP_{self.identity.step_no:02d}"
                or state.get("scope") != self.identity.scope
            ):
                raise ContractError("existing run state disagrees with run ID")
            return state
        timestamp = utc_now()
        state = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": self.identity.run_id,
            "step_id": f"STEP_{self.identity.step_no:02d}",
            "scope": self.identity.scope,
            "status": "INITIALIZED",
            "created_at_utc": timestamp,
            "updated_at_utc": timestamp,
            "pid": None,
            "message": None,
        }
        atomic_write_json(self.state_path, state, replace=False)
        return state

    def transition(self, status: str, *, message: str | None = None) -> dict[str, Any]:
        if status not in VALID_RUN_STATUSES:
            raise ContractError(f"invalid run status: {status!r}")
        state = self.initialize()
        updated = {
            **state,
            "status": status,
            "updated_at_utc": utc_now(),
            "pid": os.getpid() if status in {"RUNNING", "PAUSE_REQUESTED"} else None,
            "message": message,
        }
        atomic_write_json(self.state_path, updated)
        return updated

    def request_pause(self) -> dict[str, Any]:
        state = self.read()
        if state.get("status") not in {"RUNNING", "PAUSE_REQUESTED"}:
            raise ContractError(
                f"run is not active and cannot be paused: {state.get('status')!r}"
            )
        PauseController(self.pause_path).request()
        updated = {
            **state,
            "status": "PAUSE_REQUESTED",
            "updated_at_utc": utc_now(),
            "message": "cooperative pause requested",
        }
        atomic_write_json(self.state_path, updated)
        return updated


def write_step_pass(
    project_root: Path | str,
    *,
    step_no: int,
    run_id: str,
    artifact_paths: Iterable[Path | str],
    gate_evidence: Mapping[str, Any],
    predecessor_hashes: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    validate_run_id(run_id, step_no=step_no)
    artifact_hashes: dict[str, str] = {}
    for artifact in artifact_paths:
        absolute = _inside(paths.root, paths.root / Path(artifact))
        relative = absolute.relative_to(paths.root).as_posix()
        artifact_hashes[relative] = sha256_path(absolute)
    body = {
        "schema_version": PASS_SCHEMA_VERSION,
        "step_id": f"STEP_{step_no:02d}",
        "status": "PASS",
        "completed_at_utc": utc_now(),
        "run_id": run_id,
        "predecessor_hashes": dict(sorted((predecessor_hashes or {}).items())),
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "gate_evidence": dict(gate_evidence),
    }
    record = {**body, "record_sha256": sha256_bytes(canonical_json_bytes(body))}
    atomic_write_json(paths.state / f"STEP_{step_no:02d}_PASS.json", record)
    return record


def verify_step_pass(project_root: Path | str, step_no: int) -> dict[str, Any]:
    paths = load_project_paths(project_root)
    pass_path = paths.state / f"STEP_{step_no:02d}_PASS.json"
    if not pass_path.is_file():
        raise ContractError(f"Step {step_no:02d} PASS is missing")
    with pass_path.open("r", encoding="utf-8") as stream:
        record = json.load(stream)
    if record.get("schema_version") != PASS_SCHEMA_VERSION:
        raise StaleStateError("unsupported PASS record schema")
    if record.get("step_id") != f"STEP_{step_no:02d}" or record.get("status") != "PASS":
        raise StaleStateError("PASS record identity is invalid")
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    observed = sha256_bytes(canonical_json_bytes(body))
    if supplied != observed:
        raise StaleStateError("PASS record content hash mismatch")
    for relative, expected in record.get("artifact_hashes", {}).items():
        artifact = _inside(paths.root, paths.root / relative)
        if sha256_path(artifact) != expected:
            raise StaleStateError(f"Step {step_no:02d} artifact changed: {relative}")
    for predecessor_id, expected in record.get("predecessor_hashes", {}).items():
        predecessor_no = int(predecessor_id.removeprefix("STEP_"))
        predecessor = verify_step_pass(paths.root, predecessor_no)
        if predecessor["record_sha256"] != expected:
            raise StaleStateError(f"predecessor hash changed: {predecessor_id}")
    return record


def predecessor_hashes(project_root: Path | str, step_no: int) -> dict[str, str]:
    return {
        f"STEP_{prior:02d}": verify_step_pass(project_root, prior)["record_sha256"]
        for prior in range(step_no)
    }
