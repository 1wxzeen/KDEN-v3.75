from __future__ import annotations

import unittest

from kden_v375.io.http_range import (
    HttpContractError,
    HttpResponse,
    MessageRange,
    VerifiedHttpClient,
    coalesce_exact_adjacent_ranges,
    split_coalesced_payload,
)


class RangeTests(unittest.TestCase):
    def test_exact_adjacent_coalescence_and_split(self) -> None:
        first = b"GRIBa7777"
        second = b"GRIBb7777"
        groups = coalesce_exact_adjacent_ranges(
            "source", (MessageRange("a", 0, 8), MessageRange("b", 9, 17))
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(split_coalesced_payload(groups[0], first + second), {"a": first, "b": second})

    def test_gap_does_not_coalesce(self) -> None:
        groups = coalesce_exact_adjacent_ranges(
            "source", (MessageRange("a", 0, 8), MessageRange("b", 10, 18))
        )
        self.assertEqual(len(groups), 2)

    def test_content_range_is_fail_closed(self) -> None:
        def transport(_url: str, _headers: dict[str, str], _timeout: float) -> HttpResponse:
            return HttpResponse(206, {"content-range": "bytes 1-9/10"}, b"GRIBx7777")

        client = VerifiedHttpClient(transport=transport, max_attempts=1)
        with self.assertRaises(HttpContractError):
            client.fetch_range("https://example.invalid", 0, 8)


if __name__ == "__main__":
    unittest.main()

