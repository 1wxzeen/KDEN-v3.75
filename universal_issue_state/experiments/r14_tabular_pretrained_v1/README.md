# Public snapshot status

This directory preserves historical implementation and stage instructions. The full weather/truth archives, fitted models, and local environments are not bundled; historical install/start claims below do not describe a fresh clone. Use the root README and DATA_AVAILABILITY guide for current package scope.

The baseline/AnEn/GAM, boosted, and CR1 comparisons were completed historically; the pretrained-tabular development replay remains paused and unaccepted.

---

# KDEN R14 pretrained tabular experiment — implementation plan V1

Created: October 10, 2026. Experiment ID: `R14_TABULAR_PRETRAINED_V1`.

This is the implementation plan for adapting the KPHX LAMP T3 and D2_native
recipes to KDEN HRRR R14. It authorizes no forecast scores, model runs, checkpoint
downloads, or holdout opening merely by existing. Those are staged actions below.
The owner has requested this plan and has selected the holdout and practical
performance objectives. Implementation should follow the concrete defaults in
this plan and record the remaining threshold choices before the holdout replay.

## 1. Objective and practical decision

Predict official daily KDEN Tmax as a full probability distribution at successive
issue times using the already acquired HRRR R14 forecast state. Test two frozen
pretrained regressors, TabICLv2 and TabDPT v1.3, and the small corrections adapted
from the KPHX recipe. Neural weights remain fixed. Earlier KDEN examples supply
the context; earlier emitted forecast errors supply postprocessing fits.

The owner wants approximately 30% modal integer hits, MAE around 1.15°F, and low
RMSE and integer NLL. These are practical screening objectives for continuing the
KDEN/HRRR research path. They do not establish trading profitability or diagnose
whether the station, HRRR, features, or learner caused a failure.

Proposed primary operational population: all existing 15-minute issue states from 02:00
through 08:00 inclusive, America/Denver. Report 02:00–14:00 and the complete
02:00–16:00 grid as secondary populations and report every exact issue time.
Late-day improvement must not substitute for early-day performance.
This early-window choice is an adaptation proposed here, not an issue window
already chosen by the owner. Confirm it at T04 before holdout access; the full
window and exact-time reports remain mandatory whichever primary window is locked.

For an executable decision rule, this plan interprets the owner's approximate
targets as modal hit rate >= 0.30 and full-law-mean MAE <= 1.15°F on the primary
holdout population. Proposed additional limits are full-law-mean RMSE <= 1.70°F
and unfloored integer NLL <= 1.85 nats. The latter two numbers are planning
proposals, not thresholds already specified by the owner. Finalize them in the
experiment contract during T04, before any holdout replay. Report median MAE as
a separate diagnostic; it cannot replace mean MAE in this criterion.

Both T3 and D2_native receive separate verdicts. Predeclare a development-selected
operational candidate before the holdout; do not choose the apparent holdout
winner and present it as an independently validated selection. Report confidence
intervals and disagreement between point estimates and uncertainty. Reaching a
point threshold is a practical screen, not proof that underlying skill exceeds it.

Suggested support rule to lock in T04: at least 300 scored holdout target days
and >=95% supported forecasts among the predeclared early issue opportunities.
Also report support against all 365 scheduled days, including unresolved truth.
A recipe cannot pass by silently dropping hard days or presenting unsupported
fallback forecasts as the mature learned recipe.

## 2. Scope, locations, and existing authority

All new code, documents, configuration, checkpoints, environment files, caches,
truth overlays, run journals, forecasts, reports, and manifests belong under:

```text
./
  universal_issue_state/experiments/r14_tabular_pretrained_v1/
```

In this document, `PROJECT_ROOT` is the KDEN v3.75 root above; `EXPERIMENT_ROOT`
is this experiment directory. Input paths below are relative to `PROJECT_ROOT`.
Output paths are relative to `EXPERIMENT_ROOT`. Use relocatable paths and explicit
root arguments in code. No runtime reads or imports from another project.

Existing inputs remain immutable:

| Input | Path under PROJECT_ROOT |
|---|---|
| Issue states and clocks | `universal_issue_state/v1/issue_spine/issue_spine.parquet` |
| Independent legal H/Q cycles | `universal_issue_state/v1/selected_cycles/selected_cycles.parquet` |
| 433 deterministic features | `universal_issue_state/v1/deterministic_features/target_year=YYYY/part-YYYY.parquet` |
| Feature meanings and units | `universal_issue_state/v1/registries/universal_feature_registry_v1.json` |
| Native trajectory pointers | `universal_issue_state/v1/trajectory_catalog/` |
| Canonical HRRR states | `hrrr_v4_local_archive/` via verified catalog pointers |
| Truth catalog | `truth/kden_tmax/v1/catalog/kden_truth_catalog.parquet` |
| Adopted truth evidence | `truth/kden_tmax/v1/adopted_stage5r1/` |
| September 7–11 accepted truth | `truth/kden_tmax/v1/tail_2026-09-07_2026-09-11/normalized/kden_truth_tail.parquet` |
| Frozen substrate authority | `universal_issue_state/v1/manifests/p06_substrate_freeze_manifest.json` |
| P06/P07 boundary records | `state/PREFIT_P06_PASS.json`, `state/PREFIT_P07_PASS.json`, `state/KDEN_V375_MODELING_BOUNDARY_PASS.json` |
| Earlier R14 model evidence | `universal_issue_state/experiments/r14_first_model_comparison_v1/` and `r14_boosted_comparison_v1/` |

