# Research reading edition

Historical document, not the current v3.75 execution contract. This GitHub reading edition preserves the source's proposals and results; they are not relabeled as completed R14 work. Agent-directed wording is retained.

Source: `KDEN_Universal_Issue_Time_Feature_Panel_Implementation_Manual_v1.5.docx`  
Source SHA-256: `c15fb27e36fb1426c31989efd59307849c4eb3407971ba5b9f949b9757f106db`

Word metadata is omitted by conversion. Any additional withholding is recorded in the publication manifest.

---

**COMPANION CODING RUNBOOK**

KDEN Universal Issue-Time\
Feature Panel

Serial Implementation Manual for Acquisition, Canonical Tables, Feature Engineering, and Model-Ready Release

**Version 1.5 \| 2 September 2026**

*Companion to the KDEN Universal Issue-Time Feature Panel Scientific Specification v1.0\
Execution mode: one step at a time; no parallel production work*

Written so a coding agent can implement any named step using these two documents as the complete handoff

# Document control

| **Property** | **Binding value** |
|:--:|----|
| **Document** | KDEN Universal Issue-Time Feature Panel Implementation Manual |
| **Version / status** | v1.0 / coding-agent execution contract |
| **Companion authority** | KDEN Universal Issue-Time Feature Panel Scientific Specification v1.0 |
| **Historical window** | 2021-01-01 through 2026-08-04, unless the run configuration narrows it |
| **Station / target** | KDEN / official whole-degree-Fahrenheit daily Tmax |
| **Checkpoints** | CP_0900, CP_0945, CP_1000, CP_1045, CP_1100, CP_1145 in America/Denver |
| **Execution policy** | Exactly one numbered step may be in progress; Step N requires Step N-1 PASS |
| **Full-history acquisition authority** | Only the project owner may start, pause/stop, or resume a full-history acquisition. A coding agent may implement acquisition code and run bounded pilot, test, or diagnostic slices when warranted, but it must never launch or supervise a full-history acquisition. |
| **Primary deliverable** | A frozen, target-free checkpoint_features release plus isolated training_labels |
| **Out of scope** | GAM fitting, state-space estimation, market execution, PnL optimization, and live deployment |

| **Precedence rule** The Scientific Specification controls what the data mean. This manual controls how the code is organized and executed. Existing sealed Layer 1 registries control historical checkpoint, cycle, availability, coordinate-era, and baseline facts. If the three disagree, the coding agent must stop and write a conflict report; it may not choose an interpretation silently. |
|----|

# How to use this manual

Give the coding agent the Scientific Specification, this manual, the existing repository, and a single instruction such as “Implement Step 08.” The agent first verifies the preceding PASS record and implements only the files listed for that step. For ordinary steps, it runs the prescribed tests, writes the step evidence, and stops. For owner-controlled acquisition Steps 08, 09, and 11, the agent implements the code, runs only bounded pilot, test, or diagnostic scopes, writes STEP\_\<NN\>\_READY_FOR_OWNER_RUN.json, prints the exact owner commands, and stops. Only the project owner may start, pause/stop, or resume the full-history acquisition. A successful owner-run acquisition performs its terminal validation and writes STEP\_\<NN\>\_PASS.json. Neither the coding agent nor the owner begins the next numbered step until that PASS record exists.

| **Actor** | **Responsibility** |
|:--:|----|
| **Owner** | Supplies the configurable project root, approves the Step 07 cost envelope, and is the sole authority permitted to start, pause/stop, or resume full-history acquisition in Steps 08, 09, and 11. |
| **Coding agent** | Implements exactly one step, preserves upstream artifacts, and produces machine-verifiable evidence. For Steps 08, 09, and 11, it may execute the production acquisition code only against a bounded pilot, test, or diagnostic scope and must stop at READY_FOR_OWNER_RUN. |
| **Step runner** | Refuses out-of-order execution and unscoped acquisition. It supports bounded diagnostic, owner-full, and validation-only modes; checkpoints interrupted owner runs; and creates PASS only after the complete owner-full acquisition and all terminal gates succeed. |
| **Scientific reviewer** | Uses the Specification to adjudicate semantic conflicts; no field is promoted by implementation convenience. |
| **Downstream model code** | Reads frozen features through declared keys and view masks; joins truth only in training/evaluation. |

# Contents

- Part I — Global execution contract

- Part II — Strict serial chronology

- Part III — Steps 01–18

- Part IV — Shared schemas, algorithms, and acceptance gates

- Appendix A — Existing-source reuse map

- Appendix B — Coding-agent prompt template

- Appendix C — Release and modeling-reader contracts

# Part I — Global execution contract

## 1. The serial-only rule

Logical independence does not authorize operational concurrency. The pipeline is deliberately linear so each artifact is inspectable before it becomes an input. The orchestrator must hold one global run lock and must reject a requested step unless every earlier required PASS record is present and its recorded input hashes still match.

| **State** | **Allowed action** |
|:--:|----|
| **PENDING** | Read-only inspection and planning only. |
| **RUNNING** | Exactly one step owns the global lock. For Steps 08, 09, and 11, full-history RUNNING state must originate from an owner-full invocation. |
| **FAILED** | Preserve logs and quarantine outputs; repair or rerun the same step. |
| **PASS** | Seal output manifest and permit the next numbered step. |
| **STALE** | An upstream hash changed; invalidate this and all later PASS records without deleting evidence. |
| **READY_FOR_OWNER_RUN** | Code and bounded diagnostics passed. The coding agent stops and hands the full-run commands to the owner. |
| **PAUSED** | The owner interrupted a full acquisition after durable checkpointing. Only the owner may resume it using the same run_id. |

**Owner-controlled full-history acquisition**

For this manual, a **full-history acquisition** is any execution of the complete historical network-retrieval plan, or any material portion of it beyond the bounded diagnostic scope sealed in Step 07. This rule applies to Steps 08, 09, and 11 and to any future step that retrieves the complete historical source universe.

A coding agent may implement acquisition software and may run the production code path against a bounded pilot, test, or diagnostic scope when necessary to verify or debug it. Diagnostic mode must enforce the sealed date, request, and byte limits from config/diagnostic_scope.json; it must be technically incapable of expanding to the full request plan.

Only the project owner may invoke --scope owner-full. The coding agent may generate and print the command, but it must not execute it, remain attached to it, poll it continuously, or wait for it to finish during an agent turn. Approval of the Step 07 cost envelope does not itself authorize the coding agent to launch acquisition.

An owner-full process must be safely interruptible. On SIGINT or SIGTERM, it finishes or rolls back the current atomic work unit, writes durable progress and hashes, marks the step PAUSED, releases its lock, and exits without writing PASS. Resume uses the same run_id, verifies all previously published partitions and hashes, and continues from the first incomplete work unit.

When the full request plan is exhausted, the owner-full process runs the step’s terminal validation automatically. It writes STEP\_\<NN\>\_PASS.json only if every request, partition, hash, ledger, and acceptance gate reconciles. A coding agent may subsequently inspect the completed outputs or run --scope validate-only, but it may not restart acquisition without a new explicit owner action.

In this manual, “stop” means a graceful pause: the run transitions to PAUSED and remains resumable. No terminal CANCELLED state or destructive cancellation operation is defined.

**Normative orchestration pattern**

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th>def assert_step_may_run(step_no, state_dir, current_input_hashes):<br />
assert acquire_exclusive_lock(state_dir / "pipeline.lock")<br />
for prior in range(1, step_no):<br />
record = read_pass(state_dir / f"STEP_{prior:02d}_PASS.json")<br />
if not record or record["status"] != "PASS":<br />
raise OutOfOrderStep(prior)<br />
if record["output_hashes"] != recompute_declared_outputs(record):<br />
raise StaleDependency(prior)<br />
assert no_other_step_is_running(state_dir)</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

## 2. Immutable input and output rules

- All Layer 1, Layer 1.5, historical MADIS, and curated truth roots are mounted or treated read-only.

- No canonical table is overwritten in place. A run writes to a temporary run directory, validates, then atomically publishes a versioned partition.

- Raw GRIB message bytes may be discarded only after extracted values, inventory, response metadata, and hashes are durable and reconciled.

- Existing temperature-floor observations, bounds, and floor baselines are reused exactly; extended MADIS acquisition adds variables without rewriting those artifacts.

- True Tmax, residuals, finalized daily summaries, and market outcomes are forbidden from all feature-build processes and imports.

## 3. Time, key, and unit conventions

| **Convention** | **Contract** |
|:--:|----|
| **UTC authority** | All source availability, joins, cycle initializations, valid times, and intervals use timezone-aware UTC. |
| **Local display** | America/Denver civil time is materialized for checkpoints; never infer UTC using a fixed offset. |
| **Target window** | W\[d\] = \[07:00Z on d, 07:00Z on d+1), left-inclusive/right-exclusive. |
| **Checkpoint key** | target_day + checkpoint_id is unique; all six rows for a day remain a grouped modeling unit. |
| **HRRR key** | target_day + product + cycle_init_utc + valid_time_utc + field_registry_id + spatial_stat. |
| **Observation key** | station_id + observation_time_utc + source_file_hash + variable_code, with receipt time retained when available. |
| **Units** | Preserve native units and write canonical units. Numeric feature names end in a unit suffix. |

## 4. Repository and artifact layout

**Required project layout**

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th>feature_panel/<br />
pyproject.toml<br />
config/panel_v1.toml<br />
registries/{hourly,subhourly,madis,operators,features,views}.csv|yaml<br />
schemas/{cycle_manifest,hrrr_point_trajectory,madis_observation_sequence,<br />
madis_selected_cycle_expectation,checkpoint_features,<br />
training_labels}.json<br />
src/kden_panel/<br />
cli.py contracts.py hashes.py time.py units.py<br />
io/{parquet.py,atomic.py,http_range.py,grib.py,madis.py}.py<br />
steps/step_01_*.py ... step_18_*.py<br />
features/{temporal.py,spatial.py,composites.py,observations.py}.py<br />
tests/{unit,integration,golden,acceptance}/<br />
state/STEP_XX_{RUNNING,READY_FOR_OWNER_RUN,PAUSED,PASS,FAIL}.json<br />
runs/&lt;run_id&gt;/{logs,manifests,quarantine,reports}/<br />
data/{staging,canonical,release}/</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

The physical data root may be outside the code repository. It is supplied by configuration. Code must not hard-code the owner’s filesystem prefix, username, mounted-volume name, or Finder path.

READY_FOR_OWNER_RUN and PAUSED apply only to owner-controlled acquisition steps. A STEP_XX_FAIL.json file carries status FAILED.

## 5. Run identifiers, logging, and PASS records

Each command receives a stable run_id. Every log record is structured JSON and includes run_id, step_id, target_day when applicable, source object identity, severity, and event code. Retries append events; they do not erase the failed attempt.

