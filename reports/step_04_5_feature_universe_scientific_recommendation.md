# KDEN v3.75: meteorological recommendation for the acquisition universe

Research date: 13 September 2026. Documentation only. Decision status: **DO_NOT_REDUCE_YET** for the production acquisition contract; **the seven-day-budget reconsideration in section 1.1 supersedes C32 as the preferred first test**. C32 remains a conservative comparator.

## 1. Executive recommendation

KDEN needs a compact description of the air mass, its connection to the surface, the energy available for heating, and the weather transitions that can interrupt or restart heating. It does not need every diagnostic of those processes at both hourly and quarter-hourly cadence.

The initial conservative proposal was **30 H identities, including static H14, plus Q05 and Q11**. Section 1.1 revises its priority in response to the seven-day runtime objective. This is a proposed acquisition union, not a 32-column model. It preserves both independent temperature baselines, 850-mb temperature and flow, 700-mb structure, surface state, energy partition, snow, boundary-layer cloud, radiation, and convective potential. It tests whether most rapid-event information can be recovered adequately from hourly paths, spatial context, cycle revisions, and the protected Q15 temperature trajectory.

**Proposed core, C32:**

```text
Hourly, 30 identities / 29 dynamic fields:
H01 H02 H03 H04 H05
H07 H09 H10 H12 H13 H14 H15 H16 H17 H18 H19
H21 H22 H24 H25 H26 H28
H31 H32 H33 H34 H36 H38 H43 H44

Subhourly, 2 fields:
Q05 Q11
```

This reduces projected logical requests from **55,593,858 to 21,315,352**, a **61.66% reduction**. Holding the measured eight-worker request rate fixed gives **381.90 hours / 15.91 days**, versus **996.06 hours / 41.50 days**. These are request-scaled scenarios, not a measured runtime for C32. Field size, range adjacency, and network behavior can change the result.

The proposed omission set is:

```text
H06 H08 H11 H20 H23 H27 H29 H30 H35 H37 H39 H40 H41 H42
Q01 Q02 Q03 Q04 Q06 Q07 Q08 Q09 Q10 Q12 Q13 Q14
```

**None of these 26 omissions is a completed empirical deletion decision.** They receive `RETAIN_CHALLENGER_PENDING_COHORT` in the matrix and remain in the selection acquisition. There is no demonstrated deterministic redundancy among the present 58 identities that licenses deleting one now. The historically removed raw specific-humidity field is already outside this universe.

Prioritize these findings:

1. **Keep H07, 850-mb temperature, in the core.** D1 is direct KDEN evidence in its favor. Test the added value of thickness; do not let thickness's physical appeal displace the stronger simple temperature control.
2. **Prefer H28 as the initial lower-cloud regime field.** NOAA specifically recommends its terrain-relative boundary-layer cloud diagnostic over conventional low-cloud fraction in elevated terrain. H29 remains a comparison, not an assumed interchangeable substitute. [R1]
3. **Keep Q11 as the leading non-temperature Q candidate.** Its preceding-quarter-hour average supplies solar-energy information that hourly instantaneous H31 cannot reconstruct exactly. Whether that difference improves Tmax probabilities remains a test.
4. **Treat Q07/Q08, Q01, and Q13 as the leading rapid-transition challengers.** Front/outflow arrival and interrupted heating are plausible reasons to pay for additional Q messages. Their benefits must survive comparisons against better H spatial summaries and revisions.
5. **Test geometry before adding correlated diagnostics.** A centered 9×9 tile samples only a local neighborhood. Fixed foothills, north/northeast plains, east plains, and Palmer Divide sectors may add more useful information per retrieved message.

A practical fallback if C32 loses stable skill is **C36 = C32 + Q01/Q07/Q08/Q13**. A more conservative, explicitly costed sensitivity is **C41 = C36 + H06/H08/H39/H41/H42**. These are test sets, not a claim that all four extra Q fields or all five extra H fields must survive together.

The immediate next acquisition should be a separately approved, full-universe **selection cohort**, not the reduced full-history run. A 600-day design is specified below. At the current rate it costs approximately 12.0 days itself; if C32 subsequently passes and cohort data can be reused, cohort plus remaining C32 acquisition is approximately **23.3 days total**. That honest end-to-end number is more useful than advertising 15.9 days alone.

## 1.1 Reconsideration: C32 is not a demonstrated minimum

**Yes, C32 still contains plausible excess acquisition.** The initial recommendation placed too much weight on preserving complete mechanistic diagnostics. A diagnostic can be physically distinct without providing useful additional information about the temperature forecast error. The right test is incremental probability skill conditional on the more important retained predictors, not whether the omitted quantity can be reconstructed exactly.

This distinction changes the priority of several C32 groups:

| C32 sources to challenge first | More economical representation retained | What is deliberately lost, rather than falsely reconstructed |
|---|---|---|
| Q11: quarter-hour mean solar | H31 hourly solar path/spatial context plus Q05 temperature evolution | Exact quarter-hour solar energy. Semantic novelty alone does not justify 1.62 days of acquisition. |
| H32/H34: net longwave; H33: reflected solar | H31, H26 snow fraction, H28 cloud and temperature context | Explicit net radiation and albedo. These become challenger diagnostics; no blackbody or constant-albedo substitution is asserted. |
| H15/H21/H22: skin temperature and turbulent flux partition | H24 mixing depth, H17 moisture, radiation/snow and T2 path | Explicit surface-air contrast and sensible/latent partition. Wet-ground and early-morning cases are the main deletion risks. |
| H01–H05: 700-mb height, temperature, moisture and vector | H07 T850, surface wind/moisture and H24 | Deep thermal/moisture structure and upper flow. This is a substantial compression, especially risky during deep mixing or decoupling. |
| H09/H10: 850-mb vector; H12 reduced pressure | H18/H19 surface vector and H13 pressure tendency, with frozen upstream surface supports | Vertical shear and reduced-pressure spatial pattern. Surface signals may identify the relevant error regime without those full diagnostics. |
| H25: snow water | H26 snow fraction | Snow mass/melt persistence. Fraction is a first representation of snow regime, not an exact SWE substitute. |
| H43/H44: CAPE/CIN | H36 echo evolution and cloud/temperature paths | Untriggered convective potential. This is higher-risk than dropping redundant energy diagnostics; retain the pair as a priority challenger. |

These are **conditional-redundancy hypotheses**, not established lossless deletions. The most aggressive cuts surrender some potentially useful information. The proposed trade is a smaller set that may still support competitive calibrated models, not equal representation of every mechanism.

### A seven-day acquisition target

At the measured request rate, seven days accommodates at most **12 dynamic H fields plus Q05 and static H14**. Keeping Q11 as well leaves room for only eight dynamic H fields. I would prioritize broader hourly regime coverage over Q11 until Q11 demonstrates incremental skill.

A concrete **C13 budget candidate** is:

```text
11 dynamic hourly fields:
H07  T850                 H13  surface pressure
H16  hourly T2            H17  surface dewpoint
H18/H19  surface U/V      H24  PBL depth
H26  snow fraction        H28  boundary-layer cloud
H31  downward solar       H36  composite reflectivity

Plus static H14 and protected Q05.
```

C13 is 8,609,879 logical requests: **154.26 hours / 6.43 days** under the same first-order scaling. **C14 = C13 + H38 hourly precipitation amount** costs **164.74 hours / 6.86 days**. H38 adds wet-event amount beyond echoes, but C14 has almost no timing margin. Neither estimate guarantees a seven-day wall-clock maximum; both exclude selection work and require actual field-byte/throughput confirmation.

This retains temperature evolution, a separate low-level thermal reference, surface circulation/moisture/pressure, mixing, snow, cloud, sunlight and nearby modeled weather. All current cycles, horizons, issue-time legality, and independent H16/Q05 identities remain intact. Newly proposed upstream extraction must be frozen and validated; its benefit is not assumed in the cost or skill result.

**Revised priority:** test C13/C14 first, then add physical groups only where their incremental benefit justifies their measured cost. Compare at least a thermal-depth addition (H02), a surface-energy group (H21/H22), the 850 vector, CAPE/CIN, snow/albedo additions, and Q11. C32 is the conservative comparator, not a claim that everything below it is scientifically inadequate. None of these groups is automatically entitled to a place in the final union.

### Why retain T850?

The reason is physical as well as empirical. T2 is the model's surface-temperature answer after its assumptions about mixing, radiation and surface exchange. T850 supplies another view of the low-level air mass. At a similar forecast T2, differing T850 can indicate differing coupling or air-mass regimes and potentially different residual bias or spread. That is the meteorological hypothesis; D1 strengthens it with local predictive evidence. The thermal-forecasting precedent and HRRR coupling evidence support testing this distinction. [R2/R3]

**D1 does not prove incremental value over T2.** A strong standalone T850 regression may partly reflect the seasonal/air-mass signal already in the temperature baseline. H07 should therefore face a baseline-plus-regime versus baseline-plus-regime-plus-H07 comparison. It is the preferred initial thermal challenger because of physical relevance and local evidence, not because earlier work makes it permanently protected. If it adds no stable conditional skill, it can be removed too.

### The seven-day limit and selection cost

The original 600-day full-universe cohort alone costs approximately 12 days. It is incompatible with a seven-day **total project** acquisition budget. Even a 6.43-day final universe leaves room for only roughly 34 full-universe cohort days under the reusable-cohort scaling, before confirmation overhead—insufficient to certify the proposed fine all-regime tolerances.

Therefore the brief's comprehensive full-universe validation and a seven-day end-to-end cap cannot both be promised at current throughput. If seven days refers to the final full-history run, C13/C14 are plausible acquisition targets. If it includes research acquisition, the study design or measured throughput must also change; a small pilot can screen feasibility but cannot prove all-weather noninferiority. No larger run or contract change is authorized by this reconsideration.

**Interpretation of the original matrix:** section 6 records the original C32 dispositions and mechanisms. Under this revised budget proposal, every C32 `RETAIN_CORE` field absent from C13 becomes `RETAIN_CHALLENGER_PENDING_COHORT`; the three protected fields remain protected. Thus the revised C13 proposal has 3 protected, 10 core, and 45 challenger identities. This explicit override supersedes the initial retention priority without erasing its rationale or claiming that any deletion has been validated.

## 2. Scope, evidence, and what historical results establish

This report uses the supplied Step 04.5 brief and Universal Panel specification, the subsequently supplied D1 synthesis, and a narrow set of files explicitly referenced by the brief: current `PROJECT.md`, both field registries, decoded-identity metadata, and the Step 04 pilot reports. No previous codebase was imported or executed. No source acquisition or model fitting was performed. Literature is used to identify mechanisms and prioritize tests; it is not presented as a KDEN feature-ablation result.

Three evidence classes apply throughout:

- **KDEN empirical:** reported results from D1, specific to its sunny-day cohort and forecast construction.
- **Regional/process evidence:** Front Range observations, local NWS studies, HRRR diagnostics, or HRRR evaluations elsewhere. These support a pathway, not a numerical KDEN benefit.
- **Study hypothesis:** the proposed summary, cadence, geometry, retention priority, or decision threshold. These require validation.

### 2.1 D1 materially changes the prior for thermal pruning

The supplied D1 synthesis reports 546 k3 sunny-day rows, with 94 days in the 2025 holdout. Its one-predictor annual 850-mb TMP model, using the 18Z cycle at FH03 and valid at 21Z, achieved development LOYO MAE 1.654°F and holdout MAE 1.871°F. The corresponding 850–700-mb thickness model achieved 2.141°F and 2.311°F. The freshest low-level predictors repeatedly led their respective searches. These numbers are transcribed from D1, not independently recomputed here. [L3, pp. 3–6]

**Implication:** preserve H07 and give H01/H06 thickness a fair incremental comparison. The fact that T850 beat thickness alone does not prove that thickness adds nothing conditional on T850, nor that H06 is unnecessary to every competitive model.

