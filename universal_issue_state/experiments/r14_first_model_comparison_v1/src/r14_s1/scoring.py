"""Common point, probability, calibration and coverage score primitives."""
from collections import Counter
import hashlib
import numpy as np
from s0 import require
from .data import day_weights
from .probability import SUPPORT,validate_pmf,summarize_pmf,round_half_away,partition_probabilities


def score_rows(p,y,issue_ids,scorecard,point=None):
    p=validate_pmf(p);p=p[None,:] if p.ndim==1 else p
    y=np.asarray(y)
    require(y.shape==(len(p),) and len(issue_ids)==len(p),'Score row dimensions')
    require(len(set(issue_ids))==len(issue_ids),'Duplicate issue IDs')
    require(np.all(np.isfinite(y)) and np.all(y==np.floor(y)) and np.all((y>=-40)&(y<=120)),'Truth outside integer support; never clip')
    yi=y.astype(int)+40;s=summarize_pmf(p);mean_err=s['mean']-y;median_err=s['median']-y
    scored=np.maximum(p,1e-6);scored/=scored.sum(axis=1,keepdims=True)
    cdf=np.cumsum(p,axis=1);event=(SUPPORT[None,:]>=y[:,None])
    row=np.arange(len(y));obs=np.zeros_like(p);obs[row,yi]=1
    out={'mae':np.abs(median_err),'mean_squared_error':mean_err**2,'bias':mean_err,'median_error':median_err,'modal_integer_hit':(s['mode']==y).astype(float),'within_one':(np.abs(s['mode']-y)<=1).astype(float),'within_two':(np.abs(s['mode']-y)<=2).astype(float),'negative_log_score':-np.log(scored[row,yi]),'discrete_crps_f':np.sum((cdf[:,:-1]-event[:,:-1])**2,axis=1),'multiclass_brier':np.sum((p-obs)**2,axis=1),'max_integer_probability':s['max_integer_probability'],'entropy':s['entropy'],'endpoint_mass':s['endpoint_mass'],'score_floor_count':np.sum(p<1e-6,axis=1),'score_floor_added_mass':np.maximum(1e-6-p,0).sum(axis=1),'score_floor_total_variation':.5*np.abs(scored-p).sum(axis=1)}
    out['normalized_rps']=out['discrete_crps_f']/160
    for name,pred in [('mean',s['mean']),('median',s['median'])]+([] if point is None else [('named_point',np.asarray(point,dtype=float))]):
        require(np.shape(pred)==y.shape and np.all(np.isfinite(pred)),'Invalid named point')
        out[name+'_absolute_error']=np.abs(pred-y);out[name+'_squared_error']=(pred-y)**2;out[name+'_bias']=pred-y
    if point is not None:out['rounded_point_hit']=(round_half_away(point)==y).astype(float)
    for t in scorecard['thresholds_f']:
        q=cdf[:,t+40];hit=(y<=t).astype(float)
        out[f'threshold_{t}_probability']=q;out[f'threshold_{t}_event']=hit;out[f'threshold_{t}_brier']=(q-hit)**2
    for level in [50,80,90,95]:
        out[f'interval_{level}_coverage']=((s[f'lower_{level}']<=y)&(y<=s[f'upper_{level}'])).astype(float)
        out[f'interval_{level}_width']=s[f'width_{level}'].astype(float)
    for t in [3,5,10]:
        out[f'ae_ge_{t}']=(np.abs(median_err)>=t).astype(float)
        out[f'warm_ge_{t}']=(median_err>=t).astype(float);out[f'cold_ge_{t}']=(median_err<=-t).astype(float)
    u=np.array([(int(hashlib.sha256(f'3750925|{i}'.encode()).hexdigest()[:16],16)+.5)/2**64 for i in issue_ids])
    left=np.where(yi>0,cdf[row,np.maximum(yi-1,0)],0)
    out['randomized_pit']=left+u*p[row,yi]
    for name,bands in scorecard['partitions'].items():
        b=partition_probabilities(p,bands);index=np.array([next(i for i,v in enumerate(bands) if v['lower']<=t<=v['upper']) for t in y]);one=np.zeros_like(b);one[row,index]=1
        mode=np.argmax(b,axis=1);prefix='synthetic_'+name
        out[prefix+'_brier']=np.sum((b-one)**2,axis=1)
        out[prefix+'_modal_hit']=(mode==index).astype(float)
        out[prefix+'_max_probability']=b.max(axis=1)
        integer_band=np.array([next(i for i,v in enumerate(bands) if v['lower']<=t<=v['upper']) for t in s['mode']])
        out[prefix+'_integer_mode_band_probability']=b[row,integer_band]
        out[prefix+'_integer_mode_band_hit']=(integer_band==index).astype(float)
    return out


