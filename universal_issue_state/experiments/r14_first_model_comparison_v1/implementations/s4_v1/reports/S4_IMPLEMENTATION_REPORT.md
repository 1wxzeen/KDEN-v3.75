# S4 implementation and verification

Status: **implementation complete; full historical nested run pending owner execution**. No S4 comparative outer scores or commercial results are claimed.

## Delivered behavior

- Reuses the frozen S3 AnEn and three GAM implementations and all 208 candidate settings. No changes to scientific feature choices, smoothing grids, lag, training-only transformations, optimizer settings, or probability conventions.
- Uses seven unique inner periods instead of refitting identical periods for each outer vintage. Checks date-population equality before reuse. Twelve selected outer model/vintage partitions join six already-frozen S2 baseline partitions in the final release.
- Freezes target-free common family support before assessment labels. Excluded blocks have explicit sealed decisions and no assessment losses. A model requires two supported inner blocks.
- Restricts the inner-label accessor to the full registered family, sealed candidate dispositions, authorized development source and exact assessment dates. No outer-label accessor exists in S4.
- Selects on equal-day negative log score and declared smoothing-favoring ties. Invalid solver settings are excluded as whole candidates, without removing hard rows. Failed optimizer diagnostics preserve nonfinite values explicitly as strings; numeric probabilities and scores may never be nonfinite.
- Provides resumable atomic checkpoints, exclusive run locking, retained fitted states, code/environment bindings, logged status and a menu launcher. AnEn training artifacts are shared with hard links; parameter-specific identities and predictions remain separate.
- Emits all expected outer keys even for unsupported models, using explicit abstentions and a visibly qualified release status. Covers both per-model and common primary-model support without outcome filtering.

## Tests

21 automated tests passed. They exercise common-support parity with native AnEn forecasts, missing/constant predictors and empty complete training populations, unequal-day weighting, declared ties, invalid configurations, population mismatches, reporting-floor renormalization, complete-registry enforcement, authorized inner truth and rejected reserved metadata, forbidden outer access, disk/publication failure, corrupted checkpoints, changed run identity, optimizer failure including nonfinite diagnostics, outer abstention publication, saved-fit restoration, key alignment, bounded pause/resume, shared inner reuse, shared training files, insufficient tuning support, and final release support/key accounting. Several tests cover multiple checks.

The synthetic workflow completes two outer vintages, then resumes a second time with no new fitting or assessment reads. The release test also rejects a deliberately changed forecast key.

## Bounded real-data evidence

1. Four sparse-calendar engineering fits used 122 training days and 167 assessment issue rows each. AnEn, location–scale normal GAM, constant-scale normal GAM and location–scale t5 GAM all saved valid forecasts and passed checkpoint verification and no-refit reload. Assessment outcomes were not read. These are engineering probes, not model scores.
2. The real workflow was invoked twice, with each invocation capped at one new candidate. It excluded INNER_01 for AnEn using the target-free intersection across the registered grid: 0 of 184 days met common support. This does not mean every smaller-k setting has zero predictions; the comparison must use support shared with the hardest registered setting.
3. INNER_02 had 180 eligible target days, 10,256 expected issue rows, and 10,248 common available rows (99.922% day-weighted coverage). Two registered candidates were saved. The second invocation verified and retained the first checkpoint byte-for-byte and added exactly one candidate. Hard-linked training data were confirmed.
4. Both invocations paused before any candidate-family scoring, so no inner assessment or outer outcomes were read by the real rehearsals. The first candidate took 25.54 seconds to fit/publish after loading; the second took 23.06 seconds. These are small-k AnEn timings, not an end-to-end ETA. One candidate's forecast file was about 20.8 MB, so planning for tens of GB is appropriate for the full candidate archive even with shared training artifacts.

The real rehearsals were disposable `/tmp` runs under a pre-report implementation seal. Final hardening independently enforces the full candidate registry at the inner-label boundary, checks completion counts before release publication, excludes empty complete training populations, and serializes failed optimizer diagnostics safely. The final code passed the test suite. The temporary probe runs are not production runs and must not be resumed against the final release identity.

## Remaining scientific work

Owner execution must complete the historical run to produce `COMPARISON_RELEASE.json`. Until then, there are no selected S4 generalist models or complete comparative forecast release. A qualified release containing unsupported models is an accounting result, not evidence that every model generalized. S5 will evaluate performance, calibration, coverage and regime transfer on the frozen forecasts. Earlier S2 outer-outcome exposure remains documented; the historical comparison is development evidence. Market execution and PnL remain separate later work.
