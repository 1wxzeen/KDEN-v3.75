# KDEN v3.75 Step 04.5 Feature Universe Study

- Status: Research brief and scientific handoff
- Project: KDEN v3.75 HRRR-only intraday Tmax probability system
- Position in workflow: After Step 04 PASS and before full-history Steps 05 and 06
- Primary reader: Meteorological research agent working inside this repository

## 1. Decision requested from this study

Step 04 established that the current H01-H44 and Q01-Q14 acquisition plan is technically valid, but its extrapolated full-history runtime is approximately 996 hours, or 41.5 days, at the selected eight-worker profile. Step 04.5 must determine whether a smaller HRRR source-message universe can preserve the information needed for serious KDEN Tmax probability modeling while materially reducing acquisition time.

This is a scientific scope study, not a request to make an arbitrary engineering cut. The desired result is the smallest defensible union of hourly and subhourly source fields that retains KDEN-specific information about why HRRR 2-m temperature and daily Tmax forecasts can fail.

The retained union must support three initial model families:

1. distributional GAM or GAMM MOS;
2. Analog Ensemble, abbreviated AnEn;
3. ordinal-hazard or related ordered-distribution modeling.

It should also avoid knowingly excluding a source field that provides stable, unique value to another downstream model that proves genuinely competitive under the same leakage-safe evaluation. Hypothetical future usefulness by itself is not sufficient reason to retain a field.

The guiding product objective is numerical prediction of the contract-authoritative KDEN whole-degree-Fahrenheit daily maximum early enough in the day to support decisions in Kalshi temperature markets. The meteorological research must therefore emphasize calibrated probability distributions, sharpness, and tail behavior at useful intraday issue times, not only average point-error reduction. Market prices, fills, and PnL must remain outside meteorological feature selection.

## 2. Authority and working boundary

`PROJECT.md` is the controlling current project specification. Older documents under `1. research/` and all material under `previous codebases/` are evidence and historical context, not current instructions.

The research agent may read the entire repository. The agent may create research documentation only. Unless the owner gives separate authority, the agent must not edit:

- `PROJECT.md`;
- code under `src/` or `tests/`;
- `config/`, `registries/`, or `schemas/`;
- sealed request plans or canonical archives;
- any PASS record under `state/`;
- anything under `previous codebases/`.

The research agent must not import or execute the fossilized previous codebases. They may be inspected to understand prior scientific and engineering decisions.

Step 04 remains a valid PASS for the original 58-field engineering pilot. Step 04.5 does not silently invalidate or rewrite it. If the owner later accepts a reduced universe, a successor registry and new request plans must be created explicitly, followed by a bounded confirmation pilot and new extrapolation before Steps 05 and 06 begin.

Long-running acquisition and modeling experiments are owner-run. The research agent should specify any required experiment, cohort, inputs, commands to be implemented later, and decision rule, but should not launch a long-running job.

## 3. What remains frozen and what is open

### 3.1 Frozen unless the owner separately reopens it

- HRRRv4 only for this branch.
- Historical target dates 2021-01-01 through 2026-09-11 inclusive.
- The fixed target window `W[d] = [07:00Z_d, 07:00Z_{d+1})`.
- The previous-local-day c23 anchor plus target-local-day c00 through c14 schedule.
- Native UTC cycle identities and DST-aware `America/Denver` conversion.
- FH00 inclusion and the `TARGET_WINDOW` lead ceiling.
- Acquisition of independent, coherent forecast cycles without cross-cycle splicing.
- Historical availability emulation and strict issue-time legality.
- Independent hourly and subhourly product identities.
- KDEN coordinate-era provenance and fail-closed source semantics.
- Separation of source acquisition, derived features, model fitting, truth, and market data.
- No MADIS or other observations in the v3.75 source branch.
- No lossy source substitution or silent interval reinterpretation.

The minimum operational emphasis for this study is approximately 02:00 through 14:00 `America/Denver`, as requested by the owner. The current project specification supports a somewhat broader intraday range, approximately through 16:00, and includes cycles through local c14. Step 04.5 may describe the distinction, but it must not remove cycles or shorten the current issue-time envelope without a separate owner decision.

