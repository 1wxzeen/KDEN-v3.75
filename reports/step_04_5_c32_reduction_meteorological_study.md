# KDEN v3.75: reducing C32 to a seven-day acquisition candidate

Research date: 13 September 2026. **New, standalone scientific recommendation; documentation only.**

## 1. Recommendation and exact proposed universe

**REVISE C32 to the R13 candidate below for selection testing. Recommend R13 as the proposed full-history acquisition universe if it passes the Step 04.5 selection process.** Its request-scaled runtime is **154.26 hours, or 6.43 continuous days**, approximately **59.6% less than C32**. C32's 15.91 days are not justified merely by the fact that its fields each have a meteorological interpretation.

R13 deliberately represents fewer physical quantities. It prioritizes predictors of **temperature forecast error**, rather than acquiring enough variables to reconstruct every term of the atmosphere's energy and momentum budgets. This distinction is the principal reason a substantially smaller universe is scientifically worth testing.

| Retain | Source | Distinct question it is intended to answer, conditional on the other retained sources |
|---|---|---|
| H07 | 850-mb temperature | Is the lower-air-mass thermal state consistent with the model's surface temperature response? |
| H14 | Static surface height | What model terrain supports each extracted value? Protected lineage, essentially no repeated cost. |
| H16 | Hourly 2-m temperature | What does the independent hourly product predict? Protected baseline. |
| H17 | 2-m dewpoint | Is the site in a different moisture/air-mass regime despite similar temperature, and how dry is the near-surface air? |
| H18, H19 | 10-m U/V vector | Which surface flow regime reaches KDEN, and where are the forecast wind transitions and convergence? |
| H24 | Boundary-layer depth | Does the model expect shallow isolation or substantial vertical mixing? |
| H26 | Snow-covered fraction | Is heating occurring over a snow-covered or patchy surface, including when solar ratios are unavailable? |
| H28 | Boundary-layer cloud fraction | Is low cloud associated with a shallow/cloudy boundary layer, rather than just reduced sunlight? |
| H31 | Downward shortwave radiation | How much solar input and forecast clearing opportunity remain? |
| H33 | Upward shortwave radiation | How much incoming sunlight is reflected rather than absorbed? |
| H36 | Composite reflectivity | Does modeled precipitation-bearing weather approach, develop near, or miss the site? |
| Q05 | Native 15-minute 2-m temperature | What intrahour temperature trajectory, peak timing, and hourly/Q disagreement does the independent Q product predict? Protected baseline. |

Exact identity list:

```text
11 dynamic hourly identities:
H07 H16 H17 H18 H19 H24 H26 H28 H31 H33 H36

1 static hourly identity:
H14

1 subhourly identity:
Q05
```

**R13 is a strict subset of C32.** Remove these 19 C32 identities from the proposed full-history list:

```text
H01 H02 H03 H04 H05 H09 H10 H12 H13
H15 H21 H22 H25 H32 H34 H38 H43 H44 Q11
```

All 58 identities remain in the separately approved **selection cohort**. The 45 identities excluded from R13 are not being declared empirically useless. The matrix assigns them `RETAIN_CHALLENGER_PENDING_COHORT`, which means retain for that limited research acquisition, not for the proposed full-history archive. There are no completed `DROP_*` findings because no new KDEN ablations have been run. This is the distinction required by the brief, not an instruction to download all 58 for all 2,080 days.

**What changes from the earlier seven-day suggestion:** the prior report's C13 kept H13 surface pressure and omitted H33. This new **R13 exchanges H13 for H33**, at equal first-order cost. The reason is that absorbed solar energy is central to daytime Tmax, and snow fraction does not determine snow albedo. Surface pressure tendency remains useful but competes with the retained surface wind/moisture/temperature transitions. Section 3 explains this proposed priority; it is not an established performance ranking.

The preferred first single-field addition is **H38 hourly precipitation amount**, producing **R14-P**, at **6.86 projected days**. It distinguishes precipitation reaching the ground and persistent wetting from echoes alone. Do not add it automatically: test it against equal-cost alternatives, particularly surface pressure, 700-mb temperature, downward longwave, and snow water. R13 leaves more runtime margin than R14-P.

### What “nonredundant” can honestly mean here

The achievable target is **a small union in which each discretionary source has stable incremental probability value, or belongs to a jointly useful physical group**. It is not statistical independence, zero correlation, or a complete causal explanation of every failure. Temperature, cloud, radiation, moisture, and mixing are physically coupled. H16 and Q05 also intentionally overlap because the contract protects independent products.

No paper establishes that this exact R13 list is internally nonredundant for KDEN. That requires the specified cohort. This report supplies an actual list, a meteorological reason for each choice and omission, and falsifiable tests. It does not claim an unperformed feature-selection experiment has already succeeded. Production registries must remain unchanged until the selection and versioned approval process is complete.

## 2. Evidence, scope, and the cost constraint

The primary local sources are the supplied [Step 04.5 brief][L1], [Universal Panel scientific specification][L2], [D1 synthesis][L3], and [previous recommendation][L4]. Current identities and costs were checked against the brief-referenced [hourly registry][L5], [subhourly registry][L6], [pilot report][L7], and [PROJECT.md][L8]. Historical document instructions are treated as historical design evidence. The user's current request authorizes this new research document, not production changes or long experiments.

The literature review focuses on Front Range weather and HRRR temperature-error pathways, including additional work on cloud-related solar biases and surface fluxes. Evidence is classified as:

- **Local empirical:** D1's KDEN regression results, within its actual population and forecast construction.
- **Regional meteorological:** Front Range observations and Denver operational studies.
- **Model/process:** HRRR documentation and evaluations elsewhere; these support mechanisms, not a KDEN effect size.
- **Hypothesis:** this report's acquisition priorities, derived features, and expected conditional redundancy. These need the cohort.

The date range contains 2,080 target days. Preserve the previous-local c23 and target-local c00–c14 cycles, FH00, native horizons capped by `TARGET_WINDOW`, full native paths for every retained field, independent H/Q identities, coordinate-era provenance, and current availability emulation. Assess issues 02:00–16:00 America/Denver, with emphasis through 14:00. DST identities remain UTC-explicit. A quarter-hour output is not a quarter-hour model initialization.

The target remains `W[d] = [07Z_d, 07Z_(d+1))`. Any archived right-endpoint state is excluded from the target maximum. Features use only products available at issue time, including legal forecasts of future valid times. Do not splice cycles or use current-day observed floors. Cross-product composites require independently legal sources with the same cycle and compatible valid time/interval.

### Runtime arithmetic

For `h` dynamic hourly fields and `q` subhourly fields:

```text
requests(h,q) = 585,085 h + 2,173,943 q + 1 static request
projected hours = requests / 15.503877879428323 / 3,600
```

One H field costs approximately **10.48 hours**; one Q costs **38.95 hours**, or **3.72 H fields**. These are logical-request projections using the pilot's selected eight-worker throughput. Actual field bytes, range grouping, latency, retries, and weather-dependent compression can change runtime. Per-field network bytes and runtime remain unmeasured for the proposed subset; output Parquet bytes are not network bytes. [L7]

| Universe | Dynamic H | Q | Total identities incl. H14 | Logical requests | Hours | Days | Meaning |
|---|---:|---:|---:|---:|---:|---:|---|
| Full 58 benchmark | 43 | 14 | 58 | 55,593,858 | 996.06 | 41.50 | Selection cohort only; original full plan |
| C32 | 29 | 2 | 32 | 21,315,352 | 381.90 | 15.91 | Conservative comparator |
| R13 — recommended candidate | 11 | 1 | 13 | 8,609,879 | 154.26 | 6.43 | Exact list in section 1 |
| R14-P | 12 | 1 | 14 | 9,194,964 | 164.74 | 6.86 | R13 + H38; other one-H additions have same first-order cost |
| R12 | 10 | 1 | 12 | 8,024,794 | 143.78 | 5.99 | R13 − H33; net-shortwave composite retired |
| R13 + one two-H group | 13 | 1 | 15 | 9,780,049 | 175.23 | 7.30 | For example complete 850 vector or CAPE/CIN |
| R13 + Q11 | 11 | 2 | 14 | 10,783,822 | 193.21 | 8.05 | Pays for exact Q solar without hourly cuts |
| Eight-H/two-Q comparison | 8 | 2 | 11 | 9,028,567 | 161.76 | 6.74 | R13 − H07/H28/H33 + Q11 |

Seven days at that rate permits at most **12 dynamic H fields with Q05**, or **eight dynamic H fields with Q05 and one additional Q**. R13 therefore spends the expensive Q allowance on the protected temperature trajectory and spends the remaining budget on broader hourly process coverage.

R13 has about **13.74 hours** of margin relative to seven days. It needs at least **14.24 requests/second** to finish in seven days; R14-P needs about **15.20**. A 10% reduction from the pilot rate would put R13 at roughly **7.14 days**. Neither is a guaranteed seven-day maximum. This report treats the user's seven days as the target for the reduced full-history acquisition, separately from selection work.

## 3. Meteorological reappraisal of C32

### 3.1 Temperature is the model's answer; error predictors must add something to it

The relevant conditional comparison is not “does field X correlate with Tmax?” It is “does X improve the distribution of the observed Tmax conditional on the legal H16/Q05 trajectory, time of year, issue time, lead, spatial context, and other retained regimes?” Much of C32 describes processes HRRR has already used to produce its temperature forecast. A diagnostic deserves acquisition only if it identifies a recurring failure, timing ambiguity, or uncertainty not adequately represented by the retained summaries.

A national HRRR evaluation using 2021 USCRN data found that afternoon temperature bias differed in sign between weak- and strong-heating regimes. That supports conditional evaluation rather than annual-average screening; it does not establish a KDEN source ranking. [E10]

A model-predicted temperature fall does not reveal whether a real outflow arrived. A model-predicted cloud deck does not verify that clouds exist. HRRR-only features can identify conditions in which past forecast errors were systematically different; they cannot observe the current forecast's departure from reality. Wider or shifted predictive distributions, rather than invented real-time corrections, are the appropriate response.

### 3.2 Keep T850 for a physical reason, not institutional familiarity

**850 mb is treated as above ground in the supplied KDEN study context.** Its omission is not justified by a generic terrain objection. At the site, a lower-air-mass temperature reference can distinguish warm air above a poorly coupled surface from a genuinely colder air mass, or identify a changing air mass behind similar modeled T2. The conditional relationship should depend on mixing, snow, cloud, and surface flow. A raw T850–T2 contrast is an empirical thermal contrast, not a geometric lapse rate or a diagnosed inversion depth.