**Minimum STEP_XX_PASS.json schema**

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th><p>{<br />
"step_id": "STEP_08",<br />
"status": "PASS",<br />
"run_id": "fpv1_20260902T180000Z",<br />
"started_at_utc": "...",<br />
"finished_at_utc": "...",<br />
"code_commit": "&lt;git sha or source-tree hash&gt;",<br />
"config_sha256": "...",<br />
"input_hashes": {"request_plan": "...", "cycle_manifest": "..."},<br />
"output_hashes": {"wrfsfcf_extract_manifest": "..."},<br />
"tests": [{"id": "A03", "status": "PASS"}],<br />
"counts": {},<br />
"warnings": [],</p>
<p>"execution_scope": "owner-full",<br />
"next_permitted_step": 9<br />
}</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

execution_scope is required. Ordinary steps record ordinary. For Steps 08, 09, and 11, only an owner-full execution may emit PASS; diagnostic execution emits READY_FOR_OWNER_RUN, while validate-only is read-only and may not create or modify PASS or acquisition state.

## 6. Common failure policy

| **Condition** | **Required response** |
|:--:|----|
| **Ambiguous key or cycle** | Fail closed; write conflict rows; do not guess. |
| **Optional field absent** | Write null plus field-specific missingness and reason; dependent composites remain null. |
| **GRIB selector miss** | Quarantine the source inventory and stop the affected pilot/full partition. |
| **Unsupported step semantics** | Do not reinterpret; quarantine the message and fail A04. |
| **Source unavailable** | Record confirmed missingness and retries; do not silently substitute a different product. |
| **Hash mismatch** | Do not resume past the object; preserve both expected and observed hashes. |
| **Truth-like column detected** | Abort before publish and identify the import path that introduced it. |

# Part II — Strict serial chronology

| **Step** | **Independent focus** | **Exit artifact** |
|:--:|----|----|
| **01** | Initialize the implementation workspace | Executable shell and immutable run contract |
| **02** | Resolve and verify sealed upstream sources | Resolved source map and denylist |
| **03** | Encode scientific registries and schemas | Machine-readable v1 contracts |
| **04** | Build the Layer 1 checkpoint spine | Six-row-per-day target-free spine |
| **05** | Build cycle_manifest | Legal retained-cycle authority |
| **06** | Build the deduplicated request plan | Exact source-message and valid-time plan |
| **07** | Execute the representative pilot | Selector/semantics proof and authorized cost envelope |
| **08** | Acquire and extract wrfsfcf | Hourly HRRR compact extracts |
| **09** | Acquire and extract wrfsubhf | Subhourly HRRR compact extracts |
| **10** | Assemble hrrr_point_trajectory | Unified HRRR reconstruction authority |
| **11** | Acquire the extended MADIS variables | Raw variable-preserving observation extracts |
| **12** | Build madis_observation_sequence | Legal ordered sequence, departures, and innovations |
| **13** | Derive NWP and baseline feature blocks | Target-free structural staging table |
| **14** | Derive observation and departure blocks | Checkpoint-legal V2 staging table |
| **15** | Assemble checkpoint_features and view registry | Wide target-free model input product |
| **16** | Run acceptance, reproducibility, and freeze | Sealed feature release |
| **17** | Build isolated training_labels | Truth sidecar and training-only join contract |
| **18** | Publish the implementation handoff | Release manifest and downstream reader contract |

| **No skipped chronology** This table is the execution order. The 8–13 numbering visible in Section 15.1 of the Scientific Specification is treated as a list-continuation artifact, not as executable step identifiers. This manual renumbers and expands those planner operations inside the complete 01–18 dependency chronology. |
|----|

# Part III — Exact implementation steps

Every step below is intentionally bounded. For Steps other than 08, 09, and 11, the coding agent implements the named step, executes its tests, emits PASS or FAIL evidence, and stops. For Steps 08, 09, and 11, it implements the step, runs the bounded diagnostic, emits READY_FOR_OWNER_RUN or FAIL evidence, prints the owner commands, and stops; only an owner-full process may later emit PASS.

# 1. Initialize the implementation workspace

| **Step objective** Create the reproducible Python project, serial step runner, test harness, configuration loader, and append-only run evidence without touching scientific data. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | None. |
| **Single active concern** | Initialize the implementation workspace |
| **Run command** | python -m kden_panel run-step 01 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_01_PASS.json |

## 1.1 Inputs and read boundary

- This manual and the Scientific Specification v1.0.

- The existing repository runtime and dependency conventions, if present.

## 1.2 Files the coding agent must implement

- pyproject.toml and lock file

- src/kden_panel/cli.py, contracts.py, hashes.py, and io/atomic.py

- tests/unit/test_step_order.py and test_atomic_publish.py

- config/panel_v1.example.toml and config/panel_v1.toml. The example is portable; the active file is generated from it using the owner-supplied project_root. The coding agent must not invent an external path. If the required project root is unavailable, it writes a blocker and does not emit STEP_01_PASS.json.

## 1.3 Exact implementation sequence

> 1\. Create the required repository layout and a Python package importable as kden_panel.
>
> 2\. Implement run-step, verify-step, status, pause-run, and invalidate-from CLI subcommands.
>
> 3\. Implement the global exclusive lock and preceding-PASS verification shown in Part I.
>
> 4\. Implement canonical SHA-256 hashing for files and sorted directory manifests.
>
> 5\. Implement temporary-write, fsync, hash, and atomic-rename publication. No step may write directly to a final path.
>
> 6\. Freeze dependency versions and record Python, ecCodes/wgrib2, pyarrow, projection, timezone-database, and OS versions in each run manifest.
>
> 7\. Implement explicit diagnostic, owner-full, and validate-only execution scopes for Steps 08, 09, and 11. Omitting --scope for these steps is an error; full acquisition must never be the default.
>
> 8\. Diagnostic scope must enforce the sealed Step 07 limits before issuing any request. It must refuse a request plan exceeding the authorized target-day, request-count, or projected-byte ceiling. During Step 01, this behavior is proved only with synthetic request-plan and diagnostic-scope fixtures under tests/; the production Step 07 artifacts do not yet exist and must not be fabricated.
>
> 9\. Implement READY_FOR_OWNER_RUN and PAUSED states, graceful SIGINT/SIGTERM handling, hash-verified resume using the same run_id, and status reporting that does not require attaching an agent to the running process.

## 1.4 Durable outputs

- Executable project shell

- state/STEP_01_PASS.json

- runs/\<run_id\>/environment.json and test report

- schemas/step_ready_for_owner_run.json

- schemas/step_paused.json

- Machine-readable schemas and synthetic test fixtures for READY_FOR_OWNER_RUN and PAUSED, including resumable owner-run state contracts for Steps 08, 09, and 11. Step 01 must not create live STEP_08, STEP_09, or STEP_11 READY or PAUSED records.

## 1.5 Pass gate

- PASS — A second empty-workspace bootstrap produces the same declared layout.

- PASS — Out-of-order step execution is rejected.

- PASS — A simulated crash before atomic rename leaves no published partial artifact.

- PASS — All unit tests pass from the locked environment.

- PASS — Steps 08, 09, and 11 reject an omitted or unknown execution scope.

- PASS — Diagnostic mode cannot exceed its sealed request, date, or byte limits.

- PASS — Only explicit owner-full mode can schedule or execute the complete acquisition plan; diagnostic mode may inspect plan metadata but cannot schedule work outside the sealed Step 07 limits.

- PASS — A simulated interruption creates PAUSED state and resumes without repeating or losing a completed atomic work unit.

| **Failure behavior** Do not proceed with ad hoc scripts. Repair the project shell until serial ordering and atomic publication are proven. |
|----|

# 2. Resolve and verify sealed upstream sources

| **Step objective** Convert the screenshots and repository discovery into an explicit, read-only source map with exact paths, schemas, hashes, and forbidden roots. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_01 PASS. |
| **Single active concern** | Resolve and verify sealed upstream sources |
| **Run command** | python -m kden_panel run-step 02 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_02_PASS.json |

## 2.1 Inputs and read boundary

- Owner-supplied project_root that contains layer1_baseline, Tmax_MADIS_v3, and Tmax_IEM_v3.

- Existing L1.3 trajectory_long and raw_baseline_panel partitions for 2021–2026.

- Existing L1.5 full_history/checkpoint_panel.parquet.

- Existing MADIS full_history observations, checkpoint_bounds, and manifests.

- Existing Tmax_IEM_v3 yearly truth CSVs; record only at this step, never load their contents into feature code.

## 2.2 Files the coding agent must implement

- src/kden_panel/steps/step_02_sources.py

- schemas/upstream_source_contracts.json

- tests/integration/test_source_preflight.py

## 2.3 Exact implementation sequence

> 1\. Resolve each configured source path. Discovery may locate candidates, but exactly one resolved path must be written to resolved_sources.toml; ambiguous matches fail.
>
> 2\. Open every source read-only and enumerate partitions, columns, row counts, date coverage, file sizes, and SHA-256 hashes without mutating access metadata where avoidable.
>
> 3\. Confirm L1.3 trajectory_long contains wrfsfcf and wrfsubhf TMP:2 m, NN and bilinear_projected values, selected cycle, valid time, temperature_k/f, coordinate era, and source lineage.
>
> 4\. Confirm raw_baseline_panel supplies target_date, checkpoint_id, product, cycle_time_utc, spatial_method, maximum_f, peak-time fields, coverage, and lead bounds.
>
> 5\. Confirm the L1.5 checkpoint panel supplies R_low/R_high, floor activation/delta, raw and floored H/Q15 parents, observation counts, and lineage.
>
> 6\. Create an import denylist containing every evaluation_panel.parquet, truth root, residual/error table, final daily summary, and market-data root.
>
> 7\. Run a write-protection probe using a temporary sibling under the new output root—not inside sealed inputs—and record the upstream trees’ before/after hashes.

## 2.4 Durable outputs

- config/resolved_sources.toml

- runs/\<run_id\>/reports/upstream_inventory.parquet

- config/import_denylist.yaml

- state/STEP_02_PASS.json

## 2.5 Scientific and engineering notes

- The root prefix is deliberately configurable. The screenshots establish relative locations, not a portable absolute POSIX path.

- The L1.6 evaluation panel is explicitly unsafe because it already contains y_tmax_f, residuals, and errors.

## 2.6 Pass gate

- PASS — Each required source resolves uniquely and covers the configured date range or records explicit gaps.

- PASS — All required columns are present or mapped by an approved alias table.

- PASS — Sealed source tree hashes are unchanged.

- PASS — The feature-package import graph cannot open a denylisted path.

| **Failure behavior** Stop on a missing or ambiguous source. Do not guess filenames, reconstruct sealed values, or copy truth-bearing evaluation panels for convenience. |
|----|

