# R14 first model comparison: baselines, generalist AnEn, and location–scale GAM

Version: 1.0  
Date: 2026-09-25  
Proposed experiment ID: `R14_FIRST_MODEL_COMPARISON_V1`  
Status: Research and implementation plan; no models fitted or outcomes opened by this work  
Working home: `universal_issue_state/` within KDEN v3.75

## 1. Objective and scope

Build, freeze, and compare two R14-derived baselines, a general thermal analog ensemble (AnEn), and a location–scale generalized additive model (GAM). Determine what each can generalize across future periods, issue times, seasons, physical states, and forecast-support conditions. Establish whether their native confidence identifies more precise forecasts at useful coverage.

Commercial viability is the eventual objective, not an assumed consequence of model construction. This milestone produces weather probability forecasts and evidence about their reliability. It does not claim trading edge, select trades, or optimize historical PnL. A later commercial test must establish information beyond contemporaneous prices under fees, latency, executable-price proxies, and exposure constraints.

The main questions are:

1. Does conditioning on R14 state improve a simple HRRR forecast plus its historical residual distribution?
2. Does analog similarity or smooth distributional regression better predict the center, spread, and tails of final Tmax?
3. Do high-confidence forecasts actually achieve greater exact-integer and fixed-band accuracy on later data?
4. How much checkpoint and unique-day coverage remains at higher precision?
5. Where are failures systematic enough to motivate a specific next experiment?

A well-supported null result is a successful research outcome. No model must be declared a winner, and no target hit rate or profit level is promised.

## 2. Existing assets versus work still required

The universal substrate is already frozen. The local modeling-boundary record reports 2,080 target days, 118,536 issue states, 433 features, 1,707 supervised development days, three unresolved development days, three outer folds, and 15 nested inner-fold instances. Ordinary days have 57 issue states from 02:00 through 16:00 America/Denver; spring-forward days have 53.

P07 contains R14 H-BI/Q15-BI baseline definitions and an AnEn specification. It does not contain fitted baseline residual distributions, model forecasts, or measured model skill. Those must now be constructed and frozen. Historical Layer 1 results used a different experiment, including observation floors, and are not the numerical baselines for this comparison.

This is a new experiment. It deliberately reuses appropriate P07 definitions and folds without claiming to execute the complete RAFM V1 protocol. Adding a GAM and a broader diagnostic scorecard does not amend the immutable RAFM experiment. Any inherited definition and any departure must be recorded in a comparison manifest.

## 3. Workspace and immutability

Keep all new work beneath the requested parent directory:

```text
universal_issue_state/
  README.md                              existing navigation; unchanged
  R14_MODEL_COMPARISON_PLAN_V1.md         this plan
  v1/                                    frozen substrate; read-only
  experiments/
    r14_first_model_comparison_v1/
      README.md
      config/                            machine-readable research contract
      schemas/
      src/                               experiment-specific implementation
      tests/
      environment/                       separate pinned modeling environment
      manifests/
      runs/<run_id>/
        status/
        preprocessing/
        fitted_models/
        inner_predictions/
        outer_predictions/
        diagnostics/
        scorecards/
        figures/
        reports/
      releases/<release_id>/             immutable accepted outputs
```

Use project-root-relative input references and experiment-relative output references. New code may reuse verified, current v3.75 utilities where useful. Record their hashes/dependencies. Keep model-specific implementation here; do not alter frozen acquisition or prefit code/environment to accommodate it. Do not import legacy KDEN v2/v3/v3.5 runtimes.

Read-only inputs outside this work area are:

- `universal_issue_state/v1/` feature partitions, spine, selected cycles, registry, and manifests;
- `truth/kden_tmax/v1/` authorized audited truth and metadata;
- `folds/kden_v375/v1/` date roles, outer folds, and inner folds;
- P07 configuration, adapter definitions, and boundary records as reference authorities.

Do not change `v1/`, truth, folds, RAFM V1, or their PASS records. New outputs never overwrite an earlier accepted run. A restart resumes the same immutable input/configuration identity; a scientific change gets a new run and contract version.