### 3.2 Open scientific questions

- Which H01-H44 source messages remain necessary?
- Which Q01-Q14 source messages remain necessary?
- For which mechanisms does 15-minute within-cycle evolution add information beyond an hourly field, hourly tendency, spatial structure, and cycle-to-cycle revision?
- Which apparent redundancies are deterministic, and which become nonredundant in important KDEN regimes?
- What is the smallest shared acquisition union after model-specific selection?
- Do current centered BI, NN, 3x3, and 9x9 spatial supports adequately represent KDEN-specific terrain and upstream mechanisms?
- Which uncertainties cannot be resolved without a dedicated selection cohort?

## 4. Why Step 04.5 is necessary

### 4.1 The acquisition is network-bound

The completed Step 04 pilot processed 1,849 logical requests and accepted approximately 1.96 GB of source-range bytes. About 93 percent of measured time was spent fetching byte ranges. Decoding, extraction, Parquet writing, and ordinary bookkeeping were not the dominant costs.

The selected eight-worker profile achieved approximately 15.5 logical requests per second. It was only about 1.264 times as fast as four workers, so additional workers alone should not be assumed to reduce the runtime by another large factor.

The full sealed plan contains:

| Product | Native field-states before field expansion | Dynamic fields per state | Logical requests | Approximate share |
|---|---:|---:|---:|---:|
| `wrfsfcf` | 585,085 | 43, with H14 static | 25,158,656 | 45.25% |
| `wrfsubhf` | 2,173,943 | 14 | 30,435,202 | 54.75% |
| Total | - | - | 55,593,858 | 100% |

At the current extrapolated rate, one dynamic hourly field represents approximately 585,085 requests, about 1.05 percent of the plan or roughly 10.5 hours of first-order projected runtime. One subhourly field represents approximately 2,173,943 requests, about 3.91 percent of the plan or roughly 1.62 days. Actual savings must be estimated from field-specific bytes and timings because GRIB message sizes differ.

Both H and Q must be scrutinized. Q has the larger marginal acquisition cost, but high cost is not evidence that a Q field is scientifically redundant, and lower cost is not a reason to leave redundant H fields untouched.

### 4.2 Other investigated optimizations are not sufficient by themselves

The project already uses verified byte-range retrieval, exact-adjacent coalescence, persistent HTTPS sessions, bounded concurrency, atomic work units, and transient GRIB disposal. Removing QC or lineage would mainly reduce auditability, not the dominant network time.

Public Zarr alternatives were investigated and rejected for the present scientific contract. The traditional HRRR Zarr archive lacks `wrfsubhf`, contains lossy early-period values, and has known missing forecast-variable stores. Newer virtual HRRR Zarr products remain hourly, expose no Q15 forecast product, and do not provide the necessary exact H/Q parity. Building a private Zarr would still require the initial GRIB acquisition and therefore would not solve the 2021-2026 first-pass download cost.

Source-object-centric range coalescing, bounded-gap range bundling, adaptive concurrency, and running computation closer to the archive remain valid engineering investigations. Step 04.5 should not assume they will be sufficient, and it should not redesign them. Its responsibility is the meteorological and statistical value of the source universe.

## 5. What the historical work did

### 5.1 D1 and Layer 1

The early D1 work was intentionally narrow. It tested selected thermal predictors on a sunny-day subset and established that KDEN Tmax contains a strong, physically coherent lower-tropospheric thermal signal. It did not establish a production model for all weather regimes. Clouds, radiation, mixing, wind transitions, fronts, moisture, snow, ground state, convection, and other mechanisms remained incompletely represented.

Layer 1 then created issue-time-indexed HRRR temperature baselines and, in the older branch, MADIS-derived observed floors. Its six-way bakeoff was built around six issue checkpoints and a probability-modeling handoff. It established the need to model the center and dispersion of the remaining error, not just MAE.

### 5.2 The Universal Issue-Time Feature Panel

The historical Universal Issue-Time Feature Panel was designed primarily for structural and observation-augmented location-scale GAMs at six checkpoints:

