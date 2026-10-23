from pathlib import Path
from datetime import date
import numpy as np
import pyarrow.parquet as pq
from scipy.special import expit
from scipy.optimize import minimize
import s0
from inputs import Context,save,seal,verify_record_file,digest
from core import block_weights,ratio_draws,interval,reliability,day_sum
from model import day_weights
from runner import validate,verified_unit


def binary_scores(p,y):
    p=np.asarray(p);y=np.asarray(y);q=np.clip(p,1e-6,1-1e-6)
    return {'brier':(p-y)**2,'binary_nll':-y*np.log(q)-(1-y)*np.log1p(-q)}

def calibration_coefficients(p,y,w):
    if len(np.unique(y))<2:return {'status':'UNDEFINED_SINGLE_CLASS','intercept':None,'slope':None}
    q=np.clip(p,1e-6,1-1e-6);x=np.column_stack([np.ones(len(p)),np.log(q)-np.log1p(-q)])
    def f(b):
        z=x@b;return float(w@(np.logaddexp(0,z)-y*z)),x.T@(w*(expit(z)-y))
    r=minimize(f,np.array([0.,1.]),jac=True,method='L-BFGS-B',options={'maxiter':2000,'gtol':1e-6,'ftol':1e-12})
    valid=r.success and np.isfinite(r.fun) and np.abs(r.jac).max()<=1e-4
    return {'status':'DESCRIPTIVE_FIT' if valid else 'UNRESOLVED','intercept':float(r.x[0]) if valid else None,'slope':float(r.x[1]) if valid else None,'used_to_modify_forecasts':False}

def summarize(p,y,days,mask,di,W):
    w=day_weights(days,mask);n=len(W[0]);cnt=day_sum(mask.astype(float),di,n);good=cnt>0
    if not mask.any():return {'rows':0,'days':0,'metrics':{},'intervals':{}}
    losses=binary_scores(p,y);metrics={k:float(w@np.nan_to_num(v)) for k,v in losses.items()};cis={}
    for k,v in losses.items():
        daily=np.divide(day_sum(np.nan_to_num(v)*mask,di,n),cnt,out=np.zeros(n),where=good)
        cis[k]=interval(ratio_draws(W,daily,good.astype(float)))
    return {'rows':int(mask.sum()),'days':int(good.sum()),'sparse':int(good.sum())<60,'metrics':metrics,'intervals':cis,'calibration':reliability(np.nan_to_num(p),y,di,mask,W),'calibration_coefficients':calibration_coefficients(p[mask],y[mask],w[mask]/w[mask].sum())}


def selected(p,y,rows,di,W,mask,coverage,truth):
    expected=np.array([r['expected_issues'] for r in rows]);available=np.array([r['status']=='AVAILABLE' for r in rows]);ad=np.array([r['admit_'+str(coverage)] for r in rows])&mask&available
    w=ad/expected;den=w.sum();n=W.shape[1];d=day_sum(w,di,n)
    out={'expected_rows':int(mask.sum()),'available_rows':int((mask&available).sum()),'admitted_rows':int(ad.sum()),'checkpoint_coverage':float(ad.sum()/mask.sum()) if mask.any() else 0.,'dayweighted_coverage':float(den/(mask/expected).sum()) if mask.any() else 0.,'admitted_days':int(np.unique(di[ad]).size),'admitted_issues_per_day':day_sum(ad.astype(float),di,n).astype(int).tolist(),'metrics':{},'intervals':{}}
    out['unique_day_coverage']=out['admitted_days']/len(np.unique(di[mask])) if mask.any() else 0.
    values={'hit':y,'predicted':np.nan_to_num(p),'gap':y-np.nan_to_num(p),'B0_Q_hit':np.array([r['B0_Q_integer'] for r in rows])==truth,'B0_H_hit':np.array([r['B0_H_integer'] for r in rows])==truth,'base_error_ge5':np.abs(np.array([r['base_median'] for r in rows])-truth)>=5}
    values['same_case_Q_hit_lift']=values['hit']-values['B0_Q_hit'];values.update(binary_scores(p,y))
    for k,v in values.items():
        v=np.nan_to_num(v);out['metrics'][k]=float(w@v/den) if den else None;out['intervals'][k]=interval(ratio_draws(W,day_sum(w*v,di,n),d))
    out['equal_admitted_day_hit']=float(day_weights(np.array([r['target_date'] for r in rows]),ad)@y) if den else None
    return out