## 4. Evidence roles and the cross-project exposure ledger

Retain the original development split for this first comparison:

| Role | Dates | Treatment |
|---|---|---|
| Historical development | 2021-01-01–2025-09-06 | 1,707 audited labels available for fitting and rolling assessment; three unresolved dates excluded from all supervised uses |
| Reserved historical evaluation | 2025-09-07–2026-09-06 | No label reads in this milestone's development stages; not described as globally untouched |
| Five-day tail | 2026-09-07–2026-09-11 | Excluded from fitting/tuning; optional later descriptive evaluation, too small for a generalization claim |
| Prospective confirmation | To be registered before the selected future window begins | Predictions and policy locked before outcomes influence decisions; requires a later data extension |

The distinction is necessary because v3.75 records the 365-day interval as unopened locally, while KDEN_NBM explicitly opened those labels and reported model results. Earlier Layer 1/Layer 4 studies also inspected overlapping outcomes. A new directory cannot restore blindness. Preserve original files and describe cross-project exposure in a new ledger; do not silently rewrite historical evidence roles or import NBM labels into training.

Chronological outer assessment is still useful for evaluating a fixed pipeline. Because historical findings already influenced this research, and future iterations may consume its results, call it historical out-of-time evaluation rather than a pristine final test.

This plan does not authorize opening reserved labels. The implementation can complete the development comparison without them. A subsequent reserved evaluation needs its own recorded prediction/code freeze and an honest evidence label; it cannot restore a blind-test claim.

### Label availability

A target date preceding a forecast date is necessary but not sufficient for historical training eligibility. Before fits, specify a reproducible label-availability cutoff, including a conservative reporting lag and how retrospective audited corrections are treated. Do not treat archive retrieval time as historical publication time. If exact historical availability of final audited labels cannot be reconstructed, label the study as using retrospective audited training truth under a declared lag, not as a perfect real-time replay.

Apply that cutoff to training dates at fold boundaries without moving assessment dates. Record resulting exclusions. The original nominal fold sizes must not be presented as actual fit sizes after availability or missingness filters.

## 5. Time, targets, and model inputs

- Target: official audited integer-Fahrenheit KDEN Tmax, `y_audited_f`.
- Target window: fixed right-open `[07Z_d, 07Z_(d+1))`, not DST-adjusted civil midnight.
- Issues: frozen 02:00–16:00 America/Denver 15-minute grid.
- Forecast availability: existing independently selected hourly/subhourly cycles under the 105-minute emulator. Do not reselect cycles or stitch products.
- Statistical grouping: all issue rows from a target day remain together. Serial dependence across days is handled in uncertainty estimates.
- Predictor source: deterministic feature partitions first; no trajectory expansion is required for this milestone.
- Units/windows: taken from the feature registry, with conversion tests.
- Missingness: no silent zero fill. Primary models abstain when their required input set is incomplete; operational fallbacks are separately identified.
- Truth/QC/fold/source-path fields are provenance only, never predictors.

HRRR `asof` values describe model states, not observed station temperatures. This experiment contains no observation floor, observed running maximum, MADIS input, or observation–forecast departure. Observation-aware modeling is a future, separately versioned extension requiring receipt/availability and quantization treatment.

The full feature universe is available, but not automatically admitted into every model. A compact, explicit predictor set is preferable to an unrestricted search through 433 features.

## 6. Common forecast contract

Every probabilistic model emits a normalized PMF over integer Fahrenheit values -40 through 120. Below/above-support mass accumulates at the respective endpoint. Record endpoint mass and any out-of-support truth rather than concealing guardrail failures.

For continuous distributions, calculate integer probabilities from CDF differences at half-degree boundaries. This is a statistical discretization convention, not a claim about an undocumented physical sensor-rounding mechanism. Freeze the convention before scoring. Empirical residual kernels use the same integer integration and endpoint rules.

