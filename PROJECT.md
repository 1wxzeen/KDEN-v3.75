# Public edition: historical contract snapshot

The status line below records an earlier development point, not the current
public release. Acquisition and P01–P07 were subsequently accepted; selected
model comparisons were completed, while pretrained-tabular replay remains
unfinished. See the [current evidence summary](README.md) and
[data availability](DATA_AVAILABILITY.md). Commands below require the omitted
working archives and are not fresh-clone quickstart commands.

---

# KDEN v3.75 — HRRR-Only Intraday Tmax Probability System

Version: 1.1  
Status: R14 acquisition and Steps 00–08 frozen; prefit P01–P02 PASS; P03 implemented and awaits its owner run  
Station: KDEN  
Historical target dates: 2021-01-01 through 2026-09-11 inclusive  
Primary issue-time range: approximately 02:00 through 16:00 `America/Denver`  
Primary objective: calibrated probability distributions for contract-authoritative whole-degree-Fahrenheit daily Tmax

New developers and coding agents must begin with
`KDEN_V375_DEVELOPER_HANDOFF.md`, then read the governing Version 2 prefit plan.

Post-acquisition universal-substrate and modeling-prefit work is governed by
`RAFM_V375_UNIVERSAL_MODELING_PREFIT_PLAN.md`. Its P01–P07 ledger supersedes
the brief model-bakeoff ordering in section 15 while preserving this document's
sealed acquisition, R14, timing, and reader contracts.

P02 has written and validated the self-contained KDEN Tmax truth package at
`truth/kden_tmax/v1/`. Its immutable gate is `state/PREFIT_P02_PASS.json`.
P03 is implemented to build the target-free causal issue spine and independent
hourly/Q05 cycle selections; its owner commands and artifact map are in
`reports/prefit/P03_OWNER_RUNBOOK.md`.

## 1. Executive decision

KDEN v3.75 will be a new, self-contained, HRRR-only sibling project. It will not inherit the six-checkpoint limitation of KDEN v3, and it will not depend on MADIS or the dual-candidate temperature ambiguity that motivated KDEN v3.5.

The acquisition objective is to build a reusable local archive of as-issued HRRRv4 states from which legal information sets can be reconstructed throughout the target day. The immediate research target is intraday forecasting, beginning near 02:00 local and ending near 16:00 local. This acquisition will therefore retain only source states relevant to the current target day.

The binding source-field universe is the owner-selected **R14** contract recorded on 2026-09-14. R14 contains 12 dynamic hourly identities, one static terrain identity, and one subhourly identity. It preserves the full cycle envelope and native temporal paths; it reduces meteorological source redundancy rather than temporal density. R14 is a source-acquisition contract, not a requirement that every downstream model use all 14 identities or produce exactly 14 columns.

The binding retention policy is `TARGET_WINDOW`. A native valid state \(v\) is retained only when:

\[
c \le v \le c+\text{native horizon}(c,p)
\quad\text{and}\quad
v < W[d]_{\mathrm{end}}.
\]

Acquisition begins at `FH00` for every retained cycle and product. It does not retain an extended hourly cycle through FH48 merely because FH48 exists. Any later day-ahead project will require a separately planned acquisition with earlier previous-day cycle coverage; it is outside v3.75.

The archive will support, without reacquiring HRRR:

- Q15 and hourly T2m baseline reconstruction;
- issue-time-aware GAM/GAMM MOS;
- Analog Ensemble (AnEn) modeling;
- ordinal-hazard or related ordered-distribution modeling;
- cycle-revision and Q15-versus-hourly disagreement features;
- arbitrary intraday issue grids within the intended modeling window;
- later comparison or fusion with other sources, while keeping this HRRR-only branch intact.

## 2. Scientific objective

For target day \(d\), issue time \(t\), and integer Tmax outcome \(k\), the project seeks to estimate

\[
P(Y_d=k\mid X^{\mathrm{HRRR}}_{d,t}),
\]

where \(X^{\mathrm{HRRR}}_{d,t}\) contains only HRRR information that would have been legally available at \(t\).

The project is successful only if its probabilities are sharp and calibrated across the full year—not merely if its point forecast has low MAE. The archive is the model-agnostic source substrate for that work; it is not itself a prediction table.

## 3. Why v3.75 exists

### 3.1 Limitation of KDEN v3

KDEN v3 was optimized around six fixed checkpoints. Its cycle set and SPARSE/PATH request geometry were therefore deliberately narrow. That archive cannot reliably reconstruct arbitrary issue states beginning near 02:00 or support model-driven trajectory features that were not anticipated in advance.

### 3.2 Limitation of KDEN v3.5

KDEN v3.5 adds useful observations, but MADIS temperature can contain dual-candidate ambiguity. Even if modeled carefully, that ambiguity enters the observation-conditioned error structure. v3.75 creates a clean NWP-only branch so HRRR's independent predictive ceiling can be measured directly.

### 3.3 Why acquisition is intentionally compact but temporally dense

The original v3.75 plan retained H01–H44 and Q01–Q14 as a hedge against an unfrozen downstream model. The representative Step 04 pilot showed that this 58-field universe would impose excessive acquisition time, while a large correlated source set would also be awkward for an Analog Ensemble distance metric. Step 04.5 therefore reconsidered the source universe as a KDEN-specific meteorological question and the owner selected R14.

R14 prioritizes independent temperature baselines, vertical thermal context, near-surface moisture and flow, boundary-layer mixing, snow cover, cloud and solar control, and nearby-weather/precipitation interruption. It deliberately gives up several reconstructible composites and lower-priority diagnostics. Feature derivation and model-specific selection still occur only inside leakage-safe training folds.

The reduction does **not** thin cycles or lead times. Previous-local c23, target-local c00–c14, FH00, the `TARGET_WINDOW` ceiling, the full native hourly paths, and the full native 15-minute Q05 paths remain binding so the archive can reconstruct live-like intraday issue states.

## 4. Binding scope

### 4.1 Included

