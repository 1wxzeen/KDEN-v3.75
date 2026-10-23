"""Replot saved aggregate scores; no fitting, downloads, or individual rows."""
import argparse
import json
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = root / "universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/scorecards.json"
    cards = json.loads(source.read_text())
    models = ["ANEN", "B0_H", "B0_Q", "GAM_LOCATION_NORMAL", "GAM_LS_NORMAL", "GAM_LS_T5"]
    assert set(cards) == set(models)
    names = ["AnEn", "Hourly baseline", "Subhourly baseline", "Constant-scale GAM", "Location–scale GAM", "Student-t GAM"]
    colors = ["#777777", "#e15759", "#2474a4", "#d47722", "#9774ad", "#378365"]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 120, "savefig.dpi": 150})
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, key, label, scale in zip(axes,
            ["mae", "modal_integer_hit", "negative_log_score"],
            ["MAE (°F), lower better", "Exact integer hit (%), higher better", "Negative log score (nats), lower better"],
            [1, 100, 1]):
        values = [cards[m]["overall"]["ALL"]["metrics"][key] * scale for m in models]
        intervals = [cards[m]["overall"]["ALL"]["intervals"][key] for m in models]
        ax.barh(range(len(models)), values, color=colors)
        ax.errorbar(values, range(len(models)), xerr=[
            [max(0, v - c["lower"] * scale) for v, c in zip(values, intervals)],
            [max(0, c["upper"] * scale - v) for v, c in zip(values, intervals)]],
            fmt="none", color="black", capsize=2)
        ax.set_yticks(range(len(models)), names)
        ax.invert_yaxis()
        ax.set_xlabel(label)
    fig.suptitle("980 days · identical support · descriptive 95% seven-day block intervals")
    fig.tight_layout(rect=(0, 0, 1, .97))
    output = args.output_dir or Path(tempfile.mkdtemp(prefix="kden-scorecard-"))
    output.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg"):
        fig.savefig(output / f"overall_scorecard.{extension}", bbox_inches="tight")
    plt.close(fig)
    print(json.dumps({"output_directory": str(output), "model_fits": 0, "individual_rows_read": 0}))


if __name__ == "__main__":
    main()
