"""Residual analog ensemble with balanced physical-group distance."""
from datetime import date
import numpy as np
from scipy.special import logsumexp
from scipy.spatial.distance import cdist
from s0 import require
from r14_s1.scoring import weighted_quantile
from .data import weather,center,check_training
from .probability import pmf

def doy(d):return (date(2000,d.month,d.day)-date(2000,1,1)).days

def scale_fit(X):
    med=np.median(X,axis=0);sc=np.quantile(X,.75,axis=0)-np.quantile(X,.25,axis=0)
    for backup in [1.4826*np.median(np.abs(X-med),axis=0),np.std(X,axis=0)]:sc=np.where(sc>0,sc,backup)
    active=sc>0;return med,np.where(active,sc,1.),active

def coordinate_weights(names,groups,active):
    groups=[[names.index(n) for n in g if active[names.index(n)]] for g in groups]
    groups=[g for g in groups if g];w=np.zeros(len(names))
    for g in groups:w[g]=1/(len(groups)*len(g))
    return w

class Analog:
    def __init__(self,batch,y,config):
        check_training(batch,y);self.batch=batch;self.config=config;self.groups={};self.reference_cache={}
        X=weather(batch,config);res=np.asarray(y)-center(batch)
        for minute in sorted({m['local_minutes_since_0200'] for m in batch.metadata}):
            ids=[i for i,m in enumerate(batch.metadata) if batch.available[i] and m['local_minutes_since_0200']==minute]
            if not ids:continue
            ids=sorted(ids,key=lambda i:(batch.metadata[i]['target_date'],batch.metadata[i]['issue_state_id']))
            x=X[ids];med,sc,active=scale_fit(x);w=coordinate_weights(list(config['features']),config['groups'],active)
            self.groups[minute]={'ids':np.array(ids),'X':x,'Z':(x-med)/sc*np.sqrt(w),'median':med,'scale':sc,'active':active,'weights':w,'residuals':res[ids],
                'doy':np.array([doy(batch.metadata[i]['target_date']) for i in ids]),'min':x.min(axis=0),'max':x.max(axis=0)}
    def references(self,minute,width,k):
        key=(minute,width,k)
        if key in self.reference_cache:return self.reference_cache[key]
        g=self.groups[minute];distance=cdist(g['Z'],g['Z']);delta=np.abs(g['doy'][:,None]-g['doy']);eligible=np.minimum(delta,366-delta)<=width;np.fill_diagonal(eligible,False)
        counts=eligible.sum(axis=1);distance[~eligible]=np.inf
        valid=counts>=max(40,k)
        values=np.partition(distance,k-1,axis=1)[:,k-1][valid] if len(distance)>=k else np.array([])
        self.reference_cache[key]=values;return values
    def forecast(self,query,parameters):
        require(query.model_id=='ANEN','Analog model mismatch');require((min(query.dates)-max(self.batch.dates)).days>=2,'Training overlaps assessment/lag')
        X=weather(query,self.config);centers=center(query);w=parameters['seasonal_half_width_days'];k=parameters['neighbors'];b=parameters['bandwidth_multiplier'];sigma=parameters['kernel_sigma_f']
        for i,m in enumerate(query.metadata):
            reason=None;diag={};p=None;point=None;minute=m['local_minutes_since_0200'];g=self.groups.get(minute)
            if not query.available[i]:reason='MISSING_REQUIRED_INPUT'
            elif g is None:reason='NO_EXACT_ISSUE_TRAINING'
            elif not g['active'].any():reason='ALL_COORDINATES_CONSTANT'
            else:
                delta=np.abs(g['doy']-doy(m['target_date']));pool=np.where(np.minimum(delta,366-delta)<=w)[0];diag['pool_days']=len(pool)
                if len(pool)<40:reason='INSUFFICIENT_ANALOG_POOL'
                elif len(pool)<k:reason='INFEASIBLE_NEIGHBOR_COUNT'
                else:
                    z=(X[i]-g['median'])/g['scale']*np.sqrt(g['weights']);distance=np.sqrt(np.sum((g['Z'][pool]-z)**2,axis=1))
                    order=np.argsort(distance,kind='stable')[:k];selected=pool[order];dist=distance[order];h=max(float(dist[-1])*b,1e-12)
                    logw=-.5*(dist/h)**2;weights=np.exp(logw-logsumexp(logw));res=g['residuals'][selected]
                    p=weights@pmf(centers[i]+res,np.full(k,sigma));point=float(centers[i]+weights@res)
                    refs=self.references(minute,w,k);q=None if len(refs)<40 else float(np.mean(refs<=dist[-1]));ood_limit=None if len(refs)<40 else float(np.quantile(refs,.95))
                    active=g['active'];outside=float(np.mean(((X[i]<g['min'])|(X[i]>g['max']))[active]));median=weighted_quantile(res,weights,.5)
                    diag.update(neighbor_days=k,effective_sample_size=float(1/(weights@weights)),nearest_distance=float(dist[0]),kth_distance=float(dist[-1]),distance_concentration=float((dist[-1]-dist[0])/max(dist[-1],1e-12)),distance_quantile=q,reference_count=len(refs),out_of_range_fraction=outside,ood=bool(outside>.25 or (ood_limit is not None and dist[-1]>ood_limit)),kernel_sigma_f=sigma,weighted_residual_mad_f=1.4826*weighted_quantile(np.abs(res-median),weights,.5),active_coordinates=int(active.sum()),neighbors=[self.batch.metadata[g['ids'][j]]['issue_state_id'] for j in selected],weights=weights.tolist())
            yield m,(float(centers[i]) if np.isfinite(centers[i]) else None),p,point,reason,diag