- HRRRv4 `wrfsfcf` dynamic hourly identities H02, H07, H16, H17, H18, H19, H24, H26, H28, H31, H36, and H38.
- HRRRv4 `wrfsfcf` static terrain identity H14, acquired once per grid/version.
- HRRRv4 `wrfsubhf` subhourly identity Q05.
- Historical target dates 2021-01-01 through 2026-09-11 inclusive: 2,080 target dates.
- Source-cycle coverage begins on 2020-12-31 local because the first target date requires its previous-local-day c23 anchor.
- Previous-local-day c23 plus target-day c00 through c14.
- `FH00` for both products.
- Native forecast-valid states through the `TARGET_WINDOW` ceiling.
- Reacquisition of H16 and Q05 so v3.75 has no runtime dependency on KDEN v3 or Layer 1.
- Audited KDEN coordinate-era and grid geometry copied and frozen inside v3.75.
- The retained identities' registered projected-bilinear, nearest-neighbor, and compact 3×3/9×9 baseline supports.
- Versioned compact upstream KDEN-regional context after its exact geometry and operators pass the spatial gate in section 8.2.
- Source identity, timing, interval, byte-range, hash, retry, missingness, and derivation lineage.
- One owner-facing R14 acquisition workflow with independent hourly and subhourly plans, archives, checkpoints, validation, sealing, and use.

### 4.2 Excluded

- MADIS, NBM, LAMP, observations, Kalshi prices, and market outcomes.
- Official Tmax labels or any other truth values inside the source archive.
- Six-checkpoint-only planning.
- Full-native hourly retention through FH48 after the target window ends.
- Previous-day afternoon/evening cycles needed for true day-ahead modeling.
- Full-CONUS GRIB persistence.
- Any source identity outside the active R14 field list, even when it remains present in the historical 58-field identity catalogs.
- Additional acquisition-time field selection or irreversible feature aggregation beyond the frozen R14 decision.
- Synthetic paths created by stitching two cycles together.
- Model fitting during acquisition.

## 5. Time and cycle contract

### 5.1 Target window

The contract-authoritative target window remains fixed in UTC:

\[
W[d]=[07{:}00Z_d,\;07{:}00Z_{d+1}).
\]

The archive should store `window_start_utc` and `window_end_utc` for every target date. Local clock representations are descriptive only; the boundary itself does not move with DST.

### 5.2 Cycle envelope

For each target date \(d\), schedule:

\[
c23_{d-1},\;c00_d,c01_d,\ldots,c14_d.
\]

Cycles must be enumerated as native UTC initializations and then converted with the IANA timezone `America/Denver`. Do not hard-code a UTC-hour list and do not construct nonexistent local timestamps.

On ordinary dates this yields 16 cycles per product. Across the requested date range, the DST-aware schedule contains 33,279 product-cycle candidates per product:

- ordinary target date: 16 cycles;
- spring-forward target date: 15 cycles because local 02:00 does not exist;
- fall-back target date: 17 cycles because local 01:00 occurs twice with different UTC offsets.

`cycle_init_utc` is the unique cycle key. Store the local timestamp, offset, DST flag, and fold/ambiguity indicator as metadata.

### 5.3 Why c23 is included

The previous local 23:00 cycle provides:

- an immediate predecessor for c00 revision features;
- a winter tail anchor, because 23:00 MST is 06Z and 06Z is an extended hourly cycle;
- a separate older-but-longer forecast state when c00 is newer but has a shorter hourly horizon.

c23 and c00 must remain distinct forecast states. They may become separate predictors or experts downstream, but they must never be concatenated into a fake single-cycle trajectory.

### 5.4 Forecast-lead retention

For each target date \(d\), retained cycle \(c\), and product \(p\):

```text
retained_start    = cycle initialization (FH00)
candidate_ceiling = min(cycle initialization + native maximum horizon,
                        W[d]_end)
retain native valid time v only when v < W[d]_end
```

Retain every native valid state from `retained_start` through the native horizon except a state exactly at `W[d]_end`, because the target window is right-open. This keeps pre-window FH00/FH01 states from c23 because they can describe the initial state and cycle revisions; the cap applies to the end, not the beginning.

Consequences:

- `wrfsubhf` is normally available through native FH18, but late cycles are truncated when their later Q15 blocks extend beyond \(W[d]_{\mathrm{end}}\).
- ordinary `wrfsfcf` cycles retain their available hourly leads only while they remain relevant to the target day.
- an extended c23 may retain roughly through FH25 in MST or FH26 in MDT because those leads can still reach the current target-window end.
- FH26–FH48 states after \(W[d]_{\mathrm{end}}\) are not acquired for v3.75.

The planner must discover actual native file availability. It must not assume every cycle has the same maximum horizon.

### 5.5 Historical availability policy

The archive contains candidate source states; a downstream issue-time selector determines which state was legal.

The initial historical completeness emulator remains:

\[
\widehat{A}_{\mathrm{complete}}(c,p)=c+105\text{ minutes},
\]

under policy ID `KDEN_HIST_COMPLETE_L105_V1`, subject to actual file completeness and product support.

Acquisition must not shrink itself to cycles selected by this policy at predetermined checkpoints. Instead, store the availability metadata needed to apply the policy later. This allows a 5- or 15-minute issue grid to reuse the same cycle until the next one becomes legal.

## 6. HRRR source and retrieval contract

Primary historical source root:

```text
https://noaa-hrrr-bdp-pds.s3.amazonaws.com
```

Canonical source-object patterns:

```text
hrrr.YYYYMMDD/conus/hrrr.tCCz.wrfsfcfFF.grib2
hrrr.YYYYMMDD/conus/hrrr.tCCz.wrfsubhfFF.grib2
```

For `wrfsfcf`, `FF` is the integer forecast hour. For `wrfsubhf`, Q15 valid states are repeated blocks within the appropriate forecast-hour file; the file hour is the ceiling of lead minutes divided by 60. `FH00` existence and selector behavior must be explicitly covered by pilot tests.

For every source object:

1. Fetch and hash the `.idx` inventory.
2. Parse record offsets while retaining the original index line and normalized tokens.
3. Match every field using the full frozen selector: parameter, level/layer, step type, interval semantics, and valid time.
4. Require exactly one supported match.
5. Coalesce only exactly adjacent required byte ranges from the same source object.
6. Fetch the verified byte range with persistent HTTPS.
7. Require a valid `206` response and exact `Content-Range`/payload-length agreement.
8. Split coalesced payloads deterministically and hash each extracted GRIB message payload.
9. Decode and re-verify the GRIB identity and interval keys.
10. Extract only the required KDEN point and compact tile data.
11. Convert units under a versioned conversion contract.
12. Publish Parquet plus retrieval/coverage lineage atomically.
13. Discard transient GRIB bytes only after hashes, manifest, Parquet, and ledger reconciliation are durable.

