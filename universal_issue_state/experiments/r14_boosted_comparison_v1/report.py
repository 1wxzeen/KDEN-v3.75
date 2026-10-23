from datetime import date
import numpy as np
import pyarrow.parquet as pq
import s0
from common import validate,digest,read_seal,save,seal
from data import Data
from bootstrap_core import block_weights,summarize,reliability,day_sum,interval,ratio_draws
from r14_s1.scoring import score_rows


def score(root,project,out,status):
 identity=validate(root);r=read_seal(out/'PREDICTION_RELEASE.json');s0.require(r['binding']==digest(identity),'Different prediction release')
 for rel,h in r['files'].items():s0.require(s0.sha256(out/rel)==h,'Changed frozen predictions: '+rel)
 cfg=s0.read_json(root/'config.json');data=Data(root,project,cfg).load(out/'shared');mask=data.dates>='2023-01-01';idx=np.where(mask)[0];days=data.dates[idx];ids=[data.ids[i] for i in idx];truth=data.truth(mask)[idx].astype(int);dates=sorted(set(days));mp={d:i for i,d in enumerate(dates)};di=np.array([mp[d] for d in days]);scores={};available={};diagnostics={};sc=s0.read_json(root/'foundation/config/scorecard.json')
 status('SCORING_FROZEN_OUTER')
 for family in ['XGB_QUANTILE','NGB_NORMAL']:
  rows=[]
  for f in data.contract['folds']['outer']:rows+=pq.read_table(out/'outer'/(f['outer_fold_id']+'_'+family)/'predictions.parquet').to_pylist()
  s0.require([r['issue_state_id'] for r in rows]==ids,'Outer row alignment failed');ok=np.array([r['status']=='AVAILABLE' for r in rows]);available[family]=ok
  p=np.array([r['probabilities'] if r['status']=='AVAILABLE' else np.ones(161)/161 for r in rows]);point=np.array([r['point_f'] if r['status']=='AVAILABLE' else 0 for r in rows]);scores[family]=score_rows(p,truth,ids,sc,point);diagnostics[family]={'expected_rows':len(ids),'available_rows':int(ok.sum()),'days':len(dates),'missing_raw_Q':int((~ok).sum())}
  pq.write_table(__import__('pyarrow').table({'issue_state_id':ids,**scores[family],'available':ok}),out/(family+'_row_scores.parquet'))
 source=s0.read_json(root/'benchmarks/SOURCE_S5_RELEASE.json')
 for baseline in ['B0_H','B0_Q']:
  path=root/'benchmarks'/(baseline+'_row_scores.parquet');s0.require(s0.sha256(path)==source['artifacts'][path.name],'Baseline score snapshot changed');table=pq.read_table(path);s0.require(table['issue_state_id'].to_pylist()==ids,'Baseline row mismatch');scores[baseline]={k:table[k].to_numpy() for k in table.column_names if k!='issue_state_id'};available[baseline]=np.ones(len(ids),bool)
 common=np.logical_and.reduce(list(available.values()));folds=data.contract['folds']['outer'];status('BOOTSTRAP_AND_CALIBRATION');W=block_weights(dates,folds,7,5000,cfg['seed']);W14=block_weights(dates,folds,14,5000,cfg['seed']);slices={'overall':np.ones(len(ids),bool)}
 for f in folds:slices[f['outer_fold_id']]=(days>=f['assessment_start'])&(days<=f['assessment_end'])
 months=np.array([int(d[5:7]) for d in days]);minutes=np.array([data.meta[i]['minutes'] for i in idx])
 for name,m in {'DJF':[12,1,2],'MAM':[3,4,5],'JJA':[6,7,8],'SON':[9,10,11]}.items():slices['season/'+name]=np.isin(months,m)
 for name,lo,hi in [('02–06',0,240),('06–10',240,480),('10–13',480,660),('13–16',660,841)]:slices['issue/'+name]=(minutes>=lo)&(minutes<hi)
 summary={};cal={};exact={}
 for model,values in scores.items():
  summary[model]={k:summarize(values,di,m&common,W) for k,m in slices.items()};cal[model]={k:reliability(values['max_integer_probability'],values['modal_integer_hit'],di,m&common,W) for k,m in slices.items()};exact[model]={str(int(t)):summarize(values,di,(minutes==t)&common) for t in sorted(set(minutes))}
 pairs=[];n=len(dates);cnt=day_sum(common.astype(float),di,n);good=cnt>0
 for a,b in cfg['scoring']['primary_contrasts']:
  delta=scores[a]['negative_log_score']-scores[b]['negative_log_score'];daily=np.divide(day_sum(delta*common,di,n),cnt,out=np.zeros(n),where=good)
  pairs.append({'model':a,'reference':b,'difference':float(daily[good].mean()),'seven_day_adjusted':interval(ratio_draws(W,daily,good.astype(float)),(.005,.995)),'fourteen_day_adjusted':interval(ratio_draws(W14,daily,good.astype(float)),(.005,.995))})
 save(out/'SCORECARDS.json',summary);save(out/'CALIBRATION.json',cal);save(out/'EXACT_ISSUE.json',exact);save(out/'PRIMARY_COMPARISONS.json',pairs);save(out/'SUPPORT.json',{'models':diagnostics,'common_rows':int(common.sum()),'expected_rows':len(ids),'common_days':int(good.sum()),'baseline_timing_disclosed':True})
 lines=['# R14 boosted model comparison','','Historical development evidence, not a fresh blind test. Both models correct raw Q HRRR Tmax. All six selected outer forecasts were frozen before comparison. The baseline score snapshots retain the disclosed original selection-timing violation; its excluded-date sensitivity selected unchanged settings.','','| Model | MAE °F | Exact integer hit | Log loss | CRPS °F | Error ≥5°F |','|---|---:|---:|---:|---:|---:|']
 for model,v in summary.items():
  m=v['overall']['metrics'];lines.append(f'| {model} | {m["mae"]:.3f} | {100*m["modal_integer_hit"]:.2f}% | {m["negative_log_score"]:.4f} | {m["discrete_crps_f"]:.3f} | {100*m["ae_ge_5"]:.2f}% |')
 lines+=['',f'Identical comparison support: {int(common.sum()):,} of {len(ids):,} expected checkpoints, {int(good.sum())} days. MAE uses the PMF median, exact hits use its modal integer, and scores weight days equally. Point/mean errors, intervals, signed tails, threshold and synthetic-band scores are retained in the machine-readable tables. Synthetic bands do not represent Kalshi listings.','','## Paired primary comparisons','']
 for p in pairs:lines.append(f'- {p["model"]} − {p["reference"]}: NLL difference {p["difference"]:.5f}; adjusted interval [{p["seven_day_adjusted"]["lower"]:.5f}, {p["seven_day_adjusted"]["upper"]:.5f}]. Negative favors the first model.')
 lines+=['','Five primary comparisons use nominal approximate familywise 95% calendar-block intervals; fourteen-day sensitivity is included. Other intervals and slices are descriptive. No formal promotion or PnL claim is made.','','## Read the whole result','','[Scorecards](SCORECARDS.json) · [Calibration bins and their population coverage](CALIBRATION.json) · [All exact issue times](EXACT_ISSUE.json) · [Primary intervals and sensitivity](PRIMARY_COMPARISONS.json) · [Support](SUPPORT.json)','','Confidence bins are diagnostics, not gates optimized from these outcomes. Inspect periods and issue times before interpreting pooled accuracy. XGBoost quantile crossings are repaired by the preregistered rule; NGBoost normal scale guards are output safeguards. Per-forecast diagnostics and each saved FIT.json retain those modeling details. Neither these outcomes nor a failed run establish that HRRR is categorically useful or useless.']
 (out/'REPORT.md').write_text('\n'.join(lines)+'\n');files={name:s0.sha256(out/name) for name in ['SCORECARDS.json','CALIBRATION.json','EXACT_ISSUE.json','PRIMARY_COMPARISONS.json','SUPPORT.json','REPORT.md','XGB_QUANTILE_row_scores.parquet','NGB_NORMAL_row_scores.parquet']};seal(out/'SCORE_RELEASE.json',{'status':'COMPLETE','files':files,'prediction_release_sha256':s0.sha256(out/'PREDICTION_RELEASE.json'),'reserved_labels_read':False});status('SCORED_COMPLETE')