- 09:00;
- 09:45;
- 10:00;
- 10:45;
- 11:00;
- 11:45 `America/Denver`.

Under the illustrative 105-minute availability mapping, those checkpoints ordinarily reduced to approximately four distinct selected cycles per day. The planner deduplicated shared checkpoint requests.

The historical design acquired 44 hourly message identities and 14 subhourly families, but it did not acquire every field at every possible state in the way v3.75 currently plans to do. It used:

- `STATIC` for surface height;
- `REUSE_L1` for previously acquired 2-m temperature paths;
- `SPARSE` valid times for slowly varying or checkpoint/peak state variables;
- `PATH` valid times for mechanisms such as radiation, fluxes, boundary-layer evolution, clouds, reflectivity, precipitation, visibility, ceiling, CAPE, and CIN;
- subhourly paths only where intrahour evolution or observation matching was considered valuable.

The old study described its H/Q universe as the minimum serious source universe for the problem it had defined. It had already removed a deterministic raw redundancy by deriving 2-m specific humidity from dewpoint and pressure, treated surface height as static, and deferred a much larger set of MAYBE fields.

### 5.3 Why that work remains valuable

The old field audit and scientific specification remain strong priors. They contain:

- a physical error-pathway classification;
- exact GRIB identities and interval semantics;
- the original rationale for all H and Q families;
- candidate location and scale roles;
- derived composite definitions;
- KDEN-specific cautions about terrain-problematic pressure levels;
- a first cross-barrier wind proxy using earth-relative U;
- rules for snapshots, averages, and accumulations;
- evidence about the limited effective sample size of approximately 2,000 independent target days.

The study should begin there rather than rebuilding the HRRR field universe from scratch.

## 6. Why the historical selection cannot simply be applied to v3.75

The historical solution answered a different question.

### 6.1 Different temporal objective

The old design optimized around six mid-morning checkpoints and their selected cycles. KDEN v3.75 must reconstruct legal HRRR information states across a much broader rolling intraday window, with particular importance from approximately 02:00 through 14:00 local. A field that was unnecessary near a known mid-morning checkpoint may be useful for identifying an early-day transition, while a field selected for a checkpoint-specific future-to-peak operator may be redundant in a rolling model.

### 6.2 Different cycle density

KDEN v3.75 ordinarily retains 16 cycles per product per target day: previous-local c23 and target-local c00 through c14. Spring-forward and fall-back dates contain 15 and 17 cycles, respectively. Every cycle begins at FH00 and retains native states only through the target-window ceiling.

The cycle richness is intentional. It permits a historical reconstruction of what the newest legally available HRRR run would have implied throughout the day, supports cycle-revision features, and avoids another acquisition when the final issue grid is chosen.

Step 04.5 must not treat issue rows and model cycles as interchangeable. HRRR initializes a new model cycle hourly. `wrfsubhf` supplies 15-minute valid-time states inside that hourly model run; it does not introduce a new model initialization every 15 minutes. Many consecutive live issue times will use the same newest legal cycle.

### 6.3 Different temporal-density policy

In v3.75 the old `SPARSE` and `PATH` labels were removed from acquisition control. Every dynamic H field currently follows the full native hourly path, and every retained Q field follows the native 15-minute path, subject to `TARGET_WINDOW`.

That expansion makes cadence necessity a first-class selection question. For each Q field, the study must test whether the mechanism requires 15-minute within-cycle resolution or is represented sufficiently by an hourly counterpart, hourly tendency, spatial statistic, and cycle revision. For each H field, the study must still ask whether the field itself adds unique information.

An hourly field can sometimes describe a fairly rapid mechanism through its current state, short tendency, and cross-cycle revision. It cannot automatically reproduce an intrahour onset, duration, maximum, average, or accumulation. Sufficiency must be established per mechanism and per issue-time range.

### 6.4 Different model universe

The historical field panel centered on GAM-based residual modeling and MADIS-conditioned extensions. KDEN v3.75 is HRRR-only and must support GAM/GAMM, AnEn, and ordinal-hazard modeling from the start.

