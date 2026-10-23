# T03 — native laws, correction engine and bounded acceptance

T01 and T02 remain byte-immutable. T03 adds self-contained native probability
laws, the seven specified correction arms, separate H/Q point and empirical
residual-law controls, and chronological atomic publication/restart machinery.
No additional environment installation or checkpoint download is needed.

## What the owner runs now

This is **technical acceptance, not T04**. It tests both learners at 10:00 Denver
on January 1–2, 2022 and August 1–2, 2025: four context preparations, eight
native query predictions, plus extra reversal/singleton invariance calls.
The later contexts use all eligible earlier history, not a reduced sample.
They may take materially longer than T02's synthetic 180-day test. The agent
does not execute them. If capacity/inference fails, the run fails visibly;
there is no hidden device, feature, or context-size fallback.

Paste these setup lines in **every new terminal**. Shell variables are local to
that terminal; they are not installed by a Python package. Do not paste all
start/pause/resume commands together.

```zsh
cd "."
EXP="$PWD/universal_issue_state/experiments/r14_tabular_pretrained_v1"
RUN_ID="kdenv375-t03-owner-bounded-native-laws"
```

Short checks and network-free preflight (no inference):

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" check-t03
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" t03-preflight
```

Start in the original terminal:

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" run-t03 --run-id "$RUN_ID"
```

Append-only live monitoring in a separate terminal (no clearing old lines):

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" t03-live-status --run-id "$RUN_ID" --interval-seconds 5
```

One-time status or ETA:

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" t03-status --run-id "$RUN_ID"
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" t03-eta --run-id "$RUN_ID"
```

Pause/stop from another terminal; these are synonyms for cooperative pause:

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" pause-t03 --run-id "$RUN_ID"
```

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" stop-t03 --run-id "$RUN_ID"
```

The current native context/invariance or correction unit finishes first. No
partially computed unit is accepted. A heartbeat updates status every two
seconds even while native inference is busy. Cooperative pause may therefore
not be immediate. Keep the lid open, network is not required, and retain power.
If urgently interrupting, Ctrl-C in the original terminal is preferable; an
uninterruptible native call may require an owner-selected process signal. Inspect
the displayed PID rather than copying an old PID from another run.

Resume after PAUSED/FAILED or a dead interrupted process:

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" recover-t03-lock
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" resume-t03 --run-id "$RUN_ID"
```

Recovery refuses to remove a live process's lock. It removes only the small
stale T03 lock, not predictions, contexts, inputs, or checkpoints. Resume rechecks
T01/T02 acceptance, adapter hashes, the pinned environment/weights, T03 code,
configuration, run identity and completed unit/forecast bytes. Complete orphan
bundles can be verified and adopted; incomplete inference is recomputed. Never
manually edit a receipt to make an inconsistent run resume.

After PASS:

```zsh
"$EXP/.venv/bin/python" -B "$EXP/run_t03.py" validate-t03
```

Validation runs no inference, opens no holdout outcomes and rehashes only accepted
T02 adapter/runtime and the small bounded T03 output. It does not rescan HRRR's
original archive. No package reinstall is required per terminal; use the
**experiment** interpreter above, not the acquisition root's `.venv`.

## Artifacts (all inside this experiment)

* `config/replay.json`: exact fixed native/correction recipe and bounded scope.
* `manifests/T03_IMPLEMENTATION_CHECKS.json`: short synthetic test/code identity.
* `manifests/T03_PASS.json`: bounded acceptance; explicitly **not** a recipe lock.
* `runs/<RUN_ID>/identity.json`, `state.json`: fixed bindings and live progress.
* `runs/<RUN_ID>/units/native-*.json`: native shapes, context/preprocessing metadata,
  source IDs/clocks, baseline residual shapes and inference/performance timings.
* `runs/<RUN_ID>/receipts/*.json`: immutable unit commits and hash dependencies.
* `runs/<RUN_ID>/forecasts/YYYY-MM-DD.parquet` and `.commit.json`: target-free
  wide issue records with seven arms, H/Q controls and native-shape references.
* `runs/<RUN_ID>/history/YYYY-MM-DD.json`: scalar, originally emitted forecast
  histories and coefficient versions, without outcomes or accuracy columns.
* `runs/<RUN_ID>/units/day-*.json`: original monthly/weekly coefficient versions.
* `runs/<RUN_ID>/units/performance-report.json`: time/RSS observations and clearly
  qualified native-only workload projections.

Each `prediction_json` contains full-law mean, median, modal integer, exported
integer masses -40..120, outside tails, interval endpoints and law transforms.
The raw quantile/histogram shape is resolved from `native_references` only after
checking its hash. An arm is `shift_f + scale * RAW_SHAPE`; its Q05 anchor was
already added once in RAW_SHAPE. H/Q kernel references instead contain residual
centers: add that query's respective raw anchor once. Display bins do not truncate
the laws. Source provenance includes init/availability/physical support clocks.

The forecast files contain **no query labels or outcome-based losses**. Context
residuals encode authorized earlier outcomes as training information, not query
truth. Future scoring must happen through the separate committed-forecast truth
gate. Holdout truth remains closed; no T03 option opens it.

## Corrections and scientific safeguards

Monthly location learns actually emitted RAW; weekly center learns actually
emitted supported T1/D0; T3 width learns supported TRANSITION with preserved T1
shape. The exclusive date cutoff, 90-day recency, per-day weights, 90-day overall
and 60-day exact-minute warmup, no-intercept center ridge and width optimizer
match the accepted plan. Missing correction weather uses earlier-fit imputation
and explicit flags. Future/query labels cannot enter contexts or coefficient
fits. New coefficients never rewrite old controls.

The sparse bounded probe cannot warm up these learned corrections: identity
fallbacks are explicitly **unsupported**, not successful calibrated forecasts.
Synthetic tests exercise supported fits/weights/optimizer errors/width guard.
The 2021 period remains initial neural context; honest correction histories begin
with the full 2022 development replay. Probe emissions must never seed that replay.

The engine preserves exact rounding-boundary atoms, genuine zero-probability
NLL, stable remote log mass, native tails/within-bin variance, and one-anchor
residual inversion. Constant contexts produce point masses, not fabricated spread.
Model/library, malformed input, optimizer and numerical-guard failures stop the
unit. There is no neural weight fine-tuning, no uncertainty inferred from eight
point forecasts, and no Gaussian replacement for native laws. Gaussian kernels
appear only in the predeclared empirical baseline controls.

The heartbeat's ETA is **for this bounded run** and uses recent completed-unit
active costs. It is unavailable until each remaining cost class is measured.
Performance-report projections multiply measured early/late costs by enumerated
native contexts/query counts; they exclude learned correction fits, scoring,
later-context memory effects and unknown cache/device variation. They are not a
guaranteed full-study finish date or proof that 2026 contexts will fit memory.

## Boundary after T03

PASS + VALID makes T04 implementation/development replay the next action.
T03 does not run T04, select a model, finalize RMSE/NLL/support limits, audit/open
holdout labels, or authorize holdout fitting. The full development scheduler is
enumerated and reusable internally, but no full-replay CLI is exposed here.
T04 must add scoring/recipe-lock owner controls and authorize its long run.
