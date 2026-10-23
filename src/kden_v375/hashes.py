"""Canonical SHA-256 helpers for immutable manifests and state records."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Iterable


CHUNK_SIZE = 1024 * 1024
TRANSIENT_NAMES = frozenset({"__pycache__", ".pytest_cache", ".DS_Store"})


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def directory_manifest(
    root: Path | str,
    *,
    excluded_names: Iterable[str] = TRANSIENT_NAMES,
) -> list[dict[str, object]]:
    base = Path(root)
    excluded = set(excluded_names)
    rows: list[dict[str, object]] = []
    for path in sorted((item for item in base.rglob("*") if item.is_file())):
        relative = path.relative_to(base)
        if any(part in excluded for part in relative.parts):
            continue
        rows.append(
            {
                "path": relative.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def sha256_directory(path: Path | str) -> str:
    return sha256_bytes(canonical_json_bytes(directory_manifest(path)))


def sha256_path(path: Path | str) -> str:
    candidate = Path(path)
    if candidate.is_file():
        return sha256_file(candidate)
    if candidate.is_dir():
        return sha256_directory(candidate)
    raise FileNotFoundError(candidate)


def wheel_record_digest(data: bytes) -> str:
    """Return a PEP 427-compatible digest for build verification."""

    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"