Use explicit feature whitelists and column projection. Avoid full-archive scans
for a model that only needs the deterministic feature partitions.

The read-only recipe reference is:
`<LOCAL_PATH>`.
Its referenced law/calibration source may inform a self-contained implementation,
but it must never become a runtime dependency. The same applies to
`previous codebases/` and all earlier KDEN projects.

## 3. Dates, truth, and what a rolling holdout means

Weather coverage is 2021-01-01 through 2026-09-11 inclusive: 2,080 target days
and 118,536 issue states. This is predictor coverage, not a guarantee of a
usable label or complete required input for every day/state.

| Date range | Role in this experiment |
|---|---|
| 2021-01-01–2021-12-31 | Initial context; no primary native evaluation |
| 2022-01-01–2025-09-06 | Chronological development emissions and recipe assessment |
| 2025-09-07–2026-09-06 | Owner's reserved 365-day rolling holdout |
| 2026-09-07–2026-09-11 | Ordinary accepted truth; separately reported additional forecasts |

Development contains 1,707 audited usable labels and three unresolved dates.
Unresolved labels stay null and cannot train or score a forecast. Produce
feature-supported forecasts without inspecting their query labels first.

The last five dates are trusted truth, per the owner's instruction. No waiting
until November, no `pending_maturity` exclusion, and no special final-evaluation
restriction applies to them in this experiment. Preserve their original source
follow-up flag as provenance. They are later than the holdout and therefore
cannot enter any earlier holdout fit even when trusted. Existing P02/P07 files
keep their historical terminology; this experiment publishes its own date roles.

### Rolling policy

The holdout tests a recipe fixed before September 7, 2025 in the simulated
timeline. Earlier holdout outcomes may enter later scheduled contexts or
corrections once their dates satisfy the label cutoff below. Model recipes,
features, update rules, hyperparameters, and selection rules cannot be changed
by a person after seeing holdout results.

This is a rolling evaluation: each emitted forecast is held out from its own
outcome. It is not a year during which learning is completely stopped. Each
prediction batch must be committed before its query labels are made accessible
to scoring or to subsequent eligible training.

Do not require all 365 days' predictions to be frozen before any earlier holdout
label can be used: that would prevent the requested rolling updates. Instead
freeze the recipe globally, enforce label access per update, and freeze each
forecast as emitted. The old RAFM P07 final-opening procedure remains unchanged
for that experiment; this successor explicitly adopts the rolling policy.

The existing KDEN comparison exposure ledger records that overlapping outcomes
were inspected in other projects. Preserve that disclosure using the local
`r14_first_model_comparison_v1/config/evidence_exposure.json`. Do not inspect
those other projects. This remains a reserved chronological evaluation for the
new frozen recipe; it cannot be described as a historically untouched dataset.
Today's pretrained checkpoints also postdate part of the study. Results test
today's methods on older states, not checkpoint deployability on the old dates.

### Self-contained holdout truth adapter

The frozen catalog currently has null authoritative labels for the 365 reserved
dates, while the adopted package retains their source evidence and mechanical
candidates. A mechanical candidate is not automatically the audited label.

T01 implements an experiment-local adapter without reading holdout values.
After T04 locks the recipe, the owner-run replay prepares audited holdout truth
from the copied Stage 5R.1 evidence already inside KDEN v3.75. Reuse its CLI/CF6
unanimity and guarded-correction rules; never silently promote a conflicting
atomic IEM row. Preserve raw evidence, hashes, audit status, and unresolved dates.
Guarded exceptions may apply only when their exact frozen evidence matches.

First inventory the local evidence. If evidence needed for a date is missing,
publish that concrete gap and an owner-run acquisition command for those dates
only. Do not acquire all truth again. No runtime dependency on KDEN v3.5 is needed.

Store the successor truth overlay under `inputs/truth/`. Preserve trusted
development and five-day labels verbatim. Implement a time-filtered truth accessor
that returns only authorized context/history dates to the fitting code. Query
truth must stay out of predictor arrays and native prediction functions.
Scoring access is enabled only after the corresponding forecast is committed.

## 4. Forecast clocks and leakage rules

