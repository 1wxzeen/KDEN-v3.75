"""Hash-verified source-group cache with fail-closed partial-pair quarantine."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..contracts import utc_now
from ..hashes import sha256_bytes, sha256_file
from .atomic import atomic_write_bytes, atomic_write_json, fsync_directory
from .http_range import HttpContractError, TransportRangeGroup, split_coalesced_payload


CACHE_SCHEMA_VERSION = "KDEN_V375_SOURCE_GROUP_CACHE_V1"


class CacheContractError(RuntimeError):
    pass


class SourceGroupCache:
    def __init__(self, cache_root: Path | str, quarantine_root: Path | str):
        self.cache_root = Path(cache_root)
        self.quarantine_root = Path(quarantine_root)

    def paths(self, group: TransportRangeGroup) -> tuple[Path, Path]:
        return (
            self.cache_root / f"{group.group_id}.grib2",
            self.cache_root / f"{group.group_id}.json",
        )

    def _quarantine(
        self, group: TransportRangeGroup, payload_path: Path, metadata_path: Path, reason: str
    ) -> Path:
        stamp = utc_now().replace(":", "").replace("-", "")
        destination = self.quarantine_root / group.group_id / f"{stamp}_{reason}"
        destination.mkdir(parents=True, exist_ok=False)
        for source in (payload_path, metadata_path):
            if source.exists():
                os.replace(source, destination / source.name)
        fsync_directory(destination)
        fsync_directory(destination.parent)
        return destination

    def load(self, group: TransportRangeGroup) -> bytes | None:
        payload_path, metadata_path = self.paths(group)
        exists = (payload_path.exists(), metadata_path.exists())
        if exists == (False, False):
            return None
        if exists[0] != exists[1]:
            self._quarantine(group, payload_path, metadata_path, "partial_pair")
            return None
        try:
            with metadata_path.open("r", encoding="utf-8") as stream:
                metadata = json.load(stream)
            payload = payload_path.read_bytes()
            expected = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "group_id": group.group_id,
                "source_uri": group.source_uri,
                "range_start": group.start,
                "range_end": group.end,
                "member_request_ids": [member.request_id for member in group.members],
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
            }
            if metadata != expected:
                raise CacheContractError("cache metadata or payload hash changed")
            split_coalesced_payload(group, payload)
            return payload
        except (
            OSError,
            json.JSONDecodeError,
            CacheContractError,
            HttpContractError,
            ValueError,
        ) as exc:
            self._quarantine(group, payload_path, metadata_path, "invalid_pair")
            if isinstance(exc, CacheContractError):
                raise
            raise CacheContractError(f"invalid cache pair: {group.group_id}") from exc

    def publish(self, group: TransportRangeGroup, payload: bytes) -> dict[str, Any]:
        existing = self.load(group)
        if existing is not None:
            return {"cache_status": "VERIFIED_HIT", "sha256": sha256_bytes(existing)}
        split_coalesced_payload(group, payload)
        payload_path, metadata_path = self.paths(group)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(payload_path, payload, replace=False)
        metadata = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "group_id": group.group_id,
            "source_uri": group.source_uri,
            "range_start": group.start,
            "range_end": group.end,
            "member_request_ids": [member.request_id for member in group.members],
            "size_bytes": len(payload),
            "sha256": sha256_file(payload_path),
        }
        try:
            atomic_write_json(metadata_path, metadata, replace=False)
        except Exception:
            self._quarantine(group, payload_path, metadata_path, "publication_interrupted")
            raise
        return {"cache_status": "PUBLISHED", "sha256": metadata["sha256"]}
