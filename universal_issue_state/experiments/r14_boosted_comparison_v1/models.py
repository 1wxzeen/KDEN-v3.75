"""Two distinct, registered boosted probabilistic residual models."""
import numpy as np
from scipy.special import ndtr
from sklearn.tree import DecisionTreeRegressor
from ngboost import NGBRegressor
from ngboost.distns import Normal
from ngboost.scores import LogScore
import xgboost as xgb
from r14_s1.scoring import weighted_quantile

class WeightedNormalBoost(NGBRegressor):
    # NGBoost 0.5.6's marginal initializer ignores sample_weight. Correct it explicitly.
    def fit(self,X,Y,**kwargs):
        self.initial_weights_=np.asarray(kwargs.get('sample_weight',np.ones(len(Y))),float)
        result=super().fit(X,Y,**kwargs)
        del self.initial_weights_
        return result
    def fit_init_params_to_marginal(self,Y,sample_weight=None,iters=1000):
        w=self.initial_weights_;mu=np.average(Y,weights=w);sd=max(float(np.sqrt(np.average((Y-mu)**2,weights=w))),.25)
        self.init_params=np.array([mu,np.log(sd)])

def training_weights(days):
    _,idx,cnt=np.unique(days,return_inverse=True,return_counts=True)
    return 1/cnt[idx] # sum = number of days; XGB leaf weights/penalties have day units.

def fit_imputer(X,w):
    X=np.asarray(X,float);w=np.asarray(w,float)
    meds=[];allmissing=[]
    for j in range(X.shape[1]):
        ok=np.isfinite(X[:,j]);allmissing.append(not ok.any());meds.append(weighted_quantile(X[ok,j],w[ok],.5) if ok.any() else 0.)
    return {'medians':meds,'all_missing':allmissing,'columns':X.shape[1]}

def transform(X,state):
    X=np.asarray(X,float);missing=~np.isfinite(X)
    return np.column_stack([np.where(missing,np.array(state['medians']),X),missing.astype(float)]).astype(np.float32)

def fit_model(X,y,days,candidate,cfg):
    if not np.all(np.isfinite(y)):raise ValueError('Missing training residual')
    w=training_weights(days);state=fit_imputer(X,w);A=transform(X,state)
    if candidate['family']=='XGB_QUANTILE':
        p=cfg['xgb'];model=xgb.XGBRegressor(objective='reg:quantileerror',quantile_alpha=np.array(p['quantiles']),n_estimators=candidate['rounds'],max_depth=candidate['depth'],random_state=cfg['seed'],**{k:v for k,v in p.items() if k!='quantiles'})
    else:
        p=cfg['ngb'];tree=DecisionTreeRegressor(max_depth=candidate['depth'],min_samples_leaf=p['min_samples_leaf'],min_weight_fraction_leaf=p['min_weight_fraction_leaf'],criterion='friedman_mse',random_state=cfg['seed'])
        model=WeightedNormalBoost(Dist=Normal,Score=LogScore,Base=tree,n_estimators=candidate['rounds'],learning_rate=p['learning_rate'],natural_gradient=True,minibatch_frac=1.,col_sample=1.,tol=p['tol'],verbose=False,random_state=cfg['seed'])
    model.fit(A,y,sample_weight=w)
    return {'model':model,'imputer':state,'candidate':candidate,'training_days':len(set(days)),'training_rows':len(days)}

def repair_quantiles(q,gap=.05):
    q=np.asarray(q,float)
    if q.ndim!=2 or q.shape[1]!=9 or not np.all(np.isfinite(q)):raise ValueError('Invalid predicted quantiles')
    crossing=np.any(np.diff(q,axis=1)<0,axis=1);s=np.sort(q,axis=1);out=s.copy()
    for j in range(3,-1,-1):out[:,j]=np.minimum(s[:,j],out[:,j+1]-gap)
    for j in range(5,9):out[:,j]=np.maximum(s[:,j],out[:,j-1]+gap)
    return out,crossing,np.max(np.abs(out-q),axis=1)

def quantile_cdf(q,x,alphas):
    a=np.asarray(alphas);x=np.asarray(x);out=np.empty((len(q),len(x)))
    for i,knots in enumerate(q):
        v=np.interp(x,knots,a);low=x<knots[0];high=x>knots[-1]
        ls=max((knots[1]-knots[0])/np.log(a[1]/a[0]),.25);us=max((knots[-1]-knots[-2])/np.log((1-a[-2])/(1-a[-1])),.25)
        v[low]=a[0]*np.exp((x[low]-knots[0])/ls);v[high]=1-(1-a[-1])*np.exp(-(x[high]-knots[-1])/us);out[i]=v
    return out

def predict_pmf(fit,X,offset,cfg):
    A=transform(X,fit['imputer']);offset=np.asarray(offset);cuts=np.arange(-39.5,120.,1.)
    if fit['candidate']['family']=='XGB_QUANTILE':
        raw=fit['model'].predict(A);q,cross,repair=repair_quantiles(raw,cfg['pmf']['minimum_quantile_gap_f']);q=q+offset[:,None]
        cdf=quantile_cdf(q,cuts,cfg['xgb']['quantiles']);point=q[:,4];diag={'quantile_crossed':cross.astype(float),'quantile_max_repair_f':repair}
    else:
        dist=fit['model'].pred_dist(A);mu=np.asarray(dist.params['loc']);sigma=np.asarray(dist.params['scale'])
        if not np.all(np.isfinite(mu)) or not np.all(np.isfinite(sigma)) or np.any(sigma<=0):raise ValueError('Invalid NGBoost distribution')
        lo=cfg['ngb']['scale_output_floor_f'];hi=cfg['ngb']['scale_output_ceiling_f'];s=np.clip(sigma,lo,hi);point=offset+mu;cdf=ndtr((cuts[None,:]-point[:,None])/s[:,None]);diag={'scale_guard_applied':(s!=sigma).astype(float),'scale_f':s,'native_scale_f':sigma}
    p=np.diff(np.column_stack([np.zeros(len(X)),cdf,np.ones(len(X))]),axis=1)
    if not np.all(np.isfinite(p)) or np.any(p< -1e-12) or not np.allclose(p.sum(axis=1),1,atol=1e-10):raise ValueError('Invalid PMF')
    p=np.maximum(p,0);p/=p.sum(axis=1,keepdims=True)
    return p,point,diag
