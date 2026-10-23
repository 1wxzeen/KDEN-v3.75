from pathlib import Path
import json,hashlib,itertools
E=Path(__file__).resolve().parents[2];R=E.parents[2];out=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
base=json.loads((E/'config/experiment.json').read_text())
features={
 'thermal_state':['identity','q05_local_asof_value'],
 'thermal_850':['identity','h07_local_future_first_value'],
 'thermal_contrast':['identity','derived_t850_minus_t2m_future_first_k'],
 'heating_potential':['difference','q05_local_remaining_max','q05_local_asof_value'],
 'product_difference':['identity','derived_q05_minus_h16_common_remaining_mean_k'],
 'forecast_revision':['identity','revision_h16_remaining_max_abs'],
 'solar_energy':['identity','derived_h31_remaining_trapezoid_mj_m2'],
 'mixing_depth':['identity','h24_local_remaining_max'],
 'dryness':['identity','derived_dewpoint_depression_future_first_k'],
 'wind_speed':['identity','derived_wind_speed_remaining_mean_m_s']}
groups=[['thermal_state','heating_potential'],['thermal_850','thermal_contrast'],['solar_energy'],['mixing_depth','wind_speed'],['dryness'],['product_difference','forecast_revision']]
registry='universal_issue_state/v1/registries/universal_feature_registry_v1.json'
c={'schema':'R14_S3_PHYSICAL_V1','authority':'User authorized S3 implementation and physically informed executive feature selection after inspecting baseline diagnostics.',
 'parent_s1_sha256':sha(E/'manifests/S1_RELEASE.json'),'parent_s2_sha256':sha(E/'manifests/S2_IMPLEMENTATION_RELEASE.json'),
 'baseline_release_sha256':sha(E/'runs/r14-s2-20260925T185129Z/BASELINE_RELEASE.json'),
 'exposure_sha256':sha(E/'diagnostics/s2_baseline_review_v1/EXPOSURE.json'),
 'registry':registry,'registry_sha256':sha(R/registry),'features':features,'groups':groups,
 'center':'q05_local_retained_max','clocks':['clock_issue_minutes_since_0200','clock_local_dst_flag','clock_target_doy_sin','clock_target_doy_cos','clock_wrfsfcf_cycle_age_minutes','clock_wrfsubhf_cycle_age_minutes'],
 'anen':base['anen'],'gam':base['gam'],'tuning':base['tuning'],
 'probe':{'outer':'OUTER_01','inner':'INNER_02','training_dates':'eligible 2021 days at calendar positions 0,3,6,...; label-free deterministic subsample','assessment_dates':['2022-01-20','2022-02-20','2022-03-13'],'assessment_labels':False,'anen_parameters':{'seasonal_half_width_days':90,'neighbors':15,'bandwidth_multiplier':1.0,'kernel_sigma_f':1.25},'gam_parameters':{'lambda_mu':0.01,'lambda_scale':0.1}},
 'amendments':['Replace old weather vector with ten physical coordinates; same vector for GAM location and AnEn.','AnEn squared distance averages within active physical groups then averages groups equally.','Retain 850-mb temperature and its surface contrast following D1 evidence and user clarification; treat as model thermal proxies, not guaranteed above-ground mixing measurements.','Use wind speed rather than direction until earth/grid vector orientation is audited.','GAM scale adds heating potential and mixing depth to product difference and revision.','Do not reselect S2 baselines; preserve earlier frozen artifacts.'],
 'evidence':'Baseline outer outcomes inspected; no fresh-blind claims for subsequent development on those periods.',
 'scope':'S3 implementation and bounded fits only; S4 full nested orchestration remains a separate stage.'}
c['anen']['features']=list(features);c['anen']['distance']='sqrt(mean_active_groups(mean_active_coordinates_in_group(standardized_difference**2)))'
c['gam']['location_weather_smooths']=list(features);c['gam']['scale_weather_smooths']=['heating_potential','mixing_depth','product_difference','forecast_revision'];c['gam']['required_features']=list(features)+c['clocks']+[c['center']]
candidates=[]
for w,k,b,s in itertools.product(c['anen']['seasonal_half_width_days'],c['anen']['neighbors'],c['anen']['bandwidth_multiplier'],c['anen']['kernel_sigma_f']):
 candidates.append({'model_id':'ANEN','parameters':dict(seasonal_half_width_days=w,neighbors=k,bandwidth_multiplier=b,kernel_sigma_f=s)})
for model in ['GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5']:
 for lm,ls in itertools.product(c['gam']['lambda_mu'],[0.] if model=='GAM_LOCATION_NORMAL' else c['gam']['lambda_scale']):
  candidates.append({'model_id':model,'parameters':dict(lambda_mu=lm,lambda_scale=ls)})
for x in candidates:x['candidate_id']=x['model_id']+'_'+hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()[:12]
(out/'config.json').write_text(json.dumps(c,indent=2,sort_keys=True)+'\n');(out/'candidates.json').write_text(json.dumps(candidates,indent=2,sort_keys=True)+'\n')