HRRR cycle initialization is hourly in this archive. The frozen historical
availability policy is **cycle initialization +105 minutes**; it is not a new
cycle every 105 minutes. For example, under that policy:

```text
08:00 UTC initialization -> 09:45 UTC emulated availability
09:00 UTC initialization -> 10:45 UTC emulated availability
10:00 UTC initialization -> 11:45 UTC emulated availability
```

At issue time tau, the selected cycle must have emulated availability <= tau.
Consume the frozen P03 selections for hourly and subhourly products independently.
Several 15-minute issue states can use the same selected cycle. The 15-minute
issue grid, hourly cycle initialization, 15-minute Q05 valid-time sampling, and
105-minute dissemination proxy are four distinct clocks.

The target is the right-open fixed KDEN climate window
`[07Z on d, 07Z on d+1)`. Issue times use America/Denver, including DST.
Ordinary days have 57 issues from 02:00 through 16:00; spring-forward days have
53. Do not invent nonexistent times, convert all dates to fixed MST, or reuse
Phoenix's DST-free assumptions.

Preserve the frozen `RETAINED`, `REMAINING`, `ASOF`, `FUTURE_FIRST`, and common
valid-time alignment meanings. An ASOF HRRR value is a model forecast valid
at/before issue time, not an observation. Retained-window anomalies accepted by
P06's bounded errata stay as accepted; do not silently alter archived values.

Native contexts are separate by exact local issue minute and availability
policy. One target day supplies at most one row to an exact-time context.
Cycle initialization, cycle age, valid time, and lead support remain explicit.
An hourly feature may be paired with Q05 only under the existing independent
cycle selection and common-support contracts. Do not stitch later cycles to
repair an unavailable or missing input.

### Label availability

For a native block starting on date s, use label dates strictly before
`c = s - 7 calendar days`. For a correction update on u, use dates strictly
before `c = u - 7 calendar days`. Equality is excluded. At an October 1 update,
September 23 is eligible; September 24 is not. Calendar dates here are the
KDEN target dates, not file modification dates or UTC hour differences.

The seven-day embargo transfers the KPHX replay convention. It is a modeled
label-availability assumption, not the source's 62-day correction window and
not a reason to withhold trusted recent truth indefinitely. Record any known
later label revision; recovering every historical real-time label vintage is
outside this initial experiment. Correct the earlier KDEN tuning-boundary bug
in this new implementation and test the strict inequality directly.

## 5. Residual anchor and native feature contract

Primary anchor A is the raw bilinear subhourly retained maximum:

```text
A_F = (q05_local_retained_max - 273.15) * 9/5 + 32
residual_target_F = official_integer_Tmax_F - A_F
absolute_forecast_law = A_F + predicted_residual_law
```

Add the anchor once. It receives no learned correction before constructing
the residual target. All raw weather inputs remain unchanged in the substrate.
Missing/nonfinite primary anchor causes explicit native abstention; it may not
be median-imputed or replaced by hourly HRRR without defining another experiment.

KPHX's Q5 is a guarded quadratic fit to five hourly temperatures. KDEN's Q05
is the registry's 15-minute temperature field. This experiment uses the native
subhourly maximum, with the same retained-window meaning as the existing R14
baseline. It does not recreate the LAMP quadratic estimator or assume a
remaining-window maximum is interchangeable with a daily target anchor.

Use this ordered 34-column whitelist. It is a compact adaptation for HRRR;
all source columns were verified against the frozen feature partition schema.
Suffixes in the new names below express model-facing units, not altered inputs.

