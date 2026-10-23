from __future__ import annotations

import unittest

from kden_v375.contracts import ContractError, make_run_id, validate_run_id, validate_scope


class ContractTests(unittest.TestCase):
    def test_run_id_round_trip(self) -> None:
        run_id = make_run_id(
            5, "owner-full", "hourly", timestamp="20260912T120000Z"
        )
        identity = validate_run_id(run_id, step_no=5, scope="owner-full")
        self.assertEqual(identity.label, "hourly")

    def test_legacy_style_run_id_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            validate_run_id("fpv1_20260906_step08_owner_full_v2")

    def test_owner_scope_is_limited_to_steps_five_and_six(self) -> None:
        with self.assertRaises(ContractError):
            validate_scope(4, "owner-full")
        validate_scope(5, "owner-full")
        validate_scope(6, "owner-full")


if __name__ == "__main__":
    unittest.main()

