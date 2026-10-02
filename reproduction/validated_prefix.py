"""One-pass Arb evaluation of dependent checkpoint features.

Parameters and normalized inputs are exact dyadic interpretations of stored
binary64 values. These are point certificates, not uncertainty-box certificates.
"""
import numpy as np
from flint import arb,ctx
from gabriel import Gabriel,Config
from validated_observer import ValidatedObserver

def endpoints(scores):
    winners=[i for i,a in enumerate(scores) if all(i==j or a-b>0 for j,b in enumerate(scores))]
    bounds=[[[str(int(z)) for z in a.lower().man_exp()],
             [str(int(z)) for z in a.upper().man_exp()]] for a in scores]
    return dict(winner=winners[0] if len(winners)==1 else -1,bounds=bounds)

def feature_balls(u,cuts,precision=100,reset_blocks=False):
    u=np.asarray(u,float);m=u.shape[1]
    if not np.isfinite(u).all() or np.any(abs(u)>1):raise ValueError('input contract')
    g=Gabriel(0,Config(input_dim=m),mode='trace_only')
    v=ValidatedObserver(g,np.zeros((1,1+m+3*g.config.n)),precision)
    ctx.prec=precision;n=v.n;x=[arb(0) for _ in range(n)]
    c=[[arb(0) for _ in range(n)] for _ in v.beta]
    total=[arb(0) for _ in range(m)];ans=[];b=0
    for t,event in enumerate(u,1):
        a=[arb(float(z)) for z in event];total=[p+q for p,q in zip(total,a)]
        prod=[x[i]*sum((x[j] for j in v.parents[i]),arb(0))/v.degree for i in range(n)]
        c=[[(1-beta)*row[i]+beta*prod[i] for i in range(n)] for row,beta in zip(c,v.beta)]
        d=[v.bias[i]+sum((w*x[j] for w,j in zip(v.base[i],v.parents[i])),arb(0))
           +sum((w*z for w,z in zip(v.U[i],a)),arb(0)) for i in range(n)]
        x=[(1-alpha)*old+alpha*z.tanh() for alpha,old,z in zip(v.alpha,x,d)]
        if t==cuts[b]:
            ans.append(([arb(1)]+a+x+[z for row in c for z in row],
                        [arb(1)]+[z/t for z in total]));b+=1
            if reset_blocks:
                x=[arb(0) for _ in range(n)];c=[[arb(0) for _ in range(n)] for _ in v.beta]
            if b==len(cuts):break
    return ans

def validate_record(u,cuts,coefficients,precision=100):
    fs=feature_balls(u,cuts,precision);bs=feature_balls(u,cuts,precision,True)
    result={}
    for model,heads in coefficients.items():
        feats=bs if model=='reset_blocks' else fs
        if model=='full_observer':feats=feats[-1:]
        ans=[]
        for head,(f,mean) in zip(heads,feats):
            if model=='stage_mean':f=mean
            scores=[sum((arb(float(a))*b for a,b in zip(row,f)),arb(0)) for row in head.T]
            ans.append(endpoints(scores))
        result[model]=ans
    return result

