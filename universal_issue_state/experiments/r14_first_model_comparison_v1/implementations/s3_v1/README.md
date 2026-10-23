# S3: AnEn and location–scale GAM

S3 implements the model families and validates bounded fits. It does **not** select final model settings, run the full historical comparison, establish improved accuracy, or create a trading gate. Full nested tuning and prediction generation belong to S4.

The final feature decision retains **850-mb temperature and its surface contrast**, supported by D1 and the user's clarification. Ten physical coordinates are organized into six groups. See [DECISIONS.md](DECISIONS.md) for every feature, its physical rationale, limitations, parameter choices, differences from S0, sources and exposure disclosure.

Implemented:

- **ANEN:** exact-issue seasonal residual analog ensemble with training-only robust scaling and balanced physical-group distances.
- **GAM_LS_NORMAL:** regularized additive corrections to both forecast location and uncertainty.
- **GAM_LOCATION_NORMAL:** constant-scale diagnostic.
- **GAM_LS_T5:** fixed Student-t(5) tail diagnostic.

All emit the S1 forecast schema, native integer PMFs, raw Q center, corrected continuous point, causal training lineage and explicit abstentions. Fits can be saved/restored without retraining; restore checks hashes and uses JSON/NPZ, not executable pickles.

## Easy checks

Open **S3 Checks.command** to choose a validation or test check. This uses the existing modeling environment installed for S2. It does not start a long model-comparison run.

For a terminal, run each line separately in the same terminal:

```sh
E='./universal_issue_state/experiments/r14_first_model_comparison_v1'
S="$E/implementations/s3_v1"
P="$E/.venv-models/bin/python"
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
"$P" -B "$S/s3.py" validate
```

A test run uses only synthetic fixtures:

```sh
R14_EXPERIMENT_ROOT="$E" "$P" -B -m unittest discover -s "$S/tests" -v
```

The pinned environment is unchanged: NumPy 2.0.2, SciPy 1.15.3, PyArrow 23.0.0. The S2 installation instructions still apply if it is absent. No meteorological or market data are downloaded.

## Optional bounded probe

The probe is already completed and reported in [reports/PROBE.json](reports/PROBE.json). It fits on a fixed subsample of 122 eligible 2021 days, then predicts 2022-01-20, 2022-02-20 and the spring DST day 2022-03-13 without reading those assessment outcomes. It is not hyperparameter tuning or model evaluation.

To repeat deliberately, choose a new destination; existing outputs are never overwritten:

```sh
"$P" -u -B "$S/s3.py" probe --output "$E/runs/s3-probe-repeat-01"
```

## One candidate unit (for S4 integration, not a selected model)

The reusable `runtime.fit`, `runtime.records`, and `runtime.load_fit` APIs provide the model/forecast interface for S4. `candidates.json` contains 180 AnEn settings, 12 primary GAM settings, four constant-scale settings and 12 Student-t settings. `config.json` carries the S4 tuning requirements: chronological inner folds, common target-free feasibility support, equal target-day weights, minimum two eligible blocks, and deterministic ties. S3 does not implement a new selection shortcut or reuse a baseline winner as an AnEn/GAM winner.

A single registered candidate can be fitted and published with:

```sh
"$P" -B "$S/s3.py" candidates --model ANEN
```

Select an ID from that list for an explicit engineering unit (selection from this list is **not** scientific tuning):

```sh
"$P" -u -B "$S/s3.py" fit-unit --model ANEN --candidate-id REPLACE_WITH_LISTED_ID --outer OUTER_01 --inner INNER_02 --output "$E/runs/s3-single-candidate-01"
```

Omit `--inner` only for an explicitly requested outer candidate forecast unit. No assessment outcomes are loaded by this command. A finished candidate unit is marked `S3_CANDIDATE_UNIT_COMPLETE_NOT_SELECTED`, not a full comparison release.

**Progress:** `<output>.status.json` records LOADING, FITTING, PREDICTING, COMPLETE, FAILED or INTERRUPTED. The foreground console returns when the unit ends. ETA is intentionally unknown because one candidate unit has no completed-unit timing history; use the recorded elapsed time and the bounded probe timings only as rough guidance. To inspect the state in another terminal, open that status file; do not repeatedly launch the fit command.

**Pause/stop:** S3's single-unit helper has no mid-optimizer pause/resume. Ctrl-C safely interrupts it, writes interruption status, and discards uncommitted scratch output. Retry the identical command to restart that unfinished unit. Completed units are immutable and remain reusable. Do not interpret the S2 multi-unit pause/resume controls as applying to S3. Long multi-unit resumable orchestration is S4 work; the helper makes atomic units available for it.

**Recovery:** the process lock prevents two writers to the same destination. After a hard process termination, confirm no writer remains, then retry the identical command. Orphan `.s3-unit-*` scratch directories are ignored and may be removed after that confirmation. Never change code/configuration mid-run or overwrite a committed unit. Do not mix units with different configuration/code/input identities in a later release.

Validate one completed unit:

```sh
"$P" -B "$S/s3.py" validate-unit --output "$E/runs/s3-single-candidate-01"
```

The unit contains `forecast/`, `fit_state.json`, `training.npz`, `training_metadata.json`, `identity.json`, and `UNIT.json`. Training artifacts contain authorized training labels/residuals and are not OOF validation evidence. The forecast table contains no outcomes.

## What remains

S4 must run the registered nested comparison, handle unsupported candidates/blocks without favorable case deletion, choose and freeze each model's settings, and publish all outer forecasts with the existing S2 baseline release as a dependency. S5 remains the comprehensive descriptive/inferential scorecard. Existing baseline diagnostics and D1 results are already inspected evidence; later performance on overlapping periods is not a newly blind test.

Original S0/S1/S2 files remain unchanged. S3 lives outside their `src/` directory so it does not invalidate S2's code-inventory identity.
