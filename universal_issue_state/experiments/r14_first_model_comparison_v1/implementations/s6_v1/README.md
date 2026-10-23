# S6 — registered next experiment

**Decision: test conditional reliability first, using the existing AnEn and location–scale normal GAM as fixed temperature-model families.** S6 completes the decision and registration stage. It does not train the reliability models or start live collection.

## The question

Can information visible at issuance improve our estimate of whether a model's chosen integer will be correct, beyond its own confidence, season and issue time?

The target is a yes/no event: did the unchanged base model's most probable integer equal audited Tmax? Every eligible hit and miss is used. A predicted 30% means an estimated 30% chance of that particular integer being correct. It is not a new temperature distribution, and it cannot price arbitrary Kalshi bands. Extending a single-event reliability estimate to a coherent full PMF is separate work.

## Why this comes before another temperature model

S5 established modest average distribution improvements, but confidence failed to transfer consistently. At the strictest selector, normal-GAM pooled accuracy was 27.74%, while partial-2025 accuracy was 16.18% against a predicted 28.08%. Its 2025 subset covered only 55 days. AnEn also weakened. Easier selected cases improved the baselines too. These findings justify testing conditional reliability, not assuming a weather gate already exists.

A new distributional tree remains a reasonable next alternative. It is deferred here so that we first learn whether confidence can be made more informative without simultaneously changing the temperature model. No model family is guaranteed to reach tradability.

## A deliberately small comparison

For each of AnEn and the normal GAM, compare:

| Model | Inputs | Question |
|---|---|---|
| Native reference | Original maximum integer probability | How informative is current confidence? |
| R0 | Logistic recalibration of native confidence | Is simple probability recalibration enough? |
| R1 | R0 plus issue time and cyclic season | Can the calendar explain reliability? |
| R2 | R1 plus six physical forecast coordinates | Does weather add information beyond confidence and calendar? |

The six physical coordinates describe temperature revision, absolute hourly/subhourly disagreement, remaining solar energy, modeled mixing depth, wind strength and surface–850-mb thermal contrast. They are forecasts available at issuance, not future observations. We retain the user's D1-motivated thermal contrast; we do not infer an above-ground lapse rate from it. Solar forcing replaces a redundant cloud input in this first test. Analog support diagnostics remain available in S5 but are not extra candidate features here.

All three models use ridge logistic regression, a fixed penalty of 0.01 on standardized nonintercept terms, and no interactions or hyperparameter search. This is a conservative first test of incremental information. It cannot rule out richer nonlinear reliability structure if it fails. Exact transforms, weighting, solver acceptance and missingness are frozen in [registration.json](registration.json).

## Chronology and evidence cost

| Historical block | Reliability fit | Threshold-only block | Assessment |
|---|---|---|---|
| REL_DEV_2024 | Jan 1–Jun 29, 2023 | Jul 1–Dec 30, 2023 | 2024 |
| REL_DEV_2025_PARTIAL | Jan 1, 2023–Jun 29, 2024 | Jul 1–Dec 30, 2024 | Jan 1–Sep 6, 2025 |

The reliability model remains unchanged from the beginning of its threshold block through its assessment block. This deliberately avoids refitting after choosing a threshold, which would change the score distribution to which that threshold applies. The cost is a less recently trained reliability model; any later rolling-update experiment must be separately registered.

Each row uses the base forecast version available at its historical issuance. The experiment must not fit a final base model and retroactively predict its own training years. Base vintage changes are reported explicitly; we do not smooth away their distribution shifts.

Before reuse, the successor implementation must certify that base selection, fitting and every label-consuming transformation obeyed the two-day lag. S5's excluded-date sensitivity found all 18 base settings unchanged, making reuse plausible, but the successor runtime must verify lineage and issue a certificate. Frozen S2/S4 artifacts remain preserved.

The new [boundary primitive](boundaries.py) enforces the two-day calendar cutoff and authorized evidence interval at all five stages: base fitting, base selection, preprocessing, reliability fitting and threshold fitting. Tests cover the December 31 failure, leap years, reserved dates and each stage separately. **It is not integrated into the frozen runners and does not repair them retroactively.** Integration is the first requirement of CR1.

