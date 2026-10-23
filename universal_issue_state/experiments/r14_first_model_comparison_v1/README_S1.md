# S1 — development loader and scoring foundation

S1 is complete. Read [the completion report](reports/S1_REPORT.md). The immutable S0 files remain unchanged; [the S1 supplement](config/s1_foundation.json) records the current access and synthetic-band clarification.

## Bands are supplied, never inferred

An outcome of 92°F does not establish whether Kalshi listed 91–92°F, 92–93°F, or another applicable contract. The fixed pair-even, pair-odd and five-degree partitions are **synthetic weather diagnostics only**. Every corresponding score name begins with `synthetic_`. They are not historical listings, and neither alignment is selected using outcomes.

`inclusive_band_probability(pmf, lower, upper)` requires explicit integer endpoints (or `None` for an open-ended tail). It sums the supplied interval and does not choose boundaries. A future market bridge must obtain actual listed boundaries and settlement rules as of the decision. S1 reads no market data and implements no inference about how Kalshi chooses listings.

## Validate and test

From the KDEN v3.75 project root, use the existing environment read-only. No dependency installation is needed for S1.

```sh
.venv/bin/python -B universal_issue_state/experiments/r14_first_model_comparison_v1/src/s1.py validate --project-root .
.venv/bin/python -B -m unittest discover -s universal_issue_state/experiments/r14_first_model_comparison_v1/tests -v
```

Expected: `VALID`; 61 passing tests (13 S0 and 48 S1). Validation hashes the S0/S1 artifacts and upstream inputs; it reads no outcome values.

The bounded probe loads four predetermined development days. It checks feature joins and training labels but does not compute real model scores or print/persist label values.

```sh
.venv/bin/python -B universal_issue_state/experiments/r14_first_model_comparison_v1/src/s1.py probe --project-root .
```

Expected: four model input batches, 224 issue states each; four unique audited training labels returned across 224 rows for the GAM batch; no model fits or real model scores. The spring-forward date contributes 53 issues and the other dates 57 each.

## API map

The package is `src/r14_s1/`; add this experiment's `src` directory to the Python import path when writing later experiment-owned runners.

- `data.DevelopmentLoader`: verifies used input hashes; reads nominal folds and role metadata; enforces the two-day training-label cutoff; loads strict required-input feature sets; verifies issue/spine/cycle identities and legal time windows. `load_features()` returns a `FeatureBatch` with numeric predictors, separate metadata, availability, missing-column reasons and feature lineage.
- `loader.training_labels(batch)`: returns aligned audited labels only for a TRAIN batch. Labels never become columns of X. Unresolved, reserved, tail, outside-fold and lag-excluded dates are rejected.
- `loader.input_hashes()`: call after features and labels are loaded to capture complete fit input lineage, including the audited development ledger. `batch.source_hashes` describes feature-loading lineage only.
- `probability`: integer PMF validation; stable normal-CDF interval masses; residual-kernel mixtures; endpoint accumulation; half-away rounding; mean/median/mode, entropy and intervals; explicit-boundary summation.
- `scoring.score_rows`: named row-level point, probability, interval, tail, threshold and synthetic-band scores. Pass raw center as `point` for baselines, GAM location for GAM, and PMF mean for AnEn. If omitted, rounded named-point metrics are omitted rather than guessed.
- `aggregate_scores`: equal-day summaries, root-of-mean-squared-error RMSE and weighted absolute-error quantiles. Missing predictions remain outside conditional accuracy with explicit coverage counts.
- `paired_common_summary`: requires identical issue-ID ordering and applies one common availability mask across models. It never pairs rows on position without checking keys.
- `reliability`: fixed bins, signed gaps and descriptive ECE; sparse bins remain visible.
- `confidence_threshold`: training-OOF weighted quantiles. The caller must supply the eligible training OOF population required by S0; this numerical primitive does not validate model-fit chronology itself.
- `selection_summary`: expects a row for every issue in the declared evaluation population, including unavailable forecasts. It reports expected/available checkpoint coverage, day-weighted coverage, unique-day coverage, admitted counts, probability versus realized hit rate, and the separately labeled equal-admitted-day hit rate. Optional `ranking_scores` supports entropy/interval-width ranking while retaining actual event probabilities for reliability.
- `forecast`: outcome-free Arrow record schema, causal lineage checks, explicit abstentions, expected-key checks, write-once prediction partitions and hash-bound manifests. A partition is accepted only after its manifest exists and verifies. Interrupted publication can leave an incomplete directory; it is rejected rather than silently resumed/overwritten. The S2 runner must implement the authorized recovery protocol.

## Truth access refinement

The canonical truth catalog combines development and final-evaluation rows in one Parquet row group. Reading its target column with a row filter may still decode the whole outcome column chunk. S1 never projects that target column.

Instead, it reads catalog authorization and source-identity metadata for requested training dates, verifies the exact audited development ledger referenced there, verifies the ledger contains no reserved/tail dates, and projects `target_date` plus `y_audited_f` for the authorized dates. The frozen P02 builder assigns development catalog `y_audited_f` directly from this ledger without transformation; its code hash is recorded and checked by the S1 validator. This is the same target through its physical provenance, not a substitute truth series.

The source ledger contains earlier development-era records (2017–2025) in one row group. Arrow may internally decode those source-column pages, but only requested fold-eligible 2021–2025 labels are returned. There are no reserved or tail outcomes in that file. No sealed source or market settlement file is accessed.

## What is deliberately next

S1 implements foundation code and bounded verification. It has not constructed fitted baseline distributions, tuned AnEn/GAM, run whole-history scoring, produced comparative findings, or read outer-assessment labels. The assessment API exposes features only; locked outcome-bearing scoring orchestration belongs to the later model/evaluation runners. Bootstrap inference, plots and the assembled scorecard remain S5 work using these primitives.

Next stage: **S2 — construct and freeze the R14 hourly and subhourly baseline distributions and predictions** under the registered nested folds. The actual model-fitting environment, long-run commands and recovery controls must be prepared before those runs.
