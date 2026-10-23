# Public snapshot status

This directory preserves historical implementation and stage instructions. The full weather/truth archives, fitted models, and local environments are not bundled; historical install/start claims below do not describe a fresh clone. Use the root README and DATA_AVAILABILITY guide for current package scope.

The baseline/AnEn/GAM, boosted, and CR1 comparisons were completed historically; the pretrained-tabular development replay remains paused and unaccepted.

---

# R14 first model comparison — S0

S0 specifies and validates the experiment. Start with [the S0 report](reports/S0_REPORT.md), then [the experiment contract](config/experiment.json). The next implementation stage is S1: shared data loading and scoring. No model-fitting command exists yet.

This experiment lives beside the frozen substrate, not inside it. It builds new R14 baselines, a generalist residual AnEn, and a location–scale GAM. P07 is a reference for inherited definitions and folds; this is not a run of the full RAFM protocol.

## Contents

- `config/experiment.json`: complete prefit choices, formulas, tuning, evidence roles and execution boundary.
- `config/features.json`: exact feature definitions, accepted range corrections, and diagnostic regimes.
- `config/scorecard.json`: point/distribution/band/calibration/coverage metrics and required figures.
- `config/candidates.json`: 232 explicit registered parameter configurations; four primary and two diagnostic model IDs.
- `config/evidence_exposure.json`: cross-project exposure ledger; no fresh-blind-test claim.
- `config/decisions.json`: resolutions of all twelve plan decision categories and explicit deviations.
- `schemas/`: exact-revision JSON Schemas using `const`. They deliberately reject any changed scientific choice. The local validator supports only the small keyword subset used here; it is not a general JSON Schema library.
- `environment/`: isolated modeling dependency specification; no modeling environment installed during S0.
- `manifests/input_inventory.json`: 29 selected input files, measured hashes, recorded upstream hashes, schemas and counts. This is not a re-audit of the complete raw archive.
- `manifests/research_context.json`: documentation provenance only; no external runtime imports.
- `manifests/S0_RELEASE.json`: sealed S0 artifact identities.
- `src/s0.py`: read-only validator; hashes selected inputs, decodes allowlisted fold metadata, checks Parquet schemas/row counts, and checks contract/release identities. It never decodes truth or weather data pages.
- `tests/test_s0.py`: focused positive and negative controls.

## Validate S0

Run from the KDEN v3.75 project root. The existing project environment is used read-only for its PyArrow installation; this does not add packages to it.

```sh
.venv/bin/python -B universal_issue_state/experiments/r14_first_model_comparison_v1/src/s0.py --project-root .
```

Expected result: `status: VALID`, 29 selected inputs verified, 118,536 feature rows accounted for, 232 registered configurations, zero model fits and zero decoded outcome values. Validation reads only selected file identities, schemas and role/fold metadata. Feature/truth data-page checks belong to later stages under the data-access contract.

```sh
.venv/bin/python -B -m unittest discover -s universal_issue_state/experiments/r14_first_model_comparison_v1/tests -v
```

Expected result: 13 passing tests. An invalid contract, changed input, changed artifact, broken partition or unsafe path fails closed. Do not edit this release to make a failing validation pass; investigate and publish an explicitly versioned successor if necessary.

To repeat the instrumented metadata-only access audit:

```sh
.venv/bin/python -B universal_issue_state/experiments/r14_first_model_comparison_v1/src/audit_access.py --project-root .
```

The audit must report exactly three allowlisted metadata-table reads and zero truth/weather data-page reads.

## Modeling environment — for a later implementation stage

The environment is specified, not installed or claimed numerically validated. From this experiment directory, when implementation needs it:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r environment/requirements.txt
```

Record the actual Python patch version, installed packages, platform, BLAS and wheel hashes before numerical work. Set the three thread variables listed in `environment/environment.json` to 1 before numerical fitting. Do not modify the acquisition environment.

The GAM will use a local joint discrete-likelihood objective and the documented [SciPy L-BFGS-B optimizer](https://docs.scipy.org/doc/scipy-1.15.3/reference/optimize.minimize-lbfgsb.html), with [B-spline bases](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.interpolate.BSpline.html). S3 must implement and test the objective, analytic gradients, convergence and probability stability before fitting real models. S0 specifies that work; it does not claim the solver is already validated.

## Evidence boundary

Training uses only authorized audited development truth, with a two-day target-date lag and fixed model vintages. This is retrospective audited truth under an assumed reporting lag, not exact historical first-seen replay. Reserved historical and tail labels remain outside this experiment's development stages. NBM already exposed the nominal holdout elsewhere; no new directory can restore blindness.

No learned gate, probability calibrator, specialist mixture, observation adapter, market data, trading policy, or formal model promotion is included here. Native-confidence diagnostics will establish whether those later experiments are justified.
