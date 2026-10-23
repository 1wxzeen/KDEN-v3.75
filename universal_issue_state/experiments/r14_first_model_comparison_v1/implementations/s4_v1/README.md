# S4 — nested tuning and prediction freeze

S4 is implemented. **The full historical run has not been performed.** Completion of the code is separate from completion of the scientific stage. S5 performance comparisons and market/PnL analysis remain later steps.

## Start without pasting commands

Double-click **S4 Launcher.command** in this folder. The menu offers a new run, resume, status, pause, and an installation check. Use the existing modeling environment; there is no new dependency installation.

Choose **1** to start the full run. It runs in the terminal that opens and writes `console.log` and `status.json` in a new `experiments/r14_first_model_comparison_v1/runs/r14-s4-…` folder. Keep that terminal open and the laptop powered. Ctrl+C requests a pause **after the current candidate checkpoint finishes**; fitting or publishing a candidate can take time. Resume from the same launcher with option 2. A power loss can require recomputing the unfinished candidate; completed checkpoints are retained. If a second process already owns the run, the exclusive lock rejects the duplicate launch.

The launcher does not launch a background process silently. The initial full run is substantial: 208 registered settings across seven distinct inner periods, plus 12 selected outer forecasts. There are 1,468 candidate decisions; feature-only excluded blocks count as decisions without fits. Six existing baseline partitions are referenced rather than refitted. These counts are not independent days or statistical sample sizes. No reliable end-to-end runtime estimate is available from sparse probes. Expect a long run and material disk use; the status reports the latest measured candidate duration separately by model, without a misleading pooled ETA.

## What happens

1. Verify sealed S1–S4 authorities, the S3 candidate grid, pinned environment, baseline release and earlier outcome-exposure record.
2. Fix each inner model family's common feasibility mask using features only. Require at least 60 eligible days and 50% expected day-weighted issue coverage. Unsupported blocks are recorded before any assessment outcome is read and are not fitted or scored.
3. Fit every registered candidate on the earlier training population. Preprocessing and solver settings remain those frozen in S3. Store fitted state and all expected issue rows as probabilities or explicit abstentions.
4. Once the block's entire candidate family has a sealed forecast or solver-failure disposition, read only the authorized inner development outcomes. Select on equal-day negative log score; use S3's frozen tie rules. At least two supported inner blocks are required. A solver failure invalidates that candidate across the included blocks, not just its difficult cases.
5. Fit the selected setting on the outer vintage's training data, then save its outer predictions. Repeat for AnEn, location–scale normal GAM and the two diagnostic GAM variants. No outer scores are calculated.
6. Publish `COMPARISON_RELEASE.json`, tying 18 outer model/vintage partitions to their expected issue keys, coverage and common primary support. The six baseline partitions stay in their original S2 run. The release contains explicit relative references to them; keep both run folders.

Identical inner folds are stored once, with their earliest containing outer ID as canonical lineage. Before reuse, the workflow checks that training and assessment dates are identical for every consuming outer vintage. Selection artifacts reference these shared block scores explicitly. AnEn parameter candidates also share immutable training files through hard links; each candidate keeps its own identity and predictions and remains individually reloadable. Never edit a checkpoint in place. A plain copy to another disk may expand hard-linked files.

## Failures and evidence

A registered GAM optimizer failure is recorded with all starts. No valid setting, insufficient tuning support, or a failed selected outer refit produces an abstention at **every expected issue**, with a specific reason. The release is then `FROZEN_WITH_UNSUPPORTED_MODELS`, and the run status is `COMPLETE_WITH_UNSUPPORTED_MODELS`. That means accounting is complete, not that every model worked. The settings and support thresholds are never relaxed to force success. Other errors stop the run; fixing an external interruption and resuming preserves completed work. Changing sealed code or settings requires a new implementation and run.

The already-inspected S2 outer outcomes remain development evidence. S4 cannot make those periods blind again. There is no selective trading gate, post-hoc calibration, Kalshi band reconstruction, or profitability claim here. The normal and t5 GAM variants are separately tuned diagnostics; they are not additional primary comparisons.

Native probabilities remain untouched. Inner model selection alone applies the registered 1e-6 scoring floor followed by renormalization. It gives each included target day equal weight and each admitted issue within a day equal weight. Inner scores are tuning evidence, not the final comparative scorecard.

## Outputs and verification

- `inner/INNER_…_MODEL/SUPPORT.json`: target-free mask, denominator, inclusion and canonical fold lineage.
- Candidate `UNIT.json`, fit state and `forecast/`: sealed forecast or explicit optimizer failure.
- `SCORES.json`: inner-only losses and invalid candidates, bound to support and unit digests.
- `selections/`: one selection and grid-boundary flags per model/vintage.
- `outer/`: selected-model forecasts or explicit unsupported-model abstentions.
- `OUTER_…_common_support.json`: expected keys and four-primary-model intersection, without outcome filtering.
- `COMPARISON_RELEASE.json`: final forecast inventory, model coverage and unsupported-model report.

Forecast rows and PMFs are validated when published. Resume verifies committed file hashes; cached inner scores are reused only when all dependencies match. Final publication checks the outer partitions and their keys. It does **not** launch an extra full-row reread of every inner candidate. The optional `validate-run --deep` does that expensive audit only when explicitly requested.

For automation, `s4.py run --run-dir PATH --max-new-units 1` stops after one newly committed unit. Supply the experiment root when executing a staged copy. `status`, `pause`, `validate`, and `validate-run` are also available. Use the launcher for the normal owner workflow. A PAUSE file persists until the launcher resumes the run; the low-level `run` command intentionally does not clear it.
