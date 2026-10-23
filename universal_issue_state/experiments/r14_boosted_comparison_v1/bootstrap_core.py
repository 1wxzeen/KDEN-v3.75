"""Calendar-block inference and explicitly weighted descriptive estimands."""
from datetime import date,timedelta
import numpy as np
from s0 import require
from r14_s1.scoring import weighted_quantile

KEYS=['negative_log_score','mae','modal_integer_hit','discrete_crps_f','ae_ge_5','bias']

def block_weights(days,folds,length=7,replicates=5000,seed=3750925):
    """Noncircular calendar windows; missing date slots stay missing; fixed fold mass."""
    ds=[date.fromisoformat(str(d)) for d in days];lookup={d:i for i,d in enumerate(ds)}
    require(len(lookup)==len(ds),'Duplicate bootstrap days')
    rng=np.random.default_rng(seed);W=np.zeros((replicates,len(ds)),dtype=float)
    for fold in folds:
        start=date.fromisoformat(fold['assessment_start']);end=date.fromisoformat(fold['assessment_end'])
        n=(end-start).days+1;require(n>=length,'Fold shorter than bootstrap block')
        grid=np.array([lookup.get(start+timedelta(days=i),-1) for i in range(n)])
        eligible=grid[grid>=0];require(len(eligible)>0,'Empty fold')
        starts=rng.integers(0,n-length+1,size=(replicates,int(np.ceil(n/length))))
        sampled=(starts[:,:,None]+np.arange(length)).reshape(replicates,-1)[:,:n]
        for b in range(replicates):
            ids=grid[sampled[b]];ids=ids[ids>=0]
            if len(ids): W[b]+=np.bincount(ids,minlength=len(ds))*len(eligible)/len(ids)
    return W

def interval(draws,quantiles=(.025,.975)):
    a=np.asarray(draws);finite=np.isfinite(a);rate=float(finite.mean())
    return {'lower':float(np.quantile(a[finite],quantiles[0])) if rate>=.95 else None,
            'upper':float(np.quantile(a[finite],quantiles[1])) if rate>=.95 else None,
            'undefined_fraction':1-rate,'quantiles':list(quantiles)}

def ratio_draws(W,num,den):
    a=W@np.asarray(num);b=W@np.asarray(den)
    return np.divide(a,b,out=np.full_like(a,np.nan),where=b>0)

def day_sum(x,di,n):return np.bincount(di,weights=x,minlength=n)

def summarize(scores,di,mask,W=None):
    mask=np.asarray(mask,bool);n=int(di.max())+1;counts=day_sum(mask.astype(float),di,n);good=counts>0
    out={'expected_rows':len(di),'rows':int(mask.sum()),'days':int(good.sum()),'sparse':int(good.sum())<60,
         'uncertainty':'descriptive unadjusted calendar-block intervals; no slice-search significance claim'}
    if not mask.any():return {**out,'metrics':{},'intervals':{}}
    w=np.divide(mask.astype(float),counts[di],out=np.zeros(len(di)),where=counts[di]>0);w/=good.sum()
    out['metrics']={k:float(w@v) for k,v in scores.items() if not k.startswith('adjacent_') and k not in ['absolute_mean_revision','absolute_mode_revision']}
    for k in ['mean','median','named_point','raw']:
        if k+'_squared_error' in scores:out['metrics'][k+'_rmse']=float(np.sqrt(out['metrics'][k+'_squared_error']))
    out['metrics']['rmse']=float(np.sqrt(out['metrics']['mean_squared_error']))
    for q in [.5,.9,.95,.99]:out['metrics'][f'absolute_error_p{int(q*100)}']=weighted_quantile(scores['mae'],w,q)
    out['intervals']={}
    if W is not None:
        use=[k for k in KEYS if k in scores]
        values=np.column_stack([np.divide(day_sum(v*mask,di,n),counts,out=np.zeros(n),where=good) for k in use for v in [scores[k]]])
        den=W@good.astype(float);draw=W@values
        draw=np.divide(draw,den[:,None],out=np.full_like(draw,np.nan),where=den[:,None]>0)
        out['intervals']={k:interval(draw[:,j]) for j,k in enumerate(use)}
    return out

