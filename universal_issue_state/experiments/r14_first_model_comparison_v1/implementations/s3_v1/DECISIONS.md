# S3 modeling decisions and physical rationale

This is an additive S3 amendment, authorized by the user's request to make physically informed feature decisions. It does not rewrite the sealed S0/S1/S2 contracts or baseline predictions. The operative S3 authority is `config.json` plus `candidates.json` and `RELEASE.json`. Model IDs still name the same model families, but S3 configuration hashes explicitly identify this revised feature specification. The original S0 feature list is not silently presented as the fitted S3 list.

## What prior evidence supports

The D1 historical synthesis reports that the primary mostly-sunny annual 850-mb TMP model had development LOYO MAE 1.654°F and 2025 holdout MAE 1.871°F on 94 days (Table 5, pages 5–6). It beat the corresponding thickness control and repeatedly favored fresh low-level forecasts. That is a reason to retain 850-mb information. The initial proposal to exclude it solely because of terrain was withdrawn before any S3 model probe after the user supplied this evidence.

D1 was a one-predictor, mostly-sunny study using fixed 21Z valid times. It does not prove generalist, all-issue AnEn/GAM performance. In particular, its observed CF6 sunny-day filter is not an issuance-time gate and is not imported here. Its full-2025 results are already inspected historical reference evidence, not an untouched holdout for the new models.