Store native probabilities. For finite log scoring only, apply the inherited 1e-6 probability floor and renormalize; record how often and how much it changes probabilities. Calibration, intervals, and confidence diagnostics use native PMFs. Define log score as negative log probability so lower is better.

Each forecast records:

- issue-state ID, date, issue clock, statistical group, fold, model and configuration IDs;
- training dates, label cutoff, fit timestamp, input/code/environment hashes;
- native PMF, predictive mean, median, mode, variance, entropy, intervals;
- raw continuous baseline center and model correction where applicable;
- availability, abstention reason, fallback identity, and support/OOD diagnostics.

Use the PMF median for MAE-oriented point evaluation, mean for squared-error evaluation, and mode for exact-integer decisions. Also report the raw baseline and model location as named continuous point forecasts. Preserve rounded-point exact-hit metrics separately, using nearest integer with halves away from zero. Freeze ties in PMF modes and interval quantiles deterministically.

For a band, sum its integer masses. The modal band need not contain the modal integer. Neither band hits nor within-one-degree hits are exact-integer hits.

## 7. Candidate models

### B0-H: R14 hourly baseline

Raw center: `h16_local_retained_max`, converted once from Kelvin to Fahrenheit.

Construct an empirical residual distribution from eligible training days at the exact issue minute and within a circular seasonal neighborhood. Forecast the current center plus training residuals using a Gaussian residual kernel. Do not optimize a multivariate correction for this baseline. Store its raw center separately because the residual distribution can shift its predictive mean/mode.

### B0-Q: R14 subhourly baseline

Identical procedure using `q05_local_retained_max`. These are retained-trajectory maxima under the current release definition, not the older future-only maximum plus observed-floor construction.

For both baseline PMFs, proposed tuning choices are seasonal half-width {45, 60, 90 days} and residual kernel sigma {0.75, 1.25, 2, 3°F}, selected inside training only. Require at least 40 eligible distinct days. Use equal residual weights and abstain if support is inadequate. Record selected pool size and bandwidth. Freeze the numerical tie-break rule before fitting.

### M1: general thermal residual AnEn

Reuse the P07 generalist's eight similarity features:

1. `h16_local_asof_value`
2. `h16_local_remaining_max`
3. `q05_local_asof_value`
4. `q05_local_remaining_max`
5. `derived_q05_minus_h16_common_remaining_mean_k`
6. `derived_t850_minus_t2m_future_first_k`
7. `derived_t700_minus_t850_future_first_k`
8. `revision_h16_remaining_max_abs`

Center on B0-Q's raw forecast. Select analogs using training-only robust scaling and equal-weight scaled Euclidean distance. Each historical target day contributes at most one candidate at the exact local issue minute. Candidate dates must be eligible training dates preceding the query and satisfying label availability.

Translate the neighbors' raw-Q residuals to the query's raw-Q center and construct a weighted residual-kernel PMF. This translation is explicit: do not silently switch between raw historical Tmax and residual analog targets.

Carry forward P07's seasonal windows, neighbor counts {15, 20, 30, 40, 60}, distance bandwidth multipliers {0.5, 1, 2}, kernel widths, minimum eligible pool of 40, scaling fallback, and deterministic distance ties. A configuration requiring more neighbors than available is unavailable, not silently reduced. Before coding, freeze unambiguous mathematical formulas for distance normalization, kernel bandwidth, zero-distance cases, and hyperparameter ties.

Emit nearest/median/kth distance, pool count, selected neighbor count, effective sample size, residual spread, distance concentration, extrapolation, and training-reference distance percentile. Reference distance distributions must exclude self-matches and use training data only.

No specialists, adaptive mixture, neighboring-time analogs, or learned distance metric in this milestone.

### M2: location–scale GAM

Use the same raw Q15 center as an offset:

`mu(X) = B0_Q_raw(X) + g_mu(X)`  
`log(sigma(X)) = g_sigma(X)`

