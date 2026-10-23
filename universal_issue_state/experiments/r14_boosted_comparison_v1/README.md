# Public snapshot status

This directory preserves historical implementation and stage instructions. The full weather/truth archives, fitted models, and local environments are not bundled; historical install/start claims below do not describe a fresh clone. Use the root README and DATA_AVAILABILITY guide for current package scope.

The baseline/AnEn/GAM, boosted, and CR1 comparisons were completed historically; the pretrained-tabular development replay remains paused and unaccepted.

---

# R14 XGBoost and NGBoost — full training implementation

This is a new, self-contained model comparison. It consumes the frozen R14 substrate, audited development truth and chronological folds. It does not require the AnEn/GAM tuning folders, fit new reliability gates, or access market data. Existing S5 baseline **row scores** are copied and hash-bound here because some original baseline forecast partitions were deleted. The old experiments and R14 inputs are not modified.

## Start the complete run

Double-click **Start Boosted Models.command**, then choose **1 — Start full training and report**. The isolated `.venv` is installed and pinned. No package installation or pasted variable definitions are needed.

The run performs 60 inner candidate fits, chooses settings separately for each outer vintage, fits six outer winners, freezes their predictions, and only then computes the comparative report. It saves a new timestamped folder under `runs/`. Keep the terminal open and the laptop powered. The full production training run has not been started as part of implementation; only synthetic tests and a bounded real-data engineering probe were run.

Other menu options let you resume the latest run, inspect status, watch progress, request a pause between fits, validate installation, or score an already-frozen run. Progress and unit-level estimates appear in the terminal and in `status.json`; `console.log` preserves the output. Estimates based on completed fits mix two algorithms and growing training sets, so they are rough. The current unit may take longer than the previous one.

Pause completes the current fit before stopping. Ctrl+C interrupts immediately; any unfinished unit is repeated on resume, while completed units are hash-checked and reused. Scoring can be restarted without fitting again. One writer per run is enforced. Changed code/configuration requires a new run folder. An invalid model candidate is recorded and excluded as a whole wherever its required block failed; a family with no valid candidates stops rather than relaxing criteria. Input corruption or unexpected operational errors stop immediately.

For an explicit terminal command from this experiment folder:

```bash
./.venv/bin/python -u -B train.py full --output runs/my-first-boosted-run
```

Use a fresh output folder for a new experiment run. For that named folder, commands are `status`, `watch`, `pause`, `resume`, and `score`, with the same `--output`. The double-click menu manages timestamped `r14-boost-*` folders; it does not automatically select custom CLI folder names.

## What is different from AnEn and the additive GAM

Both methods learn the residual `audited Tmax °F − raw Q HRRR Tmax °F`. The raw Q value is added back afterward. This retains HRRR's broad temperature level while letting the model learn its conditional errors. A residual target also reduces the burden on trees to extrapolate absolute summer/winter temperatures. It does not guarantee that residual relationships extrapolate.

**XGB_QUANTILE** predicts nine residual quantiles: 1%, 5%, 10%, 25%, 50%, 75%, 90%, 95% and 99%. This allows asymmetric distributions without imposing a normal shape. Each quantile uses boosted trees; splits can express weather interactions. Training minimizes weighted quantile loss. Candidate selection uses the resulting integer-PMF log score on later inner periods, not training loss.

Quantile estimates can cross or coincide. The frozen adapter sorts them, retains the sorted median, and expands adjacent gaps outward to at least 0.05°F. It uses linear CDF interpolation between quantiles and exponential tails anchored at 1% and 99%, with tail scales derived from adjacent quantiles and floored at 0.25°F. This is a specific distributional approximation, not a native full-density XGBoost model. Crossing frequency and correction size are retained in diagnostics; the adapter is not retuned after outer scores.

**NGB_NORMAL** predicts residual location and scale with natural-gradient boosting and shallow decision trees. It retains a normal conditional shape, but its location/uncertainty relationships can contain interactions absent from the additive GAM. It minimizes continuous normal log score, not the GAM's discretized fitting likelihood. Output scale is guarded to [0.25, 30]°F before PMF construction, and guard frequency/native scale are recorded. Invalid/nonfinite distributions fail rather than being repaired silently.

NGBoost 0.5.6's ordinary marginal initializer does not use sample weights. The implementation supplies a weighted normal mean and variance explicitly; its subsequent weighted tree fits and line searches use the registered day weights. This correction is covered by an exact numerical test.

Both outputs become probabilities for integer Fahrenheit outcomes −40 through 120 using half-degree boundaries. Endpoint bins absorb the tails. Reported log loss uses the existing 1e−6 floor/renormalization; native PMFs remain stored. This common scoring representation does not imply identical fitting objectives or distribution assumptions.

## Feature decisions

There are 27 registered R14 predictors plus one deterministic heating-potential difference. Missingness indicators are appended for all 28 inputs.

| Physical information | Inputs and reason |
|---|---|
| Thermal level and evolution | Raw hourly/subhourly maxima, modeled issue-time temperature, remaining maximum and endpoint slope; remaining warming minus issue-time modeled temperature is derived explicitly. These are forecasts, not thermometer observations. |
| Air mass and vertical contrasts | 850-mb temperature, surface–850 and 700–850 contrasts. Retains the D1-motivated 850-mb signal without asserting an above-ground lapse rate. |
| Energy and surface | Remaining solar integral, mean cloud cover and issue-time modeled snow cover. Trees can distinguish their interactions; no distance metric gives correlated coordinates extra geometric weight. |
| Mixing and moisture | PBL depth, mean/maximum wind magnitude, dewpoint depression, wet-interval fraction and reflectivity occurrence. Wind magnitude is not signed thermal advection. |
| Spatial context | Regional near-surface temperature range, west-minus-east temperature contrast, and tile cloud variability. These capture heterogeneity absent from a strictly local thermal vector; geographic contrasts are proxies, not causal attribution. |
| Forecast consistency | Aligned hourly/subhourly difference and absolute revision magnitude. Related forecast products are not treated as independent ensemble members. |
| Timing | Issue minute, annual sine/cosine, and both cycle ages. No calendar-year feature or separate seasonal-model search. |