The owner identifies 850 mb as above ground in the project context; D1 describes 850–700 mb among its above-ground study layers while also calling 850 mb terrain-adjacent. **This recommendation does not classify the KDEN 850-mb family as invalid or remove it on terrain grounds.** A numerical pressure/height check is ordinary provenance QC, especially for newly displaced mountain points; it is not evidence overturning D1. The synthesis is a predictive study, not a supplied cell-by-cell vertical-clearance audit.

D1 does not establish incremental skill over the HRRR 2-m path, early-morning skill, all-weather calibrated probabilities, or the optimal joint field union. Its 21Z valid-time and observed sunshine gate must not become v3.75 acquisition filters. Development LOYO was appropriate to that historical study but is not the future-blocked evaluation proposed here.

D1's broader lesson is also important: seasonal calibration transferred unevenly, and comparing different sunny-day gates changed the evaluated population. Therefore use common target days when comparing universes, and diagnose fall transitions through weather fields rather than deleting troublesome days. The disclosed 2025 results mean 2025 cannot now be described as an entirely untouched project-wide final test. [L3, pp. 7–10]

The western-site precedent is consistent with this interpretation. Struthwolf's Dugway method used adjusted 850–700-mb thickness with additional treatment of advection, ground state, pressure, and circulation. It is supporting precedent, not a Denver validation or an HRRR-only recipe. [R2]

### 2.2 What remains frozen

Retain HRRRv4; 2021-01-01 through 2026-09-11; fixed `W[d] = [07Z_d, 07Z_(d+1))`; previous-local c23 and target-local c00–c14; native UTC identities and DST handling; FH00; current native-product horizons and `TARGET_WINDOW` ceiling; independent coherent cycles; current availability emulation; independent H/Q products; KDEN coordinate-era lineage; fail-closed semantics; and source/truth/model/market separation.

Evaluate a 15-minute issue grid approximately 02:00–16:00 America/Denver, with primary reporting through 14:00. Nonexistent spring-forward issues are omitted; repeated civil timestamps retain UTC/offset identity. Do not cut late cycles because the owner's main emphasis is earlier. Every retained dynamic H/Q field keeps its full allowed native path. There is no return to the old checkpoint-driven SPARSE/PATH acquisition policy.

Model output at a future valid time is legal only because its producing cycle/product was available at issue time. Cross-product composites require the same initialization. Revision features compare separately legal cycles on identical valid-time support; they never create a spliced trajectory. A 15-minute output cadence does not mean a new HRRR initialization every 15 minutes.

The current archive can retain an endpoint state at `W_end` under its ceiling rule. The target maximum still excludes that endpoint because the target window is right-open. Initial c23 states before `W_start` can supply context but cannot enter the target-window maximum.

**HRRR-only also means no observed floor.** Do not carry `R_low`, MADIS departures, observation-conditioned floor flags, or the old FLOOR baseline into these experiments. Forecast temperatures earlier in the target window are model estimates, not proof of a realized maximum. Include forecast elapsed-window context, remaining-window maxima, and alternate-peak geometry; validate against the full-day authoritative label.

## 3. KDEN failure mechanisms and acquisition implications

### 3.1 Air-mass temperature versus realized surface coupling

T850 can be a strong thermal predictor while the forecast still misjudges how that air mass couples to the airport surface. The proposed diagnosis separates thermal state (H07, H02), vertical moisture contrast (H03, optionally H08), flow (H04/H05 and H09/H10), and surface coupling (H15–H19, H21/H22, H24).

Candidate features include T850 relative to T2, T850–T700 difference, 700-mb height above model terrain, daytime PBL growth, sensible-heating integral, and differences between lower and upper wind vectors. A pressure-coordinate temperature difference is not a geometric lapse rate. Potential-temperature contrasts are preferable when diagnosing stability; two levels do not resolve a shallow inversion or a full mountain-wave profile.

The question is often whether HRRR mixes too quickly or too slowly, not whether its free-air temperature is simply wrong. The HRRR system literature identifies PBL, cloud, and land-surface representation as central to near-surface forecast behavior. Use that as mechanism support; it does not show H24's incremental KDEN score. [R3]

**Issue relevance:** 02:00–08:00 for forecast inversion persistence and future coupling; 08:00–14:00 for mixing onset, entrainment, and heating rate; 14:00–16:00 for delayed or renewed heating. These are approximate civil-time reporting bands; actual sunrise and season control the physics.

### 3.2 Downslope penetration, upslope replacement, and shallow fronts

Warm/dry downslope air near the foothills and cooler/moister air over the plains can be separated by a mobile boundary. In the Front Range event studied by Darby, Neff, and Banta, wind and moisture changes were important boundary indicators, and the boundary moved with the competing flows. This is regional observational evidence; it is not a measured frequency of Tmax failure at KDEN. [R4]

The forecast failure hypothesis is that HRRR places this boundary on the wrong side of the airport or mistimes its passage. Preserve both U and V at 10 m, 850 mb, and 700 mb. Eastward U is a useful first westerly-flow proxy, but **positive U at one level is not a Chinook classifier**. Surface penetration, drying, thermal contrast, and spatial coherence matter. A cold northwest flow can also have positive U.

H13's same-location pressure tendencies and H12's reduced-pressure spatial pattern are distinct candidates. Do not take raw surface-pressure differences across a mountain/plain elevation contrast as pure meteorological pressure gradients. H12 is retained primarily to test a physically interpretable mesoscale pressure context.

Q07/Q08 can resolve a modeled intrahour wind change; Q06 can resolve drying/moistening; Q04 can resolve a pressure jump. Their joint transition signature may matter when Q05 already shows a rapid temperature change. Conversely, if Q05, hourly vectors/moisture, and spatial H fields already distinguish the error regime, acquiring all three additional Q families is unnecessary. This is a conditional ablation, not a correlation argument.

**Spatial implication:** test north/northeast cold-intrusion sectors, east-plain contrasts, and west/foothill-to-airport structure. KDEN should not inherit Boulder windstorm climatology as if it were the same exposure.

### 3.3 Denver convergence, Palmer Divide influence, and interrupted heating

NWS's Denver aviation study describes convergence near DIA involving mountain westerlies and plains easterlies, sometimes organized into a Denver cyclone. Local moisture, instability, and convergence determine whether storms develop. The airport-specific relevance supports retaining flow vectors plus a pre-convective and a realized-weather representation. [R5]

The Denver cyclone modeling literature also links heating and mixing to lee-side shear and convergence. This makes circulation and PBL variables complementary rather than interchangeable. [R6] Denver-area nowcast experiments provide additional evidence that convergence boundaries matter for initiation, although their observational inputs are outside this HRRR-only branch. [R7]

Retain H43/H44 as a CAPE/CIN pair and H36/H38 for echo/precipitation occurrence. CAPE/CIN diagnose forecast potential; REFC and APCP describe what the model actually develops. CAPE alone does not specify the trigger, and surface-parcel CAPE/CIN can miss elevated convection. No new parcel family is proposed here.

For Tmax, a storm can terminate heating, produce evaporative cooling, leave a cold pool, or permit recovery after passage. Precipitation need not fall at the station for an outflow to reach it. REFC alone does not measure rain reaching the surface, and an hourly accumulation cannot locate onset within that hour. Q01, Q13, and Q07/Q08 therefore receive high-priority challenger tests, including event onset relative to the forecast maximum and post-event recovery.

Use a window through the entire remaining target interval as well as a prepeak window. Restricting everything to the model's first predicted peak would miss an incorrectly early peak followed by renewed warming.

**Issue relevance:** strongest approximately 10:00–16:00 in convective seasons, but pre-dawn forecasts can still use legally available future convective paths as uncertainty predictors. Fifteen-minute detail at long leads may express model timing noise rather than useful precision.

### 3.4 Cloud, solar energy, and clearing errors

Cloud timing can alter both the accumulated daytime energy and the location of the maximum. A 2021 USCRN evaluation found substantial changes in HRRR temperature bias across solar/heating regimes. This supports regime-specific probability evaluation; its national numerical biases should not be copied into a KDEN correction. [R8]

Use H28 for boundary-layer cloud context, H31 for instantaneous downwelling solar structure and revisions, and Q11 for native interval energy. Retain H32/H34 together for net longwave and H31/H33 together for absorbed shortwave. A flux-only model may miss an error regime; a cloud-only model does not measure heating energy.

The principal candidate alternatives are H28 versus H29; total cloud H30 added to lower cloud; H35 cloud forcing added to actual radiation; and H42 ceiling added to cloud fraction and radiation. Test each after normalizing daytime radiation for solar geometry, with low-sun guards. Astronomical top-of-atmosphere radiation is not the model's clear-sky surface flux; it cannot exactly reconstruct CFNSF.

Ceiling and cloud cover are different quantities. Their potential added value is distinguishing persistent low stratus/fog from higher cloud with comparable solar suppression. Preserve no-cloud/missing states before computing any height threshold. Native ceiling height needs its documented vertical reference converted consistently with H14. [R1]

Q11 is deliberately retained as **core for testing, not a proven necessity**. Hourly H31 integration is a quadrature estimate. Q11 integrates the model's native quarter-hour average over complete intervals; it still is not observed sunlight and cannot repair an entirely missed cloud regime by itself.

### 3.5 Snow, ground moisture, and the partition of energy

Snow-covered fraction, snow water, and snow depth describe different aspects of the ground. None is deterministically recoverable from the others without extra assumptions. The core retains H25/H26; H27 must earn its added cost through snow density/insulation or melt-state information.

The proposal also retains reflected solar flux H33. Incoming radiation alone cannot distinguish strong sunshine absorbed by bare ground from strong sunshine reflected by snow. Test H25/H26 jointly with H31/H33 and H21/H22; do not discard reflected radiation just because it tracks downwelling radiation on snow-free days.

A Colorado mountain-valley HRRRv4 study found snow-dependent temperature, stratification, and radiation errors. That is evidence for a snow–coupling interaction, **not evidence that KDEN has the same valley inversion, bias sign, or magnitude**. [R9] A separate Columbia Basin study found cloud representation and cold-pool erosion strongly affected simulated temperatures, again supporting a process analogy rather than a KDEN coefficient. [R10]

H21/H22 describe the modeled sensible/latent partition; H24 describes mixing depth. These are not redundant simply because HRRR computes them in a coupled system. H20 moisture availability is a challenger for antecedent ground regime, especially before sunrise when fluxes are weak. It is not an observed soil-moisture analysis and must not be relabeled as a particular volumetric soil layer. H23 ground heat flux tests storage/release beyond skin-air contrast and radiation.

Do not reconstruct H23 from a simplistic energy-balance residual. Storage, phase changes, diagnostic timing, and surface representation prevent assuming exact closure from the retained snapshots. Likewise, do not delete H34 by assuming a blackbody formula from H15 alone; effective emissivity and surface aggregation matter.

### 3.6 Smoke and visibility

H41 is a serious **high-priority H challenger**, not a generic pollution index. NOAA identifies AOTK as smoke optical depth rather than total dust/urban-aerosol optical depth. [R1] HRRR-Smoke includes radiative feedback, so some modeled smoke influence is already in radiation and temperature. [R11]

The residual hypothesis is that a smoke-affected forecast has different bias or uncertainty even at the same modeled solar flux. Test H41 conditional on H31/Q11, lower cloud, season, and baseline geometry. Column optical depth is not equivalent to surface visibility; elevated smoke can reduce sunlight without comparable surface obscuration. If HRRR misses the plume altogether, its own AOTK may also fail to flag the situation.

H40/Q02 may distinguish near-surface fog or obscuration, but their historical observation-bridge rationale is weaker without MADIS. They remain challengers because fog and low cloud are not identical. No study reviewed here establishes stable KDEN incremental skill for H41, H40, or Q02, and none establishes that these mechanisms do not matter.

### 3.7 Spatial uncertainty and cycle instability

HRRR evaluations describe run-to-run variability and remaining timing errors. Treat revisions and spatial contrasts as possible predictors of conditional dispersion, not as independent ensemble members. [R12]

A neighborhood standard deviation is spatial heterogeneity in one forecast, not an estimated probability spread. Likewise, agreement between two cycles is not proof of correctness. Test whether those quantities predict residual width on held-out target days. Keep revision counts, common-support fractions, forecast age, and unavailable-revision flags so the model cannot confuse missing history with a stable forecast.