Fit center and scale with a coherent distributional likelihood. Do not fit a mean and then estimate predictive uncertainty naively from optimistic in-sample residuals. Primary likelihood: discretized Gaussian, including endpoint mass. Fit pooled issue rows with equal total day weights.

Start with the same eight thermal features as M1 plus issue minutes, cyclic calendar position, and cycle-age metadata. Use a noncyclic smooth for issue time: 02:00 and 16:00 are not neighboring times. Use a cyclic day-of-year representation. DST flags and cycle ages distinguish changes in cycle availability.

The scale equation should be smaller than the location equation, initially emphasizing issue time, season, revision magnitude, and hourly/subhourly disagreement. These feature choices and exact terms must be resolved in the prefit contract before any outcome-driven search.

Use shrinkage/penalized low-rank smooths. Proposed maximum basis sizes: five per weather smooth, six for issue time, and eight for cyclic season. Freeze centering, identifiability, interaction rules, boundary extrapolation, sigma bounds, optimization tolerances, and a small regularization grid. Include at most one predeclared issue-time-by-revision interaction initially; no automatic search through all interactions.

Two bounded diagnostics are proposed, both registered before results:

- location-only GAM with constant scale, to isolate the contribution of conditional dispersion;
- location–scale Student-t with fixed degrees of freedom (proposed nu=5), to assess sensitivity to heavy tails.

The primary GAM remains the Gaussian specification. These diagnostics do not create an unrestricted likelihood search. All reported candidate comparisons belong in the experiment ledger.

A broader physical feature set can be a later amendment or successor after the thermal comparison identifies a specific gap. No automatic feature addition based on outer-block results while retaining the same experiment identity.

## 8. Chronological fitting and comparison

Reuse the existing nominal outer splits:

| Fold | Training window | Assessment window |
|---|---|---|
| OUTER_01 | 2021–2022 | 2023 |
| OUTER_02 | 2021–2023 | 2024 |
| OUTER_03 | 2021–2024 | 2025-01-01–2025-09-06 |

Reuse the nested half-year blocks falling inside each training window. Apply the declared label-availability exclusion at each fit. Fit scalers, smooth bases/knots, thresholds, residual kernels, hyperparameters, and diagnostic reference distributions using training data only.

For each outer block:

1. Generate inner assessment predictions for each registered candidate using only its inner training data.
2. Choose settings by day-weighted inner negative log score on a predeclared common tuning support across feasible configurations, with minimum-coverage requirements, secondary safety diagnostics, and deterministic ties defined in advance. A configuration cannot win by abstaining on harder inner cases; if common support is inadequate, report tuning as unsupported rather than choosing from incomparable losses.
3. Refit using eligible outer training days.
4. Freeze configuration and all outer predictions before assessment scoring.
5. Evaluate without changing that block's candidate.

Keep model vintages fixed over each assessment block for the primary experiment. Do not add previously assessed labels to the analog pool mid-block. A rolling operational retraining schedule is a separate sensitivity or later experiment.

Use the same target population and nominal folds across candidates. Report both common available support and each model's native support. Never present a model's smaller, easier retained sample as a paired performance improvement. Missing predictions count as missing coverage, not silent sample deletion.

All primary outer predictions should be sealed before comparative result inspection. Later adaptive changes consume those results as development evidence and require a new version. Repeated inner-fold instances across outer fits are not independent observations; identify and deduplicate where predictions are pooled for downstream use.

No post-hoc probability calibrator or learned hit gate is fitted in this milestone. Its output supports that later work. Such a gate needs its own chronological cross-fitting: choosing base settings on an inner block's labels and then calling those selected forecasts fully out-of-sample for gate training is insufficient. Generate genuinely forward-selected base predictions or use an additional nested/sequential layer when that stage begins.

## 9. Descriptive scorecard

The report must explain model behavior, not merely rank models. Every table shows the estimand, denominator, days, checkpoints, missing/abstained counts, and uncertainty where support permits. Use forecast-minus-truth as the signed error throughout.

