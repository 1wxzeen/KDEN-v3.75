"""Plot saved confidence diagnostics without importing project models or data.

Reads only the adjacent compact JSON. Requires Matplotlib and its NumPy dependency.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path

MODEL_IDS = ("ANEN", "GAM_LS_NORMAL")
TARGETS = (1.0, 0.75, 0.5, 0.25, 0.1)
PERIOD_IDS = ("OUTER_01", "OUTER_02", "OUTER_03")
PROBABILITIES = ("retained_share", "observed_hit", "predicted_hit", "baseline_same_cases_hit")
# Colors encode the measured role in every panel, not the model identity.
# Model names are supplied by the column titles; old per-model color metadata
# in the compact input is deliberately not used for this figure.
SERIES = {
    "observed": {"label": "Observed hit rate", "color": "#009e73"},
    "predicted": {"label": "Predicted hit probability", "color": "#d55e00"},
    "baseline": {"label": "Subhourly baseline, same cases", "color": "#2474a4"},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_data(data):
    require(data["schema_version"] == "KDEN_PUBLICATION_CONFIDENCE_RELIABILITY_V1", "Unknown figure schema")
    a = data["assessment"]
    require((a["start"], a["end"], a["days"], a["rows_per_model"]) ==
            ("2023-01-01", "2025-09-06", 980, 55848), "Changed development population")
    require(a["timezone"] == "America/Denver" and a["issue_window"] == "02:00–16:00", "Wrong issue window")
    require(tuple(p["fold_id"] for p in a["periods"]) == PERIOD_IDS, "Wrong assessment periods")
    require(tuple(data["selection"]["nominal_targets"]) == TARGETS, "Changed registered targets")
    require(data["selection"]["strictest_target"] == 0.1, "Changed strict selection rule")
    require(data["selection"]["model_specific_cases"] is True, "Model selectors must retain their own cases")
    uncertainty = data["uncertainty"]
    require((uncertainty["level"], uncertainty["block_days"], uncertainty["replicates"],
             uncertainty["adjustment"]) == (0.95, 7, 5000, "none"), "Changed interval semantics")
    require(tuple(m["model_id"] for m in data["models"]) == MODEL_IDS, "Unexpected model set")
    for model in data["models"]:
        require(tuple(p["nominal_target"] for p in model["pooled"]) == TARGETS, "Missing or duplicate selection target")
        require(tuple(p["fold_id"] for p in model["strict_by_period"]) == PERIOD_IDS, "Missing annual result")
        for i, point in enumerate(model["pooled"] + model["strict_by_period"]):
            for key in PROBABILITIES:
                v = point[key]
                require(isinstance(v, (float, int)) and not isinstance(v, bool)
                        and math.isfinite(v) and 0 <= v <= 1, "Invalid probability or coverage")
            ci = point["observed_hit_interval"]
            require(ci["quantiles"] == [0.025, 0.975] and ci["undefined_fraction"] == 0,
                    "Missing or undefined observed interval")
            lo, hi = ci["lower"], ci["upper"]
            require(lo is not None and hi is not None and math.isfinite(lo) and math.isfinite(hi)
                    and 0 <= lo <= point["observed_hit"] <= hi <= 1, "Invalid observed interval")
            require(0 < point["days_with_admissions"] <= point["population_days"], "Invalid admitted day count")
            require(point["days_with_admissions"] <= point["admitted_rows"] <= point["expected_rows"],
                    "Invalid admitted row count")
            require(point["sparse"] is (point["days_with_admissions"] < 60), "Incorrect sparse-support flag")
            if i < len(TARGETS):
                require((point["population_days"], point["expected_rows"]) == (980, 55848), "Wrong pooled support")
            else:
                j = i - len(TARGETS)
                require(point["nominal_target"] == 0.1, "Annual result is not the strict rule")
                require((point["population_days"], point["expected_rows"]) ==
                        ((365, 20801), (366, 20858), (249, 14189))[j], "Wrong annual support")
        full = model["pooled"][0]
        require(full["retained_share"] == 1 and full["admitted_rows"] == 55848
                and full["days_with_admissions"] == 980, "Full-coverage rule is incomplete")
    return data


def plot_series(ax, points, x, annual=False):
    offsets = (-0.13, 0, 0.13) if annual else (0, 0, 0)
    observed = [100 * p["observed_hit"] for p in points]
    lo = [100 * (p["observed_hit"] - p["observed_hit_interval"]["lower"]) for p in points]
    hi = [100 * (p["observed_hit_interval"]["upper"] - p["observed_hit"]) for p in points]
    observed_artist = ax.errorbar([v + offsets[0] for v in x], observed, yerr=[lo, hi],
                color=SERIES["observed"]["color"], marker="o", markersize=5.5, linewidth=1.9,
                ecolor="#26384a", elinewidth=0.8, capsize=2.5, zorder=3)
    observed_artist.lines[0].set_label(SERIES["observed"]["label"])
    predicted_artist, = ax.plot([v + offsets[1] for v in x], [100 * p["predicted_hit"] for p in points],
            color=SERIES["predicted"]["color"], label=SERIES["predicted"]["label"],
            marker="D", markerfacecolor="white", markersize=5.5,
            linestyle="--", linewidth=1.6, zorder=4)
    baseline_artist, = ax.plot([v + offsets[2] for v in x], [100 * p["baseline_same_cases_hit"] for p in points],
            color=SERIES["baseline"]["color"], label=SERIES["baseline"]["label"],
            marker="s", markersize=4.5, linestyle=":",
            linewidth=1.8, zorder=4)
    return [observed_artist.lines[0], predicted_artist, baseline_artist]


def render(data, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    validate_data(data)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10.5,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#59616b", "text.color": "#17263a",
        "axes.labelcolor": "#26384a", "xtick.color": "#46576b",
        "ytick.color": "#46576b", "figure.facecolor": "white",
        "axes.facecolor": "white", "svg.fonttype": "none",
    })
    fig = plt.figure(figsize=(13.5, 9.4))
    grid = fig.add_gridspec(2, 2, left=0.07, right=0.985, top=0.79, bottom=0.17,
                            wspace=0.20, hspace=0.69)
    axes = [[fig.add_subplot(grid[row, col]) for col in range(2)] for row in range(2)]
    for col, model in enumerate(data["models"]):
        ax = axes[0][col]
        points = sorted(model["pooled"], key=lambda p: p["retained_share"])
        handles = plot_series(ax, points, [100 * p["retained_share"] for p in points])
        ax.set_title(model["label"], fontsize=13, fontweight="bold", loc="left", pad=10)
        ax.set(xlim=(0, 104), ylim=(12, 38), xlabel="Forecasts retained (day-weighted %)",
               xticks=[0, 25, 50, 75, 100], yticks=[15, 20, 25, 30, 35])
        ax.xaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))

        bottom = axes[1][col]
        points = model["strict_by_period"]
        plot_series(bottom, points, list(range(3)), annual=True)
        labels = []
        for period, p in zip(data["assessment"]["periods"], points):
            dagger = "†" if p["sparse"] else ""
            labels.append(f'{period["label"]}\n{100*p["retained_share"]:.2f}% retained\n{p["days_with_admissions"]} days{dagger}')
        bottom.set(xlim=(-0.4, 2.4), ylim=(0, 45), xticks=[0, 1, 2],
                   xticklabels=labels, yticks=[0, 10, 20, 30, 40])
        bottom.tick_params(axis="x", labelsize=9.5)
        for item in (ax, bottom):
            item.set_ylabel("Exact-temperature hit rate")
            item.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
            item.grid(axis="y", color="#dce3ea", linewidth=0.65)
            item.set_axisbelow(True)

    fig.suptitle("Did confident forecasts deliver?", x=0.07, y=0.985, ha="left",
                 fontsize=18, fontweight="bold")
    fig.text(0.07, 0.945,
             "980 development days · 02:00–16:00 America/Denver · Jan 1, 2023–Sep 6, 2025",
             fontsize=11, color="#46576b")
    # Use the actual plotted artists so legend swatches cannot drift from them.
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.064, 0.92),
               ncol=3, frameon=False, handlelength=3.2, columnspacing=3.0, fontsize=10.5)
    fig.text(0.07, 0.845, "A · Pooled confidence versus actual coverage", fontsize=12,
             fontweight="bold")
    fig.text(0.07, 0.455, "B · Strictest registered confidence rule by year (nominal 10% retention)",
             fontsize=12, fontweight="bold")
    fig.text(0.07, 0.08,
             "*2025 ends September 6. †55 selected GAM days: below the registered 60-day slice threshold.",
             fontsize=9.5, color="#46576b")
    fig.text(0.07, 0.052,
             "Whiskers: saved descriptive 95% seven-day block intervals. Model selectors admit different cases.",
             fontsize=9.5, color="#46576b")
    fig.text(0.07, 0.024,
             "Previously inspected development evidence; the disclosed selection-timing qualification applies. No new cutoff was fitted.",
             fontsize=9.0, color="#46576b")
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for artist in list(fig.texts) + list(fig.legends):
        box = artist.get_window_extent(renderer)
        require(box.x0 >= 0 and box.y0 >= 0 and box.x1 <= fig.bbox.width + 1
                and box.y1 <= fig.bbox.height + 1, "Clipped figure annotation")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_dir / "confidence_reliability"
    fig.savefig(stem.with_suffix(".png"), dpi=180, facecolor="white",
                metadata={"Title": "KDEN: did confident forecasts deliver?",
                          "Description": "Saved confidence-selection diagnostics, with matched-case baselines and descriptive uncertainty. No models refitted."})
    fig.savefig(stem.with_suffix(".svg"), facecolor="white",
                metadata={"Title": "KDEN: did confident forecasts deliver?",
                          "Description": "Historical development evidence; thresholds, support, uncertainty, and timing qualifications are documented in the publication figure notes.",
                          "Date": None})
    plt.close(fig)
    return stem.with_suffix(".png"), stem.with_suffix(".svg")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).with_name("confidence_reliability.json"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    data = validate_data(json.loads(args.data.read_text()))
    outputs = render(data, args.output_dir or Path(tempfile.mkdtemp(prefix="kden-reliability-")))
    print(json.dumps({"outputs": [str(p) for p in outputs], "selection_summaries": 16,
                      "model_fits_performed": 0}, indent=2))


if __name__ == "__main__":
    main()