Forbidden fallbacks:

- selecting by GRIB record number alone;
- accepting the nearest plausible repeated Q15 block;
- silently changing a selector;
- silently downloading a full-domain GRIB after selector failure;
- treating an HTTP/selector/decode failure as meteorological missingness;
- imputing missing source data in the canonical archive.

## 7. Frozen R14 source universe

Registry IDs are project identifiers, not GRIB record numbers. Retained IDs are intentionally sparse and must not be renumbered. Exact selector strings, decoded-key allowlists, units, interval semantics, and existing baseline spatial contracts are inherited by identity from the sealed v1 catalogs and copied into a content-addressed R14 bundle. A planner must load the active R14 selection; it must not expand every row merely because the historical catalogs still contain 58 identities.

### 7.1 Active `wrfsfcf` identities

Every dynamic H identity follows its complete native hourly path under `TARGET_WINDOW`. H14 is static and acquired once.

| ID | Parameter and level | Step / interval | Baseline spatial contract |
|---|---|---|---|
| H02 | TMP 700 mb | snapshot | `POINT_BI_TILE3_V1` |
| H07 | TMP 850 mb | snapshot | `POINT_BI_TILE3_V1` |
| H14 | HGT surface | static snapshot | `GRID_STATIC_ONCE_V1` |
| H16 | TMP 2 m AGL | snapshot | `POINT_BI_NN_V1`; reacquire |
| H17 | DPT 2 m AGL | snapshot | `POINT_BI_V1` |
| H18 | UGRD 10 m AGL | snapshot | `POINT_BI_V1` |
| H19 | VGRD 10 m AGL | snapshot | `POINT_BI_V1` |
| H24 | HPBL surface | snapshot | `POINT_BI_V1` |
| H26 | SNOWC surface | snapshot | `POINT_BI_V1` |
| H28 | TCDC boundary-layer cloud | snapshot | `POINT_BI_TILE9_V1` |
| H31 | DSWRF surface | snapshot | `POINT_BI_TILE9_V1` |
| H36 | REFC entire atmosphere | snapshot | `POINT_BI_TILE9_DERIVE3_V1` |
| H38 | APCP surface | preceding 60-minute accumulation | `POINT_NN_TILE9_V1` |

H38 is an interval amount, not a rate. Preserve its registered positive-lead interval and its observed zero-duration FH00 source encoding; never fabricate an unavailable preceding interval. Existing Layer-1 H16 rows are validation oracles only.

### 7.2 Active `wrfsubhf` identity

| ID | Field | Native time semantics | Baseline spatial contract |
|---|---|---|---|
| Q05 | TMP 2 m AGL | 15-minute snapshots | `POINT_BI_NN_V1`; reacquire |

Q05 is the sole subhourly R14 identity and follows its complete native 15-minute path. It remains a separate source product from H16; hourly interpolation is not a substitute.

### 7.3 Explicit exclusions and unsupported composites

The R14 full-history planner must exclude:

```text
Hourly: H01 H03 H04 H05 H06 H08 H09 H10 H11 H12 H13 H15
        H20 H21 H22 H23 H25 H27 H29 H30 H32 H33 H34 H35
        H37 H39 H40 H41 H42 H43 H44

Subhourly: Q01 Q02 Q03 Q04 Q06 Q07 Q08 Q09 Q10 Q11 Q12 Q13 Q14
```

Do not acquire an excluded identity merely because a historical feature builder expects it. Exact pressure-dependent specific humidity, aloft shear/advection, 850–700 height thickness, geometric lapse rate, net shortwave/albedo, net longwave/total radiation, turbulent-flux partition, snow density, and CAPE/CIN are unsupported by R14 and must be removed from eligible derived-feature contracts. T850−T700 remains supported as a temperature difference, and hourly solar integration from H31 is explicitly approximate.

## 8. Spatial extraction and physical encoding

### 8.1 Coordinate independence

Copy the audited KDEN station coordinate-era registry, projection definition, grid-node ordering, BI weights, and NN convention into immutable v3.75 registries. Record their source hashes, but make no runtime read from the v3/v3.5 repositories.

Where v3 overlaps v3.75, H16 and Q05 values must match the old audited extraction within the frozen numeric tolerance.

### 8.2 R14 upstream spatial context gate

R14 requires compact context beyond a single KDEN point for the retained fields where regional structure is scientifically relevant. The intended sectors are west/foothill, north/northeast plains, east plains, and south/southeast/Palmer Divide, initially near 30 km and 60 km from KDEN.

`config/r14_spatial_contract_v375.json` now seals those targets as eight ordered, map-aware supports: west at 270°, north-northeast at 22.5°, east at 90°, and south-southeast at 157.5°, each at 30 km and 60 km from the applicable KDEN coordinate-era location on the HRRR sphere. `registries/r14_spatial_geometry_v375.json` resolves the exact nearest and bilinear HRRR nodes and weights for both v4 coordinate eras. Continuous surface fields use bilinear extraction, H36/H38 use nearest extraction, H14 supplies terrain at every support, and isobaric H02/H07 remain on their existing local 3×3 contracts rather than being projected into potentially invalid high terrain.

The geometry, ordering, operators, output columns, and fail-closed terrain policy are sealed for the R14 confirmation pilot. This is not full-history authorization: the pilot must still show finite H14 support, correct extraction, parity, deterministic output, and acceptable processing/storage cost before `STEP_04_R14_PASS.json` can be issued.

The existing point/tile contracts in section 7 are the non-negotiable baseline. Regional samples extracted from an already requested GRIB message do not add logical source-message requests, but their output bytes, decode/extraction time, and storage must be measured by the R14 pilot.

### 8.3 Compact tile rule

Do not store one long-table row per tile cell. Store one field-state row with:

```text
tile_shape       = null | [3, 3] | [9, 9]
tile_values      = null | row-major fixed/list array
tile_center_i/j  = center indices
grid_geometry_id = immutable geometry reference
```

For a 9×9 field that also needs 3×3 support, retain only the 9×9 tile and derive the centered 3×3 later. Store BI/NN point outputs separately in the same field-state row when the registry requires them.

Pilot `float32` tile storage with Zstandard-compressed Parquet. Keep coordinate geometry and BI weights in `float64`. Accept `float32` physical values only after parity and round-trip tests show no scientifically meaningful loss relative to decoded HRRR precision; otherwise use `float64` for the affected field.

