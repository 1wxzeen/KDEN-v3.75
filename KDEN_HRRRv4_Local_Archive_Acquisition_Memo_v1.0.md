# KDEN HRRRv4 Local Archive Acquisition Memo

**Version:** 1.0  
**Date:** 2026-09-11  
**Purpose:** Scientific and engineering handoff for designing a reusable local HRRRv4 archive for continuous KDEN Tmax probabilistic modeling  
**Station / target:** KDEN / contract-authoritative whole-degree-Fahrenheit daily Tmax  
**Historical source window requested:** 2021-01-01 through 2026-09-11  
**HRRR products:** `wrfsfcf` (hourly) and `wrfsubhf` (subhourly/Q15)  
**Cycle-initialization envelope requested:** all HRRR cycles whose initialization, expressed in `America/Denver`, falls from 00:00 through 14:00 inclusive on each target local date  
**Primary downstream use cases:** continuous/rolling HRRR-only MOS, GAM/GAMM, Analog Ensemble (AnEn), exact-integer PMF modeling, feature-family screening, cycle-revision studies, and later model fusion

---

## 1. Executive decision

The project now needs a **reusable, target-free, local HRRRv4 source archive** that is broader than the existing six-checkpoint KDEN Universal Issue-Time Feature Panel.

The existing feature-panel program was deliberately optimized around six fixed issue checkpoints:

- 09:00
- 09:45
- 10:00
- 10:45
- 11:00
- 11:45

and therefore retained only the small bounded set of Policy-A cycles required by those checkpoints. That was appropriate for the original KDEN v3 architecture, but it is no longer sufficient if the research program is expanded to a rolling forecast beginning near 02:00 America/Denver and updating throughout the day.

The new archive should instead preserve a broad set of **as-issued HRRRv4 forecast states** so that downstream modeling code can later reconstruct an arbitrary issue-time information set without reacquiring HRRR.

The core principle is:

> **Acquire the meteorological source universe once; decide which issue times, predictors, GAM formulas, analog metrics, or probability models to use later.**

This archive is not itself a forecast model. It is the research substrate that permits several model families to be compared fairly.

The flagship motivation is an NWP-first exact-Tmax system:

\[
P(Y_d=k \mid X^{HRRR}_{d,t}),
\]

where \(Y_d\) is final contract-authoritative KDEN daily Tmax and \(X^{HRRR}_{d,t}\) is the legal HRRR information state available at issue time \(t\).

The archive should support at least:

1. Q15-BI and H-BI baseline reconstruction;
2. pooled issue-time-aware GAM/GAMM MOS;
3. checkpoint-specific or rolling distributional MOS;
4. classical or modified Analog Ensemble searches;
5. feature screening across the full physically motivated HRRR field universe;
6. cycle-to-cycle forecast revision features;
7. exact-integer residual / PMF modeling;
8. later fusion with MADIS, NBM, LAMP, ensembles, or other forecast systems without reacquiring HRRR.

---

## 2. Why a new archive is needed

The current Universal Issue-Time Feature Panel is not a general HRRR archive.

Its scientific specification intentionally froze:

- six checkpoint rows per day;
- a cycle-retention envelope containing only Policy-A cycles selected by those checkpoints;
- a limited revision history;
- `SPARSE` versus `PATH` acquisition densities chosen around those checkpoint/peak calculations;
- future-path support that generally ends near the Q15 modeled peak plus two hours;
- Layer-1 reuse of already acquired T2m trajectories.

Those constraints made the original acquisition economical and auditable, but they also mean the resulting source mart cannot necessarily answer a later question such as:

> “What did the newest legally available HRRR run imply at 03:15, 06:45, 08:30, 12:15, or 14:50 on every day from 2021 onward?”

The new archive should be deliberately designed so that arbitrary issue-time panels are *derived from it*, rather than causing another round of historical downloads.

This memo therefore defines a **new sibling acquisition program**, not an in-place mutation of the existing Feature Panel v1 contract.

The existing Feature Panel, Layer 1, and their registries remain immutable historical work.

---

## 3. Requested historical and cycle coverage

### 3.1 Date range

Acquire HRRRv4 data for target local dates:

\[
2021\text{-}01\text{-}01
\quad\text{through}\quad
2026\text{-}09\text{-}11
\]

inclusive.

This contains **2,080 target local dates**.

The source archive may include 2026-09-11 forecast data even if the final target label for that date is not yet settlement-complete at the instant acquisition is run. Source acquisition and target-label eligibility are separate concerns.

### 3.2 Cycle range

For each target local date \(d\), acquire every HRRR cycle whose `cycle_init_utc`, when converted using the IANA timezone `America/Denver`, falls inside:

\[
00{:}00 \le c_{\text{local}} \le 14{:}00.
\]

Do **not** implement this as a fixed UTC range.

The local-to-UTC mapping changes with daylight saving time:

- MDT: local 00:00–14:00 usually corresponds to 06Z–20Z.
- MST: local 00:00–14:00 usually corresponds to 07Z–21Z.

DST transition dates require explicit handling:

- a spring-forward date contains no 02:00 civil hour;
- a fall-back date contains two distinct 01:00 civil hours with different UTC offsets.

Therefore the canonical rule is:

> enumerate native hourly UTC cycles and retain those whose converted `America/Denver` civil initialization belongs to target date \(d\) and has local clock hour 00 through 14 inclusive.

Nominally this is 15 cycles per ordinary day. For 2021-01-01 through 2026-09-11 the DST-aware schedule contains approximately **31,199 cycle-date candidates per product**: 15 on normal dates, 14 on spring-forward dates, and 16 on fall-back dates.

### 3.3 Why acquire cycles rather than issue-time rows

Issue times and cycle initialization times are different objects.

The archive should store the source cycles independent of any final forecast cadence.

If a model later issues every five minutes, many consecutive issue rows will use the same newest legal HRRR cycle. The archive should therefore not duplicate a cycle merely because many issue times refer to it.

The archive grain is the HRRR forecast source, not the forecast product row.

---

## 4. Availability / Policy-A lineage must be preserved but not used to shrink acquisition

Historical modeling must continue to emulate what would have been knowable live.

The existing project uses:

\[
\widehat{A}_{complete}(c,p)=c+105\text{ minutes}
\]

under policy ID:

`KDEN_HIST_COMPLETE_L105_V1`

subject to actual product horizon and completeness.

That policy should remain available to downstream modeling code.

However, **the new acquisition should not download only the cycles that Policy A would select at prechosen checkpoints.**

Instead:

1. archive all cycles in the requested 00:00–14:00 local initialization envelope;
2. persist each cycle's initialization, native product, horizon class, inventory identity, completeness state, and availability metadata;
3. when a downstream model requests an issue time \(t\), determine which archived cycle would have been legal under the chosen historical availability policy;
4. never let the archive itself leak a later cycle into an earlier issue-time model merely because the later cycle is now present locally.

A useful cycle table should therefore include at minimum:

- `target_day`
- `product`
- `cycle_init_utc`
- `cycle_init_local`
- `local_utc_offset`
- `dst_flag`
- `local_cycle_hour`
- `hrrr_version`
- `native_max_forecast_hour`
- `horizon_class`
- `emulated_complete_time_utc`
- `actual_first_seen_utc`, when a trustworthy value exists
- `availability_basis`
- `source_inventory_hash`
- `complete_flag`
- `missing_or_quarantine_reason`
- `retrieval_run_id`

The data archive contains possible source states. The issue-time selector decides which state is legal.

---

## 5. Critical early-day horizon caveat

This point must not be hidden during implementation.

The existing Layer-1 Policy A requires one coherent selected cycle to cover the **entire required remaining forecast grid** inside:

\[
W_{\text{future}}[d,t]
=
\{\tau\in W[d]:\tau>t\},
\]

where:

\[
W[d]=[07{:}00Z_d,07{:}00Z_{d+1}).
\]

`wrfsubhf` Q15 forecasts extend only through approximately forecast hour 18.

Therefore, although a 00:00-local HRRR cycle is old enough to satisfy the +105-minute availability emulator by approximately 02:00 local, its Q15 trajectory ends near 18:00 local. It does **not** cover the entire official remaining target window:

- in MDT, \(W[d]\) closes at roughly 01:00 local the next civil date;
- in MST, \(W[d]\) closes at roughly 00:00 local the next civil date.

Thus:

> **A 02:00 rolling Q15 forecast cannot simply reuse the original full-window Policy-A baseline definition unchanged.**

This is a modeling-policy issue, not an acquisition reason to omit the cycle.

The archive should acquire the cycle because it contains valuable early-day physical information. A later modeling specification must explicitly choose one of the following:

1. define an early-day Q15 baseline over the available FH18 trajectory and separately model residual late-tail risk;
2. use long-horizon hourly HRRR guidance as a separately identified tail predictor;
3. use an earlier extended `wrfsfcf` cycle as a tail expert;
4. define another scientifically justified baseline contract.

What must **not** happen is silently pretending that Q15 FH18 covers the full settlement window.

The acquisition code should preserve enough hourly extended-cycle information to make these later experiments possible.

---

## 6. Product separation is a binding engineering requirement

