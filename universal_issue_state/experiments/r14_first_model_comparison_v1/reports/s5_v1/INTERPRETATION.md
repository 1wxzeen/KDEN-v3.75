# S5 — what the completed comparison tells us

S5 is complete. Start here for the interpretation, then use the [full scorecard](../../runs/r14-s5-20260927T024658Z/REPORT.md) for definitions, plots, uncertainty, all weather slices and case studies. These are previously inspected historical development periods, not a new blind test. No model was refitted and no trading strategy was evaluated.

## What transferred

AnEn and the location–scale normal GAM both improved average probability forecasts over both baselines. Their pooled log-loss reductions are approximately 0.06 nats, and all four registered model-versus-baseline comparisons retain negative intervals under both seven- and fourteen-day block resampling with the five-comparison adjustment. The direct normal-GAM-versus-AnEn interval includes zero; this score does not establish a winner between them. Statistical separation from a baseline is not a registered practical promotion decision or evidence of trading profits.

| Model | MAE °F | Exact-integer hit | Log loss |
|---|---:|---:|---:|
| Hourly baseline | 2.035 | 17.35% | 2.390 |
| Subhourly baseline | 2.037 | 17.41% | 2.391 |
| AnEn | 1.948 | 18.14% | 2.325 |
| Location–scale normal GAM | 1.959 | 18.68% | 2.329 |
| Constant-scale GAM | 1.971 | 17.80% | 2.416 |
| Student-t GAM | 1.965 | 18.64% | 2.309 |

AnEn's MAE and log-loss gains over the subhourly baseline appear in each of the three assessment periods. Its exact-hit gains do not: in the partial 2025 period, AnEn hits 15.56% versus the baseline's 16.76%. AnEn can improve the distribution and typical error without improving its most likely integer.

The normal GAM's exact-hit rate exceeds the subhourly baseline in all three periods: 17.15% versus 15.69% in 2023, 19.72% versus 19.56% in 2024, and 19.38% versus 16.76% in partial 2025. These annual differences are descriptive, not separate multiplicity-adjusted discoveries. The very small 2024 difference and the selection failures below prevent claiming uniformly strong precision.

## Higher confidence helps in aggregate, but its reliability does not transfer consistently

The strictest registered rule targets the most confident 10% of earlier inner forecasts. Its cutoff is carried forward; actual assessment coverage is allowed to differ. Coverage below is the day-weighted share of checkpoints, not the share of days on which any trade would be possible.

| Model | Actual pooled coverage | Selected exact hit | Q baseline on identical cases | Mean predicted hit | Days with admissions |
|---|---:|---:|---:|---:|---:|
| AnEn | 10.29% | 25.20% | 22.68% | 23.46% | 479 |
| Normal GAM | 5.88% | 27.74% | 26.00% | 28.87% | 235 |
| Student-t GAM | 5.73% | 28.92% | 25.05% | 33.01% | 282 |

Part of the higher selected accuracy comes from selecting easier cases: the baseline also improves substantially on those same checkpoints. The residual differences are much smaller than comparing selected model accuracy with an unrestricted baseline. Different model selectors also select different cases, so the table is not a controlled ranking of their selected performance.

The pooled picture hides a serious annual weakness:

| Strictest selector | 2023 selected hit | 2024 selected hit | Partial 2025 selected hit | 2025 predicted hit | 2025 coverage | 2025 admitted days |
|---|---:|---:|---:|---:|---:|---:|
| AnEn | 21.81% | 35.20% | 16.68% | 22.97% | 6.97% | 128 |
| Normal GAM | 28.07% | 32.42% | 16.18% | 28.08% | 4.31% | 55 |
| Student-t GAM | 27.61% | 36.21% | 17.60% | 31.83% | 4.40% | 73 |