- AnEn is sensitive to irrelevant and duplicated distance coordinates.
- GAM/GAMM can suffer from correlated smooths, concurvity, unstable attribution, and excessive effective degrees of freedom.
- Ordinal-hazard models can suffer from redundant predictors, sparse integer outcomes, coefficient instability, and poor calibration.

Regularization reduces these problems but does not make redundant inputs desirable.

### 6.5 Different information boundary

The historical observation-augmented design could detect that the realized atmosphere was departing from HRRR through MADIS observations and forecast-observation innovations. KDEN v3.75 deliberately excludes MADIS. Its predictors must therefore indicate, using HRRR alone, when the forecast trajectory is in a KDEN regime where its temperature error distribution tends to shift or widen.

This changes the value of a field. A variable retained mainly as a close analogue to a MADIS observation may be less useful here. A variable that reveals forecast-internal regime uncertainty, spatial heterogeneity, cycle instability, or a KDEN-specific failure mechanism may be more important.

## 7. KDEN-specific meteorological framing

The study must be local to KDEN. It must not rank fields merely because they are commonly useful in generic surface-temperature models.

The core question for every retained source field is:

> Does this field help identify, early and legally, a KDEN-specific pathway by which the HRRR remaining-day 2-m temperature trajectory or its implied daily maximum can be biased, mistimed, or overconfident?

The owner has offered Chinook or downslope-wind behavior as an example of the required style of reasoning, not as a predetermined conclusion. The research agent should identify and support the actual important KDEN and Front Range mechanisms. Candidate lines of inquiry include, but are not limited to:

- downslope warming and drying, including Chinook-like or foehn-like regimes;
- upslope transitions, shallow cold-air intrusions, and cold-pool persistence;
- frontal passages, Denver-cyclone or lee-trough environments, and pressure/wind shifts;
- boundary-layer growth, entrainment, mixing depth, and surface coupling;
- lower-tropospheric thermal structure and horizontal thermal advection;
- snow cover, snow water, soil moisture, ground heat storage, and albedo feedbacks;
- low cloud, total cloud, solar suppression, longwave forcing, and cloud timing errors;
- convection, precipitation onset, evaporative cooling, and interrupted heating;
- smoke or aerosol regimes that alter solar heating;
- station-versus-grid elevation and terrain-representation effects;
- spatial heterogeneity or upstream conditions that a single KDEN grid-point value cannot reveal;
- cycle-to-cycle instability as a signal that the forecast distribution should widen.

These are research hypotheses. The agent must distinguish documented KDEN mechanisms, plausible but unverified mechanisms, and mechanisms shown not to matter.

### 7.1 Field identity versus spatial geometry

A KDEN-specific failure mechanism may be poorly represented because the wrong field was selected, because the field is sampled at the wrong cadence, or because the spatial support is inadequate. These are different problems.

For example, a centered 9x9 HRRR tile spans only a compact neighborhood around the station. A terrain-driven transition may depend on an upstream sector, cross-barrier gradient, foothills-to-plains contrast, or displaced corridor that is not summarized well by a centered mean or spread. The study should flag such cases explicitly.

Once a GRIB message is already being retrieved, extracting a different compact tile or a few additional displaced points does not multiply source-message network cost. It can increase local output size, computation, and schema complexity, but it may be more efficient than acquiring several correlated fields. The research agent may recommend spatial-contract experiments in documentation, but must not implement them.

### 7.2 Required mechanism-to-field map

At minimum, the study must evaluate the following current source families:

| Mechanism family | Current candidate source IDs |
|---|---|
| 700/850-mb thermal and flow structure | H01-H10 |
| Surface pressure, gust, skin/2-m state, and near-surface wind | H11-H19 |
| Land-surface energy and boundary-layer coupling | H20-H24 |
| Snow and ground regime | H25-H27 |
| Cloud and radiative forcing | H28-H35 |
| Reflectivity, precipitation, moisture, visibility, and aerosol | H36-H41 |
| Ceiling and convective stability | H42-H44 |
| Subhourly reflectivity, visibility, gust, pressure, temperature, and dewpoint | Q01-Q06 |
| Subhourly wind snapshots and five-minute averages | Q07-Q10 |
| Subhourly solar, precipitation rate/amount, and ceiling | Q11-Q14 |

