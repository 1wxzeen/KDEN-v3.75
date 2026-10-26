"""Standard-library checks of the bundled synthetic illustration record."""

import json
import math
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class MathematicalIllustrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads(
            (ROOT / "mathematical_illustration_checks.json").read_text(encoding="utf-8")
        )

    def test_synthetic_scope_and_moments(self):
        record = self.record
        self.assertEqual(record["status"], "PASS")
        self.assertTrue(record["all_inputs_synthetic"])
        for name in ("project_data_files_read", "project_modules_imported",
                     "model_fits_performed"):
            self.assertEqual(record[name], 0)
        example = record["analog_illustration"]
        residuals = [
            actual - anchor for actual, anchor in zip(
                example["historical_outcomes_f"], example["historical_anchors_f"]
            )
        ]
        self.assertEqual(residuals, example["residuals_f"])
        weights = example["illustrative_weights"]
        self.assertTrue(all(weight >= 0 for weight in weights))
        self.assertAlmostEqual(sum(weights), 1)
        residual_mean = sum(w * r for w, r in zip(weights, residuals))
        self.assertAlmostEqual(
            example["current_anchor_f"] + residual_mean, example["continuous_mean_f"]
        )
        variance = example["kernel_sigma_f"] ** 2 + sum(
            w * (r - residual_mean) ** 2 for w, r in zip(weights, residuals)
        )
        self.assertAlmostEqual(variance, example["continuous_variance_f_squared"])
        self.assertAlmostEqual(example["integer_probability_sum"], 1)
        self.assertAlmostEqual(example["numerical_integral"], 1)
        self.assertAlmostEqual(
            1 / sum(w * w for w in weights), example["effective_sample_size"]
        )
        shape = record["shape_illustration"]
        mean = sum(w * c for w, c in zip(
            shape["mixture_weights"], shape["mixture_centers_f"]
        ))
        variance = shape["mixture_component_sigma_f"] ** 2 + sum(
            w * (c - mean) ** 2 for w, c in zip(
                shape["mixture_weights"], shape["mixture_centers_f"]
            )
        )
        self.assertAlmostEqual(mean, shape["shared_shape_comparison_mean_f"])
        self.assertAlmostEqual(variance, shape["shared_shape_comparison_variance_f_squared"])
        scales = record["scale_link_test_values_f"]
        self.assertTrue(all(math.isfinite(s) and 0.25 <= s <= 20 for s in scales))
        self.assertTrue(all(a < b for a, b in zip(scales, scales[1:])))

    def test_explicit_panel_numbers_and_disclosure(self):
        expected = {
            "analog_residual_transfer.svg": (
                "1. Historical errors",
                "2. Today's anchor + old errors",
                "3. Integrate integer bins",
            ),
            "location_spread_shape.svg": (
                "1. Shift the center; keep the width",
                "2. Keep the center; vary the width",
                "3. Same mean and variance; new shape",
            ),
        }
        for filename, labels in expected.items():
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn("SYNTHETIC ILLUSTRATION", text)
            for label in labels:
                self.assertIn(label, text)
            self.assertNotIn("<script", text.lower())


if __name__ == "__main__":
    unittest.main()
