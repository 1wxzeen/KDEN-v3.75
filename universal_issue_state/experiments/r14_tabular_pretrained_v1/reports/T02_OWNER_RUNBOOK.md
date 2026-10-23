# T02 — model feature adapter and pinned environments

T02 adds a modeling view and an isolated pretrained-model environment. It does
not change the universal substrate, original truth package, accepted T01 files,
study dates, or the 365-day holdout. It does not perform development replay,
forecast scoring, model selection, corrections, or recipe locking. Those are
later stages. Holdout weather is transformed, but holdout truth pages stay closed.

All new persistent files live inside
`universal_issue_state/experiments/r14_tabular_pretrained_v1/` in KDEN v3.75.
Neither the KPHX environment nor the acquisition environment is reused or changed.
The entry point is **run_t02.py**, separately added because **run.py and the
README are accepted T01 artifacts and must not be edited**.

## What the adapter does

The immutable configuration `config/features.json` implements the README's exact
34-field whitelist, in order. It converts absolute Kelvin temperatures to °F,
temperature differences and rates by 1.8, snow/cloud percentages by 100, and
leaves the other quantities in their declared units. The source registry labels
endpoint slopes K/m; the original P04 formula divides by elapsed hours. The new
names explicitly express those rates. No archived physical-range errata are
"repaired" or statistically clipped by this adapter.

The model inputs are 34 values, their 34 missing flags, annual sine/cosine using
the actual 365/366-day year, and the issue spine's DST flag: **71 columns**.
One weather day contributes at most one row to an exact-local-minute context.
The 105-minute rule means hourly HRRR cycles are usable after init+105 minutes;
it does not mean that initialization occurs every 105 minutes.

The raw Q05 retained maximum, converted to °F, is the primary residual anchor.
If absent or nonfinite, the state is retained with explicit native abstention.
It is never imputed or replaced with H16. Unexpected nonfinite ancillary values
fail acceptance. The adapter never changes missing values to global medians.
Context construction later uses **all eligible earlier distinct days**, minimum
180, exact issue minute, and target dates strictly before update_date minus seven
calendar days. Only those rows fit medians; an all-missing ancillary column uses
zero plus its missing flag. Query values or labels cannot affect preprocessing.
Residual training targets are y−raw_anchor; the later law adapter adds it once.

The label-free trend is today's Q05 anchor minus the mean of valid same-minute
anchors in the preceding 14 calendar days, with at least seven valid days. Its
support crosses years correctly. It never uses future weather states or truth,
is preserved for the later T3 correction, and is **not** a 72nd neural column.

Each row keeps source feature path/hash, issue ID, issue/cycle/availability and
retained support clocks, prior cycle IDs/support, and original coverage/missing
diagnostics outside X. Missing spring-DST issue slots are not fabricated.

## Run the owner preparation

Paste these commands from a terminal. Do not paste a Markdown heading or `#`
comment into interactive zsh. Variables belong to that terminal; the setup below
must be repeated in a new one. No activation or package reinstall per terminal
is necessary when using the explicit interpreter paths.

```sh
cd "."
EXP="universal_issue_state/experiments/r14_tabular_pretrained_v1"
.venv/bin/python "$EXP/run_t02.py" t02-preflight
.venv/bin/python "$EXP/run_t02.py" prepare-t02-environment
"$EXP/.venv/bin/python" "$EXP/run_t02.py" download-t02-checkpoints
"$EXP/.venv/bin/python" "$EXP/run_t02.py" probe-t02 --device cpu
"$EXP/.venv/bin/python" "$EXP/run_t02.py" t02-preflight --runtime --device cpu
```

The initial structural preflight reports
`FEATURE_INPUTS_READY_RUNTIME_PREPARATION_REQUIRED`. That is expected before
preparation: it verifies T01, the registry, six Parquet footers and source binding
metadata, without inference or downloads. `--runtime` additionally verifies
installed versions, actual weight SHA-256 and an accepted offline device probe.
Only after that check does it say `READY_FOR_OWNER_ACCEPTANCE`.