No KDEN mechanism reviewed here has been shown irrelevant to v3.75. The selection problem is whether a particular source adds enough information about that mechanism after conditioning on the retained sources.

## 4. Protected sources, composites, and physically valid summaries

H14 is static lineage; H16 and Q05 are independently reacquired baselines. They are protected in every deployable candidate. H-only experiments are diagnostics with a separately named baseline and cannot silently revoke Q05 protection.

| Scientific group | Required sources | Meaning and elimination rule |
|---|---|---|
| 700-mb vector | H04 + H05 | Earth-relative two-component flow; keep/remove the vector jointly. |
| 850-mb vector | H09 + H10 | Low-level flow/advection; joint selection. |
| Hourly 10-m vector | H18 + H19 | Surface flow and shear; joint selection. |
| Q15 snapshot vector | Q07 + Q08 | Within-cycle direction/speed transitions; joint selection. |
| Five-minute mean vector | Q09 + Q10 | Distinct time support; joint comparison with snapshots. |
| Thickness | H01 + H06 | Same-time 700-minus-850 height; dropping H06 removes this composite. H01 can remain independently for 700-mb height context. |
| Thermal depth | H07 + H02 | Temperature difference; add H01/H06 if a geometric lapse rate is wanted. |
| Net shortwave | H31 + H33 | Consistent instantaneous absorbed solar flux. |
| Net longwave | H32 + H34 | Consistent instantaneous longwave balance. |
| Net radiation | H31 + H33 + H32 + H34 | Removing a component retires this composite or creates an explicitly different approximation. |
| Evaporative fraction | H21 + H22 | Signed, denominator-guarded LHTFL/(SHTFL+LHTFL). |
| Convective potential | H43 + H44 | CAPE with inhibition, not an isolated CAPE coordinate. |
| Snow density challenger | H25 + H27 | Water/depth ratio only with valid depth and consistent units. |
| Derived humidity | H17 + H13; H16 for RH | Frozen thermodynamics, same-time/cycle/support alignment. No extra raw humidity request. |

For fluxes, retain native signs and document any conversion to an upward-positive turbulent or downward-positive radiative convention. Use complete interval support. Q11 cannot be combined with an hourly H33 snapshot and called exact quarter-hour net shortwave. H31/H33 hourly integration remains an approximation; Q11 can enter separately as exact integration of available complete mean-flux intervals.

For precipitation, sum non-overlapping native H38 or Q13 amounts. A partial interval overlapping an issue/peak boundary cannot be fractionally allocated and called exact without additional assumptions. Report complete-interval totals plus boundary coverage; any duration-proportional allocation is a named approximation. Quarter-hour APCP totals are not guaranteed identical to independently acquired H38 until parity is demonstrated, and even exact parity would not itself authorize dropping either product identity.

Store U/V with a verified orientation; convert grid-relative winds before interpreting eastward flow or earth-coordinate advection. For advection, gradients and vectors must share coordinates and valid times. Reflectivity is logarithmic: threshold coverage and maxima are simple robust candidates; any mean requiring linear reflectivity must transform to Z before averaging, rather than silently treating mean dBZ as mean echo power.

## 5. Spatial-contract experiments

Existing supports remain the reference: BI, NN, centered 3×3, and centered 9×9. A nominal 3-km grid gives about 6 km between outer centers in a 3×3 and 24 km in a 9×9; a 9×9 extends only approximately 12 km from its center in each grid direction. Actual physical distances require the projection/map factors.

The proposed additional supports are **experimental geometry**, not coordinates or schema changes already approved:

| Geometry | Initial design to freeze before scoring | Mechanism / source priorities |
|---|---|---|
| G0 | Existing point and centered tiles | Reference for every spatial comparison. |
| G1 | Add compact 3×3 tiles for T2, Td2, surface wind, pressure, skin temperature, snow, PBL and fluxes where current fields are BI only | Local thermal/wind boundary, land heterogeneity, station/grid mismatch. |
| G2-W | Three fixed western/west-northwestern locations roughly 30–80 km from KDEN, chosen against terrain | Foothill-to-airport warming/drying and downslope penetration. Prefer surface fields; check pressure-level terrain support independently at each point. |
| G2-N/E | Fixed north/northeast and eastern plains locations, approximately 30–100 km away | Cold surges, shallow fronts, moisture supply, low-cloud displacement; T2/Td2/U10/V10/PRES/MSLMA and cloud/precipitation. |
| G2-S | Fixed south/southeast locations approximately 30–80 km away spanning the Palmer Divide approach | Southerly flow, convergence and convective initiation. |
| G3 | A fixed union of small sectors, summarized as directional contrasts; optionally weight them using the selected legal cycle's forecast flow | Test source-internal upstream context without selecting geography after seeing errors. |

Distances are initial search bounds, not claimed optimal meteorological influence radii. Before acquisition, map the proposed locations to the HRRR grid and both station eras; reject terrain-invalid pressure-level cells. A whole-GRIB message already contains these locations, so compact extractions need no additional field-message network request. They do increase output bytes, extraction work, and the number of candidate summaries.

**Acquire the frozen experimental supports during the cohort itself.** After transient GRIB disposal, a later geometry change may require another download. Extract H14 at the union of proposed supports once. Freeze a modest menu, not a raw-grid convolution project.

Do not assume a centered isobaric gradient resolves the actual shallow front. NOAA cautions that isobaric output is smoothed relative to native-level structure. [R1] Within this fixed 58-field study, use those fields for broad air-mass context and emphasize surface contrasts for boundary location. New native-level variables are outside scope unless the cohort shows a specific unresolved mechanism that justifies reopening the field universe.

## 6. The complete 58-field decision matrix

The grouped tables below collectively form one matrix, keyed by unique field ID. Exact identity comes from the current registries [L4]. Each identity includes parameter, level, step type and interval. No source-ID count is a model-dimension requirement.

**Legend.** `I0`: `instant`, zero-duration snapshot at its valid time; H native cadence 60 minutes, Q native cadence 15 minutes. `A60`/`A15`: `accum`, preceding 60/15-minute interval ending at valid time. `M5`/`M15`: `avg`, preceding 5/15-minute interval ending at valid time. FH00 and missing intervals obey the current decoded contract and failure handling; no invented zero interval. `P`: `PROTECTED_BASELINE_OR_STATIC`; `C`: `RETAIN_CORE`; `X`: `RETAIN_CHALLENGER_PENDING_COHORT`. These are the full disposition names represented by the compact table codes. No current field receives a proven DROP or model-specific promotion.

`E` = 02–08 local; `M` = 08–11; `L` = 11–16; `all` = E/M/L, including future forecast paths available at issue time. `A` = AnEn candidate distance group; `μ` = GAM/GAMM location; `σ` = GAM/GAMM scale; `O` = ordinal-hazard predictor. Model-role entries are eligibility hypotheses, not evidence that the field must enter every model.

`H-cost`: 585,085 full-history logical requests; 10.48 hours at 15.503877879 requests/s; bytes `585,085 × b_f`. `Q-cost`: 2,173,943 requests; 38.95 hours; bytes `2,173,943 × b_f`. Here `b_f` is the field/season/lead-weighted mean retrieved source-message size, not extracted Parquet size. Field-specific network bytes and causal wall-time allocations are **not available in the inspected aggregate pilot report**; measure them in the cohort. `S-cost`: one static request in the present plan, negligible repeated cost. A vector pair costs twice its single-field class. Confidence describes the rationale; deletion risk describes what could be lost.

### 6.1 H01–H10: thermal and flow structure

| ID and exact identity | Physical quantity | KDEN failure mechanism | Issue | Temporal need | Spatial need | Derived uses | Roles | Redundancy candidates | Conditional exceptions | Evidence / test | Cost | Disposition | Confidence / deletion risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01 HGT, 700 mb, I0 | Geopotential height | Depth of thermal reservoir / coupling | all | State, tendency, revision | BI+3×3; G2 for broad pattern | Height above H14; H01−H06 thickness | A, μ, σ, O | H02/H07 thermal summaries | Height varies with synoptic state; lapse needs geometric depth | L2/L3; T1/T2 | H-cost | C | Medium; loses height reference and thickness capability |
| H02 TMP, 700 mb, I0 | Air temperature | Entrainment, warm cap, upper advection | all | State, path, revision | BI+3×3; broad G2 | T850−T700; θ700; gradient/advection with vector | A, μ, σ, O | H07; thickness | Deep mixing versus shallow cold intrusion | L2/R2/R3; T1/T2 | H-cost | C | Medium-high mechanism; cap/entrainment loss |
| H03 DPT, 700 mb, I0 | Dewpoint | Dry-air entrainment / evaporation potential | M/L; future at E | Hourly moisture path/revision | BI; G2-W challenger | T700−Td700; moisture contrast with surface | μ, σ, O; optional A | H08/H17/H39 | Dry layer aloft with moist surface, elevated moisture | L2; T2/T6 | H-cost | C | Medium; vertical moisture lost |
| H04 UGRD, 700 mb, I0 | U wind component | Upper flow supporting downslope / advection | all | Hourly vector path/revision | BI; G2 terrain-aware | Joint H04/H05 flow; 700-to-low-level shear | A, μ, σ, O | H09/H10 | Vertically decoupled flow; deep mixing | R4/R6; T2 | H-cost | C | Medium; assess jointly with H05 |
| H05 VGRD, 700 mb, I0 | V wind component | Meridional flow / directional shear | all | Same as H04 | Same as H04 | Joint H04/H05 vector | A, μ, σ, O | H09/H10 | Along-range changes invisible to U alone | R4/R6; T2 | H-cost | C | Medium; vector loss if removed alone |
| H06 HGT, 850 mb, I0 | Geopotential height | Layer thickness / geometric lapse context | all | Hourly state/revision | BI+3×3; audited G2 | H01−H06; lapse denominator | A, μ, σ, O | H07/H02; H01 relative height | Thickness may add stable all-weather/scale value despite D1 TMP win | L3/R2; T1 | H-cost | X | Strong prior for testing, unknown increment; high composite loss |
| H07 TMP, 850 mb, I0 | Low-level temperature | Air-mass thermal baseline and advection | all | Full hourly path and revisions | BI+3×3; audited G2 | θ850; contrast to T2; broad advection | A, μ, σ, O | H16/Q05; H02; thickness | Surface decoupling makes thermal context distinct | L3 direct KDEN; T1 | H-cost | C | Highest project-specific thermal prior; high deletion risk |
| H08 DPT, 850 mb, I0 | Low-level dewpoint | Moisture stratification / air-mass transition | all | State, tendency, revision | BI; audited G2 | Dewpoint depression; vertical moisture contrast | A, μ, σ, O | H17/H03/H39 | Moist layer aloft above shallow dry/cold surface | L2/R4; T2/T6 | H-cost | X | Medium; high-priority moisture challenger |
| H09 UGRD, 850 mb, I0 | U wind component | Low-level downslope/upslope flow | all | Hourly vector path/revision | BI; G2 with valid support | H09/H10 vector; 850−10-m shear; T850 advection | A, μ, σ, O | H18/H19; H04/H05 | Surface flow decoupled from air mass above | L2/L3/R4; T2 | H-cost | C | Medium-high; delete only joint vector |
| H10 VGRD, 850 mb, I0 | V wind component | Northerly surge / southerly convergence | all | Same as H09 | Same as H09 | Joint vector; along-range flow/advection | A, μ, σ, O | H18/H19; H04/H05 | Palmer Divide approach and turning flow | R5/R6; T2 | H-cost | C | Medium-high; U alone insufficient |

### 6.2 H11–H19: surface and near-surface state