def weighted_quantile(values,weights,q):
    v=np.asarray(values,dtype=float);w=np.asarray(weights,dtype=float)
    require(v.ndim==1 and w.shape==v.shape and 0<=q<=1,'Quantile arguments')
    require(np.all(np.isfinite(v)) and np.all(np.isfinite(w)) and np.all(w>=0) and w.sum()>0,'Quantile values/weights')
    keep=w>0;v=v[keep];w=w[keep];order=np.argsort(v,kind='stable');v=v[order];w=w[order]
    return float(v[min(np.searchsorted(np.cumsum(w),q*w.sum(),side='left'),len(v)-1)])


def aggregate_scores(scores,days,available=None):
    days=list(days);n=len(days);available=np.ones(n,dtype=bool) if available is None else np.asarray(available,dtype=bool)
    w=day_weights(days,available);out={'days':len(set(days)),'scored_days':len({d for d,a in zip(days,available) if a}),'rows':n,'scored_rows':int(available.sum())}
    for name,values in scores.items():
        a=np.asarray(values,dtype=float);require(a.shape==(n,),'Aggregate row count')
        require(np.all(np.isfinite(a[available])),'Nonfinite available score')
        out[name]=float(np.sum(a[available]*w[available])) if w.sum()>0 else None
    if 'mean_squared_error' in scores:out['rmse']=None if not w.sum() else float(np.sqrt(out['mean_squared_error']))
    for point in ['mean','median','named_point']:
        name=point+'_squared_error'
        if name in scores:out[point+'_rmse']=None if not w.sum() else float(np.sqrt(out[name]))
    if 'mae' in scores:
        for q in [.5,.9,.95,.99]:out[f'absolute_error_p{int(q*100)}']=weighted_quantile(np.asarray(scores['mae'])[available],w[available],q) if w.sum() else None
    return out


def reliability(probability,event,days,weights=None):
    p=np.asarray(probability,dtype=float);y=np.asarray(event,dtype=float);days=list(days)
    require(p.shape==y.shape==(len(days),) and np.all(np.isfinite(p)) and np.all((p>=0)&(p<=1)) and np.all((y==0)|(y==1)),'Invalid reliability input')
    w=day_weights(days,np.ones(len(days),dtype=bool)) if weights is None else np.asarray(weights,dtype=float)
    require(w.shape==p.shape and np.all(np.isfinite(w)) and np.all(w>=0),'Invalid reliability weights')
    if w.sum()==0:return {'bins':[],'ECE':None,'calibration_in_the_large':None}
    w=w/w.sum();index=np.minimum((p*10).astype(int),9);bins=[]
    for b in range(10):
        mask=(index==b)&(w>0);mass=w[mask].sum();distinct=len({d for d,m in zip(days,mask) if m})
        predicted=float(np.sum(w[mask]*p[mask])/mass) if mass else None;observed=float(np.sum(w[mask]*y[mask])/mass) if mass else None
        bins.append({'lower':b/10,'upper':(b+1)/10,'rows':int(mask.sum()),'days':distinct,'weight':float(mass),'mean_probability':predicted,'observed_rate':observed,'gap':None if not mass else observed-predicted,'sparse':distinct<30})
    return {'bins':bins,'ECE':float(sum(b['weight']*abs(b['gap']) for b in bins if b['weight'])),'calibration_in_the_large':float(np.sum(w*(y-p)))}


