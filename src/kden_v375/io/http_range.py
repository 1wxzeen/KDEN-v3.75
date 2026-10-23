"""Verified, retry-bounded HTTP retrieval for indexed HRRR messages.

Index requests require HTTP 200. Byte-range requests require HTTP 206, exact
``Content-Range``, exact length, identity encoding, and GRIB framing where a
single message is expected. The transport remains injectable for network-free
contract tests.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..hashes import canonical_json_bytes, sha256_bytes


class HttpContractError(RuntimeError):
    """A response failed the frozen retrieval contract."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class AttemptEvidence:
    attempt: int
    status: int | None
    outcome: str
    elapsed_seconds: float
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes
    sha256: str
    size_bytes: int
    wall_seconds: float
    attempts: tuple[AttemptEvidence, ...]
    cache_status: str = "DOWNLOADED"

    @property
    def retry_count(self) -> int:
        return max(0, len(self.attempts) - 1)


Transport = Callable[[str, Mapping[str, str], float], HttpResponse]
AttemptCallback = Callable[[str, AttemptEvidence], None]


@dataclass(frozen=True, slots=True)
class MessageRange:
    """One fully identified scientific message and its inclusive byte range."""

    request_id: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class TransportRangeGroup:
    """One HTTP span made only from exactly adjacent scientific messages."""

    group_id: str
    source_uri: str
    start: int
    end: int
    members: tuple[MessageRange, ...]