D1 strengthens this hypothesis: it reports 546 sunny-day rows, 94 in the 2025 holdout, and an annual T850 model using 18Z/FH03 valid at 21Z with development LOYO MAE **1.654°F** and holdout MAE **1.871°F**. The corresponding 850–700 thickness results were **2.141°F** and **2.311°F**. These are transcribed study findings, not recomputed results. D1 was restricted by observed sunshine and fixed forecast construction; it did not establish conditional value over the T2 path or calibrated all-weather early-issue distributions. [L3]

**Selection consequence:** choose H07 as the first single thermal reference; test H02 T700 as an addition or replacement, and H01/H06 thickness jointly. Do not retain height, temperature, dewpoint, and wind at both levels solely for profile completeness. T850 must itself pass R13 versus R13-minus-H07. Its historical success does not confer protected status.

The western-site temperature forecasting precedent also combines thermal structure with weather-dependent adjustments, rather than establishing a universally sufficient layer predictor. It supports testing conditional coupling, not transferring coefficients to Denver. [E8]

### 3.3 Surface flow and moisture are the minimum transition description

KDEN lies where mountain-related flow, plains air, and shallow boundaries interact. In a documented Front Range mesofront, moisture and wind shifts distinguished air masses particularly clearly; temperature alone was less revealing. This is regional case evidence, not a six-year KDEN climatology. [E2]

**Retain H17 and the H18/H19 vector together.** Dewpoint is not a second temperature forecast: at comparable T2, it differentiates dry/mixed and moist/shallow regimes and supplies dewpoint depression and vapor-pressure deficit. A surface vector retains directional information needed to distinguish easterly, northerly, southerly, and westerly regimes. Scalar speed, gust, or one component cannot replace it generally.

**Omit H12/H13 from the initial full-history set.** Pressure can signal frontal progression or a lee trough, but much of its proposed use is a second description of circulation already exposed by spatial wind, moisture, and T2 changes. H13 is the stronger single pressure challenger: same-point tendency avoids direct comparison of surface pressures across different terrain elevations. H12's reduced-pressure pattern is not interchangeable with H13, and neither is exactly reconstructible from R13. If pressure anticipates shallow cold intrusion before wind/temperature respond, it may win a place back.

**Omit both 850 and 700 wind pairs initially, with substantial conditional risk.** The surface vector answers which flow the station experiences; aloft vectors answer whether momentum/advection remains above a decoupled layer and how flow crosses terrain. R13 cannot diagnose vertical shear, full thermal advection, mountain-wave structure, or the strength of an overlying downslope jet. Its proposal is that surface/upstream transitions plus thermal/mixing state may classify enough of the residual-error regime. Test this assumption directly in shallow-cold and strong-westerly cases. “Westerly surface wind” must not be labeled a verified Chinook.

### 3.4 Separate sunlight arriving from sunlight absorbed

**Retain H31 and H33 as a net-shortwave group.** Their difference is the modeled net solar flux; their guarded ratio gives effective modeled albedo. These address different questions from H26 snow fraction. Equal cloud cover or snow fraction does not force equal reflected radiation.

This deserves special weight in Colorado: an HRRR evaluation in the East River Valley associated excessive daytime net radiation under snow with underestimated albedo, even for fully snow-covered grid cells. Its terrain and bias magnitudes cannot be transferred to KDEN. It nevertheless directly contradicts the assumption that retaining snow fraction automatically preserves all snow-radiation information. [E3]

The proposal is an **error-regime predictor**, not a perfect correction: if HRRR's albedo is wrong in exactly the same way on every snow day, H33 may add little beyond snow and season. Its value would come from differences in modeled absorption, snow transitions, spatial heterogeneity, and revisions. Test H26/H31 versus H26/H31/H33, including snow and thaw subsets. Remove H33 if its conditional value is bounded below the approved tolerance. Do not claim to retain net solar after that removal.

**Prefer H28 to multiple cloud amounts.** Its purpose is the lower-cloud/mixing regime, especially in darkness and during morning persistence. H31 supplies the daytime radiative consequence of clouds at all levels. NOAA describes the elevated-terrain limitations of fixed-pressure low-cloud layers and recommends the boundary-layer cloud diagnostic. Thus H29 is not the preferred substitute simply because its label says “low cloud.” [E1]

Newer HRRR research identifies persistent excessive downward solar radiation associated with insufficient cloud attenuation and dry initial conditions; Table Mountain, Colorado, is among the sites with pronounced solar bias. The bias also varies with forecast lead, including rapid cloud loss after initialization. [E4] This supports **H17/H28/H31 plus lead and cycle-revision context**, rather than automatically acquiring every cloud diagnostic or believing the newest cycle is always the most accurate.

**Omit Q11 initially.** A fifteen-minute mean is physically distinct from H31's hourly snapshot. But paying 1.62 days for that distinction requires proof of added Tmax probability value beyond H31 paths/spatial variability/revisions and Q05's temperature evolution. Thin-cloud fluctuations and short sunny gaps are the main risks. Hourly integration remains an approximation; no exact interval energy is reconstructed.

### 3.5 Mixing is retained; the complete energy budget is not

**Retain H24**, interpreted as the model's diagnosed mixing depth, not a measured inversion top or an error-free truth. It supplies information about isolation versus mixing that irradiance alone does not determine. Its diagnostic combines stability-related information in the model; it is not computed from the small R13 vector. [E1]

**Omit H15 skin temperature, H21/H22 turbulent fluxes, and H32/H34 longwave initially.** These describe meaningful processes, but can substantially duplicate the retained radiation, snow, moisture, boundary-layer, and temperature response. The source cost must be justified by conditional error skill rather than by the ability to draw a closed energy-budget diagram.

This is not a claim that flux diagnostics are dispensable everywhere. An ARM Southern Great Plains HRRR evaluation found sensible/latent fluxes particularly difficult to reproduce and documented differing shortwave and longwave errors. It provides a reason to test wet-ground and cloudy-night exceptions, not a measured Denver benefit from retaining those sources. [E5]

H21/H22 jointly recover turbulent partition, which H17 cannot: moist air is not soil moisture, and a dry air mass can overlie wet ground. H15/H16 measure skin–air separation, which H24 cannot reconstruct. H32 adds radiative information at night when H31 is zero, particularly from cloud outside H28's layer. Test these distinct pathways rather than declaring them exact duplicates. Retire net-longwave and total-net-radiation composites when dropping their components.

Cold-pool research with HRRR elsewhere shows that cloud persistence and radiation can alter erosion timing. [E6] This makes early issues and cloudy winter days mandatory checks on the proposed loss of longwave/skin diagnostics; a daytime annual score alone is insufficient.

### 3.6 Snow fraction versus snow mass

H26 captures spatial cover and forecast loss of cover; H33 adds surface reflectivity. H25 adds water mass and therefore a different view of melt persistence, while H27 adds depth. Neither mass nor depth is recovered exactly from fractional cover or albedo. R13 prioritizes the surface's immediate heating exposure over snowpack inventory for intraday Tmax.

The most important counterexample is a shallow, bright snowpack that disappears before the peak versus a deeper pack with similar initial cover/albedo. Retained forecast H26 evolution helps only to the extent that the model's melt forecast is informative. Compare H25 addition, H25-for-H26 replacement, and H25/H27 density-context group. Do not treat a season indicator as sufficient snow information, and do not remove all snowy days from evaluation.

### 3.7 Represent nearby weather before acquiring every convective ingredient

The Denver operational literature emphasizes terrain-linked convergence, moisture, the Denver convergence/vorticity zone, and outflows interacting with local boundaries. It also shows why weather west, north, and south of the airport matters. This is strong geographic motivation for upstream sampling, not evidence that any single HRRR diagnostic predicts KDEN Tmax error best. [E7]

**Retain H36**, with spatial echo footprint and evolution, rather than using a bilinear point dBZ value alone. In one legally available forecast cycle, future afternoon echo development is available even at an early issue; it is not limited to echoes valid “now.” Compare timing relative to the modeled thermal peak. An uncertain interruption before the peak can change the center, skew, and tail of Tmax; a storm after an already-completed peak may have much less impact on Tmax.

**Omit H38 initially, but make it the first single-field addition.** Column echoes are not precipitation reaching the surface: virga, stratiform rain, and persistent wetting break that equivalence. Q05 and dewpoint do not encode precipitation mass. H38 is thus a genuinely different process observation whose conditional value is unresolved, not obvious excess fat.

**Omit H43/H44 jointly**, while retaining a CAPE/CIN challenger. Potential instability and inhibition address storms the deterministic forecast failed to initiate or initiated too easily; echoes address what it actually forecast. Their omission is one of R13's largest tail risks. Echo-free but unstable/convergent environments must be evaluated, using cohort-only CAPE/CIN to stratify evaluation even when those fields are absent from the reduced model. Never imply that H36 reconstructs convective potential.

### 3.8 Smoke and other less direct diagnostics

The H41 product represents modeled smoke optical effects rather than a universal aerosol inventory. HRRR-Smoke research establishes a radiative pathway. [E1], [E9] H31 already reflects modeled attenuation, but smoke-specific bias or a displaced plume can leave H41 useful conditionally. Retain it in the full-universe cohort, assess smoke-exposed days, and do not infer no value from rarity.

H39 column water, H40 visibility, H42 ceiling, and H35 cloud forcing are alternative or supplementary regime descriptions. Prefer the physically closer retained terms initially: near-surface moisture for local boundaries, low cloud for shallow-cloud state, and incident/absorbed sunlight for daytime heating. Ceiling can still add vertical cloud information; visibility can distinguish shallow fog/hydrometeors; column moisture can reveal moisture aloft. Each is a challenger with a specified failure case, not noise by definition.

## 4. C32 removal ledger and the claim made by each cut

