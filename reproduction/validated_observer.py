"""Independent Arb evaluation of the real recurrence at dyadic input points.

Uses original class coefficients (no rounded pair subtraction) and row-mean
trace recurrence. All stored binary64 parameters are interpreted as exact
dyadic reals. This validates point winners, not a box or physical calibration.
"""
from flint import arb,ctx
import numpy as np

class ValidatedObserver:
    def __init__(self,graph,coefficients,precision=100):
        if graph.mode!='trace_only':raise ValueError('frozen observer required')
        ctx.prec=precision;self.precision=precision
        self.parents=graph.parents.tolist();self.n=graph.config.n
        self.degree=graph.config.degree;self.m=graph.config.input_dim
        self.alpha=[arb(float(v)) for v in graph.alpha]
        self.beta=[arb(float(v)) for v in graph.beta[:,0,0]]
        self.base=[[arb(float(v)) for v in row] for row in graph.base]
        self.U=[[arb(float(v)) for v in row] for row in graph.U]
        self.bias=[arb(float(v)) for v in graph.bias]
        self.co=[[arb(float(v)) for v in row] for row in coefficients]
        assert all(len(row)==1+self.m+self.n*(1+len(self.beta)) for row in self.co)

    def scores(self,inputs):
        u=np.asarray(inputs,float)
        if u.ndim!=2 or u.shape[1]!=self.m or not np.isfinite(u).all():raise ValueError('input')
        if np.any(abs(u)>1):raise ValueError('normalized input contract')
        ctx.prec=self.precision;x=[arb(0) for _ in range(self.n)]
        c=[[arb(0) for _ in range(self.n)] for _ in self.beta]
        for event in u:
            v=[arb(float(a)) for a in event]
            prod=[x[i]*sum((x[j] for j in self.parents[i]),arb(0))/self.degree for i in range(self.n)]
            c=[[(1-b)*row[i]+b*prod[i] for i in range(self.n)] for row,b in zip(c,self.beta)]
            d=[self.bias[i]+sum((w*x[j] for w,j in zip(self.base[i],self.parents[i])),arb(0))+sum((w*a for w,a in zip(self.U[i],v)),arb(0)) for i in range(self.n)]
            x=[(1-a)*xx+a*dd.tanh() for a,xx,dd in zip(self.alpha,x,d)]
        f=[arb(1)]+v+x+[a for row in c for a in row]
        return [sum((a*b for a,b in zip(row,f)),arb(0)) for row in self.co]

    def evaluate(self,inputs):
        scores=self.scores(inputs)
        winners=[i for i,a in enumerate(scores) if all(i==j or a-b>0 for j,b in enumerate(scores))]
        # Exact integer/exponent pairs serialize outward score endpoints.
        bounds=[[[str(int(z)) for z in a.lower().man_exp()],[str(int(z)) for z in a.upper().man_exp()]] for a in scores]
        return dict(winner=winners[0] if len(winners)==1 else -1,bounds=bounds)