| Dimension | Required measures | What it diagnoses |
|---|---|---|
| Coverage and integrity | Expected/scored days and checkpoints; missing inputs, insufficient support, failed fits; fallback usage | Whether apparent gains come from exclusions |
| Center accuracy | MAE, RMSE, bias, median AE; mean/median/raw-center forecasts clearly distinguished | Typical accuracy and systematic bias |
| Integer precision | Modal-integer hit; rounded-point hit; within 1°F and 2°F; signed integer-error histogram | Exactness versus near misses |
| Tail failures | P90/P95/P99 absolute error; rates at >=3, >=5, >=10°F; warm/cold breakdown | Large-loss weather states |
| Distribution quality | Negative log score; discrete CRPS/RPS with formula and normalization; multiclass Brier | Quality of the full predictive distribution |
| Threshold/band quality | Brier/reliability at 32, 40, 50, 60, 70, 80, 90, 100°F; fixed two-integer and five-integer partitions | Boundary-relevant precision without market outcomes |
| Calibration | Predicted-versus-observed hit probabilities; threshold reliability; randomized discrete PIT; calibration-in-the-large | Overconfidence and systematic probability errors |
| Intervals and sharpness | 50/80/90/95% central interval coverage and width; entropy; largest integer mass; endpoint mass | Whether narrow forecasts are earned |
| Selectivity | Precision–coverage and selective-loss curves; actual versus intended coverage; calibration among admitted cases | Whether confidence predicts precision |
| Generalization | Fold/year, season, issue, physical regime, support/OOD, documented source era | Transfer and stability |
| Intraday behavior | Revisions in mean/mode/PMF; gain from new cycle versus same-cycle wait; probability of a hit across issues | Whether later forecasts add information |
| Operations | Fit/predict duration, memory, nonconvergence, reproducibility | Practical future delivery constraints |

### Band conventions

Use fixed exhaustive partitions, with both adjacent-pair alignments: pairs anchored at even integers and pairs anchored at odd integers, with explicit edge categories. This prevents results depending on a favorable arbitrary two-degree alignment. Preserve the P07 five-degree diagnostic convention after making endpoint treatment explicit.

Report modal-band accuracy and the probability assigned to the band containing the predicted integer separately where useful. These are diagnostic bands, not claims about actual listed contracts. Real-market bands are joined only in the later commercial phase.

### Prespecified slices

- Every outer block and target year; highlight that OUTER_03 is a partial year.
- DJF/MAM/JJA/SON and descriptive month-level views.
- All 57 issue times; readable summaries for [02,06), [06,10), [10,13), [13,16].
- New-cycle transitions versus same-cycle updates; hourly/subhourly cycle ages.
- Forecast snow presence, cloud/solar state, reflectivity/wet support, vertical stability, wind/mixing, and revision magnitude.
- Forecast-temperature bins; realized-temperature bins only as ex-post error diagnostics, never as live gates.
- Analog-support and extrapolation strata; GAM feature-range and extrapolation diagnostics.
- Source/model eras only when independently documented. Do not infer version changes from changes in error.

Specify exact columns and fixed or training-derived thresholds in a registry before scoring. Do not cross every slice with every other slice. Primary one-dimensional slices and a small named interaction set keep the evidence interpretable. Weather regime labels are forecast-state proxies, not proof of actual observed mechanisms.

For a slice with fewer than 60 distinct days, report it as sparse/exploratory and ineligible for a supported-generalization claim; publish counts and uncertainty rather than implying stability. Sixty days is a reporting safeguard, not a guarantee of power. Report seasonal/regime calibration only at a resolution the data support.

### Required plots and explanations

1. Overall scorecard with paired model differences and coverage.
2. Fold-by-issue skill and calibration heatmaps with support counts.
3. Reliability plots for exact integer and fixed bands, with confidence histograms.
4. Precision–coverage and selective log-score/CRPS curves.
5. Interval coverage versus nominal level, interval widths, and discrete PIT diagnostics.
6. Signed-error and tail-error distributions by predeclared broad conditions.
7. Analog distance/effective sample size versus future error and confidence reliability.
8. GAM location/scale effects, their supported input ranges, and uncertainty/limitations; no causal interpretation of fitted effects.
9. Intraday forecast paths for a deterministic selection of representative hits, misses, and large failures.

