# Research reading edition

Historical document, not the current v3.75 execution contract. This GitHub reading edition preserves the source's proposals and results; they are not relabeled as completed R14 work. Agent-directed wording is retained.

Source: `KDEN_Universal_Issue_Time_Feature_Panel_Scientific_Specification_v2.2.docx`  
Source SHA-256: `02fed6f2381f346cc8ac9b68bcd7678a58ce55b972637f0f1a5e84f99f77e616`

Word metadata is omitted by conversion. Any additional withholding is recorded in the publication manifest.

---

**SCIENTIFIC ACQUISITION FREEZE**

KDEN Universal Issue-Time\
Feature Panel

Exact source universe, feature contracts, and causal lineage for the structural and observation-augmented location-scale GAMs

**Version 2.2 \| 31 August 2026**

*Historical window: 2021-01-01 through 2026-08-04\
Station: KDEN \| Target: official whole-degree-Fahrenheit daily Tmax*

Prepared as the scientific contract immediately downstream of Layer 1

# Document control

| **Property** | **Frozen value** |
|:--:|----|
| **Document** | KDEN Universal Issue-Time Feature Panel Scientific Specification |
| **Version / status** | v1.0 / acquisition freeze for implementation |
| **Primary unit** | One target day d x one checkpoint t; six checkpoint rows per eligible day |
| **Primary baseline** | Q15-BI-FLOOR when the sealed R_low is defined |
| **Protected challenger** | H-BI-FLOOR under identical folds and feature lineage |
| **Historical availability** | KDEN_HIST_COMPLETE_L105_V1, subject to horizon and completeness |
| **Checkpoint set** | 09:00, 09:45, 10:00, 10:45, 11:00, 11:45 America/Denver |
| **Cycle-retention envelope** | Distinct Policy-A cycles selected by those checkpoints only; illustrative 07/08/09/10 local labels |
| **Target window** | W\[d\] = \[07:00Z on d, 07:00Z on d+1), left-inclusive/right-exclusive |
| **Design authority** | This specification; field audit is evidence and inspiration, not verbatim authority |

| **Binding decision** Acquire a normalized universal source panel that can generate two separate GAM views: an HRRR-driven structural prior and a checkpoint-legal MADIS-augmented batch forecast. Preserve the MADIS sequence separately so the state-space challenger can replay observations without forcing the GAM and filter to consume the same information twice. |
|----|

# Contents

- 1\. Executive acquisition freeze

- 2\. Forecast objects and modeling separation

- 3\. Data architecture and canonical tables

- 4\. Clocks, cycle retention, and revision limits

- 5\. Feature-admission standard

- 6\. Temporal and spatial operators

- 7\. HRRR wrfsfcf acquisition freeze

- 8\. HRRR wrfsubhf acquisition freeze

- 9\. Baseline, solar, and deterministic context

- 10\. MADIS observation universe and summaries

- 11\. Departures, innovations, and state-space replay

- 12\. Exact checkpoint-panel feature blocks

- 13\. GAM views and initial modeling shortlist

- 14\. Missingness, leakage, and acceptance gates

- 15\. Acquisition plan and cost controls

- 16\. Deferred and prohibited features

- Appendices: source registry, naming grammar, implementation checklist

# 1. Executive acquisition freeze

Layer 1 established an issue-time-indexed baseline B\[d,t\] and left a residual e\[d,t\] = Y\[d\] - B\[d,t\]. The present program does not ask which weather fields predict Tmax from scratch. It asks which legally available quantities can explain the conditional center and conditional dispersion of that residual. The commercial deliverable is therefore a calibrated whole-degree distribution, not merely a lower MAE point forecast.

mu\[d,t\] = B\[d,t\] + g_mu(x\[d,t\]) and log sigma\[d,t\] = g_sigma(x\[d,t\])

The acquisition freeze intentionally separates raw source retention from model eligibility. The source mart retains a compact, mechanistically justified set of trajectories and observations. The checkpoint panel applies deterministic operators to those sources. Individual GAM specifications then select only the columns appropriate to their information boundary.

## 1.1 Frozen decisions

1.  Retain only the distinct Policy-A cycles selected across the six checkpoints. Under the illustrative 105-minute mapping these are 07, 08, 09, and 10 local-cycle labels, but production code must resolve native UTC initialization times rather than hard-code local labels.

2.  Do not acquire an open-ended prior-cycle archive for revision features. With the bounded set, revisions are 08-07, 09-08, and 10-09 on identical valid-time support. The 09:00 row has no predecessor revision and must be null by design.

3.  Anchor the primary feature bundle to the Q15 primary-baseline cycle. wrfsfcf and wrfsubhf fields may be combined only when they share the same native cycle initialization. If product-specific Policy A ever selects different cycles, build branch-specific bundles or fail closed; never create a cross-cycle physical state silently.

4.  Acquire 44 hourly wrfsfcf messages: 39 serious-core messages after deriving specific humidity rather than downloading it, plus five promoted challengers (visibility, aerosol optical thickness, cloud ceiling, surface CAPE, surface CIN). Surface height is stored once and Q15/HRRR 2-m temperature is reused from Layer 1.

5.  Acquire 14 subhourly message families, with exact snapshot/interval semantics. Reuse the existing Q15 2-m-temperature trajectory. The subhourly extension is restricted to fast variables that can plausibly alter intrahour heating or provide close MADIS analogues.

6.  Retain raw MADIS observations and QC/provenance as a long sequence. Derive checkpoint summaries without deleting the sequence. Historical eligibility remains observationTime \<= checkpoint as the documented pseudo-live proxy; live deployment must use receiptTime \<= checkpoint.

7.  Do not permit truth, later observations, later cycles, finalized market prices, or post-event QC products with unverified time semantics into any inference view.

## 1.2 Why this is the minimum serious universe

The field audit's 40 KEEP messages identify the correct physical pathways: low-level thermal structure, surface state, cloud/radiation, boundary-layer energy partitioning, snow, and precipitation transitions. This specification removes one deterministic redundancy (SPFH at 2 m, derivable from dewpoint and pressure), changes surface height to static lineage, reuses already-acquired 2-m temperature, and promotes only five MAYBE messages whose information is not already represented cleanly. All other MAYBEs remain deferred.

The result is deliberately not a 300-column dump. Raw trajectories are sampled at field-specific temporal density, and the wide checkpoint panel is generated from a named operator grammar. This preserves future scientific flexibility while bounding downloads, storage, and effective model dimension.

# 2. Forecast objects and modeling separation

## 2.1 Three different conditional distributions

Structural prior: p0(Y\[d\] \| X_NWP\[d,t\])

Batch checkpoint forecast: p(Y\[d\] \| X_NWP\[d,t\], X_OBS\[d,t\], X_DEP\[d,t\])

Sequential forecast: p(Y\[d\] \| X_NWP\[d,t\], z\[d,1:t\])

The structural GAM learns recurring cross-day forecast error conditional on HRRR state, trajectory, cycle stability, season, solar geometry, and Layer-1 baseline geometry. The observation-augmented GAM conditions additionally on checkpoint-legal summaries of MADIS and forecast-observation departure. A GAM that has already consumed MADIS through t is not a prior relative to those observations; it is a batch observation-conditioned forecast.

The state-space challenger starts from the structural prior and consumes the ordered observation sequence z\[d,1:t\]. It must demonstrate incremental value against the observation-augmented GAM at the same checkpoint. A later hybrid may use a batch GAM through an initialization time t0 and assimilate only observations after t0.

## 2.2 Permitted model views

| **View** | **Permitted columns** | **Forbidden overlap** | **Scientific question** |
|:--:|----|----|----|
| V0 raw | Layer-1 baselines and lineage | No learned correction | What does Layer 1 achieve? |
| V1 structural GAM | Baseline + solar/time + HRRR state/path/revision | No current-day MADIS summaries beyond the chosen FLOOR baseline geometry | Can recurring NWP error structure reduce bias and conditional uncertainty? |
| V2 observation GAM | V1 + legal MADIS summaries + current-cycle departures | No sequential filter replay through the same t | How much live information can a transparent batch model capture? |
| V3 state-space | V1 prior + ordered MADIS sequence | Do not precondition the same prior on identical detailed MADIS history | Does persistence-aware sequential assimilation beat V2? |
| V4 non-overlap hybrid | V2 through t0 + observations received after t0 | No replay of observations \<= t0 | Can new reports update a strong checkpoint forecast between scheduled issues? |

