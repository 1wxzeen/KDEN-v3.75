"""Self-contained unfloored native laws; no station-reference runtime imports.

Spline/tail and histogram integrals follow the read-only KPHX reference formulas.
Mass is half-open, including exact atoms; remote log mass never uses an epsilon.
"""
from __future__ import annotations
import math
import numpy as np
from scipy.special import logsumexp, log_ndtr, ndtr
from .common import ContractError


def interval(lo, hi):
    lo, hi = np.broadcast_arrays(np.asarray(lo, float), np.asarray(hi, float))
    if np.isnan(lo).any() or np.isnan(hi).any() or np.any(hi <= lo):
        raise ContractError("positive, ordered law interval required")
    return lo, hi


def probability(p):
    if not math.isfinite(p) or not 0 < p < 1:
        raise ContractError("interior quantile probability required")


def checked_crps(value):
    if not math.isfinite(value) or value < -1e-10:
        raise ContractError("invalid analytic CRPS")
    return max(0., float(value))  # roundoff only, never a statistical floor


def integer_mode(law, first, last):
    if last-first > 100000:
        raise ContractError("unexpectedly wide law; refuse unsupported mode search")
    bins = np.arange(first, last+1)
    masses = law.mass(bins-.5, bins+.5)
    j = int(np.argmax(masses))
    return int(bins[j]), float(masses[j])


class PointLaw:
    family = "EXACT_CONSTANT_CONTEXT_POINT_MASS"
    def __init__(self, point):
        if not math.isfinite(point): raise ContractError("nonfinite point law")
        self.point = float(point)
    def cdf(self, x, left=False):
        return np.asarray(x) > self.point if left else np.asarray(x) >= self.point
    def mass(self, lo, hi):
        lo, hi = interval(lo, hi)
        return np.asarray((lo <= self.point) & (self.point < hi), float)
    def log_mass(self, lo, hi): return 0. if float(self.mass(lo, hi)) else -math.inf
    def quantile(self, p): probability(p); return self.point
    def moments(self): return self.point, 0.
    def crps(self, y): return abs(self.point-y)
    def modal_integer(self): return math.floor(self.point+.5), 1.
    def payload(self): return {"kind": "point", "point_f": self.point}