| C32 identities removed | H-equivalent cost saved | Why they are not in R13 | What would overturn the omission |
|---|---:|---|---|
| H01/H02/H03/H04/H05 | 5 H | Keep one lower thermal reference; abandon complete 700-mb profile description. | Stable deep-mixing, entrainment, or aloft-flow contribution beyond H07/H24/surface context. Test subsets and full profile. |
| H09/H10 | 2 H | Surface vector directly represents local regime; both aloft components cost a pair. | Improved pre-transition or decoupled/downslope tails from vertical shear/advection. |
| H12/H13 | 2 H | Wind/moisture/T2 paths and geography already represent much frontal/circulation context. | Pressure tendency or a terrain-aware pressure pattern anticipates error before retained fields. |
| H15/H21/H22 | 3 H | Surface response and partition may overlap radiation/moisture/PBL/snow. | Wet-ground, skin–air, or partition contrasts improve location or scale. |
| H25 | 1 H | Cover, albedo, and cover evolution get priority over snow mass. | Melt persistence or mass adds skill at fixed cover/albedo. |
| H32/H34 | 2 H | Abandon net-longwave/complete radiation budget; retain solar and low-cloud regime. | Night/early-morning cloud radiative effects materially change remaining-day Tmax probabilities. |
| H38 | 1 H | Echo footprint, near-surface state, and temperature evolution are the first weather-interruption description. | Wetting/ground precipitation or virga distinctions improve probability forecasts. High-priority add-back. |
| H43/H44 | 2 H | Explicit forecast weather gets priority over two-field convective potential. | Echo-free unstable regimes reveal missed-initiation tails, or false-storm forecasts need cap context. |
| Q11 | 3.72 H | Hourly solar information competes with three to four additional hourly mechanisms. | Native interval energy improves calibrated probabilities beyond the strongest hourly representation. |

The ledger removes **18 dynamic H and one Q**, saving approximately **227.64 hours / 9.49 days** relative to C32. Several cuts are aggressive information compression. Calling all of them “proven redundancy” would overstate the evidence.

## 5. Derived features, spatial reach, and information legality

### 5.1 Compact features from R13

Preserve raw acquired sources independently. Candidate derived summaries below are proposed model features, not changes to acquisition semantics:

- **Baseline:** legal H16 and Q05 target-window maxima, remaining-path maximum, peak lead, heating slope, plateau duration, and H/Q disagreement on common support. Preserve uncertainty about already elapsed hours: model temperatures are not observed floors.
- **Thermal/coupling:** H07 current/future-peak values, tendency, revision, and empirical H07–H16 contrast, interacting selectively with H24 and snow/cloud. Without height/pressure components, do not call this an exact lapse rate, potential-temperature contrast, or inversion depth.
- **Moisture/flow:** H17 dewpoint, H16–H17 depression, saturation-vapor-pressure deficit under a frozen formula, full U/V, direction changes, and fixed-sector contrasts. Without H13, do not derive exact specific humidity, mixing ratio, air density, or a pressure-dependent thermodynamic composite. This intentionally retires the historical exact specific-humidity derivation.
- **Mixing:** H24 value, growth, maximum before the temperature peak, and revisions. It is a model diagnostic of PBL depth, not proof of actual coupling.
- **Solar:** H31 normalized by deterministic top-of-atmosphere horizontal sunlight with a low-sun guard; H31–H33 net shortwave at matched support; H33/H31 effective albedo only for adequate illumination. Predeclare, for example, H31 > 100 W m−2 and solar elevation > 10° for ratio eligibility, with 50/150 W m−2 sensitivity selected in training. Do not clip invalid ratios into plausible values; preserve QC flags. Hourly trapezoidal energy is labeled approximate.
- **Cloud/snow:** forecast H28 persistence, neighborhood heterogeneity, clearance timing; H26 cover and cover-change paths. No claim to exact cloud optical thickness, snow depth, or melt energy.
- **Weather:** H36 echo-area fractions and approach/evolution in local and upstream supports; onset relative to the predicted peak; cycle disagreements about interruption. Reflectivity thresholds, initially 10/20/35 dBZ for sensitivity, are research operators, not guaranteed surface-rain thresholds. Never average dBZ as if it were linear reflectivity power.

Candidate operators include issue state, one-to-three-hour tendency, issue-to-peak summary, remaining-window summary, and revisions across legal cycles at identical valid times. Past-valid forecast states are still forecasts. Compute H/Q comparisons only on native overlap unless an explicitly named interpolated feature is being tested; interpolated points must not be represented as native data.

### 5.2 Spatial economy is material, but not free skill

A centered 9×9 grid has outer centers approximately 24 km apart on a nominal 3-km grid. It cannot describe the entire Front Range–Palmer Divide–northern plains environment. Point-only pressure or wind can appear indispensable because an alternative field was sampled too narrowly. Conversely, deleting pressure or aloft flow while retaining only a KDEN wind point would weaken the proposed rationale.

Test this compact, **new spatial contract proposal** against both point-only and existing registered supports:

| Support | Initial geometry to freeze before labels are used | Main sources and mechanism |
|---|---|---|
| KDEN neighborhood | Existing 3×3/9×9 plus compact surface-state tiles where currently point-only | Surface heterogeneity, wind shifts, snow edges, cloud/echo displacement. |
| West/foothill corridor | Fixed western sectors at approximately 30 and 60 km | H16/H17/U/V/H28/H31/H36; approach versus dissipation west of KDEN. |
| North/northeast plains | Fixed sectors at approximately 30 and 60 km | Surface cold/moist intrusions and advancing weather. |
| East plains | Fixed sectors at approximately 30 and 60 km | Moisture/temperature contrasts and eastward storm displacement. |
| South/southeast corridor | Fixed sectors at approximately 30 and 60 km | Palmer Divide/convergence-related weather and surface-flow contrasts. |

Use map-aware displacements from each coordinate-era anchor, freeze exact cells/radii/weights and terrain QC in a successor spatial specification, and visually inspect coverage before acquisition. These distances are starting hypotheses, not a validated optimal geometry. A limited wider-radius sensitivity belongs in the cohort; do not tune dozens of sectors on the final holdout.

Static H14 height must cover every new extraction support. Sample isobaric fields only at valid supports; the accepted local 850-mb premise does not establish validity over higher mountains. Surface-temperature sector differences include elevation effects, so retain terrain differences and do not impose a universal lapse correction. Surface wind at a western foothill point is not the upstream free-atmospheric wind.

Additional extraction from an already retrieved full-domain GRIB message does not multiply source-message retrievals. It does add output, processing, lineage, and validation cost. The candidate's predictive benefit from these supports is unmeasured. Extract them during the cohort before transient GRIB disposal; test them, then freeze the winning geometry before full-history acquisition. Existing point-only archives cannot later supply unsaved upstream values without reacquisition.

Two coordinate metadata eras must remain distinct: through 2021-11-21 and from 2021-11-22. An era change is not by itself proof of a physical station move. Aggregate scores must not hide an era-dependent failure.

## 6. Temporal scrutiny of every Q field

Every Q challenger must beat **H state + hourly tendency/path + appropriate spatial context + cycle revisions**, conditional on the protected Q05 temperature path and other retained fields. A comparison with only one H snapshot is too weak. If the H analogue is excluded from R13, include it in a staged comparison: reduced core, core+H, then core+H+Q. Also compare a scientifically valid Q-for-H source replacement where the H is not protected.

| Q | Exact temporal distinction and H comparator | Increment that could justify Q cost | Initial decision |
|---|---|---|---|
| Q01 | Instantaneous reflectivity every 15 min; H36 | Intrahour echo passage/onset changes timing before the thermal peak beyond hourly spatial evolution. | Challenger; priority after hourly weather representation. |
| Q02 | Instantaneous visibility every 15 min; H40 | Rapid fog clearance or obscuration not represented by cloud/moisture/solar and hourly visibility. | Challenger; requires fog-specific skill. |
| Q03 | Instantaneous gust diagnostic every 15 min; H11 | Rapid gust-potential changes add information about mixing/outflow. Not a recorded interval maximum. | Challenger; compare vector/PBL alternatives. |
| Q04 | Instantaneous surface pressure every 15 min; H13 | Subhourly pressure jump anticipates cold intrusion/outflow error. | Challenger; must first justify pressure itself. |
| Q05 | Instantaneous T2 every 15 min; H16 | Native thermal peak/path and independent-product reconstruction. | Protected; no replacement by interpolated H16. |
| Q06 | Instantaneous dewpoint every 15 min; H17 | Rapid moisture boundary missed between hourly states, especially with little T2 change. | Challenger; retain moisture mechanism hourly first. |
| Q07 | Instantaneous U10 every 15 min; H18 | Direction/onset jointly with Q08. | Challenger vector group Q07/Q08. |
| Q08 | Instantaneous V10 every 15 min; H19 | Same vector-group question; do not select independently. | Challenger vector group Q07/Q08. |
| Q09 | Preceding 5-min mean U10, sampled every 15 min; H18 | Smoothed flow may improve regime classification over snapshots. | Challenger jointly with Q10; compare with Q07/Q08. |
| Q10 | Preceding 5-min mean V10, sampled every 15 min; H19 | Same mean-vector question. Ten-minute gaps are not observed averages. | Challenger jointly with Q09. |
| Q11 | Preceding 15-min mean solar; H31 instantaneous | Exact modeled quarter-hour incident energy, short cloud gaps, pre-peak solar timing. | Leading non-temperature Q challenger; omitted initially. |
| Q12 | Instantaneous precipitation rate every 15 min; H37 | Peak rate/onset adds more than interval amount and echoes. | Challenger; rate is not a 15-min mean. |
| Q13 | Preceding 15-min precipitation amount; H38 preceding 60-min amount | Subhourly precipitation timing relative to the thermal peak. | Challenger; compare amount before rate. |
| Q14 | Instantaneous ceiling every 15 min; H42 | Abrupt low-cloud lowering/lifting affects erosion and heating. | Challenger; first justify hourly vertical-cloud information. |

Q11 means integrate as flux × 900 s only over complete legal intervals; Q13 amounts are summed, not differenced again. H38 cannot be subdivided into exact quarters. Q13 sums and H38 amounts require product/interval parity checks rather than assumed equality. Q09/Q10 do not supply full fifteen-minute mean winds. The removal of a composite retires its derived quantity; it does not license interval reinterpretation.

## 7. Selection cohort: the required empirical decision, not another full-history universe

The engineering pilot's 1,849 requests do not support feature selection. Follow the brief's full-universe cohort requirement. No long acquisition or model run was launched for this report.

### 7.1 Sampling and staged expenditure

Use a reproducible calendar-stratified random sample, selected before looking at target errors:

