# KDEN decision-to-evidence map

Prepared October 23, 2026. Read with the [research index](RESEARCH_INDEX.md).
Each entry follows a design decision into concrete implementation and checks,
then identifies the strongest justified conclusion. Test references show where
behavior is checked; no tests or long acceptance scans were rerun to create
this documentation. Saved reports are cited as existing historical evidence.

## D01 Define what was knowable at forecast issuance

**Decision and reasoning.** Keep target day, issue time, cycle initialization,
availability, physical valid time, and lead distinct. Select hourly/subhourly
cycles independently and use a fixed right-open climate day. Dense issue rows
must not fabricate nonexistent spring-forward times or splice newer forecasts
into older information sets.

- Design: [R14 handoff](../reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md),
  [prefit plan](../RAFM_V375_UNIVERSAL_MODELING_PREFIT_PLAN.md).
- Implementation: [schedule](../src/kden_v375/r14_schedule.py),
  [issue spine and cycle selection](../src/kden_v375/prefit/p03_issue_spine.py).
- Checks: [right-open schedule tests](../tests/unit/test_r14_schedule.py),
  [issue-spine tests](../tests/unit/test_prefit_p03_issue_spine.py).
- Saved acceptance: [P03](../state/PREFIT_P03_PASS.json),
  [P06](../state/PREFIT_P06_PASS.json).

**Supported conclusion.** An explicitly governed historical information set was
built. Initialization plus 105 minutes is an availability emulator, not proof of
every archive object's original receipt time. HRRR initializes hourly; 105
minutes is not the spacing between successive initializations.

## D02 Reduce acquisition scope without reducing temperature-path density

**Decision and reasoning.** Preserve native hourly and quarter-hourly paths,
but narrow the source union using meteorological mechanisms, possible
redundancies, and acquisition cost. Keep lower/middle-level thermal context,
moisture, wind, mixing, snow, cloud, solar, and modeled precipitation/echo context.

- Research question: [Step 04.5 brief](../STEP_04_5_FEATURE_UNIVERSE_STUDY.md).
- Accepted choice: [final R14 handoff](../reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md).
- Contract: [acquisition scope](../config/r14_acquisition_v375.json),
  [spatial contract](../config/r14_spatial_contract_v375.json).
- Implementation: [R14 contracts](../src/kden_v375/r14.py),
  [request plans](../src/kden_v375/r14_request_plans.py).
- Checks: [scope](../tests/unit/test_r14_scope_contract.py),
  [request planning](../tests/unit/test_r14_request_plans.py).

**Supported conclusion.** The accepted union contains 12 dynamic hourly
identities, one static terrain identity, and Q05. It deliberately sacrifices
other information. Neither pilot feasibility nor a smaller request plan proves
that the omitted fields have zero incremental predictive value. The early
41.5-day and later reduced-duration numbers were projections, not a controlled
measured speedup experiment.

## D03 Retrieve source messages efficiently while retaining failure evidence

**Decision and reasoning.** Use source-object indexes and verified byte ranges,
persistent HTTPS, exact-adjacent coalescence, and bounded workers. Distinguish
confirmed source absence from transport failure, selector ambiguity, or corrupt
cache evidence. Retain extracted values and provenance rather than all GRIBs.

- Design: [acquisition memo](../KDEN_HRRRv4_Local_Archive_Acquisition_Memo_v1.0.md),
  [project contract](../PROJECT.md).
- Implementation: [HTTP/range checks](../src/kden_v375/io/http_range.py),
  [source-object processing](../src/kden_v375/acquisition/source.py),
  [resumable acquisition workflow](../src/kden_v375/acquisition/workflow.py).
- Checks: [HTTP tests](../tests/unit/test_http_range.py),
  [acquisition tests](../tests/unit/test_r14_acquisition.py),
  [atomic publication](../tests/unit/test_atomic.py).
- Saved result: [acquisition PASS](../state/KDEN_V375_ACQUISITION_PASS.json).

**Supported conclusion.** Full-history acquisition and acceptance have saved
completion evidence. The 8,919,598 logical requests are not separate downloads
or independent observations. There is no need to rerun acquisition to prepare
the portfolio. Older source code was reference material, not a runtime import.

## D04 Preserve spatial and interval meanings instead of treating fields as names

