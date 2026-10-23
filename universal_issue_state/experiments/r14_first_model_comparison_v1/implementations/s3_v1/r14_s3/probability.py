"""Stable native integer likelihood and analytic derivatives (no score floor)."""
import numpy as np
from scipy.special import log_ndtr,logsumexp,ndtr
from scipy.stats import t
from s0 import require
from r14_s1.probability import validate_pmf

def log_interval(a,b,family):
    require(np.all(a<b),'Nonpositive interval')
    cdf=log_ndtr if family=='normal' else lambda z:t.logcdf(z,5)
    sf=(lambda z:log_ndtr(-z)) if family=='normal' else lambda z:t.logsf(z,5)
    positive=a>=0
    upper=np.where(positive,sf(a),cdf(b));lower=np.where(positive,sf(b),cdf(a))
    with np.errstate(divide='ignore',invalid='ignore'):
        result=upper+np.log(-np.expm1(lower-upper))
    require(np.isfinite(result).all(),'Nonfinite interval log mass')
    return result

def likelihood(y,mu,sigma,family='normal'):
    require(family in ['normal','t5'],'Unknown family')
    y,mu,sigma=np.broadcast_arrays(y,mu,sigma)
    require(np.isfinite(mu).all() and np.isfinite(sigma).all() and (sigma>0).all(),'Invalid location/scale')
    a=np.where(y==-40,-np.inf,(y-.5-mu)/sigma);b=np.where(y==120,np.inf,(y+.5-mu)/sigma)
    lp=log_interval(a,b,family)
    lpdf=lambda z:-.5*z*z-.5*np.log(2*np.pi) if family=='normal' else t.logpdf(z,5)
    la,lb=lpdf(a),lpdf(b)
    def ratio(logs,signs):
        v,s=logsumexp(np.stack(logs),b=np.stack(signs),axis=0,return_sign=True)
        return s*np.exp(v-lp)
    dmu=ratio([la,lb],[np.ones_like(a),-np.ones_like(b)])/sigma
    with np.errstate(divide='ignore',invalid='ignore'):
        va=np.where(np.isfinite(a)&(a!=0),la+np.log(np.abs(a)),-np.inf)
        vb=np.where(np.isfinite(b)&(b!=0),lb+np.log(np.abs(b)),-np.inf)
    dlog=ratio([va,vb],[np.sign(a),-np.sign(b)])
    require(np.isfinite(dmu).all() and np.isfinite(dlog).all(),'Nonfinite derivatives')
    return -lp,-dmu,-dlog

def pmf(mu,sigma,family='normal'):
    mu,sigma=np.broadcast_arrays(np.atleast_1d(mu),np.atleast_1d(sigma))
    z=(np.arange(-39.5,120.)[None,:]-mu[:,None])/sigma[:,None]
    a,b=z[:,:-1],z[:,1:]
    cdf=ndtr if family=='normal' else lambda z:t.cdf(z,5)
    sf=(lambda z:ndtr(-z)) if family=='normal' else lambda z:t.sf(z,5)
    middle=np.where(a>=0,sf(a)-sf(b),cdf(b)-cdf(a))
    return validate_pmf(np.column_stack([cdf(z[:,0]),middle,sf(z[:,-1])]))