1. **Development screen: 240 target days**, four dates per month in 2021–2025. Acquire all 58 identities, complete retained cycles, and full allowed paths. This can reject obvious excess or expose missing mechanisms; it cannot certify tight all-regime noninferiority.
2. **Expanded development: 480 total days**, eight dates per month in 2021–2025, including the first 240. Expand if precision, regime counts, or subset stability are inadequate. Do not use a favorable small-sample result as a stopping rule without prespecified sequential inference.
3. **Final temporal test: 120 days in 2026**, initially 14 randomly selected dates in each January–August month and eight in September 1–11. Preserve outcomes untouched until subsets, models, tolerances, and all operators are frozen. Confirm these outcomes have not already informed project decisions; otherwise reserve a genuinely unexamined period and record the limitation.

The full planned study is 600 days, rather than 2,080 full-universe days. It is still substantial. At proportional request scaling, the first 240 days cost **4.79 days**, 480 cost **9.58 days**, and 600 cost **11.97 days**. Exact sealed cohort plans will differ slightly with date-specific horizons/DST.

Reusing selected-source data from a compatible 600-day cohort, the approximate end-to-end acquisition is **11.97 + (1,480/2,080 × 6.43) = 16.55 days**, before confirmation overhead. The *final universe* is a 6.43-day equivalent, but comprehensive selection is additional work. A seven-day total project cap cannot support this design at current throughput. No larger budget or run is authorized by this report.

Stratify within months for both coordinate eras, ordinary/extended cycle patterns, and necessary DST/archive cases using explicit inclusion probabilities. Keep natural-prevalence scores weighted appropriately. If rare regimes are absent or too sparse, acquire an additional separately costed source-screened challenge sample, for example up to 48 days; report it separately from population-weighted headline scores unless sampling weights are known. Forty-eight extra full-universe days cost about **0.96 day**.

Use HRRR-only, predeclared criteria to audit coverage of snow/thaw, shallow moist easterly flow, strong dry westerlies, wind/thermal boundaries, low-cloud persistence, broken-cloud/high solar variability, echo/precipitation events, echo-free CAPE/CIN, and smoke. Cohort-only fields may define an evaluation stratum without entering the reduced model. Do not choose “interesting” final days from observed Tmax errors. Labels belong only in a separate research join.

### 7.2 Independent days, temporal validation, and sample sufficiency

All issue rows and cycles from a target day stay together. Use rolling outer folds such as training 2021–2022, testing 2023; training through 2023, testing 2024; training through 2024, testing 2025. Use earlier future-blocked inner folds for transformations, feature selection, penalties, distance weights, neighbor counts, threshold choices, imputation, and calibration. Keep shared source objects or overlapping episode dependencies out of opposite sides of a split; use a two-day boundary gap where needed and test longer gaps for persistent weather.

The 2025 D1 outcomes are already disclosed; 2025 is not a pristine project-wide holdout. The 2026 final interval contains little autumn, so full autumn transfer cannot be certified by that final period alone. Use historical outer-year autumn diagnostics and state the limitation rather than claiming full-season final confirmation. An early-era diagnostic requires chronological splits inside 2021 and has much lower power than the main folds.

Estimate uncertainty from paired target-day scores, with contiguous weather-episode block bootstrap (initially seven days, three/fourteen-day sensitivity) or a justified grouped alternative. Hundreds of issue rows do not multiply the number of independent weather events.

For the sparse calendar sample, blocks mean actual calendar/episode intervals containing sampled dates, not seven adjacent rows of the sampled table. Preserve inclusion weights. If dependence cannot be estimated adequately from that sample, use the separately approved complete-episode supplement and report the uncertainty limitation.

Set sample size from paired-score variability and the approved tolerance. For illustration only, with paired daily CRPS SD 0.30°F, margin 0.05°F, one-sided 5% level and 80% power, a simple independent-day approximation gives `(1.645+0.842)^2 × (0.30/0.05)^2 ≈ 223` effective days. Dependence, multiple subsets, and regime checks increase requirements. Neither the 120-day final test nor 600 sampled days guarantees sufficient power for every rare regime. If bounds remain too wide, record unresolved deletion and extend the appropriate cohort rather than declaring a null result proof of redundancy.

## 8. Models, ablations, and the smallest supported union

### 8.1 Common benchmark and different model representations

Establish separately tuned **full-58**, **C32**, **R13**, **R14-P**, and reduced/swap benchmarks for each family on identical days and issue times. Full-58 is a candidate-information benchmark with training-only feature control, not an unregularized concatenation of every field/lead. Otherwise a deliberately overfit benchmark would make reduction look artificially successful.

**AnEn:** start with compact baseline shape, thermal reference, U/V regime, moisture, PBL, solar/cloud, snow, and echo summaries. Standardize within training; group weights prevent cloud/solar or paired wind from dominating through duplicated coordinates. Learn weights/dimension reduction and neighbor count in inner folds. One historical day must not appear repeatedly as dozens of independent neighbors simply because it has many issue rows. Permit a smaller AnEn source subset than R13, but test omissions on calibrated predictive distributions. Analog methods' value depends on historical forecast similarity and available training examples, not merely a physically long vector. [E11]

**Distributional GAM/GAMM:** use a T2 baseline offset or equivalent forecast-centered location model. Select location and scale terms separately; include only supported interactions such as thermal contrast × mixing, snow × absorbed solar, cloud × heating opportunity, and echo timing × peak lead. Penalize smooths and inspect concurvity. A field retained only for stable scale/tail value is legitimate. If random effects are used, predict an unseen target day by the proper marginal/new-level treatment; do not estimate its effect from that day's future outcome.

**Ordinal hazard:** fit coherent ordered whole-degree probabilities with training-only regularization and calibration. Evaluate threshold-specific reliability and sparse tails. Here “hazard” concerns the ordered outcome construction; it does not automatically mean a clock-time event hazard. Do not force probabilities or interval widths to narrow monotonically across issue times. New forecasts can legitimately increase uncertainty.

For every competitive family, identify its smallest supported source subset. Acquire their **union plus protected sources**, not the intersection, and rerun joint elimination on that union. Retain a model-specific field only if its family remains competitive and its incremental gain is stable. A hypothetical future model is not sufficient justification. No field currently receives `RETAIN_MODEL_SPECIFIC` because that evidence has not yet been produced.

### 8.2 Required experiments and decision targets

| Test | Comparisons, always on common folds/issues | Decision it resolves |
|---|---|---|
| A0 Baselines/cadence | H16-only versus H16+Q05; full H-only versus H+all Q; C32 with/without Q11 | Quantify temporal value without changing protected acquisition yet. |
| A1 Thermal | R13 with/without H07; H02-for-H07; +H02; +H01/H06; +H02/H03; +complete H01–H10 as a block | T850's conditional value, upper thermal/dewpoint structure, thickness, synergy missed by single additions. |
| A2 Flow/pressure | +H13, +H12, +H09/H10, +H04/H05, and joint additions; repeat with improved surface geometry | Pressure/vertical flow versus local and upstream surface transitions. |
| A3 Cloud/radiation | H28-for-H29/H30/H42; R13-minus-H28; R13-minus-H33; +H32; +H32/H34; +H35; +Q11 | Low-cloud regime, absorbed solar, net longwave, cloud forcing, exact Q energy. |
| A4 Surface exchange | +H15; +H21; +H22; +H21/H22; +H20; +H23; +complete flux/radiation budget; H24 replacement/removal | Whether direct coupling/partition information beats proxies; groups test otherwise hidden synergy. |
| A5 Snow | H26 versus H25 or H27; H26+H33 versus +H25; +H25/H27; spatial snow-edge contrasts | Cover, reflected solar, mass, and depth are judged jointly in snow/thaw regimes. |
| A6 Weather interruption | R13 with/without H36; +H38; +H37; +H43/H44; combined precip/instability block; +H39/H41/H40/H42 as relevant | Surface precipitation versus echoes, missed/false convection, fog and smoke exceptions. |
| A7 Every Q | Section 6 H-strengthened tests, including Q07/Q08 versus Q09/Q10; single Q and coherent multigroup additions | Test all Q fields, not only the Q11 that survived C32. |
| A8 Geometry | Point versus current tiles versus frozen displaced sectors | Distinguish missing spatial information from a missing field. |
| A9 Forecast evolution | Current state; +within-cycle path; +same-valid-time revisions, matched for legal horizon | Separate state, cadence, and cycle-instability value; account for lead-dependent bias. |
| A10 Union/minimum | Family subsets and their union; backward block deletion plus forward additions/swaps | Avoid bloated union, greedy-path dependence, and unjustified single-field significance screens. |

Repeat tests in relevant issues/seasons/regimes and for location, scale, and tails. Do not explode into all possible 58-field subsets. Predeclare physical blocks and a limited interaction hierarchy. Test both additions to R13 and deletions from C32/full-58 so that compensating predictors or synergistic groups are not missed. Freeze the resulting shortlist before final testing.

### 8.3 Equal-cost challengers must compete, not accumulate

One extra H fits the first-order seven-day budget. Compare **R13+H38**, **+H13**, **+H02**, **+H32**, **+H25**, and **+H41** as separate 6.86-day candidates, not a single growing union. H15/H20/H21/H22/H23 and other single-field candidates remain eligible through A4/full-universe selection, even though the initial priority is lower.

Two-field groups such as the 850 wind vector, CAPE/CIN, or turbulent flux pair cost about 20.97 hours. R13 plus such a group costs **7.30 days**. To fit approximately seven days, they must either justify that modest overrun or replace at least one discretionary H source, yielding 12 dynamic H overall. Evaluate scientific group loss when choosing that swap: removing H33 retires net-shortwave; removing H28 sacrifices direct low-cloud context; removing H07 sacrifices the separate thermal reference. Never drop one U/V member to force a budget fit.

Adding Q11 to R13 costs **8.05 days**. A two-Q universe fitting seven days needs only eight dynamic H. An explicit comparison is R13 minus H07/H28/H33 plus Q11, costing **6.74 days**, which sacrifices thermal reference, low-cloud regime, and reflected solar. This is an opportunity-cost test, not the preferred universe. It makes clear what Q11 must outperform; novelty of its interval semantics alone is insufficient.

R12 = R13 minus H33 costs **5.99 days** and is the first smaller solar alternative. Other single deletions and coherent group deletions must be tested too. Do not stop shrinking at 13 simply because its name matches a convenient budget. Conversely, if the validated family union needs more than seven days, report that conflict rather than silently discarding a useful family or field.

## 9. Proper scores and the acquisition–skill frontier