Environment preparation is the only package-install command. It creates the
experiment's own `.venv` using Python 3.12, installs the two specified packages
(`tabicl==2.2.0`, `tabdpt==1.3.1`) and pinned numerical core, checks dependency
compatibility, and saves the complete platform-specific resolved version lock
plus pip's download/install report. Some ancillary dependencies are bounded in
the input requirements; their exact resolved versions are frozen in
`environment/requirements-resolved.txt` before T02 acceptance. This is a
platform-specific version lock with pip source hashes where reported, **not a
claim of a portable fully hash-locked wheelhouse**. Do not upgrade it after PASS.
An existing installation receipt is not overwritten; the runtime gate detects
subsequent package/version changes. Setup/downloads may take time: the owner runs
them, not the agent. All package/model caches are routed under `.cache/` here.

Download preparation uses the README's exact Hugging Face revisions and filenames,
checks their SHA-256 before publication, and never accepts current/default weights.
Existing different checkpoints fail rather than being overwritten. It writes no
data to KPHX or the original substrate. An interrupted unaccepted download can be
restarted with the same command; completed matching weights are reused.

CPU float32 without AMP is the conservative reference device in these commands.
The probe exercises both released APIs with the same 71 inputs, eight views,
seed 42 and full supplied context. Its fixture has 180 synthetic context rows and
two synthetic queries; no weather targets are fitted or scored. It checks finite
native 999-quantile/histogram outputs, feature capacity, and query order/batch
invariance within 1e-5 numerical tolerance. It saves timings and device identity.
It is **not** a full-context stress test or a replay ETA. Later large-context
runtime or memory limits must fail openly, not reduce context or change precision.

You can measure MPS/CUDA explicitly by repeating probe/preflight with that device.
Unavailable/unsupported devices fail, and CPU fallback is disabled. Use the
chosen device consistently for run/resume; it is fixed in the T02 PASS. Device
probes use no network, gradient updates, tuning or study truth. The reference
TabDPT API requires reduction options in its constructor; we keep its declared
defaults but prevent their engagement: capacity is checked before fit and
`context_size=None` ensures every supplied context row is used. No silent PCA,
subsampling, context recency weighting, or model auto-download is allowed.

## Start acceptance / feature-view preparation

After the runtime preflight is ready, use a new run ID. This is the owner-run
whole-study transformation, **not** a neural replay.

```sh
cd "."
EXP="universal_issue_state/experiments/r14_tabular_pretrained_v1"
RUN_ID="kdenv375-t02-owner-full-$(date -u +%Y%m%dT%H%M%SZ)-feature-adapter"
"$EXP/.venv/bin/python" "$EXP/run_t02.py" run-t02 --device cpu --run-id "$RUN_ID"
```

Keep the printed/chosen RUN_ID. The scan rehashes its nine direct frozen inputs
(registry, spine, selections, six feature files), not the entire source archive
or thousands of truth evidence files. It joins clocks by issue ID, checks both
independent product cycles, converts all 118,536 weather states, and publishes
six complete immutable year partitions with receipts. It checks for pause every
512 transformed rows and before publication. File reads, hashes and Parquet writes
finish before checking pause. An unfinished year is not accepted; resume repeats
only that year and verifies already completed partitions and all run identities.
It runs the focused synthetic T02 contract tests before publishing PASS.

## Monitoring from a separate terminal

Use the actual run ID from the start terminal, not the placeholder below.

```sh
cd "."
EXP="universal_issue_state/experiments/r14_tabular_pretrained_v1"
RUN_ID="PASTE_YOUR_ACTUAL_T02_RUN_ID"
"$EXP/.venv/bin/python" "$EXP/run_t02.py" t02-live-status --run-id "$RUN_ID" --interval-seconds 5
```

The feed appends lines and does not clear earlier output. Ctrl-C stops the viewer,
not acceptance. One-time status and approximate transform ETA:

```sh
"$EXP/.venv/bin/python" "$EXP/run_t02.py" t02-status --run-id "$RUN_ID"
"$EXP/.venv/bin/python" "$EXP/run_t02.py" t02-eta --run-id "$RUN_ID"
```

