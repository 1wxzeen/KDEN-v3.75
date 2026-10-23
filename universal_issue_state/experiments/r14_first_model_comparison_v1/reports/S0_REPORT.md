# S0 completion report

Date: 2026-09-25  
Experiment: `R14_FIRST_MODEL_COMPARISON_V1`  
Status: **S0 COMPLETE — ready for S1 implementation**

## What was implemented

The experiment now has a machine-readable scientific contract, exact feature and metric registries, complete candidate grid, evidence-exposure ledger, decision register, separate environment specification, input inventory, focused tests, and a read-only validator. All twelve decision categories from section 14 of the plan have a recorded disposition. Prospective testing is explicitly outside this milestone; formal promotion is disabled rather than left with undefined acceptance margins.

No models were fitted. No outcome values or weather data pages were decoded. Discovery and validation used file hashes, JSON configuration, Parquet schemas/row counts, and explicitly selected role/fold columns. Truth-file bytes were hashed and its schema/row count inspected without decoding target values. Existing source files, v1 artifacts, truth, folds and P07 were not modified.

## Input verification

Twenty-nine selected files were hashed. Where upstream frozen hashes were supplied, actual bytes were checked against them. Canonical embedded record identities were checked separately from whole-file hashes. The P06→P07→modeling-boundary relationships were verified. All 433 feature definitions and all six feature partition row counts are accounted for; every selected model/diagnostic feature exists with matching semantics. The three accepted P06 range corrections are carried forward without rewriting the registry.

This is a bounded input verification, not a rerun of P06's complete raw archive or physical-value acceptance. No 8.9-million-reference trajectory scan, weather-value QC, or truth re-audit was performed. S1 will enforce data access, row joins and value checks when it builds loaders.

Nominal folds match the frozen date roles. A two-day label lag excludes the final nominal training day at each assessment boundary:

| Outer fold | Nominal supervised training days | Lag-eligible training days | Assessment days |
|---|---:|---:|---:|
| OUTER_01 | 727 | 726 | 365 |
| OUTER_02 | 1,092 | 1,091 | 366 |
| OUTER_03 | 1,458 | 1,457 | 249 |

These counts precede model-specific missing-input exclusions. All 15 nested instances are checked with the same rule. The two-day lag is a declared availability assumption applied to retrospectively audited labels, not proof that every later correction was historically available then.

## Closed design choices

- **Baselines:** hourly and subhourly retained maxima; uniform seasonal exact-issue residual kernels. Twelve parameter configurations each.
- **AnEn:** eight thermal similarity features, robust exact-issue scaling, residual translation to raw Q15, deterministic weighted neighbors, explicit zero-distance behavior and no silent k reduction. 180 configurations.
- **Primary GAM:** compact pooled location–scale Gaussian distributional model with eight thermal location smooths, issue-time smooth, seasonality, cycle ages and DST; smaller scale equation. Twelve configurations.
- **Diagnostic GAMs:** four constant-scale normal settings and twelve location–scale Student-t settings with fixed nu=5. These are descriptive, not additional primary inferential comparisons.
- **Numerical guardrails:** smooth bounded log-scale link, 0.25–20°F; fixed basis rules, ridge penalties, three initial scales, deterministic optimization requirements. The bounded link refines the plan's schematic unbounded log-scale formula. Numerical implementation and gradient validation remain S3 work.
- **Tuning:** common target-free feasible support within each family; minimum 60 days and 50% expected day-weighted coverage per included inner block, at least two included blocks. No tuning by favorable missing predictions. Early seasonal gaps can make a block unsupported; report rather than relax thresholds.
- **Missingness:** strict required-input abstention. No hidden operational fallback.
- **Selective forecasting:** native confidence at 100/75/50/25/10% intended coverage, using training OOF quantiles, all confidence ties admitted. Actual future-block coverage is reported; no learned gate or test-set threshold optimization.
- **Inference:** five primary paired NLL contrasts with approximate familywise 95% Bonferroni-adjusted bootstrap intervals; seven-calendar-day blocks and fixed fourteen-day sensitivity. Rich secondary diagnostics are descriptive.
- **Promotion:** none in this milestone. Report effects, uncertainty, stable conditional promise, and failures; do not infer tradability.

## Scorecard coverage

The registry defines mean/median/mode decisions separately; exact-integer and rounded-point hits; both alignments of inclusive two-integer bands; five-degree bands; threshold and multiclass Brier scores; NLL and discrete CRPS/RPS; calibration/PIT; intervals; tail misses; expected/available/day coverage; issue/season/forecast-regime/support slices; intraday revisions; and numerical/operational failure counts.

It also freezes denominators, sparse-bin policies, tie rules, no-admission behavior, and case-study selection. Observed-temperature slices and selected failure cases are explicitly ex-post diagnostics, not validated gates.

## Evidence limitations carried forward

The nominal 365-day holdout was opened and evaluated in KDEN_NBM. Its local v3.75 sealed record is preserved, but it cannot support a fresh blind-test claim for this research. The exposure ledger records overlapping findings from NBM, Layer 1, Layer 4, and Dataset 1. A later truly prospective test must be separately registered.

The R14 substrate supplies forecasts, not station observations. No observed floor or observation departure is synthesized. No historical Layer 1 metric is used as this experiment's baseline score.

## Verification and next step

The S0 validator passed against the selected inputs. Thirteen focused tests passed, including negative controls for reserved-outcome access, fitting in S0, target leakage, changed label lag, unregistered candidates, partition gaps/overlaps, record tampering and path escape. A metadata-access guard confirmed that the validator only reads data pages from the three permitted role/fold files, with explicit column lists.

The environment's direct numerical dependency versions are specified. It has not been installed, and S0 does not claim a validated model-fitting environment or a full platform/wheel lock. The existing project environment was used read-only for metadata checks.

Next: implement **S1 — the filtered development loader and common scoring foundation**, with synthetic scoring tests and bounded data probes. S0 is not authorization to run S2–S4 training or inspect reserved outcomes.
