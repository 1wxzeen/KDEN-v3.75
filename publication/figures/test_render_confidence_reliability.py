"""Bounded publication-renderer checks; no raw weather, truth, or predictions."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from render_confidence_reliability import SERIES, plot_series, validate_data


class ConfidenceFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(Path(__file__).with_name("confidence_reliability.json").read_text())

    def test_saved_selection_summaries_are_accepted(self):
        self.assertIs(validate_data(self.data), self.data)

    def test_every_series_has_a_distinct_color(self):
        self.assertEqual(len({s["color"] for s in SERIES.values()}), 3)

    def test_plotted_colors_and_legend_artists_agree(self):
        for model in self.data["models"]:
            for annual in (False, True):
                points = model["strict_by_period"] if annual else model["pooled"]
                ax = Mock()
                observed, predicted, baseline = Mock(), Mock(), Mock()
                ax.errorbar.return_value.lines = [observed]
                ax.plot.side_effect = [[predicted], [baseline]]
                handles = plot_series(ax, points, list(range(len(points))), annual=annual)
                self.assertEqual(handles, [observed, predicted, baseline])
                self.assertEqual(ax.errorbar.call_args.kwargs["color"], SERIES["observed"]["color"])
                observed.set_label.assert_called_once_with(SERIES["observed"]["label"])
                self.assertEqual(ax.plot.call_args_list[0].kwargs["color"], SERIES["predicted"]["color"])
                self.assertEqual(ax.plot.call_args_list[0].kwargs["label"], SERIES["predicted"]["label"])
                self.assertEqual(ax.plot.call_args_list[1].kwargs["color"], SERIES["baseline"]["color"])
                self.assertEqual(ax.plot.call_args_list[1].kwargs["label"], SERIES["baseline"]["label"])

    def test_actual_coverage_is_not_replaced_with_nominal(self):
        for model in self.data["models"]:
            strict = model["pooled"][-1]
            self.assertEqual(strict["nominal_target"], 0.1)
            self.assertNotEqual(strict["retained_share"], strict["nominal_target"])
        self.assertNotEqual(self.data["models"][0]["pooled"][-1]["retained_share"],
                            self.data["models"][1]["pooled"][-1]["retained_share"])

    def test_sparse_2025_gam_result_is_preserved(self):
        gam = self.data["models"][1]["strict_by_period"][-1]
        self.assertEqual(gam["days_with_admissions"], 55)
        self.assertTrue(gam["sparse"])

    def test_invalid_baseline_probability_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["pooled"][0]["baseline_same_cases_hit"] = 20
        with self.assertRaisesRegex(ValueError, "probability"):
            validate_data(data)

    def test_missing_registered_target_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["pooled"].pop()
        with self.assertRaisesRegex(ValueError, "target"):
            validate_data(data)

    def test_replacement_annual_cutoff_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["strict_by_period"][0]["nominal_target"] = 0.25
        with self.assertRaisesRegex(ValueError, "strict rule"):
            validate_data(data)

    def test_missing_interval_is_not_fabricated(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["pooled"][0]["observed_hit_interval"]["lower"] = None
        with self.assertRaisesRegex(ValueError, "interval"):
            validate_data(data)

    def test_incorrect_sparse_flag_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][1]["strict_by_period"][-1]["sparse"] = False
        with self.assertRaisesRegex(ValueError, "sparse"):
            validate_data(data)

    def test_incorrect_annual_support_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["strict_by_period"][-1]["population_days"] = 365
        with self.assertRaisesRegex(ValueError, "annual support"):
            validate_data(data)

    def test_no_claim_of_shared_model_selection_cases(self):
        data = copy.deepcopy(self.data)
        data["selection"]["model_specific_cases"] = False
        with self.assertRaisesRegex(ValueError, "own cases"):
            validate_data(data)


if __name__ == "__main__":
    unittest.main()
