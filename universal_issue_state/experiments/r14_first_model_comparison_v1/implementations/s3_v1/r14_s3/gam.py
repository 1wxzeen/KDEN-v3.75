"""Penalized native discrete distributional regression; all starts audited."""
from dataclasses import replace
import numpy as np
from scipy.special import expit,logit
from scipy.optimize import minimize
from s0 import require,ContractError
from r14_s1.data import day_weights
from .data import check_training,center
from .design import Design
from .probability import likelihood,pmf

def subset(batch,indices):
    indices=np.asarray(indices,dtype=int)
    return replace(batch,X=batch.X[indices],available=batch.available[indices],metadata=tuple(batch.metadata[i] for i in indices),missing_features=tuple(batch.missing_features[i] for i in indices))

def scale_link(eta):
    low=np.log(.25);span=np.log(20.)-low;q=expit(eta)
    return np.exp(low+span*q),span*q*(1-q)

def objective(theta,A,B,offset,y,weights,lm,ls,family):
    beta=theta[:A.shape[1]];gamma=theta[A.shape[1]:];mu=offset+A@beta;sigma,d=scale_link(B@gamma)
    loss,dmu,dlog=likelihood(y,mu,sigma,family)
    penalty=.5*(lm*(beta[1:]@beta[1:])+ls*(gamma[1:]@gamma[1:]))
    gb=A.T@(weights*dmu);gg=B.T@(weights*dlog*d);gb[1:]+=lm*beta[1:];gg[1:]+=ls*gamma[1:]
    return float(weights@loss+penalty),np.r_[gb,gg]

class GAM:
    def __init__(self,batch,y,config,parameters):
        check_training(batch,y);self.batch=batch;self.config=config;self.parameters=parameters;self.model=batch.model_id
        require(self.model in ['GAM_LS_NORMAL','GAM_LOCATION_NORMAL','GAM_LS_T5'],'Unknown GAM')
        self.family='t5' if self.model=='GAM_LS_T5' else 'normal';self.starts=[]
        ids=np.where(batch.available)[0];train=subset(batch,ids);target=np.asarray(y)[ids];weights=day_weights(train.dates,np.ones(len(ids),dtype=bool))
        self.location=Design(train,weights,config);self.scale=Design(train,weights,config,scale=True,constant=self.model=='GAM_LOCATION_NORMAL')
        A,_=self.location.transform(train);B,_=self.scale.transform(train);offset=center(train);solver=config['gam']['solver'];valid=[]
        for index,initial in enumerate(solver['starts_sigma_f']):
            theta=np.zeros(A.shape[1]+B.shape[1]);theta[0]=weights@(target-offset);theta[A.shape[1]]=logit((np.log(initial)-np.log(.25))/(np.log(20)-np.log(.25)))
            try:
                result=minimize(objective,theta,args=(A,B,offset,target,weights,parameters['lambda_mu'],parameters['lambda_scale'],self.family),method='L-BFGS-B',jac=True,options={k:solver[k] for k in ['ftol','gtol','maxfun','maxiter','maxls']})
                value,grad=objective(result.x,A,B,offset,target,weights,parameters['lambda_mu'],parameters['lambda_scale'],self.family)
                gnorm=float(np.max(np.abs(grad)));accepted=bool(result.success and np.isfinite(value) and np.isfinite(result.x).all() and gnorm<=1e-4)
                self.starts.append({'start':index,'initial_sigma_f':initial,'accepted':accepted,'objective':value,'gradient_inf':gnorm,'iterations':int(result.nit),'message':str(result.message)})
                if accepted:valid.append((value,index,result.x))
            except (FloatingPointError,ValueError) as exc:self.starts.append({'start':index,'initial_sigma_f':initial,'accepted':False,'message':str(exc)})
        if not valid:
            error=ContractError('ALL_GAM_STARTS_FAILED');error.starts=self.starts;raise error
        best=min(valid,key=lambda item:(item[0],item[1]));self.theta=best[2];self.selected_start=best[1]
        require(np.isfinite(self.theta).all(),'Invalid fit')
    def forecast(self,query,parameters=None):
        require(query.model_id==self.model,'GAM model mismatch');require((min(query.dates)-max(self.batch.dates)).days>=2,'Training overlaps assessment/lag')
        centers=center(query);ids=np.where(query.available)[0];pred={}
        if len(ids):
            complete=subset(query,ids);A,outa=self.location.transform(complete);B,outb=self.scale.transform(complete);n=A.shape[1]
            mu=center(complete)+A@self.theta[:n];sigma,_=scale_link(B@self.theta[n:]);P=pmf(mu,sigma,self.family)
            for j,i in enumerate(ids):pred[i]=(mu[j],sigma[j],P[j],bool(outa[j] or outb[j]))
        for i,m in enumerate(query.metadata):
            if i not in pred:yield m,(float(centers[i]) if np.isfinite(centers[i]) else None),None,None,'MISSING_REQUIRED_INPUT',{};continue
            mu,sigma,p,outside=pred[i]
            diag={'location_f':float(mu),'scale_f':float(sigma),'continuous_sd_f':float(sigma*(np.sqrt(5/3) if self.family=='t5' else 1)),
                'scale_near_bound':bool(sigma<.275 or sigma>18.),'out_of_range':outside,'location_columns':self.location.dimension,'scale_columns':self.scale.dimension,'selected_start':self.selected_start,'distribution':self.family}
            yield m,float(centers[i]),p,float(mu),None,diag
