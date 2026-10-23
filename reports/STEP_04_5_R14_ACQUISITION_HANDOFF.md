# KDEN v3.75 — approved R14 field universe and coding handoff

**Decision recorded: 14 September 2026. Status: OWNER-SELECTED FOR IMPLEMENTATION.**

**Adoption recorded: 14 September 2026.** The owner subsequently authorized the R14 migration plan. `PROJECT.md` v1.1 and `config/r14_acquisition_v375.json` now govern implementation. This handoff remains the authoritative scientific field-selection record; where implementation choreography is concerned, the newer project contract governs.

The owner accepted the final 14-source recommendation: “ok then, we go with R14.” This document records the selected acquisition universe for the coding agent. It is a source-field decision, not a 14-column model specification or a record of completed predictive experiments.

## 1. Authoritative selection

**R14 = R13 − H33 + H02 + H38.**

This is **not the earlier R14-P**, which added H38 to R13 while retaining H33. The approved R14 **includes T700 (H02) and hourly precipitation amount (H38), and excludes reflected solar (H33)**. Use the explicit lists below, not a name-based inference from an older report.

```text
Dynamic hourly — wrfsfcf, 12 identities:
H02 H07 H16 H17 H18 H19 H24 H26 H28 H31 H36 H38

Static terrain — wrfsfcf, 1 identity:
H14

Subhourly — wrfsubhf, 1 identity:
Q05
```

The owner chose a practical meteorological judgment about descriptive coverage, redundancy, and acquisition cost. Earlier C32/R13 recommendations and their “pending cohort” language are supplementary research context; they do not override this accepted field list or require a full-58 selection acquisition before implementing it. No experiment-derived nonredundancy claim or scientific PASS is implied. Existing engineering validation and owner-run boundaries still apply.

## 2. Exact source identities

Preserve the existing field IDs, exact selectors, decoded GRIB identity allowlists, units/conversions, and interval validation from the current registries. Do not renumber retained IDs or select by short name alone.

| ID | Product | Parameter | Level | Step type / interval | Native cadence | Existing spatial contract |
|---|---|---|---|---|---|---|
| H02 | wrfsfcf | TMP | 700 mb | instant / 0 min | 60 min | POINT_BI_TILE3_V1 |
| H07 | wrfsfcf | TMP | 850 mb | instant / 0 min | 60 min | POINT_BI_TILE3_V1 |
| H14 | wrfsfcf | HGT | surface | instant / static snapshot | once | GRID_STATIC_ONCE_V1 |
| H16 | wrfsfcf | TMP | 2 m above ground | instant / 0 min | 60 min | POINT_BI_NN_V1 |
| H17 | wrfsfcf | DPT | 2 m above ground | instant / 0 min | 60 min | POINT_BI_V1 |
| H18 | wrfsfcf | UGRD | 10 m above ground | instant / 0 min | 60 min | POINT_BI_V1 |
| H19 | wrfsfcf | VGRD | 10 m above ground | instant / 0 min | 60 min | POINT_BI_V1 |
| H24 | wrfsfcf | HPBL | surface | instant / 0 min | 60 min | POINT_BI_V1 |
| H26 | wrfsfcf | SNOWC | surface | instant / 0 min | 60 min | POINT_BI_V1 |
| H28 | wrfsfcf | TCDC | boundary-layer cloud | instant / 0 min | 60 min | POINT_BI_TILE9_V1 |
| H31 | wrfsfcf | DSWRF | surface | instant / 0 min | 60 min | POINT_BI_TILE9_V1 |
| H36 | wrfsfcf | REFC | entire atmosphere | instant / 0 min | 60 min | POINT_BI_TILE9_DERIVE3_V1 |
| H38 | wrfsfcf | APCP | surface | accum / preceding 60 min | 60 min | POINT_NN_TILE9_V1 |
| Q05 | wrfsubhf | TMP | 2 m above ground | instant / 0 min | 15 min | POINT_BI_NN_V1 |

Canonical units remain K for TMP/DPT, m s−1 for wind, m for HPBL and converted HGT, % for SNOWC/TCDC, W m−2 for DSWRF, dBZ for REFC, and kg m−2 for APCP. HGT retains the registered gpm-to-m conversion. H31 is an instantaneous hourly flux, not Q11's interval mean. H38 is an interval amount, not a rate; preserve the existing FH00 and accumulation validation rules without fabricating values for unavailable intervals.

Explicitly excluded from the full-history field universe:

```text
Hourly — 31 identities:
H01 H03 H04 H05 H06 H08 H09 H10 H11 H12 H13 H15
H20 H21 H22 H23 H25 H27 H29 H30 H32 H33 H34 H35
H37 H39 H40 H41 H42 H43 H44

Subhourly — 13 identities:
Q01 Q02 Q03 Q04 Q06 Q07 Q08 Q09 Q10 Q11 Q12 Q13 Q14
```

Do not acquire excluded messages merely because a historical composite or feature builder expects them. Adapt eligibility and dependencies to the approved source list.

## 3. Brief scientific rationale

- **H16/Q05/H14:** preserve both independent temperature baselines and terrain lineage.
- **H07/H02:** retain lower and middle-level thermal context for surface coupling and mixing. T850 has local D1 support; T700 adds vertical thermal information. The accepted KDEN context treats 850 mb as above ground.
- **H17/H18/H19/H24:** represent moisture boundaries, the complete surface wind vector, and shallow versus deep mixing.
- **H26/H28/H31:** represent snow-covered ground, lower-cloud persistence, and incoming sunlight.
- **H36/H38:** distinguish modeled nearby weather from precipitation reaching the ground and potential wetting/heating interruption.

