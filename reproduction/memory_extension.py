"""Exploratory memory extension, designed after the core ablations.
Quadratic delay features are a known NVAR/Volterra construction, not a novelty claim.
Fresh seeds 20..29 form the extension evaluation cohort; no retuning on them.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import numpy as np
from gabriel import Gabriel
from run_experiments import data,evaluate,savecsv,OUT,T,TASKS

def quadratic_delay(u,delay=12):
    z=np.zeros((len(u),(delay+1)*u.shape[1]))
    for d in range(delay+1):
        z[d:,d*u.shape[1]:(d+1)*u.shape[1]]=u[:len(u)-d]
    i,j=np.triu_indices(z.shape[1])
    return np.column_stack([z,z[:,i]*z[:,j]])

def main():
    rows=[]
    for seed in range(20,30):
        u,y=data(seed)
        m=Gabriel(seed,mode='adaptive');o=Gabriel(seed,mode='trace_only')
        core=[];observer=[];traces=[]
        for ut in u:
            m.step(ut);o.step(ut)
            core.append(m.features(ut,True));observer.append(o.features(ut,True))
            traces.append(o.c.mean(axis=2).reshape(-1))
        quadratic=quadratic_delay(u)
        features={'adaptive_joint':np.array(core),'trace_only':np.array(observer),'quadratic_delay':quadratic,'hybrid_memory':np.column_stack([quadratic,np.array(traces)])}
        payload={'u':u,'targets':y}
        for name,f in features.items():
            err,lam,pred,mean,scale,w,ym=evaluate(f,y)
            for j,task in enumerate(TASKS):rows.append(dict(seed=seed,model=name,task=task,nmse=float(err[j]),ridge=float(lam[j]),features=f.shape[1]+1))
            payload[name+'_predictions']=pred;payload[name+'_readout']=w
            payload[name+'_feature_mean']=mean;payload[name+'_feature_scale']=scale;payload[name+'_target_mean']=ym
        np.savez_compressed(OUT/f'extension_seed_{seed:02d}.npz',**payload)
        print('extension seed',seed,'done',flush=True)
    savecsv('extension.csv',rows)
    summary=[]
    for model in features:
        for task in TASKS:
            a=np.array([r['nmse'] for r in rows if r['model']==model and r['task']==task])
            summary.append(dict(model=model,task=task,mean=float(a.mean()),sd=float(a.std(ddof=1)),min=float(a.min()),max=float(a.max())))
    savecsv('extension_summary.csv',summary)
    for row in summary:print(row)
if __name__=='__main__':main()
