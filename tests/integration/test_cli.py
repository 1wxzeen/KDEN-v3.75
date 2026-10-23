from __future__ import annotations

import contextlib
import io
import unittest

from kden_v375.cli import STEP_MODULES, main


class CliTests(unittest.TestCase):
    def test_all_required_commands_parse(self) -> None:
        for argv in (
            ["run-step", "0", "--run-id", "kdenv375-s00-synthetic-20260912T120000Z-cli"],
            ["status"],
            ["live-status", "--run-id", "kdenv375-s04-synthetic-20260912T120000Z-cli"],
            ["eta", "--run-id", "kdenv375-s04-synthetic-20260912T120000Z-cli"],
            ["pilot-preflight"],
            ["acquisition-preflight"],
            ["pause-run", "kdenv375-s05-owner-full-20260912T120000Z-hourly"],
            ["resume", "kdenv375-s05-owner-full-20260912T120000Z-hourly"],
            ["validate-only", "--step", "0"],
        ):
            with self.subTest(argv=argv):
                parser = __import__("kden_v375.cli", fromlist=["build_parser"]).build_parser()
                parsed = parser.parse_args(argv)
                self.assertTrue(parsed.command)

    def test_help_surface_is_available(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        for command in (
            "run-step",
            "status",
            "live-status",
            "eta",
            "pilot-preflight",
            "acquisition-preflight",
            "pause-run",
            "resume",
            "validate-only",
        ):
            self.assertIn(command, output.getvalue())

    def test_step03_dispatches_to_r14_without_overwriting_historical_planner(self) -> None:
        self.assertEqual(
            STEP_MODULES[3],
            "kden_v375.steps.step_03_r14_request_plans",
        )

    def test_step04_dispatches_to_r14_confirmation_pilot(self) -> None:
        from kden_v375.pilot import PILOT_DESIGN_PATH

        self.assertEqual(STEP_MODULES[4], "kden_v375.steps.step_04_pilot")
        self.assertEqual(PILOT_DESIGN_PATH, "config/pilot_design_r14_v375.json")

    def test_step05_dispatches_to_unified_r14_acquisition(self) -> None:
        self.assertEqual(
            STEP_MODULES[5], "kden_v375.steps.step_05_r14_acquisition"
        )


if __name__ == "__main__":
    unittest.main()
