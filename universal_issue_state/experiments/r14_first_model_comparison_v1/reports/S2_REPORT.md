# S2 implementation and bounded validation

The hourly and subhourly R14 residual-distribution baseline workflow is implemented. The full historical baseline fitting/prediction run remains pending under the registered owner-run policy. S2's scientific exit—six complete frozen outer baseline partitions—is not yet achieved. No model-comparison or tradability result is claimed.

## Modeling decisions

Preserved all 12 registered settings per baseline: seasonal half-widths 45/60/90 days and Gaussian residual widths 0.75/1.25/2/3°F. These span the seasonal relevance/sample-size and probability-smoothing tradeoffs without a large exploratory search. Settings are selected by chronological inner day-weighted negative log score, on common feasibility support. Wider windows and then wider smoothing break numerical ties. Selected grid-edge settings are recorded for later investigation, without adaptive grid expansion in this experiment.

Both baselines fit exact-local-issue historical residuals and translate those errors onto the query's retained HRRR maximum. Raw centers, continuous corrected means, native integer distributions, pool size, effective sample size and residual moments remain separately available. Each day contributes at most one residual at each exact issue minute. No observations, inferred Kalshi band assignment, learned confidence gate or market prices enter the fit.

## Checks completed

- **80 tests passed**: all 61 inherited S0/S1 checks plus 19 S2 tests. Coverage includes seasonal wrap/leap days, exact-issue residual translation, missing inputs, 39-versus-40-day support, causal lag, probability integration, equal-day tuning, tie handling, inner truth access, corrupted checkpoints, atomic failure recovery and a synthetic complete 366-unit orchestration with resume and release validation.
- **Real-data small fit probe:** each baseline fit 89 eligible January–March 2021 days and generated 167 forecasts across three registered January–March 2022 dates, including spring DST. All forecasts were available, with 62–84 residual days. Accelerated/reference probability differences on the checked first row were approximately 2.78e-17. No assessment labels or accuracy scores were read/computed.
- **Bounded historical runner rehearsal:** two hourly candidate units each accounted for all 10,488 expected INNER_01 rows, with 627 valid PMFs and 9,861 explicit abstentions. The first unit remained unchanged after pause/resume. These pre-release temporary checkpoints are engineering evidence, not a production baseline release.
- **Feasibility finding:** INNER_01's shared hourly tuning support retained 11 of 184 days (5.98% day-weighted coverage), below the registered minimum. It was excluded before validation-label access. This is an expected consequence of attempting seasonal transfer from only the first half-year, not evidence to lower the minimum sample safeguard.

The three-day probe and the early, largely abstaining historical block are not representative full-run timing estimates. Later residual pools are larger. Status exposes observed unit timings and a provisional ETA; storage is several million 161-bin distributions, potentially multiple GB.

## Boundaries and remaining execution

No outer assessment accuracy was inspected. The source ledger contains development-era outcomes only; its single row group may be decoded internally by Arrow, while returned labels are restricted to authorized requested dates. No reserved/tail outcome source was read. All legacy S0/S1 release artifacts and the frozen universal substrate remain unchanged.

The runner seals each complete fit/prediction unit, verifies completed units on resume, rejects changed run identities, records pre-loss support decisions, and requires every registered candidate prediction before inner validation-label access. The full job produces 360 inner candidate partitions and six selected outer partitions. It seals the baseline release only after all expected units and supporting artifacts verify; insufficient tuning support fails without silently weakening the protocol. Comparative outer scoring remains deferred until S4's full model-comparison predictions are sealed.

See `../README_S2.md` for installation, start/status/ETA, safe pause/resume/recovery, validation and output locations. The implementation release is deliberately distinguished from the future `BASELINE_RELEASE.json`.