The primary score is discrete CRPS/RPS on a common whole-degree-Fahrenheit support: sum over thresholds of squared CDF error, with the 1°F spacing retained so score units are explicit. Use the contract-authoritative integer outcome and the same support/tail treatment for every model. For a continuous distributional model, map to integer bin probabilities under a frozen convention consistent with the outcome contract; do not infer the truth-record rounding rule from model convenience. Proper scores assess the distribution, rather than rewarding an artificially sharp point forecast. [E12]

Also report log score with exact-zero failures separately and a declared numerical floor (proposed 10⁻⁶, with activation counts); threshold/band Brier scores and reliability; discrete PIT; 50/80/90% coverage and calibrated widths; lower/upper tail errors; and earliest useful concentration. MAE/RMSE/bias are secondary. Markets, fills, and PnL are excluded.

**Proposed tolerance contract for owner review before holdout:** reduced-minus-reference day-averaged CRPS must have a one-sided 95% upper bound no greater than `min(0.05°F, 2% of reference CRPS)`. Propose log-score deterioration ≤0.02 nats/outcome, and ≤3 percentage-point degradation in nominal coverage as additional checks. Predeclare how simultaneous issue/regime comparisons and multiple candidate testing are controlled. These values are research proposals, not established domain tolerances.

Make 02:00–06:00, 06:00–10:00, 10:00–14:00, and 14:00–16:00 issue bands explicit; weight target days equally before combining issues. Report all seasons and mechanism strata with counts and paired uncertainty. A stable, materially worse important-regime score can veto a small annual improvement. For illustration, propose a 5% regime CRPS loss screen with uncertainty; a low-powered regime must be marked unresolved, not passed by default.

For concentration, propose the first legal issue with a calibrated 80% interval no wider than 4°F, plus persistence/reversal statistics and score/calibration at that issue. Compare delay against a proposed 15-minute tolerance. The interval threshold is a scientific product criterion to approve, not a market-derived choice. Compute population calibration and coverage at adaptive stopping times as well as fixed issues.

For each tested source set, record request count, measured accepted bytes, retries, complete end-to-end wall time, and probability results. **A cost-only table is not an empirical Pareto frontier.** The frontier exists only after those experiments. Compare against the best validated competitive reference for each model family, not merely whichever full-universe fit was weakest. Prefer the smallest union inside approved tolerances, then confirm no cheaper tested deletion/swap remains acceptable.

Record deletion as `DROP_DETERMINISTIC_REDUNDANCY` only after exact reconstruction under required precision/semantics is demonstrated; `DROP_CONDITIONAL_REDUNDANCY` after sufficient conditional noninferiority evidence; or `DROP_NO_STABLE_PREDICTIVE_VALUE` after adequately powered, repeated out-of-sample evidence. Pairwise correlation, an insignificant coefficient, or a noisy null is insufficient. The present universe contains no newly demonstrated exact duplicate.

## 10. Full 58-field decision matrix

This matrix is the authoritative disposition record **for this new report**, superseding neither registry nor PASS. It is split by family for readability, with the same 14 required columns throughout. Identities come directly from the frozen H/Q registries: H product `wrfsfcf`, Q product `wrfsubhf`. “Instant/0” means a snapshot with zero duration, not an interval average. H14 is static; H38 alone is hourly accumulation. Q09/Q10 are 5-minute means; Q11 is a 15-minute mean; Q13 is a 15-minute accumulation.

Spatial abbreviations: **B** projected bilinear; **N** nearest neighbor; **T3/T9** existing centered tile; **S** proposed fixed-sector/expanded support, to be tested and versioned; **G** static terrain. “→S” is proposed, not already acquired. Temporal **P/R** means native within-cycle path and same-valid-time legal cycle revisions. Issue times are local. **A/M/S/O** in the model-role column means AnEn / GAM location / GAM scale / ordinal distribution; these are candidate roles, not demonstrated gains.

Cost **H** = 585,085 requests, 10.48 projected hours, field-specific network bytes unmeasured. **Q** = 2,173,943 requests, 38.95 hours, bytes unmeasured. **Z** = one static logical request, negligible repeated runtime; bytes unmeasured. A vector/group costs the sum of its member rows. Every row therefore records requests/time and explicitly unknown bytes via its cost code, rather than inventing byte precision.

Evidence entries link to local sources or research below and identify the resolving experiment A0–A10. Dispositions are printed in full. Confidence describes the **proposed role or omission**, not a computed posterior probability. “Risk” is the consequence of deleting the source if the hypothesis is wrong.

### 10.1 Thermal and aloft flow

| Field ID and exact identity | Physical quantity | KDEN failure mechanism | Issue relevance | Temporal requirement | Spatial requirement | Derived uses | Model roles | Redundancy candidates | Conditional exceptions | Evidence / resolving test | Acquisition cost | Disposition | Confidence and risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **H01** — wrfsfcf; HGT; 700 mb; instant/0 min; native 60 min; gpm | Geopotential height at 700 mb | Column thermal/synoptic context beyond local warming | 02–14, remaining afternoon | Hourly P/R; slow state | B+T3 →S | Thickness only with H06; height changes | A/M/O; S if instability | H07 thermal state; H02; circulation summaries | Deep thermal structure changes at fixed T850 | [L2]; A1 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium risk; standalone height not thickness |
| **H02** — wrfsfcf; TMP; 700 mb; instant/0 min; native 60 min; K | Air temperature at 700 mb | Deep mixing/entrainment or elevated thermal cap | 02–14; hot afternoons | Hourly P/R | B+T3 →S | H07−H02 thermal difference; with heights geometric lapse | A/M/S/O | H07 plus H24 and surface path | Deep PBL reaches different air than H07 represents | [L3]; A1 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high conditional risk; leading one-H thermal challenger |
| **H03** — wrfsfcf; DPT; 700 mb; instant/0 min; native 60 min; K | Dewpoint at 700 mb | Dry entrainment or moist layer aloft alters surface heating/clouds | 02–14, especially mixed afternoons | Hourly P/R | B →S | H02−H03 dryness; elevated moisture contrast | M/S/O; A optional | H17/H28/H36 weather state | Dry air aloft over moist surface; virga environment | [L2]; A1/A6 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high risk; joint H02 test |
| **H04** — wrfsfcf; UGRD; 700 mb; instant/0 min; native 60 min; m s-1 | 700-mb zonal wind | Aloft cross-terrain flow/steering despite weak surface wind | 02–14 forecast evolution | Hourly P/R, joint H05 | B →S | 700 vector; shear with lower pair | A/M/S/O | Surface vector/spatial weather evolution; 850 pair | Strong flow over decoupled cold air | [L2]; [E2]; A2 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high risk; evaluate vector jointly |
| **H05** — wrfsfcf; VGRD; 700 mb; instant/0 min; native 60 min; m s-1 | 700-mb meridional wind | Aloft directional/steering context | 02–14 forecast evolution | Hourly P/R, joint H04 | B →S | 700 vector and directional shear | A/M/S/O | Same alternatives as H04 | Along-barrier flow, turning with height | [L2]; A2 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high risk; never discard independently of vector test |
| **H06** — wrfsfcf; HGT; 850 mb; instant/0 min; native 60 min; gpm | Geopotential height at 850 mb | Thermal-column depth with H01 | 02–14 | Hourly P/R | B+T3; valid supports only | H01−H06 thickness; with H02/H07 lapse | A/M/O | H07; H02 thermal difference | Thickness increment conditional on T850 | [L3]; A1 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium risk; above-ground local premise accepted |
| **H07** — wrfsfcf; TMP; 850 mb; instant/0 min; native 60 min; K | Air temperature at 850 mb | Air-mass thermal reference separate from surface response | 02–16, assess early independently | Hourly P/R, peak and remaining path | B+T3 →valid S | T850 state/change; empirical T850−T2 contrast | A/M/S/O | H16/Q05 plus regimes; H02 | Apparent standalone skill may duplicate baseline/season | [L3]; [E8]; A1 | H | RETAIN_CORE | Moderate-high initial retention; conditional gain unproved; high deletion risk |
| **H08** — wrfsfcf; DPT; 850 mb; instant/0 min; native 60 min; K | Dewpoint at 850 mb | Lower-layer moisture above surface | 02–14 | Hourly P/R | B →valid S | H07−H08 depression; layer/surface moisture contrast | A/M/S/O | H17/H28 plus thermal/mixing context | Moist layer aloft while surface remains dry | [L2]; A1/A3 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high risk in decoupling |
| **H09** — wrfsfcf; UGRD; 850 mb; instant/0 min; native 60 min; m s-1 | 850-mb zonal wind | Lower aloft advection and momentum above surface | 02–16 | Hourly P/R, joint H10 | B →valid S; H07 gradients | 850 vector; shear versus H18/H19; advection with T850 gradients | A/M/S/O | Surface vector and upstream gradients | Aloft warm/dry flow before surface penetration | [L2]; [E2]; A2 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high conditional risk |
| **H10** — wrfsfcf; VGRD; 850 mb; instant/0 min; native 60 min; m s-1 | 850-mb meridional wind | Lower aloft directional flow | 02–16 | Hourly P/R, joint H09 | B →valid S | Same vector/shear/advection group | A/M/S/O | Surface vector and upstream gradients | Directional shear with shallow cold air | [L2]; A2 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high risk; paired decision |

### 10.2 Surface state, energy, and mixing