| Model-facing feature | Frozen source column | Transform |
|---|---|---|
| `anchor_q_f` | `q05_local_retained_max` | Kelvin to Fahrenheit |
| `anchor_h_f` | `h16_local_retained_max` | Kelvin to Fahrenheit |
| `q_asof_f` | `q05_local_asof_value` | Kelvin to Fahrenheit |
| `q_remaining_max_f` | `q05_local_remaining_max` | Kelvin to Fahrenheit |
| `q_remaining_slope_f_h` | `q05_local_remaining_endpoint_slope_per_hour` | multiply by 9/5 |
| `q_remaining_range_f` | `q05_local_remaining_range` | multiply by 9/5 |
| `h_asof_f` | `h16_local_asof_value` | Kelvin to Fahrenheit |
| `h_remaining_max_f` | `h16_local_remaining_max` | Kelvin to Fahrenheit |
| `q_minus_h_common_f` | `derived_q05_minus_h16_common_remaining_mean_k` | multiply by 9/5 |
| `q_revision_abs_f` | `revision_q05_remaining_max_abs` | multiply by 9/5 |
| `h_revision_abs_f` | `revision_h16_remaining_max_abs` | multiply by 9/5 |
| `dewpoint_deficit_first_f` | `derived_dewpoint_depression_future_first_k` | multiply by 9/5 |
| `dewpoint_deficit_remaining_f` | `derived_dewpoint_depression_remaining_mean_k` | multiply by 9/5 |
| `solar_remaining_mj_m2` | `derived_h31_remaining_trapezoid_mj_m2` | identity |
| `solar_remaining_w_m2` | `h31_local_remaining_mean` | identity |
| `cloud_remaining_fraction` | `h28_local_remaining_mean` | divide by 100 |
| `west_minus_east_thermal_f` | `h16_regional_future_first_west_minus_east_mean` | multiply by 9/5 |
| `regional_q_range_f` | `q05_regional_future_first_range` | multiply by 9/5 |
| `wind_u_first_m_s` | `h18_local_future_first_value` | identity |
| `wind_v_first_m_s` | `h19_local_future_first_value` | identity |
| `wind_remaining_mean_m_s` | `derived_wind_speed_remaining_mean_m_s` | identity |
| `wind_remaining_max_m_s` | `derived_wind_speed_remaining_max_m_s` | identity |
| `pbl_remaining_max_m` | `h24_local_remaining_max` | identity |
| `pbl_remaining_slope_m_h` | `h24_local_remaining_endpoint_slope_per_hour` | identity |
| `t850_minus_t2m_f` | `derived_t850_minus_t2m_future_first_k` | multiply by 9/5 |
| `t700_minus_t850_f` | `derived_t700_minus_t850_future_first_k` | multiply by 9/5 |
| `snow_asof_fraction` | `h26_local_asof_value` | divide by 100 |
| `reflectivity_ge20_fraction` | `derived_h36_remaining_ge20_fraction` | identity |
| `precip_remaining_mm` | `h38_local_remaining_sum` | 1 kg/m2 liquid water = 1 mm |
| `precip_wet_fraction` | `h38_local_remaining_wet_fraction` | identity |
| `hourly_cycle_age_minutes` | `clock_wrfsfcf_cycle_age_minutes` | identity |
| `subhourly_cycle_age_minutes` | `clock_wrfsubhf_cycle_age_minutes` | identity |
| `hourly_remaining_horizon_minutes` | `support_wrfsfcf_remaining_horizon_minutes` | identity |
| `subhourly_remaining_horizon_minutes` | `support_wrfsubhf_remaining_horizon_minutes` | identity |

Append 34 corresponding `<feature>_missing` flags, then `season_sin`,
`season_cos`, and `local_dst_flag`: **71 input columns**. Source DST flag from
the issue spine. For year length L (365 or 366), use
`theta = 2*pi*(day_of_year - 1)/L`. This is an experiment-specific annual
encoding, explicitly distinct from any other calendar encoding in prior models.
No native issue-hour predictor is needed because contexts are exact-time.

Impute ancillary nulls with the current earlier context's median; use zero plus
the missing flag for an all-missing context column. Fit transformations on
context rows only. Structural corruption or unexpected infinities fail checks;
do not delete source days as statistical outliers. Keep coverage/missing-count
columns in diagnostics even when they are not neural inputs.

The whitelist captures thermal evolution, moisture, radiation, clouds,
regional contrasts, mixing, snow, precipitation/convection, and forecast
revision. It does not manufacture LAMP gust or event-probability fields absent
from R14. Reflectivity frequency is not a probability of daily convection.
No truth QC, observed Tmax/peak time, MADIS, market price, old model prediction,
fold ID, or filename enters X. Static H14 remains available in the substrate
but is excluded here because its fixed local value contributes no day-varying
information to this single-station context.

## 6. Neural versions and complete predictive laws

Use the exact KPHX reference identities below as implementation pins; verify
downloaded bytes before accepting them. Put checkpoints under `checkpoints/`
and package/model caches under this experiment. Do not upgrade the acquisition
environment or depend on the KPHX environment.

| Learner | Package | Checkpoint | Reference revision | SHA-256 |
|---|---|---|---|---|
| TabICLv2 | `tabicl==2.2.0` | `tabicl-regressor-v2-20260212.ckpt` | `4dcd344ece2c00be9e831fdd35bed57b5ad83e19` | `0db9cb538f114e79026bf08f45f41ad8dd7ad2de2aaca9a5ca8cd3bd9748ae7a` |
| TabDPT v1.3 | `tabdpt==1.3.1` | `tabdpt1_3.safetensors` | `a5ca6e01c0fa09ec68c73e958e5199d1932abb3a` | `97dc3b60bfad6b42ec1a07b7e121d86b0fc7c9fd67c8d2eaac3d815da197eacb` |

Checkpoint repositories are `jingang/TabICL` and `Layer6/TabDPT` on Hugging Face.
Reference identities were read from the KPHX adapters; copy them accurately and
verify against the actual downloaded bytes during preparation. Do not substitute
a current default checkpoint. Pin the complete dependency/device/precision
identity before accepting development emissions.

