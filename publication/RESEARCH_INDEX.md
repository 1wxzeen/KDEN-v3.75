# KDEN research index

Prepared October 23, 2026. This guide connects research decisions to the data,
software, and results in KDEN v3.75. It is new navigational documentation, not a
replacement for any frozen specification or permission to execute its steps.

The project asks whether meteorologically informed post-processing can improve
HRRR daily maximum-temperature forecasts for Denver, and whether the resulting
probabilities are reliable enough for useful decisions. The work includes the
less visible prerequisites to modeling: source selection, historical timing,
spatial extraction, label auditing, restartable acquisition, and a reusable
feature release. Its completed comparisons show modest average improvements
and important confidence failures, not a demonstrated trading strategy.

## A short reading route

1. Read the [substrate guide](../universal_issue_state/README.md) for the data
   objects and distinctions between issue time, cycle time, and physical time.
2. Read the [approved R14 selection](../reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md)
   for the final source universe and its scientific tradeoffs.
3. Read the [comparison plan](../universal_issue_state/R14_MODEL_COMPARISON_PLAN_V1.md)
   for the baseline, analog-ensemble, and distributional-GAM experiment.
4. Read the [completed comparison interpretation](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md)
   and [conditional-reliability findings](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/cr1_v1/INTERPRETATION.md).
5. Use the [decision-to-evidence map](DECISION_EVIDENCE_MAP.md) to follow a
   particular design choice into its implementation, tests, and reported result.

The original research documents below supply the longer reasoning behind this
route. They are central evidence, but their proposals and historical results
must not be mistaken for the final v3.75 implementation.

## Evidence status

| Label | Meaning |
|---|---|
| Historical rationale | An earlier design or experiment that informed later choices; not the current execution contract. |
| Adopted design | An accepted scientific or engineering choice; predictive benefit is not established merely by adopting it. |
| Implemented and accepted | Code and a saved acceptance record exist. This guide has not rerun the acceptance process. |
| Completed historical analysis | A saved report describes an executed evaluation; its population and qualifications remain attached. |
| Implemented, partially evaluated | Software and partial outputs exist, but the planned evaluation is unfinished. |
| Proposed or registered | A specification exists; it does not establish fitting, activation, or performance. |

An implementation manual is not proof that every step was completed. A PASS
record is not a model-skill result. A chronological assessment is not necessarily
a never-inspected blind test. The companion map keeps these distinctions explicit.

## Research documents and the questions they address

### 1. From a narrow thermal study to an issue-time forecasting problem

**R01 — [Product-direction white paper v2.0](../docs/research/product_direction_v2.md).**
Historical rationale. Explains the move from a narrow sunny-day regression study
toward probabilistic model-output statistics and intraday adaptation. Its
observation-augmented and state-space proposals are not evidence that those
systems were deployed in v3.75. Earlier D1 findings referenced by this document
belong to their own study, not to the R14 model comparison.

**R02 — [Layer 1 baseline specification v3.0](../docs/research/layer1_baseline_specification_v3.md).**
Historical rationale and algorithm specification. Defines coherent trajectories,
cycle availability, spatial extraction, and explicit forecast clocks for the
earlier six-checkpoint baseline. It helps explain why a historical forecast must
be reconstructed from the information available at issuance. Its checkpoint
grid and observation-floor comparators are not the v3.75 source contract.

**R03 — [Layer 1 scientific record v1.0](../docs/research/layer1_scientific_record_v1.md).**
Historical completed-analysis record. Documents the older baseline program,
including hourly/subhourly extraction and MADIS observed-floor variants. Use it
to understand what the earlier experiment established and why its results
cannot simply be relabeled as R14 results. It describes 2,042 days and six
checkpoints, not the later 2,080-day universal issue grid.

### 2. Establishing a defensible outcome rather than trusting one parsed row

**R04 — [Public truth-audit guide](../docs/TRUTH_AUDIT.md).**
Explains why a parsed IEM candidate and the underlying CLI/CF6 chronology can
disagree, and summarizes the adopted Stage 5R.1 protocol. This is a new public
guide, not a copy of the historical truth-layer PDF. That PDF is not bundled
because it contains individual reserved-period outcomes and superseded
repair/fallback and market-source discussions. Its later-date values are not
repeated here, and its market discussion is not presented as current advice.

The implemented v3.75 authority is the self-contained, byte-preserved adoption
of the Stage 5R.1 package plus the separately acquired five-day extension.
Start with the [P02 coverage report](../truth/kden_tmax/v1/reports/P02_TRUTH_COVERAGE_QC.md),
[audit-rule implementation](../src/kden_v375/prefit/p02_rules.py), and
[rule tests](../tests/unit/test_prefit_p02_truth.py). This is reuse and extension
of prior audited work, not a claim that v3.75 rebuilt the entire historical
audit from nothing. Raw candidates, accepted labels, and unresolved dates have
different roles; metadata and truth status are never weather predictors.

