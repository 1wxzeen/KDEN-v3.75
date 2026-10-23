"""Exact terminal request, retry, byte, extraction, and publication accounting."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Literal


Disposition = Literal["SUCCESS", "CONFIRMED_REMOTE_MISSING", "QUARANTINED"]


class ReconciliationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RequestTerminalResult:
    request_id: str
    disposition: Disposition
    source_object_identity: str
    transport_group_id: str | None = None
    retry_count: int = 0
    accepted_bytes: int = 0
    extracted_value_count: int = 0
    published_bytes: int = 0


class AcquisitionAccounting:
    """A coordinator-owned ledger with exactly one terminal result per request."""

    def __init__(self, expected_request_ids: set[str] | frozenset[str]):
        if not expected_request_ids:
            raise ReconciliationError("expected request IDs must not be empty")
        self.expected = frozenset(str(value) for value in expected_request_ids)
        if len(self.expected) != len(expected_request_ids):
            raise ReconciliationError("expected request IDs must be unique")
        self._owner_thread = threading.get_ident()
        self._results: dict[str, RequestTerminalResult] = {}

    def record(self, result: RequestTerminalResult) -> None:
        if threading.get_ident() != self._owner_thread:
            raise ReconciliationError("only the coordinator may record terminal accounting")
        if result.request_id not in self.expected:
            raise ReconciliationError(f"unplanned request: {result.request_id}")
        if result.request_id in self._results:
            raise ReconciliationError(f"duplicate terminal request: {result.request_id}")
        if result.disposition not in {
            "SUCCESS",
            "CONFIRMED_REMOTE_MISSING",
            "QUARANTINED",
        }:
            raise ReconciliationError(f"unknown disposition: {result.disposition}")
        counts = (
            result.retry_count,
            result.accepted_bytes,
            result.extracted_value_count,
            result.published_bytes,
        )
        if any(value < 0 for value in counts):
            raise ReconciliationError("accounting counters must be nonnegative")
        if result.disposition != "SUCCESS" and (
            result.extracted_value_count or result.published_bytes
        ):
            raise ReconciliationError("missing/quarantined requests cannot publish values")
        self._results[result.request_id] = result

    @property
    def remaining(self) -> frozenset[str]:
        return self.expected.difference(self._results)

    def report(self) -> dict[str, int]:
        results = tuple(self._results.values())
        return {
            "planned_request_count": len(self.expected),
            "terminal_request_count": len(results),
            "success_count": sum(item.disposition == "SUCCESS" for item in results),
            "confirmed_remote_missing_count": sum(
                item.disposition == "CONFIRMED_REMOTE_MISSING" for item in results
            ),
            "quarantined_count": sum(item.disposition == "QUARANTINED" for item in results),
            "source_object_count": len({item.source_object_identity for item in results}),
            "transport_group_count": len(
                {item.transport_group_id for item in results if item.transport_group_id is not None}
            ),
            "retry_count": sum(item.retry_count for item in results),
            "accepted_bytes": sum(item.accepted_bytes for item in results),
            "extracted_value_count": sum(item.extracted_value_count for item in results),
            "published_bytes": sum(item.published_bytes for item in results),
            "unreconciled_count": len(self.remaining),
        }

    def assert_reconciled(self, *, allow_quarantine: bool = False) -> dict[str, int]:
        report = self.report()
        if self.remaining:
            raise ReconciliationError(
                f"unreconciled planned requests remain: {len(self.remaining)}"
            )
        if report["quarantined_count"] and not allow_quarantine:
            raise ReconciliationError("final reconciliation contains quarantined requests")
        if (
            report["success_count"]
            + report["confirmed_remote_missing_count"]
            + report["quarantined_count"]
            != report["planned_request_count"]
        ):
            raise ReconciliationError("terminal dispositions do not sum to the plan")
        return report

