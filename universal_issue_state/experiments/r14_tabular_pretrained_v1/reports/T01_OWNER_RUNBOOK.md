# T01 — experiment foundation owner runbook

T01 inventories and verifies existing local inputs, records date/block roles,
copies the existing exposure disclosure, and creates an experiment-local trusted
label overlay. It does not acquire weather or truth, download models, fit a
model, open the 365-day holdout, or alter an earlier release.

## Location and installation

From the **KDEN v3.75 project root**, use its existing Python interpreter and
the experiment-local entry point below. No package reinstall is needed for T01.
The only third-party runtime dependency is the already installed PyArrow.
T02 will prepare a separate neural environment rather than modify this one.

Set these terminal-local convenience variables in **each new terminal**:

```sh
cd "."
EXP="universal_issue_state/experiments/r14_tabular_pretrained_v1"
RUN_ID="kden-r14-t01-20261010T000000Z-foundation"
```

The example run ID is a stable label, not the current time. You may replace its
timestamp with your own UTC timestamp before starting, then use the same ID in
all terminals and on resume. The code finds the project/experiment roots from
the entry point, so it does not depend on these environment variables internally.

## Preflight, start, and validation

Quick, network-free preflight (metadata, filenames and small authority documents;
not a deep original-input hash scan):

```sh
.venv/bin/python "$EXP/run.py" t01-preflight
```

Proceed only on `READY_FOR_OWNER_T01`. It reports any missing local holdout audit
files without exposing their values. Structural presence is not proof that CLI
and CF6 agree; the content audit remains a later, locked-recipe step.

Owner-run hash verification and T01 publication:

```sh
.venv/bin/python "$EXP/run.py" run-t01 --run-id "$RUN_ID"
```

This checks the P06 frozen substrate bindings, P07 artifact bindings, and all
7,139 copied truth-evidence files. It does not re-scan the canonical HRRR value
archive. Bytes of sealed files may be hashed, but no sealed value page, audit
JSON content, or raw report text is parsed. Expect more work than the quick
preflight; the owner, not the coding agent, runs it.

After `PASS`, quick validation:

```sh
.venv/bin/python "$EXP/run.py" validate-t01
```

Optional owner-run rehash of original inputs:

```sh
.venv/bin/python "$EXP/run.py" validate-t01 --deep
```

Quick validation checks the signed PASS, code/config/schema identities, output
hashes, predecessor chain, input paths/sizes/declared hash authorities, and date
enumeration. It is explicitly **not** another byte-by-byte check of all originals.
Deep validation adds that byte verification without opening holdout outcomes.

## Separate-terminal monitoring and pause/resume

```sh
.venv/bin/python "$EXP/run.py" t01-status --run-id "$RUN_ID"
.venv/bin/python "$EXP/run.py" t01-live-status --run-id "$RUN_ID" --interval-seconds 5
.venv/bin/python "$EXP/run.py" t01-eta --run-id "$RUN_ID"
.venv/bin/python "$EXP/run.py" pause-t01 --run-id "$RUN_ID"
.venv/bin/python "$EXP/run.py" resume-t01 --run-id "$RUN_ID"
```

Live status appends lines; it does not erase previous terminal output. ETA uses
active-time input-binding throughput, not paused wall time. Different files
have different costs, so this estimate is approximate and is not a model ETA.

Pause waits for a file boundary. During overlay publication, already published
immutable outputs can remain, but no incomplete PASS is accepted. Resume checks
the original run identity, signed checkpoints, and input bytes again rather
than assuming old file modification times prove integrity. This can repeat
verification work; it never rewrites a completed immutable overlay.

`Ctrl+C` in the live-status terminal stops only monitoring. Prefer `pause-t01`
for the worker. If the worker is forcibly stopped, inspect its reported PID and
ensure it is no longer running. Only then, if a stale lock remains:

```sh
.venv/bin/python "$EXP/run.py" recover-t01-lock
.venv/bin/python "$EXP/run.py" resume-t01 --run-id "$RUN_ID"
```

Recovery removes only a dead-process `runs/T01_RUNNING.lock`; it never removes
inputs, outputs or checkpoints. It refuses recovery while that PID exists.
If a copied/restored project contains an active PID belonging to another
process, do not force deletion: inspect ownership first.

## Artifacts and truth access

All new artifacts live under the experiment directory:

| Output | Meaning |
|---|---|
| `config/experiment.json` | Dates, 105-minute HRRR lag, exclusive seven-day label delay, pinned authorities; scoring-window/limit proposals are not yet locked |
| `inputs/input_inventory.json` | Verified byte identities and predecessor authorities |
| `inputs/date_roles.json` | 2,080 dates, DST-safe issue counts, 45 development +13 holdout blocks and weekly update dates |
| `inputs/truth/trusted_labels.json` | 1,710 development/context dates plus five additional accepted dates; three unresolved labels remain null |
| `inputs/truth/holdout_evidence_inventory.json` | 365 opaque audit file references, source bundles, structural gaps and deferred-content-audit disclosure |
| `inputs/truth/adapter_contract.json` | Closed holdout gate and training/scoring access contract |
| `inputs/exposure_ledger.json` | Original local exposure disclosure plus this experiment's truthful claims |
| `manifests/T01_PASS.json` | Signed T01 completion receipt and artifact/code/input bindings |
| `runs/<RUN_ID>/state.json` | Live status; mutable, not a freeze authority |
| `runs/<RUN_ID>/identity.json` | Immutable resume identity |
| `runs/<RUN_ID>/checkpoints/` | Signed hash-verification chunks |

The original package remains at `truth/kden_tmax/v1/` in KDEN v3.75. No second
full truth-package copy is needed inside the experiment: all inputs are already
self-contained in KDEN, and the new overlay references its frozen local sources.
The overlay contains **no** holdout labels. September 7–11, 2026 labels are
preserved verbatim as trusted additional dates, not excluded for maturity.

Later fitting code uses `TruthAccess.from_release(EXPERIMENT_ROOT).context(date)`.
An explicitly requested target at/after `date - 7 calendar days` raises an error;
the default expanding request simply returns earlier non-null trusted labels.
October 1 admits September 23, not September 24. Holdout access always fails in
T01, even when a caller requests an otherwise-old date inside that year.

Scoring uses `.score(target_date, commit_path=...)`. It requires a signed
`COMMITTED` receipt, the matching Parquet payload hash, and matching forecast
query keys before returning authorized query truth. No forecast is emitted by
T01; this interface is reserved for T03. These are software safeguards, not
operating-system secrecy from someone who intentionally opens a source file.

The pure `audit_chronology` rule is tested on synthetic CLI/CF6 events only.
It does not turn mechanical candidates into truth and does not enable holdout
opening. Parsing and publication of the reserved year's actual evidence will
be gated by T04's recipe lock and implemented before the owner-run T05 replay.

## Short implementation tests

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$EXP/src" .venv/bin/python -m unittest discover -s "$EXP/tests" -v
```

Tests use synthetic fixtures in the experiment's cache and remove them after
completion. They do not read production outcome values or fit models.

After T01 `PASS` and `VALID`, the next implementation stage is **T02**, the
71-column feature adapter and pinned neural environments. Do not open the
holdout or begin a model run merely because T01 passed.

T01 binds only its declared owned code/config/schema/document files. Later
stages must add their own modules, configuration and entry points rather than
edit the frozen T01 components. In particular, T04 confirms the scoring proposals
in a new recipe-lock contract; it does not rewrite `config/experiment.json`.
Future holdout access will be a separately gated rolling accessor, not an
`allow_holdout` switch retrofitted into this trusted-label reader.