Exact names, registry descriptions and physical ranges are in `config.json`. The loader validates selected-cycle availability and applies the original frozen feature-range errata. It never stitches later cycles or imports observed future weather.

Only missing raw Q forces abstention because the residual translation needs it. Other missing predictors are replaced by **training-only day-weighted medians**, accompanied by explicit fixed indicators. All-missing training columns use zero plus the indicator, a declared neutral storage value rather than a claim that the weather was zero. This shared preprocessing makes the two families comparable. There is no global preprocessing, outcome-based feature search, random split or hidden zero-filling.

## Bounded parameter search

| Choice | XGBoost | NGBoost |
|---|---|---|
| Tree depths | 2, 3, 4 | 2, 3 |
| Boosting rounds | 200, 600 | 200, 600 |
| Learning rate | 0.03 | 0.03 |
| Candidate count | 6 | 4 |
| Row subsampling | None | None |
| Other regularization | Histogram trees, 128 bins; minimum child weight 10; L2 10 | Minimum 40 rows and 1% training weight per leaf |
| Execution | CPU, two XGBoost threads | Full-batch, fixed random seed |

Rows are weighted `1 / eligible checkpoints on their training day`, so each day contributes total weight one. XGBoost's child-weight threshold is therefore in **day-equivalent weight**, not raw issue rows; it does not guarantee ten distinct days in each leaf. NGBoost's weight-fraction constraint likewise addresses effective mass rather than making intraday rows independent.

The grid is intentionally limited. Depths permit low-order interactions while constraining memorization; 200 versus 600 rounds tests underfitting versus additional capacity at a fixed modest step size. Fixed round budgets avoid random validation splits or early stopping on the assessment block. NGBoost's native gradient-convergence tolerance can terminate before its maximum rounds; this is a numerical stopping rule, not an outcome-driven choice of validation period.

These are reasoned starting choices, not a claim of optimal hyperparameters. A negative result would apply to these features, objectives, adapters and tuning budget; it would not establish that no HRRR-based model can work.

## Chronology

The six shared inner blocks span the half-years from January 2022 through December 2024, each fitted using only preceding eligible development dates and the two-day label lag. The initial half-year block is excluded in advance because we require at least 300 training days. Each candidate needs at least two eligible inner blocks with at least 60 assessment days each.

For outer 2023, settings use the two 2022 inner blocks; for outer 2024, four inner blocks through 2023; for partial 2025, six through 2024. **Loss dates after outer start minus two days are removed before selection**, including December 31. Every outer fit also obeys that cutoff. All intraday rows of a target day remain together. Ties within 1e−10 nats prefer shallower trees, then fewer rounds.

Earlier periods, including S5 and CR1, were inspected before this design. The new comparisons are historical development evidence, not restored blind tests. Reserved historical/tail outcomes remain forbidden. The original baseline timing violation stays disclosed; S5's sensitivity found unchanged settings when the late date was excluded.

## Storage and results

One shared feature cache is retained per run. Inner models and inner PMFs remain in memory only; the durable inner record contains daily losses, diagnostics, a confidence histogram, training support, parameters and run identity. Reproduction of a discarded inner model requires refitting from its pinned inputs and seed. We explicitly trade stored replay artifacts for disk efficiency.

Only the six winning outer models and their PMFs are saved. The baseline score snapshots occupy roughly 26 MiB, and no historical tuning folder is copied. A normal run is designed to remain well below the earlier tens-of-GiB footprint, although model sizes and filesystem overhead determine the actual total. A 2 GiB free-space preflight prevents starting without a reasonable output allowance; it is not a hard storage quota.

Read `REPORT.md` along with `SCORECARDS.json`, `CALIBRATION.json`, `EXACT_ISSUE.json`, `PRIMARY_COMPARISONS.json` and `SUPPORT.json`. They cover MAE, RMSE, exact hits, log loss, CRPS, intervals, tails, synthetic bands, calendar/issue slices and native-confidence reliability with coverage. Primary log-score comparisons use five Bonferroni-adjusted paired calendar-block intervals, 5,000 draws, and a fourteen-day sensitivity. Secondary findings remain descriptive. No gate is selected from assessment outcomes, and no market profitability is evaluated.

## Reproducibility and installation

`RELEASE.json` binds code, configuration, foundation snapshots, benchmark score snapshots and the environment lock. Existing models are loaded only from this run's hash-verified artifacts. `requirements.txt` lists direct pinned dependencies; `environment.lock.txt` freezes all installed packages. The installed environment is separate from previous experiments.

If reinstalling on a compatible Python 3.12/macOS system, create `.venv` here and install `environment.lock.txt`, then choose Validate. Never update package versions in a live run. The bounded probe checks real R14 joins, training, PMF validity and model save/load behavior without reading its query outcomes. Synthetic tests exercise time cutoffs, weighting, missingness, quantile repair/tails, model serialization, fit–freeze–score ordering, resume and tamper rejection.

References: [XGBoost quantile/interval documentation](https://xgboost.readthedocs.io/en/latest/python/examples/prediction_intervals.html), [NGBoost usage](https://stanfordmlgroup.github.io/ngboost/1-useage.html), [NGBoost tuning](https://stanfordmlgroup.github.io/ngboost/2-tuning.html). The exact pinned installed source, rather than changing online examples, controls execution.