| ID and exact identity | Physical quantity | KDEN failure mechanism | Issue | Temporal need | Spatial need | Derived uses | Roles | Redundancy candidates | Conditional exceptions | Evidence / test | Cost | Disposition | Confidence / deletion risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H11 GUST, surface, I0 | Gust potential diagnostic | Mixing or outflow transition | all | State/path maximum; not interval maximum | BI; G1/G2 test | Gust-minus-speed; gust revision | σ, μ, O; optional A | U/V, H24, shear; Q03 | Momentum available between sampled levels | L2/R1; T2/T4 | H-cost | X | Medium; profile information may be unique |
| H12 MSLMA, mean sea level, I0 | MAPS-reduced pressure | Lee trough / mesoscale circulation context | all | Pattern, hourly tendency/revision | 3×3 reference; G2 essential challenger | Broad pressure contrasts and pattern change | A, μ, σ, O | H13 tendency plus vectors | Unequal-terrain spatial pressure cannot use raw PRES alone | R4; T2/T8 | H-cost | C | Medium; must prove spatial value |
| H13 PRES, surface, I0 | Surface pressure | Front/pool tendency; thermodynamic state | all | Hourly state/tendency/revision | BI; G1/G2 with elevation controls | q2; θ2; same-point pressure change | A, μ, σ, O | H12; Q04 | Local pressure surge; humidity conversion | L2/R4; T2/T7 | H-cost | C | High composite need; no MSLP substitution |
| H14 HGT, surface, static I0 | Model terrain height | Station/grid and extraction lineage | all | Static once per verified grid | All frozen supports | Elevation contrasts; height references; geometry QC | Infrastructure | None | Coordinate-era change does not mean terrain changed | L1/L4 | S-cost | P | High; protect |
| H15 TMP, surface, I0 | Skin temperature | Surface storage / surface-air decoupling | E/M chiefly | Hourly path, contrasts, revision | BI; G1/surface sectors | Skin−T2; night-to-day transition | A, μ, σ, O | H21/H23; H34 | Snow, dry soil, weak turbulent coupling | L2/R9; T4/T5 | H-cost | C | Medium; surface-state information loss |
| H16 TMP, 2 m AGL, I0 | Hourly air temperature | Baseline trajectory and peak error | all | Full hourly trajectory | BI+NN, G1/G2 test | H baseline; Q−H; peak/revision geometry | A, μ, σ, O | Q05 scientifically comparable, not authorized replacement | Baseline/product parity | L1/L4; T0/T7 | H-cost | P | High; independent reacquisition required |
| H17 DPT, 2 m AGL, I0 | Near-surface moisture | Air-mass shift / evaporative potential | all | State/path/tendency/revision | BI; G1/G2 | q2/RH2; drying/moistening; moisture gradients | A, μ, σ, O | H08/H39; Q06 | Moist front before temperature response | R4; T2/T6/T7 | H-cost | C | Medium-high; important surface moisture context |
| H18 UGRD, 10 m AGL, I0 | Surface U | Surface penetration of flow / convergence | all | Vector path/tendency/revision | BI; G1/G2 strongly motivated | H18/H19 vector; wind shift, shear, convergence | A, μ, σ, O | 850 vector; Q07/Q08; gust | Shallow flow differing from flow aloft | R4/R5; T2/T7/T8 | H-cost | C | High mechanism; joint vector |
| H19 VGRD, 10 m AGL, I0 | Surface V | Cold surge / southerly boundary flow | all | Same as H18 | Same as H18 | Joint vector; along-range contrast | A, μ, σ, O | 850 vector; Q07/Q08 | Northerly/southerly change with weak U | R4/R5; T2/T7/T8 | H-cost | C | High mechanism; joint vector |

### 6.3 H20–H27: energy, boundary layer, and snow

| ID and exact identity | Physical quantity | KDEN failure mechanism | Issue | Temporal need | Spatial need | Derived uses | Roles | Redundancy candidates | Conditional exceptions | Evidence / test | Cost | Disposition | Confidence / deletion risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H20 MSTAV, 0 m underground, I0 | Moisture availability diagnostic | Antecedent wet/dry ground changes heating | E/M; all future | Hourly state/revision; no Q need proposed | BI; G1 land heterogeneity | Moisture-regime interactions | A, μ, σ, O | H21/H22 fraction; skin-air contrast | Weak pre-dawn flux or antecedent wetness | L2/R8; T4/T5 | H-cost | X | Medium; flux-only core may miss initial state |
| H21 SHTFL, surface, I0 | Sensible heat flux | Heating/coupling error | M/L; forecast at E | Hourly approximate energy/path | BI; G1/G2 | Heating integral; H21/H22 fraction | A, μ, σ, O | Radiation, H15, H24 | Similar radiation but different partition | L2/R3; T4 | H-cost | C | Medium-high; retain partition group |
| H22 LHTFL, surface, I0 | Latent heat flux | Evaporative partition of surface energy | M/L; forecast at E | Same temporal basis as H21 | BI; G1 | Evaporative fraction; latent integral | A, μ, σ, O | H20/H17; H21 | Wet ground, postrain, snow sublimation | L2; T4/T5 | H-cost | C | Medium; joint EF loss if removed |
| H23 GFLUX, surface, I0 | Ground heat flux | Storage/release and morning warming | E/M | Hourly signed path/integral | BI; G1 | Ground-energy integral; partition test | μ, σ, O | H15; radiation/flux subset | Nighttime storage and thaw/freeze | L2; T4/T5 | H-cost | X | Medium; not an exact energy residual |
| H24 HPBL, surface, I0 | Diagnosed PBL depth | Inversion erosion / mixing depth error | all | Hourly growth/max/revision | BI; G1/G2 | Mixing growth, height relative to 700 layer | A, μ, σ, O | H21, skin-air, shear | Similar surface flux but differing stratification | R3/R10; T4 | H-cost | C | Medium-high; coupling diagnostic loss |
| H25 WEASD, surface, I0 | Snow water equivalent | Melt reservoir / persistent ground cooling | all, cold season | Hourly state/change/revision | BI; G1/G2 snow contrast | Snow interaction; density with H27 | A, μ, σ, O | H26/H27 | Same fractional cover, different water/melt reservoir | R9; T5 | H-cost | C | Medium; snow-memory loss |
| H26 SNOWC, surface, I0 | Snow-covered fraction | Effective albedo / patchy surface | all, cold season | Hourly state/change/revision | BI; G1/G2 | Snow×absorbed SW; heterogeneity | A, μ, σ, O | H25; H33/H31 | Fractional cover differs at same SWE | R9; T5 | H-cost | C | Medium-high; albedo regime loss |
| H27 SNOD, surface, I0 | Snow depth | Insulation / density / evolving snowpack | all, cold season | Hourly state/change | BI; G1 | H25/H27 density proxy | μ, σ, O; optional A | H25/H26 | Fresh versus compacted snow at same SWE | L2/R9; T5 | H-cost | X | Medium; test, do not assume fixed density |

### 6.4 H28–H35: cloud and radiation

| ID and exact identity | Physical quantity | KDEN failure mechanism | Issue | Temporal need | Spatial need | Derived uses | Roles | Redundancy candidates | Conditional exceptions | Evidence / test | Cost | Disposition | Confidence / deletion risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H28 TCDC, boundary-layer cloud, I0 | Boundary-layer cloud fraction | Stratus/clearing and coupling error | all | Hourly exposure, clearing, revision | BI+9×9; G2 | Fraction/exposure/spread; cloud×solar | A, μ, σ, O | H29/H30; solar; ceiling | Terrain-relative cloud regime differs from pressure-layer cloud | R1/R10; T3 | H-cost | C | High diagnostic rationale; increment unmeasured |
| H29 LCDC, low cloud, I0 | Conventional low-cloud fraction | Low-cloud regime | all | Hourly path/exposure/revision | BI+9×9; terrain-aware G2 | Exposure/clearing comparator | A, μ, σ, O | H28, H31, H42 | Different layer definition can diverge from PBL cloud | R1; T3 | H-cost | X | Medium; weaker initial choice at elevated terrain |
| H30 TCDC, entire atmosphere, I0 | Total cloud fraction | Higher cloud/anvil shielding | M/L; future at E | Hourly exposure/revision | BI+9×9; G2 | Total-minus-low cloud context | μ, σ, O; optional A | H31/Q11/H28 | High-cloud timing not captured by low cloud | L2/R8; T3 | H-cost | X | Medium; higher-cloud residual regime possible |
| H31 DSWRF, surface, I0 | Downward solar snapshot | Heating amount and cloud displacement | Daylight; future at E | Hourly path, approximate integral/revision | BI+9×9; G2 | Net SW with H33; normalized solar; spread | A, μ, σ, O | Q11; cloud fields | Snapshot and interval energy differ | L2/L4/R8; T3/T7 | H-cost | C | High mechanism; retain for H composites |
| H32 DLWRF, surface, I0 | Downward longwave | Overnight cloud/air-mass radiative forcing | E/M; all | Hourly path and approximate integral | BI; G1 | Net LW with H34 | μ, σ, O; grouped A | H28/H17; skin T | Low-sun/overnight cloud forcing | L2/R10; T3/T4 | H-cost | C | Medium; pre-dawn coverage matters |
| H33 USWRF, surface, I0 | Reflected shortwave | Snow/albedo changes absorbed energy | Daylight | Hourly path with H31 | BI; G1 snow contrasts | H31−H33; albedo proxy with guards | A, μ, σ, O | H26 plus assumed albedo | Fractional snow, melt, land-type variation | L2/R9; T3/T5 | H-cost | C | Medium-high; do not assume constant albedo |
| H34 ULWRF, surface, I0 | Upward longwave | Surface radiative loss | all | Hourly path with H32 | BI; G1 | H32−H34; full net radiation | μ, σ, O; grouped A | H15-derived emission approximation | Emissivity/surface mosaic differences | L2; T3/T4 | H-cost | C | Medium; exact net-LW component |
| H35 CFNSF, surface, I0 | Cloud-forcing net solar diagnostic | Cloud attenuation beyond actual flux | Daylight; future at E | Hourly path/revision | BI+9×9; G2 | Cloud-forcing integral/spread | μ, σ, O; optional A | H31/Q11/H28/H30 | Cloud optical effects at matched actual radiation | L2/L4; T3 | H-cost | X | Medium; no exact derivation from solar geometry |

### 6.5 H36–H44: weather, moisture, aerosol, and convective potential

| ID and exact identity | Physical quantity | KDEN failure mechanism | Issue | Temporal need | Spatial need | Derived uses | Roles | Redundancy candidates | Conditional exceptions | Evidence / test | Cost | Disposition | Confidence / deletion risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H36 REFC, entire atmosphere, I0 | Composite reflectivity | Nearby modeled storms / heating interruption | M/L; future at E | Hourly onset/max/revision | BI+9×9, derive3; G2 corridors | Echo coverage, proximity, event before peak | σ, μ, O; A regime | H38/H43/H44; Q01 | Outflow/virga or echoes not raining at point | R5/R7; T6/T7 | H-cost | C | Medium-high; weather-location context |
| H37 PRATE, surface, I0 | Instantaneous precipitation rate | Intensity and evaporative cooling | M/L chiefly | Hourly state/onset | BI+9×9; G2 | Event/intensity/coverage | σ, μ, O | H38/H36; Q12/Q13 | Brief intense rain versus equal accumulated total | L2/R5; T6 | H-cost | X | Medium; amount does not determine instantaneous rate |
| H38 APCP, surface, A60 | Previous-hour precipitation amount | Rain/snow exposure and interrupted heating | all | Native nonoverlapping amounts | NN+9×9; G2 | Interval sum; wet exposure; recovery | σ, μ, O; A regime | H37; Q13 | Event between snapshots; exact amount needed | L2/L4; T6/T7 | H-cost | C | High semantic distinction; hourly onset uncertain |
| H39 PWAT, entire atmosphere, I0 | Column water vapor | Moisture depth / cloud and precipitation regime | all | Hourly state/path/revision | BI; G2 with terrain awareness | Moisture regime; cycle change | A, μ, σ, O | H17/H03/H08; CAPE/CIN | Deep moisture or elevated layers absent from two levels | L2; T2/T6 | H-cost | X | Medium; high-priority column challenger |
| H40 VIS, surface, I0 | Visibility diagnostic | Fog/obscuration and delayed heating | E/M chiefly | Hourly minimum/recovery/revision | BI+9×9; G2 | Log/threshold visibility, recovery | σ, μ, O | H28/H42/H17; H41 | Shallow fog and mixed obscuration | L2/R12; T3/T6 | H-cost | X | Medium-low increment; observation bridge removed |
| H41 AOTK, entire atmosphere, I0 | Smoke optical depth | Smoke-associated solar/coupling bias | Daylight; future at E | Hourly state/path/revision | BI+9×9; G2 source-only sector | Smoke×solar; optical-depth variability | σ, μ, O; A regime | H31/Q11; H40 | Elevated smoke differs from surface visibility/cloud | R1/R11; T3/T6 | H-cost | X | Medium; high-priority rare-regime risk |
| H42 HGT, cloud ceiling, I0 | Ceiling height | Persistent stratus / delayed clearing | E/M; future L | Hourly threshold/recovery/revision | BI+9×9 with sentinel handling; G2 | Valid AGL ceiling; low-ceiling fraction | σ, μ, O; A regime | H28/H29/H40; Q14 | Similar cloud cover but different low-cloud geometry | L2/R1; T3/T7 | H-cost | X | Medium; high-priority fog/stratus challenger |
| H43 CAPE, surface, I0 | Surface-parcel buoyant energy | Pre-convective interruption uncertainty | M/L; forecast at E | Hourly path/max/revision | BI+9×9; G2 | CAPE/CIN group; unstable coverage | σ, O; A regime; optional μ | H36/H38, moisture | Potential exists before modeled precipitation | R5/R7; T6 | H-cost | C | Medium-high; jointly test with H44 |
| H44 CIN, surface, I0 | Surface-parcel inhibition | Suppressed versus released convection | M/L; forecast at E | Hourly path and cap erosion | BI+9×9; G2 | CAPE/CIN group; inhibition exposure | σ, O; A regime; optional μ | H43; H36/H38 | High CAPE with strong cap | R5/R7; T6 | H-cost | C | Medium-high; sign convention required |