The final research report should refine this coarse map into KDEN-specific failure mechanisms, source fields, possible derived summaries, issue-time relevance, and model roles.

## 8. What redundancy means in this study

The goal is to remove as much redundancy as possible without deleting information that matters conditionally. Pairwise correlation is evidence, not a decision rule.

The agent must consider at least these forms of redundancy:

### 8.1 Deterministic redundancy

One source can be reconstructed to the required precision from retained sources. The historical removal of raw 2-m specific humidity, derivable from dewpoint and pressure under a frozen formula, is the model example.

### 8.2 Duplicate physical representation

Two messages measure effectively the same state at similar levels or cadences, and one provides no stable incremental value. Potential examples must be tested rather than assumed, such as hourly versus subhourly surface pressure or two representations of near-surface wind.

### 8.3 Temporal redundancy

A Q trajectory may add no useful information beyond the H counterpart, hourly trajectory summaries, and cross-cycle revision. Conversely, a Q field may be essential if onset timing, interval magnitude, or a rapid transition changes the Tmax distribution.

### 8.4 Composite redundancy

Several fields may be needed together to construct a physically meaningful composite even when individual members are correlated. Examples include U/V vectors, 850-700 thickness, net shortwave/longwave radiation, and CAPE/CIN. Components must be evaluated as an atomic scientific group when dropping one would destroy the intended quantity.

### 8.5 Spatial redundancy

Multiple local fields may proxy the same regime, while a better spatial contrast from one retained message could contain the unique information. The agent must distinguish a redundant variable from an inadequate spatial operator.

### 8.6 Conditional or regime-specific nonredundancy

Two fields may be highly correlated in the annual sample but diverge during snow, smoke, convection, frontal, cloud-transition, upslope, or downslope regimes. A field may primarily affect conditional scale rather than the mean. Annual correlation and aggregate MAE can miss this value.

### 8.7 Weak correlation without predictive value

A field is not useful merely because it is statistically different from other fields. Weakly correlated noise, unstable relationships, or variables with no incremental out-of-sample probability skill should not survive solely for uniqueness.

Vector pairs and physically coupled components must not be broken by naive collinearity screening. In particular, do not independently discard one of U/V, a radiative component required by a retained energy composite, or one member of another predeclared physical pair without evaluating the resulting loss of physical meaning.

## 9. Source universe versus model feature vector

The study must not equate a retained source message with a final model coordinate.

One retained HRRR message can support multiple derived quantities, issue times, valid-time summaries, spatial statistics, and cycle revisions. Conversely, a raw trajectory flattened across fields and leads would be unsuitable as a direct model vector.

### 9.1 AnEn

AnEn should use a compact, training-fold-standardized distance representation. Candidate safeguards include learned or predeclared distance weights, grouping, whitening, PCA or another leakage-safe dimension reduction, and regime-aware distance definitions. Correlated features can otherwise double-count one physical mechanism and degrade neighbor quality.

The study must identify which source fields are required to construct plausible compact AnEn states. It must not require AnEn to use every retained source. An initial distance vector may be much smaller than the acquisition union.

### 9.2 GAM or GAMM

The GAM/GAMM assessment must treat location and scale separately. A field that does not reduce conditional mean error may still improve uncertainty calibration, tail width, or regime-dependent sharpness. Penalized smooths and shrinkage are appropriate, but field retention should be based on stable out-of-sample contribution and physical plausibility rather than in-sample significance.

Repeated issue rows from one target day are not independent observations. GAMM structure may address justified grouping, but it cannot create more independent weather days.

### 9.3 Ordinal hazard

The ordinal-hazard assessment should determine whether the source subset can support coherent probabilities for ordered whole-degree outcomes across issue times. It should measure ranked probability or equivalent proper scores, calibration by threshold or band, and stability in sparse tails. It should not retain fields merely because a flexible hazard model can assign them coefficients.