**Decision and reasoning.** A point interpolation, a neighborhood summary, and
an upstream support answer different questions. So do instantaneous radiation,
interval-mean flux, and accumulated precipitation. Explicit geometry, units,
coordinate eras, and interval metadata prevent silent scientific substitutions.

- Design: [R14 spatial contract](../config/r14_spatial_contract_v375.json),
  [field identities and intervals](../reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md).
- Implementation: [GRIB identity checks](../src/kden_v375/io/grib.py),
  [feature operators](../src/kden_v375/prefit/p04_features.py).
- Checks: [GRIB contracts](../tests/unit/test_grib_contracts.py),
  [feature tests](../tests/unit/test_prefit_p04_features.py).

**Supported conclusion.** The pipeline defines and checks the quantities it
extracts and derives. A physically motivated spatial summary is not proof of a
causal effect or an experimentally validated optimal extraction geometry.

## D05 Treat raw parsed Tmax as a candidate, not an infallible label

**Decision and reasoning.** Preserve original values and report chronology.
Use accepted CLI/CF6 agreement and evidence-guarded exceptions; leave unresolved
truth null. Adopt existing rigorously audited work rather than reacquiring it
and accidentally discarding its corrections.

- Coverage and status: [P02 report](../truth/kden_tmax/v1/reports/P02_TRUTH_COVERAGE_QC.md).
- Adoption and extension: [P02 workflow](../src/kden_v375/prefit/p02_truth.py),
  [audit rules](../src/kden_v375/prefit/p02_rules.py).
- Checks: [truth-rule and adoption tests](../tests/unit/test_prefit_p02_truth.py).
- Saved acceptance: [P02 PASS](../state/PREFIT_P02_PASS.json).

**Supported conclusion.** v3.75 adopted the Stage 5R.1 package and extended it
for five additional dates. Its 1,710 development dates include 1,707 usable
labels and three unresolved dates. Later accepted truth is not excluded merely
because a follow-up window was open; experiment-specific chronology still
governs whether it can enter training. Do not claim 2,080 audited training
labels, a newly performed all-history audit in v3.75, or that every historical
discrepancy was an IEM error. The public package should not expose sealed
outcome files simply to demonstrate provenance.

## D06 Freeze a model-neutral dataset before experimenting

**Decision and reasoning.** Separate weather, labels, folds, and model outputs.
Publish stable issue keys, a feature registry, and trajectory references so
later model families share the same source semantics without modifying accepted
data or materializing every possible model view.

- Design: [P01–P07 plan](../RAFM_V375_UNIVERSAL_MODELING_PREFIT_PLAN.md),
  [substrate guide](../universal_issue_state/README.md).
- Implementation: [P04 definitions](../src/kden_v375/prefit/p04_features.py),
  [P05 materialization](../src/kden_v375/prefit/p05_materialization.py),
  [P06 acceptance](../src/kden_v375/prefit/p06_acceptance.py).
- Checks: [materialization tests](../tests/unit/test_prefit_p05_materialization.py),
  [acceptance tests](../tests/unit/test_prefit_p06_acceptance.py).
- Saved acceptance: [P06 PASS](../state/PREFIT_P06_PASS.json),
  [universal issue-state PASS](../state/KDEN_V375_UNIVERSAL_ISSUE_STATE_PASS.json).

**Supported conclusion.** The saved release describes 2,080 target days,
118,536 issue states, 433 features, and 8,919,598 trajectory references. Feature
columns and repeated issue rows are not independent samples. Freezing provides
reproducibility, not a guarantee that every feature improves prediction.

## D07 Fit and compare chronologically, grouping all issues from a day

**Decision and reasoning.** Treat a day as the grouping unit, fit preprocessing
only on training data, compare identical supported forecasts, and keep selection
separate from assessment. Earlier audited truth is subject to the declared
reporting lag, not merely an earlier calendar date.

- Design: [comparison plan](../universal_issue_state/R14_MODEL_COMPARISON_PLAN_V1.md),
  [S3 feature/fit amendment](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s3_v1/DECISIONS.md).
- Implementation: [development loader](../universal_issue_state/experiments/r14_first_model_comparison_v1/src/r14_s1/data.py),
  [baseline workflow](../universal_issue_state/experiments/r14_first_model_comparison_v1/src/r14_s2/workflow.py),
  [comparison engine](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s4_v1/engine.py).
- Checks: [loader tests](../universal_issue_state/experiments/r14_first_model_comparison_v1/tests/test_s1_loader.py),
  [comparison tests](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s4_v1/tests/test_s4.py).