### 6.6 Q01–Q14: cadence decisions for every family

For every row below, the test comparator includes its H analogue's **state, hourly trajectory, spatial summary, and same-valid-time cycle revision**, plus protected Q05 and common deterministic context. Compare at identical issue times and legal cycle ages. An H snapshot interpolated to a quarter hour is an approximation, never reclassified as a native Q value.

| ID and exact identity | Physical quantity | KDEN failure mechanism | Issue | Temporal need / H comparison | Spatial need | Derived uses | Roles | Redundancy candidates | Conditional exceptions | Evidence / test | Cost | Disposition | Confidence / deletion risk |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 REFC, entire atmosphere, I0 | Q15 composite reflectivity | Storm arrival relative to Tmax | M/L; long-lead E test | Q onset/max versus H36; preserve unsmoothed snapshots | BI+9×9, derive3; G2 | Onset bracket, coverage, near-peak echo persistence | σ, μ, O; A regime | H36+H38; Q13; Q05 | Subhourly transient storm/outflow | R5/R7; T6/T7 | Q-cost | X | High-priority Q test; timing loss possible |
| Q02 VIS, surface, I0 | Q15 visibility | Rapid fog clearing / obscuration | E/M | Recovery/minimum versus H40 hourly | BI+9×9; G2 | Low-visibility duration/recovery | σ, μ, O | H40+H28/H42; Q14 | Fog breaks within an hour near heating onset | L2/R12; T3/T7 | Q-cost | X | Lower priority; lacks former observation matching role |
| Q03 GUST, surface, I0 | Q15 gust diagnostic | Mixing burst / outflow passage | all | Snapshot-path max versus H11; not true interval max | BI; G1/G2 | Gust minus vector speed; pulse | σ, μ, O | H11/shear/HPBL; Q07/Q08 | Brief gust-potential transition uncaptured by hourly fields | L2/R1; T2/T7 | Q-cost | X | Lower priority; diagnostic maximum is not resolved turbulence |
| Q04 PRES, surface, I0 | Q15 pressure | Sharp frontal/mesohigh jump | all | Jump/tendency versus H13 hourly | BI; G1/G2 elevation-controlled | Pressure change concurrent with wind/T | σ, μ, O; optional A | H13/H12; Q05/Q07/Q08 | Short mesohigh or surge; early-lead model adjustment | L2/R4; T2/T7 | Q-cost | X | Medium priority; high cadence can capture noise too |
| Q05 TMP, 2 m AGL, I0 | Q15 temperature | Peak timing / rapid cooling / recovery | all | Full native Q path; H16 independent comparator | BI+NN; G1/G2 test | Q15 baseline, alternate peaks, Q−H, revisions | A, μ, σ, O | H16 not an authorized substitute | Baseline reconstruction and intrahour peak | L1/L4; T0/T7 | Q-cost | P | High; protected independent source |
| Q06 DPT, 2 m AGL, I0 | Q15 dewpoint | Rapid drying/moistening boundary | all | Transition path versus H17 hourly | BI; G1/G2 | Moisture jump with wind/T; humidity at matched support | σ, μ, O; optional A | H17/H08/H03; Q05/vector | Moisture leads temperature across boundary | R4; T2/T7 | Q-cost | X | Medium-high priority; pair conditional event test |
| Q07 UGRD, 10 m AGL, I0 | Q15 U snapshot | Rapid flow transition | all | Q vector change versus H18/H19; compare Q09/Q10 | BI; G1/G2 | Q07/Q08 vector, transition timing | A, μ, σ, O | Hourly vector/path/revision; Q09/Q10 | Boundary passage between hourly endpoints | R4/R5; T2/T7 | Q-cost | X | High-priority vector challenger |
| Q08 VGRD, 10 m AGL, I0 | Q15 V snapshot | Rapid northerly/southerly shift | all | Same as Q07 | Same as Q07 | Joint snapshot vector | A, μ, σ, O | Same as Q07 | Directional transition with little U change | R4/R5; T2/T7 | Q-cost | X | High-priority; joint selection only |
| Q09 UGRD, 10 m AGL, M5 | Five-minute mean U | Short-lived flow versus persistent flow | all | Preceding 5-min mean sampled every 15 min; compare snapshot pair | BI; G1/G2 | Q09/Q10 vector; mean-minus-snapshot | A, σ, μ, O | Q07/Q08; H18/H19 | Averaging may suppress phase noise or retain persistence | L2/L4; T7 | Q-cost | X | First deletion candidate; not deterministic duplicate |
| Q10 VGRD, 10 m AGL, M5 | Five-minute mean V | Same vector-persistence question | all | Same as Q09; intervals leave gaps | Same as Q09 | Joint mean vector | A, σ, μ, O | Same as Q09 | Crosswind mean differs from end snapshot | L2/L4; T7 | Q-cost | X | First deletion candidate with Q09; never quarter-hour mean |
| Q11 DSWRF, surface, M15 | Quarter-hour mean solar flux | Integrated heating / cloud interruption | Daylight; forecast at E | Exact complete-interval energy versus H31 quadrature | BI+9×9; G2 | Sum(mean×900 s), clearing ramp, energy revision | A, μ, σ, O | H31/H28/H35 path/revisions | Clouds change between hourly snapshots | L2/L4/R8; T3/T7 | Q-cost | C | Strong semantic novelty; predictive increment unproven |
| Q12 PRATE, surface, I0 | Q15 precipitation rate | Brief intense cooling event | M/L; future at E | Rate/onset versus H37; compare Q13 amount | BI+9×9; G2 | Rate threshold, peak rate, onset bracket | σ, μ, O | H37/H38; Q13+Q01 | Same amount but different peak intensity | L2/R5; T6/T7 | Q-cost | X | Medium priority after Q13; snapshots miss some events |
| Q13 APCP, surface, A15 | Quarter-hour precipitation amount | Timing and exposure of wet cooling | all | Native interval amount versus H38; no redifferencing | NN+9×9; G2 | Amount before/after peak; wet-interval count | σ, μ, O; A regime | H38/H36; Q12/Q01 | Brief event hidden in hourly total; no exact onset within interval | L2/L4; T6/T7 | Q-cost | X | High-priority Q challenger; exact amount information |
| Q14 HGT, cloud ceiling, I0 | Q15 ceiling height | Rapid low-cloud clearing | E/M; future at E | Threshold crossing versus H42 hourly | BI+9×9; no-cloud handling; G2 | Ceiling recovery time / low-ceiling fraction | σ, μ, O | H42/H28; Q11/Q02 | Ceiling changes before radiation response | L2/R1; T3/T7 | Q-cost | X | Medium priority; high fog-regime deletion risk |

The table does not call H or Q cheap enough to escape scrutiny. For example, H06/H08/H39/H41/H42 together cost about 52.4 request-scaled hours; Q07/Q08 together cost about 77.9 hours. Their relative priority must depend on conditional probability skill and actual retrieved bytes.

## 7. Owner-run selection cohort

### 7.1 A bounded design with an explicit power limitation

Recommend **600 target days with all 58 fields**, all retained cycles, complete same-cycle native paths, existing supports, and the predeclared experimental spatial supports. The purpose is feature/cadence/geometry selection, not another sparse engineering pilot.

| Partition | Proposed sample | Role |
|---|---|---|
| Development, 2021–2025 | 8 dates uniformly sampled without replacement in every calendar month: 96/year, 480 total | Seasonal and multi-year selection, tuning, learning curves, paired ablations. |
| Sealed temporal evaluation, 2026-01-01–2026-09-11 | 14 dates/month January–August plus 8 dates September 1–11: 120 total | One final test after subset, model-selection rules, and tolerances are frozen. |
| Optional development-only challenger supplement | Up to 48 additional 2021–2025 dates, selected by predeclared source-only regime coverage deficits | Resolve specific rare-regime uncertainties; separately authorized and separately weighted. |

Use a reproducible seed and publish the date-selection rule before inspecting labels or residuals. For population scores, account for differing calendar-month inclusion probabilities; the September 2026 fraction is particularly different. Uniform-date sampling is a starting design, not a reason to omit known archive/coordinate strata.

The coordinate registry changes from `KDEN_COORD_20040105` through 2021-11-21 to `KDEN_COORD_20211122` on 2021-11-22. It describes an effective metadata update; physical relocation is unproven. [L6] Ensure both eras and dates on either side of this boundary are covered. Within the 480-day development budget, reserve/reallocate dates for the boundary, both DST transition types, and any already documented archive-semantic strata. Record the resulting sampling probabilities or report those deterministic audit cases separately from prevalence-weighted headline scores. Do not count audit duplicates twice.

Every target day includes its full c23/c00–c14 schedule, so ordinary and extended UTC cycle classes and revisions are represented without selecting isolated leads. Include both spring and fall scheduling cases; all retained cycles still start at FH00. Source paths remain complete even if some downstream model uses only a few summaries.

The proposed 2026 holdout has only January through early September. It is not a full-year final test, and cannot independently validate October–December transfer. Use rolling development years for late-fall evidence and state this limitation. Before sealing it, confirm that its errors have not already informed prior project decisions. If it has been used, label it reused evaluation; identify genuinely untouched dates or arrange a separately approved later prospective evaluation. Do not silently call a contaminated interval untouched or expand the frozen acquisition period.

**600 days is a feasible selection budget, not a guarantee of statistical equivalence.** There are 2,080 target dates in full history, not millions of independent issue rows. Repeated issues share one outcome; adjacent weather days also share synoptic episodes. Initial rolling training samples are small for a rich AnEn or GAM, so use compact grouped representations and report sample-size learning curves.

For a paired daily loss difference with standard deviation `s_delta`, an approximate one-sided noninferiority sample-size planning relation is:

```text
n_eff ≈ [(z_(1-alpha) + z_power) × s_delta / margin]^2
```

For illustration only, alpha 0.05, power 0.80, `s_delta = 0.30°F`, and a discrete-CRPS margin of 0.05°F give about **223 independent paired days**. These are assumed values, not measured KDEN variance. Estimate `s_delta` from development predictions and adjust for episode dependence. A 120-day final sample may not resolve a narrow margin. Inconclusive results require more evidence or a conservative retention decision; they do not prove redundancy.

### 7.2 Acquisition stages and decision gates