Other pressure, cloud, radiation, flux, snowpack, and Q diagnostics were omitted to limit overlapping descriptions and acquisition cost. H33 was displaced by H02 because minimal vertical thermal context gets priority over explicit albedo. Aloft wind vectors and CAPE/CIN are deliberate information sacrifices; the retained sources do not reconstruct them. These are meteorological priorities, not findings that excluded fields have zero predictive value.

Retire unsupported composites: exact pressure-dependent specific humidity, aloft shear/advection, 850–700 height thickness, geometric lapse rate, net shortwave/albedo, net longwave/total radiation, turbulent-flux partition, snow density, and CAPE/CIN. T850−T700 remains a temperature difference; hourly solar integration is approximate. The acquisition union supports AnEn, distributional GAM/GAMM, and ordinal models, each with its own later derived-feature subset.

## 4. Acquisition behavior to preserve

- HRRRv4 only; target dates **2021-01-01 through 2026-09-11 inclusive**, 2,080 days. Do not extend the end date to the date of this handoff.
- Fixed target window **[07Z_d, 07Z_(d+1))**. An archived endpoint state must not enter the right-open target maximum.
- Previous-local-day **c23**, then target-local **c00–c14**; preserve native UTC identities and America/Denver DST handling, FH00, discovered native horizons, and the `TARGET_WINDOW` ceiling.
- Every retained dynamic H follows its **full native hourly path**; Q05 follows its **full native 15-minute path**. Do not revive historical SPARSE/PATH control, selected-checkpoint acquisition, cycle cuts, or cross-cycle splicing.
- Independently reacquire H16 and Q05; do not reuse older Layer 1 archives or substitute interpolated hourly temperatures for Q05. Preserve independent product plans, completeness, and PASS handling.
- Preserve `KDEN_HIST_COMPLETE_L105_V1`, availability metadata, issue-time legality, both coordinate eras, fail-closed source semantics, lineage, QC, retry/resume, and source/truth/model separation. No MADIS, current-day observed floors, or market information enters this source branch.

**Spatial implementation:** retain the registered supports above as the baseline. The accepted recommendation also relies on compact upstream context, not only a KDEN point. Carry forward section 5.2 of the R13 report: west/foothill, north/northeast plains, east plains, and south/southeast/Palmer Divide sectors, initially around 30/60 km, with appropriate surface-state, cloud, solar, echo, precipitation, and snow sampling. Exact cells, offsets, operators, terrain checks, and schemas remain an implementation detail to specify and version before full-history acquisition; those proposed distances are not already sealed geometry. Preserve matching static terrain and coordinate-era lineage. New high-terrain supports require their own isobaric validity checks. Extract chosen supports before transient GRIB disposal. Additional extraction from an already retrieved message need not add source-message requests, but output and processing costs must be measured.

## 5. Engineering handoff and expected cost

Build the successor R14 acquisition configuration/plans using existing validated infrastructure. Preserve the original registries, sealed plans, and Step 04 PASS; record the owner-selected scope change explicitly in the successor specification. Reconcile older broad-universe requirements with this decision rather than silently mixing universes.

1. Create versioned R14 field/spatial contracts and update affected derived-feature eligibility.
2. Regenerate both product request plans, hashes, and counts; rerun affected validations.
3. Prepare the bounded confirmation pilot and owner commands under the existing execution policy. Check identities, intervals, spatial extraction, H/Q parity, deterministic output, and resume behavior; remeasure end-to-end throughput.
4. Deliver **READY_FOR_OWNER_RUN** with exact commands and updated projections. Acceptance of R14 is not an instruction to launch the multi-day full-history run automatically.

Expected request accounting, using the current frozen state counts:

```text
wrfsfcf: 12 × 585,085 + 1 static = 7,021,021
wrfsubhf: 1 × 2,173,943          = 2,173,943
total                            = 9,194,964 logical requests
```

At the previous selected rate of 15.5038778794 requests/s: **164.74 hours / 6.86 continuous days**, versus C32's 15.91 days. This is a first-order projection, not a guaranteed seven-day maximum. Reconcile any count differences explicitly against successor plans; do not trim required cycles to force the estimate.

**Implementation correction adopted in PROJECT v1.1:** the counts above came from the historical planner, which included native states exactly at the nominal 07Z endpoint. The handoff's binding window is right-open, so those endpoint states are excluded. The corrected pre-plan expectation is 6,762,997 `wrfsfcf` requests plus 2,156,601 Q05 requests, or 8,919,598 total (about 159.81 hours / 6.66 days at the same rate). Successor plan manifests remain authoritative.

## 6. Supporting documents and identity references

Read this handoff first for the final selection. Use the following for supporting rationale and existing implementation contracts:

- [Step 04.5 research brief](../STEP_04_5_FEATURE_UNIVERSE_STUDY.md).
- [C32 recommendation and earlier budget reconsideration](step_04_5_feature_universe_scientific_recommendation.md).
- [R13 meteorological reduction study](step_04_5_c32_reduction_meteorological_study.md), especially mechanisms, cadence, spatial context, and full field audit. Its R13/R14-P selections are superseded by this handoff.
- [Current project specification](../PROJECT.md) and [Not bundled: pilot report](../DATA_AVAILABILITY.md#not-bundled).
- [Hourly registry](../registries/hrrr_hourly_v375.csv), [subhourly registry](../registries/hrrr_subhourly_v375.csv), and [decoded GRIB identities](../registries/decoded_grib_identities_v375.json).

This handoff records the decision only. No acquisition code, registry, sealed plan, or PASS was changed while preparing it.
