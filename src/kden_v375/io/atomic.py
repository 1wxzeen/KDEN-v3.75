"""Crash-safe immutable file and directory publication.

The frozen rule is: create a temporary sibling, write and fsync it, compute its
hash, atomically replace or promote it, then fsync the parent directory. A
failed pre-publication hook cannot alter an existing destination.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..hashes import canonical_json_bytes, sha256_file


ATOMIC_RULE_ID = "KDEN_V375_ATOMIC_WRITE_V1"


class PublicationExistsError(FileExistsError):
    """Immutable publication would replace an existing artifact."""


def fsync_directory(path: Path | str) -> None:
    descriptor = os.open(Path(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(
    destination: Path | str,
    data: bytes,
    *,
    replace: bool = True,
    before_replace: Callable[[Path], None] | None = None,
) -> str:
    final = Path(destination)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists() and not replace:
        raise PublicationExistsError(final)

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=final.parent,
            prefix=f".{final.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        digest = sha256_file(temporary)
        if before_replace is not None:
            before_replace(temporary)
        if final.exists() and not replace:
            raise PublicationExistsError(final)
        os.replace(temporary, final)
        temporary = None
        fsync_directory(final.parent)
        return digest
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_json(destination: Path | str, value: Any, *, replace: bool = True) -> str:
    return atomic_write_bytes(destination, canonical_json_bytes(value), replace=replace)


def atomic_publish_directory(staging: Path | str, destination: Path | str) -> None:
    source = Path(staging)
    final = Path(destination)
    if not source.is_dir():
        raise NotADirectoryError(source)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise PublicationExistsError(final)
    os.replace(source, final)
    fsync_directory(final.parent)


def atomic_publish_file(
    staging: Path | str, destination: Path | str, *, replace: bool = False
) -> str:
    """Promote an already flushed sibling file and return its content hash."""

    source = Path(staging)
    final = Path(destination)
    if not source.is_file():
        raise FileNotFoundError(source)
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists() and not replace:
        raise PublicationExistsError(final)
    digest = sha256_file(source)
    os.replace(source, final)
    fsync_directory(final.parent)
    return digest