# 3. Encode scientific registries and schemas

| **Step objective** Translate the Scientific Specification’s frozen field, operator, model-view, naming, and canonical-table contracts into versioned machine-readable files. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_02 PASS. |
| **Single active concern** | Encode scientific registries and schemas |
| **Run command** | python -m kden_panel run-step 03 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_03_PASS.json |

## 3.1 Inputs and read boundary

- Scientific Specification Appendices A–D and Sections 4–14.

- Resolved Layer 1 registry locations from Step 02.

## 3.2 Files the coding agent must implement

- registries/hrrr_hourly_v1.csv

- registries/hrrr_subhourly_v1.csv

- registries/madis_raw_v1.csv

- registries/operators_v1.yaml

- registries/features_v1.csv

- registries/views_v1.yaml

- schemas/\*.json

- tests/unit/test_registries_v1.py

## 3.3 Exact implementation sequence

> 1\. Encode H01–H44 exactly. Mark H14 STATIC and H16 REUSE_L1 so neither produces ordinary repeated downloads.
>
> 2\. Encode Q01–Q14 exactly. Mark Q05 REUSE_L1 and preserve Q09/Q10 five-minute averages, Q11 fifteen-minute average, and Q13 fifteen-minute accumulation semantics.
>
> 3\. Encode M01–M11 exactly, including raw preservation, derived status, arrays/layers, resolution, QC, and interval metadata.
>
> 4\. Encode CUR, PK, DPK, PREMEAN, PREMIN, PREMAX, PREINT, PRESUM, FRAC, ONSET, GROWTH, SPREAD, and REV with required support and missingness behavior.
>
> 5\. Encode the feature naming grammar and the K/B/S/T/N/R/E/W/C/O/D/Q block registry. Every numeric feature declares canonical unit, source IDs, temporal support, spatial operator, eligibility, and missing reason.
>
> 6\. Encode V0–V4 permissions; A14 tests must be generated from this registry rather than handwritten column lists.
>
> 7\. Create JSON/Arrow-compatible schemas for all canonical tables using Appendix D minimum columns plus implementation lineage columns.

## 3.4 Durable outputs

- Versioned registries with FEATURE_PANEL_V1_0 semantic version

- Schema bundle and registry digest

- state/STEP_03_PASS.json

## 3.5 Pass gate

- PASS — Exactly 44 unique H IDs, 14 unique Q IDs, and 11 unique M IDs exist.

- PASS — Every operator used by a field is defined exactly once.

- PASS — Every feature has a legal source, unit, role, and missingness contract.

- PASS — View-mask tests demonstrate that V1 excludes current-day observation summaries/departures and V3 consumes the ordered sequence rather than V2’s detailed history.

| **Failure behavior** Do not invent aliases or infer GRIB semantics from record numbers. Resolve any mismatch against the Specification before PASS. |
|----|

# 4. Build the Layer 1 checkpoint spine

| **Step objective** Create the target-free six-checkpoint-per-day spine and reuse the sealed baseline/floor geometry that all later tables join against. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_03 PASS. |
| **Single active concern** | Build the Layer 1 checkpoint spine |
| **Run command** | python -m kden_panel run-step 04 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_04_PASS.json |

## 4.1 Inputs and read boundary

- L1.3 raw_baseline_panel and trajectory_long

- Frozen checkpoint, availability-policy, baseline-variant, and station coordinate-era registries

- L1.5 checkpoint_panel.parquet

## 4.2 Files the coding agent must implement

- src/kden_panel/steps/step_04_checkpoint_spine.py

- schemas/checkpoint_spine.json

- tests/integration/test_checkpoint_spine.py

## 4.3 Exact implementation sequence

> 1\. Construct target_day × six checkpoint_id keys from the sealed checkpoint registry, resolving issue_time_local and issue_time_utc with America/Denver.
>
> 2\. Join primary Q15 product/spatial rows using product=wrfsubhf and spatial_method=bilinear_projected; retain native cycle_time_utc and Q15 peak timing.
>
> 3\. Join hourly parents and protected floor geometry by the full available key, never by row order.
>
> 4\. Normalize target_date to target_day only in this adapter; preserve upstream names in a source-column map.
>
> 5\. Copy no target, residual, absolute error, squared error, final CLI, or evaluation-only column.
>
> 6\. Sort deterministically by target_day and checkpoint registry order; write source hashes for every joined row.

## 4.4 Durable outputs

- data/staging/checkpoint_spine_v1/

- reports/checkpoint_spine_join_audit.parquet

- state/STEP_04_PASS.json

## 4.5 Pass gate

- PASS — Exactly one row exists per target_day/checkpoint_id on eligible days (A01).

- PASS — All issue times are timezone-aware and DST-correct.

- PASS — Selected-cycle, peak-time, coordinate-era, and floor lineage match Layer 1 exactly.

- PASS — A11 target-name denylist returns zero columns and zero upstream import paths.

| **Failure behavior** Quarantine duplicate or incomplete keys. Never fill a missing floor with the raw baseline inside the canonical floor field. |
|----|

# 5. Build cycle_manifest

| **Step objective** Materialize the authoritative bounded set of legal retained HRRR cycles per target day and product before any new meteorological acquisition. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_04 PASS. |
| **Single active concern** | Build cycle_manifest |
| **Run command** | python -m kden_panel run-step 05 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_05_PASS.json |

## 5.1 Inputs and read boundary

- checkpoint_spine_v1

- Frozen Policy-A selection, source latency, horizon, completeness, and fallback registries

- Layer 1 source-message provenance

## 5.2 Files the coding agent must implement

- src/kden_panel/steps/step_05_cycle_manifest.py

- tests/acceptance/test_a01_a02_cycle_manifest.py

## 5.3 Exact implementation sequence

> 1\. Read the actual native cycle_init_utc selected for each checkpoint; never hard-code illustrative local labels 07/08/09/10.
>
> 2\. Deduplicate cycles shared by multiple checkpoints and retain selected_by_checkpoint_ids in registry order.
>
> 3\. For each product/cycle, record emulated and actual-first-seen availability when present, basis, policy ID, horizon class, completeness, fallback reason, source inventory hash, and required support envelope.
>
> 4\. Rank retained cycles chronologically within target day/product. The earliest retained cycle has no predecessor revision by design.
>
> 5\. Assert that the primary Q15 feature bundle cycle is the anchor. If hourly/subhourly Policy A diverges, record branch-specific state and fail the primary same-cycle bundle closed.

## 5.4 Durable outputs

- data/canonical/cycle_manifest/

- reports/cycle_parity_audit.parquet

- state/STEP_05_PASS.json

## 5.5 Pass gate

- PASS — One row per target_day/product/cycle_init_utc (A01).

- PASS — Every checkpoint maps to exactly one retained Q15 cycle or an explicit failure.

- PASS — Selected-cycle parity with the checkpoint spine is exact (A02).

- PASS — 09:00/no-predecessor revision state is explicit rather than imputed.

| **Failure behavior** Do not replace a missing selected cycle with a later run, infer cycles from filename text alone, or add older cycles for convenience. |
|----|

# 6. Build the deduplicated request plan

| **Step objective** Turn Layer 1 selected cycles and Q15 peaks into an exact, storage-bounded set of HRRR source messages, valid times, byte-range lookups, and spatial statistics. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_05 PASS. |
| **Single active concern** | Build the deduplicated request plan |
| **Run command** | python -m kden_panel run-step 06 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_06_PASS.json |

## 6.1 Inputs and read boundary

- cycle_manifest

- checkpoint_spine_v1 including Q15 peak times

- H/Q registries and temporal-density classes

## 6.2 Files the coding agent must implement

- src/kden_panel/steps/step_06_request_plan.py

- src/kden_panel/planning.py

- schemas/request_plan.json

- tests/unit/test_valid_time_unions.py

## 6.3 Exact implementation sequence

> 1\. For each target/product/cycle, gather all checkpoints assigned to that cycle and compute one deduplicated valid-time union.
>
> 2\. STATIC requests occur once per grid/version. REUSE_L1 requests are represented as local reads and create zero network requests.
>
> 3\. SPARSE requests include the legal checkpoint brackets and Q15-peak brackets required by each field/operator.
>
> 4\. PATH requests cover the union from the earliest assigned checkpoint through Q15 tau_peak + 2 hours, restricted to W\[d\] and legal forecast horizons.
>
> 5\. For subhourly variables, request only the required 15-minute blocks; preserve interval-start/end requirements for five- and fifteen-minute products.
>
> 6\. Expand requested spatial statistics exactly from the field registry: BI, NN, 3×3, and/or 9×9. Do not multiply network byte estimates by spatial statistic because one message supplies the local tile.
>
> 7\. Generate stable request_id from product, cycle, forecast lead, full selector identity, interval semantics, and source URI identity; deduplicate on request_id.
>
> 8\. Calculate projected request counts, bytes placeholder, extracted-value counts, and per-family density totals.

## 6.4 Durable outputs

- data/staging/request_plan_v1/

- reports/request_plan_summary.json

- reports/reuse_l1_zero_download_audit.parquet

- state/STEP_06_PASS.json

## 6.5 Pass gate

- PASS — Shared-cycle checkpoints do not create duplicate requests.

- PASS — H16 and Q05 produce zero acquisition tasks.

- PASS — No planned cycle lies outside cycle_manifest.

- PASS — Every request has a field ID, full selector, required valid time, spatial set, and support reason.

- PASS — The earliest-to-peak+2h support is reproducible from input rows.

| **Failure behavior** Stop if peak time, assigned checkpoint, horizon, or interval support is ambiguous. Never broaden to an entire GRIB file as a fallback. |
|----|

# 7. Execute the representative pilot

| **Step objective** Prove selector stability, GRIB semantics, spatial parity, MADIS schema feasibility, and the extrapolated full-history cost before bulk acquisition. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_06 PASS. |
| **Single active concern** | Execute the representative pilot |
| **Run command** | python -m kden_panel run-step 07 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_07_PASS.json |

## 7.1 Inputs and read boundary

- request_plan_v1

- Specification Section 15.3 pilot strata

- Archive/source URL builders from sealed Layer 1 provenance

## 7.2 Files the coding agent must implement

- src/kden_panel/steps/step_07_pilot.py

- src/kden_panel/io/http_range.py

- src/kden_panel/io/grib.py

- tests/golden/pilot_cases.yaml

- tests/acceptance/test_a03_a06_pilot.py

## 7.3 Exact implementation sequence

