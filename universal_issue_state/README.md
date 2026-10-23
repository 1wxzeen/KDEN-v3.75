# KDEN v3.75 Universal Modeling Substrate

## Start here

This directory contains the frozen, model-neutral weather-state substrate built
for KDEN v3.75. It is the main weather-data input for future model fitting,
including the first frozen RAFM/analog-ensemble experiment.

The short version is:

1. `universal_issue_state/v1/` describes what was knowable at each historical
   forecast issue time.
2. `truth/kden_tmax/v1/` contains the physically separate KDEN daily Tmax
   targets.
3. `folds/kden_v375/v1/` says which target dates may be used for training,
   assessment, or final evaluation.
4. `modeling/experiments/rafm_v1/` freezes the first experiment's feature
   subsets, analog rules, baselines, mixtures, metrics, and holdout policy.

Do not edit any of those versioned directories. They are accepted releases,
not working directories. New models should read them and write their own
outputs elsewhere.

This README is navigational documentation beside the frozen release. It is not
itself part of the P06 or P07 release authority. If this explanation ever
conflicts with a machine-readable contract, manifest, or PASS record, the
machine-readable artifact wins.

## What was built

KDEN v3.75 began with a large HRRR acquisition problem. The project acquired
the scientifically selected R14 weather universe for every target day from
2021-01-01 through 2026-09-11, then converted that archive into a universal
issue-time representation suitable for many different model families.

The central modeling object is not one enormous flat table. It is a small set
of linked, immutable Parquet and JSON artifacts:

```text
target day + issue time
          |
          v
issue spine ---------> independently selected hourly/subhourly cycles
          |                              |
          v                              v
deterministic feature row          trajectory references
          |
          +------ join folds by target_date
          |
          +------ join truth by target_date only when authorized
```

This design preserves several distinctions that matter scientifically:

- the time a forecast is issued;
- the HRRR cycle initialization time;
- the physical valid time being forecast;
- forecast lead time;
- the target KDEN climate day;
- the hourly (`wrfsfcf`) and subhourly (`wrfsubhf`) product histories; and
- what information would actually have been available at the simulated issue
  time.

The result is a reusable substrate rather than a table tailored to one model.
An analog ensemble, GAM/GAMM, boosting model, neural model, or another future
method can all start from the same frozen issue states, features, trajectories,
truth, and date-grouped evaluation structure.

## The release in numbers

| Item | Accepted value |
|---|---:|
| Target days | 2,080 |
| Issue states | 118,536 |
| Deterministic features per issue state | 433 |
| Hourly and subhourly trajectory references | 8,919,598 |
| Development target days | 1,710 |
| Supervised development target days | 1,707 |
| Unresolved development target days | 3 |
| Sealed final-holdout target days | 365 |
| Accepted post-holdout tail days | 5 |
| Outer rolling-origin folds | 3 |
| Nested inner-fold instances | 15 |

Ordinary target days contain 57 issue states on the 15-minute local issue grid
from 02:00 through 16:00 America/Denver. A spring-forward day contains 53
because the nonexistent local times are not fabricated. The independent
statistical unit is always the target day, not each issue row.

## What the folders contain

### 1. Frozen weather substrate

Root: `universal_issue_state/v1/`

#### Issue spine

`issue_spine/issue_spine.parquet`

One row represents one historical `(target_date, issue_time)` state. Its stable
key is `issue_state_id`. It contains the local and UTC clocks, target-day
window, issue ordinal, and calendar fields, but no outcome.

The KDEN target window is the fixed right-open climate day
`[07Z on target_date, 07Z on target_date + 1 day)`. The local issue grid is
DST-safe.

#### Selected cycles

`selected_cycles/selected_cycles.parquet`

There are two rows per issue state: one for `wrfsfcf` and one for `wrfsubhf`.
The products are selected independently because they are separate HRRR source
products. The table records the selected and previous cycles, their emulated
completion times, retained valid-time support, and trajectory-bundle pointers.

The historical availability emulator uses the frozen 105-minute publication
lag. A model must not replace these selections with a cycle that was not yet
available at the historical issue time.