- Qualification: [S5 timing disclosure](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md).

**Supported conclusion.** Chronological model comparisons were executed, but
this is not a blanket claim of a flawless leakage-free implementation: S5 found
a selection-label boundary violation. Previously inspected periods remain
historical development evidence even when predictions were chronologically fit.

## D08 Evaluate full probability forecasts, not only point error

**Decision and reasoning.** Compare hourly/subhourly residual baselines with
AnEn and location–scale GAMs; use registered diagnostics and a bounded boosted
challenger. Distinguish the predictive median, mean, and modal integer, as well
as integer hits, interval coverage, and band probabilities.

- Design: [comparison plan](../universal_issue_state/R14_MODEL_COMPARISON_PLAN_V1.md).
- Implementation: [AnEn](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s3_v1/r14_s3/anen.py),
  [GAM](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s3_v1/r14_s3/gam.py),
  [probability/scoring utilities](../universal_issue_state/experiments/r14_first_model_comparison_v1/src/r14_s1/probability.py),
  [boosted models](../universal_issue_state/experiments/r14_boosted_comparison_v1/models.py).
- Checks: [model tests](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s3_v1/tests/test_s3.py),
  [boosted-model tests](../universal_issue_state/experiments/r14_boosted_comparison_v1/tests/test_models.py).
- Results: [S5 interpretation](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md),
  [boosted report](../universal_issue_state/experiments/r14_boosted_comparison_v1/runs/r14-boost-20260927T093806Z/REPORT.md).

**Supported conclusion.** These reports compare 980 target days and 55,848
issue checkpoints per model over 2023–2025-09-06. The Q baseline has median MAE
2.037°F and modal hit rate 17.41%; AnEn has 1.948°F and 18.14%; the normal
location–scale GAM has 1.959°F and 18.68%. Results are day-weighted historical
estimates, not commercial promotion. The S5 protocol's finite-support/floored
log-scoring convention differs from the later tabular experiment's full-law,
unfloored scoring. They must not be ranked together without reconciliation.

## D09 Check whether confidence transfers at meaningful coverage

**Decision and reasoning.** A high hit rate on selected cases is insufficient
if selection mainly finds easier weather, admits few forecasts, or fails in a
later period. Compare a baseline on the same admitted cases and report expected
versus realized hit probability, checkpoint coverage, and contributing days.

- Design/result: [S5 interpretation](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md).
- Implementation: [S5 scoring core](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s5_v1/core.py),
  [figure generation](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s5_v1/plots.py).
- Checks: [S5 tests](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s5_v1/tests/test_s5.py).
- Follow-up design: [S6 registration](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s6_v1/README.md).

**Supported conclusion.** Pooled improvements and selected hit rates concealed
important period-specific confidence failures. This motivates a reliability
experiment; it does not validate a deployable confidence gate. Exploratory
regime/effect plots support hypotheses, not causal claims or discovered
trading opportunities.

## D10 Disclose a timing defect and test its effect without rewriting history

**Decision and reasoning.** December 31 tuning outcomes were used for a
January 1 selection despite a two-day lag. Preserve the original record, test
the excluded-date sensitivity, and integrate a corrected boundary into a
successor rather than quietly overwriting accepted forecasts.

- Disclosure and sensitivity: [S5](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md).
- Successor primitive: [S6 boundary rules](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s6_v1/boundaries.py).
- Checks: [S6 boundary tests](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s6_v1/tests/test_boundaries.py).
- Follow-up evidence: [CR1 lineage and results](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/cr1_v1/INTERPRETATION.md),
  [CR1 data/lineage implementation](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/cr1_v1/data.py).

**Supported conclusion.** The reported sensitivity retained all 18 settings;
outer fitting respected the lag. That limits the apparent effect but does not
retroactively make the original selection procedure compliant. The portfolio
should demonstrate the correction and qualification, not claim that tests
prevented every defect.

## D11 Evaluate post-processing as a separate falsifiable experiment

**Decision and reasoning.** Compare native hit confidence with confidence-only,
calendar-enhanced, and weather-enhanced logistic reliability models, using
separate chronological fit/threshold/assessment blocks and explicit stopping
criteria. Do not substitute hit-event probabilities for a coherent Tmax PMF.

