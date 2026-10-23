# S3 implementation result

S3 is implemented and ready for S4 integration. No full-history candidate selection or AnEn/GAM outer-performance evaluation was run in this stage. The existing S2 baselines and early diagnostic report remain unchanged.

## Scientific implementation

- Generalist AnEn uses ten physically motivated R14 coordinates in six equally weighted groups. It retains 850-mb temperature and its surface contrast following the D1 evidence and user clarification; it does not assume every pressure-level value is a directly observed above-ground mixing diagnostic.
- Location–scale GAM uses the same ten physical coordinates for location correction, plus issue time, cyclic season and cycle-age/DST terms. Scale varies with heating potential, mixing depth, forecast-product difference, forecast revision, issue time and season.
- The constant-scale Gaussian GAM and fixed Student-t(5) distributional GAM are implemented as registered diagnostics.
- Stable integer-bin likelihoods, analytic gradients, train-only preprocessing, saved fits, native PMFs, explicit abstentions and the common S1 forecast schema are implemented. AnEn reference-distance diagnostics leave out the candidate's own day.
- The declared candidate count is 208: AnEn 180; primary GAM 12; constant-scale diagnostic 4; Student-t diagnostic 12. They have not been ranked or selected in S3.

## Validation

**23 S3 tests passed** in approximately 2.4 seconds. They cover:

- Independent normal-PMF parity and Student-t normalization.
- Analytic likelihood and complete penalized-objective gradients against central finite differences, including extreme tails and endpoint bins.
- Physical-group weighting, robust-scale fallbacks, constant-coordinate behavior, deterministic ties and equal zero-distance weights.
- Minimum pool size and infeasible requested neighbor counts; missing-input abstentions and causal day separation.
- Training-only basis behavior, valid fits for all three GAM variants, recorded all-start solver failures, and constant-scale architecture.
- No-self reference neighborhoods, no duplicate training day/issue rows, and equal-day weights.
- Exact save/restore prediction parity for all four models, unit atomic publication/no-overwrite, and S3 feature transformations.

**Bounded real-data probe:** 122 eligible 2021 dates selected by a fixed calendar rule (day offset divisible by three), 6,950 training rows per model. All required features were present in that probe. Prediction dates were 2022-01-20, 2022-02-20 and 2022-03-13, including spring DST. Each of the four models emitted 167 available forecasts; all passed the S1 prediction schema and PMF checks. No assessment labels were read or scores calculated.

| Model | Total probe seconds, including load/fit/publish checks | Solver result |
|---|---:|---|
| ANEN | 6.65 | Deterministic analog construction |
| GAM_LS_NORMAL | 7.12 | All 3 starts accepted; 140–148 iterations |
| GAM_LOCATION_NORMAL | 6.36 | All 3 starts accepted; 59–70 iterations |
| GAM_LS_T5 | 10.75 | All 3 starts accepted; 120–122 iterations |

Every accepted real-data GAM start finished with maximum absolute objective-gradient component below 1e-6, tighter than the registered 1e-4 acceptance limit. The probe uses fixed engineering parameters, not winners selected from outcomes. Its training objectives must not be read as model-comparison evidence. These times are not a full-history or full-grid runtime forecast; larger analog pools and more fit candidates materially change costs.

The probe was conducted before the final documentation and operational-helper seal. The numerical model and feature implementations used in it were retained; additional serialization, atomic-unit and operational checks were completed with synthetic tests. The final implementation release is distinct from a full fitted-model comparison release.

## Interpretation and remaining work

A well-converged GAM is not necessarily a good forecast. Gaussian/Student-t GAM distributions are symmetric and unimodal, whereas the analog mixture can represent asymmetry/multiple modes. Neither architecture guarantees exact-integer precision, reliable confidence, or market edge. AnEn's grouped metric is a physical prior; it still needs empirical testing on chronological validation blocks. D1's mostly-sunny results motivate the 850-mb feature but do not establish all-weather/all-issue transfer.

S4 must implement/run the full nested tuning and combined prediction release using the registered day-grouped support, lag, candidate-failure and tie rules. The old S2 baseline forecasts should be referenced, not regenerated. Subsequent comparisons must acknowledge both the inspected baseline outcomes and the prior D1 reference results. No fresh blind-test claim is available for those overlapping periods.

Read [DECISIONS.md](../DECISIONS.md) for physical reasoning, exact model assumptions and source references. Read [README.md](../README.md) for operation, bounded probes, the single-candidate API and the limits of its stop/recovery behavior.
