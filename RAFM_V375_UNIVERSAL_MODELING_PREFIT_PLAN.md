# Public edition: historical prefit plan

The planning status below predates implementation. P01–P07 were subsequently
accepted; that acceptance does not mean the planned adaptive RAFM mixture was
fitted. See the [current evidence summary](README.md). This public copy does
not bundle the full frozen substrate; see [data availability](DATA_AVAILABILITY.md).

---

# KDEN v3.75 — Universal Modeling Substrate and RAFM Prefit Plan

Version: 2.0  
Planning date: 2026-09-23  
Plan ID: `KDEN_V375_UNIVERSAL_MODELING_PREFIT_V2`  
Intended substrate release: `KDEN_V375_UNIVERSAL_ISSUE_STATE_V1`  
Intended truth bundle: `KDEN_V375_TRUTH_EVIDENCE_V1`  
Status: governing post-acquisition plan; P01–P07 are not implemented  
Primary model direction: Regime-Adaptive Forecast Mixture (RAFM), centered on Analog Ensemble (AnEn) experts  

## 1. Purpose

This document is the complete implementation map between the frozen R14 HRRR
archive and model fitting. It replaces all earlier versions of the v3.75
P01–P07 plan.

Its purpose is to remove conversational ambiguity. A coding agent implementing
`P01`, `P02`, or any later stage must be able to determine:

- what already exists;
- what must be copied rather than rebuilt;
- what is frozen and may not be changed;
- what each stage produces;
- what the owner must run;
- what remains sealed;
- which dates may be used for training, tuning, and final evaluation; and
- exactly when model fitting may begin.

This plan does not authorize trading, model promotion, or opening the final
holdout. It does authorize implementation of P01–P07 under the contracts below.

## 2. Current project state

The HRRR acquisition phase is complete. It must not be reopened by P01–P07.

| Foundation | Frozen identity |
|---|---|
| R14 scope | `KDEN_V375_R14_V1` |
| R14 acquisition PASS | `0852fea463aaad9b4b65ce5c103c45605a0b13ccd338914911b025b1aff8ecfb` |
| Step 07 reader PASS | `5d66348c7dc7bbba5beb4eb3f27a9e1b847c4e15abc4646da6f8c9849b8928c5` |
| Final acquisition PASS | `66c58ff231b1382c0a00e4aae0ae32c93e3c48255ce8ab3aa8a444c20cc37c1a` |
| Step 08 PASS | `2d525d3e7949adcb5e64781c858e3b7f2f7be7072ec917bd88eea087dbc4f85e` |
| Acquisition freeze | `291cfc543f41fce327812e4453e2a56688eb1145ec19fc8193242b647de4c320` |

The frozen acquisition contains:

- 2,080 target days from 2021-01-01 through 2026-09-11 inclusive;
- 12 dynamic hourly fields: H02, H07, H16, H17, H18, H19, H24, H26,
  H28, H31, H36, and H38;
- static terrain field H14;
- subhourly temperature field Q05;
- 2,081 hourly work units and 2,080 Q05 work units;
- 8,919,598 logical requests; and
- explicit source missingness, including 12 accepted remote-missing hourly
  requests.

The R14 archive is a model-neutral source archive. It is not yet a training
table.

## 3. Authority and required reading

Before implementing a stage, read these in order:

1. `KDEN_V375_DEVELOPER_HANDOFF.md`, when present;
2. this entire plan;
3. `PROJECT.md`;
4. `reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md`;
5. `config/issue_time_views_r14_v375.json`;
6. `schemas/issue_time_view_r14_v375.json`;
7. `reports/step_07_OWNER_RUNBOOK.md`;
8. `reports/step_08_final_acceptance_v375.json`;
9. `reports/kden_v375_acquisition_freeze_manifest.json`;
10. `state/KDEN_V375_ACQUISITION_PASS.json`; and
11. `state/STEP_08_PASS.json`.

Use this authority order:

1. explicit current owner instruction;
2. frozen manifests and PASS records for completed work;
3. this V2 plan for P01 onward;
4. `PROJECT.md` for R14 acquisition, timing, and spatial contracts;
5. current v3.75 schemas/configs/runbooks;
6. research documents;
7. historical KDEN v3/v3.5 code and documents; and
8. conversational recollection.

