"""Finite-window, bounded-input audits for the ordered elapsed-time branch.

Exact vertex principle in real arithmetic; reference execution is float64 with
explicit comparison tolerances, NOT outward-rounded certified numerics.
The recurrent tanh graph and squared delay features are outside this contract.
"""
import numpy as np

TAUS=np.array([.5,2.,8.,32.])
MARGIN=1e-12

def replay_features(u,h,a0=None,r0=None,taus=TAUS,substeps=1):
    """Batched held-input replay. Repeated substeps share the SAME input value."""
    u=np.asarray(u,float);h=np.asarray(h,float);taus=np.asarray(taus,float)
    if taus.ndim!=1 or not len(taus) or np.any(taus<=0) or not np.isfinite(taus).all():raise ValueError('invalid time constants')
    if not isinstance(substeps,int) or substeps<1:raise ValueError('invalid subdivision')
    if u.ndim==2:u=u[None]
    batch,n,m=u.shape
    if m!=2 or h.shape!=(n,) or np.any(h<=0) or not np.isfinite(h).all():raise ValueError('invalid durations')
    if not np.isfinite(u).all() or np.any(np.abs(u)>1):raise ValueError('input outside declared box')
    a=np.broadcast_to(np.zeros((len(taus),2)) if a0 is None else a0,(batch,len(taus),2)).copy()
    r=np.broadcast_to(np.zeros(len(taus)) if r0 is None else r0,(batch,len(taus))).copy()
    for j in range(n):
        e=np.exp(-h[j]/substeps/taus);v=-np.expm1(-h[j]/substeps/taus)
        for _ in range(substeps):
            r=e**2*r+e*v*(a[:,:,0]*u[:,j,1,None]-a[:,:,1]*u[:,j,0,None])
            a=e[None,:,None]*a+v[None,:,None]*u[:,j,None,:]
    return np.c_[np.ones(batch),u[:,-1],np.full(batch,np.log(h[-1])),a.reshape(batch,-1),r]

def sign_verdict(bounds,margin=MARGIN):
    lo,hi=map(float,bounds)
    if not np.isfinite([lo,hi]).all() or lo>hi:raise ValueError('empty or invalid evidence range')
    return 1 if lo>margin else (0 if hi < -margin else -1)

class VertexAudit:
    """A scalar multiaffine readout over a Cartesian box of buffered inputs.

    Queries identify an event-channel coordinate. Repeated identical readings
    are idempotent; conflicts are errors. No unknown true values enter selection.
    """
    def __init__(self,lower,upper,h,coefficients,a0=None,r0=None,taus=TAUS,max_missing=16):
        lo=np.array(lower,float);hi=np.array(upper,float);self.h=np.array(h,float)
        if lo.shape!=hi.shape or lo.ndim!=2 or lo.shape[1]!=2:raise ValueError('input shape')
        if not np.isfinite([lo,hi]).all() or np.any(lo>hi) or np.any(lo < -1) or np.any(hi>1):raise ValueError('invalid or empty input box')
        self.lower=lo;self.upper=hi;self.unknown=np.flatnonzero((hi>lo).ravel()).tolist();self.readings={};self.ledger=[]
        m=len(self.unknown)
        if m>max_missing:raise ValueError('enumeration budget exceeded; no claim issued')
        coeff=np.asarray(coefficients,float)
        if coeff.shape!=(4+3*len(taus),) or not np.isfinite(coeff).all():raise ValueError('readout shape')
        vertex=((np.arange(2**m)[:,None] >> np.arange(m-1,-1,-1))&1)
        u=np.broadcast_to(lo,(2**m,)+lo.shape).copy().reshape(2**m,-1)
        if m:u[:,self.unknown]=lo.ravel()[self.unknown]+vertex*(hi-lo).ravel()[self.unknown]
        self.values=(replay_features(u.reshape(2**m,*lo.shape),self.h,a0,r0,taus)@coeff).reshape((2,)*m or ())

    def bounds(self):return float(np.min(self.values)),float(np.max(self.values))

    def scores(self):
        """Exact worst-case remaining width after one noiseless coordinate query."""
        return {coord: max(float(np.ptp(np.take(self.values,side,axis=axis))) for side in [0,1])
                for axis,coord in enumerate(self.unknown)}

    def choose(self,policy='minimax',rng=None):
        if not self.unknown:return None
        if policy=='minimax':
            scores=self.scores();return min(scores,key=lambda k:(scores[k],k))
        if policy=='recent':return max(self.unknown)
        if policy=='random':return int(rng.choice(self.unknown))
        raise ValueError('unknown policy')

    def acquire(self,coordinate,value):
        coordinate=int(coordinate);value=float(value)
        if not np.isfinite(value):raise ValueError('nonfinite observation')
        if coordinate in self.readings:
            if self.readings[coordinate]!=value:raise ValueError('conflicting duplicate observation')
            return False
        if coordinate not in self.unknown:raise ValueError('coordinate is not a queryable missing field')
        low=self.lower.ravel()[coordinate];high=self.upper.ravel()[coordinate]
        if not low<=value<=high:raise ValueError('observation contradicts the declared bounds')
        before=self.bounds();axis=self.unknown.index(coordinate);s=(value-low)/(high-low)
        self.values=(1-s)*np.take(self.values,0,axis=axis)+s*np.take(self.values,1,axis=axis)
        self.unknown.pop(axis);self.lower.ravel()[coordinate]=value;self.upper.ravel()[coordinate]=value
        self.readings[coordinate]=value
        self.ledger.append(dict(coordinate=coordinate,value=value,before=before,after=self.bounds()))
        return True

def interval_bounds(lower,upper,h,coefficients,a0=None,r0=None,taus=TAUS):
    """Conservative box propagation; discards inter-coordinate dependencies."""
    al=np.zeros((len(taus),2)) if a0 is None else np.array(a0,float).copy();ah=al.copy()
    rl=np.zeros(len(taus)) if r0 is None else np.array(r0,float).copy();rh=rl.copy()
    def mul(l,r,v,w):
        allv=np.array([l*v,l*w,r*v,r*w]);return allv.min(0),allv.max(0)
    for lo,hi,dt in zip(lower,upper,h):
        e=np.exp(-dt/taus);v=-np.expm1(-dt/taus)
        pl,ph=mul(al[:,0],ah[:,0],lo[1],hi[1]);ql,qh=mul(al[:,1],ah[:,1],lo[0],hi[0])
        rl=e**2*rl+e*v*(pl-qh);rh=e**2*rh+e*v*(ph-ql)
        al=e[:,None]*al+v[:,None]*lo;ah=e[:,None]*ah+v[:,None]*hi
    fl=np.r_[1,lower[-1],np.log(h[-1]),al.ravel(),rl];fh=np.r_[1,upper[-1],np.log(h[-1]),ah.ravel(),rh]
    c=np.asarray(coefficients)
    return float(np.sum(np.where(c>=0,c*fl,c*fh))),float(np.sum(np.where(c>=0,c*fh,c*fl)))