> 1\. Select at least one week in DJF, MAM, JJA, and SON; include early/middle/late archive versions, all checkpoints/cycle positions, both KDEN coordinate eras, and declared MADIS edge cases.
>
> 2\. Fetch each .idx object first. Parse byte offsets and match by parameter, level/layer, step type, and interval metadata; record zero/one/multiple match counts.
>
> 3\. Range-fetch only matched messages. Verify HTTP status, Content-Range, expected length, GRIB message identity, source hash, and decode success.
>
> 4\. Use the exact Layer 1 projected-bilinear and nearest-node geometry or a parity-tested port. Extract required tiles and spatial summaries.
>
> 5\. Validate unit conversions and reconstruct native values within tolerance. Validate snapshot, average, accumulation, and maximum semantics separately.
>
> 6\. Pilot MADIS extended variables against raw files without modifying the existing temperature outputs.
>
> 7\. Record requests, bytes, retries, wall time, decode time, extracted values, selector hit rates, min/max/quantiles, missingness, and quarantine counts.
>
> 8\. Extrapolate full-history storage and wall time; write pilot_authorization.json and the bounded diagnostic_scope.json. Owner cost approval is the sole pre-acquisition approval gate, while every full-history acquisition’s actual start, pause/stop, and resume remain separate owner-controlled actions. Generate the exact owner start, status, pause, and resume commands for Steps 08, 09, and 11.

## 7.4 Durable outputs

- runs/\<run_id\>/pilot/ compact extracts

- reports/pilot_evidence.md plus machine tables

- reports/pilot_cost_ledger.json

- config/pilot_authorization.json

- state/STEP_07_PASS.json

- config/diagnostic_scope.json

- reports/owner_full_run_commands.md

## 7.5 Scientific and engineering notes

- A signed authorization may be a small JSON file containing accepted projected bytes, storage, wall time, pilot report hash, approver, and timestamp.

- Pilot message bytes remain quarantined or cached according to the same verified-write rules used in production.

## 7.6 Pass gate

- PASS — All 44 hourly and 14 subhourly selectors resolve exactly once on supported pilot inventories (A03).

- PASS — Step/interval metadata pass A04.

- PASS — Unit round trips pass A05.

- PASS — Spatial weights, coordinate eras, tile centers, and Layer 1 TMP parity pass A06.

- PASS — Cost ledger reconciles and owner authorization is signed/hash-bound.

- PASS — Diagnostic limits are explicit, hash-bound, and materially smaller than the full-history request plan.

- PASS — Owner-full commands are generated but have not been executed by the coding agent.

- PASS — The authorization file states that cost approval and full-run execution authority are separate decisions.

| **Failure behavior** Do not start bulk acquisition while any selector is ambiguous, any interval semantics are unresolved, spatial parity fails, or cost authorization is absent. |
|----|

# 8. Acquire and extract wrfsfcf

| **Step objective** Execute only the authorized hourly request-plan rows and publish compact hourly field/tile extracts with complete lineage. |
|----|

<table>
<colgroup>
<col style="width: 22%" />
<col style="width: 77%" />
</colgroup>
<thead>
<tr>
<th style="text-align: center;"><p><strong>Contract item</strong></p></th>
<th style="text-align: center;"><p><strong>Binding value</strong></p></th>
</tr>
</thead>
<tbody>
<tr>
<td style="text-align: center;"><p><strong>Depends on</strong></p></td>
<td><p>STEP_07 PASS and matching pilot authorization hash.</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Single active concern</strong></p></td>
<td><p>Acquire and extract wrfsfcf</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Agent diagnostic</strong></p></td>
<td><p>python -m kden_panel run-step 08 --scope diagnostic --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner start</strong></p></td>
<td><p>python -m kden_panel run-step 08 --scope owner-full --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner status</strong></p></td>
<td><p>python -m kden_panel status --config config/panel_v1.toml --run-id &lt;same-id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner pause</strong></p></td>
<td><p>python -m kden_panel pause-run --config config/panel_v1.toml --run-id &lt;same-id&gt;</p>
<p>(pause-run sends a graceful termination request to the process recorded for the owner-full run. The process completes or rolls back its current atomic work unit, writes PAUSED, releases the lock, and exits without PASS. It never deletes completed artifacts.)</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner resume</strong></p></td>
<td><p>python -m kden_panel run-step 08 --scope owner-full --resume --config config/panel_v1.toml --run-id &lt;same-id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Validation without acquisition</strong></p></td>
<td><p>python -m kden_panel run-step 08 --scope validate-only --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Coding-agent handoff</strong></p></td>
<td><p>state/STEP_08_READY_FOR_OWNER_RUN.json</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Full completion</strong></p></td>
<td><p>state/STEP_08_PASS.json, written only after a successful owner-full acquisition and terminal validation</p></td>
</tr>
</tbody>
</table>

## 8.1 Inputs and read boundary

- Authorized wrfsfcf request-plan subset

- H01–H44 registry

- cycle_manifest and coordinate-era registry

- Verified range-fetch and GRIB extraction code from Step 07

## 8.2 Files the coding agent must implement

- src/kden_panel/steps/step_08_wrfsfcf.py

- tests/integration/test_wrfsfcf_resume.py

- tests/acceptance/test_wrfsfcf_inventory.py

## 8.3 Exact implementation sequence

> 1\. Implement and test the step using unit, golden, integration, and bounded diagnostic scopes. Before any full-history execution, verify the bounded results, write STEP_08_READY_FOR_OWNER_RUN.json, print the exact owner start/status/pause/resume commands, and stop the coding-agent task.
>
> 2\. Process partitions in deterministic target-year/month/cycle order with a configured bounded network worker count internal to this step. This is not cross-step parallelism.
>
> 3\. Skip H16 network acquisition and link to the sealed Layer 1 hourly TMP path. Store H14 once per HRRR grid/version and reference it by lineage.
>
> 4\. For each planned request, verify the current .idx hash/identity against pilot-supported semantics before range retrieval.
>
> 5\. Range-fetch, verify, decode, extract required KDEN BI/NN/tile statistics, convert units, and write one append-only staging partition.
>
> 6\. Write source response, selector, byte range, source SHA-256, decoded identity, coordinate era, nodes/weights, and extracted-value counts to the retrieval ledger.
>
> 7\. Discard transient message bytes only after Parquet write, partition manifest, hashes, and ledger reconciliation succeed.
>
> 8\. On resume, recompute published-partition hashes before skipping. Never trust a done flag alone.

## 8.4 Durable outputs

- data/staging/hrrr_hourly_extract/ partitioned by target year/month/cycle

- runs/\<run_id\>/manifests/wrfsfcf_retrieval.parquet

- reports/wrfsfcf_cost_ledger.json

- state/STEP_08_PASS.json

- state/STEP_08_PAUSED.json only when an owner-full run is interrupted.

- state/STEP_08_READY_FOR_OWNER_RUN.json after successful bounded diagnostics.

## 8.5 Pass gate

- PASS — Every authorized request is success, confirmed missing, or quarantined with reason; counts reconcile (A13).

- PASS — No unplanned request or full-domain GRIB retention exists.

- PASS — H16 reuse parity is exact and H14 is not duplicated per valid time.

- PASS — Published partitions are hash-valid, sorted, schema-valid, and resume-safe.

- PASS — Diagnostic executions remained within the sealed Step 07 limits and could not schedule or issue any request outside the authorized diagnostic scope.

- PASS — STEP_08_PASS.json records execution_scope=owner-full and cannot be emitted by diagnostic mode.

- PASS — If an owner run was interrupted, it resumed from hash-verified durable progress without duplicating completed work; if no interruption occurred, the synthetic interruption/resume test from Step 01 remains the required evidence.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th><p><strong>Failure behavior</strong> Fail the affected partition on selector drift, semantics drift, response mismatch, decode error, or hash disagreement. Do not reinterpret or silently widen the request.</p>
<p>A coding agent must never invoke --scope owner-full, remain attached to the full acquisition, or continuously poll it. Its acquisition-step assignment ends at READY_FOR_OWNER_RUN unless the owner later requests validation of an already completed or paused run.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 9. Acquire and extract wrfsubhf

| **Step objective** Execute only the authorized subhourly request-plan rows while preserving each 15-minute block’s snapshot/average/accumulation semantics. |
|----|

<table>
<colgroup>
<col style="width: 22%" />
<col style="width: 77%" />
</colgroup>
<thead>
<tr>
<th style="text-align: center;"><p><strong>Contract item</strong></p></th>
<th style="text-align: center;"><p><strong>Binding value</strong></p></th>
</tr>
</thead>
<tbody>
<tr>
<td style="text-align: center;"><p><strong>Depends on</strong></p></td>
<td><p>STEP_08 PASS.</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Single active concern</strong></p></td>
<td><p>Acquire and extract wrfsubhf</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Agent diagnostic</strong></p></td>
<td><p>python -m kden_panel run-step 09 --scope diagnostic --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner start</strong></p></td>
<td><p>python -m kden_panel run-step 09 --scope owner-full --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner status</strong></p></td>
<td><p>python -m kden_panel status --config config/panel_v1.toml --run-id &lt;same-id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner pause</strong></p></td>
<td><p>python -m kden_panel pause-run --config config/panel_v1.toml --run-id &lt;same-id&gt;</p>
<p>(pause-run sends a graceful termination request to the process recorded for the owner-full run. The process completes or rolls back its current atomic work unit, writes PAUSED, releases the lock, and exits without PASS. It never deletes completed artifacts.)</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner resume</strong></p></td>
<td><p>python -m kden_panel run-step 09 --scope owner-full --resume --config config/panel_v1.toml --run-id &lt;same-id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Validation without acquisition</strong></p></td>
<td><p>python -m kden_panel run-step 09 --scope validate-only --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Coding-agent handoff</strong></p></td>
<td><p>state/STEP_09_READY_FOR_OWNER_RUN.json</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Full completion</strong></p></td>
<td><p>state/STEP_09_PASS.json, written only after a successful owner-full acquisition and terminal validation.</p></td>
</tr>
</tbody>
</table>

## 9.1 Inputs and read boundary

- Authorized wrfsubhf request-plan subset

- Q01–Q14 registry

- cycle_manifest and coordinate-era registry

- Existing Layer 1 Q15 TMP trajectory

## 9.2 Files the coding agent must implement

- src/kden_panel/steps/step_09_wrfsubhf.py

- tests/integration/test_wrfsubhf_blocks.py

- tests/acceptance/test_subhourly_semantics.py

## 9.3 Exact implementation sequence

> 1\. Implement and test the step using unit, golden, integration, and bounded diagnostic scopes. Before any full-history execution, verify the bounded results, write STEP_09_READY_FOR_OWNER_RUN.json, print the exact owner start/status/pause/resume commands, and stop the coding-agent task.
>
> 2\. Process the subhourly source separately from hourly; do not assume identical record ordering or block counts.
>
> 3\. Skip Q05 network acquisition and link to the sealed Layer 1 wrfsubhf TMP path.
>
> 4\. Select each repeated block using full message identity plus interval metadata and valid time, never record number.
>
> 5\. Retain Q09/Q10 interval start/end and midpoint/end matching metadata; do not relabel five-minute averages as snapshots.
>
> 6\. Retain Q11 as a preceding fifteen-minute average and Q13 as a preceding fifteen-minute accumulation. Q13 is never differenced again.
>
> 7\. Extract and publish the same lineage, coordinate, spatial, unit, response, and hash evidence as Step 08.
>
> 8\. Reconcile requests and discard verified transient message bytes only after durable publication.