# 3. Data architecture and canonical tables

| **Architecture rule** The universal panel is a small family of normalized tables, not one irreversible wide file. The checkpoint GAM table is a derived product. Long trajectories and observation sequences remain the reconstruction authority. |
|----|

| **Canonical table** | **Grain** | **Purpose** | **Contains target?** |
|:--:|----|----|----|
| cycle_manifest | target day x product x retained cycle | Legality, availability, horizon, source hash, completeness and retained-cycle order | No |
| hrrr_point_trajectory | cycle x product x valid time x field x spatial statistic | Compact extracted HRRR values; raw GRIB messages may be discarded after verified extraction | No |
| madis_observation_sequence | station x observation/receipt time | Raw legal observation stream, candidate intervals, QC, source lineage | No |
| checkpoint_features | target day x checkpoint | Wide universal panel generated deterministically from the three source tables and Layer 1 | No |
| training_labels | target day | Final curated CLI/Weather.com-regime Tmax and truth lineage | Yes, isolated |
| model_predictions | target day x checkpoint x model version | Out-of-fold centers, scales, integer probabilities, diagnostics | Prediction output only |

## 3.1 Why truth is a separate table

Keeping Y\[d\] and residual columns outside checkpoint_features makes the inference boundary mechanically testable. Training code joins labels only after features pass as-of validation. Production code never loads the label table. This also prevents final CLI issue or revision metadata from becoming accidental predictors.

## 3.2 Canonical keys

- target_day: date label bound to W\[d\], never a naive local calendar maximum.

- checkpoint_id: CP_0900, CP_0945, CP_1000, CP_1045, CP_1100, CP_1145.

- issue_time_utc and issue_time_local: both materialized; UTC is the join authority.

- station_id and station_coord_era: KDEN identity plus the effective coordinate record used by Layer 1.

- product and cycle_init_utc: native HRRR identifiers; never infer cycle from filename text alone.

- valid_time_utc, step_type, interval_start/end: required to distinguish snapshots, averages, maxima, and accumulations.

- feature_spec_version and derivation_version: immutable versions for every generated panel.

# 4. Clocks, cycle retention, and revision limits

## 4.1 Two clocks and one immutable target window

W\[d\] = \[07:00Z on d, 07:00Z on d+1) and W_future\[d,t\] = {tau in W\[d\] : tau \> t}

Checkpoint labels use America/Denver civil time and therefore resolve differently in MST and MDT. Source joins and forecast availability are evaluated in UTC. Future forecast values are legal predictors when the producing file was usable by t; future observations are never legal.

## 4.2 Bounded cycle set

| **Checkpoint** | **Illustrative selected cycle** | **Revision pair** | **Status** |
|:--:|----|----|----|
| 09:00 | 07 | none | revision unavailable by design |
| 09:45 | 08 | 08 - 07 | new-cycle revision available |
| 10:00 | 08 | 08 - 07 | same pair; recompute summaries on the 10:00 window |
| 10:45 | 09 | 09 - 08 | new-cycle revision available |
| 11:00 | 09 | 09 - 08 | same pair; recompute summaries on the 11:00 window |
| 11:45 | 10 | 10 - 09 | new-cycle revision available |

These labels reproduce the Baseline Specification's 105-minute illustration. They are not a hard-coded UTC mapping. The historical selector must resolve actual issue UTC, native cycle UTC, horizon class, product completeness, and the frozen availability emulator. Fallback days may select an older cycle; the manifest records what actually happened.

## 4.3 Exact revision algebra

REV_CUR_Z = Z(c_new, t) - Z(c_prev, t)

REV_PK_Z = Z(c_new, tau_peak_new) - Z(c_prev, tau_peak_new)

REV_SUM_Z = S\[Z(c_new); t, tau_peak_new\] - S\[Z(c_prev); t, tau_peak_new\]

Both cycles are evaluated on identical valid-time support. Comparing each cycle at its own peak would mix a value revision with a timing revision. Peak-time revision is stored separately as tau_peak_new - tau_peak_prev. Baseline revision recomputes the older cycle's maximum over the current checkpoint's strict future window.

## 4.4 What the bounded set cannot do

The retained selected cycles are sufficient for the structural GAM, the observation-augmented GAM, and bounded cycle-revision features. They are not sufficient to reconstruct a strict causal HRRR innovation for every observation from the opening of W\[d\]. At 09:00, for example, no retained predecessor may exist for early-morning observations. The panel therefore keeps two distinct observation-model comparisons:

- selected-cycle departure: legal at the checkpoint and useful for the batch GAM, even when the selected run was not available at the original observation minute;

- causal sequential innovation: observation minus the newest retained forecast that was already operationally available before that observation was received; null before the first retained cycle becomes available.

| **State-space boundary** If later state-space work proves that pre-09:00 causal innovation history is commercially material, authorize a separately costed c06/earlier-cycle extension. Do not smuggle that extra acquisition into v1 under the name of cycle revision. |
|----|

# 5. Feature-admission standard

Every model-eligible feature must have a feature contract. A field is acquired only when the raw information supports at least one credible residual pathway and cannot be reconstructed reliably from already retained information. A derived feature enters a GAM view only when its transformation, time support, missingness behavior, and intended location/scale role are predeclared.

| **Contract property** | **Required statement** |
|:--:|----|
| **Error pathway** | Why can this explain E\[Y-B \| X\], Var(Y-B \| X), or both? |
| **Information novelty** | What does it add beyond B, correlated retained fields, and deterministic derivations? |
| **Temporal meaning** | Snapshot, interval average, interval maximum, accumulation, tendency, future summary, revision, or innovation? |
| **Causal availability** | Which file/observation was usable by t, under which historical/live time basis? |
| **Cycle and product** | Exact initialization, wrfsfcf/wrfsubhf source, forecast lead, and same-cycle alignment rule. |
| **Spatial meaning** | Bilinear point, nearest cell, 3x3 gradient, or 9x9 displacement summary? |
| **Units and transform** | Native unit, canonical unit, clipping/domain rule, and derived formula. |
| **Model role** | Eligible for g_mu, g_sigma, both, audit only, or state-space only. |
| **Failure behavior** | Null, fallback, missingness indicator, or row invalidation; never silent imputation. |
| **Promotion evidence** | Out-of-fold improvement in probabilistic scores, stability, and calibration rather than in-sample MAE alone. |

## 5.1 Dispositions

| **Code** | **Meaning** | **Action** |
|:--:|----|----|
| A0 | Already available | Reuse Layer-1 trajectory/baseline or static metadata; do not download again. |
| A1 | Acquire in v1 | Included in the frozen source mart. |
| D1 | Derive in v1 | Compute from A0/A1 sources with the named operator grammar. |
| C | Candidate column | Retain in universal panel but not automatically in the first GAM formula. |
| R | Research extension | Do not acquire until a controlled value-of-information gate authorizes it. |
| X | Prohibited | Leakage, semantic mismatch, terrain-invalid level, duplication, or market contamination. |

# 6. Temporal and spatial operators

## 6.1 Named temporal operators

