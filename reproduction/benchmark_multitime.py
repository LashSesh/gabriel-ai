"""Exploratory mechanism tests, ten fresh seeds, including duration shift.

Not a comparison against trained CDE/SSM models. Targets deliberately diagnose
event-index storage, elapsed-time filtering, and ordered bilinear memory.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import json,argparse
from pathlib import Path
import numpy as np
from scipy.linalg import cho_factor,cho_solve
from gabriel import Gabriel
from multitime import OrderedMemory
from memory_extension import quadratic_delay
from run_experiments import TRAIN,VALID,TEST,RIDGES,savecsv,OUT

TASKS=['event_delay6','physical_fast','physical_slow','ordered_history']
TAUS=(.5,2.,8.,32.)

def stream(seed,shift=False):
    rng=np.random.default_rng((60000 if shift else 50000)+seed)
    n=3000 if shift else 6000
    u=rng.uniform(-1,1,(n,2));h=np.exp(rng.uniform(np.log(.03 if shift else .1),np.log(.3 if shift else 2.),n))
    target=np.zeros((n,4));state=np.zeros(4)
    # Independent scalar target equations; target taus are NOT any feature tau.
    for i,(v,dt) in enumerate(zip(u,h)):
        state[0]=np.exp(-dt/1.3)*state[0]-np.expm1(-dt/1.3)*v[0]
        state[1]=np.exp(-dt/13.)*state[1]-np.expm1(-dt/13.)*v[1]
        target[i,0]=u[i-6,0] if i>=6 else 0.
        target[i,1:3]=state[:2]
    a=np.zeros(2);r=0.
    for i,(v,dt) in enumerate(zip(u,h)):
        e=np.exp(-dt/5.);r=e*e*r+e*(-np.expm1(-dt/5.))*(a[0]*v[1]-a[1]*v[0])
        a=e*a-np.expm1(-dt/5.)*v;target[i,3]=r
    return u,h,target

def features(u,h,seed):
    mem=OrderedMemory(TAUS);obs=Gabriel(seed,mode='trace_only');aa=[];rr=[];ss=[];tr=[]
    for v,dt in zip(u,h):
        mem.advance(v,dt);obs.step(v)
        aa.append(mem.a.ravel().copy());rr.append(mem.r.copy());ss.append(mem.symmetric.copy())
        tr.append(obs.c.mean(axis=2).ravel())
    a=np.array(aa);r=np.array(rr);sym=np.array(ss);logh=np.log(h)[:,None]
    event=np.c_[quadratic_delay(u),np.array(tr),logh]
    ij=np.triu_indices(a.shape[1]);base=np.c_[u,logh,a]
    return dict(event_hybrid=event,elapsed_symmetric=np.c_[base,sym],
                elapsed_ordered=np.c_[base,r],elapsed_quadratic=np.c_[base,a[:,ij[0]]*a[:,ij[1]]],
                combined=np.c_[event,a,r])

def fit(f,y):
    mu=f[TRAIN].mean(0);sd=f[TRAIN].std(0);sd[sd<1e-10]=1.
    z=np.c_[np.ones(len(f)),(f-mu)/sd];ym=y[TRAIN].mean(0)
    gram=z[TRAIN].T@z[TRAIN];rhs=z[TRAIN].T@(y[TRAIN]-ym)
    penalty=np.eye(z.shape[1]);penalty[0,0]=0
    ws=[];ve=[]
    for lam in RIDGES:
        w=cho_solve(cho_factor(gram+lam*penalty,lower=True),rhs)
        ws.append(w);ve.append(np.mean((z[VALID]@w+ym-y[VALID])**2,axis=0))
    idx=np.argmin(ve,axis=0);w=np.column_stack([ws[idx[j]][:,j] for j in range(y.shape[1])])
    return z@w+ym,mu,sd,w,ym,RIDGES[idx]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cohort',choices=['discovery','routing'],default='discovery')
    args=parser.parse_args();routing=args.cohort=='routing'
    prefix='multitime_routing' if routing else 'multitime'
    seeds=range(60,70) if routing else range(40,50)
    rows=[]
    selections=[]
    for seed in seeds:
        u,h,y=stream(seed);us,hs,ys=stream(seed,True)
        f=features(u,h,seed);fs=features(us,hs,seed)
        payload=dict(u=u,durations=h,targets=y,shift_u=us,shift_durations=hs,shift_targets=ys)
        vp=[];ps=[];sps=[];ridges=[]
        for name,x in f.items():
            pred,mu,sd,w,ym,lam=fit(x,y);sp=np.c_[np.ones(len(us)),(fs[name]-mu)/sd]@w+ym
            vp.append(np.mean((pred[VALID]-y[VALID])**2,axis=0));ps.append(pred);sps.append(sp);ridges.append(lam)
            payload.update({name+'_predictions':pred,name+'_shift_predictions':sp,name+'_readout':w,
                name+'_feature_mean':mu,name+'_feature_scale':sd,name+'_target_mean':ym})
            for regime,truth,p,idx in [('same_duration',y,pred,TEST),('shorter_duration',ys,sp,np.arange(400,len(us)))]:
                errors=np.mean((p[idx]-truth[idx])**2,axis=0)/np.var(truth[idx],axis=0)
                for j,task in enumerate(TASKS):rows.append(dict(seed=seed,regime=regime,model=name,task=task,nmse=float(errors[j]),ridge=float(lam[j]),features=x.shape[1]+1))
        if routing:
            choice=np.argmin(vp,axis=0);names=list(f)
            pred=np.column_stack([ps[choice[j]][:,j] for j in range(4)])
            sp=np.column_stack([sps[choice[j]][:,j] for j in range(4)])
            payload['routed_predictions']=pred;payload['routed_shift_predictions']=sp
            payload['routed_model_indices']=choice;payload['routing_validation_errors']=np.array(vp)
            for j,task in enumerate(TASKS):selections.append(dict(seed=seed,task=task,selected_model=names[choice[j]]))
            for regime,truth,p,idx in [('same_duration',y,pred,TEST),('shorter_duration',ys,sp,np.arange(400,len(us)))]:
                errors=np.mean((p[idx]-truth[idx])**2,axis=0)/np.var(truth[idx],axis=0)
                for j,task in enumerate(TASKS):rows.append(dict(seed=seed,regime=regime,model='routed',task=task,nmse=float(errors[j]),ridge=float(ridges[choice[j]][j]),features=f[names[choice[j]]].shape[1]+1))
        np.savez_compressed(OUT/f'multitime_seed_{seed}.npz',**payload)
        print('multitime seed',seed,'complete',flush=True)
    savecsv(prefix+'_benchmark.csv',rows)
    if routing:savecsv('multitime_routing_selections.csv',selections)
    summary=[]
    for regime in ['same_duration','shorter_duration']:
        for name in list(f)+(['routed'] if routing else []):
            for task in TASKS:
                v=np.array([r['nmse'] for r in rows if r['regime']==regime and r['model']==name and r['task']==task])
                summary.append(dict(regime=regime,model=name,task=task,mean=float(v.mean()),sd=float(v.std(ddof=1)),min=float(v.min()),max=float(v.max())))
    savecsv(prefix+'_summary.csv',summary)
    (OUT/(prefix+'_protocol.json')).write_text(json.dumps(dict(seeds=list(seeds),cohort=args.cohort,routing='per-target argmin validation MSE among five fixed models' if routing else 'none',input_seed_offset=50000,shift_seed_offset=60000,
        feature_taus=TAUS,target_taus=[1.3,13.,5.],duration_distribution='loguniform',train_durations=[.1,2.],shift_durations=[.03,.3],
        shift_samples=3000,shift_washout=400,initial_state='zero, independently per regime',training='original training split only; no refit or retuning on duration shift',
        features={k:x.shape[1]+1 for k,x in f.items()},tasks=TASKS),indent=2))
    for r in summary: print(r)

if __name__=='__main__':main()
