# S1 completion report

Date: 2026-09-25  
Experiment: `R14_FIRST_MODEL_COMPARISON_V1`  
Status: **S1 COMPLETE — ready for S2 baseline implementation**

## Result

Implemented the shared development loader, probability and scoring primitives, explicit-band aggregation, forecast record schema and immutable partition manifests. All original S0 artifacts remain byte-identical. The new S1 contract supplement records the user's band clarification and the safe development-truth accessor.

No weather models were fitted, no real model comparison was scored, and no reserved or tail outcome source was read. The numerical modeling environment was not modified or installed.

## Kalshi band clarification

A realized maximum of 92°F does not determine a corresponding 91–92°F or 92–93°F market band. S1 never makes that inference. Its fixed two-integer and five-degree partitions are synthetic diagnostics, explicitly named `synthetic_*`. The generic probability aggregator requires supplied boundaries. Tests demonstrate that a PMF with masses 0.2 at 91°F, 0.5 at 92°F and 0.3 at 93°F assigns 0.7 to a supplied 91–92°F interval and 0.8 to a supplied 92–93°F interval. The realized integer cannot select which contract was listed.

Actual market-band mapping remains a later task using actual listing metadata and rules. No claim is made that parity, outcomes or a learned listing pattern reconstructs historical/live markets.

## Loading and access checks

The loader:

- verifies every input file used against recorded hashes;
- inherits target-day folds and applies the two-day label lag;
- rejects unresolved, reserved, tail and out-of-fold requests;
- returns predictors separately from labels and provenance;
- joins by exact issue identity and checks statistical groups and timestamps;
- verifies the DST-safe issue grid and fixed 07Z climate-day window;
- verifies selected and previous-cycle availability, without selecting new cycles;
- validates feature bounds with the accepted P06 corrections;
- preserves missing inputs as unavailable model rows, with specific missing-feature reasons;
- supplies equal-day training weights and complete input hashes for later fit lineage.

The mixed truth catalog's outcome column is never read. Catalog role/source metadata authorizes the hash-bound audited development ledger, whose `y_audited_f` is the value copied into the catalog by the frozen P02 builder. Only requested training labels are returned. The ledger has no reserved/tail dates, although its single row group also contains older development-era values that Arrow can decode internally. This implementation detail and evidence boundary are explicit in the supplement and README.

## Scoring foundation

Implemented integer PMFs with endpoint accumulation; stable normal and residual-kernel probability masses; deterministic mean/median/mode and rounding; explicit interval and band probabilities; NLL with the frozen reporting-only probability floor; discrete CRPS/RPS; multiclass/threshold/band Brier scores; named-point errors; exact/near hits; tail-miss indicators; native confidence and entropy; interval coverage/width; and deterministic randomized PIT.

Aggregation includes equal-day metrics, correct RMSE aggregation, weighted absolute-error quantiles, key-checked common support, fixed-bin reliability, training-threshold primitives, and selection coverage with explicit unavailable forecasts and no-admission nulls. A separate outcome-free forecast schema carries model/fold/training/input lineage and explicit abstentions. Prediction partitions reject missing/duplicate expected keys and changes to their committed contents.

The primitives do not themselves assemble the full future report, run bootstrap inference or validate the chronology of arbitrary arrays supplied by a caller. Later runners must enforce the frozen experiment protocol and score only prediction sets committed at the required stage.

## Verification

**61 tests passed:** 13 unchanged S0 tests plus 48 S1 tests. New tests cover hand-calculated probability scores, tails, rounding, distinct point summaries, interval/band semantics, both synthetic alignments, equal-day weighting, no-admission behavior, common-support key alignment, missing inputs, forbidden dates, lag exclusions, future-cycle rejection, hash mismatches, catalog/source binding, prediction lineage, write-once output and tampering.

A bounded real-data probe checked four training dates: 2021-01-20, 2022-04-18, 2023-03-12 and 2024-11-03. Each of the four primary model input sets loaded 224 issue states with no missing required features on these dates. The spring DST date contributed 53 issues; the other dates contributed 57 each. Four unique audited training labels were joined and returned across 224 issue rows; their values were not printed or persisted in probe reports. No real forecast losses or hit rates were computed.

The probe logs exact projected columns and requested dates. It rejects any projection of the catalog target column or target read from a source other than the audited development ledger. It is representative verification, not a full-history feature/value scan or evidence of model performance.

## Next step

S2 constructs the R14 hourly and subhourly baseline residual distributions and commits their inner/outer forecasts. S1 provides the common loader and numerical score definitions; it does not supply an already fitted baseline, AnEn or GAM.
