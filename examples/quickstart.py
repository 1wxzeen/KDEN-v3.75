"""Inspect bundled aggregates offline; no model fitting or individual labels."""
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "publication/figures/issue_time_development.json").read_text())
    assessment = data["assessment"]
    print("KDEN v3.75 — bundled historical development evidence")
    print(f"Assessment: {assessment['start']} to {assessment['end']}")
    print(f"Days: {assessment['unique_days']}; issues/model: {assessment['rows_per_model']}")
    print("Issue-time examples (MAE °F / exact-integer hit / log loss nats):")
    for model in data["models"]:
        points = model["points"]
        assert len(points) == assessment["issue_count"] == 57
        for point in (points[0], points[-1]):
            print(f"  {model['label']:24} {point['issue_time']}  "
                  f"{point['mae']:.3f} / {point['modal_integer_hit']:.2%} / "
                  f"{point['negative_log_score']:.3f}  ({point['days']} days)")
    print("No raw weather, individual truth, download, fit, or blind test was used.")
    print("Read README.md for scoring definitions and the selection-timing qualification.")


if __name__ == "__main__":
    main()