| **Code** | **Definition** | **Use** |
|:--:|----|----|
| CUR | Field value at checkpoint t. Continuous hourly snapshots use same-cycle linear interpolation between bracketing valid times. | Current regime |
| PK | Field value at tau_peak from the primary Q15 raw trajectory, using same-cycle interpolation. | Physical state at modeled maximum |
| DPK | PK - CUR. | Modeled evolution to the peak |
| PREMEAN | Time-weighted mean on \[t, tau_peak\]. | Sustained forcing/state |
| PREMIN / PREMAX | Minimum/maximum on \[t, tau_peak+2h\], capped at end W\[d\]. | Thresholds, alternate-peak risk |
| PREINT | Trapezoidal integral on \[t, tau_peak\]; radiation/flux output in MJ m-2. | Cumulative heating energy |
| FRAC_a | Fraction of path exceeding threshold a, with threshold in the feature registry. | Cloud/precip exposure |
| ONSET_a | Minutes from t to first threshold crossing; null plus no-event flag if absent. | Timing of interruption |
| GROWTH | Field change per hour over a named window, never applied blindly to accumulations/maxima. | PBL/trajectory rate |
| REV\_\* | New retained cycle minus immediate prior retained cycle on common support. | Forecast stability |

The +2-hour extension after tau_peak applies only to event/min/max operators used to identify delayed or alternate-peak risk. Energy integrals stop at tau_peak unless a separately named post-peak operator is introduced. Interval accumulations are summed on their native non-overlapping intervals; they are never interpolated as snapshots.

## 6.2 Spatial operators

| **Code** | **Geometry** | **Fields** |
|:--:|----|----|
| BI | Layer-1 bilinear extraction at the effective KDEN coordinate. | Smooth continuous point state and fluxes |
| NN | Nearest model cell. | Categorical/accumulation support and audit comparisons |
| 3x3 | Centered local tile; compute central gradients with map-aware physical distances. | T850/T700/HGT/MSLMA and compact displacement summaries |
| 9x9 | Centered nominal 24 km x 24 km tile on the approximately 3-km HRRR grid. | Cloud, radiation spatial spread, reflectivity, precip, CAPE/CIN, visibility, ceiling |

For 9x9 fields the checkpoint panel stores only predeclared summaries: center BI, neighborhood mean, standard deviation, maximum/minimum as appropriate, and threshold coverage. A compact extracted tile may be retained in the long trajectory mart because it is small and permits later summary corrections without redownloading a full-domain GRIB message.

## 6.3 Mechanistic composite features

thickness_850_700 = HGT700 - HGT850

net_SW = DSWRF - USWRF; net_LW = DLWRF - ULWRF; net_rad = net_SW + net_LW

evaporative_fraction = LHTFL / (SHTFL + LHTFL), with signed/near-zero denominator guards

adv_T850 = - (u850 \* dT850/dx + v850 \* dT850/dy) \* 3600

Wind is retained as U/V. Direction is derived only for interpretation; vector differences are never calculated by subtracting compass degrees. The approximate Front Range cross-barrier component is earth-relative U: positive eastward flow is a downslope/westerly proxy and negative westward flow is an upslope/easterly proxy. This approximation is explicitly named, not treated as exact terrain-normal physics.

# 7. HRRR wrfsfcf acquisition freeze

The hourly product supplies the rich physical state. The official NCEP forecast-hour-2 inventory contains 173 records, but v1 retrieves only the 44 message identities listed in Appendix A. Records are selected by parameter, level, step type, and interval metadata, not by a brittle record number alone. Actual .idx inventories must be audited on representative dates and at version boundaries before the full run.

## 7.1 Temporal-density classes

| **Class** | **Required valid times** | **Field families** | **Cost rationale** |
|:--:|----|----|----|
| STATIC | Once per fixed grid/version | surface HGT | Do not repeat immutable terrain lineage. |
| REUSE L1 | Existing complete Layer-1 trajectories | 2-m TMP | No second acquisition of the baseline variable. |
| SPARSE | Hourly brackets for each assigned checkpoint and Q15 peak, deduplicated by cycle | 700/850 state, surface state, snow, PWAT, AOTK | Captures regime and peak evolution without full hourly paths. |
| PATH | Every hourly interval in the union from earliest assigned checkpoint through tau_peak+2h | cloud/radiation, flux/PBL, precip, visibility, ceiling, CAPE/CIN | Needed for energy, onset, exposure and uncertainty summaries. |

The retrieval planner operates after Layer-1 Q15 peak times and selected cycles are known. It unions required valid times across checkpoints sharing a cycle, so 09:45 and 10:00 do not create duplicate cycle downloads and 10:45 and 11:00 do not create duplicates. Message bytes are range-fetched, verified, locally subset, and discarded after the compact extracted values and hashes are written.

## 7.2 Five promoted challengers

| **Field** | **Why promoted now** | **Why the rest remain deferred** |
|:--:|----|----|
| VIS surface | Direct observation bridge and morning fog/stable-layer regime not fully represented by radiation alone. | No need for additional visibility-like diagnostics. |
| AOTK column | Smoke is a plausible Denver solar-bias regime; may affect scale even after modeled DSWRF. | Beam/diffuse radiation remains redundant initially. |
| HGT cloud ceiling | Low-cloud geometry and partial ASOS analogue; useful for delayed morning heating. | Cloud base/top and pressure forms are redundant. |
| surface CAPE | Pre-convective potential before reflectivity/precipitation begins; mainly g_sigma. | Do not acquire every alternative CAPE parcel definition. |
| surface CIN | Separates realized convective threat from strongly capped potential; mainly g_sigma. | Other CIN layers remain redundant. |

# 8. HRRR wrfsubhf acquisition freeze

The subhourly product is not a second copy of the hourly field universe. It repeats a smaller set at 15-minute valid times and mixes snapshots with 5-minute averages and 15-minute averages/accumulations. v1 uses it only where intrahour evolution or observation matching is scientifically valuable. The exact 14-family list is in Appendix B.

| **Subhourly rule** For each retained cycle, fetch only the union of valid blocks required by its assigned checkpoints through tau_peak+2h. TMP:2 m comes from the existing Layer-1 Q15 cache. DSWRF uses the preceding 15-minute average for energy calculations. Wind retains both snapshots and preceding 5-minute U/V averages. APCP retains its 15-minute accumulation semantics. |
|----|

## 8.1 Same-cycle hourly/subhourly coherence

The primary structural bundle is coherent only when all cross-product algebra uses the same initialization. Q15-H disagreement is a named feature comparing two temporal representations from the same cycle; it is not permission to use a newer partial subhourly run with an older hourly state. If a product is missing, missingness is explicit and the affected composite is null.

## 8.2 Interpolation rules

- Continuous snapshots (T, Td, P, U, V) may be linearly interpolated between legal same-cycle 15-minute valid times to an observation timestamp.

- Gust, visibility, reflectivity, precipitation rate, and cloud ceiling use nearest valid snapshot with signed time offset retained; do not smooth an onset across time.

- Five-minute wind averages are matched to observations by interval midpoint/end semantics, not relabeled as instantaneous wind.

- Fifteen-minute DSWRF averages are integrated as average flux x 900 seconds. Fifteen-minute APCP is summed; it is not differenced again.

- No interpolation may cross cycle initialization or splice different cycles into one physical trajectory.

# 9. Baseline, solar, and deterministic context

## 9.1 Layer-1 columns retained at negligible cost

| **Columns** | **Meaning** |
|:--:|----|
| b_h_nn_f, b_h_bi_f | Raw hourly parents |
| b_q15_nn_f, b_q15_bi_f | Raw quarter-hour parents |
| b_h_bi_floor_f, b_q15_bi_floor_f | Protected and primary floor baselines |
| r_low_f, r_high_f, q_f | Definitely achieved lower bound, ambiguity diagnostic, width |
| floor_active, floor_delta_f, signed_floor_margin_f | Piecewise residual regime and baseline-floor geometry |
| q15_peak_time_utc, h_peak_time_utc | Modeled peak timing |
| q15_remaining_heating_f | B_q15_raw - Q15 temperature at t |
| q15_near_peak_duration_min | Number of 15-min future points within 1 F of B_raw x 15 |
| q15_top2_separated_gap_f | Highest forecast value minus the highest temporally separated alternative local peak |
| q15_minus_h_f, peak_time_difference_min | Temporal-product disagreement |
| bi_minus_nn_q15_f, bi_minus_nn_h_f | Station/grid spatial-sampling sensitivity |

## 9.2 Deterministic calendar and solar features