Historical documents are context, not current stage instructions.

## 4. Frozen boundary

### 4.1 Acquisition artifacts

Everything named by `reports/kden_v375_acquisition_freeze_manifest.json` is
immutable. This includes:

- the canonical archive under `hrrr_v4_local_archive/`;
- acquisition and acceptance journals/checkpoints;
- frozen source files;
- acquisition environment files;
- request plans and schedules;
- registries and spatial contracts;
- schemas;
- final reports; and
- PASS/state records.

Do not edit, rename, compact, normalize, rewrite, delete, or regenerate these
artifacts in place. A real defect requires an owner-authorized, versioned
successor that preserves the old bytes and hashes.

### 4.2 Legacy code

`previous codebases/`, KDEN v3, and KDEN v3.5 are fossil references.

They may be read for engineering or scientific ideas. Code may be manually
adapted into new v3.75-owned modules and retested. They may not be imported,
added to `PYTHONPATH`, executed as runtime dependencies, or referenced through
absolute paths by a v3.75 release.

P02 has one explicit exception to the ordinary fossil rule: the completed KDEN
v3.5 Stage 5R.1 truth package is an authorized migration input. Its artifacts
are copied into v3.75, verified, and thereafter used from v3.75 only. This does
not authorize runtime coupling to `kden35`.

### 4.3 Environment

The acquisition environment recorded in `pyproject.toml` and
`environment/requirements.lock` is frozen by Step 08. P01 must define a
separate, versioned modeling/prefit environment strategy rather than silently
changing the frozen acquisition environment.

## 5. Scientific objective

For target day `d`, issue time `tau`, and whole-degree-Fahrenheit outcome `k`,
the project ultimately estimates:

`P(Y_d = k | X[d,tau])`

`X[d,tau]` must contain only information legally available by `tau`.

The immediate modeling hierarchy is:

1. raw H-BI baseline;
2. raw Q15-BI baseline;
3. generalist thermal AnEn;
4. constant-weight specialist AnEn mixture; and
5. adaptive RAFM soft-gated specialist mixture.

RAFM is the first model program, not the definition of the substrate. A later
GAM/GAMM, tree model, neural model, or other defensible model must be able to
consume the same frozen issue states without rebuilding R14.

Weather-model development remains separate from Kalshi market replay. Market
prices, outcomes, trades, settlement data, and market-derived features are not
permitted in the universal weather substrate.

## 6. Binding time contract

Every issue state distinguishes:

| Clock | Meaning |
|---|---|
| Target day `d` | Contract-authoritative KDEN date |
| Issue time `tau` | Weather-information cutoff |
| Cycle initialization `c_p` | HRRR product initialization |
| Emulated availability `a_p` | Time a cycle becomes usable |
| Physical/valid time `v` | Time described by a forecast value |
| Forecast lead | `v - c_p` |
| Issue horizon | `v - tau` |
| Interval start/end | Physical support of interval fields |
| Model-ready time | Issue time plus operational processing latency |
| Market time | Causal market observation/decision time |
| Truth availability | Time the final outcome can be known |

The source target window remains:

`W[d] = [07:00Z_d, 07:00Z_(d+1))`

The right boundary is open and fixed in UTC.

The binding V1 issue grid is:

- 02:00 through 16:00 `America/Denver`;
- every 15 minutes;
- inclusive;
- enumerated DST-safely on a UTC timeline.

The historical availability emulator remains
`KDEN_HIST_COMPLETE_L105_V1`: the selected product cycle is the newest cycle
whose initialization plus 105 minutes is no later than issue time.

Hourly and Q05 cycles are selected independently. Same-cycle bundles may not
be stitched from multiple cycles.

## 7. Independent statistical unit

The independent weather event is the target day, not the issue row.

An ordinary target day has 57 issue rows, but all 57 describe one realized
daily Tmax. Folds, uncertainty estimates, analog pools, calibration, and
evaluation must group all rows from the same target day together.

