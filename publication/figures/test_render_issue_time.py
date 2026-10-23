"""Small checks for the publication-only renderer; no project data access."""
import copy
import json
from pathlib import Path
import unittest

from render_issue_time import validate_data


class IssueTimeFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(Path(__file__).with_name("issue_time_development.json").read_text())

    def test_saved_population_is_accepted(self):
        self.assertIs(validate_data(self.data), self.data)

    def test_four_models_share_each_issue_support(self):
        supports = [[(p["issue_time"], p["days"], p["rows"]) for p in m["points"]]
                    for m in self.data["models"]]
        self.assertTrue(all(s == supports[0] for s in supports[1:]))
        self.assertEqual(sum(p["rows"] for p in self.data["models"][0]["points"]), 55848)

    def test_mismatched_model_support_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][1]["points"][0]["days"] = 978
        with self.assertRaisesRegex(ValueError, "support"):
            validate_data(data)

    def test_duplicate_issue_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["points"][1]["issue_time"] = "02:00"
        with self.assertRaisesRegex(ValueError, "issue times"):
            validate_data(data)

    def test_nonfinite_metric_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["points"][0]["mae"] = float("nan")
        with self.assertRaisesRegex(ValueError, "metric"):
            validate_data(data)

    def test_percentage_instead_of_proportion_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["points"][0]["modal_integer_hit"] = 20.0
        with self.assertRaisesRegex(ValueError, "proportion"):
            validate_data(data)

    def test_changed_assessment_dates_are_rejected(self):
        data = copy.deepcopy(self.data)
        data["assessment"]["end"] = "2026-09-06"
        with self.assertRaisesRegex(ValueError, "population"):
            validate_data(data)

    def test_negative_metric_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["models"][0]["points"][0]["negative_log_score"] = -1
        with self.assertRaisesRegex(ValueError, "metric"):
            validate_data(data)


if __name__ == "__main__":
    unittest.main()
