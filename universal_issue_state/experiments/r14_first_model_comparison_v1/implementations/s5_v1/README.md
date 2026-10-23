# S5 — frozen scientific scorecard

This implementation reads the completed S4/S2 forecasts and produces the registered historical development scorecard. It does not fit models, train gates, calibrate probabilities, open reserved labels or access markets.

The separate `.venv-s5-report` plotting environment contains matplotlib 3.10.6 and numpy 2.0.2; the original pinned modeling environment is unchanged. If recreating it, create that environment under the experiment root and install those two pinned packages. Numeric analysis uses `.venv-models`.

Double-click **S5 Launcher.command** for a new report, resume or status. A full statistical report can take several minutes or longer, including 5,000 paired bootstrap replicates, all registered slices, confidence policies and figures. Progress is written to `status.json` and printed in the terminal. Keep the terminal open. Ctrl+C interrupts safely; resume the same folder through the menu. Incomplete numeric analysis restarts from frozen inputs (never from model training); a completed, hash-verified analysis is reused when rendering/reporting is retried. Implementation changes require a new folder. The launcher refuses a second writer.

Outputs include REPORT.md, scientific PNG figures, full row scores, machine-readable scorecards with counts and uncertainty, paired seven-/fourteen-day bootstrap inference, reliability, selection coverage with same-case baseline scores, immutable threshold sources, physical regimes, GAM effects, deterministic case studies, operations and a final SCORECARD_RELEASE.json. `status=COMPLETE` means the report is complete; consult the release and timing audit for scientific qualifications.

## Timing qualification discovered during S5

S2/S4 model selection included the previous December 31 label for a January 1 outer vintage despite the declared two-day label lag. Outer model fitting applied the lag correctly. S5 explicitly audits the excluded-date sensitivity for every model/vintage without overwriting any selected configuration or forecast. The final report records whether selections change. A timing nonconformance is still disclosed even when choices are unchanged. Correct this before successor fitting; do not describe the original workflow as an exact replay of its stated timing rule.

## Statistical definitions

The sealed S0 contract supplies 5,000 seven-calendar-day paired noncircular moving-block bootstrap draws within fold, seed 3750925, with a fourteen-day sensitivity. Missing calendar slots stay missing; each fold retains original eligible-day mass. The five primary NLL contrasts use .005/.995 quantiles for nominal approximate familywise 95% intervals. Other intervals are descriptive .025/.975 quantiles. No finite-sample coverage guarantee or formal promotion is claimed. An undefined bootstrap ratio is missing, not zero; intervals require at least 95% finite draws.

Regular score tables weight target days equally and issues equally within each reported day. Selective tables preserve population day/issue weights before restriction and separately report equal-admitted-day accuracy. All ties at a training-derived threshold are admitted, so actual outer coverage can differ from its target. No thresholds are derived from outer ranks. Confidence selection on earlier base-model-tuning predictions is a diagnostic, not independent reliability-model training evidence.

Nine registered physical slices use eligible training predictors only. AnEn diagnostic quartiles are explicitly operationalized after earlier outcome exposure and remain descriptive. Source eras are unknown without independent documentation. Raw HRRR states are model forecasts, not observed temperatures. Synthetic pair partitions in either alignment are not actual or inferred Kalshi bands.

Sparse slices (<60 days) and reliability bins (<30 days, per frozen calibration contract) are flagged. Exact issue × fold tables contain support and point estimates; broad strata contain bootstrap intervals. Extensive slice comparisons do not inherit the five-contrast familywise protection.

Historical fit/predict unit durations exist, but their separate components and historical peak memory were not recorded. GAM effects have no coefficient uncertainty bands because no coefficient covariance/refit bootstrap was saved; the report states this limitation instead of fabricating intervals.

`config.json` binds the exact inputs and exposure record. The prior small diagnostic headlines are reproduced as an integration check. Training-label timing findings, historical outcome exposure and this stage's new interpretation remain visible in the resulting evidence record.