### 3. Turning meteorological mechanisms into an acquisition design

**R05 — [Universal feature-panel scientific specification v2.2](../docs/research/universal_feature_specification_v2_2.md).**
Historical scientific specification. Connects physical pathways to source
identities, temporal/spatial operators, feature admission, and causal lineage.
It describes the broader 44-hourly/14-subhourly universe and the earlier
six-checkpoint design, including observation-augmented views. Those are design
ancestry, not the field list acquired for R14.

**R06 — [Feature-panel implementation manual v1.5](../docs/research/implementation_manual_v1_5.md).**
Historical engineering specification. Translates scientific requirements into
serial work units, artifact contracts, acceptance checks, restart behavior,
and owner-controlled long runs. Its references to coding agents describe the
development workflow; they do not authorize present execution. The manual
names an earlier companion scientific version, so it should not be presented
as a perfectly synchronized manual for every later specification.

**R07 — [HRRRv4 local-archive acquisition memo](../KDEN_HRRRv4_Local_Archive_Acquisition_Memo_v1.0.md).**
Supporting acquisition-design record. Read alongside the implemented
[project specification](../PROJECT.md), not as an independent description of
the current run state. Byte ranges, source identities, units, and interval
semantics matter as much as the names of weather variables.

### 4. Choosing R14 under a real acquisition constraint

**R08 — [Step 04.5 feature-universe study brief](../STEP_04_5_FEATURE_UNIVERSE_STUDY.md).**
Research brief. Poses the scientific question behind reducing a costly broad
universe without discarding dense cycles or native temperature trajectories.
The approximately 41.5-day runtime in this brief is a historical pilot
extrapolation, not a measured duration for the final R14 acquisition.

**R09 — [Initial recommendation and budget reconsideration](../reports/step_04_5_feature_universe_scientific_recommendation.md)**
and **R10 — [meteorological reduction study](../reports/step_04_5_c32_reduction_meteorological_study.md).**
Intermediate research recommendations. They explain candidate reductions,
regional mechanisms, cadence, and deliberate information sacrifices. Their
C32/R13/R14-P field lists are superseded. Their hypotheses are not an empirical
proof that omitted fields add no predictive information.

**R11 — [Approved R14 acquisition handoff](../reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md).**
Adopted source-selection record. This is the correct starting point for the
final field choice: 12 dynamic hourly identities, static terrain H14, and
subhourly temperature Q05. R14 means 14 source identities, not 14 model columns.
The handoff explicitly preserves native trajectories and records the later
right-open endpoint correction. Earlier request counts and throughput
projections should not be presented as final measurements.

### 5. Building the model-neutral substrate before fitting

**R12 — [PROJECT.md](../PROJECT.md).**
Implemented acquisition and reader design. Relate its steps to the saved
[acquisition acceptance record](../state/KDEN_V375_ACQUISITION_PASS.json).
Its roadmap is not a live status dashboard for every later experiment.

**R13 — [Universal modeling prefit plan](../RAFM_V375_UNIVERSAL_MODELING_PREFIT_PLAN.md).**
P01–P07 design. Covers the truth package, issue spine, deterministic features,
materialization, acceptance/freeze, and experiment boundary. The accepted
[P06](../state/PREFIT_P06_PASS.json) and [P07](../state/PREFIT_P07_PASS.json)
records distinguish the completed data work from planned model fitting.
P07's frozen RAFM specification is not evidence of an executed adaptive mixture.

**R14 — [Universal substrate guide](../universal_issue_state/README.md).**
Reader-facing explanation of the accepted data objects. Weather coverage is
2021-01-01–2026-09-11: 2,080 target days, 118,536 issue states, 433 deterministic
features, and 8,919,598 trajectory references. These references are not that many
independent days, downloaded files, or necessarily separate HTTP requests.
There are 1,707 usable development labels, three unresolved development dates,
a 365-day reserved interval, and five additional accepted truth dates. Full
weather coverage does not imply usable labels or model support on every row.

### 6. Designing and interpreting the completed comparisons

**R15 — [R14 model-comparison plan v1](../universal_issue_state/R14_MODEL_COMPARISON_PLAN_V1.md).**
Experiment design built on the already-frozen substrate. It is the bridge from
data engineering to the first baseline/AnEn/GAM comparison, not the plan that
originally created the substrate. It defines common support, chronological
assessment, target-day grouping, probability semantics, and the distinction
between a forecast improvement and trading value. Later
[S3 decisions](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s3_v1/DECISIONS.md)
record changes to the fitted feature set; the initial proposal alone does not
identify every final model input.