def score(E,root,out,status):
    identity=validate(E,root);reg=s0.read_json(E/'implementations/s6_v1/registration.json');release=verify_record_file(out/'PREDICTION_RELEASE.json')
    s0.require(release['binding']==digest(identity),'Scoring binding changed')
    for rel,h in release['files'].items():s0.require(s0.sha256(out/rel)==h,'Changed frozen predictions')
    status('SCORING_FROZEN_PREDICTIONS');ctx=Context(E,E/'implementations/s5_v1');allrows={}
    for base in reg['base_models']:
        for model in ['NATIVE','R0','R1','R2']:
            rows=[]
            for b in reg['historical_blocks']:
                unit=out/'units'/f'{b["id"]}_{base}_{model}';verified_unit(unit);rows+=pq.read_table(unit/'predictions.parquet').to_pylist()
            allrows[base+'/'+model]=rows
    ref=next(iter(allrows.values()));ids=[r['issue_state_id'] for r in ref];days=np.array([r['target_date'] for r in ref]);ds=sorted(set(days));index={d:i for i,d in enumerate(ds)};di=np.array([index[d] for d in days]);truthmap=ctx.truth([date.fromisoformat(d) for d in ds]);truth=np.array([truthmap[date.fromisoformat(d)] for d in days]);folds=[{'assessment_start':b['assessment'][0],'assessment_end':b['assessment'][1]} for b in reg['historical_blocks']]
    for rows in allrows.values():s0.require([r['issue_state_id'] for r in rows]==ids,'Different assessment support/order')
    availability=np.array([r['status']=='AVAILABLE' for r in ref])
    for rows in allrows.values():s0.require(np.array_equal(availability,[r['status']=='AVAILABLE' for r in rows]),'Different comparison support')
    W=block_weights(ds,folds,7,5000,3750927);W14=block_weights(ds,folds,14,5000,3750927);masks={'overall':np.ones(len(ref),bool)}
    for b in reg['historical_blocks']:masks[b['id']]=(days>=b['assessment'][0])&(days<=b['assessment'][1])
    months=np.array([int(d[5:7]) for d in days]);mins=np.array([r['issue_minutes'] for r in ref]);
    for season,values in {'DJF':[12,1,2],'MAM':[3,4,5],'JJA':[6,7,8],'SON':[9,10,11]}.items():masks['season/'+season]=np.isin(months,values)
    for label,lo,hi in [('02–06',0,240),('06–10',240,480),('10–13',480,660),('13–16',660,841)]:masks['issue/'+label]=(mins>=lo)&(mins<hi)
    results={};selectors={};losses={}
    for key,rows in allrows.items():
        status('SCORING_MODEL',key);p=np.array([r['hit_probability'] if r['hit_probability'] is not None else np.nan for r in rows]);y=(np.array([r['base_integer'] for r in rows])==truth).astype(float)
        losses[key]=binary_scores(p,y);results[key]={name:summarize(p,y,days,mask&availability,di,W) for name,mask in masks.items()}
        selectors[key]={str(c):{name:selected(p,y,rows,di,W,mask,c,truth) for name,mask in masks.items()} for c in [1.,.5,.25,.1]}
    contrasts={};readiness={}
    for base in reg['base_models']:
        diff=losses[base+'/R2']['brier']-losses[base+'/R1']['brier'];count=day_sum(availability.astype(float),di,len(ds));good=count>0;daily=np.divide(day_sum(np.nan_to_num(diff),di,len(ds)),count,out=np.zeros(len(ds)),where=good)
        contrasts[base]={'difference':float(day_weights(days,availability)@np.nan_to_num(diff)),'seven_day':interval(ratio_draws(W,daily,good.astype(float)),(.0125,.9875)),'fourteen_day':interval(ratio_draws(W14,daily,good.astype(float)),(.0125,.9875))}
        checks={};upper=contrasts[base]['seven_day']['upper'];checks['primary_adjusted_margin']=upper is not None and upper<=-.002
        for name in ['overall']+[b['id'] for b in reg['historical_blocks']]:
            a=results[base+'/R2'][name]['metrics'];b=results[base+'/R1'][name]['metrics'];checks[name+'/nll']=bool(a and b and a['binary_nll']-b['binary_nll']<=.01)
            if name!='overall':
                checks[name+'/brier_direction']=bool(a and b and a['brier']<b['brier']);s=selectors[base+'/R2']['0.25'][name];v=s['metrics'];checks[name+'/coverage']=s['dayweighted_coverage']>=.1;checks[name+'/days']=s['admitted_days']>=60;checks[name+'/calibration']=v['gap'] is not None and abs(v['gap'])<=.03;checks[name+'/same_case_lift']=v['same_case_Q_hit_lift'] is not None and v['same_case_Q_hit_lift']>=.02
        readiness[base]={'status':'MEETS_HISTORICAL_RESEARCH_HURDLES' if all(checks.values()) else 'DOES_NOT_MEET_ALL_HURDLES','checks':checks,'formal_blind_promotion':False}
    save(out/'RELIABILITY_SCORES.json',results);save(out/'SELECTION.json',selectors);save(out/'PRIMARY_COMPARISONS.json',contrasts);save(out/'READINESS.json',readiness)
    lines=['# CR1 historical reliability results','','Development evidence only. All predictions were frozen before this comparative score was computed. S2/S4 original timing nonconformance remains disclosed; reused base configurations matched lag-correct selection. No temperature PMFs or market prices were changed.','','| Base / reliability | Binary Brier | Binary log loss |','|---|---:|---:|']
    for key,v in results.items():m=v['overall']['metrics'];lines.append(f'| {key} | {m.get("brier",float("nan")):.5f} | {m.get("binary_nll",float("nan")):.5f} |')
    lines+=['','Lower scores are better. Primary contrasts are R2 minus R1; the paired intervals adjust for both registered base-model comparisons.','']
    for base,r in contrasts.items():lines.append(f'- {base}: Brier difference {r["difference"]:.5f}; adjusted seven-day interval {r["seven_day"]["lower"]} to {r["seven_day"]["upper"]}. {readiness[base]["status"]}.')
    lines+=['','[Full scores and calibration](RELIABILITY_SCORES.json) · [Selection, counts and same-case baselines](SELECTION.json) · [Primary comparisons and sensitivity](PRIMARY_COMPARISONS.json) · [Every readiness check](READINESS.json)','','Calibration intercept/slope are descriptive assessment fits and never modify forecasts. Binary log scores clip probabilities to [1e-6,1−1e-6] for reporting only. Undefined metrics remain null. Secondary comparisons are descriptive; no search for an alternative passing cutoff is allowed. Native, R0, R1 and R2 selectors can select different cases. Prospective reservation remains inactive and tradability is untested.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    seal(out/'SCORE_RELEASE.json',{'status':'COMPLETE','prediction_release_sha256':s0.sha256(out/'PREDICTION_RELEASE.json'),'historical_not_blind':True,'files':{f:s0.sha256(out/f) for f in ['RELIABILITY_SCORES.json','SELECTION.json','PRIMARY_COMPARISONS.json','READINESS.json','REPORT.md']}});status('SCORED_COMPLETE')