### 9.4 Shared acquisition union

Each model may select a different source subset. The acquisition decision is the union of the smallest well-supported model-specific subsets, plus protected infrastructure fields. A field useful to only one model should remain only if that model is competitive and the field's incremental gain is stable enough to justify its cost.

## 10. Protected fields and groups

The research agent must explicitly identify protected fields before ordinary elimination begins. At present the following require special treatment:

- H14 is static grid-height lineage and contributes negligible repeated acquisition cost. It should not be treated like a dynamic field.
- H16 is the independently reacquired hourly 2-m temperature baseline source.
- Q05 is the independently reacquired Q15 2-m temperature trajectory source.
- Required components of any retained vector or mechanistic composite must be assessed jointly.
- Fields required to preserve exact interval meaning must not be replaced by a differently defined snapshot merely because names are similar.

The agent may recommend changing protected status, but must provide a direct explanation of how baseline reconstruction, parity, or the mechanism will remain possible.

## 11. Required study design

The four-week Step 04 pilot was an engineering and semantic pilot. It deliberately sampled selected cycle and lead roles and contains only 1,849 logical field requests. It is not a statistically adequate dataset for feature elimination or model comparison.

The scientific study therefore requires a separate, owner-approved selection cohort containing the complete candidate universe before the final universe can be reduced. The research agent's immediate job is to design this cohort and its decision rules, not to run it.

### 11.1 Cohort requirements

The proposed cohort must:

- contain enough independent target days for model and regime comparisons;
- cover all seasons and multiple years across 2021-2026;
- include both KDEN coordinate eras and relevant archive regimes;
- include ordinary, extended, and DST-sensitive scheduling cases where relevant;
- include the full issue-time range needed to assess early and later intraday value;
- preserve complete same-cycle paths needed for H/Q and revision comparisons;
- include difficult KDEN regimes, not only climatologically ordinary or sunny days;
- remain small enough to be acquired before committing to the 41.5-day plan;
- use labels only in a separate research/modeling join, never in the canonical HRRR source archive;
- justify sample size in terms of independent target days, not the much larger count of issue rows.

Regime coverage may use predeclared seasonal sampling and source-only screening. Outcome-aware selection of interesting days must not leak final errors into a test fold or bias the estimated prevalence of regimes.

### 11.2 Full-universe benchmark

The selection cohort must first establish a full H01-H44/Q01-Q14 benchmark for each model family. Reduced subsets are compared with that benchmark on identical folds and issue times. The full benchmark is not presumed optimal; it is the reference needed to measure information loss.

### 11.3 Nested and grouped validation

- Keep every issue row from one target day in the same fold.
- Use rolling-origin or otherwise future-blocked validation.
- Fit normalization, imputation, dimension reduction, feature selection, smooth penalties, AnEn weights, neighbor counts, thresholds, and calibration using training data only.
- Preserve a final untouched temporal evaluation period after selection rules are frozen.
- Report uncertainty using paired target-day comparisons or another day-grouped method.
- Evaluate performance by issue time, season, and predeclared KDEN mechanism/regime, not only in aggregate.

### 11.4 Model metrics

Primary meteorological metrics should include:

- CRPS or the appropriate discrete equivalent;
- log score with explicit treatment of zero-probability failures;
- ranked probability score for ordered outcomes where appropriate;
- Brier scores and reliability for relevant whole-degree thresholds or bands;
- calibration, interval coverage, and calibrated interval width;
- sharpness conditional on calibration;
- tail performance and failure-regime performance;
- stability across rolling years and issue times;
- earliest issue time at which useful concentration is achieved.

MAE, RMSE, and bias remain useful diagnostics but are secondary to probability quality. Market PnL is not a feature-promotion metric.

### 11.5 Acquisition-aware objective

The study should produce a Pareto frontier rather than one unconstrained leaderboard. For a retained set `S`, assess both predictive performance and estimated acquisition cost:

```text
cost(S) = sum of measured or projected source bytes, requests, and wall time for fields in S
```