| Field ID and exact identity | Physical quantity | KDEN failure mechanism | Issue relevance | Temporal requirement | Spatial requirement | Derived uses | Model roles | Redundancy candidates | Conditional exceptions | Evidence / resolving test | Acquisition cost | Disposition | Confidence and risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **H11** — wrfsfcf; GUST; surface; instant/0 min; native 60 min; m s-1 | Gust wind-speed potential | Intermittent mixing or outflow-risk regime | 02–16 | Hourly diagnostic P/R, not interval maximum | B →S | Gust−sustained speed; revisions | S/O; A/M challenger | H18/H19/H24; aloft vectors | Full-profile momentum not recoverable from retained fields | [E1]; A2/A7 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium risk; gust is not observed realization |
| **H12** — wrfsfcf; MSLMA; mean sea level; instant/0 min; native 60 min; Pa | Mean-sea-level reduced pressure diagnostic | Lee trough/large circulation placement | 02–16 | Hourly P/R; broad pattern | B+T3 →terrain-aware S | Reduced-pressure gradients and revisions | A/M/S/O | Surface wind/moisture/T2 transitions; H13 tendency | Circulation pattern adds warning before local transition | [L2]; A2 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium risk; not equal to H13 |
| **H13** — wrfsfcf; PRES; surface; instant/0 min; native 60 min; Pa | Surface air pressure | Cold surge/outflow pressure tendency | 02–16, including early warning | Hourly same-point tendency and R | B →same-elevation-aware S | Pressure tendency; exact humidity with H17 if retained | M/S/O; A optional | H17/H18/H19/H16 spatial/P/R | Pressure jump precedes visible wind/thermal change | [L2]; A2 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high risk; equal-cost H33/H38 competitor |
| **H14** — wrfsfcf; HGT; surface; instant/0 min; static once; gpm | Static model surface height | Station/grid terrain mismatch and extraction provenance | All issues | Static once; geometry coverage | G at all retained supports | Terrain contrast; AGL conversion when corresponding HGT exists | Infrastructure for all families | No dynamic substitute needed | New sectors need compatible static terrain | [L1]; [L5] | Z | PROTECTED_BASELINE_OR_STATIC | High protection; negligible repeated acquisition cost |
| **H15** — wrfsfcf; TMP; surface; instant/0 min; native 60 min; K | Skin temperature | Skin–air exchange/decoupling beyond air temperature | 02–10 and snow/wet afternoons | Hourly P/R | B →surface-context S | H15−H16 skin–air contrast | M/S/O; A optional | H24/H17/solar/snow and T2 path | Wet/dry soil or snow skin differs at equal PBL state | [L2]; [E5]; A4 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high risk; not identical to T2 |
| **H16** — wrfsfcf; TMP; 2 m above ground; instant/0 min; native 60 min; K | 2-m air temperature hourly product | Baseline thermal trajectory and product disagreement | 02–16 | Protected full hourly native path | B+N; proposed local S | Hourly baseline; peaks; slopes; comparison with Q05 | A/M/S/O baseline | Q05 overlaps but independent identity protected | Native H/Q parity, missingness and hourly extrema | [L1]; A0 | H | PROTECTED_BASELINE_OR_STATIC | High protection; no interpolation/reuse substitution |
| **H17** — wrfsfcf; DPT; 2 m above ground; instant/0 min; native 60 min; K | 2-m dewpoint | Moist shallow intrusion versus dry mixed air | 02–16 | Hourly P/R and spatial contrasts | B →T9/S | Dewpoint depression; vapor-pressure deficit; moisture transitions | A/M/S/O | T2/cloud/flow; H08/H39 alternatives | Moisture boundary with weak temperature signal | [E2]; [E4]; A2/A3 | H | RETAIN_CORE | Moderate-high initial retention; high deletion risk |
| **H18** — wrfsfcf; UGRD; 10 m above ground; instant/0 min; native 60 min; m s-1 | 10-m zonal wind | Surface regime, westerly/easterly transitions | 02–16 | Hourly P/R; joint H19 | B →T9/S | Full vector; convergence/terrain-oriented components | A/M/S/O | Gust/aloft/Q vectors, not one scalar | Along/across-flow directions differ at same speed | [E2]; [E7]; A2/A7 | H | RETAIN_CORE | High physical priority; empirical minimum unproved |
| **H19** — wrfsfcf; VGRD; 10 m above ground; instant/0 min; native 60 min; m s-1 | 10-m meridional wind | Northerly/southerly component of shallow intrusions/convergence | 02–16 | Hourly P/R; joint H18 | B →T9/S | Full vector and directional changes | A/M/S/O | Same vector alternatives as H18 | Shallow northerly cooling at similar zonal wind | [E2]; [E7]; A2/A7 | H | RETAIN_CORE | High physical priority; retain vector jointly |
| **H20** — wrfsfcf; MSTAV; 0 m underground; instant/0 min; native 60 min; % | Moisture-availability diagnostic, percent | Surface wetness/evaporative regime | 02–14 | Hourly P/R; slow ground context | B →snow/land S | Moisture availability state; not volumetric soil water | M/S/O; A optional | H17/H24/snow/solar; H21/H22 | Air dryness does not reveal wet ground | [L2]; [E5]; A4 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium risk; identity limits interpretation |
| **H21** — wrfsfcf; SHTFL; surface; instant/0 min; native 60 min; W m-2 | Surface sensible heat flux | Direct atmospheric heating/mixing efficiency | 02–14 | Hourly snapshots/P/R; approximate integral | B →S | Heating integral; with H22 turbulent partition | M/S/O; A optional | H24/solar/T2 response | Different partition at similar radiation and PBL depth | [E5]; A4 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high conditional risk; test alone and paired |
| **H22** — wrfsfcf; LHTFL; surface; instant/0 min; native 60 min; W m-2 | Surface latent heat flux | Energy diverted to evaporation | 02–14 | Hourly snapshots/P/R; approximate integral | B →S | Evaporative fraction/Bowen only with H21 and guards | M/S/O; A optional | H17/H24/snow/solar; H20 | Wet soil under dry advected air | [E5]; A4 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high conditional risk; preserve pair for composite test |
| **H23** — wrfsfcf; GFLUX; surface; instant/0 min; native 60 min; W m-2 | Ground heat flux | Heat storage/release and surface-energy timing | 02–10, afternoon storage | Hourly snapshots/P/R | B →S | Ground storage proxy; full energy budget only with all required terms | M/S; O challenger | Skin/PBL/solar/season | Snow/thaw or substrate storage changes independently | [L2]; A4 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium risk; no energy-residual reconstruction |
| **H24** — wrfsfcf; HPBL; surface; instant/0 min; native 60 min; m | Diagnosed PBL depth | Surface isolation versus mixing and growth timing | 02–16 | Hourly P/R; growth/peak depth | B →T9/S | Depth/growth/revision; thermal coupling interaction | A/M/S/O | Wind/solar/T2; flux or profile groups | Cloudy shallow and sunny deep states at same T2 | [E1]; A1/A4 | H | RETAIN_CORE | Moderate-high priority; diagnostic error remains; high deletion risk |

### 10.3 Snow, cloud, radiation, and weather