## 9.4 Durable outputs

- data/staging/hrrr_subhourly_extract/

- runs/\<run_id\>/manifests/wrfsubhf_retrieval.parquet

- reports/wrfsubhf_cost_ledger.json

- state/STEP_09_PASS.json

- state/STEP_09_PAUSED.json only when an owner-full run is interrupted.

- state/STEP_09_READY_FOR_OWNER_RUN.json after successful bounded diagnostics.

## 9.5 Pass gate

- PASS — All requested blocks resolve by identity and interval semantics.

- PASS — Q05 produces zero network downloads and matches Layer 1 exactly.

- PASS — Average and accumulation fields preserve interval boundaries (A04).

- PASS — Request, byte, retry, extraction, and quarantine ledgers reconcile (A13).

- PASS — Diagnostic executions remained within the sealed Step 07 limits and could not schedule or issue any request outside the authorized diagnostic scope.

- PASS — STEP_09_PASS.json records execution_scope=owner-full and cannot be emitted by diagnostic mode.

- PASS — If an owner run was interrupted, it resumed from hash-verified durable progress without duplicating completed work; if no interruption occurred, the synthetic interruption/resume test from Step 01 remains the required evidence.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th><p><strong>Failure behavior</strong> Quarantine any file whose repeated-block identity is ambiguous. Never use a nearby block merely because it has the expected record number.</p>
<p>A coding agent must never invoke --scope owner-full, remain attached to the full acquisition, or continuously poll it. Its acquisition-step assignment ends at READY_FOR_OWNER_RUN unless the owner later requests validation of an already completed or paused run.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 10. Assemble hrrr_point_trajectory

| **Step objective** Union the two new compact extracts with the sealed Layer 1 temperature trajectories into one normalized HRRR reconstruction authority. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_09 PASS. |
| **Single active concern** | Assemble hrrr_point_trajectory |
| **Run command** | python -m kden_panel run-step 10 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_10_PASS.json |

## 10.1 Inputs and read boundary

- hrrr_hourly_extract

- hrrr_subhourly_extract

- Layer 1 trajectory_long TMP paths

- cycle_manifest and hrrr_point_trajectory schema

## 10.2 Files the coding agent must implement

- src/kden_panel/steps/step_10_hrrr_trajectory.py

- tests/integration/test_hrrr_union.py

- tests/acceptance/test_a07_support.py

## 10.3 Exact implementation sequence

> 1\. Adapt Layer 1 column names to the canonical schema without changing values, cycles, valid times, spatial methods, coordinate eras, or source lineage.
>
> 2\. Map product/spatial names to the frozen vocabulary and attach H16/Q05 field IDs to reused TMP rows.
>
> 3\. Union reused and newly extracted rows, preserving one record per canonical HRRR key and rejecting collisions with unequal values or lineage.
>
> 4\. Materialize forecast_lead_min, step_type, interval_start/end, native/canonical units, spatial_stat, tile_shape, coverage, source hash, and derivation version.
>
> 5\. Partition by target year/month/product/cycle token and sort by the full canonical key.
>
> 6\. Generate completeness masks against the request plan and cycle manifest; absent optional fields remain explicit rather than causing row splicing.

## 10.4 Durable outputs

- data/canonical/hrrr_point_trajectory/

- reports/hrrr_union_and_coverage.parquet

- state/STEP_10_PASS.json

## 10.5 Pass gate

- PASS — Canonical HRRR keys are unique.

- PASS — Reused H16/Q05 values are value-identical to Layer 1.

- PASS — Every non-reuse request resolves to a trajectory row or explicit missing/quarantine record.

- PASS — All temporal support is same-cycle and coverage fractions are recorded (A07).

- PASS — No hourly/subhourly cross-product composite has yet been computed.

| **Failure behavior** Fail on unequal duplicate keys, unregistered units, cross-cycle collisions, or loss of interval/source lineage. |
|----|

# 11. Acquire the extended MADIS variables

| **Step objective** Extend the existing KDEN HFMETAR acquisition to M02–M11 while leaving the sealed temperature observation, checkpoint-bound, and floor artifacts unchanged. |
|----|

<table>
<colgroup>
<col style="width: 22%" />
<col style="width: 77%" />
</colgroup>
<thead>
<tr>
<th style="text-align: center;"><p><strong>Contract item</strong></p></th>
<th style="text-align: center;"><p><strong>Binding value</strong></p></th>
</tr>
</thead>
<tbody>
<tr>
<td style="text-align: center;"><p><strong>Depends on</strong></p></td>
<td><p>STEP_10 PASS.</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Single active concern</strong></p></td>
<td><p>Acquire the extended MADIS variables</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Agent diagnostic</strong></p></td>
<td><p>python -m kden_panel run-step 11 --scope diagnostic --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner start</strong></p></td>
<td><p>python -m kden_panel run-step 11 --scope owner-full --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner status</strong></p></td>
<td><p>python -m kden_panel status --config config/panel_v1.toml --run-id &lt;same-id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner pause</strong></p></td>
<td><p>python -m kden_panel pause-run --config config/panel_v1.toml --run-id &lt;same-id&gt;</p>
<p>(pause-run sends a graceful termination request to the process recorded for the owner-full run. The process completes or rolls back its current atomic work unit, writes PAUSED, releases the lock, and exits without PASS. It never deletes completed artifacts.)</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Owner resume</strong></p></td>
<td><p>python -m kden_panel run-step 11 --scope owner-full --resume --config config/panel_v1.toml --run-id &lt;same-id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Validation without acquisition</strong></p></td>
<td><p>python -m kden_panel run-step 11 --scope validate-only --config config/panel_v1.toml --run-id &lt;id&gt;</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Coding-agent handoff</strong></p></td>
<td><p>state/STEP_11_READY_FOR_OWNER_RUN.json</p></td>
</tr>
<tr>
<td style="text-align: center;"><p><strong>Full completion</strong></p></td>
<td><p>state/STEP_11_PASS.json, written only after a successful owner-full acquisition and terminal validation.</p></td>
</tr>
</tbody>
</table>

## 11.1 Inputs and read boundary

- Existing Tmax_MADIS_v3 build code, observations, checkpoint_bounds, and manifests

- M01–M11 registry

- Historical pseudo-live observation-time policy

## 11.2 Files the coding agent must implement

- src/kden_panel/steps/step_11_madis_acquire.py

- src/kden_panel/io/madis.py

- tests/golden/madis_edge_cases.\*

- tests/integration/test_madis_extension_nonmutation.py

## 11.3 Exact implementation sequence

> 1\. Implement and test the step using unit, golden, integration, and bounded diagnostic scopes. Before any full-history execution, verify the bounded results, write STEP_11_READY_FOR_OWNER_RUN.json, print the exact owner start/status/pause/resume commands, and stop the coding-agent task.
>
> 2\. Reuse the existing eight-route HFMETAR source adapter and manifest behavior where possible. The compatible HFMETAR product remains mandatory; do not substitute standard point/METAR data.
>
> 3\. Parse and preserve raw TD, station P, wind speed/direction and averaging semantics, gust, visibility, precipitation rate, one-hour amount and window, sky-cover layer arrays, cloud-base arrays, and present-weather codes.
>
> 4\. Preserve raw values, units, resolution, report type, observation time, receipt/insertion times when actually present, provider flags, MADIS QC-stage flags, source URL/file/hour, and source hash.
>
> 5\. Mark provider-derived variables as derived. Do not manufacture missing receipt timestamps or backfill later QC times.
>
> 6\. Apply only conservative as-of-local QC: station identity, provider validity, gross physical bounds, and past-window consistency. Any potentially future-aware QC remains audit-only.
>
> 7\. Write one raw-variable-preserving long extract. Do not compute checkpoint summaries in this step.
>
> 8\. Verify before/after hashes of existing M01 observations, checkpoint_bounds, and L1.5 floor panel.

## 11.4 Durable outputs

- data/staging/madis_extended_raw/ partitioned by target year/day

- runs/\<run_id\>/manifests/madis_extended_retrieval.parquet

- reports/madis_nonmutation_audit.json

- state/STEP_11_PASS.json

- state/STEP_11_PAUSED.json only when an owner-full run is interrupted.

- state/STEP_11_READY_FOR_OWNER_RUN.json after successful bounded diagnostics.

## 11.5 Pass gate

- PASS — M02–M11 raw identities and units are preserved; missing variables are explicit.

- PASS — Existing M01 temperature and floor artifacts are byte/value unchanged.

- PASS — Source request/missing-hour/hash ledgers reconcile.

- PASS — No final CLI truth or later daily summary is imported.

- PASS — Diagnostic executions remained within the sealed Step 07 limits and could not schedule or issue any request outside the authorized diagnostic scope.

- PASS — STEP_11_PASS.json records execution_scope=owner-full and cannot be emitted by diagnostic mode.

- PASS — If an owner run was interrupted, it resumed from hash-verified durable progress without duplicating completed work; if no interruption occurred, the synthetic interruption/resume test from Step 01 remains the required evidence.

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th><p><strong>Failure behavior</strong> Do not overwrite Layer 1.5 outputs, use an incompatible product, fabricate receipt time, or promote unverified later-stage QC into eligibility.</p>
<p>A coding agent must never invoke --scope owner-full, remain attached to the full acquisition, or continuously poll it. Its acquisition-step assignment ends at READY_FOR_OWNER_RUN unless the owner later requests validation of an already completed or paused run.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# 12. Build madis_observation_sequence

| **Step objective** Create the normalized ordered observation authority and a checkpoint-context child table for selected-cycle expectations, including candidate intervals and bounded causal innovations. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_11 PASS. |
| **Single active concern** | Build madis_observation_sequence |
| **Run command** | python -m kden_panel run-step 12 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_12_PASS.json |

## 12.1 Inputs and read boundary

- Existing M01 observation sequence

- madis_extended_raw

- cycle_manifest

- hrrr_point_trajectory

- MADIS base-sequence and selected-cycle-expectation child schemas

## 12.2 Files the coding agent must implement

- src/kden_panel/steps/step_12_madis_sequence.py

- src/kden_panel/features/observation_matching.py

- schemas/madis_selected_cycle_expectation.json

- tests/unit/test_candidate_geometry.py

- tests/acceptance/test_a09_a10_madis.py

## 12.3 Exact implementation sequence