The normal GAM's 2025 selected hit rate is actually below its unrestricted 2025 rate of 19.38%. Its 55-day subset also falls below the registered 60-day slice threshold. This does not prove that selection can never work; it demonstrates why pooled precision is insufficient evidence for a deployable confidence rule. The partial 2025 period also has a different seasonal composition, so the annual comparison alone does not identify the cause. Fold, season and issue-time tables should be read together.

These are aggregate point estimates, with descriptive block intervals retained in the machine-readable selection output. The report does not claim that every apparent difference is statistically resolved, and it does not optimize replacement thresholds using these outcomes.

## What each diagnostic adds

- **Baselines:** similar pooled performance, but high native confidence is not consistently trustworthy. The strictest Q-baseline selector in partial 2025 admitted 3.86% of checkpoints across 64 days, predicted a 25.49% hit rate and achieved only 5.47%. A pooled near-calibration result can conceal a large local failure.
- **AnEn:** its distribution and average-error gains transfer more consistently than its exact-integer precision. Analog-distance and effective-neighbor slices are available for hypothesis development, but they do not validate a learned reliability rule.
- **Normal GAM:** the strongest pooled primary-model exact-hit rate, with useful overall confidence ordering, but a clear weakness in the most confident 2025 subset. This makes calibration stability an explicit research target.
- **Constant-scale GAM:** lower pooled MAE than the baselines but worse pooled log loss. Its strictest integer-confidence threshold admitted no outer checkpoints. Low point error alone does not establish useful uncertainty or adequate opportunity.
- **Student-t GAM:** the lowest pooled log loss of these six models, but it is a registered diagnostic rather than a silently promoted replacement. Its strictest pooled subset is overconfident, and its 2025 selection also underperforms its advertised probability. A heavier-tailed distribution does not solve reliability automatically.

The nine physical regime comparisons, GAM effect curves and deterministic hit/miss cases help formulate explanations. They are exploratory, overlap in their weather conditions and involve many comparisons. They do not yet establish that a particular weather feature predicts deployable precision. GAM effect curves show fitted relationships, not causal mechanisms or coefficient confidence bands.

## Timing qualification and verification

S5 found a procedure violation missed in the earlier S4 review: December 31 tuning outcomes were included when selecting a January 1 model despite the declared two-day label lag. Outer model fits respected the lag. Excluding the late date leaves **all 18 model/vintage configurations unchanged**. Frozen models and forecasts were preserved. This sensitivity substantially limits the apparent impact here, but it does not erase the violation; the selection boundary must be corrected and tested before successor fitting.

The numerical report reproduced the earlier diagnostic's pooled MAE, exact-hit, CRPS and log-loss values. Twelve focused tests passed for calendar resampling, missing dates, weighting, empty admissions, threshold ties, training-only regime boundaries, calibration and the distinction between integer and band hits. The completed report's 152 sealed artifacts were verified, and representative selection/effect figures were visually reviewed. S5 numerical analysis took approximately 6.6 minutes; the complete delivery includes 122 figures. The original modeling environment and frozen S0–S4 artifacts were preserved.

## Bounded recommendation for S6

First repair the selection-label timing boundary in a successor implementation. Then prioritize a small, chronologically evaluated reliability experiment asking whether issuance-time conditions add information beyond the model's own probability, season and issue time. Its target should include both hits and misses, and its evaluation should emphasize future-period calibration, same-case baseline comparisons and actual coverage. It needs base forecasts selected using only information available at their historical issuance, with separate chronological development and evaluation for the reliability model itself.

Keep one distributional tree challenger as the alternative model-development route, with a bounded feature and tuning plan. The present findings do not justify an unrestricted parameter search, many weather gates or a complex mixture of experts. S6 should register which experiment goes first, its success criteria and its prospective evidence budget. None is registered or run by this S5 delivery.

Exact hits remain distinct from hits on actual listed bands. Fixed two-integer partitions in the scorecard are diagnostic only. Tradability still requires contemporaneous prices, actual contracts, fees and execution assumptions; S5 supplies no PnL claim.