1. **Design freeze:** cohort dates/rules, supports, source semantics, model ladders, folds, metrics, and acceptable loss tolerances. Labels remain separate. Owner approves this study acquisition independently of this report.
2. **Initial 240 development days:** four dates per month across 2021–2025, a nested subset of the final monthly sample except documented stratum reservations. Acquire the full universe. Check bytes, timing, missingness, feature ranges, and ability to represent the proposed regimes. Its first-order source time is 4.79 days. Use early chronological folds only for exploratory power/feasibility; do not issue final deletion claims.
3. **Complete 480 development days:** acquire the remaining full-universe development data. Freeze any revised power plan before looking at final evaluation. Full-universe benchmark and reduced candidates use identical date/issue support.
4. **Acquire/evaluate 120 sealed 2026 days:** source acquisition can occur earlier if convenient, but labels, error summaries, and model comparisons remain sealed. The complete 600-day cost is approximately 11.97 days, not 4.79 plus 11.97.
5. **Resolve only material uncertainty:** if a specific challenger remains important but underpowered, add up to 48 source-screened development days or retain it conservatively. An inconclusive opened holdout is not a license for repeated selection against that holdout. Any new choice needs fresh evaluation evidence.

The original Step 04 report has 1,849 requests, 1,809 successfully decoded rows, and 40 quarantined rows. It is valid engineering evidence but neither a complete 28-day science cohort nor proof that every selected value is usable. Establish the reason and field/era distribution of quarantines before interpreting missingness as meteorology. Preserve the current quarantine contract. [L5]

### 7.3 Regime coverage without outcome-based selection

Use legal source-only screening from a fixed early cycle/issue and fixed future summaries, or from separately declared issue-specific source classifications. Do not classify dates using their final observed temperature errors, hindsight radar, realized sunshine, or markets.

Proposed screening dimensions, frozen before label access:

- Snow presence and substantial/patchy snow: H25/H26 with H33/H31 daylight albedo proxy.
- Stable or decoupled state: low H24, surface-versus-air-mass potential-temperature contrast, weak surface flow; these are proxies, not verified inversions.
- Downslope-like or upslope-like state: jointly use 700/850/10-m vectors, moisture change, and directional spatial contrast. Never use U sign alone.
- Front/rapid-transition state: forecast wind change together with pressure, temperature, or moisture tendency; distinguish lead-zero/early-lead adjustment from sustained transitions.
- Cloud clearing or persistent suppression: H28/H31, with challenger H42 for diagnostic evaluation.
- Convective threat versus actual modeled interruption: H43/H44 separately from H36/H38.
- Smoke forecast: H41 stratification; separately test whether radiation captures its predictive contribution.
- Large cycle revision and BI–NN/spatial disagreement.

For continuous regime thresholds, use physical definitions where available and training-only quantiles otherwise. Publish numeric thresholds with units before the relevant validation labels are opened. Quantile cutoffs must not be learned from the final holdout. A source-only label can miss a real-world event that HRRR misses; describe the stratum as **forecast snow**, **forecast smoke**, etc., rather than observed truth.

Aim for at least 30 development target days and about 10 distinct episodes in each important rare-regime comparison. These are minimum descriptive targets, not a promise of precision. If there are fewer, report counts and uncertainty and keep the relevant challenger unresolved. Overlapping regimes remain multi-label; do not force a snowy frontal day into only one category.

Enrichment is for diagnosing incremental effects, not estimating climatological prevalence. Use known inclusion weights for population scoring, or report the enrichment separately. A balanced sunny/snow/convective challenge set must not be presented as the naturally occurring all-day mix.

## 8. Model-specific construction and nested selection

### 8.1 Common baselines and full-universe reference

Start each model ladder with season/solar geometry, legal issue time, selected-cycle age, hourly/Q15 temperature-path summaries, and availability indicators. Include current forecast T2, elapsed-window forecast maximum, remaining-window maximum, peak lead, plateau duration, separated alternative peaks, H/Q disagreement, BI/NN difference, and same-valid-time revisions. No observed run maximum or MADIS floor enters the HRRR-only panel.

The **full-universe benchmark** exposes all candidate source groups to training-only selection with a comparable complexity budget. It does not force every raw trajectory coordinate into each fit. A deliberately overfit 58-field benchmark is not a fair target for a compact subset to beat. Benchmark and reduced sets each receive the same tuning effort, feature-operator menu, folds, issue grid, and missingness rules.

All families must output probabilities for the same authoritative integer outcome. For a continuous location-scale model, one candidate mapping is `P(Y=k)=F(k+0.5)-F(k-0.5)` with compatible training likelihood and explicit tails; it is a statistical discretization model, not a substitute for the actual truth-source convention. AnEn likewise needs a declared outcome/residual-to-integer mapping. Use the same target lineage and scoring support in every comparison.

Compare against both the tuned full-universe benchmark and the best validated candidate **within each competitive family**. If a reduced model is better because the full feature set harms estimation, record that result instead of presuming information count must improve forecasts.

### 8.2 AnEn

The original AnEn work uses historical forecast similarity to select corresponding verifying observations and demonstrates flow-dependent forecast uncertainty; it is a methodological precedent, not a proof that a particular KDEN distance vector is optimal. [R13]

An initial KDEN distance representation should use roughly 8–12 **physical groups**, not every raw field/lead. Suggested groups are temperature level/path shape, T850 thermal state, upper thermal/moisture contrast, surface/850 flow, radiation exposure, mixing/energy partition, snow, convective threat, and cycle/spatial disagreement. Some groups have more than one coordinate; the number of source messages is not the distance dimension.

Standardize within training folds. Weight groups so duplicated radiation or thermal coordinates do not acquire weight merely by their count. Tune neighbor count, group weights, time-window alignment, season/issue restrictions, and any whitening/PCA inside inner chronological splits. Wind U/V is a joint group. Prefer physically defined summaries before generic dimension reduction.

Use one analog contribution per historical target day for a query; do not allow many issue rows from the same day to masquerade as independent ensemble members. Compare direct outcome analogs against residual analogs relative to each day's matching baseline. Residual analogs may handle a changing temperature level better, but their tails still require training-only smoothing/calibration and a check for inadequate analog support.

A small selection archive can unfairly reject useful AnEn predictors because it lacks neighbors. Report score versus training-day count, neighbor effective size, and seasonal/rare-regime coverage. Do not delete an AnEn-only field because a high-dimensional distance metric was poorly designed.

### 8.3 Distributional GAM/GAMM

Use a location-scale ladder with shrinkage and a controlled interaction menu. Initial location terms: baseline geometry, season/solar position, T850, thermal contrast, flow, absorbed solar, net longwave, sensible/latent partition, PBL evolution, snow, and event-before-peak context. Initial scale terms: H/Q disagreement, revision magnitude, spatial spread, forecast age, near-peak ambiguity, cloud/convective regime, and coupling/snow interactions.

Test source removal separately for location and scale. A field that improves dispersion or calibration without lowering MAE can survive. Inspect concurvity, effective degrees of freedom, and stability of functional shape across years; do not promote by in-sample p-values. Partial pooling over issue time and season is preferable to many tiny independent fits at each quarter-hour.

Use GAMM effects only for justified grouping. An unobserved new-day random effect must be marginalized or otherwise handled as a new group; it cannot be estimated using the day's final Tmax or later issue labels during prediction. Repeated issues increase coverage of the forecast process, not the count of independent daily outcomes.

### 8.4 Ordinal hazard / ordered distribution

Model an ordered whole-degree target with shared, regularized covariate effects across thresholds and limited issue interactions. One coherent construction uses continuation probabilities `r_k = P(Y >= k+1 | Y >= k, X)`. Multiplying successive continuation probabilities yields survival probabilities and differencing yields a nonnegative PMF. Specify how the tails close; do not fit unrelated threshold probabilities that can cross.

Use temperature baseline/peak geometry first, then flow, cloud/energy, coupling/snow, convection, and uncertainty groups. Evaluate tail pooling and threshold-specific calibration. Reject a field whose apparent contribution depends on unstable coefficients for a handful of integer outcomes.

Temperature thresholds are outcome thresholds, not clock-time hazards. Separate PMFs at successive issue times need not become monotonically narrower as new forecasts arrive. Each issue must be legal and internally coherent; learning about a potential front can properly widen the distribution.

### 8.5 Shared union and other model families

For each family, select the smallest source set within the predeclared tolerance of its best validated formulation. A field gains `RETAIN_MODEL_SPECIFIC` only if its contribution is repeatable in a **competitive** model under the same folds and metrics. A model is competitive when its probability quality/calibration is within the agreed band of the best available family or offers a predeclared, demonstrated complementary benefit. Mere flexibility is insufficient.

Take the union of those supported subsets plus H14/H16/Q05 and required composite dependencies. Refit/revalidate compact model views on that union; do not force each model to use the entire union. A bounded distributional-tree or other challenger can be added if it is actually tested under the same information boundary. Do not retain fields for hypothetical future models with no demonstrated competitive result.

## 9. Required ablations and ordering

All comparisons below are paired on target day and issue time. Refit after removal and retune within the training fold. In a composite ablation, remove all dependent derived columns; never leave a precomputed feature containing a removed source. Distinguish ablation of an operator from ablation of the source that may support other operators.

| Test | Required comparison | Mechanistic question and promotion requirement |
|---|---|---|
| T0: baseline/cadence reference | H-only; H+Q05; all H+Q05+Q11; full H/Q | How much does protected temperature cadence explain before paying for other Q fields? H-only is diagnostic only. |
| T1: thermal compression | T850 core versus T850+T700; add thickness H01/H06; full thermal group | Does thickness or another thermal representation improve conditional probabilities over the 2-m baseline and T850? Preserve H07 as the initial prior, not an untestable dogma. |
| T2: flow/moisture/pressure | Surface vector only; add 850 and 700 vectors; add H08/H39; H13 tendency versus H12 spatial pattern; optional H11 | Which vertical/spatial contrasts distinguish shallow intrusions, downslope penetration, and changing air masses? Respect vector pairs. |
| T3: cloud/radiation | H28 versus H29; add H30, H35, H42/H40; incoming SW versus full SW/LW composites; Q11 | Do cloud geometry or forcing add beyond actual radiation? Does exact interval solar information help particularly on cloud-transition days? |
| T4: surface coupling | H24 only versus H21/H22, combined; add H15/H20/H23 | Which parts distinguish energy supply, partition, and mixing depth? Remove the net-radiation operator if its components are removed. |
| T5: snow/ground | H25 alone; H26 alone; H25/H26; add H27; cross with H33 and surface coupling | Does mass, area, or depth add unique snow-regime skill? Never presume fixed density or albedo. |
| T6: convection/wet/smoke | H43/H44; H36; H38; add H37/H39; H41 conditional on solar/cloud; H40 conditional on fog/ceiling | Potential versus occurrence, wet cooling versus nearby echoes, smoke beyond radiation; evaluate scale and tails. |
| T7: every Q family | Q01/H36, Q02/H40, Q03/H11, Q04/H13, Q05/H16, Q06/H17, Q07+Q08/H18+H19, Q09+Q10/H18+H19 and Q07+Q08, Q11/H31, Q12/H37, Q13/H38, Q14/H42 | Each H comparator has state, trajectory, spatial and revision summaries. Mean/snapshot/amount semantics stay distinct. Also compare Q01+Q13+Q07/Q08 jointly and Q06+Q04 added to that transition group. |
| T8: geometry | Point-only; current centered neighborhoods; G1; frozen G2/G3 | Can one retained field with better support replace several correlated local diagnostics? Include matched complexity controls. |
| T9: information evolution | State only; add same-cycle path summaries; add legal cycle revisions | Does each temporal operator improve score, and at which issue times/leads? Include revision-missing cases. |
| T10: model union | Independently selected AnEn, GAM/GAMM, ordinal subsets; shared union; competitive additional family if warranted | Does every acquired source support a stable useful feature in at least one competitive model? |

T7 is not only “full versus Q removed one at a time.” Correlated Q groups can mask each other's value. Use both backward group removal and forward group addition to C32, with predeclared joint transition candidates. Compare Q09/Q10 versus Q07/Q08, both, and neither; five-minute means sampled every 15 minutes do not tile the hour.