The archive must be acquired and published as two independently usable products.

### 6.1 Archive A: `wrfsfcf`

This archive should be completed, validated, and sealed independently.

Once complete, downstream modeling work may begin immediately using hourly HRRR even if the Q15 acquisition has not started or is still running.

Suggested root:

```text
hrrr_v4_local_archive/
  wrfsfcf/
    canonical/
    manifests/
    reports/
    state/
```

### 6.2 Archive B: `wrfsubhf`

This archive should have its own request plan, retrieval ledger, partitions, validation, and PASS state.

Suggested root:

```text
hrrr_v4_local_archive/
  wrfsubhf/
    canonical/
    manifests/
    reports/
    state/
```

### 6.3 Common metadata

The two products may share immutable registries and the target-date/cycle schedule:

```text
hrrr_v4_local_archive/
  common/
    registries/
    schemas/
    cycle_schedule/
    station_coordinate_eras/
```

But `wrfsfcf` completion must not depend on `wrfsubhf` completion.

The same is true in reverse.

This separation is specifically intended to allow:

> hourly modeling in the foreground while subhourly acquisition continues in the background.

---

## 7. The field universe to preserve

The new archive should inherit the physically motivated field universe from the Universal Issue-Time Feature Panel rather than re-inventing it.

### 7.1 Hourly `wrfsfcf`: H01–H44

The existing scientific registry contains 44 hourly IDs:

| ID | Parameter / level | Core role |
|---|---|---|
| H01 | HGT 700 mb | thickness / regime |
| H02 | TMP 700 mb | thermal depth / advection |
| H03 | DPT 700 mb | entrainment / cloud potential |
| H04 | UGRD 700 mb | flow / transition |
| H05 | VGRD 700 mb | flow / transition |
| H06 | HGT 850 mb | 850–700 thickness |
| H07 | TMP 850 mb | primary low-level thermal state |
| H08 | DPT 850 mb | mixed-layer moisture |
| H09 | UGRD 850 mb | cross-barrier / thermal advection |
| H10 | VGRD 850 mb | along-barrier flow |
| H11 | GUST surface | mixing / transition |
| H12 | MSLMA mean sea level | synoptic / frontal context |
| H13 | PRES surface | pressure state |
| H14 | HGT surface | static grid/station lineage |
| H15 | TMP surface | skin-air contrast |
| H16 | TMP 2 m AGL | H baseline / thermal trajectory |
| H17 | DPT 2 m AGL | near-surface moisture |
| H18 | UGRD 10 m AGL | near-surface flow |
| H19 | VGRD 10 m AGL | near-surface flow |
| H20 | MSTAV 0 m underground | moisture availability |
| H21 | SHTFL surface | sensible heating |
| H22 | LHTFL surface | latent partition |
| H23 | GFLUX surface | ground storage/release |
| H24 | HPBL surface | mixing depth |
| H25 | WEASD surface | snow-water state |
| H26 | SNOWC surface | snow-cover/albedo |
| H27 | SNOD surface | snow depth |
| H28 | TCDC boundary-layer cloud | low-level cloud |
| H29 | LCDC low cloud | solar suppression |
| H30 | TCDC entire atmosphere | total cloud regime |
| H31 | DSWRF surface | incoming solar |
| H32 | DLWRF surface | downward longwave |
| H33 | USWRF surface | reflected shortwave |
| H34 | ULWRF surface | surface longwave loss |
| H35 | CFNSF surface | HRRR cloud solar forcing |
| H36 | REFC entire atmosphere | convection / heating interruption |
| H37 | PRATE surface | precipitation onset/intensity |
| H38 | APCP surface | accumulated precipitation |
| H39 | PWAT entire atmosphere | column moisture |
| H40 | VIS surface | fog/haze/stable regime |
| H41 | AOTK entire atmosphere | smoke regime |
| H42 | HGT cloud ceiling | low-cloud geometry |
| H43 | CAPE surface | pre-convective potential |
| H44 | CIN surface | convective inhibition |

Derived quantities such as specific humidity, RH, 850–700 thickness, lapse proxies, shear, T850 advection, net radiation, evaporative fraction, Bowen ratio, surface-air contrast, and snow-density proxy should be created later from this source archive rather than changing source acquisition.

### 7.2 Subhourly `wrfsubhf`: Q01–Q14

The subhourly product is a smaller physical universe and must retain its native interval semantics:

| ID | Field | Native semantics |
|---|---|---|
| Q01 | REFC entire atmosphere | 15-min snapshot blocks |
| Q02 | VIS surface | 15-min snapshot blocks |
| Q03 | GUST surface | 15-min snapshot blocks |
| Q04 | PRES surface | 15-min snapshot blocks |
| Q05 | TMP 2 m | 15-min snapshot blocks; primary Q15 thermal path |
| Q06 | DPT 2 m | 15-min snapshot blocks |
| Q07 | UGRD 10 m | 15-min snapshot blocks |
| Q08 | VGRD 10 m | 15-min snapshot blocks |
| Q09 | UGRD 10 m | preceding 5-min average |
| Q10 | VGRD 10 m | preceding 5-min average |
| Q11 | DSWRF surface | preceding 15-min average |
| Q12 | PRATE surface | 15-min snapshot blocks |
| Q13 | APCP surface | preceding 15-min accumulation |
| Q14 | HGT cloud ceiling | 15-min snapshot blocks |

Do not reinterpret averages or accumulations as instantaneous fields.

---

## 8. Important change from the existing Feature Panel: T2m can no longer be assumed fully reusable

The current six-checkpoint implementation marks:

- H16 (`wrfsfcf` TMP 2 m) as `REUSE_L1`
- Q05 (`wrfsubhf` TMP 2 m) as `REUSE_L1`

because Layer 1 already acquired the trajectories needed by the six-checkpoint retained-cycle set.

That assumption is **not globally valid for the new archive**.

The new archive contains many cycles that Layer 1 never retained.

Therefore:

- exact H16/Q05 rows already present in sealed Layer-1 storage may be reused by exact key and lineage;
- missing H16/Q05 coverage for newly added cycles/valid times must be acquired;
- the new archive's completeness test must treat H16/Q05 exactly like any other required source field unless an identical sealed local row is proven available.

Do not create silent holes because an old registry label says `REUSE_L1`.

---

## 9. Temporal-density policy for this reusable archive

The current Feature Panel used `SPARSE` and `PATH` classes to minimize downloads around six checkpoints and Q15 peak windows.

For the new reusable research archive, that optimization risks creating irreversible gaps.

### Recommended archive-level rule

For every dynamic hourly field H01–H44 except static H14:

> retain every native hourly forecast-valid state available from the cycle initialization through the end of the required target-support envelope, capped by the product's native horizon.

For `wrfsubhf` Q01–Q14:

> retain every native subhourly block in the cycle's available forecast horizon that belongs to the chosen target-support envelope.

A practical support envelope is:

\[
[c,\ \min(c+\text{native horizon},\ W[d]_{\text{end}})]
\]

with optional retention of cycle-to-issue history before \(W[d]\) begins when the cycle initialized before the fixed 07Z target-window boundary.

This recommendation is intentionally broader than the existing `SPARSE`/`PATH` plan because the research questions are no longer frozen.

It allows later investigators to derive:

- current-state features;
- full forecast trajectories;
- pre-peak integrals;
- fixed-window summaries;
- late-clearing / secondary-peak features;
- revision features on common support;
- AnEn trajectory descriptors;
- arbitrary rolling issue-time states.

### Cost warning

Full-path retention of the entire 44-field hourly universe over 00:00–14:00 cycles is materially larger than the old six-checkpoint source plan.

A representative pilot and cost extrapolation are mandatory before the owner starts the historical run.

If the full-path cost is unacceptable, reducing temporal density must be an explicit scientific compromise, not an implementation shortcut.

---

## 10. Forecast-hour / target-window handling

### `wrfsubhf`

Preserve the available Q15 forecast blocks through native FH18, subject to the target-support cap.

The exact block identities must be discovered from `.idx` plus decoded GRIB metadata, not inferred from record numbers.

### `wrfsfcf`

Preserve ordinary hourly forecasts and retain extended-cycle leads where the source provides them and where they are relevant to the target-day support.

The hourly product is important not only because it contains the richer physical feature universe, but also because selected UTC cycles have longer native horizons than Q15.

This may become the mechanism for representing late-day/tail risk in early issue-time forecasts.

### No fake trajectory stitching

Even if an early forecast later uses both:

- a recent Q15 path, and
- an older or extended hourly tail,

the source archive should keep those cycles separately identified.

Do not concatenate them into one synthetic HRRR trajectory at acquisition time.

Any future multi-source tail model must know exactly which initialization generated each predictor.

---

## 11. Spatial extraction

Reuse the scientifically audited KDEN coordinate-era and projected-bilinear geometry from Layer 1.

The source archive should preserve enough local spatial information to avoid future reacquisition.

### Point statistics

Retain:

- projected bilinear (`BI`) where the registry calls for smooth continuous point extraction;
- nearest node (`NN`) where appropriate for accumulations/categorical support.

### Local tiles

For fields whose existing registry calls for 3×3 or 9×9 information, retain the compact local tile when cost permits, not only today's chosen summary.