class QuantileLaw:
    family = "TABICL_SORTED_QUANTILE_SPLINE_EXPONENTIAL_TAILS"
    def __init__(self, quantiles):
        raw = np.asarray(quantiles, float)
        if raw.shape != (999,) or not np.isfinite(raw).all():
            raise ContractError("999 finite native quantiles required")
        self.p = np.arange(1, 1000)/1000
        self.q = np.sort(raw)
        self.raw = raw
        self.crossings = int(np.count_nonzero(np.diff(raw)<0))
        self.max_sort_change = float(np.max(np.abs(raw-self.q)))
        def slope(x, y):
            x, y = x-x.mean(), y-y.mean()
            return max(0., float(x@y/(x@x)))
        self.beta_left = slope(np.log(self.p[:20]), self.q[:20])
        self.beta_right = slope(-np.log1p(-self.p[-20:]), self.q[-20:])
    def quantile(self, p):
        probability(p)
        if p < self.p[0]: return float(self.q[0]+self.beta_left*math.log(p/self.p[0]))
        if p > self.p[-1]: return float(self.q[-1]-self.beta_right*math.log((1-p)/(1-self.p[-1])))
        return float(np.interp(p, self.p, self.q))
    def cdf(self, x, left=False):
        x = np.asarray(x, float); flat = x.reshape(-1)
        j = np.searchsorted(self.q, flat, side="left" if left else "right")
        out = np.empty_like(flat); low = j == 0; high = j == len(self.q); middle = ~(low|high)
        out[low] = self.p[0]*np.exp(np.minimum(0., (flat[low]-self.q[0])/self.beta_left)) if self.beta_left else 0.
        out[high] = 1-(1-self.p[-1])*np.exp(np.minimum(0., (self.q[-1]-flat[high])/self.beta_right)) if self.beta_right else 1.
        k = j[middle]
        out[middle] = self.p[k-1]+(flat[middle]-self.q[k-1])/(self.q[k]-self.q[k-1])*(self.p[k]-self.p[k-1])
        return out.reshape(x.shape)
    def mass(self, lo, hi):
        lo, hi = interval(lo, hi)
        a, b, dp = self.q[:-1], self.q[1:], np.diff(self.p)
        width = b-a; overlap = np.maximum(0., np.minimum(hi[...,None],b)-np.maximum(lo[...,None],a))
        fraction = np.divide(overlap, width, out=np.zeros_like(overlap), where=width>0)
        fraction += ((width == 0) & (lo[...,None] <= a) & (a < hi[...,None]))
        result = fraction@dp
        for edge, beta, tail_p, is_left in [(self.q[0], self.beta_left, self.p[0], True),
                                           (self.q[-1], self.beta_right, 1-self.p[-1], False)]:
            if beta == 0:
                result += tail_p*((lo <= edge) & (edge < hi))
            else:
                aa, bb = (lo, np.minimum(hi,edge)) if is_left else (np.maximum(lo,edge), hi)
                span = np.maximum(0., bb-aa)
                exponent = (bb-edge)/beta if is_left else (edge-aa)/beta
                result += tail_p*np.exp(np.minimum(0.,exponent))*(-np.expm1(-span/beta))
        return result
    def log_mass(self, lo, hi):
        interval(lo, hi)
        if hi <= self.q[0] and self.beta_left:
            return math.log(self.p[0])+(hi-self.q[0])/self.beta_left+math.log(-math.expm1(-(hi-lo)/self.beta_left))
        if lo > self.q[-1] and self.beta_right:
            return math.log1p(-self.p[-1])+(self.q[-1]-lo)/self.beta_right+math.log(-math.expm1(-(hi-lo)/self.beta_right))
        m = float(self.mass(lo, hi)); return math.log(m) if m else -math.inf
    def moments(self):
        origin = self.q[499]; q = self.q-origin; dp = np.diff(self.p)
        mean = float(dp@((q[:-1]+q[1:])/2)+self.p[0]*(q[0]-self.beta_left)+(1-self.p[-1])*(q[-1]+self.beta_right))
        second = float(dp@((q[:-1]**2+q[:-1]*q[1:]+q[1:]**2)/3)
                       +self.p[0]*(q[0]**2-2*q[0]*self.beta_left+2*self.beta_left**2)
                       +(1-self.p[-1])*(q[-1]**2+2*q[-1]*self.beta_right+2*self.beta_right**2))
        return float(origin+mean), math.sqrt(max(0.,second-mean**2))
    def crps(self, y):
        lo, hi = self.q[:-1], self.q[1:]; width = hi-lo
        slope = np.divide(np.diff(self.p),width,out=np.zeros_like(width),where=width>0)
        before = np.clip(y-lo,0,width); middle = self.p[:-1]+before*slope
        total = float(np.sum(before*(self.p[:-1]**2+self.p[:-1]*middle+middle**2)/3)
                      +np.sum((width-before)*((1-middle)**2+(1-middle)*(1-self.p[1:])+(1-self.p[1:])**2)/3))
        for edge, beta, tail_p, delta in [(self.q[0],self.beta_left,self.p[0],y-self.q[0]),
                                        (self.q[-1],self.beta_right,1-self.p[-1],self.q[-1]-y)]:
            decay = math.exp(min(0.,delta)/beta) if beta else 0.
            total += beta*tail_p**2*decay**2/2
            if delta < 0: total += -delta-2*tail_p*beta*(1-decay)+tail_p**2*beta*(1-decay**2)/2
        return checked_crps(total)
    def modal_integer(self):
        return integer_mode(self,math.floor(self.q[0]+.5)-1,math.floor(self.q[-1]+.5)+1)
    def payload(self): return {"kind": "quantiles", "quantiles_f": self.raw.tolist()}