Case studies generate hypotheses. Freeze their selection rule (for example largest day-average errors plus a fixed-seed sample of ordinary successes/misses), label them ex-post, and never validate a new gate on the cases that suggested it.

## 10. Selective forecasting in this milestone

Use native maximum integer probability as the primary exact-hit confidence score. For each diagnostic band partition, use the maximum band probability as its corresponding band-confidence score. Entropy and interval width are secondary registered rankings, not interchangeable probability estimates.

Proposed coverage targets: 100%, 75%, 50%, 25%, and 10%. Determine thresholds from applicable inner training/validation forecasts only, then freeze them before the outer block. Report actual achieved outer coverage; never tune a test threshold to force the desired coverage. Freeze quantile and tie handling; all-equal scores must not generate arbitrary favorable selection.

Where inner OOF predictions were also used to select base hyperparameters, their precision is tuning evidence, not an unbiased reported gate result. The untouched outer block evaluates the complete selected pipeline. No learned reliability fit is claimed from those selected OOF records.

For each confidence threshold report:

- admission rate over eligible checkpoints and over the original expected checkpoint population;
- fraction of eligible days with at least one admitted issue;
- admitted issues per day and number of distinct admitted days;
- exact/band hit rate, expected hit probability, calibration gap, and tail-error rates;
- full-day-weighted admitted mass and within-admitted-day averages, explicitly distinguished;
- baseline performance on identical admitted cases;
- each model's own selection at comparable coverage, with support differences visible;
- results by outer block and a small number of sufficiently supported issue/season strata.

For population-weighted selection curves, assign each eligible day total weight one across its prespecified eligible issue grid, then restrict those weights to admitted issues and normalize for conditional accuracy. Do not silently switch to equal weighting over only admitted issues per day: that answers a different question. Show both if useful and label them.

Do not choose an operating threshold from the pooled outer curve. Learned confidence calibration, physical gates, and trade policies belong to the next experiment after this diagnostic milestone.

## 11. Statistical uncertainty and repeated experimentation

Primary objective: mean negative log score, first averaged within target day and then across days. Complement with CRPS, calibration, precision, coverage, and tails; no single metric establishes overall superiority.

Use paired seven-calendar-day moving-block bootstrap resampling, 5,000 replicates, with all issue rows and model predictions from each day kept together. Preserve fold boundaries and missing-date structure. Proposed seed: 3750925; proposed confidence level: 95%. Record this deliberate departure from P07's 90% interval convention. A fixed 14-day block sensitivity can assess serial-dependence sensitivity without selecting whichever interval looks favorable.

The contract must enumerate the primary model contrasts before fitting: AnEn versus each baseline, GAM versus each baseline, and GAM versus AnEn. Use simultaneous bootstrap intervals or another fully specified familywise procedure across these primary contrasts. Freeze its implementation before results. Ablations and extensive slice analyses are descriptive unless separately included in a registered inferential family.

Calibration bins, interval conventions, Brier aggregation, RPS normalization, sparse-bin behavior, and bootstrap behavior with no admitted cases must be specified before scoring. No-admission draws/strata are undefined, not zero error; report their incidence.

Maintain a ledger of all configurations, failed fits, amendments, models and gates considered, and what outcome evidence motivated each change. Report both statistically resolved differences and practically small differences. Do not quietly reset the experiment count when renaming a model.

## 12. What constitutes progress

This first milestone need not promote a single model. Its accepted result includes:

- reproducible baselines and forecasts on the R14 substrate;
- honest paired model comparisons with coverage and uncertainty;
- evidence for or against conditional dispersion and native confidence ranking;
- identification of stable advantages and explicit weak/sparse regimes;
- a short list of next hypotheses tied to observed deficiencies;
- a clear statement of what remains unproven.