Examples include:

- 3×3: 700/850 temperature/height, MSLMA, reflectivity;
- 9×9: cloud, radiation, reflectivity, precip, visibility, ceiling, CAPE/CIN, AOTK.

This is valuable because later modeling may want different physically motivated summaries without another HRRR download.

One GRIB message provides the source field needed for all these local spatial summaries; the network request should not be multiplied simply because several local statistics are retained.

---

## 12. Canonical long-table schema

The archive should be model-agnostic and long-form.

Recommended primary grain:

```text
product
cycle_init_utc
valid_time_utc
field_registry_id
spatial_stat_or_tile_cell
```

with target-date context attached.

Minimum columns should include:

```text
target_day
cycle_init_utc
cycle_init_local
local_cycle_hour
utc_offset_minutes
dst_flag

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
spatial_stat
tile_row
tile_col
value

coverage_flag
missing_reason
selector_identity
source_uri_redacted
source_idx_hash
source_hash
byte_start
byte_end
decoded_grib_identity
retrieval_run_id
derivation_version
```

Static H14 may be stored once per HRRR grid/version and referenced rather than repeated.

Derived feature tables must remain downstream of this canonical source archive.

---

## 13. Retrieval strategy

Reuse the proven engineering pattern from the existing KDEN feature-panel acquisition.

For each source object:

1. request the `.idx` inventory first;
2. parse record start offsets;
3. select by full message identity:
   - parameter,
   - level/layer,
   - step type,
   - interval semantics,
   - valid time;
4. require exactly one supported match;
5. range-fetch only the matched GRIB message bytes;
6. verify HTTP response status and `Content-Range`;
7. decode the GRIB message and re-verify its identity;
8. extract only the KDEN point/tile values required by the registry;
9. convert units deterministically;
10. publish an append-only Parquet partition and retrieval-ledger row;
11. discard transient GRIB bytes only after extracted values, hashes, and manifests are durable.

Never use GRIB record number alone.

Never fall back to downloading/retaining the full CONUS GRIB file merely because a selector fails.

Selector drift should quarantine the object and fail the affected partition.

---

## 14. Partitioning and resumability

Recommended physical partitioning:

### Hourly

```text
wrfsfcf/canonical/
  year=YYYY/
    month=MM/
      cycle_date=YYYY-MM-DD/
        cycle=<UTC token>/
```

### Subhourly

```text
wrfsubhf/canonical/
  year=YYYY/
    month=MM/
      cycle_date=YYYY-MM-DD/
        cycle=<UTC token>/
```

The actual table key remains UTC-based.

Every published partition should have:

- deterministic sort order;
- row count;
- coverage summary;
- SHA-256;
- source-count reconciliation;
- missing/quarantine counts.

Resume must verify hashes of already published partitions before skipping them.

A `done=true` flag is not sufficient.

Graceful interruption should finish or roll back the current atomic work unit, persist progress, and allow the owner to resume using the same run ID.

---

## 15. Separate acquisition-state contracts

A suggested state structure:

```text
state/
  WRFSFCF_READY_FOR_OWNER_RUN.json
  WRFSFCF_RUNNING.json
  WRFSFCF_PAUSED.json
  WRFSFCF_PASS.json

  WRFSUBHF_READY_FOR_OWNER_RUN.json
  WRFSUBHF_RUNNING.json
  WRFSUBHF_PAUSED.json
  WRFSUBHF_PASS.json
```

The hourly PASS should be sufficient to declare the hourly archive model-ready.

It should not wait for the subhourly PASS.

Likewise, the subhourly validation should not alter or invalidate the sealed hourly archive unless a shared upstream contract itself changes.

---

## 16. Required pilot before historical owner-full execution

The new archive is much larger than the old checkpoint-bounded request plan.

Before full acquisition, run a representative pilot that covers:

- at least one winter week;
- at least one spring week;
- at least one summer week;
- at least one fall week;
- early, middle, and late HRRRv4 archive dates;
- both KDEN coordinate eras;
- ordinary and extended hourly cycles;
- both DST regimes;
- one spring-forward date;
- one fall-back date;
- all H01–H44 selectors;
- all Q01–Q14 selectors;
- multiple forecast-hour files, including late Q15 blocks.

The pilot must report:

- `.idx` selector hit rate;
- decode success;
- requests;
- bytes;
- retries;
- wall time;
- decode time;
- local extraction time;
- parquet size;
- expected full-history wall time;
- expected full-history disk use;
- missing-file rate;
- quarantine rate;
- field-specific missingness;
- value min/max/quantiles;
- H16/Q05 parity against existing Layer-1 rows where overlap exists.

