"""Continuous-state checkpoints and exact integer vote certificates.

The acquisition rule only consumes a vote when all its input dependencies are
known. Dependence between unread votes does not invalidate the certificate.
"""
import numpy as np
from gabriel import Gabriel, Config
from benchmark_external import feature_map, fit_ridge

MODELS = ['full_observer','reset_blocks','shared_prefix','stage_prefix','stage_mean']

def checkpoints(N):
    if N < 5: raise ValueError('five nonempty stages required')
    return np.arange(1,6)*N//5

def representations(x):
    n,N,m=x.shape; cuts=checkpoints(N)
    g=Gabriel(0,Config(input_dim=m),mode='trace_only')
    prefix=np.empty((n,5,1+m+3*g.config.n))
    for i,seq in enumerate(x):
        g.reset(); b=0
        for t,u in enumerate(seq,1):
            g.step(u)
            if t==cuts[b]:
                prefix[i,b]=np.r_[1,g.features(u,joint=True)];b+=1
                if b==5:break
    blocks=np.stack([feature_map(x[:,a:b],None,None,'trace_observer')
                     for a,b in zip(np.r_[0,cuts[:-1]],cuts)],axis=1)
    means=np.stack([np.c_[np.ones(n),x[:,:t].mean(1)] for t in cuts],axis=1)
    return dict(full_observer=prefix[:,-1:],reset_blocks=blocks,
                shared_prefix=prefix,stage_prefix=prefix,stage_mean=means)

def fit_heads(f,y,K,penalty,model):
    if model in ['stage_prefix','stage_mean']:
        return np.stack([fit_ridge(f[:,b],y,K,penalty) for b in range(f.shape[1])])
    co=fit_ridge(f.reshape(-1,f.shape[-1]),np.repeat(y,f.shape[1]),K,penalty)
    return np.broadcast_to(co,(f.shape[1],)+co.shape).copy()

def predict(f,co):
    scores=np.einsum('nbd,bdk->nbk',f,co)
    votes=scores.argmax(-1)
    count=np.eye(scores.shape[-1],dtype=int)[votes].sum(1)
    return count.argmax(-1),votes,scores

def forced_winner(count,remaining,tie_aware=True):
    """Exact for arbitrary unread votes, sufficient for dependent real votes."""
    a=int(np.argmax(count))
    for k in range(len(count)):
        if k==a:continue
        gap=int(count[a])-int(count[k])-int(remaining)
        if gap<0 or (gap==0 and (not tie_aware or k<a)):return -1
    return a

def acquire(votes,mask,cuts,m,K,model,tie_aware=True):
    """mask=True means initially missing. Return exact acquired scalar IDs."""
    missing=mask.copy();start=np.r_[0,cuts[:-1]]
    deps=[np.arange((start[b] if model=='reset_blocks' else 0)*m,t*m)
          for b,t in enumerate(cuts)]
    seen=np.array([not missing[idx].any() for idx in deps]);path=[]
    for b in list(range(len(cuts)))+[None]:
        count=np.bincount(votes[seen],minlength=K);R=int((~seen).sum())
        winner=forced_winner(count,R,tie_aware)
        if R==0: winner=int(count.argmax())
        if winner>=0:
            return dict(winner=winner,queries=np.array(path,int),seen=seen.copy(),
                        count=count,remaining=R)
        if b is None:raise AssertionError('all inputs must resolve all votes')
        if not seen[b]:
            q=deps[b][missing[deps[b]]];path.extend(q.tolist());missing[q]=False
            seen=np.array([not missing[idx].any() for idx in deps])