### 8.4 Unit policy

Retain `native_unit`, `canonical_unit`, and `conversion_version`. Unit conversion occurs once during extraction. Raw GRIB metadata remains in lineage so the conversion can be audited.

Supported derived quantities belong in downstream feature tables, not the canonical source archive. A derived-feature registry must enforce the R14 eligibility restrictions in section 7.3.

## 9. Canonical data architecture

### 9.1 Repository layout

```text
KDEN v3.75/
  PROJECT.md
  pyproject.toml
  config/
    project_v375.toml
    r14_acquisition_v375.json
    r14_spatial_contract_v375.json
    cycle_schedule_r14_v375.toml
    request_plan_r14_v375.toml
    pilot_design_r14_v375.json
    wrfsfcf_4w.toml
    wrfsfcf_8w.toml
    wrfsubhf_4w.toml
    wrfsubhf_8w.toml
  registries/
    # Historical 58-identity selector catalogs; retained, never planned wholesale.
    hrrr_hourly_v375.csv
    hrrr_subhourly_v375.csv
    station_coordinate_eras_v375.csv
    availability_policies_v375.csv
    grid_geometry_v375.json
    registry_bundle_v375.json
    registry_bundle_r14_v375.json
    r14_spatial_geometry_v375.json
  schemas/
    cycle_schedule_v375.json
    request_plan_v375.json
    request_plan_r14_v375.json
    hrrr_field_state_v375.json
    hrrr_field_state_r14_v375.json
    r14_attestation_v375.json
    r14_step03_pass_v375.json
    r14_step04_pass_v375.json
    monitor_snapshot_v375.json
    retrieval_ledger_v375.json
    temporal_coverage_v375.json
  src/kden_v375/
    cli.py
    contracts.py
    time.py
    planning.py
    progress.py
    monitoring.py
    pilot.py
    r14.py
    r14_records.py
    r14_schedule.py
    r14_request_plans.py
    r14_plan_records.py
    r14_pilot_records.py
    acquisition/
      wrfsfcf.py
      wrfsubhf_q05.py
    io/
      atomic.py
      http_range.py
      grib.py
      parquet.py
    steps/
      step_00_initialize.py
      step_01_registries.py
      step_01_r14_registries.py
      step_02_cycle_schedule.py
      step_02_r14_cycle_schedule.py
      step_03_request_plans.py
      step_03_r14_request_plans.py
      step_04_pilot.py
      step_05_r14_acquisition.py
      step_06_wrfsubhf.py  # deprecated compatibility entry point
      step_07_archive_readers.py
      step_08_acceptance.py
  tests/
    unit/
    integration/
    golden/
    acceptance/
  hrrr_v4_local_archive/
    common/
      cycle_schedule/
      cycle_schedule_r14/
      registries/
      schemas/
    wrfsfcf/
      canonical/
      manifests/
      reports/
      state/
    wrfsubhf/
      canonical/
      manifests/
      reports/
      state/
  runs/
  reports/
  state/
```

### 9.2 Canonical tables

#### `cycle_schedule`

Primary key: `(target_day, product, cycle_init_utc)`.

Minimum columns:

```text
target_day
product
cycle_init_utc
cycle_init_local
local_calendar_date
local_cycle_hour
utc_offset_minutes
dst_flag
local_fold
hrrr_version
native_max_forecast_hour
horizon_class
window_start_utc
window_end_utc
retained_valid_start_utc
retained_valid_end_utc
availability_policy_id
emulated_complete_time_utc
actual_first_seen_utc
availability_basis
source_inventory_hash
complete_flag
missing_or_quarantine_reason
retrieval_run_id
```

#### `request_plan`

Primary key: deterministic `request_id`; logically unique on product, cycle, source object, valid time/block, field selector, and extraction contract.

Minimum columns:

```text
request_id
target_day
product
cycle_init_utc
source_object_identity
index_object_identity
forecast_lead_min
valid_time_utc
field_registry_id
selector_identity
step_type
interval_start_utc
interval_end_utc
spatial_contract_id
request_action
```

All v3.75 H16/Q05 rows use a network acquisition action. There is no `REUSE_L1` action.

#### `hrrr_field_state`

Primary grain: one `(target_day, product, cycle_init_utc, valid_time_utc, field_registry_id)` state, with interval boundaries included for interval fields.

Minimum columns:

```text
target_day
cycle_init_utc
cycle_init_local
product
hrrr_version
forecast_lead_min
valid_time_utc
valid_time_local
field_registry_id
parameter
level
step_type
interval_start_utc
interval_end_utc
native_unit
canonical_unit
station_id
station_coord_era
grid_geometry_id
bi_value
nn_value
tile_shape
tile_values
coverage_flag
missing_reason
selector_identity
source_idx_hash
payload_hash
byte_start
byte_end
decoded_grib_identity
retrieval_run_id
derivation_version
```

#### `retrieval_ledger`

Records attempts, response contracts, retries, byte counts, coalescence groups, selector results, decode status, source/payload hashes, publication location, and terminal disposition.

#### `temporal_coverage`

For each target-day/product/cycle/field, records expected native states, present states, explicit remote missing states, quarantined states, first/last valid time, gaps, and completeness.

### 9.3 Partitioning

Use UTC identities in paths and keys:

```text
canonical/
  target_year=YYYY/
    target_month=MM/
      target_day=YYYY-MM-DD/
        cycle=YYYYMMDDTHHZ/
          part-....parquet
```

Hourly and subhourly roots remain separate. Within each work unit, sort deterministically by product, cycle, valid time, field ID, and interval start.

H14 is stored once per HRRR grid/version in common static geometry storage and referenced by `grid_geometry_id` rather than repeated at every lead.

## 10. Engineering reuse from KDEN v3

Port the proven implementation into the new package; do not import the old repository at runtime.

### 10.1 Port with minimal behavioral change

- `.idx` parsing and full-identity selector resolution;
- verified HTTP byte-range client;
- exact-adjacent range coalescence;
- one persistent `requests.Session` per worker thread;
- bounded `ThreadPoolExecutor` orchestration;
- retry/backoff and confirmed-404 classification;
- GRIB decoding and decoded-identity validation;
- audited BI/NN/tile extraction;
- atomic file/directory publication;
- deterministic hashing and manifests;
- single-coordinator append-only progress journal;
- hash-verified resume;
- source-group cache and partial-cache quarantine;
- graceful pause/status/resume behavior;
- request/byte/retry/cost reconciliation.

