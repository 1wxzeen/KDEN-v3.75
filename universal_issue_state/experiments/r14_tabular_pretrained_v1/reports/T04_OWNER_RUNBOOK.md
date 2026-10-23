# T04 — full development replay, scorecard and explicit recipe lock

Implementation is additive. Accepted T01–T03 source/configuration/receipts,
environments, checkpoint bytes, acquisition, truth and prefit releases are not
changed. All new outputs live inside this experiment. No legacy runtime imports,
HRRR reacquisition, holdout opening, T05 replay or model-recipe revision is done.

The owner explicitly chose **02:00–14:00 inclusive America/Denver as the primary
window during T04 implementation**. This overrides the earlier *proposed*
02:00–08:00 primary in the accepted planning README/config, which remain byte
immutable. `config/scoring_t04.json` records the additive override. 02:00–08:00
is now diagnostic; 02:00–16:00 is also reported. Ordinary primary days have 49
issue opportunities; spring DST days have 45. The unchanged full grid has 57/53.

## What runs

Development emissions: **2022-01-01 through 2025-09-06**, 1,345 days and 76,649
issue states; 2021 supplies initial training history, not primary evaluation.
45 monthly blocks × 57 exact issue minutes × 2 learners = **5,130 contexts**.
One neural process runs at a time. Seven neural arms plus H/Q point and residual
controls are preserved. T03's four sparse technical contexts are not calibration
seed history and are not substituted into this replay.

There are **7,822 restart units**: development predictor-only regime cutoffs,
5,130 native contexts, 1,345 forecast/correction days, 1,345 separately committed
verification days, and one scorecard. Each day is forecast-committed before its
truth accessor is enabled for scoring. Only emitted forecast histories—not
verification tables—train later corrections. Monthly/weekly clocks, strict
seven-day cutoff, native full-context/71-feature/8-view recipe and unsupported
warmup rules are unchanged. No custom lookback reduction or feature thinning.

T03 already proved order/batch invariance in real early and late contexts.
T04 uses its accepted prediction API without multiplying every monthly context
by extra singleton/reversal probes. Its native metadata does not falsely claim
a new per-context invariance measurement.

Full-history width likelihood is mathematically the T03 objective, summed in
512-row chunks with an experiment-local temporary quantile mapping. Native
shapes are loaded in file groups and cached in a bounded cache, never all neural
models at once. Baseline CRPS's exact translation-invariant pair integral is
cached per context. These are storage/evaluation optimizations, not statistical
approximations. Scratch mappings are removed after each completed/failed width
fit; an abrupt kill may leave a `t04-width-*` scratch directory. It is not a
published forecast or an accepted input. Do not delete broad cache directories.

T03's CPU measurements give a **native-only** development envelope of about
2.7–18.1 days. This is a wide early/late-context extrapolation, not a promised
T04 runtime: calibration, scoring, reporting and restart verification add cost.
The live estimate learns recent completed unit active costs. It never charges
paused wall time as throughput; slow in-flight units and growing calibration
history can still exceed prior samples. The final report/reverification is not
included in ETA. No long run has been executed by the implementation agent.

## Setup and start — owner terminal 1

Use the **already accepted experiment environment**. No pip reinstall, new
checkpoints or root package install is needed. Run each block separately; do
not paste pause/resume commands along with start. Blocks deliberately contain
no shell comment lines, avoiding interactive zsh comment errors.

```sh
cd "."
EXP="universal_issue_state/experiments/r14_tabular_pretrained_v1"
RUN_ID="kdenv375-t04-owner-full-development-v1"
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" check-t04
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-preflight
```

`check-t04` is bounded synthetic testing, not real inference. Preflight validates
accepted T03/T02/T01 receipts, local pinned runtime and prepared adapter bytes,
not the original large HRRR archive. It makes zero network requests and reads
zero holdout outcome pages. It does not start replay.

After READY:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" run-t04 --run-id "$RUN_ID"
```

Keep charger connected, lid open and use a separate terminal with `caffeinate -is`
if desired. Display brightness is immaterial. A native context/calibration fit
is an atomic unit and can take much longer than one status refresh.

## Monitoring — separate terminal

Variables are local to each terminal; repeat this setup in every new terminal.
You do not need to activate or reinstall packages there.

```sh
cd "."
EXP="universal_issue_state/experiments/r14_tabular_pretrained_v1"
RUN_ID="kdenv375-t04-owner-full-development-v1"
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-live-status --run-id "$RUN_ID" --interval-seconds 5
```

This prints append-only lines, never clears previous terminal output. Ctrl-C in
this monitor only stops the monitor. One-time checks, from a configured terminal:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-status --run-id "$RUN_ID"
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-eta --run-id "$RUN_ID"
```

## Pause / stop and resume

From another configured terminal, request a cooperative pause (stop is a synonym):

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" pause-t04 --run-id "$RUN_ID"
```

Wait for PAUSED; the in-flight unit finishes before pausing. Then:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" resume-t04 --run-id "$RUN_ID"
```

Resume verifies immutable identities/receipts/artifacts and rebuilds calibration
history from original committed emissions. It does not refit completed native
contexts or rewrite forecasts/scores. Resume can spend time verifying completed
outputs; this is owner-run work. A changed implementation/recipe/runtime refuses
mixed-history resume. If the original process was forcibly terminated, first
inspect status and its PID; recover *only a dead process's* lock:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" recover-t04-lock
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" resume-t04 --run-id "$RUN_ID"
```

Recovery removes only the stale lock; it removes no forecasts, inputs or history.
Do not issue concurrent replay/validation/locking commands while replay is live.

## After development PASS — owner-run validation

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" validate-t04
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-report
```