def reliability(p,y,di,mask,W=None,expected_counts=None):
    n=int(di.max())+1;mask=np.asarray(mask,bool);counts=day_sum(mask.astype(float),di,n)
    denom=counts[di] if expected_counts is None else np.asarray(expected_counts)
    w=np.divide(mask.astype(float),denom,out=np.zeros(len(di)),where=denom>0);total=w.sum();bins=[]
    index=np.minimum((np.clip(p,0,1)*10).astype(int),9)
    for b in range(10):
        include=mask&(index==b);weights=w*include;mass=weights.sum();distinct=np.unique(di[include]).size
        item={'lower':b/10,'upper':(b+1)/10,'rows':int(include.sum()),'days':int(distinct),'sparse':distinct<30,
              'weight':float(mass/total) if total else 0.,'predicted':float(weights@p/mass) if mass else None,
              'observed':float(weights@y/mass) if mass else None}
        item['gap']=None if not mass else item['observed']-item['predicted']
        if W is not None:
            den=day_sum(weights,di,n);num=day_sum(weights*y,di,n);gap=day_sum(weights*(y-p),di,n)
            item['observed_interval']=interval(ratio_draws(W,num,den));item['gap_interval']=interval(ratio_draws(W,gap,den))
        bins.append(item)
    return {'bins':bins,'ECE':sum(x['weight']*abs(x['gap']) for x in bins if x['gap'] is not None),
            'calibration_in_the_large':float(w@(y-p)/total) if total else None}

def selective(scores,confidence,ranking,di,expected_counts,mask,threshold,W,baseline_scores):
    population=np.asarray(mask,bool);admit=population&(ranking>=threshold);n=int(di.max())+1
    weights=1/expected_counts;mass=weights*admit;total=float(weights[population].sum());den=day_sum(mass,di,n)
    admitted_days=np.unique(di[admit]);population_days=np.unique(di[population]);out={
      'expected_rows':int(population.sum()),'available_rows':int(population.sum()),'admitted_rows':int(admit.sum()),
      'expected_checkpoint_coverage':float(admit.sum()/population.sum()) if population.any() else 0.,
      'available_checkpoint_coverage':float(admit.sum()/population.sum()) if population.any() else None,
      'dayweighted_coverage':float(mass.sum()/total) if total else 0.,'days_with_any_admission':len(admitted_days),
      'unique_day_coverage':len(admitted_days)/len(population_days) if len(population_days) else 0.,
      'admitted_issues_per_day':day_sum(admit.astype(float),di,n).astype(int).tolist(),
      'sparse':len(admitted_days)<60,'metrics':{},'intervals':{},'baselines':{}}
    for k in ['negative_log_score','mae','modal_integer_hit','discrete_crps_f','ae_ge_5','ae_ge_10','event_hit']:
        num=day_sum(mass*scores[k],di,n);out['metrics'][k]=float(num.sum()/mass.sum()) if mass.sum() else None
        out['intervals'][k]=interval(ratio_draws(W,num,den))
    out['mean_predicted_hit']=float(mass@confidence/mass.sum()) if mass.sum() else None
    out['calibration_gap']=out['metrics']['event_hit']-out['mean_predicted_hit'] if mass.sum() else None
    out['equal_admitted_day_hit_rate']=summarize({'mae':scores['mae'],'mean_squared_error':scores['mean_squared_error'],'event_hit':scores['event_hit']},di,admit)['metrics'].get('event_hit')
    for name,values in baseline_scores.items():
        out['baselines'][name]={k:float(mass@values[k]/mass.sum()) if mass.sum() else None for k in ['negative_log_score','mae','modal_integer_hit','event_hit']}
    return out

def regime_labels(values,minutes,train_values,train_minutes,train_di,method):
    labels=np.full(len(values),'MISSING',dtype='<U12');rules={}
    if method=='positive_vs_nonpositive':
        labels[np.isfinite(values)&(values>0)]='POSITIVE';labels[np.isfinite(values)&(values<=0)]='NONPOSITIVE';return labels,rules
    count=np.bincount(train_di);weight=1/count[train_di]
    for minute in np.unique(minutes):
        eligible=(train_minutes==minute)&np.isfinite(train_values);idx=(minutes==minute)&np.isfinite(values)
        if not eligible.any():continue
        q=[weighted_quantile(train_values[eligible],weight[eligible],p) for p in [1/3,2/3]];rules[str(minute)]=q
        labels[idx]=np.where(values[idx]<=q[0],'LOW',np.where(values[idx]<=q[1],'MIDDLE','HIGH'))
    return labels,rules