The existing eight-worker profiles are the selected production starting point. The R14 confirmation pilot must exercise the eight-worker path and may retain a small matched four-worker diagnostic as a fallback comparison. The owner-full workflow uses at most eight total download workers across both products; it must never create two independent eight-worker pools.

### 10.2 Replace or remove

- six-checkpoint scheduler;
- checkpoint spine dependency;
- bounded four-cycle manifest;
- SPARSE/PATH acquisition logic;
- H16/Q05 `REUSE_L1` logic;
- MADIS and truth-root dependencies;
- Step 09 dependence on Step 08 PASS;
- checkpoint-specific extract assumptions;
- serial coupling between product completion states.

### 10.3 Concurrency invariant

Workers may fetch/decode independent work units concurrently. Only the main coordinator may append durable progress, claim publication ownership, or advance global state. A worker returns an immutable result; it does not mutate shared progress files.

## 11. Execution plan

Each step writes a content-addressed PASS record. A later step must validate the required predecessor hashes before running. Full-history acquisition is owner-controlled; implementation agents stop after producing `READY_FOR_OWNER_RUN` and exact commands.

### 11.1 R14 migration lineage

The existing Step 00–04 artifacts describe the original broad-universe implementation and must not be overwritten or relabeled:

- `STEP_00_PASS.json` remains immutable evidence that the original package-isolation and shared-primitive gates passed. Because R14 changed `README.md`, project configuration, and added source modules, the generic historical validator correctly considers its artifact snapshot stale; R14 Step 01 therefore re-runs current runtime-isolation checks rather than overwriting or pretending to reuse that PASS.
- `STEP_02_PASS.json` remains evidence for dates, cycle identities, DST handling, and native horizons. Its inclusive endpoint enumeration is superseded by the right-open R14 rule and cannot be reused as the active R14 schedule without rebuilding the retained-boundary fields.
- `STEP_01_PASS.json`, the v1 registry bundle, both original Step 03 product plans/PASS records, and `STEP_04_PASS.json` remain immutable historical evidence. They do not authorize R14 acquisition.

Successor records use an explicit `R14` identity, including `STEP_01_R14_PASS.json`, `STEP_02_R14_ATTESTATION.json`, `STEP_03_R14_*`, and `STEP_04_R14_PASS.json`. No R14 record may claim a predecessor merely from a filename; it must store and verify the predecessor's content hash and active scope ID `KDEN_V375_R14_V1`.

### Step 00 — Initialize the independent project

Actions:

- create the repository/package layout;
- port shared acquisition primitives from the supplied v3 source snapshot;
- remove absolute paths and old-repository runtime imports;
- freeze environment, dependencies, log schema, run-ID grammar, and atomic-write rules;
- implement CLI commands for `run-step`, `status`, `pause-run`, `resume`, and `validate-only`.

Gate:

- clean installation in a fresh environment;
- no required path outside `KDEN v3.75/`;
- synthetic atomic publication and interruption/resume tests pass.

Deliverable: `state/STEP_00_PASS.json`.

### Step 01 — Freeze the R14 registry overlay and schemas

Actions:

- preserve the v1 58-identity CSVs and registry bundle as historical selector catalogs;
- select exactly the sparse R14 IDs from those catalogs without renumbering them;
- copy their exact selectors, interval semantics, units, baseline spatial requirements, and allowed decoded identities into a versioned R14 bundle;
- encode the explicit excluded-ID sets and fail if a retained/excluded identity overlaps or the union is incomplete;
- freeze the audited coordinate-era and grid registries plus the new R14 spatial contract;
- mark H16 and Q05 as normal network acquisitions;
- define the compact array/tile Parquet schemas;
- update derived-feature eligibility so unsupported composites cannot request excluded sources;
- hash the complete R14 registry bundle.

Gate:

- the active set is exactly 12 dynamic H, static H14, and Q05, with original sparse IDs preserved;
- every retained field has exactly one acquisition contract and every excluded field has none in the active plan;
- H38 positive-lead and FH00 interval semantics are machine-testable;
- the exact upstream spatial geometry and operators are sealed, all nodes are in-grid, the H14 terrain requirement is explicit, and actual finite-terrain/extraction validation is assigned to the bounded R14 pilot;
- no `REUSE_L1`, MADIS, or truth dependency remains.

Deliverable: `state/STEP_01_R14_PASS.json` and `registries/registry_bundle_r14_v375.json`.

### Step 02 — Rebuild and re-attest the DST-safe R14 cycle schedule

Actions:

- verify the original schedule manifest, directory, policy, and Step 02 PASS hashes as predecessor evidence;
- preserve target dates, UTC cycle identities, DST handling, horizon discovery, FH00, and the `[07Z,07Z next day)` window;
- rebuild the R14 retained-boundary fields and manifest so no native valid state exactly at `W[d]_end` is eligible;
- record the old-to-R14 logical-state count delta explicitly rather than mutating the old schedule artifact.

Gate:

- 2,080 target dates;
- exactly 33,279 scheduled cycles per product under the frozen timezone rule;
- direct tests for every DST transition in 2021–2026;
- every cycle key is unique in UTC;
- every retained native valid time satisfies `< W[d]_end`;
- every cycle begins at FH00.

Deliverable: `state/STEP_02_R14_ATTESTATION.json` plus a new sealed R14 cycle-schedule manifest, both referencing the historical `STEP_02_PASS.json` hash.

### Step 03 — Build independent request plans

Actions:

- create `plan_wrfsfcf_r14` and `plan_wrfsubhf_q05_r14` separately, without overwriting the historical broad plans;
- enumerate all native valid states from FH00 to the `TARGET_WINDOW` cap;
- expand only the active R14 identities from the R14 bundle;
- map subhourly lead minutes to the correct forecast-hour file and repeated block;
- deduplicate identical source-object fetches and coalescible messages;
- attach spatial, unit, and selector contracts;
- estimate source objects, messages, byte ranges, extracted values, tile cells, and output bytes;
- seal plan hashes before network execution.
- checkpoint each completed target-year partition so a cooperative pause/resume preserves completed planning work;
- extract only the KDEN plus eight support values from static H14 and never persist its transient decoded full grid.

Gate:

- every planned valid time is strictly earlier than the target-window end;
- no FH48-only tail remains after the cap;
- H16/Q05 have positive network request counts;
- H14 is planned once per grid/version;
- no checkpoint or MADIS column is required;
- the two product plans can be loaded and executed independently;
- expected right-open logical counts reconcile to 6,762,997 hourly requests, including one static H14 request, and 2,156,601 Q05 requests unless a documented planner correction explains the difference.

Deliverables:

- `state/STEP_03_R14_WRFSFCF_PASS.json`;
- `state/STEP_03_R14_WRFSUBHF_PASS.json`;
- `state/STEP_03_R14_PASS.json` binding both independent plan hashes;
- dry-run cost and disk projections by product, field, year, and tile size.

### Step 04 — Run the bounded R14 confirmation pilot

The original broad-universe `STEP_04_PASS.json` remains engineering evidence but is not the R14 pilot gate. Reuse its valid selector, decoding, storage, and performance evidence where the underlying contract and artifact hash are unchanged; do not redownload a broad four-week cohort merely for ceremony.

Pilot coverage must include:

- bounded representatives sufficient to cover both KDEN coordinate eras, ordinary/extended hourly horizons, c23/c00, and both DST transition types, using existing immutable pilot evidence where valid;
- FH00 in both products;
- all active R14 selectors, with explicit H38 FH00 and positive-lead accumulation checks and Q05 repeated-block identity checks;
- early, middle, and final retained forecast files/blocks;
- at least one late cycle truncated by `W[d]_end`;
- overlapping H16/Q05 rows for parity against v3;
- every sealed R14 regional spatial operator, including terrain checks where applicable;

Pilot reports:

- selector hit rate and ambiguity rate;
- decoded-key and interval-semantic validation;
- requests, coalescence ratio, accepted bytes, retries, and wall time;
- fetch, decode, extraction, and Parquet-write timing;
- peak memory and temporary-disk usage;
- output size by product/field/spatial shape;
- float32 versus float64 parity and storage comparison;
- projected full-history duration and disk requirement;
- missingness versus quarantine classification;
- physical-value ranges and obvious-unit checks;
- eight-worker end-to-end throughput and an optional small matched four-worker diagnostic.

Gate:

- every selector is either validated or explicitly blocked;
- no ambiguous repeated Q15 block is accepted;
- H16/Q05 spatial parity passes;
- interruption/resume produces no duplicate or changed rows;
- pilot rebuild is value-identical and hash-stable;
- projected disk use fits the owner's available storage with a documented safety margin;
- no excluded H/Q identity appears in a request, payload, or canonical row.

The lead policy is not reopened by this pilot: it remains the right-open `TARGET_WINDOW` policy (`TARGET_WINDOW_RIGHT_OPEN` in machine-readable artifacts). The pilot decides only physical encoding/compression and confirms the safe eight-worker profile.

Deliverable: `state/STEP_04_R14_PASS.json` and an owner-readable R14 pilot/cost report. The implementation agent stops after the bounded code/test preparation and supplies owner start, live-status, pause, resume, ETA, and validation commands; the owner runs any long-lived pilot.

### Step 05 — Prepare and execute the complete R14 acquisition

Step 05 is the only owner-facing full-history acquisition stage. It contains two atomic product subphases:

```text
05A  WRFSFCF_R14       12 dynamic hourly identities + static H14
05B  WRFSUBHF_Q05_R14  Q05 at native 15-minute cadence
```

Implementation phase:

- finalize both product acquirers against their independently sealed R14 plans;
- provide one coordinator, run ID, lock, start/status/pause/resume/ETA/validate interface, and bounded eight-worker pool;
- schedule 05A first and automatically begin 05B after hourly PASS without requiring a second owner command;
- retain deterministic product checkpoints and separate manifests, ledgers, coverage, archives, and validation;
- run only bounded diagnostics under the selected worker profile;
- emit exact owner commands and write `R14_READY_FOR_OWNER_RUN.json`; the implementation agent then stops.

Owner phase:

- execute the complete R14 historical acquisition with one command;
- allow graceful pauses and same-run-ID resumes;
- verify hashes before skipping prior work;
- expose component and combined progress, throughput, and ETA in a non-clearing status command;
- terminally reconcile every planned request and publication for each product.

PASS requires:

- every planned request is successful, confirmed remote-missing, or quarantined with an explicit reason;
- quarantines are zero for final PASS unless the owner explicitly approves a documented exception policy;
- no unplanned request or full-domain GRIB retention;
- H16 is reacquired and parity-tested;
- H14 is not duplicated;
- Q05 resolves by full identity and valid-time metadata, including FH00, and is reacquired and parity-tested;
- late-cycle Q05 blocks beyond `W[d]_end` are absent by plan, not marked missing;
- partitions are schema-valid, sorted, hash-valid, and resume-safe;
- request, source-object, byte, retry, extraction, missingness, and publication totals reconcile exactly;
- 05A emits `WRFSFCF_R14_PASS.json` independently; a later 05B failure cannot invalidate or delete it;
- overall `R14_PASS.json` is emitted only after both product PASS records validate.

Deliverables:

- `hrrr_v4_local_archive/wrfsfcf/canonical/`;
- `hrrr_v4_local_archive/wrfsubhf/canonical/`;
- hourly retrieval ledger and coverage tables;
- Q05 retrieval ledger and coverage tables;
- `WRFSFCF_R14_PASS.json`, `WRFSUBHF_Q05_R14_PASS.json`, and `R14_PASS.json`.

Hourly modeling may begin as soon as `WRFSFCF_R14_PASS.json` exists. It does not wait for subhourly acquisition.

### Step 06 — Deprecated Q05 compatibility entry point

Step 06 is no longer a separate project stage or a prerequisite for Step 07. During migration, the old numeric entry point may remain as a compatibility alias that can validate, diagnose, or resume the 05B Q05 subphase of an existing R14 run. It must use the same R14 plan, coordinator ownership, product checkpoint, and global worker bound; it may not start a competing independent acquisition or produce a second archive. New owner runbooks use Step 05 only.

### Step 07 — Build archive readers and issue-time views

Full Step 07 PASS requires the combined `R14_PASS.json`. Hourly-reader development and hourly-only modeling may begin after `WRFSFCF_R14_PASS.json`, but Q15 and cross-product views remain unavailable until the Q05 component passes.

Implement:

- raw field-state reader;
- cycle-schedule reader;
- historical availability-policy selector;
- newest-legal-cycle resolver by product and issue time;
- same-cycle physical bundle builder;
- Q15-BI and H-BI trajectory/baseline reconstruction;
- cycle-revision builder on identical valid-time support;
- Q15-versus-hourly comparison views with both cycle identities retained;
- model-view builder for arbitrary intraday issue grids.

Rules:

- selecting a legal issue-time view never mutates the archive;
- no cycle with emulated availability after issue time is used;
- product-specific selected cycles are stored explicitly;
- cross-product features require a declared same-cycle or intentionally separate-expert contract;
- c23 and c00 are never spliced;
- truth is unavailable to production readers.

Deliverable: `state/STEP_07_PASS.json`.

### Step 08 — Final acceptance and freeze

Run full-dataset acceptance:

- schedule and target-window integrity;
- source/selector/decoded-message identity;
- interval semantics;
- spatial geometry and parity;
- canonical units and physical ranges;
- expected/present/missing request reconciliation;
- partition, manifest, and progress-journal hashes;
- independent hourly and Q15 usability;
- deterministic bounded rebuild;
- no truth/MADIS/market columns or dependencies;
- no valid time at or after `W[d]_end`;
- no dependence on v3/v3.5 after bootstrap.

Freeze immutable registry, schema, plan, code, environment, and archive digests.

Deliverable: `KDEN_V375_ACQUISITION_PASS.json`.

## 12. State, failure, and resume policy

The owner operates one R14 run state, while each product retains independent checkpoints:

```text
R14_READY_FOR_OWNER_RUN.json
R14_RUNNING.json
R14_PAUSED.json
R14_PASS.json

WRFSFCF_R14_PENDING.json
WRFSFCF_R14_RUNNING.json
WRFSFCF_R14_PAUSED.json
WRFSFCF_R14_PASS.json

WRFSUBHF_Q05_R14_PENDING.json
WRFSUBHF_Q05_R14_RUNNING.json
WRFSUBHF_Q05_R14_PAUSED.json
WRFSUBHF_Q05_R14_PASS.json
```

Rules:

- a diagnostic run cannot emit an owner-full PASS;
- only one owner-full R14 run may own either product dataset at a time;
- the global coordinator enforces a total maximum of eight download workers and hourly-first phase order;
- pause finishes or rolls back the current atomic work unit, persists progress, releases the lock, and never deletes completed artifacts;
- resume uses the same run ID and verifies published hashes before skipping;
- a resume continues the incomplete product phase and never reopens an already sealed product PASS;
- a stale or partial source-group cache is quarantined, not trusted;
- selector drift, decoded-key mismatch, invalid `Content-Range`, or hash disagreement fails the affected work unit;
- a confirmed remote gap is explicit missingness; a code or selector failure is not;
- global PASS is impossible with unreconciled work.

## 13. Testing matrix

### Unit tests

- DST-aware cycle enumeration and fall-back fold handling;
- `TARGET_WINDOW` lead ceilings for ordinary/extended cycles;
- FH00 URI generation for both products;
- subhourly lead-to-file mapping;
- selector exactness and ambiguity rejection;
- interval start/end derivation;
- byte-range and `Content-Range` verification;
- exact-adjacent coalescence split logic;
- unit conversions;
- compact tile serialization and round-trip;
- deterministic request IDs and hashes;
- exact R14 retained and excluded sets, with sparse field IDs preserved;
- H38 positive-lead and FH00 interval behavior;
- R14 scope/registry/plan lineage verification.

### Golden tests

- H16 and Q05 BI/NN parity with audited v3 overlap;
- KDEN coordinate-era boundary dates;
- known hourly and Q15 `.idx` files across archive eras;
- known H38 accumulation and Q05 repeated snapshot blocks;
- fixed tile orientation and center-cell identity;
- every R14 regional spatial operator and terrain-validity rule.

### Integration tests

- bounded end-to-end hourly acquisition;
- bounded end-to-end Q15 acquisition;
- four-worker and eight-worker value identity;
- synthetic interruption, pause, and resume;
- partial-cache quarantine;
- confirmed 404 versus selector failure;
- independent product sealing and reading;
- one Step 05 start followed by automatic hourly-to-Q05 phase transition;
- a single shared eight-worker ceiling across the complete workflow;
- component plus combined status and ETA, including pause/resume continuity;
- Q05 failure injection proving the hourly PASS remains valid;
- issue-time selection around the +105-minute boundary.

### Acceptance tests

- all planned work reconciles;
- no valid state exists at or after the right-open target-window end;
- no illegal issue-time cycles appear in derived views;
- every interval field retains exact boundaries;
- every excluded identity has zero planned and canonical rows;
- both product PASS records bind to the same R14 scope and combined run;
- every tile has expected shape/orientation or explicit coverage failure;
- truth isolation holds.

## 14. Storage and cost policy

The previous v3 Step 08/09 outputs occupied roughly 6.65 GB, but that value cannot be scaled by cycle count alone because v3.75 adds many more cycles, full native paths, independently reacquired temperature fields, and regional supports while also changing the physical encoding. Applying the binding right-open target window gives an initial R14 accounting of 6,762,997 hourly logical requests plus 2,156,601 Q05 requests, or 8,919,598 total. Scaling the previous selected rate of 15.5038778794 requests/s gives 159.81 hours (6.66 continuous days). This is a planning estimate, not a duration guarantee; successor plans and the R14 pilot replace it with sealed counts and observed end-to-end measurements.

Therefore:

- do not promise a disk total before the representative pilot;
- report compressed and uncompressed bytes per field, product, lead, cycle, and tile shape;
- extrapolate by season, horizon class, and archive era;
- reserve explicit temporary-space and safety margins in addition to final Parquet size;
- use byte-range extraction and discard transient GRIB payloads only after durable publication;
- use compact arrays rather than 81 long rows for a 9×9 tile;
- keep the `TARGET_WINDOW` ceiling fixed even if FH48 is available.

If the pilot projection is too large, pause for an explicit scientific scope decision. Do not silently thin temporal paths, drop fields, discard tiles, or switch to lossy precision.

## 15. Brief downstream modeling plan

Acquisition and modeling remain separate. Truth is joined only after a legal issue-time feature view is built.

### 15.1 Common modeling frame

Begin with a 15-minute issue grid from approximately 02:00 through 16:00 local. A later five-minute grid can reuse the same archive; repeated issue rows will often use the same newest legal HRRR cycle.

For each issue time:

1. resolve the newest legal cycle for each product;
2. reconstruct Q15-BI and H-BI trajectories;
3. derive current state, forecast peak, heating path, late-tail, cycle-revision, spatial, and regime summaries;
4. preserve every source cycle identity;
5. join the single daily Tmax label only in the training pipeline.

All issue rows from the same target date remain in the same rolling-origin fold. Normalization, feature selection, smooth selection, AnEn tuning, threshold tuning, and calibration occur inside the training portion of each fold.

### 15.2 Analog Ensemble (AnEn)

Use R14 to derive a compact analog state rather than placing every retained trajectory and regional sample directly into the distance metric.

Initial workflow:

- create candidate summaries from thermal trajectory, T850/T700 structure, near-surface flow and moisture, boundary-layer mixing, snow cover, boundary-layer cloud, incoming solar, echo/precipitation interruption, spatial structure, and cycle stability;
- standardize within the training fold;
- remove redundant predictors and forward-select roughly 3–8 similarity features using out-of-fold probabilistic score;
- find historical as-issued HRRR states at comparable issue times/regimes;
- construct an empirical residual distribution using \(e_i=Y_i-B_i\) and \(Y_i^*=B_t+e_i\);
- tune neighbor count, distance weights, season/issue-time restrictions, and kernel weights inside rolling-origin training only.

Evaluate calibration, CRPS/log score, interval coverage, sharpness, and exact/band probabilities—not only analog-mean MAE.

### 15.3 GAM/GAMM

Start with a transparent distributional MOS form:

\[
\mu_{d,t}=B_{d,t}+g_\mu(X^{\mathrm{HRRR}}_{d,t}),
\qquad
\log\sigma_{d,t}=g_\sigma(X^{\mathrm{HRRR}}_{d,t}).
\]

Candidate smooth families include season/solar geometry, baseline level and peak timing, T850/T700 difference, surface wind and dewpoint, Q15/H disagreement, incoming solar and boundary-layer cloud, PBL depth, snow cover, echo/precipitation interruption, spatial spread, and cycle revisions. Do not specify unsupported aloft advection, net radiation, flux partition, pressure-dependent humidity, or CAPE/CIN features.

Use GAMM structure only where repeated issue rows or systematic grouping justify it; do not treat hundreds of issue rows from one target day as independent Tmax outcomes. Keep model dimension conservative relative to roughly 2,080 independent days.

### 15.4 Ordinal hazard

Model the ordered integer outcome through a coherent sequence of thresholds or hazards, for example conditional probabilities of reaching/exceeding successive whole-degree values. This directly produces a nonnegative PMF that sums to one and can be aggregated exactly into Kalshi temperature bands.

Use HRRR baseline and physical summaries as predictors, allow issue-time-varying effects where supported, and enforce a coherent ordered distribution. Compare direct ordinal-hazard probabilities against PMFs derived from GAM/GAMM and AnEn residual distributions. Apply any recalibration strictly out of sample.

### 15.5 First comparison

The first serious benchmark should compare, at identical rolling issue times and folds:

1. raw Q15-BI and H-BI probability baselines;
2. distributional GAM/GAMM MOS;
3. HRRR AnEn residual MOS;
4. ordinal-hazard PMF.

Primary evaluation: CRPS, log score, Brier scores for market bands/thresholds, calibration/reliability, interval coverage, sharpness, and the earliest issue time at which the correct distribution becomes usefully concentrated. MAE remains secondary.

## 16. Definition of done

Acquisition is complete when:

- the frozen 2021-01-01–2026-09-11 schedule is fully reconciled;
- previous-local c23 and target-local c00–c14 are represented DST-correctly;
- all 12 dynamic R14 hourly identities and Q05 are present through the `TARGET_WINDOW` ceiling or carry explicit legitimate missingness, while H14 is present once per grid/version;
- all 44 hourly and 14 subhourly historical catalog identities remain available for selector provenance, but the 31 excluded H and 13 excluded Q identities have zero active-plan and canonical rows;
- FH00 is included and validated for both products;
- every retained native valid time is strictly earlier than `W[d]_end`;
- H16 and Q05 are independently reacquired;
- required point values and compact tiles are preserved;
- hourly and Q05 archives each have their own terminal R14 PASS;
- one owner-facing Step 05 run produces the two product PASS records and the final combined R14 PASS;
- the final combined acquisition PASS freezes all hashes and contracts;
- arbitrary legal intraday issue-time views can be reconstructed without network access;
- no truth, MADIS, market, or post-event information exists in the source archive;
- the project runs without the v3 or v3.5 repositories.

## 17. Deferred future acquisition

If the research objective later expands to true day-ahead forecasting, create a new versioned acquisition extension. That extension must first define the desired issue times and then add the necessary previous-day initialization envelope. It may retain full native FH48 where scientifically relevant.

Do not reinterpret the present v3.75 archive as complete for day-ahead forecasting merely because some retained cycles are extended cycles.

## 18. Governing source material

This plan synthesizes and supersedes acquisition-scope choices in the following supplied materials while preserving their validated engineering and field semantics:

- `reports/STEP_04_5_R14_ACQUISITION_HANDOFF.md`, the authoritative R14 field decision;
- `reports/step_04_5_c32_reduction_meteorological_study.md` and related Step 04.5 research as supporting rationale only where not superseded by the R14 handoff;
- `KDEN_HRRRv4_Local_Archive_Acquisition_Memo_v1.0(1).md`;
- `KDEN_Universal_Issue_Time_Feature_Panel_Scientific_Specification_v1.0(5).docx`;
- `KDEN_Universal_Issue_Time_Feature_Panel_Implementation_Manual_v1.0(7).docx`;
- `step08_wrfsfcf_8w.toml`;
- `step09_wrfsubhf_8w.toml`;
- `STEP_08_PASS.json`;
- `STEP_09_PASS.json`;
- the supplied KDEN v3 `src` snapshot;
- the owner's final decisions on c23, FH00, independent H16/Q05 acquisition, compact tile retention, `TARGET_WINDOW` instead of FH48 retention, the R14 source universe, and one owner-facing Step 05 workflow with independent product checkpoints.

Where an older source says H16/Q05 should be reused, Step 09 depends on Step 08, only six checkpoints are modeled, SPARSE/PATH controls acquisition, or H01–H44/Q01–Q14 must all be acquired, this v3.75 v1.1 plan overrides it. Historical broad-universe artifacts remain immutable evidence; they are not active R14 authorization.