**R16 — [S5 completed comparison interpretation](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/s5_v1/INTERPRETATION.md).**
Completed historical analysis. Modest average improvements coexist with
confidence failures across periods. The report discloses a selection-label
timing violation and a sensitivity retaining all 18 configurations. That
sensitivity does not erase the violation. These results are inspected
historical development evidence, not a new blind test or a profit backtest.

**R17 — [CR1 conditional-reliability interpretation](../universal_issue_state/experiments/r14_first_model_comparison_v1/reports/cr1_v1/INTERPRETATION.md).**
Completed follow-up to the [S6 registration](../universal_issue_state/experiments/r14_first_model_comparison_v1/implementations/s6_v1/README.md).
Tests whether confidence, calendar, and weather improve the probability of a
fixed modal-integer hit. The registered readiness requirements were not met.
This is not a recalibrated full Tmax distribution and not a successful trade gate.

**R18 — [Boosted-model comparison report](../universal_issue_state/experiments/r14_boosted_comparison_v1/runs/r14-boost-20260927T093806Z/REPORT.md).**
Completed historical analysis of XGBoost quantile and NGBoost normal forecasts.
Both are compared with the baselines on identical support; the disclosed
baseline timing qualification remains attached. Neither is declared a
commercially ready winner.

### 7. Pretrained tabular models and the limit of completed evidence

**R19 — [Pretrained-tabular experiment plan](../universal_issue_state/experiments/r14_tabular_pretrained_v1/README.md).**
Implemented, partially evaluated. TabICL/TabDPT neural weights remain fixed;
historical contexts and emitted-error corrections change on declared schedules.
The original proposed 02:00–08:00 primary window was superseded by the
owner-confirmed 02:00–14:00 window in the
[T04 scoring contract](../universal_issue_state/experiments/r14_tabular_pretrained_v1/config/scoring_t04.json).

The [saved T04 state](../universal_issue_state/experiments/r14_tabular_pretrained_v1/runs/kdenv375-t04-owner-full-development-v1/state.json)
is PAUSED, last updated October 11, 2026: 874 native contexts, 12,080 emitted
issue states, and 212 scored days. No final T04 development PASS or recipe lock
was found in the checked locations. This paused run does not establish a final
holdout result. Do not advertise T3/D2 performance as a completed comparison.
This is a snapshot, not a monitor.

## What the public evidence can support

The strongest supported account is an end-to-end research workflow: formulate
an issue-time problem, choose inputs with explicit scientific tradeoffs, build
and accept a reusable dataset, compare forecasts chronologically, and examine
where uncertainty estimates fail. Its negative and qualified findings are part
of that account, not material to remove for a cleaner success story.

Keep the following limits attached:

- R14 pruning was an accepted meteorological/cost judgment, not a completed
  all-field ablation proving lossless compression.
- The 118,536 issue rows are repeated forecasts for 2,080 weather days, not
  independent weather events. Later-model features are explicit subsets of the
  433-column universe, not automatic use of every column.
- S5/boosted results and the tabular preview differ in periods, issue windows,
  point decisions, and probability conventions. Do not merge them into one
  leaderboard or an implied learning curve.
- Local reserved-label access rules do not restore global blindness after
  related studies have inspected overlapping outcomes.
- No reported result establishes profitable trading, causal meteorological
  effects, or that KDEN/HRRR is intrinsically unforecastable.

## Publication handling and attribution

This public snapshot supplies five GitHub-readable editions of the research
Word documents, with source filenames and hashes. Word binaries and their
personal metadata are not distributed. One individual reserved-period
correction-example row was withheld from the older scientific record; the
original working document was not changed. The public truth guide replaces a
link to an unbundled historical PDF, rather than pretending that PDF is present.

Preserve originals and their versions. Public editorial editions must identify
their source and changes; do not silently revise historical claims or erase
agent-directed wording to imply sole manual authorship. AI assistance in
research drafting or implementation should be described accurately. The
owner-directed questions, reviewed choices, acceptance decisions, and ability
to explain the implementation are the substance to demonstrate; document
complexity alone does not establish authorship or correctness.

Personal paths were made portable in public documentation, and unavailable
artifact links point to explicit data-availability notices. Research proposals
and agent-directed wording remain visible as historical records. Third-party
literature is referenced rather than copied as a collection of papers.
Large archives, environments, weights, unrestricted run dumps, and individual
truth packages are excluded. See the [publication audit](PUBLICATION_AUDIT.md)
and [manifest](PUBLIC_MANIFEST.json) for the delivered scope.

[SOURCE_INVENTORY.json](SOURCE_INVENTORY.json) is the earlier navigation-review
inventory, not an exhaustive list of public files. The public manifest records
the shipped files and public edits separately. Neither is a new acquisition,
truth, model, or freeze authority. No training, acquisition, full validation,
or reserved-outcome access is needed to read this guide.