Pause and then resume in separate invocations:

```sh
"$EXP/.venv/bin/python" "$EXP/run_t02.py" pause-t02 --run-id "$RUN_ID"
"$EXP/.venv/bin/python" "$EXP/run_t02.py" resume-t02 --device cpu --run-id "$RUN_ID"
```

Wait for PAUSED before resuming. If the laptop/process was interrupted, inspect
status first. `recover-t02-lock` removes only a dead-process running/preparation
lock, refuses if its PID exists, and leaves all inputs/weights/receipts intact:

```sh
"$EXP/.venv/bin/python" "$EXP/run_t02.py" recover-t02-lock
```

There is no cooperative pause for package installation, downloading or the small
native probe; Ctrl-C interrupts those commands. Rerun preparation/probe only if
it did not finish. The acceptance scan has its own pause/resume controls above.

## Validate after PASS

```sh
"$EXP/.venv/bin/python" "$EXP/run_t02.py" validate-t02
```

Validation checks the T01 predecessor and metadata, T02 code/config, six adapter
file hashes/footers, signed report, complete installed-version/device identity,
actual checkpoint hashes and accepted probe. It does not rerun native inference,
open holdout truth, or rehash the original full archive. Rehashing the original
feature sources is performed during run/resume; the output identifies this
validation mode explicitly.

## Main artifacts / model-facing use

- `config/features.json`: exact feature order, source units and transformations.
- `config/checkpoints.json`: exact package/weight identities, native settings and
  publisher model-card license references (TabICL BSD-3-Clause; TabDPT Apache-2.0).
- `.venv/`, `.cache/`, `checkpoints/`: isolated runtime, caches and verified weights.
- `environment/installation.json`, `requirements-resolved.txt`,
  `pip-install-report.json`, `checkpoint_receipt.json`, `probe-cpu.json`: owner
  preparation, dependency and hardware identities. Other explicit devices get
  their own probe files.
- `runs/<RUN_ID>/features/target_year=YYYY/part-YYYY.parquet`: nullable native
  features, missing flags/calendar, trend and provenance. No global imputation
  and no truth columns.
- `runs/<RUN_ID>/receipts/YYYY.json`: immutable year-level hashes and status counts.
- `runs/<RUN_ID>/feature_report.json`: source proofs and complete missing-anchor
  abstention counts; useful before interpreting future supported-forecast rates.
- `runs/<RUN_ID>/state.json`: live transform state.
- `manifests/T02_PASS.json`: accepted adapter/runtime authority used by T03.

The local `FeatureStore` reads accepted T02 partitions; `context(truth_access,
update_date, minute)` retrieves all earlier exact-minute weather states and uses
the separate guarded `TruthAccess` for eligibility/residual labels. `queries`
loads only weather for requested target dates and reports missing issue slots or
anchor abstentions. `FeatureContext.matrix` uses the earlier context medians;
changing query order, batches, or injected label metadata cannot change X.
There is no interface that pools 118,536 issue rows as independent weather days,
opens all holdout labels, applies a global scaler, or silently fills Q05 anchors.

T02 outputs/identities become immutable at acceptance. Additional T03 files can
be added later without editing T01 or T02. T03 implements the predictive laws,
corrections and chronological development replay; **it is not implemented here**.

Primary upstream references inspected for the release API and native full-output
contract: [TabICL API](https://tabicl.readthedocs.io/en/latest/api.html),
[TabDPT estimator](https://github.com/layer6ai-labs/TabDPT-inference/blob/main/src/tabdpt/estimator.py),
[TabDPT regressor](https://github.com/layer6ai-labs/TabDPT-inference/blob/main/src/tabdpt/regressor.py),
[TabDPT dependency/reproduction pins](https://github.com/layer6ai-labs/TabDPT-inference/blob/main/pyproject.toml),
[TabICL model card](https://huggingface.co/jingang/TabICL), and
[TabDPT model card](https://huggingface.co/Layer6/TabDPT). Installed package releases
and checkpoint bytes, not a future upstream main branch, govern actual execution.