def confidence_threshold(confidence,days,expected_counts,coverage):
    require(coverage in [1.,.75,.5,.25,.1],'Unregistered coverage')
    q=np.asarray(confidence,dtype=float);require(q.shape==(len(days),) and np.all(np.isfinite(q)),'Invalid confidence values')
    require(len(q)>0,'No training confidence support')
    w=np.array([1/expected_counts[d] for d in days]);require(np.all(w>0),'Invalid expected counts')
    return -float('inf') if coverage==1 else weighted_quantile(q,w,1-coverage)


def selection_summary(confidence,hits,days,issue_ids,expected_counts,threshold,ranking_scores=None):
    """Rows include every expected issue; unavailable forecasts use NaN confidence/hit."""
    q=np.asarray(confidence,dtype=float);h=np.asarray(hits,dtype=float);days=list(days)
    require(q.shape==h.shape==(len(days),) and len(issue_ids)==len(days) and len(set(issue_ids))==len(days),'Selection row alignment')
    require(Counter(days)==Counter(expected_counts),'Selection must include every expected issue; missing forecasts remain explicit')
    require(not np.any(np.isinf(q)), 'Infinite confidence is not a missing forecast')
    rank=q if ranking_scores is None else np.asarray(ranking_scores,dtype=float)
    require(rank.shape==q.shape and not np.any(np.isinf(rank)), 'Invalid ranking scores')
    valid=np.isfinite(q)&np.isfinite(rank);require(np.all((q[valid]>=0)&(q[valid]<=1)) and np.all((h[valid]==0)|(h[valid]==1)),'Selection probabilities/events')
    require(not np.isnan(threshold),'Invalid threshold')
    admitted=valid&(rank>=threshold);w=np.array([1/expected_counts[d] for d in days]);den=w.sum();mass=w[admitted].sum()
    admitted_days={d for d,a in zip(days,admitted) if a};counts=Counter(d for d,a in zip(days,admitted) if a)
    expected=float(np.sum(w[admitted]*q[admitted])/mass) if mass else None
    observed=float(np.sum(w[admitted]*h[admitted])/mass) if mass else None
    within_day=[float(np.mean(h[[a and d==day for d,a in zip(days,admitted)]])) for day in sorted(admitted_days)]
    return {'expected_rows':len(days),'available_rows':int(valid.sum()),'admitted_rows':int(admitted.sum()),'expected_checkpoint_coverage':float(admitted.mean()) if days else 0.,'available_checkpoint_coverage':float(admitted.sum()/valid.sum()) if valid.any() else None,'dayweighted_coverage':float(mass/den) if den else 0.,'days_with_any_admission':len(admitted_days),'unique_day_coverage':len(admitted_days)/len(expected_counts) if expected_counts else 0.,'admitted_issues_per_day':{str(d):counts.get(d,0) for d in expected_counts},'hit_rate':observed,'mean_predicted_hit':expected,'calibration_gap':None if mass==0 else observed-expected,'equal_admitted_day_hit_rate':float(np.mean(within_day)) if within_day else None}


def paired_common_summary(model_scores,days,availability,issue_ids):
    require(model_scores and set(model_scores)==set(availability)==set(issue_ids),'Paired model identities')
    ordered=[list(issue_ids[k]) for k in sorted(model_scores)]
    require(all(ids==ordered[0] for ids in ordered) and len(set(ordered[0]))==len(days)==len(ordered[0]), 'Paired issue keys are not identically aligned')
    n=len(days);masks=[np.asarray(availability[k],dtype=bool) for k in sorted(model_scores)]
    require(all(m.shape==(n,) for m in masks),'Paired mask lengths')
    common=np.logical_and.reduce(masks)
    return {k:aggregate_scores(v,days,common) for k,v in model_scores.items()}
