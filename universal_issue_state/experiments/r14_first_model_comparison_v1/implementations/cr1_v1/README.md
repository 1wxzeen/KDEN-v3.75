# CR1 — conditional reliability implementation

CR1 implements the S6 registration: native confidence plus R0, R1 and R2 for AnEn and the normal location–scale GAM. It keeps the temperature PMFs and integer decisions unchanged. It estimates the probability that each base model's chosen integer is correct. There are twelve historical reliability fits and four unfitted reference units across the two registered blocks.

## Run without assembling terminal commands

Double-click **CR1 Launcher.command**. It uses the existing pinned modeling environment; no installation is required.

1. **Start historical fits and freeze predictions** creates a new run under the experiment's `runs/r14-cr1-…` folder. It validates inputs, certifies reuse of the base forecasts, loads issuance-safe predictors, fits the registered models and freezes all assessment predictions. It does not compute comparative assessment scores.
2. **Score latest frozen predictions** computes the registered comparisons only after every prediction unit is sealed. Read the resulting `REPORT.md`, `RELIABILITY_SCORES.json`, `SELECTION.json`, `PRIMARY_COMPARISONS.json` and `READINESS.json` together.
3. **Show latest status** reports the current phase and unit progress. During fitting, the displayed ETA covers remaining units only; it excludes the earlier lineage/feature-loading work and later scoring. No precise total ETA is claimed before those phases are measured.
4. **Request pause** asks the active fitting process to stop between completed units. **Resume latest run** clears that request and verifies/reuses completed units. Keep the terminal open. Ctrl+C interrupts immediately; completed sealed units remain reusable. An interrupted score calculation restarts from the frozen predictions.

Only one process may own a run folder. If code, registration or inputs change, use a new run folder. A failed fit stops the run with an explicit reason; there is no fallback or relaxed support criterion. The menu's latest-run actions name the latest timestamped run; the CLI permits an explicit output directory when managing older runs.

CLI commands are `validate`, `probe`, `certify`, `run`, `score`, `status`, `pause`, `resume` and `menu`. Supply `--output /absolute/run/path` except for validate/menu. `--experiment-root` is optional after installation. The launcher sets single-thread numerical execution.

## Chronology and lineage

Every fit uses only the registered fit dates and complete common support. Day weights give equal total weight to each eligible date. Means, standard deviations and dropped constants are computed from those fit rows only. Thresholds use the separate earlier threshold block with original expected-issue weights. All ties are admitted; assessment coverage is not forced to its nominal target. The same reliability coefficients score both threshold and assessment periods; there is no refit after threshold selection.

The reusable boundary component from S6 is invoked on fit and threshold dates. Base reuse first recomputes selection after excluding unavailable tuning dates, checks its equality with the saved configuration, verifies referenced score/unit records and shared training-date metadata, and verifies selected primary outer fit artifacts. Forecast keys, PMFs, expected issue counts and cutoff dates are checked when loading predictors. This certificate preserves the original S2/S4 timing nonconformance; it does not claim that the original runs followed the corrected procedure. It also does not exhaustively reread every discarded inner fit array.

No future observation, later correction to a predictor, year indicator, automatic feature search, probability recalibration of the full Tmax PMF, market listing or price is used. The six weather transformations are exactly those registered in S6. Inputs missing or invalid for any registered reliability model create common-support abstentions for all three models and both base forecasts; they still count against expected coverage. The pinned S4 base release has full availability. A changed or incomplete base release fails closed and requires an explicit support amendment, rather than being silently accepted.

## Evaluation details

The primary comparison is day-weighted binary Brier, R2 minus R1 separately for the two base forecasts, with paired seven-day calendar blocks, 5,000 replicates, and fourteen-day sensitivity. The adjusted intervals use 1.25th/98.75th percentiles. Other intervals are descriptive. S6's historical readiness hurdles are applied exactly, and every pass/fail check is recorded; these are not trading or blind-validation decisions.

Scores and calibration are reported overall, by assessment block, season and issue band. Selection outputs retain expected/available/admitted counts, checkpoint and day-weighted coverage, unique days, admissions per day, hit probability versus actual hits, same-case baseline hits, base tail errors and descriptive intervals. The primary 25% selector is never replaced by a secondary cutoff because its results look better.

Binary NLL uses a fixed reporting-only clip to [1e-6,1−1e-6]; native forecasts and Brier scores are unchanged. Calibration intercept/slope are descriptive assessment fits, never used to change predictions. Undefined single-class calibration or no-admission metrics remain null. The bootstrap matches the S5 implementation. Synthetic tests use a much smaller resampling fixture to test workflow wiring; real scoring retains all 5,000 registered draws.

## Validation and evidence

Fourteen tests cover analytic gradients, extreme logits, known intercept-only solutions, training-only standardization, serialization, weighting, support failure, negative log1p inputs, abstentions, threshold ties, prediction freezing before scoring, completed-run reuse and tamper rejection. The eight S6 boundary tests remain applicable and are unchanged.

The bounded real probe uses the first 120 eligible 2023 calendar days (6,836 checkpoints) for six engineering fits. All converged; maximum reported gradient norms were below 1e-6. It predicts the first half-year feature batch without computing model skill on its remaining outcomes. Probe convergence is engineering evidence, not evidence of predictive improvement. Saved probe files carry their exact implementation binding; final implementation tests and the published run are separately bound.

All historical outcomes are already development evidence. Reserved historical/tail outcomes remain inaccessible. Prospective collection remains inactive, and no trading claim follows from this implementation or its historical scores.

## Follow-on stages

No new broad planning document is needed: S6 is the scientific contract and this file describes its implementation. The full fit-and-freeze run and the subsequent score are separately controlled operations. After reviewing their results, any proposed CR2 research change must be recorded as an amendment before fitting; do not invent new candidates or thresholds as results arrive. Live prospective activation still needs the independently verified operational protocol required by S6.
