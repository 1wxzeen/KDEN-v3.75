"""Integer-Fahrenheit probabilities and explicit-boundary aggregation."""
import math
import numpy as np
from s0 import require

SUPPORT=np.arange(-40,121,dtype=np.int16)


def validate_pmf(p):
    p=np.asarray(p,dtype=float)
    require(p.ndim in (1,2) and p.shape[-1]==161,'PMF must have 161 integer masses')
    require(np.all(np.isfinite(p)) and np.all(p>=0),'Invalid PMF values')
    require(np.all(np.abs(p.sum(axis=-1)-1)<=1e-10),'PMF not normalized')
    return p


def _normal_interval(lo,hi):
    root=math.sqrt(2.0)
    if lo>=0:return .5*(math.erfc(lo/root)-math.erfc(hi/root))
    if hi<=0:return .5*(math.erfc(-hi/root)-math.erfc(-lo/root))
    return 1-.5*math.erfc(-lo/root)-.5*math.erfc(hi/root)


def normal_pmf(mu,sigma):
    require(math.isfinite(mu) and math.isfinite(sigma) and sigma>0,'Invalid normal parameters')
    boundaries=np.r_[-np.inf,np.arange(-39.5,120,1),np.inf]
    standardized=(boundaries-mu)/sigma
    p=np.array([_normal_interval(a,b) for a,b in zip(standardized[:-1],standardized[1:])])
    validate_pmf(p)
    return p


def residual_kernel_pmf(center,residuals,weights,sigma):
    residuals=np.asarray(residuals,dtype=float);weights=np.asarray(weights,dtype=float)
    require(residuals.ndim==1 and residuals.size>0 and weights.shape==residuals.shape,'Kernel dimensions')
    require(np.all(np.isfinite(residuals)) and np.all(np.isfinite(weights)) and np.all(weights>=0) and weights.sum()>0,'Invalid kernel weights/residuals')
    weights=weights/weights.sum()
    p=sum(w*normal_pmf(float(center+r),sigma) for r,w in zip(residuals,weights))
    return validate_pmf(p)


def round_half_away(x):
    x=np.asarray(x,dtype=float);require(np.all(np.isfinite(x)),'Nonfinite rounding input')
    return (np.sign(x)*np.floor(np.abs(x)+.5)).astype(np.int64)


def quantile(p,q):
    require(0<=q<=1,'Invalid quantile')
    p=validate_pmf(p);cdf=np.cumsum(p,axis=-1)
    # q=1 is defined at the first support point attaining mass 1 within FP tolerance.
    cdf[...,-1]=1.0
    return SUPPORT[np.argmax(cdf>=q,axis=-1)]


def summarize_pmf(p):
    p=validate_pmf(p);mean=p@SUPPORT
    with np.errstate(divide='ignore',invalid='ignore'):
        entropy=-np.where(p>0,p*np.log(p),0).sum(axis=-1)
    out={'mean':mean,'median':quantile(p,.5),'mode':SUPPORT[np.argmax(p,axis=-1)],'variance':np.sum(p*(SUPPORT-np.expand_dims(mean,-1))**2,axis=-1),'entropy':entropy,'max_integer_probability':p.max(axis=-1),'endpoint_mass':p[...,0]+p[...,-1]}
    for level in [.5,.8,.9,.95]:
        key=str(round(level*100));lo=quantile(p,(1-level)/2);hi=quantile(p,(1+level)/2)
        out['lower_'+key]=lo;out['upper_'+key]=hi;out['width_'+key]=hi-lo
    return out


def inclusive_band_probability(p,lower,upper):
    """Sum the explicitly supplied integer bounds. No outcome-to-band inference."""
    p=validate_pmf(p)
    require(lower is None or type(lower) is int,'Lower bound must be integer or None')
    require(upper is None or type(upper) is int,'Upper bound must be integer or None')
    lo=-40 if lower is None else lower;hi=120 if upper is None else upper
    require(lo<=hi,'Reversed band')
    mask=(SUPPORT>=lo)&(SUPPORT<=hi)
    return p[...,mask].sum(axis=-1)


def partition_probabilities(p,bands):
    """Exhaustive synthetic diagnostic partitions; not historical market listings."""
    expanded=[]
    for b in bands:
        require(type(b['lower']) is int and type(b['upper']) is int,'Noninteger diagnostic band')
        require(b['lower']<=b['upper'],'Reversed diagnostic band')
        expanded.extend(range(b['lower'],b['upper']+1))
    require(expanded==list(range(-40,121)),'Partition must cover support once, in order')
    return np.stack([inclusive_band_probability(p,b['lower'],b['upper']) for b in bands],axis=-1)
