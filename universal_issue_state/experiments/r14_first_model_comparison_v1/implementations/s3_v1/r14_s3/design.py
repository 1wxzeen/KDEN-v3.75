"""Training-only low-rank spline basis, with saved knots, centering and scaling."""
import numpy as np
from scipy.interpolate import BSpline
from r14_s1.scoring import weighted_quantile
from .data import get

class Design:
    def __init__(self,batch,weights,config,scale=False,constant=False):
        self.blocks=[];self.config=config;self.constant=constant
        if not constant:
            for name in config['gam']['scale_weather_smooths' if scale else 'location_weather_smooths']:
                x=get(batch,name);lo=float(x.min());hi=float(x.max());mid=weighted_quantile(x,weights,.5)
                spline=len(np.unique(x))>=5 and lo<mid<hi
                self.blocks.append({'name':name,'kind':'spline' if spline else 'linear','lo':lo,'hi':hi,'knots':[lo]*4+[mid]+[hi]*4 if spline else None})
            self.blocks.append({'name':'clock_issue_minutes_since_0200','kind':'spline','lo':0.,'hi':840.,'knots':[0.]*4+[280.,560.]+[840.]*4})
            for name in ([] if scale else config['gam']['location_linear']):
                x=get(batch,name);self.blocks.append({'name':name,'kind':'linear','lo':float(x.min()),'hi':float(x.max()),'knots':None})
        raw,_=self.raw(batch);self.mean=weights@raw
        rms=np.sqrt(weights@((raw-self.mean)**2));self.keep=rms>1e-12;self.rms=np.where(self.keep,rms,1.)
        self.dimension=1+int(self.keep.sum())
    def raw(self,batch):
        columns=[];outside=np.zeros(len(batch.metadata),dtype=bool)
        for b in self.blocks:
            x=get(batch,b['name']);outside|=(x<b['lo'])|(x>b['hi']);x=np.clip(x,b['lo'],b['hi'])
            if b['kind']=='spline':
                B=BSpline.design_matrix(x,b['knots'],3,extrapolate=False).toarray()[:,:-1];columns.extend(B.T)
            else:columns.append(x)
        if not self.constant:
            angle=np.arctan2(get(batch,'clock_target_doy_sin'),get(batch,'clock_target_doy_cos'))
            for k in range(1,5):columns.extend([np.sin(k*angle),np.cos(k*angle)])
        return (np.column_stack(columns) if columns else np.empty((len(batch.metadata),0))),outside
    def transform(self,batch):
        raw,outside=self.raw(batch);scaled=((raw-self.mean)/self.rms)[:,self.keep]
        return np.column_stack([np.ones(len(batch.metadata)),scaled]),outside