| **Feature** | **Definition / implementation contract** | **Role** |
|:--:|----|----|
| doy_sin, doy_cos | Cyclic day-of-year encoding using the actual year's day count. | Season without December-January discontinuity |
| utc_offset_minutes, dst_flag | America/Denver timezone resolution at checkpoint. | Audit and clock regime |
| solar_elevation_t_deg | Solar position at effective KDEN coordinates and issue UTC; versioned algorithm. | Physical interpretation of observed heating |
| solar_elevation_peak_deg | Solar elevation at Q15 modeled peak. | Peak geometry |
| minutes_to_solar_noon | Signed checkpoint-to-local-solar-noon difference. | Separates morning ramp from afternoon decline |
| minutes_to_sunset, daylight_minutes | Astronomical geometry under versioned calculation. | Remaining heating opportunity |
| toa_horizontal_sw | Extraterrestrial horizontal shortwave from solar geometry. | Denominator for solar-normalized DSWRF; null at low sun |

Solar-normalized radiation is calculated only when cosine solar zenith exceeds a frozen threshold. Nighttime/near-horizon ratios are null with a denominator flag; they are never clipped into apparently meaningful daylight values.

# 10. MADIS observation universe and summaries

MADIS is retained because it measures the realized local atmosphere. It is not a substitute for final CLI Tmax, and it is not numerically identical to an HRRR grid-cell state. The observation sequence stores raw reports, station identity, observation time, receipt time when available, source file, units, resolution, provider/QC flags, and all conversions. Derived API variables are marked as derived rather than treated as independent measurements.

## 10.1 Temperature candidate geometry

k_low(c) = ceil((18c + 311)/10); k_high(c) = ceil((18c + 329)/10) - 1

R_low\[d,t\] = max k_low(o); R_high\[d,t\] = max k_high(o), over legal observations in W\[d\] through t

The raw whole-Celsius report is never silently converted to one exact whole-Fahrenheit integer. For general temperature departures the observation contributes an interval \[k_low, k_high\], its midpoint, and its width. For the deterministic floor only k_low is definitely achieved. Probability mass below R_low is removed from final integer distributions; R_high is not a hard lower bound.

## 10.2 Rolling summary windows

| **Family** | **Core summaries** | **Candidate summaries** |
|:--:|----|----|
| Temperature | latest interval; R_low/R_high; elapsed min/max; time since R_low; Theil-Sen slopes 30/60/120m; counts/gaps | 15m slope; slope30-slope120; interval-censored slope |
| Dewpoint | latest; depression; slopes 60/120m; counts/gaps | 30m slope; rapid-drying threshold |
| Pressure | latest station P; robust slopes 60/120m | 30m tendency; change-point flag |
| Wind | latest/mean U,V; cross-barrier component; vector shift 30/60m; gust max 60m | direction-change threshold; variability |
| Visibility | latest and min 60/120m | recovery rate |
| Precipitation | any onset; latest rate; rolling amount; present-weather flag | intensity trend |
| Cloud | latest layer categories; effective ceiling; modal opaque coverage over 60m | category-transition count |
| Completeness | n reports, pass fraction, latest age, maximum gap, source-gap flag | variable-specific stale-state flags |

Theil-Sen slopes are predeclared because whole-degree-Celsius quantization makes endpoint and ordinary least-squares slopes brittle. A window requires a frozen minimum number of usable reports and a maximum allowed internal gap; otherwise the slope is null with a reason code. Acceleration is not core because differencing quantized short-window slopes can amplify noise.

## 10.3 QC and pseudo-live caution

Historical Layer 1 uses observationTime \<= checkpoint and does not claim literal receipt-time truth. The new sequence preserves receipt/insertion/QC timestamps when present but does not backfill them. MADIS QC flags are stored, yet any QC stage that may use later observations must be excluded from a strict as-of model until its operational timing is verified. A conservative first pass can apply provider validity, station identity, gross physical bounds, and frozen within-past-window consistency checks computed locally.

# 11. Departures, innovations, and state-space replay

## 11.1 Selected-cycle batch departures

DEP_Z\[d,t\] = Z_obs(s_last \<= t) - Z_HRRR(c_selected, s_last)

DEP_TREND_Z\[h\] = slope_obs(Z; h) - slope_HRRR(Z; h), for h in {30,60,120} minutes

These are legal checkpoint features because both the observation and selected cycle are known by t. They answer whether the atmosphere represented at the checkpoint agrees with the currently selected HRRR interpretation. They do not prove what the model expected before each earlier report occurred.

| **Variable** | **Level departure** | **Trend departure** | **Special rule** |
|:--:|----|----|----|
| Temperature | low/high/mid interval minus Q15 | 30/60/120m robust slope difference | retain candidate width and forecast interpolation offset |
| Dewpoint | TD - HRRR DPT2m | 60/120m | raw resolution/derived status retained |
| Pressure | station P - HRRR surface PRES | 60/120m | both in hPa; do not compare with MSLMA |
| Wind | Uobs-Uhrrr and Vobs-Vhrrr | vector trend/shift | never subtract direction angles |
| Gust | observed - HRRR gust | rolling max difference | different algorithms acknowledged |
| Visibility | observed - HRRR visibility | recovery/worsening category | prefer log or threshold scale if skewed |
| Precip | rate/amount departure | onset disagreement | match accumulation windows exactly |
| Cloud | categorical interval disagreement | category transition mismatch | no percent-category subtraction |

## 11.2 Cloud-category algebra

ASOS cloud categories are encoded as coverage intervals in eighths: CLR/SKC = \[0,0\], FEW = \[1,2\], SCT = \[3,4\], BKN = \[5,7\], OVC = \[8,8\]. VV remains a separate obscuration state. HRRR low-cloud fraction is converted to eighths only for comparison. Core outputs are below-interval distance, above-interval distance, within-interval flag, opaque-cloud mismatch, and ceiling-threshold mismatch. ASOS reports only limited vertical sky information, so total-atmosphere cloud is not treated as a direct analogue.

## 11.3 Causal innovation stream

c_asof(s) = newest retained cycle with availability_time(c) \<= receipt_time(s)

INNOV_Z(s) = Z_obs(s) - Z_HRRR(c_asof(s), s)

The long observation table carries c_asof, expected value, innovation or innovation interval, cycle age, forecast lead, and a no-causal-vintage reason. This is the state-space replay input. The checkpoint panel may summarize the causal stream for diagnostics, but those summaries are not automatically eligible for the observation GAM because V2 is already defined around selected-cycle batch departures.

# 12. Exact checkpoint-panel feature blocks

The following blocks define the wide checkpoint_features table. Appendix D provides the naming grammar. A column may be present for audit or challenger use without entering the first GAM. Every column carries a registry row with source IDs, operator, spatial rule, unit, role, and missingness behavior.

| **Block** | **Contents** | **Model eligibility** |
|:--:|----|----|
| K - keys and lineage | target_day; checkpoint_id; issue UTC/local; offset/DST; station/coordinate era; feature version; policy ID; selected hourly/Q15 cycles; cycle ages; HRRR/source versions; completeness and hashes | audit only |
| B - baseline geometry | six Layer-1 baselines; R_low/R_high/q; floor state/delta/margin; current Q15; remaining heating; peak lead; plateau width; alternate-peak gap; Q15-H and BI-NN disagreement | g_mu and g_sigma |
| S - solar/calendar | cyclic day of year; solar elevation at t/peak; solar noon/sunset offsets; daylight; TOA horizontal shortwave | g_mu; selected g_sigma interactions |
| T - thermal/air mass | 700/850 T/Td/HGT/U/V CUR/PK/DPK; thickness; dewpoint depressions; shear; cross-barrier flow; local advection proxies | primarily g_mu |
| N - near surface | surface P/MSLMA/skin T; 2m Td; 10m wind; gust; surface-air contrast; pressure gradient | g_mu and transition g_sigma |
| R - radiation/cloud | cloud exposure/spatial spread; DSWRF and cloud-forcing integrals; net SW/LW/radiation; normalized solar; ceiling; AOT | g_mu and g_sigma |
| E - energy/PBL/ground | sensible/latent/ground flux integrals; EF/Bowen guards; HPBL growth/max; moisture availability; SWE/cover/depth | g_mu and g_sigma |
| W - weather transition | reflectivity/precip onset, maxima, neighborhood coverage; PWAT; CAPE/CIN; visibility | primarily g_sigma; signed g_mu only if stable |
| C - cycle stability | baseline/peak-time/current/peak/summary revisions; legal retained-cycle count; baseline range; revision unavailable flag | primarily g_sigma; selected g_mu |
| O - observation summaries | temperature bounds/slopes/runmax; Td/P/wind/gust/visibility/precip/cloud summaries; counts, age and gaps | V2 only |
| D - selected-cycle departures | level/trend departures for T/Td/P/U/V; gust/visibility/precip/cloud disagreement | V2 only |
| Q - quality/missingness | field/source stale flags, interpolation offsets, QC pass rates, missing-block masks, fallbacks | g_sigma and audit |