For the default exact-time AnEn design, a query issue time may use at most one
compatible historical state from each eligible training day. Treating every
issue row as an independent analog would create pseudoreplication.

Any neighboring-time analog challenger is a separate P07 experiment and may
not replace the exact-time default silently.

## 8. Existing authoritative KDEN truth package

### 8.1 The truth work is already done for the development period

KDEN v3.5 Stage 5R.1 created an audited KDEN Tmax truth package. P02 must copy
and adopt it rather than rebuild 2021–2025 truth from IEM.

The human-visible migration source is:

`<LEGACY_TRUTH_SOURCE>`

This absolute path may appear in documentation and an owner migration command.
It must not appear in runtime code or persisted scientific artifacts.

The binding source artifacts are:

| Artifact | Source-relative path | SHA-256 |
|---|---|---|
| Audited truth ledger | `data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/kden_truth_ledger.parquet` | `8e720bc58c1b31f63ba207a26fa50b9e49b5582850b2304ea2c0df1d008634ca` |
| CLI/CF6 event chronology | `data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/kden_truth_events.parquet` | `e73e976d0023edb4fbd1126b714111ca068d2b5713689842857074d9180840fb` |
| Review queue | `data/processed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/kden_truth_review_queue.parquet` | `f75989560f3c2603c5729fba806770098147d2925b4a51600350e0b7cfb84a9e` |
| Sealed mechanical candidates | `data/sealed/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/kden_truth_mechanical_candidates.parquet` | `3ae63561b432e302a304319ad87fbc3c302fab091469516b00279e6c6985dd36` |
| Frozen protocol | `configs/stage5r_truth_v1.toml` | `0d60111957f79f25128e0dacdd400cb93ead9f75690449ba045c151dddf37ded` |
| Guarded exceptions | `configs/stage5r_truth_exceptions_v1.csv` | `3a94910bdfe58a13dcbb7098e6bf13be0e4265a10b1458522414ce340ac665a5` |
| Stage 5R.1 manifest | `manifests/stage5r/schema=1.0/stage=5R.1/protocol=1.0.0/run=stage5r1-build-20260911T081406Z-e1bd6f97f4/manifest.json` | `2a61bc8a0d2b7160399d9138b7ef461ff2678a53d59fc6e791949b736ab37fe8` |

The complete source-evidence roots must also be copied:

- `data/raw/stage5r/kden_truth/protocol=1.0.0/`;
- `data/sealed/stage5r/kden_truth/protocol=1.0.0/`.

The copied package therefore preserves the daily audit responses, `CLIDEN`
archives, `CF6DEN` archives, indexes, source metadata, hashes, accepted values,
unresolved values, and sealed evidence.

### 8.2 Authoritative field

The authoritative model target is:

`kden_truth_ledger.parquet::y_audited_f`

Rules:

- join by `target_date`;
- use only non-null `y_audited_f` for supervised fitting/scoring;
- preserve `truth_qc_status` as metadata;
- never expose truth status, review flags, CLI/CF6 values, or target values as
  predictor features;
- never impute an unresolved truth value.

The following are not authoritative targets:

- an atomic IEM daily value;
- `selected_tmax_f` or `label_selected_tmax_f` from older tables;
- an individual CLI value by itself;
- an individual CF6 value by itself;
- a MADIS-derived daily maximum;
- a mechanical candidate by itself; or
- a reconstructed Kalshi settlement value.

### 8.3 Why the audit was necessary

Atomic IEM daily values were usually useful but were not guaranteed truth.
Later malformed or misdated reports could replace a correct value. Two guarded
corrections in the frozen package are:

| Date | Incorrect atomic value | Audited truth |
|---|---:|---:|
| 2021-01-20 | 39°F | 59°F |
| 2022-04-18 | 80°F | 65°F |

Stage 5R.1 therefore preserved the complete eligible CLI/CF6 chronology and
accepted a date automatically only when both products existed and all eligible
values agreed. Disagreements remained unresolved unless a guarded exception
matched the exact evidence. That logic is reused; it is not redesigned.

### 8.4 Coverage inside R14

