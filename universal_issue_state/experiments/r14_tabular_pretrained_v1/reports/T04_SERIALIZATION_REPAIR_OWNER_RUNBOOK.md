# T04 boolean serialization recovery — V1

## Cause and scope

On 2026-10-10, the development run stopped saving the verification for
2022-02-11. Six TabICL RAW forecasts (14:45–16:00 America/Denver) produced
NumPy boolean diagnostic flags from the quantile law's finite exponential-tail
log-probability calculation. Python's JSON writer accepts builtin booleans but
not NumPy booleans. The recorded error was:
`TypeError: Object of type bool is not JSON serializable`.

This is an implementation serialization error, not missing HRRR/truth data,
model fitting failure, numerical probability flooring, or failed model skill.
The fix converts only `genuine_zero_probability` and `probability_underflow`
to builtin booleans, preserving their true/false values. Numeric metrics,
probabilities, genuine infinite NLL, laws, features, timestamps, cutoffs,
forecast bytes and correction history do not change.

The stopped checkpoint has 312 committed units: 228 native contexts,
42 forecast days (2,394 issue states), 41 score days and one regime unit.
2022-02-11's forecast is already committed. Its verification can be retried
without refitting those contexts or recomputing earlier forecasts/scores.

## Immutable compatibility record

The original T04 source, check receipt, run identity and completed artifacts
remain byte-identical. This additive entry point installs the boolean-only
conversion for scoring in memory. It does not rewrite the baseline binding.
Preparation writes a signed immutable attestation at:
`runs/<run-id>/repairs/T04_NUMPY_BOOLEAN_SERIALIZATION_V1.json`.

That attestation records the original run identity, existing receipt hashes,
failure-state hash, exact repair code/test/document hashes and short-test
receipt. Every newly committed score and the final report bind the attestation
as an extra artifact. The final report also contains `implementation_repairs`;
the final PASS and recipe lock bind that report. The repair entry point verifies
both original and additive identities on resume, validation and recipe lock.
Use this entry point for subsequent long controls, validation and locking of
this repaired run. The original monitor/status commands remain valid.

No original check receipt is replaced. No accepted T01–T03 artifact is changed.
No HRRR acquisition, substrate acceptance, truth acquisition, package install,
weight download, new model fitting policy or holdout opening is required.

## Owner commands

Run from the KDEN v3.75 root; repeat these two variables in each new terminal.

```sh
EXP="universal_issue_state/experiments/r14_tabular_pretrained_v1"
RUN_ID="kdenv375-t04-owner-full-development-v1"
```

Prepare the small recovery record and check readiness:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04_serialization_repair.py" prepare-t04-serialization-repair --run-id "$RUN_ID"
"$EXP/.venv/bin/python" -B "$EXP/run_t04_serialization_repair.py" repair-preflight --run-id "$RUN_ID"
```

Resume the long replay yourself:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04_serialization_repair.py" resume-t04 --run-id "$RUN_ID"
```

Monitor in a separate terminal:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-live-status --run-id "$RUN_ID" --interval-seconds 5
```

One-time status/ETA or cooperative pause:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-status --run-id "$RUN_ID"
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" t04-eta --run-id "$RUN_ID"
```

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04.py" pause-t04 --run-id "$RUN_ID"
```

After PASS, run the full output validation yourself, then inspect the report:

```sh
"$EXP/.venv/bin/python" -B "$EXP/run_t04_serialization_repair.py" validate-t04
"$EXP/.venv/bin/python" -B "$EXP/run_t04_serialization_repair.py" t04-report
```

Recipe decision preparation and locking use the same arguments as the original
T04 runbook, but substitute `run_t04_serialization_repair.py` for `run_t04.py`.
Do not lock before successful owner-run validation and development review.
The primary window remains 02:00–14:00 America/Denver. Numeric success limits
still require explicit owner confirmation. No T05 is started by this repair.

## Where to look

- Repair checks: `manifests/T04_SERIALIZATION_REPAIR_CHECKS_V1.json`.
- Recovery attestation: `runs/<run-id>/repairs/T04_NUMPY_BOOLEAN_SERIALIZATION_V1.json`.
- Live status: `runs/<run-id>/state.json`.
- Original forecast commits: `runs/<run-id>/forecasts/`.
- Verification bundles: `runs/<run-id>/units/score-<date>.json`.
- Final report: `runs/<run-id>/units/development-scorecard.json`.
- Final PASS: `manifests/T04_DEVELOPMENT_PASS.json`.

The repair was tested with synthetic laws and short synthetic recovery checks,
plus a read-only reconstruction of the single failing day. The agent does not
restart the replay, refit models, run full validation or read holdout outcomes.