| Field ID and exact identity | Physical quantity | KDEN failure mechanism | Issue relevance | Temporal requirement | Spatial requirement | Derived uses | Model roles | Redundancy candidates | Conditional exceptions | Evidence / resolving test | Acquisition cost | Disposition | Confidence and risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **H25** — wrfsfcf; WEASD; surface; instant/0 min; native 60 min; kg m-2 | Snow water equivalent mass | Melt persistence/latent demand | 02–14, cold-season peak | Hourly P/R of snow mass | B →T9/S | SWE change; with H27 density proxy | M/S/O; A optional | H26/H33 and cover evolution | Thin versus deep bright snow at same cover/albedo | [L2]; [E3]; A5 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high risk on thaw days |
| **H26** — wrfsfcf; SNOWC; surface; instant/0 min; native 60 min; % | Snow-covered fraction | Patchy/covered ground modifies heating and coupling | 02–16 | Hourly P/R; cover loss before peak | B →T9/S | Snow fraction/edge/change; solar interaction | A/M/S/O | H25/H27; H33 daytime albedo | Darkness, snow phase/melt, cover heterogeneity | [E3]; A5 | H | RETAIN_CORE | Moderate-high priority; albedo does not make coverage identical |
| **H27** — wrfsfcf; SNOD; surface; instant/0 min; native 60 min; m | Snow depth | Snowpack persistence and insulation context | 02–14 | Hourly P/R | B →T9/S | Depth; density proxy with H25 | M/S/O challenger | H25/H26/H33 | Different density/insulation for same mass or cover | [L2]; A5 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk; not exact redundancy |
| **H28** — wrfsfcf; TCDC; boundary-layer cloud; instant/0 min; native 60 min; % | Boundary-layer cloud fraction | Shallow cloud/cold-pool persistence versus clearing | 02–16; early/night important | Hourly P/R; exposure/clearance | B+T9 →S | Low-cloud persistence/spread; solar/PBL interaction | A/M/S/O | H31 daytime effect; H29/H30/H42/H32 | Same solar but different cloud layer; nighttime solar zero | [E1]; [E4]; A3 | H | RETAIN_CORE | Moderate-high priority; independent value beyond solar/PBL requires test |
| **H29** — wrfsfcf; LCDC; low cloud; instant/0 min; native 60 min; % | Conventional low-cloud fraction | Low-cloud suppression, alternative layer definition | 02–16 | Hourly P/R | B+T9 →S | Low-cloud exposure/spread | M/S/O; A alternative | H28/H31 | Alternative layer may better capture some elevated cloud | [E1]; A3 | H | RETAIN_CHALLENGER_PENDING_COHORT | High omission priority relative to H28; medium conditional risk |
| **H30** — wrfsfcf; TCDC; entire atmosphere; instant/0 min; native 60 min; % | Total column cloud fraction | Cloud cover beyond PBL layer | 02–16 | Hourly P/R | B+T9 →S | Total-cloud exposure/spread | M/S/O; A optional | H31 radiative consequence plus H28 | High/mid cloud at night or differing cloud optical properties | [L2]; [E4]; A3 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk |
| **H31** — wrfsfcf; DSWRF; surface; instant/0 min; native 60 min; W m-2 | Downward solar flux | Heating opportunity and cloud/solar forecast error | Daylight forecasts at every issue | Hourly snapshots P/R; approximate integral | B+T9 →S | Solar normalization; net SW with H33 | A/M/S/O | Cloud fields; Q11 interval means | Equal cloud fraction but unequal optical attenuation | [E4]; A3/A7 | H | RETAIN_CORE | High initial priority; Q cadence value unresolved |
| **H32** — wrfsfcf; DLWRF; surface; instant/0 min; native 60 min; W m-2 | Downward thermal infrared flux | Night/cloud radiative forcing and morning coupling | 02–10 especially; all valid times | Hourly P/R | B →S | Downward LW exposure; net LW with H34 | M/S/O; A optional | H28/H17/T2/solar/season | High-cloud or moisture radiative effects when SW zero | [E5]; [E6]; A3/A4 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high early-issue risk |
| **H33** — wrfsfcf; USWRF; surface; instant/0 min; native 60 min; W m-2 | Upward solar flux | Surface reflection versus absorption at same incident solar | Daylight valid times, even at early issue | Hourly P/R; matched H31 support | B →matched T9/S | H31−H33 net SW; guarded H33/H31 albedo | M/S/O; compact A solar feature | H26 plus season; H31 alone | Changing albedo at fixed snow fraction; patchy surface | [E3]; A3/A5 | H | RETAIN_CORE | Moderate retention; less local evidence than T850; key equal-cost test |
| **H34** — wrfsfcf; ULWRF; surface; instant/0 min; native 60 min; W m-2 | Upward thermal infrared flux | Surface radiative response/net LW | 02–10 and afternoon | Hourly P/R; joint H32 for net LW | B →matched S | Net LW with H32; total net radiation with SW pair | M/S; O challenger | Skin temperature/other coupling fields | Emissivity and radiative response not exact blackbody substitution | [L2]; [E5]; A3/A4 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium group risk |
| **H35** — wrfsfcf; CFNSF; surface; instant/0 min; native 60 min; W m-2 | Cloud forcing net solar flux | Cloud-related solar attenuation diagnostic | Daylight valid times | Hourly P/R | B+T9 →S | Cloud-forcing exposure and revisions | M/S/O; A alternative | H28/H31 and solar geometry | Cloud-forcing signal differs from normalized all-sky SW | [L2]; A3 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk; no exact clear-sky reconstruction |
| **H36** — wrfsfcf; REFC; entire atmosphere; instant/0 min; native 60 min; dBZ | Composite radar reflectivity | Approaching/developing weather interrupts heating | 02–16, future path to peak | Hourly spatial P/R; onset uncertainty | B+T9/derived T3 →S | Echo footprint/approach; onset versus peak; revision | A/M/S/O, especially scale/tails | H38/H37; CAPE/CIN; Q01 | Virga or misplaced echoes; missed initiation invisible | [E7]; A6/A7 | H | RETAIN_CORE | Moderate-high priority; high deletion risk; not surface-rain amount |
| **H37** — wrfsfcf; PRATE; surface; instant/0 min; native 60 min; kg m-2 s-1 | Instantaneous surface precipitation rate | Active rain/snow cooling intensity | 02–16 | Hourly snapshots P/R, not interval total | B+T9 →S | Rate maxima/onset proxy | M/S/O; A optional | H38 interval amount; H36 weather footprint | Brief intense event matters beyond hourly amount | [L2]; A6/A7 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk |
| **H38** — wrfsfcf; APCP; surface; accum/60 min; native 60 min; kg m-2 | Preceding-hour precipitation amount | Ground precipitation/wetting and cooling duration | 02–16, especially before peak | Native 60-min accumulation; P/R | N+T9 →S | Amounts before peak; wetting exposure | M/S/O; A weather feature | H36/H17/Q05 partial context only | Virga versus rain; stratiform rain; persistent wet surface | [L2]; A6 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high risk; preferred first one-H addition |
| **H39** — wrfsfcf; PWAT; entire atmosphere; instant/0 min; native 60 min; kg m-2 | Precipitable water in column | Deep moisture/convective-cloud environment | 02–14 | Hourly P/R; slower column state | B →S | Column moisture and revision | S/O; M/A optional | H17/H28/H36; H08/H03 | Deep moist plume above dry surface | [L2]; A1/A6 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high conditional risk |
| **H40** — wrfsfcf; VIS; surface; instant/0 min; native 60 min; m | Surface visibility diagnostic | Fog/obscuration regime and clearing uncertainty | 02–10, precipitation later | Hourly P/R | B+T9 →S | Low-visibility exposure/clearance | S/O; M/A optional | H17/H28/H36/H41 | Shallow fog without high boundary cloud fraction | [L2]; A3/A6/A7 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium risk; sentinel/missingness QC |
| **H41** — wrfsfcf; AOTK; entire atmosphere; instant/0 min; native 60 min; 1 | Column smoke optical thickness | Smoke-specific solar error regime | Daylight forecasts at all issues | Hourly P/R and spatial plume | B+T9 →S | Smoke exposure; interaction with solar | S/M/O; A optional | H31 attenuation; cloud distinction | Smoke-radiation error or displaced plume at same modeled SW | [E1]; [E9]; A6 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; rare-regime high risk; not all aerosols |
| **H42** — wrfsfcf; HGT; cloud ceiling; instant/0 min; native 60 min; gpm | Cloud-ceiling height | Vertical cloud/persistence clue beyond fraction | 02–12 chiefly | Hourly P/R; height and clearance | B+T9 →S; terrain reference required | Ceiling AGL only with valid H14; no-cloud handling | M/S/O; A optional | H28/H24/H17/H31 | Same fraction at differing cloud heights; fog/stratus | [E1]; A3/A6/A7 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high risk; decode ASL/sentinels correctly |
| **H43** — wrfsfcf; CAPE; surface; instant/0 min; native 60 min; J kg-1 | Surface-based CAPE | Convective potential absent from echo forecast | 02–14, future pre-peak state | Hourly P/R, joint H44 | B+T9 →S | Instability–inhibition group and revisions | S/O; M/A optional | H36/cloud/moisture paths | Echo-free unstable convergence or false modeled storms | [L2]; [E7]; A6 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high tail risk; mandatory joint challenge |
| **H44** — wrfsfcf; CIN; surface; instant/0 min; native 60 min; J kg-1 | Surface-based convective inhibition | Cap prevents or delays temperature-interrupting storms | 02–14, future pre-peak state | Hourly P/R, joint H43 | B+T9 →S | CAPE/CIN regime; cap evolution | S/O; M/A optional | Echo/cloud paths; thermal context | Potential convection suppressed despite high CAPE | [L2]; [E7]; A6 | H | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high tail risk; jointly evaluate cap/potential |

### 10.4 All subhourly fields

| Field ID and exact identity | Physical quantity | KDEN failure mechanism | Issue relevance | Temporal requirement | Spatial requirement | Derived uses | Model roles | Redundancy candidates | Conditional exceptions | Evidence / resolving test | Acquisition cost | Disposition | Confidence and risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Q01** — wrfsubhf; REFC; entire atmosphere; instant/0 min; native 15 min; dBZ | Composite reflectivity snapshot | Intrahour weather arrival before peak | 02–16 | Native Q15 instantaneous P/R | B+T9/derived T3 →S | Rapid echo evolution/onset | S/O/M; A optional | H36 strengthened P/R/S plus Q05 | Short-lived cells between hourly samples | [L2]; A6/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high event-timing risk; 3.72H opportunity cost |
| **Q02** — wrfsubhf; VIS; surface; instant/0 min; native 15 min; m | Visibility snapshot | Rapid fog clearance affects heating start | 02–10 chiefly | Native Q15 instantaneous P/R | B+T9 →S | Fog-duration/clearance proxy | S/M/O | H40 P/R/S; cloud/solar/T2 | Clearance between hourly snapshots | [L2]; A3/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium fog risk |
| **Q03** — wrfsubhf; GUST; surface; instant/0 min; native 15 min; m s-1 | Gust-potential snapshot | Fast mixing/outflow-risk change | 02–16 | Native Q15 instantaneous P/R | B →S | Rapid gust-potential changes | S/O; M optional | H11 P/R/S; surface vector/PBL | Momentum bursts not explained by sustained flow | [E1]; A2/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk; not interval maximum |
| **Q04** — wrfsubhf; PRES; surface; instant/0 min; native 15 min; Pa | Surface-pressure snapshot | Fast pressure jump at boundary/outflow | 02–16 | Native Q15 instantaneous P/R | B →S | Subhourly tendency/jump | S/M/O | H13 P/R/S; surface flow/moisture | Pressure-only early signature | [L2]; A2/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium timing risk |
| **Q05** — wrfsubhf; TMP; 2 m above ground; instant/0 min; native 15 min; K | 2-m air temperature Q product | Native thermal trajectory/peak and H–Q disagreement | 02–16 | Protected full Q15 instantaneous path | B+N; proposed local S | Q baseline/peak/plateau/revisions | A/M/S/O baseline | H16 overlap; cannot silently substitute | Independent-product parity and native intrahour shape | [L1]; A0 | Q | PROTECTED_BASELINE_OR_STATIC | High protection; no reuse/interpolation substitution |
| **Q06** — wrfsubhf; DPT; 2 m above ground; instant/0 min; native 15 min; K | 2-m dewpoint snapshot | Fast moisture-boundary transition | 02–16 | Native Q15 instantaneous P/R | B →S | Moisture shifts between H states | S/M/O; A optional | H17 P/R/S and surface winds | Boundary changes moisture with little T2 change | [E2]; A2/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high timing risk |
| **Q07** — wrfsubhf; UGRD; 10 m above ground; instant/0 min; native 15 min; m s-1 | 10-m zonal wind snapshot | Subhourly wind-direction transition | 02–16 | Q15 instantaneous, joint Q08 | B →T9/S | Q vector/onset/convergence | A/M/S/O | H18/H19 P/R/S; Q09/Q10 | Fast boundary/outflow between hourly states | [E2]; [E7]; A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high timing risk; pair costs 7.44H |
| **Q08** — wrfsubhf; VGRD; 10 m above ground; instant/0 min; native 15 min; m s-1 | 10-m meridional wind snapshot | Subhourly directional transition | 02–16 | Q15 instantaneous, joint Q07 | B →T9/S | Full Q vector and directional change | A/M/S/O | Same vector alternatives as Q07 | Rapid northerly/southerly surge | [L2]; A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high timing risk; paired decision |
| **Q09** — wrfsubhf; UGRD; 10 m above ground; avg/5 min; native 15 min; m s-1 | 10-m zonal wind, 5-min mean | Smoothed short-period flow regime | 02–16 | Preceding 5-min avg every 15 min, joint Q10 | B →T9/S | Mean-vector evolution | A/M/S/O | Hourly vector; Q07/Q08 snapshots | Snapshot noise masks sustained transition | [L2]; A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk; 10-min gaps remain |
| **Q10** — wrfsubhf; VGRD; 10 m above ground; avg/5 min; native 15 min; m s-1 | 10-m meridional wind, 5-min mean | Smoothed short-period direction | 02–16 | Preceding 5-min avg every 15 min, joint Q09 | B →T9/S | Full mean vector; never full-quarter mean | A/M/S/O | Same alternatives as Q09 | Different smoothing affects analog/regime identification | [L2]; A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk; paired mean group |
| **Q11** — wrfsubhf; DSWRF; surface; avg/15 min; native 15 min; W m-2 | Downward solar, 15-min mean | Exact modeled quarter-hour solar energy and gaps | Daylight forecasts at all issues | Native 15-min average; integrate complete intervals | B+T9 →S | Mean×900 s energy; cloud-gap timing | M/S/O; A compact solar feature | H31 P/R/S plus Q05 and cloud | Intrahour sunlight before peak not represented by snapshots | [L2]; [E4]; A3/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; medium-high risk; strongest non-temperature Q challenger |
| **Q12** — wrfsubhf; PRATE; surface; instant/0 min; native 15 min; kg m-2 s-1 | Surface precipitation-rate snapshot | Fast precipitation intensity/onset | 02–16 | Native Q15 instant; not mean rate | B+T9 →S | Peak/onset rate proxy | S/M/O | H37 P/R/S; Q13 amounts; H36 | Intensity matters beyond accumulated amount | [L2]; A6/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium risk |
| **Q13** — wrfsubhf; APCP; surface; accum/15 min; native 15 min; kg m-2 | Preceding-quarter precipitation amount | Pre-peak rain timing and wetting | 02–16 | Native 15-min accumulation; no redifferencing | N+T9 →S | Quarter amounts and onset; sums with parity checks | S/M/O; A weather feature | H38 P/R/S; H36 and Q05 | Short shower relative to peak hidden by hourly total | [L2]; A6/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate omission; high timing risk; cannot split H38 exactly |
| **Q14** — wrfsubhf; HGT; cloud ceiling; instant/0 min; native 15 min; gpm | Cloud-ceiling snapshot | Abrupt cloud lifting/low-cloud onset | 02–12 chiefly | Native Q15 instant P/R | B+T9 →S; valid height reference | Ceiling duration/lifting with sentinels masked | S/M/O | H42 P/R/S; H28/H31/Q05 | Intrahour lifting changes heating opportunity | [E1]; A3/A7 | Q | RETAIN_CHALLENGER_PENDING_COHORT | Moderate-high omission priority; medium fog/cloud risk |