> 1\. Union sealed M01 rows and extended M02–M11 rows under canonical observation keys; preserve raw arrays/codes through sidecar columns or normalized child records.
>
> 2\. For whole-degree-C temperature c, compute k_low=ceil((18c+311)/10) and k_high=ceil((18c+329)/10)-1 exactly with integer arithmetic; retain low/high/mid/width.
>
> 3\. Assign target_day using W\[d\], not a naive local date.
>
> 4\. Set availability_time_used_utc to observation_time_utc for historical pseudo-live replay and receipt_time_utc for live-mode tests only when receipt is present. Record availability_basis.
>
> 5\. For every legal checkpoint context, compute selected-cycle expected values at each observation time using only that checkpoint's selected cycle. Write them to madis_selected_cycle_expectation keyed by the base observation key + checkpoint_id + selected_cycle_init_utc; never duplicate base observation rows or place an ambiguous checkpoint-dependent scalar on the base sequence. Continuous Q15 T/Td/P/U/V may be same-cycle interpolated; onset fields use nearest snapshots with signed offset.
>
> 6\. Compute c_asof as the newest retained cycle available no later than the observation’s legal availability time. If none exists, causal innovation is null with no_causal_vintage reason.
>
> 7\. Never subtract wind direction angles or cloud percent from ASOS categories. Use U/V and the Specification’s cloud-interval algebra.
>
> 8\. Sort by station_id, target_day, availability_time_used_utc, observation_time_utc, source hash, and variable code.

## 12.4 Durable outputs

- data/canonical/madis_observation_sequence/

- data/canonical/madis_selected_cycle_expectation/

- reports/madis_matching_audit.parquet

- state/STEP_12_PASS.json

## 12.5 Pass gate

- PASS — Historical observations used by a checkpoint never exceed issue time; live receipt-cutoff tests also pass (A09).

- PASS — Known 20 C, 21 C, and 25 C cases reproduce {68}, {69,70}, and {77}; property tests pass A10.

- PASS — Causal expected values use only retained cycles available as of each observation.

- PASS — Base observation keys and child observation+checkpoint+cycle keys are each unique; the join cannot multiply checkpoint rows.

- PASS — Selected-cycle departures and causal innovations are distinct named fields and cannot be confused.

| **Failure behavior** Fail on future observations, fabricated receipt state, cross-cycle interpolation, unsupported cloud arithmetic, or loss of raw resolution/QC lineage. |
|----|

# 13. Derive NWP and baseline feature blocks

| **Step objective** Generate only the structural K/B/S/T/N/R/E/W/C/Q blocks from the checkpoint spine and canonical HRRR trajectories. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_12 PASS. |
| **Single active concern** | Derive NWP and baseline feature blocks |
| **Run command** | python -m kden_panel run-step 13 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_13_PASS.json |

## 13.1 Inputs and read boundary

- checkpoint_spine_v1

- cycle_manifest

- hrrr_point_trajectory

- operator and feature registries

- No MADIS sequence input is permitted in this step except already-sealed floor geometry carried by Layer 1.

## 13.2 Files the coding agent must implement

- src/kden_panel/steps/step_13_structural_features.py

- src/kden_panel/features/temporal.py

- src/kden_panel/features/spatial.py

- src/kden_panel/features/composites.py

- src/kden_panel/features/solar.py

- tests/acceptance/test_a07_a08_features.py

## 13.3 Exact implementation sequence

> 1\. Materialize K lineage, B baseline/floor geometry, and deterministic solar/calendar fields at the effective coordinate era and issue time.
>
> 2\. Apply CUR, PK, DPK, PRE\*, FRAC, ONSET, GROWTH, SPREAD, and named composites exactly from the registries. Operators accept explicit same-cycle support arrays; they may not query later cycles.
>
> 3\. Integrate flux averages using their declared interval duration; sum interval precipitation; never difference accumulations or maxima as snapshots.
>
> 4\. Compute same-cycle cross-product Q15–H and other composites only when cycle_init_utc agrees. Otherwise leave null and record cross_product_cycle_mismatch.
>
> 5\. Derive specific humidity from DPT2m+PRES, RH from TMP+DPT, thickness, lapse proxy, shear, advection proxy, net radiation, guarded EF/Bowen, snow density proxy, and other Appendix A composites with versioned formulas.
>
> 6\. Compute only the frozen revision shortlist. Evaluate new and prior cycles on the new cycle’s identical valid-time support; separate peak-time revision.
>
> 7\. For every feature, write support counts, coverage fraction, source IDs, missing reason, and derivation version to a feature-lineage sidecar.

## 13.4 Durable outputs

- data/staging/structural_feature_blocks/

- data/staging/structural_feature_lineage/

- reports/revision_common_support.parquet

- state/STEP_13_PASS.json

## 13.5 Pass gate

- PASS — No current-day MADIS sequence/summary column enters structural staging beyond sealed Layer 1 floor geometry.

- PASS — Temporal operators use named same-cycle support and record coverage (A07).

- PASS — Revisions use identical support and 09:00 is null by design (A08).

- PASS — Cross-product mismatches are null/flagged, never silently spliced.

- PASS — All numeric columns satisfy the naming/unit registry.

| **Failure behavior** Fail the affected feature on unsupported semantics or cycle mismatch. Never reacquire source data merely to change a deterministic summary formula. |
|----|

# 14. Derive observation and departure blocks

| **Step objective** Generate only the checkpoint-legal O/D/Q observation summaries and selected-cycle batch departures for V2. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_13 PASS. |
| **Single active concern** | Derive observation and departure blocks |
| **Run command** | python -m kden_panel run-step 14 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_14_PASS.json |

## 14.1 Inputs and read boundary

- madis_observation_sequence

- madis_selected_cycle_expectation

- checkpoint_spine_v1

- observation-summary feature registry

- No training labels or structural feature output values are required except checkpoint keys/cycles.

## 14.2 Files the coding agent must implement

- src/kden_panel/steps/step_14_observation_features.py

- src/kden_panel/features/observations.py

- tests/golden/test_observation_windows.py

- tests/acceptance/test_observation_cutoffs.py

## 14.3 Exact implementation sequence

> 1\. For each checkpoint, filter legal observations in W\[d\] by the configured historical/live availability basis before computing any summary.
>
> 2\. Compute temperature latest interval, R_low/R_high parity, elapsed extrema, time since R_low, Theil–Sen slopes, slope contrasts, counts, ages, gaps, and null reason codes.
>
> 3\. Compute declared dewpoint, pressure, U/V wind, gust, visibility, precipitation, sky/ceiling, weather-code, and completeness summaries over frozen windows.
>
> 4\. Require the registry’s minimum report count and maximum internal gap for each slope. Insufficient support yields null+n_obs+max_gap+reason.
>
> 5\. Join madis_selected_cycle_expectation on the complete observation+checkpoint+selected-cycle key, then compute DEP level/trend fields from selected_cycle_expected_value and modeled slopes. Preserve interpolation offset, candidate width, source age, and analogue limitations; reject any row-multiplying join.
>
> 6\. Use cloud-category interval distances, opaque mismatch, and ceiling-threshold mismatch; never simple percent subtraction.
>
> 7\. Do not summarize the detailed causal innovation stream into V2 eligibility unless a future registry version explicitly permits it. Preserve diagnostic-only fields separately.

## 14.4 Durable outputs

- data/staging/observation_feature_blocks/

- data/staging/observation_feature_lineage/

- reports/observation_window_audit.parquet

- state/STEP_14_PASS.json

## 14.5 Pass gate

- PASS — Every contributing observation is legal at its checkpoint (A09).

- PASS — R_low/R_high and temperature candidate summaries reproduce sealed Layer 1 bounds where coverage overlaps.

- PASS — Insufficient trends are null with complete reasons rather than zero-filled.

- PASS — Selected-cycle departures and causal diagnostics have different registry roles.

- PASS — No label, post-checkpoint report, or final daily summary is loaded.

| **Failure behavior** Fail on a cutoff violation, unstated imputation, unsupported analogue arithmetic, or loss of observation/QC provenance. |
|----|

# 15. Assemble checkpoint_features and view registry

| **Step objective** Join the two independently derived feature staging products onto the checkpoint spine and publish the complete target-free wide panel plus machine-enforced model views. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_14 PASS. |
| **Single active concern** | Assemble checkpoint_features and view registry |
| **Run command** | python -m kden_panel run-step 15 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_15_PASS.json |

## 15.1 Inputs and read boundary

- checkpoint_spine_v1

- structural_feature_blocks

- observation_feature_blocks

- feature registry and views_v1.yaml

## 15.2 Files the coding agent must implement

- src/kden_panel/steps/step_15_checkpoint_features.py

- src/kden_panel/views.py

- tests/acceptance/test_a01_a11_a14_panel.py

## 15.3 Exact implementation sequence

> 1\. Start from checkpoint_spine_v1 and left-join structural staging by target_day+checkpoint_id and observation staging by the same key. Row multiplication is an error.
>
> 2\. Order columns deterministically: K, B, S, T, N, R, E, W, C, O, D, Q; within a block follow feature registry order.
>
> 3\. Attach feature_spec_version, derivation_version, policy IDs, source hashes, completeness masks, and feature-registry digest.
>
> 4\. Apply an allowlist generated from the registry and a denylist for y\_\*, target/truth, residual, error, final-summary, post-event, market, and evaluation-only names.
>
> 5\. Generate model-view manifests V0–V4 as column IDs and lineage predicates. V1 excludes O/D and detailed current-day MADIS; V2 includes permitted O/D; V3 points to V1 plus the sequence reader, not a wider checkpoint table; V4 declares t0 non-overlap.
>
> 6\. Write the panel without labels. Do not create residual Y−B columns.

## 15.4 Durable outputs

- data/canonical/checkpoint_features_candidate/

- data/canonical/feature_registry_v1.parquet

- data/canonical/model_view_masks_v1.json

- state/STEP_15_PASS.json

## 15.5 Pass gate

- PASS — One row per target_day/checkpoint_id with no multiplication (A01).

- PASS — Target/residual/final-summary schema and import checks pass A11.

- PASS — V0–V4 permissions are machine-readable and unit-tested; V1/V2/V3 satisfy A14.

- PASS — Every column maps to one registry row and declared lineage.

- PASS — Panel partition order and schema are deterministic.

| **Failure behavior** Abort publication on any unexpected column, duplicate key, missing registry row, forbidden lineage, or view-mask ambiguity. |
|----|

# 16. Run acceptance, reproducibility, and freeze

| **Step objective** Execute A01–A14, leakage audits, sealed-input nonmutation checks, and an independent value-reproducibility rerun before promoting the candidate panel. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_15 PASS. |
| **Single active concern** | Run acceptance, reproducibility, and freeze |
| **Run command** | python -m kden_panel run-step 16 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_16_PASS.json |

