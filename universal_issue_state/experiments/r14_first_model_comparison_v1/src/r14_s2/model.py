"""Deterministic exact-issue seasonal residual mixtures."""
from datetime import date
import hashlib
import numpy as np
import s0
from r14_s1.probability import normal_pmf, validate_pmf


def digest(value):
    return hashlib.sha256(s0.canonical(value)).hexdigest()


def calendar_index(d):
    return (date(2000,d.month,d.day)-date(2000,1,1)).days


def seasonal_distance(a,b):
    delta=np.abs(np.asarray(a)-np.asarray(b))
    return np.minimum(delta,366-delta)


def mixture(center,residuals,sigma,engine='reference'):
    residuals=np.asarray(residuals,dtype=float)
    s0.require(residuals.size>0 and np.isfinite(residuals).all() and np.isfinite(center) and sigma>0,'Invalid residual mixture')
    if engine=='reference':
        result=np.mean([normal_pmf(center+r,sigma) for r in residuals],axis=0)
    else:
        s0.require(engine=='scipy','Unknown probability engine')
        from scipy.special import ndtr
        # Survival differences for positive tails avoid catastrophic cancellation.
        z=(np.arange(-39.5,120.,1.)[None,:]-center-residuals[:,None])/sigma
        lo=z[:,:-1];hi=z[:,1:]
        middle=np.where(lo>=0,ndtr(-lo)-ndtr(-hi),ndtr(hi)-ndtr(lo))
        result=np.concatenate(([ndtr(z[:,0]).mean()],middle.mean(axis=0),[ndtr(-z[:,-1]).mean()]))
    validate_pmf(result)
    return result


class ResidualFit:
    def __init__(self,batch,labels):
        s0.require(batch.split=='TRAIN','Fit requires training batch')
        s0.require(len(labels)==len(batch.metadata) and np.isfinite(labels).all(),'Invalid training labels')
        self.batch=batch
        self.groups={}
        self.pool_cache={}
        center=batch.baseline_center_f
        seen=set()
        for i,m in enumerate(batch.metadata):
            key=(m['target_date'],m['local_minutes_since_0200'])
            s0.require(key not in seen,'Repeated training day at exact issue')
            seen.add(key)
            if batch.available[i]:
                self.groups.setdefault(key[1],[]).append((key[0],float(labels[i]-center[i]),m['issue_state_id']))
        self.groups={k:sorted(v) for k,v in self.groups.items()}

    def pool(self,metadata,width):
        q=calendar_index(metadata['target_date']);key=(metadata['local_minutes_since_0200'],q,width)
        if key not in self.pool_cache:
            rows=self.groups.get(key[0],[])
            self.pool_cache[key]=[r for r in rows if min(abs(calendar_index(r[0])-q),366-abs(calendar_index(r[0])-q))<=width]
        return self.pool_cache[key]

    def counts(self,query,width):
        return np.array([len(self.pool(m,width)) if query.available[i] else 0 for i,m in enumerate(query.metadata)])

    def artifact_rows(self):
        return [{'target_date':d,'local_minutes_since_0200':minute,'residual_f':r,'issue_state_id':key}
                for minute,rows in sorted(self.groups.items()) for d,r,key in rows]

    def forecast(self,query,parameters,engine='reference'):
        s0.require(query.model_id==self.batch.model_id,'Fit/query model mismatch')
        s0.require((min(query.dates)-max(self.batch.dates)).days>=2,'Training overlaps assessment')
        width=parameters['seasonal_half_width_days'];sigma=parameters['kernel_sigma_f']
        centers=query.baseline_center_f
        for i,m in enumerate(query.metadata):
            pool=self.pool(m,width) if query.available[i] else []
            residuals=np.array([r[1] for r in pool])
            center=float(centers[i]) if query.available[i] else None
            reason='MISSING_CENTER' if center is None else ('INSUFFICIENT_RESIDUAL_POOL' if len(pool)<40 else None)
            p=None if reason else mixture(center,residuals,sigma,engine)
            diagnostics={'pool_days':len(pool),'kernel_sigma_f':sigma,'seasonal_half_width_days':width,
                         'residual_mean_f':float(residuals.mean()) if len(pool) else None,
                         'residual_sd_f':float(residuals.std()) if len(pool) else None,
                         'effective_sample_size':len(pool),'uniform_weights':True}
            yield m,center,p,reason,diagnostics


def support_summary(dates,mask):
    dates=np.array(dates);mask=np.array(mask,dtype=bool)
    unique=sorted(set(dates));count=sum(bool(mask[dates==d].any()) for d in unique)
    coverage=float(np.mean([mask[dates==d].mean() for d in unique]))
    return {'eligible_days':count,'expected_days':len(unique),'expected_rows':len(mask),
            'available_rows':int(mask.sum()),'dayweighted_coverage':coverage,
            'included':count>=60 and coverage>=0.5}


def day_losses(p,y,dates):
    p=np.asarray(p);y=np.asarray(y)
    validate_pmf(p)
    s0.require(len(p)==len(y)==len(dates) and np.all(y==y.astype(int)) and np.all((y>=-40)&(y<=120)),'Invalid scoring labels')
    adjusted=np.maximum(p,1e-6);adjusted/=adjusted.sum(axis=1,keepdims=True)
    losses=-np.log(adjusted[np.arange(len(y)),y.astype(int)+40])
    dates=np.array(dates)
    return {str(d):float(losses[dates==d].mean()) for d in sorted(set(dates))}


def choose(candidates,losses,tolerance=1e-10):
    s0.require(set(losses)=={c['candidate_id'] for c in candidates},'Incomplete candidate scores')
    keys=[set(v) for v in losses.values()]
    s0.require(keys and keys[0] and all(k==keys[0] for k in keys),'Candidate tuning populations differ')
    means={k:float(np.mean(list(v.values()))) for k,v in losses.items()}
    s0.require(all(np.isfinite(list(means.values()))),'Nonfinite candidate scores')
    best=min(means.values())
    tied=[c for c in candidates if means[c['candidate_id']]<=best+tolerance]
    selected=max(tied,key=lambda c:(c['parameters']['seasonal_half_width_days'],c['parameters']['kernel_sigma_f']))
    return selected,means