The preferred set is the smallest shared union whose performance remains within a predeclared, scientifically acceptable tolerance of the best validated model for each competitive family. The owner must approve the tolerance before a final holdout is examined.

Where evidence is insufficient to distinguish two fields, report that uncertainty. Do not convert a low-powered null result into proof of redundancy. A sequential challenger cohort may be more appropriate than automatically retaining everything or automatically dropping the more expensive field.

## 12. Field-by-field decision record

Every H01-H44 and Q01-Q14 ID must receive one disposition:

- `PROTECTED_BASELINE_OR_STATIC`
- `RETAIN_CORE`
- `RETAIN_MODEL_SPECIFIC`
- `RETAIN_CHALLENGER_PENDING_COHORT`
- `DROP_DETERMINISTIC_REDUNDANCY`
- `DROP_CONDITIONAL_REDUNDANCY`
- `DROP_NO_STABLE_PREDICTIVE_VALUE`
- `UNRESOLVED`

The decision matrix must contain at least:

| Required column | Meaning |
|---|---|
| Field ID and exact identity | Registry ID, parameter, level, step type, and interval |
| Physical quantity | What the source message measures |
| KDEN failure mechanism | Specific pathway by which it may diagnose bias, timing error, or dispersion |
| Issue-time relevance | When between early morning and afternoon the information can matter |
| Temporal requirement | Hourly state, Q15 path, interval amount, onset, tendency, or revision need |
| Spatial requirement | BI, NN, centered tile, upstream sector, gradient, or other proposed support |
| Derived uses | Composites and summaries that require the source |
| Model roles | AnEn distance, GAM/GAMM location, GAM/GAMM scale, ordinal hazard, or competitive challenger |
| Redundancy candidates | Fields or derived quantities that may substitute for it |
| Conditional exceptions | Regimes in which apparent redundancy may fail |
| Evidence | KDEN-specific literature, prior project evidence, or planned cohort test |
| Acquisition cost | Requests, bytes, time, and Q-versus-H cost class |
| Disposition | One of the allowed decisions |
| Confidence and risk | Strength of evidence and consequence of an incorrect deletion |

The matrix must distinguish raw-source necessity from the number of eventual model columns.

## 13. Required ablations and comparisons

The research plan should specify, at minimum:

1. H-only versus H plus Q performance at identical issue times.
2. For every Q family with an H analogue, H state/tendency/revision versus H plus Q trajectory.
3. Q07/Q08 snapshot wind versus Q09/Q10 five-minute-average wind, evaluated as vector groups.
4. Alternative cloud/radiation subsets and retained energy composites.
5. Alternative surface-flux and boundary-layer subsets.
6. Alternative snow/ground-state subsets.
7. Thermal-level and flow subsets needed for KDEN terrain and advection regimes.
8. Precipitation/reflectivity/convection subsets for interrupted-heating and scale effects.
9. Point-only versus existing neighborhood summaries for spatially sensitive fields.
10. Existing centered spatial support versus any scientifically justified KDEN/upstream geometry proposal.
11. Current-state-only versus trajectory summaries versus cycle-revision summaries.
12. Model-specific compact subsets followed by their shared acquisition union.

Ablations must remove scientifically coherent groups when required. They should not break vector pairs or composites merely to generate a superficially smaller column count.

## 14. Deliverables from the research agent

The primary deliverable should be:

```text
reports/step_04_5_feature_universe_scientific_recommendation.md
```

It must include:

1. an executive recommendation;
2. a KDEN-specific failure-mechanism review with sources and uncertainty;
3. the full 58-field decision matrix;
4. protected fields and scientific groups;
5. the proposed selection-cohort design;
6. model-specific feature-selection and ablation plans;
7. a temporal-density analysis for every Q field and relevant H analogue;
8. spatial-geometry limitations and proposed tests;
9. a cost-aware Pareto decision rule;
10. estimated request and runtime consequences of each recommended universe;
11. unresolved questions and the exact evidence needed to resolve them;
12. a clear `RECOMMEND`, `REVISE`, or `DO_NOT_REDUCE_YET` conclusion.