| R14 interval | Evidence state | V2 policy |
|---|---|---|
| 2021-01-01–2025-09-06 | 1,710 ledger rows; 1,707 audited and 3 unresolved | Copy exactly; audited non-null rows are development truth |
| 2025-09-07–2026-09-06 | 365 days of locally stored source evidence and sealed candidates | Copy exactly and keep sealed as the final one-year holdout |
| 2026-09-07–2026-09-11 | Five R14 dates outside Stage 5R.1 | Acquire and audit with the same rules |

The 365-day holdout is not missing data. The underlying reports are stored,
but `y_audited_f` is intentionally null and must remain unopened until the
weather model and evaluation procedure are frozen.

### 8.5 Final five dates

P02 must acquire the source evidence for 2026-09-07 through 2026-09-11 using
the adapted Stage 5R.1 machinery. It must retrieve the KDEN daily audit
evidence and the relevant `CLIDEN`/`CF6DEN` product archive evidence, then apply
the same fixed climate-day and unanimity rules.

The owner has explicitly authorized these dates to be treated as truth now if
the currently available evidence passes the existing audit rules. There is no
`pending_maturity` exclusion.

For transparency, accepted tail rows must record:

- `truth_evidence_cutoff_utc`;
- `source_followup_window_open_at_freeze`;
- source retrieval timestamps and hashes; and
- the same normal truth QC status used for other accepted or unresolved rows.

`source_followup_window_open_at_freeze` is metadata only. It is not a reason to
null or exclude an otherwise accepted target. If CLI/CF6 evidence conflicts,
the existing rule still applies: leave the date unresolved rather than guess.

Because these five dates occur after the sealed holdout, they are not training
or tuning data. After the model is frozen, final reporting must show:

1. the sealed 365-day holdout result;
2. an extended result that also includes any accepted five-day tail labels;
3. the tail-only result, clearly identified as only five days; and
4. the extended result again with `source_followup_window_open_at_freeze=true`
   rows excluded as a robustness check.

This sensitivity report does not demote the accepted five-day labels. It makes
the owner's accepted assumption visible.

## 9. Self-contained truth-bundle design

P02 creates one v3.75-owned evidence bundle rather than a runtime link to two
KDEN v3.5 directories.

Recommended layout:

```text
truth/kden_tmax/v1/
├── adopted_stage5r1/
│   ├── development/
│   ├── sealed_holdout/
│   ├── source_evidence/
│   │   ├── development/
│   │   └── sealed/
│   ├── protocol/
│   └── source_manifest/
├── tail_2026-09-07_2026-09-11/
│   ├── source_evidence/
│   ├── normalized/
│   └── manifest/
├── catalog/
│   ├── kden_truth_catalog.parquet
│   └── manifest.json
└── reports/
```

The exact copied Stage 5R.1 files remain immutable. The catalog may reference
them, but it does not rewrite or concatenate them destructively.

The catalog has one row per R14 target day and, at minimum:

- `target_date`;
- `truth_release_id`;
- `truth_evidence_status`;
- `label_available_for_supervised_use`;
- `y_audited_f` where legally available;
- `truth_qc_status`;
- source artifact identity/hash;
- evidence-cutoff time;
- follow-up-window flag; and
- explicit exclusion reason where applicable.

Allowed evidence statuses are:

- `audited`;
- `audited_guarded_exception`;
- `unresolved`;
- `sealed_holdout`;
- `tail_audited`;
- `tail_unresolved`; and
- `source_unavailable`.

Do not describe a sealed row as missing and do not describe a mechanical
candidate as audited truth.

## 10. Universal issue-state substrate

The intended release `KDEN_V375_UNIVERSAL_ISSUE_STATE_V1` contains normalized,
linked objects rather than one enormous duplicated table.

### 10.1 Issue spine

One row per `(target_date, issue_time)` with stable `issue_state_id`, UTC/local
clocks, target window, calendar metadata, and eligibility.

### 10.2 Selected cycles

One row per `(issue_state_id, product)` with selected cycle, emulated
availability, previous legal cycle, cycle age, availability age, source
schedule identity, and missingness.

### 10.3 Trajectory catalog