## 11. Unresolved findings and the evidence that would settle them

| Open question | Required evidence | Consequence |
|---|---|---|
| Does H07 add error information beyond T2? | A1 on all-weather early and late issues, with/without thermal–mixing interactions. | Retain for demonstrated conditional value; otherwise allow removal despite D1. |
| Is H33 a better use of one H slot than H13/H38/H02? | Equal-cost nested swaps; snow and frontal/precipitation strata; location and scale scores. | Keep the winning supported source or report indistinguishability. No literature-derived numerical ranking. |
| Does surface geometry cover enough aloft-flow information? | A2/A8 in shallow-cold, deep-mixed, and strong-westerly episodes, including combined aloft blocks. | Add a whole aloft vector or thermal group if needed; never claim surface wind measures shear. |
| Does R13 miss wet-ground or nocturnal radiation errors? | A3/A4/A6 and early-issue winter/wet-day checks. | Promote pressure/longwave/skin/flux/precipitation source or group as supported. |
| Are echo-free convective tails underdispersed? | A6 with CAPE/CIN-defined, source-only strata and false/missed storm diagnostics. | CAPE/CIN may require a swap or budget revision. |
| Is Q11 or another Q worth several H fields? | All section 6 H-strengthened and equal-cost comparisons. | Retain Q only if incremental probability value warrants its opportunity cost. |
| Is 6.43 days realistic for these fields? | Bounded reduced-universe pilot with representative regimes, field bytes, and full wall time. | Recompute the projection; do not imply a guaranteed seven-day finish. |
| Is the final union actually minimal among plausible choices? | A10 bidirectional block selection, swaps, model-family union, precision bounds. | Shrink further if supported; otherwise retain the smallest demonstrated union. |

## 12. Decision and versioned next steps

**Scientific conclusion: REVISE.** C32 is a conservative comparator, not an established minimum. R13 is the proposed acquisition list, with R14-P the first one-field expansion and the cost-matched challenges specified above. The meteorological case for major reduction is credible; the claim of zero predictive loss is not yet established.

The required sequence is:

1. Review this scientific proposal, the separately costed full-universe selection cohort, and proposed tolerances. This document does not authorize either run.
2. Implement and owner-run the approved cohort and leakage-safe comparisons. Freeze the selected model-family union, cadence, geometry, and empirical dispositions using the declared decision rules.
3. After acceptance of that reduced union, create successor H/Q registries and spatial/derivation contracts without overwriting originals. Explicitly retire unavailable composites.
4. Regenerate and seal both request plans with honest identities/hashes; rerun affected registry/schema/plan validations.
5. Run the separately authorized bounded confirmation pilot. Confirm selectors, native intervals, H/Q independence and parity checks, coordinate-era/upstream extraction, missingness, deterministic output, and resume behavior. Re-measure bytes/throughput and update runtime.
6. Obtain the separate full-history approval required by the brief before Steps 05/06. Preserve the original Step 04 PASS for the original 58-field pilot.

This research created only a new Markdown document. It did not change code, registries, schemas, request plans, canonical archives, or PASS records, and did not launch acquisition or modeling.

## 13. References and evidence limits

Local documents are project evidence, not independent literature replications. Published results below are used within their geography, model version, and study population. Acquisition priorities and expected conditional overlap are this report's inferences.

- **L1:** [KDEN v3.75 Step 04.5 Feature Universe Study][L1]. Governs requested scope, selection requirements, and documentation-only process.
- **L2:** [Universal Issue-Time Feature Panel Scientific Specification v1.0][L2]. Historical source families, composites, and semantics; checkpoint/MADIS/SPARSE policies are not adopted as current instructions.
- **L3:** [D1 Historical Synthesis][L3], especially pp. 3–6 and 7–10. Sunny-day thermal comparison and transfer limitations.
- **L4:** [Previous feature-universe recommendation][L4]. Defines C32 and its later C13/C14 addendum; unchanged by this new report.
- **L5–L8:** [Hourly registry][L5], [subhourly registry][L6], [Step 04 pilot][L7], [current project specification][L8]. Exact identities and current engineering/legality constraints.
- **E1:** [Benjamin et al., NOAA Technical Memorandum OAR GSL-66, updated 2021][E1]. Diagnostic definitions: PBL/gust, cloud layer/ceiling, and smoke optical thickness. A documentation source, not a field-selection study.
- **E2:** [Darby, Neff, and Banta (1999), Multiscale Analysis of a Meso-β Frontal Passage in the Complex Terrain of the Colorado Front Range][E2]. Observed regional air-mass/boundary behavior; one event cannot establish typical predictor importance.
- **E3:** [Adler et al. (2023), Impact of Seasonal Snow-Cover Change on the Observed and Simulated State of the Atmospheric Boundary Layer in a High-Altitude Mountain Valley][E3]. Colorado snow/albedo/coupling evidence; East River Valley is not the airport plains.
- **E4:** [Benjamin, James, and Turner (2025), Excessive Downward Shortwave Radiation in the HRRR and RAP Weather Models and Testing Strategies for Improvements][E4]. Cloud/solar/lead-related model-error evidence, including Table Mountain; not KDEN ablation evidence.
- **E5:** [He et al. (2023), Evaluation of the Near-Surface Variables in the HRRR Weather Model Using Observations from the ARM SGP Site][E5]. Radiation and flux error evidence from Oklahoma.
- **E6:** [Adler et al. (2023), Evaluation of a Cloudy Cold-Air Pool in the Columbia River Basin in Different Versions of the HRRR Model][E6]. Cloud/erosion mechanism with a different basin and case-study setting.
- **E7:** [Meyer, Bobb, and Dulong, Denver ARTCC thunderstorm-pattern study][E7]. Local operational terrain/convergence context. Historical aviation/runway details are not used as current facts.
- **E8:** [Struthwolf (1995), Forecasting Maximum Temperatures through Use of an Adjusted 850- to 700-mb Thickness Technique][E8]. Western-site thermal-method precedent and modifiers; not an HRRR/KDEN conditional test.
- **E9:** [HRRR-Smoke Williams Flats fire evaluation (2022)][E9]. Smoke representation/radiative coupling context; wildfire-case results do not establish KDEN H41 incremental skill.
- **E10:** [Lee et al. (2024), On the Importance of Regime-Specific Evaluations for Numerical Weather Prediction Models as Demonstrated Using the HRRR Model][E10]. Supports evaluating conditional weather regimes rather than annual averages. The study does not select this report's fields.
- **E11:** [Delle Monache et al. (2013), Probabilistic Weather Prediction with an Analog Ensemble][E11]. Analog forecast methodology; the underlying model/site experiment differs from this application.
- **E12:** [Gneiting and Raftery (2007), Strictly Proper Scoring Rules, Prediction, and Estimation][E12]. Probability evaluation principles; numeric tolerances here are proposals.

[L1]: <./STEP_04_5_FEATURE_UNIVERSE_STUDY.md>
[L2]: <./1. research/direction /v2---x[d,t] acquistion/KDEN_Universal_Issue_Time_Feature_Panel_Scientific_Specification_v1.0.docx>
[L3]: <<LOCAL_PATH> v2/research/x. inhouse findings/D1--Historical Synthesis of the KDEN Dataset 1 Regression Study.pdf>
[L4]: <./reports/step_04_5_feature_universe_scientific_recommendation.md>
[L5]: <./registries/hrrr_hourly_v375.csv>
[L6]: <./registries/hrrr_subhourly_v375.csv>
[L7]: <./reports/step_04_pilot_report_v375.md>
[L8]: <./PROJECT.md>
[E1]: https://repository.library.noaa.gov/view/noaa/32904/noaa_32904_DS1.pdf
[E2]: https://journals.ametsoc.org/view/journals/mwre/127/9/1520-0493_1999_127_2062_maoamf_2.0.co_2.xml
[E3]: https://repository.library.noaa.gov/view/noaa/52443/noaa_52443_DS1.pdf
[E4]: https://doi.org/10.1175/MWR-D-25-0094.1
[E5]: https://journals.ametsoc.org/view/journals/apme/62/6/JAMC-D-23-0003.1.xml
[E6]: https://gmd.copernicus.org/articles/16/597/2023/
[E7]: https://www.weather.gov/media/aviation/CaseStudies/zdvtstms.pdf
[E8]: https://journals.ametsoc.org/view/journals/wefo/10/1/1520-0434_1995_010_0160_fmttuo_2_0_co_2.xml
[E9]: https://acp.copernicus.org/articles/22/10195/2022/
[E10]: https://doi.org/10.1175/WAF-D-23-0177.1
[E11]: https://doi.org/10.1175/MWR-D-12-00281.1
[E12]: https://doi.org/10.1198/016214506000001437