Classify findings as overall weather improvement, supported conditional promise, no resolved difference, material failure, or insufficient support. A model may be worth further work for conditional precision even without an overall win, but the subset must be declared and tested honestly. Post-hoc slices are hypotheses only.

Before using labels to make a formal promotion claim, freeze practical improvement margins and allowed degradation for log score, calibration, CRPS, tails, and worst-fold behavior. Do not copy RAFM's mixture-promotion thresholds into this different comparison without justification. If margins remain unset, report effect estimates and uncertainty and make no binary promotion claim.

## 13. Implementation stages and deliverables

### S0 — Inventory, evidence roles, and executable contract

Read and verify relevant boundary/input identities without opening reserved outcomes. Create the experiment directory, provenance map, exposure ledger, feature/metric registries, candidate ledger, and separate environment definition. Translate this plan into a machine-readable contract.

Exit: all decisions in section 14 are resolved and recorded; every model input maps to an existing registry field; no fit or score is needed to resolve engineering ambiguities.

### S1 — Data loader and scoring foundation

Implement filtered development truth joins, folds with label cutoffs, feature/unit conversions, PMF construction, deterministic point decisions, diagnostic partitions, day weighting, and run manifests. Validate with synthetic examples and bounded real-input probes without examining reserved outcomes.

Meaningful checks include unit conversion, date/issue alignment, label exclusion, no cross-day fold splitting, CDF mass conservation, endpoint treatment, mean/median/mode distinctions, two-integer band mapping, and absence of future-selected cycles. Validate score formulas against hand-calculated fixtures, not only implementation-shaped tests.

Exit: a validated forecast/evaluation contract usable unchanged by all four primary candidates.

### S2 — Construct and freeze R14 baselines

Generate inner and outer forecasts for B0-H and B0-Q, retaining raw centers and probabilistic residual forecasts. Seal model definitions, training provenance, support diagnostics, and prediction hashes. These become this experiment's baseline releases; no Layer 1 score is substituted.

Exit: complete expected-key accounting, valid PMFs or explicit abstentions, and immutable baseline predictions. Avoid inspecting comparative assessment outcomes until S4 predictions are sealed.

### S3 — Generalist AnEn and GAM implementation

Implement M1/M2 and registered ablations. Use bounded synthetic and small development fixtures for correctness, optimizer convergence, support behavior, and reproducibility. Estimate full-run cost from probes. Freeze code and candidate settings before broad runs.

Exit: both implementations emit the common forecast/diagnostic schema, fail explicitly, and respect identical evidence boundaries.

### S4 — Nested fits and prediction freeze

Run registered inner tuning and outer prediction generation. Store fit artifacts, run status, selected settings, failed candidate reasons, and all expected prediction keys. Freeze the full outer prediction set before comparative scoring. No fitting on reserved historical evaluation or tail labels.

Exit: reproducible prediction release and integrity report, with explicit incomplete-support records.

### S5 — Scorecard and scientific interpretation

Generate the tables, figures, paired comparisons, native-confidence selection diagnostics, and case studies specified above. Separate validated findings from exploratory explanations. Include a concise model-by-model account of what transferred, what failed, what is sparse, and whether increased confidence was deserved.

Exit: a durable research report, machine-readable scorecards, and a bounded recommendation for the next milestone; no trading claim.

### S6 — Choose the next experiment

Use the results to decide among reliability calibration/gating, a richer GAM feature set, ordinal/distribution-shape models, specialist AnEn/RAFM, an observation adapter, or model-diversity work. Register the choice and its evidence cost. Reserve prospective validation before developing a commercial bridge.

## 14. Decisions to close before model fitting

These are implementation design tasks, not reasons to open outcomes or repeatedly ask for approval. Resolve routine technical choices from this plan and available data contracts, document them, and obtain clarification only for material scientific scope changes.