#### Deterministic features

`deterministic_features/target_year=YYYY/part-YYYY.parquet`

These six year partitions contain the 433 target-free features for each issue
state. They include:

- clocks and cycle-age/support metadata;
- local retained and remaining-trajectory summaries;
- regional and tile summaries;
- static terrain summaries;
- physical derived features such as lapse/stability, moisture deficit, wind,
  solar integration, reflectivity occurrence, and snow support; and
- current-versus-previous-cycle revision features.

The first columns identify the row. The feature definitions, units, bounds,
and missingness contracts live in
`registries/universal_feature_registry_v1.json`. Use that registry; do not
infer units from column names alone.

#### Trajectory catalog

`trajectory_catalog/target_year=YYYY/part-YYYY.parquet`

This is a reference catalog, not a second copy of all weather values. Each row
identifies an R14 field/cycle/valid-time state and points to the canonical
archive path and row ordinal. It preserves the full temporal trajectories for
models that need more than the 433 deterministic summaries.

`trajectory_catalog/static/h14.parquet` contains the static H14 terrain
reference.

Use the deterministic feature partitions for the first fitting workflow. Use
the trajectory catalog only when a model genuinely needs the retained native
trajectory. Resolve its canonical archive pointer and verify the recorded
archive SHA before reading the referenced row. Do not rewrite or expand the
catalog inside the frozen release.

#### Release authority

- `release_index.json`
- `manifests/p05_release_manifest.json`
- `manifests/p06_substrate_freeze_manifest.json`
- `registries/universal_feature_registry_v1.json`

P06 accepted this release as `KDEN_V375_UNIVERSAL_ISSUE_STATE_V1`.

### 2. KDEN Tmax truth sidecar

Root: `truth/kden_tmax/v1/`

The canonical table for joining outcomes is:

`catalog/kden_truth_catalog.parquet`

Join it to issue states by `target_date`. The authoritative outcome field is
`y_audited_f`, but only when the row's role and availability fields authorize
its use. For development fitting or assessment, require all of the following:

- `truth_group == "development"`;
- `label_available_for_supervised_use == true`; and
- `y_audited_f` is not null.

The package is based on the independently audited KDEN CLI/CF6 truth process,
including the two guarded historical corrections. The original atomic IEM
candidate is provenance, not authoritative truth. Do not substitute old
`selected_tmax_f`, `label_selected_tmax_f`, mechanical-candidate, MADIS daily
maximum, or reconstructed market-settlement values for `y_audited_f`.

Truth is deliberately physically separate from weather predictors. That
separation reduces accidental target leakage and allows the weather substrate
to be used for unsupervised work without reading labels.

### 3. Frozen date roles and folds

Root: `folds/kden_v375/v1/`

- `date_roles.parquet` assigns every target day its evidence role.
- `outer_folds.parquet` contains the three rolling-origin train/assessment
  splits.
- `inner_folds.parquet` contains the nested tuning splits.
- `fold_manifest.json` records counts, dates, seasons, and integrity evidence.

Join folds by `target_date` and `statistical_group_id`. Every issue state from
one target day has the same `statistical_group_id` and must remain in the same
fold.

The outer folds are:

| Fold | Training dates | Assessment dates |
|---|---|---|
| `OUTER_01` | 2021-01-01–2022-12-31 | 2023-01-01–2023-12-31 |
| `OUTER_02` | 2021-01-01–2023-12-31 | 2024-01-01–2024-12-31 |
| `OUTER_03` | 2021-01-01–2024-12-31 | 2025-01-01–2025-09-06 |

The final OUTER_03 assessment is a realistic partial-year assessment, not a
complete annual test.

### 4. RAFM V1 experiment adapters

Root: `modeling/experiments/rafm_v1/`

`adapters/issue_model_index.parquet` is the recommended entry point for the
first RAFM implementation. It maps every issue state to its year-partitioned
feature file using:

- `issue_state_id`;
- `target_date` and `statistical_group_id`;
- local issue-time fields and `exact_time_key`;
- `feature_partition_path`; and
- `feature_row_ordinal`.