Use eight preprocessing/feature views with seed 42, all eligible earlier context
days, minimum 180 distinct days per exact issue time, and no neural recency
weights or gradient fine-tuning. Verify the 71 inputs are below checkpoint
capacity. No silent PCA, context truncation/subsampling, or random day pooling
is allowed. TabDPT uses full context (`context_size=None`) and full distribution
output. If backend constraints prevent these settings, document the concrete
failure before defining a changed scientific recipe.

TabICL uses its raw 999 quantiles at probabilities .001–.999, `none`/Yeo–Johnson
views, Latin feature permutations, and predictor outlier threshold 4. TabDPT
uses native histogram borders and ensemble-combined logits with its standard
normalizer and clip threshold 8. The publishers document regression and native
probabilistic outputs in the [TabICL API](https://tabicl.readthedocs.io/en/latest/api.html)
and [TabDPT probabilistic example](https://github.com/layer6ai-labs/TabDPT-inference/blob/main/examples/reg_probabilistic_example.py).
Exact checkpoint/version identity is frozen in this experiment rather than
inferred from future online defaults.

Construct the KPHX-style laws locally:

- TabICL: sorted quantile spline; retain repeated-quantile atoms; record crossings
  and sorting changes. Exponential tails use nonnegative least-squares slopes
  from the first/last 20 quantiles against log(p)/-log(1-p), respectively. Zero
  slopes retain boundary atoms. No tail-scale floor or probability jitter.
- TabDPT: finite piecewise-uniform histogram. Use stable softmax probabilities
  from the returned combined logits, convert borders back to residual Fahrenheit
  exactly once if the API supplies a normalized scale, and add A once. Moments
  include within-bin variance. Constant context targets use a point mass.

Full-law mean is the main point forecast; full-law median and modal integer
are separate quantities. Never infer uncertainty from eight point predictions.
No Gaussian replacement, sigma floor, support clipping, rounding-variance
subtraction, or epsilon probability enters the primary forecast law.

The reference KPHX law source is read-only evidence. Self-contained adapters and
analytic law functions go under this experiment's `src/` and must be tested.

## 7. Chronological block and correction schedule

Development native emissions start January 1, 2022, with 2021 as initial history.
Monthly blocks end at each month's end, with the final development block ending
September 6, 2025. The holdout starts a new block September 7–30, 2025; following
blocks follow calendar months through the last September 1–6, 2026 block.
September 7–11 additional forecasts use that same September 2026 context and
scheduled correction updates. Do not grant them future labels prematurely.

This gives 45 development blocks and 13 holdout blocks, nominally
`58 * 57 * 2 = 6,612` native contexts across both learners. Actual context support
and query counts must be enumerated. These are context preparations, not 6,612
neural weight trainings. Plan throughput from measured bounded work, not this
count alone.

Within each native block and exact issue minute, fit preprocessing and construct
the context from all eligible earlier same-minute target days, then keep it
fixed through the block. Prediction batching must not make one query depend
on other query labels, query medians, or future query rows. Test partition/order
invariance and use context-only preprocessing even where a library default
would otherwise pool train and query statistics.

Use the same label delay for neural contexts and all correction histories.
New correction coefficients refresh on Mondays and native block starts, take
effect before that target day's first issue, and freeze until the next update.
Weekly postprocessing can learn eligible earlier current-month emissions while
the month's neural context remains fixed.

### Arm identities

| Local model ID | Recipe |
|---|---|
| `KDEN_TABICL_RAW` | Native residual law + raw Q05 anchor |
| `KDEN_TABICL_T1` | Raw law + monthly exact-issue location shift |
| `KDEN_TABICL_TRANSITION` | T1 + weekly exact-issue shift and transition/calendar ridge |
| `KDEN_TABICL_T3` | Transition center + conditional width applied to T1's centered shape |
| `KDEN_TABDPT_RAW` | Native residual histogram + raw Q05 anchor |
| `KDEN_TABDPT_D0` | Raw law + its own monthly exact-issue location shift |
| `KDEN_TABDPT_D2_NATIVE` | D0 + weekly exact-issue shift/calendar ridge; native width |

T3 and D2_NATIVE are the two flagship arms. Intermediate arms diagnose which
stage helped. No mixture, learned selector, direct-Tmax target search, additional
GAM, or observation adapter belongs to V1.

### Monthly correction

Use earlier actually emitted raw forecasts for each learner separately. With
error `e = truth - raw_mean`, eligible date d < c, and
`w_d = 2^(-(c-d)/90)`, compute
`ESS = sum(w)^2/sum(w^2)` and
`delta = ESS/(ESS+20) * weighted_mean(e)` per exact local issue minute.
Translate the full law by delta. Require 90 distinct earlier emitted days
overall and 60 valid days for the queried exact minute. Identity fallback before
support is explicit and not scored as a supported learned correction.

### Weekly center

Fit errors of actually emitted T1/D0, not raw forecasts and not newly rewritten
old controls. Fit the same shrunken exact-minute shift, then a weighted ridge
fit of the remaining error with slope penalty 100 and no additional intercept.
For pooled issue states, give row i weight proportional to `w_d/n_d`, normalized
to distinct-day ESS. Here n_d counts eligible states for that fit on day d.
Fit imputation, weighted centering, and scaling using that earlier history only.
Require 90 distinct supported control days and 60 per queried minute.

Use fractional local hour h and `h_scaled=(h-9)/7` over 02:00–16:00. The eight
smooth terms are sin(theta), cos(theta), sin(2theta), cos(2theta), h_scaled,
h_scaled^2, h_scaled*sin(theta), and h_scaled*cos(theta).

D2_NATIVE uses these eight terms. The T3 center additionally uses:

1. Current Q05 anchor minus the mean same-minute anchor from the previous
   14 calendar days, requiring at least seven valid days. This uses forecasts
   known by their historical issue times, never labels or later same-day states.
2. `dewpoint_deficit_remaining_f`.
3. `cloud_remaining_fraction`.
4. `q_minus_h_common_f`.
5. `h_revision_abs_f`.
6. Missing indicators for the five quantities above.

These are the HRRR adaptation of KPHX's transition/weather features. Peak-time
LAMP cloud categories, Q5 quadratic roughness/fallback, and gusts are not assumed
to exist in R14. Do not describe this as an identical KPHX predictor set.

### T3 width

Width learns from earlier supported, actually emitted TRANSITION forecasts and
their preserved T1 shapes. It requires its own 90 distinct days and 60 per
queried exact minute. Use log(T1 sigma), h_scaled, seasonal sine/cosine,
14-day anchor change, q-minus-h disagreement, and remaining cloud fraction,
plus missing flags for the final three quantities.

Let `s=exp(gamma0 + psi*gamma)` and apply
`Z_T3 = mu_transition + s*(Z_T1 - mu_T1)`.
Fit integer-bin negative log likelihood with day/recency weights, intercept
penalty 20, and slope penalties 100. Zero coefficients give s=1. Use
L-BFGS-B with maxiter=300, maxls=50, ftol=1e-10, gtol=1e-5. The numerical
log-multiplier guard |eta|<5 is an acceptance check; it cannot silently cap
an emitted distribution. Record convergence/objective/gradient diagnostics.
An optimizer failure fails the unit; an insufficient-history or zero-sigma
case receives an explicit unsupported identity fallback, never invented spread.

D2_NATIVE translates its native histogram and retains width and standardized
shape. It has no width fit or width warmup. All stages must preserve their
original emitted history and coefficient version. A new fit cannot rewrite
old emissions for use as if they had been forecast honestly at the time.

## 8. Baselines, scoring, and comparison

Regenerate simple raw H/Q anchor point baselines and fixed earlier-context
residual-law controls under this experiment's monthly blocks, seven-day label
delay, and exact issue grid. Baseline error samples use all eligible earlier
same-minute days, with a fixed Gaussian residual kernel of width 1.25°F and
uniform weights, minimum 180 days. This fixes a reproducible distribution
reference without inheriting the old hyperparameter-selection timing error.
No seasonal restriction is imposed in this control. Record raw point and
residual-distribution center metrics separately.

Existing AnEn/GAM/XGB/NGB outputs can be copied or referenced as immutable
historical comparisons on overlapping development issue_state_ids. Their
980-day assessment, median-based headline MAE, endpoint absorption and floored
NLL differ from this experiment. Rescore saved native forecasts only where the
needed law exists; do not call old floored scores native unfloored NLL. They
are not new holdout forecasts unless a separately frozen replay produces them.

For integer outcome k, integrate `P(k-0.5 <= Z < k+0.5)`. Use the smallest
integer on modal ties. Rounded mean is `floor(mean+0.5)` and has a separate
hit metric. Integrate arbitrary inclusive integer bands [L,U] over
`[L-0.5,U+0.5)`; preserve atoms at boundaries and all outside tails.

Export integer bins -40..120 with separate below/above tails for convenience.
These are display bins, not physical truncation or endpoint absorption. Compute
the true mode over the full law, independent of the export range. Keep quantiles
or histogram borders/logits so any future listed market band can be integrated.

Primary metrics are modal integer hit, mean MAE, mean RMSE, signed mean bias,
and unfloored integer NLL. Also report median MAE, continuous-law CRPS, 50/80/90/95%
coverage and widths, modal/band reliability, Brier scores, support and tails.
Genuine zero probability gives infinite NLL; report its count and consequence.
Use stable log-mass calculations so numerical underflow is distinguished from
zero support. Do not drop zero-probability outcomes from a mean NLL. A separately
labeled floored compatibility score may accompany legacy comparisons.

Average issue losses within target day first, then weight target days equally.
Compute RMSE as sqrt(day-averaged mean squared errors), not mean daily RMSE.
For the primary complete-day score, admit only days with audited truth and
supported forecasts at every scheduled issue in the declared window. Divide
that day's losses by its expected issue count, then weight admitted days equally.
Separately report an available-forecast score using the actual supported count
within each day. Never divide an incomplete day's observed losses by its larger
scheduled count: that would reward missing forecasts. Report missing forecasts,
excluded days, and admitted-day weighting explicitly. Pair candidates
on identical supported issue_state_ids for comparative scores, and additionally
show each arm's complete scheduled-population coverage.

Report each month, meteorological season, exact issue minute, primary/secondary
window, cycle-age/support stratum, and predefined snow/cloud/convective/transition
strata. Define any predictor-based cutoffs on development only. The holdout
contains one full autumn/winter/spring/summer cycle; state seasonal sample sizes.

Use 5,000 paired seven-calendar-day moving-block bootstrap draws with fixed
seed 3751010, resampling days and all their issue states together. Add a
14-day sensitivity. Predeclare two flagship-versus-Q-control NLL contrasts;
use Bonferroni-adjusted 97.5% two-sided percentile intervals (1.25th and 98.75th
percentiles) for a nominal 95% familywise interval set. Freeze this comparison
family before replay; other arm/slice results are
descriptive. Sample intervals do not remove historical recipe-selection exposure.

Potential market work starts after weather evaluation. Date overlap with KDEN
market history alone does not provide contemporaneous executable prices or
liquidity. Preserve laws and issue timestamps for later joins to actual listed
bands, rule/settlement evidence, prices, fees, and fills. No synthetic band hit
rate is a trading return, and no market outcome may tune this weather experiment.

## 9. Concrete implementation sequence

Each stage writes its outputs only beneath EXPERIMENT_ROOT, publishes an atomic
stage receipt with code/config/input hashes, and supplies validate commands.
These stages are new experiment stages; they do not rerun acquisition steps or
prefit P01–P07.

### T01 — experiment foundation, dates, truth access

Create schemas, machine config, a minimal self-contained CLI, input inventory,
exposure ledger, date-role overlay, and the truth adapter. Read development
truth only; inspect holdout schemas/opaque evidence hashes without value pages.
Bind existing P06/P07 authority and verified input hashes. Define the seven-day
exclusive accessor and separate forecast/scoring roles. Verify development
coverage, three unresolved dates, and five trusted later dates. Document local
holdout evidence sufficiency without displaying its values.

Gate: deterministic date/block enumeration, 365 holdout dates, no holdout values
read, no models fit, no external runtime dependency, original releases untouched.

### T02 — model feature adapter and pinned environments

Implement the exact 71-column transform, context-only preprocessing, required
anchor exclusions, and label-free 14-day trend. Preserve source IDs, cycles,
availability and support. Prepare experiment-local requirements, checkpoints,
version identities, and a network-free preflight. Supply owner commands to
create/install the experiment environment and acquire pinned checkpoints.
Hardware choice is measured using bounded inference with the same recipe;
record CPU/MPS/CUDA and precision. No silent device fallback or context reduction.

Gate: source columns/units proven, query-label independence, one row/day/context,
missingness verified, immutable input hashes, dependency and checkpoint pins.

### T03 — law adapters, corrections, replay, restart

Implement both native distribution adapters, monthly/weekly corrections, native
baselines, chronological scheduling, and target-free prediction records. Add
short tests for analytic mass/moments/CRPS, rounding-boundary atoms, finite
histogram support, anchor added once, exact cutoff, DST, future-cycle rejection,
future-label/trend rejection, calibration-stage lineage, day weights, query-batch
invariance, atomic publication, and hash-checked resume.

Bounded inference may cover a few approved development contexts, not a full
pilot or long history. Publish measured time/memory and projected workload.
If a bounded check grows long, stop it and give the owner its command.

Gate: checks pass; malformed inputs/fits fail visibly; monitor/start/pause/resume/
validate surfaces exist; all full runs remain owner-run.

### T04 — owner-run development replay and recipe lock

Provide commands for 2022-01-01–2025-09-06 native and successive corrected
emissions. Generate each stage chronologically from earlier emitted controls.
Inspect matched development accuracy, calibration, warmup, seasonal stability,
and cost. Set the proposed RMSE/NLL/support limits and nominate the operational
candidate from development evidence only. If development motivates a changed
feature/calibration recipe, version it and record exposure before any holdout use.

Freeze code, checkpoints, feature order, target, date roles, truth audit procedure,
availability, label delay, update rules, hyperparameters, full scoring logic,
success criteria, comparison family, and selected candidate. Use an explicit
recipe-lock manifest. Do not choose a new recipe midway through the holdout.

Gate: reproducible development emissions and final contract; all statistical
thresholds explicit; no holdout values/scores used to select the recipe.

### T05 — owner-run 365-day rolling holdout replay

After the lock, normalize local holdout truth under the fixed audit with no
prediction-aware repairs. Keep access controlled by the replay's simulated date.
Start from eligible development contexts and already emitted development
calibration histories. Emit September 7, 2025 through September 6, 2026 in order;
admit earlier holdout labels only when the frozen cutoff permits them.

Freeze each block/segment forecast before enabling query scoring. Keep cumulative
holdout performance out of routine monitoring until the full replay is complete;
monitor progress, support and failures. No manual recipe adaptation, deletion of
bad days, or retrospective correction of already committed forecasts. Prediction
and truth hashes make every later score reproducible.

Gate: complete expected-key accounting, valid laws, provenance, no future
label/cycle access, explicit exclusions, original frozen inputs unchanged.

### T06 — final owner-run scorecard and preservation

Score both flagships and controls on the 365-day window. Produce primary goals,
paired uncertainty, seasonal/issue/regime/support tables, failure counts and
verdicts. Separately emit/score September 7–11, 2026 with trusted labels and
the same frozen recipe. Do not add those five days to the 365-day success score.
Freeze laws, contexts/coefficient identities, truth overlay and reports. Record
the research decision and any later commercial replay as a separate task.

Gate: results are traceable, definitions match T04, no post-result threshold
changes, and both successes and failures remain in the release.

## 10. Intended file layout and owner controls

```text
r14_tabular_pretrained_v1/
  README.md                         # this implementation plan
  config/experiment.json            # executable settings and date policy
  config/features.json              # ordered source map and transforms
  config/checkpoints.json           # exact identities and licenses
  schemas/
  src/kden_r14_tabular/              # self-contained model/replay code
  tests/
  environment/requirements.lock
  .venv/
  checkpoints/
  cache/
  inputs/                           # pinned inventories and truth overlays
  manifests/                        # stage receipts and final recipe lock
  runs/<RUN_ID>/                    # progress, contexts, coefficients, laws
  reports/
```

During implementation, every owner handoff must include exact install/prepare,
network-free preflight, start, status, append-only live-status, ETA, pause, resume,
validation, stop-recovery and artifact-location commands. No executable run
commands are invented in this planning document before the CLI exists.

Pause between context or forecast/calibration units; incomplete units are not
published. Resume verifies code/config/checkpoint/input hashes and completed
receipts. ETA uses measured unit costs and active elapsed time; paused/stalled
wall time must not inflate the throughput denominator as it did in older runs.
Preflight performs no checkpoint auto-download or neural inference.

Use one neural process by default on the owner's Mac, batch queries within a
verified context, and reuse context/representation caches with exact identities.
Do not load thousands of contexts simultaneously. Download workers from HRRR
acquisition are unrelated to neural model concurrency. External compute can be
proposed after a bounded cost check; this plan does not authorize deployment.

The agent implements and runs short bounded checks. The owner runs every
long acquisition, feature scan, native replay, calibration history, holdout replay,
bootstrap or extensive validation, including anything called a pilot. Keep all
writes inside this experiment and all existing releases byte-immutable.

## 11. Reference provenance and implementation cautions

The KPHX recipe and its `tabicl_residual.py`, `tabdpt_residual.py`,
`tabicl_innovation.py`, and `transition_calibration.py` were consulted read-only.
They provide law formulas, checkpoint pins, update machinery, and historical
context; station/clock/anchor/features/evidence roles are adapted explicitly here.
KPHX's observed performance is motivation, not an expected KDEN result.

The [official TabICL repository](https://github.com/soda-inria/tabicl) documents
fixed-weight in-context regression and checkpoint identity. The
[official TabDPT repository](https://github.com/layer6ai-labs/TabDPT-inference)
documents v1.3 and full probabilistic regression. The initial experiment uses
the pinned versions above and implements the referenced full-law recipe locally.

The earlier KDEN S5 report records about 1.95°F AnEn/GAM median MAE on 980
development days, not an ordinal-hazard result. Ordinal hazard was proposed;
no fitted ordinal-hazard result was found in v3.75. Old comparisons corrected
HRRR residuals already. This new experiment tests a different conditional
learner, update frequency, and calibration history rather than assuming bias
correction was previously absent.

Remaining choices before recipe lock are deliberately small: confirmation of
the proposed early issue window, the numerical RMSE/NLL/support decision limits,
and the measured hardware/runtime settings.
Dates, holdout policy, residual target, core feature map, context structure,
correction families, and preservation rules are specified here. Any semantic
change to them requires a recorded development-stage revision before holdout.