Full validation checks all experiment receipts and bound artifacts, native query
keys/clocks, forecast keys/coefficients, and recomputes the scorecard from daily
verification losses. It runs **no neural inference** and does not reread original
HRRR value archives, but it can be long: the owner runs it. Acceptance of score
definitions is backed by the bounded analytic tests; validate-t04 is integrity
and aggregation verification, not refitting or a second independent accuracy
experiment.

Reports distinguish complete-day and available-forecast denominators. True zero
support produces `"Infinity"` NLL, retained in averages; underflow with finite
log probability is counted separately. No floors or loss-row dropping. Brier
categories are the 161 display integer bins plus two unabsorbed outside-tail
categories; modal/band Brier are also supplied. Quantile-interval coverage uses
closed endpoints, explicitly retaining point atoms.

Strata are descriptive and overlapping: snow fraction >0, cloud fraction ≥0.5,
reflectivity≥20 fraction >0, and transition signals exceeding development-only
75th percentiles of absolute HRRR revision/14-day change. Missing predictors are
UNKNOWN. These are proxies, not a claim to diagnose specific meteorological
mechanisms. Cutoffs are computed only on 2022–2025-09-06 weather predictors and
included in the eventual lock; no holdout predictors or labels select them.
Month, meteorological season, exact minute, support and H/Q cycle-age slices are
included. All neural/Q and H-residual/Q comparisons use identical supported issue IDs; only the two flagship/Q contrasts belong to the predeclared inferential family. Separate
coverage tables retain all expected opportunities. The suggested candidate
uses the lowest complete-day NLL on common T3/D2/Q primary-window keys, then
mean MAE/name as tie breakers. **The owner still chooses after inspecting
accuracy, calibration, warmup, seasonality and cost.** Development scores are
not commercial returns or holdout verdicts. No bootstrap is run in T04; the
frozen scoring utility specifies T06's 5,000 calendar-block draws, seven-day
blocks and 14-day sensitivity, seed 3751010, 1.25/98.75 percentiles for the two
predeclared flagship-vs-Q NLL contrasts.

## Explicit recipe lock — only after review

Development PASS does **not** automatically lock or start holdout. Primary window
02:00–14:00 has owner approval. Numerical proposals still need confirmation:
modal hit ≥0.30, mean MAE ≤1.15°F, RMSE ≤1.70°F, integer NLL ≤1.85 nats,
≥300 complete holdout days, and support ≥95% of all primary opportunities.
These are future holdout decision limits, not development admission thresholds.

After inspecting the report, choose **one** candidate and supply a substantive
development-only rationale. The example below selects T3 solely as an example;
it is not a recommendation before evidence. Replace it with D2_NATIVE if that
is the actual choice. Running `--confirm-proposed-limits` explicitly approves
all numerical proposals; do not run it if you want different numerical limits.

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" prepare-t04-decision --candidate KDEN_TABICL_T3 --confirm-proposed-limits --rationale "OWNER: replace this text with the development evidence supporting this choice"
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" lock-t04 --decision-file reports/T04_OWNER_DECISION_APPROVED.json
```

Alternatively create your own experiment-relative JSON with the exact fields
of `config/decision_t04_proposal.json`, set `owner_confirmed` true, explicitly
set numerical limits/candidate/rationale, and pass its path to `lock-t04`.
Do not edit the immutable proposal/source/scoring config after replay begins.
The primary window cannot change after this release's development replay;
a different window/recipe requires a versioned development-stage revision.
The lock binds code, features, checkpoints/runtime, truth audit/date/availability
contracts, update rules, score definitions, thresholds, candidate, descriptive
cutoffs, comparison family and historical exposure ledger. T05 is a later
implementation; no holdout-opening command is supplied by T04.

## Artifact locations, relative to this experiment

- `manifests/T04_IMPLEMENTATION_CHECKS.json`: short test attestation.
- `manifests/T04_DEVELOPMENT_PASS.json`: completed development replay receipt.
- `manifests/T04_DEVELOPMENT_VALIDATED.json`: owner-run full validation receipt.
- `manifests/T04_OWNER_DECISION.json`, `manifests/T04_RECIPE_LOCK.json`: explicit
  approved decision and lock, absent until the owner locks.
- `runs/<RUN_ID>/identity.json`, `state.json`: immutable binding and live state.
- `runs/<RUN_ID>/units/native-*.json`: original laws, monthly contexts, timing.
- `runs/<RUN_ID>/forecasts/YYYY-MM-DD.parquet` and `.commit.json`: target-free
  seven-arm/H/Q forecast records and immutable forecast receipt.
- `runs/<RUN_ID>/history/YYYY-MM-DD.json`: original emitted scalar calibration
  histories, native-shape references and coefficient versions.
- `runs/<RUN_ID>/units/day-*.json`: preserved coefficient fits/diagnostics.
- `runs/<RUN_ID>/units/score-*.json`: physically separate verification losses.
- `runs/<RUN_ID>/units/regime-cutoffs.json`: predictor-only cutoff receipt.
- `runs/<RUN_ID>/units/development-scorecard.json`: full report, paired daily
  NLLs, support/warmup and descriptive slices, nominated candidate.
- `runs/<RUN_ID>/receipts/*.json`: atomic unit receipts and dependency chain.

Status/ETA are read-only and lightweight. Full development replay, complete
output validation, future holdout replay and future bootstrap are owner-run.