This registration creates six reliability candidates, each assessed in two historical blocks, for twelve scheduled fits. There is no tuning grid. All these outcomes were previously inspected in this or related projects; historical results are development evidence, regardless of chronological fitting. The existing reserved historical and tail dates remain prohibited. The [evidence ledger](evidence_ledger.json) records the research decisions and their evidence cost.

## Evaluation and explicit stopping rules

The two primary comparisons are R2 versus R1 binary Brier score, one for each base model, over the full common-supported forecast population. This directly asks whether weather improves probability estimates beyond native confidence and calendar. Use the inherited day weighting, paired seven-day calendar bootstrap, fourteen-day sensitivity and 5,000 draws; adjust the two primary intervals together. R0 and the raw probability reference explain where an improvement came from.

The primary selector targets 25% of the earlier threshold block. The 100%, 50% and 10% settings are secondary diagnostics, not alternative cutoffs to try until one wins. Actual future coverage is measured, not forced. Baselines are scored on precisely the same admitted cases. R1 and R2 leave the same base integer unchanged, so their hit rates on identical cases are necessarily identical; their differences concern probability quality and which cases they admit.

Research-readiness targets are registered now:

- At least 0.002 absolute Brier improvement, with the upper adjusted difference bound at or below −0.002, and a favorable point difference in both historical blocks.
- Binary log-loss degradation no greater than 0.01 in the pooled population or either block.
- For the primary selector in each block: at least 10% actual checkpoint coverage and 60 admitted days, absolute predicted-versus-realized hit gap no greater than 3 percentage points, and at least 2 percentage points of hit lift over the Q baseline on identical cases.

These are research hurdles, not estimates of commercial break-even. The Brier margin requires a material probability improvement rather than a merely positive point estimate; the coverage and day limits discourage success through tiny subsets; the calibration and same-case requirements address the failures S5 exposed. The values are judgment-based and are being fixed before this experiment's fitting. Secondary point thresholds do not acquire simultaneous statistical guarantees from the primary Brier intervals. Report uncertainty and failures plainly. Historical success permits considering a prospective test, not claiming blind validation or trading readiness. Failure or insufficient support does not authorize extra gates or a new search.

## Prospective evidence reservation

Reserve **November 1, 2026–October 31, 2027**, in America/Denver target dates, for a potential full-season-cycle prospective test. The reservation is inactive. Before the October 25, 2026 readiness deadline, a successor operational protocol must seal actual model artifacts, permitted training data, live issuance-safe feature construction, forecast archival and scoring rules. These details cannot be certified by a plan document or by historical R14 data alone.

S6 does not start acquisition, monitoring, trading or label access. If readiness is missed, do not backfill forecasts and call them prospective. Record an amendment with genuinely future dates before accessing their outcomes. Keep all twelve months in the planned evaluation, require at least 250 complete target days, and disclose missingness; do not stop early because results look favorable. The initial policy freezes models and thresholds during the reserved year. Any operational modification changes the recorded comparison identity.

A future full-year reservation has an opportunity cost, but S5's annual instability makes that cost explicit and justified. It cannot restore blindness to 2025–2026 dates already inspected elsewhere.

## What is ready and what comes next

S6 delivers this decision, a machine-readable registration, parent hashes, an evidence ledger, a tested boundary primitive and a read-only validation command. No new forecasts or models have been created.

**CR1 is the next implementation:** certify forward base lineage; implement the three reliability estimators and fixed threshold blocks; validate on synthetic/bounded inputs; freeze code and forecast outputs; then score the registered historical comparison. It must provide run status, recovery and output-location instructions before a long run. A separate activation protocol is required before consuming prospective evidence.

Validation from this folder: use the existing modeling Python environment to run `validate.py`, or run the standard-library unittest discovery on `tests/`. The validator checks sealed implementation and parent hashes and registration boundaries without loading weather or truth data pages.