No full-history run should start until this cost envelope and selector audit pass.

---

## 17. Acceptance gates

At minimum, the final archive should satisfy:

### Identity and source integrity

- every requested field matches the frozen H/Q registry;
- every decoded message identity matches the `.idx` selection;
- all source hashes and byte ranges reconcile;
- no unplanned source substitution occurs.

### Time integrity

- all cycle timestamps are timezone-aware UTC;
- `cycle_init_local` is derived using `America/Denver`;
- DST transition dates are correct;
- valid times are strictly ordered within cycle/field after deduplication;
- interval fields preserve start/end semantics.

### Product integrity

- `wrfsfcf` and `wrfsubhf` are separate;
- cross-product composites are not materialized in the raw source archive;
- Q09/Q10 remain 5-minute averages;
- Q11 remains a preceding 15-minute average;
- Q13 remains a preceding 15-minute accumulation.

### Spatial integrity

- KDEN coordinate era matches Layer 1;
- projected BI parity passes on overlapping H16/Q05 rows;
- BI weights sum to one;
- tile centers match the audited HRRR grid geometry.

### Coverage integrity

- every planned cycle is either complete, explicitly missing, or quarantined;
- every planned field/time is either present or has a machine-readable missing reason;
- the retrieval ledger reconciles exactly to the request plan.

### Reproducibility

- rebuilding a bounded pilot from the same source/config produces value-identical canonical output.

---

## 18. Truth isolation and leakage boundary

The local HRRR archive itself should contain **no target values**.

Do not import:

- official daily Tmax;
- final CLI values;
- Weather.com settlement values;
- residuals;
- absolute errors;
- market prices;
- winning bands;
- post-event labels.

Truth should live in a separate training-label sidecar and be joined only after an issue-time legal feature view has been constructed.

This is important because the archive is intended to be a permanent inference-compatible source mart.

---

## 19. How rolling issue-time models should use the archive

After acquisition, create issue rows at any desired cadence, for example:

\[
02{:}00,\ 02{:}15,\ 02{:}30,\ldots
\]

or eventually every five minutes.

For each issue time \(t\):

1. determine the native HRRR cycles archived by that time;
2. apply the chosen availability policy;
3. choose the newest legal cycle for each product under that modeling contract;
4. materialize the HRRR state/path features that are known at \(t\);
5. never use a cycle that became legal after \(t\);
6. preserve the full native cycle identity on every feature row.

This means a 15-minute forecast grid does **not** require four HRRR cycles per hour.

Many issue rows will reuse the same HRRR initialization until the next cycle becomes legally complete.

---

## 20. Baseline reconstruction

The new NWP-only backbone should preserve at least two raw baseline families.

### Q15-BI

\[
B^{Q15}_{d,t}
\]

constructed from `wrfsubhf` 2-m temperature using the audited projected-bilinear KDEN extraction.

This is the primary temporally dense HRRR T2m baseline based on the Layer-1 evidence.

### H-BI

\[
B^{H}_{d,t}
\]

constructed from `wrfsfcf` 2-m temperature using the same spatial method.

This remains a protected hourly challenger / tail reference.

### MADIS floor is not part of the archive baseline

`Q15-BI-FLOOR` and `H-BI-FLOOR` remain historically important Layer-1 benchmarks, but this new archive is intended to support a clean HRRR-only MOS branch.

The acquisition therefore must be capable of reconstructing Q15-BI and H-BI independently of MADIS.

MADIS can be added later as a separate information source.

---

## 21. Downstream GAM/GAMM use

The archive should permit a model such as:

\[
Y_{d}
=
B_{d,t}
+
g(X^{HRRR}_{d,t})
+
\epsilon_{d,t},
\]

or a distributional/ordinal variant.

The full 44-field hourly universe should be available so that candidate features can be evaluated across:

- thermal state;
- moisture;
- flow/advection;
- cloud/radiation;
- energy/PBL;
- snow/ground state;
- weather-transition variables;
- cycle stability;
- spatial gradients/spread.

The archive should not decide the final GAM formula.

Feature normalization, smooth selection, interactions, imputation, and calibration belong inside rolling-origin training folds.

---

## 22. Downstream Analog Ensemble use

The same archive should support AnEn without forcing all 44 fields into the distance metric.

The expected workflow is:

1. retain the broad source universe locally;
2. derive candidate physical summaries;
3. screen individual fields / feature families;
4. reduce redundant collinear features;
5. forward-select a small analog-search state based on out-of-fold probabilistic score;
6. search historical HRRR states for the nearest analogs;
7. use historical KDEN outcomes or, preferably, historical HRRR residuals to construct today's empirical distribution.