class HistogramLaw:
    family = "TABDPT_NATIVE_FINITE_PIECEWISE_UNIFORM"
    def __init__(self, borders, logits):
        self.edges = np.asarray(borders,float); self.logits = np.asarray(logits,float)
        if (self.edges.ndim != 1 or len(self.edges)<2 or self.logits.shape != (len(self.edges)-1,)
            or not np.isfinite(self.edges).all() or np.any(np.diff(self.edges)<=0)
            or not np.isfinite(self.logits).all()): raise ContractError("malformed finite native histogram")
        self.logp = self.logits-logsumexp(self.logits); self.probs = np.exp(self.logp)
        self.width = np.diff(self.edges); self.cumulative = np.r_[0.,np.cumsum(self.probs)]
        self.cumulative[-1] = 1.
    def cdf(self, x, left=False):
        x = np.asarray(x,float); j = np.clip(np.searchsorted(self.edges,x,side="right")-1,0,len(self.probs)-1)
        return np.clip(self.cumulative[j]+self.probs[j]*np.clip((x-self.edges[j])/self.width[j],0,1),0,1)
    def mass(self, lo, hi):
        lo,hi = interval(lo,hi)
        overlap = np.maximum(0.,np.minimum(hi[...,None],self.edges[1:])-np.maximum(lo[...,None],self.edges[:-1]))
        return (overlap/self.width)@self.probs
    def log_mass(self, lo, hi):
        interval(lo,hi)
        overlap = np.maximum(0.,np.minimum(hi,self.edges[1:])-np.maximum(lo,self.edges[:-1])); take = overlap>0
        return float(logsumexp(self.logp[take]+np.log(overlap[take]/self.width[take]))) if take.any() else -math.inf
    def quantile(self, p):
        probability(p); j = min(int(np.searchsorted(self.cumulative[1:],p,side="left")),len(self.probs)-1)
        if self.probs[j] <= 0: raise ContractError("quantile selected a zero-mass bin")
        return float(self.edges[j]+self.width[j]*(p-self.cumulative[j])/self.probs[j])
    def moments(self):
        mid = (self.edges[:-1]+self.edges[1:])/2; mean = float(mid@self.probs)
        return mean, math.sqrt(max(0.,float((self.width**2/12+(mid-mean)**2)@self.probs)))
    def crps(self,y):
        before = np.clip(y-self.edges[:-1],0,self.width); after = self.width-before
        c, slope = self.cumulative[:-1], self.probs/self.width; at = c+slope*before-1
        return checked_crps(np.sum(c*c*before+c*slope*before**2+slope*slope*before**3/3)
                            +np.sum(at*at*after+at*slope*after**2+slope*slope*after**3/3)
                            +max(0.,self.edges[0]-y)+max(0.,y-self.edges[-1]))
    def modal_integer(self): return integer_mode(self,math.floor(self.edges[0]+.5)-1,math.floor(self.edges[-1]+.5)+1)
    def payload(self): return {"kind": "histogram", "borders_f": self.edges.tolist(), "logits": self.logits.tolist()}


class AffineLaw:
    """Translate/scale a preserved shape without refitting or adding an anchor twice."""
    def __init__(self, base, shift=0., scale=1.):
        if not math.isfinite(shift) or not math.isfinite(scale) or scale<=0: raise ContractError("invalid law transform")
        self.base,self.shift,self.scale = base,float(shift),float(scale); self.family = base.family
    def cdf(self,x,left=False): return self.base.cdf((np.asarray(x)-self.shift)/self.scale,left=left)
    def mass(self,lo,hi): return self.base.mass((np.asarray(lo)-self.shift)/self.scale,(np.asarray(hi)-self.shift)/self.scale)
    def log_mass(self,lo,hi): return self.base.log_mass((lo-self.shift)/self.scale,(hi-self.shift)/self.scale)
    def quantile(self,p): return self.shift+self.scale*self.base.quantile(p)
    def moments(self):
        m,s = self.base.moments(); return self.shift+self.scale*m,self.scale*s
    def crps(self,y): return self.scale*self.base.crps((y-self.shift)/self.scale)
    def modal_integer(self):
        if isinstance(self.base, PointLaw): return math.floor(self.quantile(.5)+.5),1.
        knots = self.base.q if isinstance(self.base,QuantileLaw) else self.base.edges
        return integer_mode(self,math.floor(self.shift+self.scale*knots[0]+.5)-1,
                            math.floor(self.shift+self.scale*knots[-1]+.5)+1)


def gaussian_log_interval(a,b):
    # Evaluate on the nearer side of the normal; avoid subtracting two rounded ones.
    a,b = np.broadcast_arrays(a,b)
    la = np.where(a>=0,log_ndtr(-b),log_ndtr(a))
    lb = np.where(a>=0,log_ndtr(-a),log_ndtr(b))
    with np.errstate(divide="ignore",invalid="ignore"):
        return lb+np.log(-np.expm1(la-lb))


