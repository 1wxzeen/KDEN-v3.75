"""Deterministic identities shared by later schedule and request planners."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .hashes import canonical_json_bytes, sha256_bytes


def deterministic_id(prefix: str, identity: Mapping[str, Any]) -> str:
    normalized = prefix.strip().upper()
    if not normalized or not normalized.replace("_", "").isalnum():
        raise ValueError("identity prefix must be alphanumeric with optional underscores")
    return f"{normalized}_{sha256_bytes(canonical_json_bytes(dict(identity)))}"

