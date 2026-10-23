from __future__ import annotations

import threading
import time
import unittest

from kden_v375.execution import execute_bounded


class ExecutionTests(unittest.TestCase):
    def test_worker_results_commit_in_plan_order_on_coordinator(self) -> None:
        coordinator = threading.get_ident()
        committed: list[tuple[int, int]] = []

        def worker(value: int) -> int:
            time.sleep((3 - value) * 0.001)
            return value

        def commit(value: int) -> None:
            committed.append((value, threading.get_ident()))

        summary = execute_bounded(
            [0, 1, 2, 3], worker=worker, commit=commit, max_workers=2
        )
        self.assertEqual([value for value, _ in committed], [0, 1, 2, 3])
        self.assertEqual({thread for _, thread in committed}, {coordinator})
        self.assertEqual(summary.committed_count, 4)


if __name__ == "__main__":
    unittest.main()

