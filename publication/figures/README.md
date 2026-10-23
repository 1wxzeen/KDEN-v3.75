# Publication figures

These are the curated public figures and their inputs. Their creation did not
modify or reaccept the original scientific releases. The public checkout does
not include the full local scientific archive; see [reproduction instructions](../../REPRODUCIBILITY.md).

## System overview

- Editable source: [system_overview.svg](system_overview.svg).
- README rendering: [system_overview.png](system_overview.png), a 2× raster
  export of that source (2,360 × 1,440 pixels).

The diagram is a workflow schematic, not a chart of model performance. Its
upper branch is the weather-only input pipeline; the separate lower branch
supplies daily maximum-temperature labels for model fitting and scoring.
Only authorized, available labels may be joined by target date. The diagram
does not imply that every target date has an audited training label, that
reserved outcomes have been opened, or that all historical experiment timing
requirements were satisfied. The publication README retains the disclosed
selection-timing qualification.

The frozen weather dataset is a collection of linked artifacts, not a single
flat table. The 433 columns are deterministic weather/context features;
models can select subsets rather than use all columns. “12 hourly + terrain”
means 12 dynamic hourly source identities plus one static terrain identity.
Q05 is the sole subhourly source field.

The principal evidence is:

| Diagram element | Existing evidence |
|---|---|
| Selective downloads, eight workers, explicit gaps and resume | [Source workflow](../../src/kden_v375/acquisition/workflow.py), [HTTP range checks](../../src/kden_v375/io/http_range.py), [decision D03](../DECISION_EVIDENCE_MAP.md#d03-retrieve-source-messages-efficiently-while-retaining-failure-evidence) |
| Accepted R14 hourly, static, and subhourly source union | [R14 acquisition handoff](../../reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md) |
| 2,080 target days, 118,536 issue states, 433 features | [Universal release acceptance record](../../state/KDEN_V375_UNIVERSAL_ISSUE_STATE_PASS.json), [dataset guide](../../universal_issue_state/README.md) |
| Physically separate truth adoption and five-date extension | [P02 coverage report](../../truth/kden_tmax/v1/reports/P02_TRUTH_COVERAGE_QC.md), [adoption workflow](../../src/kden_v375/prefit/p02_truth.py), [audit rules](../../src/kden_v375/prefit/p02_rules.py) |
| Date-grouped chronological fitting and scoring | [Comparison plan](../../universal_issue_state/R14_MODEL_COMPARISON_PLAN_V1.md), [completed interpretation and timing qualification](../../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md) |

### Regenerate the displayed diagram

From the project root, using an existing local librsvg installation:

```sh
rsvg-convert --zoom 2 --output publication/figures/system_overview.png publication/figures/system_overview.svg
```

No downloads, raw data reads, model fitting, or project acceptance scans are
needed to render this diagram. The SVG contains no external assets or scripts.

## Overall scorecard

[overall_scorecard.png](overall_scorecard.png) is a publication copy of the
[saved original](../../universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/figures/overall_scorecard.png).
It changes the hourly-baseline bar fill to red for contrast. Numeric values,
confidence intervals, layout, and black error bars are unchanged. The
[original plotting implementation](../../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s5_v1/plots.py)
and [saved scorecards](../../universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/scorecards.json)
remain preserved in the experiment. The figure does not establish a profitable
strategy or a universally best model.

The standalone [public renderer](render_overall_scorecard.py) reads the bundled
saved scorecards and reproduces the red-baseline version without model imports
or individual records:

```sh
python -B publication/figures/render_overall_scorecard.py --output-dir /tmp/kden-public-figures
```

## Accuracy through the day

- Displayed figure: [issue_time_development.png](issue_time_development.png).
- Editable vector export: [issue_time_development.svg](issue_time_development.svg).
- Compact, full-precision inputs: [issue_time_development.json](issue_time_development.json).
- Standalone renderer: [render_issue_time.py](render_issue_time.py).
- Bounded renderer checks: [test_render_issue_time.py](test_render_issue_time.py).

The figure compares only the four primary models: hourly residual baseline
(`B0_H`), subhourly residual baseline (`B0_Q`), analog ensemble (`ANEN`), and
location–scale normal GAM (`GAM_LS_NORMAL`). Colors match the overall scorecard;
line styles provide a second way to distinguish the curves.

### Population and quantities

The source is the saved [S5 scorecard](../../universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/scorecards.json),
specifically each model's `exact_issue` summaries. The accepted development
population contains 980 dates from January 1, 2023 through September 6, 2025,
with 55,848 forecasts per model and 57 local issue labels. No predictions were
recomputed and no fitting, truth acquisition, or reserved-outcome reads were
performed for this figure.

At a given issue time there is one forecast per contributing day, and each
day has equal weight:

- MAE is the mean absolute error of the **integer predictive median**, in °F.
- Exact-temperature hit rate is the fraction whose **modal integer** equals
  the audited integer outcome. It is not a listed-contract-band hit rate.
- Reported log loss uses the existing finite-support probability convention:
  a 1e-6 floor and renormalization for scoring, not for fitting.

All four models share the same cases at each exact issue. The first four
labels (02:00–02:45 America/Denver) have 977 dates; all labels from 03:00
through 16:00 have 980. The three absent early-hour states are the
spring-forward dates March 12, 2023, March 10, 2024, and March 9, 2025. They
are not missing forecasts that were interpolated or filled.

### Verification and limitations

The publication extraction checked all 684 plotted metric values
(4 models × 57 times × 3 metrics) against the saved scorecard and independently
reconstructed each aggregate as a contributing-day-weighted combination of
the saved [fold-by-issue summaries](../../universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/fold_issue.json).
It also checked model/time support counts and the
[saved population](../../universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/population.json).
Source paths and SHA-256 fingerprints are recorded in the compact input JSON.

The original [scoring workflow](../../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s5_v1/workflow.py)
checks identical prediction identifiers/order across models; that historical
support check was inspected, not rerun against the prediction files here.
These publication checks do not constitute a new acceptance of the
experiment.

Curves connect the original 15-minute summary values with straight segments.
They are not smoothed, and the figure shows no uncertainty bands. Small
pointwise separations are not pointwise significance claims. Later issue
times combine newer available information with an advancing day; this plot
does not identify a causal contribution of a cycle, field, or model component.
The [disclosed selection-timing defect and its sensitivity check](../../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md#timing-qualification-and-verification)
remain attached to these previously inspected development results. They are
not new blind or prospective evaluation results.

### Regenerate from the compact inputs

From the project root, in a Python environment with Matplotlib installed:

```sh
python -B publication/figures/render_issue_time.py --output-dir /tmp/kden-public-figures
python -B -m unittest discover -s publication/figures -p test_render_issue_time.py
```

The renderer reads only its adjacent compact JSON and writes the PNG/SVG with
the same stem into the chosen output directory (a temporary directory by
default). It has no project/model imports, makes no network requests, and
does not require the large weather archive or prediction files. The displayed
exports used the already-existing reporting environment with Matplotlib 3.10.6
and NumPy 2.0.2; no dependencies or accepted environments were modified.

## Confidence and reliability

- Displayed figure: [confidence_reliability.png](confidence_reliability.png).
- Editable vector export: [confidence_reliability.svg](confidence_reliability.svg).
- Full-precision compact inputs: [confidence_reliability.json](confidence_reliability.json).
- Standalone renderer: [render_confidence_reliability.py](render_confidence_reliability.py).
- Bounded checks: [test_render_confidence_reliability.py](test_render_confidence_reliability.py).

### What is compared

This is the S5 **native-confidence selection diagnostic** for AnEn and the
location–scale normal GAM. It is not the later CR1 learned reliability
experiment or a new calibration fit. Nor does it test calibration of the
whole temperature distribution. An exact hit means the model's modal integer
equals audited Tmax, not that a listed market contract would win.

The source is the saved [Not bundled: selection summaries](../../DATA_AVAILABILITY.md#not-bundled).
The unfiltered development population is the same 980 dates and 55,848
02:00–16:00 America/Denver checkpoints used by the preceding figures, from
January 1, 2023 through September 6, 2025.

The upper row shows all five registered nominal retention targets: 100%, 75%,
50%, 25%, and 10%. These were used to set thresholds on earlier inner
forecasts, not to fix assessment coverage. Thresholds are carried forward by
model and vintage with all ties admitted; the x axis is the actual
day-weighted share retained in assessment. Moving left is more selective.

The lower row uses only the strictest registered rule, nominally the most
confident 10% of earlier forecasts. This was not chosen by optimizing the
displayed outer outcomes. It is shown separately for 2023, 2024, and
January 1–September 6, 2025. Tick labels give actual retained share and the
number of dates with at least one admitted forecast. The GAM's 55-day
partial-2025 subset is marked sparse because it falls below the registered
60-day slice threshold.

### Weighting and same-case baselines

Each forecast keeps its original weight of 1/(expected legal issue times on
its target date). Selected hit rates and mean predicted hits normalize those
weights over admitted forecasts. They are **not** equal-admitted-day hit rates,
unweighted selected-row averages, or the fraction of unique days retained.
Coverage divides admitted weight by eligible day count.

Colors encode the same roles in all four panels; column titles identify the
models. Green solid circles show the achieved exact-hit rate. Orange dashed
diamonds show the selected model's mean **native maximum integer probability**,
without the separate log-loss floor. Blue dotted squares show the subhourly
residual baseline on precisely the same admitted rows. The legend uses the
actual plotted lines, and marker shapes and line styles also distinguish roles.

AnEn and GAM choose their own cases; their selected results are not a
controlled model-to-model ranking. The matched-case baseline helps reveal
whether increased hit rates merely reflect concentrating on easier cases.
It does not, by itself, estimate a statistically resolved incremental gain.

### Uncertainty and evidence limits

Whiskers reproduce the saved unadjusted 2.5th/97.5th percentile intervals from
5,000 seven-calendar-day block replicates. They describe uncertainty in
**achieved hit rates**, not temperature forecast intervals, paired
model-minus-baseline differences, or simultaneous confidence bands for the
whole curve. Predicted-hit means and baseline rates do not acquire invented
intervals. Lines connect the saved point estimates; no smoothing is applied.

The broad sparse-subset intervals matter: the partial-2025 point estimate
falls below predicted confidence, but the plot is not a new significance test
establishing overconfidence. The different seasonal composition of a partial
year also prevents attributing the annual change to a single cause.

The [selection-timing nonconformance and sensitivity check](../../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md#timing-qualification-and-verification)
remain attached. These are previously inspected historical development
outcomes, not prospective or blind results. No cutoff, model, learned
reliability rule, or trading gate was refitted for publication.

### Verification and reproduction

All 16 displayed selection summaries were checked against the source.
Admitted-row counts, dates with admissions, and actual coverage were
reconstructed from the saved per-date admission vectors and the legal
57/53-issue day lengths. Thirty pooled observed/predicted/baseline statistics
were independently reconstructed from their annual summaries using **retained
day-weighted mass**, not raw row counts or admitted-day counts. The full-
coverage endpoints reproduce the [overall scorecard](../../universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/scorecards.json).
The [saved population](../../universal_issue_state/experiments/r14_first_model_comparison_v1/runs/r14-s5-20260927T024658Z/population.json)
and source fingerprints are recorded in the compact input JSON.

From the project root, with Matplotlib installed:

```sh
python -B publication/figures/render_confidence_reliability.py --output-dir /tmp/kden-public-figures
python -B -m unittest discover -s publication/figures -p test_render_confidence_reliability.py
```

The renderer consumes only its adjacent compact JSON. It makes no network
requests and does not read weather, truth, prediction, or model-fit files or
import project runtime packages. PNG and SVG were rendered with the existing
Matplotlib 3.10.6 / NumPy 2.0.2 reporting environment. Original reports,
selection summaries, and accepted releases remain unchanged.

## Scope of the source inventory

The earlier [source inventory](../SOURCE_INVENTORY.json) fingerprints references
in the research index and decision map. It is not an exhaustive manifest of
these later publication assets, nor an approval to redistribute every linked
source or underlying dataset.