class PersistentHttpTransport:
    """Thread-local ``requests.Session`` transport with explicit lifecycle.

    ``requests.Session`` is not shared across worker threads.  Each calling
    thread receives one session and therefore one independent connection pool;
    sequential work units executed by that thread can still reuse established
    TCP/TLS connections.  urllib3 retries are deliberately disabled because
    :class:`VerifiedHttpClient` owns the complete, durable retry ledger.
    """

    BACKEND = "requests_session"
    CONNECTION_POLICY = "persistent_per_worker_thread"

    def __init__(
        self,
        *,
        pool_connections: int = 8,
        pool_maxsize: int = 1,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        if pool_connections < 1 or pool_maxsize < 1:
            raise ValueError("HTTP connection-pool sizes must be positive")
        self.pool_connections = int(pool_connections)
        self.pool_maxsize = int(pool_maxsize)
        self._session_factory = session_factory
        self._local = threading.local()
        self._lock = threading.Lock()
        self._sessions: list[Any] = []
        self._requests_by_host: Counter[str] = Counter()
        self._request_count = 0
        self._closed = False

    def _new_session(self) -> Any:
        if self._session_factory is not None:
            return self._session_factory()
        try:
            import requests
            from requests.adapters import HTTPAdapter
        except ImportError as exc:
            raise HttpContractError(
                "requests is required for persistent HTTP acquisition"
            ) from exc
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=self.pool_connections,
            pool_maxsize=self.pool_maxsize,
            max_retries=0,
            pool_block=True,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _session_for_current_thread(self) -> Any:
        session = getattr(self._local, "session", None)
        if session is not None:
            return session
        with self._lock:
            if self._closed:
                raise HttpContractError("persistent HTTP transport is closed")
            session = self._new_session()
            self._sessions.append(session)
            self._local.session = session
        return session

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> HttpResponse:
        session = self._session_for_current_thread()
        host = urlsplit(url).netloc.lower()
        with self._lock:
            if self._closed:
                raise HttpContractError("persistent HTTP transport is closed")
            self._request_count += 1
            self._requests_by_host[host] += 1
        response = None
        try:
            response = session.get(
                url,
                headers=dict(headers),
                timeout=float(timeout),
                allow_redirects=True,
                stream=True,
            )
            content_encoding = response.headers.get("content-encoding", "").strip().lower()
            if content_encoding not in {"", "identity"}:
                raise HttpContractError(
                    f"unexpected Content-Encoding {content_encoding!r} for {url}"
                )
            # ``Accept-Encoding: identity`` plus the explicit encoding check
            # ensures these are the exact archived bytes used for size/hash
            # evidence, including MADIS files whose payload is itself gzip.
            body = response.content
            return HttpResponse(
                status=int(response.status_code),
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
            )
        except HttpContractError:
            raise
        except Exception as exc:
            raise HttpContractError(f"transport error for {url}: {exc}") from exc
        finally:
            if response is not None:
                response.close()

    def snapshot(self) -> dict[str, Any]:
        """Return non-scientific transport lineage and usage counters."""

        with self._lock:
            return {
                "backend": self.BACKEND,
                "connection_policy": self.CONNECTION_POLICY,
                "adapter_retry_count": 0,
                "pool_connections_per_session": self.pool_connections,
                "pool_maxsize_per_host": self.pool_maxsize,
                "sessions_created": len(self._sessions),
                "request_count": self._request_count,
                "requests_by_host": dict(sorted(self._requests_by_host.items())),
                "closed": self._closed,
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            sessions = tuple(self._sessions)
        for session in sessions:
            session.close()

    def __enter__(self) -> "PersistentHttpTransport":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def default_transport(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    request = Request(url, headers=dict(headers), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status),
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read(),
            )
    except HTTPError as exc:
        return HttpResponse(
            status=int(exc.code),
            headers={key.lower(): value for key, value in exc.headers.items()},
            body=exc.read(),
        )
    except (URLError, TimeoutError, OSError) as exc:
        raise HttpContractError(f"transport error for {url}: {exc}") from exc


def _normalise_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


class VerifiedHttpClient:
    """Fail-closed HTTP client with deterministic exponential retry delays."""

    RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        max_attempts: int = 4,
        timeout_seconds: float = 120.0,
        initial_backoff_seconds: float = 1.0,
        user_agent: str = "KDEN-v3.75/0.1",
        sleep: Callable[[float], None] = time.sleep,
        attempt_callback: AttemptCallback | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if timeout_seconds <= 0 or initial_backoff_seconds < 0:
            raise ValueError("timeouts/backoff must be nonnegative and timeout positive")
        self.transport = default_transport if transport is None else transport
        self.max_attempts = int(max_attempts)
        self.timeout_seconds = float(timeout_seconds)
        self.initial_backoff_seconds = float(initial_backoff_seconds)
        self.user_agent = user_agent
        self.sleep = sleep
        self.attempt_callback = attempt_callback

    def _request(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        accepted_statuses: frozenset[int],
    ) -> tuple[HttpResponse, tuple[AttemptEvidence, ...], float]:
        attempts: list[AttemptEvidence] = []
        request_started = time.monotonic()
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                response = self.transport(url, headers, self.timeout_seconds)
            except HttpContractError as exc:
                evidence = AttemptEvidence(
                    attempt, None, "TRANSPORT_ERROR", time.monotonic() - started, str(exc)
                )
                attempts.append(evidence)
                if self.attempt_callback is not None:
                    self.attempt_callback(url, evidence)
                if attempt == self.max_attempts:
                    raise
            else:
                response = HttpResponse(
                    int(response.status), _normalise_headers(response.headers), bytes(response.body)
                )
                if response.status in accepted_statuses:
                    evidence = AttemptEvidence(
                        attempt, response.status, "HTTP_ACCEPTED", time.monotonic() - started
                    )
                    attempts.append(evidence)
                    if self.attempt_callback is not None:
                        self.attempt_callback(url, evidence)
                    return response, tuple(attempts), time.monotonic() - request_started
                evidence = AttemptEvidence(
                    attempt,
                    response.status,
                    "HTTP_REJECTED",
                    time.monotonic() - started,
                    f"unexpected HTTP {response.status}",
                )
                attempts.append(evidence)
                if self.attempt_callback is not None:
                    self.attempt_callback(url, evidence)
                if response.status not in self.RETRYABLE or attempt == self.max_attempts:
                    raise HttpContractError(f"HTTP {response.status} for {url}")
            if attempt < self.max_attempts:
                self.sleep(self.initial_backoff_seconds * (2 ** (attempt - 1)))
        raise HttpContractError(f"request exhausted without an accepted response: {url}")

    @staticmethod
    def _evidence(
        url: str,
        response: HttpResponse,
        attempts: tuple[AttemptEvidence, ...],
        wall_seconds: float,
    ) -> RetrievalEvidence:
        return RetrievalEvidence(
            url=url,
            status=response.status,
            headers=response.headers,
            body=response.body,
            sha256=hashlib.sha256(response.body).hexdigest(),
            size_bytes=len(response.body),
            wall_seconds=wall_seconds,
            attempts=attempts,
        )

    def fetch_index(self, url: str) -> RetrievalEvidence:
        response, attempts, wall = self._request(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"},
            accepted_statuses=frozenset({200}),
        )
        if not response.body:
            raise HttpContractError(f"empty HRRR index response: {url}")
        try:
            response.body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HttpContractError(f"HRRR index is not UTF-8 text: {url}") from exc
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) != len(response.body):
            raise HttpContractError("index Content-Length disagrees with body size")
        return self._evidence(url, response, attempts, wall)

    def fetch_object(self, url: str) -> RetrievalEvidence:
        """Fetch one complete non-GRIB pilot object with the same retry ledger."""

        response, attempts, wall = self._request(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"},
            accepted_statuses=frozenset({200}),
        )
        if not response.body:
            raise HttpContractError(f"empty object response: {url}")
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) != len(response.body):
            raise HttpContractError("object Content-Length disagrees with body size")
        return self._evidence(url, response, attempts, wall)

    def fetch_range_span(self, url: str, start: int, end: int) -> RetrievalEvidence:
        """Fetch and verify one exact byte span without assuming one GRIB message.

        A span may contain one or more exactly adjacent GRIB messages.  Callers
        remain responsible for splitting the accepted payload at frozen index
        offsets and validating every constituent message independently.
        """

        start, end = int(start), int(end)
        if start < 0 or end < start:
            raise ValueError("byte range must be nonnegative and ordered")
        response, attempts, wall = self._request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "identity",
                "Range": f"bytes={start}-{end}",
            },
            accepted_statuses=frozenset({206}),
        )
        expected = end - start + 1
        if len(response.body) != expected:
            raise HttpContractError(
                f"range response length mismatch: expected {expected}, received {len(response.body)}"
            )
        content_range = response.headers.get("content-range", "")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range)
        if not match or int(match.group(1)) != start or int(match.group(2)) != end:
            raise HttpContractError("Content-Range does not match requested byte interval")
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) != expected:
            raise HttpContractError("range Content-Length disagrees with requested byte count")
        return self._evidence(url, response, attempts, wall)

    def fetch_range(self, url: str, start: int, end: int) -> RetrievalEvidence:
        """Fetch one exact, independently framed GRIB message."""

        evidence = self.fetch_range_span(url, start, end)
        response_body = evidence.body
        if not (response_body.startswith(b"GRIB") and response_body.endswith(b"7777")):
            raise HttpContractError("range payload is not one framed GRIB message")
        return evidence

    def fetch_parent_size(self, url: str) -> tuple[int, RetrievalEvidence]:
        """Obtain parent length with a one-byte range when the selected record is last."""

        response, attempts, wall = self._request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "identity",
                "Range": "bytes=0-0",
            },
            accepted_statuses=frozenset({206}),
        )
        if len(response.body) != 1:
            raise HttpContractError("parent-size probe did not return exactly one byte")
        size = parent_size_from_content_range(response.headers)
        if size is None or size < 1:
            raise HttpContractError("parent-size probe lacks a finite Content-Range total")
        return size, self._evidence(url, response, attempts, wall)


