# R14 boosted model comparison

Historical development evidence, not a fresh blind test. Both models correct raw Q HRRR Tmax. All six selected outer forecasts were frozen before comparison. The baseline score snapshots retain the disclosed original selection-timing violation; its excluded-date sensitivity selected unchanged settings.

| Model | MAE °F | Exact integer hit | Log loss | CRPS °F | Error ≥5°F |
|---|---:|---:|---:|---:|---:|
| XGB_QUANTILE | 1.959 | 17.71% | 2.3113 | 1.410 | 8.81% |
| NGB_NORMAL | 1.971 | 18.02% | 2.3301 | 1.425 | 8.63% |
| B0_H | 2.035 | 17.35% | 2.3901 | 1.493 | 9.20% |
| B0_Q | 2.037 | 17.41% | 2.3911 | 1.497 | 9.23% |

Identical comparison support: 55,848 of 55,848 expected checkpoints, 980 days. MAE uses the PMF median, exact hits use its modal integer, and scores weight days equally. Point/mean errors, intervals, signed tails, threshold and synthetic-band scores are retained in the machine-readable tables. Synthetic bands do not represent Kalshi listings.

## Paired primary comparisons

- XGB_QUANTILE − B0_H: NLL difference -0.07875; adjusted interval [-0.11554, -0.04209]. Negative favors the first model.
- XGB_QUANTILE − B0_Q: NLL difference -0.07984; adjusted interval [-0.11616, -0.04365]. Negative favors the first model.
- NGB_NORMAL − B0_H: NLL difference -0.05993; adjusted interval [-0.10188, -0.02175]. Negative favors the first model.
- NGB_NORMAL − B0_Q: NLL difference -0.06102; adjusted interval [-0.10378, -0.02254]. Negative favors the first model.
- XGB_QUANTILE − NGB_NORMAL: NLL difference -0.01882; adjusted interval [-0.04645, 0.01172]. Negative favors the first model.

Five primary comparisons use nominal approximate familywise 95% calendar-block intervals; fourteen-day sensitivity is included. Other intervals and slices are descriptive. No formal promotion or PnL claim is made.

## Read the whole result

[Scorecards](SCORECARDS.json) · [Not bundled: Calibration bins and their population coverage](../../../../../DATA_AVAILABILITY.md#not-bundled) · [Not bundled: All exact issue times](../../../../../DATA_AVAILABILITY.md#not-bundled) · [Primary intervals and sensitivity](PRIMARY_COMPARISONS.json) · [Support](SUPPORT.json)

Confidence bins are diagnostics, not gates optimized from these outcomes. Inspect periods and issue times before interpreting pooled accuracy. XGBoost quantile crossings are repaired by the preregistered rule; NGBoost normal scale guards are output safeguards. Per-forecast diagnostics and each saved FIT.json retain those modeling details. Neither these outcomes nor a failed run establish that HRRR is categorically useful or useless.