Compare Q13-only versus Q12-only versus both, conditional on H38/H36. Compare Q11 versus Q14/Q02 in cloud-clearing cases rather than assuming all are required. Assess native temporal added value separately from better Q spatial extraction by holding spatial operators matched in the cadence experiment.

After physical triage, prioritize **Q09/Q10 and Q02/Q03** for early removal tests; they carried prominent observation-matching or rapidly sampled diagnostic rationales. Among H fields, prioritize **H29/H30/H35, H11/H20/H23/H27/H37/H40** for conditional redundancy tests. **H06/H08/H39/H41/H42 and Q01/Q04/Q06/Q07/Q08/Q12/Q13/Q14** merit explicit regime-focused tests before omission. These priorities do not change their pending-cohort dispositions.

## 10. Validation and the cost–skill decision rule

### 10.1 Chronological validation

Outer development evaluations: train on sampled 2021–2022 and validate 2023; train 2021–2023 and validate 2024; train 2021–2024 and validate 2025. Inner splits use earlier versus later months/years strictly within each outer training period. Every issue row from a target day stays in the same fold. Use a declared short boundary embargo, initially two target days, if overlapping source objects or synoptic persistence would otherwise cross a split; assess episode dependence with sensitivity to longer blocks.

Those principal outer folds evaluate the newer coordinate era. Add an explicitly limited earlier-era diagnostic: train on the sampled January–June 2021 dates and evaluate July–October 2021, using a very small baseline/physical-group model with choices fixed in advance. This gives chronological evidence for the older era but only about 48 training and 32 evaluation days before reservations or exclusions. It cannot certify rare-regime equivalence for the full model ladder. Report geometric parity and older-era predictive evidence separately; do not pool in-sample 2021 fits with later out-of-sample scores or claim that the current history supports equally strong validation of both eras.

Inside training only, fit all normalization, missing-value handling, PCA/whitening, feature selection, thresholds learned from data, GAM penalties, analog weights and neighbor counts, distributional shape choices, and recalibration. Generate features from legal source vintages before joining labels. In backtests, training labels must be available before the prediction period being simulated.

Use identical evaluation rows for the main paired comparisons, with a common documented completeness criterion. Separately score operational coverage/fallback behavior. If a dropped field was frequently missing, reduced-universe availability can be a benefit, but must not be confused with better meteorological skill on an easier complete-case subset.

### 10.2 Proper probability scores and diagnostics

For integer Fahrenheit outcomes, use the unnormalized discrete CRPS/RPS:

```text
DS(P,y) = sum over integer k of [F(k) - 1(y <= k)]^2 × 1°F
```

The unit spacing makes this the CRPS of a distribution supported on the integer grid. Document the evaluated support and tail treatment; do not compare it numerically with an RPS normalized by a changing number of categories.

Primary reports:

- Day-weighted discrete CRPS, separately for 02–08, 08–11, 11–14, and 14–16 local; also show all quarter-hour issues.
- Negative log probability of the realized whole-degree outcome. Report exact zero-mass failures. For finite numerical summaries, publish a fixed probability floor such as 1e-6 and its activation count; clipping must not hide support failures.
- Brier score/reliability for predeclared whole-degree exceedances and temperature bands, with no market-price input. Pool sparse thresholds by training-defined climatological quantile region and show sample counts.
- Calibration and coverage of 50%, 80%, and 90% intervals; calibrated interval widths, randomized PIT appropriate to discrete outcomes, bias and conditional sharpness.
- Lower/upper tails, forecast snow/stratus/front/downslope/convection/smoke regimes, seasons, years, both coordinate eras, and source-completeness strata.
- MAE, RMSE, and bias as secondary diagnostics.

For an initial **useful concentration** diagnostic, propose the first legal issue at which a calibrated 80% interval is at most 4°F wide, together with its subsequent persistence. Count days never reaching that criterion; report whether the claimed coverage holds across those selected cases. Freeze the width/coverage criterion before scoring. This is a meteorological concentration criterion, not evidence of profitable trades.

Average within a target day first so dense issue grids do not dominate. For uncertainty, use paired target-day differences and an episode/block bootstrap (initially seven calendar days with a three-/fourteen-day sensitivity), respecting the sampling design and chronological folds. Report day and episode counts. Do not bootstrap individual issue rows as independent weather events. Proper-score principles support evaluating the whole distribution rather than optimizing point error alone. [R14]

### 10.3 Proposed noninferiority tolerances for owner approval

These are **proposed study settings**, not values established by the literature or already authorized for final acceptance:

| Criterion | Proposed acceptance gate for a reduced set |
|---|---|
| Primary discrete CRPS | Upper one-sided 95% confidence bound on reduced-minus-reference loss no greater than the smaller of 0.05°F and 2% of reference score; assess aggregate and each main issue band. |
| Log score | Mean degradation no greater than 0.02 nats and no increase in unregularized zero-mass failure rate; report paired uncertainty. |
| Calibration | No material new threshold/reliability defect; nominal interval coverage deterioration greater than 3 percentage points triggers review with uncertainty and counts. |
| Regimes/tails | No stable degradation exceeding 5% in a sufficiently sampled critical regime; low-powered cases remain unresolved, not passed. |
| Early concentration | No stable delay exceeding one 15-minute issue in reaching the predeclared concentration criterion, conditional on maintained calibration. |
| Stability | Gains/losses cannot depend entirely on one year, one episode, or one issue checkpoint. |

The owner should approve or revise these tolerances before final evaluation is examined, as required by the brief. Use simultaneous uncertainty across predeclared primary issue bands or an explicitly multiplicity-adjusted procedure; a nominal 95% interval on many opportunistically selected comparisons is insufficient. Secondary exploratory splits should be labeled exploratory.

If the preferred margin is much smaller than the paired uncertainty, reassess the cohort size using development data. Do not turn “not significant” into “equivalent.” The same caution applies to the 5% regime threshold: a ten-day smoke sample cannot certify a safe deletion merely because its interval is wide.

### 10.4 Constructing the actual Pareto frontier

For set S, preserve a vector of costs rather than only a field count:

```text
cost(S) = (logical messages, accepted source bytes, HTTP range groups,
           measured wall time, extracted output bytes)
```

For each field, measure GRIB byte length, cadence, product, forecast lead, month/year, source-object grouping, retries, and extraction shape. Byte estimates can be summed from message lengths; wall times require remeasurement because concurrency and coalescence are nonadditive. Removing a middle message can break an adjacent range group and partly offset its savings. Do not use per-field Parquet compression as a proxy for network savings.

Plot/report the nondominated cost-versus-score sets, including C32, C36, C41, the full set, and genuinely competitive model-specific unions. The current document contains **cost scenarios, not an empirical Pareto frontier**: no out-of-sample score exists for these candidates yet.

Choose the lowest-cost shared union that meets the agreed tolerance for every competitive family and the calibrated-tail/regime gates. If adding Q07/Q08 costs 77.9 projected hours but provides stable early frontal-tail improvement, retain it. If adding H41 costs 10.5 hours and improves smoke-regime scale in a competitive model, it may be preferable to several additional Q diagnostics. These are decision examples, not observed benefits.

## 11. Acquisition consequences and accounting

With `h` dynamic hourly fields, `q` subhourly fields, and the present single static H14 request:

```text
N(h,q) = 585,085 h + 2,173,943 q + 1
hours_request_scaled = N(h,q) / 15.503877879428323 / 3600
```

The 43 dynamic H fields give 25,158,655 requests, plus one static request = 25,158,656; 14 Q fields give 30,435,202. One Q field has about 3.72 times the logical-message burden of one H field. These are the sealed-plan counts supplied in the brief and reconciled to the pilot projection. [L1/L5]

| Universe | Exact definition | Dynamic H / Q / static | Logical requests | Hours | Days | Request reduction |
|---|---|---:|---:|---:|---:|---:|
| Full F58 | H01–H44 + Q01–Q14 | 43 / 14 / 1 | 55,593,858 | 996.06 | 41.50 | 0% |
| H-only diagnostic | All H, no Q; not deployment-eligible | 43 / 0 / 1 | 25,158,656 | 450.76 | 18.78 | 54.75% |
| All H + Q05 | Temperature-cadence control | 43 / 1 / 1 | 27,332,599 | 489.71 | 20.40 | 50.84% |
| All H + Q05/Q11 | H-rich solar candidate | 43 / 2 / 1 | 29,506,542 | 528.66 | 22.03 | 46.92% |
| C31 | C32 minus Q11; semantic-loss test | 29 / 1 / 1 | 19,141,409 | 342.95 | 14.29 | 65.57% |
| **C32** | Core in section 1 | **29 / 2 / 1** | **21,315,352** | **381.90** | **15.91** | **61.66%** |
| C36 | C32 + Q01/Q07/Q08/Q13 | 29 / 6 / 1 | 30,011,124 | 537.70 | 22.40 | 46.02% |
| C41 | C36 + H06/H08/H39/H41/H42 | 34 / 6 / 1 | 32,936,549 | 590.11 | 24.59 | 40.76% |

C31 tests whether Q11 earns its cost; it is not the preferred prior because it discards native solar averages. C36 deliberately tests a costly coherent transition package, then removes unnecessary components after joint/conditional comparisons. C41 protects several uncertain H mechanisms during comparison; it is not a substitute for measuring each increment.

The illustrative 600-day full-universe cohort is 600/2,080 of history, approximately **16.04 million logical requests and 287.32 hours / 11.97 days**. Exact counts must be generated from the cohort's actual cycles, DST, horizons, source keys, and deduplication, not from day fractions. The optional 48-day full-universe supplement adds approximately 0.96 days before reuse effects.

If cohort data can be reused under the successor lineage, the approximate end-to-end source time is:

```text
full-universe cohort cost + reduced-universe cost on the remaining days
≈ 11.97 days + candidate_days × (1 - 600/2,080)
```

| Subsequent universe | Cohort + remaining acquisition, approximate |
|---|---:|
| C31 | 22.14 days |
| C32 | 23.29 days |
| All H + Q05/Q11 | 27.65 days |
| C36 | 27.91 days |
| C41 | 29.47 days |

These exclude model-fitting time, the bounded confirmation pilot, extra geometry output work, and network variability. If a version transition requires reacquiring overlapping retained data, the simple reusable-cohort formula is too optimistic. For example, adding the full C32 projection to the cohort gives approximately 27.88 days. Resolve reuse by exact source/message/spatial identity with explicit successor lineage, without editing old manifests or pretending their plan hashes match.

Do not scale the 88.7-GB projected extracted output by message count and call it a network estimate. The inspected pilot reports aggregate network bytes and field-specific extracted storage, but do not expose a reliable field-by-field network-time model. Report candidate source bytes only after the field ledger is measured. The current first-order runtime scenarios are useful for design and deliberately limited in precision.

## 12. Open questions and exact evidence needed