The agent may create an additional Markdown research log or bibliography under `reports/`, but should not create code, registry, schema, state, or acquisition artifacts.

## 15. Acceptance conditions for Step 04.5 research

The research recommendation is ready for owner review only when:

- all 58 fields have explicit, evidence-backed dispositions;
- H and Q were both scrutinized rather than presuming hourly fields are free or subhourly fields are expendable;
- KDEN-specific mechanisms drive the analysis;
- retained Q fields have a demonstrated or testable need for native subhourly semantics;
- fields useful mainly through a composite were evaluated with their required group;
- pairwise correlation was not used as the sole elimination criterion;
- location, scale, ordered-probability, and AnEn-distance roles were considered separately;
- all repeated issue rows were treated as belonging to approximately 2,080 independent target days;
- the proposal preserves cycle richness and issue-time legality;
- predictive comparisons use proper out-of-sample probability metrics;
- market information was not used to select meteorological fields;
- projected acquisition consequences are reported transparently;
- uncertain deletions are identified as uncertain rather than presented as facts;
- no current code, sealed registry, plan, or PASS record was modified.

Owner acceptance of the research document is a separate decision from authorizing new acquisition or modeling runs.

## 16. What happens after owner acceptance

If a reduced universe is accepted, implementation should proceed as a versioned contract change:

1. freeze the new H/Q registry version without overwriting the original registry;
2. record the retained and removed IDs with scientific rationale;
3. regenerate both product request plans and their counts;
4. rerun affected registry, schema, and plan validations;
5. run a bounded confirmation pilot using the reduced universe;
6. verify selectors, interval semantics, spatial extraction, parity, resume behavior, and deterministic output;
7. compare the new measured throughput and extrapolated runtime directly with the original Step 04 report;
8. obtain separate owner approval before launching Steps 05 or 06.

Because a feature-universe change alters request identities and plan hashes, it is not a lightweight schema re-attestation. The affected registries and request plans must be regenerated and sealed honestly.

## 17. Repository sources to read first

Current controlling and engineering evidence:

- `PROJECT.md`
- `KDEN_HRRRv4_Local_Archive_Acquisition_Memo_v1.0.md`
- `reports/step_04_pilot_report_v375.md`
- `reports/step_04_pilot_report_v375.json`
- `state/STEP_04_PASS.json`
- `registries/hrrr_hourly_v375.csv`
- `registries/hrrr_subhourly_v375.csv`
- `registries/decoded_grib_identities_v375.json`
- `config/pilot_design_v375.json`

Historical scientific context:

- `1. research/direction /7-25-26KDEN_Probabilistic_MOS_Product_Direction_White_Paper_v2.0.docx`
- `1. research/direction /KDEN_Layer_1_Scientific_Record_v1.0.docx`
- `1. research/direction /v2---stages/KDEN_Layer_1_Baseline_Forecast_Specification_v3.0.docx`
- `1. research/direction /v2---x[d,t] acquistion/KDEN_Universal_Issue_Time_Feature_Panel_Scientific_Specification_v1.0.docx`
- `1. research/direction /v2---x[d,t] acquistion/KDEN_Universal_Issue_Time_Feature_Panel_Implementation_Manual_v1.0.docx`

When an older document conflicts with `PROJECT.md`, use the older material to understand why the historical choice was made, then follow the current v3.75 contract. In particular, old instructions involving six checkpoints, selected-cycle-only acquisition, `SPARSE`/`PATH` acquisition control, MADIS, Layer-1 H16/Q05 reuse, or serial Step 08/09 dependencies are not current implementation instructions.

## 18. Final principle

The study is not trying to find the smallest generic weather feature list. It is trying to preserve the smallest HRRR source universe that can reveal the KDEN-specific ways a legally available forecast of the remaining day's temperature trajectory can be wrong.

Cycle richness protects live-like issue-time reconstruction. Field and cadence selection control the acquisition burden. Spatial design controls whether retained fields actually observe the relevant local and upstream structure. Model-specific regularization controls the final statistical dimension. Step 04.5 must treat those as separate levers and make every proposed deletion auditable.
