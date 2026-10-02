"""Run the complete synthetic study; no downloads and no unpublished input data."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import csv, json, time, platform
from pathlib import Path
import numpy as np
import scipy
from scipy.linalg import cho_factor, cho_solve
from gabriel import Gabriel,Config,soft_threshold

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results'; OUT.mkdir(exist_ok=True)
SEEDS=list(range(10))
T=6000
TRAIN=np.arange(400,3000)
VALID=np.arange(3100,4000)
TEST=np.arange(4100,6000)
RIDGES=np.array([1e-6,1e-4,1e-2,1.,100.])
TASKS=['delay6','lag_product','smoothed_covariance']

def savecsv(name,rows):
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def data(seed):
    rng=np.random.default_rng(10000+seed)
    u=rng.uniform(-1,1,(T,2)); y=np.zeros((T,3)); cov=0.
    for t in range(T):
        y[t,0]=u[t-6,0] if t>=6 else 0.
        y[t,1]=u[t-2,0]*u[t-5,1] if t>=5 else 0.
        cov=.96*cov+.04*(u[t-1,0]*u[t-1,1] if t else 0.)
        y[t,2]=cov
    return u,y

def evaluate(features,y):
    mean=features[TRAIN].mean(0); scale=features[TRAIN].std(0)
    scale[scale<1e-10]=1.
    z=(features-mean)/scale
    z=np.column_stack([np.ones(len(z)),z])
    ym=y[TRAIN].mean(0); yc=y-ym
    xt=z[TRAIN]; gram=xt.T@xt; rhs=xt.T@yc[TRAIN]
    penalty=np.eye(z.shape[1]);penalty[0,0]=0.
    candidates=[]; valerrors=[]
    for lam in RIDGES:
        w=cho_solve(cho_factor(gram+lam*penalty,lower=True),rhs)
        candidates.append(w)
        valerrors.append(np.mean((z[VALID]@w-yc[VALID])**2,axis=0))
    chosen=np.argmin(valerrors,axis=0)
    w=np.column_stack([candidates[chosen[j]][:,j] for j in range(3)])
    pred=z@w+ym
    err=np.mean((pred[TEST]-y[TEST])**2,axis=0)/np.var(y[TEST],axis=0)
    return err,RIDGES[chosen],pred,mean,scale,w,ym

def benchmark():
    rows=[]; diagnostics=[]
    for seed in SEEDS:
        u,y=data(seed)
        models={key:Gabriel(seed,mode=mode) for key,mode in [('fixed','fixed'),('budget','budget'),('trace_only','trace_only'),('adaptive','adaptive')]}
        feats={key:[] for key in ['input','fir12','fixed','budget','trace_only','adaptive_x','adaptive_joint']}
        active=[]; total_active=[]; churn=[]; oldsupport=None; wrows=[]
        for t,ut in enumerate(u):
            feats['input'].append(ut.copy())
            feats['fir12'].append(np.concatenate([u[max(0,t-j)] if t>=j else np.zeros(2) for j in range(13)]))
            for name,m in models.items():
                m.step(ut)
                if name=='adaptive':
                    feats['adaptive_x'].append(m.features(ut))
                    feats['adaptive_joint'].append(m.features(ut,True))
                    support=np.abs(m.c)>m.lam
                    active.append(support.mean())
                    total_active.append(np.mean(np.abs(m.weights())>0))
                    churn.append(0. if oldsupport is None else np.mean(support!=oldsupport))
                    oldsupport=support.copy()
                    wrows.append(np.abs(m.weights()).sum(axis=1).max())
                else:
                    feats[name].append(m.features(ut,joint=(name=='trace_only')))
        payload={'u':u,'targets':y}
        for name,raw in feats.items():
            f=np.array(raw)
            err,lam,pred,mean,scale,w,ym=evaluate(f,y)
            for j,task in enumerate(TASKS):
                rows.append(dict(seed=seed,model=name,task=task,nmse=float(err[j]),ridge=float(lam[j]),features=f.shape[1]+1))
            payload[name+'_predictions']=pred
            payload[name+'_readout']=w
            payload[name+'_feature_mean']=mean
            payload[name+'_feature_scale']=scale
            payload[name+'_target_mean']=ym
        payload['adaptive_activity']=models['adaptive'].x
        payload['adaptive_traces']=models['adaptive'].c
        payload['parents']=models['adaptive'].parents
        payload['backbone']=models['adaptive'].base
        payload['input_matrix']=models['adaptive'].U
        payload['bias']=models['adaptive'].bias
        payload['active_fraction']=np.array(active)
        payload['support_churn']=np.array(churn)
        payload['total_active_fraction']=np.array(total_active)
        np.savez_compressed(OUT/f'benchmark_seed_{seed:02d}.npz',**payload)
        diagnostics.append(dict(seed=seed,active_fraction=float(np.mean(np.array(active)[TEST])),total_active_fraction=float(np.mean(np.array(total_active)[TEST])),churn=float(np.mean(np.array(churn)[TEST])),max_weight_row=float(max(wrows))))
        print('benchmark seed',seed,'done',flush=True)
    savecsv('benchmark.csv',rows);savecsv('graph_diagnostics.csv',diagnostics)
    summary=[]
    for name in feats:
        for task in TASKS:
            x=np.array([r['nmse'] for r in rows if r['model']==name and r['task']==task])
            summary.append(dict(model=name,task=task,mean=float(x.mean()),sd=float(x.std(ddof=1)),min=float(x.min()),max=float(x.max())))
    savecsv('summary.csv',summary)
    paired=[]
    for other in ['trace_only','fixed','budget','adaptive_x']:
        for task in TASKS:
            a=np.array([r['nmse'] for r in rows if r['model']=='adaptive_joint' and r['task']==task])
            b=np.array([r['nmse'] for r in rows if r['model']==other and r['task']==task])
            delta=a-b
            paired.append(dict(comparison='adaptive_joint minus '+other,task=task,mean_delta=float(delta.mean()),sd_delta=float(delta.std(ddof=1)),wins=int(np.sum(delta<0)),seeds=len(SEEDS)))
    savecsv('paired.csv',paired)
    return summary

def verification():
    rng=np.random.default_rng(8801); m=Gabriel(81); cert=m.certificate();r=cert['trace_scale'];k=cert['kappa']
    assert cert['valid'] and k<1
    maxratio=0.;worst_bound_excess=-float('inf');invariance=0.
    for trial in range(2000):
        a=Gabriel(81);b=Gabriel(81)
        a.x=rng.uniform(-1,1,a.x.shape);b.x=rng.uniform(-1,1,b.x.shape)
        a.c=rng.uniform(-1,1,a.c.shape);b.c=rng.uniform(-1,1,b.c.shape)
        old=a.distance(b,r);u=rng.uniform(-3,3,2)
        a.step(u);b.step(u);new=a.distance(b,r)
        maxratio=max(maxratio,new/old)
        worst_bound_excess=max(worst_bound_excess,new-k*old)
        invariance=max(invariance,float(np.max(np.abs(a.x))),float(np.max(np.abs(a.c))))
    assert worst_bound_excess<=1e-12 and invariance<=1+1e-12
    # Same drive, large activity and trace displacement; support certificates at every time.
    a=Gabriel(81); b=Gabriel(81)
    a.x=rng.uniform(-1,1,a.x.shape);a.c=rng.uniform(-1,1,a.c.shape)
    b.x=rng.uniform(-1,1,b.x.shape);b.c=rng.uniform(-1,1,b.c.shape)
    d0=a.distance(b,r);history=[];falsecerts=0
    for t in range(1601):
        bound=(k**t)*d0;eps=r*bound
        margin=np.abs(np.abs(a.c)-a.lam)
        certified=margin>eps
        mismatch=(np.abs(a.c)>a.lam)!=(np.abs(b.c)>b.lam)
        falsecerts+=int(np.sum(certified&mismatch))
        history.append(dict(t=t,distance=a.distance(b,r),bound=bound,support_disagreement=float(mismatch.mean()),certified_fraction=float(certified.mean())))
        drive=rng.uniform(-1,1,2);a.step(drive);b.step(drive)
    assert falsecerts==0
    savecsv('synchronization.csv',history)
    # Roundoff stress; empirical discrepancy only, no interval arithmetic certification.
    a=Gabriel(82);b=Gabriel(82)
    for name in ['base','U','bias','alpha','beta','lam','gains','x','c']:
        setattr(b,name,getattr(b,name).astype(np.float32))
    precision=0.
    for t in range(3000):
        u=rng.uniform(-1,1,2);a.step(u);b.step(u.astype(np.float32))
        # step casts inputs to float64 intentionally: compare full storage rounding instead.
        b.x=b.x.astype(np.float32);b.c=b.c.astype(np.float32)
        precision=max(precision,a.distance(b,r))
    # Constructive discontinuity of hard top-1 selection at a tie.
    e=1e-8
    hard_jump=1. # selecting different coordinate changes max-norm output by approx one
    sa=np.array([1+e,1.]);sb=np.array([1.,1+e])
    ha=np.zeros(2);hb=np.zeros(2);ha[np.argmax(sa)]=sa.max();hb[np.argmax(sb)]=sb.max()
    topk_ratio=float(np.max(np.abs(ha-hb))/np.max(np.abs(sa-sb)))
    # Perturbation recovery experiment: reset half the cells and their incoming traces once.
    a=Gabriel(90);b=Gabriel(90)
    for _ in range(300):
        u=rng.uniform(-1,1,2);a.step(u);b.step(u)
    b.x[:24]=0.;b.c[:,:24,:]=0.;damage0=a.distance(b,r)
    damage=[]
    for t in range(801):
        damage.append(dict(t=t,distance=a.distance(b,r),bound=k**t*damage0))
        u=rng.uniform(-1,1,2);a.step(u);b.step(u)
    savecsv('recovery.csv',damage)
    assert all(row['distance']<=row['bound']+1e-12 for row in damage)
    # Threshold edges, nonexpansiveness, and locality/order reference cases.
    z=np.array([-.5,-.08,0,.08,.5]); soft=soft_threshold(z,.08)
    assert np.allclose(soft,[-.42,0,0,0,.42])
    x=rng.normal(size=1000);y=rng.normal(size=1000)
    assert np.all(np.abs(soft_threshold(x,.08)-soft_threshold(y,.08))<=np.abs(x-y)+1e-14)
    a=Gabriel(4);a.step(np.ones(2));assert np.all(a.c==0.) # old-state update
    tests=dict(certificate=cert,random_pair_trials=2000,max_observed_ratio=maxratio,max_bound_excess=worst_bound_excess,max_absolute_state=invariance,false_support_certificates=falsecerts,precision='mixed arithmetic with float32 state/storage rounding',max_rounded_storage_discrepancy=precision,hard_top1_amplification=topk_ratio,damage_initial_distance=damage0,damage_final_distance=damage[-1]['distance'],synchronization_final_distance=history[-1]['distance'],tolerance=1e-12)
    (OUT/'verification.json').write_text(json.dumps(tests,indent=2)+'\n')
    return tests

def main():
    start=time.time()
    tests=verification();summary=benchmark()
    meta=dict(config=Config().__dict__,seeds=SEEDS,input_seed_rule='10000 + model seed',verification_seed=8801,n_steps=T,train=[400,3000],validation=[3100,4000],test=[4100,6000],indexing='zero-based, half-open',ridge_grid=RIDGES.tolist(),python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,elapsed_seconds=time.time()-start)
    (OUT/'environment.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(tests,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