References unique R14 archive states and preserves field, product, cycle,
physical valid time, lead, interval support, spatial identity, archive unit,
hash, value columns, and coverage status.

### 10.4 Deterministic feature panel

Target-free, model-neutral summaries keyed by `issue_state_id`. It may include
thermal paths, peaks, slopes, vertical temperature structure, moisture, wind,
PBL, snow, cloud, solar, reflectivity, precipitation, terrain, spatial
summaries, cycle revisions, clock diagnostics, and missingness.

It may not contain target-guided feature selection, learned scaling, learned
embeddings, analog weights, fitted regimes, truth fields, or market data.

### 10.5 Labels

Labels remain physically and logically separate and are keyed by target day.
The feature release must be buildable without reading target values.

### 10.6 Fold assignments

Fold assignments remain separate and group all issue rows from the same target
day together.

## 11. P01–P07 stage ledger

Stages are serial governance gates. Each PASS stores predecessor hashes. A
later stage may not silently repair or reinterpret an earlier PASS.

### P01 — Foundation and contract freeze

**Purpose:** Turn this plan into machine-readable contracts before building
data.

**Binding decisions already made:**

- issue grid: 02:00–16:00 America/Denver every 15 minutes inclusive;
- availability emulator: L105;
- independent hourly/Q05 cycle selection;
- target-day grouping;
- existing 365-day Stage 5R.1 holdout remains sealed;
- final five dates are acquired/audited now and not blocked by the historical
  62-day follow-up convention;
- exact folds are frozen in P07, not invented in P01;
- model-ready/market latency belongs to a later commercial bridge;
- truth, MADIS, market, and legacy runtime remain isolated;
- RAFM is the first adapter, not the substrate definition; and
- the frozen acquisition environment is preserved.

**Required work:**

- bind this V2 plan and Step 07/08 predecessors;
- encode the clock ontology and object primary keys;
- encode the truth evidence roles and date groups in section 8.4;
- define the modeling-environment successor strategy;
- define new artifact roots without modifying frozen acquisition files; and
- define PASS/validation schemas.

**Deliverables:**

- P01 foundation contract;
- time-ontology and evidence-role schemas;
- owner-readable decision report;
- `state/PREFIT_P01_PASS.json`.

**Prohibited:** network acquisition, target-value inspection, feature
materialization, fold invention, and model fitting.

**PASS:** All decisions above are encoded without introducing a new scientific
choice.

### P02 — Truth-package adoption and five-day extension

**Purpose:** Make all truth evidence self-contained in v3.75 while preserving
audited, unresolved, sealed, and tail roles.

**Required work:**

1. Copy every Stage 5R.1 artifact and source-evidence root listed in section 8.
2. Verify the known hashes before and after copying.
3. Preserve the copied bytes unchanged.
4. Create a v3.75 adoption manifest using source-relative identities, never an
   absolute runtime path.
5. Adapt the necessary Stage 5R.1 acquisition/audit logic into new
   `kden_v375`-owned code with no `kden35` import.
6. Add bounded tests reproducing the two guarded correction cases and
   representative accepted/unresolved/sealed behavior.
7. Prepare the owner-run network command for 2026-09-07 through 2026-09-11.
8. Apply the identical audit rules to those five dates.
9. Build the 2,080-day truth catalog without opening the 365-day holdout.
10. Validate copy hashes, schemas, coverage, statuses, and isolation.

The five-day network run is owner-run. The implementation agent supplies start,
status, live status, ETA where meaningful, pause/resume if supported,
validation, artifact locations, and PASS criteria.

**Deliverables:**

- `KDEN_V375_TRUTH_EVIDENCE_V1`;
- copied immutable Stage 5R.1 package;
- five-day tail evidence and normalized results;
- `kden_truth_catalog.parquet`;
- adoption and tail manifests;
- coverage/QC report;
- owner runbook; and
- `state/PREFIT_P02_PASS.json`.

**PASS:** All copied hashes match; the 365-day holdout remains sealed; every
R14 day has an explicit evidence status; accepted targets are reproducible;
unresolved rows remain null; and no runtime KDEN v3.5 dependency exists.