## 12.1 Frozen revision shortlist

Although revisions can be calculated for every acquired field at no extra source cost, the first panel materializes only the following high-information revisions to avoid correlated expansion:

- rev_b_q15_raw_f and rev_q15_peak_time_min;

- rev_t2m_cur_f and rev_t2m_at_new_peak_f;

- rev_t850_cur_c and rev_thickness_850_700_cur_m;

- rev_crossbarrier_wind850_cur_mps;

- rev_dswrf_prepeak_mjm2 and rev_cfnsf_prepeak_mjm2;

- rev_low_cloud_premean_pct and rev_cloud_spatial_sd;

- rev_hpbl_premax_m;

- rev_precip_before_peak_flag and rev_refc_9x9_premax_dbz;

- rev_pwat_cur_kgm2;

- revision_pair_available, previous_cycle_init_utc, and common_support_fraction.

# 13. GAM views and initial modeling shortlist

## 13.1 Structural location GAM

The initial g_mu formula should begin with a small set of physically distinct summaries, not all raw registry columns. Smooth terms and interactions are penalized and estimated separately by checkpoint first. The shortlist is:

- baseline/floor geometry: B_raw, B_floor, floor_active, signed floor margin, remaining heating, peak lead;

- thermal state: T850 CUR, 850-700 thickness CUR, T850 DPK, 850 dewpoint depression, cross-barrier 850 wind, 850-10m shear, optional T850 advection;

- radiative forcing: prepeak DSWRF integral, solar-normalized DSWRF, low-cloud exposure, CFNSF integral, net-radiation integral;

- energy/mixing: HPBL CUR and growth, sensible-flux integral, evaporative fraction, ground flux, surface-air contrast;

- ground/season: cyclic day of year, snow cover/SWE, MSTAV and predeclared snow x radiation/floor interactions;

- transitions: pressure state/change, PWAT, cross-barrier wind transition, precip-before-peak indicator;

- stability: Q15-H disagreement and selected signed cycle revisions when available.

## 13.2 Structural scale GAM

The first g_sigma view emphasizes uncertainty markers rather than copying g_mu mechanically:

- absolute Q15-H disagreement, peak-time disagreement, BI-NN sensitivity, baseline cycle revision magnitude and retained-cycle range;

- cloud spatial standard deviation, low-cloud exposure, ceiling threshold, AOT smoke regime;

- reflectivity/precip neighborhood coverage, CAPE/CIN, PWAT, and convective onset timing;

- HPBL growth, wind shear/transition, snow/ground regime, and selected energy-partition extremes;

- checkpoint, season, floor state, source age, missingness, interpolation distance, and observation completeness only when permitted by the view.

## 13.3 Observation-augmented additions

- latest temperature candidate interval, R_low/R_high, time since runmax, heating from elapsed minimum, and robust 30/60/120-minute slopes;

- temperature level-departure interval and 30/60/120-minute heating-rate departures;

- latest dewpoint/depression and 60/120-minute dewpoint departure;

- station-pressure tendency and pressure-trend departure;

- U/V and cross-barrier wind departure, vector shift, and gust departure;

- visibility, precipitation onset, opaque-cloud mismatch, and ceiling mismatch;

- observation counts, latest age, maximum gap, QC pass fraction, and quantization/candidate width.

## 13.4 Interaction policy

Only scientifically predeclared interactions enter the first ladder. Candidate interactions are checkpoint x remaining heating; season x snow; floor_active x signed margin; low cloud x DSWRF; T850 x cross-barrier wind; HPBL x sensible flux; CAPE x CIN; precipitation x peak lead; and temperature trend departure x remaining heating. Tensor-product or factor-smooth forms are used only when sample support is adequate. The model must not search arbitrary pairwise interactions across the full panel.

# 14. Missingness, leakage, and acceptance gates

## 14.1 Missingness semantics

| **Condition** | **Required behavior** |
|:--:|----|
| Critical key/cycle ambiguity | Fail row closed; do not guess. |
| One optional field missing | Null field and all dependent composites; set field-specific missing flag. |
| MADIS missing floor | Canonical floor baseline remains null; raw-parent fallback receives a separate variant ID. |
| No predecessor cycle | All revision values null; revision_unavailable_by_design = 1. |
| No event before peak | Event flag = 0; onset time null with no_event = 1, not an arbitrary large number. |
| Insufficient trend reports | Trend null with n_obs, max_gap, and reason code. |
| Cross-product cycle mismatch | Do not compute cross-product composites; branch-specific flag/failure. |
| Unsupported GRIB semantics | Quarantine source object and fail affected feature; never reinterpret accumulation as snapshot. |

## 14.2 Leakage tests

- Every HRRR source object's legal availability is \<= issue_time_utc under the frozen emulator or actual first-seen ledger.

- Every MADIS observation used by a historical checkpoint has observationTime \<= t; live uses receiptTime \<= t.

- No training feature reads CLI/Weather.com truth, final daily summaries, later market prices, or later checkpoints.

- All future values are forecasts from the selected legal cycle; no future observation or later-cycle valid-time mosaic is present.

- Rows from one target day remain in the same rolling-origin fold, including all six checkpoints.

- Any normalization, imputation, smooth selection, threshold tuning, or calibration is fit inside the training window.

- Historical QC features are verified as as-of-safe or excluded from model eligibility.

## 14.3 Source and panel acceptance tests

| **ID** | **Gate** | **Pass condition** |
|:--:|----|----|
| A01 | Exact key uniqueness | One cycle manifest row per target/product/cycle; one checkpoint row per day/checkpoint. |
| A02 | Selected-cycle parity | Feature bundle cycle equals primary Q15 baseline cycle; mismatch never silent. |
| A03 | Inventory stability | All 44 hourly and 14 subhourly selectors resolve on representative dates/version strata. |
| A04 | Step semantics | Snapshot/average/accumulation interval fields match expected metadata. |
| A05 | Unit round trip | Known sample values convert to canonical units and reconstruct native values within tolerance. |
| A06 | Spatial geometry | BI weights sum to one; station era and tile center match Layer 1. |
| A07 | Temporal support | CUR/PK/PRE operators use only named same-cycle valid times; coverage fraction recorded. |
| A08 | Revision common support | New and previous cycles evaluated on identical times and operators. |
| A09 | MADIS cutoff | No observation timestamp exceeds checkpoint; live receipt cutoff tested separately. |
| A10 | Candidate geometry | Known integer-C cases reproduce singleton/dual Fahrenheit sets exactly. |
| A11 | No truth in inference | Feature schema rejects target/residual/final-summary names. |
| A12 | Reproducibility | Second build from sealed inputs is byte- or value-identical under declared ordering. |
| A13 | Cost ledger | Requests, bytes, extracted values, cache hits, retries and quarantines reconcile. |
| A14 | Model-view masks | V1, V2 and V3 permissions are machine-readable and unit tested. |

# 15. Acquisition plan and cost controls

## 15.1 Request planner

8.  Read Layer-1 selected cycles and Q15 peak times; construct the deduplicated retained-cycle set per target day.

