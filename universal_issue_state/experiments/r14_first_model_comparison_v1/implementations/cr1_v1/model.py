"""Registered small reliability models; no temperature-PMF modification."""
import numpy as np
from scipy.special import expit
from scipy.optimize import minimize


def day_weights(days,mask):
    days=np.asarray(days);mask=np.asarray(mask,bool);_,idx=np.unique(days,return_inverse=True)
    count=np.bincount(idx,weights=mask);n=np.count_nonzero(count)
    return np.divide(mask.astype(float),count[idx]*n,out=np.zeros(len(days)),where=count[idx]>0) if n else np.zeros(len(days))


def design(native,minutes,sin,cos,weather,registration):
    p=np.asarray(native,float);valid=np.isfinite(p)&(p>=0)&(p<=1)
    p=np.clip(p,*registration['estimator']['logit_clip']);t=np.asarray(minutes)/840
    shared=np.column_stack([np.log(p)-np.log1p(-p),t,t*t,sin,cos,2*sin*cos,cos*cos-sin*sin])
    extra=[]
    for f in registration['weather_features']:
        x=np.asarray(weather[f['column']],float).copy();valid &= np.isfinite(x)
        if f['transform']=='log1p':
            valid &= x>=0;x=np.log1p(np.where(x>=0,x,np.nan))
        elif f['transform']=='absolute':x=np.abs(x)
        extra.append(x)
    full=np.column_stack([shared,*extra]);valid &= np.all(np.isfinite(full),axis=1)
    return {'R0':shared[:,:1],'R1':shared,'R2':full},valid


def objective(beta,X,y,w,lam):
    eta=X@beta;pen=beta.copy();pen[0]=0
    return float(w@(np.logaddexp(0,eta)-y*eta)+lam/2*(pen@pen)),X.T@(w*(expit(eta)-y))+lam*pen


def fit(X,y,days,mask,registration):
    X=np.asarray(X,float);y=np.asarray(y,float);mask=np.asarray(mask,bool)
    if not np.all(np.isfinite(X[mask])) or not np.all(np.isin(y[mask],[0,1])):raise ValueError('Invalid fit values')
    ch=registration['chronology'];nd=len(set(np.asarray(days)[mask]))
    if nd<ch['minimum_fit_days'] or y[mask].sum()<ch['minimum_fit_hits'] or (1-y[mask]).sum()<ch['minimum_fit_misses']:raise ValueError('INSUFFICIENT_SUPPORT')
    w=day_weights(days,mask)[mask];raw=X[mask];mu=w@raw;sd=np.sqrt(w@((raw-mu)**2));keep=sd>1e-12
    A=np.column_stack([np.ones(mask.sum()),((raw-mu)/np.where(keep,sd,1))[:,keep]])
    result=minimize(objective,np.zeros(A.shape[1]),args=(A,y[mask],w,registration['estimator']['ridge_lambda']),jac=True,method='L-BFGS-B',options={'maxiter':2000,'gtol':1e-6,'ftol':1e-12})
    value,grad=objective(result.x,A,y[mask],w,registration['estimator']['ridge_lambda'])
    if not result.success or not np.isfinite(value) or not np.all(np.isfinite(result.x)) or np.max(np.abs(grad))>1e-4:raise ValueError('SOLVER_FAILURE: '+str(result.message))
    return {'mean':mu.tolist(),'sd':sd.tolist(),'keep':keep.tolist(),'beta':result.x.tolist(),'fit_days':nd,'fit_rows':int(mask.sum()),'hits':int(y[mask].sum()),'misses':int((1-y[mask]).sum()),'objective':value,'gradient_inf':float(np.abs(grad).max()),'iterations':int(result.nit),'converged':True}


def predict(state,X,mask):
    keep=np.array(state['keep'],bool);raw=np.asarray(X)[mask];sd=np.array(state['sd']);A=np.column_stack([np.ones(mask.sum()),((raw-state['mean'])/np.where(keep,sd,1))[:,keep]])
    out=np.full(len(X),np.nan);out[mask]=expit(A@state['beta']);return out


def threshold(p,days,expected_counts,mask,coverage,minimum_days=120):
    mask=np.asarray(mask,bool)&np.isfinite(p)
    if len(set(np.asarray(days)[mask]))<minimum_days:raise ValueError('INSUFFICIENT_THRESHOLD_SUPPORT')
    if coverage==1:return None
    if not 0<coverage<1:raise ValueError('Invalid coverage')
    x=np.asarray(p)[mask];w=1/np.asarray(expected_counts)[mask];ix=np.argsort(x,kind='stable');cum=np.cumsum(w[ix]);j=min(np.searchsorted(cum,(1-coverage)*cum[-1],side='left'),len(ix)-1)
    return float(x[ix[j]])


def admit(p,available,cut):return np.asarray(available,bool)&np.isfinite(p)&(np.asarray(p)>=(-np.inf if cut is None else cut))
