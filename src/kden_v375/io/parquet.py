"""Deterministic Parquet publication boundary for later acquisition steps."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from .atomic import atomic_publish_file


PARQUET_COMPRESSION = "zstd"


def _modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required for Parquet publication; install environment/requirements.lock"
        ) from exc
    return pa, pq


def atomic_write_table(
    table: Any,
    destination: Path | str,
    *,
    schema: Any | None = None,
    compression: str = PARQUET_COMPRESSION,
    replace: bool = False,
) -> str:
    """Write a table to a temporary sibling, fsync, and atomically promote it."""

    pa, pq = _modules()
    if not isinstance(table, pa.Table):
        raise TypeError("table must be a pyarrow.Table")
    if schema is not None and not table.schema.equals(schema, check_metadata=True):
        raise ValueError("table schema disagrees with the frozen schema")
    final = Path(destination)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            dir=final.parent, prefix=f".{final.name}.", suffix=".tmp.parquet"
        )
        os.close(descriptor)
        temporary = Path(name)
        pq.write_table(
            table,
            temporary,
            compression=compression,
            use_dictionary=True,
            write_statistics=True,
        )
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        digest = atomic_publish_file(temporary, final, replace=replace)
        temporary = None
        return digest
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

