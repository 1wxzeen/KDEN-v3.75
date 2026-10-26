"""Render explicitly synthetic explanations; no KDEN data or models are read."""

from pathlib import Path
import argparse
import json
import math
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter
import numpy as np


BLUE = "#176B91"
ORANGE = "#CD6817"
GRAY = "#777D84"
RED = "#B84940"
TEAL = "#65A6A2"
INK = "#23313F"


def ndtr(x):
    """Normal CDF for these synthetic plots; not a production tail routine."""
    x = np.asarray(x, dtype=float)
    erf = np.vectorize(math.erf, otypes=[float])
    return 0.5 * (1 + erf(x / np.sqrt(2)))


def expit(x):
    return 1 / (1 + np.exp(-np.asarray(x, dtype=float)))

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "svg.fonttype": "none",
        "savefig.facecolor": "white",
    }
)


def normal_pdf(x, mean, scale):
    return np.exp(-0.5 * ((np.asarray(x) - mean) / scale) ** 2) / (
        scale * np.sqrt(2 * np.pi)
    )


def mixture_pdf(x, centers, weights, sigma):
    return np.sum(
        [
            weight * normal_pdf(x, center, sigma)
            for center, weight in zip(centers, weights)
        ],
        axis=0,
    )


def mixture_cdf(x, centers, weights, sigma):
    return np.sum(
        [
            weight * ndtr((np.asarray(x) - center) / sigma)
            for center, weight in zip(centers, weights)
        ],
        axis=0,
    )


def integer_pmf(centers, weights, sigma):
    support = np.arange(-40, 121)
    edges = np.r_[-np.inf, support[:-1] + 0.5, np.inf]
    probabilities = np.diff(mixture_cdf(edges, centers, weights, sigma))
    assert np.min(probabilities) >= -1e-14
    assert np.isclose(probabilities.sum(), 1, atol=1e-12)
    return support, probabilities


def tidy(ax):
    ax.grid(axis="y", color="#E8ECEF", linewidth=0.7)
    ax.set_axisbelow(True)