P02 may PASS with an explicitly `source_unavailable` or `tail_unresolved` final
date if the source itself prevents an audited answer. It may not invent one.

### P03 — Issue spine and legal-cycle selections

**Purpose:** Materialize every causal historical decision state.

**Required work:**

- enumerate the DST-safe issue grid for all 2,080 R14 target days;
- create stable issue-state IDs;
- select hourly and Q05 cycles independently under L105;
- preserve previous legal cycles for revision features;
- record cycle/availability ages and schedule provenance;
- link issue states to trajectory bundles;
- prove no future or post-window source state is selected; and
- seal exact row and missingness counts.

**Deliverables:**

- `issue_spine.parquet`;
- `selected_cycles.parquet`;
- selection manifest;
- coverage/DST report; and
- `state/PREFIT_P03_PASS.json`.

**PASS:** Every issue state is causal, DST-valid, independently resolved by
product, and traceable to frozen R14.

### P04 — Universal primitive and feature registry

**Purpose:** Define deterministic, model-neutral transformations before the
full build.

**Required work:**

- define trajectory, spatial, revision, clock, and missingness primitives;
- specify units, valid-time support, windows, alignment, null behavior, and
  physical ranges;
- distinguish point, tile, and registered regional operations;
- prohibit cycle stitching and unjustified interpolation;
- separate universal deterministic features from model-specific adapters;
- create deterministic names and schema evolution rules; and
- test bounded ordinary, DST, missingness, snow, convective, dry-heating, and
  mixing/downslope cases.

**Deliverables:**

- universal feature registry;
- feature-panel schema;
- deterministic transformation library/tests;
- P04 report; and
- `state/PREFIT_P04_PASS.json`.

**PASS:** Every feature uses legal R14 state alone and has explicit time
support, units, missingness, and provenance.

### P05 — Universal substrate materialization

**Purpose:** Build the complete target-free issue-state release.

**Required work:**

- materialize the normalized objects in section 10;
- avoid duplicating canonical R14 trajectories for every issue row;
- partition deterministically, normally by target year;
- preserve archive identities and hashes;
- keep labels separate;
- provide atomic publication and resumable checkpoints; and
- publish status, live status, ETA, pause, resume, and validation surfaces.

The full-history build is owner-run.

**Deliverables:**

- `KDEN_V375_UNIVERSAL_ISSUE_STATE_V1`;
- release index and manifest;
- resumable journal;
- owner runbook/build report; and
- `state/PREFIT_P05_PASS.json`.

**PASS:** The feature-only release is complete, deterministic,
content-addressed, resumable, and rebuildable from frozen local inputs without
network access.

### P06 — Full substrate acceptance and freeze

**Purpose:** Prove the release is safe for arbitrary model adapters.

**Required work:**

- reconcile issue states, cycles, trajectory references, and features;
- verify clock equations, right-open windows, and issue-time availability;
- validate lead, horizon, intervals, units, spatial rules, and ranges;
- validate DST, coordinate eras, explicit missingness, and anchor rebuilds;
- scan for truth, market, MADIS, outcome, and legacy-runtime leakage; and
- freeze code, contracts, environment, inputs, outputs, and manifests.

The full acceptance scan is owner-run.

**Deliverables:**

- final substrate acceptance report;
- immutable substrate freeze manifest;
- `state/KDEN_V375_UNIVERSAL_ISSUE_STATE_PASS.json`; and
- `state/PREFIT_P06_PASS.json`.

**PASS:** The release is causal, complete, deterministic, model-neutral,
isolated, and content-addressed.

### P07 — Folds, model adapters, and RAFM experiment freeze

**Purpose:** Create fitting-ready views and freeze experiments without fitting
an expert or gate.

**Development evidence:**

- R14-overlap audited targets from 2021-01-01 through 2025-09-06;
- unresolved rows excluded from supervised loss/scoring but retained for
  target-free diagnostics.

**Final evaluation evidence:**

- sealed holdout: 2025-09-07 through 2026-09-06;
- post-holdout tail: 2026-09-07 through 2026-09-11, using accepted P02 labels;
- neither group is used for feature selection, tuning, calibration, expert
  fitting, gate fitting, or promotion-rule design.