def parent_size_from_content_range(headers: Mapping[str, str]) -> int | None:
    """Return the parent-object size carried by a verified range response."""

    value = _normalise_headers(headers).get("content-range", "")
    match = re.fullmatch(r"bytes \d+-\d+/(\d+|\*)", value)
    if not match or match.group(1) == "*":
        return None
    return int(match.group(1))


def coalesce_exact_adjacent_ranges(
    source_uri: str, members: Sequence[MessageRange]
) -> tuple[TransportRangeGroup, ...]:
    """Group disjoint inclusive ranges only when they touch exactly."""

    ordered = sorted(
        (
            MessageRange(str(member.request_id), int(member.start), int(member.end))
            for member in members
        ),
        key=lambda member: (member.start, member.end, member.request_id),
    )
    if not ordered:
        return ()
    if len({member.request_id for member in ordered}) != len(ordered):
        raise HttpContractError(f"duplicate request IDs in source object: {source_uri}")
    for member in ordered:
        if member.start < 0 or member.end < member.start:
            raise HttpContractError(
                f"invalid byte range for {member.request_id}: {member.start}-{member.end}"
            )

    raw_groups: list[list[MessageRange]] = []
    current: list[MessageRange] = []
    for member in ordered:
        if current and member.start <= current[-1].end:
            raise HttpContractError(
                f"overlapping ranges in {source_uri}: "
                f"{current[-1].request_id} and {member.request_id}"
            )
        if current and member.start != current[-1].end + 1:
            raw_groups.append(current)
            current = []
        current.append(member)
    raw_groups.append(current)

    groups: list[TransportRangeGroup] = []
    for raw_group in raw_groups:
        identity = {
            "source_uri": source_uri,
            "members": [
                {
                    "request_id": member.request_id,
                    "range_start": member.start,
                    "range_end": member.end,
                }
                for member in raw_group
            ],
        }
        groups.append(
            TransportRangeGroup(
                group_id="TR_" + sha256_bytes(canonical_json_bytes(identity)),
                source_uri=source_uri,
                start=raw_group[0].start,
                end=raw_group[-1].end,
                members=tuple(raw_group),
            )
        )
    return tuple(groups)


def split_coalesced_payload(
    group: TransportRangeGroup, payload: bytes
) -> dict[str, bytes]:
    """Split a verified span and validate every constituent independently."""

    if len(payload) != group.end - group.start + 1:
        raise HttpContractError(f"coalesced payload length changed: {group.group_id}")
    output: dict[str, bytes] = {}
    consumed = 0
    for member in group.members:
        relative_start = member.start - group.start
        relative_end = member.end - group.start + 1
        constituent = payload[relative_start:relative_end]
        expected = member.end - member.start + 1
        if len(constituent) != expected or not (
            constituent.startswith(b"GRIB") and constituent.endswith(b"7777")
        ):
            raise HttpContractError(
                f"coalesced constituent failed framing/length validation: {member.request_id}"
            )
        output[member.request_id] = constituent
        consumed += len(constituent)
    if consumed != len(payload):
        raise HttpContractError(
            f"coalesced payload has bytes outside constituents: {group.group_id}"
        )
    return output