## 16.1 Inputs and read boundary

- All canonical/staging manifests and candidate checkpoint_features

- A01–A14 executable tests

- Fresh temporary output root for the independent rerun

## 16.2 Files the coding agent must implement

- src/kden_panel/steps/step_16_acceptance.py

- tests/acceptance/test_a01_to_a14.py

- schemas/feature_release_manifest.json

## 16.3 Exact implementation sequence

> 1\. Run A01–A14 and emit one machine record per gate with evidence paths, counts, tolerances, and failures.
>
> 2\. Run explicit leakage tests: source availability \<= issue time; historical observation time \<= issue time; live receipt time \<= issue time; no later cycles, later observations, truth, market, or future-aware QC.
>
> 3\. Rebuild the complete candidate from sealed canonical inputs into a new temporary root using the same config and code version.
>
> 4\. Compare sorted schemas, keys, null masks, values, lineage, view masks, and partition manifests. Value-identical is mandatory; byte-identical is required when the writer environment is identical and deterministic.
>
> 5\. Recompute hashes of all sealed upstream inputs and verify nonmutation.
>
> 6\. Atomically promote checkpoint_features_candidate to data/release/FEATURE_PANEL_V1_0/checkpoint_features only after every gate passes.
>
> 7\. Write RELEASE_FROZEN marker containing config, code, registry, schema, input, output, and acceptance hashes.

## 16.4 Durable outputs

- data/release/FEATURE_PANEL_V1_0/checkpoint_features/

- reports/acceptance_A01_A14.parquet

- reports/reproducibility.json

- data/release/FEATURE_PANEL_V1_0/RELEASE_FROZEN.json

- state/STEP_16_PASS.json

## 16.5 Pass gate

- PASS — A01–A14 all PASS with no waived critical gate.

- PASS — Independent rebuild is value-identical under canonical ordering (A12).

- PASS — Cost ledgers reconcile across HRRR and MADIS (A13).

- PASS — Sealed inputs are unchanged.

- PASS — Frozen release contains no target and cannot be modified without a new version.

| **Failure behavior** Do not publish or join truth when any gate fails. Preserve the candidate, rerun output, and evidence for diagnosis; repair the earliest responsible step and invalidate downstream PASS records. |
|----|

# 17. Build isolated training_labels

| **Step objective** Create the curated target-day truth sidecar only after the feature release is frozen, with no path from label code back into feature generation or production inference. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_16 PASS and RELEASE_FROZEN marker. |
| **Single active concern** | Build isolated training_labels |
| **Run command** | python -m kden_panel run-step 17 --config config/panel_v1.toml --run-id \<id\> --label-authorized |
| **Completion evidence** | state/STEP_17_PASS.json |

## 17.1 Inputs and read boundary

- Tmax_IEM_v3/year=YYYY/kden_tmax_truth_YYYY.csv

- Truth schema, source registry, and exception ledger

- Frozen feature target-day coverage used only for an anti-join report

## 17.2 Files the coding agent must implement

- src/kden_panel/steps/step_17_training_labels.py

- src/kden_panel/training_reader.py

- tests/acceptance/test_truth_isolation.py

## 17.3 Exact implementation sequence

> 1\. Launch this step in a separate label-authorized process. Feature-building modules remain unable to import or open the truth root.
>
> 2\. Read yearly truth CSVs, validate schema/source-regime/exception lineage, and preserve y_iem_cli_raw_f for audit while using y_tmax_f as the authoritative target.
>
> 3\. Validate one row per target_day and whole-degree integrality/tolerance according to the truth handoff. Preserve QC and source regime; do not expose them as inference features.
>
> 4\. Write training_labels partitioned by year with target_day as the only ordinary join key.
>
> 5\. Produce anti-join coverage reports against frozen features without copying labels into checkpoint_features.
>
> 6\. Implement a training-only reader that requires an explicit label_authorized=True capability, loads a frozen feature view, joins y_tmax_f by target_day, and groups all six checkpoints of a day in the same fold.
>
> 7\. Implement a production reader whose dependency graph contains no truth package or path configuration.

## 17.4 Durable outputs

- data/release/FEATURE_PANEL_V1_0/training_labels/

- reports/label_coverage_and_exceptions.parquet

- training_reader API and production_reader isolation test

- state/STEP_17_PASS.json

## 17.5 Pass gate

- PASS — Exactly one curated label per eligible target_day or explicit exception.

- PASS — checkpoint_features hashes are unchanged.

- PASS — Production reader cannot resolve/import the truth root.

- PASS — Training join occurs only after view selection and feature freeze.

- PASS — Fold helper groups all checkpoints from one target day together.

| **Failure behavior** Never load the L1.6 evaluation panel wholesale, write y_tmax_f into checkpoint_features, or expose truth lineage to inference code. |
|----|

# 18. Publish the implementation handoff

| **Step objective** Package the frozen normalized tables, schemas, registries, view masks, evidence, and reader APIs so the modeling agent can begin without interpreting acquisition details. |
|----|

| **Contract item** | **Binding value** |
|:--:|----|
| **Depends on** | STEP_17 PASS. |
| **Single active concern** | Publish the implementation handoff |
| **Run command** | python -m kden_panel run-step 18 --config config/panel_v1.toml --run-id \<id\> |
| **Completion evidence** | state/STEP_18_PASS.json |

## 18.1 Inputs and read boundary

- Frozen feature release

- Isolated training_labels

- All PASS records, registries, schemas, acceptance reports, and cost ledgers

## 18.2 Files the coding agent must implement

- src/kden_panel/steps/step_18_release.py

- RELEASE_README.md

- MODEL_INPUT_CONTRACT.md

- tests/integration/test_fresh_reader.py

## 18.3 Exact implementation sequence

> 1\. Verify every STEP_01–STEP_17 PASS record and that no earlier output hash is stale.
>
> 2\. Publish a release manifest listing every artifact, schema version, row/partition count, coverage dates, digest, lineage, and permitted reader.
>
> 3\. Package or reference cycle_manifest, hrrr_point_trajectory, madis_observation_sequence, madis_selected_cycle_expectation, frozen checkpoint_features, training_labels, feature registry, model-view masks, and source/cost/acceptance evidence.
>
> 4\. Document exact reader examples for V0, V1, V2, and V3 sequence replay; V4 remains a future hybrid contract.
>
> 5\. Run a fresh-environment smoke test that installs the locked package, reads each canonical table by keys, selects V1/V2, joins labels only in the training reader, and proves the production reader cannot load truth.
>
> 6\. Write downstream boundary: GAM fitting creates model_predictions later and may not mutate any release table.

## 18.4 Durable outputs

- data/release/FEATURE_PANEL_V1_0/release_manifest.json

- RELEASE_README.md and MODEL_INPUT_CONTRACT.md

- archived acceptance/evidence bundle

- state/STEP_18_PASS.json

## 18.5 Pass gate

- PASS — Fresh reader smoke test succeeds from documented commands.

- PASS — All canonical keys, schemas, views, and hashes match the release manifest.

- PASS — No release table is writable through the reader API.

- PASS — Model code can select features by view registry and join labels by target_day without filename assumptions.

- PASS — The handoff explicitly excludes model_predictions until out-of-fold GAM training exists.

| **Failure behavior** Do not call the acquisition program complete if a fresh coding/modeling agent still needs an undocumented path, alias, manual join, or scientific interpretation. |
|----|

# Part IV — Shared schemas, algorithms, and gates

## 19. Canonical table types and partitions

| **Table** | **Primary key / grain** | **Recommended partition** | **Truth access** |
|:--:|----|----|----|
| **cycle_manifest** | target_day, product, cycle_init_utc | target_year/product | Forbidden |
| **hrrr_point_trajectory** | target_day, product, cycle, valid time, field ID, spatial stat | target_year/month/product/cycle token | Forbidden |
| **madis_observation_sequence** | station, observation time, source hash, variable | target_year/month | Forbidden |
| **madis_selected_cycle_expectation** | observation key, checkpoint, selected cycle | target_year/month | Forbidden |
| **checkpoint_features** | target_day, checkpoint_id | target_year/month | Forbidden |
| **training_labels** | target_day | target_year | Label-authorized training only |
| **model_predictions** | target_day, checkpoint_id, model_version | model_version/target_year | Created downstream |

Use Arrow date32 for target_day; timezone-aware UTC timestamps for cycle, issue, valid, interval, observation, receipt, and creation times; bool for flags; nullable numeric types for physical values; strings/enums for identities and reason codes. Store SHA-256 as lowercase 64-character hexadecimal or a fixed 32-byte binary type consistently across all tables.

## 20. Minimum column contracts

**Normalization resolution.** Scientific Specification Appendix D.3 lists selected_cycle_expected_value beside the madis_observation_sequence fields. Because this value depends on checkpoint context and the checkpoint’s selected cycle, its binding physical location is the normalized madis_selected_cycle_expectation child table defined below. It must not be duplicated on the immutable base observation row. This is a lossless physical normalization under this manual’s code-organization authority, not a change in scientific meaning and not a precedence conflict.

**cycle_manifest** target_day, product, cycle_init_utc, cycle_rank_within_retained, selected_by_checkpoint_ids, availability_policy_id, emulated_available_time_utc, actual_first_seen_utc, availability_basis, horizon_class, required_valid_start_utc, required_valid_end_utc, complete_flag, fallback_reason, source_uri_redacted, source_inventory_hash, hrrr_version, retrieval_run_id, created_at_utc.

**hrrr_point_trajectory** target_day, product, cycle_init_utc, valid_time_utc, forecast_lead_min, field_registry_id, parameter, level, step_type, interval_start_utc, interval_end_utc, native_unit, canonical_unit, station_coord_era, spatial_stat, value, tile_shape, coverage_flag, source_hash, derivation_version.

**madis_observation_sequence** station_id, target_day, observation_time_utc, receipt_time_utc, availability_time_used_utc, availability_basis, report_type, source_file_hash, variable_code, raw_value, raw_unit, resolution, provider_qc, madis_qc_stage_flags, local_asof_qc, derived_flag, temp_candidate_low_f, temp_candidate_high_f, causal_cycle_init_utc, causal_expected_value, innovation_low, innovation_high. It contains no checkpoint-dependent selected-cycle scalar.

**madis_selected_cycle_expectation** All columns of the immutable base observation key needed for an exact join, plus checkpoint_id, issue_time_utc, selected_cycle_init_utc, selected_cycle_expected_value, interpolation_method, interpolation_offset_min, support_valid_times_utc, match_reason, source_trajectory_hash, and derivation_version. This normalized child resolves the checkpoint context of the selected-cycle expectation.