**Required work:**

- freeze target-day-grouped rolling-origin outer folds within development;
- freeze nested inner folds;
- preserve seasonal representation and report fold coverage by winter,
  spring, summer, and autumn;
- define target joins without duplicating independent outcomes;
- freeze integer PMF support and tail treatment;
- freeze H-BI and Q15-BI baselines;
- freeze generalist/specialist AnEn features;
- freeze exact-time analog matching as default;
- define any neighboring-time challenger separately;
- freeze fold-local scaling, distances, neighbor/kernel bounds, seasonal
  eligibility, pool minima, and tie breaking;
- freeze specialist eligibility, abstention, and fallback;
- freeze analog-support and out-of-distribution diagnostics;
- freeze constant-mixture and adaptive-gate inputs/regularization;
- require nested out-of-fold expert predictions for gate training;
- freeze metrics, ablations, uncertainty, and promotion criteria;
- freeze the final holdout-opening procedure; and
- freeze the four-way final report specified in section 8.5.

**Deliverables:**

- fold registry/manifest;
- target-free model-input adapters;
- RAFM experiment contract/schemas;
- contamination and holdout report; and
- `state/PREFIT_P07_PASS.json`.

**PASS:** Fitting can begin without making another causal, feature, fold,
target, tuning, or evaluation decision. The holdout remains unopened.

## 12. Exact model-fitting boundary

Model fitting is prohibited until P01–P07 each PASS and validate.

The first fitted operation is:

> Generate inner-fold out-of-fold PMFs and analog-support diagnostics for the
> generalist thermal AnEn using development dates only.

Then:

1. evaluate raw H-BI and Q15-BI baselines;
2. fit/tune generalist AnEn within nested development folds;
3. fit/tune specialist AnEn experts within those folds;
4. build an equal/fixed-weight specialist comparator;
5. fit a training-only constant-weight mixture;
6. fit adaptive RAFM using expert out-of-fold PMFs and legal diagnostics;
7. perform any authorized fold-internal calibration;
8. freeze the weather model and evaluation code;
9. open/audit the sealed holdout without looking at predictions;
10. perform the frozen final evaluation, including the specified tail
    sensitivity; and
11. only afterward build a separate rolling commercial/market bridge.

No gate may train on in-sample expert predictions. Scaling, feature selection,
distance tuning, analog tuning, calibration, and gate fitting remain inside the
applicable training fold.

## 13. RAFM specialist hypotheses

| Expert | Principal R14 evidence |
|---|---|
| General thermal | H16/Q05 paths, H02/T700, H07/T850, peaks/revisions |
| Dry heating | H31 solar, H17 dewpoint depression, H24 PBL, H18/H19 wind |
| Cloud/solar | H28 cloud, H31 solar, H36 reflectivity, path disruption |
| Convection/precipitation | H36, H38, H28, H17, H18/H19 |
| Snow/surface | H26, H31, H16/H17, H24 |
| Mixing/downslope | H24, H18/H19, H07/H02, H14 terrain context |

R14 does not contain CAPE/CIN, pressure-level wind, or subhourly cloud or
precipitation fields. Q05 provides fast temperature evolution only. An expert
may not pretend excluded evidence exists.

## 14. Minimum diagnostics and evaluation

Every AnEn expert should emit:

- nearest, median, and kth-neighbor distance;
- eligible-pool and retained-neighbor counts;
- effective sample size;
- robust residual spread;
- distance concentration;
- out-of-training-range fraction;
- distance relative to the fold's training distribution;
- seasonal/issue-time compatibility;
- missing-input and abstention indicators; and
- PMF entropy and interval width as descriptive diagnostics.

Minimum model comparisons:

- H-BI;
- Q15-BI;
- generalist AnEn;
- equal-weight eligible specialist mixture;
- training-only constant-weight mixture;
- adaptive RAFM;
- RAFM with each specialist removed; and
- state-only, support-only, and combined gate inputs.

