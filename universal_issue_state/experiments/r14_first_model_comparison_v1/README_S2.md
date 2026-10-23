# S2: R14 hourly and subhourly residual baselines

Implementation is ready for the owner-run historical job. **The full baseline prediction release has not been generated.** `manifests/S2_IMPLEMENTATION_RELEASE.json` seals code and checks, not trained historical baselines. Only a completed run's `BASELINE_RELEASE.json` declares `S2_BASELINES_FROZEN`.

Both models retain their raw retained-trajectory maximum in °F. At each exact local issue minute they translate historical errors onto today's raw forecast, using equally weighted Gaussian residual kernels. This is a probabilistic residual correction, not a re-use of Layer 1 results. `point_f` is the continuous translated-mixture mean; derive integer PMF mean, median and mode separately for their respective scorecard metrics.

## Parameter choices

Keep the predeclared 12 candidates per model: seasonal half-width 45, 60 or 90 calendar days, crossed with residual kernel sigma 0.75, 1.25, 2 or 3°F. The seasonal window controls relevance versus sample size. Kernel sigma controls smoothing of the empirical errors; it is **not** the total predictive standard deviation. The total continuous mixture variance is residual population variance plus sigma squared.

Select one setting per model and outer vintage by chronological inner negative log score, weighting days equally. Use the same target-free feasible cases for every candidate, at least 40 residual days per prediction, at least 60 scored days and 50% day-weighted coverage per included block, and at least two included blocks. Numerical ties prefer the wider seasonal window and then the wider kernel. Unsupported tuning fails explicitly. Do not widen the grid or lower minimum support in response to outer outcomes. Selection records flag grid-edge choices as future research questions.

The first short training block can lack seasonal support. Its inclusion is decided before its validation losses are read. Missing raw centers and insufficient pools remain explicit abstentions. Neither diagnostic confidence nor native availability is a learned trading gate.

## Install once

Use a separate modeling environment; preserve the acquisition environment. In a terminal:

```sh
R='.'
E="$R/universal_issue_state/experiments/r14_first_model_comparison_v1"
"$R/.venv/bin/python" -m venv "$E/.venv-models"
"$E/.venv-models/bin/python" -m pip install -r "$E/environment/requirements.txt"
P="$E/.venv-models/bin/python"
"$P" -B "$E/src/s2.py" validate --project-root "$R"
"$P" -B -m unittest discover -s "$E/tests" -v
```

No weather or market data are downloaded. These installation commands obtain the pinned numerical libraries. The accelerated engine requires SciPy 1.15.3; NumPy 2.0.2 and PyArrow 23.0.0 are also checked. Run identity records the Python version, operating platform, engine, code, configuration and upstream input inventory. Changing any of these requires a new run directory. Do not edit a running job's files.

## Start and inspect

```sh
RUN="$E/runs/r14-s2-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$RUN"
"$P" -u -B "$E/src/s2.py" run --project-root "$R" --run-dir "$RUN" > "$RUN/console.log" 2>&1 &
echo "$!" > "$RUN/launcher.pid"
"$P" -B "$E/src/s2.py" status --run-dir "$RUN"
"$P" -B "$E/src/s2.py" watch --run-dir "$RUN"
```

Retain the printed/chosen RUN path; in another terminal, set R, E, P and RUN to the same values. Status appears after initial input verification. Ctrl-C exits the watcher without stopping the separate job. Status reports the current unit, completed units, state and approximate ETA. ETA is unknown until a new unit completes and can be inaccurate as pools grow. This is 360 inner candidate partitions plus six selected outer partitions; expect several million PMFs and multiple GB of output. The small three-day probe is not a full-run timing benchmark.

A bounded rehearsal can use a **separate** run directory with `run ... --max-units 1`. This stops after one newly committed unit; resuming adds at most the specified number of new units while verifying existing units. Use `probe --project-root "$R"` for the fixed 89-day training/three-day assessment correctness probe, with no assessment labels or scores.

## Pause, resume, and recover

```sh
"$P" -B "$E/src/s2.py" pause --run-dir "$RUN"
"$P" -B "$E/src/s2.py" status --run-dir "$RUN"
# After status becomes PAUSED, resume in the foreground (or background as above):
"$P" -u -B "$E/src/s2.py" resume --project-root "$R" --run-dir "$RUN"
```

Pause finishes the current fit/prediction partition, then stops. SIGINT or SIGTERM to the **runner** also requests a safe stop at the next unit boundary. An OS process lock rejects concurrent writers and releases automatically on process exit; do not remove the lock file. A stale RUNNING status after a crash is a last-known snapshot, not proof the process is alive. Confirm the recorded PID before sending any signal.

After a crash, resume with identical code/configuration/environment. Completed units are verified and reused. Interrupted `.unit-*` scratch directories are ignored; they may be removed only after confirming no writer is running. Partial or corrupted committed units fail validation and are never silently overwritten: investigate the cause and start a new run directory rather than modifying the historical record. Run directory names are not model identities; hashes are.

## Validate and find results

```sh
"$P" -B "$E/src/s2.py" validate --project-root "$R" --run-dir "$RUN"
```

- `units/<outer>_<inner>_<candidate>/`: training residual artifact, complete inner prediction partition, and hash manifest.
- `units/<outer>_OUTER_<model>/`: selected-model outer predictions with raw centers, native integer PMFs and explicit abstentions.
- `*_support.json`: pre-loss inclusion decisions and feasibility-mask hashes.
- `*_selection.json`: chosen parameters, inner tuning losses, support counts and grid-edge flags. These are development evidence, not model-comparison claims.
- `status.json`, `console.log`: operations and errors.
- `BASELINE_RELEASE.json`: appears only after all 366 expected units and supporting artifacts are verified. Six outer partitions are the frozen baselines for the later common scorecard.

Every forecast has training dates, the two-day label cutoff, candidate/code/input hashes and residual-pool diagnostics. Fits remain fixed throughout each assessment block. Inner validation labels are exposed only after every candidate's predictions for that block are sealed. All intraday rows stay together; no within-day split or same-day training.

S2 has no outer-scoring command. Do not inspect comparative outer results before the complete S4 comparison prediction seal. Labels come from the verified development-only source ledger; Arrow may internally decode its 2017–2025 row group, but only authorized requested dates are returned. No reserved/tail outcome source is read. This is retrospective audited truth under an assumed reporting lag, not an exact first-publication replay or a newly blind holdout.

No Kalshi band is inferred from the realized temperature. Actual contract bands and executable market data belong to the later market study. Weather accuracy alone cannot establish tradability.
