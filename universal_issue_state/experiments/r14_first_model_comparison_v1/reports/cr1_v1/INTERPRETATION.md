# CR1 — implementation and first historical comparison

CR1 is implemented, tested and run. The twelve registered reliability fits and four native-confidence references were frozen before comparative scoring. The assessment contains **615 target days and 35,047 checkpoints**, covering 2024 and January 1–September 6, 2025. All compared models have the same complete support.

The existing [S6 registration](../../implementations/s6_v1/README.md) was sufficient to implement this stage. Subsequent research changes should be registered before fitting; they should not be improvised while reading new results.

## Main result

**This first reliability design does not meet the registered research-readiness requirements for either base model.** Keep the existing native probabilities as the reference. The experiment does not justify deploying these learned probabilities or gates.

| Base forecast | Native-confidence Brier | Confidence-only recalibration R0 | Confidence + calendar R1 | Weather-enhanced R2 |
|---|---:|---:|---:|---:|
| AnEn | 0.15389 | 0.15624 | 0.16158 | 0.16351 |
| Normal GAM | 0.15643 | 0.15730 | 0.15920 | 0.15871 |

Lower Brier is better: it rewards assigning accurate probabilities to both hits and misses. All three learned versions are worse than native confidence in the pooled assessment for each base model. This comparison concerns the probability of the base model's unchanged modal-integer hit; it does not change the underlying Tmax forecast or measure full-PMF log loss.

The primary question was whether the six weather coordinates add information beyond confidence, issue time and season:

- **AnEn:** R2 minus R1 Brier is **+0.00193**, with the adjusted seven-day interval **[+0.00106, +0.00289]**. Weather-enhanced probabilities worsened this registered historical comparison.
- **Normal GAM:** R2 minus R1 is **−0.00049**, with interval **[−0.00175, +0.00070]**. The small pooled improvement is unresolved and falls short of the registered 0.002 improvement hurdle. It is not an improvement over native confidence.

The intervals account for the two primary comparisons under the registered calendar-block procedure. They do not make previously inspected historical outcomes a fresh blind test.

## Why selected hit rates alone would mislead

The primary selector targets 25% of the earlier threshold block. It then uses that fixed threshold on the later assessment; realized coverage may change.

| R2 selector | Assessment | Actual checkpoint coverage, day-weighted | Exact hit | Predicted hit | Q baseline on identical cases | Admitted days |
|---|---|---:|---:|---:|---:|---:|
| AnEn | 2024 | 38.51% | 18.68% | 14.89% | 17.50% | 248 |
| AnEn | Partial 2025 | 2.30% | 33.13% | 24.03% | 32.21% | 71 |
| Normal GAM | 2024 | 11.54% | 24.84% | 35.52% | 24.14% | 108 |
| Normal GAM | Partial 2025 | 8.81% | 21.03% | 23.56% | 17.27% | 152 |

AnEn's 33.13% selected hit rate in 2025 looks attractive in isolation. But it retained just 2.30% of checkpoints, the baseline hit 32.21% on the same cases, and its forecast hit probability was not calibrated. That is not evidence of a useful incremental gate.

The GAM selector was substantially overconfident in 2024 and did not retain the minimum 10% checkpoint coverage in 2025. Its 2025 same-case baseline lift is an interesting descriptive result, but it does not override the failed probability-quality and coverage requirements. We do not replace the registered primary cutoff with a secondary one that happens to look better.

Checkpoint coverage and unique admitted days answer different questions. Many days may contribute only a handful of admitted checkpoints. Full uncertainty intervals, per-day admission counts and fold/season/issue summaries are retained in the machine-readable outputs.

## What this does and does not establish

The bounded, fixed-penalty additive logistic design did not produce sufficiently stable incremental reliability. That is evidence against this particular specification and training schedule. It does not prove that conditional forecasting is impossible or that every R14 weather feature is uninformative.

The first reliability fit uses only the first half of 2023 and stays fixed across its threshold and assessment periods. The later fit also remains fixed after its threshold period begins. Those registered choices protect the chronology but can leave limited seasonal training support and older relationships. Base-model versions also change across years. These are plausible explanations to investigate, not established causes, and they were not used to revise this run after scoring.

A sensible next decision is to compare a clearly registered adjustment to reliability-training history/update policy against the deferred distributional-tree route. Neither should start through an unrecorded parameter search. Prospective activation remains off, and no Kalshi bands, prices, fees or executions were analyzed.

## Verification and delivery

- Fourteen implementation tests passed, including a complete synthetic fit → prediction freeze → score → resume sequence and changed-file rejection.
- All eight inherited S6 timing-boundary tests remain unchanged from their passing release.
- Six bounded real-data engineering fits on 120 days converged; no skill conclusions were drawn from that probe.
- The lag-correct selection replay retained all eighteen saved base configurations. Primary base lineage covered 1,170 distinct referenced fit units, with shared training-date metadata verified once per unique content hash and selected outer artifacts checked. The original timing violation remains disclosed, not erased.
- Forty-six inherited dependency artifacts were checked against their releases. The completed CR1 prediction and score releases bind the published outputs to the implementation and registration.
- The full fit-and-freeze phase took approximately 88 seconds, dominated by data loading and verification. The sixteen fit/reference units together took about 2.46 seconds. Scoring took approximately 20 seconds. These are observed timings for this run, not guaranteed future durations.

Use the [implementation and launcher instructions](../../implementations/cr1_v1/README.md), [generated score report](../../runs/r14-cr1-20260927T030821Z/REPORT.md), [full probability scorecards](../../runs/r14-cr1-20260927T030821Z/RELIABILITY_SCORES.json), [Not bundled: selection results](../../../../../DATA_AVAILABILITY.md#not-bundled), and [every readiness check](../../runs/r14-cr1-20260927T030821Z/READINESS.json).