| Unresolved question | Evidence that resolves it |
|---|---|
| Does thickness merit H06 beyond H07/T2 and H02/H01 context? | T1 paired out-of-sample CRPS/log/calibration, including early issues, snow, and fronts; source removal retires all thickness/lapse features. |
| Which vertical moisture representation survives? | T2 H03/H08/H17/H39 group comparisons, especially entrainment, elevated moisture, and fronts; conditional scale as well as location. |
| Does H12's spatial context earn a core slot? | G0 versus G2 pressure-pattern tests conditional on H13 tendencies and wind vectors, with terrain effects controlled. |
| Can surface-coupling sources be reduced further? | T4 joint H21/H22/H24 comparisons, then H15/H20/H23; paired probabilities and pre-dawn behavior, not annual correlations. |
| Is H28 sufficient for cloud regime? | T3 H28/H29/H30/H35/H42 comparisons with correct layer/sentinel semantics and common solar paths. |
| Does Q11's semantic novelty improve prediction? | T7 exact complete-interval energy versus H31 quadrature, on both all days and cloud-transition days, controlling for solar geometry and cycle age. |
| Which rapid Q package is necessary? | Factorial/joint T7 tests of echo, amount, vector, pressure and moisture timing conditional on Q05 and H geometry; no inference from a single redundant drop-out test. |
| Is Q09/Q10 useful without an observation bridge? | Snapshot-versus-mean vector comparison at matched issue/cycle, including mean-minus-snapshot persistence; assess pair jointly. |
| Are snow depth or smoke fields safely omitted? | Adequate independent snow/smoke forecast episodes; T5 snow group and T6 H41 conditional tests; otherwise retain challengers or extend cohort. |
| Does proposed geography see the relevant structure? | Fixed G0/G1/G2 comparisons with controlled feature dimension, common folds, both coordinate eras and verified wind/gradient orientation. |
| Are 850-mb data physically interpretable at new displaced sites? | Per-node surface-pressure and level-height provenance using the actual extracted messages; independent of the positive KDEN D1 predictive result. No blanket KDEN exclusion. |
| How much are bytes and wall time actually reduced? | Field/stratum message-length ledger and bounded successor pilot with the selected support/menu; include effects of broken/coalesced ranges. |
| Is the planned final test untouched and sufficiently powered? | Project disclosure audit before scoring; development-based paired-loss variance and episode-adjusted sample-size estimate; extra evaluation if inconclusive. |
| Can cohort sources be reused under new plan hashes? | Explicit identity-preserving successor import/reuse design, validated without altering the old registry, source manifests, or PASS record. |

The highest-priority additional evidence is not another generic predictor-ranking paper. It is the **paired KDEN probability-score evidence for these predeclared mechanistic alternatives**, acquired on a complete, legal, common-day cohort.

## 13. Decision and versioned handoff

**Conclusion: DO_NOT_REDUCE_YET.** Following the budget reconsideration in section 1.1, prioritize **C13/C14 as seven-day-scale acquisition candidates**, retaining C32 as a conservative comparator. Neither the original 26 omissions nor the larger budget-driven omission set has been validated. Reconcile the selection design with the total runtime budget before authorizing experiments; use conditional probability skill to decide which groups earn reacquisition.

This conclusion completes the documentation study. It does not request that the research agent launch the owner-run experiments. The production acquisition contract remains the original full universe until separately changed.

Once a final reduced union is accepted:

1. Publish the accepted decision matrix, tolerances, cohort/fold definitions, proper-score results, uncertainty, selected spatial supports, and cost ledger as versioned research records.
2. Create a successor H/Q registry with retained/removed IDs and rationale. Preserve the original registry and current Step 04 PASS.
3. Regenerate and seal both product request plans and counts; revise affected schemas/spatial contracts explicitly. Do not treat changed request identities as a schema re-attestation.
4. Validate registry, selector, interval, unit, geometry, target-window, availability, and derived-feature dependency contracts. H16/Q05 parity remains required.
5. Run a bounded confirmation pilot covering both station eras, normal/extended/DST cases, FH00, Q block boundaries, resume/rebuild, explicit missingness/quarantine, and deterministic extraction. Include any newly accepted spatial support.
6. Measure actual selected-universe throughput, network bytes, output size, and full-history projection against original Step 04 results; reconcile any cohort reuse honestly.
7. Obtain separate owner authorization before full-history Steps 05/06.

No executable command is prescribed as already available for a scientific selection pipeline that has not been implemented. The implementation handoff should provide owner-run entry points for: cohort-plan generation; full-universe cohort acquisition; issue-time feature construction; isolated label join; nested family benchmarks; grouped ablations; Pareto/uncertainty reporting; and successor confirmation. Each must accept frozen cohort, registry, spatial, availability, fold, and feature-spec versions and produce separate research outputs.

## References and evidence provenance

Literature access date: 13 September 2026. The specific proposed field choices, geometries, cohort sizes, and statistical thresholds are recommendations made in this report. External studies support mechanisms or methodology; none is represented as having run this KDEN v3.75 ablation.

### Local sources

- **L1.** [Step 04.5 research brief](../STEP_04_5_FEATURE_UNIVERSE_STUDY.md). Study objective, frozen/open decisions, engineering counts, full matrix and validation requirements.
- **L2.** [Not bundled: Universal Issue-Time Feature Panel Scientific Specification v1.0](../DATA_AVAILABILITY.md#not-bundled). Historical field identities, operators, composite definitions and GAM priors; its MADIS, selected-cycle and reuse instructions are historical context, not current task instructions.
- **L3.** [Reference not bundled: D1 Historical Synthesis](../DATA_AVAILABILITY.md#not-bundled). Especially pp. 1, 3–7, 9–10; Table 5 checked against the rendered source page. Numerical results are reported by the supplied synthesis; underlying prior-codebase artifacts were not executed or independently audited.
- **L4.** [Current hourly registry](../registries/hrrr_hourly_v375.csv), [subhourly registry](../registries/hrrr_subhourly_v375.csv), and [decoded identities](../registries/decoded_grib_identities_v375.json). Exact ID, parameter, level, step/interval and current spatial contracts.
- **L5.** [Not bundled: Step 04 pilot report](../DATA_AVAILABILITY.md#not-bundled) and [Not bundled: pilot JSON](../DATA_AVAILABILITY.md#not-bundled). Selected throughput, projection, storage, decoding/quarantine and aggregate network evidence.
- **L6.** [Current project specification](../PROJECT.md) and [station coordinate eras](../registries/station_coordinate_eras_v375.csv). Current scope and effective coordinate dates; targeted reads used to reconcile the brief and historical specification.

### Primary meteorological and methodological sources

- **R1.** Benjamin, S. G., et al. (2021 update). [Diagnostic fields developed for hourly updated NOAA weather models, NOAA Technical Memorandum OAR GSL-66](https://repository.library.noaa.gov/view/noaa/32904/noaa_32904_DS1.pdf). Sections B, G, I and J. Key diagnostic distinctions: PBL versus conventional low cloud, ceiling vertical reference, gust diagnostic, smoothed isobaric output, and smoke-specific AOTK. These clarify semantics, not KDEN incremental skill.
- **R2.** Struthwolf, M. E. (1995). [Forecasting Maximum Temperatures through Use of an Adjusted 850- to 700-mb Thickness Technique](https://journals.ametsoc.org/view/journals/wefo/10/1/1520-0434_1995_010_0160_fmttuo_2_0_co_2.xml). Weather and Forecasting, 10, 160–171. Western-site thermal forecasting precedent; Dugway, not Denver.
- **R3.** Dowell, D. C., et al. (2022). [The HRRR, Part I: Motivation and System Description](https://repository.library.noaa.gov/view/noaa/53029). Weather and Forecasting, 37, 1371–1395; doi:10.1175/WAF-D-21-0151.1. Model/physics context.
- **R4.** Darby, L. S., W. D. Neff, and R. M. Banta (1999). [Multiscale Analysis of a Meso-β Frontal Passage in the Complex Terrain of the Colorado Front Range](https://journals.ametsoc.org/view/journals/mwre/127/9/1520-0493_1999_127_2062_maoamf_2.0.co_2.xml). Monthly Weather Review, 127, 2062–2081. Regional wind/moisture boundary observations; publisher-indexed full-text passages reviewed.
- **R5.** Meyer, T. A., W. R. Bobb, and T. W. Dulong (undated archived NWS study). [Denver Air Route Traffic Control Thunderstorm Patterns](https://www.weather.gov/media/aviation/CaseStudies/zdvtstms.pdf). Airport-specific topographic and convergence context. Historical operational details are not used as present-day airport specifications.
- **R6.** Crook, N. A., T. L. Clark, and M. W. Moncrieff (1991). [The Denver Cyclone, Part II: Interaction with the Convective Boundary Layer](https://journals.ametsoc.org/view/journals/atsc/48/19/1520-0469_1991_048_2109_tdcpii_2_0_co_2.xml). Journal of the Atmospheric Sciences, 48, 2109–2126. Regional circulation/heating/mixing mechanism; abstract reviewed.
- **R7.** Wilson, J. W., and C. K. Mueller (1993). [Nowcasts of Thunderstorm Initiation and Evolution](https://journals.ametsoc.org/view/journals/wefo/8/1/1520-0434_1993_008_0113_notiae_2_0_co_2.xml). Weather and Forecasting, 8, 113–131. Denver-area initiation and boundary evidence; observations in that study are not proposed v3.75 inputs.
- **R8.** Lee, T. R., et al. (2024). [On the Importance of Regime-Specific Evaluations for NWP Models as Demonstrated Using HRRR](https://repository.library.noaa.gov/view/noaa/61725). Weather and Forecasting, 39, 781–791; doi:10.1175/WAF-D-23-0177.1. 2021 USCRN solar/heating-regime evaluation.
- **R9.** Adler, B., et al. (2023). [Impact of Seasonal Snow-Cover Change on the Observed and Simulated State of the Atmospheric Boundary Layer in a High-Altitude Mountain Valley](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2023JD038497). Journal of Geophysical Research: Atmospheres. Colorado mountain-valley HRRRv4 process evidence; not a KDEN error estimate.
- **R10.** Adler, B., et al. (2023). [Evaluation of a cloudy cold-air pool in the Columbia River basin in different versions of HRRR](https://gmd.copernicus.org/articles/16/597/2023/). Geoscientific Model Development, 16, 597–619. Cloud and cold-pool process analogy, with geographic/version limitations.
- **R11.** [Simulating wildfire emissions and plume rise using geostationary satellite fire radiative power measurements: a case study of the 2019 Williams Flats fire](https://acp.copernicus.org/articles/22/10195/2022/) (2022). Atmospheric Chemistry and Physics, 22, 10195 onward; section 2.2 describes HRRR-Smoke coupling. Supports radiation-feedback context, not a KDEN smoke coefficient.
- **R12.** James, E. P., et al. (2022). [The HRRR, Part II: Forecast Performance](https://journals.ametsoc.org/view/journals/wefo/37/8/WAF-D-21-0130.1.xml). Weather and Forecasting, 37, 1397–1417. Regional/diurnal verification and variability; no transfer of CONUS bias magnitudes to KDEN.
- **R13.** Delle Monache, L., et al. (2013). [Probabilistic Weather Prediction with an Analog Ensemble](https://journals.ametsoc.org/doi/pdf/10.1175/MWR-D-12-00281.1). Monthly Weather Review, 141, 3498–3516. Analog construction and archive-length sensitivity, not the optimal KDEN source union.
- **R14.** Gneiting, T., and A. E. Raftery (2007). [Strictly Proper Scoring Rules, Prediction, and Estimation](https://doi.org/10.1198/016214506000001437). Journal of the American Statistical Association, 102, 359–378. General probability-scoring foundation; the numeric tolerances in section 10 are this report's proposed settings.

[R1]: https://repository.library.noaa.gov/view/noaa/32904/noaa_32904_DS1.pdf
[R2]: https://journals.ametsoc.org/view/journals/wefo/10/1/1520-0434_1995_010_0160_fmttuo_2_0_co_2.xml
[R3]: https://repository.library.noaa.gov/view/noaa/53029
[R4]: https://journals.ametsoc.org/view/journals/mwre/127/9/1520-0493_1999_127_2062_maoamf_2.0.co_2.xml
[R5]: https://www.weather.gov/media/aviation/CaseStudies/zdvtstms.pdf
[R6]: https://journals.ametsoc.org/view/journals/atsc/48/19/1520-0469_1991_048_2109_tdcpii_2_0_co_2.xml
[R7]: https://journals.ametsoc.org/view/journals/wefo/8/1/1520-0434_1993_008_0113_notiae_2_0_co_2.xml
[R8]: https://repository.library.noaa.gov/view/noaa/61725
[R9]: https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2023JD038497
[R10]: https://gmd.copernicus.org/articles/16/597/2023/
[R11]: https://acp.copernicus.org/articles/22/10195/2022/
[R12]: https://journals.ametsoc.org/view/journals/wefo/37/8/WAF-D-21-0130.1.xml
[R13]: https://journals.ametsoc.org/doi/pdf/10.1175/MWR-D-12-00281.1
[R14]: https://doi.org/10.1198/016214506000001437