- Registration: [S6](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s6_v1/README.md).
- Implementation: [CR1 model](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/cr1_v1/model.py),
  [workflow](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/cr1_v1/runner.py).
- Checks: [CR1 model tests](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/cr1_v1/tests/test_model.py),
  [workflow tests](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/cr1_v1/tests/test_workflow.py).
- Result: [CR1 interpretation](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/cr1_v1/INTERPRETATION.md).

**Supported conclusion.** On 615 target days and 35,047 checkpoints, the learned
reliability designs did not meet the registered requirements. All three learned
versions had worse pooled Brier than native confidence for each base model.
The prospective reservation in the S6 document was inactive, not evidence of
live collection, operational readiness, or a completed future test.

## D12 Preserve the distinction between tabular implementation and final skill

**Decision and reasoning.** Use fixed pretrained TabICL/TabDPT weights with
earlier-date contexts and declared emitted-error corrections. Commit forecasts
before scoring and keep per-unit recovery evidence. Evaluate compute cost and
warm-up support as well as accuracy.

- Design: [tabular plan](../universal_issue_state/experiments/r14_tabular_pretrained_v1/README.md),
  [owner-confirmed scoring window](../universal_issue_state/experiments/r14_tabular_pretrained_v1/config/scoring_t04.json).
- Implementation: [native runtime](../universal_issue_state/experiments/r14_tabular_pretrained_v1/src/kden_r14_tabular/t02_runtime.py),
  [T04 workflow](../universal_issue_state/experiments/r14_tabular_pretrained_v1/src/kden_r14_tabular/t04_workflow.py).
- Checks: [T04 tests](../universal_issue_state/experiments/r14_tabular_pretrained_v1/tests/test_t04.py),
  [serialization-repair tests](../universal_issue_state/experiments/r14_tabular_pretrained_v1/tests/test_t04_serialization_repair.py).
- Snapshot: [paused state](../universal_issue_state/experiments/r14_tabular_pretrained_v1/runs/kdenv375-t04-owner-full-development-v1/state.json).

**Supported conclusion.** The saved state is paused after 212 scored days, not
a final T04 PASS. The mature T3/D2 recipes cannot be advertised as evaluated
flagships on the strength of earlier fallback/basic-correction scores. The
later boolean-serialization repair is an engineering fix, not an accuracy
improvement. A decision not to spend more compute is not evidence that all
tabular foundation models, HRRR, or Denver forecasts are intrinsically inadequate.

## Figure and public-claim checklist

| Candidate figure | Evidence decision | What it must retain |
|---|---|---|
| Issue-time and cycle diagram | D01 | UTC/local distinction, hourly initialization, 105-minute emulator, independent H/Q products. |
| R14 mechanism and scope diagram | D02, D04 | Accepted list, source-versus-derived-feature distinction, sacrificed information; no lossless-pruning claim. |
| Data and truth architecture | D03, D05, D06 | Separate labels, unresolved status, freeze boundary, references rather than duplicate data. |
| Baseline and model scorecard | D07, D08 | Same dates/support, point decision, issue window, uncertainty, timing qualification. |
| Reliability and selective coverage | D09, D11 | Same-case baseline, admitted coverage/days, period differences, failed readiness requirements. |
| Defect and successor boundary test | D10 | Original violation, unchanged-settings sensitivity, preserved original artifacts. |

Use existing completed reports for initial result figures; this task does not
require new training. A plot of later issue times is not a model-learning curve.
Results from sunny-day studies, observation-floor baselines, S5, CR1, boosted
models, and the partial tabular run have different populations and purposes.
Do not combine their numbers merely to suggest improvement across versions.

## Review boundary and next packaging step

This mapping checks source paths, records source-file fingerprints, and reads
selected specifications, code/tests, saved status records, and interpretation
reports. It does not independently re-audit all raw truth, hash the full weather
archive, rerun the cited tests, reproduce the scorecards, or resume any process.
No held-out raw outcome file is needed to construct it.

Before public release, copy only reviewed sources into a standalone repository,
resolve their internal links, include a small synthetic/development-only demo,
and reproduce the selected figures from compact exported evidence with the
same definitions and qualifications. Preserve originals; clearly mark public
editorial copies. Inspect metadata, personal paths, reserved outcomes,
third-party citations and licenses before redistributing the research documents.
The [source inventory](SOURCE_INVENTORY.json) supports this next step; it is not
a new scientific acceptance record or a claim that the public package exists.