def save(fig, name, output_dir):
    for suffix in ["png", "svg"]:
        fig.savefig(output_dir / f"{name}.{suffix}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def analog_figure(output_dir):
    historical_anchors = np.array([71.0, 77.0, 74.0, 78.0])
    historical_outcomes = np.array([69.0, 76.0, 76.0, 82.0])
    residuals = historical_outcomes - historical_anchors
    weights = np.array([0.40, 0.25, 0.25, 0.10])
    current_anchor = 73.0
    sigma = 0.8
    centers = current_anchor + residuals
    fig, axes = plt.subplots(
        1, 3, figsize=(15.8, 4.8), gridspec_kw={"width_ratios": [1.0, 1.30, 1.05]}
    )
    fig.subplots_adjust(top=0.74, bottom=0.18, wspace=0.35)
    fig.suptitle(
        "Transfer the forecast error—not the historical temperature",
        fontsize=17,
        x=0.5,
        y=0.98,
    )
    fig.text(
        0.5,
        0.90,
        "SYNTHETIC ILLUSTRATION  |  Invented values and weights; no measured KDEN performance",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    ax = axes[0]
    ypos = np.arange(4)
    for index, (forecast, observed, residual) in enumerate(
        zip(historical_anchors, historical_outcomes, residuals)
    ):
        ax.plot([forecast, observed], [index, index], color="#B9C4CB", linewidth=2)
        ax.text(
            (forecast + observed) / 2,
            index - 0.17,
            f"{residual:+.0f}°F",
            ha="center",
            va="bottom",
            fontsize=10,
        )
    ax.scatter(historical_anchors, ypos, s=48, color=GRAY, zorder=3, label="HRRR anchor")
    ax.scatter(
        historical_outcomes,
        ypos,
        marker="D",
        s=42,
        color=BLUE,
        zorder=3,
        label="Observed maximum",
    )
    ax.set(
        title="1. Historical errors",
        xlabel="Temperature (°F)",
        yticks=ypos,
        yticklabels=["Day A", "Day B", "Day C", "Day D"],
        xlim=(67.5, 83.5),
        ylim=(3.5, -0.8),
    )
    ax.legend(loc="lower left", bbox_to_anchor=(-0.02, -0.43), frameon=False, fontsize=9)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)

    ax = axes[1]
    x = np.linspace(67, 81, 1600)
    for center, weight in zip(centers, weights):
        ax.plot(x, weight * normal_pdf(x, center, sigma), color=TEAL, linewidth=1.4)
    density = mixture_pdf(x, centers, weights, sigma)
    ax.fill_between(x, density, color=BLUE, alpha=0.10)
    ax.plot(x, density, color=BLUE, linewidth=2.7)
    ax.axvline(current_anchor, color=RED, linestyle="--", linewidth=1.5)
    ax.set(
        title="2. Today's anchor + old errors",
        xlabel="Possible maximum today (°F)",
        ylabel="Probability density (per °F)",
        xlim=(67, 81),
        ylim=(0, 0.34),
    )
    ax.legend(
        handles=[
            Line2D([0], [0], color=BLUE, lw=2.7, label="Weighted residual mixture"),
            Line2D([0], [0], color=TEAL, lw=1.4, label="Individual contributions"),
            Line2D([0], [0], color=RED, ls="--", label="Today's HRRR anchor: 73°F"),
        ],
        loc="upper right",
        frameon=False,
        fontsize=8.5,
    )
    tidy(ax)

    ax = axes[2]
    support, probabilities = integer_pmf(centers, weights, sigma)
    visible = (support >= 67) & (support <= 81)
    ax.bar(
        support[visible],
        probabilities[visible],
        width=0.82,
        color=BLUE,
        edgecolor="white",
        linewidth=0.6,
    )
    ax.set(
        title="3. Integrate integer bins",
        xlabel="Integer maximum (°F)",
        ylabel="Probability",
        xlim=(66.5, 81.5),
        ylim=(0, 0.26),
    )
    ax.set_xticks(np.arange(67, 82, 2))
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    tidy(ax)
    save(fig, "analog_residual_transfer", output_dir)

    fine_x = np.linspace(40, 105, 30000)
    fine_density = mixture_pdf(fine_x, centers, weights, sigma)
    theoretical_mean = float(current_anchor + weights @ residuals)
    theoretical_variance = float(
        sigma**2 + weights @ ((residuals - weights @ residuals) ** 2)
    )
    integral = float(np.trapezoid(fine_density, fine_x))
    numeric_mean = float(np.trapezoid(fine_x * fine_density, fine_x))
    numeric_variance = float(
        np.trapezoid((fine_x - theoretical_mean) ** 2 * fine_density, fine_x)
    )
    assert np.isclose(integral, 1, atol=1e-9)
    assert np.isclose(numeric_mean, theoretical_mean, atol=1e-8)
    assert np.isclose(numeric_variance, theoretical_variance, atol=1e-8)
    return {
        "historical_anchors_f": historical_anchors.tolist(),
        "historical_outcomes_f": historical_outcomes.tolist(),
        "residuals_f": residuals.tolist(),
        "illustrative_weights": weights.tolist(),
        "current_anchor_f": current_anchor,
        "kernel_sigma_f": sigma,
        "continuous_mean_f": theoretical_mean,
        "continuous_variance_f_squared": theoretical_variance,
        "numerical_integral": integral,
        "integer_probability_sum": float(probabilities.sum()),
        "effective_sample_size": float(1 / (weights @ weights)),
    }


def shape_figure(output_dir):
    fig, axes = plt.subplots(1, 3, figsize=(15.8, 4.5))
    fig.subplots_adjust(top=0.73, bottom=0.18, wspace=0.30)
    fig.suptitle("Center, spread, and shape are different decisions", fontsize=17, y=0.98)
    fig.text(
        0.5,
        0.90,
        "SYNTHETIC ILLUSTRATIONS  |  Narrower is useful only when its confidence is justified",
        ha="center",
        fontsize=10,
        color=GRAY,
    )
    x = np.linspace(63, 84, 2000)
    axes[0].plot(x, normal_pdf(x, 75, 2.5), color=GRAY, ls="--", lw=2, label="Before center correction")
    axes[0].plot(x, normal_pdf(x, 72.5, 2.5), color=BLUE, lw=2.5, label="After center correction")
    axes[0].set(title="1. Shift the center; keep the width")

    axes[1].plot(x, normal_pdf(x, 73, 2.5), color=ORANGE, lw=2.2, label="More uncertain state")
    axes[1].plot(x, normal_pdf(x, 73, 1.2), color=BLUE, lw=2.5, label="Less uncertain state")
    axes[1].set(title="2. Keep the center; vary the width")

    shape_centers = np.array([71.0, 75.0])
    shape_weights = np.array([0.5, 0.5])
    shape_sigma = 0.75
    shape_mean = float(shape_weights @ shape_centers)
    shape_variance = float(
        shape_sigma**2 + shape_weights @ ((shape_centers - shape_mean) ** 2)
    )
    axes[2].plot(
        x,
        normal_pdf(x, shape_mean, np.sqrt(shape_variance)),
        color=ORANGE,
        ls="--",
        lw=2.2,
        label="One bell-shaped distribution",
    )
    axes[2].plot(
        x,
        mixture_pdf(x, shape_centers, shape_weights, shape_sigma),
        color=BLUE,
        lw=2.5,
        label="Two-component mixture",
    )
    axes[2].set(title="3. Same mean and variance; new shape")
    for ax in axes:
        ax.set(
            xlabel="Possible daily maximum (°F)",
            ylabel="Probability density (per °F)",
            xlim=(64, 83),
            ylim=(0, 0.36),
        )
        ax.set_xticks([65, 70, 75, 80])
        ax.legend(loc="upper right", frameon=False, fontsize=8.7)
        tidy(ax)
    save(fig, "location_spread_shape", output_dir)
    dense_x = np.linspace(40, 105, 30000)
    density = mixture_pdf(dense_x, shape_centers, shape_weights, shape_sigma)
    assert np.isclose(np.trapezoid(dense_x * density, dense_x), shape_mean, atol=1e-8)
    assert np.isclose(
        np.trapezoid((dense_x - shape_mean) ** 2 * density, dense_x),
        shape_variance,
        atol=1e-8,
    )
    return {
        "shared_shape_comparison_mean_f": shape_mean,
        "shared_shape_comparison_variance_f_squared": shape_variance,
        "mixture_centers_f": shape_centers.tolist(),
        "mixture_weights": shape_weights.tolist(),
        "mixture_component_sigma_f": shape_sigma,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Output directory; defaults to a new temporary directory.")
    args = parser.parse_args(argv)
    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="kden-math-figures-"))
    output_dir.mkdir(parents=True, exist_ok=True)
    analog = analog_figure(output_dir)
    shape = shape_figure(output_dir)
    edge_support, edge_pmf = integer_pmf(
        np.array([-50.0, 73.0, 130.0]), np.array([0.2, 0.5, 0.3]), 0.8
    )
    assert edge_support[0] == -40 and edge_support[-1] == 120
    assert np.isclose(edge_pmf[0], 0.2, atol=1e-8)
    assert np.isclose(edge_pmf[-1], 0.3, atol=1e-8)
    scale_values = np.exp(
        np.log(0.25) + (np.log(20) - np.log(0.25)) * expit(np.array([-30, 0, 30]))
    )
    assert np.all(scale_values >= 0.25 - 1e-12)
    assert np.all(scale_values <= 20 + 1e-12)
    assert np.all(np.diff(scale_values) > 0)
    checks = {
        "status": "PASS",
        "scope": "ILLUSTRATIVE_ALGEBRA_AND_RENDERING_ONLY_NOT_PROJECT_ACCEPTANCE",
        "all_inputs_synthetic": True,
        "project_data_files_read": 0,
        "project_modules_imported": 0,
        "model_fits_performed": 0,
        "checks": [
            "Integer PMF nonnegative and normalized",
            "Endpoint bins absorb lower and upper tails",
            "Mixture mean and variance agree with numerical integrals",
            "Shape comparison has matched mean and variance",
            "GAM scale link monotone within declared safeguards",
        ],
        "analog_illustration": analog,
        "shape_illustration": shape,
        "scale_link_test_values_f": scale_values.tolist(),
    }
    (output_dir / "mathematical_illustration_checks.json").write_text(
        json.dumps(checks, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "synthetic_figures": 2, "model_fits": 0,
                      "output_dir": str(output_dir)}))


if __name__ == "__main__":
    main()