`adapters/adapter_registry.json` freezes the H-BI and Q15-BI baselines, the
general thermal expert, five specialist feature sets, and the named neighboring
time challenger. The adapter contains no truth, fold, or market columns.

The binding scientific and evaluation contract is:

`config/prefit/p07_rafm_experiment_v375.json`

Read this alongside:

- `reports/prefit/P07_SCIENTIFIC_DECISIONS.md`;
- `reports/prefit/P07_CONTAMINATION_HOLDOUT_REPORT.md`; and
- `modeling/experiments/rafm_v1/manifests/p07_experiment_freeze.json`.

## Evidence boundaries: what may be used when

### Development

Dates 2021-01-01 through 2025-09-06 form the development era. Of 1,710 target
days, 1,707 have supervised labels. The three unresolved dates may be retained
for target-free diagnostics but must not contribute to loss, tuning,
calibration, residual estimation, or scoring.

### Sealed final holdout

Dates 2025-09-07 through 2026-09-06 are the 365-day final holdout. Their
outcomes remained unopened through P07. Do not use these rows for fitting,
feature selection, QC-policy selection, hyperparameter tuning, calibration,
residual kernels, regime definitions, exploratory outcome analysis, or model
comparison.

The holdout may be opened only after model code, evaluation code,
hyperparameters, and predictions have been frozen under the P07 contract. No
model change is allowed after opening.

### Five-day post-holdout tail

Dates 2026-09-07 through 2026-09-11 are accepted truth evidence, but are final
evaluation evidence only. They are never development evidence. The truth
catalog preserves whether a source follow-up window was still open at freeze,
so final reporting can include the predeclared sensitivity that excludes such
tail rows. This flag does not authorize their use in fitting.

## Safe data-loading pattern

The following example uses PyArrow, which is already part of the project
environment. It loads one year of target-free issue states, verifies their
identity against the P07 adapter, and separately selects authorized development
labels. It intentionally does not open holdout labels.

```python
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(".")

year = 2023
feature_path = ROOT / (
    f"universal_issue_state/v1/deterministic_features/"
    f"target_year={year}/part-{year}.parquet"
)
index_path = ROOT / "modeling/experiments/rafm_v1/adapters/issue_model_index.parquet"

# Choose only the columns required by the model being fit.
feature_columns = [
    "issue_state_id",
    "h16_local_asof_value",
    "h16_local_remaining_max",
    "q05_local_asof_value",
    "q05_local_remaining_max",
    "derived_q05_minus_h16_common_remaining_mean_k",
    "derived_t850_minus_t2m_future_first_k",
    "derived_t700_minus_t850_future_first_k",
    "revision_h16_remaining_max_abs",
]

features = pq.read_table(feature_path, columns=feature_columns)
index = pq.read_table(
    index_path,
    filters=[("target_year", "=", year)],
)

# P07 freezes the same row identity/order. Verify instead of assuming it.
assert features.num_rows == index.num_rows
assert features["issue_state_id"].equals(index["issue_state_id"])

issue_states = pa.table({
    **{name: index[name] for name in index.column_names},
    **{name: features[name] for name in feature_columns if name != "issue_state_id"},
})

# Read role metadata before touching any outcome value.
roles = pq.read_table(ROOT / "folds/kden_v375/v1/date_roles.parquet")
development_dates = roles.filter(
    pc.and_(
        pc.equal(roles["evidence_role"], "DEVELOPMENT_SUPERVISED"),
        roles["supervised_eligible"],
    )
)["target_date"]

assert len(development_dates) == 1707

# Read outcome values only for the pre-authorized development group.
truth = pq.read_table(
    ROOT / "truth/kden_tmax/v1/catalog/kden_truth_catalog.parquet",
    columns=[
        "target_date",
        "truth_group",
        "label_available_for_supervised_use",
        "y_audited_f",
    ],
    filters=[
        ("truth_group", "=", "development"),
        ("label_available_for_supervised_use", "=", True),
    ],
)

assert truth.num_rows == 1707
assert truth["target_date"].null_count == 0
assert truth["y_audited_f"].null_count == 0
```