For example:

\[
e_i=Y_i-B_i,
\qquad
Y^{*}_{i,t}=B_t+e_i.
\]

The archive therefore needs both:

- enough physical information to identify relevant forecast regimes;
- exact cycle/path lineage so analog states are constructed from comparable as-issued HRRR information.

The field universe used for acquisition may be broad even if the eventual AnEn distance uses only 3–8 compressed predictors.

---

## 23. Feature-family compression should happen after acquisition

Likely physics families include:

- **baseline / thermal trajectory**
  - Q15-BI
  - H-BI
  - peak time
  - heating trajectory
- **lower-tropospheric thermal state**
  - T850
  - T700
  - 850–700 thickness
- **flow/advection**
  - U/V at 850/700/10 m
  - cross-barrier wind
  - T850 advection
- **radiation/cloud**
  - DSWRF
  - low/total cloud
  - cloud solar forcing
  - net radiation
- **mixing/energy**
  - HPBL
  - sensible/latent flux
  - ground flux
- **moisture**
  - DPT
  - PWAT
  - dewpoint depression
- **ground/snow**
  - WEASD
  - SNOWC
  - SNOD
  - MSTAV
- **weather transitions**
  - pressure
  - precipitation
  - reflectivity
  - CAPE/CIN
  - ceiling/visibility
- **forecast stability**
  - cycle revisions
  - Q15/H disagreement
  - peak-time revisions

Because many of these variables are physically correlated, later AnEn or GAM work can compress them.

That compression should not force another acquisition.

---

## 24. Model-validation implications

Although a rolling panel may contain hundreds of rows per target day, the final target is still one daily Tmax realization.

All issue rows for the same target day must remain in the same evaluation fold.

Recommended evaluation remains rolling-origin / forward-chaining by target date.

Any feature selection, analog weight tuning, number-of-neighbors selection, normalization, GAM smooth selection, calibration, or neural tuning must occur inside the training portion of each fold.

The existence of many issue rows must not be treated as thousands of independent Tmax events.

---

## 25. Core archive scale

Requested source window:

- 2,080 target local dates;
- nominally 15 local initialization hours per ordinary day;
- DST-aware total: approximately 31,199 cycle-date candidates per product;
- approximately 62,398 product-cycle bundles across the two products before remote gaps.

This is much larger than the original six-checkpoint feature acquisition.

The archive must therefore rely on:

- `.idx`-driven byte-range retrieval;
- local point/tile extraction;
- no full-domain GRIB persistence;
- persistent HTTP connections;
- bounded internal concurrency;
- resumable atomic partitions;
- exact cache keys;
- robust progress writing.

The existing optimized KDEN acquisition code should be reused or ported rather than rewriting these mechanisms from scratch.

---

## 26. Explicit non-goals

This acquisition project does **not**:

- fit the GAM;
- fit AnEn;
- choose AnEn predictors;
- choose \(K\);
- train a neural network;
- create final probability distributions;
- use MADIS;
- add a deterministic MADIS floor;
- incorporate Kalshi prices;
- optimize trading P&L;
- decide whether HRRRv2/v3 should be pooled with v4;
- silently redefine Policy A;
- splice cycles;
- backfill later cycles into earlier issue rows.

Its responsibility ends when a complete, auditable, model-agnostic HRRRv4 local source archive exists.

---

## 27. Recommended optional extensions that are **not** part of the requested core scope

These should be discussed explicitly rather than added silently.

### 27.1 Previous local 23:00 cycle

If cycle-to-cycle revisions are desired immediately at the earliest 02:00 issue time, c00 has no predecessor inside the requested 00:00–14:00 local cycle envelope.

Adding the previous date's 23:00-local cycle would permit c00-minus-c23 revision features.

### 27.2 Latest pre-midnight extended hourly cycle

During some timezone regimes, the latest extended `wrfsfcf` cycle useful for full-target-window tail guidance at 02:00 may initialize before local midnight.

A separately costed “tail-anchor” extension could retain the newest extended hourly cycle available before the local 00:00 boundary.

This may be useful if strict full-target-window guidance is required from the earliest issue times.

### 27.3 Later-than-14:00 cycles

The requested source envelope stops at a 14:00-local initialization.

Under the +105-minute historical emulator, that 14:00 cycle is not treated as complete until roughly 15:45.

If production forecasts will continue much later in the afternoon and should continue rebasing onto newer NWP, later cycle initializations may eventually be worth acquiring.

The core archive should not expand beyond 14:00 without explicit owner approval.

---

## 28. Questions the coding agent should resolve in design, not by assumption