| Decision | Proposed direction / closure requirement |
|---|---|
| Label availability | Declare reporting lag and retrospective-truth limitations; enforce exact fold-boundary cutoff |
| Baseline/AnEn formulas | Explicit residual translation, kernel equations, zero-distance handling, infeasible-k behavior, and deterministic tuning ties |
| GAM feature terms | Verify columns and freeze location/scale formulas, cyclic calendar representation, limited interaction, basis sizes and regularization grid |
| GAM solver | Choose a maintained distributional-fitting implementation or validated local solver; lock dependencies, convergence rules, sigma bounds and extrapolation policy |
| Model ablations | Register constant-scale and fixed-nu Student-t diagnostics or explicitly defer before outcomes; no silent expansion |
| Missingness/fallback | Strict required-input abstention primary; separate named fallback policy and common-support reporting |
| Metric details | Freeze PMF/point/partition conventions, calibration bins, threshold direction, and loss normalization |
| Regime definitions | Explicit registry columns and training-only thresholds, with sparse-support policy |
| Selection curves | Freeze threshold-learning population, confidence rankings, target coverages, ties, denominators, and plot conventions |
| Statistical claims | Exact simultaneous-inference method, primary contrasts, any practical margins, and exploratory labeling |
| Runtime policy | Bounded probes first; documented resumable full-run commands and status surfaces before owner execution |
| Prospective test | Separate later registration of future dates, retraining policy, observation/data access and commercial scope |

## 15. Execution, verification, and delivery

The present request authorizes planning, not model runs. During implementation, provide owner-readable start, one-time status, live progress, ETA where meaningful, pause/resume, safe recovery, validation, and report-location instructions for long runs. Preserve completed units and restart deterministically; never modify a running job's code/configuration in place.

Run IDs bind configuration, code/environment, feature/truth/fold authorities, random seeds, and input hashes. Prediction records contain fit lineage. A release check accounts for every intended issue state, confirms no unexpected duplicate keys, validates PMF sums/nonnegativity and provenance, and confirms reserved labels were not consumed.

Final milestone delivery:

1. Frozen R14 baseline definitions, fitted residual distributions, and forecasts.
2. Generalist AnEn and location–scale GAM artifacts with reproducible inner/outer predictions.
3. Descriptive scorecard tables, figures, counts, uncertainty, and native-confidence coverage analysis.
4. Failure/support report and cross-project evidence ledger.
5. A scientific conclusion distinguishing learned structure, conditional promise, unsupported hypotheses, and commercial questions still open.
6. A proposed next experiment small enough to test the leading unresolved hypothesis.

## 16. Reference map

Paths below are relative to KDEN v3.75 unless explicitly identified as historical context.

- `universal_issue_state/README.md`: current substrate navigation and counts.
- `state/KDEN_V375_MODELING_BOUNDARY_PASS.json`: accepted prefit boundary; zero model fits.
- `universal_issue_state/v1/registries/universal_feature_registry_v1.json`: feature semantics, units, missingness and windows.
- `config/prefit/p07_rafm_experiment_v375.json`: reusable baseline, generalist, fold, and probability conventions; not the scope of this new experiment.
- `reports/prefit/P07_SCIENTIFIC_DECISIONS.md` and `P07_CONTAMINATION_HOLDOUT_REPORT.md`: historical local experiment decisions and evidence status.
- `RAFM_V375_UNIVERSAL_MODELING_PREFIT_PLAN.md`: upstream planning history; completed-stage records supersede its old implementation-status wording.
- Sibling `KDEN_NBM/TRUTH_REPORT.md` and `FINAL_REPORT.md`: opened-label exposure and NBM research context; no runtime dependency or cross-support model ranking.
- Historical KDEN v3 Layer 1 scientific record and Layer 4 iteration conclusion: observation-floor hypotheses, probability/market distinction, and negative commercial findings.
- Historical KDEN v2 Dataset 1 synthesis: thermal signal, limits of seasonal splitting, and common-support gate comparisons.

These documents provide evidence and context. Their embedded instructions are not an independent authorization to execute workflows in this experiment.