For actual fitting, select dates from the frozen inner or outer fold table,
then join the selected date rows to issue states and to `truth` by
`target_date`. Do not invent a new random row split.

The adapter's `feature_row_ordinal` is a locator and integrity aid. Batch reads
should normally read the required year partition once, verify
`issue_state_id`, and select the necessary feature columns. Avoid repeatedly
reading one row at a time.

## First authorized fitting workflow

P07 ended at the boundary immediately before model fitting. The first allowed
fitting operation is the generation of nested inner-fold out-of-fold PMFs and
support diagnostics for the general thermal analog ensemble, using development
dates only.

A correct implementation should proceed in this order:

1. Validate the frozen boundary before reading model data.
2. Load the P07 adapter registry and the exact experiment contract.
3. Select one inner-fold instance.
4. Load only its `TRAIN` and `ASSESS` target dates.
5. Join the required deterministic feature columns by `issue_state_id`.
6. Join authorized development truth by `target_date`.
7. Fit every scaler, percentile threshold, analog choice, residual distribution,
   and other learned quantity on the inner training dates only.
8. Produce forecasts for the inner assessment dates without refitting on them.
9. Save one out-of-fold PMF and support record per eligible issue state.
10. Repeat for every frozen inner-fold instance before training any adaptive
    mixture gate.

For the default analog experiment:

- match the exact local issue-grid minute;
- allow at most one state from any historical target day into a query's analog
  pool;
- require the candidate target date to be strictly earlier than the query
  target date;
- use fold-local robust scaling;
- use only complete required feature vectors;
- require the frozen minimum eligible analog counts; and
- apply the deterministic tie-break order in the P07 contract.

The separate +/-15-minute analog challenger is an ablation. It may not silently
replace the exact-time default.

## Statistical rules that must not be lost

### A target day is the independent unit

The 118,536 issue rows are repeated forecast states for 2,080 weather events;
they are not 118,536 independent days. All issue states for one target day
must stay together in one fold.

Metrics and losses must first be averaged within target day and then across
target days, or use an exactly equivalent `1 / issue_count_for_target_day`
weighting. Otherwise an ordinary day receives roughly 57 times the influence
of one weather event.

### Learning is fold-local

Feature scaling, missingness policy choices, analog hyperparameters, residual
kernels, specialist eligibility percentiles, mixture weights, and gate
standardization must be learned using only the applicable training fold.

### Missingness is information

Nulls and the coverage/missing-count columns are explicit archive or support
facts. Do not replace all nulls with zero. The P07 RAFM experts abstain when a
required feature is missing, and mixtures renormalize over available experts.

### Units are contractual

Consult `universal_feature_registry_v1.json`. Temperature-centered baseline
features are stored in their canonical weather units and the P07 baseline
contract explicitly converts Kelvin to Fahrenheit. Do not apply a second
conversion. Analog distance features should be scaled inside the training
fold before Euclidean distance is computed.

### Forecast time is not observation time

Never use weather values, cycles, revisions, or truth that would not have been
available at the simulated issue time. The frozen cycle selections and
retained windows encode this rule.

## RAFM V1 starting ladder

The frozen experiment compares increasing levels of complexity:

1. H-BI raw hourly baseline;
2. Q15-BI raw subhourly baseline;
3. general thermal analog ensemble;
4. physical specialist analog ensembles;
5. constant-weight specialist mixture; and
6. adaptive RAFM mixture.

The adapter registry defines one generalist plus dry-heating, cloud/solar,
convection/precipitation, snow/surface, and mixing/downslope specialists. The
adaptive gate is a small masked multinomial logistic softmax trained only from
nested out-of-fold expert PMFs. In-sample expert predictions may not train the
gate.

The forecast PMF support is every whole degree Fahrenheit from -40 through
120. The primary metric is target-day mean log score. The contract also
requires RPS/discrete CRPS, Brier scores, calibration, coverage, sharpness,
deterministic errors, issue-time slices, seasons, regimes, support strata, and
worst-fold stability. Promotion thresholds and the bootstrap procedure are
predeclared in the P07 contract and must not be adjusted after seeing results.

## Using the substrate for a different model