9.  Build required valid-time unions by product, cycle, field density class, checkpoint, and peak window.

10. Inspect .idx metadata before downloading; select by full GRIB identity rather than record number.

11. Range-fetch only required messages, verify response and GRIB inventory, extract BI/NN/3x3/9x9 values, then discard message bytes after durable write and hash reconciliation.

12. Write append-only partitioned long tables by target year/month and cycle; resume only after verifying partition manifests and hashes.

13. Generate checkpoint_features deterministically from long tables; never reacquire merely to change a summary formula.

## 15.2 Bounded scale

The nominal six-checkpoint design contains only four distinct selected cycles under the standard mapping. Over 2,042 target days, that is at most 8,168 day-cycle bundles per product before fallbacks and extended-cycle horizon rules, not 12,252 independent checkpoint downloads. The planner must deduplicate identical cycle/valid-time/message requests across checkpoints.

Storage should consist mainly of extracted point/tile trajectories and manifests, not full-domain GRIB files. Network cost remains real because each GRIB message covers the domain; temporal-density classes therefore matter. A pilot must record bytes per message family and extrapolate the full run before authorization.

## 15.3 Required pilot before full history

| **Pilot stratum** | **Minimum coverage** | **Purpose** |
|:--:|----|----|
| Season | At least one week each in DJF, MAM, JJA, SON | Field ranges, missingness, solar/snow/convective regimes |
| HRRR dates | Representative early/middle/late archive dates | Inventory and encoding stability |
| Checkpoint/cycle | All six checkpoints and each retained cycle position | Deduplication and revision construction |
| MADIS | Normal, gap, dual/singleton, precip/cloud days | Observation schema and quantization behavior |
| Spatial | Both KDEN coordinate eras | Layer-1 parity and tile centering |

The pilot produces an evidence memo with selector hit rates, units, min/max/quantiles, bytes and wall time, missingness, and sample derived features. Full acquisition proceeds only after extrapolated storage/time is accepted and no unresolved semantic mismatch remains.

# 16. Deferred and prohibited features

## 16.1 Deferred research extensions

- Cycles older than the earliest selected cycle, including c06 for pre-09:00 causal innovations;

- newer incomplete cycles or Policy-C partial-run features;

- 80-m wind, friction velocity, beam/diffuse radiation, MCDC/HCDC, cloud base/top, 500-mb height, vertical motion, and alternative CAPE/CIN definitions;

- pressure-level/native-level expansion beyond the constrained wrfsfcf universe;

- external station networks, radar mosaics, satellite retrievals, soil analyses, NBM, LAMP, or RRFS;

- one-minute OMO and advanced interval-aware filtering;

- learned spatial convolutions or raw 2-D grids;

- market price/order-book features in any meteorological training view.

## 16.2 Prohibited constructions

- 925- or 1000-mb local-state predictors at KDEN, because those nominal pressure surfaces are terrain-problematic or below ground;

- cross-cycle spliced trajectories, later-cycle backfills, or forecast values selected after observing Y;

- simple HRRR cloud-percent minus ASOS cloud-category arithmetic;

- wind-direction subtraction in degrees;

- differences of accumulation or hourly-maximum records as if they were snapshots;

- using R_high as a definitely achieved floor or deterministically adding 1 F to dual-candidate reports;

- treating six checkpoint rows as six independent target days;

- feature promotion because of in-sample MAE or backtest PnL alone.

## 16.3 Promotion standard

Promote only for repeatable out-of-fold gains in probabilistic scores or calibration. A useful g_sigma field need not lower MAE. Trading P&L follows meteorological selection and never defines the target.

# Appendix A. Exact wrfsfcf acquisition registry

The table below is the v1 source freeze. GRIB selection must use parameter, level/layer, and step/interval metadata. The H identifiers are project registry IDs, not official record numbers. DPT + PRES is retained and 2-m SPFH is derived, avoiding a redundant raw message.

| **ID** | **Param** | **Level** | **Step** | **Unit** | **Density** | **Spatial** | **Operators** | **Role** |
|:--:|----|----|----|----|----|----|----|----|
| H01 | HGT | 700 mb | SNAP | gpm | SPARSE | BI+3x3 | CUR,PK,DPK | mu: thickness; sigma: regime |
| H02 | TMP | 700 mb | SNAP | K | SPARSE | BI+3x3 | CUR,PK,DPK,GRAD | mu: thermal depth/advection |
| H03 | DPT | 700 mb | SNAP | K | SPARSE | BI | CUR,PK,DPK | mu/sigma: entrainment/cloud potential |
| H04 | UGRD | 700 mb | SNAP | m s-1 | SPARSE | BI | CUR,PK,DPK | mu: flow; sigma: transition |
| H05 | VGRD | 700 mb | SNAP | m s-1 | SPARSE | BI | CUR,PK,DPK | mu: flow; sigma: transition |
| H06 | HGT | 850 mb | SNAP | gpm | SPARSE | BI+3x3 | CUR,PK,DPK | mu: 850-700 thickness |
| H07 | TMP | 850 mb | SNAP | K | SPARSE | BI+3x3 | CUR,PK,DPK,GRAD | mu: primary low-level thermal state |
| H08 | DPT | 850 mb | SNAP | K | SPARSE | BI | CUR,PK,DPK | mu/sigma: mixed-layer moisture |
| H09 | UGRD | 850 mb | SNAP | m s-1 | SPARSE | BI | CUR,PK,DPK | mu: cross-barrier advection |
| H10 | VGRD | 850 mb | SNAP | m s-1 | SPARSE | BI | CUR,PK,DPK | mu: along-barrier flow |
| H11 | GUST | surface | SNAP | m s-1 | PATH | BI | CUR,PREMAX | mu/sigma: mixing or transition |
| H12 | MSLMA | mean sea level | SNAP | Pa | SPARSE | BI+3x3 | CUR,PK,DPK,GRAD | mu/sigma: synoptic/frontal context |
| H13 | PRES | surface | SNAP | Pa | SPARSE | BI | CUR,PK,DPK | mu/sigma: pressure state and bridge |
| H14 | HGT | surface | SNAP/static | gpm | STATIC | grid lineage | ONCE | audit only; station-grid geometry |
| H15 | TMP | surface | SNAP | K | SPARSE | BI | CUR,PK,DPK | mu: skin-air thermal contrast |
| H16 | TMP | 2 m AGL | SNAP | K | REUSE L1 | BI+NN | FULL Q15/H PATH | baseline geometry and innovations |
| H17 | DPT | 2 m AGL | SNAP | K | SPARSE | BI | CUR,PK,DPK | mu/sigma: moisture; derive Q/RH |
| H18 | UGRD | 10 m AGL | SNAP | m s-1 | SPARSE | BI | CUR,PK,PREMEAN | mu/sigma: flow and wind bridge |
| H19 | VGRD | 10 m AGL | SNAP | m s-1 | SPARSE | BI | CUR,PK,PREMEAN | mu/sigma: flow and wind bridge |
| H20 | MSTAV | 0 m underground | SNAP | % | SPARSE | BI | CUR | mu/sigma: moisture-availability regime |
| H21 | SHTFL | surface | SNAP | W m-2 | PATH | BI | CUR,PREMEAN,PREINT | mu: sensible heating |
| H22 | LHTFL | surface | SNAP | W m-2 | PATH | BI | CUR,PREMEAN,PREINT | mu: evaporative partition |
| H23 | GFLUX | surface | SNAP | W m-2 | PATH | BI | CUR,PREMEAN,PREINT | mu: ground storage/release |
| H24 | HPBL | surface | SNAP | m | PATH | BI | CUR,PK,PREMAX,GROWTH | mu/sigma: mixing depth |
| H25 | WEASD | surface | SNAP | kg m-2 | SPARSE | BI | CUR | mu/sigma: snow-water state |
| H26 | SNOWC | surface | SNAP | % | SPARSE | BI | CUR | mu/sigma: snow-cover/albedo regime |
| H27 | SNOD | surface | SNAP | m | SPARSE | BI | CUR | mu/sigma: snow depth/density context |
| H28 | TCDC | boundary-layer cloud | SNAP | % | PATH | BI+9x9 | CUR,PREMEAN,PREMAX,FRAC,SPREAD | mu/sigma: low-level cloud |
| H29 | LCDC | low cloud | SNAP | % | PATH | BI+9x9 | CUR,PREMEAN,PREMAX,FRAC,SPREAD | mu/sigma: solar suppression |
| H30 | TCDC | entire atmosphere | SNAP | % | PATH | BI+9x9 | CUR,PREMEAN,PREMAX,FRAC,SPREAD | mu/sigma: total cloud regime |
| H31 | DSWRF | surface | SNAP | W m-2 | PATH | BI+9x9 | CUR,PREMEAN,PREINT,NORM,SPREAD | mu/sigma: incoming solar energy |
| H32 | DLWRF | surface | SNAP | W m-2 | PATH | BI | CUR,PREMEAN,PREINT | mu: downward longwave |
| H33 | USWRF | surface | SNAP | W m-2 | PATH | BI | CUR,PREMEAN,PREINT | mu: reflected shortwave |
| H34 | ULWRF | surface | SNAP | W m-2 | PATH | BI | CUR,PREMEAN,PREINT | mu: surface longwave loss |
| H35 | CFNSF | surface | SNAP | W m-2 | PATH | BI+9x9 | CUR,PREMEAN,PREINT,SPREAD | mu/sigma: HRRR cloud solar forcing |
| H36 | REFC | entire atmosphere | SNAP | dBZ | PATH | BI+3x3+9x9 | CUR,PREMAX,COVER20,ONSET | sigma; mu if heating interrupted |
| H37 | PRATE | surface | SNAP | kg m-2 s-1 | PATH | BI+9x9 | CUR,PREMAX,EVENT,COVER | sigma; mu if precip begins |
| H38 | APCP | surface | HACC | kg m-2 | PATH | NN+9x9 | PRESUM,EVENT,COVER | sigma: accumulated precipitation |
| H39 | PWAT | entire atmosphere | SNAP | kg m-2 | SPARSE | BI | CUR,PK,DPK | mu/sigma: column moisture |
| H40 | VIS | surface | SNAP | m | PATH | BI+9x9 | CUR,PREMIN | mu/sigma: fog/haze/stable regime |
| H41 | AOTK | entire atmosphere | SNAP | 1 | SPARSE | BI+9x9 | CUR,PK,PREMAX | sigma/conditional mu: smoke regime |
| H42 | HGT | cloud ceiling | SNAP | gpm | PATH | BI+9x9 | CUR,PREMIN,BELOW_THRESH | mu/sigma: low-cloud geometry |
| H43 | CAPE | surface | SNAP | J kg-1 | PATH | BI+9x9 | CUR,PREMAX | sigma: pre-convective potential |
| H44 | CIN | surface | SNAP | J kg-1 | PATH | BI+9x9 | CUR,PREMIN | sigma: convective inhibition |