Source: [Reference not bundled: D1 historical synthesis](../../../../../DATA_AVAILABILITY.md#not-bundled). The PDF is reference material, not a new execution instruction.

850-mb values remain HRRR model predictors. Their relationship to local terrain may complicate literal parcel/stability interpretation; a temperature contrast is not a measured mixing depth, and a temperature difference is not geopotential thickness. We keep the demonstrated empirical thermal signal without asserting those stronger physical interpretations.

## Ten coordinates, six physical groups

Every input is a forecast available at issuance from the frozen selected cycles; none is a future observation. All feature names below map to the audited 433-feature R14 registry. Units are K for absolute temperatures and temperature differences, MJ/m² for integrated shortwave, m for PBL depth, and m/s for wind speed. Only the Tmax offset is converted to °F; training standardization makes analog distances dimensionless.

| Group | Model coordinate | Frozen input / transformation | Reason and limit |
|---|---|---|---|
| Surface thermal evolution | thermal_state | q05_local_asof_value | Forecast near-surface thermal state; not an observation. |
| Surface thermal evolution | heating_potential | q05_local_remaining_max − q05_local_asof_value | Forecast remaining warming/cooling relative to current modeled state; can be negative. Avoids counting several nearly duplicate hourly/subhourly absolute temperatures. |
| Low-level thermal structure | thermal_850 | h07_local_future_first_value | D1-motivated model air-mass signal near issuance. This changes D1's fixed-valid-time feature into an issue-relative feature, so transfer must be evaluated anew. |
| Low-level thermal structure | thermal_contrast | derived_t850_minus_t2m_future_first_k | Same-cycle, same-valid-time model surface/850 contrast; not asserted to be an above-ground lapse rate. |
| Solar forcing | solar_energy | derived_h31_remaining_trapezoid_mj_m2 | Remaining modeled downwelling solar energy, reflecting cloud interference and remaining daylight. It is not net surface heat input. |
| Mixing/ventilation | mixing_depth | h24_local_remaining_max | Modeled remaining maximum PBL depth; a mixing-regime proxy rather than observed mixing. |
| Mixing/ventilation | wind_speed | derived_wind_speed_remaining_mean_m_s | Remaining mean 10-m wind magnitude; captures ventilation strength, not the sign of thermal advection. |
| Moisture state | dryness | derived_dewpoint_depression_future_first_k | Model temperature minus dewpoint; moisture/evaporative-cooling potential proxy, not proof precipitation or cooling occurs. |
| Forecast consistency | product_difference | derived_q05_minus_h16_common_remaining_mean_k | Aligned hourly/subhourly forecast difference. These products are related, not independent ensemble members. |
| Forecast consistency | forecast_revision | revision_h16_remaining_max_abs | Maximum absolute temperature revision on the exact common remaining overlap; measures model instability, without asserting that large changes cause errors. |

The 700–850 temperature contrast and duplicate hourly temperature levels are excluded to keep the first vector compact. Cloud cover is not added alongside solar energy in this first version, avoiding repeated weight for closely related forcing. Snow cover, precipitation/reflectivity, wind direction and richer temporal/spatial structures remain possible later, separately registered additions. Their omission is a limitation, especially for snow/convective/advection regimes; the current temperature forecasts may encode some effects but do not guarantee adequate conditioning.

Wind direction is deferred until the source vector orientation is audited; speed avoids incorrectly labeling model grid-relative components as east/west upslope flow. Direction is physically important, so speed is not a complete substitute.

Boundary-layer depth and mixing are physically relevant to daily surface temperature and moisture ([NOAA PSL](https://www.psl.noaa.gov/psd3/boundary/pbl/)). Clouds affect incoming solar and outgoing thermal radiation ([NOAA NSSL](https://inside.nssl.noaa.gov/ensmith/metr5603/intro-overview/)). These sources support variable selection, not an assertion that this particular feature set will improve scores.

## AnEn choices

The analog approach matches current model forecasts to historical model forecasts, as in [Delle Monache et al. (2013)](https://journals.ametsoc.org/doi/pdf/10.1175/MWR-D-12-00281.1). Here it uses translated historical Tmax residuals rather than simply treating past observed Tmax values as today's ensemble.

- Exact local issue minute and circular seasonal window; two-day truth lag and fixed training vintage inherited from S0/S1. Minimum 40 complete historical days. No imputation or substitution of a different issue time.
- At each issue time, robust scaling uses only complete training vectors: median/IQR, falling back to 1.4826×MAD, population standard deviation, then dropping a constant coordinate. All-constant vectors abstain.
- Squared standardized differences are averaged within each active physical group, then averaged equally across active groups; the final distance is the square root. Thus a two-coordinate temperature or consistency group does not get twice the total weight of solar forcing. This is a declared scientific prior, not learned feature importance. Correlation across groups can still remain.
- Keep the registered search: seasonal half-width 45/60/90 days, neighbors 15/20/30/40/60, distance bandwidth multiplier 0.5/1/2, Gaussian residual smoothing 0.75/1.25/2/3°F: 180 candidates. A query with fewer available analogs than requested neighbors abstains; k is never silently reduced.
- Select nearest neighbors by distance, then date, then issue ID. Weight with exp(−0.5×(distance/h)²), where h=max(kth distance×bandwidth multiplier, 1e−12). Equal zero distances give equal weights. Mix Gaussian kernels centered on raw Q Tmax plus each neighbor's historical residual.
- Report pool size, effective sample size, nearest/kth distance, distance concentration, weighted residual MAD, training-reference distance quantile and out-of-range flags. Reference neighborhoods exclude their own day; fixed training scalers remain fitted on training. These are diagnostics, not OOF forecasts or learned gates.
- No new error-based feature weighting, arbitrary four-season experts, or reuse of the S2 winning window as an automatically chosen AnEn setting. S4 must tune candidates chronologically on common feasibility support.

## GAM choices

The primary GAM_LS_NORMAL models both corrected location and uncertainty. It is a low-rank additive distributional model with coefficient ridge regularization; it does not use a classical integrated-curvature spline penalty or random effects (not GAMM).

The location is raw Q Tmax in °F plus an intercept and smooth additive corrections for all ten physical coordinates, issue time, cyclic season, and linear product cycle ages/DST. The scale has additive effects of heating potential, mixing depth, product disagreement, revision, issue time and cyclic season. This allows uncertainty to vary with observable conditions without claiming the learned confidence is calibrated before future evaluation.

Weather splines use degree three, five basis functions and a training day-weighted median interior knot; low-cardinality or degenerate inputs fall back to linear/constant behavior. Issue time has six basis functions with fixed knots. Season uses four Fourier harmonics. Training day-weighted centering and RMS scaling precede ridge penalties. All fitted transformations, knots and dropped columns are saved. Assessment values outside training ranges are clipped for spline/linear correction terms and flagged; the raw Q offset is not clipped.

Scale is smoothly constrained between 0.25°F and 20°F. This permits narrow forecasts when supported but prevents scale collapse and extreme numerical instability. These limits are safeguards, not expected errors; near-bound frequencies are emitted. A normal scale is a standard deviation; Student-t(5) scale is not—its standard deviation is scale×sqrt(5/3).

Fit the native integer-bin likelihood, including endpoint tails, with no probability floor in the fitting objective. Use stable log-CDF/log-survival differences and analytic derivatives. Penalties remain the registered location grid 0.001/0.01/0.1/1 and scale grid 0.01/0.1/1. Both intercepts are unpenalized. L-BFGS-B uses the registered strict tolerances, gradient acceptance threshold, iteration limits, and starts at scales 1/3/6°F; every start is recorded and all-start failure invalidates the fit. [SciPy log_ndtr](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.special.log_ndtr.html) and [BSpline](https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.interpolate.BSpline.html) support the implementation.

GAM_LOCATION_NORMAL is the constant-scale diagnostic (four location-penalty candidates). GAM_LS_T5 has fixed five degrees of freedom and the same location/scale architecture (12 candidates). The primary GAM has 12 candidates. These are declared diagnostics, not extra primary winners or opportunistic tail tuning. Total S3 candidate count is 208.

## Evidence and interpretation

Baseline diagnostics were inspected at the user's request before this implementation. The same outer periods are development evidence for later decisions, including these. No fresh blind claim is made. S3 uses synthetic checks and a fixed, label-independent calendar subsample of 122 eligible training days from 2021, then predicts three development dates without reading their outcomes. Probe training losses and solver convergence are engineering diagnostics, not model skill or parameter-selection results. S4 remains responsible for full inner tuning, outer predictions, common-support comparison prerequisites and a new combined prediction release referencing the immutable S2 baselines.