class KernelLaw:
    family = "EARLIER_CONTEXT_UNIFORM_GAUSSIAN_KERNEL_CONTROL_1_25F"
    def __init__(self, centers):
        self.centers = np.asarray(centers,float); self.bandwidth = 1.25
        if self.centers.ndim != 1 or not len(self.centers) or not np.isfinite(self.centers).all():
            raise ContractError("finite baseline kernel samples required")
    def cdf(self,x,left=False): return ndtr((np.asarray(x)[...,None]-self.centers)/1.25).mean(axis=-1)
    def mass(self,lo,hi):
        lo,hi = interval(lo,hi)
        return np.exp(gaussian_log_interval((lo[...,None]-self.centers)/1.25,(hi[...,None]-self.centers)/1.25)).mean(axis=-1)
    def log_mass(self,lo,hi):
        interval(lo,hi)
        return float(logsumexp(gaussian_log_interval((lo-self.centers)/1.25,(hi-self.centers)/1.25))-math.log(len(self.centers)))
    def moments(self): return float(self.centers.mean()),math.sqrt(float(self.centers.var())+1.25**2)
    def quantile(self,p):
        from scipy.optimize import brentq
        from scipy.special import ndtri
        probability(p); a = self.centers.min()+1.25*ndtri(p); b = self.centers.max()+1.25*ndtri(p)
        if a==b: return float(a)
        return float(brentq(lambda z: float(self.cdf(z))-p,a-1e-10,b+1e-10))
    def modal_integer(self): return integer_mode(self,math.floor(self.centers.min()+.5)-1,math.floor(self.centers.max()+.5)+1)
    def crps(self,y):
        def expected_abs(delta,sigma):
            z = delta/sigma
            return 2*sigma*np.exp(-z*z/2)/math.sqrt(2*math.pi)+delta*(2*ndtr(z)-1)
        first = expected_abs(y-self.centers,1.25).mean()
        # Bounded memory for the exact empirical Gaussian-mixture pair integral.
        second = sum(expected_abs(self.centers[i:i+128,None]-self.centers[None,:],math.sqrt(2)*1.25).sum()
                     for i in range(0,len(self.centers),128))/len(self.centers)**2
        return checked_crps(first-.5*second)
    def payload(self): return {"kind": "kernel", "centers_f": self.centers.tolist(), "bandwidth_f": 1.25}


def from_payload(value):
    kind = value["kind"]
    if kind=="point": return PointLaw(value["point_f"])
    if kind=="quantiles": return QuantileLaw(value["quantiles_f"])
    if kind=="histogram": return HistogramLaw(value["borders_f"],value["logits"])
    if kind=="kernel" and value["bandwidth_f"]==1.25: return KernelLaw(value["centers_f"])
    raise ContractError("unknown native law payload")


def native_law(raw,name,index,anchor):
    if not math.isfinite(anchor): raise ContractError("native law needs the actual Q05 anchor")
    # Pinned TabDPT 1.3.1 returns borders in original target (residual-F) space.
    if name=="tabicl": return QuantileLaw(np.asarray(raw["quantiles"][index])+anchor)
    if name=="tabdpt": return HistogramLaw(np.asarray(raw["borders"])+anchor,raw["logits"][index])
    raise ContractError("unknown learner")


def describe(law):
    mean,sigma = law.moments(); modal,modal_p = law.modal_integer()
    bins = np.arange(-40,121); pmf = law.mass(bins-.5,bins+.5)
    below,above = float(law.cdf(-40.5,left=True)),float(1-law.cdf(120.5,left=True))
    if not all(math.isfinite(x) for x in (mean,sigma,modal_p)) or abs(float(pmf.sum())+below+above-1)>1e-9:
        raise ContractError("invalid forecast moments or complete exported mass")
    return {"mean_f":mean,"sigma_f":sigma,"median_f":law.quantile(.5),"modal_integer_f":modal,
            "modal_probability":modal_p,"rounded_mean_integer_f":math.floor(mean+.5),
            "pmf_minus40_to120":pmf.tolist(),"pmf_below_minus40":below,"pmf_above120":above,
            "intervals":{str(level):[law.quantile((1-level/100)/2),law.quantile((1+level/100)/2)] for level in (50,80,90,95)}}


def losses(law,truth):
    if isinstance(truth,bool) or not float(truth).is_integer(): raise ContractError("integer verification target required")
    m,s = law.moments(); k,p = law.modal_integer(); lp = law.log_mass(truth-.5,truth+.5)
    return {"absolute_error_f":abs(m-truth),"squared_error_f":(m-truth)**2,"signed_error_f":m-truth,
            "median_absolute_error_f":abs(law.quantile(.5)-truth),"modal_integer_hit":int(k==truth),
            "integer_nll":-lp,"genuine_zero_probability":lp == -math.inf,
            "probability_underflow":math.isfinite(lp) and math.exp(lp)==0.,"crps_f":law.crps(truth)}