Before owner-full acquisition, the implementation agent should return explicit answers to:

1. What exact archive endpoint/source will be used for each historical era?
2. Are all H01–H44 selectors stable across representative HRRRv4 dates?
3. Are all Q01–Q14 repeated blocks selected unambiguously by full identity and interval metadata?
4. What forecast-hour files exist for ordinary versus extended hourly cycles?
5. What exact target-support cap will be used for long hourly forecasts?
6. What is the projected request count / byte volume under full-path retention?
7. What compact tile representation will be stored for 3×3/9×9 fields?
8. Which existing Layer-1 H16/Q05 rows can be reused by exact key?
9. How are DST transition days enumerated?
10. How will interrupted owner-full acquisitions resume without duplicate work?
11. How will true remote gaps be distinguished from selector/code failures?
12. How will source/version drift be surfaced?
13. Can the hourly archive be sealed and modeled without importing or waiting for the Q15 archive?
14. Can the Q15 archive be validated independently against overlapping Layer-1 data?

Any unresolved item should produce a blocker or bounded diagnostic, not a silent fallback.

---

## 29. Proposed implementation sequence

### Phase A — scaffold and registries

- create a new sibling archive root;
- import/freeze H01–H44 and Q01–Q14 source registries;
- import KDEN coordinate-era registry;
- implement DST-aware target-date/cycle scheduler;
- define canonical schemas.

### Phase B — request planners

Create two independent planners:

```text
plan_wrfsfcf
plan_wrfsubhf
```

Each should:

- enumerate target dates;
- enumerate native UTC cycles matching local 00:00–14:00;
- enumerate legal native forecast support;
- intersect with target-support rules;
- expand field selectors;
- deduplicate source objects;
- estimate requests/bytes;
- write a sealed plan.

### Phase C — bounded pilots

Run seasonal/version/DST representative slices.

Do not start full history until selectors, spatial parity, and cost estimates pass.

### Phase D — hourly owner-full acquisition

Run `wrfsfcf` first.

On completion:

- terminal validate;
- write PASS;
- freeze manifests;
- permit modeling against the hourly archive.

### Phase E — Q15 owner-full acquisition

Run `wrfsubhf` independently.

Hourly model development can proceed while this longer acquisition runs.

### Phase F — archive readers

Implement:

- raw long-table reader;
- cycle selector;
- issue-time legal-state reader;
- baseline reconstruction helper;
- model-view builder.

Do not embed target labels in any production reader.

---

## 30. Final scientific objective

The archive exists to support the following research question:

> **How early in the KDEN target day can an HRRRv4-based, hyperlocal statistical postprocessor place a sharp, calibrated probability distribution on the exact integer daily Tmax?**

The first major model comparisons should include:

\[
\text{Q15-BI / H-BI raw baselines}
\]

versus:

\[
\text{distributional or ordinal GAM/GAMM MOS}
\]

versus:

\[
\text{HRRR Analog Ensemble MOS}
\]

and potentially later:

\[
\text{small nonlinear / neural challenger}.
\]

The broad source archive should make those comparisons possible without another major historical HRRR download.

The archive should therefore be judged not by whether every retained field enters the final model, but by whether it preserves the physically serious HRRR information needed to let later statistical learning determine which small subset of variables actually produces the earliest sharp and calibrated KDEN Tmax distribution.

---

## 31. Source documents governing this memo

This memo is derived from, and should be used alongside:

1. **KDEN Universal Issue-Time Feature Panel Scientific Specification v1.0**
   - source-field universe;
   - H01–H44 registry;
   - Q01–Q14 registry;
   - time/lineage contracts;
   - same-cycle rules;
   - spatial operators;
   - leakage policy.

2. **KDEN Universal Issue-Time Feature Panel Implementation Manual v1.0**
   - `.idx` / byte-range retrieval pattern;
   - append-only publication;
   - owner-controlled full acquisition;
   - resumability;
   - retrieval ledgers;
   - selector/semantics validation;
   - canonical long-table philosophy.

3. **KDEN Layer 1 Baseline Forecast Specification / Scientific Record**
   - fixed 07Z–07Z target window;
   - Policy A;
   - product-specific horizon sufficiency;
   - `KDEN_HIST_COMPLETE_L105_V1`;
   - projected-bilinear KDEN extraction;
   - Q15 versus H trajectory semantics;
   - established Q15-BI / H-BI baseline lineage.

Where this memo deliberately differs from Feature Panel v1, the difference is explicit:

> Feature Panel v1 is checkpoint-bounded. This new archive is a broader reusable source layer intended to support continuous issue-time modeling and must be implemented as a new version/project rather than silently altering the historical v1 contract.