## Appendix A.1 Derived hourly composites

| **Composite** | **Inputs** | **Exact convention** | **Primary role** |
|:--:|----|----|----|
| specific_humidity_2m | DPT2m + PRES | Thermodynamic conversion under versioned formula; retain source units and QC | moisture without raw SPFH download |
| rh_2m | TMP2m + DPT2m | Versioned saturation-vapor-pressure formula | interpretation/candidate only |
| thickness_850_700 | HGT700 - HGT850 | same cycle, valid time, spatial rule | thermal column |
| temp_lapse_850_700 | TMP850 - TMP700 | K difference, not geometric lapse unless divided by height | thermal depth |
| dd_850 / dd_700 | TMP - DPT | K | moisture/entrainment |
| shear_850_10 | U/V850 - U/V10 | component-wise; derive magnitude separately | mixing/flow transition |
| adv_t850 | U/V850 + 3x3 T850 gradient | earth-relative wind and map-distance central gradient, K h-1 | air-mass change |
| surface_air_contrast | TMPsurface - TMP2m | same cycle/time/spatial extraction | land-atmosphere coupling |
| net_sw | DSWRF - USWRF | W m-2; integrate with same path | absorbed shortwave |
| net_lw | DLWRF - ULWRF | W m-2; integrate with same path | net longwave |
| net_rad | net_sw + net_lw | W m-2; MJ m-2 after integration | radiative energy |
| evaporative_fraction | LHTFL/(SHTFL+LHTFL) | null/flag when denominator magnitude below threshold or signs inconsistent | energy partition |
| bowen_ratio | SHTFL/LHTFL | guard small denominator; winsorization fit in training only | energy partition challenger |
| snow_density_proxy | WEASD/SNOD | guard zero depth; audit units | snow-state consistency |

# Appendix B. Exact wrfsubhf acquisition registry

Official wrfsubhf files repeat record blocks at 15-minute valid times. Select by full message identity and interval, because record numbers change across blocks/files. The v1 set intentionally excludes duplicate visible-beam and longwave snapshot families.

| **ID** | **Field** | **Time semantics** | **Unit** | **Spatial** | **Panel use** |
|:--:|----|----|----|----|----|
| Q01 | REFC \| entire atmosphere | snapshot every 15 min | dBZ | BI+3x3+9x9 | max, onset, coverage before peak |
| Q02 | VIS \| surface | snapshot every 15 min | m | BI+9x9 | current/min; fog-transition context |
| Q03 | GUST \| surface | snapshot every 15 min | m s-1 | BI | current/max; observation bridge |
| Q04 | PRES \| surface | snapshot every 15 min | Pa | BI | current/tendency; innovation |
| Q05 | TMP \| 2 m | snapshot every 15 min | K | BI+NN | reuse existing Q15 full path; no re-download |
| Q06 | DPT \| 2 m | snapshot every 15 min | K | BI | current/tendency/path; innovation |
| Q07 | UGRD \| 10 m | snapshot every 15 min | m s-1 | BI | trajectory and wind innovation |
| Q08 | VGRD \| 10 m | snapshot every 15 min | m s-1 | BI | trajectory and wind innovation |
| Q09 | UGRD \| 10 m | preceding 5-min average | m s-1 | BI | closer time support for ASOS wind bridge |
| Q10 | VGRD \| 10 m | preceding 5-min average | m s-1 | BI | closer time support for ASOS wind bridge |
| Q11 | DSWRF \| surface | preceding 15-min average | W m-2 | BI+9x9 | solar energy integral/ramp; not snapshot DSWRF |
| Q12 | PRATE \| surface | snapshot every 15 min | kg m-2 s-1 | BI+9x9 | onset/intensity/coverage |
| Q13 | APCP \| surface | preceding 15-min accumulation | kg m-2 | NN+9x9 | interval amount; never difference as a snapshot |
| Q14 | HGT \| cloud ceiling | snapshot every 15 min | gpm | BI+9x9 | low-ceiling onset/minimum |

# Appendix C. Exact MADIS raw-variable registry

| **ID** | **Code** | **Observed quantity** | **Raw preservation** | **Derived use** |
|:--:|----|----|----|----|
| M01 | T | Air temperature | raw whole deg C; provider/QC flags | Temperature candidate interval, runmax floor, slopes, innovations |
| M02 | TD | Dewpoint | raw reported value/resolution; QC | Dewpoint depression, tendency, HRRR departure |
| M03 | P | Station pressure | raw value plus derived/provenance flag | Pressure tendency and departure; do not substitute MSLP |
| M04 | FF, DD | Wind speed/direction | raw values, averaging semantics, QC | Derive earth-relative U/V, cross-barrier flow, vector shifts |
| M05 | FFGUST | Wind gust | raw value and QC | Rolling maximum and HRRR gust departure |
| M06 | VIS | Visibility | raw value and QC | Rolling minimum, fog/haze state, HRRR departure |
| M07 | PCPRATE | Precipitation rate | raw/converted value and QC | Onset/intensity; compare categorically/numerically when aligned |
| M08 | PCP1H | One-hour accumulation | window metadata required | Hourly precip departure; note HFMETAR window convention |
| M09 | SKYCOV | Sky-cover layers | up to layer array; preserve category | Ordinal/interval cloud disagreement; never percent subtraction |
| M10 | SKYCVLB | Sky-layer base | layer array and units | Ceiling/base diagnostics with ASOS vertical-limit caveat |
| M11 | WX/PW | Present weather | raw codes | Precipitation/fog/smoke transition flags |

