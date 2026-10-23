"""Bounded worker execution with deterministic single-coordinator commits."""

from __future__ import annotations

import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Generic, Sequence, TypeVar


InputT = TypeVar("InputT")
ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    submitted_count: int
    committed_count: int
    paused: bool
    remaining_count: int


def execute_bounded(
    items: Sequence[InputT],
    *,
    worker: Callable[[InputT], ResultT],
    commit: Callable[[ResultT], None],
    max_workers: int,
    pause_requested: Callable[[], bool] = lambda: False,
) -> ExecutionSummary:
    """Run workers concurrently and commit results on the calling thread.

    At most ``2 * max_workers`` work units are in flight. Results are buffered
    and committed in input order, so concurrency cannot change durable progress
    ordering. Once a pause is observed, no new work is submitted; already
    running atomic units are drained and committed before returning.
    """

    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    coordinator_thread = threading.get_ident()
    total = len(items)
    next_submit = 0
    next_commit = 0
    submitted = 0
    completed: dict[int, ResultT] = {}
    futures: dict[Future[ResultT], int] = {}
    paused = False
    window = max_workers * 2

    def submit_available(executor: ThreadPoolExecutor) -> None:
        nonlocal next_submit, submitted, paused
        while next_submit < total and len(futures) + len(completed) < window:
            if pause_requested():
                paused = True
                return
            ordinal = next_submit
            futures[executor.submit(worker, items[ordinal])] = ordinal
            next_submit += 1
            submitted += 1

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="kden-v375") as executor:
        submit_available(executor)
        try:
            while futures:
                done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    ordinal = futures.pop(future)
                    completed[ordinal] = future.result()
                while next_commit in completed:
                    if threading.get_ident() != coordinator_thread:  # defensive
                        raise RuntimeError("durable commit left the coordinator thread")
                    commit(completed.pop(next_commit))
                    next_commit += 1
                if pause_requested():
                    paused = True
                if not paused:
                    submit_available(executor)
        except BaseException:
            for future in futures:
                future.cancel()
            raise

    return ExecutionSummary(
        submitted_count=submitted,
        committed_count=next_commit,
        paused=paused and next_submit < total,
        remaining_count=total - next_commit,
    )
