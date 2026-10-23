"""Relocatable paths, small schema checks, atomic records and SHA-256."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path


class ContractError(RuntimeError):
    """An input, access request or publication violates the experiment contract."""


def utc_now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def hash_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError("paths must be relative and may not escape their root")
    candidate = root / relative
    # Reject symlinks even when they happen to point back inside the same root.
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ContractError(f"symlink input/output is forbidden: {relative}")
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise ContractError("resolved path escapes its root") from exc
    return candidate


def read_json(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot read JSON: {Path(path).name}") from exc
    if not isinstance(value, dict):
        raise ContractError("JSON object required")
    return value


def signed(body):
    if "record_sha256" in body:
        raise ContractError("cannot sign an already signed body")
    return {**body, "record_sha256": digest(body)}


def verify_record(record):
    body = dict(record)
    supplied = body.pop("record_sha256", None)
    if supplied != digest(body):
        raise ContractError("record content SHA-256 mismatch")
    return record


def atomic_json(path, value, *, immutable=False):
    path = Path(path)
    if path.is_symlink():
        raise ContractError("refusing symlink publication")
    payload = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != payload:
            raise ContractError(f"immutable artifact already differs: {path.name}")
        return
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise ContractError("concurrent immutable publication differs")
        else:
            os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def schema_check(value, schema, location="$", *, root=None):
    """Validate the deliberately small JSON-schema subset shipped with T01.

    No dependency installation is needed. Only the keywords below are used in
    our schemas; this is not a general replacement for a JSON-schema library.
    """
    root = root or schema
    allowed = {"$schema", "$id", "$defs", "$ref", "title", "description",
               "type", "required", "properties", "additionalProperties", "items",
               "enum", "const", "pattern", "minimum", "minItems", "maxItems"}
    if set(schema) - allowed:
        raise ContractError("unsupported schema keyword")
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ContractError("only local schema references are supported")
        return schema_check(value, root["$defs"][ref.split("/")[-1]], location, root=root)
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool,
             "integer": int, "number": (int, float), "null": type(None)}
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        valid = any(isinstance(value, kinds[t]) and
                    not (t in {"number", "integer"} and isinstance(value, bool))
                    for t in types)
        if not valid:
            raise ContractError(f"schema type mismatch at {location}")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("nonfinite JSON number")
    if "const" in schema and value != schema["const"]:
        raise ContractError(f"schema constant mismatch at {location}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"schema enumeration mismatch at {location}")
    if "minimum" in schema and value < schema["minimum"]:
        raise ContractError(f"schema minimum mismatch at {location}")
    if "pattern" in schema and not re.search(schema["pattern"], value):
        raise ContractError(f"schema pattern mismatch at {location}")
    if isinstance(value, dict):
        if set(schema.get("required", [])) - set(value):
            raise ContractError(f"schema required field missing at {location}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            child = properties.get(key, schema.get("additionalProperties", True))
            if child is False:
                raise ContractError(f"schema unexpected property at {location}.{key}")
            if isinstance(child, dict):
                schema_check(item, child, f"{location}.{key}", root=root)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ContractError(f"schema array length mismatch at {location}")
        if "items" in schema:
            for index, item in enumerate(value):
                schema_check(item, schema["items"], f"{location}[{index}]", root=root)


def check_document(experiment, schema_name, value):
    schema_check(value, read_json(inside(experiment, f"schemas/{schema_name}.json")))