## Appendix C.1 Observation-summary naming examples

| **Example column** | **Meaning** |
|:--:|----|
| obs_t_latest_low_f / high_f / mid_f | Latest legal temperature candidate interval and midpoint |
| obs_t_runmax_low_f / high_f | Checkpoint R_low/R_high |
| obs_t_slope_ts_60m_cph | Theil-Sen temperature slope over past 60 minutes in C per hour |
| obs_p_slope_ts_120m_hpa_ph | Theil-Sen station-pressure tendency over 120 minutes |
| obs_u_mean_60m_mps / obs_v_mean_60m_mps | Vector-component means; do not average direction angles |
| obs_wind_shift_60m_mps | Magnitude of difference between recent and earlier mean U/V vectors |
| dep_t_mid_curcycle_f | Latest temperature midpoint minus selected-cycle Q15 estimate |
| dep_t_slope_60m_cph | Observed minus selected-cycle modeled 60-minute heating slope |
| innov_t_low_f / innov_t_high_f | Causal forecast innovation interval for one observation |
| obs_cloud_opaque_mismatch | ASOS BKN/OVC while HRRR low cloud is below frozen threshold, or converse |
| obs_latest_age_min / obs_max_gap_120m | Staleness and internal completeness |

# Appendix D. Naming grammar and machine-readable contracts

{source}\_{quantity}\_{spatial}\_{temporal}\_{window}\_{unit}

| **Token** | **Allowed examples** | **Rule** |
|:--:|----|----|
| source | b, hrrr_h, hrrr_q, obs, dep, innov, rev | Distinguishes baseline, hourly, subhourly, observation, departure, causal innovation, revision |
| quantity | t850, dswrf, hpbl, refc, floor_margin | Stable registry vocabulary; no ad hoc aliases |
| spatial | bi, nn, n3_mean, n9_sd, n9_max | Omit only when inherently nonspatial |
| temporal | cur, pk, dpk, premean, preint, premax, onset | Must map to named operator |
| window | 30m, 60m, 120m, prepeak, prepeak_p2h | Explicit when operator needs support |
| unit | f, c, k, mps, hpa, wm2, mjm2, pct, min | Canonical unit suffix required for numeric columns |

## Appendix D.1 Minimum cycle_manifest columns

target_day, product, cycle_init_utc, cycle_rank_within_retained, selected_by_checkpoint_ids, availability_policy_id, emulated_available_time_utc, actual_first_seen_utc, availability_basis, horizon_class, required_valid_start_utc, required_valid_end_utc, complete_flag, fallback_reason, source_uri_redacted, source_inventory_hash, hrrr_version, retrieval_run_id, created_at_utc.

## Appendix D.2 Minimum hrrr_point_trajectory columns

target_day, product, cycle_init_utc, valid_time_utc, forecast_lead_min, field_registry_id, parameter, level, step_type, interval_start_utc, interval_end_utc, native_unit, canonical_unit, station_coord_era, spatial_stat, value, tile_shape, coverage_flag, source_hash, derivation_version.

## Appendix D.3 Minimum madis_observation_sequence columns

station_id, target_day, observation_time_utc, receipt_time_utc, availability_time_used_utc, availability_basis, report_type, source_file_hash, variable_code, raw_value, raw_unit, resolution, provider_qc, madis_qc_stage_flags, local_asof_qc, derived_flag, temp_candidate_low_f, temp_candidate_high_f, causal_cycle_init_utc, causal_expected_value, selected_cycle_expected_value, innovation_low, innovation_high.

# Appendix E. Implementation handoff checklist

14. Freeze this document's field and operator registries in code constants with semantic version FEATURE_PANEL_V1_0.

15. Audit representative wrfsfcf and wrfsubhf .idx files; produce selector-resolution report before full acquisition.

16. Read Layer-1 checkpoint keys, selected cycles, station coordinate eras, Q15 paths, and peak times without mutating sealed outputs.

17. Construct deduplicated request plan and projected byte/time ledger; obtain owner approval after pilot extrapolation.

18. Build cycle_manifest first and fail closed on ambiguity.

19. Acquire/extract HRRR long trajectories with unit, interval, spatial, and source provenance.

20. Extend MADIS acquisition to the frozen raw variables while preserving existing temperature-floor outputs unchanged.

21. Build selected-cycle departures and bounded causal innovation sequence as separate columns/records.

22. Generate checkpoint_features and training_labels separately; enforce schema-level target exclusion.

23. Run A01-A14 acceptance gates and a byte/value reproducibility rerun.

24. Only then fit checkpoint-specific structural and observation-augmented location-scale GAMs under rolling-origin day-grouped validation.

# Appendix F. Source registry

| **ID** | **Source** | **Use / URL** |
|:--:|----|----|
| P1 | KDEN Layer 1 Scientific Record v1.0 | Frozen Layer-1 results, downstream GAM contract, floor geometry, checkpoints, validation and limitations. |
| P2 | KDEN Layer 1 Baseline Forecast Specification v3.0 | Policy A, 105-minute illustrative cycle mapping, strict future window, source lineage and no-splice rules. |
| P3 | Scientific Audit of the HRRR wrfsfcf Field Universe for KDEN Tmax MOS | 40 KEEP / 40 MAYBE / 93 DROP evidence and physical error pathways; used as inspiration, not verbatim authority. |
| P4 | KDEN Probabilistic MOS Product Direction White Paper v2.0 | Location-scale architecture, MADIS/state-space concept, issue-time panel and commercial validation. |
| P5 | KDEN Tmax Truth Layer - Weather.com and IEM Coding Handoff v1.0 | Target truth isolation, source regimes and historical exception policy. |
| E1 | NCEP HRRR wrfsfcf02 inventory | https://www.nco.ncep.noaa.gov/pmb/products/hrrr/hrrr.t00z.wrfsfcf02.grib2.shtml |
| E2 | NCEP HRRR wrfsubhf02 inventory | https://www.nco.ncep.noaa.gov/pmb/products/hrrr/hrrr.t00z.wrfsubhf02.grib2.shtml |
| E3 | NOAA MADIS surface variable notes | https://madis.ncep.noaa.gov/sfc_notes.shtml |
| E4 | NOAA/NWS ASOS program and reported elements | https://www.weather.gov/asos |
| E5 | JMA combined bias correction and Kalman-filter study (2024) | https://www.jstage.jst.go.jp/article/jmsj/102/4/102_2024-020/\_html/-char/en |
| E6 | Strengths and Weaknesses of MOS, Running-Mean Bias Removal, and Kalman Filter Techniques over the Western U.S. | https://journals.ametsoc.org/view/journals/wefo/22/6/2007waf2006084_1.xml |
| E7 | The High-Resolution Rapid Refresh, Parts I-II | https://journals.ametsoc.org/view/journals/wefo/37/8/WAF-D-21-0151.1.xml and https://journals.ametsoc.org/view/journals/wefo/37/8/WAF-D-21-0130.1.xml |

# Appendix G. Final scientific interpretation

This panel does not assume that every retained field will improve MAE. It preserves the smallest source universe judged capable of explaining the main KDEN Tmax residual pathways while also identifying when the forecast distribution should widen. The structural GAM asks when HRRR's remaining-day trajectory is systematically biased. The observation GAM asks whether today's realized atmosphere is already departing from that trajectory. The state-space challenger asks whether the order and persistence of those departures add information beyond checkpoint summaries.

The architecture is commercially aligned but meteorologically insulated from the market. It creates whole-degree probabilities whose quality can later be compared with executable Kalshi prices. Profitability remains an external validation layer requiring fees, spread, fill and risk. The panel's immediate success criterion is honest, stable, issue-time-correct probability improvement.
