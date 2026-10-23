from __future__ import annotations

from collections import Counter
from pathlib import Path
import unittest

from kden_v375.prefit import p07_experiment as p07


ROOT = Path(__file__).resolve().parents[2]


class P07ExperimentTests(unittest.TestCase):
    def test_contract_names_only_frozen_features(self) -> None:
        config, digest = p07._load_config(ROOT)
        evidence = p07._validate_features(ROOT, config)
        self.assertEqual(len(digest), 64)
        self.assertEqual(
            evidence, {"feature_count": 433, "required_feature_count": 37}
        )

    def test_roles_and_nested_folds_are_target_day_grouped(self) -> None:
        config, _ = p07._load_config(ROOT)
        roles = p07._date_role_rows(p07._truth_metadata(ROOT))
        outer, inner, coverage = p07._fold_rows(config, roles)
        self.assertEqual(
            Counter(row["evidence_role"] for row in roles),
            {
                "DEVELOPMENT_SUPERVISED": 1707,
                "DEVELOPMENT_UNRESOLVED": 3,
                "SEALED_HOLDOUT": 365,
                "POST_HOLDOUT_TAIL": 5,
            },
        )
        self.assertEqual(len(outer), 6240)
        self.assertEqual(len(inner), 31200)
        self.assertEqual(len(coverage["outer"]), 3)
        self.assertEqual(len(coverage["inner"]), 15)
        self.assertTrue(
            all(
                row["assignment"] == "FINAL_EVALUATION_LOCKED"
                for row in outer
                if row["target_date"].isoformat() >= "2025-09-07"
            )
        )

    def test_adapter_schema_is_target_and_fold_free(self) -> None:
        names = set(p07.adapter_index_schema().names)
        self.assertNotIn("y_audited_f", names)
        self.assertNotIn("truth_qc_status", names)
        self.assertNotIn("fold_id", names)
        self.assertTrue(
            {"issue_state_id", "target_date", "feature_partition_path"} <= names
        )


if __name__ == "__main__":
    unittest.main()