**checkpoint_features** target_day, checkpoint_id, issue_time_utc, issue_time_local, UTC offset/DST, station_coord_era, feature_spec_version, derivation_version, availability policy, selected native cycles, source/completeness digests, and every registered K/B/S/T/N/R/E/W/C/O/D/Q feature. It contains no target.

**training_labels** target_day, y_tmax_f, y_iem_cli_raw_f, truth_source_regime, truth_qc_status, exception_rule_id, truth_source_hash, truth_spec_version. Only target_day and y_tmax_f are needed by ordinary model fitting.

## 21. Exact source selection and range retrieval

**Normative source-message selection skeleton**

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th>idx = fetch_text(source_uri + ".idx")<br />
records = parse_idx_with_start_offsets(idx)<br />
matches = [r for r in records if registry_selector.matches(<br />
parameter=r.parameter,<br />
level=r.level,<br />
step_type=r.step_type,<br />
interval_start=r.interval_start,<br />
interval_end=r.interval_end,<br />
valid_time=r.valid_time,<br />
)]<br />
require_exactly_one(matches)<br />
start = matches[0].byte_offset<br />
i = records.index(matches[0])<br />
end = records[i + 1].byte_offset - 1 if i + 1 &lt; len(records) else content_length - 1<br />
payload = http_get(source_uri, headers={"Range": f"bytes={start}-{end}"})<br />
verify_206_content_range_length(payload, start, end)<br />
verify_decoded_grib_identity(payload, registry_selector)</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

The \`.idx\` parser must retain the original line and normalized tokens. When the archive omits interval detail from \`.idx\`, final acceptance depends on decoded GRIB keys. A match by record ordinal alone is never sufficient.

## 22. Spatial extraction contract

- Resolve the effective station coordinate from the frozen station coordinate-era registry for target_day.

- Use the same projected-bilinear algorithm, grid projection, node ordering, and nearest-node convention as Layer 1. A port must pass golden parity against H16/Q05.

- Persist the four BI nodes and weights or their immutable geometry reference. BI weights sum to one within tolerance.

- 3×3 and 9×9 tiles are centered on the declared Layer 1 grid neighborhood. The panel stores only predeclared summaries, while the long trajectory may retain compact cell values if cost-authorized.

- Gradient calculations use map-distance-aware central differences and earth-relative U/V; edge or incomplete tiles yield null+coverage flags.

## 23. Temporal operator contract

| **Operator** | **Implementation requirement** | **Failure metadata** |
|:--:|----|----|
| **CUR** | Value at checkpoint; interpolate only permitted same-cycle continuous snapshots. | bracket times, offset, coverage |
| **PK / DPK** | Value at Q15 modeled peak / change from current to that peak. | peak source and support |
| **PREMEAN/MIN/MAX** | Aggregate legal same-cycle path from checkpoint through named endpoint. | n_expected, n_present, coverage |
| **PREINT** | Integrate flux using declared interval seconds; output canonical energy. | interval gaps and unit path |
| **PRESUM** | Sum non-overlapping interval amounts; no redifferencing. | overlap/gap flags |
| **FRAC/ONSET** | Threshold exposure/onset on declared support; no event=0 with null time. | threshold, no_event, coverage |
| **GROWTH** | Named end-minus-start or robust slope; registry chooses one. | support endpoints |
| **REV** | New minus previous on identical new-cycle support. | predecessor and common-support hash |

## 24. Missingness and imputation boundary

The canonical panel records meteorological missingness; it does not learn imputation values. Model-time normalization, imputation, winsorization, smooth selection, thresholds learned from outcomes, and calibration are fit inside each rolling-origin training window. The acquisition layer may only apply deterministic unit conversion, declared physical guards, and registry-defined structural null rules.

| **Case** | **Canonical representation** |
|:--:|----|
| **No predecessor cycle** | revision values null; revision_unavailable_by_design=1 |
| **No event before endpoint** | event=0; onset_time null; no_event=1 |
| **Insufficient observation window** | statistic null; n_obs/max_gap/reason populated |
| **Optional field absent** | field and dependent composites null; field_missing=1 |
| **Cross-product cycle mismatch** | composite null; mismatch flag and both cycle IDs |
| **Small/invalid composite denominator** | ratio null; denominator value and guard reason |

## 25. Acceptance gate ownership

| **Gate** | **First/primary owner** | **Subject**                          |
|:--------:|-------------------------|--------------------------------------|
| **A01**  | Steps 05, 15, 16        | Canonical key uniqueness             |
| **A02**  | Steps 05, 16            | Selected-cycle parity                |
| **A03**  | Steps 07–09, 16         | All 44/14 selectors stable           |
| **A04**  | Steps 07–09, 16         | Step and interval semantics          |
| **A05**  | Steps 07–10, 16         | Unit round trip                      |
| **A06**  | Steps 07–10, 16         | Spatial geometry parity              |
| **A07**  | Steps 10, 13, 16        | Temporal support/coverage            |
| **A08**  | Steps 13, 16            | Revision common support              |
| **A09**  | Steps 12, 14, 16        | MADIS checkpoint cutoff              |
| **A10**  | Steps 12, 16            | Temperature candidate geometry       |
| **A11**  | Steps 04, 15–17         | No truth in inference                |
| **A12**  | Step 16                 | Independent reproducibility          |
| **A13**  | Steps 07–11, 16         | Cost/retrieval ledger reconciliation |
| **A14**  | Steps 03, 15, 16        | Machine-readable model-view masks    |

# Appendix A — Existing-source reuse map

| **New canonical object** | **Existing source to reuse** | **Handling rule** |
|:--:|----|----|
| **cycle_manifest** | layer1_baseline/L1.3_trajectory_engine/raw_baseline_panel plus frozen registries/provenance | Read selected cycles/peaks; do not recompute Policy A. |
| **H16/Q05 TMP rows** | layer1_baseline/L1.3_trajectory_engine/trajectory_long/year=YYYY/month=MM/part-YYYY-MM-DD.parquet | Reuse hourly wrfsfcf and Q15 wrfsubhf TMP; no re-download. |
| **Floor geometry** | layer1_baseline/L1.5_observed_floor/full_history/checkpoint_panel.parquet | Copy approved checkpoint columns and lineage; never mutate. |
| **M01 observations** | Tmax_MADIS_v3/full_history/observations/year=YYYY/KDEN_YYYYMMDD.parquet | Reuse raw temperature/candidate sequence; extend with M02–M11. |
| **Checkpoint-bound parity** | Tmax_MADIS_v3/full_history/checkpoint_bounds/year=YYYY/... | Use to test R_low/R_high; long sequence remains authority. |
| **MADIS provenance** | Tmax_MADIS_v3/full_history/manifests | Reuse download status, source gaps, and hashes. |
| **training_labels** | Tmax_IEM_v3/year=YYYY/kden_tmax_truth_YYYY.csv | Load only in Step 17 label-authorized process. |
| **Forbidden convenience table** | Layer 1.6 evaluation_panel.parquet | Never load into feature building; contains truth/residual/error. |

| **Path portability** The relative paths above are the screenshot-confirmed reuse map. Step 02 must resolve them beneath the owner-supplied project_root and freeze the resulting absolute paths and hashes. No later module performs filesystem discovery. |
|----|

# Appendix B — Coding-agent prompt template

**Recommended instruction to the coding agent**

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th><p>Implement Step &lt;NN&gt; from “KDEN Universal Issue-Time Feature Panel<br />
Implementation Manual v1.0,” using the companion Scientific Specification v1.0<br />
as the scientific authority.<br />
<br />
Constraints:<br />
1. Work only on Step &lt;NN&gt;; do not begin a later step.<br />
2. Verify every prerequisite PASS record and recorded hash before editing/running.<br />
3. Preserve all sealed Layer 1, MADIS, and truth artifacts read-only.<br />
4. Implement every file, algorithm, test, output, and pass criterion named in the step.<br />
5. Fail closed on ambiguity; do not silently choose a source, cycle, unit, or GRIB record.<br />
6. Run all step-owned tests. For an initial Step 08, 09, or 11 implementation, run diagnostic scope. Use validate-only only when the owner explicitly requests validation of an existing completed or paused owner run. Never invoke --scope owner-full.<br />
7. For Steps 08, 09, and 11, write STEP_&lt;NN&gt;_READY_FOR_OWNER_RUN.json, print the exact owner start/status/pause/resume commands, and stop. Do not wait for or supervise the full-history acquisition.<br />
8. For all other steps, emit STEP_&lt;NN&gt;_PASS.json only if every criterion passes; otherwise emit FAIL evidence.</p>
<p>9. Never begin a later step until the required preceding PASS record exists. READY_FOR_OWNER_RUN and PAUSED are not PASS.</p>
<p>10. Finish with a concise report of changed files, tests, diagnostic scope, counts, gates, owner commands, and blockers.</p></th>
</tr>
</thead>
<tbody>
</tbody>
</table>

# Appendix C — Release and modeling-reader contracts

Downstream training and testing should index the normalized family by canonical keys, not by file ordering. The feature view is selected first; truth is joined second and only in the training/evaluation process.

**Normative downstream access pattern**

<table>
<colgroup>
<col style="width: 100%" />
</colgroup>
<thead>
<tr>
<th>features = release.open_checkpoint_features(view="V1")<br />
labels = release.open_training_labels(label_authorized=True)<br />
train = features.join(labels.select("target_day", "y_tmax_f"), on="target_day", how="inner")<br />
folds = rolling_origin_split(train, group="target_day")<br />
<br />
# Observation-augmented challenger<br />
features_v2 = release.open_checkpoint_features(view="V2")<br />
<br />
# State-space challenger: structural prior plus ordered sequence<br />
prior_v1 = release.open_checkpoint_features(view="V1")<br />
sequence = release.open_madis_sequence(as_of_basis="historical_observation_time")<br />
<br />
# Production process: no label API, no truth path, no evaluation panel<br />
live = release.open_checkpoint_features(view="V1", production=True)</th>
</tr>
</thead>
<tbody>
</tbody>
</table>

| **Consumer** | **May read** | **Must not read/write** |
|:--:|----|----|
| **Structural GAM** | V1 checkpoint_features + training_labels in training | O/D blocks, detailed same-day sequence, canonical mutations |
| **Observation GAM** | V2 checkpoint_features + training_labels in training | Sequential replay through same t |
| **State-space challenger** | V1 prior + ordered madis_observation_sequence + labels in training | V2 detailed history as preconditioned prior |
| **Production inference** | Legal live feature/sequence inputs and frozen model artifacts | training_labels, truth roots, L1.6 evaluation panel |
| **Model prediction writer** | Frozen inputs and model version | Any acquisition or feature canonical table |

| **Completion definition** The implementation is complete when a fresh coding agent can run Step 18’s reader smoke test and begin a separate GAM-training specification without asking where data live, how tables join, which columns are legal, what any missing state means, or how to reproduce the feature release. |
|----|
