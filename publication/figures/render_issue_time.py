"""Render the public issue-time figure from compact saved development summaries.

This script has no project or model imports and reads no prediction/truth pages.
Dependencies: matplotlib (including its NumPy dependency).
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path

MODEL_IDS = ("B0_H", "B0_Q", "ANEN", "GAM_LS_NORMAL")
METRICS = ("mae", "modal_integer_hit", "negative_log_score")
EXPECTED_TIMES = tuple(f"{m // 60:02d}:{m % 60:02d}" for m in range(120, 961, 15))
DISPLAY = (
    ("mae", "Point error ↓", "MAE (°F)", 1),
    ("modal_integer_hit", "Exact-temperature hits ↑", "Modal integer hit (%)", 100),
    ("negative_log_score", "Probability loss ↓", "Log loss (nats)", 1),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_data(data):
    require(data["schema_version"] == "KDEN_PUBLICATION_ISSUE_TIME_DEVELOPMENT_V1", "Unknown data schema")
    assessment = data["assessment"]
    require((assessment["start"], assessment["end"], assessment["unique_days"],
             assessment["rows_per_model"], assessment["issue_count"]) ==
            ("2023-01-01", "2025-09-06", 980, 55848, 57), "Changed assessment population")
    require(assessment["timezone"] == "America/Denver", "Wrong time-zone definition")
    require(tuple(m["model_id"] for m in data["models"]) == MODEL_IDS, "Unexpected model set or order")
    for model in data["models"]:
        points = model["points"]
        require(tuple(p["issue_time"] for p in points) == EXPECTED_TIMES, "Missing, duplicated, or reordered issue times")
        for point in points:
            expected = 977 if point["issue_time"] < "03:00" else 980
            require(point["days"] == point["rows"] == expected, "Model support mismatch")
            for key in METRICS:
                value = point[key]
                require(isinstance(value, (float, int)) and not isinstance(value, bool)
                        and math.isfinite(value) and value >= 0, "Invalid metric value")
            require(point["modal_integer_hit"] <= 1, "Hit rate must be a proportion")
        require(sum(p["rows"] for p in points) == 55848, "Incorrect row total")
    return data


def render(data, output_dir):
    # Select a noninteractive backend before importing pyplot. Setting the
    # Matplotlib cache location, when necessary, is the caller's responsibility.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator, PercentFormatter

    validate_data(data)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10.5,
        "axes.titlesize": 12, "axes.labelsize": 10.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#59616b", "text.color": "#17263a",
        "axes.labelcolor": "#26384a", "xtick.color": "#46576b",
        "ytick.color": "#46576b", "figure.facecolor": "white",
        "axes.facecolor": "white", "svg.fonttype": "none",
    })
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.3))
    fig.subplots_adjust(left=0.065, right=0.985, top=0.70, bottom=0.29, wspace=0.30)
    for ax, (key, title, ylabel, factor) in zip(axes, DISPLAY):
        for model in data["models"]:
            x = [int(p["issue_time"][:2]) + int(p["issue_time"][3:]) / 60 for p in model["points"]]
            y = [factor * p[key] for p in model["points"]]
            ax.plot(x, y, label=model["label"], color=model["color"],
                    linestyle=model["line_style"], linewidth=1.9,
                    solid_capstyle="round")
        ax.set_title(title, loc="left", pad=12, fontweight="bold", color="#17263a")
        ax.set_ylabel(ylabel)
        ax.set_xlim(1.75, 16.25)
        ax.set_xticks([2, 6, 10, 14, 16], ["02:00", "06:00", "10:00", "14:00", "16:00"])
        ax.tick_params(axis="both", labelsize=9.5)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=4))
        if key == "modal_integer_hit":
            ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
        ax.grid(axis="y", color="#dce3ea", linewidth=0.65, alpha=0.8)
        ax.set_axisbelow(True)
        ax.margins(y=0.12)
    fig.suptitle("Forecast accuracy through the day", x=0.065, y=0.985,
                 ha="left", fontsize=17, fontweight="bold")
    fig.text(0.065, 0.91,
             "Saved development forecasts · Jan 1, 2023–Sep 6, 2025 · identical model cases at each issue",
             ha="left", fontsize=10.5, color="#46576b")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.06, 0.865),
               ncol=4, frameon=False, handlelength=3.3, columnspacing=2.0, fontsize=10.5)
    fig.text(0.525, 0.17, "Forecast issue time (America/Denver)", ha="center", fontsize=11)
    fig.text(0.065, 0.09,
             "02:00–02:45: 977 days; 03:00–16:00: 980 days. Three spring-forward dates lack the 02:00 hour.",
             fontsize=9.5, color="#46576b")
    fig.text(0.065, 0.04,
             "Descriptive 15-minute summaries; no smoothing or uncertainty bands. The disclosed selection-timing qualification applies.",
             fontsize=9.0, color="#46576b")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_dir / "issue_time_development"
    fig.savefig(stem.with_suffix(".png"), dpi=180, facecolor="white",
                metadata={"Title": "KDEN forecast accuracy through the day",
                          "Description": "Four models on identical saved development cases at each issue; no smoothing. Selection-timing qualification applies."})
    fig.savefig(stem.with_suffix(".svg"), facecolor="white",
                metadata={"Title": "KDEN forecast accuracy through the day",
                          "Description": "Historical development summaries; identical model cases at each issue. Read the publication figure notes for definitions, support, and timing qualification.",
                          "Date": None})
    # Short layout check, not a scientific acceptance scan.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for artist in list(fig.texts) + list(fig.legends):
        bbox = artist.get_window_extent(renderer)
        require(bbox.x0 >= 0 and bbox.y0 >= 0
                and bbox.x1 <= fig.bbox.width + 1
                and bbox.y1 <= fig.bbox.height + 1, "Figure annotation clipped")
    plt.close(fig)
    return (stem.with_suffix(".png"), stem.with_suffix(".svg"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).with_name("issue_time_development.json"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    data = validate_data(json.loads(args.data.read_text()))
    outputs = render(data, args.output_dir or Path(tempfile.mkdtemp(prefix="kden-issue-time-")))
    print(json.dumps({"outputs": [str(p) for p in outputs], "models": 4,
                      "times_per_model": 57, "model_fits_performed": 0}, indent=2))


if __name__ == "__main__":
    main()