The universal substrate is not limited to RAFM. A different model may use the
same issue spine, features or trajectories, truth catalog, and target-day
grouping. It should create a new versioned experiment directory and explicitly
freeze:

- its predictor subset and preprocessing;
- its rolling-origin split or its deliberate reuse of the P07 folds;
- its target and missing-label policy;
- its tuning procedure;
- its probability support and evaluation metrics;
- its holdout-opening rules; and
- its own hashes and manifest.

Do not mutate `universal_issue_state/v1/`, `truth/kden_tmax/v1/`,
`folds/kden_v375/v1/`, or `modeling/experiments/rafm_v1/` to accommodate a new
model. Publish a versioned successor or model-specific adapter instead.

## Prohibited shortcuts

Do not:

- import anything at runtime from `previous codebases/`, KDEN v3, or KDEN v3.5;
- edit, rename, delete, or overwrite frozen P01-P07 artifacts;
- rebuild the selected cycles during model fitting;
- use a later HRRR cycle than the frozen issue-time selection;
- treat the 118,536 issue rows as independent samples;
- split rows from one target day across training and assessment;
- expose truth, truth QC, CLI/CF6 chronology, or fold assignment as weather
  predictor features;
- use holdout or tail outcomes for fitting, tuning, calibration, residual
  distributions, or research decisions;
- replace explicit missingness with a blanket zero fill;
- silently change exact-time analog matching, feature subsets, units, or
  metrics; or
- write fitted-model outputs back into the frozen release directories.

Historical codebases may be read as fossils for ideas, but the v3.75 runtime is
self-contained and may never import them.

## Validate before fitting

From the KDEN v3.75 project root, run:

```bash
.venv/bin/python -m kden_v375.prefit.p07_experiment validate
```

Expected high-level result:

- `status: VALID`;
- `release_status: PREFIT_COMPLETE_MODEL_FITTING_AUTHORIZED`;
- 118,536 adapter rows;
- 2,080 date-role rows;
- three outer folds and 15 nested inner-fold instances;
- 365 sealed holdout rows;
- zero model fits in the prefit release; and
- zero network requests.

The key final authority records are:

- `state/KDEN_V375_UNIVERSAL_ISSUE_STATE_PASS.json`;
- `state/PREFIT_P06_PASS.json`;
- `state/PREFIT_P07_PASS.json`; and
- `state/KDEN_V375_MODELING_BOUNDARY_PASS.json`.

At the accepted boundary, the P06 release status is `FROZEN_ACCEPTED` and the
P07 boundary status is `PREFIT_COMPLETE_MODEL_FITTING_AUTHORIZED`.

## Where new work should go

Keep the accepted inputs immutable. A clean model implementation should write
to a new, clearly versioned location, for example:

```text
modeling/experiments/<new_experiment_id>/
  config/
  manifests/
  oof_predictions/
  fitted_models/
  evaluation/
  reports/
```

Record the P06 substrate release ID, P07 contract hash when applicable, truth
release ID, fold manifest hash, code revision, random seeds, and every input
artifact hash in the new experiment manifest. Predictions should retain
`issue_state_id`, `target_date`, `statistical_group_id`, issue time, fold IDs,
model ID, and fit provenance so every score can be traced back to its evidence.

## Authoritative reading order

A newcomer should read these files in order:

1. this README;
2. `state/KDEN_V375_MODELING_BOUNDARY_PASS.json`;
3. `universal_issue_state/v1/release_index.json`;
4. `universal_issue_state/v1/registries/universal_feature_registry_v1.json`;
5. `reports/prefit/P07_SCIENTIFIC_DECISIONS.md`;
6. `config/prefit/p07_rafm_experiment_v375.json`;
7. `modeling/experiments/rafm_v1/adapters/adapter_registry.json`;
8. `folds/kden_v375/v1/fold_manifest.json`; and
9. `truth/kden_tmax/v1/reports/P02_TRUTH_COVERAGE_QC.md` when truth provenance
   or exclusions matter.

The weather substrate, truth package, folds, and experiment contract are now
engineered and frozen. Model-fitting code should consume those authorities,
not recreate them.
