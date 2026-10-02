"""Quadratic ordered-memory readouts and polynomial-cost outer ranges.

The symbolic polynomial is exact in real arithmetic. Its coefficient enclosure
is generally conservative. Float64 execution is not outward-rounded verification.
"""
import numpy as np
from itertools import combinations

def pairs(dim):return list(combinations(range(dim),2))

def memory_features(u,h,taus,ordered=True):
    u=np.asarray(u,float);h=np.asarray(h,float);taus=np.asarray(taus,float)
    if u.ndim==2:u=u[None]
    batch,n,dim=u.shape
    if h.shape!=(n,) or np.any(h<=0) or np.any(taus<=0) or not np.isfinite(u).all():raise ValueError('invalid data')
    a=np.zeros((batch,len(taus),dim));pp=pairs(dim);area=np.zeros((batch,len(taus),len(pp)))
    ia=np.array([x for x,y in pp]);ib=np.array([y for x,y in pp])
    for t in range(n):
        e=np.exp(-h[t]/taus);v=-np.expm1(-h[t]/taus)
        if ordered:area=e[None,:,None]**2*area+(e*v)[None,:,None]*(a[:,:,ia]*u[:,t,:][:,ib][:,None,:]-a[:,:,ib]*u[:,t,:][:,ia][:,None,:])
        a=e[None,:,None]*a+v[None,:,None]*u[:,t,None,:]
    features=[np.ones((batch,1)),u[:,-1],a.reshape(batch,-1)]
    if ordered:features.append(area.reshape(batch,-1))
    return np.concatenate(features,axis=1)

def compile_readouts(coefficients,h,taus,dim):
    """f(x)=c+b*x+0.5*x.T*Q*x, symmetric Q with zero diagonal.
    Feature order: intercept,current input,all means,all oriented pair areas.
    Initial state is zero. Coordinates are ordered event first, channel second.
    """
    co=np.atleast_2d(np.asarray(coefficients,float));h=np.asarray(h,float);taus=np.asarray(taus,float)
    n=len(h);rr=len(taus);pp=pairs(dim);k=len(co);total=n*dim
    if co.shape[1]!=1+dim+rr*(dim+len(pp)):raise ValueError('readout shape')
    c=co[:,0].copy();b=np.zeros((k,n,dim));b[:,-1]=co[:,1:1+dim]
    Q=np.zeros((k,total,total));cm=co[:,1+dim:1+dim+rr*dim].reshape(k,rr,dim);cr=co[:,1+dim+rr*dim:].reshape(k,rr,len(pp))
    after=np.r_[np.cumsum(h[::-1])[::-1][1:],0.]
    for s,tau in enumerate(taus):
        w=-np.expm1(-h/tau)*np.exp(-after/tau);b+=w[None,:,None]*cm[:,s,None,:]
        wt=np.triu(np.outer(w,w),1)
        for cls in range(k):
            antisym=np.zeros((dim,dim))
            for j,(aa,bb) in enumerate(pp):antisym[aa,bb]=cr[cls,s,j];antisym[bb,aa]=-cr[cls,s,j]
            q=np.kron(wt,antisym);Q[cls]+=q+q.T
    return c,b.reshape(k,total),Q

def evaluate_polynomial(c,b,Q,x):
    x=np.asarray(x,float)
    return np.asarray(c)+x@np.asarray(b).T+.5*np.einsum('...i,kij,...j->...k',x,Q,x,optimize=True)

class CoefficientAudit:
    """Exact substitution of queried coordinates; triangle-inequality enclosure."""
    def __init__(self,c,b,Q,lower,upper):
        lo=np.asarray(lower,float).ravel();hi=np.asarray(upper,float).ravel();b=np.atleast_2d(b);Q=np.asarray(Q,float)
        if lo.shape!=hi.shape or not np.isfinite([lo,hi]).all() or np.any(lo>hi):raise ValueError('empty or invalid box')
        if Q.shape!=(len(b),len(lo),len(lo)) or np.any(np.diagonal(Q,axis1=1,axis2=2)!=0) or not np.allclose(Q,Q.transpose(0,2,1),atol=1e-14):raise ValueError('requires symmetric zero-diagonal quadratic')
        self.lower=lo.copy();self.upper=hi.copy();self.ids=np.flatnonzero(hi>lo);self.readings={}
        mid=(hi+lo)/2;rad=(hi-lo)/2;idx=self.ids
        self.c=evaluate_polynomial(c,b,Q,mid)
        self.l=(b+np.einsum('kij,j->ki',Q,mid))[:,idx]*rad[idx]
        self.Q=Q[:,idx][:,:,idx]*rad[idx,None]*rad[None,idx]
    def bounds(self):
        rad=np.abs(self.l).sum(axis=1)+.5*np.abs(self.Q).sum(axis=(1,2))
        return np.stack([self.c-rad,self.c+rad],axis=-1)
    def scores(self):
        """Worst post-query enclosure width, maximized over the supplied outputs."""
        row=np.abs(self.Q).sum(axis=1);quad=.5*row.sum(axis=1)
        plus=np.abs(self.l[:,:,None]+self.Q).sum(axis=1)-np.abs(self.l)
        minus=np.abs(self.l[:,:,None]-self.Q).sum(axis=1)-np.abs(self.l)
        return 2*np.maximum(0,np.max(np.maximum(plus,minus)+quad[:,None]-row,axis=0))
    def choose(self,policy='coefficient',rng=None):
        if len(self.ids)==0:return None
        if policy=='coefficient':return int(self.ids[np.argmin(self.scores())])
        if policy=='recent':return int(self.ids[-1])
        if policy=='random':return int(rng.choice(self.ids))
        raise ValueError('unknown policy')
    def acquire(self,coordinate,value):
        coordinate=int(coordinate);value=float(value)
        if coordinate in self.readings:
            if self.readings[coordinate]!=value:raise ValueError('conflicting observation')
            return False
        found=np.flatnonzero(self.ids==coordinate)
        if len(found)!=1:raise ValueError('not a missing field')
        lo=self.lower[coordinate];hi=self.upper[coordinate]
        if not lo<=value<=hi or not np.isfinite(value):raise ValueError('out-of-bounds observation')
        j=int(found[0]);z=(2*value-lo-hi)/(hi-lo);keep=np.arange(len(self.ids))!=j
        self.c+=self.l[:,j]*z;self.l=(self.l+self.Q[:,:,j]*z)[:,keep];self.Q=self.Q[:,keep][:,:,keep];self.ids=self.ids[keep]
        self.lower[coordinate]=self.upper[coordinate]=value;self.readings[coordinate]=value
        return True

def class_pairs(c,b,Q):
    pp=pairs(len(c))
    return (np.array([c[a]-c[z] for a,z in pp]),np.array([b[a]-b[z] for a,z in pp]),np.array([Q[a]-Q[z] for a,z in pp]))

def class_verdict(bounds,n_classes,margin=1e-10):
    wins=np.zeros((n_classes,n_classes),bool);np.fill_diagonal(wins,True)
    for (a,b),(lo,hi) in zip(pairs(n_classes),bounds):
        if lo>margin:wins[a,b]=True
        if hi < -margin:wins[b,a]=True
    winning=np.flatnonzero(wins.all(axis=1))
    return int(winning[0]) if len(winning)==1 else -1