Primary evaluation includes log score, RPS/CRPS, threshold/band Brier scores,
calibration, interval coverage/sharpness, issue-time performance, seasonal and
meteorological strata, analog-support strata, paired target-day block
uncertainty, worst-year stability, and worst-regime stability.

MAE, bias, exact hit, and within-one-degree accuracy are secondary.

## 15. Long-running owner-run rule

The implementation agent does not run or wait on:

- network acquisitions;
- full-history materializations;
- full acceptance scans;
- broad validations that may take substantial time;
- model fitting/tuning;
- backtests; or
- other minute-to-hour jobs.

The agent runs only bounded unit tests, schema checks, tiny fixtures, and small
representative probes. If a probe unexpectedly exceeds roughly 30–60 seconds,
stop it and hand it to the owner.

Every owner-run workflow must provide:

1. install command;
2. exact start command;
3. run ID;
4. one-time status command;
5. append-only live-status command;
6. separate ETA command when meaningful;
7. pause command;
8. resume command using the same run ID;
9. safe stop/recovery guidance;
10. validation command;
11. output/report/journal locations; and
12. expected PASS conditions.

Do not modify code, schemas, contracts, environment files, or live output while
an owner process is running unless the process is first stopped and the owner
explicitly authorizes the correction.

## 16. Engineering requirements

- Use new v3.75-owned modules and artifact roots.
- Never embed user-specific absolute paths in runtime artifacts.
- Preserve deterministic ordering and stable primary keys.
- Preserve explicit missingness and evidence status.
- Use atomic publication and resumable checkpoints.
- Store content hashes, schema IDs, contract IDs, and predecessor PASS hashes.
- Keep truth, features, folds, market data, and commercial replay separate.
- Never synthesize a value merely to meet an expected count.
- Preserve unrelated owner changes.
- Do not destructively reset, delete, or rewrite historical artifacts.
- Use network-free validation wherever possible.
- Treat a stage PASS as protocol/artifact success, not evidence of model skill
  or commercial value.

## 17. Open decisions assigned to later stages

The following remain deliberately unresolved, but their responsible stages are
fixed:

| Decision | Stage |
|---|---|
| Exact modeling-environment layout | P01 |
| Destination filenames within the prescribed truth-bundle layout | P02 |
| Exact full-history issue-row count | P03 |
| Exact deterministic feature definitions | P04 |
| Substrate partitions/chunk sizes and storage accounting | P05 |
| Full-release acceptance anchors and final hashes | P06 |
| Rolling-origin fold boundaries | P07 |
| PMF integer support/tails | P07 |
| Exact analog distance/scaling/k/kernel/seasonal bounds | P07 |
| Specialist eligibility/abstention/fallback | P07 |
| RAFM gate family and regularization | P07 |
| Numeric promotion/non-inferiority margins | P07 |
| Operational model-ready latency | Later commercial bridge |

These are not invitations for silent agent choices. Each stage must present and
record its assigned decision before PASS.

## 18. Definition of prefit complete

The project reaches the model-fitting boundary only when:

- P01–P07 each have a verified content-addressed PASS;
- the v3.75 truth bundle is self-contained and hash-verified;
- the one-year holdout remains sealed;
- the final five dates have explicit accepted/unresolved/source status;
- the universal issue-state release is frozen and accepted;
- every issue state has explicit clocks and selected cycles;
- deterministic target-free features are complete;
- target-day folds and nested tuning are frozen;
- RAFM inputs, diagnostics, gate, metrics, and promotion rules require no new
  choice; and
- no truth, market, MADIS, or legacy dependency contaminates predictors.

Only then may the generalist AnEn fitting program begin.

## 19. Supersession record

This Version 2 replaces Version 1.0 and the partial Version 1.1 clarification.
The earlier plan was not sealed by a P01 PASS and produced no authoritative
P01/P02 artifacts. It was replaced because it:

- failed to identify the existing Stage 5R.1 truth authority;
- incorrectly framed P02 as a new ground-up truth-source project;
- left the holdout period ambiguous;
- duplicated split responsibility between P01 and P07; and
- did not distinguish stored sealed evidence from absent data.

No acquisition artifact or Step 00–08 PASS was changed by this supersession.
