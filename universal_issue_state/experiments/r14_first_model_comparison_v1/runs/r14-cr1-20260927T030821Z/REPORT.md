# CR1 historical reliability results

Development evidence only. All predictions were frozen before this comparative score was computed. S2/S4 original timing nonconformance remains disclosed; reused base configurations matched lag-correct selection. No temperature PMFs or market prices were changed.

| Base / reliability | Binary Brier | Binary log loss |
|---|---:|---:|
| ANEN/NATIVE | 0.15389 | 0.48543 |
| ANEN/R0 | 0.15624 | 0.49390 |
| ANEN/R1 | 0.16158 | 0.52351 |
| ANEN/R2 | 0.16351 | 0.53601 |
| GAM_LS_NORMAL/NATIVE | 0.15643 | 0.49191 |
| GAM_LS_NORMAL/R0 | 0.15730 | 0.49395 |
| GAM_LS_NORMAL/R1 | 0.15920 | 0.49925 |
| GAM_LS_NORMAL/R2 | 0.15871 | 0.49879 |

Lower scores are better. Primary contrasts are R2 minus R1; the paired intervals adjust for both registered base-model comparisons.

- ANEN: Brier difference 0.00193; adjusted seven-day interval 0.0010639883007479837 to 0.0028917890585896276. DOES_NOT_MEET_ALL_HURDLES.
- GAM_LS_NORMAL: Brier difference -0.00049; adjusted seven-day interval -0.001749803782351949 to 0.000703597997802695. DOES_NOT_MEET_ALL_HURDLES.

[Full scores and calibration](RELIABILITY_SCORES.json) · [Not bundled: Selection, counts and same-case baselines](../../../../../DATA_AVAILABILITY.md#not-bundled) · [Primary comparisons and sensitivity](PRIMARY_COMPARISONS.json) · [Every readiness check](READINESS.json)

Calibration intercept/slope are descriptive assessment fits and never modify forecasts. Binary log scores clip probabilities to [1e-6,1−1e-6] for reporting only. Undefined metrics remain null. Secondary comparisons are descriptive; no search for an alternative passing cutoff is allowed. Native, R0, R1 and R2 selectors can select different cases. Prospective reservation remains inactive and tradability is untested.
